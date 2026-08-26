# GeoSentinel-NER GIS Service Dockerfile
# NOTE: build context must be the REPOSITORY ROOT:
#   docker build -f services/gis-service/Dockerfile .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gdal-bin libgdal-dev proj-bin libproj-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/services/gis-service
RUN pip install --no-cache-dir poetry==1.8.2

COPY services/gis-service/pyproject.toml services/gis-service/poetry.lock* ./
COPY packages/geosentinel-shared /app/packages/geosentinel-shared

RUN poetry config virtualenvs.create false \
    && poetry install --only=main --no-root --no-interaction --no-ansi

COPY services/gis-service/app ./app

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app/services/gis-service
USER app
EXPOSE 8004
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
