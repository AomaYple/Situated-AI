"""Finite independent VM for the complete locked conquest score and overlay.

Only native special atoms named here are added to the existing actual-PDX
condition interpreter. Nonempty strategic-region traversal remains outside
this fixture's physical world, rather than being treated as known absent.
"""

from pdx.model import Block, Scalar
from pdx.situated import pdx_eval


def all3(values):
    return False if False in values else None if None in values else True


def any3(values):
    return True if True in values else None if None in values else False


def condition(block, world):
    results = []
    for row in block.assignments():
        if row.key in {"AND", "OR", "NOT"}:
            values = [condition(Block([r]), world) for r in row.value.assignments()]
            value = any3(values) if row.key == "OR" else all3(values)
            results.append(None if value is None else not value if row.key == "NOT" else value)
        elif row.key in {"has_secret_goal", "has_attitude"}:
            expected = {
                "has_secret_goal": (
                    ("who", "scope:target_state.owner"),
                    ("secret_goal", "conquer"),
                ),
                "has_attitude": (("who", "scope:target_country"), ("attitude", "antagonistic")),
            }[row.key]
            assert tuple((r.key, r.value.unquoted) for r in row.value.assignments()) == expected
            results.append(world["ROOT"].get(row.key))
        elif row.key == "scope:diplomatic_play":
            assert row.op == "?="
            assert tuple((r.key, r.value.unquoted) for r in row.value.assignments()) == (
                ("initiator_is", "root"),
            )
            play = world.get(row.key)
            results.append(None if play is None else play["initiator_is_root"])
        elif row.key == "scope:target_state.ai_state_value:root":
            assert row.op == ">="
            assert row.value.unquoted == "define:NAI|AI_STRONGLY_DESIRES_STATE_VALUE_THRESHOLD"
            results.append(
                world["scope:target_state"]["ai_state_value:root"]
                >= world["define:NAI|AI_STRONGLY_DESIRES_STATE_VALUE_THRESHOLD"]
            )
        elif row.key == "any_country_strategic_region":
            assert world["ROOT"][row.key] == [], (
                "nonempty native region matching remains a separate obligation"
            )
            results.append(False)
        else:
            results.append(pdx_eval.condition(Block([row]), {**world["ROOT"], **world}))
    return all3(results)


def number(block, world, initial=0):
    total = initial
    chain = False
    for row in block.assignments():
        if row.key in {"limit", "desc"}:
            continue
        if row.key in {"if", "else_if", "else"}:
            if row.key == "if":
                chain = False
            limit = row.value.first("limit")
            hit = not chain and (row.key == "else" or condition(limit.value, world) is True)
            if hit:
                total = number(row.value, world, total)
                chain = True
            continue
        assert row.key in {"value", "add", "multiply", "min", "max"}
        if isinstance(row.value, Block):
            value = number(row.value, world)
        elif row.value.unquoted == "scope:target_state.ai_state_value:root":
            value = world["scope:target_state"]["ai_state_value:root"]
        else:
            assert isinstance(row.value, Scalar)
            value = float(row.value.unquoted)
        total = (
            value
            if row.key == "value"
            else total + value
            if row.key == "add"
            else total * value
            if row.key == "multiply"
            else max(total, value)
            if row.key == "min"
            else min(total, value)
        )
    return total
