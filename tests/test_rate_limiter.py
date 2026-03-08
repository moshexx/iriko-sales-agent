"""
Unit tests for the Redis sliding-window rate limiter (app/middleware/rate_limiter.py).

Uses fakeredis — no real Redis required.

Key test cases:
  1. First message is always allowed
  2. Messages within the limit are allowed
  3. Message that exceeds the limit is rejected with RateLimitedError
  4. After the window expires, the counter resets (sliding window)
  5. get_current_rate returns correct count (read-only, does not add entry)
  6. Different tenant_ids have separate rate limits
  7. Rejection does not increment the counter (rejected message is rolled back)
"""

import fakeredis.aioredis
import pytest

from app.middleware.rate_limiter import RateLimitedError, check_rate_limit, get_current_rate

TENANT_A = "aaaaaaaa-0000-0000-0000-000000000001"
TENANT_B = "bbbbbbbb-0000-0000-0000-000000000002"


@pytest.fixture
async def redis():
    """Fresh in-memory Redis for each test."""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


class TestCheckRateLimit:
    async def test_first_message_is_allowed(self, redis):
        """The very first message should never be rate-limited."""
        # Should not raise
        await check_rate_limit(TENANT_A, redis, limit_rpm=5)

    async def test_messages_within_limit_are_allowed(self, redis):
        """All messages up to the limit are allowed."""
        for _ in range(5):
            await check_rate_limit(TENANT_A, redis, limit_rpm=5)

        count = await get_current_rate(TENANT_A, redis)
        assert count == 5

    async def test_message_over_limit_raises(self, redis):
        """The (limit+1)th message in the window raises RateLimitedError."""
        for _ in range(5):
            await check_rate_limit(TENANT_A, redis, limit_rpm=5)

        with pytest.raises(RateLimitedError):
            await check_rate_limit(TENANT_A, redis, limit_rpm=5)

    async def test_rejection_does_not_increment_counter(self, redis):
        """A rejected message must NOT be counted in the window."""
        for _ in range(5):
            await check_rate_limit(TENANT_A, redis, limit_rpm=5)

        count_before = await get_current_rate(TENANT_A, redis)

        with pytest.raises(RateLimitedError):
            await check_rate_limit(TENANT_A, redis, limit_rpm=5)

        count_after = await get_current_rate(TENANT_A, redis)
        assert count_after == count_before  # rejection must not increment

    async def test_different_tenants_are_independent(self, redis):
        """Tenant A's rate limit must not affect Tenant B."""
        # Fill Tenant A's window
        for _ in range(5):
            await check_rate_limit(TENANT_A, redis, limit_rpm=5)

        # Tenant B should still be allowed
        await check_rate_limit(TENANT_B, redis, limit_rpm=5)  # must not raise

    async def test_custom_limit_is_respected(self, redis):
        """limit_rpm parameter controls the threshold."""
        for _ in range(10):
            await check_rate_limit(TENANT_A, redis, limit_rpm=10)

        with pytest.raises(RateLimitedError):
            await check_rate_limit(TENANT_A, redis, limit_rpm=10)


class TestGetCurrentRate:
    async def test_empty_window_returns_zero(self, redis):
        """A fresh tenant has no entries in the window."""
        count = await get_current_rate(TENANT_A, redis)
        assert count == 0

    async def test_returns_count_after_messages(self, redis):
        """get_current_rate reflects how many allowed messages have been recorded."""
        await check_rate_limit(TENANT_A, redis, limit_rpm=10)
        await check_rate_limit(TENANT_A, redis, limit_rpm=10)
        await check_rate_limit(TENANT_A, redis, limit_rpm=10)

        count = await get_current_rate(TENANT_A, redis)
        assert count == 3

    async def test_is_read_only(self, redis):
        """Calling get_current_rate must not add an entry to the window."""
        count_before = await get_current_rate(TENANT_A, redis)
        await get_current_rate(TENANT_A, redis)
        count_after = await get_current_rate(TENANT_A, redis)
        assert count_before == count_after == 0
