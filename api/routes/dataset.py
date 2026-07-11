

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset.exporter import DatasetExporter
from dataset.recorder import DatasetRecorder
from db.models.dataset import DatasetRecord
from db.session import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dataset", tags=["dataset"])
_exporter = DatasetExporter()


def _get_recorder(request: Request) -> DatasetRecorder:
    return request.app.state.dataset_recorder


@router.get("/stats")
async def get_dataset_stats(
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    
    return await _exporter.export_stats(db)


@router.get("/records")
async def list_records(
    limit: int = Query(default=50, ge=1, le=500),
    scenario_tag: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    sop_only: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    
    query = (
        select(DatasetRecord)
        .order_by(DatasetRecord.created_at.desc())
        .limit(limit)
    )
    if scenario_tag:
        query = query.where(DatasetRecord.scenario_tag == scenario_tag)
    if task_type:
        query = query.where(DatasetRecord.task_type == task_type)
    if sop_only is True:
        query = query.where(DatasetRecord.is_sop_task.is_(True))
    elif sop_only is False:
        query = query.where(DatasetRecord.is_sop_task.is_(False))

    result = await db.execute(query)
    records = list(result.scalars().all())

    return {
        "records": [
            {
                "id": str(r.id),
                "task_type": r.task_type,
                "is_sop_task": r.is_sop_task,
                "scenario_tag": r.scenario_tag,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "prompt_preview": r.prompt_text[:120].replace("\n", " "),
                "reference_output_preview": r.reference_output[:120],
            }
            for r in records
        ],
        "count": len(records),
    }


@router.get("/export/jsonl", response_class=PlainTextResponse)
async def export_jsonl(
    scenario_tag: str | None = Query(default=None),
    sop_only: bool | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=10000),
    db: AsyncSession = Depends(get_db_session),
) -> PlainTextResponse:
    

    content = await _exporter.export_jsonl(
        db, scenario_tag=scenario_tag, sop_only=sop_only, limit=limit
    )
    return PlainTextResponse(
        content=content,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": "attachment; filename=llm4ias_dataset.jsonl"
        },
    )


@router.get("/export/csv", response_class=PlainTextResponse)
async def export_csv(
    scenario_tag: str | None = Query(default=None),
    sop_only: bool | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=10000),
    db: AsyncSession = Depends(get_db_session),
) -> PlainTextResponse:
    
    content = await _exporter.export_csv(
        db, scenario_tag=scenario_tag, sop_only=sop_only, limit=limit
    )
    return PlainTextResponse(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=llm4ias_dataset.csv"
        },
    )


@router.post("/recording/{enabled}")
async def set_recording_enabled(
    enabled: bool,
    request: Request,
) -> dict:
    


    recorder: DatasetRecorder = _get_recorder(request)
    recorder.set_enabled(enabled)

    state_str = "enabled" if enabled else "disabled"
    logger.info("Dataset recording %s via API.", state_str)

    return {
        "recording_enabled": enabled,
        "message": f"Dataset recording is now {state_str}.",
    }
