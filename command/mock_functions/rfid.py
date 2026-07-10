"""
command/mock_functions/rfid.py
─────────────────────────────────
Mock implementation of RFID_read_workpiece_info.

Paper SOP: "The function is called to gather data about the workpiece."

Behaviour:
  Returns a mock workpiece info dict (recorded in agent_command_log /
  dataset_records for traceability). Sets rfid_read_complete=True so the
  DataObserver can emit "The workpiece information is successfully
  retrieved." — the trigger for the next SOP step
  (request_inspection_service).
"""

import logging
import uuid

from digital_twin.information_model.model import InformationModel

logger = logging.getLogger(__name__)

_MOCK_WORKPIECE_TYPES = ["white plastic cylinder", "black metal cube", "blue ceramic disk"]


async def RFID_read_workpiece_info(model: InformationModel) -> dict:
    workpiece_id = str(uuid.uuid4())[:8]
    workpiece_type = _MOCK_WORKPIECE_TYPES[
        hash(workpiece_id) % len(_MOCK_WORKPIECE_TYPES)
    ]

    info = {
        "workpiece_id": workpiece_id,
        "workpiece_type": workpiece_type,
    }

    model.register_node_if_absent("rfid_read_complete", False)
    await model.update_node("rfid_read_complete", True)

    logger.info(
        "RFID_read_workpiece_info: read %s (%s).", workpiece_id, workpiece_type
    )

    return info