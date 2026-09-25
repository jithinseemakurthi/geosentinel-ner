"""
GeoSentinel Live Internet Engine — standalone service (optional).

This is the same LiveInternetEngine that runs inside api-gateway lifespan,
but as a dedicated container on :8007 for horizontally scaled deployments.
The gateway already runs the engine, so this service is only needed with
`docker compose --profile live-engine up -d`.

Build context is repo root:  docker build -f services/live-engine/Dockerfile .
"""
# live_engine.py is copied to /app/live_engine.py by the Dockerfile
import sys
from pathlib import Path

from fastapi import FastAPI

# Ensure /app is on path (uvicorn sets WORKDIR /app)
sys.path.insert(0, "/app")

try:
    from live_engine import engine
except ImportError:
    # Fallback when running from repo root without Docker (dev)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api-gateway"))
    from app.live_engine import engine  # type: ignore

app = FastAPI(title="GeoSentinel Live Engine (standalone)", version="1.0.0")


@app.on_event("startup")
async def _startup():
    await engine.start()


@app.on_event("shutdown")
async def _shutdown():
    await engine.stop()


@app.get("/health")
async def health():
    return engine.get_status()


@app.get("/api/v1/live/engine/status")
async def status():
    return engine.get_status()


@app.post("/api/v1/live/engine/run")
async def run():
    summary = await engine.run_cycle()
    return {"status": "ok", "summary": summary, "engine": engine.get_status()}


@app.get("/api/v1/live/engine/reports")
async def reports(limit: int = 20):
    items = engine.get_reports(limit=min(limit, 100))
    return {"items": items, "count": len(items), "engine": engine.get_status()}


@app.get("/api/v1/live/reports")
async def live_reports(limit: int = 12):
    items = engine.get_reports(limit=limit)
    return {"items": items, "internet_count": len(items), "citizen_count": 0, "cached": False}
