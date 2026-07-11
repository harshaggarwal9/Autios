






























import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.event_log.store import EventLogStore
from core.subscription.registry import SubscriptionRegistry
from schemas.event import EventBatch

logger = logging.getLogger(__name__)


class SubscriptionEngine:
    










    def __init__(self, subscription_registry: SubscriptionRegistry) -> None:
        self._registry = subscription_registry

    async def poll_once(
        self,
        agent_id: str,
        after_sequence_id: int,
        db: AsyncSession,
        limit: int = 50,
    ) -> EventBatch:
        


















        scopes = self._registry.get_scopes(agent_id)
        if not scopes:
            logger.debug(
                "SubscriptionEngine.poll_once: agent '%s' has no subscriptions.",
                agent_id,
            )
            return EventBatch(events=[], total_count=0, latest_sequence_id=None)

        store = EventLogStore(db)
        batch = await store.get_events_since(
            after_sequence_id=after_sequence_id,
            limit=limit,
            scopes=scopes,
        )

        if batch.events:
            logger.debug(
                "SubscriptionEngine.poll_once: agent '%s' received %d event(s) "
                "(seq %d–%d).",
                agent_id,
                len(batch.events),
                batch.events[0].sequence_id,
                batch.events[-1].sequence_id,
            )

        return batch

    async def continuous_poll(
        self,
        agent_id: str,
        after_sequence_id: int,
        session_factory: async_sessionmaker[AsyncSession],
        limit: int = 50,
        poll_interval_seconds: float = 0.5,
    ) -> AsyncIterator[EventBatch]:
        

































        fetch_cursor = after_sequence_id

        while True:
            try:
                async with session_factory() as db:
                    batch = await self.poll_once(
                        agent_id=agent_id,
                        after_sequence_id=fetch_cursor,
                        db=db,
                        limit=limit,
                    )

                if batch.events:
                    fetch_cursor = batch.latest_sequence_id
                    yield batch
                else:
                    await asyncio.sleep(poll_interval_seconds)

            except asyncio.CancelledError:
                logger.debug(
                    "SubscriptionEngine.continuous_poll: cancelled for agent '%s'.",
                    agent_id,
                )
                return

            except Exception as exc:
                logger.exception(
                    "SubscriptionEngine.continuous_poll: error for agent '%s': %s",
                    agent_id, exc,
                )
                await asyncio.sleep(poll_interval_seconds)
