
import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.event_log import EventLog
from schemas.event import EventBatch, EventCreate, EventRead

logger = logging.getLogger(__name__)


class EventLogStore:
    

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def append(self, event: EventCreate) -> EventRead:
        
        row = EventLog(
            scope=event.scope,
            source=event.source,
            text=event.text,
            event_metadata=event.metadata,
        )
        self._db.add(row)
        await self._db.flush()

        logger.debug(
            "EventLogStore.append: seq=%d scope=%r source=%r text=%r",
            row.sequence_id, row.scope, row.source, row.text[:60],
        )

        return EventRead.model_validate(row, from_attributes=True)

    async def append_many(self, events: list[EventCreate]) -> list[EventRead]:

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



    async def get_events_since(
        self,
        after_sequence_id: int,
        limit: int = 50,
        scopes: list[str] | None = None,
    ) -> EventBatch:
        


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
        
        result = await self._db.execute(
            select(EventLog).where(EventLog.sequence_id == sequence_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return EventRead.model_validate(row, from_attributes=True)

    async def get_latest_sequence_id(self) -> int:
        


        result = await self._db.execute(
            select(func.max(EventLog.sequence_id))
        )
        value = result.scalar_one_or_none()
        return value if value is not None else 0

    async def count_events(self, scopes: list[str] | None = None) -> int:
        
        query = select(func.count(EventLog.id))
        if scopes:
            query = query.where(EventLog.scope.in_(scopes))
        result = await self._db.execute(query)
        return result.scalar_one_or_none() or 0
