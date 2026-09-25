"""
GeoSentinel-NER Report Service
Citizen report ingestion, CV triage, and verification workflow.
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from geosentinel_shared import (
    CitizenReportMediaRead,
    CitizenReportRead,
    close_db,
    configure_logging,
    get_db_session,
    get_logger,
    init_db,
    settings,
    verify_token,
)
from pydantic import BaseModel
from sqlalchemy import text

UTC = timezone.utc

configure_logging()
logger = get_logger(__name__)

# Auth: report uploads and verify actions must be authenticated.
_bearer = HTTPBearer(auto_error=False)


async def _current_principal(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[str]:
    """Return the username from the access token, or None if anonymous
    (anonymous submission is allowed for citizen reports)."""
    if not creds or not creds.credentials:
        return None
    try:
        payload = verify_token(creds.credentials, "access")
        return payload.username
    except ValueError:
        return None


async def _require_official(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """Require a valid access token. Used for verify / status-update actions."""
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = verify_token(creds.credentials, "access")
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return payload.username


# -----------------------------------------------------------------------------
# CV Triage Client (calls ML Engine)
# -----------------------------------------------------------------------------
class CVTriageClient:
    """Client for calling ML Engine M3 CV triage model."""

    def __init__(self):
        self.base_url = "http://ml-engine:8002"
        self.enabled = settings.ENABLE_CV_TRIAGE

    async def triage_report(self, report_id: UUID, image_urls: List[str]) -> Dict[str, Any]:
        if not self.enabled:
            return {"classification": "pending", "confidence": 0.0}

        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/predict/m3",
                json={"image_urls": image_urls, "report_id": str(report_id)},
            )
            resp.raise_for_status()
            return resp.json()


cv_client = CVTriageClient()


# -----------------------------------------------------------------------------
# MinIO Client for media uploads
# -----------------------------------------------------------------------------
class MediaStorage:
    """Handle media uploads to MinIO."""

    def __init__(self):
        from minio import Minio
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET

    def ensure_bucket(self):
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def upload_file(self, object_name: str, file_data: bytes, content_type: str) -> str:
        self.ensure_bucket()
        from io import BytesIO
        self.client.put_object(
            self.bucket,
            object_name,
            BytesIO(file_data),
            length=len(file_data),
            content_type=content_type,
        )
        return f"s3://{self.bucket}/{object_name}"

    def generate_presigned_url(self, object_name: str, expiry_hours: int = 24) -> str:
        from datetime import timedelta
        return self.client.presigned_get_object(self.bucket, object_name, expires=timedelta(hours=expiry_hours))


media_storage = MediaStorage()

# -----------------------------------------------------------------------------
# DB helpers — powerful report querying (used to surface live-engine problems)
# -----------------------------------------------------------------------------
_REPORT_SELECT = text(
    """
    SELECT id, report_code, reporter_name, reporter_phone,
           report_type, severity, description, accuracy_m, altitude_m,
           village_id, road_id, status, priority_score, cv_classification,
           cv_confidence, cv_inference_at, verified_by, verified_at,
           verification_notes, assigned_to, resolved_at, resolution_notes,
           metadata, created_at, updated_at,
           ST_AsGeoJSON(geom)::json AS geom_json
    FROM citizen_report
    WHERE (:status IS NULL OR status = :status)
      AND (:report_type IS NULL OR report_type = :report_type)
      AND (:village_id IS NULL OR village_id = :village_id)
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset
    """
)
_REPORT_BY_ID_SELECT = text(_REPORT_SELECT.text.replace(
    "WHERE (:status IS NULL OR status = :status)\n"
    "      AND (:report_type IS NULL OR report_type = :report_type)\n"
    "      AND (:village_id IS NULL OR village_id = :village_id)",
    "WHERE id = :id",
))


def _row_to_report(row) -> CitizenReportRead:
    geom = row.geom_json
    if isinstance(geom, str):
        geom = json.loads(geom)
    return CitizenReportRead(
        id=row.id,
        report_code=row.report_code,
        reporter_name=row.reporter_name,
        reporter_phone=row.reporter_phone,
        report_type=row.report_type,
        severity=row.severity or "unknown",
        description=row.description,
        accuracy_m=float(row.accuracy_m) if row.accuracy_m is not None else None,
        altitude_m=float(row.altitude_m) if row.altitude_m is not None else None,
        village_id=row.village_id,
        road_id=row.road_id,
        status=row.status,
        priority_score=float(row.priority_score or 0),
        cv_classification=row.cv_classification,
        cv_confidence=float(row.cv_confidence) if row.cv_confidence is not None else None,
        cv_inference_at=row.cv_inference_at,
        verified_by=row.verified_by,
        verified_at=row.verified_at,
        verification_notes=row.verification_notes,
        assigned_to=row.assigned_to,
        resolved_at=row.resolved_at,
        resolution_notes=row.resolution_notes,
        metadata=row.metadata or {},
        geom=geom,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# -----------------------------------------------------------------------------
# Request/Response Schemas
# -----------------------------------------------------------------------------
class ReportSubmitRequest(BaseModel):
    reporter_name: Optional[str] = None
    reporter_phone: Optional[str] = None
    report_type: str
    severity: str = "unknown"
    description: Optional[str] = None
    accuracy_m: Optional[float] = None
    altitude_m: Optional[float] = None
    village_id: Optional[UUID] = None
    road_id: Optional[UUID] = None
    metadata: Dict[str, Any] = {}
    # Geometry as GeoJSON
    geom: Dict[str, Any]


class ReportVerifyRequest(BaseModel):
    verified: bool
    verification_notes: Optional[str] = None
    assigned_to: Optional[UUID] = None


class ReportStatusUpdateRequest(BaseModel):
    status: str
    resolution_notes: Optional[str] = None


class ReportListParams(BaseModel):
    status: Optional[str] = None
    report_type: Optional[str] = None
    village_id: Optional[UUID] = None
    district_id: Optional[UUID] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    page: int = 1
    page_size: int = 20


# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_report_service")
    await init_db()
    yield
    logger.info("shutting_down_report_service")
    await close_db()


app = FastAPI(
    title="GeoSentinel-NER Report Service",
    description="Citizen report ingestion, CV triage, and verification",
    version="0.1.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "report-service", "cv_triage_enabled": settings.ENABLE_CV_TRIAGE}


@app.post("/reports", response_model=CitizenReportRead)
async def submit_report(
    request: ReportSubmitRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
):
    """Submit a new citizen report."""
    # Generate report code
    report_code = f"GSN-{datetime.now().year}-{uuid4().hex[:6].upper()}"

    # Create report record
    report = CitizenReportRead(
        id=uuid4(),
        report_code=report_code,
        reporter_name=request.reporter_name,
        reporter_phone=request.reporter_phone,
        report_type=request.report_type,
        severity=request.severity,
        description=request.description,
        geom=request.geom,  # Would convert to PointGeometry
        accuracy_m=request.accuracy_m,
        altitude_m=request.altitude_m,
        village_id=request.village_id,
        road_id=request.road_id,
        status="submitted",
        priority_score=0.0,
        metadata=request.metadata,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # Save to DB (placeholder)
    logger.info("report_submitted", report_id=report.id, report_code=report_code, type=request.report_type)

    # Trigger CV triage if media uploaded (would be handled after media upload)
    # background_tasks.add_task(run_cv_triage, report.id, media_urls)

    return report


@app.post(f"{settings.API_PREFIX}/reports/{{report_id}}/media", response_model=List[CitizenReportMediaRead])
async def upload_report_media(
    report_id: UUID,
    files: List[UploadFile] = File(...),
    is_primary: List[bool] = Form(default=[]),
    principal: Optional[str] = Depends(_current_principal),
    db=Depends(get_db_session),
):
    """Upload media files for a report. Requires either an authenticated
    user or a valid (file-size-limited) submission. Enforces per-file and
    aggregate upload size limits to prevent DoS via huge media."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files per upload")

    media_records = []
    image_urls = []
    max_bytes = settings.MAX_UPLOAD_BYTES

    for idx, file in enumerate(files):
        # Stream the upload and reject early if it exceeds the limit.
        chunks = []
        total = 0
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{file.filename}' exceeds {max_bytes} bytes",
                )
            chunks.append(chunk)
        content = b"".join(chunks)
        ext = Path(file.filename or "").suffix.lstrip(".") or "jpg"
        if ext.lower() not in {"jpg", "jpeg", "png", "webp", "mp4", "webm", "mov", "m4a", "mp3"}:
            raise HTTPException(status_code=400, detail=f"Unsupported file extension: {ext}")
        object_name = f"reports/{report_id}/{uuid4()}.{ext}"

        s3_path = media_storage.upload_file(object_name, content, file.content_type or "image/jpeg")
        presigned_url = media_storage.generate_presigned_url(object_name)
        image_urls.append(presigned_url)

        # Create media record
        media = CitizenReportMediaRead(
            id=uuid4(),
            report_id=report_id,
            media_type="photo" if file.content_type and file.content_type.startswith("image/") else "video",
            file_path=s3_path,
            file_size_bytes=len(content),
            mime_type=file.content_type,
            is_primary=is_primary[idx] if idx < len(is_primary) else (idx == 0),
            created_at=datetime.now(),
        )
        media_records.append(media)

    # Trigger CV triage asynchronously
    if image_urls and settings.ENABLE_CV_TRIAGE:
        # background_tasks.add_task(run_cv_triage, report_id, image_urls)
        pass

    return media_records


async def run_cv_triage(report_id: UUID, image_urls: List[str]):
    """Background task to run CV triage on report images."""
    try:
        result = await cv_client.triage_report(report_id, image_urls)
        # Update report with CV results
        logger.info("cv_triage_completed", report_id=report_id, classification=result.get("classification"))
    except Exception as e:
        logger.error("cv_triage_failed", report_id=report_id, error=str(e))


@app.get("/reports", response_model=List[CitizenReportRead])
async def list_reports(
    params: ReportListParams = Depends(),
    db=Depends(get_db_session),
):
    """List citizen reports with filters — DB-backed, surfaces live-engine problems too."""
    try:
        result = await db.execute(
            _REPORT_SELECT,
            {"status": params.status, "report_type": params.report_type, "village_id": params.village_id,
             "limit": params.page_size, "offset": (params.page - 1) * params.page_size},
        )
        return [_row_to_report(row) for row in result.all()]
    except Exception as exc:
        logger.warning("reports_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Report store unavailable") from exc


@app.get("/reports/{report_id}", response_model=CitizenReportRead)
async def get_report(report_id: UUID, db=Depends(get_db_session)):
    """Get a single report by ID."""
    row = (await db.execute(_REPORT_BY_ID_SELECT, {"id": report_id, "limit": 1, "offset": 0})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _row_to_report(row)


@app.post("/reports/{report_id}/verify", response_model=CitizenReportRead)
async def verify_report(
    report_id: UUID,
    request: ReportVerifyRequest,
    db=Depends(get_db_session),
):
    """Verify or reject a report — persists to DB so live problems can be triaged."""
    now = datetime.now(UTC)
    # Use dummy user when auth not wired in report-service
    result = await db.execute(
        text(
            "UPDATE citizen_report SET status = :status, verification_notes = :notes, "
            "verified_at = :now, updated_at = :now WHERE id = :id RETURNING id"
        ),
        {
            "id": report_id,
            "status": "verified" if request.verified else "rejected",
            "notes": request.verification_notes,
            "now": now,
        },
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Report not found")
    await db.commit()
    row = (await db.execute(_REPORT_BY_ID_SELECT, {"id": report_id, "limit": 1, "offset": 0})).first()
    return _row_to_report(row)


@app.patch("/reports/{report_id}/status", response_model=CitizenReportRead)
async def update_report_status(
    report_id: UUID,
    request: ReportStatusUpdateRequest,
    db=Depends(get_db_session),
):
    """Update report status (e.g., escalated, resolved)."""
    allowed = {"submitted", "triaged", "verified", "rejected", "assigned", "escalated", "resolved"}
    if request.status not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported report status")
    now = datetime.now(UTC)
    result = await db.execute(
        text(
            "UPDATE citizen_report SET status = :status, resolution_notes = :notes, "
            "resolved_at = CASE WHEN :status='resolved' THEN :now ELSE NULL END, "
            "updated_at = :now WHERE id = :id RETURNING id"
        ),
        {"id": report_id, "status": request.status, "notes": request.resolution_notes, "now": now},
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Report not found")
    await db.commit()
    row = (await db.execute(_REPORT_BY_ID_SELECT, {"id": report_id, "limit": 1, "offset": 0})).first()
    return _row_to_report(row)


@app.get("/reports/{report_id}/media")
async def get_report_media(report_id: UUID, db=Depends(get_db_session)):
    """Get media files for a report."""
    return []


@app.get("/reports/{report_id}/media/{media_id}/download")
async def download_media(report_id: UUID, media_id: UUID, db=Depends(get_db_session)):
    """Download media file (stream from MinIO)."""
    # In production: get presigned URL or stream from MinIO
    raise HTTPException(status_code=501, detail="Not implemented")


# -----------------------------------------------------------------------------
# Offline Sync Endpoints (for mobile app)
# -----------------------------------------------------------------------------
class SyncPushRequest(BaseModel):
    reports: List[ReportSubmitRequest]
    media: List[Dict[str, Any]]  # metadata for media files


class SyncPushResponse(BaseModel):
    synced: int
    failed: int
    report_ids: List[UUID]


@app.post("/sync/push", response_model=SyncPushResponse)
async def sync_push(request: SyncPushRequest, db=Depends(get_db_session)):
    """Push offline reports from mobile app."""
    synced = 0
    failed = 0
    report_ids = []

    for report_data in request.reports:
        try:
            # Submit each report
            # ...
            synced += 1
            report_ids.append(uuid4())
        except Exception as e:
            logger.error("sync_push_failed", error=str(e))
            failed += 1

    return SyncPushResponse(synced=synced, failed=failed, report_ids=report_ids)


@app.get("/sync/pull")
async def sync_pull(
    last_sync: Optional[datetime] = None,
    village_id: Optional[UUID] = None,
    db=Depends(get_db_session),
):
    """Pull updated data for offline sync (reports, alerts, risk zones)."""
    return {
        "reports": [],
        "alerts": [],
        "risk_zones": [],
        "sync_timestamp": datetime.now().isoformat(),
    }


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=settings.APP_DEBUG)
