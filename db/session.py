"""
db/session.py
─────────────
Async SQLAlchemy engine and session factory.

Design rationale:
  All database I/O in this project is async (asyncpg driver + SQLAlchemy async
  extension). Mixing sync and async sessions would silently block the event
  loop — this module enforces async-only by exporting only AsyncSession.

  The engine and session factory are created lazily via init_db() called from
  the lifespan handler, NOT at module import time. This allows tests to set
  a different DATABASE_URL before the engine is created.

  get_db_session() is a FastAPI dependency that yields a scoped session and
  automatically rolls back on exception.

Dependencies:
  sqlalchemy[asyncio], asyncpg, config.settings
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Module-level references — populated by init_db() at startup
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(database_url: str, echo: bool = False) -> None:
    """
    Create the async engine and session factory.

    Must be called once during application startup (lifespan handler)
    before any database operations are attempted.
    """
    global _engine, _session_factory

    _engine = create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


def get_engine() -> AsyncEngine:
    """Return the current async engine. Raises if init_db() has not been called."""
    if _engine is None:
        raise RuntimeError("Database engine not initialised. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory. Raises if init_db() has not been called."""
    if _session_factory is None:
        raise RuntimeError("Session factory not initialised. Call init_db() first.")
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a database session per request.

    Usage:
        @router.get("/example")
        async def endpoint(db: AsyncSession = Depends(get_db_session)):
            ...

    Automatically commits on success, rolls back on exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()