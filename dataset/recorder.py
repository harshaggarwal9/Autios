"""
dataset/recorder.py
────────────────────
DatasetRecorder — converts live OperatorAgent inference cycles into
typed DatasetRecord rows for dataset creation and future fine-tuning.

Paper connection (§IV — Dataset Creation):
  "We record the data produced during system operation. Each test case
  consists of the prompt 𝒯𝒫 and the reference output 𝒪*ℓℓ𝓂 = (reason, fc).
  The dataset 𝒟 contains all such test cases, partitioned into SOP tasks
  and unexpected tasks."

  The paper records data during *normal operation*, not a separate offline
  pass. DatasetRecorder is called from inside OperatorAgent.run_loop()
  immediately after each LLM inference + command dispatch completes.

Integration points:
  - OperatorAgent calls record_inference() after every parse+dispatch cycle
    (success or failure).
  - ManagerAgent calls record_task_assignment() when it publishes a task.

Failure isolation:
  Recording must never interrupt the agent loop. Every public method
  catches and logs exceptions internally rather than propagating them.

Dependencies:
  db.models.dataset.DatasetRecord
  db.models.inference_log.CommandOutcome
"""

import json
import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.dataset import DatasetRecord
from db.models.inference_log import CommandOutcome

logger = logging.getLogger(__name__)

# Map function names to human-readable task_type tags for dataset organisation
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

# Functions that represent unexpected/error situations rather than normal SOP flow
_UNEXPECTED_TASK_TYPES = {"emergency_stop", "supervisor_alert"}


class DatasetRecorder:
    """
    Records OperatorAgent inference cycles into dataset_records.

    One shared instance, created at startup and injected into OperatorAgent
    and ManagerAgent by AgentRunner. Thread-safe: each call opens its own
    DB session.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._enabled = True

    # ── Public API ────────────────────────────────────────────────────────────

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
        """
        Persist one OperatorAgent inference cycle as a DatasetRecord.

        Args:
            inference_id:      The LLMInferenceLog.id for this cycle.
            prompt_text:       The full five-section prompt (𝒯𝒫).
            response_text:     The raw LLM response string.
            parsed_reason:     Extracted reason string, or None on parse failure.
            parsed_command:    Extracted function call string, or None.
            dispatch_outcome:  CommandOutcome from CommandInterface.execute(),
                               or None if parse failed before dispatch.
            module_id:         Which automation module handled this cycle.
            scenario_tag:      Optional grouping tag for the test suite.

        Returns:
            The created DatasetRecord, or None if disabled or on error
            (errors are logged and swallowed, never raised).
        """
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
        """
        Record a ManagerAgent task assignment for dataset provenance.

        Stored as a DatasetRecord with scenario_tag="task_assignment" so it
        can be filtered separately from per-cycle inference records.
        """
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
        """Enable or disable recording at runtime (e.g. during evaluation runs)."""
        self._enabled = enabled
        logger.info(
            "DatasetRecorder: recording %s.", "enabled" if enabled else "disabled"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_reference_output(
        reason: str | None,
        command: str | None,
        raw_response: str,
    ) -> str:
        """
        Build a clean JSON reference output string.

        If both reason and command are available, returns a canonical
        {"reason": ..., "command": ...} JSON string. Otherwise falls back
        to the raw response with a "_parse_failed" marker so the record is
        still useful for studying failure modes.
        """
        if reason is not None and command is not None:
            return json.dumps({"reason": reason, "command": command})
        return json.dumps({"raw": raw_response, "_parse_failed": True})

    @staticmethod
    def _classify_task(parsed_command: str | None) -> str:
        """Derive a human-readable task_type from the function call string."""
        if parsed_command is None:
            return "parse_failure"
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(", parsed_command.strip())
        if not match:
            return "unknown"
        fn_name = match.group(1)
        return _FUNCTION_TO_TASK_TYPE.get(fn_name, fn_name)