"""完整消费者的顺序反例：原版保护须在新增评分之后继续执行。"""

from __future__ import annotations

import hashlib
import operator
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from pdx import decision_interfaces, decision_rules, decisions
from pdx.model import Block, Scalar
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Callable


def _block(text, field):
    node = parse_text(text).root
    for part in field.split("."):
        assignment = node.first(part)
        assert assignment is not None
        assert isinstance(assignment.value, Block)
        node = assignment.value
    return node


def _condition(node, facts, mode="AND"):
    values = []
    for item in node.assignments():
        if item.key == "exists":
            values.append(item.value.text == "ROOT")
        elif isinstance(item.value, Block):
            if item.key == "can_reach_target_country":
                values.append(facts["reachable"])
            else:
                values.append(_condition(item.value, facts, item.key))
        else:
            expected = {"yes": True, "no": False}.get(item.value.text)
            if item.key == "is_subject_of":
                values.append(facts["existing_subject"])
            elif expected is None:
                comparison = {
                    "=": operator.eq,
                    "<": operator.lt,
                    "<=": operator.le,
                    ">": operator.gt,
                    ">=": operator.ge,
                }[item.op]
                values.append(comparison(facts[item.key], float(item.value.text)))
            else:
                values.append(facts[item.key] == expected)
    return any(values) if mode == "OR" else not all(values) if mode == "NOT" else all(values)


def _number(block, facts, value=0.0):
    taken = False
    for item in block.assignments():
        if item.key in {"limit", "desc"}:
            continue
        if item.key in {"if", "else_if", "else"}:
            if item.key == "if":
                taken = False
            if not taken and (
                item.key == "else" or _condition(item.value.first("limit").value, facts)
            ):
                value = _number(item.value, facts, value)
                taken = True
        else:
            operand = (
                float(item.value.text)
                if isinstance(item.value, Scalar)
                else _number(item.value, facts)
            )
            operations: dict[str, Callable[[float, float], float]] = {
                "value": lambda _old, new: new,
                "add": operator.add,
                "multiply": operator.mul,
                "min": max,
                "max": min,
            }
            value = operations[item.key](value, operand)
    return value


def _generate(field, body, operation, adjustment):
    wrapped = body
    for part in reversed(field.split(".")):
        wrapped = f"{part} = {{ {wrapped} }}"
    baseline = f"ai_strategy_default = {{ {wrapped} }}\n"
    original = decision_rules.load()
    reader = next(reader for reader in original.readers if reader.key == "default")
    rule = replace(
        original.rules[0],
        id="synthetic_safety",
        field=tuple(field.split(".")),
        conditions=(decision_rules.Predicate("default", "=", False),),
        operation=operation,
        value=adjustment,
    )
    policy = replace(
        original,
        readers=(reader,),
        rules=(rule,),
        enabled_domains=frozenset({rule.domain}),
        baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest(),
    )
    return decision_rules.patch(baseline, policy, baseline=baseline, reader_evidence="in_default")


@pytest.mark.parametrize(
    ("reachable", "existing", "refusal"),
    [(False, False, False), (True, False, True), (False, True, False), (True, False, False)],
)
@pytest.mark.parametrize("is_ai", [False, True])
def test_complete_subject_result_keeps_reachability_refusal_and_native_clamp(
    reachable, existing, refusal, is_ai
):
    body = """value = 0
    if = { limit = { OR = {
        scope:target_country = { is_subject_of = root }
        can_reach_target_country = { TARGET_COUNTRY = scope:target_country }
    } } add = 50 }
    if = { limit = { hard_refusal = yes } multiply = 0 }
    if = { limit = { scope:target_country = { is_subject_of = root } } min = 100 max = 1000 }
    else = { min = 0 max = 200 }
    """
    generated = _generate("subject_value", body, "add", 3)
    value = _number(
        _block(generated, "ai_strategy_default.subject_value"),
        {
            "reachable": reachable,
            "existing_subject": existing,
            "hard_refusal": refusal,
            "is_ai": is_ai,
            "in_default": False,
        },
    )
    expected = 100 if existing else 0 if refusal or not reachable else 53 if is_ai else 50
    assert value == expected


@pytest.mark.parametrize(
    ("field", "body", "operation", "adjustment", "expected"),
    [
        ("max_active_stances", "value = 1 min = 1 max = 10", "multiply", 0.9, 1),
        ("state_value", "value = 1000 min = 0 max = 1000", "multiply", 1.05, 1000),
        ("become_subject_value", "value = 0 max = 0 min = -200", "add", 3, 0),
        ("negotiation_chance", "value = 1 max = 1", "multiply", 1.1, 1),
    ],
)
def test_complete_numeric_consumer_retains_native_bounds(
    field, body, operation, adjustment, expected
):
    generated = _generate(field, body, operation, adjustment)
    assert (
        _number(
            _block(generated, "ai_strategy_default." + field),
            {"is_ai": True, "in_default": False},
        )
        == expected
    )


def test_subject_guard_drift_refuses_generation():
    with pytest.raises(ValueError, match="可达性保护"):
        _generate("subject_value", "value = 0 if = { limit = { is_ai = yes } add = 10 }", "add", 3)


@pytest.mark.parametrize(
    "field", ["wanted_construction_output", "ai_strategy_default.wanted_construction_output"]
)
@pytest.mark.parametrize(
    ("operation", "adjustment"),
    [
        ("add", 3),
        ("subtract", -3),
        ("multiply", -1),
        ("multiply", 0),
        ("multiply", float("nan")),
        ("multiply", float("inf")),
    ],
)
def test_construction_consumer_rejects_operations_that_break_native_zero_or_direction(
    field, operation, adjustment
):
    """接口禁止零分后加法复活和非正乘数改变原版数值方向。"""
    rules = decision_rules.load()
    rule = replace(
        rules.rules[0], field=tuple(field.split(".")), operation=operation, value=adjustment
    )
    policy = replace(rules, rules=(rule,), semantic_ir=())
    with pytest.raises(ValueError, match=r"建设目标.*正乘数"):
        decision_interfaces.validate(policy)


@pytest.mark.parametrize("operation", ["add", "subtract"])
def test_construction_patch_rejects_additive_bypass(operation):
    with pytest.raises(ValueError, match=r"建设目标.*正乘数"):
        _generate("wanted_construction_output", "value = 0 min = 0", operation, 3)


@pytest.mark.parametrize("population", [250000, 250001])
@pytest.mark.parametrize("is_ai", [True, False])
def test_construction_positive_multiplier_keeps_native_population_zero_and_clamp(population, is_ai):
    """独立解释完整合成字段，核对人口边界和玩家的最终数值。"""
    body = """value = 100
    if = { limit = { total_population <= 250000 } multiply = 0 }
    min = 0
    """
    generated = _generate("wanted_construction_output", body, "multiply", 1.3)
    value = _number(
        _block(generated, "ai_strategy_default.wanted_construction_output"),
        {"is_ai": is_ai, "in_default": False, "total_population": population},
    )
    assert value == (0 if population <= 250000 else 130 if is_ai else 100)


def test_current_construction_rules_satisfy_positive_multiplier_contract():
    rules = decision_rules.load()
    selected = tuple(rule for rule in rules.rules if rule.field == ("wanted_construction_output",))
    assert {rule.id for rule in selected} == {
        "fiscal_construction_guard",
        "liquidity_construction_guard",
        "remaining_industrial_construction_need",
        "remaining_industrial_construction_need_funded",
        "remaining_reconstruction_need",
        "remaining_reconstruction_need_funded",
    }
    assert all(rule.operation == "multiply" and rule.value > 0 for rule in selected)
    decision_interfaces.validate(replace(rules, rules=selected, semantic_ir=()))


@pytest.mark.parametrize("refusal", [True, False])
def test_treaty_port_cost_discount_refusal_and_final_cap_remain_last(refusal):
    body = (
        "value = 100 "
        + "if = { limit = { is_ai = yes } add = 0 } " * 4
        + """
    if = { limit = { is_ai = yes }
        multiply = 0.25
        if = { limit = { hard_refusal = yes } multiply = 0 }
    }
    min = 0 max = 100
    """
    )
    generated = _generate("treaty_port_value", body, "add", 3)
    assert _number(
        _block(generated, "ai_strategy_default.treaty_port_value"),
        {"is_ai": True, "in_default": False, "hard_refusal": refusal},
    ) == (0 if refusal else 25.75)


@pytest.mark.parametrize("field", ["conquer_state", "transfer_subject"])
@pytest.mark.parametrize("refusal", [True, False])
def test_wargoal_zero_clamp_and_intentional_regional_multiplier_remain_last(field, refusal):
    body = "value = 100 if = { limit = { hard_refusal = yes } multiply = 0 } min = 0 max = 100 multiply = 2.5"
    generated = _generate("wargoal_scores." + field, body, "add", -5)
    assert _number(
        _block(generated, "ai_strategy_default.wargoal_scores." + field),
        {"is_ai": True, "in_default": False, "hard_refusal": refusal},
    ) == (0 if refusal else 237.5)


def test_liberation_special_goal_is_not_amplified_or_clamped_away():
    generated = _generate(
        "wargoal_scores.liberate_subject",
        "value = 100 min = 0 max = 100 add = 1000",
        "multiply",
        1.1,
    )
    assert (
        _number(
            _block(generated, "ai_strategy_default.wargoal_scores.liberate_subject"),
            {"is_ai": True, "in_default": False},
        )
        == 1100
    )


@pytest.mark.parametrize("refusal", [True, False])
@pytest.mark.parametrize("is_ai", [True, False])
def test_action_overlay_cannot_revive_native_aggression_zero(refusal, is_ai):
    baseline = """ai_strategy_default = {
    aggression = {
        value = 2
        if = { limit = { hard_refusal = yes } multiply = 0.0 }
        if = { limit = { is_ai = yes } multiply = 0.5 }
    }
}
"""
    policy = replace(
        decisions.load(),
        enabled=False,
        baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest(),
    )
    generated = decisions.patch_default(
        baseline,
        policy,
        action_overlay={"aggression": "if = { limit = { ROOT ?= { is_ai = yes } } add = 0.1 }\n"},
    )
    expected = 0 if refusal else 1.05 if is_ai else 2
    assert (
        _number(
            _block(generated, "ai_strategy_default.aggression"),
            {"is_ai": is_ai, "hard_refusal": refusal},
        )
        == expected
    )


def test_aggression_overlay_refuses_missing_native_zero_boundary():
    baseline = "ai_strategy_default = { aggression = { value = 2 } }\n"
    policy = replace(
        decisions.load(),
        enabled=False,
        baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest(),
    )
    with pytest.raises(ValueError, match="归零保护"):
        decisions.patch_default(baseline, policy, action_overlay={"aggression": "add = 0.1"})


@pytest.mark.parametrize("refusal", [True, False])
@pytest.mark.parametrize("is_ai", [True, False])
def test_rule_aggression_keeps_zero_boundary_and_later_native_multipliers(refusal, is_ai):
    generated = _generate(
        "aggression",
        "value = 2 if = { limit = { hard_refusal = yes } multiply = 0.0 } "
        "if = { limit = { is_ai = yes } multiply = 0.5 }",
        "add",
        0.1,
    )
    assert _number(
        _block(generated, "ai_strategy_default.aggression"),
        {"hard_refusal": refusal, "is_ai": is_ai, "in_default": False},
    ) == pytest.approx(0 if refusal else 1.05 if is_ai else 2)
