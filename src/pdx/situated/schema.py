"""处境行动内核的类型化生成期数据结构。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

UnknownPolicy = Literal["vanilla", "conservative", "lower_tier"]
EvidenceKind = Literal["boolean", "number", "ratio", "enum"]
EvidenceQuality = Literal["observed", "derived", "declared", "unknown"]
RelationKind = Literal["complements", "substitutes", "conflicts", "enables"]


@dataclass(frozen=True, slots=True)
class EvidenceSpec:
    id: str
    domain: str
    source: str
    scope: str
    kind: EvidenceKind
    unit: str
    refresh: Literal["consumer", "monthly", "shock"]
    unknown: UnknownPolicy
    trigger: str
    minimum: float | None = None
    maximum: float | None = None
    quality: EvidenceQuality = "observed"
    identity: str = ""

    def __post_init__(self) -> None:
        if not self.identity:
            object.__setattr__(self, "identity", self.id)
        for name, value in (("minimum", self.minimum), ("maximum", self.maximum)):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError(f"事实 {self.id} 的 {name} 边界必须是有限数")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"事实 {self.id} 的范围无效")


@dataclass(frozen=True, slots=True)
class EvidenceValue:
    spec_id: str
    value: object | None
    known: bool
    stale: bool = False
    provenance: str = ""


@dataclass(frozen=True, slots=True)
class StateVector:
    capacities: tuple[tuple[str, float | None], ...] = ()
    pressures: tuple[tuple[str, float | None], ...] = ()
    opportunities: tuple[tuple[str, float | None], ...] = ()
    commitments: tuple[tuple[str, float | None], ...] = ()
    shock: str | None = None
    route: str | None = None


@dataclass(frozen=True, slots=True)
class CostPredicate:
    """A typed pressure test; values retain their reader's unit until tiering."""

    fact: str
    op: Literal["=", "<", "<=", ">", ">="]
    value: bool | float
    unit: str


@dataclass(frozen=True, slots=True)
class RankTerm:
    """Observed demand benefit, measured in consumer delta units.

    An explicit evidence group takes its strongest known benefit only. Empty
    groups remain independent; tier is provenance, not an invented multiplier.
    """

    fact: str
    goal: str
    tier: int
    unit: str
    amount: float = 0.0
    evidence_group: str = ""
    origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fact, str)
            or not self.fact
            or not isinstance(self.goal, str)
            or not self.goal
            or type(self.tier) is not int
            or not 1 <= self.tier <= 2
            or self.unit != "flag"
            or type(self.amount) not in (int, float)
            or not math.isfinite(self.amount)
            or self.amount < 0
            or not isinstance(self.evidence_group, str)
            or (self.evidence_group and not re.fullmatch(r"[a-z][a-z0-9_]*", self.evidence_group))
            or not isinstance(self.origins, tuple)
            or any(not isinstance(origin, str) or not origin for origin in self.origins)
            or len(set(self.origins)) != len(self.origins)
            or (self.origins and not self.evidence_group)
        ):
            raise ValueError("RankTerm 必须绑定事实、目标与 1..2 的 flag 需求档")


@dataclass(frozen=True, slots=True)
class ActionCard:
    id: str
    domain: str
    consumer: str
    improves: tuple[str, ...]
    consumes: tuple[str, ...]
    requires_all: tuple[str, ...]
    requires_any: tuple[str, ...]
    blocked_by: tuple[str, ...]
    complements: tuple[str, ...]
    substitutes: tuple[str, ...]
    conflicts: tuple[str, ...]
    enables: tuple[str, ...]
    exit_when: tuple[str, ...]
    base: float
    stress: float
    opportunity: float
    commitment: float
    max_delta: float
    political_cost: float
    unknown_policy: UnknownPolicy
    explanation: str
    commitment_when: tuple[CostPredicate, ...] = ()
    political_when: tuple[CostPredicate, ...] = ()
    zero_cost_reason: str = ""
    rank_terms: tuple[RankTerm, ...] = ()
    variant_group: str = ""
    variant_priority: int = 0
    cause_group: str = ""
    commitment_cost_id: str = ""
    political_cost_id: str = ""
    cause_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.cause_origins, tuple)
            or any(not isinstance(origin, str) or not origin for origin in self.cause_origins)
            or len(set(self.cause_origins)) != len(self.cause_origins)
            or (self.cause_origins and not self.cause_group)
        ):
            raise ValueError("行动因果来源必须唯一且绑定cause_group")
        for value in (
            self.variant_group,
            self.cause_group,
            self.commitment_cost_id,
            self.political_cost_id,
        ):
            if not isinstance(value, str) or (
                value and not re.fullmatch(r"[a-z][a-z0-9_]*", value)
            ):
                raise ValueError("行动分组和共享成本必须使用小写 ID")
        if type(self.variant_priority) is not int or (
            self.variant_priority and not self.variant_group
        ):
            raise ValueError("variant_priority 必须是显式 variant_group 的整数优先级")


@dataclass(frozen=True, slots=True)
class Relation:
    source: str
    target: str
    kind: RelationKind
    strength: float
    scope: str = "root"
    condition_facts: tuple[str, ...] = ()
    unknown_policy: UnknownPolicy = "vanilla"
    cause_id: str = ""
    origins: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConsumerContract:
    id: str
    field: str
    domain: str
    max_delta: float
    budget: int
    vanilla_tail: str
    source: str = "situated"
    scope: str = "root"
    operation: Literal["add", "multiply"] = "add"
    owner: str = "situated_kernel"
