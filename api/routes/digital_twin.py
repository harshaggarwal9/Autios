"""
api/routes/digital_twin.py
───────────────────────────
REST endpoints for inspecting and updating the Digital Twin layer.

Endpoints:
  GET   /digital-twin/modules                          — list all modules
  GET   /digital-twin/modules/{module_id}              — module info + node list
  GET   /digital-twin/modules/{module_id}/state        — full InformationModel state
  PATCH /digital-twin/modules/{module_id}/state        — partial state update

Paper connection (§II.B — Digital Twins):
  Exposes the InformationModel state for each automation module.
  PATCH /state writes node values directly via InformationModel.update_many(),
  bypassing the hardware adapter. Equivalent to POST /simulate/sensor-trigger
  for multi-node atomic updates. Both paths set change_event and wake the
  DataObserver.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from digital_twin.information_model.registry import ModuleRegistry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digital-twin", tags=["digital-twin"])


class StateUpdateRequest(BaseModel):
    """Partial state update — only the supplied node_ids are written."""
    updates: dict[str, Any]


@router.get("/modules")
async def list_modules(request: Request) -> dict:
    """List all registered automation modules."""
    module_registry: ModuleRegistry = request.app.state.module_registry
    module_ids = module_registry.all_module_ids()
    return {
        "modules": [
            {
                "module_id": mid,
                "node_count": len(module_registry.get_model(mid).node_ids()),
            }
            for mid in module_ids
        ],
        "count": len(module_ids),
    }


@router.get("/modules/{module_id}")
async def get_module(module_id: str, request: Request) -> dict:
    """
    Return the module info and node list for one module.

    For the full current state dict, use GET /modules/{module_id}/state.
    """
    module_registry: ModuleRegistry = request.app.state.module_registry

    try:
        model = module_registry.get_model(module_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Module '{module_id}' not found. "
                   f"Registered: {module_registry.all_module_ids()}",
        )

    return {
        "module_id": module_id,
        "node_ids": model.node_ids(),
        "node_count": len(model.node_ids()),
    }


@router.get("/modules/{module_id}/state")
async def get_module_state(module_id: str, request: Request) -> dict:
    """
    Return the full current InformationModel state for one module.

    Shows all node_id → value pairs as the digital twin currently holds
    them. Useful for debugging and verifying states after sensor triggers
    or command dispatch.
    """
    module_registry: ModuleRegistry = request.app.state.module_registry

    try:
        model = module_registry.get_model(module_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Module '{module_id}' not found. "
                   f"Registered: {module_registry.all_module_ids()}",
        )

    return {
        "module_id": module_id,
        "state": model.get_state(),
        "node_count": len(model.node_ids()),
    }


@router.patch("/modules/{module_id}/state")
async def patch_module_state(
    module_id: str,
    payload: StateUpdateRequest,
    request: Request,
) -> dict:
    """
    Partially update the InformationModel state for one module.

    Writes only the node_ids present in the request body. All other nodes
    are left unchanged. Any updated node will set the InformationModel's
    change_event, waking the DataObserver which evaluates rules and emits
    semantic events to the EventLog — identical to what happens after a
    real hardware state change or POST /simulate/sensor-trigger.

    Use this endpoint for multi-node atomic updates (e.g. setting both
    C1_running=True and C1_direction="forward" in one request). For single
    nodes, POST /simulate/sensor-trigger is more ergonomic.

    Returns only the nodes that actually changed value.
    """
    module_registry: ModuleRegistry = request.app.state.module_registry

    try:
        model = module_registry.get_model(module_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Module '{module_id}' not found. "
                   f"Registered: {module_registry.all_module_ids()}",
        )

    if not payload.updates:
        raise HTTPException(
            status_code=422,
            detail="'updates' must be a non-empty dict of node_id → value.",
        )

    unknown_nodes = [
        k for k in payload.updates if k not in model.node_ids()
    ]
    if unknown_nodes:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown node_id(s): {unknown_nodes}. "
                f"Known nodes: {model.node_ids()}"
            ),
        )

    changed_nodes = await model.update_many(payload.updates)

    logger.info(
        "Module '%s' state patched via API: %d node(s) changed: %s",
        module_id, len(changed_nodes), changed_nodes,
    )

    return {
        "module_id": module_id,
        "requested_updates": len(payload.updates),
        "changed_nodes": changed_nodes,
        "unchanged_nodes": [
            k for k in payload.updates if k not in changed_nodes
        ],
        "message": (
            f"{len(changed_nodes)} node(s) changed. "
            "DataObserver will emit semantic events for matched rules."
            if changed_nodes
            else "No values changed — all nodes were already at the requested state."
        ),
    }