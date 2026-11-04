"""Production construction programs: direct need and separately observed costs."""

from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/buildings/03_mines.txt"
FIELD = ("building_iron_mine", "ai_value")
METHOD = "pm_picks_and_shovels_building_iron_mine"


def _generate(source, field):
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[source]
    rules = tuple(rule for rule in original.rules if rule.field == field)
    keys = {key for rule in rules for key in rule.input_keys()}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(reader for reader in original.readers if reader.key in keys),
        semantic_ir=(),
        consumer_programs=(),
        enabled_domains=frozenset(rule.domain for rule in rules),
    )
    model = compiler.load_model()
    compiled, _ = compiler.compile_policy(policy, source, model)
    selected = replace(
        adapters,
        policies=((source, compiled),),
        supply=None,
        initial_values=tuple(
            row for row in adapters.initial_values if row.source == source and row.field == field
        ),
        scalar_values=tuple(
            row for row in adapters.scalar_values if row[0] == source and row[1] == field
        ),
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return compiled, files[source], selected, inputs


@pytest.fixture(scope="module")
def production():
    return _generate(SOURCE, FIELD)


@pytest.fixture(scope="module")
def steel():
    return _generate("common/buildings/01_industry.txt", ("building_steel_mill", "ai_value"))


@pytest.fixture(scope="module")
def shipyard():
    return _generate("common/buildings/01_industry.txt", ("building_shipyard", "ai_value"))


@pytest.mark.parametrize(
    ("active", "balance", "default", "infrastructure", "input_shortage", "expected"),
    [
        (True, -1, None, None, False, 1.08),
        (True, -1, True, 0, False, 0.93),
        (True, -1, True, -1, False, 0.83),
        (True, -1, False, -1, True, 0.78),
        (True, 0, False, 0, False, 1.0),
        (None, -1, False, 0, False, 1.0),
        (False, -1, False, 0, False, 1.0),
        (True, None, True, None, False, 0.85),
    ],
)
def test_shipyard_basic_need_does_not_require_all_capacity_and_input_gates(
    shipyard, active, balance, default, infrastructure, input_shortage, expected
):
    policy, text, _, _ = shipyard
    method = "pm_basic_shipbuilding"
    values = {
        f"pm_active_building_shipyard_{method}": active,
        "state_owner_clippers_balance": balance,
        "state_owner_default": default,
        "state_infrastructure": infrastructure,
        "state_owner_wood_price": 0.6 if input_shortage else None,
        "state_owner_wood_balance": -1 if input_shortage else None,
    }
    facts = {
        "ROOT": {
            "infrastructure_delta": infrastructure,
            "is_production_method_active": {"building_shipyard": {method: active}},
            "owner": {
                "is_ai": True,
                "in_default": default,
                "market": {
                    "mg:clippers": {"market_goods_delta": balance},
                    "mg:wood": {
                        "market_goods_pricier": values["state_owner_wood_price"],
                        "market_goods_delta": values["state_owner_wood_balance"],
                    },
                },
            },
        }
    }
    field = "building_shipyard.ai_value"
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(field, ("", 1))[1] == (
        pytest.approx(expected)
    )
    program = next(
        item for item in policy.consumer_programs if item.field == tuple(field.split("."))
    )
    assert pdx_eval.select(pdx_eval.marked_block(text, program.action_id), facts).delta == (
        pytest.approx(expected)
    )


def _observations(changes, *, is_ai=True):
    values = {"state_owner_iron_balance": -1, **changes}
    owner: dict[str, Any] = {
        "is_ai": is_ai,
        "bureaucracy": -10,
        "literacy_rate": 0.01,
        "market": {},
    }
    state: dict[str, Any] = {"is_ai": not is_ai, "owner": owner}
    facts = {"ROOT": state}
    # Handwritten engine mapping keeps absence unknown. No production reader
    # or query implementation manufactures the expected observations.
    for key, engine in (
        ("state_owner_default", "in_default"),
        ("state_owner_loans", "taking_loans"),
    ):
        if key in values:
            owner[engine] = values[key]
    if "state_infrastructure" in values:
        state["infrastructure_delta"] = values["state_infrastructure"]
    for good in ("iron", "tools"):
        market_good = {}
        for suffix, engine in (
            ("balance", "market_goods_delta"),
            ("price", "market_goods_pricier"),
        ):
            key = f"state_owner_{good}_{suffix}"
            if key in values:
                market_good[engine] = values[key]
        if market_good:
            owner["market"][f"mg:{good}"] = market_good
    if (key := f"pm_active_building_iron_mine_{METHOD}") in values:
        state["is_production_method_active"] = {"building_iron_mine": {METHOD: values[key]}}
    return values, facts


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.08),
        ({"state_owner_iron_price": 0.5}, 1.12),
        ({"state_owner_iron_price": 0.5, "state_owner_loans": True}, 1.12),
        ({"state_owner_iron_price": 0.5, "state_owner_default": True}, 0.97),
        ({"state_owner_iron_price": 0.5, "state_infrastructure": -1}, 1.02),
        (
            {
                "state_owner_iron_price": 0.5,
                "state_owner_default": True,
                "state_infrastructure": -1,
            },
            0.87,
        ),
        ({"state_owner_iron_balance": 0}, 1.0),
        ({"state_owner_iron_balance": None}, 1.0),
        ({"state_owner_iron_price": None, "state_owner_default": True}, 0.93),
        (
            {
                "state_owner_iron_price": 0.5,
                f"pm_active_building_iron_mine_{METHOD}": True,
                "state_owner_tools_price": 0.6,
                "state_owner_tools_balance": -1,
            },
            1.0,
        ),
    ],
)
def test_actual_program_combines_need_and_costs_with_local_unknown(production, changes, expected):
    policy, text, _, _ = production
    values, facts = _observations(changes)
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert reference.get(".".join(FIELD), ("", 1))[1] == pytest.approx(expected)
    program = next(p for p in policy.consumer_programs if p.field == FIELD)
    generated = pdx_eval.select(pdx_eval.marked_block(text, program.action_id), facts)
    assert generated.delta == pytest.approx(expected)


def test_player_owner_and_all_domains_disabled_preserve_native_path(production):
    policy, text, adapters, inputs = production
    values, facts = _observations({"state_owner_iron_price": 0.5}, is_ai=False)
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    program = next(p for p in policy.consumer_programs if p.field == FIELD)
    assert pdx_eval.select(pdx_eval.marked_block(text, program.action_id), facts).operation is None
    files, _ = decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())
    assert files == {}


def test_unconditional_world_expansion_is_retired_from_ordinary_construction():
    adapters = decision_adapters.load()
    for source, policy in adapters.policies:
        if not source.startswith("common/buildings/"):
            continue
        ordinary = {
            rule.field for rule in policy.rules if rule.id.startswith("building_opportunity_")
        }
        assert all(
            not rule.id.startswith("coordinated_layered_building_")
            for rule in policy.rules
            if rule.field in ordinary
        )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.2),
        ({"state_unemployment": 0.1}, 1.3),
        ({"state_unemployment": 0.09999}, 1.2),
        ({"state_unemployment": 0.1, "state_owner_reserves": 0}, 1.2),
        ({"state_owner_steel_price": 0.25}, 1.08),
        ({"state_owner_steel_balance": 0}, 1.0),
        # Missing cheap inputs removes the ready-PM tier, leaving basic
        # observed output opportunity +.12 and actual input cost -.20.
        ({"state_owner_coal_price": 0.6, "state_owner_coal_balance": -10}, 0.92),
        # Poor access and infrastructure share one causal cost envelope:
        # -.20 replaces -.10 instead of charging the same shortfall twice.
        ({"state_market_access": 0.8, "state_infrastructure": -1}, 0.92),
        ({"state_owner_loans": True}, 1.12),
        ({"state_owner_default": True}, 0.97),
    ],
)
def test_steel_opportunity_employment_and_costs_in_complete_production_program(
    steel, changes, expected
):
    policy, text, _, _ = steel
    values = {
        reader.key: False if reader.kind == "boolean" else max(0.0, reader.minimum or 0.0)
        for reader in policy.readers
    }
    values.update(
        pm_active_building_steel_mill_pm_bessemer_process=True,
        state_owner_steel_price=0.4,
        state_owner_steel_balance=-10,
        state_owner_reserves=100,
        state_market_access=1,
    )
    values.update(changes)
    root: dict[str, Any] = {"owner": {"is_ai": True}}
    for reader in policy.readers:
        assert reader.scope == "root"
        current = root
        for part in reader.path:
            current = current.setdefault(part, {})
        if reader.engine == "is_production_method_active":
            parameters = dict(reader.parameters)
            current.setdefault(reader.engine, {}).setdefault(parameters["building_type"], {})[
                parameters["production_method"]
            ] = values[reader.key]
        else:
            assert not reader.argument
            assert not reader.parameters
            current[reader.engine] = values[reader.key]
    field = "building_steel_mill.ai_value"
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert reference.get(field, ("", 1))[1] == pytest.approx(expected)
    program = policy.consumer_programs[0]
    generated = pdx_eval.select(pdx_eval.marked_block(text, program.action_id), {"ROOT": root})
    assert generated.delta == pytest.approx(expected)
