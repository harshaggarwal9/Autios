"""
command/mock_functions/inspection.py
───────────────────────────────────────
Mock implementation of request_inspection_service.

Paper SOP: "request_inspection_service(description): initiates an
inspection process based on specific details provided about a workpiece."

Behaviour:
  Simulates inspection over a fixed delay, then invokes the
  emit_completed_event callback so a fresh DB session can persist the
  "inspection service is successfully completed" event.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

INSPECTION_DURATION_SECONDS = 2.0


async def request_inspection_service(description: str, emit_completed_event) -> None:
    logger.info(
        "request_inspection_service('%s') dispatched — completing in %.1fs.",
        description[:80], INSPECTION_DURATION_SECONDS,
    )

    asyncio.create_task(
        _simulate_inspection(emit_completed_event),
        name="inspection_service",
    )


async def _simulate_inspection(emit_completed_event) -> None:
    await asyncio.sleep(INSPECTION_DURATION_SECONDS)
    await emit_completed_event()
    logger.info("Inspection service completion event emitted.")