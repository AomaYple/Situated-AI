"""Previewable A4 reconciliation; preserve decisions and archive only stale evidence."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from tools.ci import a4_history
from tools.ci.a4_discovery import encoded
from tools.ci.a4_schema import RECEIPT, SCHEMA, check_shape, pending_row


def stale_closure(
    rows: list[dict[str, Any]], sources: Any, receipts: list[dict[str, Any]] | None = None
) -> set[str]:
    direct = set()
    stale_receipts = set()
    for receipt in receipts or []:
        try:
            reference = {**receipt, "kind": "file", "identity": "whole_file"}
            reference.pop("id")
            sources.verify(reference)
            accepted = sources.json(receipt["path"])
            check_shape(accepted, RECEIPT)
            if accepted["id"] != receipt["id"]:
                raise ValueError("receipt identity mismatch")
            sources.verify(accepted["junit"])
            for binding in accepted["bindings"]:
                sources.verify(binding)
        except (ValueError, OSError, KeyError):
            stale_receipts.add(receipt["id"])
    for row in rows:
        if any(witness["receipt_id"] in stale_receipts for witness in row["witnesses"]):
            direct.add(row["id"])
        refs = [
            *row["input_hashes"],
            *row["evidence_hashes"],
            *row["boundary_evidence"],
            *(proof["reference"] for proof in row["boundary_proofs"]),
        ]
        refs.extend(
            ref
            for binding in row["writer_bindings"]
            for key, ref in binding.items()
            if key in {"writer", "production", "consumer"}
        )
        try:
            for reference in refs:
                sources.verify(reference)
            for path in [*row["production_paths"], *row["witness_paths"], *row["source_paths"]]:
                sources.read(path)
        except (ValueError, OSError):
            direct.add(row["id"])
    changed = True
    while changed:
        before = len(direct)
        direct.update(row["id"] for row in rows if set(row["dependency_ids"]) & direct)
        changed = len(direct) != before
    return direct


def reconcile(
    data: dict[str, Any], root: Path, *, index: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    from tools.ci import a4_scope as gate  # noqa: PLC0415 - gate calls reconciliation via CLI.

    result = copy.deepcopy(data)
    result.update(schema=2)
    result.setdefault("pending_rows", [])
    result.setdefault("stale_history", [])
    sources = gate.Sources(
        root, {gate.DISCOVERY_INDEX: encoded(index) + b"\n"} if index is not None else None
    )
    original, old = gate.original_a3(sources)
    delta = gate.changes(root)
    discovered = gate.discover(sources, old, delta)
    refs, reports, catalogs = gate.load_investigations(sources, result["freeze"]["target_version"])
    discovered.extend(item for report in reports for item in report["discoveries"])
    expected = gate.unique(discovered, "id", "discovery")
    previous = gate.unique(result["discoveries"], "id", "discovery")
    if set(previous) - set(expected):
        raise ValueError("reconcile refuses to drop a historical discovery")
    rows = gate.expanded_rows(result)
    stale = stale_closure(rows, sources, result["receipts"])
    changed_discoveries = {
        identity for identity in previous if previous[identity] != expected[identity]
    }
    stale.update(
        row["id"] for row in rows if changed_discoveries.intersection(row["discovery_ids"])
    )
    # Discovery changes also invalidate dependent evidence transitively.
    while True:
        expanded = stale | {row["id"] for row in rows if stale.intersection(row["dependency_ids"])}
        if expanded == stale:
            break
        stale = expanded
    for row in result["rows"]:
        if row["id"] not in stale:
            continue
        result["stale_history"].append(
            {
                "row": copy.deepcopy(row),
                "reason": "direct input/discovery or transitive dependency identity drift",
            }
        )
        row.update(
            obligation_status="pending",
            interface_status="changed",
            failure_reason="输入/发现或传递依赖变化；保留处置决定与历史证据，待重验。",
        )
        for key in (
            "evidence_hashes",
            "boundary_evidence",
            "boundary_proofs",
            "writer_bindings",
            "witnesses",
        ):
            row[key] = []
        row["input_hashes"] = [expected[identity]["source"] for identity in row["discovery_ids"]]
        row["source_paths"] = sorted({ref["path"] for ref in row["input_hashes"]})
        row["production_paths"] = [
            path for path in row["production_paths"] if (root / path).is_file()
        ]
        row["witness_paths"] = [path for path in row["witness_paths"] if (root / path).is_file()]
    covered = {identity for row in rows for identity in row["discovery_ids"]}
    result["rows"].extend(
        pending_row(item, result["freeze"]["target_version"])
        for item in discovered
        if item["id"] not in covered and item["origin"] != "native_projection"
    )
    known_groups = {row["domain"] for row in rows}
    result["pending_rows"].extend(
        item
        for item in gate.compact_pending(catalogs, discovered)
        if item["domain"] not in known_groups
    )
    # Refresh compact members by canonical ID without erasing explicit rows or decisions.
    compact = {item["domain"]: item for item in gate.compact_pending(catalogs, discovered)}
    result["pending_rows"] = [compact[item["domain"]] for item in result["pending_rows"]]
    result["discoveries"] = discovered
    old_by_id = {item["id"]: item for item in old}
    for row in result["rows"]:
        stages = {
            gate.responsibility_stage(expected[identity], old_by_id)[0]
            for identity in row["discovery_ids"]
        }
        if len(stages) != 1:
            raise ValueError("reconcile requires a split for mixed strategic responsibilities")
        row["stage"] = stages.pop()
    existing_changes = gate.unique(result["candidate_changes"], "id", "candidate")
    result["candidate_changes"] = []
    for item in delta:
        previous_change = existing_changes.get(item["id"], {})
        result["candidate_changes"].append(
            {
                **item,
                "decision": previous_change.get("decision", "reverify"),
                "row_ids": previous_change.get("row_ids", [f"O:D:candidate:{item['id']}"]),
                "reason": previous_change.get("reason", "新增生产变更，待独立迁移/目标重验。"),
            }
        )
    result["inventory"]["investigation_sources"] = refs
    gate.merge_inventory(result, reports)
    if sources.jsons.get("a4:classification-checkpoint"):
        result["inventory"].update(
            status="verified",
            reason="完整原始观察永久保留；当前物理分类/角色映射/6193生产IR与17迁移静态子合同独立核验通过。未来接口、B/R/U产品及DLC应用问题仍逐责任pending，不授予新writer权限。",
        )
    result["inventory"]["crosscheck_receipts"] = sorted(
        {identity for report in reports for identity in report["crosscheck_receipt_ids"]}
    )
    inputs = {
        gate.MANIFEST,
        gate.SNAPSHOT,
        gate.SUMMARY,
        gate.DISCOVERY_INDEX,
        original["path"],
        a4_history.HISTORY_PATH,
        *gate.production_paths(root),
        *gate.GATE_INPUTS,
    }
    result["freeze"]["inputs"] = [sources.reference(path) for path in sorted(inputs)]
    result["freeze"]["plan_inputs"] = [sources.reference(path) for path in gate.PLANS]
    check_shape(result, SCHEMA)
    return result, {
        "added_discoveries": sorted(set(expected) - set(previous)),
        "stale_rows": sorted(stale),
        "preserved_discoveries": len(previous),
        "preserved_migrations": len(result["migrations"]),
    }


def publish(root: Path, data: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete overlay before any root switch; a split root always fails closed."""
    from tools.ci import a4_scope as gate  # noqa: PLC0415 - gate calls reconciliation via CLI.

    index_raw = encoded(index) + b"\n"
    ledger_raw = encoded(data) + b"\n"
    if max(len(index_raw), len(ledger_raw)) >= 64 * 1024 * 1024:
        raise ValueError("registration root size budget")
    targets = (gate.DISCOVERY_INDEX, gate.LEDGER)
    preimages = {path: (root / path).read_bytes() for path in targets}
    checked = gate.validate(
        data, root, stage="A4-0", source_overrides={gate.DISCOVERY_INDEX: index_raw}
    )
    if any((root / path).read_bytes() != raw for path, raw in preimages.items()):
        raise ValueError("registration preimage changed during preview")
    # Immutable input files are rechecked immediately before switching acceptance roots.
    sources = gate.Sources(root, {gate.DISCOVERY_INDEX: index_raw})
    for reference in [*data["freeze"]["inputs"], *data["freeze"]["plan_inputs"]]:
        sources.verify(reference)
    for reference in data["inventory"]["investigation_sources"]:
        sources.verify(reference)
        for member in sources.json(reference["path"])["source_inputs"]:
            sources.verify(member)
    for path, raw in ((targets[0], index_raw), (targets[1], ledger_raw)):
        staged = root / "tools/out/a4-task7-transaction" / Path(path).name
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(raw)
        staged.replace(root / path)
    return checked
