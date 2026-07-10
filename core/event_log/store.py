"""
core/event_log/store.py
────────────────────────
EventLogStore — the single write and read interface for the event_log table.

Paper connection (§III.B — Event Log Memory ℰ):
  "The event log ℰ is a persistent, ordered record of all events in the system.
  Agents append to it and read from it using a cursor (last processed
  sequence_id)."

  This class is the only component that writes to or reads from event_log.
  Every other component (DataObserver, OperatorAgent, ManagerAgent,
  SubscriptionEngine) goes through this store — never through raw SQLAlchemy
  queries on the EventLog model.

Design decisions:
  1. append() / append_many() return the persisted EventRead schema so callers
     can immediately access the server-assigned sequence_id without a
     second query.
  2. get_events_since() is the SubscriptionEngine's read path — it takes a
     cursor (after_sequence_id) and an optional list of scope filters.
  3. All methods accept an AsyncSession injected by the caller — the store
     does NOT manage its own session lifecycle (that is the caller's
     responsibility, keeping the store stateless and testable).

Dependencies:
  db.models.event_log.EventLog, schemas.event.EventCreate/EventRead,
  sqlalchemy async
"""

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.event_log import EventLog
from schemas.event import EventBatch, EventCreate, EventRead

logger = logging.getLogger(__name__)


class EventLogStore:
    """
    Stateless read/write interface for the event_log table.

    One instance is created per request (or per agent loop iteration)
    from an injected AsyncSession. The instance holds no state beyond
    the session reference — it is safe to create and discard freely.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Write ─────────────────────────────────────────────────────────────────

    async def append(self, event: EventCreate) -> EventRead:
        """
        Append a single event to the log.

        Returns the persisted EventRead (including the server-assigned
        sequence_id and created_at) without requiring a separate query.

        The caller is responsible for calling db.commit() after this method
        returns — the store deliberately does not commit so that callers
        can batch multiple appends in a single transaction.
        """
        row = EventLog(
            scope=event.scope,
            source=event.source,
            text=event.text,
            event_metadata=event.metadata,
        )
        self._db.add(row)
        await self._db.flush()  # populates sequence_id and id from the DB

        logger.debug(
            "EventLogStore.append: seq=%d scope=%r source=%r text=%r",
            row.sequence_id, row.scope, row.source, row.text[:60],
        )

        return EventRead.model_validate(row, from_attributes=True)

    async def append_many(self, events: list[EventCreate]) -> list[EventRead]:
        """
        Append multiple events in a single flush.

        More efficient than calling append() in a loop because the DB round-trip
        (flush) is performed once for all rows.

        Returns EventRead objects in the same order as the input list.
        """
        if not events:
            return []

        rows = [
            EventLog(
                scope=e.scope,
                source=e.source,
                text=e.text,
                event_metadata=e.metadata,
            )
            for e in events
        ]
        for row in rows:
            self._db.add(row)

        await self._db.flush()

        results = [
            EventRead.model_validate(row, from_attributes=True)
            for row in rows
        ]

        logger.debug(
            "EventLogStore.append_many: %d events flushed (seq %d–%d)",
            len(rows),
            rows[0].sequence_id,
            rows[-1].sequence_id,
        )

        return results

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_events_since(
        self,
        after_sequence_id: int,
        limit: int = 50,
        scopes: list[str] | None = None,
    ) -> EventBatch:
        """
        Return events with sequence_id > after_sequence_id.

        This is the SubscriptionEngine's primary read path — it calls this
        method on every agent poll cycle with the agent's current cursor.

        Args:
            after_sequence_id: The agent's current cursor. Returns events
                               strictly AFTER this sequence_id.
            limit:             Max events to return per call (default 50).
                               The SubscriptionEngine uses this to bound
                               memory usage on the agent's event window.
            scopes:            Optional list of scope strings to filter by.
                               If None (or empty), returns events from all scopes.
                               Used by the SubscriptionEngine to implement
                               per-agent scope filtering.

        Returns:
            EventBatch containing the matching events (oldest first) and the
            highest sequence_id in the batch (for cursor advancement).
        """
        query = (
            select(EventLog)
            .where(EventLog.sequence_id > after_sequence_id)
            .order_by(EventLog.sequence_id.asc())
            .limit(limit)
        )

        if scopes:
            query = query.where(EventLog.scope.in_(scopes))

        result = await self._db.execute(query)
        rows = list(result.scalars().all())

        events = [EventRead.model_validate(row, from_attributes=True) for row in rows]
        latest_seq = rows[-1].sequence_id if rows else None

        return EventBatch(
            events=events,
            total_count=len(events),
            latest_sequence_id=latest_seq,
        )

    async def get_recent_events(
        self,
        limit: int = 100,
        scopes: list[str] | None = None,
    ) -> EventBatch:
        """
        Return the most recent N events, newest first.

        Used by the SummarizationAgent and the GET /events API endpoint.
        Unlike get_events_since(), this does not take a cursor — it always
        returns the tail of the log.

        Args:
            limit:  Max number of events to return.
            scopes: Optional scope filter (same semantics as get_events_since).

        Returns:
            EventBatch with events in descending sequence_id order (newest first).
        """
        query = (
            select(EventLog)
            .order_by(EventLog.sequence_id.desc())
            .limit(limit)
        )

        if scopes:
            query = query.where(EventLog.scope.in_(scopes))

        result = await self._db.execute(query)
        rows = list(result.scalars().all())

        events = [EventRead.model_validate(row, from_attributes=True) for row in rows]
        latest_seq = rows[0].sequence_id if rows else None

        return EventBatch(
            events=events,
            total_count=len(events),
            latest_sequence_id=latest_seq,
        )

    async def get_event_by_sequence(self, sequence_id: int) -> EventRead | None:
        """Return one event by exact sequence_id, or None if not found."""
        result = await self._db.execute(
            select(EventLog).where(EventLog.sequence_id == sequence_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return EventRead.model_validate(row, from_attributes=True)

    async def get_latest_sequence_id(self) -> int:
        """
        Return the current maximum sequence_id in the log.

        Returns 0 if the log is empty (so agents starting fresh begin
        their cursor at 0, which get_events_since treats as "from the beginning").
        """
        result = await self._db.execute(
            select(func.max(EventLog.sequence_id))
        )
        value = result.scalar_one_or_none()
        return value if value is not None else 0

    async def count_events(self, scopes: list[str] | None = None) -> int:
        """Return the total number of events, optionally filtered by scope."""
        query = select(func.count(EventLog.id))
        if scopes:
            query = query.where(EventLog.scope.in_(scopes))
        result = await self._db.execute(query)
        return result.scalar_one_or_none() or 0