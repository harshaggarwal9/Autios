"""
db/base.py
──────────
SQLAlchemy declarative base shared by all ORM models.

Design rationale:
  A single Base ensures Alembic's autogenerate can discover every table by
  importing this module.  All ORM models must inherit from Base — never
  define a second Base elsewhere.

  We also attach two reusable column mixins (UUIDPrimaryKeyMixin,
  TimestampMixin) so every table gets consistent primary key and audit
  column definitions without boilerplate.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ── Reusable column mixins ────────────────────────────────────────────────────

class UUIDPrimaryKeyMixin:
    """
    Adds a server-generated UUID primary key column named 'id'.

    Using UUID (not SERIAL) as the PK because:
    - Records are often created by the application layer before a DB round-trip
    - UUIDs are safe to generate distributed (multiple agent processes)
    - The event_log table uses a separate BIGSERIAL sequence_id for ordering;
      other tables only need a stable identity key
    """
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    """Adds created_at and updated_at audit columns to any model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )