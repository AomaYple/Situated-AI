"""Immutable historical identities, independent of the current production source.

The manifest was extracted from the published v3.0.1 commit, not reconstructed
from today's rules. It freezes identities and consumer contracts, not values:
intentional semantic repairs still require their own counterfactual receipts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .decision_ir import ConsumerIRBundle

DEFAULT_SOURCE = Path(__file__).resolve().parents[3] / "research/situated/v3.0.1-migration.json"
_MANIFEST_SHA256 = "fcce11e045e9933c13644a361da3a448330208c0b712ac3df615eed307aa55e6"
_COMMIT = "74492fc05321c0767cb07202a91797a7663e7ee0"
_FIELDS = ("source", "definition", "field", "actor", "target", "operation")


def validate_bundle(bundle: ConsumerIRBundle, *, path: Path = DEFAULT_SOURCE) -> None:
    """Reject lost historical identities even when today's total count is unchanged."""

    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _MANIFEST_SHA256:
        raise ValueError("历史迁移 manifest 原始字节漂移：v3.0.1")
    historical = json.loads(raw)
    if (
        historical["schema"] != 1
        or historical["tag"] != "v3.0.1"
        or historical["commit"] != _COMMIT
        or len(historical["rules"]) != 1401
        or len(historical["cards"]) != 7
    ):
        raise ValueError("历史迁移 manifest 身份无效：v3.0.1")
    current = {
        (writer.source, writer.definition): writer
        for writer in bundle.writers
        if writer.kind == "rule_action"
    }
    for row in historical["rules"]:
        identity = (row["source"], row["definition"])
        writer = current.get(identity)
        if writer is None:
            raise ValueError(f"历史迁移身份缺失：{identity}")
        if any(getattr(writer, field) != row[field] for field in _FIELDS):
            raise ValueError(f"历史迁移消费者合同漂移：{identity}")
    cards = {writer.definition: writer for writer in bundle.writers if writer.kind == "action_card"}
    for row in historical["cards"]:
        writer = cards.get(row["definition"])
        if writer is None:
            raise ValueError(f"历史显式卡身份缺失：{row['definition']}")
        if writer.field != row["field"] or writer.operation != row["operation"]:
            raise ValueError(f"历史显式卡消费者合同漂移：{row['definition']}")


__all__ = ["DEFAULT_SOURCE", "validate_bundle"]
