"""K5：对生成 PDX 行动文本执行独立语义见证。"""

from dataclasses import replace

import pytest

from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated.compiler import load_model, strategy_overlay
from pdx.situated.pdx_eval import UnsupportedPdxError, condition, select

pytestmark = pytest.mark.unit


def _overlays() -> dict[str, str]:
    return strategy_overlay(load_model())


def _facts(**updates: object | None) -> dict[str, object | None]:
    values: dict[str, object | None] = {
        "is_ai": True,
        "is_at_war": False,
        "in_default": False,
        "any_insurrection_ongoing": False,
        "legitimacy": 60,
        "bureaucracy": 1,
        "literacy_rate": 0.3,
        "is_subject": True,
    }
    values.update(updates)
    return values


def test_pdx_evaluator_selects_crisis_before_normal_capacity() -> None:
    result = select(_overlays()["diplomatic_play_neutrality"], _facts(in_default=True))
    assert (result.action_id, result.fallback) == ("fiscal_recovery", "selected")
    assert result.operation == "add"


def test_pdx_evaluator_changes_to_wartime_defense_without_reference_call() -> None:
    result = select(
        _overlays()["diplomatic_play_neutrality"], _facts(is_at_war=True, in_default=False)
    )
    assert result == result.__class__("wartime_defense", "add", 6.0, "selected")


def test_wartime_defense_yields_to_fiscal_recovery_while_in_default() -> None:
    """The symmetric substitute pair is ordered once, rather than deadlocking."""

    result = select(
        _overlays()["diplomatic_play_neutrality"],
        _facts(is_at_war=True, in_default=True),
    )
    assert result == result.__class__("fiscal_recovery", "add", 8.0, "selected")


def test_diplomatic_restraint_keeps_its_negative_add_in_war() -> None:
    result = select(_overlays()["recklessness"], _facts(is_at_war=True))
    assert result == result.__class__("diplomatic_restraint", "add", -4.0, "selected")


def test_reform_layers_select_progressive_window_when_stable() -> None:
    result = select(_overlays()["max_progressiveness"], _facts())
    assert result == result.__class__("reform_progressive_window", "add", 4.0, "selected")


def test_reform_layers_select_conservative_guard_under_domestic_crisis() -> None:
    result = select(
        _overlays()["max_regressiveness"],
        _facts(in_default=True, any_insurrection_ongoing=True),
    )
    assert result == result.__class__("reform_conservative_guard", "add", 5.0, "selected")


def test_diplomatic_layers_add_boldness_and_aggression_only_inside_capacity_window() -> None:
    boldness = select(_overlays()["diplomatic_play_boldness"], _facts())
    aggression = select(_overlays()["aggression"], _facts())
    assert boldness == boldness.__class__("diplomatic_boldness_window", "add", 6.75, "selected")
    assert aggression == aggression.__class__(
        "diplomatic_aggression_guard", "add", 0.075, "selected"
    )


def test_unknown_peace_does_not_fall_through_to_diplomatic_opening() -> None:
    """Unknown war/peace state is a vanilla boundary for the first candidate."""

    result = select(_overlays()["recklessness"], _facts(is_at_war=None))
    assert result == result.__class__("diplomatic_restraint", None, 0.0, "unknown")


def test_unknown_high_priority_action_does_not_fall_through_to_known_lower_action() -> None:
    """Unknown default status blocks the lower wartime candidate as in the reference path."""

    result = select(
        _overlays()["diplomatic_play_neutrality"],
        _facts(in_default=None, is_at_war=True),
    )
    assert result == result.__class__("fiscal_recovery", None, 0.0, "unknown")


def test_pdx_evaluator_keeps_local_economy_and_education_paths_reachable() -> None:
    result = select(_overlays()["economic_vs_government_spending_balance"], _facts())
    assert result.action_id == "education_and_research"
    assert result.delta == 0.65


def test_unknown_core_fact_is_an_explicit_unknown_fallback() -> None:
    result = select(_overlays()["economic_vs_government_spending_balance"], _facts(is_at_war=None))
    assert result.fallback == "unknown"
    assert result.action_id == "education_and_research"


def test_player_boundary_falls_back_to_vanilla() -> None:
    result = select(_overlays()["recklessness"], _facts(is_ai=False, is_subject=False))
    assert result == result.__class__(None, None, 0.0, "vanilla")


def test_generated_unknown_condition_fails_loudly() -> None:
    with pytest.raises(UnsupportedPdxError, match="未登记"):
        select(
            "# ACTION mystery [test];\nif = { limit = { mystery_trigger = { x = yes } } add = 1 }",
            _facts(),
        )


def test_unknown_complement_falls_back_to_known_base_delta() -> None:
    result = select(
        _overlays()["economic_vs_government_spending_balance"],
        _facts(bureaucracy=None, legitimacy=60),
    )
    assert result.action_id == "education_and_research"
    assert result.fallback == "selected"
    assert result.delta == 0.65


def test_nested_complement_is_part_of_the_generated_delta() -> None:
    model = load_model()
    rows = tuple(
        replace(row, max_delta=3.0) if row.action_id == "education_and_research" else row
        for row in model.decision_ir
    )
    bundle = model.consumer_ir
    assert bundle is not None
    by_id = {row.action_id: row for row in rows}
    model = replace(
        model,
        actions=tuple(
            replace(action, max_delta=3.0) if action.id == "education_and_research" else action
            for action in model.actions
        ),
        decision_ir=rows,
        consumer_ir=replace(
            bundle,
            actions=rows,
            writers=tuple(
                replace(writer, action=by_id[writer.definition])
                if writer.kind == "action_card"
                else writer
                for writer in bundle.writers
            ),
        ),
    )
    overlay = strategy_overlay(model)["economic_vs_government_spending_balance"]
    result = select(overlay, _facts())
    assert result.delta == 0.65
    without_bureaucracy = select(overlay, _facts(bureaucracy=0))
    assert without_bureaucracy.action_id == "education_and_research"
    assert without_bureaucracy.delta == 0.65


def test_complement_must_not_exceed_action_limit() -> None:
    model = load_model()
    action = next(item for item in model.actions if item.id == "education_and_research")
    result = select(_overlays()["economic_vs_government_spending_balance"], _facts())
    assert result.action_id == action.id
    assert abs(result.delta) <= action.max_delta


def _condition_block(text: str) -> Block:
    parsed = parse_text(text)
    assert not parsed.errors
    assignment = parsed.root.first("limit")
    assert assignment is not None
    assert isinstance(assignment.value, Block)
    return assignment.value


def test_fact_reference_uses_explicit_root_path_and_preserves_missing_unknown() -> None:
    block = _condition_block('limit = { ROOT = { gdp > "ROOT.population" } }')
    assert condition(block, {"ROOT": {"gdp": 9.0, "population": 9.0}}) is False
    assert condition(block, {"ROOT": {"gdp": 11.0, "population": 9.0}}) is True
    assert condition(block, {"ROOT": {}}) is None


def test_complete_parameter_identity_handles_arguments_and_numeric_value_fields() -> None:
    boolean = _condition_block("limit = { has_strategy = ai_strategy_industrial_expansion }")
    facts = {
        "has_strategy": {
            (("argument", "ai_strategy_industrial_expansion"),): True,
            (("argument", "ai_strategy_resource_expansion"),): False,
        }
    }
    assert condition(boolean, facts) is True
    assert condition(boolean, {}) is None

    numeric = _condition_block(
        "limit = { pop_type_percent_country = { pop_type = laborers percent >= 0.2 } }"
    )
    numeric_facts = {
        "pop_type_percent_country": {
            (("pop_type", "laborers"),): 0.25,
            (("pop_type", "peasants"),): 0.75,
        }
    }
    assert condition(numeric, numeric_facts) is True
    assert condition(numeric, {"pop_type_percent_country": {}}) is None


def test_parameterized_production_method_keeps_legal_hyphen_identity() -> None:
    block = _condition_block(
        "limit = { is_production_method_active = { "
        "building_type = building_explosives_factory "
        "production_method = pm_ammonia-soda_process } }"
    )
    facts = {
        "is_production_method_active": {
            "building_explosives_factory": {"pm_ammonia-soda_process": True}
        }
    }
    assert condition(block, facts) is True
    assert (
        condition(block, {"is_production_method_active": {"building_explosives_factory": {}}})
        is None
    )


def test_overlord_interest_group_and_named_interest_group_scopes_are_explicit() -> None:
    overlord = _condition_block("limit = { scope:overlord = { is_at_war = yes } }")
    assert condition(overlord, {"scope:overlord": {"is_at_war": True}}) is True
    assert condition(overlord, {}) is None

    group = _condition_block("limit = { ROOT = { ig:ig_landowners = { ig_clout >= 0.5 } } }")
    assert condition(group, {"ROOT": {"ig:ig_landowners": {"ig_clout": 0.7}}}) is True
    assert condition(group, {"ROOT": {"ig:ig_trade_unions": {"ig_clout": 0.7}}}) is None
