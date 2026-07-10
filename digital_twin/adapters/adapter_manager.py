"""
digital_twin/adapters/adapter_manager.py
──────────────────────────────────────────
AdapterManager — creates and owns one hardware adapter per module.

Mirrors the lifecycle pattern of ModuleRegistry: one instance created at
startup, held on app.state, torn down at shutdown.

In development/testing: always creates MockOpcUaAdapter instances.
In production: the ADAPTER_TYPE setting (or a factory pattern) would
select the real OPC UA adapter instead.

Dependencies:
  digital_twin.adapters.mock_adapter.MockOpcUaAdapter
  digital_twin.information_model.registry.ModuleRegistry
"""

import logging

from digital_twin.adapters.mock_adapter import MockOpcUaAdapter
from digital_twin.information_model.registry import ModuleRegistry

logger = logging.getLogger(__name__)


class AdapterManager:
    """
    Creates and owns one hardware adapter per automation module.

    Held on app.state.adapter_manager.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, MockOpcUaAdapter] = {}

    async def initialise(self, module_registry: ModuleRegistry) -> None:
        """
        Create one MockOpcUaAdapter per registered module and connect it.

        Args:
            module_registry: Already-initialised ModuleRegistry. Each adapter
                             is backed by the corresponding InformationModel.
        """
        for module_id in module_registry.all_module_ids():
            model = module_registry.get_model(module_id)
            adapter = MockOpcUaAdapter(
                module_id=module_id,
                initial_state=model.get_state(),
                model=model,
            )
            await adapter.connect()
            self._adapters[module_id] = adapter
            logger.info(
                "AdapterManager: MockOpcUaAdapter connected for '%s'.", module_id
            )

        logger.info(
            "AdapterManager: %d adapter(s) connected: %s",
            len(self._adapters), list(self._adapters.keys()),
        )

    def get_adapter(self, module_id: str) -> MockOpcUaAdapter:
        """
        Return the adapter for a module.

        Raises:
            KeyError: if module_id is not registered.
        """
        try:
            return self._adapters[module_id]
        except KeyError:
            raise KeyError(
                f"No adapter for module_id={module_id!r}. "
                f"Registered: {list(self._adapters.keys())}"
            )

    def get_mock_adapter(self, module_id: str) -> MockOpcUaAdapter:
        """Alias for get_adapter() — explicit about the type for callers
        that need MockOpcUaAdapter-specific methods like trigger_node()."""
        return self.get_adapter(module_id)

    def all_module_ids(self) -> list[str]:
        return list(self._adapters.keys())

    async def shutdown(self) -> None:
        """Disconnect all adapters cleanly."""
        for module_id, adapter in self._adapters.items():
            await adapter.disconnect()
            logger.info("AdapterManager: '%s' disconnected.", module_id)
        self._adapters.clear()