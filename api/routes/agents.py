
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.agent_runner import AgentRunner
from db.models.agent import Agent
from db.session import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents(
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    
    result = await db.execute(select(Agent).order_by(Agent.agent_id))
    agents = list(result.scalars().all())
    return {
        "agents": [
            {
                "id": str(a.id),
                "agent_id": a.agent_id,
                "agent_type": a.agent_type.value,
                "status": a.status.value,
                "last_event_sequence": a.last_event_sequence,
                "module_id": str(a.module_id) if a.module_id else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in agents
        ],
        "count": len(agents),
    }


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    
    result = await db.execute(
        select(Agent).where(Agent.agent_id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found.",
        )
    return {
        "id": str(agent.id),
        "agent_id": agent.agent_id,
        "agent_type": agent.agent_type.value,
        "status": agent.status.value,
        "last_event_sequence": agent.last_event_sequence,
        "module_id": str(agent.module_id) if agent.module_id else None,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
    }


@router.post("/{agent_id}/start")
async def start_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    


    runner: AgentRunner = request.app.state.agent_runner
    agent = runner.get_agent(agent_id)

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Agent '{agent_id}' is not managed by AgentRunner. "
                "Only agents started at application boot can be "
                "controlled via this endpoint."
            ),
        )

    if agent.is_running:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agent_id}' is already running.",
        )

    await agent.start()
    logger.info("Agent '%s' started via API.", agent_id)

    return {
        "agent_id": agent_id,
        "status": "running",
        "message": f"Agent '{agent_id}' started successfully.",
    }


@router.post("/{agent_id}/stop")
async def stop_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:

    runner: AgentRunner = request.app.state.agent_runner
    agent = runner.get_agent(agent_id)

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' is not managed by AgentRunner.",
        )

    if not agent.is_running:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agent_id}' is not currently running.",
        )

    await agent.stop()
    logger.info("Agent '%s' stopped via API.", agent_id)

    return {
        "agent_id": agent_id,
        "status": "stopped",
        "cursor": agent.cursor,
        "message": f"Agent '{agent_id}' stopped. Final cursor={agent.cursor}.",
    }
