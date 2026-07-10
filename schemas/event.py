"""
schemas/event.py
────────────────
Pydantic v2 schemas for the EventLog domain.

Design rationale:
  These schemas are the boundary between the API layer (FastAPI route handlers)
  and the service layer (EventLogStore). They are distinct from the ORM models
  to keep the API contract stable even if the database schema evolves.

  Three schemas:
    EventCreate  — incoming payload for POST /events
    EventRead    — outgoing payload for GET /events
    EventBatch   — a list of EventRead rows returned by subscription queries

Paper connection (§III.B — Event Log Memory ℰ):
  The three-label format "[scope][source][timestamp] text" from prompt_example.txt
  is reconstructed in EventRead.formatted_label, which is exactly what the
  PromptConstructionEngine (Phase 4) includes verbatim in the LLM prompt.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventCreate(BaseModel):
    """
    Payload for creating a new event. Used by:
    - POST /events (API route)
    - DataObserver (emits events programmatically)
    - ManagerAgent (emits task assignment events)
    - OperatorAgent (emits command confirmation events)
    """

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
    """
    Full event as returned by the API and consumed by agents.

    formatted_label is the paper's bracketed format:
      "[Inspection Station][System][00:01:50] BG51 detects a workpiece…"
    The PromptConstructionEngine uses this string verbatim in the LLM prompt.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,  # allows using either 'metadata' or 'event_metadata'
    )

    id: uuid.UUID
    sequence_id: int
    scope: str
    source: str
    text: str
    # The DB column is named "event_metadata" (renamed from "metadata" to avoid
    # shadowing SQLAlchemy's Table.metadata attribute). populate_by_name=True
    # means callers can pass either key name.
    metadata: dict[str, Any] | None = Field(default=None, alias="event_metadata")
    created_at: datetime

    @property
    def formatted_label(self) -> str:
        """
        Assembles the paper's three-label event format for LLM prompt inclusion.

        Format: [scope][source][HH:MM:SS] text
        Matches prompt_example.txt exactly.
        """
        ts = self.created_at.strftime("%H:%M:%S")
        return f"[{self.scope}][{self.source}][{ts}] {self.text}"


class EventBatch(BaseModel):
    """A batch of events returned by subscription queries."""

    events: list[EventRead]
    total_count: int
    # The highest sequence_id in this batch — agents advance their cursor to this
    latest_sequence_id: int | None = None