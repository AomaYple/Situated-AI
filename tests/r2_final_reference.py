"""Independent interpreter for the complete native diplomacy score in R2 reviews.

Road and school use test_network_profile's independent numeric interpreter.
This file adds only the native diplomacy vocabulary that it does not cover;
neither interpreter calls production evaluation, rendering or specialization.
"""

from __future__ import annotations

from pdx.model import Block, Scalar


def _block(value):
    assert isinstance(value, Block)
    return value


def _scalar(value):
    assert isinstance(value, Scalar)
    return value.unquoted


def _condition(block, facts, scope="actor"):
    results = []
    for item in block.assignments():
        if item.key in {"AND", "OR", "NOT"}:
            values = [
                _condition(Block([child]), facts, scope) for child in _block(item.value).items
            ]
            result = any(values) if item.key == "OR" else all(values)
            results.append(not result if item.key == "NOT" else result)
        elif item.key == "is_ai":
            assert scope == "actor"
            results.append(facts["ai"] is (_scalar(item.value) == "yes"))
        elif item.key == "always":
            assert item.op == "="
            literal = _scalar(item.value)
            assert literal in {"yes", "no"}
            results.append(literal == "yes")
        elif item.key == "scope:target_country":
            assert scope == "actor"
            results.append(_condition(_block(item.value), facts, "target"))
        elif item.key == "c:HAW":
            assert item.op == "?="
            results.append(
                bool(facts.get("hawaii_exists", False))
                and _condition(_block(item.value), facts, "hawaii")
            )
        elif item.key == "this":
            assert scope == "hawaii"
            assert _scalar(item.value) == "scope:target_country"
            results.append(bool(facts.get("hawaii_is_target", False)))
        elif item.key in {
            "ai_has_regional_objective_befriend_reason",
            "ai_is_regional_objective_protect_target",
        }:
            assert scope == "actor"
            body = _block(item.value)
            assert body.keys() == ["TARGET"]
            assert _scalar(body.first("TARGET").value) == "scope:target_country"
            results.append(bool(facts.get(item.key, False)))
        elif item.key == "has_attitude":
            assert scope == "actor"
            parameters = {
                child.key: _scalar(child.value) for child in _block(item.value).assignments()
            }
            assert parameters["who"] == "scope:target_country"
            assert parameters["attitude"] in {"protective", "conciliatory"}
            results.append(bool(facts.get(parameters["attitude"], False)))
        elif item.key == "has_journal_entry":
            assert scope == "actor"
            assert _scalar(item.value) == "je_hawaiian_interest"
            results.append(_scalar(item.value) in facts.get("journals", ()))
        elif item.key == "is_subject_of":
            assert scope in {"actor", "target"}
            assert _scalar(item.value) == ("scope:target_country" if scope == "actor" else "root")
            results.append(bool(facts.get(scope + "_is_subject", False)))
        elif item.key == "has_diplomatic_pact":
            assert scope == "target"
            assert {
                child.key: _scalar(child.value) for child in _block(item.value).assignments()
            } == {"who": "root", "type": "support_separatism"}
            results.append(bool(facts["target-interference"]))
        elif item.key == "influence":
            assert scope == "actor"
            assert item.op in {"<", ">="}
            value = facts["influence"]
            results.append(
                value < float(_scalar(item.value))
                if item.op == "<"
                else value >= float(_scalar(item.value))
            )
        else:
            raise AssertionError(f"unreviewed diplomacy condition: {item.key}")
    return all(results)


def diplomacy_score(block, facts, initial=0):
    value = initial
    for item in block.assignments():
        if item.key == "limit":
            continue
        if item.key == "if":
            body = _block(item.value)
            limit = body.first("limit")
            assert limit is not None
            if _condition(_block(limit.value), facts):
                value = diplomacy_score(body, facts, value)
        elif item.key in {"value", "add", "multiply", "min", "max"}:
            if isinstance(item.value, Block):
                operand = diplomacy_score(item.value, facts, 1 if item.key == "multiply" else 0)
            else:
                token = _scalar(item.value)
                operand = (
                    facts["target_rank"]
                    if token == "scope:target_country.country_rank"
                    else float(token)
                )
            if item.key == "value":
                value = operand
            elif item.key == "add":
                value += operand
            elif item.key == "multiply":
                value *= operand
            elif item.key == "min":
                value = max(value, operand)
            else:
                value = min(value, operand)
        else:
            raise AssertionError(f"unreviewed diplomacy numeric statement: {item.key}")
    return value
