















import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from command.interface import CommandInterface
from config.module_loader import ModuleConfig
from digital_twin.information_model.registry import ModuleRegistry

logger = logging.getLogger(__name__)


class CommandInterfaceManager:
    




    def __init__(self) -> None:
        self._interfaces: dict[str, CommandInterface] = {}

    def initialise(
        self,
        module_registry: ModuleRegistry,
        module_configs: dict[str, ModuleConfig],
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        for module_id in module_registry.all_module_ids():
            if module_id not in module_configs:
                logger.warning(
                    "CommandInterfaceManager: no ModuleConfig for '%s' — "
                    "skipping CommandInterface construction.", module_id,
                )
                continue

            display_name = module_configs[module_id].display_name

            interface = CommandInterface(
                module_id=module_id,
                display_name=display_name,
                module_registry=module_registry,
                session_factory=session_factory,
            )
            self._interfaces[module_id] = interface

            logger.info(
                "CommandInterface built for module '%s': %d function(s) "
                "registered.",
                module_id, len(interface.registered_function_names()),
            )

        logger.info(
            "CommandInterfaceManager initialised: %d interface(s): %s",
            len(self._interfaces), list(self._interfaces.keys()),
        )

    def get_interface(self, module_id: str) -> CommandInterface:
        try:
            return self._interfaces[module_id]
        except KeyError:
            raise KeyError(
                f"No CommandInterface for module_id={module_id!r}. "
                f"Registered: {list(self._interfaces.keys())}"
            )

    def all_module_ids(self) -> list[str]:
        return list(self._interfaces.keys())
