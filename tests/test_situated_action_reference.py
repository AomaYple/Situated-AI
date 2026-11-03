"""Real explicit consumers: handwritten expectations, production reference and PDX."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.unit
_BASE: dict[str, object] = {
    "is_ai": True,
    "is_at_war": False,
    "in_default": False,
    "any_insurrection_ongoing": False,
    "legitimacy": 60,
    "bureaucracy": 1,
    "literacy_rate": 0.3,
    "is_subject": True,
}
_CASES = json.loads(
    (Path(__file__).parent / "fixtures/situated/cases.json").read_text(encoding="utf-8")
)["cases"]


def _typed(engine: dict[str, object]) -> dict[str, object]:
    """Independent observation mapping; missing input remains unknown, never zero."""
    values: dict[str, object] = {}
    for source, target in (
        ("is_at_war", "war"),
        ("in_default", "default"),
        ("any_insurrection_ongoing", "ongoing_insurrection"),
        ("has_insurrectionary_interest_groups", "insurrection"),
        ("is_subject", "subject"),
        ("legitimacy", "legitimacy"),
        ("bureaucracy", "bureaucracy"),
        ("scaled_debt", "debt_ratio"),
        ("net_total_income", "net_surplus"),
        ("infamy", "infamy"),
        ("sitai_context_evidence_need_industry", "coord_evidence_need_industry"),
        ("sitai_context_need_education", "coord_need_education"),
    ):
        if source in engine:
            values[target] = engine[source]
    for source, target in (
        ("is_at_war", "peace"),
        ("in_default", "no_default"),
        ("any_insurrection_ongoing", "no_insurrection"),
    ):
        raw = engine.get(source)
        values[target] = not raw if type(raw) is bool else None
    for source, target, op, boundary in (
        ("legitimacy", "stable_legitimacy", ">=", 50),
        ("legitimacy", "strong_legitimacy", ">=", 75),
        ("bureaucracy", "bureaucracy_positive", ">", 0),
        ("literacy_rate", "literacy_low", "<", 0.5),
        ("literacy_rate", "literacy_ready", ">=", 0.5),
    ):
        raw = engine.get(source)
        if type(raw) in (int, float):
            number = cast("float", raw)
            values[target] = {
                ">=": number >= boundary,
                ">": number > boundary,
                "<": number < boundary,
            }[op]
        else:
            values[target] = None
    return values


@pytest.fixture(scope="module")
def production():
    model = compiler.load_model()
    return model, compiler.strategy_overlay(model)


# The JSON retains the original observation corpus. Expectations below are
# handwritten for signed contributions, local unknowns and one consumer clamp.
_SC_DELTAS = (
    0,
    0.25,
    0.05,
    0.25,
    0,
    0.25,
    0.05,
    -4,
    0,
    0,
    0.05,
    -4,
    8,
    0.25,
    0.05,
    0.25,
    0,
    0.25,
    0.05,
    0.25,
    0,
    0,
    0,
    0.25,
    8,
    0.25,
    0.05,
    0.25,
    0,
    0.25,
    0.05,
    -4,
)
_JOINT_IDS = {
    "diplomatic_play_neutrality": "joint_fiscal_neutrality",
    "change_law_chance": "joint_reform_chance",
    "economic_vs_government_spending_balance": "joint_economic_balance",
    "recklessness": "joint_diplomatic_recklessness",
}


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_sc01_to_sc32_use_real_reference_entry(production, case):
    model, overlays = production
    engine = {**_BASE, **case["facts"]}
    field = case["consumer"]
    delta = _SC_DELTAS[int(case["id"][2:]) - 1]
    reference = compiler.evaluate_actions(model, _typed(engine), is_ai=engine["is_ai"])
    generated = pdx_eval.select(overlays[field], engine)
    assert generated.delta == pytest.approx(delta)
    if delta == 0:
        assert field not in reference
        if engine["is_ai"] is False:
            assert generated.action_id is None
            assert generated.operation is None
            assert generated.fallback == "vanilla"
        else:
            assert generated.action_id == _JOINT_IDS[field]
            assert generated.operation == "add"
            assert generated.fallback == "selected"
    else:
        assert generated.action_id == _JOINT_IDS[field]
        assert reference[field][0] == _JOINT_IDS[field]
        assert reference[field][1] == pytest.approx(delta)


_COMPLETE = {
    **_BASE,
    "legitimacy": 80,
    "literacy_rate": 0.6,
    "is_subject": False,
    "scaled_debt": 0.2,
    "net_total_income": 1,
    "infamy": 0,
    "sitai_context_evidence_need_industry": False,
    "sitai_context_need_education": False,
}
_CARD_CASES = [
    ("fiscal_recovery", "diplomatic_play_neutrality", {"in_default": True}, 8.0),
    ("wartime_defense", "diplomatic_play_neutrality", {"is_at_war": True}, 6.0),
    ("political_reform", "change_law_chance", {}, 0.5),
    ("industrial_foundation", "economic_vs_government_spending_balance", {}, 0.15),
    (
        "education_and_research",
        "economic_vs_government_spending_balance",
        {"literacy_rate": 0.3, "sitai_context_need_education": True},
        0.025,
    ),
    ("diplomatic_restraint", "recklessness", {"is_at_war": True}, -4.0),
    ("diplomatic_opening", "recklessness", {}, 2.0),
    ("reform_progressive_window", "max_progressiveness", {}, 5.0),
    ("reform_conservative_guard", "max_regressiveness", {"in_default": True}, 5.0),
    ("diplomatic_boldness_window", "diplomatic_play_boldness", {}, 8.0),
    ("diplomatic_aggression_guard", "aggression", {}, 0.1),
]


@pytest.mark.parametrize(("action", "field", "changes", "delta"), _CARD_CASES, ids=str)
def test_all_eleven_actual_cards_have_handwritten_three_way_witnesses(
    production, action, field, changes, delta
):
    model, overlays = production
    assert {row[0] for row in _CARD_CASES} == {card.id for card in model.actions}
    engine = {**_COMPLETE, **changes}
    reference = compiler.evaluate_actions(model, _typed(engine), is_ai=True)
    generated = pdx_eval.select(overlays[field], engine)
    consumer = next(row for row in model.consumers if row.field == field)
    assert reference[field][0] == generated.action_id == f"joint_{consumer.id}"
    assert reference[field][1] == pytest.approx(delta)
    assert generated.delta == pytest.approx(delta)


def test_one_observation_evaluates_multiple_real_consumers(production):
    model, _ = production
    result = compiler.evaluate_actions(model, _typed(_COMPLETE), is_ai=True)
    assert {
        "change_law_chance",
        "economic_vs_government_spending_balance",
        "recklessness",
        "max_progressiveness",
        "diplomatic_play_boldness",
        "aggression",
    } == set(result)
    assert result["economic_vs_government_spending_balance"][0] == "joint_economic_balance"
    assert result["economic_vs_government_spending_balance"][1] == pytest.approx(0.15)


@pytest.mark.parametrize("enabled", [frozenset(), frozenset({"recklessness"})])
def test_actual_module_switch_isolates_reference_and_generated_output(production, enabled):
    model, _ = production
    values = _typed(_COMPLETE)
    result = compiler.evaluate_actions(model, values, is_ai=True, enabled_consumer_fields=enabled)
    overlays = compiler.strategy_overlay(model, enabled_consumer_fields=enabled)
    assert set(result) <= enabled
    for field in enabled:
        actual = pdx_eval.select(overlays[field], _COMPLETE)
        assert result[field] == (actual.action_id, actual.delta)


def test_disabled_optional_cross_consumer_complement_does_not_block_base(production):
    """The retired political edge cannot leave an unrelated consumer dependency."""
    model, _ = production
    field = "economic_vs_government_spending_balance"
    result = compiler.evaluate_actions(
        model, _typed(_COMPLETE), is_ai=True, enabled_consumer_fields={field}
    )
    actual = pdx_eval.select(
        compiler.strategy_overlay(model, enabled_consumer_fields={field})[field], _COMPLETE
    )
    assert result[field] == ("joint_economic_balance", 0.15)
    assert (actual.action_id, actual.delta) == result[field]


def test_player_and_missing_core_cannot_create_explicit_adjustment(production):
    model, overlays = production
    assert compiler.evaluate_actions(model, _typed(_COMPLETE), is_ai=False) == {}
    assert compiler.evaluate_actions(model, {}, is_ai=True) == {}
    player = {**_COMPLETE, "is_ai": False}
    assert all(pdx_eval.select(text, player).delta == 0 for text in overlays.values())


def test_unknown_cost_uses_conservative_tier_without_fabricating_health(production):
    model, overlays = production
    engine = {**_COMPLETE, "scaled_debt": None}
    field = "economic_vs_government_spending_balance"
    reference = compiler.evaluate_actions(model, _typed(engine), is_ai=True)
    actual = pdx_eval.select(overlays[field], engine)
    assert reference[field][0] == "joint_economic_balance"
    assert reference[field][1] == pytest.approx(0.05)
    assert actual.action_id == reference[field][0]
    assert actual.delta == pytest.approx(reference[field][1])


def test_reference_rejects_non_boolean_actor_flag(production):
    model, _ = production
    with pytest.raises(ValueError, match="布尔"):
        compiler.evaluate_actions(model, {}, is_ai=cast("bool", 1))
