









import logging

from digital_twin.information_model.model import InformationModel

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"divert", "continue"}


async def switch_actuate(model: InformationModel, action: str) -> None:
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"Invalid action {action!r} for switch_actuate; "
            f"expected one of {VALID_ACTIONS}."
        )

    changed = await model.update_node("S1", action)
    logger.info("switch_actuate('%s') dispatched (changed=%s).", action, changed)
