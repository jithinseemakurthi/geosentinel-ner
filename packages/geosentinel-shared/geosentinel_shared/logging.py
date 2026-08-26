"""
GeoSentinel-NER Shared Logging Module
"""
import logging
import sys
from typing import Any

import structlog

from . import config


def configure_logging() -> None:
    """Configure structured logging for the application."""
    settings = config.settings

    # Standard library logging config
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper()),
        format="%(message)s",
        stream=sys.stdout,
    )

    # Structlog configuration
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if settings.APP_ENV == "production"
            else structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library loggers to use structlog
    for name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "sqlalchemy", "asyncpg"]:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


class LoggerMixin:
    @property
    def logger(self) -> structlog.stdlib.BoundLogger:
        if not hasattr(self, "_logger"):
            self._logger = get_logger(self.__class__.__module__)
        return self._logger


def log_request_response(logger: structlog.stdlib.BoundLogger) -> Any:
    """Middleware-style request/response logging."""
    async def middleware(request, call_next):
        import time
        start_time = time.time()

        # Log request
        logger.info(
            "http_request_started",
            method=request.method,
            url=str(request.url),
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                "http_request_completed",
                method=request.method,
                url=str(request.url),
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
            return response
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.exception(
                "http_request_failed",
                method=request.method,
                url=str(request.url),
                duration_ms=round(duration_ms, 2),
                error=str(e),
            )
            raise

    return middleware
