"""Both native canal survey consumers retain zero, eligibility and actual effects."""

from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _render

from pdx import canal_opportunities as canals
from pdx import decision_rules
from pdx.parser import parse_text
from pdx.situated import programs

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def policy():
    derived = canals.derive({"readers": {}})
    data = {
        "schema": 1,
        "baseline_sha256": canals.load()["sources"][canals.SOURCE],
        "domains": {"geography": True},
        "readers": {
            key: reader
            for key, reader in derived["readers"].items()
            if key in {"bureaucracy", "default"}
        },
        "rules": [
            {key: value for key, value in rule.items() if key != "source"}
            for rule in derived["rules"]
            if rule["field"] in canals.FIELDS
        ],
    }
    return programs.enable(
        decision_rules.from_data(data, source_sha256="0" * 64), source=canals.SOURCE
    )


def _overlay(program):
    guards = {
        term.action_id: (
            "bureaucracy < 1000"
            if term.action_id.endswith("administration")
            else "in_default = yes"
        )
        for term in program.variants
    }
    return programs.render(
        program, guards=guards, ai_guard="is_ai = yes", descriptions={}, producer_markers={}
    )


@pytest.mark.parametrize("name", canals.NAMES)
@pytest.mark.parametrize(
    ("bureaucracy", "default", "factor"),
    [
        (1000, False, 1),
        (999.99, False, 0.8),
        (-1, False, 0.8),
        (1000, True, 0.85),
        (999.99, True, 0.65),
        (None, True, 0.85),
        (999.99, None, 0.8),
        (None, None, 1),
    ],
)
def test_independent_net_cost_manual_reference_and_native_pdx(
    policy, name, bureaucracy, default, factor
):
    field = f"{name}_survey_decision.ai_chance"
    program = next(
        program for program in policy.consumer_programs if ".".join(program.field) == field
    )
    values = {"bureaucracy": bureaucracy, "default": default}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(field, ("native", 1))[
        1
    ] == pytest.approx(factor)
    native = _block(
        _block(parse_text(canals.frozen_inputs()[canals.SOURCE]).root, f"{name}_survey_decision"),
        "ai_chance",
    )
    body = (
        "\n".join(_render(row) for row in native.items if getattr(row, "key", "") != "value")
        + "\n"
        + _overlay(program)
    )
    facts = {
        "ROOT": {
            "is_ai": True,
            "bureaucracy": bureaucracy,
            "in_default": default,
            "produced_bureaucracy": 6000,
            "has_strategy": {(("argument", "ai_strategy_armed_isolationism"),): False},
            "is_diplomatic_play_committed_participant": False,
            "is_at_war": False,
        }
    }
    assert _native_number(0, body, facts) == pytest.approx(10 * factor)
    # Total production remains 6000 in every row; net capacity alone varies.
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert (
        decision_rules.evaluate_ir(replace(policy, enabled_domains=frozenset()), values, is_ai=True)
        == {}
    )


@pytest.mark.parametrize("name", canals.NAMES)
@pytest.mark.parametrize(
    "changed",
    [
        {"produced_bureaucracy": 5000},
        {"produced_bureaucracy": 1001},
        {"has_strategy": {(("argument", "ai_strategy_armed_isolationism"),): True}},
        {"is_at_war": True},
        {"is_diplomatic_play_committed_participant": True},
    ],
)
def test_native_zero_and_terminal_zero_are_never_overridden(policy, name, changed):
    program = next(
        program
        for program in policy.consumer_programs
        if program.field[0] == f"{name}_survey_decision"
    )
    native = _block(
        _block(parse_text(canals.frozen_inputs()[canals.SOURCE]).root, f"{name}_survey_decision"),
        "ai_chance",
    )
    body = (
        "\n".join(_render(row) for row in native.items if getattr(row, "key", "") != "value")
        + "\n"
        + _overlay(program)
    )
    facts = {
        "is_ai": True,
        "bureaucracy": -1,
        "in_default": True,
        "produced_bureaucracy": 6000,
        "has_strategy": {(("argument", "ai_strategy_armed_isolationism"),): False},
        "is_at_war": False,
        "is_diplomatic_play_committed_participant": False,
        **changed,
    }
    assert _native_number(0, body, {"ROOT": facts}) == 0


def test_complete_help_effects_and_two_exact_consumers_are_frozen():
    inputs = canals.frozen_inputs()
    canals.verify_inputs(inputs)
    catalog = canals.consumer_catalog()
    assert {row["field"] for row in catalog} == {*canals.FIELDS, *canals.PURCHASE_FIELDS}
    assert all(row["native_root"] == "country" and row["actor"] == "root" for row in catalog)
    assert all(row["operation"] == "multiply" and row["native_base"] == 0 for row in catalog)
    surveys = [row for row in catalog if row["field"] in canals.FIELDS]
    purchases = [row for row in catalog if row["field"] in canals.PURCHASE_FIELDS]
    assert all(row["cost"] == 1000 and row["cost_source"] == canals.MODIFIERS for row in surveys)
    assert all(
        row["cost"] == 30000
        and row["duration_months"] == 120
        and row["cost_source"] == canals.PURCHASE_MODIFIERS
        for row in purchases
    )
    for source in inputs:
        with pytest.raises(ValueError, match="漂移"):
            canals.verify_inputs({**inputs, source: inputs[source] + "\n# drift"})
    with pytest.raises(ValueError, match="完整身份"):
        canals.derive({"readers": {"bureaucracy": {"engine": "produced_bureaucracy"}}})


def test_unknown_cost_does_not_assume_default_or_free_administration(policy):
    assert decision_rules.evaluate_ir(policy, {}, is_ai=True) == {}
    assert all(rule.operation == "multiply" and rule.value > 0 for rule in policy.rules)
    assert all(not rule.conservative_unknown_facts for rule in policy.rules)
