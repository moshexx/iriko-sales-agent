import logging

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Request
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.services.ingress import handle_webhook

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])

# Shared ARQ pool — initialized lazily on first webhook
_arq_pool = None


async def get_arq():
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _arq_pool


@router.post("/greenapi/{instance_id}")
async def greenapi_webhook(
    instance_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ORJSONResponse:
    """
    Receives all events from Green API for a specific instance (phone number).

    Green API expects a 200 response quickly. We parse, filter, dedup,
    then dispatch to the ARQ background worker and return immediately.
    """
    try:
        payload = await request.json()
    except Exception:
        return ORJSONResponse({"accepted": False, "reason": "invalid_json"}, status_code=400)

    arq = await get_arq()
    result = await handle_webhook(instance_id, payload, db, arq)

    return ORJSONResponse({"accepted": result.accepted, "reason": result.reason})
