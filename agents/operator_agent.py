

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
        self._dataset_recorder = dataset_recorder


        self._prompt_builder = PromptBuilder(module_config)
        self._output_parser = OutputParser()
        self._subscription_engine = SubscriptionEngine(subscription_registry)


        self._rate_limiter = RateLimiter(requests_per_minute=14, burst=2)



    async def run_loop(self) -> None:

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


                prompt_text = self._prompt_builder.build(batch.events)


                await self._rate_limiter.acquire()
                llm_response = await self._llm_client.generate(prompt_text)


                parsed = self._output_parser.parse(llm_response.raw_text)


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


                dispatch_result = None
                if parsed.is_success:
                    dispatch_result = await self._command_interface.execute(
                        call_string=parsed.function_call,
                        agent_db_id=self._agent_db_id,
                        inference_id=inference_id,
                    )


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


                async with self._session_factory() as db:
                    store = EventLogStore(db)
                    if parsed.is_success:
                        await self._emit_command_event(
                            store, parsed.function_call, dispatch_result
                        )
                    else:
                        await self._emit_alert_event(store, parsed)
                    await db.commit()


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



    async def _persist_inference(
        self,
        db: AsyncSession,
        prompt_text: str,
        llm_response,
        parsed_reason: str | None,
        parsed_command: str | None,
    ) -> LLMInferenceLog:
        
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
        await db.flush()
        return row



    async def _emit_command_event(
        self,
        store: EventLogStore,
        function_call: str,
        dispatch_result,
    ) -> None:

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
