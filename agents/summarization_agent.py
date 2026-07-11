import asyncio
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.base_agent import BaseAgent
from core.event_log.store import EventLogStore
from llm.client import GeminiClient
from llm.rate_limiter import RateLimiter
from schemas.event import EventCreate, EventRead

logger = logging.getLogger(__name__)


class SummaryType(str, Enum):
    TASK = "task"
    PRODUCTION = "production"
    ERROR = "error"
    DAILY = "daily"


_SUMMARY_PROMPTS: dict[SummaryType, str] = {
    SummaryType.TASK: (
        "You are an industrial automation system monitor. "
        "Below is a list of recent events from the Inspection Station automation system. "
        "Write a concise TASK SUMMARY (3-5 sentences) focused on:\n"
        "  - Which tasks were assigned by the Manager\n"
        "  - Which operator commands were issued\n"
        "  - Whether tasks completed successfully\n"
        "Be specific about function calls and their outcomes."
    ),
    SummaryType.PRODUCTION: (
        "You are an industrial automation system monitor. "
        "Below is a list of recent events from the Inspection Station automation system. "
        "Write a concise PRODUCTION FLOW SUMMARY (3-5 sentences) focused on:\n"
        "  - Workpiece movement through the station (sensors triggered)\n"
        "  - Conveyor and holder activations\n"
        "  - Overall throughput and flow status"
    ),
    SummaryType.ERROR: (
        "You are an industrial automation system monitor. "
        "Below is a list of recent events from the Inspection Station automation system. "
        "Write a concise ERROR AND ALERT SUMMARY focused on:\n"
        "  - Any alert_to_supervisor events and their reasons\n"
        "  - Any emergency_stop activations\n"
        "  - Any parse failures or dispatch errors\n"
        "If there are no errors or alerts, state that explicitly."
    ),
    SummaryType.DAILY: (
        "You are an industrial automation system monitor. "
        "Below is a complete event log from the Inspection Station automation system. "
        "Write a comprehensive DAILY ACTIVITY REPORT covering:\n"
        "  1. Production summary (workpieces processed, conveyors used)\n"
        "  2. Task summary (tasks assigned and completed)\n"
        "  3. Error summary (alerts and emergency stops)\n"
        "  4. Notable observations or anomalies\n"
        "Keep the report under 200 words and use bullet points for each section."
    ),
}

DEFAULT_SUMMARY_INTERVAL_SECONDS = 60.0
MAX_EVENTS_PER_SUMMARY = 100


class SummarizationAgent(BaseAgent):

    def __init__(
        self,
        agent_id: str,
        agent_db_id: uuid.UUID,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: GeminiClient,
        summary_types: list[SummaryType] | None = None,
        summary_interval_seconds: float = DEFAULT_SUMMARY_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(agent_id, agent_db_id, session_factory)

        self._llm_client = llm_client
        self._summary_types = summary_types or [SummaryType.PRODUCTION]
        self._interval = summary_interval_seconds


        self._rate_limiter = RateLimiter(
            requests_per_minute=5,
            burst=1,
        )

    async def stop(self) -> None:
  
        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()

            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info(
            "SummarizationAgent '%s' stopped.",
            self._agent_id,
        )

    async def _advance_cursor(self, new_sequence_id: int) -> None:

        self._cursor = new_sequence_id

        logger.debug(
            "SummarizationAgent '%s': cursor advanced "
            "to %d (in-memory only).",
            self._agent_id,
            self._cursor,
        )



    async def run_loop(self) -> None:

        logger.info(
            "SummarizationAgent '%s' started "
            "(interval=%.0fs, types=%s).",
            self._agent_id,
            self._interval,
            [t.value for t in self._summary_types],
        )

        while True:
            try:
                await asyncio.sleep(self._interval)

                async with self._session_factory() as db:
                    store = EventLogStore(db)

                    batch = await store.get_events_since(
                        after_sequence_id=self._cursor,
                        limit=MAX_EVENTS_PER_SUMMARY,
                    )

                if not batch.events:
                    logger.debug(
                        "SummarizationAgent '%s': no new events since "
                        "cursor=%d.",
                        self._agent_id,
                        self._cursor,
                    )
                    continue

                logger.info(
                    "SummarizationAgent '%s': generating %d summary/ies "
                    "for %d events.",
                    self._agent_id,
                    len(self._summary_types),
                    len(batch.events),
                )

                for summary_type in self._summary_types:
                    await self._generate_and_persist_summary(
                        events=batch.events,
                        summary_type=summary_type,
                    )

                await self._advance_cursor(
                    batch.latest_sequence_id,
                )

            except asyncio.CancelledError:
                logger.info(
                    "SummarizationAgent '%s' cancelled.",
                    self._agent_id,
                )
                raise

            except Exception as exc:
                logger.exception(
                    "SummarizationAgent '%s' error (will retry): %s",
                    self._agent_id,
                    exc,
                )
                await asyncio.sleep(10.0)



    async def _generate_and_persist_summary(
        self,
        events: list[EventRead],
        summary_type: SummaryType,
    ) -> None:
        
        prompt = self._build_summary_prompt(
            events,
            summary_type,
        )

        async with self._rate_limiter:
            response = await self._llm_client.generate(
                prompt
            )

        summary_text = response.raw_text.strip()

        if not summary_text:
            logger.warning(
                "SummarizationAgent: empty summary for type %s.",
                summary_type.value,
            )
            return

        async with self._session_factory() as db:
            store = EventLogStore(db)

            await store.append(
                EventCreate(
                    scope="Summaries",
                    source="System",
                    text=summary_text,
                    metadata={
                        "summary_type": summary_type.value,
                        "events_covered": len(events),
                        "cursor_from": self._cursor,
                        "cursor_to": events[-1].sequence_id,
                        "generated_at":
                            datetime.now(
                                timezone.utc
                            ).isoformat(),
                    },
                )
            )

            await db.commit()

        logger.info(
            "SummarizationAgent: %s summary persisted "
            "(%d events → %d chars).",
            summary_type.value,
            len(events),
            len(summary_text),
        )

    @staticmethod
    def _build_summary_prompt(
        events: list[EventRead],
        summary_type: SummaryType,
    ) -> str:
        
        system_prompt = _SUMMARY_PROMPTS[summary_type]

        event_lines = "\n".join(
            e.formatted_label
            for e in events
        )

        return (
            f"{system_prompt}\n\n"
            f"Recent events ({len(events)}):\n"
            f"{event_lines}\n\n"
            f"Summary:"
        )
