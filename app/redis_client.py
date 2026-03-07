"""
Shared Redis client.

We use a single async Redis connection pool across the app for:
- Message deduplication (idMessage → seen)
- Rate limiting (per-tenant sliding window)
- ARQ job queue (via arq's own connection)
- Future: session cache
"""

from redis.asyncio import Redis

from app.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
