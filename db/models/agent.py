"""
db/models/agent.py
──────────────────
ORM models for the agents and agent_subscriptions tables.

Paper connection (§III.B — LLM Agent 𝒜ℳi):
  Each row in `agents` represents one agent instance. last_event_sequence
  is the paper's implied cursor — the highest sequence_id the agent has
  already processed, persisted for crash recovery.

  AgentSubscription implements the paper's subscription set:
    ℰ_AMi = 𝒮(AMi) ⊆ ℰ
"""

import enum
import uuid

from sqlalchemy import BigInteger, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentType(str, enum.Enum):
    """
    The three agent roles from §II.C of the paper.
    Using str-enum means the stored DB value is a readable string.
    """
    MANAGER = "MANAGER"
    OPERATOR = "OPERATOR"
    SUMMARIZATION = "SUMMARIZATION"


class AgentStatus(str, enum.Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    # Stable string identifier used in log messages and API routes.
    # Convention: "{module_id}_operator" / "manager" / "summarization"
    agent_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )

    agent_type: Mapped[AgentType] = mapped_column(
        Enum(AgentType, name="agent_type_enum"),
        nullable=False,
    )

    # FK to automation_modules.
    # Null for Manager and Summarization agents.
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "automation_modules.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # Event cursor
    last_event_sequence: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
    )

    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status_enum"),
        default=AgentStatus.IDLE,
        server_default="IDLE",
        nullable=False,
    )

    # Relationships
    module: Mapped["AutomationModule | None"] = relationship(
        "AutomationModule",
        back_populates="agents",
        lazy="raise",
    )

    subscriptions: Mapped[list["AgentSubscription"]] = relationship(
        "AgentSubscription",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return (
            f"<Agent "
            f"id={self.id} "
            f"agent_id={self.agent_id!r} "
            f"type={self.agent_type.value} "
            f"status={self.status.value}>"
        )


class AgentSubscription(UUIDPrimaryKeyMixin, Base):
    """
    One subscription row = one event scope an agent listens to.

    Paper formalism:
      𝒮(𝒜ℳi) ⊆ ℰ
    """

    __tablename__ = "agent_subscriptions"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "agents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    # Scope label as it appears in event_log.scope
    event_scope: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    # Optional source filter
    event_source: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    agent: Mapped["Agent"] = relationship(
        "Agent",
        back_populates="subscriptions",
        lazy="raise",
    )