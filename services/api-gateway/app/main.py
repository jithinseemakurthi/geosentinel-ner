"""
GeoSentinel-NER API Gateway
Main FastAPI application with authentication, routing, and middleware.
"""
import asyncio
import contextlib
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from geosentinel_shared import (
    AdminStateRead,
    AlertRead,
    AppUserCreate,
    AppUserRead,
    AppUserUpdate,
    CitizenReportCreate,
    CitizenReportMediaRead,
    CitizenReportRead,
    HealthCheck,
    InfrastructureFacilityRead,
    InfrastructureRoadRead,
    LandslideInventoryRead,
    PageParams,
    PaginatedResponse,
    RiskForecastRead,
    SensorReadingRead,
    SensorStationRead,
    SusceptibilityZoneRead,
    Token,
    check_permission,
    close_db,
    configure_logging,
    create_access_token,
    create_refresh_token,
    get_db_session,
    get_logger,
    get_primary_db,
    get_ts_session,
    hash_password,
    init_db,
    settings,
    verify_password,
    verify_token,
)
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

configure_logging()
logger = get_logger(__name__)

security = HTTPBearer(auto_error=False)

# -----------------------------------------------------------------------------
# In-process rate limiter (token bucket keyed by client IP + route).
# Good enough for a single instance; in a multi-instance deployment use Redis.
# -----------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._buckets: dict[str, tuple[float, float]] = {}
        self._max_buckets = 10_000

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._prune(now)
        refill = self.per_minute / 60.0
        tokens, last = self._buckets.get(key, (float(self.per_minute), now))
        tokens = min(float(self.per_minute), tokens + (now - last) * refill)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1, now)
        return True

    def _prune(self, now: float) -> None:
        """Drop stale buckets so spoofed IPs cannot grow memory unboundedly."""
        if len(self._buckets) < self._max_buckets:
            return
        # A bucket is stale once it has fully refilled since its last touch.
        idle_seconds = self.per_minute / max(self.per_minute / 60.0, 1e-9)
        cutoff = now - max(idle_seconds * 2, 120.0)
        for k in [k for k, (_, last) in self._buckets.items() if last < cutoff]:
            del self._buckets[k]
        if len(self._buckets) >= self._max_buckets:
            self._buckets.clear()


limiter = _RateLimiter(settings.RATE_LIMIT_PER_MINUTE)


def _client_ip(request: Request) -> str:
    # Only honour X-Forwarded-For when explicitly configured to sit behind a
    # trusted proxy; otherwise attackers could spoof it to bypass rate limits.
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit(scope: str):
    """FastAPI dependency that enforces per-IP rate limiting on a route group."""
    async def _dep(request: Request):
        ip = _client_ip(request)
        if not limiter.allow(f"{scope}:{ip}"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again later.",
            )
    return _dep


# -----------------------------------------------------------------------------
# Lifespan
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_application", env=settings.APP_ENV)
    await init_db()
    pump_task = asyncio.create_task(_redis_event_pump())
    yield
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await pump_task
    logger.info("shutting_down_application")
    await close_db()


# -----------------------------------------------------------------------------
# Realtime: Redis Pub/Sub -> WebSocket fan-out
#
# Other services publish JSON envelopes to Redis channels:
#   geosentinel:alerts   {"type": "alert.new",     "payload": {...AlertRead...}}
#   geosentinel:sensors  {"type": "sensor.reading","payload": {...}}
#   geosentinel:reports  {"type": "report.new",    "payload": {...}}
# This pump relays them to every connected WebSocket client. When Redis is not
# reachable (local dev without Docker) the pump retries quietly — the app and
# dashboard keep working, just without live push.
# -----------------------------------------------------------------------------
REDIS_CHANNELS = ("geosentinel:alerts", "geosentinel:sensors", "geosentinel:reports")


async def _redis_event_pump() -> None:
    while True:
        pubsub = None
        client = None
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.REDIS_URL, password=settings.REDIS_PASSWORD)
            pubsub = client.pubsub()
            await pubsub.subscribe(*REDIS_CHANNELS)
            logger.info("realtime_subscribed", channels=list(REDIS_CHANNELS))
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                try:
                    body = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
                envelope = {
                    "type": str(body.get("type", "event")),
                    "payload": body.get("payload", body),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                await manager.broadcast(json.dumps(envelope))
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("realtime_pump_retrying", error=str(exc), retry_s=5)
            await asyncio.sleep(5)
        finally:
            for closer in (
                lambda: pubsub.unsubscribe(),
                lambda: pubsub.aclose(),
                lambda: client.aclose(),
            ):
                with contextlib.suppress(Exception):
                    if callable(closer):
                        maybe = closer()
                        if asyncio.iscoroutine(maybe):
                            with contextlib.suppress(Exception):
                                await maybe


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(
    title="GeoSentinel-NER API",
    description="AI-Powered Landslide Early Warning & Monitoring Platform for North Eastern Region",
    version="0.1.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url="/redoc" if settings.APP_DEBUG else None,
    openapi_url="/openapi.json" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)

# --- Middleware ---
# CORS: never use "*" with allow_credentials=True. Read origins from config.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)

if not settings.APP_DEBUG:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    request_id = request.headers.get("x-request-id", str(uuid4()))
    response = None
    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as e:
        logger.exception(
            "request_failed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            error=str(e),
        )
        raise


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


# -----------------------------------------------------------------------------
# Auth dependencies
# -----------------------------------------------------------------------------
_USER_SELECT = text(
    """
    SELECT id, username, email, phone, full_name, role, state_id, district_id,
           block_id, village_id, preferred_language, is_active, is_verified,
           last_login_at, created_at, updated_at
    FROM app_user
    WHERE id = :user_id AND is_active
    LIMIT 1
    """
)


def _row_to_user(row) -> AppUserRead:
    return AppUserRead(
        id=row.id,
        username=row.username,
        email=row.email,
        phone=row.phone,
        full_name=row.full_name,
        role=row.role,
        state_id=row.state_id,
        district_id=row.district_id,
        block_id=row.block_id,
        village_id=row.village_id,
        preferred_language=row.preferred_language or settings.DEFAULT_LANGUAGE,
        is_active=row.is_active,
        is_verified=row.is_verified,
        created_at=row.created_at or datetime.now(UTC),
        updated_at=row.updated_at,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db_session),
) -> AppUserRead:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = verify_token(credentials.credentials, "access")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The token proves identity; the DB decides whether the account still
    # exists and is active (revocation on deactivate/delete is immediate).
    result = await db.execute(_USER_SELECT, {"user_id": str(payload.sub)})
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found or deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _row_to_user(row)


def require_permission(resource: str, action: str):
    async def permission_checker(user: AppUserRead = Depends(get_current_user)):
        if not check_permission(user.role, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: {resource}.{action}",
            )
        return user
    return permission_checker


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/health", response_model=HealthCheck, tags=["Health"])
async def health_check():
    checks: dict[str, str] = {"database": "unknown", "redis": "unknown", "minio": "unknown"}

    try:
        async with get_primary_db().session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        logger.warning("health_db_unhealthy", error=str(e))
        checks["database"] = "unhealthy"

    try:
        import redis.asyncio as redis
        r = redis.from_url(settings.REDIS_URL, password=settings.REDIS_PASSWORD)
        await r.ping()
        await r.aclose()
        checks["redis"] = "healthy"
    except Exception as e:
        logger.warning("health_redis_unhealthy", error=str(e))
        checks["redis"] = "unhealthy"

    try:
        from minio import Minio
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        client.list_buckets()
        checks["minio"] = "healthy"
    except Exception as e:
        logger.warning("health_minio_unhealthy", error=str(e))
        checks["minio"] = "unhealthy"

    overall = "healthy" if all(v == "healthy" for v in checks.values()) else "degraded"
    return HealthCheck(
        status=overall,
        version="0.1.0",
        environment=settings.APP_ENV,
        checks=checks,
    )


# -----------------------------------------------------------------------------
# Auth endpoints
# -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

# Roles that can never be self-assigned via public registration.
_SELF_ASSIGNABLE_ROLES = {"citizen", "volunteer"}

_REGISTER_SQL = text(
    """
    INSERT INTO app_user (username, email, phone, password_hash, full_name, role,
                          state_id, district_id, block_id, village_id, preferred_language)
    VALUES (:username, :email, :phone, :password_hash, :full_name, :role,
            :state_id, :district_id, :block_id, :village_id, :preferred_language)
    RETURNING id, username, email, phone, full_name, role, state_id, district_id,
              block_id, village_id, preferred_language, is_active, is_verified,
              last_login_at, created_at, updated_at
    """
)


@app.post(f"{settings.API_PREFIX}/auth/register", response_model=AppUserRead, tags=["Auth"],
          dependencies=[Depends(rate_limit("auth"))])
async def register(user_data: AppUserCreate, db: AsyncSession = Depends(get_db_session)):
    """Public registration. Passwords are bcrypt-hashed; privileged roles must be
    granted by an admin — they cannot be self-assigned here."""
    if len(user_data.password) < MIN_PASSWORD_LENGTH or len(user_data.password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters",
        )
    role = user_data.role if user_data.role in _SELF_ASSIGNABLE_ROLES else "citizen"
    params = {
        "username": user_data.username.strip(),
        "email": user_data.email,
        "phone": user_data.phone,
        "password_hash": hash_password(user_data.password),
        "full_name": user_data.full_name,
        "role": role,
        "state_id": user_data.state_id,
        "district_id": user_data.district_id,
        "block_id": user_data.block_id,
        "village_id": user_data.village_id,
        "preferred_language": user_data.preferred_language,
    }
    try:
        result = await db.execute(_REGISTER_SQL, params)
        row = result.first()
    except IntegrityError:
        await db.rollback()
        # Generic message: do not reveal whether the username or email exists.
        raise HTTPException(status_code=409, detail="Username or email already registered")
    logger.info("user_registered", user_id=str(row.id), role=row.role)
    return _row_to_user(row)


_LOGIN_SQL = text(
    """
    SELECT id, username, password_hash, role, is_active, failed_login_attempts, locked_until
    FROM app_user
    WHERE username = :identifier OR email = :identifier
    LIMIT 1
    """
)
_RECORD_FAILED_LOGIN_SQL = text(
    """
    UPDATE app_user
    SET failed_login_attempts = failed_login_attempts + 1,
        locked_until = CASE
            WHEN failed_login_attempts + 1 >= :max_failed THEN NOW() + make_interval(mins => :lockout_mins)
            ELSE locked_until END
    WHERE id = :user_id
    """
)
_RECORD_SUCCESS_SQL = text(
    """
    UPDATE app_user
    SET failed_login_attempts = 0, locked_until = NULL, last_login_at = NOW()
    WHERE id = :user_id
    """
)


@app.post(f"{settings.API_PREFIX}/auth/login", response_model=Token, tags=["Auth"],
          dependencies=[Depends(rate_limit("auth-login"))])
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db_session)):
    """Verify credentials against the DB. Always returns a generic 401 so
    attackers cannot enumerate usernames. Accounts lock after repeated failures."""
    if not body.username or not body.password:
        raise HTTPException(status_code=422, detail="username and password are required")
    identifier = body.username.strip()
    logger.info("login_attempt")

    result = await db.execute(_LOGIN_SQL, {"identifier": identifier})
    row = result.first()
    generic_401 = HTTPException(status_code=401, detail="Incorrect username or password")
    if row is None:
        # Burn a hash comparison anyway to keep timing consistent.
        try:
            verify_password(body.password, "$2b$12$" + "x" * 53)
        except Exception:
            pass
        raise generic_401

    now = datetime.now(UTC)
    if not row.is_active:
        raise generic_401
    if row.locked_until is not None and row.locked_until > now:
        raise HTTPException(status_code=423, detail="Account temporarily locked. Try again later.")

    try:
        password_ok = verify_password(body.password, row.password_hash)
    except Exception:
        # Malformed/legacy hash in DB — treat as a failed login, not a 500.
        password_ok = False

    if not password_ok:
        await db.execute(
            _RECORD_FAILED_LOGIN_SQL,
            {"max_failed": MAX_FAILED_LOGINS, "lockout_mins": LOCKOUT_MINUTES, "user_id": str(row.id)},
        )
        await db.commit()
        logger.warning("login_failed", user_id=str(row.id))
        raise generic_401

    await db.execute(_RECORD_SUCCESS_SQL, {"user_id": str(row.id)})
    await db.commit()
    access = create_access_token(subject=row.id, username=row.username, role=row.role)
    refresh = create_refresh_token(subject=row.id, username=row.username, role=row.role)
    return Token(access_token=access, refresh_token=refresh)


@app.post(f"{settings.API_PREFIX}/auth/refresh", response_model=Token, tags=["Auth"],
          dependencies=[Depends(rate_limit("auth"))])
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Refresh access token. Refresh token is taken from the request body to
    avoid leaking it via access logs / proxy URLs. The account must still
    exist and be active — deactivation kills refresh immediately."""
    try:
        payload = verify_token(body.refresh_token, "refresh")
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    result = await db.execute(_USER_SELECT, {"user_id": str(payload.sub)})
    row = result.first()
    if row is None:
        raise HTTPException(status_code=401, detail="Account not found or deactivated")
    access = create_access_token(subject=row.id, username=row.username, role=row.role)
    new_refresh = create_refresh_token(subject=row.id, username=row.username, role=row.role)
    return Token(access_token=access, refresh_token=new_refresh)


@app.get(f"{settings.API_PREFIX}/auth/me", response_model=AppUserRead, tags=["Auth"])
async def get_me(user: AppUserRead = Depends(get_current_user)):
    return user


@app.patch(f"{settings.API_PREFIX}/auth/me", response_model=AppUserRead, tags=["Auth"])
async def update_me(
    user_data: AppUserUpdate,
    user: AppUserRead = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    # Self-service updates may only touch profile fields. Role and jurisdiction
    # assignments are admin-controlled — silently ignore them here to prevent
    # privilege escalation.
    updates = user_data.model_dump(exclude_unset=True)
    for field in ("role", "state_id", "district_id", "block_id", "village_id"):
        updates.pop(field, None)
    if not updates:
        return user
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    stmt = text(f"UPDATE app_user SET {set_clause} WHERE id = :user_id RETURNING id")
    await db.execute(stmt, {**updates, "user_id": str(user.id)})
    result = await db.execute(_USER_SELECT, {"user_id": str(user.id)})
    row = result.first()
    logger.info("user_profile_update", user_id=str(user.id), fields=sorted(updates))
    return _row_to_user(row)


# -----------------------------------------------------------------------------
# Geo utilities (TomTom primary, Nominatim keyless fallback)
# -----------------------------------------------------------------------------
@app.get(f"{settings.API_PREFIX}/geo/reverse", tags=["Geo"])
async def reverse_geocode(lat: float, lon: float):
    """Reverse geocode a coordinate to a human-readable place label.

    Unauthenticated by design: it proxies public geocoding providers and must
    work in demo/offline-login modes where no JWT exists. Tries TomTom first
    (when TOMTOM_API_KEY is configured), then falls back to keyless
    OpenStreetMap/Nominatim so the feature degrades gracefully.
    """
    import httpx

    async def _tomtom(client: httpx.AsyncClient) -> dict[str, Any] | None:
        if not settings.TOMTOM_API_KEY:
            return None
        resp = await client.get(
            f"{settings.TOMTOM_BASE_URL}/search/2/reverseGeocode/{lat},{lon}.json",
            params={"key": settings.TOMTOM_API_KEY},
        )
        resp.raise_for_status()
        addresses = resp.json().get("addresses", [])
        if not addresses:
            return {"label": None, "village": None, "district": None, "state": None, "lat": lat, "lon": lon}
        addr = addresses[0].get("address", {})
        village = (
            addr.get("municipalitySubdivision")
            or addr.get("municipalityNeighbourhood")
            or addr.get("municipality")
        )
        return {
            "label": addr.get("freeformAddress") or addresses[0].get("position") and f"{lat}, {lon}",
            "village": village,
            "district": addr.get("secondaryCountrySubdivision") or addr.get("municipality"),
            "state": addr.get("countrySubdivision"),
            "lat": lat,
            "lon": lon,
            "provider": "tomtom",
        }

    async def _nominatim(client: httpx.AsyncClient) -> dict[str, Any] | None:
        resp = await client.get(
            f"{settings.NOMINATIM_BASE_URL}/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 14, "addressdetails": 1},
            headers={"User-Agent": "GeoSentinel-NER/0.1 (landslide early warning dashboard)"},
        )
        if resp.status_code == 404:
            return {"label": None, "village": None, "district": None, "state": None, "lat": lat, "lon": lon}
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})
        village = (
            addr.get("village") or addr.get("hamlet") or addr.get("suburb")
            or addr.get("town") or addr.get("city_district") or addr.get("city")
        )
        parts = [p for p in (data.get("display_name") or "").split(", ") if p]
        return {
            "label": ", ".join(parts[:3]) if parts else None,
            "village": village,
            "district": addr.get("state_district") or addr.get("county"),
            "state": addr.get("state"),
            "lat": lat,
            "lon": lon,
            "provider": "osm-nominatim",
        }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            try:
                result = await _tomtom(client)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning("reverse_geocode_tomtom_failed_falling_back", error=str(e))
            try:
                return await _nominatim(client)
            except Exception as e:
                logger.warning("reverse_geocode_nominatim_failed", error=str(e))
                raise HTTPException(status_code=502, detail="Geocoding lookup failed")
    except HTTPException:
        raise
    except Exception:
        logger.exception("reverse_geocode_unexpected_error")
        raise HTTPException(status_code=502, detail="Geocoding lookup failed")


# -----------------------------------------------------------------------------
# Admin endpoints (State, District, Block, Village)
# -----------------------------------------------------------------------------
@app.get(f"{settings.API_PREFIX}/admin/states", response_model=PaginatedResponse[AdminStateRead], tags=["Admin"])
async def list_states(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(f"{settings.API_PREFIX}/admin/states/{{state_id}}", response_model=AdminStateRead, tags=["Admin"])
async def get_state(state_id: UUID, db: AsyncSession = Depends(get_db_session)):
    raise HTTPException(status_code=404, detail="Not found")


# -----------------------------------------------------------------------------
# Infrastructure
# -----------------------------------------------------------------------------
@app.get(
    f"{settings.API_PREFIX}/infrastructure/roads",
    response_model=PaginatedResponse[InfrastructureRoadRead],
    tags=["Infrastructure"],
)
async def list_roads(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(
    f"{settings.API_PREFIX}/infrastructure/facilities",
    response_model=PaginatedResponse[InfrastructureFacilityRead],
    tags=["Infrastructure"],
)
async def list_facilities(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


# -----------------------------------------------------------------------------
# Sensors
# -----------------------------------------------------------------------------
@app.get(
    f"{settings.API_PREFIX}/sensors/stations",
    response_model=PaginatedResponse[SensorStationRead],
    tags=["Sensors"],
)
async def list_stations(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(
    f"{settings.API_PREFIX}/sensors/readings",
    response_model=PaginatedResponse[SensorReadingRead],
    tags=["Sensors"],
)
async def get_readings(
    station_id: UUID | None = None,
    parameter_id: UUID | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_ts_session),
):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


# -----------------------------------------------------------------------------
# Hazard & Risk
# -----------------------------------------------------------------------------
@app.get(
    f"{settings.API_PREFIX}/hazard/inventory",
    response_model=PaginatedResponse[LandslideInventoryRead],
    tags=["Hazard"],
)
async def list_inventory(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(f"{settings.API_PREFIX}/risk/zones", response_model=PaginatedResponse[SusceptibilityZoneRead], tags=["Risk"])
async def list_zones(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(f"{settings.API_PREFIX}/risk/forecasts", response_model=PaginatedResponse[RiskForecastRead], tags=["Risk"])
async def list_forecasts(
    zone_id: UUID | None = None,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


# -----------------------------------------------------------------------------
# Alerts
# -----------------------------------------------------------------------------
_ALERTS_SELECT = text(
    """
    SELECT id, rule_id, zone_id, severity, title, message, message_local, language,
           issued_at, expires_at, acknowledged_at, acknowledged_by, status,
           cap_identifier, metadata
    FROM alert
    WHERE (:status IS NULL OR status = :status)
      AND (:severity IS NULL OR severity = :severity)
      AND (:since IS NULL OR issued_at > :since)
    ORDER BY issued_at DESC
    LIMIT :limit OFFSET :offset
    """
)


@app.get(f"{settings.API_PREFIX}/alerts", response_model=PaginatedResponse[AlertRead], tags=["Alerts"])
async def list_alerts(
    severity: str | None = None,
    zone_id: UUID | None = None,
    status: str | None = None,
    since: datetime | None = None,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db_session),
    user: AppUserRead = Depends(get_current_user),
):
    """List alerts. `since=<ISO8601>` returns only alerts issued after that
    timestamp — the realtime client uses it to backfill anything missed while
    its WebSocket was disconnected."""
    try:
        result = await db.execute(
            _ALERTS_SELECT,
            {
                "status": status,
                "severity": severity,
                "since": since,
                "limit": params.page_size,
                "offset": (params.page - 1) * params.page_size,
            },
        )
        rows = result.all()
        items = [
            AlertRead(
                id=r.id,
                rule_id=r.rule_id,
                zone_id=r.zone_id,
                severity=r.severity,
                title=r.title,
                message=r.message,
                message_local=r.message_local,
                language=r.language or "en",
                issued_at=r.issued_at,
                expires_at=r.expires_at,
                acknowledged_at=r.acknowledged_at,
                acknowledged_by=r.acknowledged_by,
                status=r.status,
                cap_identifier=r.cap_identifier,
                metadata=r.metadata or {},
            )
            for r in rows
        ]
        return PaginatedResponse(
            items=items, total=len(items), page=params.page, page_size=params.page_size, total_pages=1
        )
    except Exception as exc:
        # Table may not exist yet before migrations run — degrade to an empty
        # page instead of failing the dashboard.
        logger.warning("alerts_query_degraded", error=str(exc))
        return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.post(f"{settings.API_PREFIX}/alerts/{{alert_id}}/acknowledge", tags=["Alerts"])
async def acknowledge_alert(
    alert_id: UUID,
    user: AppUserRead = Depends(require_permission("alerts", "acknowledge")),
    db: AsyncSession = Depends(get_db_session),
):
    return {"status": "acknowledged", "alert_id": str(alert_id)}


# -----------------------------------------------------------------------------
# Citizen reports
# -----------------------------------------------------------------------------
@app.post(f"{settings.API_PREFIX}/reports", response_model=CitizenReportRead, tags=["Reports"],
          dependencies=[Depends(rate_limit("reports"))])
async def create_report(
    report: CitizenReportCreate,
    user: AppUserRead | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    logger.info("report_submitted", report_type=report.report_type)
    return CitizenReportRead(
        id=uuid4(),
        report_code=f"GSN-{datetime.now(UTC).year}-{uuid4().hex[:6].upper()}",
        **report.model_dump(),
        status="submitted",
        priority_score=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@app.get(f"{settings.API_PREFIX}/reports", response_model=PaginatedResponse[CitizenReportRead], tags=["Reports"])
async def list_reports(
    status: str | None = None,
    report_type: str | None = None,
    village_id: UUID | None = None,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db_session),
    user: AppUserRead = Depends(get_current_user),
):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


# Allowed media types for citizen report uploads (defence in depth: extension
# AND declared content type must both match; actual bytes are re-validated by
# the CV triage pipeline downstream).
_ALLOWED_MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic",
    ".mp4", ".mov", ".webm",
    ".m4a", ".mp3", ".wav",
}
_ALLOWED_MEDIA_MIME_PREFIXES = ("image/", "video/", "audio/")


@app.post(f"{settings.API_PREFIX}/reports/{{report_id}}/media", response_model=CitizenReportMediaRead, tags=["Reports"],
          dependencies=[Depends(rate_limit("media-upload"))])
async def upload_report_media(
    report_id: UUID,
    file: UploadFile = File(...),
    is_primary: bool = False,
    user: AppUserRead = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_MEDIA_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or 'unknown'}")
    mime = (file.content_type or "").lower()
    if not mime.startswith(_ALLOWED_MEDIA_MIME_PREFIXES):
        raise HTTPException(status_code=415, detail="Unsupported content type")

    # Enforce upload size limit before buffering everything into memory.
    max_bytes = settings.MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum size of {max_bytes} bytes",
            )
        chunks.append(chunk)
    object_name = f"reports/{report_id}/{uuid4().hex}{suffix}"
    logger.info(
        "report_media_upload",
        report_id=str(report_id),
        filename=file.filename,
        size_bytes=total,
    )
    return CitizenReportMediaRead(
        id=uuid4(),
        report_id=report_id,
        media_type="photo",
        file_path=object_name,
        file_size_bytes=total,
        mime_type=file.content_type,
        is_primary=is_primary,
        created_at=datetime.now(UTC),
    )


# -----------------------------------------------------------------------------
# WebSocket (real-time updates) — requires a valid JWT
# -----------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)

    async def send_personal_message(self, message: str, client_id: str):
        ws = self.active_connections.get(client_id)
        if ws:
            await ws.send_text(message)

    async def broadcast(self, message: str):
        for ws in list(self.active_connections.values()):
            try:
                await ws.send_text(message)
            except Exception:
                pass


manager = ConnectionManager()


# -----------------------------------------------------------------------------
# Development helpers — auto-disabled unless APP_DEBUG=true
# -----------------------------------------------------------------------------
def _ensure_dev_mode():
    if not settings.APP_DEBUG:
        raise HTTPException(status_code=404, detail="Not found")


@app.post(f"{settings.API_PREFIX}/dev/session", tags=["Dev"])
async def dev_session():
    """Mint a working access token without a database (local dev/demo only)."""
    _ensure_dev_mode()
    token = create_access_token(UUID(int=1), "demo-live", "district_officer")
    return {"access_token": token, "token_type": "bearer"}


@app.post(f"{settings.API_PREFIX}/dev/broadcast", tags=["Dev"])
async def dev_broadcast(event: dict[str, Any]):
    """Inject a RealtimeEvent to every connected WebSocket client."""
    _ensure_dev_mode()
    await manager.broadcast(json.dumps(event))
    return {"delivered": True, "clients": len(manager.active_connections)}


@app.websocket(f"{settings.API_PREFIX}/ws/{{client_id}}")
async def websocket_endpoint(websocket: WebSocket, client_id: str, token: str | None = None):
    """Authenticate before accepting. Token may be passed as `?token=` query param
    because browsers cannot set headers on WebSocket upgrade requests. Reject
    clients without a valid access token."""
    if not token:
        await websocket.close(code=4401)
        return
    try:
        verify_token(token, "access")
    except ValueError:
        await websocket.close(code=4401)
        return

    # Reject obviously-bogus client_id values.
    try:
        UUID(client_id)
    except ValueError:
        await websocket.close(code=4400)
        return

    await manager.connect(websocket, client_id)
    try:
        await websocket.send_text(
            json.dumps({"type": "connection.established", "payload": {"client_id": client_id}})
        )
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            # Client keepalive: respond pong so the browser knows the link is up.
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_text(
                    json.dumps({"type": "pong", "timestamp": datetime.now(UTC).isoformat()})
                )
    except WebSocketDisconnect:
        manager.disconnect(client_id)


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.APP_DEBUG)
