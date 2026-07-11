





























import json
import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.dataset import DatasetRecord
from db.models.inference_log import CommandOutcome

logger = logging.getLogger(__name__)


_FUNCTION_TO_TASK_TYPE: dict[str, str] = {
    "conveyor_1_run": "conveyor_start",
    "conveyor_2_run": "conveyor_start",
    "conveyor_3_run": "conveyor_start",
    "conveyor_4_run": "conveyor_start",
    "release_holder_H1": "holder_release",
    "release_holder_H2": "holder_release",
    "release_holder_H3": "holder_release",
    "RFID_read_workpiece_info": "rfid_read",
    "transport_robot_request": "robot_request",
    "request_inspection_service": "inspection_request",
    "switch_actuate": "switch_control",
    "emergency_stop": "emergency_stop",
    "alert_to_supervisor": "supervisor_alert",
}


_UNEXPECTED_TASK_TYPES = {"emergency_stop", "supervisor_alert"}


class DatasetRecorder:
    







    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._enabled = True



    async def record_inference(
        self,
        *,
        inference_id: uuid.UUID,
        prompt_text: str,
        response_text: str,
        parsed_reason: str | None,
        parsed_command: str | None,
        dispatch_outcome: CommandOutcome | None,
        module_id: str,
        scenario_tag: str | None = None,
    ) -> DatasetRecord | None:
        

















        if not self._enabled:
            return None

        try:
            reference_output = self._build_reference_output(
                parsed_reason, parsed_command, response_text
            )
            task_type = self._classify_task(parsed_command)
            is_sop = task_type not in _UNEXPECTED_TASK_TYPES

            record = DatasetRecord(
                inference_id=inference_id,
                prompt_text=prompt_text,
                reference_output=reference_output,
                is_sop_task=is_sop,
                scenario_tag=scenario_tag or module_id,
                task_type=task_type,
            )

            async with self._session_factory() as db:
                db.add(record)
                await db.commit()
                await db.refresh(record)

            logger.debug(
                "DatasetRecorder: recorded inference %s "
                "(module=%s, task_type=%s, sop=%s).",
                inference_id, module_id, task_type, is_sop,
            )
            return record

        except Exception as exc:
            logger.exception(
                "DatasetRecorder.record_inference failed (non-fatal): %s", exc
            )
            return None

    async def record_task_assignment(
        self,
        *,
        task_id: uuid.UUID,
        task_title: str,
        task_description: str,
        plan: dict,
        module_id: str,
    ) -> None:
        





        if not self._enabled:
            return

        try:
            record = DatasetRecord(
                inference_id=None,
                prompt_text=f"Task: {task_title}\n\n{task_description}",
                reference_output=json.dumps(plan, indent=2),
                is_sop_task=True,
                scenario_tag="task_assignment",
                task_type="task_assignment",
            )

            async with self._session_factory() as db:
                db.add(record)
                await db.commit()

            logger.debug(
                "DatasetRecorder: recorded task assignment %s.", task_id
            )

        except Exception as exc:
            logger.exception(
                "DatasetRecorder.record_task_assignment failed (non-fatal): %s",
                exc,
            )

    def set_enabled(self, enabled: bool) -> None:
        
        self._enabled = enabled
        logger.info(
            "DatasetRecorder: recording %s.", "enabled" if enabled else "disabled"
        )



    @staticmethod
    def _build_reference_output(
        reason: str | None,
        command: str | None,
        raw_response: str,
    ) -> str:
        







        if reason is not None and command is not None:
            return json.dumps({"reason": reason, "command": command})
        return json.dumps({"raw": raw_response, "_parse_failed": True})

    @staticmethod
    def _classify_task(parsed_command: str | None) -> str:
        
        if parsed_command is None:
            return "parse_failure"
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(", parsed_command.strip())
        if not match:
            return "unknown"
        fn_name = match.group(1)
        return _FUNCTION_TO_TASK_TYPE.get(fn_name, fn_name)
