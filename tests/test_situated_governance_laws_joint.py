"""Complete governance consumers use current law effects and independent costs.

Grain pressure is a food-security proxy for charity; low SoL is a need for the
public law's flat SoL effect. Neither observation measures mortality or support.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import pytest
from test_situated_joint_witnesses import _facts

from pdx import config, country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

pytestmark = pytest.mark.integration
STRATEGY = "common/ai_strategies/00_default_strategy.txt"
EDUCATION = "common/laws/01_education_system.txt"
HEALTH = "ai_strategy_default.institution_scores.institution_health_system"
SCHOOL = "law_public_schools.ai_enact_weight_modifier"
TARGETS = ((STRATEGY, HEALTH, "multiply", 1), (EDUCATION, SCHOOL, "add", 0))
RETIRED = {
    "coordinated_institution_health_system_social_need",
    "coordinated_layered_health_stable",
    "social_health_low_living_standard",
    "law_public_schools_ai_enact_weight_modifier",
    "social_education_peasant_pressure",
    "coordinated_layered_law_education_public_schools",
}


def _values(changes):
    values = {
        "default": False,
        "war": False,
        "loans": False,
        "debt_ratio": 0.2,
        "net_surplus": 1,
        "income": 100,
        "bureaucracy": 1,
        "legitimacy": 60,
        "insurrection": False,
        "radical_share": 0.1,
        "population": 1_000_000,
        "literacy": 0.3,
        "average_sol": 7,
        "grain_price": 0.6,
        "grain_balance": -1,
        "peasant_share": 0.5,
        "industrial_workforce": 0.2,
        "current_charitable_health": True,
        "current_public_health": False,
        "current_private_schools": True,
        "current_religious_schools": False,
        "current_no_schools": False,
    }
    values.update(changes)
    context = country_state.load()
    raw = {k: v for k, v in values.items() if k in context.readers}
    derived = country_state.derive(context, raw)["coordination"]
    values.update({f"coord_{k}": v for k, v in derived.items()})
    return values


PUBLIC = {"current_charitable_health": False, "current_public_health": True}
PRIVATE = {"current_charitable_health": False, "current_public_health": False}
RELIGIOUS = {"current_private_schools": False, "current_religious_schools": True}
NO_SCHOOLS = {"current_private_schools": False, "current_no_schools": True}
CASES = [
    ({}, (1.16, 10)),
    ({"loans": True}, (1.16, 10)),
    ({"war": True}, (1.16, 10)),
    ({"bureaucracy": -1}, (0.96, 2)),
    ({"bureaucracy": 0}, (1.16, 10)),
    ({"default": True}, (0.91, 4)),
    ({"default": True, "bureaucracy": -1}, (0.71, -4)),
    ({"default": True, "war": True, "bureaucracy": -1}, (0.71, -4)),
    ({"net_surplus": -1, "debt_ratio": 0.8}, (0.98, 10)),
    ({"bureaucracy": None}, (1.16, 10)),
    ({"default": None}, (1.16, 10)),
    ({"net_surplus": None, "loans": None}, (1.16, 10)),
    ({"average_sol": 8}, (1.08, 10)),
    ({"average_sol": None}, (1.08, 10)),
    ({"grain_price": 0.5}, (1, 10)),
    ({"grain_balance": 0}, (1, 10)),
    ({"grain_price": None}, (1, 10)),
    ({"grain_balance": None}, (1, 10)),
    ({"current_charitable_health": None}, (1, 10)),
    (PRIVATE, (1, 10)),
    ({**PRIVATE, "average_sol": 1, "sol": 1}, (1, 10)),
    ({**PRIVATE, "legitimacy": 20}, (1, 10)),
    (PUBLIC, (1.1, 10)),
    ({**PUBLIC, "grain_price": None, "grain_balance": None}, (1.1, 10)),
    ({**PUBLIC, "average_sol": 10}, (1, 10)),
    ({**PUBLIC, "average_sol": None}, (1, 10)),
    ({**PUBLIC, "bureaucracy": -1, "default": True}, (0.65, -4)),
    ({**PRIVATE, "default": True, "bureaucracy": -1}, (0.55, -4)),
    ({"peasant_share": 0.6}, (1.16, 12)),
    ({"peasant_share": None}, (1.16, 10)),
    (RELIGIOUS, (1.16, 8)),
    ({**RELIGIOUS, "industrial_workforce": None}, (1.16, 8)),
    (NO_SCHOOLS, (1.16, 14)),
    ({"current_private_schools": None}, (1.16, 0)),
    ({"current_private_schools": False}, (1.16, 0)),
    ({"literacy": 0.5}, (1.16, 0)),
    ({"literacy": None, "default": True, "bureaucracy": -1}, (0.71, -14)),
    ({"legitimacy": 0}, (1.16, 10)),
    ({"legitimacy": 20, "insurrection": True, "radical_share": 0.3}, (1.16, 0)),
    (
        {
            "legitimacy": 20,
            "insurrection": True,
            "radical_share": 0.3,
            "bureaucracy": -1,
            "default": True,
        },
        (0.71, -14),
    ),
    ({"candidate_selected": True, "law_enacting": True}, (1.16, 10)),
]


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_complete_source_handwritten_law_and_cost_cases(changes, expected):
    policies = dict(decision_adapters.load().policies)
    values = _values(changes)
    for (source, field, _operation, native), wanted in zip(TARGETS, expected, strict=True):
        policy = programs.enable(policies[source], source=source)
        selected = decision_rules.evaluate(policy, values, is_ai=True).get(field)
        assert (selected[1] if selected else native) == pytest.approx(wanted)


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    inputs = decision_adapters.read_inputs(adapters)
    original = dict(adapters.policies)
    policies = tuple(
        (source, compiler.compile_policy(original[source], source, model)[0])
        for source in (STRATEGY, EDUCATION)
    )
    selected_sources = {source for source, _policy in policies}
    selected = replace(
        adapters,
        policies=policies,
        initial_values=tuple(
            row for row in adapters.initial_values if row.source in selected_sources
        ),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] in selected_sources),
        supply=None,
    )
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
    return original, dict(policies), inputs, files, disabled


def _overlay(text, field):
    start = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", start)
    return "\n".join(text[start:end].splitlines()[1:])


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_complete_real_consumers_match_handwritten_law_and_cost_cases(
    production, changes, expected
):
    _original, policies, _inputs, files, _disabled = production
    values = _values(changes)
    for (source, field, operation, native), wanted in zip(TARGETS, expected, strict=True):
        policy = policies[source]
        observed = pdx_eval.select(_overlay(files[source], field), _facts(policy, values))
        assert (observed.delta if observed.operation == operation else native) == pytest.approx(
            wanted
        )


def _syntax(node: Any):
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _syntax(node.value)
    assert isinstance(node, Block)
    return tuple(_syntax(child) for child in node.items)


def test_native_law_technology_exclusions_petitions_and_imposition_stay_exact(production):
    _original, _policies, inputs, files, _disabled = production
    stripped = re.sub(
        r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
        "",
        files[EDUCATION],
        flags=re.MULTILINE | re.DOTALL,
    )
    assert _syntax(parse_text(stripped).root) == _syntax(parse_text(inputs[EDUCATION]).root)
    law = parse_text(inputs[EDUCATION]).root.first("law_public_schools")
    assert law is not None
    assert isinstance(law.value, Block)
    assert "empiricism" in inputs[EDUCATION]
    assert "law_state_religion" in inputs[EDUCATION]
    assert "law_serfdom" in inputs[EDUCATION]
    assert "add = 750" in files[EDUCATION]
    assert "add = 500" in files[EDUCATION]
    assert "can_impose_law_default = yes" in files[EDUCATION]


def test_player_disabled_domains_and_foreign_laws_do_not_supply_observations(production):
    _original, policies, _inputs, files, disabled = production
    assert disabled == {}
    values = _values({})
    for source, field, _operation, _native in TARGETS:
        policy = policies[source]
        overlay = _overlay(files[source], field)
        assert decision_rules.evaluate(policy, values, is_ai=False) == {}
        assert (
            decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
        )
        assert pdx_eval.select(overlay, _facts(policy, values, is_ai=False)).operation is None
    policy = policies[STRATEGY]
    unknown = _values({**PRIVATE, "current_charitable_health": None, "current_public_health": None})
    facts = _facts(policy, unknown)
    facts["other_country"] = {
        "has_law_or_variant": {(("argument", "law_type:law_charitable_health_system"),): True}
    }
    observed = pdx_eval.select(_overlay(files[STRATEGY], HEALTH), facts)
    assert observed.operation is None or observed.delta == 1


def test_exact_readers_law_effects_all_rules_and_retirements(production):
    original, policies, _inputs, _files, _disabled = production
    expected_laws = {
        "current_charitable_health": "law_type:law_charitable_health_system",
        "current_public_health": "law_type:law_public_health_insurance",
        "current_no_schools": "law_type:law_no_schools",
    }
    for key, argument in expected_laws.items():
        source = STRATEGY if "health" in key else EDUCATION
        reader = next(r for r in original[source].readers if r.key == key)
        assert reader.engine == "has_law_or_variant"
        assert reader.kind == "boolean"
        assert reader.scope == "root"
        assert reader.path == ()
        assert reader.unit == "boolean"
        assert reader.argument == argument
        assert reader.parameters == ()
        assert reader.value_field is None
        assert reader.minimum is None
        assert reader.maximum is None
    all_ids = {r.id for policy in original.values() for r in policy.rules}
    assert not (all_ids & RETIRED)
    for source, field, _operation, _native in TARGETS:
        rules = tuple(r for r in original[source].rules if ".".join(r.field) == field)
        assert len(rules) < 32
        assert all(r.contribution_group for r in rules)
        consumer = next(p for p in policies[source].consumer_programs if ".".join(p.field) == field)
        assert {v.action_id for v in consumer.variants} == {r.id for r in rules}
    health = (config.GAME / "common/laws/01_health_system.txt").read_text(encoding="utf-8-sig")
    root = parse_text(health).root
    expected = {
        "law_charitable_health_system": {
            "state_food_security_add": "0.02",
            "state_mortality_mult": "-0.03",
        },
        "law_private_health_insurance": {
            "state_mortality_wealth_mult": "-0.002",
            "state_upper_strata_standard_of_living_add": "0.5",
        },
        "law_public_health_insurance": {
            "state_standard_of_living_add": "0.5",
            "state_mortality_mult": "-0.05",
        },
    }
    for name, modifiers in expected.items():
        law = root.first(name)
        assert law is not None
        assert isinstance(law.value, Block)
        effects = law.value.first("institution_modifier")
        assert effects is not None
        assert isinstance(effects.value, Block)
        for key, value in modifiers.items():
            effect = effects.value.first(key)
            assert effect is not None
            assert isinstance(effect.value, Scalar)
            assert effect.value.text == value


def test_charity_argument_has_a_locked_country_call_not_a_synthetic_word(production):
    _original, _policies, inputs, _files, _disabled = production
    source = "common/achievements/ip2_pivot_of_empire_achievements.txt"
    achievement = parse_text(inputs[source]).root.first("achievement_be_prepared")
    assert achievement is not None
    assert isinstance(achievement.value, Block)
    happened = achievement.value.first("happened")
    assert happened is not None
    assert isinstance(happened.value, Block)
    calls = []
    # These are logical wrappers in achievement's country context; no state
    # iterator or target scope is traversed to establish the law getter.
    for tooltip in happened.value.assignments():
        if tooltip.key != "custom_tooltip" or not isinstance(tooltip.value, Block):
            continue
        choice = tooltip.value.first("OR")
        if choice is None or not isinstance(choice.value, Block):
            continue
        for clause in choice.value.assignments():
            if clause.key == "AND" and isinstance(clause.value, Block):
                call = clause.value.first("has_law_or_variant")
                if call is not None and isinstance(call.value, Scalar):
                    calls.append(call.value.text)
    assert "law_type:law_charitable_health_system" in calls
    evidence = decision_adapters.reader_evidence(inputs)
    assert evidence["law_type:law_charitable_health_system"]["source"] == source
    assert "law_type:law_public_health_insurance" in evidence
    assert "law_type:law_no_schools" in evidence
