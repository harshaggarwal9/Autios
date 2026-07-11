import asyncio
import logging
from copy import deepcopy
from typing import Any

from config.module_loader import ModuleConfig

logger = logging.getLogger(__name__)

StateDict = dict[str, Any]


class InformationModel:


    def __init__(self, module_config: ModuleConfig) -> None:
        self._module_id = module_config.module_id
        self._module_config = module_config


        self._state: StateDict = self._build_initial_state(module_config)





        self._previous_state: StateDict = deepcopy(self._state)



        self.change_event = asyncio.Event()

        logger.info(
            "InformationModel '%s' initialised with %d nodes.",
            self._module_id, len(self._state),
        )



    @staticmethod
    def _build_initial_state(cfg: ModuleConfig) -> StateDict:

        state: StateDict = {}


        for sensor in cfg.component_description.sensors:
            state[sensor.node_id] = False


        for actuator in cfg.component_description.actuators:
            if actuator.type == "holder":
                state[actuator.node_id] = True
            elif actuator.type == "switch":
                state[actuator.node_id] = "continue"
            else:
                state[actuator.node_id] = False


        for conveyor in cfg.component_description.conveyors:
            state[f"{conveyor.id}_running"] = False
            state[f"{conveyor.id}_direction"] = "forward"

        return state



    def get_node(self, node_id: str) -> Any:
        
        return self._state.get(node_id)

    def get_state(self) -> StateDict:
        
        return deepcopy(self._state)

    def get_previous_state(self) -> StateDict:
        
        return deepcopy(self._previous_state)

    async def update_node(self, node_id: str, value: Any) -> bool:

        if node_id not in self._state:
            logger.warning(
                "InformationModel '%s': update_node called for unknown "
                "node_id '%s'. Call register_node_if_absent() first.",
                self._module_id, node_id,
            )
            return False

        old_value = self._state[node_id]
        if old_value == value:
            return False

        self._previous_state[node_id] = old_value
        self._state[node_id] = value
        self.change_event.set()

        logger.debug(
            "InformationModel '%s': %s: %r → %r",
            self._module_id, node_id, old_value, value,
        )
        return True

    async def update_many(self, updates: dict[str, Any]) -> list[str]:
  
        changed: list[str] = []

        for node_id, value in updates.items():
            if node_id not in self._state:
                logger.warning(
                    "InformationModel '%s': update_many skipping unknown "
                    "node_id '%s'.", self._module_id, node_id,
                )
                continue

            old_value = self._state[node_id]
            if old_value != value:
                self._previous_state[node_id] = old_value
                self._state[node_id] = value
                changed.append(node_id)

        if changed:
            self.change_event.set()
            logger.debug(
                "InformationModel '%s': update_many changed %d node(s): %s",
                self._module_id, len(changed), changed,
            )

        return changed



    def get_changed_nodes(self) -> dict[str, tuple[Any, Any]]:

        changed: dict[str, tuple[Any, Any]] = {}
        for node_id, current_value in self._state.items():
            prev = self._previous_state.get(node_id)
            if current_value != prev:
                changed[node_id] = (prev, current_value)
        return changed

    def acknowledge_changes(self, node_ids: list[str]) -> None:
 
        for node_id in node_ids:
            if node_id in self._state:
                self._previous_state[node_id] = self._state[node_id]



    def update_from_snapshot(self, snapshot: StateDict) -> None:

        for key, value in snapshot.items():
            if key in self._state:
                self._state[key] = value
        self._previous_state = deepcopy(self._state)
        logger.info(
            "InformationModel '%s' restored from snapshot (%d nodes).",
            self._module_id, len(snapshot),
        )

    def register_node_if_absent(self, node_id: str, default_value: Any) -> None:

        if node_id not in self._state:
            self._state[node_id] = default_value
            self._previous_state[node_id] = default_value
            logger.debug(
                "InformationModel '%s': registered new node '%s' = %r",
                self._module_id, node_id, default_value,
            )



    @property
    def module_id(self) -> str:
        return self._module_id

    def node_ids(self) -> list[str]:
        return list(self._state.keys())

    def __repr__(self) -> str:
        return (
            f"<InformationModel module_id={self._module_id!r} "
            f"nodes={len(self._state)}>"
        )
