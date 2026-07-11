import logging
from typing import Any

from digital_twin.adapters.base import AbstractHardwareAdapter
from digital_twin.information_model.model import InformationModel, StateDict

logger = logging.getLogger(__name__)


class MockOpcUaAdapter(AbstractHardwareAdapter):

    def __init__(
        self,
        module_id: str,
        initial_state: StateDict,
        model: InformationModel,
    ) -> None:
        super().__init__(module_id)
        self._initial_state = initial_state
        self._model = model
        self._connected = False

    async def connect(self) -> None:

        self._connected = True
        logger.info(
            "MockOpcUaAdapter '%s': connected (mock, %d initial nodes).",
            self._module_id, len(self._initial_state),
        )

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("MockOpcUaAdapter '%s': disconnected.", self._module_id)

    async def read_node(self, node_id: str) -> Any:
        
        value = self._model.get_node(node_id)
        if value is None:
            logger.warning(
                "MockOpcUaAdapter '%s': read_node('%s') — node not found.",
                self._module_id, node_id,
            )
        return value

    async def write_node(self, node_id: str, value: Any) -> bool:
        
        changed = await self._model.update_node(node_id, value)
        if not changed:
            logger.debug(
                "MockOpcUaAdapter '%s': write_node('%s', %r) — value unchanged.",
                self._module_id, node_id, value,
            )
        return changed

    async def trigger_node(self, node_id: str, value: Any) -> bool:

        changed = await self._model.update_node(node_id, value)
        if changed:
            logger.info(
                "MockOpcUaAdapter '%s': triggered '%s' = %r.",
                self._module_id, node_id, value,
            )
        return changed

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def model(self) -> InformationModel:
        
        return self._model
