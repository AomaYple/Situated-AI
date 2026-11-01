"""K4 成本、稳定排序和失败语义。"""

import math
from typing import cast

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


def test_core_unknown_does_not_replace_vanilla_or_unlock_a_candidate() -> None:
    result = choose(
        (Candidate("unknown", capability_gain=100, core_evidence=(None,)),),
        max_delta=20,
    )
    assert result.action_id is None
    assert result.fallback == "vanilla"


def test_auxiliary_unknown_keeps_only_the_known_base_tier() -> None:
    result = choose(
        (
            Candidate(
                "partial",
                capability_gain=100,
                base_delta=2,
                auxiliary_evidence=(None,),
            ),
        ),
        max_delta=20,
    )
    assert result.action_id == "partial"
    assert result.delta == 2
    assert result.fallback == "lower_tier"


def test_false_core_evidence_is_a_qualification_failure() -> None:
    result = choose(
        (
            Candidate("blocked", capability_gain=100, core_evidence=(False,)),
            Candidate("eligible", base_delta=1, core_evidence=(True,)),
        ),
        max_delta=20,
    )
    assert result.action_id == "eligible"


def test_malformed_evidence_fails_closed() -> None:
    with pytest.raises(ValueError, match="bool/None"):
        choose((Candidate("bad", core_evidence=(cast("bool | None", 1),)),), max_delta=5)
