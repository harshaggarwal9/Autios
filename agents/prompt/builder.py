

import logging

from config.module_loader import ModuleConfig
from schemas.event import EventRead

logger = logging.getLogger(__name__)


class PromptBuilder:
   

    def __init__(self, module_config: ModuleConfig) -> None:
        self._config = module_config

        self._static_sections = self._build_static_sections()

    def build(self, events: list[EventRead]) -> str:
        


        event_log_section = self._build_event_log_section(events)
        return f"{self._static_sections}{event_log_section}\nOutput:\n"

    def module_id(self) -> str:
        return self._config.module_id



    def _build_static_sections(self) -> str:
        



        cfg = self._config
        parts: list[str] = []


        parts.append("# Your role definition:")
        parts.append(cfg.role_definition.strip())
        parts.append("")


        parts.append("# Component description")

        for conveyor in cfg.component_description.conveyors:
            parts.append(f"Conveyor {conveyor.id}: {conveyor.description.strip()}")

        for sensor in cfg.component_description.sensors:
            parts.append(
                f"Sensor {sensor.node_id} ({sensor.type}): "
                f"{sensor.description.strip()}"
            )

        for actuator in cfg.component_description.actuators:
            parts.append(
                f"Actuator {actuator.node_id} ({actuator.type}): "
                f"{actuator.description.strip()}"
            )
        parts.append("")


        parts.append("# You can call the following functions")
        for fn in cfg.callable_functions:
            parts.append(f"{fn.signature}: {fn.description.strip()}")
            if fn.parameters:
                for param in fn.parameters:
                    values_str = (
                        f" Values: {param.values}" if param.values else ""
                    )
                    parts.append(
                        f"  - {param.name} ({param.type}):{values_str}"
                    )
            if fn.examples:
                for example in fn.examples:
                    parts.append(f"  Example: {example}")
        parts.append("")


        parts.append("# Standard operation procedure:")
        for step in cfg.standard_operation_procedure:
            parts.append(f"- {step.strip()}")
        parts.append("")


        parts.append("# Auxiliary Instruction:")
        parts.append(cfg.auxiliary_instruction.strip())
        parts.append("")

        return "\n".join(parts)

    @staticmethod
    def _build_event_log_section(events: list[EventRead]) -> str:


        if not events:
            return "Input:\n(no events)"

        lines = ["Input:"]
        for event in events:
            lines.append(event.formatted_label)
        return "\n".join(lines)
