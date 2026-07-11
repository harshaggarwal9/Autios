import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventCreate(BaseModel):

    scope: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Module/layer that produced the event, e.g. 'Inspection Station', "
            "'MES'. Must match a subscription scope in agent_subscriptions."
        ),
        examples=["Inspection Station", "MES"],
    )
    source: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Producer within the scope: 'System', 'Operator', 'Manager'.",
        examples=["System", "Operator"],
    )
    text: str = Field(
        ...,
        min_length=1,
        description="High-semantic event description as it will appear in the LLM prompt.",
        examples=["BG51 detects a workpiece at the holder H2 on conveyor C1."],
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured payload (node_id, raw value, etc.).",
    )

    @field_validator("scope", "source")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class EventRead(BaseModel):


    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )

    id: uuid.UUID
    sequence_id: int
    scope: str
    source: str
    text: str



    metadata: dict[str, Any] | None = Field(default=None, alias="event_metadata")
    created_at: datetime

    @property
    def formatted_label(self) -> str:

        ts = self.created_at.strftime("%H:%M:%S")
        return f"[{self.scope}][{self.source}][{ts}] {self.text}"


class EventBatch(BaseModel):


    events: list[EventRead]
    total_count: int

    latest_sequence_id: int | None = None
