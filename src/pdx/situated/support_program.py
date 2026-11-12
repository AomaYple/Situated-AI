"""Finite, typed continuous program for the native additive support consumer.

The reference and renderer consume these same immutable terms. The independent
PDX evaluator reads the rendered AST and never calls this reference evaluator.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from pdx import version_contracts

if TYPE_CHECKING:
    from pdx.decisions import Extensions


def _finite(value: object, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label)
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(label) from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(label)
    return number


@dataclass(frozen=True, slots=True)
class SupportResult:
    value: float
    reasons: tuple[str, ...]


def combine(
    market: float | None,
    security: tuple[tuple[str, float | None], ...],
    *,
    maximum: float = 50,
) -> SupportResult:
    """Skip unknown auxiliary terms, select one absolute defense cause, clamp once."""
    value = 0.0
    reasons: list[str] = []
    if market is not None:
        value = _finite(market, "市场支持贡献必须是有限数值或未知", -math.inf, math.inf)
        reasons.append("market")
    candidates: list[tuple[float, str]] = []
    for reason, amount in security:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("安全理由必须是非空字符串")
        if amount is not None:
            number = _finite(amount, "安全支持贡献必须是有限数值", -math.inf, math.inf)
            if number:
                candidates.append((number, reason))
    if candidates:
        amount, reason = max(candidates, key=lambda item: (abs(item[0]), item[1]))
        value += amount
        if reason not in reasons:
            reasons.append(reason)
    return SupportResult(max(-maximum, min(maximum, value)), tuple(reasons))


@dataclass(frozen=True, slots=True)
class EconomicDifference:
    multiplier: float
    country_getter: Literal["ROOT.economic_dependence(scope:country)"] = (
        "ROOT.economic_dependence(scope:country)"
    )
    enemy_getter: Literal["ROOT.economic_dependence(scope:enemy_country)"] = (
        "ROOT.economic_dependence(scope:enemy_country)"
    )
    description: str = "SITAI_MARKET_DEPENDENCE_SUPPORT_REASON"

    def __post_init__(self) -> None:
        _finite(self.multiplier, "市场倍率必须是0到10的有限数值", 0, 10)
        if (self.country_getter, self.enemy_getter) != (
            "ROOT.economic_dependence(scope:country)",
            "ROOT.economic_dependence(scope:enemy_country)",
        ):
            raise ValueError("未登记的经济依赖getter")


@dataclass(frozen=True, slots=True)
class DefenseReason:
    name: Literal["commitment", "neighbor"]
    amount: float
    query: Literal["sitai_defense_commitment", "sitai_neighbor_defense"]
    description: str

    def __post_init__(self) -> None:
        _finite(self.amount, "外部防御权重必须是 0 到 50 的有限数值", 0, 50)
        if (self.name, self.query) not in {
            ("commitment", "sitai_defense_commitment"),
            ("neighbor", "sitai_neighbor_defense"),
        }:
            raise ValueError("未登记的防御理由")


@dataclass(frozen=True, slots=True)
class SupportObservation:
    is_ai: bool | None = None
    has_sides: bool | None = None
    initiator: bool | None = None
    country_dependence: float | None = None
    enemy_dependence: float | None = None
    commitment: bool | None = None
    neighbor: bool | None = None

    def __post_init__(self) -> None:
        for value in (self.is_ai, self.has_sides, self.initiator, self.commitment, self.neighbor):
            if value is not None and type(value) is not bool:
                raise ValueError("支持事实必须是布尔或未知")
        for dependence in (self.country_dependence, self.enemy_dependence):
            if dependence is not None:
                _finite(dependence, "经济依赖必须是0到5的有限数值或未知", 0, 5)


@dataclass(frozen=True, slots=True)
class SupportProgram:
    market: EconomicDifference | None
    defense: tuple[DefenseReason, ...]
    consumer_max_delta: float = 50
    writer_id: str = "diplomatic_play_support_program"
    description: str = "SITAI_SUPPORT_BALANCE_REASON"

    def __post_init__(self) -> None:
        if self.consumer_max_delta != 50 or type(self.consumer_max_delta) is bool:
            raise ValueError("支持消费者限幅必须是50")
        if self.market is not None and not isinstance(self.market, EconomicDifference):
            raise ValueError("市场项必须是有类型的经济依赖差")
        if not isinstance(self.defense, tuple) or any(
            not isinstance(reason, DefenseReason) for reason in self.defense
        ):
            raise ValueError("防御组必须是有类型的理由")
        if len({reason.name for reason in self.defense}) != len(self.defense):
            raise ValueError("防御原因重复")

    @classmethod
    def from_extensions(cls, policy: Extensions) -> SupportProgram:
        if type(policy.market_enabled) is not bool or type(policy.security_enabled) is not bool:
            raise ValueError("支持模块开关必须是布尔")
        reasons = (
            DefenseReason(
                "commitment",
                policy.security_commitment_bonus,
                "sitai_defense_commitment",
                "SITAI_SECURITY_COMMITMENT_REASON",
            ),
            DefenseReason(
                "neighbor",
                policy.security_threat_bonus,
                "sitai_neighbor_defense",
                "SITAI_SECURITY_NEIGHBOR_REASON",
            ),
        )
        return cls(
            EconomicDifference(policy.market_multiplier) if policy.market_enabled else None,
            tuple(reason for reason in reasons if policy.security_enabled and reason.amount),
        )

    @property
    def enabled(self) -> bool:
        return self.market is not None or bool(self.defense)

    def as_dict(self) -> dict[str, object]:
        native_source = "research/vanilla-ai/1.14.5/00_default_strategy.txt:180-188"
        if version_contracts.is_115():
            from .compiler import support_evaluation_context  # noqa: PLC0415

            native_source = ";".join(support_evaluation_context().evidence)
        return {
            **asdict(self),
            "operation": "add",
            "cause_selection": "absolute_max_defense",
            "core_evidence": ["ROOT.is_ai", "scope:country", "scope:enemy_country"],
            "defense_direction": "target_positive_initiator_negative",
            "defense_partner": "country_if_target_enemy_country_if_initiator",
            "direction_fact": "exists = scope:is_initiator",
            "native_source": native_source,
            "unknown_policy": "core_vanilla_auxiliary_local",
            "single_clamp": True,
            "vanilla_tail": "preserve",
        }

    def evaluate(self, observation: SupportObservation) -> SupportResult:
        if observation.is_ai is not True or observation.has_sides is not True:
            return SupportResult(0, ())
        market = None
        if (
            self.market is not None
            and observation.country_dependence is not None
            and observation.enemy_dependence is not None
        ):
            market = (
                observation.country_dependence - observation.enemy_dependence
            ) * self.market.multiplier
        security: tuple[tuple[str, float | None], ...] = ()
        if observation.initiator is not None:
            sign = -1 if observation.initiator else 1
            security = tuple(
                (
                    reason.name,
                    sign * reason.amount if getattr(observation, reason.name) is True else None,
                )
                for reason in self.defense
            )
        return combine(market, security, maximum=self.consumer_max_delta)

    def render(self) -> str:
        if not self.enabled:
            return ""
        lines = [
            f"\t\t# ACTION {self.writer_id} [diplomacy];",
            "\t\tif = {",
            "\t\t\tlimit = { ROOT ?= { is_ai = yes } exists = scope:country exists = scope:enemy_country }",
            "\t\t\tadd = {",
            "\t\t\t\tvalue = 0",
            f"\t\t\t\tdesc = {self.description}",
        ]
        if self.market is not None:
            lines.extend(
                [
                    "\t\t\t\tadd = {",
                    f'\t\t\t\t\tvalue = "{self.market.country_getter}"',
                    f'\t\t\t\t\tsubtract = "{self.market.enemy_getter}"',
                    f"\t\t\t\t\tmultiply = {self.market.multiplier:g}",
                    f"\t\t\t\t\tdesc = {self.market.description}",
                    "\t\t\t\t}",
                ]
            )
        for initiator, partner, opponent, sign in (
            (False, "scope:country", "scope:enemy_country", 1),
            (True, "scope:enemy_country", "scope:country", -1),
        ):
            if not self.defense:
                break
            direction = "exists = scope:is_initiator"
            if not initiator:
                direction = f"NOT = {{ {direction} }}"
            lines.extend(["\t\t\t\tif = {", f"\t\t\t\t\tlimit = {{ {direction} }}"])
            for index, reason in enumerate(
                sorted(self.defense, key=lambda r: (r.amount, r.name), reverse=True)
            ):
                parameters = f"PARTNER = {partner}"
                if reason.name == "neighbor":
                    parameters += f" OPPONENT = {opponent}"
                branch = "if" if index == 0 else "else_if"
                lines.extend(
                    [
                        f"\t\t\t\t\t{branch} = {{",
                        f"\t\t\t\t\t\tlimit = {{ ROOT ?= {{ {reason.query} = {{ {parameters} }} }} }}",
                        f"\t\t\t\t\t\tadd = {{ value = {sign * reason.amount:g} desc = {reason.description} }}",
                        "\t\t\t\t\t}",
                    ]
                )
            lines.append("\t\t\t\t}")
        lines.extend(
            [
                f"\t\t\t\tmin = {-self.consumer_max_delta:g}",
                f"\t\t\t\tmax = {self.consumer_max_delta:g}",
                "\t\t\t}",
                "\t\t}",
            ]
        )
        return "\n".join(lines) + "\n"
