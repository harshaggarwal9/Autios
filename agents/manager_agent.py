
import asyncio
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.base_agent import BaseAgent
from config.module_loader import ModuleConfig
from config.settings import get_settings
from core.event_log.store import EventLogStore
from dataset.recorder import DatasetRecorder
from db.models.agent import Agent, AgentType
from db.models.task import Task, TaskAssignment, TaskStatus
from schemas.event import EventCreate

logger = logging.getLogger(__name__)
settings = get_settings()


class ManagerAgent(BaseAgent):
    
    TASK_POLL_INTERVAL_SECONDS = 2.0

    def __init__(
        self,
        agent_id: str,
        agent_db_id: uuid.UUID,
        session_factory: async_sessionmaker[AsyncSession],
        module_configs: dict[str, ModuleConfig],
        dataset_recorder: DatasetRecorder | None = None,
    ) -> None:
        super().__init__(agent_id, agent_db_id, session_factory)
        self._module_configs = module_configs
        self._dataset_recorder = dataset_recorder



    async def run_loop(self) -> None:

        logger.info("ManagerAgent '%s' run_loop started.", self._agent_id)

        while True:
            try:
                pending_task = await self._claim_next_pending_task()

                if pending_task is None:
                    await asyncio.sleep(self.TASK_POLL_INTERVAL_SECONDS)
                    continue

                logger.info(
                    "ManagerAgent '%s': claimed task %s ('%s').",
                    self._agent_id, pending_task.id, pending_task.title,
                )

                await self._process_task(pending_task)

            except asyncio.CancelledError:
                logger.info(
                    "ManagerAgent '%s' run_loop cancelled.", self._agent_id
                )
                raise

            except Exception as exc:
                logger.exception(
                    "ManagerAgent '%s' unhandled error (will retry): %s",
                    self._agent_id, exc,
                )
                await asyncio.sleep(5.0)



    async def _claim_next_pending_task(self) -> Task | None:
        



        async with self._session_factory() as db:
            result = await db.execute(
                select(Task)
                .where(Task.status == TaskStatus.PENDING)
                .order_by(Task.created_at.asc())
                .limit(1)
            )
            task = result.scalar_one_or_none()

            if task is None:
                return None

            await db.execute(
                update(Task)
                .where(Task.id == task.id)
                .values(status=TaskStatus.IN_PROGRESS)
            )
            await db.commit()

            task.status = TaskStatus.IN_PROGRESS
            return task



    async def _process_task(self, task: Task) -> None:
        


        plan: dict | None = None
        try:
            plan = self._build_plan(task)
            assignments = await self._create_assignments(task, plan)
            await self._publish_assignment_events(task, assignments)
            await self._finalise_task(task.id, plan, TaskStatus.IN_PROGRESS)


            if self._dataset_recorder is not None and plan:
                await self._dataset_recorder.record_task_assignment(
                    task_id=task.id,
                    task_title=task.title,
                    task_description=task.description,
                    plan=plan,
                    module_id=list(self._module_configs.keys())[0]
                    if self._module_configs else "unknown",
                )

            logger.info(
                "ManagerAgent '%s': task %s decomposed into %d assignment(s).",
                self._agent_id, task.id, len(assignments),
            )

        except Exception as exc:
            logger.exception(
                "ManagerAgent '%s': failed to process task %s: %s",
                self._agent_id, task.id, exc,
            )
            await self._finalise_task(task.id, plan=plan, status=TaskStatus.FAILED)

    def _build_plan(self, task: Task) -> dict:
        
        steps = []
        for module_id, cfg in self._module_configs.items():
            steps.append({
                "module_id": module_id,
                "display_name": cfg.display_name,
                "operator_agent_id": f"{module_id}_operator",
                "subtask_description": (
                    f"{task.description.strip()} "
                    f"(assigned to {cfg.display_name})"
                ),
            })

        return {
            "task_id": str(task.id),
            "title": task.title,
            "steps": steps,
        }

    async def _create_assignments(
        self, task: Task, plan: dict
    ) -> list[TaskAssignment]:
        
        assignments: list[TaskAssignment] = []

        async with self._session_factory() as db:
            for order, step in enumerate(plan["steps"]):
                result = await db.execute(
                    select(Agent).where(
                        Agent.agent_id == step["operator_agent_id"]
                    )
                )
                operator_agent = result.scalar_one_or_none()

                if operator_agent is None:
                    logger.warning(
                        "ManagerAgent: no Agent row for '%s' — skipping. "
                        "Run scripts/seed_db.py to create it.",
                        step["operator_agent_id"],
                    )
                    continue

                assignment = TaskAssignment(
                    task_id=task.id,
                    assigned_to_agent_id=operator_agent.id,
                    subtask_description=step["subtask_description"],
                    status=TaskStatus.PENDING,
                    sequence_order=order,
                )
                db.add(assignment)
                assignments.append(assignment)

            await db.commit()
            for a in assignments:
                await db.refresh(a)

        return assignments

    async def _publish_assignment_events(
        self, task: Task, assignments: list[TaskAssignment]
    ) -> None:
 
        async with self._session_factory() as db:
            store = EventLogStore(db)
            for assignment in assignments:
                await store.append(
                    EventCreate(
                        scope="MES",
                        source="Manager",
                        text=f"Task assigned: {assignment.subtask_description}",
                        metadata={
                            "task_id": str(task.id),
                            "assignment_id": str(assignment.id),
                            "assigned_to_agent_id": str(
                                assignment.assigned_to_agent_id
                            ),
                        },
                    )
                )
            await db.commit()

    async def _finalise_task(
        self,
        task_id: uuid.UUID,
        plan: dict | None,
        status: TaskStatus,
    ) -> None:
        
        async with self._session_factory() as db:
            values: dict = {"status": status}
            if plan is not None:
                values["plan"] = plan
            await db.execute(
                update(Task).where(Task.id == task_id).values(**values)
            )
            await db.commit()
