
























from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field




class ConveyorConfig(BaseModel):
    id: str
    description: str


class SensorConfig(BaseModel):
    node_id: str
    type: str
    description: str


class ActuatorConfig(BaseModel):
    node_id: str
    type: str
    description: str


class ComponentDescriptionConfig(BaseModel):
    conveyors: list[ConveyorConfig] = Field(default_factory=list)
    sensors: list[SensorConfig] = Field(default_factory=list)
    actuators: list[ActuatorConfig] = Field(default_factory=list)




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




class SubscriptionConfig(BaseModel):
    scope: str




class ModuleConfig(BaseModel):
    







    module_id: str
    display_name: str


    role_definition: str


    component_description: ComponentDescriptionConfig


    callable_functions: list[CallableFunctionConfig] = Field(default_factory=list)


    standard_operation_procedure: list[str] = Field(default_factory=list)


    auxiliary_instruction: str


    subscriptions: list[SubscriptionConfig] = Field(default_factory=list)



    def get_function(self, name: str) -> CallableFunctionConfig | None:
        
        return next(
            (f for f in self.callable_functions if f.function_name == name),
            None,
        )

    def all_node_ids(self) -> list[str]:
        
        sensor_ids = [s.node_id for s in self.component_description.sensors]
        actuator_ids = [a.node_id for a in self.component_description.actuators]
        return sensor_ids + actuator_ids

    def subscription_scopes(self) -> list[str]:
        
        return [s.scope for s in self.subscriptions]




def load_module_config(yaml_path: Path) -> ModuleConfig:
    







    if not yaml_path.exists():
        raise FileNotFoundError(f"Module config not found: {yaml_path}")

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return ModuleConfig.model_validate(raw)


def load_all_module_configs(modules_dir: Path) -> dict[str, ModuleConfig]:
    









    configs: dict[str, ModuleConfig] = {}

    for yaml_file in sorted(modules_dir.glob("*.yaml")):

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
    







    from digital_twin.data_observer.rule_engine import RuleEngine

    engines: dict[str, RuleEngine] = {}

    for yaml_file in sorted(modules_dir.glob("*_rules.yaml")):
        engine = RuleEngine.from_yaml(yaml_file)
        engines[engine.module_id] = engine

    return engines
