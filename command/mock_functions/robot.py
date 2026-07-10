"""
command/mock_functions/robot.py
───────────────────────────────────
Mock implementation of transport_robot_request.

Paper SOP: "This call would request a transport robot to pick up a
workpiece from the Inspection Station."

Behaviour:
  Simulates the robot docking after a fixed delay, then invokes the
  emit_docked_event callback (provided by CommandInterface) so a fresh
  DB session can persist the "transport robot has docked" event.
"""

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