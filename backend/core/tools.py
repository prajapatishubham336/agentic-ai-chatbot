import ast
import operator
import os

from langchain_core.tools import tool

ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_calculate(node):

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value

    if isinstance(node, ast.BinOp):

        operator_type = type(node.op)

        if operator_type not in ALLOWED_OPERATORS:
            raise ValueError("Operator not allowed")

        left = safe_calculate(node.left)
        right = safe_calculate(node.right)

        if isinstance(node.op, ast.Pow) and abs(right) > 8:
            raise ValueError("Exponent too large")

        return ALLOWED_OPERATORS[operator_type](
            left, right
        )

    if isinstance(node, ast.UnaryOp):

        operator_type = type(node.op)

        if operator_type not in ALLOWED_OPERATORS:
            raise ValueError("Operator not allowed")

        return ALLOWED_OPERATORS[operator_type](
            safe_calculate(node.operand)
        )

    raise ValueError("Invalid mathematical expression")


@tool
def calculator(expression: str) -> str:
    """
    Calculate mathematical expressions.
    Example: (25 * 4) / 2
    """

    try:
        tree = ast.parse(expression, mode="eval")

        result = safe_calculate(tree.body)

        return str(result)

    except Exception as error:
        return f"Calculation error: {error}"


@tool
def search_web(query: str) -> str:
    """
    Search the web using Tavily.
    """

    if not os.getenv("TAVILY_API_KEY"):
        return "Tavily API key is not configured."

    try:
        from langchain_tavily import TavilySearch

        search = TavilySearch(max_results=5)

        result = search.invoke({
            "query": query
        })

        return str(result)

    except Exception as error:
        return f"Search error: {error}"