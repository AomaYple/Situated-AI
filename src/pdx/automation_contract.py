"""游戏自动化标准流程的纯逻辑状态契约。

状态机不执行窗口操作，只约束 ``game_auto`` 记录的阶段顺序。这样可以在
没有 Windows GUI 的 CI 上验证流程没有被悄悄重排，也让实机报告能明确指出
最后到达的阶段。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AutomationPhase(StrEnum):
    CREATED = "created"
    FOREGROUND_READY = "foreground_ready"
    BOOT_SETTLED = "boot_settled"
    OBSERVE_SELECTED = "observe_selected"
    SPEED_SET = "speed_set"
    RUNNING = "running"
    BACKGROUND = "background"
    VERIFIED = "verified"
    COMPLETE = "complete"


_NEXT: dict[AutomationPhase, frozenset[AutomationPhase]] = {
    AutomationPhase.CREATED: frozenset({AutomationPhase.FOREGROUND_READY}),
    AutomationPhase.FOREGROUND_READY: frozenset({AutomationPhase.BOOT_SETTLED}),
    AutomationPhase.BOOT_SETTLED: frozenset({AutomationPhase.OBSERVE_SELECTED}),
    AutomationPhase.OBSERVE_SELECTED: frozenset({AutomationPhase.SPEED_SET}),
    AutomationPhase.SPEED_SET: frozenset({AutomationPhase.RUNNING}),
    AutomationPhase.RUNNING: frozenset({AutomationPhase.BACKGROUND}),
    AutomationPhase.BACKGROUND: frozenset({AutomationPhase.VERIFIED}),
    AutomationPhase.VERIFIED: frozenset({AutomationPhase.COMPLETE}),
    AutomationPhase.COMPLETE: frozenset(),
}


@dataclass(frozen=True, slots=True)
class AutomationTrace:
    """不可变的阶段轨迹；每次 ``advance`` 都返回新对象。"""

    phases: tuple[AutomationPhase, ...] = (AutomationPhase.CREATED,)

    @property
    def current(self) -> AutomationPhase:
        return self.phases[-1]

    def advance(self, phase: AutomationPhase) -> AutomationTrace:
        if phase not in _NEXT[self.current]:
            raise ValueError(f"非法自动化状态转移：{self.current.value} -> {phase.value}")
        return AutomationTrace((*self.phases, phase))

    @property
    def complete(self) -> bool:
        return self.current is AutomationPhase.COMPLETE

    def as_dict(self) -> dict[str, object]:
        return {
            "current": self.current.value,
            "complete": self.complete,
            "phases": [phase.value for phase in self.phases],
        }


__all__ = ["AutomationPhase", "AutomationTrace"]
