"""
agents/prompt/builder.py
─────────────────────────
PromptBuilder — assembles the five-section LLM prompt described in Table I
of the paper.

Paper connection (§III.C — The Prompting Method, Table I):
  𝒫_AMi = Textual(ℛ_AMi, 𝒞_Mi, ℱ_Mi, SOP_AMi, ℰ_AMi)

  Section 1 — Role Definition        (ℛ_AMi)
  Section 2 — Component Description  (𝒞_Mi)
  Section 3 — Callable Functions     (ℱ_Mi)
  Section 4 — Standard Operation Procedure (SOP_AMi)
  Section 5 — Auxiliary Instruction

  The event log slice (ℰ_AMi) is appended after Section 5 as the Input:
  section. The Output: label is appended last — the LLM completes it.

Design:
  PromptBuilder is stateless — build once at startup, call build(events)
  on every agent loop iteration. The five static sections are assembled
  once in _build_static_sections() and cached; only the event log slice
  changes per call.

Dependencies:
  config.module_loader.ModuleConfig
  schemas.event.EventRead
"""

import logging

from config.module_loader import ModuleConfig
from schemas.event import EventRead

logger = logging.getLogger(__name__)


class PromptBuilder:
    """
    Assembles the paper's five-section prompt for one automation module.

    One PromptBuilder instance per OperatorAgent, created at startup.

    Usage:
        builder = PromptBuilder(module_config)
        prompt = builder.build(recent_events)
    """

    def __init__(self, module_config: ModuleConfig) -> None:
        self._config = module_config
        # Cache the static sections — they don't change between calls
        self._static_sections = self._build_static_sections()

    def build(self, events: list[EventRead]) -> str:
        """
        Assemble the complete prompt for one agent inference cycle.

        Args:
            events: The event log slice for this agent's subscription
                    window (ℰ_AMi). Formatted using each event's
                    formatted_label property to produce the paper's
                    [scope][source][timestamp] text format.

        Returns:
            The complete prompt string ready to be sent to the LLM.
        """
        event_log_section = self._build_event_log_section(events)
        return f"{self._static_sections}{event_log_section}\nOutput:\n"

    def module_id(self) -> str:
        return self._config.module_id

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_static_sections(self) -> str:
        """
        Build the four static sections (1–5 minus the event log).
        Called once at construction time and cached.
        """
        cfg = self._config
        parts: list[str] = []

        # Section 1: Role Definition
        parts.append("# Your role definition:")
        parts.append(cfg.role_definition.strip())
        parts.append("")

        # Section 2: Component Description
        parts.append("# Component description")
        # Conveyors
        for conveyor in cfg.component_description.conveyors:
            parts.append(f"Conveyor {conveyor.id}: {conveyor.description.strip()}")
        # Sensors
        for sensor in cfg.component_description.sensors:
            parts.append(
                f"Sensor {sensor.node_id} ({sensor.type}): "
                f"{sensor.description.strip()}"
            )
        # Actuators
        for actuator in cfg.component_description.actuators:
            parts.append(
                f"Actuator {actuator.node_id} ({actuator.type}): "
                f"{actuator.description.strip()}"
            )
        parts.append("")

        # Section 3: Callable Functions
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

        # Section 4: Standard Operation Procedure
        parts.append("# Standard operation procedure:")
        for step in cfg.standard_operation_procedure:
            parts.append(f"- {step.strip()}")
        parts.append("")

        # Section 5: Auxiliary Instruction
        parts.append("# Auxiliary Instruction:")
        parts.append(cfg.auxiliary_instruction.strip())
        parts.append("")

        return "\n".join(parts)

    @staticmethod
    def _build_event_log_section(events: list[EventRead]) -> str:
        """
        Build the dynamic Input: section from the event log slice.

        Uses EventRead.formatted_label which produces the paper's
        three-label format:
          [Inspection Station][System][00:01:41] BG56 detects a workpiece...
        """
        if not events:
            return "Input:\n(no events)"

        lines = ["Input:"]
        for event in events:
            lines.append(event.formatted_label)
        return "\n".join(lines)