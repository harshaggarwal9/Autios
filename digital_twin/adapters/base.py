from abc import ABC, abstractmethod
from typing import Any


class AbstractHardwareAdapter(ABC):
 

    def __init__(self, module_id: str) -> None:
        self._module_id = module_id

    @property
    def module_id(self) -> str:
        return self._module_id

    @abstractmethod
    async def connect(self) -> None:
        pass




    @abstractmethod
    async def disconnect(self) -> None:
        pass




    @abstractmethod
    async def read_node(self, node_id: str) -> Any:
        pass









    @abstractmethod
    async def write_node(self, node_id: str, value: Any) -> bool:
        pass







