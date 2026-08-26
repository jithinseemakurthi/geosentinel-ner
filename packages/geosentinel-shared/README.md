# geosentinel-shared

Shared library used by every GeoSentinel-NER Python service.

Provides:
- `geosentinel_shared.config.settings` — typed environment configuration
- `geosentinel_shared.auth` — JWT issuing/verifying, password hashing, RBAC
- `geosentinel_shared.database` — async SQLAlchemy engine + session factories
- `geosentinel_shared.logging` — structlog setup
- `geosentinel_shared.schemas` — Pydantic request/response models

## Install (in a service)

In each service's `pyproject.toml` add:

```toml
geosentinel-shared = {path = "../../packages/geosentinel-shared"}
```

Then `poetry install`.
