















import asyncio
import logging

from digital_twin.information_model.model import InformationModel

logger = logging.getLogger(__name__)

VALID_DIRECTIONS = {"forward", "reverse"}


async def _run_conveyor(
    model: InformationModel,
    conveyor_id: str,
    direction: str,
    duration: float,
) -> None:
    if direction not in VALID_DIRECTIONS:
        raise ValueError(
            f"Invalid direction {direction!r} for {conveyor_id}_run; "
            f"expected one of {VALID_DIRECTIONS}."
        )
    if duration <= 0:
        raise ValueError(
            f"Invalid duration {duration!r} for {conveyor_id}_run; must be > 0."
        )

    running_key = f"{conveyor_id}_running"
    direction_key = f"{conveyor_id}_direction"

    await model.update_many({running_key: True, direction_key: direction})

    logger.info(
        "%s_run('%s', %.1f) dispatched — running=True.",
        conveyor_id, direction, duration,
    )

    asyncio.create_task(
        _auto_stop(model, running_key, duration, conveyor_id),
        name=f"conveyor_{conveyor_id}_autostop",
    )


async def _auto_stop(
    model: InformationModel,
    running_key: str,
    duration: float,
    conveyor_id: str,
) -> None:
    await asyncio.sleep(duration)
    changed = await model.update_node(running_key, False)
    if changed:
        logger.info("%s auto-stopped after %.1fs.", conveyor_id, duration)


async def conveyor_1_run(model: InformationModel, direction: str, time: float) -> None:
    await _run_conveyor(model, "C1", direction, time)


async def conveyor_2_run(model: InformationModel, direction: str, time: float) -> None:
    await _run_conveyor(model, "C2", direction, time)


async def conveyor_3_run(model: InformationModel, direction: str, time: float) -> None:
    await _run_conveyor(model, "C3", direction, time)


async def conveyor_4_run(model: InformationModel, direction: str, time: float) -> None:
    await _run_conveyor(model, "C4", direction, time)
