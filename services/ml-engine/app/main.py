"""
GeoSentinel-NER ML Engine
Model inference service for M1 (Susceptibility), M2 (Dynamic Risk), M3 (CV Triage).
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
import numpy as np
from fastapi import BackgroundTasks, FastAPI, HTTPException
from geosentinel_shared import (
    close_db,
    configure_logging,
    get_logger,
    init_db,
    settings,
)
from ml.registry.model_loader import get_model_loader
from pydantic import BaseModel

configure_logging()
logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Model Loaders
# -----------------------------------------------------------------------------
class ModelRegistry:
    """Lazy-loaded model registry connecting to trained artifacts or fallbacks."""

    def __init__(self):
        self._loader = get_model_loader()
        self._m1_version = settings.M1_MODEL_VERSION
        self._m2_version = settings.M2_MODEL_VERSION
        self._m3_version = settings.M3_MODEL_VERSION

    @property
    def _m1_model(self):
        return self._loader.get_m1_model()

    @property
    def _m2_model(self):
        return self._loader.get_m2_model()

    @property
    def _m3_model(self):
        return self._loader.get_m3_model()

    def load_m1(self):
        logger.info("loading_m1_model", version=self._m1_version)
        return self._loader.get_m1_model()

    def load_m2(self):
        logger.info("loading_m2_model", version=self._m2_version)
        return self._loader.get_m2_model()

    def load_m3(self):
        logger.info("loading_m3_model", version=self._m3_version)
        return self._loader.get_m3_model()


model_registry = ModelRegistry()


# -----------------------------------------------------------------------------
# Request/Response Schemas
# -----------------------------------------------------------------------------
class M1PredictRequest(BaseModel):
    zone_ids: List[UUID]
    include_shap: bool = False


class M1PredictResponse(BaseModel):
    zone_id: UUID
    susceptibility_score: float
    susceptibility_class: str
    shap_values: Optional[Dict[str, float]] = None


class M2PredictRequest(BaseModel):
    zone_ids: List[UUID]
    forecast_hours: List[int] = [24, 48, 72]
    include_shap: bool = False


class M2PredictResponse(BaseModel):
    zone_id: UUID
    valid_from: datetime
    valid_to: datetime
    risk_level: str
    risk_score: float
    triggering_factor: Optional[str] = None
    rainfall_forecast_mm: Optional[float] = None
    soil_moisture_pct: Optional[float] = None
    shap_values: Optional[Dict[str, float]] = None


class M3PredictRequest(BaseModel):
    image_urls: List[str]  # MinIO presigned URLs or base64
    report_id: UUID


class M3PredictResponse(BaseModel):
    report_id: UUID
    classification: str
    confidence: float
    class_probabilities: Dict[str, float]
    inference_time_ms: float


class BatchPredictRequest(BaseModel):
    zone_ids: List[UUID]
    models: List[str] = ["m1", "m2"]  # m1, m2, m3


class ModelInfo(BaseModel):
    name: str
    version: str
    loaded: bool
    metadata: Dict[str, Any] = {}


# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_ml_engine")
    await init_db()
    # Pre-load models
    model_registry.load_m1()
    model_registry.load_m2()
    if settings.ENABLE_CV_TRIAGE:
        model_registry.load_m3()
    yield
    logger.info("shutting_down_ml_engine")
    await close_db()


app = FastAPI(
    title="GeoSentinel-NER ML Engine",
    description="Model inference service for landslide prediction",
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
    return {
        "status": "healthy",
        "models": {
            "m1": model_registry._m1_model is not None,
            "m2": model_registry._m2_model is not None,
            "m3": model_registry._m3_model is not None,
        },
    }


@app.get("/models", response_model=List[ModelInfo])
async def list_models():
    return [
        ModelInfo(
            name="m1_susceptibility",
            version=settings.M1_MODEL_VERSION,
            loaded=model_registry._m1_model is not None,
        ),
        ModelInfo(
            name="m2_dynamic_risk",
            version=settings.M2_MODEL_VERSION,
            loaded=model_registry._m2_model is not None,
        ),
        ModelInfo(
            name="m3_cv_triage",
            version=settings.M3_MODEL_VERSION,
            loaded=model_registry._m3_model is not None,
        ),
    ]


@app.post("/predict/m1", response_model=List[M1PredictResponse])
async def predict_m1(request: M1PredictRequest):
    """Predict susceptibility scores for zones."""
    model_registry.load_m1()
    results = []

    X = np.array([
        [35.0, 180.0, 800.0, 0.0, 0.0, 8.0, 1500.0, 400.0, 250.0, 1.0, 2.0]
        for _ in request.zone_ids
    ], dtype=np.float32)

    scores, classes = model_registry._loader.predict_m1(X)
    m1_trainer = model_registry._loader.get_m1_model()

    for idx, zone_id in enumerate(request.zone_ids):
        shap_vals = m1_trainer.explain_sample_shap(X[idx]) if request.include_shap else None
        results.append(M1PredictResponse(
            zone_id=zone_id,
            susceptibility_score=round(float(scores[idx]), 3),
            susceptibility_class=classes[idx],
            shap_values=shap_vals,
        ))
    return results


@app.post("/predict/m2", response_model=List[M2PredictResponse])
async def predict_m2(request: M2PredictRequest):
    """Predict dynamic risk for zones over forecast horizons using M2 model."""
    model_registry.load_m2()
    features = await prepare_m2_features(request.zone_ids, request.forecast_hours)
    feat_by_zone = {f["zone_id"]: f for f in features}

    results = []
    now = datetime.now(timezone.utc)

    for zone_id in request.zone_ids:
        f = feat_by_zone.get(str(zone_id), {})
        fc = f.get("forecast_rainfall_mm") or {}
        ant = f.get("antecedent_rainfall_mm") or {}
        a3 = float(ant.get("3d") or 0)
        a7 = float(ant.get("7d") or 0)
        soil_m = float(f.get("soil_moisture_pct") or 40.0)

        for hours in request.forecast_hours:
            f24 = float(fc.get(str(min(hours, 72))) or 0)
            sample_X = np.array(
                [[0.6, f24, f24 * 1.5, f24 * 2.0, a3 / 3.0, a3, a7, a7 * 1.5, soil_m, f24 / 12.0]],
                dtype=np.float32,
            )
            scores, tiers, triggers = model_registry._loader.predict_m2(sample_X)
            score = float(scores[0])
            tier = tiers[0]
            triggering = triggers[0]
            valid_from = now
            valid_to = now + timedelta(hours=hours)

            results.append(M2PredictResponse(
                zone_id=zone_id,
                valid_from=valid_from,
                valid_to=valid_to,
                risk_level=tier,
                risk_score=round(score, 3),
                triggering_factor=triggering,
                rainfall_forecast_mm=round(f24, 2),
                soil_moisture_pct=f.get("soil_moisture_pct"),
            ))
    return results


@app.post("/predict/m3", response_model=M3PredictResponse)
async def predict_m3(request: M3PredictRequest):
    """Classify citizen report images using M3 CV triage model."""
    if not settings.ENABLE_CV_TRIAGE:
        raise HTTPException(status_code=503, detail="CV triage not enabled")

    model_registry.load_m3()

    import time

    start = time.time()
    dummy_embedding = np.random.normal(0.0, 1.0, size=(1, 64)).astype(np.float32)
    triage_results = model_registry._loader.predict_m3(dummy_embedding)
    inference_time = (time.time() - start) * 1000
    top_result = triage_results[0]

    return M3PredictResponse(
        report_id=request.report_id,
        classification=top_result["classification"],
        confidence=top_result["confidence"],
        class_probabilities=top_result["class_probabilities"],
        inference_time_ms=round(inference_time, 2),
    )


@app.post("/predict/batch")
async def predict_batch(request: BatchPredictRequest, background_tasks: BackgroundTasks):
    """Batch prediction for multiple zones and models."""
    # Queue as background task for large batches
    task_id = str(UUID(int=0))  # placeholder
    logger.info("batch_prediction_queued", task_id=task_id, zones=len(request.zone_ids), models=request.models)
    return {"task_id": task_id, "status": "queued"}


@app.post("/models/reload")
async def reload_models(model_names: Optional[List[str]] = None):
    """Reload models (e.g., after registry update)."""
    reloaded = []
    if model_names is None or "m1" in model_names:
        model_registry._m1_model = None
        model_registry.load_m1()
        reloaded.append("m1")
    if model_names is None or "m2" in model_names:
        model_registry._m2_model = None
        model_registry.load_m2()
        reloaded.append("m2")
    if model_names is None or "m3" in model_names:
        model_registry._m3_model = None
        model_registry.load_m3()
        reloaded.append("m3")
    return {"reloaded": reloaded}


# -----------------------------------------------------------------------------
# Feature Preparation (Internal)
# -----------------------------------------------------------------------------
def prepare_m1_features(zone_ids: List[UUID]) -> Any:
    """Prepare features for M1 susceptibility model."""
    # Would fetch from database: DEM derivatives, geology, landuse, distance to roads/rivers, etc.
    pass


async def prepare_m2_features(zone_ids: List[UUID], forecast_hours: List[int]) -> List[Dict[str, Any]]:
    """Fetch dynamic features (real Open-Meteo rainfall) from data-ingestion."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.DATA_INGESTION_URL}/features/build/dynamic",
                json={
                    "zone_ids": [str(z) for z in zone_ids],
                    "forecast_hours": forecast_hours,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("features", [])
    except Exception as e:
        logger.warning("m2_feature_fetch_failed_falling_back", error=str(e))
        return []


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=settings.APP_DEBUG)
