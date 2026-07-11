













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
