"""
db/models/dataset.py
─────────────────────
ORM models for dataset_records, evaluation_runs, and evaluation_results.

Paper connection (§IV — Dataset Creation, §V — Experiments):
  These tables implement the paper's dataset hierarchy:
    𝒯𝒫  (Test Point)  → DatasetRecord.prompt_text
    𝒯𝒸  (Test Case)   → DatasetRecord (prompt + reference output)
    𝒯𝓈  (Test Suite)  → grouped by scenario_tag
    𝒟   (Dataset)     → all DatasetRecord rows

  The paper's two evaluation metrics (Table II):
    - Correctness Rate     → EvaluationResult.command_correct
    - Reason Plausibility  → EvaluationResult.reason_plausibility

  EvaluationRun stores aggregated scores matching Table II format,
  distinguishing SOP tasks from unexpected tasks (paper §V.C).

Note: The DatasetRecorder (Phase 6) populates dataset_records automatically
  during normal operation by mirroring rows from llm_inference_log.
"""

import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DatasetRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    One test case: 𝒯𝒸 = (𝒯𝒫, 𝒪*ℓℓ𝓂)

    Populated by the DatasetRecorder (Phase 6) from llm_inference_log rows,
    or manually authored for edge-case scenarios.
    """
    __tablename__ = "dataset_records"

    # Source inference (null for manually authored records)
    inference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_inference_log.id", ondelete="SET NULL"),
        nullable=True,
    )

    # The full prompt text — this IS the test point (𝒯𝒫)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)

    # The reference (ground truth) output: {"reason": "...", "command": "fn()"}
    reference_output: Mapped[str] = mapped_column(Text, nullable=False)

    # Paper §V.C distinguishes SOP vs unexpected tasks
    is_sop_task: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Groups records into test suites (𝒯𝓈) by scenario name
    scenario_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Short description for human review e.g. "conveyor_start", "holder_release"
    task_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    evaluation_results: Mapped[list["EvaluationResult"]] = relationship(
        "EvaluationResult",
        back_populates="dataset_record",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return (
            f"<DatasetRecord id={self.id} sop={self.is_sop_task} "
            f"tag={self.scenario_tag!r}>"
        )


class EvaluationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    One evaluation run aggregating scores across N test cases.
    Matches the row structure of Table II in the paper.
    """
    __tablename__ = "evaluation_runs"

    run_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # The model evaluated in this run
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)

    total_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sop_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unexpected_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Paper Table II metrics
    correctness_rate_all: Mapped[float | None] = mapped_column(Float, nullable=True)
    correctness_rate_sop: Mapped[float | None] = mapped_column(Float, nullable=True)
    correctness_rate_unexpected: Mapped[float | None] = mapped_column(Float, nullable=True)

    avg_reason_plausibility_all: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_reason_plausibility_sop: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_reason_plausibility_unexpected: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    results: Mapped[list["EvaluationResult"]] = relationship(
        "EvaluationResult",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return (
            f"<EvaluationRun id={self.id} model={self.model_name!r} "
            f"correctness={self.correctness_rate_all}>"
        )


class EvaluationResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One scored test case within an EvaluationRun."""
    __tablename__ = "evaluation_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    dataset_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_records.id", ondelete="CASCADE"),
        nullable=False,
    )

    # What the model actually generated in this run
    generated_output: Mapped[str] = mapped_column(Text, nullable=False)

    # Paper metric 1: exact match on function call string
    command_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Paper metric 2: Likert scale 1–5 (human or LLM-as-judge)
    reason_plausibility: Mapped[float | None] = mapped_column(Float, nullable=True)

    evaluator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    run: Mapped["EvaluationRun"] = relationship(
        "EvaluationRun", back_populates="results", lazy="raise"
    )
    dataset_record: Mapped["DatasetRecord"] = relationship(
        "DatasetRecord", back_populates="evaluation_results", lazy="raise"
    )