"""
command/interface.py
─────────────────────
CommandInterface — the complete dispatch path from a raw LLM function-call
string to executed (mocked) hardware action, with full audit logging.

Paper connection (§II.A, §III.B — Command Interface):
  "The command interface receives function calls and routes them to
  microservices."

Pipeline per dispatch:
  1. CallParser.parse(call_string)        → ParsedCall(name, args)
  2. Check emergency_stop_active           → guard
  3. FunctionRegistry.dispatch(...)        → executes, returns DispatchResult
  4. AgentCommandLog row persisted         → audit trail (success or failure)

transport_robot_request and request_inspection_service are bound with
emit-event callbacks that open a fresh DB session, since their completion
is delayed and decoupled from the call's immediate return.

Dependencies:
  command.call_parser.CallParser
  command.function_registry.FunctionRegistry, DispatchResult
  command.mock_functions.*
  digital_twin.information_model.registry.ModuleRegistry
  core.event_log.store.EventLogStore
  db.models.inference_log.AgentCommandLog
  schemas.event.EventCreate
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from command import mock_functions as mf
from command.call_parser import CallParser, CallParseError
from command.function_registry import DispatchResult, FunctionRegistry
from core.event_log.store import EventLogStore
from db.models.inference_log import AgentCommandLog, CommandOutcome
from digital_twin.information_model.registry import ModuleRegistry
from schemas.event import EventCreate

logger = logging.getLogger(__name__)


class CommandInterface:
    """
    Dispatches parsed LLM commands to mock hardware functions for one module.
    One instance per automation module, constructed by CommandInterfaceManager.
    """

    def __init__(
        self,
        module_id: str,
        display_name: str,
        module_registry: ModuleRegistry,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._module_id = module_id
        self._display_name = display_name
        self._module_registry = module_registry
        self._session_factory = session_factory
        self._call_parser = CallParser()
        self._registry = self._build_registry()

    # ── Registry construction ────────────────────────────────────────────────

    def _build_registry(self) -> FunctionRegistry:
        registry = FunctionRegistry(self._module_id)
        model = self._module_registry.get_model(self._module_id)

        model.register_node_if_absent("emergency_stop_active", False)

        registry.register(
            "conveyor_1_run",
            lambda direction, time: mf.conveyor_1_run(model, direction, time),
            arity=2,
        )
        registry.register(
            "conveyor_2_run",
            lambda direction, time: mf.conveyor_2_run(model, direction, time),
            arity=2,
        )
        registry.register(
            "conveyor_3_run",
            lambda direction, time: mf.conveyor_3_run(model, direction, time),
            arity=2,
        )
        registry.register(
            "conveyor_4_run",
            lambda direction, time: mf.conveyor_4_run(model, direction, time),
            arity=2,
        )
        registry.register(
            "release_holder_H1", lambda: mf.release_holder_H1(model), arity=0,
        )
        registry.register(
            "release_holder_H2", lambda: mf.release_holder_H2(model), arity=0,
        )
        registry.register(
            "release_holder_H3", lambda: mf.release_holder_H3(model), arity=0,
        )
        registry.register(
            "RFID_read_workpiece_info",
            lambda: mf.RFID_read_workpiece_info(model),
            arity=0,
        )
        registry.register(
            "switch_actuate",
            lambda action: mf.switch_actuate(model, action),
            arity=1,
        )
        registry.register(
            "emergency_stop", lambda: mf.emergency_stop(model), arity=0,
        )
        registry.register(
            "alert_to_supervisor",
            lambda reason: mf.alert_to_supervisor(reason),
            arity=1,
        )
        registry.register(
            "transport_robot_request",
            lambda: mf.transport_robot_request(self._emit_robot_docked_event),
            arity=0,
        )
        registry.register(
            "request_inspection_service",
            lambda description: mf.request_inspection_service(
                description, self._emit_inspection_completed_event
            ),
            arity=1,
        )

        return registry

    # ── Delayed-completion event emitters ────────────────────────────────────

    async def _emit_robot_docked_event(self) -> None:
        async with self._session_factory() as db:
            store = EventLogStore(db)
            await store.append(
                EventCreate(
                    scope=self._display_name,
                    source="System",
                    text=(
                        "The transport robot has docked with the "
                        f"{self._display_name}."
                    ),
                    metadata={"module_id": self._module_id, "event": "robot_docked"},
                )
            )
            await db.commit()

    async def _emit_inspection_completed_event(self) -> None:
        async with self._session_factory() as db:
            store = EventLogStore(db)
            await store.append(
                EventCreate(
                    scope=self._display_name,
                    source="System",
                    text="The inspection service is successfully completed.",
                    metadata={
                        "module_id": self._module_id,
                        "event": "inspection_completed",
                    },
                )
            )
            await db.commit()

    # ── Public dispatch API ───────────────────────────────────────────────────

    async def execute(
        self,
        call_string: str,
        agent_db_id: uuid.UUID,
        inference_id: uuid.UUID,
    ) -> DispatchResult:
        """
        Parse and dispatch one LLM-generated function call string.

        Never raises — all failure modes captured in the returned
        DispatchResult.outcome.
        """
        try:
            parsed = self._call_parser.parse(call_string)
        except CallParseError as exc:
            logger.warning(
                "CommandInterface['%s']: call parse failed: %s",
                self._module_id, exc,
            )
            result = DispatchResult(
                outcome=CommandOutcome.PARSE_ERROR,
                function_name="<unparseable>",
                parameters={"raw": call_string},
                error_message=str(exc),
            )
            await self._persist_command_log(result, agent_db_id, inference_id)
            return result

        model = self._module_registry.get_model(self._module_id)
        emergency_active = bool(model.get_node("emergency_stop_active"))

        result = await self._registry.dispatch(
            function_name=parsed.function_name,
            args=parsed.args,
            emergency_stop_active=emergency_active,
        )
        result.parameters = {"args": parsed.args}

        await self._persist_command_log(result, agent_db_id, inference_id)
        return result

    async def _persist_command_log(
        self,
        result: DispatchResult,
        agent_db_id: uuid.UUID,
        inference_id: uuid.UUID,
    ) -> None:
        async with self._session_factory() as db:
            row = AgentCommandLog(
                agent_id=agent_db_id,
                inference_id=inference_id,
                function_name=result.function_name,
                parameters=result.parameters,
                outcome=result.outcome,
                error_message=result.error_message,
            )
            db.add(row)
            await db.commit()

    # ── Introspection ─────────────────────────────────────────────────────────

    def registered_function_names(self) -> list[str]:
        return self._registry.registered_names()

    @property
    def module_id(self) -> str:
        return self._module_id