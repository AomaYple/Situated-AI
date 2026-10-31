"""K2 动态目标的进入、保持、退出与 TTL 合同。"""

from __future__ import annotations

import pytest

from pdx.situated.goals import Goal, contract, transition

pytestmark = pytest.mark.unit


def test_goal_enters_on_any_source_and_exits_when_all_sources_false() -> None:
    goal = Goal(
        "survival",
        100,
        "crisis",
        True,
        source_pressures=("fiscal_default", "wartime"),
        ttl_days=30,
        consumer_bindings=("fiscal_neutrality",),
    )
    active = transition((goal,), {"fiscal_default": False, "wartime": True}, day=10)[0]
    assert active.active
    assert active.entered_day == 10
    assert active.expires_day == 40
    held = transition(
        (goal,), {"fiscal_default": None, "wartime": None}, day=20, previous={"survival": active}
    )[0]
    assert held.active
    assert held.reason == "unknown_hold"
    expired = transition(
        (goal,), {"fiscal_default": None, "wartime": None}, day=40, previous={"survival": held}
    )[0]
    assert not expired.active
    assert expired.reason == "ttl_expired"
    exited = transition(
        (goal,), {"fiscal_default": False, "wartime": False}, day=41, previous={"survival": active}
    )[0]
    assert not exited.active
    assert exited.reason == "sources_false"


def test_unconditional_goal_is_available_without_fake_pressure() -> None:
    goal = Goal("capacity", 60, "medium", True, ttl_days=100)
    result = transition((goal,), {}, day=0)
    assert result[0].active
    assert result[0].expires_day == 100


def test_goal_contract_contains_dynamic_bindings() -> None:
    goal = Goal("capacity", 60, "medium", True, consumer_bindings=("economic_balance",))
    result = contract((goal,))
    assert result["dynamic"] is True
    assert result["consumer_bindings"] == ["economic_balance"]
    assert result["goals"][0]["id"] == "capacity"


def test_invalid_ttl_is_rejected() -> None:
    with pytest.raises(ValueError):
        Goal("bad", 1, "short", True, ttl_days=0)
