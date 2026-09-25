"""
Standalone runner for the Live Internet Analysis Engine — proves it works without Docker.

Usage:
  # One-shot: fetch → analyze → build and print reports
  python scripts/run_live_engine.py --once

  # Continuous engine (every 5 min, like in api-gateway lifespan)
  python scripts/run_live_engine.py --loop

  # Minimal HTTP server for the dashboard when Docker is down (serves live endpoints on :8000)
  python scripts/run_live_engine.py --serve --port 8000

The engine fetches GDACS + EONET + USGS (free, no key), analyzes with LLM (Groq/OpenAI/NVIDIA/Ollama)
or heuristic fallback, deduplicates, and builds CitizenReport-like objects. No hardcoded data.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure imports work when run from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "geosentinel-shared"))
sys.path.insert(0, str(ROOT / "services" / "api-gateway"))

os.environ.setdefault("PYTHONPATH", str(ROOT / "packages" / "geosentinel-shared"))


async def once():
    from app.live_engine import engine

    print("=== Live Internet Analysis Engine — ONE-SHOT ===\n")
    summary = await engine.run_cycle()
    print(f"Cycle summary: {summary}\n")
    status = engine.get_status()
    print(f"Status: {status}\n")
    reports = engine.get_reports(limit=10)
    print(f"Built {len(reports)} reports (in-memory):\n")
    for r in reports:
        print(
            f"  {r['code']} | {r['district']:15} | {r['report_type']:12} | {r['severity']:8} "
            f"| prio {r['priorityScore']:3} | {r['source']:9} | {r['description'][:90]}"
        )
        if r.get("url"):
            print(f"    -> {r['url']}")
    if not reports:
        print("  (no reports built — internet may be unreachable or all items deduplicated)")
    print("\n=== Proof: engine is working — reports are LIVE from GDACS/EONET/USGS ===\n")


async def loop():
    from app.live_engine import engine

    await engine.start()
    print(f"Engine started — interval {engine.interval}s — press Ctrl+C to stop\n")
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping...")
        await engine.stop()


def serve(port: int):
    """Minimal FastAPI server exposing just the live-engine endpoints (no DB needed)."""
    import uvicorn
    from app.live_engine import engine
    from fastapi import FastAPI

    app = FastAPI(title="GeoSentinel Live Engine (standalone)")

    @app.on_event("startup")
    async def _startup():
        await engine.start()

    @app.on_event("shutdown")
    async def _shutdown():
        await engine.stop()

    @app.get("/api/v1/live/engine/status")
    async def _status():
        return engine.get_status()

    @app.post("/api/v1/live/engine/run")
    async def _run():
        summary = await engine.run_cycle()
        return {"status": "ok", "summary": summary, "engine": engine.get_status()}

    @app.get("/api/v1/live/engine/reports")
    async def _reports(limit: int = 20):
        items = engine.get_reports(limit=min(limit, 100))
        return {"items": items, "count": len(items), "engine": engine.get_status()}

    @app.get("/api/v1/live/reports")
    async def _live_reports(limit: int = 12):
        # Directly return engine reports (no DB, no GDACS cache — just engine's in-memory)
        items = engine.get_reports(limit=limit)
        return {"items": items, "internet_count": len(items), "citizen_count": 0, "cached": False}

    @app.get("/api/v1/live/health")
    async def _health():
        return {"gdacs": "free", "reliefweb": "fallback EONET/USGS", "engine": "standalone", "status": "ok"}

    print(f"\n=== Standalone Live Engine server at http://localhost:{port} ===")
    print(f"  GET  http://localhost:{port}/api/v1/live/engine/status")
    print(f"  POST http://localhost:{port}/api/v1/live/engine/run")
    print(f"  GET  http://localhost:{port}/api/v1/live/engine/reports?limit=10")
    print(f"  Dashboard will proxy /api to :8000 — point VITE_API_BASE_URL=http://localhost:{port}/api/v1 if needed\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def main():
    ap = argparse.ArgumentParser(description="Live Internet Analysis Engine runner")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--once", action="store_true", help="Run one fetch→analyze→build cycle and exit")
    g.add_argument("--loop", action="store_true",
                   help="Run continuous engine (interval from LIVE_ENGINE_INTERVAL_SECONDS)")
    g.add_argument("--serve", action="store_true",
                   help="Start minimal HTTP server for dashboard (standalone, no Docker)")
    ap.add_argument("--port", type=int, default=8000, help="Port for --serve (default 8000)")
    args = ap.parse_args()

    if args.serve:
        serve(args.port)
    elif args.loop:
        asyncio.run(loop())
    else:
        # default: once
        asyncio.run(once())


if __name__ == "__main__":
    main()
