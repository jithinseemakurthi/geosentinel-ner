# GeoSentinel-NER API Gateway Dockerfile
# NOTE: build context must be the REPOSITORY ROOT:
#   docker build -f services/api-gateway/Dockerfile .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    proj-bin \
    libproj-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/services/api-gateway

# Install Poetry
RUN pip install --no-cache-dir poetry==1.8.2

# Copy dependency manifests first for better layer caching
COPY services/api-gateway/pyproject.toml services/api-gateway/poetry.lock* ./

# Copy the shared library (path dependency ../../packages/geosentinel-shared)
COPY packages/geosentinel-shared /app/packages/geosentinel-shared

# Install dependencies (--no-root: the app itself is copied below, not packaged)
RUN poetry config virtualenvs.create false \
    && poetry install --only=main --no-root --no-interaction --no-ansi

# Copy application code
COPY services/api-gateway/app ./app

# Admin/password management utilities
COPY scripts /app/scripts

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app/services/api-gateway
USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
