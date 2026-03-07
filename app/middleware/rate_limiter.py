"""
Per-tenant rate limiter — Redis sliding window algorithm.

How it works:
  We use a Redis sorted set (ZSET) per tenant as a sliding window.
  Key:   rate:{tenant_id}
  Score: Unix timestamp (float)
  Value: unique message ID

  On each request:
  1. Remove entries older than (now - window_seconds)
  2. Count remaining entries
  3. If count >= limit → reject with RateLimitedError
  4. Otherwise → add current timestamp + return allowed

Why sliding window instead of fixed window?
  Fixed window (e.g. "60 messages per minute") resets at :00 and :60.
  This allows a burst of 120 messages in 2 seconds (59 at end of minute 1,
  61 at start of minute 2). Sliding window prevents this.

Usage:
    from app.middleware.rate_limiter import check_rate_limit, RateLimitedError
    try:
        await check_rate_limit(tenant_id, redis, limit_rpm=60)
    except RateLimitedError:
        return IngressResult(accepted=False, reason="rate_limited")
"""

from __future__ import annotations

import time
import uuid


class RateLimitedError(Exception):
    """Raised when a tenant exceeds their configured message rate limit."""
    pass


async def check_rate_limit(
    tenant_id: str,
    redis,
    limit_rpm: int = 60,
    window_seconds: int = 60,
) -> None:
    """
    Check if the tenant is within their rate limit. Raises RateLimitedError if not.

    This function is a write operation — it records the current message in the
    sliding window. Call it exactly once per accepted message, after tenant lookup.

    Args:
        tenant_id:      The tenant's UUID string.
        redis:          An aioredis / fakeredis client.
        limit_rpm:      Max messages per window (from tenant config).
        window_seconds: Window size in seconds (default: 60 for RPM).

    Raises:
        RateLimitedError: if the tenant has exceeded their limit.
    """
    key = f"rate:{tenant_id}"
    now = time.time()
    window_start = now - window_seconds

    # Pipeline: atomic read-then-write to avoid race conditions
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, "-inf", window_start)   # remove expired entries
    pipe.zcard(key)                                      # count current entries
    pipe.zadd(key, {str(uuid.uuid4()): now})             # add this message
    pipe.expire(key, window_seconds + 1)                 # auto-cleanup

    results = await pipe.execute()
    current_count = results[1]  # count before adding this message

    if current_count >= limit_rpm:
        # Remove the entry we just added — the message is rejected
        await redis.zremrangebyscore(key, now, now)
        raise RateLimitedError(
            f"Tenant {tenant_id} rate limited: {current_count}/{limit_rpm} rpm"
        )


async def get_current_rate(
    tenant_id: str,
    redis,
    window_seconds: int = 60,
) -> int:
    """
    Return the current message count in the sliding window (read-only).

    Used in tests and monitoring — does not add an entry.
    """
    key = f"rate:{tenant_id}"
    now = time.time()
    window_start = now - window_seconds

    await redis.zremrangebyscore(key, "-inf", window_start)
    return await redis.zcard(key)
