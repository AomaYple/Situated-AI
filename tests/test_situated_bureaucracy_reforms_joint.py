"""Tax collection and institution administration are separate reform reasons.

Preference points do not estimate revenue, actual bureaucracy saved or enactment
probability. Original population-cost and political effects remain native.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

pytestmark = pytest.mark.integration
SOURCE = "common/laws/00_bureaucracy.txt"
FIELDS = (
    "law_appointed_bureaucrats.ai_enact_weight_modifier",
    "law_elected_bureaucrats.ai_enact_weight_modifier",
)
INVESTMENTS = (
    "police_investment",
    "home_affairs_investment",
    "colonial_affairs_investment",
    "health_investment",
    "schools_investment",
    "social_security_investment",
    "workplace_safety_investment",
)
RETIRED = {
    "law_appointed_bureaucrats_ai_enact_weight_modifier",
    "law_elected_bureaucrats_ai_enact_weight_modifier",
    "coordinated_layered_law_administrative_appointed_bureaucrats",
    "coordinated_layered_law_administrative_elected_bureaucrats",
}


def _values(changes):
    values = {
        **dict.fromkeys(INVESTMENTS, 0),
        "schools_investment": 1,
        "owned_incorporated_tax_shortfall": True,
        "current_appointed_bureaucrats": False,
        "current_elected_bureaucrats": False,
        "bureaucracy": 1,
        "default": False,
        "war": False,
        "loans": False,
        "legitimacy": 60,
        "insurrection": False,
        "radical_share": 0.1,
    }
    values.update(changes)
    return values


ZERO = dict.fromkeys(INVESTMENTS, 0)
UNKNOWN = dict.fromkeys(INVESTMENTS, None)
APPOINTED = {"current_appointed_bureaucrats": True}
ELECTED = {"current_elected_bureaucrats": True}
CRISIS = {"legitimacy": 20, "insurrection": True, "radical_share": 0.3}
CASES = [
    ({}, (14, 8)),
    ({"war": True, "loans": True, "default": True, "legitimacy": 0}, (14, 8)),
    ({"bureaucracy": -1}, (14, 14)),
    ({"bureaucracy": 0}, (14, 8)),
    ({"bureaucracy": None}, (14, 8)),
    ({"owned_incorporated_tax_shortfall": False}, (0, 8)),
    ({"owned_incorporated_tax_shortfall": None}, (0, 8)),
    ({**ZERO, "bureaucracy": -1}, (14, 0)),
    ({**UNKNOWN, "bureaucracy": -1}, (14, 0)),
    ({**ELECTED}, (14, 0)),
    ({**ELECTED, "bureaucracy": -1}, (6, 0)),
    ({**ELECTED, **ZERO, "bureaucracy": -1}, (14, 0)),
    ({**ELECTED, **UNKNOWN, "bureaucracy": -1}, (14, 0)),
    ({**ELECTED, "owned_incorporated_tax_shortfall": False, "bureaucracy": -1}, (-8, 0)),
    ({**APPOINTED}, (0, -2)),
    ({**APPOINTED, "bureaucracy": -1}, (0, 4)),
    ({**APPOINTED, **ZERO}, (0, -10)),
    ({**APPOINTED, **UNKNOWN}, (0, -10)),
    ({**APPOINTED, "owned_incorporated_tax_shortfall": False}, (0, 8)),
    ({**APPOINTED, "owned_incorporated_tax_shortfall": None}, (0, 8)),
    ({**APPOINTED, "bureaucracy": None}, (0, -2)),
    ({**dict.fromkeys(INVESTMENTS, 5), "bureaucracy": -1}, (14, 14)),
    ({"current_appointed_bureaucrats": None}, (0, 8)),
    ({"current_elected_bureaucrats": None}, (14, 0)),
    ({"current_appointed_bureaucrats": None, "current_elected_bureaucrats": None}, (0, 0)),
    (CRISIS, (4, -2)),
    ({**CRISIS, **APPOINTED, "bureaucracy": -1}, (-10, -6)),
    ({"candidate_selected": True, "law_enacting": True}, (14, 8)),
]


@pytest.fixture(scope="module")
def source_policy():
    return programs.enable(dict(decision_adapters.load().policies)[SOURCE], source=SOURCE)


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_complete_source_bureaucracy_reforms_have_distinct_gains_and_losses(
    source_policy, changes, expected
):
    actual = decision_rules.evaluate(source_policy, _values(changes), is_ai=True)
    assert tuple(actual.get(field, ("native", 0))[1] for field in FIELDS) == pytest.approx(expected)


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[SOURCE]
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(original, SOURCE, model)
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
    return original, policy, inputs[SOURCE], files[SOURCE], disabled


def _overlay(text, field):
    start = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", start)
    return "\n".join(text[start:end].splitlines()[1:])


def _engine_facts(policy, values, *, is_ai=True):
    facts = _facts(policy, values, is_ai=is_ai)
    shortfall = values["owned_incorporated_tax_shortfall"]
    # Actual owned members supply the query, never its precomputed bool.
    facts["ROOT"]["any_scope_state"] = (
        None
        if shortfall is None
        else [{"is_incorporated": True, "tax_capacity": 5, "tax_capacity_usage": 10}]
        if shortfall
        else [{"is_incorporated": True, "tax_capacity": 10, "tax_capacity_usage": 10}]
    )
    return facts


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_complete_generated_bureaucracy_reforms_match_handwritten_tradeoffs(
    production, changes, expected
):
    _original, policy, _native, generated, _disabled = production
    facts = _engine_facts(policy, _values(changes))
    actual = [pdx_eval.select(_overlay(generated, field), facts) for field in FIELDS]
    assert tuple(row.delta if row.operation == "add" else 0 for row in actual) == pytest.approx(
        expected
    )


@pytest.mark.parametrize("investment", INVESTMENTS)
def test_each_actual_institution_can_independently_supply_cost_exposure(source_policy, investment):
    values = _values({**UNKNOWN, investment: 1, "bureaucracy": -1})
    actual = decision_rules.evaluate(source_policy, values, is_ai=True)
    assert actual[FIELDS[1]][1] == 14


@pytest.mark.parametrize("investment", INVESTMENTS)
def test_generated_institution_parameters_are_independent_when_others_unknown(
    production, investment
):
    _original, policy, _native, generated, _disabled = production
    values = _values({**UNKNOWN, investment: 1, "bureaucracy": -1})
    facts = _engine_facts(policy, values)
    assert pdx_eval.select(_overlay(generated, FIELDS[1]), facts).delta == 14


def test_all_native_effects_petitions_eligibility_and_execution_stay_exact(production):
    _original, _policy, native, generated, disabled = production
    stripped = re.sub(
        r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
        "",
        generated,
        flags=re.MULTILINE | re.DOTALL,
    )
    before, after = parse_text(native), parse_text(stripped)
    assert not before.errors
    assert not after.errors
    # Dataclasses carry line numbers; use the existing independent AST identity.
    from pdx.situated.native_treatments import _ast

    assert _ast(before.root) == _ast(after.root)
    assert "add = 750" in generated
    assert "add = 1000" in generated
    assert "country_bureaucracy_investment_cost_factor_mult = -0.15" in generated
    assert "state_tax_capacity_mult = 0.25" in generated
    assert disabled == {}


def test_player_and_missing_owned_states_do_not_gain_tax_benefit(production):
    _original, policy, _native, generated, _disabled = production
    for field in FIELDS:
        assert (
            pdx_eval.select(
                _overlay(generated, field), _engine_facts(policy, _values({}), is_ai=False)
            ).operation
            is None
        )
    facts = _engine_facts(policy, _values({}))
    facts["ROOT"].pop("any_scope_state")
    # The joint envelope may emit its neutral additive value when every term
    # exits. It must not invent a tax gain from a missing owned-state list.
    assert pdx_eval.select(_overlay(generated, FIELDS[0]), facts).delta == 0
    assert pdx_eval.select(_overlay(generated, FIELDS[1]), facts).delta == 8


def test_superseded_generic_administration_rewards_are_absent(source_policy):
    assert RETIRED.isdisjoint(rule.id for rule in source_policy.rules)
