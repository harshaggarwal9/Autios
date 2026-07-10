"""
db/models/inference_log.py
──────────────────────────
ORM models for llm_inference_log and agent_command_log.

Paper connection (§III.B — LLM Output 𝒪ℓℓ𝓂, §IV — Dataset Creation):
  Every prompt sent to the LLM and every response received is stored in
  llm_inference_log. This table is the raw material for the DatasetRecorder
  (Phase 6) — it captures 𝒯𝒫 (the prompt = test point) and 𝒪ℓℓ𝓂 (the output)
  automatically during normal operation.

  agent_command_log records the result of dispatching each function call to
  the CommandInterface (Phase 5). Separation matters: an inference can produce
  valid JSON but the command dispatch can still fail (e.g. emergency stop active).
"""

import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CommandOutcome(str, enum.Enum):
    SUCCESS = "success"
    PARSE_ERROR = "parse_error"           # OutputParser could not parse LLM JSON
    UNKNOWN_FUNCTION = "unknown_function"  # function_name not in FunctionRegistry
    INVALID_PARAMS = "invalid_params"     # params failed validation
    EXECUTION_ERROR = "execution_error"   # mock/real hardware raised an exception
    EMERGENCY_BLOCKED = "emergency_blocked"  # module in emergency stop state


class LLMInferenceLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_inference_log"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Optional FK to the task that triggered this inference
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # The full assembled prompt text (all five sections + event log slice).
    # Stored verbatim so the DatasetRecorder can export it as a test point.
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Raw LLM response text before parsing
    response_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Extracted fields for quick querying (avoid parsing JSON on every query)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    function_call_text: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Which model produced this response (supports future model comparison)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # Token and latency metrics for cost analysis
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

    # FK to the inference that produced this command
    inference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_inference_log.id", ondelete="CASCADE"),
        nullable=False,
    )

    function_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Parsed parameters as JSONB, e.g. {"direction": "forward", "time": 13}
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