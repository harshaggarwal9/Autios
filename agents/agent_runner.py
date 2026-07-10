"""
agents/agent_runner.py
───────────────────────
AgentRunner — creates, starts, and shuts down all agent instances.

Paper connection (§III.B — Agent System 𝒜𝒮):
  Manages the lifecycle of all three agent types:
    - OPERATOR: one per automation module
    - MANAGER:  exactly one (agent_id="manager")
    - SUMMARIZATION: one optional background summarizer (Phase 6)

  Adding a new module only requires a new YAML + seeded DB row.

Phase 6 additions:
  - dataset_recorder: optional DatasetRecorder injected into all agents
  - enable_summarization: start a SummarizationAgent background task
  - summary_types / summary_interval_seconds: summarization config

Dependencies:
  agents.operator_agent.OperatorAgent
  agents.manager_agent.ManagerAgent
  agents.summarization_agent.SummarizationAgent, SummaryType
  command.interface_manager.CommandInterfaceManager
  dataset.recorder.DatasetRecorder
  llm.client.GeminiClient
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.base_agent import BaseAgent
from agents.manager_agent import ManagerAgent
from agents.operator_agent import OperatorAgent
from agents.summarization_agent import SummarizationAgent, SummaryType
from command.interface_manager import CommandInterfaceManager
from config.module_loader import ModuleConfig
from core.subscription.registry import SubscriptionRegistry
from dataset.recorder import DatasetRecorder
from db.models.agent import Agent, AgentType
from llm.client import GeminiClient

logger = logging.getLogger(__name__)

MANAGER_AGENT_ID = "manager"


class AgentRunner:
    """
    Manages the lifecycle of all agent instances.
    Held on app.state.agent_runner.
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._llm_client: GeminiClient | None = None

    async def start(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        module_configs: dict[str, ModuleConfig],
        subscription_registry: SubscriptionRegistry,
        command_interface_manager: CommandInterfaceManager,
        dataset_recorder: DatasetRecorder | None = None,
        enable_summarization: bool = False,
        summary_types: list[SummaryType] | None = None,
        summary_interval_seconds: float = 60.0,
    ) -> None:
        """
        Load all agents from DB and start their run_loop tasks.

        Phase 6 additions:
            dataset_recorder:         optional DatasetRecorder for auto dataset creation.
            enable_summarization:     start a SummarizationAgent background task.
            summary_types:            which summary types to generate.
            summary_interval_seconds: how often to generate summaries.
        """
        self._llm_client = GeminiClient()

        await self._start_operator_agents(
            session_factory, module_configs, subscription_registry,
            command_interface_manager, dataset_recorder,
        )
        await self._start_manager_agent(
            session_factory, module_configs, dataset_recorder
        )

        if enable_summarization:
            await self._start_summarization_agent(
                session_factory, summary_types, summary_interval_seconds
            )

        logger.info(
            "AgentRunner: %d agent(s) running: %s",
            len(self._agents), list(self._agents.keys()),
        )

    async def _start_operator_agents(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        module_configs: dict[str, ModuleConfig],
        subscription_registry: SubscriptionRegistry,
        command_interface_manager: CommandInterfaceManager,
        dataset_recorder: DatasetRecorder | None = None,
    ) -> None:
        """Query DB for OPERATOR agents and start one OperatorAgent per row."""
        async with session_factory() as db:
            result = await db.execute(
                select(Agent).where(Agent.agent_type == AgentType.OPERATOR)
            )
            agent_rows: list[Agent] = list(result.scalars().all())

        if not agent_rows:
            logger.warning(
                "AgentRunner: no OPERATOR agents found. "
                "Run 'python scripts/seed_db.py' to create agent rows."
            )
            return

        for row in agent_rows:
            if not row.agent_id.endswith("_operator"):
                logger.warning(
                    "Agent '%s' does not follow '{module_id}_operator' "
                    "naming convention — skipping.", row.agent_id
                )
                continue

            module_id = row.agent_id[: -len("_operator")]

            if module_id not in module_configs:
                logger.warning(
                    "Agent '%s' maps to module_id='%s' but no ModuleConfig "
                    "found — skipping.", row.agent_id, module_id,
                )
                continue

            try:
                command_interface = command_interface_manager.get_interface(
                    module_id
                )
            except KeyError:
                logger.warning(
                    "Agent '%s': no CommandInterface for '%s' — skipping.",
                    row.agent_id, module_id,
                )
                continue

            agent = OperatorAgent(
                agent_id=row.agent_id,
                agent_db_id=row.id,
                module_config=module_configs[module_id],
                session_factory=session_factory,
                subscription_registry=subscription_registry,
                llm_client=self._llm_client,
                command_interface=command_interface,
                dataset_recorder=dataset_recorder,
            )

            await agent.start()
            self._agents[row.agent_id] = agent
            logger.info(
                "OperatorAgent '%s' started for module '%s'.",
                row.agent_id, module_id,
            )

    async def _start_manager_agent(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        module_configs: dict[str, ModuleConfig],
        dataset_recorder: DatasetRecorder | None = None,
    ) -> None:
        """Query DB for the 'manager' agent row and start ManagerAgent."""
        async with session_factory() as db:
            result = await db.execute(
                select(Agent).where(
                    Agent.agent_id == MANAGER_AGENT_ID,
                    Agent.agent_type == AgentType.MANAGER,
                )
            )
            manager_row = result.scalar_one_or_none()

        if manager_row is None:
            logger.warning(
                "AgentRunner: no 'manager' agent found — ManagerAgent will "
                "not start. Run 'python scripts/seed_db.py' to create it."
            )
            return

        manager = ManagerAgent(
            agent_id=manager_row.agent_id,
            agent_db_id=manager_row.id,
            session_factory=session_factory,
            module_configs=module_configs,
            dataset_recorder=dataset_recorder,
        )

        await manager.start()
        self._agents[manager_row.agent_id] = manager
        logger.info("ManagerAgent '%s' started.", manager_row.agent_id)

    async def _start_summarization_agent(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        summary_types: list[SummaryType] | None,
        summary_interval_seconds: float,
    ) -> None:
        """Create and start the SummarizationAgent background task."""
        import asyncio as _asyncio
        summ_db_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        agent = SummarizationAgent(
            agent_id="summarization_agent",
            agent_db_id=summ_db_id,
            session_factory=session_factory,
            llm_client=self._llm_client,
            summary_types=summary_types or [SummaryType.PRODUCTION],
            summary_interval_seconds=summary_interval_seconds,
        )

        # Launch run_loop directly — no start() call since there is no
        # real Agent DB row to write status to
        task = _asyncio.create_task(
            agent.run_loop(),
            name="summarization_agent",
        )
        agent._task = task
        agent._running = True
        self._agents["summarization_agent"] = agent

        logger.info(
            "SummarizationAgent started (types=%s, interval=%.0fs).",
            [t.value for t in (summary_types or [SummaryType.PRODUCTION])],
            summary_interval_seconds,
        )

    async def stop(self) -> None:
        """Stop all running agents gracefully."""
        for agent_id, agent in self._agents.items():
            await agent.stop()
            logger.info("Agent '%s' stopped.", agent_id)

        self._agents.clear()
        logger.info("AgentRunner: all agents stopped.")

    def get_agent(self, agent_id: str) -> BaseAgent | None:
        return self._agents.get(agent_id)

    def all_agent_ids(self) -> list[str]:
        return list(self._agents.keys())

    def agent_count(self) -> int:
        return len(self._agents)