"""
db/models/task.py
─────────────────
ORM models for the tasks and task_assignments tables.

Paper connection (§III.A — Manager Agent):
  The Manager agent receives a user command, builds a production plan, and
  "assigns subtasks to operator agents through the event log." This table
  persists both the top-level task and its ordered subtask assignments so we
  can track execution status and provide the /tasks/{id} status endpoint.

  The paper's Figure 4 shows the manager posting task assignments as events
  into the shared event log. The Task and TaskAssignment rows here are the
  relational backing store; the actual communication still flows through the
  event_log table (the manager emits a "[MES][Manager] task assigned" event
  which operator agents subscribe to).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    # Human-readable title, e.g. "Inspect workpiece and load onto transport robot"
    title: Mapped[str] = mapped_column(String(256), nullable=False)

    # Full natural-language description as received from the user
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # UUID of the Manager agent that created this task (nullable for seeded tasks)
    assigned_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status_enum"),
        default=TaskStatus.PENDING,
        nullable=False,
    )

    # The structured production plan the Manager agent generated (JSONB).
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Populated when the task reaches COMPLETED or FAILED
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    # FIX: use the string "TaskAssignment.sequence_order" instead of a lambda
    # referencing the not-yet-defined TaskAssignment class. SQLAlchemy resolves
    # string-based order_by at mapper configuration time, after all classes
    # in the module have been defined.
    assignments: Mapped[list["TaskAssignment"]] = relationship(
        "TaskAssignment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskAssignment.sequence_order",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r} status={self.status.value}>"


class TaskAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    One subtask assigned by the Manager to a specific Operator agent.

    The manager posts a corresponding event into the event_log after creating
    this row, so the operator agent's subscription triggers on the event,
    not by polling this table.
    """
    __tablename__ = "task_assignments"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    assigned_to_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )

    subtask_description: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status_enum"),
        default=TaskStatus.PENDING,
        nullable=False,
    )

    # Ordering within the parent task's plan
    sequence_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    task: Mapped["Task"] = relationship(
        "Task", back_populates="assignments", lazy="raise"
    )

    def __repr__(self) -> str:
        return (
            f"<TaskAssignment id={self.id} task_id={self.task_id} "
            f"status={self.status.value}>"
        )