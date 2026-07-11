






















import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DatasetRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    





    __tablename__ = "dataset_records"


    inference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_inference_log.id", ondelete="SET NULL"),
        nullable=True,
    )


    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)


    reference_output: Mapped[str] = mapped_column(Text, nullable=False)


    is_sop_task: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


    scenario_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)


    task_type: Mapped[str | None] = mapped_column(String(128), nullable=True)


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
    



    __tablename__ = "evaluation_runs"

    run_name: Mapped[str] = mapped_column(String(128), nullable=False)


    model_name: Mapped[str] = mapped_column(String(64), nullable=False)

    total_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sop_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unexpected_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


    correctness_rate_all: Mapped[float | None] = mapped_column(Float, nullable=True)
    correctness_rate_sop: Mapped[float | None] = mapped_column(Float, nullable=True)
    correctness_rate_unexpected: Mapped[float | None] = mapped_column(Float, nullable=True)

    avg_reason_plausibility_all: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_reason_plausibility_sop: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_reason_plausibility_unexpected: Mapped[float | None] = mapped_column(Float, nullable=True)


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


    generated_output: Mapped[str] = mapped_column(Text, nullable=False)


    command_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


    reason_plausibility: Mapped[float | None] = mapped_column(Float, nullable=True)

    evaluator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


    run: Mapped["EvaluationRun"] = relationship(
        "EvaluationRun", back_populates="results", lazy="raise"
    )
    dataset_record: Mapped["DatasetRecord"] = relationship(
        "DatasetRecord", back_populates="evaluation_results", lazy="raise"
    )
