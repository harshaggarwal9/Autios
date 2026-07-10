"""
command/mock_functions/holders.py
───────────────────────────────────
Mock implementations of release_holder_H1/H2/H3.

Paper SOP: "release_holder_H1(): disengages Holder H1 for 3 seconds,
releasing the workpiece held in position."
"""

import asyncio
import logging

from digital_twin.information_model.model import InformationModel

logger = logging.getLogger(__name__)

RELEASE_DURATION_SECONDS = 3.0


async def _release_holder(model: InformationModel, holder_id: str) -> None:
    changed = await model.update_node(holder_id, False)
    logger.info("%s released (changed=%s).", holder_id, changed)

    asyncio.create_task(
        _re_engage(model, holder_id),
        name=f"holder_{holder_id}_reengage",
    )


async def _re_engage(model: InformationModel, holder_id: str) -> None:
    await asyncio.sleep(RELEASE_DURATION_SECONDS)
    changed = await model.update_node(holder_id, True)
    if changed:
        logger.info("%s returned to holding position.", holder_id)


async def release_holder_H1(model: InformationModel) -> None:
    await _release_holder(model, "H1")


async def release_holder_H2(model: InformationModel) -> None:
    await _release_holder(model, "H2")


async def release_holder_H3(model: InformationModel) -> None:
    await _release_holder(model, "H3")