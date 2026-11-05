"""Declared conservative pressure, independently checked in generated numeric PDX."""

import hashlib
from dataclasses import replace

import pytest

from pdx import decision_rules
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.unit


def _policy(*, operation="multiply", count=2):
    neutral = 1.0 if operation == "multiply" else 0.0
    readers = tuple(
        decision_rules.Reader(name, name, "root", "boolean", "boolean")
        for name in ("core", "default", "liquidity", "need")
    )
    rules = [
        decision_rules.Rule(
            "need",
            "test",
            ("field",),
            1,
            neutral + 0.2,
            (decision_rules.Predicate("need", "=", True),),
            "demand",
            "none",
            operation=operation,
            contribution_group="need",
        )
    ]
    for index in range(count):
        name = f"cost_{index}"
        fact = "default" if index == 0 else "liquidity"
        rules.append(
            decision_rules.Rule(
                name,
                "test",
                ("field",),
                index + 2,
                neutral - (0.25 if index == 0 else 0.15),
                (
                    decision_rules.Predicate("core", "=", True),
                    decision_rules.Predicate(fact, "=", True),
                ),
                "pressure",
                "absent",
                operation=operation,
                contribution_group="financing",
                semantic_role="cost",
                conservative_unknown_facts=(fact,),
                unknown_cost_basis="bounded fixture pressure",
            )
        )
    return programs.enable(
        decision_rules.RuleSet(
            readers, tuple(rules), hashlib.sha256(b"").hexdigest(), "0" * 64, frozenset({"test"})
        ),
        source="fixture",
    )


def _check(policy, values, expected):
    result = decision_rules.evaluate_ir(policy, values, is_ai=True)
    neutral = policy.consumer_programs[0].neutral
    assert result.get("field", ("", neutral))[1] == pytest.approx(expected)
    cost_guards = {
        rule.id: ("core = yes", f"{rule.conservative_unknown_facts[0]} = no")
        for rule in policy.rules
        if rule.semantic_role == "cost"
    }
    text = programs.render(
        policy.consumer_programs[0],
        guards={rule.id: "always = yes" for rule in policy.rules},
        ai_guard="is_ai = yes",
        descriptions={},
        producer_markers={},
        cost_guards=cost_guards,
    )
    assert pdx_eval.select(text, {**values, "is_ai": True}).delta == pytest.approx(expected)
    return text


@pytest.mark.parametrize(
    ("default", "liquidity", "expected"),
    [
        (None, None, 0.95),
        (True, True, 0.95),
        (False, True, 1.05),
        (False, None, 1.05),
        (False, False, 1.2),
        (None, False, 0.95),
    ],
)
def test_zero_high_tier_does_not_mask_proven_or_unknown_lower_pressure(
    default, liquidity, expected
):
    _check(
        _policy(),
        {"core": True, "need": True, "default": default, "liquidity": liquidity},
        expected,
    )


@pytest.mark.parametrize("core", [None, False, 1, "wrong"])
def test_unknown_identity_never_activates_conservative_cost(core):
    _check(_policy(), {"core": core, "need": True, "default": None, "liquidity": None}, 1.2)


def test_positive_consumer_direction_uses_maximum_without_guessing_role():
    policy = _policy(operation="add")
    rules = tuple(
        replace(rule, value=-rule.value) if rule.semantic_role == "cost" else rule
        for rule in policy.rules
    )
    policy = programs.enable(
        replace(policy, rules=rules, semantic_ir=(), consumer_programs=()), source="fixture"
    )
    _check(policy, {"core": True, "need": True, "default": False, "liquidity": None}, 0.35)


def test_conservative_render_requires_proven_core_and_cheap_guard_contract():
    policy = _policy()
    with pytest.raises(ValueError, match="生成守卫"):
        programs.render(
            policy.consumer_programs[0],
            guards={r.id: "always = yes" for r in policy.rules},
            ai_guard="is_ai = yes",
            descriptions={},
            producer_markers={},
        )


def test_conservative_group_lowering_has_linear_size_and_constant_nesting():
    def script(size):
        return _check(
            _policy(count=size),
            {"core": True, "need": True, "default": None, "liquidity": None},
            0.95,
        )

    small, large = script(4), script(16)
    assert len(large) < len(small) * 4.2

    def nesting(text):
        depth = maximum = 0
        for char in text:
            depth += (char == "{") - (char == "}")
            maximum = max(maximum, depth)
        return maximum

    # Outer AI guard -> operation -> group -> extreme candidate -> core
    # branch -> numeric delta -> cheap branch -> limit; no per-tier nesting.
    assert nesting(large) == nesting(small) == 8
    assert "else_if" not in large


def test_conservative_cost_preserves_producer_marker_and_description_in_live_effect():
    policy = _policy()
    text = programs.render(
        policy.consumer_programs[0],
        guards={rule.id: "always = yes" for rule in policy.rules},
        ai_guard="is_ai = yes",
        descriptions={"cost_0": "fixture_cost_desc"},
        producer_markers={"cost_0": "# PRODUCER cost_0\n"},
        cost_guards={
            "cost_0": ("core = yes", "default = no"),
            "cost_1": ("core = yes", "liquidity = no"),
        },
    )
    assert "# PRODUCER cost_0" in text
    assert "add = { value = -0.25 desc = fixture_cost_desc }" in text
    result = pdx_eval.select(
        text, {"is_ai": True, "core": True, "need": True, "default": None, "liquidity": False}
    )
    assert result.delta == pytest.approx(0.95)
