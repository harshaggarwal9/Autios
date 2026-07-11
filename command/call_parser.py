























import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class CallParseError(Exception):
    pass


@dataclass
class ParsedCall:
    function_name: str
    args: list


class CallParser:
    










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
