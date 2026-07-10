"""
digital_twin/data_observer/rule_engine.py
──────────────────────────────────────────
RuleEngine — evaluates node state transitions against a YAML rule set
and returns zero or more semantic event descriptions.

Paper connection (§II.B — Digital Twins and Semantics, Figure 3):
  "The data observer converts data in information models into textual
  expressions on different semantic abstraction levels. We pre-define
  the rules determining which events should be emitted on data changes."

  Each rule in the YAML file maps:
    (node_id, from_value, to_value) → (scope, source, text)

  The text is what appears verbatim in the LLM prompt's event log section:
    [Inspection Station][System][00:01:41] BG56 detects a workpiece...

Rule format (YAML):
  rules:
    - node_id: BG56
      from_value: false       # null = match any previous value
      to_value: true
      source: "System"
      text: "BG56 detects a workpiece at the infeed of conveyor C1."

Rule matching:
  - from_value: null in YAML matches ANY previous value (transition INTO to_value)
  - from_value: a specific value matches only that exact previous value
  - to_value: always matched exactly against the new value

Dependencies:
  pyyaml, pathlib (stdlib)
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SemanticEvent:
    """A semantic event description produced by a matching rule."""
    scope: str
    source: str
    text: str


@dataclass
class Rule:
    """One transition rule loaded from the YAML file."""
    node_id: str
    from_value: Any  # None means "match any previous value"
    to_value: Any
    source: str
    text: str


class RuleEngine:
    """
    Evaluates node state transitions against a pre-defined YAML rule set.

    One RuleEngine instance per module, loaded once at startup.
    evaluate() is called by the DataObserver for every changed node.
    """

    def __init__(self, module_id: str, scope: str, rules: list[Rule]) -> None:
        self._module_id = module_id
        self._scope = scope
        self._rules = rules

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "RuleEngine":
        """
        Load and parse a *_rules.yaml file into a RuleEngine.

        Args:
            yaml_path: Absolute or relative path to a *_rules.yaml file.

        Returns:
            A fully configured RuleEngine instance.

        Raises:
            FileNotFoundError: if yaml_path does not exist.
            KeyError / ValueError: if required fields are missing or invalid.
        """
        if not yaml_path.exists():
            raise FileNotFoundError(f"Rules file not found: {yaml_path}")

        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

        module_id = raw["module_id"]
        scope = raw.get("scope", module_id)
        default_source = raw.get("default_source", "System")

        rules: list[Rule] = []
        for entry in raw.get("rules", []):
            rules.append(Rule(
                node_id=entry["node_id"],
                from_value=entry.get("from_value"),   # None if not specified
                to_value=entry["to_value"],
                source=entry.get("source", default_source),
                text=entry["text"],
            ))

        logger.info(
            "RuleEngine '%s': loaded %d rule(s) from '%s'.",
            module_id, len(rules), yaml_path.name,
        )
        return cls(module_id=module_id, scope=scope, rules=rules)

    def evaluate(
        self,
        node_id: str,
        old_value: Any,
        new_value: Any,
    ) -> list[SemanticEvent]:
        """
        Evaluate a state transition against all rules for this module.

        Args:
            node_id:   The node that changed (e.g. "BG56", "C1_running").
            old_value: The value the node held before the change.
            new_value: The value the node now holds.

        Returns:
            A list of SemanticEvent objects (usually 0 or 1) for transitions
            that matched one or more rules. Multiple matches are intentional
            for nodes with multiple semantic meanings at different abstraction
            levels.
        """
        matched: list[SemanticEvent] = []

        for rule in self._rules:
            if rule.node_id != node_id:
                continue

            # to_value must always match exactly
            if rule.to_value != new_value:
                continue

            # from_value: None means "match any previous value"
            if rule.from_value is not None and rule.from_value != old_value:
                continue

            matched.append(SemanticEvent(
                scope=self._scope,
                source=rule.source,
                text=rule.text,
            ))

        return matched

    @property
    def module_id(self) -> str:
        return self._module_id

    @property
    def scope(self) -> str:
        return self._scope

    def rule_count(self) -> int:
        return len(self._rules)

    def __repr__(self) -> str:
        return (
            f"<RuleEngine module_id={self._module_id!r} "
            f"rules={len(self._rules)}>"
        )