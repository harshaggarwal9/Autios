"""
digital_twin/adapters/mock_adapter.py
───────────────────────────────────────
MockOpcUaAdapter — a software-only hardware adapter for development and testing.

Paper connection (§II.A — Hardware Interface):
  In the paper, the system reads from and writes to physical OPC UA nodes
  on a Festo Didactic CP Lab. This mock adapter simulates that behaviour:
    - read_node() reads from the InformationModel (the digital twin's current state)
    - write_node() writes to the InformationModel (simulates an actuator command)
    - trigger_node() writes a value and returns whether the model changed
      (used by POST /simulate/sensor-trigger in development)

Design:
  The mock adapter holds a reference to the InformationModel for its module.
  This tight coupling is intentional — in the mock scenario the adapter IS
  the hardware, so reading from and writing to the model is the correct
  simulation of a real OPC UA node read/write.

  In a real deployment, replace this with a proper OPC UA client (e.g. using
  the asyncua library) that connects to the physical PLC.

Dependencies:
  digital_twin.adapters.base.AbstractHardwareAdapter
  digital_twin.information_model.model.InformationModel
"""

import logging
from typing import Any

from digital_twin.adapters.base import AbstractHardwareAdapter
from digital_twin.information_model.model import InformationModel, StateDict

logger = logging.getLogger(__name__)


class MockOpcUaAdapter(AbstractHardwareAdapter):
    """
    Software-only OPC UA adapter backed by the InformationModel.

    Used for development, testing, and simulation via POST /simulate/sensor-trigger.
    """

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
        """
        'Connect' to the mock adapter — loads initial state into the model
        and marks the adapter as connected.
        """
        self._connected = True
        logger.info(
            "MockOpcUaAdapter '%s': connected (mock, %d initial nodes).",
            self._module_id, len(self._initial_state),
        )

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("MockOpcUaAdapter '%s': disconnected.", self._module_id)

    async def read_node(self, node_id: str) -> Any:
        """Read a node value from the InformationModel."""
        value = self._model.get_node(node_id)
        if value is None:
            logger.warning(
                "MockOpcUaAdapter '%s': read_node('%s') — node not found.",
                self._module_id, node_id,
            )
        return value

    async def write_node(self, node_id: str, value: Any) -> bool:
        """Write a value to the InformationModel (simulates actuator command)."""
        changed = await self._model.update_node(node_id, value)
        if not changed:
            logger.debug(
                "MockOpcUaAdapter '%s': write_node('%s', %r) — value unchanged.",
                self._module_id, node_id, value,
            )
        return changed

    async def trigger_node(self, node_id: str, value: Any) -> bool:
        """
        Trigger a sensor or actuator node state change.

        This is the entry point for POST /simulate/sensor-trigger.
        Writes to the InformationModel and returns whether the value
        actually changed (False if the node was already in that state).

        Args:
            node_id: The node to trigger (e.g. "BG56").
            value:   The new value (e.g. True for a proximity sensor detection).

        Returns:
            True if the node's value changed, False if it was already equal.
        """
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
        """Direct access to the underlying InformationModel (for testing)."""
        return self._model