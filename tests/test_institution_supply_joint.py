"""Complete institution and supply consumers retain concrete causes and native AST."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, migration_baseline, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/ai_strategies/00_default_strategy.txt"
SAFETY = "ai_strategy_default.institution_scores.institution_workplace_safety"
POLICE = "ai_strategy_default.institution_scores.institution_police"
HOME = "ai_strategy_default.institution_scores.institution_home_affairs"
SUPPLY = "ai_strategy_default.wanted_num_supply_ships"
FIELDS = (SAFETY, POLICE, HOME, SUPPLY)


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policy, _ = compiler.compile_policy(dict(adapters.policies)[SOURCE], SOURCE, model)
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        initial_values=tuple(r for r in adapters.initial_values if r.source == SOURCE),
        scalar_values=tuple(r for r in adapters.scalar_values if r[0] == SOURCE),
    )
    inputs = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return policy, files[SOURCE], inputs[SOURCE], model


def _values(policy, changes):
    facts = {
        reader.key: False if reader.kind == "boolean" else max(0, reader.minimum or 0)
        for reader in policy.readers
    }
    facts.update(
        population=1_000_000,
        literacy=0.8,
        legitimacy=60,
        debt_ratio=0.1,
        bankruptcy_horizon=52,
        sol=20,
        national_gdp=100,
        candidate_gdp=1,
    )
    facts.update(changes)
    if "navy" in changes:
        facts["own_navy"] = changes["navy"]
    return facts


# Each result is handwritten: multiply combines independent deviations from 1.
CASES = [
    (SAFETY, {"bureaucracy": 1, "net_surplus": 1, "industrial_workforce": 0.5}, [], 1),
    (SAFETY, {"has_workplace_safety_institution": True, "industrial_workforce": 0.09999}, [], 1),
    (SAFETY, {"has_workplace_safety_institution": True, "industrial_workforce": 0.1}, [], 1.10),
    (
        SAFETY,
        {"has_workplace_safety_institution": True, "industrial_workforce": 0.1, "net_surplus": 1},
        [],
        1.20,
    ),
    (
        SAFETY,
        {"has_workplace_safety_institution": True, "industrial_workforce": 0.1, "bureaucracy": 1},
        [],
        1.18,
    ),
    (
        SAFETY,
        {
            "has_workplace_safety_institution": True,
            "industrial_workforce": 0.1,
            "net_surplus": 1,
            "bureaucracy": 1,
        },
        [],
        1.25,
    ),
    (
        SAFETY,
        {
            "has_workplace_safety_institution": True,
            "industrial_workforce": 0.1,
            "workplace_safety_investment": 1,
            "default": True,
            "bureaucracy": -1,
            "war": True,
        },
        [],
        0.85,
    ),
    (
        SAFETY,
        {
            "has_workplace_safety_institution": True,
            "industrial_workforce": None,
            "workplace_safety_investment": 1,
            "default": True,
        },
        [],
        0.85,
    ),
    (
        SAFETY,
        {
            "has_workplace_safety_institution": True,
            "industrial_workforce": 0.1,
            "net_surplus": None,
            "bureaucracy": 1,
        },
        [],
        1.18,
    ),
    (
        SAFETY,
        {"has_workplace_safety_institution": True, "industrial_workforce": 0.1, "default": None},
        [],
        1.10,
    ),
    (
        POLICE,
        {"has_police_institution": True, "owned_state_turmoil": True},
        [{"turmoil": 0.10001}],
        1.10,
    ),
    (
        POLICE,
        {"has_police_institution": True, "owned_state_turmoil": False, "radical_share": 0.9},
        [{"turmoil": 0.1}],
        1,
    ),
    (POLICE, {"has_police_institution": True, "owned_state_turmoil": None}, [{}], 1),
    (POLICE, {"has_police_institution": False, "owned_state_turmoil": True}, [{"turmoil": 0.8}], 1),
    (
        POLICE,
        {
            "has_police_institution": True,
            "owned_state_turmoil": True,
            "net_surplus": 1,
            "bureaucracy": 1,
        },
        [{"turmoil": 0.2}, {}],
        1.25,
    ),
    (
        POLICE,
        {
            "has_police_institution": True,
            "owned_state_turmoil": True,
            "police_investment": 1,
            "default": True,
            "bureaucracy": -1,
        },
        [{"turmoil": 0.2}],
        0.85,
    ),
    (
        POLICE,
        {
            "has_police_institution": True,
            "owned_state_turmoil": None,
            "police_investment": 1,
            "default": True,
            "bureaucracy": -1,
        },
        [{"turmoil": 0.1}, {}],
        0.75,
    ),
    (
        POLICE,
        {
            "has_police_institution": True,
            "owned_state_turmoil": False,
            "police_investment": 0,
            "default": True,
            "bureaucracy": -1,
        },
        [],
        1,
    ),
    (HOME, {"has_home_affairs_institution": True, "insurrection": True}, [], 1.10),
    (
        HOME,
        {"has_home_affairs_institution": True, "insurrection": False, "radical_share": 0.9},
        [],
        1,
    ),
    (HOME, {"has_home_affairs_institution": False, "insurrection": True}, [], 1),
    (
        HOME,
        {
            "has_home_affairs_institution": True,
            "insurrection": True,
            "net_surplus": 1,
            "bureaucracy": 1,
        },
        [],
        1.25,
    ),
    (
        HOME,
        {
            "has_home_affairs_institution": True,
            "insurrection": True,
            "home_affairs_investment": 1,
            "default": True,
            "bureaucracy": -1,
        },
        [],
        0.85,
    ),
    (
        HOME,
        {
            "has_home_affairs_institution": True,
            "insurrection": None,
            "home_affairs_investment": 1,
            "bureaucracy": -1,
        },
        [],
        0.9,
    ),
    (
        HOME,
        {
            "has_home_affairs_institution": True,
            "insurrection": True,
            "home_affairs_investment": None,
            "default": True,
            "bureaucracy": -1,
        },
        [],
        1.10,
    ),
    (SUPPLY, {"war": True, "navy": 1}, [], 1.10),
    (SUPPLY, {"war": True, "navy": 0}, [], 1),
    (SUPPLY, {"war": False, "navy": 10, "route_maritime": True}, [], 1),
    (SUPPLY, {"war": True, "navy": 1, "net_surplus": 1}, [], 1.20),
    (SUPPLY, {"war": True, "navy": 1, "net_surplus": 1, "default": True}, [], 0.95),
    (
        SUPPLY,
        {
            "war": True,
            "navy": 1,
            "loans": True,
            "debt_ratio": 0.9,
            "legitimacy": 0,
            "bureaucracy": -1,
        },
        [],
        1.10,
    ),
    # C2: known war/fleet proves the commitment; unknown financing retains
    # the .15 cost, while the funded .20 benefit needs observed non-default.
    # Base need .10 minus financing .15 gives 1 + .10 - .15 = .95.
    (SUPPLY, {"war": True, "navy": 1, "net_surplus": 1, "default": None}, [], 0.95),
    (SUPPLY, {"war": None, "navy": 1}, [], 1),
    (SUPPLY, {"war": True, "navy": None}, [], 1),
]


@pytest.mark.parametrize(("field", "changes", "states", "expected"), CASES)
def test_actual_complete_source_and_independent_generated_pdx_match_hand_values(
    production, field, changes, states, expected
):
    policy, generated, _native, _model = production
    values = _values(policy, changes)
    result = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    assert (1 if result is None else result[1]) == pytest.approx(expected)
    facts = _facts(policy, values)
    facts["ROOT"]["any_scope_state"] = states
    observed = pdx_eval.select(_overlay(generated, field), facts)
    assert (observed.delta if observed.operation else 1) == pytest.approx(expected)


def test_no_other_writers_and_full_native_ast_remain_in_each_physical_consumer(production):
    policy, generated, native, model = production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    native_root = _block(parse_text(native).root, "ai_strategy_default")
    generated_root = _block(parse_text(stripped).root, "ai_strategy_default")
    expected_counts = {SAFETY: 8, POLICE: 8, HOME: 8, SUPPLY: 3}
    names = {SAFETY: "workplace_safety", POLICE: "police", HOME: "home_affairs"}
    for field in FIELDS:
        rules = [rule for rule in policy.rules if ".".join(rule.field) == field]
        assert len(rules) == expected_counts[field]
        withdrawals = (
            {
                f"institution_priority_{names[field]}_0_{tier}"
                for tier in ("invested", "deeply_invested")
            }
            if field in names
            else set()
        )
        assert {
            rule.id for rule in rules if not rule.id.startswith("institution_supply_")
        } == withdrawals
        assert len([rule for rule in rules if rule.id.startswith("institution_supply_")]) == (
            3 if field == SUPPLY else 6
        )
        assert all(rule.intent is None and not rule.contexts for rule in rules)
        before, after = native_root, generated_root
        for part in field.split(".")[1:]:
            before, after = _block(before, part), _block(after, part)
        assert _render(before) == _render(after)
    assert model.consumer_ir is not None
    assert hashlib.sha256(migration_baseline.DEFAULT_SOURCE.read_bytes()).hexdigest() == (
        "fcce11e045e9933c13644a361da3a448330208c0b712ac3df615eed307aa55e6"
    )
    retired = migration_baseline.validated_retirements(model.consumer_ir)
    assert (SOURCE, "coordinated_institution_workplace_safety_social_need") in retired
    assert (SOURCE, "ai_strategy_default_wanted_num_supply_ships") in retired


def test_player_disabled_wrong_scope_and_all_unknown_leave_native(production):
    policy, generated, _native, _model = production
    values = _values(policy, {"has_police_institution": True, "owned_state_turmoil": True})
    assert decision_rules.evaluate(policy, {}, is_ai=True) == {}
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    for field in FIELDS:
        overlay = _overlay(generated, field)
        player = _facts(policy, values, is_ai=False)
        player["ROOT"]["any_scope_state"] = [{"turmoil": 0.8}]
        assert pdx_eval.select(overlay, player).operation is None
        assert pdx_eval.select(overlay, {}).operation is None
    wrong = _facts(policy, values)
    wrong["ROOT"]["any_scope_state"] = []
    wrong["any_scope_state"] = [{"turmoil": 0.8}]
    assert pdx_eval.select(_overlay(generated, POLICE), wrong).delta == 1


def test_supply_native_zero_and_original_twenty_factor_are_preserved(production):
    policy, generated, native, _model = production
    block = _block(
        _block(parse_text(native).root, "ai_strategy_default"), "wanted_num_supply_ships"
    )
    assert _render(block) == "{ value = wanted_navy_size_script_value multiply = 20 }"
    native_factor = block.first("multiply")
    assert native_factor is not None
    script = _render(native_factor) + " " + _overlay(generated, SUPPLY)
    facts = _facts(policy, _values(policy, {"war": True, "navy": 10, "net_surplus": 1}))
    assert _native_number(0, script, facts) == 0
    assert _native_number(5, script, facts) == pytest.approx(120)


def test_same_consumer_switching_has_no_queued_or_selected_state(production):
    policy, generated, _native, _model = production
    observed = []
    for in_war, expected in ((True, 1.1), (False, 1), (True, 1.1)):
        facts = _facts(policy, _values(policy, {"war": in_war, "navy": 1}))
        decision = pdx_eval.select(_overlay(generated, SUPPLY), facts)
        observed.append(decision.delta if decision.operation else 1)
        assert observed[-1] == pytest.approx(expected)
    assert observed == [1.1, 1, 1.1]
