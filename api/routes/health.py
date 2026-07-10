"""api/routes/health.py — liveness and readiness probes."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict:
    """Kubernetes liveness probe — returns 200 if the process is alive."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_db_session)) -> dict:
    """
    Readiness probe — returns 200 only if the database is reachable.
    FastAPI will return 500 if the DB query raises an exception.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "connected"}