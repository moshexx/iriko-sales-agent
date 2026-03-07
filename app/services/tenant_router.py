"""
Tenant routing — the entry point of multi-tenancy.

Every inbound webhook carries an instanceId (the Green API instance that received the message).
We use this to look up which tenant owns that number and what their config is.

Why this matters:
  The same server handles all tenants. Without routing, one tenant's message
  could accidentally be processed with another tenant's config. This is the
  single most important isolation point in the system.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant, TenantChannel


class TenantNotFoundError(Exception):
    pass


async def get_tenant_by_instance_id(
    instance_id: str,
    db: AsyncSession,
) -> tuple[Tenant, TenantChannel]:
    """
    Look up the tenant and channel config for a given Green API instance_id.

    Returns (Tenant, TenantChannel) or raises TenantNotFoundError.

    This is called on every inbound webhook — it must be fast.
    TODO Phase 4: add Redis cache with short TTL (30s) to avoid DB hit per message.
    """
    result = await db.execute(
        select(TenantChannel)
        .where(TenantChannel.instance_id == instance_id)
        .where(TenantChannel.is_active == True)  # noqa: E712
    )
    channel = result.scalar_one_or_none()

    if channel is None:
        raise TenantNotFoundError(f"No active channel found for instance_id={instance_id!r}")

    tenant_result = await db.execute(
        select(Tenant)
        .where(Tenant.id == channel.tenant_id)
        .where(Tenant.is_active == True)  # noqa: E712
    )
    tenant = tenant_result.scalar_one_or_none()

    if tenant is None:
        raise TenantNotFoundError(
            f"Tenant {channel.tenant_id} is inactive or missing (instance_id={instance_id!r})"
        )

    return tenant, channel
