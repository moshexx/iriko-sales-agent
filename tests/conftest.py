"""
Shared pytest fixtures for all tests.

Key concepts used here:

1. testcontainers — spins up a real Postgres Docker container for integration tests.
   This is better than SQLite because we use Postgres-specific features (UUID, JSON).
   The container starts once per test session and is shared across all tests.

2. fakeredis — an in-memory Redis implementation for unit tests.
   No Docker needed. Perfect for testing dedup logic without side effects.

3. AsyncMock — for mocking ARQ (the job queue). We don't want to actually
   enqueue jobs during tests — we just want to assert they *would have been* enqueued.

4. pytest-asyncio — allows async test functions. All our service code is async.
"""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.message import Message  # ensure model is registered for table creation
from app.models.tenant import Tenant, TenantChannel  # ensure models are registered


# ─── Postgres (testcontainers) ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def postgres_url():
    """
    Start a real Postgres container for the test session.
    'scope=session' means it starts once and is reused by all tests — much faster.
    """
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        # testcontainers gives us a sync URL; we need the async variant
        url = pg.get_connection_url().replace("psycopg2", "asyncpg").replace("postgresql", "postgresql+asyncpg")
        yield url


@pytest_asyncio.fixture(scope="session")
async def db_engine(postgres_url):
    """Create the async engine and all tables once per session."""
    engine = create_async_engine(postgres_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a fresh DB session per test, wrapped in a transaction that is
    rolled back after each test. This keeps tests isolated without dropping tables.
    """
    async with db_engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with session_factory() as session:
            yield session
        await conn.rollback()


# ─── Redis (fakeredis) ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def fake_redis():
    """
    In-memory Redis for unit tests.
    fakeredis implements the full Redis API without a real server.
    """
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.flushall()
    await redis.aclose()


# ─── ARQ (mock) ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_arq():
    """
    Mock ARQ pool. Records enqueue_job calls without actually queuing anything.
    In tests: await mock_arq.enqueue_job.assert_called_once_with("process_message", ...)
    """
    arq = AsyncMock()
    arq.enqueue_job = AsyncMock()
    return arq


# ─── Tenant factory ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def make_tenant(db_session: AsyncSession):
    """
    Factory fixture: creates a Tenant + TenantChannel in the DB.
    Usage: tenant, channel = await make_tenant(instance_id="1234567")
    """
    async def _make(
        instance_id: str = "1234567",
        slug: str = "test-tenant",
        graph_type: str = "iroko",
        is_active: bool = True,
        channel_active: bool = True,
    ) -> tuple[Tenant, TenantChannel]:
        import uuid
        tenant = Tenant(
            id=uuid.uuid4(),
            slug=slug,
            name="Test Tenant",
            graph_type=graph_type,
            is_active=is_active,
        )
        db_session.add(tenant)
        await db_session.flush()  # get the ID without committing

        channel = TenantChannel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            instance_id=instance_id,
            token_ref="test-token-ref",
            is_active=channel_active,
        )
        db_session.add(channel)
        await db_session.flush()

        return tenant, channel

    return _make
