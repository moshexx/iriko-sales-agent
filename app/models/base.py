import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantMixin:
    """
    Add to any model that is scoped to a tenant.
    All queries MUST filter by tenant_id — enforced at the service layer.
    (Production: Postgres RLS will enforce this at the DB layer too.)
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        # clock_timestamp() returns the real wall-clock time at each row insertion,
        # unlike now() which returns the transaction start time (same for all rows
        # in the same transaction). Essential for correct ordering of messages.
        DateTime(timezone=True),
        server_default=text("clock_timestamp()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
