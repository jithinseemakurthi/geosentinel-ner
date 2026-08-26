"""
GeoSentinel-NER ML Engine
Model inference service for M1 (Susceptibility), M2 (Dynamic Risk), M3 (CV Triage).
"""
import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from geosentinel_shared import (
    close_db,
    configure_logging,
    get_logger,
    init_db,
    settings,
)
from pydantic import BaseModel

configure_logging()
logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Model Loaders
# -----------------------------------------------------------------------------
class ModelRegistry:
    """Lazy-loaded model registry."""

    def __init__(self):
        self._m1_model = None
        self._m2_model = None
        self._m3_model = None
        self._m1_version = None
        self._m2_version = None
        self._m3_version = None

    def load_m1(self):
        if self._m1_model is None:
            logger.info("loading_m1_model", version=settings.M1_MODEL_VERSION)
            # In production: load from MLflow/Model Registry
            # import mlflow.pyfunc
            # self._m1_model = mlflow.pyfunc.load_model(f"models:/m1_susceptibility/{settings.M1_MODEL_VERSION}")
            # For now, placeholder
            self._m1_model = "M1_MODEL_PLACEHOLDER"
            self._m1_version = settings.M1_MODEL_VERSION
        return self._m1_model

    def load_m2(self):
        if self._m2_model is None:
            logger.info("loading_m2_model", version=settings.M2_MODEL_VERSION)
            # import mlflow.pyfunc
            # self._m2_model = mlflow.pyfunc.load_model(f"models:/m2_dynamic_risk/{settings.M2_MODEL_VERSION}")
            self._m2_model = "M2_MODEL_PLACEHOLDER"
            self._m2_version = settings.M2_MODEL_VERSION
        return self._m2_model

    def load_m3(self):
        if self._m3_model is None:
            logger.info("loading_m3_model", version=settings.M3_MODEL_VERSION)
            # import mlflow.pyfunc
            # self._m3_model = mlflow.pyfunc.load_model(f"models:/m3_cv_triage/{settings.M3_MODEL_VERSION}")
            self._m3_model = "M3_MODEL_PLACEHOLDER"
            self._m3_version = settings.M3_MODEL_VERSION
        return self._m3_model


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
    model_registry.load_m1()  # ensure the model artefact is resolved/loaded

    # In production: prepare features, run inference
    # features = prepare_m1_features(request.zone_ids)
    # predictions = model.predict(features)

    # Placeholder response
    results = []
    for zone_id in request.zone_ids:
        results.append(M1PredictResponse(
            zone_id=zone_id,
            susceptibility_score=0.75,
            susceptibility_class="High",
            shap_values={"slope": 0.3, "rainfall": 0.25, "soil_type": 0.2} if request.include_shap else None,
        ))
    return results


@app.post("/predict/m2", response_model=List[M2PredictResponse])
async def predict_m2(request: M2PredictRequest):
    """Predict dynamic risk for zones over forecast horizons.

    Features come from real Open-Meteo rainfall (via data-ingestion). While no
    trained model is registered, risk is scored with a transparent heuristic:
    logistic blend of forecast + antecedent rainfall (M2 paper's dominant
    drivers). Swap in model.predict() once MLflow registry is populated.
    """
    model_registry.load_m2()  # ensure the model artefact is resolved/loaded
    features = await prepare_m2_features(request.zone_ids, request.forecast_hours)
    feat_by_zone = {f["zone_id"]: f for f in features}

    def heuristic_score(f24: float, a3: float, a7: float) -> float:
        z = 0.9 * math.log1p(f24) + 0.6 * math.log1p(a3) + 0.3 * math.log1p(a7) - 3.2
        return max(0.02, min(0.97, 1 / (1 + math.exp(-z))))

    def level_for(score: float) -> str:
        if score >= 0.8:
            return "Evacuation"
        if score >= 0.5:
            return "Warning"
        if score >= 0.3:
            return "Watch"
        return "Advisory"

    results = []
    now = datetime.now(timezone.utc)
    for zone_id in request.zone_ids:
        f = feat_by_zone.get(str(zone_id), {})
        fc = f.get("forecast_rainfall_mm") or {}
        ant = f.get("antecedent_rainfall_mm") or {}
        a3 = float(ant.get("3d") or 0)
        a7 = float(ant.get("7d") or 0)
        for hours in request.forecast_hours:
            f24 = float(fc.get(str(min(hours, 72))) or 0)
            score = heuristic_score(f24, a3, a7) if f else 0.05
            triggering = "rainfall" if f24 >= 10 else ("antecedent-moisture" if a7 >= 50 else None)
            valid_from = now
            valid_to = now + timedelta(hours=hours)
            results.append(M2PredictResponse(
                zone_id=zone_id,
                valid_from=valid_from,
                valid_to=valid_to,
                risk_level=level_for(score),
                risk_score=round(score, 3),
                triggering_factor=triggering,
                rainfall_forecast_mm=round(f24, 2),
                soil_moisture_pct=f.get("soil_moisture_pct"),
            ))
    return results


@app.post("/predict/m3", response_model=M3PredictResponse)
async def predict_m3(request: M3PredictRequest):
    """Classify citizen report images."""
    if not settings.ENABLE_CV_TRIAGE:
        raise HTTPException(status_code=503, detail="CV triage not enabled")

    model_registry.load_m3()  # ensure the model artefact is resolved/loaded

    # In production: download images, preprocess, run inference
    # images = download_and_preprocess(request.image_urls)
    # predictions = model.predict(images)

    import time
    start = time.time()
    # Placeholder
    time.sleep(0.1)  # Simulate inference
    inference_time = (time.time() - start) * 1000

    return M3PredictResponse(
        report_id=request.report_id,
        classification="crack",
        confidence=0.87,
        class_probabilities={"crack": 0.87, "bulge": 0.08, "debris": 0.03, "other": 0.02},
        inference_time_ms=inference_time,
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
