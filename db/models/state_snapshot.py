














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



    state: Mapped[dict] = mapped_column(JSONB, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
