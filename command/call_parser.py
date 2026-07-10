"""
command/call_parser.py
────────────────────────
CallParser — safely parses a function-call string like
'conveyor_1_run("forward", 13)' into (function_name, args) without eval().

Paper connection (§III.C — LLM Output 𝒪ℓℓ𝓂):
  The LLM returns 𝒪_fc as a string such as "conveyor_1_run('forward', 13)".
  This parser is the safety boundary between that untrusted string and any
  actual Python call — it NEVER uses eval() or exec().

Security model:
  Uses ast.parse(mode="eval") to build a syntax tree, then walks only the
  literal-valued nodes. Any non-literal expression (Name, Call, Attribute,
  BinOp, comprehension, etc.) is rejected. This means a malicious or
  malformed LLM output like '__import__("os").system("rm -rf /")' is
  rejected at the AST level — it parses as a Call to an Attribute access on
  the result of another Call, which is not the simple
  `Name(args=[Constants])` shape this parser accepts.

Dependencies:
  ast (stdlib only)
"""

import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class CallParseError(Exception):
    """Raised when a call string cannot be safely parsed."""


@dataclass
class ParsedCall:
    function_name: str
    args: list


class CallParser:
    """
    Parses a single function-call expression string into (name, args).

    Only accepts:
      - A single top-level Call node
      - func must be a plain Name (no dotted access, no nested calls)
      - args must each be a Constant (str, int, float, bool, None) or a
        UnaryOp(-/+) applied to a numeric Constant (negative numbers)
      - No **kwargs, no *args, no keyword arguments
    """

    def parse(self, call_string: str) -> ParsedCall:
        call_string = call_string.strip()
        if not call_string:
            raise CallParseError("Empty call string.")

        try:
            tree = ast.parse(call_string, mode="eval")
        except SyntaxError as exc:
            raise CallParseError(
                f"Invalid Python expression syntax: {exc}"
            ) from exc

        node = tree.body
        if not isinstance(node, ast.Call):
            raise CallParseError(
                f"Expected a function call, got {type(node).__name__}."
            )

        if not isinstance(node.func, ast.Name):
            raise CallParseError(
                "Function name must be a simple identifier "
                "(no attribute access, no nested calls)."
            )
        function_name = node.func.id

        if node.keywords:
            raise CallParseError("Keyword arguments are not supported.")

        args = [self._extract_literal(arg) for arg in node.args]

        return ParsedCall(function_name=function_name, args=args)

    @staticmethod
    def _extract_literal(node: ast.expr):
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.USub, ast.UAdd)
        ):
            if isinstance(node.operand, ast.Constant) and isinstance(
                node.operand.value, (int, float)
            ):
                value = node.operand.value
                return -value if isinstance(node.op, ast.USub) else value
            raise CallParseError(
                "Unary +/- is only supported on numeric literals."
            )

        raise CallParseError(
            f"Argument must be a literal (str/int/float/bool), "
            f"got {type(node).__name__}."
        )