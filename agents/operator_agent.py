"""
agents/operator_agent.py
─────────────────────────
OperatorAgent — the paper's per-module LLM agent.

Paper connection (§III.B — Agent Processing Cycle, Figure 5):
  The paper's agent processing cycle:
    Subscribed events (ℰ_AMi)
      → Prompt construction (𝒫_AMi = Textual(ℛ, 𝒞, ℱ, SOP, ℰ))
        → LLM inference
          → Output (𝒪ℓℓ𝓂 = (𝒪_reason, 𝒪_fc))
            → Function call dispatch (Phase 5: CommandInterface.execute())

  This class implements that cycle as a persistent asyncio background task.
  One OperatorAgent instance per automation module (paper §III.B).

Event loop discipline:
  1. poll_once() → EventBatch (subscribed events since cursor)
  2. PromptBuilder.build(events) → full 5-section prompt
  3. GeminiClient.generate(prompt) → LLMResponse
  4. OutputParser.parse(response) → ParsedOutput
  5. _persist_inference() → llm_inference_log row (captures inference_id)
  6. CommandInterface.execute() → DispatchResult (Phase 5)
  7. DatasetRecorder.record_inference() → dataset_records row (Phase 6)
  8. _emit_command_event() or _emit_alert_event() → EventLogStore
  9. _advance_cursor() → persists cursor (exactly-once guarantee)

Dependencies:
  agents.base_agent.BaseAgent
  agents.prompt.builder.PromptBuilder
  command.interface.CommandInterface
  dataset.recorder.DatasetRecorder
  llm.client.GeminiClient
  llm.output_parser.OutputParser
  llm.rate_limiter.RateLimiter
  core.subscription.engine.SubscriptionEngine
  core.event_log.store.EventLogStore
  db.models.inference_log.LLMInferenceLog
  schemas.event.EventCreate
"""

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.base_agent import BaseAgent
from agents.prompt.builder import PromptBuilder
from command.interface import CommandInterface
from config.module_loader import ModuleConfig
from config.settings import get_settings
from core.event_log.store import EventLogStore
from core.subscription.engine import SubscriptionEngine
from core.subscription.registry import SubscriptionRegistry
from dataset.recorder import DatasetRecorder
from db.models.inference_log import LLMInferenceLog
from llm.client import GeminiClient
from llm.output_parser import OutputParser, ParseStatus
from llm.rate_limiter import RateLimiter
from schemas.event import EventCreate

logger = logging.getLogger(__name__)
settings = get_settings()


class OperatorAgent(BaseAgent):
    """
    Per-module LLM agent — polls the event log, calls Gemini,
    dispatches the resulting command, and emits a confirmation event.
    """

    def __init__(
        self,
        agent_id: str,
        agent_db_id: uuid.UUID,
        module_config: ModuleConfig,
        session_factory: async_sessionmaker[AsyncSession],
        subscription_registry: SubscriptionRegistry,
        llm_client: GeminiClient,
        command_interface: CommandInterface,
        dataset_recorder: DatasetRecorder | None = None,
    ) -> None:
        super().__init__(agent_id, agent_db_id, session_factory)

        self._module_config = module_config
        self._subscription_registry = subscription_registry
        self._llm_client = llm_client
        self._command_interface = command_interface
        self._dataset_recorder = dataset_recorder  # None = recording disabled

        # PromptBuilder is stateless — build once, reuse for every inference
        self._prompt_builder = PromptBuilder(module_config)
        self._output_parser = OutputParser()
        self._subscription_engine = SubscriptionEngine(subscription_registry)

        # Rate limiter: 14 req/min (slightly under Gemini free tier limit of 15)
        self._rate_limiter = RateLimiter(requests_per_minute=14, burst=2)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run_loop(self) -> None:
        """
        Main agent processing cycle — runs until asyncio.CancelledError.

        Polls the EventLog for new events in subscribed scopes,
        calls Gemini, parses the response, dispatches the command
        via CommandInterface, records to dataset, and emits a result event.
        """
        logger.info(
            "OperatorAgent '%s' run_loop started (cursor=%d).",
            self._agent_id, self._cursor,
        )

        while True:
            try:
                async with self._session_factory() as db:
                    batch = await self._subscription_engine.poll_once(
                        agent_id=self._agent_id,
                        after_sequence_id=self._cursor,
                        db=db,
                        limit=settings.agent_event_window_size,
                    )

                if not batch.events:
                    await asyncio.sleep(settings.agent_poll_interval_seconds)
                    continue

                logger.info(
                    "OperatorAgent '%s': %d new event(s) since cursor=%d.",
                    self._agent_id, len(batch.events), self._cursor,
                )

                # ── Build prompt ───────────────────────────────────────────────
                prompt_text = self._prompt_builder.build(batch.events)

                # ── LLM inference ──────────────────────────────────────────────
                await self._rate_limiter.acquire()
                llm_response = await self._llm_client.generate(prompt_text)

                # ── Parse response ─────────────────────────────────────────────
                parsed = self._output_parser.parse(llm_response.raw_text)

                # ── Persist inference to llm_inference_log ─────────────────────
                async with self._session_factory() as db:
                    inference_row = await self._persist_inference(
                        db=db,
                        prompt_text=prompt_text,
                        llm_response=llm_response,
                        parsed_reason=parsed.reason,
                        parsed_command=parsed.function_call,
                    )
                    await db.commit()
                    inference_id = inference_row.id

                # ── Dispatch command (Phase 5) ─────────────────────────────────
                dispatch_result = None
                if parsed.is_success:
                    dispatch_result = await self._command_interface.execute(
                        call_string=parsed.function_call,
                        agent_db_id=self._agent_db_id,
                        inference_id=inference_id,
                    )

                # ── Record for dataset (Phase 6) ───────────────────────────────
                if self._dataset_recorder is not None:
                    await self._dataset_recorder.record_inference(
                        inference_id=inference_id,
                        prompt_text=prompt_text,
                        response_text=llm_response.raw_text,
                        parsed_reason=parsed.reason,
                        parsed_command=parsed.function_call,
                        dispatch_outcome=(
                            dispatch_result.outcome if dispatch_result else None
                        ),
                        module_id=self._module_config.module_id,
                    )

                # ── Emit command or alert event ────────────────────────────────
                async with self._session_factory() as db:
                    store = EventLogStore(db)
                    if parsed.is_success:
                        await self._emit_command_event(
                            store, parsed.function_call, dispatch_result
                        )
                    else:
                        await self._emit_alert_event(store, parsed)
                    await db.commit()

                # ── Advance cursor (exactly-once guarantee) ────────────────────
                await self._advance_cursor(batch.latest_sequence_id)

            except asyncio.CancelledError:
                logger.info(
                    "OperatorAgent '%s' run_loop cancelled.", self._agent_id
                )
                raise

            except Exception as exc:
                logger.exception(
                    "OperatorAgent '%s' unhandled error (will retry): %s",
                    self._agent_id, exc,
                )
                await asyncio.sleep(5.0)

    # ── DB persistence ────────────────────────────────────────────────────────

    async def _persist_inference(
        self,
        db: AsyncSession,
        prompt_text: str,
        llm_response,
        parsed_reason: str | None,
        parsed_command: str | None,
    ) -> LLMInferenceLog:
        """Persist one inference cycle to llm_inference_log."""
        row = LLMInferenceLog(
            agent_id=self._agent_db_id,
            task_id=None,
            prompt_text=prompt_text,
            response_text=llm_response.raw_text,
            reason_text=parsed_reason,
            function_call_text=parsed_command,
            model_name=llm_response.model_name,
            prompt_tokens=llm_response.prompt_tokens,
            response_tokens=llm_response.response_tokens,
            latency_ms=llm_response.latency_ms,
        )
        db.add(row)
        await db.flush()  # populate server-generated id
        return row

    # ── Event emission ────────────────────────────────────────────────────────

    async def _emit_command_event(
        self,
        store: EventLogStore,
        function_call: str,
        dispatch_result,
    ) -> None:
        """
        Emit the result of dispatching the LLM's command.

        Paper format (Figure 3):
          "[Inspection Station][Operator][HH:MM:SS]
           Inspection Station calls function: conveyor_1_run('forward', 13)."

        Phase 5 addition: the event text reflects the actual dispatch outcome
        (success or failure) rather than just what the LLM requested.
        """
        from db.models.inference_log import CommandOutcome

        if dispatch_result is None or dispatch_result.outcome == CommandOutcome.SUCCESS:
            text = (
                f"{self._module_config.display_name} calls function: "
                f"{function_call}."
            )
            metadata = {
                "agent_id": self._agent_id,
                "function_call": function_call,
                "dispatch_outcome": (
                    dispatch_result.outcome.value
                    if dispatch_result else "not_dispatched"
                ),
            }
        else:
            text = (
                f"{self._module_config.display_name} attempted to call "
                f"function: {function_call}, but dispatch failed "
                f"({dispatch_result.outcome.value}): "
                f"{dispatch_result.error_message}"
            )
            metadata = {
                "agent_id": self._agent_id,
                "function_call": function_call,
                "dispatch_outcome": dispatch_result.outcome.value,
                "error_message": dispatch_result.error_message,
            }

        await store.append(
            EventCreate(
                scope=self._module_config.display_name,
                source="Operator",
                text=text,
                metadata=metadata,
            )
        )
        logger.info(
            "OperatorAgent '%s': emitted command event: %s (outcome=%s)",
            self._agent_id,
            function_call,
            dispatch_result.outcome.value if dispatch_result else "not_dispatched",
        )

    async def _emit_alert_event(
        self,
        store: EventLogStore,
        parsed,
    ) -> None:
        """
        Emit an alert_to_supervisor event when the LLM output cannot be parsed.

        The supervisor event signals that human intervention may be needed
        and that the agent cannot proceed with this event context.
        """
        reason = parsed.error_detail or "LLM output could not be parsed."
        text = (
            f"{self._module_config.display_name} calls function: "
            f'alert_to_supervisor("{reason}")'
        )
        await store.append(
            EventCreate(
                scope=self._module_config.display_name,
                source="Operator",
                text=text,
                metadata={
                    "agent_id": self._agent_id,
                    "parse_status": parsed.status.value,
                    "error_detail": parsed.error_detail,
                },
            )
        )
        logger.warning(
            "OperatorAgent '%s': parse failure (%s) — emitted alert_to_supervisor.",
            self._agent_id, parsed.status.value,
        )