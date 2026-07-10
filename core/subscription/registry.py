"""
core/subscription/registry.py
──────────────────────────────
SubscriptionRegistry — in-memory cache of agent → [scope] mappings.

Paper connection (§III.B — Agent System 𝒜𝒮):
  The paper's subscription set 𝒮(𝒜ℳi) defines which event scopes an agent
  reads. Loading these from the DB at startup and caching them in memory
  avoids a DB round-trip on every agent poll cycle.

  The registry is populated once at startup by load() and then read-only
  for the lifetime of the process. If subscriptions change at runtime
  (not expected in normal operation), the process must be restarted.

Design:
  - load() reads agent_subscriptions from the DB and builds a dict of
    agent_id → list[scope_string].
  - get_scopes(agent_id) is O(1) dict lookup — called on every poll cycle
    by the SubscriptionEngine.
  - set_subscriptions() allows tests to inject subscriptions without DB.

Dependencies:
  db.models.agent.Agent, AgentSubscription
  sqlalchemy async
"""

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.agent import Agent, AgentSubscription

logger = logging.getLogger(__name__)


class SubscriptionRegistry:
    """
    In-memory cache of agent_id → list[event_scope] mappings.

    Populated once at startup from the agent_subscriptions table.
    Thread-safe for read access (dict reads in CPython are GIL-protected);
    writes only happen during load() at startup.
    """

    def __init__(self) -> None:
        # agent_id (str) → list of event_scope strings
        self._subscriptions: dict[str, list[str]] = defaultdict(list)
        self._loaded = False

    async def load(self, db: AsyncSession) -> None:
        """
        Load all agent subscriptions from the database.

        Joins agents → agent_subscriptions to build the agent_id → scopes
        mapping. Called once during application startup (lifespan handler).

        After this call, is_loaded() returns True and get_scopes() is safe
        to call without a DB session.
        """
        result = await db.execute(
            select(Agent.agent_id, AgentSubscription.event_scope)
            .join(AgentSubscription, AgentSubscription.agent_id == Agent.id)
        )
        rows = result.all()

        self._subscriptions.clear()
        for agent_id, scope in rows:
            self._subscriptions[agent_id].append(scope)

        self._loaded = True

        logger.info(
            "SubscriptionRegistry loaded: %d agent(s), %d total subscription(s).",
            len(self._subscriptions),
            sum(len(s) for s in self._subscriptions.values()),
        )

    def get_scopes(self, agent_id: str) -> list[str]:
        """
        Return the list of event scopes the given agent subscribes to.

        Returns an empty list if the agent_id is not registered — this
        is not an error; it simply means the agent would receive no events.

        Raises:
            RuntimeError: if load() has not been called yet.
        """
        if not self._loaded:
            raise RuntimeError(
                "SubscriptionRegistry has not been loaded. "
                "Call await registry.load(db) during application startup."
            )
        return self._subscriptions.get(agent_id, [])

    def set_subscriptions(self, agent_id: str, scopes: list[str]) -> None:
        """
        Set subscriptions for one agent programmatically.

        Used by tests to inject subscriptions without a DB round-trip.
        Also useful for dynamic subscription changes (not expected in
        normal operation but supported for extensibility).
        """
        self._subscriptions[agent_id] = scopes
        self._loaded = True

    def all_agent_ids(self) -> list[str]:
        """Return all agent_ids that have at least one subscription."""
        return list(self._subscriptions.keys())

    def is_loaded(self) -> bool:
        return self._loaded