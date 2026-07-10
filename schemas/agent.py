import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from db.models.agent import AgentStatus, AgentType
from db.models.task import TaskStatus

class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: str
    agent_type: AgentType
    module_id: uuid.UUID | None
    last_event_sequence: int
    status: AgentStatus
    created_at: datetime


class AgentStatusUpdate(BaseModel):

    status: AgentStatus


class TaskCreate(BaseModel):

    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(
        ...,
        min_length=1,
        description="Natural-language task description sent to the Manager agent.",
        examples=["inspect the workpiece and load the workpiece on transport robot"],
    )


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    status: TaskStatus
    plan: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None