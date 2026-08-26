"""
GeoSentinel-NER Shared Package
"""
from .auth import (
    TokenPayload,
    check_permission,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    verify_token,
)
from .config import get_settings
from .database import (
    DatabaseManager,
    close_db,
    get_db_session,
    get_primary_db,
    get_timescale_db,
    get_ts_session,
    init_db,
)
from .logging import LoggerMixin, configure_logging, get_logger, log_request_response
from .schemas import *  # noqa: F401,F403

__all__ = [
    "settings",  # noqa: F405  (provided lazily via PEP 562 __getattr__)
    "get_settings",
    "DatabaseManager",
    "get_primary_db",
    "get_timescale_db",
    "init_db",
    "close_db",
    "get_db_session",
    "get_ts_session",
    "configure_logging",
    "get_logger",
    "LoggerMixin",
    "log_request_response",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "verify_token",
    "check_permission",
    "TokenPayload",
]


def __getattr__(name: str):  # noqa: F405
    """Lazily expose `settings` (PEP 562) so importing this package does not
    require a fully populated environment until settings are actually used."""
    if name == "settings":
        from .config import settings
        return settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
