"""K5：对生成 PDX 行动文本执行独立语义见证。"""

import pytest

from pdx.situated.compiler import load_model, strategy_overlay
from pdx.situated.pdx_eval import UnsupportedPdxError, select

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
    assert result.action_id == "wartime_defense"
    assert result.delta == 5.0


def test_pdx_evaluator_keeps_local_economy_and_education_paths_reachable() -> None:
    result = select(_overlays()["economic_vs_government_spending_balance"], _facts())
    assert result.action_id == "education_and_research"
    assert result.delta == 3.0


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


def test_nested_complement_is_part_of_the_generated_delta() -> None:
    result = select(_overlays()["economic_vs_government_spending_balance"], _facts())
    assert result.delta == 3.0
    without_bureaucracy = select(
        _overlays()["economic_vs_government_spending_balance"], _facts(bureaucracy=0)
    )
    assert without_bureaucracy.action_id == "education_and_research"
    assert without_bureaucracy.delta == 2.0
