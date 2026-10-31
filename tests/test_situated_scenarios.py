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


@pytest.mark.parametrize("case", _cases(), ids=lambda item: item["id"])
def test_handwritten_scenario_matches_independent_generated_pdx(case: Scenario) -> None:
    overlays = strategy_overlay(load_model())
    facts = dict(_BASE_FACTS)
    facts.update(case["facts"])
    result = select(overlays[case["consumer"]], facts)
    expected = case["expected"]
    assert result.action_id == expected["action_id"]
    assert result.fallback == expected["fallback"]
    assert result.delta == expected["delta"]
