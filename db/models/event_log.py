"""
db/models/event_log.py
──────────────────────
ORM model for the event_log table.

Paper connection (§III.B — Event Log Memory ℰ):
  This is the central data structure of the entire system. The paper formalizes
  the event log as:
    ℰ = {(e1,t1), (e2,t2), …, (et,tt) | t1 < t2 < … < tt}

  Key design decisions:
  1. sequence_id is a PostgreSQL BIGSERIAL — guarantees strict ordering
     independent of clock precision. The paper's t1 < t2 ordering is enforced
     by the sequence, not the wall clock.
  2. The table is append-only. No UPDATE or DELETE should ever touch it.
  3. The three-label format [scope][source][timestamp] text is stored in
     separate columns and assembled at read time by EventLogStore.
  4. event_metadata (JSONB) holds structured data from the DataObserver
     (e.g. {"node_id": "BG51", "value": true}) — not part of the prompt text.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Sequence, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, UUIDPrimaryKeyMixin

# Explicit Sequence object required for BIGSERIAL on a non-PK column.
# Using autoincrement=True alone on a non-PK BigInteger does NOT create
# a PostgreSQL sequence — this explicit Sequence does.
event_log_seq = Sequence("event_log_sequence_id_seq")


class EventLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "event_log"

    # ── Ordering column ───────────────────────────────────────────────────────
    # BIGSERIAL provides global event ordering independent of clock skew.
    # Not the PK (that's a UUID), but the sort key for all agent queries.
    sequence_id: Mapped[int] = mapped_column(
        BigInteger,
        event_log_seq,
        server_default=event_log_seq.next_value(),
        nullable=False,
        unique=True,
    )

    # ── Three-label fields (paper format: [scope][source][timestamp] text) ────
    # scope identifies which module/layer produced the event.
    # Matches the subscription scopes in agent_subscriptions.event_scope.
    scope: Mapped[str] = mapped_column(String(128), nullable=False)

    # source identifies the producer within the scope:
    # "System" (sensors/DataObserver), "Operator" (agent commands), "Manager"
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    # The high-semantic human-readable event text — appears verbatim in LLM prompt.
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Structured payload ────────────────────────────────────────────────────
    # Optional JSONB metadata (node_id, raw value, etc.) — not in prompt text.
    # Column renamed from "metadata" to "event_metadata" to avoid shadowing
    # SQLAlchemy's Table.metadata attribute.
    event_metadata: Mapped[dict | None] = mapped_column(
        "event_metadata",
        JSONB,
        nullable=True,
    )

    # ── Timestamp ─────────────────────────────────────────────────────────────
    # Wall-clock time. Used for human-readable prompt timestamps.
    # Do NOT sort by this column — use sequence_id for ordering.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    # Covers the SubscriptionEngine's core query: WHERE scope = ? AND sequence_id > ?
    __table_args__ = (
        Index("ix_event_log_scope_seq", "scope", "sequence_id"),
        Index("ix_event_log_sequence_id", "sequence_id"),
        Index("ix_event_log_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<EventLog seq={self.sequence_id} scope={self.scope!r} "
            f"source={self.source!r} text={self.text[:40]!r}>"
        )