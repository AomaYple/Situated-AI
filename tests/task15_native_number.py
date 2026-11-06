"""Finite native numeric oracle carried forward from reviewed Task11 tests.

Only the literal native negotiation variables and subject liberty getter are
accepted. Conditions remain the separate three-valued PDX VM; no production
scorer or compiler lowering is consulted.
"""

from test_remaining_joint_consumers import _block

from pdx.model import Block, Scalar
from pdx.situated import pdx_eval


def number(block, facts):
    named = {"scope:amenability", "scope:stall_chance", "scope:advance_chance", "liberty_desire"}

    def condition(limit):
        rows = list(limit.assignments())
        if len(rows) == 1 and rows[0].key == "scope:interest_group" and rows[0].op == "?=":
            comparison = list(rows[0].value.assignments())
            assert len(comparison) == 1
            assert (comparison[0].key, comparison[0].op, comparison[0].value.unquoted) == (
                "amenability_level",
                "!=",
                "4",
            )
            target = facts.get("scope:interest_group")
            return target is not None and target["amenability_level"] != 4
        return pdx_eval.condition(limit, facts)

    def value(node):
        if isinstance(node, Block):
            return execute(node, 0)
        assert isinstance(node, Scalar)
        if node.unquoted in named:
            return facts[node.unquoted]
        return float(node.unquoted)

    def execute(body, result):
        selected = False
        for item in body.assignments():
            if item.key in {"limit", "desc"}:
                continue
            if item.key in {"if", "else_if", "else"}:
                if item.key == "if":
                    selected = False
                if not selected and (
                    item.key == "else" or condition(_block(item.value, "limit")) is True
                ):
                    result = execute(item.value, result)
                    selected = True
                continue
            amount = value(item.value)
            if item.key == "value":
                result = amount
            elif item.key == "add":
                result += amount
            elif item.key == "subtract":
                result -= amount
            elif item.key == "multiply":
                result *= amount
            elif item.key == "divide":
                result /= amount
            elif item.key == "min":
                result = max(result, amount)
            elif item.key == "max":
                result = min(result, amount)
            else:
                raise AssertionError(f"unproved numeric operation: {item.key}")
        return result

    return execute(block, 0)
