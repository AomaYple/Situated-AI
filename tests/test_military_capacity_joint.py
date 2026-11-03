"""Ship maintenance and conscription join finite commitment and financing causes."""

from __future__ import annotations

import re

import pytest
import test_institution_supply_joint as institution_supply
from test_institution_supply_joint import _values
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import decision_rules
from pdx.parser import parse_text
from pdx.situated import migration_baseline, pdx_eval

pytestmark = pytest.mark.integration
production = institution_supply.production
SOURCE = "common/ai_strategies/00_default_strategy.txt"
SHIP = "ai_strategy_default.ship_construction_output_multiplier"
CONSCRIPT = "ai_strategy_default.conscript_battalion_ratio"

CASES = [
    (SHIP, {}, 1),
    (SHIP, {"war": True, "navy": 1}, 1.10),
    (SHIP, {"war": True, "navy": 0}, 1),
    (SHIP, {"war": True, "navy": 1, "net_surplus": 1}, 1.18),
    (SHIP, {"war": True, "navy": 1, "default": True}, 0.95),
    (
        SHIP,
        {"war": True, "navy": 1, "loans": True, "debt_ratio": 0.4, "bankruptcy_horizon": 25.99},
        1.00,
    ),
    (
        SHIP,
        {"war": True, "navy": 1, "loans": True, "debt_ratio": 0.4, "bankruptcy_horizon": 26},
        1.10,
    ),
    (SHIP, {"war": False, "navy": 1, "default": True}, 0.85),
    (
        SHIP,
        {
            "war": True,
            "navy": 1,
            "default": True,
            "loans": True,
            "debt_ratio": 0.8,
            "bankruptcy_horizon": 1,
        },
        0.95,
    ),
    (SHIP, {"war": False, "navy": 1, "route_maritime": True, "net_surplus": 1}, 1),
    (SHIP, {"war": True, "navy": 1, "default": None, "net_surplus": 1}, 1.10),
    (SHIP, {"war": None, "navy": 1, "default": True}, 0.85),
    (CONSCRIPT, {"war": True, "own_army": 1}, 1.10),
    (CONSCRIPT, {"war": True, "own_army": 0}, 1),
    (CONSCRIPT, {"war": True, "own_army": 1, "net_surplus": 1}, 1.18),
    (CONSCRIPT, {"war": True, "own_army": 1, "default": True}, 0.95),
    (
        CONSCRIPT,
        {"war": True, "own_army": 1, "small_arms_price": 0.9, "small_arms_balance": -1},
        1.10,
    ),
    (
        CONSCRIPT,
        {"war": True, "own_army": 1, "loans": True, "debt_ratio": 0.8, "bankruptcy_horizon": 1},
        1.00,
    ),
    (
        CONSCRIPT,
        {"war": True, "own_army": 1, "net_surplus": None, "bureaucracy": -1, "legitimacy": 0},
        1.10,
    ),
    (CONSCRIPT, {"war": None, "own_army": 1, "default": True}, 0.85),
]


@pytest.mark.parametrize(("field", "changes", "expected"), CASES)
def test_same_consumer_actual_need_and_financing_match_hand_values(
    production, field, changes, expected
):
    policy, generated, _native, _model = production
    values = _values(policy, changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    assert (1 if reference is None else reference[1]) == pytest.approx(expected)
    observed = pdx_eval.select(_overlay(generated, field), _facts(policy, values))
    assert (1 if observed.operation is None else observed.delta) == pytest.approx(expected)


def test_both_complete_consumers_retain_native_ast_and_exact_history(production):
    policy, generated, native, model = production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    original = _block(parse_text(native).root, "ai_strategy_default")
    retained = _block(parse_text(stripped).root, "ai_strategy_default")
    for field in (SHIP, CONSCRIPT):
        key = field.split(".")[-1]
        assert _render(_block(original, key)) == _render(_block(retained, key))
        writers = [rule for rule in policy.rules if ".".join(rule.field) == field]
        assert len(writers) == 4
        assert all(rule.id.startswith("military_capacity_") for rule in writers)
        assert all(rule.intent is None and not rule.contexts for rule in writers)
    retired = migration_baseline.validated_retirements(model.consumer_ir)
    assert (SOURCE, "war_supply_conscript_battalion_ratio") in retired
    assert (SOURCE, "ai_strategy_default_ship_construction_output_multiplier") in retired


@pytest.mark.parametrize(
    "law", ["law_national_militia", "law_peasant_levies", "law_mass_conscription", None]
)
def test_original_law_and_all_technology_modifiers_still_execute_before_overlay(production, law):
    policy, generated, native, _model = production
    root = _block(parse_text(native).root, "ai_strategy_default")
    body = _block(root, "conscript_battalion_ratio")
    facts = _facts(policy, _values(policy, {"war": True, "own_army": 1, "net_surplus": 1}))
    facts["ROOT"]["has_law_or_variant"] = {
        (("argument", "law_type:" + candidate),): candidate == law
        for candidate in ("law_national_militia", "law_peasant_levies", "law_mass_conscription")
    }
    facts["ROOT"]["has_technology_researched"] = {
        (("argument", technology),): True
        for technology in (
            "mandatory_service",
            "army_reserves",
            "logistics",
            "enlistment_offices",
            "war_propaganda",
        )
    }
    # Hand arithmetic: native base .5/+2.5 or +.5, then 1.15²*1.2²*1.25,
    # followed by the independent 1.18 commitment tier.
    expected = {
        "law_national_militia": 8.42697,
        "law_peasant_levies": 2.80899,
        "law_mass_conscription": 2.80899,
        None: 1.404495,
    }[law]
    initial = body.first("value")
    assert initial is not None
    assert _render(initial) == "value = 0.5"
    script = (
        " ".join(_render(item) for item in body.assignments() if item.key != "value")
        + " "
        + _overlay(generated, CONSCRIPT)
    )
    assert _native_number(0.5, script, facts) == pytest.approx(expected)


def test_both_consumers_keep_player_disabled_missing_and_zero(production):
    policy, generated, _native, _model = production
    values = _values(policy, {"war": True, "navy": 1, "own_army": 1})
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    for field in (SHIP, CONSCRIPT):
        overlay = _overlay(generated, field)
        assert pdx_eval.select(overlay, {}).operation is None
        assert pdx_eval.select(overlay, _facts(policy, values, is_ai=False)).operation is None
        assert _native_number(0, overlay, _facts(policy, values)) == 0
