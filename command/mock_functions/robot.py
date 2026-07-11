













import asyncio
import logging

logger = logging.getLogger(__name__)

ROBOT_DOCK_DELAY_SECONDS = 2.0


async def transport_robot_request(emit_docked_event) -> None:
    logger.info(
        "transport_robot_request dispatched — robot will dock in %.1fs.",
        ROBOT_DOCK_DELAY_SECONDS,
    )

    asyncio.create_task(
        _simulate_docking(emit_docked_event),
        name="transport_robot_docking",
    )


async def _simulate_docking(emit_docked_event) -> None:
    await asyncio.sleep(ROBOT_DOCK_DELAY_SECONDS)
    await emit_docked_event()
    logger.info("Transport robot docking event emitted.")
