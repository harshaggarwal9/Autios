"""
command/mock_functions/system.py
───────────────────────────────────
Mock implementations of emergency_stop and alert_to_supervisor.

Paper SOP:
  "emergency_stop(): halts all machine activity in an emergency."
  "alert_to_supervisor(reason): notifies a human supervisor about specific
  issues or events that require attention."
"""

import logging

from digital_twin.information_model.model import InformationModel

logger = logging.getLogger(__name__)


async def emergency_stop(model: InformationModel) -> None:
    state = model.get_state()
    updates = {"emergency_stop_active": True}
    for key in state:
        if key.endswith("_running"):
            updates[key] = False

    model.register_node_if_absent("emergency_stop_active", False)
    await model.update_many(updates)
    logger.warning("EMERGENCY STOP activated for module '%s'.", model.module_id)


async def alert_to_supervisor(reason: str) -> None:
    """
    No-op against hardware — the alert text is already emitted as an event
    by the calling OperatorAgent. This function exists so alert_to_supervisor
    has a FunctionRegistry entry like every other paper-defined function.
    """
    logger.warning("alert_to_supervisor: %s", reason[:200])