from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Observability (must be first) ─────────────────────────────────────────
    from app.observability.logging import setup_logging
    from app.observability.tracing import setup_tracing

    setup_logging()
    setup_tracing(app)  # instruments FastAPI automatically

    # ── DB tables (dev only — prod uses Alembic) ──────────────────────────────
    import app.models.dlq  # noqa: F401 — register DLQEvent for create_all
    import app.models.message  # noqa: F401 — register Message for create_all
    from app.db import engine
    from app.models.base import Base

    async with engine.begin() as conn:
        if not settings.is_production:
            await conn.run_sync(Base.metadata.create_all)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    from app.redis_client import close_redis
    await close_redis()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="LeadWise Sales Agent",
        description="Multi-tenant AI sales agent platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    from app.api.health import router as health_router
    from app.api.webhooks import router as webhooks_router

    app.include_router(health_router)
    app.include_router(webhooks_router, prefix="/webhooks")

    return app


app = create_app()
