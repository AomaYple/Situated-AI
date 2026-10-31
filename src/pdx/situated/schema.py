"""处境行动内核的类型化生成期数据结构。"""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class Relation:
    source: str
    target: str
    kind: RelationKind
    strength: float
    scope: str = "root"
    condition_facts: tuple[str, ...] = ()
    unknown_policy: UnknownPolicy = "vanilla"


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
