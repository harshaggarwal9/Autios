"""
core/subscription/engine.py
─────────────────────────────
SubscriptionEngine — delivers filtered event batches to agents.

Paper connection (§III.B — Agent System 𝒜𝒮):
  "Each agent subscribes to a subset of event scopes and receives only the
  events relevant to its responsibilities."

  This engine implements that filtering. Given an agent_id and its last
  processed sequence_id (cursor), poll_once() returns only the events in
  the agent's subscribed scopes that the agent has not yet seen.

  poll_once() is called by OperatorAgent and SummarizationAgent on every
  iteration of their run_loop(). It is deliberately stateless — the cursor
  is owned and persisted by the agent, not by this engine.

Design:
  - poll_once() is the primary interface — one call, one batch returned.
  - continuous_poll() is an AsyncIterator wrapper for agents that want to
    drive their own sleep/retry loop.
  - Both methods delegate filtering to EventLogStore.get_events_since()
    with the agent's scope list from SubscriptionRegistry.

Dependencies:
  core.event_log.store.EventLogStore
  core.subscription.registry.SubscriptionRegistry
  schemas.event.EventBatch
  sqlalchemy async
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.event_log.store import EventLogStore
from core.subscription.registry import SubscriptionRegistry
from schemas.event import EventBatch

logger = logging.getLogger(__name__)


class SubscriptionEngine:
    """
    Delivers filtered event batches to one agent type.

    One SubscriptionEngine instance is created per OperatorAgent instance.
    It holds a reference to the shared SubscriptionRegistry (loaded once at
    startup) and uses it to resolve the agent's scope list on every poll.

    The engine is stateless with respect to cursor position — the agent
    passes its current cursor on every call to poll_once().
    """

    def __init__(self, subscription_registry: SubscriptionRegistry) -> None:
        self._registry = subscription_registry

    async def poll_once(
        self,
        agent_id: str,
        after_sequence_id: int,
        db: AsyncSession,
        limit: int = 50,
    ) -> EventBatch:
        """
        Return events for agent_id since after_sequence_id.

        This is the hot path — called on every agent loop iteration.

        Args:
            agent_id:           The agent's string identifier (e.g.
                                "inspection_station_operator"). Used to
                                look up the agent's subscribed scopes.
            after_sequence_id:  The agent's current cursor — only events
                                with sequence_id > this value are returned.
            db:                 Open AsyncSession for the EventLogStore query.
            limit:              Max events to return in one batch.

        Returns:
            EventBatch. If no new events exist, batch.events is empty and
            batch.latest_sequence_id is None (caller should sleep before
            retrying).
        """
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
        """
        Async iterator that yields non-empty EventBatch objects as they arrive.

        The iterator:
          1. Opens a fresh DB session for each poll (avoids long-lived
             transactions that accumulate uncommitted state).
          2. Calls poll_once().
          3. If events are found, yields the batch and advances the internal
             cursor to the batch's latest_sequence_id.
          4. If no events, sleeps for poll_interval_seconds before retrying.

        This is a convenience wrapper for agents that want a simple
        "for batch in engine.continuous_poll(...)" loop. Agents that need
        more control over error handling and cursor persistence (like
        OperatorAgent) call poll_once() directly in their own run_loop().

        Usage:
            async for batch in engine.continuous_poll("my_agent", cursor, factory):
                for event in batch.events:
                    process(event)

        Args:
            agent_id:              Agent identifier for scope lookup.
            after_sequence_id:     Initial cursor position.
            session_factory:       Factory for creating per-poll DB sessions.
            limit:                 Max events per batch.
            poll_interval_seconds: Sleep duration between empty polls.

        Yields:
            EventBatch objects containing at least one event each.
            Empty batches are consumed internally and never yielded.
        """
        # Use a local cursor variable — does NOT write back to the DB.
        # Callers that need cursor persistence should use poll_once() directly.
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