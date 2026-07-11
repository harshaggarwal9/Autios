import json
import logging
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.dataset import DatasetRecord, EvaluationResult, EvaluationRun
from llm.client import GeminiClient
from llm.output_parser import OutputParser

logger = logging.getLogger(__name__)


@dataclass
class CaseResult:

    record_id: uuid.UUID
    prompt_text: str
    reference_output: str
    generated_output: str
    is_sop_task: bool
    task_type: str | None
    command_correct: bool | None
    reason_plausibility: float | None
    error: str | None = None


@dataclass
class EvaluationSummary:

    run_id: uuid.UUID
    run_name: str
    model_name: str
    total_cases: int
    sop_cases: int
    unexpected_cases: int
    correctness_rate_all: float | None
    correctness_rate_sop: float | None
    correctness_rate_unexpected: float | None
    avg_reason_plausibility_all: float | None
    avg_reason_plausibility_sop: float | None
    avg_reason_plausibility_unexpected: float | None
    parse_failure_count: int
    execution_error_count: int = 0
    case_results: list[CaseResult] = field(default_factory=list)


class EvaluationEngine:

    _JUDGE_SYSTEM = (
        "You are an expert evaluator for industrial automation systems. "
        "Score the following LLM-generated reasoning on a scale from 1 to 5:\n"
        "  5 = Perfectly logical, correct reference to the relevant "
        "sensor/actuator, and clearly explains why this command was chosen.\n"
        "  4 = Mostly correct, minor omission or imprecision.\n"
        "  3 = Partially correct, addresses the right event but reasoning "
        "is vague.\n"
        "  2 = Weak reasoning, loosely connected to the context.\n"
        "  1 = Wrong or completely irrelevant reasoning.\n\n"
        "Respond with ONLY a single integer (1-5), nothing else."
    )

    def __init__(
        self,
        llm_client: GeminiClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._llm_client = llm_client
        self._session_factory = session_factory
        self._parser = OutputParser()



    async def run_evaluation(
        self,
        run_name: str,
        scenario_tag: str | None = None,
        sop_only: bool | None = None,
        max_cases: int | None = None,
        score_reasons: bool = True,
    ) -> EvaluationSummary:

        logger.info(
            "EvaluationEngine: starting run '%s' (scenario=%s, max=%s).",
            run_name, scenario_tag, max_cases,
        )

        async with self._session_factory() as db:
            records = await self._load_test_cases(db, scenario_tag, sop_only, max_cases)

        if not records:
            logger.warning(
                "EvaluationEngine: no DatasetRecords found — nothing to evaluate."
            )
            return self._empty_summary(run_name)

        logger.info("EvaluationEngine: evaluating %d test case(s).", len(records))

        case_results: list[CaseResult] = []
        for i, record in enumerate(records):
            logger.info(
                "EvaluationEngine: case %d/%d (id=%s, type=%s).",
                i + 1, len(records), record.id, record.task_type,
            )
            result = await self._evaluate_one(record, score_reasons=score_reasons)
            case_results.append(result)

        summary = self._aggregate(run_name, case_results)

        async with self._session_factory() as db:
            run_row = await self._persist_run(db, summary, case_results, records)
            summary.run_id = run_row.id
            await db.commit()

        logger.info(
            "EvaluationEngine: run '%s' complete — correctness=%.1f%% (n=%d).",
            run_name,
            (summary.correctness_rate_all or 0) * 100,
            summary.total_cases,
        )
        return summary



    async def _evaluate_one(
        self,
        record: DatasetRecord,
        score_reasons: bool,
    ) -> CaseResult:
        try:
            llm_response = await self._llm_client.generate(record.prompt_text)
            generated_output = llm_response.raw_text
        except Exception as exc:
            logger.exception(
                "EvaluationEngine: LLM call failed for %s: %s", record.id, exc
            )
            return CaseResult(
                record_id=record.id,
                prompt_text=record.prompt_text,
                reference_output=record.reference_output,
                generated_output="",
                is_sop_task=record.is_sop_task,
                task_type=record.task_type,
                command_correct=False,
                reason_plausibility=None,
                error=str(exc),
            )

        parsed = self._parser.parse(generated_output)

        command_correct = None
        if parsed.is_success:
            ref_command = self._extract_command_from_reference(record.reference_output)
            command_correct = self._commands_match(parsed.function_call, ref_command)
        else:
            command_correct = False

        reason_plausibility = None
        if score_reasons and parsed.reason:
            reason_plausibility = await self._score_reason(
                event_context=self._extract_event_context(record.prompt_text),
                reason=parsed.reason,
            )

        return CaseResult(
            record_id=record.id,
            prompt_text=record.prompt_text,
            reference_output=record.reference_output,
            generated_output=generated_output,
            is_sop_task=record.is_sop_task,
            task_type=record.task_type,
            command_correct=command_correct,
            reason_plausibility=reason_plausibility,
        )

    async def _score_reason(self, event_context: str, reason: str) -> float | None:

        judge_prompt = (
            f"{self._JUDGE_SYSTEM}\n\n"
            f"Event context:\n{event_context}\n\n"
            f"Generated reasoning:\n{reason}\n\n"
            "Score (1-5):"
        )
        try:
            response = await self._llm_client.generate(judge_prompt)
            match = re.search(r"\b([1-5])\b", response.raw_text)
            if match:
                return float(match.group(1))
        except Exception as exc:
            logger.debug("EvaluationEngine: reason scoring failed: %s", exc)
        return None



    def _aggregate(self, run_name: str, results: list[CaseResult]) -> EvaluationSummary:
        total = len(results)
        sop = [r for r in results if r.is_sop_task]
        unexpected = [r for r in results if not r.is_sop_task]

        def correctness_rate(cases: list[CaseResult]) -> float | None:
            if not cases:
                return None
            scored = [c for c in cases if c.command_correct is not None]
            if not scored:
                return None
            return sum(1 for c in scored if c.command_correct) / len(scored)

        def avg_plausibility(cases: list[CaseResult]) -> float | None:
            scores = [
                c.reason_plausibility for c in cases
                if c.reason_plausibility is not None
            ]
            return sum(scores) / len(scores) if scores else None

        model_name = getattr(self._llm_client, "_model_name", "unknown")

        return EvaluationSummary(
            run_id=uuid.uuid4(),
            run_name=run_name,
            model_name=model_name,
            total_cases=total,
            sop_cases=len(sop),
            unexpected_cases=len(unexpected),
            correctness_rate_all=correctness_rate(results),
            correctness_rate_sop=correctness_rate(sop),
            correctness_rate_unexpected=correctness_rate(unexpected),
            avg_reason_plausibility_all=avg_plausibility(results),
            avg_reason_plausibility_sop=avg_plausibility(sop),
            avg_reason_plausibility_unexpected=avg_plausibility(unexpected),
            parse_failure_count=sum(
                1 for r in results if r.command_correct is False and r.error is None
            ),
            case_results=results,
        )



    async def _persist_run(
        self,
        db: AsyncSession,
        summary: EvaluationSummary,
        case_results: list[CaseResult],
        records: list[DatasetRecord],
    ) -> EvaluationRun:
        run = EvaluationRun(
            run_name=summary.run_name,
            model_name=summary.model_name,
            total_cases=summary.total_cases,
            sop_cases=summary.sop_cases,
            unexpected_cases=summary.unexpected_cases,
            correctness_rate_all=summary.correctness_rate_all,
            correctness_rate_sop=summary.correctness_rate_sop,
            correctness_rate_unexpected=summary.correctness_rate_unexpected,
            avg_reason_plausibility_all=summary.avg_reason_plausibility_all,
            avg_reason_plausibility_sop=summary.avg_reason_plausibility_sop,
            avg_reason_plausibility_unexpected=summary.avg_reason_plausibility_unexpected,
        )
        db.add(run)
        await db.flush()

        record_id_map = {r.id: r.id for r in records}

        for case in case_results:
            result_row = EvaluationResult(
                run_id=run.id,
                dataset_record_id=record_id_map[case.record_id],
                generated_output=case.generated_output,
                command_correct=case.command_correct,
                reason_plausibility=case.reason_plausibility,
                evaluator_notes=case.error,
            )
            db.add(result_row)

        await db.flush()
        return run



    @staticmethod
    async def _load_test_cases(
        db: AsyncSession,
        scenario_tag: str | None,
        sop_only: bool | None,
        max_cases: int | None,
    ) -> list[DatasetRecord]:
        query = select(DatasetRecord).order_by(DatasetRecord.created_at.asc())
        if scenario_tag is not None:
            query = query.where(DatasetRecord.scenario_tag == scenario_tag)
        if sop_only is True:
            query = query.where(DatasetRecord.is_sop_task.is_(True))
        elif sop_only is False:
            query = query.where(DatasetRecord.is_sop_task.is_(False))
        if max_cases is not None:
            query = query.limit(max_cases)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def _extract_command_from_reference(reference_output: str) -> str | None:
        try:
            data = json.loads(reference_output)
            return data.get("command")
        except (json.JSONDecodeError, AttributeError):
            return None

    @staticmethod
    def _commands_match(generated: str | None, reference: str | None) -> bool:

        if generated is None or reference is None:
            return False
        if generated.strip() == reference.strip():
            return True

        def fn_name(s: str) -> str | None:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(", s.strip())
            return m.group(1) if m else None

        return fn_name(generated) == fn_name(reference) and fn_name(generated) is not None

    @staticmethod
    def _extract_event_context(prompt_text: str) -> str:
        
        marker = "Input:"
        idx = prompt_text.rfind(marker)
        if idx != -1:
            return prompt_text[idx + len(marker):].strip()
        return prompt_text[-500:].strip()

    @staticmethod
    def _empty_summary(run_name: str) -> EvaluationSummary:
        return EvaluationSummary(
            run_id=uuid.uuid4(),
            run_name=run_name,
            model_name="unknown",
            total_cases=0,
            sop_cases=0,
            unexpected_cases=0,
            correctness_rate_all=None,
            correctness_rate_sop=None,
            correctness_rate_unexpected=None,
            avg_reason_plausibility_all=None,
            avg_reason_plausibility_sop=None,
            avg_reason_plausibility_unexpected=None,
            parse_failure_count=0,
        )
