"""Isolated famine rules; shared production registrations are tested by the integrator."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
from dataclasses import replace

import pytest

from pdx import decision_rules
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.unit


def test_famine_module_has_three_distinct_native_consumers():
    assert importlib.util.find_spec("pdx.famine_opportunities") is not None
    from pdx import famine_opportunities as famine

    assert len(famine.consumer_catalog()) == 3


@pytest.fixture(scope="module")
def policy():
    from pdx import famine_opportunities as famine

    derived = famine.derive({"readers": {}})
    data = {
        "schema": 1,
        "baseline_sha256": famine.load()["sources"][famine.SOURCE],
        "domains": {"political": True},
        "readers": derived["readers"],
        "rules": [{k: v for k, v in r.items() if k != "source"} for r in derived["rules"]],
    }
    return programs.enable(
        decision_rules.from_data(data, source_sha256="0" * 64), source=famine.SOURCE
    )


def _projection(program, policy):
    """Scalar unit witness using observed Boolean inputs, not the collection bridge."""
    rules = {r.id: r for r in policy.rules}
    guards, cost_guards = {}, {}
    for variant in program.variants:
        rule = rules[variant.action_id]
        predicates = {p.fact: f"{p.fact} = {'yes' if p.value else 'no'}" for p in rule.conditions}
        guards[rule.id] = " ".join(predicates.values())
        if rule.conservative_unknown_facts:
            pressure = set(rule.conservative_unknown_facts)
            core = " ".join(v for k, v in predicates.items() if k not in pressure)
            cheap = "OR = { " + " ".join("NOT = { " + predicates[k] + " }" for k in pressure) + " }"
            cost_guards[rule.id] = core, cheap
    return programs.render(
        program,
        guards=guards,
        ai_guard="is_ai = yes",
        descriptions={},
        producer_markers={},
        cost_guards=cost_guards,
    )


@pytest.mark.parametrize(
    ("railway", "nonrailway", "default", "expected"),
    [
        (False, True, False, (1.12, 0.89, 1.22)),
        (True, False, False, (1.22, 1.07, 1.34)),
        (True, True, False, (1.22, 0.97, 1.34)),
        (False, True, True, (1.04, 0.86, 1.16)),
        (None, None, None, (1.04, 0.86, 1.16)),
        (True, None, False, (1.22, 0.97, 1.34)),
    ],
)
def test_shared_scalar_reference_and_rendered_unit_projection(
    policy, railway, nonrailway, default, expected
):
    from pdx import famine_opportunities as famine

    values = {
        famine.READER: True,
        famine.RAILWAY: railway,
        famine.NONRAILWAY: nonrailway,
        "default": default,
    }
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    for name, factor in zip(famine.NAMES, expected, strict=True):
        field = f"je_indian_famines_button_{name}.ai_chance"
        program = next(p for p in policy.consumer_programs if ".".join(p.field) == field)
        assert reference[field][1] == pytest.approx(factor)
        overlay = _projection(program, policy)
        result = pdx_eval.select(overlay, {**values, "is_ai": True})
        assert result.delta == pytest.approx(factor)
        # Positive bounded multiplication never resurrects a rejected native0.
        assert 0 * result.delta == 0
        assert 10 * result.delta == pytest.approx(10 * factor)


@pytest.mark.parametrize("affected", [False, None, "yes", 1])
def test_necessary_famine_unknown_or_false_never_adds_cost_or_benefit(policy, affected):
    from pdx import famine_opportunities as famine

    values = {
        famine.READER: affected,
        famine.RAILWAY: True,
        famine.NONRAILWAY: None,
        "default": True,
    }
    assert decision_rules.evaluate_ir(policy, values, is_ai=True) == {}


def test_player_disabled_unknown_auxiliary_and_positive_bounded_contract(policy):
    from pdx import famine_opportunities as famine

    values = {famine.READER: True, "default": False}
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert (
        decision_rules.evaluate_ir(replace(policy, enabled_domains=frozenset()), values, is_ai=True)
        == {}
    )
    assert all(r.operation == "multiply" and 0 < r.value <= 1.5 for r in policy.rules)
    assert all(0.5 <= p.lower <= p.upper <= 1.5 for p in policy.consumer_programs)
    assert {
        r.contribution_group
        for r in policy.rules
        if r.id.startswith("famine_work_camps") and "mortality" in r.id
    } == {"famine_work_camps_unavoidable_mortality", "famine_work_camps_nonrailway_extra_mortality"}


def test_frozen_inputs_exact_native_cost_mortality_and_query_contracts():
    from pdx import famine_opportunities as famine

    inputs = famine.frozen_inputs()
    catalog = famine.consumer_catalog()
    assert set(inputs) == famine.SOURCES
    assert {r["native_base"] for r in catalog} == {10}
    assert all(
        r["actor"] == "root" and r["native_root"] == "country" and r["operation"] == "multiply"
        for r in catalog
    )
    assert {r["cost_scale"] for r in catalog} == {
        "money_amount_multiplier_medium",
        "money_amount_multiplier_small",
        "money_amount_multiplier_very_small",
    }
    work = next(r for r in catalog if "work_camps" in r["definition"])
    assert work["effects"]["work_camps"]["state_mortality_mult"] == "0.02"
    assert work["effects"]["improved_work_camps"]["state_mortality_mult"] == "0.01"
    expected = {
        "affected": "any_scope_state = { has_famine = yes }",
        "railway": "any_scope_state = { has_famine = yes has_building = building_railway }",
        "nonrailway": "any_scope_state = { has_famine = yes NOT = { has_building = building_railway } }",
    }
    for mode, expression in expected.items():
        query = famine.query_from_reader("any_scope_state", {famine.QUERY_PARAMETER: mode})
        assert famine.render_query(query) == expression
        assert not parse_text(expression).errors
        compiled = famine.compile_query(query, inputs)
        assert compiled.expression == expression
        assert compiled.local_collections == ("owned_states",)
        assert compiled.world_scans == 0
        assert set(famine.required_query_sources(query)) == famine.SOURCES
        assert dict(compiled.source_hashes) == famine.load()["sources"]
    for source in inputs:
        with pytest.raises(ValueError, match="漂移"):
            famine.verify_inputs({**inputs, source: inputs[source] + "\n# drift"})


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("any_country", {"famine_query": "affected"}),
        ("any_scope_state", {"famine_query": "foreign"}),
        ("any_scope_state", {"famine_query": "railway", "extra": "yes"}),
        ("any_scope_state", {"famine_query": []}),
    ],
)
def test_query_rejects_scope_injection_unknown_modes_and_malformed_parameters(engine, parameters):
    from pdx import famine_opportunities as famine

    with pytest.raises(ValueError):
        famine.query_from_reader(engine, parameters)


def test_existing_fiscal_reader_identity_cannot_be_replaced():
    from pdx import famine_opportunities as famine

    with pytest.raises(ValueError, match="完整身份"):
        famine.derive({"readers": {"default": {"engine": "taking_loans"}}})


def test_semantic_mortality_direction_is_not_signed_by_repinning_sources(monkeypatch):
    from pdx import famine_opportunities as famine

    snapshot = copy.deepcopy(famine._snapshot())
    inputs = dict(snapshot["inputs"])
    old = "state_mortality_mult = 0.02"
    assert old in inputs[famine.MODIFIERS]
    inputs[famine.MODIFIERS] = inputs[famine.MODIFIERS].replace(
        old, "state_mortality_mult = -0.02", 1
    )
    params = famine.load()
    params["sources"][famine.MODIFIERS] = hashlib.sha256(
        inputs[famine.MODIFIERS].encode()
    ).hexdigest()
    snapshot["contracts"][famine.MODIFIERS] = famine._shape(
        parse_text(inputs[famine.MODIFIERS]).root
    )
    monkeypatch.setattr(famine, "load", lambda: params)
    monkeypatch.setattr(famine, "_snapshot", lambda: snapshot)
    with pytest.raises(ValueError, match="正死亡代价"):
        famine.verify_inputs(inputs)
