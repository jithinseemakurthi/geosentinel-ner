"""
GeoSentinel-NER Shared Database Module
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from . import config


def to_async_url(url: str) -> str:
    """Normalise a Postgres URL for asyncio drivers.

    create_async_engine() requires an explicit +asyncpg dialect. Compose and
    .env files conventionally use plain postgresql:// URLs, so upgrade them
    transparently instead of failing at engine creation.
    """
    if url.startswith("postgresql+asyncpg://") or url.startswith("postgres+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


class DatabaseManager:
    def __init__(self, database_url: str, pool_size: int = 20, max_overflow: int = 10):
        self.engine: AsyncEngine = create_async_engine(
            to_async_url(database_url),
            echo=config.settings.APP_DEBUG,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def close(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_factory() as session:
            async with session.begin():
                yield session


# Global instances
_primary_db: Optional[DatabaseManager] = None
_timescale_db: Optional[DatabaseManager] = None


def get_primary_db() -> DatabaseManager:
    global _primary_db
    if _primary_db is None:
        _primary_db = DatabaseManager(config.settings.DATABASE_URL)
    return _primary_db


def get_timescale_db() -> DatabaseManager:
    global _timescale_db
    if _timescale_db is None:
        _timescale_db = DatabaseManager(config.settings.TIMESCALE_URL)
    return _timescale_db


async def init_db() -> None:
    get_primary_db()
    get_timescale_db()


async def close_db() -> None:
    global _primary_db, _timescale_db
    if _primary_db:
        await _primary_db.close()
        _primary_db = None
    if _timescale_db:
        await _timescale_db.close()
        _timescale_db = None


# Dependency for FastAPI
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_primary_db().session() as session:
        yield session


async def get_ts_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_timescale_db().session() as session:
        yield session
