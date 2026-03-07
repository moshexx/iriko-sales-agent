import logging

import sqlalchemy
from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> ORJSONResponse:
    """Liveness — always returns 200 if the process is alive."""
    return ORJSONResponse({"status": "ok"})


@router.get("/readyz")
async def readyz() -> ORJSONResponse:
    """
    Readiness — checks that all dependencies are reachable.
    Returns 200 only when the app is ready to serve traffic.
    Used by Docker Compose / Kubernetes to gate traffic.
    """
    checks: dict[str, str] = {}
    ok = True

    # Check Postgres
    try:
        from app.db import engine
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        logger.warning("Postgres readyz check failed: %s", exc)
        checks["postgres"] = "error"
        ok = False

    # Check Redis
    try:
        from app.redis_client import get_redis
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("Redis readyz check failed: %s", exc)
        checks["redis"] = "error"
        ok = False

    # Check Qdrant
    try:
        import httpx
        from app.config import settings
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.qdrant_url}/healthz")
            resp.raise_for_status()
        checks["qdrant"] = "ok"
    except Exception as exc:
        logger.warning("Qdrant readyz check failed: %s", exc)
        checks["qdrant"] = "error"
        ok = False

    status_code = 200 if ok else 503
    return ORJSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks},
        status_code=status_code,
    )
