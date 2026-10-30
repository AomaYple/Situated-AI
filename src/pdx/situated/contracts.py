"""行动内核的静态合同摘要。"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .schema import ActionCard, ConsumerContract, EvidenceSpec, Relation


def contract(
    facts: tuple[EvidenceSpec, ...],
    consumers: tuple[ConsumerContract, ...],
    actions: tuple[ActionCard, ...],
    relations: tuple[Relation, ...],
) -> dict[str, Any]:
    return {
        "schema": 1,
        "facts": [asdict(item) for item in facts],
        "consumers": [asdict(item) for item in consumers],
        "actions": [asdict(item) for item in actions],
        "relations": [asdict(item) for item in relations],
        "candidate_limit": len(actions),
        "relationship_depth": 2,
        "unknown_fallback": "vanilla",
        "behavior_quality": "user_long_term_review_pending",
    }
