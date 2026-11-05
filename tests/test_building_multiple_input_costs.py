"""Actual PM inputs: distinct goods join, repeated physical pressures deduplicate."""

from dataclasses import replace

import pytest
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/buildings/03_mines.txt"
FIELD = "building_iron_mine.ai_value"
PUMP = "pm_active_building_iron_mine_pm_atmospheric_engine_pump_building_iron_mine"
DONKEY = "pm_active_building_iron_mine_pm_steam_donkey_mine"


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(dict(adapters.policies)[SOURCE], SOURCE, model)
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        initial_values=tuple(row for row in adapters.initial_values if row.source == SOURCE),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == SOURCE),
    )
    files, _ = decision_adapters.build(
        selected, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    disabled, _ = decision_adapters.build(
        selected,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        enabled_domains=frozenset(),
    )
    return policy, files[SOURCE], disabled


def _values(policy, changes):
    values = {
        reader.key: False if reader.kind == "boolean" else max(0, reader.minimum or 0)
        for reader in policy.readers
    }
    values.update({PUMP: True, DONKEY: True})
    values.update(changes)
    return values


def _overlay(text):
    start = text.index(f"# SITAI BEGIN information:{FIELD}")
    end = text.index(f"# SITAI END information:{FIELD}", start)
    return "\n".join(text[start:end].splitlines()[1:])


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1),
        ({"state_owner_coal_price": 0.6, "state_owner_coal_balance": -1}, 0.8),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": 0.6,
                "state_owner_tools_balance": -1,
            },
            0.6,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": None,
                "state_owner_tools_balance": -1,
            },
            # The active pump consumes tools. Unknown price cannot waive its
            # declared .2 cost when the known balance supplies no cheap case.
            # Coal joins once despite its use by both PMs: 1 - .2 - .2 = .6.
            0.6,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": 0.6,
                "state_owner_tools_balance": None,
            },
            0.6,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": None,
                "state_owner_tools_balance": None,
            },
            0.6,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": None,
                "state_owner_tools_balance": 0,
            },
            # A known nonnegative balance waives this conjunctive tools cost,
            # even when price is unknown. The independent coal cost remains.
            0.8,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": 0.5,
                "state_owner_tools_balance": None,
            },
            # Price at the strict threshold proves the tools cost is absent;
            # unknown balance cannot override that known cheap counterexample.
            0.8,
        ),
        (
            {
                "state_owner_coal_price": 0.5,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": 0.6,
                "state_owner_tools_balance": -1,
            },
            0.8,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": 0.6,
                "state_owner_tools_balance": -1,
                PUMP: None,
            },
            # The known steam donkey still consumes coal (.2); every mine
            # pump uses tools, so its independently known low tier costs .05.
            # Missing the selected pump only removes its stronger .2 tier.
            0.75,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": 0.6,
                "state_owner_tools_balance": -1,
                "state_owner_engines_price": 0.6,
                "state_owner_engines_balance": -1,
            },
            0.5,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": 0.6,
                "state_owner_tools_balance": -1,
                "state_owner_engines_price": 0.6,
                "state_owner_engines_balance": -1,
                "state_owner_iron_price": 0.6,
                "state_owner_iron_balance": -1,
            },
            # 1 + .2 output - .2 coal - .2 tools - .2 engines = .6.
            # Coal is shared by two active PM groups but counted only once.
            0.6,
        ),
        (
            {
                "state_owner_coal_price": 0.6,
                "state_owner_coal_balance": -1,
                "state_owner_tools_price": 0.6,
                "state_owner_tools_balance": -1,
                "state_owner_default": True,
                "state_infrastructure": -1,
            },
            0.5,
        ),
    ],
)
def test_independent_materials_join_once_per_good_in_actual_production(
    production, changes, expected
):
    policy, text, _ = production
    values = _values(policy, changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(FIELD)
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    observed = pdx_eval.select(_overlay(text), _facts(policy, values))
    assert observed.delta == pytest.approx(expected)


def test_player_and_disabled_paths_preserve_the_complete_original_source(production):
    policy, text, disabled = production
    assert SOURCE not in disabled
    values = _values(policy, {"state_owner_coal_price": 0.6, "state_owner_coal_balance": -1})
    observed = pdx_eval.select(_overlay(text), _facts(policy, values, is_ai=False))
    assert observed.operation is None


def test_all_declared_actual_input_costs_have_exact_good_causal_identity():
    found = 0
    for _, policy in decision_adapters.load().policies:
        readers = {reader.key: reader for reader in policy.readers}
        for rule in policy.rules:
            if not rule.id.startswith("actual_cost_building_"):
                continue
            goods = {
                reader.path[-1].removeprefix("mg:")
                for clause in rule.conditions
                if (reader := readers[clause.fact]).engine
                in {"market_goods_pricier", "market_goods_delta"}
            }
            assert len(goods) == 1
            assert rule.contribution_group == "building_active_input_" + goods.pop()
            found += 1
    assert found > 100
