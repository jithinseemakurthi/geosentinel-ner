# GeoSentinel Live Internet Engine — standalone (optional)
# Build context must be the REPOSITORY ROOT:  docker build -f services/live-engine/Dockerfile .
# This service is OPTIONAL — the engine already runs inside api-gateway.
# Enable with:  docker compose --profile live-engine up -d live-engine
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends curl libpq-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy shared lib and engine code from api-gateway (single source of truth)
COPY packages/geosentinel-shared /app/packages/geosentinel-shared
COPY services/api-gateway/app/live_engine.py /app/live_engine.py
COPY services/live-engine/app /app/app

# Minimal deps for the engine (same as gateway's live subset)
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx sqlalchemy[asyncio] asyncpg structlog redis python-dotenv pydantic pydantic-settings

EXPOSE 8007

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007"]
