import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SemanticEvent:
    
    scope: str
    source: str
    text: str


@dataclass
class Rule:
    
    node_id: str
    from_value: Any
    to_value: Any
    source: str
    text: str


class RuleEngine:


    def __init__(self, module_id: str, scope: str, rules: list[Rule]) -> None:
        self._module_id = module_id
        self._scope = scope
        self._rules = rules

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "RuleEngine":

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
                from_value=entry.get("from_value"),
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
 
        matched: list[SemanticEvent] = []

        for rule in self._rules:
            if rule.node_id != node_id:
                continue


            if rule.to_value != new_value:
                continue


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
