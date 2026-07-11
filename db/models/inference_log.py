















import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CommandOutcome(str, enum.Enum):
    SUCCESS = "success"
    PARSE_ERROR = "parse_error"
    UNKNOWN_FUNCTION = "unknown_function"
    INVALID_PARAMS = "invalid_params"
    EXECUTION_ERROR = "execution_error"
    EMERGENCY_BLOCKED = "emergency_blocked"


class LLMInferenceLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_inference_log"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )


    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )



    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)


    response_text: Mapped[str] = mapped_column(Text, nullable=False)


    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    function_call_text: Mapped[str | None] = mapped_column(String(256), nullable=True)


    model_name: Mapped[str] = mapped_column(String(64), nullable=False)


    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<LLMInferenceLog id={self.id} agent_id={self.agent_id} "
            f"fn={self.function_call_text!r}>"
        )


class AgentCommandLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_command_log"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )


    inference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_inference_log.id", ondelete="CASCADE"),
        nullable=False,
    )

    function_name: Mapped[str] = mapped_column(String(128), nullable=False)


    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    outcome: Mapped[CommandOutcome] = mapped_column(
        Enum(CommandOutcome, name="command_outcome_enum"),
        nullable=False,
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AgentCommandLog id={self.id} fn={self.function_name!r} "
            f"outcome={self.outcome.value}>"
        )
