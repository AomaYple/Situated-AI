"""Handwritten local electricity/transport construction witnesses on real PDX."""

from dataclasses import replace

import pytest
from test_situated_joint_witnesses import _facts
from test_situated_local_foundations import _overlay, _tree

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
SOURCES = ("common/buildings/06_urban_center.txt", "common/buildings/11_private_infrastructure.txt")


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policies = tuple(
        (s, compiler.compile_policy(p, s, model)[0]) for s, p in adapters.policies if s in SOURCES
    )
    selected = replace(adapters, policies=policies, supply=None)
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
    assert disabled == {}
    return dict(policies), inputs, files


@pytest.mark.parametrize(
    ("building", "changes", "expected"),
    [
        ("power_plant", {}, 1.1),
        ("power_plant", {"state_local_electricity_price": 0.25}, 1),
        ("power_plant", {"state_local_electricity_price": None}, 1),
        ("power_plant", {"state_local_electricity_price": 0.6}, 1.15),
        ("power_plant", {"pm_active_building_power_plant_pm_early_power_plant": True}, 1.2),
        (
            "power_plant",
            {
                "pm_active_building_power_plant_pm_coal_fired_plant": True,
                "state_owner_coal_balance": -1,
                "state_owner_coal_price": 0.6,
                "state_owner_engines_balance": -1,
                "state_owner_engines_price": 0.6,
            },
            0.9,
        ),
        (
            "power_plant",
            {
                "pm_active_building_power_plant_pm_oil_fired_plant": True,
                "state_owner_coal_balance": -1,
                "state_owner_coal_price": 0.6,
            },
            1.2,
        ),
        ("power_plant", {"state_owner_default": True}, 0.95),
        ("railway", {}, 1.1),
        ("railway", {"state_local_transportation_price": 0.6}, 1.15),
        ("railway", {"state_local_transportation_price": 0, "state_infrastructure": -1}, 1.1),
        ("railway", {"state_infrastructure": -1}, 1.2),
        ("railway", {"pm_active_building_railway_pm_early_trains": True}, 1.2),
    ],
)
def test_real_local_supply_matches_hand_expected(production, building, changes, expected):
    policies, _inputs, files = production
    source = SOURCES[0 if building == "power_plant" else 1]
    policy = policies[source]
    field = f"building_{building}.ai_value"
    values: dict[str, bool | float | None] = {r.key: None for r in policy.readers}
    values.update({r.key: 0.2 for r in policy.readers if r.key.endswith("_price")})
    values.update({r.key: 0 for r in policy.readers if r.key.endswith("_balance")})
    values.update(
        state_local_electricity_price=0.3,
        state_local_transportation_price=0.3,
        state_infrastructure=0,
        state_owner_default=False,
    )
    values.update(changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    overlay = _overlay(files[source], field)
    observed = pdx_eval.select(overlay, _facts(policy, dict(values)))
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert (observed.delta if observed.operation else 1) == pytest.approx(expected)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert pdx_eval.select(overlay, _facts(policy, dict(values), is_ai=False)).operation is None
    facts = _facts(policy, dict(values))
    facts["ROOT"]["owner"] = None
    assert pdx_eval.select(overlay, facts).operation is None
    assert 0 * (observed.delta if observed.operation else 1) == 0


def test_local_sources_preserve_first_plant_and_native_eligibility(production):
    _policies, inputs, files = production
    for source, building in zip(SOURCES, ("building_power_plant", "building_railway"), strict=True):
        before_assignment = parse_text(inputs[source]).root.first(building)
        after_assignment = parse_text(files[source]).root.first(building)
        assert before_assignment is not None
        assert after_assignment is not None
        before = before_assignment.value
        after = after_assignment.value
        assert isinstance(before, Block)
        assert isinstance(after, Block)
        assert tuple(
            _tree(x) for x in before.items if not isinstance(x, Assignment) or x.key != "ai_value"
        ) == tuple(
            _tree(x) for x in after.items if not isinstance(x, Assignment) or x.key != "ai_value"
        )
        native_assignment = before.first("ai_value")
        generated_assignment = after.first("ai_value")
        assert native_assignment is not None
        assert generated_assignment is not None
        native = native_assignment.value
        generated = generated_assignment.value
        assert isinstance(native, Block)
        assert isinstance(generated, Block)
        assert tuple(_tree(x) for x in generated.items[: len(native.items)]) == tuple(
            _tree(x) for x in native.items
        )


def test_national_market_and_other_state_do_not_prove_local_price(production):
    policies, _inputs, files = production
    policy = policies[SOURCES[0]]
    facts = {
        "ROOT": {
            "owner": {
                "is_ai": True,
                "market": {"mg:electricity": {"market_goods_pricier": 0.75}},
                "owned_states": [{"sg:electricity": {"state_goods_pricier": 0.75}}],
            }
        }
    }
    assert (
        pdx_eval.select(_overlay(files[SOURCES[0]], "building_power_plant.ai_value"), facts).delta
        == 1
    )
    assert policy.actor_path == ("owner",)
