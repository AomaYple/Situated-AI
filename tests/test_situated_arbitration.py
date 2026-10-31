"""K4 成本、稳定排序和失败语义。"""

import math

import pytest

from pdx.situated.arbitration import Candidate, choose

pytestmark = pytest.mark.unit


def test_cost_changes_strength_before_final_delta() -> None:
    low = choose((Candidate("low", capability_gain=3, feasibility=4),), max_delta=20)
    high = choose(
        (Candidate("high", capability_gain=3, feasibility=4, political_cost=4),),
        max_delta=20,
    )
    assert high.delta < low.delta
    assert "political_cost" in high.reason_codes


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_candidate_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="非有限"):
        choose((Candidate("invalid", opportunity_value=value),), max_delta=5)


def test_empty_or_invalid_budget_falls_back_to_vanilla() -> None:
    result = choose((), max_delta=5)
    assert result.fallback == "vanilla"
    with pytest.raises(ValueError, match="正有限"):
        choose((), max_delta=0)
