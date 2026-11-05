"""逐制度实际投入和独立已有需求的有限优先级撤回。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_a3_colonial import production as adapter_production
from test_remaining_joint_consumers import _native_number, _overlay
from test_situated_joint_witnesses import _facts

from pdx import config, country_state, decision_adapters, decision_interfaces, decision_rules
from pdx import institution_opportunities as institutions
from pdx.situated import compiler
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration
# Import the full default strategy production fixture so these cases exercise
# both original institution causes and newly compiled preference withdrawal.
assert adapter_production


@pytest.fixture(scope="module")
def production(adapter_production):
    model = compiler.load_model()
    info, _ = compiler.compile_policy(
        decision_rules.load(), "mod/decisions/information.toml", model
    )
    native = compiler.BASELINE.read_text(encoding="utf-8")
    inputs = decision_adapters.read_inputs(decision_adapters.load())
    patched = decision_rules.patch(
        native,
        info,
        baseline=native,
        reader_words=(
            frozenset(decision_adapters.reader_evidence(inputs))
            | decision_interfaces.proven_reader_words()
        ),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source="mod/decisions/information.toml",
    )
    adapters = decision_adapters.load()
    selected = replace(
        adapters,
        policies=((institutions.SOURCE, adapter_production[0]),),
        supply=None,
        initial_values=tuple(
            row for row in adapters.initial_values if row.source == institutions.SOURCE
        ),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == institutions.SOURCE),
    )
    combined, _ = decision_adapters.build(
        selected,
        texts=inputs,
        overlays={institutions.SOURCE: patched},
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return {
        "information": (info, patched, native),
        "adapter": adapter_production,
        "combined": combined[institutions.SOURCE],
    }


def _selected(production, name):
    information = name in {"schools", "social_security"}
    policy, generated, _ = production["information" if information else "adapter"]
    field = f"{'institution_scores' if information else 'ai_strategy_default.institution_scores'}.institution_{name}"
    return policy, generated, field


def test_each_institution_has_one_actual_combined_production_writer(production):
    combined = production["combined"]
    for name in institutions.INSTITUTIONS:
        short = f"institution_scores.institution_{name}"
        full = f"ai_strategy_default.{short}"
        expected = short if name in {"schools", "social_security"} else full
        assert combined.count(f"# SITAI BEGIN information:{expected}\n") == 1
        other = full if expected == short else short
        assert f"# SITAI BEGIN information:{other}\n" not in combined


@pytest.fixture(scope="module")
def native_inventory():
    texts = {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in institutions.load()["sources"]
    }
    return institutions.inventory(texts)


def test_all_seven_native_institutions_and_law_specific_effects_are_inventoried(native_inventory):
    actual = native_inventory[institutions.INSTITUTION_SOURCE]
    assert len(actual) == 7
    assert actual["institution_social_security"]["modifier"] == {
        "state_welfare_payments_add": 0.2,
        "state_food_security_add": 0.02,
    }
    assert actual["institution_workplace_safety"]["modifier"] == {
        "building_working_conditions_mult": -0.2
    }
    assert actual["institution_police"]["modifier"] == {"state_turmoil_effects_mult": -0.1}
    assert actual["institution_home_affairs"]["modifier"] == {
        "country_revolution_progress_mult": -0.1,
        "country_secession_progress_mult": -0.1,
    }
    assert actual["institution_schools"] == {}
    assert actual["institution_health_system"] == {}
    assert (
        native_inventory[institutions.EDUCATION_SOURCE]["law_public_schools"][
            "institution_modifier"
        ]["state_education_access_add"]
        > 0
    )
    assert (
        native_inventory[institutions.HEALTH_SOURCE]["law_charitable_health_system"][
            "institution_modifier"
        ]["state_food_security_add"]
        == 0.02
    )
    assert (
        native_inventory[institutions.HEALTH_SOURCE]["law_public_health_insurance"][
            "institution_modifier"
        ]["state_mortality_mult"]
        < 0
    )


BASES: list[tuple[str, str, dict[str, object], float]] = [
    (
        "social_security",
        "social_security_investment",
        {"social_security_present": True, "average_sol": 7, "population": 1},
        1.08,
    ),
    (
        "workplace_safety",
        "workplace_safety_investment",
        {"has_workplace_safety_institution": True, "industrial_workforce": 0.1},
        1.1,
    ),
    (
        "schools",
        "schools_investment",
        {"schools_present": True, "literacy": 0.4, "population": 1},
        1.1,
    ),
    (
        "police",
        "police_investment",
        {"has_police_institution": True, "owned_state_turmoil": True},
        1.1,
    ),
    (
        "health_system",
        "health_investment",
        {"has_health_system_institution": True, "current_public_health": True, "average_sol": 9},
        1.1,
    ),
    (
        "health_system",
        "health_investment",
        {
            "has_health_system_institution": True,
            "current_charitable_health": True,
            "grain_price": 0.6,
            "grain_balance": -1,
        },
        1.08,
    ),
    (
        "home_affairs",
        "home_affairs_investment",
        {"has_home_affairs_institution": True, "insurrection": True},
        1.1,
    ),
]


@pytest.mark.parametrize(("name", "investment", "observed", "base"), BASES)
@pytest.mark.parametrize("level", [None, 0, 2.999, 3, 5, 50])
def test_each_known_need_retains_positive_remainder_with_actual_investment(
    production, name, investment, observed, base, level
):
    policy, generated, field = _selected(production, name)
    values = dict.fromkeys(reader.key for reader in policy.readers)
    # Exact zero capacity earns no funded or administrative-capacity reward.
    # Known nondefault isolates withdrawal from explicit conservative costs.
    values.update(default=False, bureaucracy=0, net_surplus=0, war=False)
    values.update(observed)
    values[investment] = level
    deduction = 0 if level is None or level < 3 else 0.03
    if level is not None and level >= 5:
        deduction = 0.05 if name in {"social_security", "health_system"} else 0.06
    expected = base - deduction
    assert expected > 1
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    assert reference[field][1] == pytest.approx(expected)
    facts = _facts(policy, values)
    if name == "police":
        facts["ROOT"]["any_scope_state"] = [{"turmoil": 0.2}]
    assert _native_number(1, _overlay(generated, field), facts) == pytest.approx(expected)


@pytest.mark.parametrize(("name", "investment", "observed", "base"), BASES)
def test_unknown_need_or_missing_actual_institution_does_not_prove_satisfaction(
    production, name, investment, observed, base
):
    policy, generated, field = _selected(production, name)
    values = dict.fromkeys(reader.key for reader in policy.readers)
    values.update(default=False, bureaucracy=0, net_surplus=0, war=False)
    values[investment] = 5
    assert decision_rules.evaluate(policy, values, is_ai=True).get(field, ("native", 1))[1] == 1
    facts = _facts(policy, values)
    if name == "police":
        facts["ROOT"]["any_scope_state"] = None
    assert _native_number(1, _overlay(generated, field), facts) == 1
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}


def test_financial_and_administrative_costs_still_join_invested_school_need(production):
    policy, generated, field = _selected(production, "schools")
    values = dict.fromkeys(reader.key for reader in policy.readers)
    values.update(
        schools_present=True,
        schools_investment=5,
        literacy=0.4,
        population=1,
        default=True,
        bureaucracy=-1,
    )
    # 1 + .10 need - .06 priority withdrawal - .15 default - .10 administration.
    expected = 0.79
    assert decision_rules.evaluate(policy, values, is_ai=True)[field][1] == pytest.approx(expected)
    assert _native_number(1, _overlay(generated, field), _facts(policy, values)) == pytest.approx(
        expected
    )
