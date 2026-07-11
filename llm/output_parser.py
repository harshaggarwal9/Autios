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

        if self.function_call is None:
            return None
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(", self.function_call.strip())
        return match.group(1) if match else None


class OutputParser:


    def parse(self, raw_text: str) -> ParsedOutput:

        if not raw_text or not raw_text.strip():
            return ParsedOutput(
                status=ParseStatus.PARSE_ERROR,
                reason=None,
                function_call=None,
                raw_text=raw_text or "",
                error_detail="Empty response from LLM.",
            )


        cleaned = self._strip_code_fences(raw_text.strip())


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


        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:



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



    @staticmethod
    def _strip_code_fences(text: str) -> str:

        pattern = r"^```(?:json)?\s*\n?(.*?)\n?```\s*$"
        match = re.match(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def _recover_from_unescaped_quotes(text: str) -> dict | None:

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
