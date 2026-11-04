"""Same candidate-state recovery and retained independent railway costs."""

import copy
import hashlib
import re
from dataclasses import replace
from typing import Any

import pytest

from pdx import decision_adapters, decision_interfaces, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration
SOURCE = "common/buildings/11_private_infrastructure.txt"
FIELD = ("building_railway", "ai_value")


@pytest.fixture(scope="module")
def rail():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[SOURCE]
    rules = tuple(r for r in original.rules if r.field == FIELD)
    keys = {key for rule in rules for key in rule.input_keys()}
    policy = programs.enable(
        replace(
            original,
            rules=rules,
            readers=tuple(r for r in original.readers if r.key in keys),
            enabled_domains=frozenset(r.domain for r in rules),
            semantic_ir=(),
            consumer_programs=(),
        ),
        source=SOURCE,
    )
    inputs = decision_adapters.read_inputs(adapters)
    assert len(decision_interfaces.verify_state_devastation_sources(inputs)) == 3
    words = frozenset(decision_adapters.reader_evidence(inputs))
    text = decision_rules.patch(
        inputs[SOURCE], policy, baseline=inputs[SOURCE], default_strategy=False, reader_words=words
    )
    return policy, text, inputs, words


def _facts(changes, *, is_ai=True):
    owner = {
        "is_ai": is_ai,
        "is_at_war": False,
        "in_default": False,
        "has_variable": {(("argument", "recently_lost_war"),): True},
        "market": {},
    }
    state = {"owner": owner, "infrastructure_delta": -1, "devastation": 0.21}
    for key, value in changes.items():
        if key == "state_owner_war_defeat":
            owner["has_variable"] = {(("argument", "recently_lost_war"),): value}
        elif key == "state_owner_war":
            owner["is_at_war"] = value
        elif key == "state_owner_default":
            owner["in_default"] = value
        elif key == "state_infrastructure":
            state["infrastructure_delta"] = value
        elif key == "state_devastation":
            state["devastation"] = value
        elif key == "pm_active_building_railway_pm_early_trains":
            state["is_production_method_active"] = {"building_railway": {"pm_early_trains": value}}
        elif key.startswith("state_owner_"):
            good, suffix = key.removeprefix("state_owner_").rsplit("_", 1)
            owner["market"].setdefault(f"mg:{good}", {})[
                "market_goods_pricier" if suffix == "price" else "market_goods_delta"
            ] = value
    return {
        "ROOT": state,
        "other_state": {"devastation": 1, "infrastructure_delta": -500},
        "other_country": {"is_at_war": False, "recently_lost_war": True},
    }


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.25),
        ({"state_devastation": 0.2}, 1.1),
        ({"state_devastation": None}, 1.1),
        ({"state_infrastructure": 0}, 1),
        ({"state_infrastructure": None}, 1),
        ({"state_owner_war": True}, 1.1),
        ({"state_owner_war": None}, 1.1),
        ({"state_owner_war_defeat": False}, 1.1),
        ({"state_owner_war_defeat": None}, 1.1),
        ({"state_owner_default": True}, 1.1),
        ({"state_owner_default": None}, 1.25),
        ({"state_devastation": 0.2, "state_owner_default": True}, 0.95),
        (
            {
                "pm_active_building_railway_pm_early_trains": True,
                "state_owner_coal_balance": -1,
                "state_owner_coal_price": 0.6,
            },
            1.05,
        ),
        (
            {
                "pm_active_building_railway_pm_early_trains": True,
                "state_owner_coal_balance": -1,
                "state_owner_coal_price": 0.6,
                "state_owner_engines_balance": -1,
                "state_owner_engines_price": 0.6,
                "state_owner_default": True,
            },
            0.7,
        ),
    ],
)
def test_recovery_upgrades_existing_foundation_and_costs_still_lower_net_support(
    rail, changes, expected
):
    policy, text, inputs, words = rail
    values = {
        "state_infrastructure": -1,
        "state_devastation": 0.21,
        "state_owner_war": False,
        "state_owner_war_defeat": True,
        "state_owner_default": False,
        **changes,
    }
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(".".join(FIELD), ("", 1))[
        1
    ] == pytest.approx(expected)
    overlay = pdx_eval.marked_block(text, policy.consumer_programs[0].action_id)
    actual = pdx_eval.select(overlay, _facts(changes))
    assert (actual.delta if actual.operation else 1) == pytest.approx(expected)
    assert pdx_eval.select(overlay, _facts(changes, is_ai=False)).operation is None
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.patch(
            inputs[SOURCE],
            policy,
            baseline=inputs[SOURCE],
            default_strategy=False,
            reader_words=words,
            enabled_domains=frozenset(),
        )
        == inputs[SOURCE]
    )


def test_state_recovery_does_not_pool_other_states_or_countries_and_keeps_native_zero(rail):
    policy, text, inputs, _ = rail
    recovery = [
        r for r in policy.rules if r.id == "infrastructure_railway_observed_postwar_recovery"
    ]
    assert len(recovery) == 1
    assert recovery[0].contribution_group == "building_output_demand"
    assert len(recovery[0].conditions) == 4
    # This field has native dynamic expressions outside the limited evaluator;
    # retain its actual generated multiplier while independently setting base.
    overlay_start = text.index("# SITAI BEGIN information:building_railway.ai_value")
    overlay_end = text.index("# SITAI END information:building_railway.ai_value", overlay_start)
    overlay = parse_text("\n".join(text[overlay_start:overlay_end].splitlines()[1:])).root
    for native in (0, -3, 10):
        numeric = Block(
            [Assignment("value", "=", Scalar(str(native))), *copy.deepcopy(overlay.items)]
        )
        assert pdx_eval._numeric_value(
            Assignment("multiply", "=", numeric), _facts({})
        ) == pytest.approx(native * 1.25)
    restored = re.sub(
        r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
        "",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )

    def tree(node):
        if isinstance(node, Scalar):
            return node.text, node.quoted
        if isinstance(node, Assignment):
            return node.key, node.op, node.prefix, tree(node.value)
        assert isinstance(node, Block)
        return tuple(tree(item) for item in node.items)

    assert tree(parse_text(restored).root) == tree(parse_text(inputs[SOURCE]).root)


@pytest.mark.parametrize("mutation", ["path", "scope", "minimum", "maximum", "unit", "root"])
def test_devastation_reader_rejects_role_scope_and_unit_aliases(rail, mutation):
    policy, _, _, _ = rail
    reader = next(r for r in policy.readers if r.engine == "devastation")
    all_changes: dict[str, dict[str, Any]] = {
        "path": {"path": ("owner",)},
        "scope": {"scope": "target_state"},
        "minimum": {"minimum": None},
        "maximum": {"maximum": 100},
        "unit": {"unit": "currency"},
        "root": {},
    }
    changes = all_changes[mutation]
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(
            replace(reader, **changes), () if mutation == "root" else ("owner",)
        )


@pytest.mark.parametrize("mutation", ["missing", "hash", "scope", "threshold", "memory"])
def test_devastation_and_native_defeat_lifecycle_pin_and_ast_are_enforced(
    rail, monkeypatch, mutation
):
    _, _, originals, _ = rail
    inputs = dict(originals)
    source = decision_interfaces.STATE_DEVASTATION_SOURCE
    if mutation == "missing":
        inputs.pop(source)
    elif mutation == "hash":
        inputs[source] += "# drift"
    elif mutation == "memory":
        inputs["common/on_actions/00_code_on_actions.txt"] = inputs[
            "common/on_actions/00_code_on_actions.txt"
        ].replace("days = 1825", "days = 1826")
    else:
        old, new = (
            ("devastation > 0.2", "devastation > 0.3")
            if mutation == "threshold"
            else (
                "any_scope_state = {\n\t\t\t\t\t\tis_incorporated = yes\n\t\t\t\t\t\tdevastation",
                "any_country = {\n\t\t\t\t\t\tis_incorporated = yes\n\t\t\t\t\t\tdevastation",
            )
        )
        assert old in inputs[source]
        inputs[source] = inputs[source].replace(old, new)
        monkeypatch.setattr(
            decision_interfaces,
            "STATE_DEVASTATION_SHA256",
            hashlib.sha256(normalized_text(inputs[source]).encode()).hexdigest(),
        )
    with pytest.raises(ValueError):
        decision_interfaces.verify_state_devastation_sources(inputs)
