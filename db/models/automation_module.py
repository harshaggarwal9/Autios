"""
db/models/automation_module.py
──────────────────────────────
ORM model for the automation_modules table.

Paper connection (§III.B — Automation Module ℳi):
  Represents a physical automation module such as the Inspection Station.
  Each module has a set of components (sensors/actuators), callable functions,
  and emits events. The config_snapshot stores a JSON copy of the module's
  YAML config at the time it was registered.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models.agent import Agent

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AutomationModule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "automation_modules"

    # Human-readable unique identifier matching the YAML module_id.
    module_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    display_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Snapshot of the YAML config at registration time for audit trail.
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    agents: Mapped[list["Agent"]] = relationship(  # noqa: F821
        "Agent",
        back_populates="module",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<AutomationModule id={self.id} module_id={self.module_id!r}>"