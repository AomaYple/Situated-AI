"""SC01-SC32 的手写期望与最终生成显式行动 overlay 见证。"""

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from pdx.situated.compiler import load_model, strategy_overlay
from pdx.situated.pdx_eval import select

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[1]
_BASE_FACTS: dict[str, object | None] = {
    "is_ai": True,
    "is_at_war": False,
    "in_default": False,
    "any_insurrection_ongoing": False,
    "legitimacy": 60,
    "bureaucracy": 1,
    "literacy_rate": 0.3,
    "is_subject": True,
}


class Expected(TypedDict):
    action_id: str | None
    fallback: str
    delta: float


class Scenario(TypedDict):
    id: str
    consumer: str
    facts: dict[str, object | None]
    expected: Expected


def _cases() -> list[Scenario]:
    payload = json.loads((_ROOT / "tests/fixtures/situated/cases.json").read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["evidence"] == "handwritten_static_scenarios_for_explicit_action_overlay"
    return cast("list[Scenario]", payload["cases"])


# Frozen JSON preserves all original observations. The historical winner
# expectations are superseded by these handwritten signed-program deltas.
_DELTAS = (
    0,
    0.25,
    0.05,
    0.25,
    0,
    0.35,
    0.025,
    -4,
    0,
    0,
    0.025,
    -4,
    8,
    0.35,
    0.025,
    0.25,
    0,
    0.35,
    0.025,
    0.25,
    0,
    0,
    0,
    0.25,
    8,
    0.35,
    0.025,
    0.25,
    0,
    0.35,
    0.025,
    -4,
)
_JOINT_IDS = {
    "diplomatic_play_neutrality": "joint_fiscal_neutrality",
    "change_law_chance": "joint_reform_chance",
    "economic_vs_government_spending_balance": "joint_economic_balance",
    "recklessness": "joint_diplomatic_recklessness",
}


@pytest.mark.parametrize("case", _cases(), ids=lambda item: item["id"])
def test_handwritten_scenario_matches_independent_generated_pdx(case: Scenario) -> None:
    overlays = strategy_overlay(load_model())
    facts = dict(_BASE_FACTS)
    facts.update(case["facts"])
    result = select(overlays[case["consumer"]], facts)
    delta = _DELTAS[int(case["id"][2:]) - 1]
    if facts["is_ai"] is False:
        assert result.action_id is None
        assert result.operation is None
        assert result.fallback == "vanilla"
    else:
        assert result.action_id == _JOINT_IDS[case["consumer"]]
        assert result.operation == "add"
        assert result.fallback == "selected"
    assert result.delta == pytest.approx(delta)
