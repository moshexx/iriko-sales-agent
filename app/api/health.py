from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> ORJSONResponse:
    return ORJSONResponse({"status": "ok"})


@router.get("/readyz")
async def readyz() -> ORJSONResponse:
    # TODO Phase 2: check DB, Redis, Qdrant connectivity
    return ORJSONResponse({"status": "ok"})
