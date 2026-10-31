"""阶段收据和覆盖结果的机器可判定结构。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable  # noqa: TC003
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath, PureWindowsPath
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
    scope_status: str = "unverified"

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
            "scope_status": self.scope_status,
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


_HASH = re.compile(r"^[a-f0-9]{64}$")
_STATUSES = {"not_started", "in_progress", "verified", "blocked", "rejected"}


def validate_receipt(receipt: StageReceipt, *, strict: bool = False) -> tuple[str, ...]:
    """验证阶段收据的可复核身份，不把收据存在当成功能证明。"""

    problems: list[str] = []
    if not receipt.step_id or any(ch in receipt.step_id for ch in "\r\n"):
        problems.append("step_id")
    if receipt.status not in _STATUSES:
        problems.append("status")
    if not receipt.input_hashes or any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(value, str)
        or not _HASH.fullmatch(value)
        for key, value in receipt.input_hashes.items()
    ):
        problems.append("input_hashes")
    if not receipt.output_paths or any(
        not isinstance(item, str)
        or not item
        or PurePosixPath(item).is_absolute()
        or bool(PureWindowsPath(item).drive)
        or PureWindowsPath(item).is_absolute()
        or ".." in PurePosixPath(item.replace("\\", "/")).parts
        for item in receipt.output_paths
    ):
        problems.append("output_paths")
    if not receipt.evidence_ids or any(
        not isinstance(item, str) or not item for item in receipt.evidence_ids
    ):
        problems.append("evidence_ids")
    if not receipt.dependencies or any(
        not isinstance(item, str) or not item for item in receipt.dependencies
    ):
        problems.append("dependencies")
    if strict and receipt.status == "verified" and receipt.failures:
        raise ValueError("verified 收据不能包含 failures")
    return tuple(problems)


__all__ = ["AuditResult", "CoverageRow", "StageReceipt", "digest", "status_for", "validate_receipt"]
