
import asyncio
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.agent import Agent, AgentStatus

logger = logging.getLogger(__name__)


class BaseAgent:
    

    def __init__(
        self,
        agent_id: str,
        agent_db_id: uuid.UUID,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._agent_id = agent_id
        self._agent_db_id = agent_db_id
        self._session_factory = session_factory



        self._cursor: int = 0


        self._task: asyncio.Task | None = None
        self._running: bool = False



    async def start(self) -> None:

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

        raise NotImplementedError(
            f"{type(self).__name__} must implement run_loop()."
        )



    async def _safe_run(self) -> None:
        



        try:
            await self.run_loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Agent '%s' crashed with unhandled exception: %s",
                self._agent_id, exc,
            )
            await self._set_status(AgentStatus.ERROR)

    async def _load_cursor(self) -> None:
        
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



    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def is_running(self) -> bool:
        return self._running
