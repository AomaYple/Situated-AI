"""两个有限时钟和路线退出迟滞。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TemporalState:
    route: str | None = None
    entered_day: int | None = None
    expires_day: int | None = None
    cooldown_until: int | None = None


def advance(state: TemporalState, *, day: int, ttl_days: int, cooldown_days: int) -> TemporalState:
    if day < 0 or ttl_days <= 0 or cooldown_days < 0:
        raise ValueError("时间合同参数无效")
    if state.route is None:
        return state
    if state.expires_day is not None and day >= state.expires_day:
        return TemporalState(cooldown_until=day + cooldown_days)
    return state
