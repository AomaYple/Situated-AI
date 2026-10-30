"""把静态仲裁结果格式化为可追溯的解释记录。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .arbitration import ArbitrationResult


def record(result: ArbitrationResult) -> dict[str, object]:
    return {
        "action_id": result.action_id,
        "delta": result.delta,
        "reason_codes": list(result.reason_codes),
        "evidence_ids": list(result.evidence_ids),
        "fallback": result.fallback,
        "evidence": "simulation",
        "behavior_quality": "user_long_term_review_pending",
    }
