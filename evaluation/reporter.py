"""
evaluation/reporter.py
───────────────────────
EvaluationReporter — serialises EvaluationRun results to JSON and CSV.

Paper connection (§V — Experiments, Table II):
  The paper presents results in a table comparing models across SOP and
  unexpected task correctness rates and reason plausibility scores. This
  reporter produces exactly that table as JSON and CSV.

Dependencies:
  db.models.dataset.EvaluationRun, EvaluationResult
  sqlalchemy async, csv/json (stdlib)
"""

import csv
import io
import uuid as _uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.dataset import EvaluationResult, EvaluationRun


class EvaluationReporter:
    """
    Reads EvaluationRun rows from DB and serialises them to JSON/CSV.
    """

    async def export_run_json(
        self,
        db: AsyncSession,
        run_id: str,
        include_cases: bool = True,
    ) -> dict:
        """
        Export one EvaluationRun as a structured JSON dict.

        Args:
            run_id:        UUID string of the EvaluationRun to export.
            include_cases: Whether to include per-case results.

        Returns:
            Dict matching the paper's Table II structure plus metadata.

        Raises:
            ValueError: if run_id does not match any EvaluationRun.
        """
        run_result = await db.execute(
            select(EvaluationRun).where(EvaluationRun.id == _uuid.UUID(run_id))
        )
        run = run_result.scalar_one_or_none()
        if run is None:
            raise ValueError(f"EvaluationRun '{run_id}' not found.")

        output = {
            "run_id": str(run.id),
            "run_name": run.run_name,
            "model_name": run.model_name,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "metrics": {
                "total_cases": run.total_cases,
                "sop_cases": run.sop_cases,
                "unexpected_cases": run.unexpected_cases,
                "correctness_rate": {
                    "all": _pct(run.correctness_rate_all),
                    "sop": _pct(run.correctness_rate_sop),
                    "unexpected": _pct(run.correctness_rate_unexpected),
                },
                "avg_reason_plausibility": {
                    "all": run.avg_reason_plausibility_all,
                    "sop": run.avg_reason_plausibility_sop,
                    "unexpected": run.avg_reason_plausibility_unexpected,
                },
            },
        }

        if include_cases:
            cases_result = await db.execute(
                select(EvaluationResult).where(EvaluationResult.run_id == run.id)
            )
            cases = list(cases_result.scalars().all())
            output["cases"] = [
                {
                    "result_id": str(c.id),
                    "dataset_record_id": str(c.dataset_record_id),
                    "command_correct": c.command_correct,
                    "reason_plausibility": c.reason_plausibility,
                    "generated_output_preview": (
                        c.generated_output[:120] if c.generated_output else None
                    ),
                    "evaluator_notes": c.evaluator_notes,
                }
                for c in cases
            ]

        return output

    async def export_all_runs_csv(self, db: AsyncSession) -> str:
        """
        Export all EvaluationRun rows as CSV — one row per run, matching
        Table II of the paper for direct copy-paste into a spreadsheet or
        LaTeX table.
        """
        runs_result = await db.execute(
            select(EvaluationRun).order_by(EvaluationRun.created_at.asc())
        )
        runs = list(runs_result.scalars().all())

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "run_id", "run_name", "model_name", "created_at",
                "total_cases", "sop_cases", "unexpected_cases",
                "correctness_rate_all_pct", "correctness_rate_sop_pct",
                "correctness_rate_unexpected_pct",
                "avg_plausibility_all", "avg_plausibility_sop",
                "avg_plausibility_unexpected",
            ],
        )
        writer.writeheader()
        for r in runs:
            writer.writerow({
                "run_id": str(r.id),
                "run_name": r.run_name,
                "model_name": r.model_name,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "total_cases": r.total_cases,
                "sop_cases": r.sop_cases,
                "unexpected_cases": r.unexpected_cases,
                "correctness_rate_all_pct": _pct(r.correctness_rate_all),
                "correctness_rate_sop_pct": _pct(r.correctness_rate_sop),
                "correctness_rate_unexpected_pct": _pct(r.correctness_rate_unexpected),
                "avg_plausibility_all": r.avg_reason_plausibility_all or "",
                "avg_plausibility_sop": r.avg_reason_plausibility_sop or "",
                "avg_plausibility_unexpected": r.avg_reason_plausibility_unexpected or "",
            })
        return output.getvalue()

    async def list_runs(self, db: AsyncSession) -> list[dict]:
        """Return a lightweight list of all EvaluationRun summaries."""
        runs_result = await db.execute(
            select(EvaluationRun).order_by(EvaluationRun.created_at.desc())
        )
        runs = list(runs_result.scalars().all())
        return [
            {
                "run_id": str(r.id),
                "run_name": r.run_name,
                "model_name": r.model_name,
                "total_cases": r.total_cases,
                "correctness_rate_all_pct": _pct(r.correctness_rate_all),
                "avg_plausibility_all": r.avg_reason_plausibility_all,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ]


def _pct(value: float | None) -> float | None:
    """Convert a 0-1 rate to a rounded percentage, or return None."""
    if value is None:
        return None
    return round(value * 100, 1)