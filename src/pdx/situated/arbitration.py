"""确定性、有限候选的行动仲裁参考实现。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import EvidenceValue


@dataclass(frozen=True, slots=True)
class Candidate:
    action_id: str
    crisis_protection: float = 0.0
    bottleneck_relief: float = 0.0
    capability_gain: float = 0.0
    feasibility: float = 0.0
    substitute_availability: float = 0.0
    opportunity_value: float = 0.0
    commitment_cost: float = 0.0
    political_cost: float = 0.0
    inertia: float = 0.0
    base_delta: float = 0.0


@dataclass(frozen=True, slots=True)
class ArbitrationResult:
    action_id: str | None
    delta: float
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    fallback: str


def choose(
    candidates: tuple[Candidate, ...], *, max_delta: float, evidence: tuple[EvidenceValue, ...] = ()
) -> ArbitrationResult:
    """按固定词典序选择一个行动；未知证据或空集合回退原版。"""

    if not math.isfinite(max_delta) or max_delta <= 0:
        raise ValueError("仲裁 max_delta 必须为正有限数")
    for candidate in candidates:
        values = (
            candidate.crisis_protection,
            candidate.bottleneck_relief,
            candidate.capability_gain,
            candidate.feasibility,
            candidate.substitute_availability,
            candidate.opportunity_value,
            candidate.commitment_cost,
            candidate.political_cost,
            candidate.inertia,
            candidate.base_delta,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError(f"行动 {candidate.action_id} 含非有限仲裁值")
    if not candidates or any(not candidate.action_id for candidate in candidates):
        return ArbitrationResult(
            None, 0.0, (), tuple(item.spec_id for item in evidence if item.known), "vanilla"
        )

    def cost_adjusted_feasibility(item: Candidate) -> float:
        """把承诺/政治成本提前纳入可行档，而不是只作同分 tie-break。"""

        return item.feasibility - item.commitment_cost - item.political_cost

    ranked = sorted(
        candidates,
        key=lambda item: (
            -item.crisis_protection,
            -item.bottleneck_relief,
            -item.capability_gain,
            -cost_adjusted_feasibility(item),
            -item.substitute_availability,
            -(item.opportunity_value - item.commitment_cost - item.political_cost),
            -item.inertia,
            item.action_id,
        ),
    )
    chosen = ranked[0]
    raw = (
        chosen.crisis_protection
        + chosen.bottleneck_relief
        + chosen.capability_gain
        + 0.25 * max(0.0, chosen.feasibility)
        + 0.25 * max(0.0, chosen.opportunity_value)
        - 0.5 * max(0.0, chosen.commitment_cost)
        - 0.5 * max(0.0, chosen.political_cost)
        + chosen.base_delta
    )
    delta = max(-max_delta, min(max_delta, raw))
    reasons = tuple(
        code
        for code, value in (
            ("crisis_protection", chosen.crisis_protection),
            ("bottleneck_relief", chosen.bottleneck_relief),
            ("capability_gain", chosen.capability_gain),
            ("feasibility", chosen.feasibility),
            ("opportunity_value", chosen.opportunity_value),
            ("commitment_cost", -chosen.commitment_cost),
            ("political_cost", -chosen.political_cost),
            ("base_delta", chosen.base_delta),
        )
        if value != 0
    )
    return ArbitrationResult(
        chosen.action_id,
        delta,
        reasons,
        tuple(item.spec_id for item in evidence if item.known),
        "selected",
    )
