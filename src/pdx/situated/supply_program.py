"""Typed goods-stance appends and reviewed unions, with no numeric-score credit.

The 1.15.1 default source lines 6493-6494 call these production/trade planning
stances and allow an active strategy to override them. The three pinned unions
intentionally extend local stance activation. They retain native execution gates,
produce one enum when both causes hold, and authorize no general eligibility OR.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from pdx import version_contracts
from pdx.lexer import ATOM, LBRACE, OP, RBRACE, tokenize
from pdx.parser import parse_text

SOURCE = "common/ai_strategies/00_default_strategy.txt"
PARENT = "ai_strategy_default.goods_stances"
_NATIVE_1151_SHA256 = "38e7aadd1be9465f3ab423f61fa8e9e8206b8d98f523979e8e43c42cc18753ba"
_NATIVE_STANCE_1151 = {
    "oil": "65004debc1e9f77a72c8b98b14ea63a31a471dbfdbbb87a061e5109af35b36d6",
    "radios": "bfbaf4ef8b19d20076baf6b80236ce7a365dd16e9f2a6b33db0ba7c5a5832eaf",
    "telephones": "daa1caeaf0572bf508a1338527047d41a3187706db1610723a989ed60e48408a",
}


def block_span(text: str, path: tuple[str, ...]) -> tuple[int, int]:
    """Find one exact lexical block, retaining all original whitespace/comments."""
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    stack: list[str] = []
    openings: list[int] = []
    found = []
    previous = before_previous = None
    for token in tokenize(text):
        if token.kind == LBRACE:
            key = (
                before_previous.value
                if previous is not None
                and previous.kind == OP
                and before_previous is not None
                and before_previous.kind == ATOM
                else "<anonymous>"
            )
            stack.append(key)
            openings.append(starts[token.line - 1] + token.col - 1)
        elif token.kind == RBRACE:
            if tuple(stack) == path:
                found.append((openings[-1], starts[token.line - 1] + token.col))
            stack.pop()
            openings.pop()
        before_previous, previous = previous, token
    if len(found) != 1:
        raise ValueError("供给立场必须有唯一精确原版块")
    return found[0]


@dataclass(frozen=True, slots=True)
class NativeSupplyStance:
    """Only the three independently pinned 1.15.1 preference activations."""

    good: str
    body: str

    def __post_init__(self) -> None:
        if hashlib.sha256(self.body.encode()).hexdigest() != _NATIVE_STANCE_1151.get(self.good):
            raise ValueError("供给立场原版身份漂移；只允许精确1.15.1三商品")

    def compose(self, scarcity: str) -> str:
        start, end = block_span(self.body, ("<anonymous>", "trigger"))
        original = self.body[start:end]
        # The complete original trigger body is the first AND, byte for byte.
        # This extends this local planning preference's activation only; it is
        # no permission to OR an arbitrary construction/trade execution gate.
        return (
            self.body[:start]
            + "{ OR = { AND = "
            + original
            + " AND = { "
            + scarcity
            + " } } }"
            + self.body[end:]
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "game_version": "1.15.1",
            "source": SOURCE,
            "source_sha256": _NATIVE_1151_SHA256,
            "body_sha256": _NATIVE_STANCE_1151[self.good],
            "native_trigger": "first AND retains the complete original body bytes and AST",
            "meaning": "local production/trade stance activation, not action execution eligibility",
            "scope_limit": "only oil, radios and telephones in this exact native source",
        }


def native_stances_1151() -> tuple[NativeSupplyStance, ...]:
    """Load reviewed raw evidence, never rediscover a native-policy permission."""
    if version_contracts.active_version() != "1.15.1":
        raise ValueError("合成供给立场仅支持精确1.15.1")
    path = Path(__file__).resolve().parents[3] / "research/vanilla-ai/1.15.1/native/game" / SOURCE
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _NATIVE_1151_SHA256:
        raise ValueError("供给立场冻结原件漂移")
    text = raw.decode("utf-8-sig")
    result = []
    for good in sorted(_NATIVE_STANCE_1151):
        start, end = block_span(text, ("ai_strategy_default", "goods_stances", good))
        result.append(NativeSupplyStance(good, text[start:end]))
    return tuple(result)


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
    native_stance: NativeSupplyStance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, SupplyAction):
            raise ValueError("供给程序必须携带有类型的具体商品行动")
        if self.native_stance is not None and (
            type(self.native_stance) is not NativeSupplyStance
            or self.native_stance.good != self.good
        ):
            raise ValueError("供给合成程序缺少精确原版商品身份")

    @property
    def operation(self) -> str:
        return "append" if self.native_stance is None else "idempotent_or"

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
        native_active: bool | None = None,
    ) -> str | None:
        """Evaluate the full stance as native OR guarded AI scarcity.

        ``native_active=None`` means unknown native activation. It never invents
        a native benefit; an observed scarcity can still prove the union true.
        Otherwise None reports no proven stance, not proven native inactivity.
        Disabling removes only our cause and preserves any known native truth.
        """
        if native_active is not None and type(native_active) is not bool:
            raise ValueError("原版立场观测必须为bool或unknown")
        if self.native_stance is not None and native_active is True:
            return "wants_high_supply"
        return self.action.evaluate(
            is_ai=is_ai,
            price=price,
            delta=delta,
            market_present=market_present,
            good_present=good_present,
            enabled=enabled,
        )

    def render(self) -> str:
        if self.native_stance is None:
            return self.action.render()
        return f"\t\t{self.good} = " + self.composed_body() + "\n"

    def scarcity_trigger(self) -> str:
        parsed = parse_text(self.action.render())
        if parsed.errors:
            raise ValueError("供给原有稀缺程序无法解析")
        start, end = block_span(self.action.render(), (self.good, "trigger"))
        return self.action.render()[start + 1 : end - 1]

    def composed_body(self) -> str:
        if self.native_stance is None:
            raise ValueError("追加程序没有原版立场合成体")
        return self.native_stance.compose(self.scarcity_trigger())

    def as_dict(self) -> dict[str, object]:
        return {
            "action": asdict(self.action),
            "writer_id": self.writer_id,
            "consumer_id": self.consumer_id,
            "field": self.field,
            "value_kind": "enum",
            "operation": self.operation,
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
            **(
                {
                    "native_stance": self.native_stance.as_dict(),
                    "combination": "native_trigger OR AI_scarcity; one stance value; overlapping causes are idempotent",
                    "player_boundary": "exact native trigger truth value; scarcity branch requires is_ai",
                    "disable": "restore exact native body; no own enum contribution",
                }
                if self.native_stance is not None
                else {}
            ),
        }
