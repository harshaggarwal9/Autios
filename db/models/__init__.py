"""
db/models/__init__.py
─────────────────────
Import all ORM models here so that:
1. Alembic's autogenerate discovers every table via Base.metadata.
2. Application startup can do `from db.models import *` to ensure all
   models are registered before the engine is used.

If you add a new model, add its import here.
"""

from db.models.agent import Agent, AgentSubscription, AgentStatus, AgentType
from db.models.automation_module import AutomationModule
from db.models.dataset import DatasetRecord, EvaluationResult, EvaluationRun
from db.models.event_log import EventLog
from db.models.inference_log import AgentCommandLog, CommandOutcome, LLMInferenceLog
from db.models.state_snapshot import ModuleStateSnapshot
from db.models.task import Task, TaskAssignment, TaskStatus

__all__ = [
    # Core paper components
    "AutomationModule",
    "Agent",
    "AgentSubscription",
    "AgentStatus",
    "AgentType",
    "EventLog",
    # Task management
    "Task",
    "TaskAssignment",
    "TaskStatus",
    # LLM inference
    "LLMInferenceLog",
    "AgentCommandLog",
    "CommandOutcome",
    # Digital twin
    "ModuleStateSnapshot",
    # Dataset & evaluation (Phase 6)
    "DatasetRecord",
    "EvaluationRun",
    "EvaluationResult",
]