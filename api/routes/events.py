"""
api/routes/events.py
──────────────────────
REST endpoints for the Event Log.

Endpoints:
  POST /events                          — append a new event
  GET  /events                          — recent events (newest first)
  GET  /events/since/{after_seq}        — cursor-based poll
  GET  /events/agent/{agent_id}         — events filtered by agent subscriptions
  GET  /events/{sequence_id}            — fetch one event by sequence_id

Paper connection (§III.B — Event Log Memory ℰ):
  These endpoints expose EventLogStore and SubscriptionRegistry over HTTP.
  Production agents call SubscriptionEngine.poll_once() directly (no HTTP);
  these routes are for external tooling, test harnesses, and monitoring.

Route ordering note:
  FastAPI matches routes in registration order. The specific literal sub-paths
  /since and /agent must be declared BEFORE /{sequence_id} to prevent FastAPI
  from capturing them as integer-looking path parameters. Since "since" and
  "agent" are not integers, FastAPI's type coercion will reject them for the
  /{sequence_id}: int route anyway — but explicit ordering avoids ambiguity
  and makes intent clear.
"""

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
    """Append a new event to the global event log."""
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
    """Return the most recent events, optionally filtered by scope."""
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
    """Return events with sequence_id strictly greater than after_sequence_id."""
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
    """
    Return events filtered to the scopes the given agent subscribes to.

    HTTP equivalent of SubscriptionEngine.poll_once() — used by test
    harnesses and external monitoring.
    """
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
    """
    Fetch one specific event by its sequence_id.

    sequence_id is the global ordering integer assigned by the PostgreSQL
    BIGSERIAL — not the UUID primary key. Use this endpoint to retrieve a
    specific event when you know its position in the log, e.g. after
    observing a latest_sequence_id in a poll response and wanting to
    inspect that exact event in detail.

    Returns 404 if no event with that sequence_id exists.
    """
    store = EventLogStore(db)
    event = await store.get_event_by_sequence(sequence_id)

    if event is None:
        raise HTTPException(
            status_code=404,
            detail=f"No event found with sequence_id={sequence_id}.",
        )

    return event