"""目标组合：危机抢占，普通目标并行，退出由输入变化决定。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Goal:
    id: str
    priority: int
    horizon: str
    active: bool


def prioritize(goals: tuple[Goal, ...]) -> tuple[Goal, ...]:
    return tuple(
        sorted((item for item in goals if item.active), key=lambda item: (-item.priority, item.id))
    )
