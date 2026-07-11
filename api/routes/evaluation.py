

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session, get_session_factory
from evaluation.engine import EvaluationEngine
from evaluation.reporter import EvaluationReporter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/evaluation", tags=["evaluation"])
_reporter = EvaluationReporter()


class RunEvaluationRequest(BaseModel):
    run_name: str = "default_run"
    scenario_tag: str | None = None
    sop_only: bool | None = None
    max_cases: int | None = None
    score_reasons: bool = True


async def _execute_evaluation(payload: RunEvaluationRequest) -> dict:
    
    try:
        from llm.client import GeminiClient
        llm_client = GeminiClient()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    engine = EvaluationEngine(
        llm_client=llm_client,
        session_factory=get_session_factory(),
    )

    summary = await engine.run_evaluation(
        run_name=payload.run_name,
        scenario_tag=payload.scenario_tag,
        sop_only=payload.sop_only,
        max_cases=payload.max_cases,
        score_reasons=payload.score_reasons,
    )

    return {
        "run_id": str(summary.run_id),
        "run_name": summary.run_name,
        "model_name": summary.model_name,
        "total_cases": summary.total_cases,
        "metrics": {
            "correctness_rate_all_pct": _pct(summary.correctness_rate_all),
            "correctness_rate_sop_pct": _pct(summary.correctness_rate_sop),
            "correctness_rate_unexpected_pct": _pct(
                summary.correctness_rate_unexpected
            ),
            "avg_reason_plausibility_all": summary.avg_reason_plausibility_all,
            "avg_reason_plausibility_sop": summary.avg_reason_plausibility_sop,
            "avg_reason_plausibility_unexpected": (
                summary.avg_reason_plausibility_unexpected
            ),
        },
        "parse_failure_count": summary.parse_failure_count,
    }


@router.post("/runs")
async def start_evaluation_run(payload: RunEvaluationRequest) -> dict:
    
    return await _execute_evaluation(payload)


@router.post("/run")
async def start_evaluation_run_singular(payload: RunEvaluationRequest) -> dict:

    return await _execute_evaluation(payload)


@router.get("/runs")
async def list_evaluation_runs(
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    
    runs = await _reporter.list_runs(db)
    return {"runs": runs, "count": len(runs)}


@router.get("/runs/{run_id}")
async def get_evaluation_run(
    run_id: str,
    include_cases: bool = Query(default=True),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    
    try:
        return await _reporter.export_run_json(
            db, run_id, include_cases=include_cases
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/export/csv", response_class=PlainTextResponse)
async def export_all_runs_csv(
    db: AsyncSession = Depends(get_db_session),
) -> PlainTextResponse:
    
    content = await _reporter.export_all_runs_csv(db)
    return PlainTextResponse(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=evaluation_results.csv"
        },
    )


def _pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 1)
