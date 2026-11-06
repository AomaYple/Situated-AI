"""Exact native merging and simultaneous independent political/social actions."""

from __future__ import annotations

import json

import pytest
from task15_lifecycle_support import DEFAULT, INFO, complete, defaults, native_number, numeric
from task15_native_number import number
from test_remaining_joint_consumers import _block
from test_situated_joint_witnesses import _facts
from test_task15_lifecycle import actual as actual  # noqa: PLC0414 -- pytest fixture re-export

from pdx import config
from pdx.parser import parse_text
from pdx.situated import engine_scope, pdx_eval


@pytest.mark.parametrize(
    ("active", "need", "admin", "default", "expected"),
    [
        (None, False, 0, False, 10),
        (None, True, 0, False, 10.8),
        ("ai_strategy_consolidation_agenda", True, 0, False, 135.8),
        ("ai_strategy_confrontation_agenda", True, 0, False, 210.8),
        ("ai_strategy_consolidation_agenda", True, -1, False, 134.8),
        ("ai_strategy_confrontation_agenda", True, -1, True, 207.8),
    ],
)
def test_actual_default_and_active_full_numeric_merge(
    actual, active, need, admin, default, expected
):
    contract = json.loads(engine_scope.strategy_snapshot())
    assert (
        contract["strategy_field_merges"]["institution_scores"]["interpretation"]
        == "default plus each active"
    )
    row = actual[INFO]
    vals = defaults(
        row["policy"],
        {
            "average_sol": 7 if need else 25,
            "population": 1,
            "social_security_present": True,
            "bureaucracy": admin,
            "default": default,
        },
    )
    _, _, facts = numeric(row, "institution_scores.institution_social_security", vals)
    result = complete(
        row, "ai_strategy_default.institution_scores.institution_social_security", facts
    )
    if active:
        politics = parse_text(
            (config.GAME / "common/ai_strategies/03_political_strategies.txt").read_text(
                encoding="utf-8-sig"
            )
        ).root
        strategy = _block(politics, active)
        qualification = _block(strategy, "possible")
        assert pdx_eval.condition(qualification, {"has_radical_leftist_government": False}) is False
        assert pdx_eval.condition(qualification, {"has_radical_leftist_government": True}) is True
        result += number(
            _block(_block(strategy, "institution_scores"), "institution_social_security"), facts
        )
    assert result == pytest.approx(expected)


def test_law_chance_native_active_first_nonzero_and_default_exhaustion():
    contract = json.loads(engine_scope.strategy_snapshot())
    native = parse_text((config.GAME / DEFAULT).read_text(encoding="utf-8-sig")).root
    politics = parse_text(
        (config.GAME / "common/ai_strategies/03_political_strategies.txt").read_text(
            encoding="utf-8-sig"
        )
    ).root
    for field in ("change_law_chance", "min_law_chance_to_pass"):
        assert (
            contract["strategy_field_merges"][field]["evaluation_order"]
            == "active until first nonzero; default only on exhaustion"
        )
    for active, expected in [
        ("ai_strategy_consolidation_agenda", 10),
        ("ai_strategy_confrontation_agenda", 20),
    ]:
        default = number(_block(_block(native, "ai_strategy_default"), "change_law_chance"), {})
        assert default == 1
        choice = number(_block(_block(politics, active), "change_law_chance"), {})
        assert choice == expected
        assert next(v for v in (choice, default) if v != 0) == expected
        assert next(v for v in (0, default) if v != 0) == 1


@pytest.mark.parametrize(
    ("amenability", "stall", "advance", "reason", "level", "expected"),
    [
        (0.5, 0.1, 0.1, False, 1, 0.65),
        (0.5, 0.1, 0.1, True, 1, 1),
        (0.1, 0, 0.2, False, 1, -0.05),
        (0, 0.1, 0, False, 1, 0.1),
        (0.5, 0.1, 0.1, False, 4, 0.25),
    ],
)
def test_complete_negotiation_native_reject_and_no_invented_zero_floor(
    actual, amenability, stall, advance, reason, level, expected
):
    row = actual[DEFAULT]
    vals = defaults(
        row["policy"],
        {"negotiation_amenability": amenability, "radical_share": 0.25, "legitimacy": 60},
    )
    facts = _facts(row["policy"], vals)
    facts.update(
        {
            "scope:amenability": amenability,
            "scope:stall_chance": stall,
            "scope:advance_chance": advance,
            "scope:interest_group": {"amenability_level": level},
            "ai_has_reasons_to_not_oppose_law": reason,
        }
    )
    assert native_number(row, "ai_strategy_default.negotiation_chance", facts) == pytest.approx(
        expected
    )


def test_simultaneous_school_welfare_and_law_need_survive_shared_default(actual):
    row = actual[INFO]
    vals = defaults(
        row["policy"],
        {
            "schools_present": True,
            "schools_investment": 5,
            "literacy": 0.4,
            "population": 1,
            "social_security_present": True,
            "social_security_investment": 5,
            "average_sol": 7,
            "default": True,
            "bureaucracy": -1,
        },
    )
    for field, expected in [
        ("institution_scores.institution_schools", 0.79),
        # Welfare: +.08 need -.05 invested -.10 administration -.20 strongest default.
        ("institution_scores.institution_social_security", 0.73),
    ]:
        observed, reference, facts = numeric(row, field, vals)
        assert observed == pytest.approx(expected)
        assert reference == pytest.approx(expected)
        assert complete(row, "ai_strategy_default." + field, facts) == pytest.approx(10 * expected)
    law = actual["common/laws/01_taxation.txt"]
    lawvals = defaults(
        law["policy"],
        {
            "law_context_law_proportional_taxation_movement_base": True,
            "legitimacy": 10,
            "insurrection": True,
            "radical_share": 0.3,
            "bureaucracy": -1,
            "law_context_current_law_consumption_based_taxation": True,
        },
    )

    def world(facts):
        facts["ROOT"]["any_political_movement"] = [
            {
                "law_enactment_stance": {(("law", "law_type:law_proportional_taxation"),): 1},
                "political_movement_support": 0.1,
            }
        ]

    observed, reference, _ = numeric(
        law, "law_proportional_taxation.ai_enact_weight_modifier", lawvals, base=0, world=world
    )
    assert observed == -10
    assert reference == -10
