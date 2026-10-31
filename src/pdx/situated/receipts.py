"""阶段收据和覆盖结果的机器可判定结构。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable  # noqa: TC003
from dataclasses import asdict, dataclass
from typing import Any, Literal

ReceiptStatus = Literal["not_started", "in_progress", "verified", "blocked", "rejected"]


@dataclass(frozen=True, slots=True)
class StageReceipt:
    step_id: str
    status: ReceiptStatus
    input_hashes: dict[str, str]
    output_paths: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    failures: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CoverageRow:
    surface_id: str
    disposition: str
    owner: str
    evidence_ids: tuple[str, ...]
    source: str
    status: str
    family_id: str = ""
    consumer_id: str = ""
    evidence_state: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AuditResult:
    plan_version: str
    status: str
    pending: tuple[str, ...]
    blocked: tuple[str, ...]
    unclassified: tuple[str, ...]
    rows: tuple[CoverageRow, ...]
    receipts: tuple[StageReceipt, ...]
    scope_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "plan_version": self.plan_version,
            "status": self.status,
            "pending": list(self.pending),
            "blocked": list(self.blocked),
            "unclassified": list(self.unclassified),
            "rows": [row.as_dict() for row in self.rows],
            "receipts": [receipt.as_dict() for receipt in self.receipts],
            "scope_hash": self.scope_hash,
        }


def digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def status_for(rows: Iterable[CoverageRow]) -> str:
    values = tuple(rows)
    if any(row.status == "blocked" for row in values):
        return "blocked"
    if any(row.status != "implemented" for row in values):
        return "incomplete"
    return "complete"


__all__ = ["AuditResult", "CoverageRow", "StageReceipt", "digest", "status_for"]
