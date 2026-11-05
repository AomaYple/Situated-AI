"""Single strict schema for A4 bootstrap and validation (standard library only)."""

from __future__ import annotations

from typing import Any

TEXT = "text"
HASH = "sha256"
STRINGS = [TEXT]
REFERENCE = {"path": TEXT, "sha256": HASH, "identity": TEXT, "kind": {"file", "python", "json"}}
VALUE = {"status": {"pending", "applicable", "not_applicable"}, "reason": TEXT, "value": TEXT}
COVERAGE = {
    "status": {"pending", "applicable", "not_applicable"},
    "reason": TEXT,
    "case_ids": STRINGS,
}
DIMENSIONS = (
    "base_game",
    "dlc",
    "disabled",
    "unknown",
    "object",
    "role",
    "threshold",
    "lifecycle",
    *(f"U{number:02}" for number in range(1, 11)),
)
ROW: dict[str, Any] = {
    "id": TEXT,
    "goal_ids": STRINGS,
    "kind": {"discovery", "obligation", "relation", "u_unit"},
    "stage": {f"A4-{number}" for number in range(1, 8)},
    "discovery_ids": STRINGS,
    "domain": TEXT,
    "relation": VALUE,
    "source_version": TEXT,
    "source_paths": STRINGS,
    "input_hashes": [REFERENCE],
    "object": VALUE,
    "scope": VALUE,
    "role": VALUE,
    "consumer": VALUE,
    "disposition": {"implement", "retain_native", "unsupported"},
    "interface_status": {
        "discovered",
        "verified",
        "changed",
        "boundary_unknown",
        "native_handled",
        "unsupported",
    },
    "obligation_status": {
        "pending",
        "in_progress",
        "implemented",
        "verified",
        "retained",
        "blocked",
    },
    "disposition_reason": TEXT,
    "evidence_level": {"static_check", "snapshot", "simulation", "runtime", "inference"},
    "fact_ids": STRINGS,
    "port_ids": STRINGS,
    "causal_ids": STRINGS,
    **dict.fromkeys(
        (
            "qualification",
            "unit",
            "direction",
            "timing",
            "benefit",
            "cost",
            "opportunity_cost",
            "risk",
            "alternative",
            "unknown_policy",
            "saturation",
            "persistence",
            "exit",
        ),
        VALUE,
    ),
    "applicability": dict.fromkeys(DIMENSIONS, COVERAGE),
    "configurations": [{"id": TEXT, "dlc_ids": STRINGS, "enabled": "bool", "case_ids": STRINGS}],
    "case_ids": STRINGS,
    "production_paths": STRINGS,
    "witness_paths": STRINGS,
    "evidence_hashes": [REFERENCE],
    "boundary_evidence": [REFERENCE],
    "boundary_proofs": [
        {
            "role": {
                "native_source",
                "parent_structure",
                "reference_closure",
                "disabled_path",
                "interface_boundary",
            },
            "reference": REFERENCE,
        }
    ],
    "writer_bindings": [
        {
            "writer": REFERENCE,
            "production": REFERENCE,
            "consumer": REFERENCE,
            "object": TEXT,
            "fact_ids": STRINGS,
            "port_ids": STRINGS,
            "witness_ids": STRINGS,
        }
    ],
    "witnesses": [{"node_id": TEXT, "case_ids": STRINGS, "receipt_id": TEXT}],
    "dependency_ids": STRINGS,
    "predecessor_ids": STRINGS,
    "failure_reason": TEXT,
}
DISCOVERY = {
    "id": TEXT,
    "kind": {"discovery"},
    "origin": TEXT,
    "identity": TEXT,
    "source": REFERENCE,
    "goal_ids": STRINGS,
}
REGISTRY = {"id": TEXT, "source": REFERENCE, "object": TEXT, "scope": TEXT, "unit": TEXT}
INVESTIGATION = {
    "schema": {1},
    "source_version": TEXT,
    "source_inputs": [REFERENCE],
    "scanned_directories": STRINGS,
    "parse_failures": STRINGS,
    "unrecognized": STRINGS,
    "duplicates": STRINGS,
    "discoveries": [DISCOVERY],
    "dlc_ids": STRINGS,
    "writer_ids": STRINGS,
    "consumer_ids": STRINGS,
    "crosscheck_receipt_ids": STRINGS,
}
CHANGE = {
    "id": TEXT,
    "path": TEXT,
    "checkpoint": {"presence": {"present", "absent"}, "hashes": [HASH]},
    "current": {"presence": {"present", "absent"}, "hashes": [HASH]},
    "decision": {"migrate", "reverify", "retain", "replace", "withdraw"},
    "row_ids": STRINGS,
    "reason": TEXT,
    "diff_sha256": HASH,
}
SCHEMA: dict[str, Any] = {
    "schema": {2},
    "plan": {"A4"},
    "freeze": {
        "target_version": TEXT,
        "plan_inputs": [REFERENCE],
        "inputs": [REFERENCE],
        "a3_original": REFERENCE,
        "candidate_commit": TEXT,
        "production_base": TEXT,
        "installation": {
            "root": TEXT,
            "version": [{"key": TEXT, "value": TEXT}],
            "exe_sha256": HASH,
            "steam_manifest_sha256": HASH,
            "steam_buildid": TEXT,
            "jomini_revision": TEXT,
            "trees": [{"path": TEXT, "count": "int", "sha256": HASH}],
        },
    },
    "inventory": {
        "stage": {"A4-1"},
        "status": {"pending", "verified"},
        "reason": TEXT,
        "scanned_directories": STRINGS,
        "parse_failures": STRINGS,
        "unrecognized": STRINGS,
        "duplicates": STRINGS,
        "crosscheck_receipts": STRINGS,
        "dlc_ids": STRINGS,
        "investigation_sources": [REFERENCE],
    },
    "discoveries": [DISCOVERY],
    "rows": [ROW],
    "pending_rows": [
        {"domain": TEXT, "discovery_ids": STRINGS, "goal_ids": STRINGS, "source": REFERENCE}
    ],
    "stale_history": [{"row": ROW, "reason": TEXT}],
    "migrations": [
        {
            "old_id": TEXT,
            "old_status": TEXT,
            "old_row_sha256": HASH,
            "original_sha256": HASH,
            "decision": {"migrate", "reverify", "retain", "replace", "withdraw"},
            "row_ids": STRINGS,
            "reason": TEXT,
        }
    ],
    "candidate_changes": [CHANGE],
    "receipts": [{"id": TEXT, "path": TEXT, "sha256": HASH}],
    "facts": [REGISTRY],
    "ports": [REGISTRY],
    "causes": [REGISTRY],
}
RECEIPT = {
    "schema": {1},
    "id": TEXT,
    "command": STRINGS,
    "selection": STRINGS,
    "exit_code": "int",
    "junit": REFERENCE,
    "bindings": [REFERENCE],
    "passed": STRINGS,
    "failed": STRINGS,
}


def check_shape(value: Any, schema: Any, location: str = "$", *, allow_empty: bool = False) -> None:
    """Reject unknown/missing fields and implicit coercions at every schema level."""
    if isinstance(schema, dict):
        if not isinstance(value, dict) or set(value) != set(schema):
            raise ValueError(f"schema fields at {location}: expected {sorted(schema)}")
        for key, child in schema.items():
            check_shape(value[key], child, f"{location}.{key}")
    elif isinstance(schema, list):
        if not isinstance(value, list):
            raise ValueError(f"schema list at {location}")
        for index, item in enumerate(value):
            check_shape(item, schema[0], f"{location}[{index}]")
    elif isinstance(schema, set):
        if type(value) not in (int, str) or value not in schema:
            raise ValueError(f"schema enum at {location}: {value!r}")
    elif schema in (TEXT, HASH):
        if not isinstance(value, str) or (not allow_empty and not value.strip()):
            raise ValueError(f"schema text at {location}")
        if schema == HASH and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError(f"schema hash at {location}")
    elif schema == "bool":
        if type(value) is not bool:
            raise ValueError(f"schema bool at {location}")
    elif schema == "int":
        if type(value) is not int:
            raise ValueError(f"schema int at {location}")
    else:
        raise ValueError(f"unknown schema type: {schema}")


def pending_value(reason: str) -> dict[str, str]:
    return {"status": "pending", "reason": reason, "value": "pending"}


def pending_row(discovery: dict[str, Any], version: str) -> dict[str, Any]:
    """Populate the one shared row schema without fake zero or completion evidence."""
    reason = f"A4-1调查待办：{discovery['origin']} / {discovery['identity']}；旧来源未重验，不继承完成状态。"
    row: dict[str, Any] = {}
    for key, field in ROW.items():
        if isinstance(field, list):
            row[key] = []
        elif field == VALUE:
            row[key] = pending_value(reason)
    row.update(
        id=f"O:{discovery['id']}",
        goal_ids=discovery["goal_ids"],
        kind="relation"
        if discovery["origin"] == "goal" and discovery["identity"].startswith("R")
        else "u_unit"
        if discovery["origin"] == "goal" and discovery["identity"].startswith("U")
        else "obligation",
        stage="A4-1" if discovery["origin"] != "goal" else goal_stage(discovery["identity"]),
        discovery_ids=[discovery["id"]],
        domain=discovery["identity"],
        source_version=version,
        source_paths=[discovery["source"]["path"]],
        input_hashes=[discovery["source"]],
        disposition="implement",
        interface_status="discovered",
        obligation_status="pending",
        disposition_reason=reason,
        evidence_level="snapshot",
        applicability={
            key: {"status": "pending", "reason": reason, "case_ids": []} for key in DIMENSIONS
        },
        failure_reason=reason,
    )
    check_shape(row, ROW)
    return row


def goal_stage(goal: str) -> str:
    if goal.startswith("B"):
        return "A4-3"
    if goal.startswith("R"):
        return "A4-4"
    if goal.startswith("U"):
        return "A4-5"
    if goal in {"G08", "C8"}:
        return "A4-6"
    return "A4-2"
