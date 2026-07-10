"""
agents/base_agent.py
─────────────────────
BaseAgent — shared lifecycle, cursor management, and status tracking
for all agent types (Operator, Manager, Summarization).

Paper connection (§III.B — Agent System 𝒜𝒮):
  Every agent in the paper shares the same basic lifecycle:
    1. Load its last-processed event cursor from the DB.
    2. Run a continuous processing loop.
    3. Persist cursor + status on stop.

  This base class implements that contract once, so OperatorAgent,
  ManagerAgent, and SummarizationAgent only implement their specific
  run_loop() logic.

Key design decisions:
  1. _cursor persisted to DB — agents survive process restarts and resume
     exactly where they left off without reprocessing old events.
  2. _safe_run() wraps run_loop() in error handling so an unhandled exception
     in one agent does not kill the entire AgentRunner.
  3. _set_status() writes to the agents table — status is visible via
     GET /agents for monitoring and debugging.

Dependencies:
  db.models.agent.Agent, AgentStatus
  sqlalchemy async
"""

import asyncio
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.agent import Agent, AgentStatus

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Shared lifecycle base for all agent types.

    Subclasses must implement run_loop() — the main processing coroutine
    that runs until asyncio.CancelledError is raised.
    """

    def __init__(
        self,
        agent_id: str,
        agent_db_id: uuid.UUID,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._agent_id = agent_id
        self._agent_db_id = agent_db_id
        self._session_factory = session_factory

        # Event cursor — the highest sequence_id this agent has processed.
        # Loaded from DB in start(), persisted in _advance_cursor() and stop().
        self._cursor: int = 0

        # Background task reference — set by start(), cancelled by stop()
        self._task: asyncio.Task | None = None
        self._running: bool = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Load cursor from DB, set status RUNNING, launch run_loop() as a task.

        Called by AgentRunner during application startup.
        """
        await self._load_cursor()
        await self._set_status(AgentStatus.RUNNING)

        self._running = True
        self._task = asyncio.create_task(
            self._safe_run(),
            name=f"agent_{self._agent_id}",
        )
        logger.info(
            "Agent '%s' started (cursor=%d).", self._agent_id, self._cursor
        )

    async def stop(self) -> None:
        """
        Cancel the run_loop task and update status to STOPPED.
        Called by AgentRunner during application shutdown.
        """
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._set_status(AgentStatus.STOPPED)
        logger.info(
            "Agent '%s' stopped (final cursor=%d).",
            self._agent_id, self._cursor,
        )

    async def run_loop(self) -> None:
        """
        Main processing loop — must be implemented by subclasses.

        Should run until asyncio.CancelledError is raised (by stop()).
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement run_loop()."
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _safe_run(self) -> None:
        """
        Wrapper around run_loop() that catches unexpected exceptions,
        logs them, and sets status to ERROR without crashing the process.
        """
        try:
            await self.run_loop()
        except asyncio.CancelledError:
            raise  # propagate cancellation — this is normal shutdown
        except Exception as exc:
            logger.exception(
                "Agent '%s' crashed with unhandled exception: %s",
                self._agent_id, exc,
            )
            await self._set_status(AgentStatus.ERROR)

    async def _load_cursor(self) -> None:
        """Load last_event_sequence from the DB into self._cursor."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(Agent.last_event_sequence).where(
                    Agent.id == self._agent_db_id
                )
            )
            value = result.scalar_one_or_none()
            self._cursor = value if value is not None else 0

        logger.debug(
            "Agent '%s': loaded cursor=%d.", self._agent_id, self._cursor
        )

    async def _advance_cursor(self, new_sequence_id: int) -> None:
        """
        Persist the cursor to the DB and update the in-memory value.

        Called by OperatorAgent after successfully processing a batch of
        events — the exactly-once guarantee: cursor only advances AFTER
        the entire processing pipeline (parse → dispatch → emit event)
        has completed and been committed to the DB.
        """
        async with self._session_factory() as db:
            await db.execute(
                update(Agent)
                .where(Agent.id == self._agent_db_id)
                .values(last_event_sequence=new_sequence_id)
            )
            await db.commit()

        self._cursor = new_sequence_id
        logger.debug(
            "Agent '%s': cursor advanced to %d.",
            self._agent_id, self._cursor,
        )

    async def _set_status(self, status: AgentStatus) -> None:
        """Persist agent status to the DB."""
        async with self._session_factory() as db:
            await db.execute(
                update(Agent)
                .where(Agent.id == self._agent_db_id)
                .values(status=status)
            )
            await db.commit()

        logger.debug(
            "Agent '%s': status set to '%s'.", self._agent_id, status.value
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def is_running(self) -> bool:
        return self._running