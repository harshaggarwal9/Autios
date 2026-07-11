
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from digital_twin.information_model.registry import ModuleRegistry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digital-twin", tags=["digital-twin"])


class StateUpdateRequest(BaseModel):
    
   updates: dict[str, Any]


@router.get("/modules")
async def list_modules(request: Request) -> dict:
    
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
