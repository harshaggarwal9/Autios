"""
digital_twin/adapters/base.py
──────────────────────────────
AbstractHardwareAdapter — the ABC that all hardware adapters must implement.

Paper connection (§II.A — Hardware Interface):
  "The system interfaces with physical PLCs and sensors via OPC UA."
  This ABC defines the contract that both the MockOpcUaAdapter (testing)
  and a real OPC UA adapter (production) must satisfy, allowing the rest
  of the system to be hardware-agnostic.

In production, swap MockOpcUaAdapter for a real OPC UA implementation
that subclasses this ABC without changing any other code.
"""

from abc import ABC, abstractmethod
from typing import Any


class AbstractHardwareAdapter(ABC):
    """
    Hardware adapter ABC — defines the interface for reading and writing
    node values on a physical (or simulated) automation module.
    """

    def __init__(self, module_id: str) -> None:
        self._module_id = module_id

    @property
    def module_id(self) -> str:
        return self._module_id

    @abstractmethod
    async def connect(self) -> None:
        """
        Establish a connection to the hardware (or simulation).
        Called once at startup by AdapterManager.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Cleanly close the hardware connection.
        Called at shutdown by AdapterManager.
        """

    @abstractmethod
    async def read_node(self, node_id: str) -> Any:
        """
        Read the current value of a hardware node.

        Args:
            node_id: The node identifier (e.g. "BG51", "H2", "C1_running").

        Returns:
            The current value of the node (bool, str, float, etc.).
        """

    @abstractmethod
    async def write_node(self, node_id: str, value: Any) -> bool:
        """
        Write a value to a hardware node (e.g. actuator command).

        Args:
            node_id: The node identifier.
            value:   The value to write.

        Returns:
            True if the write succeeded, False otherwise.
        """