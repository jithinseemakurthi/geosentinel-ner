# GeoSentinel-NER Data Ingestion Dockerfile
# NOTE: build context must be the REPOSITORY ROOT:
#   docker build -f services/data-ingestion/Dockerfile .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gdal-bin libgdal-dev proj-bin libproj-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/services/data-ingestion
RUN pip install --no-cache-dir poetry==1.8.2

COPY services/data-ingestion/pyproject.toml services/data-ingestion/poetry.lock* ./
COPY packages/geosentinel-shared /app/packages/geosentinel-shared

RUN poetry config virtualenvs.create false \
    && poetry install --only=main --no-root --no-interaction --no-ansi

COPY services/data-ingestion/app ./app

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app/services/data-ingestion
USER app
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
