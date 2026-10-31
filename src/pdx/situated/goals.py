"""动态目标：危机抢占，普通目标并行，退出由输入变化和 TTL 决定。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

UnknownPolicy = Literal["vanilla", "conservative", "lower_tier"]


@dataclass(frozen=True, slots=True)
class Goal:
    id: str
    priority: int
    horizon: str
    active: bool
    source_pressures: tuple[str, ...] = ()
    source_needs: tuple[str, ...] = ()
    consumer_bindings: tuple[str, ...] = ()
    ttl_days: int | None = None
    unknown_policy: UnknownPolicy = "vanilla"
    entered_day: int | None = None
    expires_day: int | None = None

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise ValueError("目标 id/priority 无效")
        if not self.horizon:
            raise ValueError("目标必须有 horizon")
        if self.ttl_days is not None and (type(self.ttl_days) is not int or self.ttl_days <= 0):
            raise ValueError("目标 ttl_days 必须为正整数")
        if self.unknown_policy not in {"vanilla", "conservative", "lower_tier"}:
            raise ValueError("目标 unknown_policy 无效")
        for label, values in (
            ("source_pressures", self.source_pressures),
            ("source_needs", self.source_needs),
            ("consumer_bindings", self.consumer_bindings),
        ):
            if any(not isinstance(item, str) or not item for item in values):
                raise ValueError(f"目标 {label} 必须是非空字符串元组")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ActiveGoal:
    id: str
    active: bool
    entered_day: int | None
    expires_day: int | None
    reason: str
    consumer_bindings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def prioritize(goals: tuple[Goal, ...]) -> tuple[Goal, ...]:
    return tuple(
        sorted((item for item in goals if item.active), key=lambda item: (-item.priority, item.id))
    )


def _status(value: object) -> bool | None:
    if value is None:
        return None
    if type(value) is bool:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value > 0
    return None


def transition(
    goals: Sequence[Goal],
    signals: Mapping[str, object],
    *,
    day: int,
    previous: Mapping[str, ActiveGoal] | None = None,
) -> tuple[ActiveGoal, ...]:
    """计算目标进入、保持、退出和过期。

    目标的多个来源压力/需求采用 OR：任一已知为真即可激活；全部已知为
    假才解除；存在未知且没有旧状态时保持 vanilla 回退。未知不会被推断
    为危机或健康，避免全满足门槛和错误自动升级。
    """

    if type(day) is not int or day < 0:
        raise ValueError("目标 day 必须为非负整数")
    old = previous or {}
    result: list[ActiveGoal] = []
    for goal in goals:
        keys = (*goal.source_pressures, *goal.source_needs)
        states = tuple(_status(signals.get(key)) for key in keys)
        if not keys:
            desired: bool | None = True
            reason = "unconditional"
        elif any(item is True for item in states):
            desired = True
            reason = "source_true"
        elif all(item is False for item in states):
            desired = False
            reason = "sources_false"
        else:
            desired = None
            reason = "source_unknown"
        prior = old.get(goal.id)
        if (
            desired is not False
            and prior is not None
            and prior.expires_day is not None
            and day >= prior.expires_day
        ):
            desired = False
            reason = "ttl_expired"
        if desired is None:
            active = prior.active if prior is not None else False
            reason = "unknown_hold" if active else "unknown_vanilla"
        else:
            active = desired
        entered = prior.entered_day if prior is not None and active else day if active else None
        expires = (
            prior.expires_day
            if prior is not None and active and prior.expires_day is not None
            else entered + goal.ttl_days
            if active and entered is not None and goal.ttl_days is not None
            else None
        )
        result.append(
            ActiveGoal(
                id=goal.id,
                active=active,
                entered_day=entered,
                expires_day=expires,
                reason=reason,
                consumer_bindings=goal.consumer_bindings,
            )
        )
    return tuple(sorted(result, key=lambda item: item.id))


def contract(goals: Sequence[Goal]) -> dict[str, Any]:
    return {
        "schema": 1,
        "goals": [item.as_dict() for item in sorted(goals, key=lambda row: row.id)],
        "dynamic": True,
        "activation": "any_source_true; unknown_preserves_active_else_vanilla",
        "deactivation": "all_sources_false_or_ttl_expired",
        "consumer_bindings": sorted(
            {binding for item in goals for binding in item.consumer_bindings}
        ),
    }


__all__ = ["ActiveGoal", "Goal", "contract", "prioritize", "transition"]
