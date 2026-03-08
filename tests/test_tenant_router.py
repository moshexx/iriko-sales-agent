"""
Integration tests for tenant routing (app/services/tenant_router.py).

These use a REAL Postgres container (via testcontainers in conftest.py).
Why real DB here and not mocks?
  - Tenant routing uses SQLAlchemy queries with real filters (.where()).
  - Mocking the DB would just test our mocks, not the actual SQL.
  - With testcontainers, we test against a real Postgres — same engine as production.

Each test gets a fresh transaction (rolled back after) so tests don't interfere.
"""


import pytest

from app.services.tenant_router import TenantNotFoundError, get_tenant_by_instance_id


class TestGetTenantByInstanceId:
    async def test_returns_tenant_and_channel(self, db_session, make_tenant):
        tenant, channel = await make_tenant(instance_id="9990001")

        found_tenant, found_channel = await get_tenant_by_instance_id("9990001", db_session)

        assert found_tenant.id == tenant.id
        assert found_tenant.slug == tenant.slug
        assert found_channel.instance_id == "9990001"

    async def test_unknown_instance_id_raises(self, db_session):
        with pytest.raises(TenantNotFoundError, match="No active channel found"):
            await get_tenant_by_instance_id("does-not-exist", db_session)

    async def test_inactive_channel_is_not_returned(self, db_session, make_tenant):
        """A deactivated channel (is_active=False) must not be routable."""
        await make_tenant(instance_id="9990002", channel_active=False)

        with pytest.raises(TenantNotFoundError):
            await get_tenant_by_instance_id("9990002", db_session)

    async def test_inactive_tenant_is_not_returned(self, db_session, make_tenant):
        """Even if channel is active, an inactive tenant must be rejected."""
        await make_tenant(instance_id="9990003", is_active=False, channel_active=True)

        with pytest.raises(TenantNotFoundError):
            await get_tenant_by_instance_id("9990003", db_session)

    async def test_multiple_tenants_are_isolated(self, db_session, make_tenant):
        """
        Two tenants with different instance_ids must never be mixed up.
        This is the core multi-tenancy isolation test.
        """
        tenant_a, channel_a = await make_tenant(
            instance_id="9990004", slug="tenant-a", graph_type="iroko"
        )
        tenant_b, channel_b = await make_tenant(
            instance_id="9990005", slug="tenant-b", graph_type="dng"
        )

        found_a, _ = await get_tenant_by_instance_id("9990004", db_session)
        found_b, _ = await get_tenant_by_instance_id("9990005", db_session)

        assert found_a.id == tenant_a.id
        assert found_a.graph_type == "iroko"

        assert found_b.id == tenant_b.id
        assert found_b.graph_type == "dng"

        # The critical check: no cross-tenant leak
        assert found_a.id != found_b.id
