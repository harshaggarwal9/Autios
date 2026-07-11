



















import csv
import io
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.dataset import DatasetRecord

logger = logging.getLogger(__name__)


class DatasetExporter:
    



    async def export_jsonl(
        self,
        db: AsyncSession,
        scenario_tag: str | None = None,
        sop_only: bool | None = None,
        limit: int | None = None,
    ) -> str:
        











        records = await self._load_records(db, scenario_tag, sop_only, limit)
        lines = []
        for r in records:
            obj = {
                "prompt": r.prompt_text,
                "completion": r.reference_output,
                "metadata": {
                    "id": str(r.id),
                    "task_type": r.task_type,
                    "is_sop_task": r.is_sop_task,
                    "scenario_tag": r.scenario_tag,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                },
            }
            lines.append(json.dumps(obj, ensure_ascii=False))
        return "\n".join(lines) + ("\n" if lines else "")

    async def export_csv(
        self,
        db: AsyncSession,
        scenario_tag: str | None = None,
        sop_only: bool | None = None,
        limit: int | None = None,
    ) -> str:
        






        records = await self._load_records(db, scenario_tag, sop_only, limit)

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "id", "task_type", "is_sop_task", "scenario_tag",
                "created_at", "inference_id",
                "prompt_preview", "reference_output_preview",
                "full_prompt", "full_reference_output",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for r in records:
            writer.writerow({
                "id": str(r.id),
                "task_type": r.task_type or "",
                "is_sop_task": r.is_sop_task,
                "scenario_tag": r.scenario_tag or "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "inference_id": str(r.inference_id) if r.inference_id else "",
                "prompt_preview": r.prompt_text[:120].replace("\n", " "),
                "reference_output_preview": r.reference_output[:120],
                "full_prompt": r.prompt_text,
                "full_reference_output": r.reference_output,
            })
        return output.getvalue()

    async def export_stats(self, db: AsyncSession) -> dict:
        





        total_result = await db.execute(select(func.count(DatasetRecord.id)))
        total = total_result.scalar_one_or_none() or 0

        sop_result = await db.execute(
            select(func.count(DatasetRecord.id)).where(
                DatasetRecord.is_sop_task.is_(True)
            )
        )
        sop_count = sop_result.scalar_one_or_none() or 0

        task_type_result = await db.execute(
            select(DatasetRecord.task_type, func.count(DatasetRecord.id))
            .group_by(DatasetRecord.task_type)
            .order_by(func.count(DatasetRecord.id).desc())
        )
        task_type_counts = {
            row[0] or "unclassified": row[1] for row in task_type_result.all()
        }

        scenario_result = await db.execute(
            select(DatasetRecord.scenario_tag, func.count(DatasetRecord.id))
            .group_by(DatasetRecord.scenario_tag)
            .order_by(func.count(DatasetRecord.id).desc())
        )
        scenario_counts = {
            row[0] or "untagged": row[1] for row in scenario_result.all()
        }

        return {
            "total_records": total,
            "sop_records": sop_count,
            "unexpected_records": total - sop_count,
            "task_type_counts": task_type_counts,
            "scenario_tag_counts": scenario_counts,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }



    @staticmethod
    async def _load_records(
        db: AsyncSession,
        scenario_tag: str | None,
        sop_only: bool | None,
        limit: int | None,
    ) -> list[DatasetRecord]:
        query = select(DatasetRecord).order_by(DatasetRecord.created_at.asc())
        if scenario_tag is not None:
            query = query.where(DatasetRecord.scenario_tag == scenario_tag)
        if sop_only is True:
            query = query.where(DatasetRecord.is_sop_task.is_(True))
        elif sop_only is False:
            query = query.where(DatasetRecord.is_sop_task.is_(False))
        if limit is not None:
            query = query.limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())
