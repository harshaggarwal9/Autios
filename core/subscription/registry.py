

























import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.agent import Agent, AgentSubscription

logger = logging.getLogger(__name__)


class SubscriptionRegistry:
    







    def __init__(self) -> None:

        self._subscriptions: dict[str, list[str]] = defaultdict(list)
        self._loaded = False

    async def load(self, db: AsyncSession) -> None:
        








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
        








        if not self._loaded:
            raise RuntimeError(
                "SubscriptionRegistry has not been loaded. "
                "Call await registry.load(db) during application startup."
            )
        return self._subscriptions.get(agent_id, [])

    def set_subscriptions(self, agent_id: str, scopes: list[str]) -> None:
        






        self._subscriptions[agent_id] = scopes
        self._loaded = True

    def all_agent_ids(self) -> list[str]:
        
        return list(self._subscriptions.keys())

    def is_loaded(self) -> bool:
        return self._loaded
