"""
llm/output_parser.py
─────────────────────
OutputParser — parses the LLM's raw JSON response into a typed ParsedOutput.

Paper connection (§III.C — LLM Output 𝒪ℓℓ𝓂):
  The paper specifies the LLM output format as:
    {"reason": "reason_for_action", "command": "a_function()"}

  The parser extracts both fields and handles real-world LLM output quirks:
    1. Code fences (```json ... ```) — some models wrap JSON in markdown
    2. Trailing text after the JSON object
    3. Unescaped double-quotes inside the command string — e.g.
       {"command": "conveyor_1_run("forward", 13)"} is invalid JSON because
       the inner quotes aren't escaped. A regex recovery path handles this.
    4. Missing fields — reason or command may be absent
    5. Empty command — the LLM may return "" for the command

Parse status values (6 outcomes):
  SUCCESS         — both reason and command extracted successfully
  PARSE_ERROR     — could not extract valid JSON (and recovery failed)
  MISSING_FIELDS  — valid JSON but reason or command key absent
  EMPTY_COMMAND   — command key present but empty string

Dependencies:
  json, re (stdlib only — no third-party dependencies)
"""

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ParseStatus(str, Enum):
    SUCCESS = "success"
    PARSE_ERROR = "parse_error"
    MISSING_FIELDS = "missing_fields"
    EMPTY_COMMAND = "empty_command"


@dataclass
class ParsedOutput:
    """Result of parsing one LLM response."""
    status: ParseStatus
    reason: str | None
    function_call: str | None
    raw_text: str
    error_detail: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == ParseStatus.SUCCESS

    @property
    def function_name(self) -> str | None:
        """
        Extract just the function name from the function call string.

        e.g. 'conveyor_1_run("forward", 13)' → 'conveyor_1_run'
        """
        if self.function_call is None:
            return None
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(", self.function_call.strip())
        return match.group(1) if match else None


class OutputParser:
    """
    Parses raw LLM response text into a typed ParsedOutput.

    Handles real-world LLM output quirks including code fences,
    trailing text, and unescaped quotes inside command strings.

    Usage:
        parser = OutputParser()
        result = parser.parse(llm_response.raw_text)
        if result.is_success:
            dispatch(result.function_call)
    """

    def parse(self, raw_text: str) -> ParsedOutput:
        """
        Parse one LLM response string.

        Pipeline:
          1. Strip code fences (```json ... ```)
          2. Extract the first complete JSON object using brace matching
          3. Parse JSON — with fallback recovery for unescaped quotes
          4. Validate required fields (reason, command)
          5. Validate command is non-empty

        Args:
            raw_text: The raw string returned by GeminiClient.generate().

        Returns:
            ParsedOutput with status, reason, function_call, and raw_text.
            Never raises — all error conditions are captured in the status.
        """
        if not raw_text or not raw_text.strip():
            return ParsedOutput(
                status=ParseStatus.PARSE_ERROR,
                reason=None,
                function_call=None,
                raw_text=raw_text or "",
                error_detail="Empty response from LLM.",
            )

        # Step 1: strip code fences
        cleaned = self._strip_code_fences(raw_text.strip())

        # Step 2: extract JSON object
        json_str = self._extract_json_object(cleaned)
        if json_str is None:
            logger.warning(
                "OutputParser: could not extract JSON from response: %r",
                cleaned[:120],
            )
            return ParsedOutput(
                status=ParseStatus.PARSE_ERROR,
                reason=None,
                function_call=None,
                raw_text=raw_text,
                error_detail=(
                    f"No JSON object found in response. "
                    f"First 100 chars: {cleaned[:100]!r}"
                ),
            )

        # Step 3: parse JSON — with fallback for unescaped quotes in command
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Recovery: some LLMs emit function calls with unescaped inner quotes,
            # e.g. "command": "conveyor_1_run("forward", 13)" — invalid JSON.
            # Extract reason and command directly with a regex before giving up.
            recovered = self._recover_from_unescaped_quotes(json_str)
            if recovered:
                data = recovered
            else:
                logger.warning(
                    "OutputParser: JSON parse error and recovery failed. text=%r",
                    json_str[:120],
                )
                return ParsedOutput(
                    status=ParseStatus.PARSE_ERROR,
                    reason=None,
                    function_call=None,
                    raw_text=raw_text,
                    error_detail=(
                        f"JSON decode error (recovery failed). "
                        f"First 100 chars: {json_str[:100]!r}"
                    ),
                )

        # Step 4: validate required fields
        reason = data.get("reason")
        command = data.get("command")

        if reason is None and command is None:
            return ParsedOutput(
                status=ParseStatus.MISSING_FIELDS,
                reason=None,
                function_call=None,
                raw_text=raw_text,
                error_detail=(
                    "Neither 'reason' nor 'command' key found in JSON. "
                    f"Keys present: {list(data.keys())}"
                ),
            )

        if command is None:
            return ParsedOutput(
                status=ParseStatus.MISSING_FIELDS,
                reason=str(reason) if reason is not None else None,
                function_call=None,
                raw_text=raw_text,
                error_detail="'command' key missing from LLM response JSON.",
            )

        if reason is None:
            return ParsedOutput(
                status=ParseStatus.MISSING_FIELDS,
                reason=None,
                function_call=str(command).strip() if command else None,
                raw_text=raw_text,
                error_detail="'reason' key missing from LLM response JSON.",
            )

        # Step 5: validate command is non-empty
        command_str = str(command).strip()
        if not command_str:
            return ParsedOutput(
                status=ParseStatus.EMPTY_COMMAND,
                reason=str(reason).strip(),
                function_call=None,
                raw_text=raw_text,
                error_detail="'command' field is present but empty.",
            )

        return ParsedOutput(
            status=ParseStatus.SUCCESS,
            reason=str(reason).strip(),
            function_call=command_str,
            raw_text=raw_text,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """
        Remove markdown code fences that some LLMs add around JSON.

        Handles:
````json\\n{...}\\n```
```\\n{...}\\n```
        """
        pattern = r"^```(?:json)?\s*\n?(.*?)\n?```\s*$"
        match = re.match(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def _recover_from_unescaped_quotes(text: str) -> dict | None:
        """
        Attempt to recover reason and command from malformed JSON where the
        LLM included unescaped double-quotes inside a string value.

        e.g.  {"reason": "r", "command": "conveyor_1_run("forward", 13)"}

        Uses a greedy regex: match from "reason": "..." to "command": "...(last "}")
        This works because the command is always the last key in the JSON object.
        """
        pattern = (
            r'"reason"\s*:\s*"([^"]*)"\s*,\s*'
            r'"command"\s*:\s*"(.+)"\s*}'
        )
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return {"reason": m.group(1), "command": m.group(2)}
        return None

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        """
        Extract the first complete JSON object from text using brace matching.

        This handles cases where the LLM adds text before or after the JSON.
        Returns None if no complete JSON object is found.
        """
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape_next = False

        for i, ch in enumerate(text[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]

        return None
