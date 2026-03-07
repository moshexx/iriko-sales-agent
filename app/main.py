from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from app.db import engine
    from app.models.base import Base

    async with engine.begin() as conn:
        # In production, Alembic handles migrations. This is dev-only auto-create.
        if not settings.is_production:
            await conn.run_sync(Base.metadata.create_all)

    yield

    # Shutdown
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
