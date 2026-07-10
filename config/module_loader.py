"""
config/module_loader.py
───────────────────────
Loads per-module YAML configuration files and validates them into typed
Pydantic models.

Design rationale:
  Every downstream component (PromptConstructionEngine, DataObserver,
  FunctionRegistry) needs module configuration.  Instead of passing raw dicts
  around and risking key-name typos, we parse YAML into typed models here once
  at startup.  Any schema mismatch fails loudly at boot rather than silently
  at the first LLM call or hardware dispatch.

Paper connection (Table I, §III.C):
  The Pydantic models mirror the five named prompt sections from Table I:
    ModuleConfig.role_definition        → Role Definition  (ℛ_AMi)
    ModuleConfig.component_description  → Component Description (𝒞_Mi)
    ModuleConfig.callable_functions     → Callable Functions (ℱ_Mi)
    ModuleConfig.standard_operation...  → SOP (SOP_AMi)
    ModuleConfig.auxiliary_instruction  → Auxiliary Instruction

Dependencies:
  pyyaml, pydantic v2, pathlib (stdlib)
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ── Sub-models for Component Description section ──────────────────────────────

class ConveyorConfig(BaseModel):
    id: str
    description: str


class SensorConfig(BaseModel):
    node_id: str
    type: str  # "proximity" | "rfid"
    description: str


class ActuatorConfig(BaseModel):
    node_id: str
    type: str  # "holder" | "switch"
    description: str


class ComponentDescriptionConfig(BaseModel):
    conveyors: list[ConveyorConfig] = Field(default_factory=list)
    sensors: list[SensorConfig] = Field(default_factory=list)
    actuators: list[ActuatorConfig] = Field(default_factory=list)


# ── Sub-models for Callable Functions section ─────────────────────────────────

class FunctionParameterConfig(BaseModel):
    name: str
    type: str
    values: list[Any] = Field(default_factory=list)
    description: str = ""


class CallableFunctionConfig(BaseModel):
    function_name: str
    signature: str
    description: str
    parameters: list[FunctionParameterConfig] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


# ── Sub-model for Subscription scopes ────────────────────────────────────────

class SubscriptionConfig(BaseModel):
    scope: str


# ── Top-level module config — maps 1:1 to a YAML file ────────────────────────

class ModuleConfig(BaseModel):
    """
    Complete configuration for one automation module.

    This model is the typed representation of a module YAML file.
    It carries the exact five sections from the paper's Table I plus
    subscription metadata used by the SubscriptionEngine.
    """

    module_id: str
    display_name: str

    # Paper Table I — Section 1
    role_definition: str

    # Paper Table I — Section 2
    component_description: ComponentDescriptionConfig

    # Paper Table I — Section 3
    callable_functions: list[CallableFunctionConfig] = Field(default_factory=list)

    # Paper Table I — Section 4
    standard_operation_procedure: list[str] = Field(default_factory=list)

    # Paper Table I — Section 5 (formatting/output instructions)
    auxiliary_instruction: str

    # SubscriptionEngine metadata — which event scopes this module's agent reads
    subscriptions: list[SubscriptionConfig] = Field(default_factory=list)

    # ── Convenience helpers ───────────────────────────────────────────────────

    def get_function(self, name: str) -> CallableFunctionConfig | None:
        """Return a callable function config by its function_name, or None."""
        return next(
            (f for f in self.callable_functions if f.function_name == name),
            None,
        )

    def all_node_ids(self) -> list[str]:
        """Return every sensor and actuator node_id for this module."""
        sensor_ids = [s.node_id for s in self.component_description.sensors]
        actuator_ids = [a.node_id for a in self.component_description.actuators]
        return sensor_ids + actuator_ids

    def subscription_scopes(self) -> list[str]:
        """Return the list of event scope strings this module subscribes to."""
        return [s.scope for s in self.subscriptions]


# ── Loader functions ──────────────────────────────────────────────────────────

def load_module_config(yaml_path: Path) -> ModuleConfig:
    """
    Load and validate a single module YAML file.

    Raises:
        FileNotFoundError: if the path does not exist.
        pydantic.ValidationError: if the YAML schema is invalid.
        yaml.YAMLError: if the file is not valid YAML.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"Module config not found: {yaml_path}")

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return ModuleConfig.model_validate(raw)


def load_all_module_configs(modules_dir: Path) -> dict[str, ModuleConfig]:
    """
    Discover and load all *.yaml files under modules_dir.

    Returns a dict keyed by module_id (e.g. "inspection_station").
    Called once at application startup; result is injected into components
    that need module config (PromptBuilder, DataObserver, FunctionRegistry).

    Raises:
        ValueError: if two YAML files declare the same module_id.
    """
    configs: dict[str, ModuleConfig] = {}

    for yaml_file in sorted(modules_dir.glob("*.yaml")):
        # Skip rule files (DataObserver uses separate *_rules.yaml files)
        if yaml_file.stem.endswith("_rules"):
            continue

        cfg = load_module_config(yaml_file)

        if cfg.module_id in configs:
            raise ValueError(
                f"Duplicate module_id '{cfg.module_id}' found in "
                f"'{yaml_file}' — each module must have a unique ID."
            )
        configs[cfg.module_id] = cfg

    return configs


def load_rule_engines(modules_dir: Path) -> "dict[str, Any]":
    """
    Discover and load RuleEngine instances for all *_rules.yaml files.

    Returns a dict keyed by module_id (e.g. "inspection_station").
    Imported lazily to avoid circular imports at module level.

    Called once during application startup by the lifespan handler.
    """
    from digital_twin.data_observer.rule_engine import RuleEngine

    engines: dict[str, RuleEngine] = {}

    for yaml_file in sorted(modules_dir.glob("*_rules.yaml")):
        engine = RuleEngine.from_yaml(yaml_file)
        engines[engine.module_id] = engine

    return engines