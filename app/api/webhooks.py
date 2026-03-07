from fastapi import APIRouter, Request
from fastapi.responses import ORJSONResponse

router = APIRouter(tags=["webhooks"])


@router.post("/greenapi/{instance_id}")
async def greenapi_webhook(instance_id: str, request: Request) -> ORJSONResponse:
    """
    Receives inbound events from Green API.
    Phase 2 will add: tenant lookup, dedup, signature verification, ARQ dispatch.
    """
    payload = await request.json()
    # TODO Phase 2: implement full ingress pipeline
    return ORJSONResponse({"received": True, "instance_id": instance_id})
