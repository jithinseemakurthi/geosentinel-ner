# =============================================================================
# GeoSentinel-NER Makefile
# =============================================================================
# Database targets read POSTGRES_USER / POSTGRES_DB / TIMESCALE_DB from the
# environment; they default to the docker-compose values below. Override with
# `make migrate POSTGRES_USER=otheruser` if you changed your .env.

.DEFAULT_GOAL := help

POSTGRES_USER ?= geosentinel
POSTGRES_DB ?= geosentinel
TIMESCALE_DB ?= geosentinel_ts
COMPOSE := docker compose

.PHONY: help up up-kafka up-full down logs restart migrate migrate-rollback seed \
        set-admin-password db-shell db-dump db-restore dev dev-api dev-web dev-ml \
        test test-unit lint format typecheck build clean clean-all shell ps \
        ci-compose-validate

# Default target
help:
	@echo "GeoSentinel-NER - Available Commands:"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make up              Start all services (docker compose)"
	@echo "  make up-kafka        Start with Kafka profile"
	@echo "  make up-full         Start with all profiles (kafka, geoserver)"
	@echo "  make down            Stop all services"
	@echo "  make logs            Follow logs for all services"
	@echo "  make logs SERVICE=x  Follow logs for specific service"
	@echo "  make restart         Restart all services"
	@echo "  make restart SERVICE=x Restart specific service"
	@echo ""
	@echo "Database:"
	@echo "  make migrate         Run database migrations"
	@echo "  make seed            Seed reference data"
	@echo "  make db-shell        Open psql shell"
	@echo "  make db-dump         Dump database to file"
	@echo "  make db-restore FILE=x Restore database from file"
	@echo "  make set-admin-password Set the admin user's password securely"
	@echo ""
	@echo "Development:"
	@echo "  make dev             Print per-service dev commands"
	@echo "  make dev-api         Start API gateway only"
	@echo "  make dev-web         Start web dashboard only"
	@echo "  make dev-ml          Start ML engine only"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test            Run all Python tests (root pytest suite)"
	@echo "  make lint            Run linters (ruff, eslint)"
	@echo "  make format          Auto-format code (ruff)"
	@echo "  make typecheck       Run frontend type checking (tsc)"
	@echo ""
	@echo "Build & Utilities:"
	@echo "  make build           Build all Docker images"
	@echo "  make ps              Show running containers"
	@echo "  make shell SERVICE=x Open shell in running container"
	@echo "  make clean           Remove containers + volumes"
	@echo "  make clean-all       Nuclear clean (incl. images + caches)"

# -----------------------------------------------------------------------------
# Infrastructure
# -----------------------------------------------------------------------------
up:
	$(COMPOSE) up -d

up-kafka:
	$(COMPOSE) --profile kafka up -d

up-full:
	$(COMPOSE) --profile kafka --profile geoserver up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f $(if $(SERVICE),$(SERVICE),)

restart:
	$(COMPOSE) restart $(if $(SERVICE),$(SERVICE),)

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
migrate:
	@echo "Running migrations on primary DB..."
	$(COMPOSE) exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -f /docker-entrypoint-initdb.d/001_init_extensions.sql
	$(COMPOSE) exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -f /docker-entrypoint-initdb.d/002_create_tables.sql
	$(COMPOSE) exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -f /docker-entrypoint-initdb.d/003_create_indexes.sql
	@echo "Running migrations on TimescaleDB..."
	$(COMPOSE) exec -T timescaledb psql -U $(POSTGRES_USER) -d $(TIMESCALE_DB) -f /docker-entrypoint-initdb.d/001_init_extensions.sql
	$(COMPOSE) exec -T timescaledb psql -U $(POSTGRES_USER) -d $(TIMESCALE_DB) -f /docker-entrypoint-initdb.d/004_timescale_hypertables.sql

migrate-rollback:
	@echo "Rollback not implemented - use manual SQL"

seed:
	@echo "Seeding reference data..."
	$(COMPOSE) exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -f /docker-entrypoint-initdb.d/010_seed_reference_data.sql

set-admin-password:
	@echo "Setting admin password (prompts securely)..."
	$(COMPOSE) exec api-gateway python /app/scripts/set_admin_password.py --username admin

db-shell:
	$(COMPOSE) exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

db-dump:
	$(COMPOSE) exec -T postgres pg_dump -U $(POSTGRES_USER) $(POSTGRES_DB) > backup_$$(date +%Y%m%d_%H%M%S).sql

db-restore:
	@if [ -z "$(FILE)" ]; then echo "Usage: make db-restore FILE=backup.sql"; exit 1; fi
	$(COMPOSE) exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) < $(FILE)

# -----------------------------------------------------------------------------
# Development
# -----------------------------------------------------------------------------
dev:
	@echo "Starting development servers..."
	@echo "Run each service in a separate terminal (or use 'make up' for Docker):"
	@echo "  cd services/api-gateway && poetry run uvicorn main:app --reload --port 8000"
	@echo "  cd services/data-ingestion && poetry run uvicorn main:app --reload --port 8001"
	@echo "  cd services/ml-engine && poetry run uvicorn main:app --reload --port 8002"
	@echo "  cd services/alert-engine && poetry run uvicorn main:app --reload --port 8003"
	@echo "  cd services/gis-service && poetry run uvicorn main:app --reload --port 8004"
	@echo "  cd services/report-service && poetry run uvicorn main:app --reload --port 8005"
	@echo "  cd services/notification-service && poetry run uvicorn main:app --reload --port 8006"
	@echo "  cd apps/web-dashboard && npm run dev"

dev-api:
	cd services/api-gateway && poetry run uvicorn main:app --reload --port 8000

dev-web:
	cd apps/web-dashboard && npm run dev

dev-ml:
	cd services/ml-engine && poetry run uvicorn main:app --reload --port 8002

# -----------------------------------------------------------------------------
# Testing & Quality
# -----------------------------------------------------------------------------
test:
	@echo "Running all tests..."
	.venv/Scripts/python -m pytest || python -m pytest

lint:
	@echo "Running linters..."
	ruff check . || .venv/Scripts/python -m ruff check .
	cd apps/web-dashboard && npm run lint

format:
	@echo "Formatting code..."
	ruff check --fix . ; ruff format . || .venv/Scripts/python -m ruff format .

typecheck:
	cd apps/web-dashboard && npm run typecheck

ci-compose-validate:
	@echo "Validating docker-compose.yml..."
	test -f .env || cp .env.example .env
	$(COMPOSE) config --quiet

# -----------------------------------------------------------------------------
# Build & Utilities
# -----------------------------------------------------------------------------
build:
	$(COMPOSE) build

clean:
	$(COMPOSE) down -v --remove-orphans

clean-all:
	$(COMPOSE) down -v --remove-orphans
	rm -rf services/*/__pycache__ services/*/.pytest_cache services/*/.ruff_cache
	rm -rf packages/geosentinel-shared/geosentinel_shared/__pycache__
	rm -rf apps/web-dashboard/node_modules apps/web-dashboard/dist

shell:
	@if [ -z "$(SERVICE)" ]; then echo "Usage: make shell SERVICE=api-gateway"; exit 1; fi
	$(COMPOSE) exec $(SERVICE) /bin/sh

ps:
	$(COMPOSE) ps
