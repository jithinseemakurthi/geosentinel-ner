"""
Root test bootstrap.

Makes the shared package and each service's ``app`` package importable from
the repository root so tests can run with plain ``pytest`` (no Poetry install
per service), and supplies safe defaults for required Settings.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault(
    "SECRET_KEY",
    "unit-test-secret-key-0123456789abcdef-unit-test-secret-key",
)
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "postgresql://geosentinel:test@localhost:5432/geosentinel")
os.environ.setdefault("TIMESCALE_URL", "postgresql://geosentinel:test@localhost:5433/geosentinel_ts")

sys.path.insert(0, str(ROOT / "packages" / "geosentinel-shared"))
for service_dir in sorted((ROOT / "services").glob("*/app")):
    sys.path.insert(0, str(service_dir))


def load_service_module(alias: str, relative_main: str):
    """Import a service ``main.py`` under a unique module name.

    Service modules are all named ``main``, so a plain import would collide;
    loading by file path keeps every service independently importable.
    """
    import importlib.util

    main_path = ROOT / relative_main
    spec = importlib.util.spec_from_file_location(f"geosentinel_{alias}_main", main_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
