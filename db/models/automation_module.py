











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


    module_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    display_name: Mapped[str] = mapped_column(String(128), nullable=False)


    config_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


    agents: Mapped[list["Agent"]] = relationship(
        "Agent",
        back_populates="module",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<AutomationModule id={self.id} module_id={self.module_id!r}>"
