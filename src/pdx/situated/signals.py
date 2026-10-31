"""K2 类型化处境信号。

信号是生成期与参考器共享的最小状态合同。每个信号保留来源、单位、
作用域、未知/过期状态和派生表达式；消费者不能把不同单位压成一个
没有来源的万能分数。游戏运行期只接收由编译器降低后的有限脚本。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Literal

SignalKind = Literal["capacity", "need", "opportunity", "commitment"]
SignalScope = Literal["country", "target_country", "state", "market", "diplomatic"]
SignalQuality = Literal["observed", "derived", "declared", "unknown"]


@dataclass(frozen=True, slots=True)
class Signal:
    """一个有界、可追溯的状态信号。"""

    id: str
    source: str
    unit: str
    scope: SignalScope
    value: object | None
    known: bool
    stale: bool = False
    quality: SignalQuality = "derived"
    expression: str = ""
    source_facts: tuple[str, ...] = ()
    bindings: tuple[str, ...] = ()
    kind: ClassVar[SignalKind] = "capacity"

    def __post_init__(self) -> None:
        if not self.id or not self.source or not self.unit or not self.expression:
            raise ValueError("信号必须有 id、source、unit 和 expression")
        if self.scope not in {"country", "target_country", "state", "market", "diplomatic"}:
            raise ValueError(f"信号作用域无效：{self.scope}")
        if self.quality not in {"observed", "derived", "declared", "unknown"}:
            raise ValueError(f"信号质量无效：{self.quality}")
        if type(self.known) is not bool or type(self.stale) is not bool:
            raise ValueError("信号 known/stale 必须是布尔值")
        if not self.known and self.value is not None:
            raise ValueError("未知信号不能携带 value")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("信号数值必须有限")
        if any(not item or not isinstance(item, str) for item in self.source_facts):
            raise ValueError("信号 source_facts 必须是非空字符串")
        if any(not item or not isinstance(item, str) for item in self.bindings):
            raise ValueError("信号 bindings 必须是非空字符串")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind
        return payload


@dataclass(frozen=True, slots=True)
class CapacitySignal(Signal):
    kind: ClassVar[SignalKind] = "capacity"


@dataclass(frozen=True, slots=True)
class NeedSignal(Signal):
    kind: ClassVar[SignalKind] = "need"


@dataclass(frozen=True, slots=True)
class OpportunitySignal(Signal):
    kind: ClassVar[SignalKind] = "opportunity"


@dataclass(frozen=True, slots=True)
class CommitmentSignal(Signal):
    kind: ClassVar[SignalKind] = "commitment"


@dataclass(frozen=True, slots=True)
class TypedState:
    """四类信号的有界快照。"""

    capacities: tuple[CapacitySignal, ...] = ()
    needs: tuple[NeedSignal, ...] = ()
    opportunities: tuple[OpportunitySignal, ...] = ()
    commitments: tuple[CommitmentSignal, ...] = ()

    def all(self) -> tuple[Signal, ...]:
        return (*self.capacities, *self.needs, *self.opportunities, *self.commitments)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "signals": [item.as_dict() for item in self.all()],
            "counts": {
                "capacity": len(self.capacities),
                "need": len(self.needs),
                "opportunity": len(self.opportunities),
                "commitment": len(self.commitments),
            },
            "unknown_policy": "unknown_never_inferred_false",
        }


def contract(state: TypedState) -> dict[str, Any]:
    """导出 K2/K5 使用的类型化状态表达式合同。"""

    return state.as_dict()


__all__ = [
    "CapacitySignal",
    "CommitmentSignal",
    "NeedSignal",
    "OpportunitySignal",
    "Signal",
    "TypedState",
    "contract",
]
