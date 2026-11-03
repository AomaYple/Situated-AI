"""Typed native goods-stance append programs, with no numeric-score projection."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

SOURCE = "common/ai_strategies/00_default_strategy.txt"
PARENT = "ai_strategy_default.goods_stances"


def _number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True, slots=True)
class SupplyAction:
    """One concrete good's existing scarcity-triggered native stance choice."""

    source: str
    good: str
    price_threshold: float

    def __post_init__(self) -> None:
        if (
            self.source != SOURCE
            or not isinstance(self.good, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]*", self.good)
        ):
            raise ValueError("供给行动必须有精确原版来源和商品身份")
        if not _number(self.price_threshold) or not 0 < self.price_threshold <= 0.75:
            raise ValueError("供给行动价格阈值必须是有界有限数值")

    @property
    def field(self) -> str:
        return f"{PARENT}.{self.good}"

    def evaluate(
        self,
        *,
        is_ai: bool | None,
        price: float | None,
        delta: float | None,
        market_present: bool | None = True,
        good_present: bool | None = True,
        enabled: bool = True,
    ) -> str | None:
        """Return only the appended enum; missing core facts preserve native stances."""
        if (
            enabled is not True
            or is_ai is not True
            or market_present is not True
            or good_present is not True
            or not _number(price)
            or not _number(delta)
        ):
            return None
        assert price is not None
        assert delta is not None
        return "wants_high_supply" if price > self.price_threshold and delta < 0 else None

    def render(self) -> str:
        return (
            f"\t\t{self.good} = {{ stance = wants_high_supply trigger = {{ "
            f"is_ai = yes exists = market market = {{ exists = mg:{self.good} "
            f"mg:{self.good} = {{ market_goods_pricier > {self.price_threshold!r} "
            "market_goods_delta < 0 } } } }\n"
        )


@dataclass(frozen=True, slots=True)
class SupplyProgram:
    """The immutable instance shared by ConsumerIR, reference, render and contract."""

    action: SupplyAction

    def __post_init__(self) -> None:
        if not isinstance(self.action, SupplyAction):
            raise ValueError("供给程序必须携带有类型的具体商品行动")

    @property
    def source(self) -> str:
        return self.action.source

    @property
    def good(self) -> str:
        return self.action.good

    @property
    def price_threshold(self) -> float:
        return self.action.price_threshold

    @property
    def field(self) -> str:
        return self.action.field

    @property
    def writer_id(self) -> str:
        return f"supply_{self.good}"

    @property
    def consumer_id(self) -> str:
        return f"goods_stances.{self.good}"

    def evaluate(
        self,
        *,
        is_ai: bool | None,
        price: float | None,
        delta: float | None,
        market_present: bool | None = True,
        good_present: bool | None = True,
        enabled: bool = True,
    ) -> str | None:
        return self.action.evaluate(
            is_ai=is_ai,
            price=price,
            delta=delta,
            market_present=market_present,
            good_present=good_present,
            enabled=enabled,
        )

    def render(self) -> str:
        return self.action.render()

    def as_dict(self) -> dict[str, object]:
        return {
            "action": asdict(self.action),
            "writer_id": self.writer_id,
            "consumer_id": self.consumer_id,
            "field": self.field,
            "value_kind": "enum",
            "operation": "append",
            "stance": "wants_high_supply",
            "actor": "root",
            "target": "market_goods",
            "reader_path": ["market", f"mg:{self.good}"],
            "core_evidence": [
                "is_ai",
                "exists = market",
                f"exists = mg:{self.good}",
                "market_goods_pricier",
                "market_goods_delta",
            ],
            "unknown_policy": "local_no_append_preserve_native",
            "vanilla_tail": "preserve",
            "forced_trade": False,
        }
