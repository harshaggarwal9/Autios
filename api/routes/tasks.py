
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.task import Task, TaskAssignment, TaskStatus
from db.session import get_db_session
from schemas.agent import TaskCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201)
async def submit_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db_session),
) -> dict:

    task = Task(
        title=payload.title,
        description=payload.description,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    logger.info("Task submitted via API: id=%s title=%r", task.id, task.title)
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status.value,
        "message": (
            "Task queued. The ManagerAgent will decompose it on its next "
            "poll cycle."
        ),
    }


@router.get("")
async def list_tasks(
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    
    result = await db.execute(
        select(Task).order_by(Task.created_at.desc())
    )
    tasks = list(result.scalars().all())
    return {
        "tasks": [
            {
                "id": str(t.id),
                "title": t.title,
                "status": t.status.value,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
        "count": len(tasks),
    }


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    
    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid task_id UUID format.")

    result = await db.execute(select(Task).where(Task.id == uid))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=404, detail=f"Task '{task_id}' not found."
        )

    assignments_result = await db.execute(
        select(TaskAssignment)
        .where(TaskAssignment.task_id == uid)
        .order_by(TaskAssignment.sequence_order)
    )
    assignments = list(assignments_result.scalars().all())

    return {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "plan": task.plan,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "assignments": [
            {
                "id": str(a.id),
                "assigned_to_agent_id": str(a.assigned_to_agent_id),
                "subtask_description": a.subtask_description,
                "status": a.status.value,
                "sequence_order": a.sequence_order,
            }
            for a in assignments
        ],
    }


@router.get("/{task_id}/assignments")
async def get_task_assignments(
    task_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    

    try:
        uid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid task_id UUID format.")

    task_result = await db.execute(select(Task).where(Task.id == uid))
    task = task_result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=404, detail=f"Task '{task_id}' not found."
        )

    assignments_result = await db.execute(
        select(TaskAssignment)
        .where(TaskAssignment.task_id == uid)
        .order_by(TaskAssignment.sequence_order)
    )
    assignments = list(assignments_result.scalars().all())

    return {
        "task_id": task_id,
        "task_status": task.status.value,
        "assignments": [
            {
                "id": str(a.id),
                "assigned_to_agent_id": str(a.assigned_to_agent_id),
                "subtask_description": a.subtask_description,
                "status": a.status.value,
                "sequence_order": a.sequence_order,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in assignments
        ],
        "count": len(assignments),
    }
