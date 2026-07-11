
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.event_log.store import EventLogStore
from core.subscription.registry import SubscriptionRegistry
from db.session import get_db_session
from schemas.event import EventBatch, EventCreate, EventRead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])


def _get_registry(request: Request) -> SubscriptionRegistry:
    return request.app.state.subscription_registry


@router.post("", response_model=EventRead, status_code=201)
async def append_event(
    payload: EventCreate,
    db: AsyncSession = Depends(get_db_session),
) -> EventRead:
    
    store = EventLogStore(db)
    event = await store.append(payload)
    logger.info(
        "Event appended via API: seq=%s scope=%r", event.sequence_id, event.scope
    )
    return event


@router.get("", response_model=EventBatch)
async def get_recent_events(
    limit: int = Query(default=50, ge=1, le=500),
    scope: str | None = Query(default=None, description="Filter by scope"),
    db: AsyncSession = Depends(get_db_session),
) -> EventBatch:
    
    store = EventLogStore(db)
    scopes = [scope] if scope else None
    return await store.get_recent_events(limit=limit, scopes=scopes)


@router.get("/since/{after_sequence_id}", response_model=EventBatch)
async def get_events_since(
    after_sequence_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    scope: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> EventBatch:
    
    store = EventLogStore(db)
    scopes = [scope] if scope else None
    return await store.get_events_since(
        after_sequence_id=after_sequence_id,
        limit=limit,
        scopes=scopes,
    )


@router.get("/agent/{agent_id}", response_model=EventBatch)
async def get_events_for_agent(
    agent_id: str,
    request: Request,
    after_sequence_id: int = Query(default=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> EventBatch:
    


    registry: SubscriptionRegistry = _get_registry(request)
    scopes = registry.get_scopes(agent_id)

    if not scopes:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found or has no subscriptions.",
        )

    store = EventLogStore(db)
    return await store.get_events_since(
        after_sequence_id=after_sequence_id,
        limit=limit,
        scopes=scopes,
    )


@router.get("/{sequence_id}", response_model=EventRead)
async def get_event_by_sequence(
    sequence_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> EventRead:
    

    store = EventLogStore(db)
    event = await store.get_event_by_sequence(sequence_id)

    if event is None:
        raise HTTPException(
            status_code=404,
            detail=f"No event found with sequence_id={sequence_id}.",
        )

    return event
