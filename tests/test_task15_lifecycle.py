"""Literal sequential world witnesses over actual producers and generated PDX.

Default is candidate preparation. Task10 runs the identical file with
TASK15_NORMAL_INTEGRATION=1 once with the normal full compiler session.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from task15_lifecycle_support import (
    DEFAULT,
    INDUSTRY,
    INFO,
    SUBJECT,
    build,
    complete,
    defaults,
    native_number,
    numeric,
    restored,
)
from test_remaining_joint_consumers import _block, _native_number, _overlay

from pdx import decision_rules
from pdx import subject_dependence_opportunities as dependence_module
from pdx.lexer import tokenize
from pdx.parser import parse_text
from pdx.situated import pdx_eval


@pytest.fixture(scope="module")
def actual():
    return build()


def test_tax_agenda_crisis_administration_independent_recovery_sequence(actual):
    row = actual["common/laws/01_taxation.txt"]
    field = "law_proportional_taxation.ai_enact_weight_modifier"
    agenda = "law_context_law_proportional_taxation_movement_base"
    # +6 need; -10 known crisis; -6 actual lost consumption-tax admin discount.
    states = [
        ({}, 0),
        ({agenda: True}, 6),
        ({agenda: True, "legitimacy": 10, "insurrection": True, "radical_share": 0.3}, -4),
        (
            {
                agenda: True,
                "legitimacy": 10,
                "insurrection": True,
                "radical_share": 0.3,
                "bureaucracy": -1,
                "law_context_current_law_consumption_based_taxation": True,
            },
            -10,
        ),
        (
            {
                agenda: True,
                "bureaucracy": -1,
                "law_context_current_law_consumption_based_taxation": True,
            },
            0,
        ),
        (
            {
                agenda: True,
                "bureaucracy": 0,
                "law_context_current_law_consumption_based_taxation": True,
            },
            6,
        ),
        ({agenda: None, "legitimacy": 10, "insurrection": True, "radical_share": 0.3}, -10),
        # Source policy explicitly declares legitimacy/radical unknown
        # conservative; this is separate from a known-only semantic cost.
        ({agenda: True, "legitimacy": None, "insurrection": True, "radical_share": 0.3}, -4),
    ]
    for changes, expected in states:
        values = defaults(row["policy"], changes)

        def movements(facts, values=values):
            facts["ROOT"]["any_political_movement"] = (
                None
                if values[agenda] is None
                else (
                    [
                        {
                            "law_enactment_stance": {
                                (("law", "law_type:law_proportional_taxation"),): 1
                            },
                            "political_movement_support": 0.1,
                        }
                    ]
                    if values[agenda]
                    else []
                )
            )

        observed, reference, _ = numeric(row, field, values, base=0, world=movements)
        assert observed == expected
        assert reference == expected


@pytest.mark.parametrize(
    ("name", "investment", "need", "base", "withdraw3", "withdraw5"),
    [
        (
            "schools",
            "schools_investment",
            {"schools_present": True, "literacy": 0.4, "population": 1},
            1.10,
            0.03,
            0.06,
        ),
        (
            "social_security",
            "social_security_investment",
            {"social_security_present": True, "average_sol": 7, "population": 1},
            1.08,
            0.03,
            0.05,
        ),
        (
            "police",
            "police_investment",
            {"has_police_institution": True, "owned_state_turmoil": True},
            1.10,
            0.03,
            0.06,
        ),
        (
            "home_affairs",
            "home_affairs_investment",
            {"has_home_affairs_institution": True, "insurrection": True},
            1.10,
            0.03,
            0.06,
        ),
        (
            "health_system",
            "health_investment",
            {
                "has_health_system_institution": True,
                "current_public_health": True,
                "average_sol": 9,
            },
            1.10,
            0.03,
            0.05,
        ),
        (
            "health_system",
            "health_investment",
            {
                "has_health_system_institution": True,
                "current_charitable_health": True,
                "average_sol": 10,
                "grain_price": 0.6,
                "grain_balance": -1,
            },
            1.08,
            0.03,
            0.05,
        ),
        (
            "workplace_safety",
            "workplace_safety_investment",
            {"has_workplace_safety_institution": True, "industrial_workforce": 0.1},
            1.10,
            0.03,
            0.06,
        ),
    ],
)
def test_actual_investment_advance_exit_unknown_and_reentry(
    actual, name, investment, need, base, withdraw3, withdraw5
):
    source = INFO if name in {"schools", "social_security"} else DEFAULT
    row = actual[source]
    field = (
        "" if source == INFO else "ai_strategy_default."
    ) + f"institution_scores.institution_{name}"
    sequence = [
        (0, need, base),
        (3, need, base - withdraw3),
        (5, need, base - withdraw5),
        (None, need, base),
        (5, {}, 1),
        (0, need, base),
    ]
    for level, observed, expected in sequence:
        values = defaults(row["policy"], {**observed, investment: level})

        def world(facts, observed=observed):
            if name == "police":
                facts["ROOT"]["any_scope_state"] = [{"turmoil": 0.2}] if observed else []

        actual_value, reference, facts = numeric(row, field, values, world=world)
        assert actual_value == pytest.approx(expected)
        assert reference == pytest.approx(expected)
        full_path = "ai_strategy_default." + field if source == INFO else field
        # Original institution base=10 remains a single initializer.
        assert complete(row, full_path, facts) == pytest.approx(10 * expected)


def test_invested_school_costs_survive_need_and_capacity_changes(actual):
    row = actual[INFO]
    field = "institution_scores.institution_schools"
    states = [
        (
            {
                "schools_present": True,
                "schools_investment": 5,
                "literacy": 0.4,
                "population": 1,
                "default": True,
                "bureaucracy": -1,
            },
            0.79,
        ),
        (
            {
                "schools_present": True,
                "schools_investment": 5,
                "literacy": 0.8,
                "population": 1,
                "default": True,
                "bureaucracy": -1,
            },
            0.75,
        ),
        (
            {
                "schools_present": True,
                "schools_investment": None,
                "literacy": 0.4,
                "population": 1,
                "default": True,
                "bureaucracy": -1,
            },
            0.85,
        ),
        (
            {
                "schools_present": True,
                "schools_investment": 5,
                "literacy": 0.4,
                "population": 1,
                "default": False,
                "bureaucracy": 0,
            },
            1.04,
        ),
    ]
    for changes, expected in states:
        observed, reference, _ = numeric(row, field, defaults(row["policy"], changes))
        assert observed == pytest.approx(expected)
        assert reference == pytest.approx(expected)


def test_subject_direct_overlord_identity_exit_and_rebind(actual):
    row = actual[SUBJECT]
    field = "ai_strategy_subject_overlord_compliance.weight"
    sequence: list[tuple[str | None, dict[str, int | None], bool, int, int, float]] = [
        ("A", {"A": 2}, True, 40, 0, 1.08),
        ("B", {"A": 2, "CANDIDATE": 5}, True, 40, 0, 1),
        ("B", {"A": 2, "B": 3}, True, 40, 0, 1.08),
        ("B", {"B": 3}, True, 25, 50, 1.26),
        ("B", {"B": None}, True, 25, 50, 1.18),
        (None, {"B": 3}, True, 40, 0, 1),
        ("B", {"B": 3}, False, 25, 50, 1),
        ("B", {"B": 3}, True, 50, 0, 1.08),
        ("B", {"B": 3}, True, 40, 0, 1.08),
    ]
    for overlord, dependence, subject, liberty, relations, expected in sequence:
        current_dependence = dependence.get(overlord) if overlord is not None else None
        values = defaults(
            row["policy"],
            {
                "actor_is_subject": subject,
                "liberty": liberty,
                "actual_overlord_relations": relations,
                dependence_module.READER: subject
                and overlord is not None
                and current_dependence is not None
                and current_dependence > 1,
            },
        )
        facts: dict[str, Any] = {
            "ROOT": {
                "is_ai": True,
                "is_subject": subject,
                "liberty_desire": liberty,
                "overlord": {"country_id": overlord, "relations:root": relations}
                if overlord
                else None,
                "economic_dependence": dependence,
                "top_overlord": {"country_id": "TOP"},
            },
            "scope:overlord": {"country_id": "CANDIDATE"},
        }
        assert _native_number(1, _overlay(row["generated"], field), facts) == pytest.approx(
            expected
        )
        assert decision_rules.evaluate(row["policy"], values, is_ai=True).get(
            field, ("multiply", 1)
        )[1] == pytest.approx(expected)
        facts["ROOT"]["is_princely_state"] = False
        assert native_number(row, field, facts) == pytest.approx((50 - liberty) * 2 * expected)
        facts["ROOT"]["is_princely_state"] = True
        assert native_number(row, field, facts) == pytest.approx(
            ((50 - liberty) * 2 + 10) * expected
        )
        if liberty == 50:
            assert _native_number(0, _overlay(row["generated"], field), facts) == 0


def test_subject_original_qualification_reject_and_zero(actual):
    row = actual[SUBJECT]
    strategy = _block(parse_text(row["generated"]).root, "ai_strategy_subject_overlord_compliance")
    possible = _block(strategy, "possible")
    for subject, liberty, enemy, expected in [
        (True, 40, False, True),
        (True, 51, False, False),
        (False, 25, False, False),
        (True, 25, True, False),
        (True, None, False, None),
    ]:
        assert (
            pdx_eval.condition(
                possible,
                {
                    "is_subject": subject,
                    "liberty_desire": liberty,
                    "is_diplomatic_play_enemy_of": {(("argument", "overlord"),): enemy},
                },
            )
            is expected
        )


def test_exact_native_journal_scope_is_finite_unknown_and_shape_checked():
    block = parse_text(
        "je:je_five_year_plan ?= { has_variable = five_year_plan_light_industry_var }"
    ).root
    assert pdx_eval.condition(block, {}) is None
    assert pdx_eval.condition(block, {"je:je_five_year_plan": None}) is None
    assert (
        pdx_eval.condition(
            block,
            {
                "je:je_five_year_plan": {
                    "has_variable": {(("argument", "five_year_plan_light_industry_var"),): True}
                }
            },
        )
        is True
    )
    for script in (
        "je:unregistered ?= { always = yes }",
        "je:je_five_year_plan > { always = yes }",
        "je:je_five_year_plan ?= { unknown = { always = yes } }",
    ):
        with pytest.raises(pdx_eval.UnsupportedPdxError):
            pdx_eval.condition(parse_text(script).root, {})


@pytest.mark.parametrize("level", [None, 0, 1, 3, 5])
@pytest.mark.parametrize("active", [True, False, None])
def test_colonial_activity_investment_exit_and_independent_cost(actual, level, active):
    row = actual[DEFAULT]
    field = "ai_strategy_default.institution_scores.institution_colonial_affairs"
    changes = {
        "has_colonial_affairs_institution": True,
        "colonial_affairs_investment": level,
        "colonial_active_projects": active,
        "bureaucracy": -1,
        "war": False,
        "default": True,
    }

    def states(facts):
        facts["ROOT"]["any_scope_state"] = (
            None if active is None else ([{"is_under_colonization": True}] if active else [])
        )

    observed, reference, facts = numeric(row, field, defaults(row["policy"], changes), world=states)
    # Independent contributions +.18 need -.10/-.14 withdrawal -.20 admin
    # -.25 financing; the declared .5 consumer floor remains explicit.
    expected = {
        (True, None): 0.73,
        (True, 0): 0.73,
        (True, 1): 0.73,
        (True, 3): 0.63,
        (True, 5): 0.59,
        (False, None): 0.55,
        (False, 0): 0.55,
        (False, 1): 0.5,
        (False, 3): 0.5,
        (False, 5): 0.5,
        (None, None): 0.55,
        (None, 0): 0.55,
        (None, 1): 0.55,
        (None, 3): 0.55,
        (None, 5): 0.55,
    }[(active, level)]
    assert observed == pytest.approx(expected)
    assert reference == pytest.approx(expected)
    assert complete(row, field, facts) == pytest.approx(10 * expected)


def test_law_actual_adoption_withdrawal_keeps_need_and_crisis_independent(actual):
    row = actual["common/laws/02_free_speech.txt"]
    field = "law_right_of_assembly.ai_enact_weight_modifier"
    agenda = "law_context_law_right_of_assembly_movement_base"
    current = "law_context_current_law_right_of_assembly"
    cases = [
        (
            {
                agenda: True,
                current: False,
                "legitimacy": 60,
                "insurrection": False,
                "radical_share": 0.2,
                "literacy": 0.8,
            },
            6,
        ),
        (
            {
                agenda: True,
                current: True,
                "legitimacy": 60,
                "insurrection": False,
                "radical_share": 0.2,
                "literacy": 0.8,
            },
            0,
        ),
        (
            {
                agenda: True,
                current: False,
                "legitimacy": 10,
                "insurrection": True,
                "radical_share": 0.3,
                "literacy": 0.8,
            },
            -4,
        ),
        (
            {
                agenda: None,
                current: True,
                "legitimacy": None,
                "insurrection": None,
                "radical_share": None,
                "literacy": None,
            },
            None,
        ),
    ]
    for changes, expected in cases:
        values = defaults(row["policy"], changes)

        def movements(facts, values=values):
            facts["ROOT"]["any_political_movement"] = (
                None
                if values[agenda] is None
                else (
                    [
                        {
                            "law_enactment_stance": {
                                (("law", "law_type:law_right_of_assembly"),): 1
                            },
                            "political_movement_support": 0.1,
                        }
                    ]
                    if values[agenda]
                    else []
                )
            )

        observed, reference, _ = numeric(row, field, values, base=0, world=movements)
        if expected is None:
            assert observed == 0
            assert reference == 0
        else:
            assert observed == pytest.approx(expected)
            assert reference == pytest.approx(expected)


def test_law_known_only_authority_cost_has_local_unknown_exit(actual):
    row = actual["common/laws/02_free_speech.txt"]
    field = "law_right_of_assembly.ai_enact_weight_modifier"
    for authority, expected in [(0, -8), (49, -8), (50, 0), (None, 0), (0, -8)]:
        values = defaults(
            row["policy"], {"law_context_current_law_censorship": True, "authority": authority}
        )
        values["law_context_law_right_of_assembly_movement_base"] = False

        def movements(facts):
            facts["ROOT"]["any_political_movement"] = []

        observed, reference, _ = numeric(row, field, values, base=0, world=movements)
        assert observed == expected
        assert reference == expected
    (rule,) = (
        r
        for r in row["policy"].rules
        if r.id == "law_context_law_right_of_assembly_law_censorship_authority_transition"
        and r.field == tuple(field.split("."))
    )
    assert rule.semantic_role == "cost"
    assert rule.conservative_unknown_facts == ()


def test_internal_security_adopted_exit_and_new_institution_costs(actual):
    row = actual["common/laws/00_internal_security.txt"]
    field = "law_national_guard.ai_enact_weight_modifier"
    agenda = "security_law_national_guard_movement_base"
    current = "security_current_law_national_guard"
    absent = "security_current_law_no_home_affairs"
    sequence = [
        ({agenda: True, absent: True, "bureaucracy": -1, "default": True}, -8),
        ({agenda: True, absent: True, "bureaucracy": 0, "default": True}, -2),
        ({agenda: True, absent: True, "bureaucracy": 0, "default": False}, 6),
        ({agenda: True, current: True, "bureaucracy": -1, "default": True}, 0),
        ({agenda: None, current: True}, 0),
        ({agenda: True, absent: True, "bureaucracy": None, "default": False}, 0),
        ({agenda: True, absent: True, "bureaucracy": 0, "default": False}, 6),
    ]
    for changes, expected in sequence:
        values = defaults(row["policy"], changes)

        def movements(facts, values=values):
            facts["ROOT"]["any_political_movement"] = (
                None
                if values[agenda] is None
                else (
                    [
                        {
                            "law_enactment_stance": {(("law", "law_type:law_national_guard"),): 1},
                            "political_movement_support": 0.1,
                            "political_movement_radicalism": 0,
                        }
                    ]
                    if values[agenda]
                    else []
                )
            )

        observed, reference, _ = numeric(row, field, values, base=0, world=movements)
        assert observed == expected
        assert reference == expected


def test_migration_cancel_unknown_absorption_recovery_and_owner_cost(actual):
    row = actual[INDUSTRY]
    field = "building_textile_mill.ai_value"
    # +.08 clothes need +max(.06 jobs,.10 actual migration upgrade) -.15 default.
    states = [
        (True, 0.1, -1, False, 1.18),
        (False, 0.1, -1, False, 1.14),
        (None, 0.1, -1, False, 1.14),
        (True, 0.09999, -1, False, 1.08),
        (True, None, -1, False, 1.08),
        (True, 0.1, 0, False, 1),
        (True, 0.1, -1, True, 1.03),
        (False, 0.1, -1, True, 0.99),
        (True, 0.1, -1, False, 1.18),
    ]
    for target, unemployment, balance, default, expected in states:
        values = defaults(
            row["policy"],
            {
                "state_mass_migration_target": target,
                "state_unemployment": unemployment,
                "state_owner_clothes_balance": balance,
                "state_owner_default": default,
                "state_peasants_share": 0.1,
            },
        )
        observed, reference, facts = numeric(row, field, values)
        assert observed == pytest.approx(expected)
        assert reference == pytest.approx(expected)
        # Exact native tail: ordinary base 1000, active light-industry JE +2500.
        owner = facts["ROOT"]["owner"]
        owner["has_journal_entry"] = {(("argument", "je_five_year_plan"),): False}
        owner["five_year_plan_light_industry_goal_met"] = False
        owner["je:je_five_year_plan"] = {
            "has_variable": {(("argument", "five_year_plan_light_industry_var"),): True}
        }
        assert complete(row, field, facts) == pytest.approx(1000 * expected)
        owner["has_journal_entry"][(("argument", "je_five_year_plan"),)] = True
        assert complete(row, field, facts) == pytest.approx(3500 * expected)
        owner["five_year_plan_light_industry_goal_met"] = True
        assert complete(row, field, facts) == pytest.approx(1000 * expected)
        decoy = deepcopy(facts)
        decoy["ROOT"]["is_mass_migration_target"] = None
        decoy["ROOT"]["owner"]["is_mass_migration_target"] = True
        decoy["other_state"] = {"is_mass_migration_target": True}
        if unemployment == 0.1 and balance == -1:
            assert _native_number(1, _overlay(row["generated"], field), decoy) == pytest.approx(
                0.99 if default else 1.14
            )


def test_player_domain_off_native_zero_and_complete_retained_sources(actual):
    for source, row in actual.items():
        policy = row["policy"]
        values = defaults(policy)
        assert decision_rules.evaluate(policy, values, is_ai=False) == {}
        assert (
            decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
        )
        assert (
            decision_rules.patch(
                row["prepared"],
                policy,
                baseline=row["native"],
                default_strategy=source == INFO,
                enabled_domains=frozenset(),
            )
            == row["prepared"]
        )
        left = [(t.kind, t.value) for t in tokenize(row["prepared"])]
        right = [(t.kind, t.value) for t in tokenize(restored(row["generated"]))]
        assert left == right


def test_normal_mode_has_actual_common_ports_and_source_contexts(actual):
    if not next(iter(actual.values()))["normal"]:
        assert all(row["model"] is None for row in actual.values())
        return  # Preparation is labelled explicitly in emitted evidence.
    for source, row in actual.items():
        policy, model = row["policy"], row["model"]
        writers = {(w.source, w.definition): w for w in model.consumer_ir.writers}
        bindings = {binding.definition: binding for binding in policy.port_bindings}
        for rule in policy.rules:
            writer = writers[(source, rule.id)]
            assert writer.evaluation_context.status == "observed"
            assert bindings[rule.id].contribution in writer.port_contributions
            bindings[rule.id].validate(rule, {reader.key: reader for reader in policy.readers})
