























import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from db.models.inference_log import CommandOutcome

logger = logging.getLogger(__name__)


ALWAYS_ALLOWED = {"emergency_stop", "alert_to_supervisor"}


@dataclass
class RegisteredFunction:
    handler: Callable[..., Awaitable[Any]]
    arity: int


@dataclass
class DispatchResult:
    outcome: CommandOutcome
    function_name: str
    parameters: dict[str, Any] | None
    return_value: Any = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.outcome == CommandOutcome.SUCCESS


class FunctionRegistry:
    



    def __init__(self, module_id: str) -> None:
        self._module_id = module_id
        self._functions: dict[str, RegisteredFunction] = {}

    def register(
        self,
        function_name: str,
        handler: Callable[..., Awaitable[Any]],
        arity: int,
    ) -> None:
        self._functions[function_name] = RegisteredFunction(handler, arity)
        logger.debug(
            "FunctionRegistry['%s']: registered '%s' (arity=%d).",
            self._module_id, function_name, arity,
        )

    def is_registered(self, function_name: str) -> bool:
        return function_name in self._functions

    def registered_names(self) -> list[str]:
        return list(self._functions.keys())

    async def dispatch(
        self,
        function_name: str,
        args: list[Any],
        emergency_stop_active: bool,
    ) -> DispatchResult:
        parameters = {"args": args}

        if function_name not in self._functions:
            logger.warning(
                "FunctionRegistry['%s']: unknown function '%s'.",
                self._module_id, function_name,
            )
            return DispatchResult(
                outcome=CommandOutcome.UNKNOWN_FUNCTION,
                function_name=function_name,
                parameters=parameters,
                error_message=(
                    f"Function '{function_name}' is not registered for "
                    f"module '{self._module_id}'. Registered: "
                    f"{self.registered_names()}"
                ),
            )

        if emergency_stop_active and function_name not in ALWAYS_ALLOWED:
            logger.warning(
                "FunctionRegistry['%s']: '%s' BLOCKED — emergency stop active.",
                self._module_id, function_name,
            )
            return DispatchResult(
                outcome=CommandOutcome.EMERGENCY_BLOCKED,
                function_name=function_name,
                parameters=parameters,
                error_message=(
                    f"Module '{self._module_id}' is in emergency stop state. "
                    f"Only {ALWAYS_ALLOWED} are permitted until cleared."
                ),
            )

        registered = self._functions[function_name]
        if len(args) != registered.arity:
            logger.warning(
                "FunctionRegistry['%s']: '%s' called with %d args, "
                "expected %d.",
                self._module_id, function_name, len(args), registered.arity,
            )
            return DispatchResult(
                outcome=CommandOutcome.INVALID_PARAMS,
                function_name=function_name,
                parameters=parameters,
                error_message=(
                    f"'{function_name}' expects {registered.arity} "
                    f"argument(s), got {len(args)}: {args!r}"
                ),
            )

        try:
            return_value = await registered.handler(*args)
        except Exception as exc:
            logger.exception(
                "FunctionRegistry['%s']: '%s' raised during execution: %s",
                self._module_id, function_name, exc,
            )
            return DispatchResult(
                outcome=CommandOutcome.EXECUTION_ERROR,
                function_name=function_name,
                parameters=parameters,
                error_message=f"{type(exc).__name__}: {exc}",
            )

        logger.info(
            "FunctionRegistry['%s']: '%s' executed successfully.",
            self._module_id, function_name,
        )
        return DispatchResult(
            outcome=CommandOutcome.SUCCESS,
            function_name=function_name,
            parameters=parameters,
            return_value=return_value,
        )
