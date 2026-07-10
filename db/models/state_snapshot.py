"""
db/models/state_snapshot.py
────────────────────────────
ORM model for module_state_snapshots.

Paper connection (§II.B — Digital Twins):
  The paper's InformationModels maintain a "synchronized digital representation"
  of physical assets. This table persists periodic snapshots of each module's
  state dict so the system can recover to a known state after a restart.

  The DataObserver reads the most recent snapshot on startup to initialize its
  "previous state" tracking — needed to detect state transitions without missing
  events (e.g. BG51 going from False → True).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, UUIDPrimaryKeyMixin


class ModuleStateSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "module_state_snapshots"

    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automation_modules.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Complete state dict for the module at the time of snapshot.
    # Keys are node_ids (BG51, H2, C1_running, etc.), values are their states.
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )