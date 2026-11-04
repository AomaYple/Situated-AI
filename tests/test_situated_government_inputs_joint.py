"""Actual government PM input costs join its complete repair/financing program."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from test_situated_joint_witnesses import _facts

from pdx import config, country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

pytestmark = pytest.mark.integration
SOURCE = "common/buildings/07_government.txt"
FIELD = "building_government_administration.ai_value"
PM_PREFIX = "pm_active_building_government_administration_"
PAPER_METHODS = ("pm_horizontal_drawer_cabinets", "pm_vertical_filing_cabinets", "pm_switch_boards")


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    source = dict(adapters.policies)[SOURCE]
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(source, SOURCE, model)
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        initial_values=tuple(row for row in adapters.initial_values if row.source == SOURCE),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == SOURCE),
        supply=None,
    )
    inputs = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    disabled, _ = decision_adapters.build(
        selected,
        texts=inputs,
        enabled_domains=frozenset(),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return source, policy, inputs[SOURCE], files[SOURCE], disabled, model


def _values(policy, changes):
    values: dict[str, Any] = {
        reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers
    }
    values.update(
        state_owner_bureaucracy=-1,
        state_owner_default=False,
        state_owner_loans=False,
        state_owner_paper_price=0.2,
        state_owner_paper_balance=0,
        state_owner_telephones_price=0.2,
        state_owner_telephones_balance=0,
    )
    values[PM_PREFIX + "pm_horizontal_drawer_cabinets"] = True
    values.update(changes)
    return values


def _overlay(text):
    start = text.index(f"# SITAI BEGIN information:{FIELD}")
    end = text.index(f"# SITAI END information:{FIELD}", start)
    return "\n".join(text[start:end].splitlines()[1:])


PAPER_PRESSURE = {"state_owner_paper_price": 0.6, "state_owner_paper_balance": -1}
TELEPHONE_PRESSURE = {"state_owner_telephones_price": 0.6, "state_owner_telephones_balance": -1}
SWITCH = {
    PM_PREFIX + "pm_horizontal_drawer_cabinets": False,
    PM_PREFIX + "pm_switch_boards": True,
}


def test_government_paper_cost_is_present_in_the_complete_source_program():
    source = dict(decision_adapters.load().policies)[SOURCE]
    policy = programs.enable(source, source=SOURCE)
    result = decision_rules.evaluate(policy, _values(policy, PAPER_PRESSURE), is_ai=True)
    assert result[FIELD][1] == pytest.approx(1.05)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.25),
        (PAPER_PRESSURE, 1.05),
        ({**PAPER_PRESSURE, "state_owner_loans": True}, 0.65),
        ({**PAPER_PRESSURE, "state_owner_default": True}, 0.6),
        ({**PAPER_PRESSURE, "state_owner_default": True, "state_owner_loans": True}, 0.6),
        ({**PAPER_PRESSURE, "state_owner_bureaucracy": 0}, 0.8),
        ({**PAPER_PRESSURE, "state_owner_bureaucracy": None}, 0.8),
        ({**PAPER_PRESSURE, "state_owner_loans": None}, 0.85),
        ({**PAPER_PRESSURE, "state_owner_default": None}, 0.85),
        ({**PAPER_PRESSURE, "state_owner_paper_price": 0.5}, 1.25),
        ({**PAPER_PRESSURE, "state_owner_paper_balance": 0}, 1.25),
        ({**PAPER_PRESSURE, "state_owner_paper_price": None}, 1.25),
        ({**PAPER_PRESSURE, "state_owner_paper_balance": None}, 1.25),
        ({**PAPER_PRESSURE, PM_PREFIX + "pm_horizontal_drawer_cabinets": None}, 1.25),
        ({**PAPER_PRESSURE, PM_PREFIX + "pm_horizontal_drawer_cabinets": False}, 1.25),
        (TELEPHONE_PRESSURE, 1.25),
        ({**SWITCH, **TELEPHONE_PRESSURE}, 1.05),
        ({**SWITCH, **TELEPHONE_PRESSURE, **PAPER_PRESSURE}, 0.85),
        ({**SWITCH, **TELEPHONE_PRESSURE, "state_owner_paper_price": None}, 1.05),
        (
            {
                **SWITCH,
                **TELEPHONE_PRESSURE,
                **PAPER_PRESSURE,
                "state_owner_bureaucracy": None,
            },
            0.60,
        ),
        (
            {
                **PAPER_PRESSURE,
                **{PM_PREFIX + method: True for method in PAPER_METHODS},
            },
            1.05,
        ),
        (
            {
                **PAPER_PRESSURE,
                PM_PREFIX + "pm_horizontal_drawer_cabinets": False,
                PM_PREFIX + "pm_vertical_filing_cabinets": True,
            },
            1.05,
        ),
        ({**PAPER_PRESSURE, "candidate_selected": True, "construction_queued": True}, 1.05),
    ],
)
def test_complete_government_consumer_matches_handwritten_input_costs(
    production, changes, expected
):
    _source, policy, _native, generated, _disabled, _model = production
    values = _values(policy, changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(FIELD)
    observed = pdx_eval.select(_overlay(generated), _facts(policy, values))
    factors = (
        reference[1] if reference else 1,
        observed.delta if observed.operation == "multiply" else 1,
    )
    assert factors == pytest.approx((expected, expected))


def test_actual_government_recipe_effects_and_reader_parameters_remain_exact(production):
    source, policy, _native, _generated, _disabled, _model = production
    text = (config.GAME / "common/production_methods/07_government.txt").read_text(
        encoding="utf-8-sig"
    )
    root = parse_text(text).root
    for method, goods in (
        ("pm_simple_organization", {}),
        ("pm_horizontal_drawer_cabinets", {"paper": "10"}),
        ("pm_vertical_filing_cabinets", {"paper": "20"}),
        ("pm_switch_boards", {"paper": "20", "telephones": "5"}),
    ):
        method_node = root.first(method)
        assert method_node is not None
        assert isinstance(method_node.value, Block)
        building = method_node.value.first("building_modifiers")
        assert building is not None
        assert isinstance(building.value, Block)
        scale = building.value.first("workforce_scaled")
        actual = {}
        if scale is not None:
            assert isinstance(scale.value, Block)
            actual = {
                a.key.removeprefix("goods_input_").removesuffix("_add"): a.value.unquoted
                for a in scale.value.assignments()
                if a.key.startswith("goods_input_") and isinstance(a.value, Scalar)
            }
        assert actual == goods
    costs = tuple(
        r
        for r in source.rules
        if ".".join(r.field) == FIELD and r.id.startswith("administrative_input_")
    )
    assert len(costs) == 4
    assert {r.id: r.contribution_group for r in costs} == {
        **{
            f"administrative_input_government_{method}_paper": "administrative_active_input_paper"
            for method in PAPER_METHODS
        },
        "administrative_input_government_pm_switch_boards_telephones": "administrative_active_input_telephones",
    }
    consumer = next(p for p in policy.consumer_programs if ".".join(p.field) == FIELD)
    expected_ids = {r.id for r in source.rules if ".".join(r.field) == FIELD}
    assert len(expected_ids) == 11
    assert len(expected_ids) < decision_rules.STATIC_BUDGET["candidates_per_field"]
    assert {v.action_id for v in consumer.variants} == expected_ids
    for method in PAPER_METHODS:
        reader = next(r for r in source.readers if r.key == PM_PREFIX + method)
        assert reader.engine == "is_production_method_active"
        assert reader.kind == "boolean"
        assert reader.scope == "root"
        assert reader.path == ()
        assert reader.unit == "boolean"
        assert reader.argument is None
        assert reader.value_field is None
        assert reader.minimum is None
        assert reader.maximum is None
        assert reader.parameters == (
            ("building_type", "building_government_administration"),
            ("production_method", method),
        )


def _syntax(node: Any):
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _syntax(node.value)
    assert isinstance(node, Block)
    return tuple(_syntax(item) for item in node.items)


def test_player_disabled_owner_and_native_tail_remain_independent(production):
    _source, policy, native, generated, disabled, _model = production
    values = _values(policy, PAPER_PRESSURE)
    overlay = _overlay(generated)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert disabled == {}
    assert pdx_eval.select(overlay, _facts(policy, values, is_ai=False)).operation is None
    observed = pdx_eval.select(overlay, {"ROOT": {"owner": None}, "bureaucracy": -1})
    assert observed.operation is None or observed.delta == 1
    before, after = (
        parse_text(native).root.first("building_government_administration"),
        parse_text(generated).root.first("building_government_administration"),
    )
    assert before is not None
    assert after is not None
    assert isinstance(before.value, Block)
    assert isinstance(after.value, Block)
    # The only new child is the already-authorized initialized ai_value.
    original_children = tuple(_syntax(a) for a in before.value.items)
    actual_children = tuple(
        _syntax(a)
        for a in after.value.items
        if not (isinstance(a, Assignment) and a.key == "ai_value")
    )
    assert actual_children == original_children
    assert pdx_eval.select(overlay, _facts(policy, values)).delta > 0
    assert 0 * pdx_eval.select(overlay, _facts(policy, values)).delta == 0


def test_foreign_market_and_wrong_building_method_cannot_supply_input_pressure(production):
    _source, policy, _native, generated, _disabled, _model = production
    values = _values(policy, {PM_PREFIX + "pm_horizontal_drawer_cabinets": False})
    facts = _facts(policy, values)
    root = facts["ROOT"]
    root["is_production_method_active"].setdefault("building_university", {})[
        "pm_horizontal_drawer_cabinets"
    ] = True
    root["market"] = {"mg:paper": {"market_goods_pricier": 0.6, "market_goods_delta": -1}}
    assert pdx_eval.select(_overlay(generated), facts).delta == pytest.approx(1.25)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.1),
        ({"state_tax_capacity": 20}, 1.0),
        ({"state_is_incorporated": False}, 1.0),
        ({"state_is_incorporated": None}, 1.0),
        ({"state_tax_capacity": None}, 1.0),
        ({"state_tax_capacity_usage": None}, 1.0),
        ({"state_owner_bureaucracy": -1}, 1.35),
        ({"state_owner_bureaucracy": -1, "state_tax_capacity": 20}, 1.25),
        ({**SWITCH, **PAPER_PRESSURE, **TELEPHONE_PRESSURE, "state_owner_default": True}, 0.5),
    ],
)
def test_local_tax_repair_independent_of_national_administration(production, changes, expected):
    _source, policy, _native, generated, _disabled, _model = production
    values = _values(
        policy,
        {
            "state_owner_bureaucracy": 100,
            "state_is_incorporated": True,
            "state_tax_capacity": 10,
            "state_tax_capacity_usage": 20,
            **changes,
        },
    )
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(FIELD)
    actual = pdx_eval.select(_overlay(generated), _facts(policy, values))
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert (actual.delta if actual.operation else 1) == pytest.approx(expected)
    # An unrelated owned state's shortage cannot become the candidate's shortage.
    facts = _facts(policy, values)
    facts["ROOT"]["owner"]["owned_states"] = [
        {"is_incorporated": True, "tax_capacity": 0, "tax_capacity_usage": 100}
    ]
    assert (pdx_eval.select(_overlay(generated), facts).delta or 1) == pytest.approx(expected)


def test_local_tax_source_drift_fails(production):
    from pdx import observation_queries

    _source, _policy, native, _generated, _disabled, _model = production
    inputs = decision_adapters.read_inputs(decision_adapters.load())
    inputs[SOURCE] = native.replace(
        "state.tax_capacity < state.tax_capacity_usage",
        "state.tax_capacity > state.tax_capacity_usage",
    )
    query = observation_queries.from_reader(
        "any_scope_state", {"state_query": "tax_capacity_shortfall"}
    )
    with pytest.raises(ValueError):
        observation_queries.compile_query(query, inputs)
