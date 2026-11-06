"""Exact current transitions; declarations describe differences, never prove them.

Production reconstruction, native protection and migration witnesses remain
independent. This module admits a candidate only, with no product terminal state.
"""

from __future__ import annotations

import ast
import io
import re
from pathlib import Path
from typing import Any, cast

from tools.ci import a4_discovery as discovery
from tools.ci.a4_schema import HASH, RECEIPT, REFERENCE, TEXT, check_shape

EVOLVING = frozenset(
    {
        "facts",
        "migration_writers",
        "migration_files",
        "responsibilities",
        "evidence_ports",
        "current_native_boundaries",
        "targets",
        "predecessors",
    }
)
DERIVED = frozenset({"migration_acceptance", "stage_assignments", "successor_registry"})
ENDPOINT = {"present": "bool", "payload_sha256": TEXT, "semantic_ir_sha256": TEXT}
AUTHORITY = {
    "role": {"endpoint", "producer", "context", "getter", "native", "production"},
    "side": {"before", "after"},
    "artifact": TEXT,
    "identity": TEXT,
    "reference": REFERENCE,
}
CHANGE = {
    "artifact": TEXT,
    "identity": TEXT,
    "before": ENDPOINT,
    "after": ENDPOINT,
    "reason": TEXT,
    "witness_nodes": [TEXT],
    "authority": [AUTHORITY],
}
CONTRACT = {
    "schema": {1},
    "base_commit": TEXT,
    "base_root": REFERENCE,
    "before_sha256": HASH,
    "after_sha256": HASH,
    "native_proof": REFERENCE,
    "witnesses": [{"node": TEXT, "source": REFERENCE}],
    "changes": [CHANGE],
    "tombstones": [
        {
            "writer_id": TEXT,
            "before_sha256": HASH,
            "successor_ids": [TEXT],
            "reason": TEXT,
            "witness_nodes": [TEXT],
        }
    ],
}


def payload(values: dict[str, Any]) -> dict[str, Any]:
    """Exclude acceptance derived later, never exclude production authority."""
    return {name: value for name, value in values.items() if name not in DERIVED}


def endpoint(rows: dict[str, Any], identity: str, *, writer: bool) -> dict[str, Any]:
    present = identity in rows
    return {
        "present": present,
        "payload_sha256": discovery.digest(rows[identity]) if present else "absent",
        "semantic_ir_sha256": rows[identity]["semantic_ir_sha256"]
        if present and writer
        else "not_applicable",
    }


def differences(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Compute the complete changed set from independently reconstructed rows."""
    left, right = payload(before), payload(after)
    if set(left) != set(right):
        raise ValueError("successor artifact coverage changed")
    result = []
    for name in sorted(left):
        if left[name] == right[name]:
            continue
        if (
            name not in EVOLVING
            or not isinstance(left[name], dict)
            or not isinstance(right[name], dict)
        ):
            raise ValueError(f"successor immutable discovery/scope artifact changed: {name}")
        for identity in sorted(set(left[name]) | set(right[name])):
            old = endpoint(left[name], identity, writer=name == "migration_writers")
            new = endpoint(right[name], identity, writer=name == "migration_writers")
            if old != new:
                result.append({"artifact": name, "identity": identity, "before": old, "after": new})
    return result


def references(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Expose the full declaration/proof closure to the ordinary manifest."""
    return [
        contract["base_root"],
        contract["native_proof"],
        *(item["source"] for item in contract["witnesses"]),
        *(entry["reference"] for item in contract["changes"] for entry in item["authority"]),
    ]


def contract(sources: Any, intake: dict[str, Any]) -> dict[str, Any]:
    from tools.ci import a4_classify as classify  # noqa: PLC0415

    check_shape(intake["successor"], REFERENCE)
    if intake["successor"]["kind"] != "file" or intake["successor"]["identity"] != "whole_file":
        raise ValueError("successor needs complete declaration source")
    sources.verify(intake["successor"])
    value = sources.json(intake["successor"]["path"])
    check_shape(value, CONTRACT)
    if not re.fullmatch(r"[0-9a-f]{40}", value["base_commit"]):
        raise ValueError("successor requires exact accepted base commit")
    root = value["base_root"]
    if (
        root["path"] != classify.CURRENT_ROOT
        or root["kind"] != "file"
        or root["identity"] != "whole_file"
    ):
        raise ValueError("successor base must be the accepted current root")
    # The base reference belongs to the frozen commit, not the replacing file.
    for reference in references(value)[1:]:
        sources.verify(reference)
    witnesses = {item["node"]: item["source"] for item in value["witnesses"]}
    if len(witnesses) != len(value["witnesses"]) or set(witnesses) != set(intake["witness_nodes"]):
        raise ValueError("successor exact independent witness coverage drift")
    for node, source in witnesses.items():
        path, function = node.split("::", 1)
        if source["kind"] != "python" or (source["path"], source["identity"]) != (
            path,
            function.split("[", 1)[0],
        ):
            raise ValueError("successor witness source/function identity drift")
    for item in [*value["changes"], *value["tombstones"]]:
        if (
            not item["reason"].strip()
            or not item["witness_nodes"]
            or len(set(item["witness_nodes"])) != len(item["witness_nodes"])
            or set(item["witness_nodes"]) - set(witnesses)
        ):
            raise ValueError("successor change lacks exact independent witnesses")
    for item in value["changes"]:
        if not item["authority"]:
            raise ValueError("successor change lacks source-bound authority")
        for side in ("before", "after"):
            point = item[side]
            expected = point["payload_sha256"]
            if point["present"]:
                check_shape(expected, HASH)
            elif expected != "absent":
                raise ValueError("successor absent endpoint carries a payload")
            if item["artifact"] == "migration_writers" and point["present"]:
                check_shape(point["semantic_ir_sha256"], HASH)
            elif point["semantic_ir_sha256"] != "not_applicable":
                raise ValueError("successor endpoint semantic identity drift")
    # changes on the intake remain the old exact semantic-hash view, including
    # only IDs present at both endpoints. New/removal identities live above.
    changed = [
        {
            "writer_id": item["identity"],
            "before": item["before"]["semantic_ir_sha256"],
            "after": item["after"]["semantic_ir_sha256"],
            "reason": item["reason"],
            "witness_nodes": item["witness_nodes"],
        }
        for item in value["changes"]
        if item["artifact"] == "migration_writers"
        and item["before"]["present"]
        and item["after"]["present"]
        and item["before"]["semantic_ir_sha256"] != item["after"]["semantic_ir_sha256"]
    ]
    if intake["changes"] != changed:
        raise ValueError("successor intake changed-set drift")
    return cast("dict[str, Any]", value)


def base(
    sources: Any, intake: dict[str, Any], transition: dict[str, Any]
) -> tuple[Any, dict[str, Any]]:
    """Read the previous accepted current view from actual immutable Git objects."""
    from tools.ci import a4_classify as classify  # noqa: PLC0415
    from tools.ci import a4_history  # noqa: PLC0415
    from tools.ci.a4_scope import Sources, git, junit_results  # noqa: PLC0415

    commit = transition["base_commit"]
    git(sources.root, "merge-base", "--is-ancestor", commit, "HEAD")
    path = transition["base_root"]["path"]
    revisions = (
        git(sources.root, "log", "-2", "--format=%H", "HEAD", "--", path).decode().splitlines()
    )
    if not revisions or any(not re.fullmatch(r"[0-9a-f]{40}", item) for item in revisions):
        raise ValueError("successor accepted baseline history missing")
    latest_raw = git(sources.root, "show", f"{revisions[0]}:{path}")
    latest = discovery.strict_json(latest_raw)
    # Replaying a committed candidate must still bind its immediate accepted
    # predecessor. A root signed by this exact intake is the candidate itself,
    # rather than a permission to select any convenient older ancestor.
    own_intake = any(
        ref["path"] == classify.CURRENT_INTAKE
        and ref["sha256"] == sources.hash(classify.CURRENT_INTAKE)
        for ref in latest["inputs"]
    )
    if own_intake and any(ref["path"] == "tools/ci/a4_successor.py" for ref in latest["inputs"]):
        if len(revisions) != 2:
            raise ValueError("successor accepted predecessor root missing")
        latest_raw = git(sources.root, "show", f"{revisions[1]}:{path}")
    if discovery.sha(latest_raw) != transition["base_root"]["sha256"]:
        raise ValueError("successor self-selected or stale accepted baseline")
    raw_root = git(sources.root, "show", f"{commit}:{path}")
    if discovery.sha(raw_root) != transition["base_root"]["sha256"]:
        raise ValueError("successor base root hash drift")
    root = discovery.strict_json(raw_root)
    if (
        root["classification_status"] != "current_witnessed"
        or root["historical_commit"] != intake["historical_commit"]
    ):
        raise ValueError("successor base is not a verified current checkpoint")
    refs = [*root["inputs"], *root["artifacts"].values()]
    raw = a4_history.tree(
        git, sources.root, commit, tuple(sorted({path, *(ref["path"] for ref in refs)}))
    )
    frozen = Sources(sources.root, raw)
    for ref in refs:
        frozen.verify(ref)
    prior = frozen.json(classify.CURRENT_INTAKE)
    if prior["status"] != "verified" or prior["receipt_path"] == "pending":
        raise ValueError("successor base has no accepted current witnesses")
    if prior["receipt_path"] not in raw:
        raise ValueError("successor base receipt is not bound by accepted root")
    receipt = frozen.json(prior["receipt_path"])
    check_shape(receipt, RECEIPT)
    closure = [receipt["junit"], *receipt["bindings"]]
    extra = {ref["path"] for ref in closure} - set(raw)
    if extra:
        raw.update(a4_history.tree(git, sources.root, commit, tuple(sorted(extra))))
        frozen = Sources(sources.root, raw)
    for ref in closure:
        frozen.verify(ref)
    historical_receipt(frozen, root, prior, receipt)
    # Parse frozen original XML, never a replacing working-tree report.
    passed, failed = junit_results(cast("Any", io.BytesIO(frozen.read(receipt["junit"]["path"]))))
    if (
        receipt["exit_code"]
        or receipt["failed"]
        or failed
        or not passed
        or sorted(passed) != sorted(receipt["passed"])
        or sorted(passed) != sorted(receipt["selection"])
        or set(prior["witness_nodes"]) - set(passed)
    ):
        raise ValueError("successor base current witness receipt is incomplete")
    return frozen, {name: frozen.json(ref["path"]) for name, ref in root["artifacts"].items()}


def historical_receipt(
    frozen: Any, root: dict[str, Any], prior: dict[str, Any], receipt: dict[str, Any]
) -> None:
    """Validate original source/command/production closure using frozen bytes only."""
    from tools.ci import a4_classify as classify  # noqa: PLC0415
    from tools.ci.a4_scope import (  # noqa: PLC0415
        witness_command_refs,
        witness_reference,
    )

    selection = receipt["selection"]
    if not selection or len(set(selection)) != len(selection):
        raise ValueError("successor historical witness selection empty or duplicated")
    bound = {discovery.encoded(ref) for ref in receipt["bindings"]}
    for node in selection:
        path = node.split("::", 1)[0]
        if path not in frozen.bytes:
            raise ValueError("successor historical original witness source missing")
        reference = witness_reference(frozen, node)
        if discovery.encoded(reference) not in bound:
            raise ValueError("successor historical original witness function binding missing")
        if discovery.encoded(frozen.reference(path)) not in bound:
            raise ValueError("successor historical complete witness/helper source missing")
    # This parser reads only frozen selection.args bytes. It does not execute.
    for argument in receipt["command"]:
        if argument.startswith("@"):
            path = Path(argument[1:]).resolve()
            if not path.is_relative_to(frozen.root.resolve()):
                raise ValueError("successor historical receipt argument file escapes repository")
            if path.relative_to(frozen.root).as_posix() not in frozen.bytes:
                raise ValueError("successor historical receipt argument file not frozen")
    witness_command_refs(frozen, receipt)
    junit_path = receipt["command"][-1].removeprefix("--junitxml=")
    if Path(junit_path).resolve() != (frozen.root / receipt["junit"]["path"]).resolve():
        raise ValueError("successor historical receipt JUnit command path mismatch")
    if "mod/generation-lock.json" not in frozen.bytes or "package" not in prior:
        raise ValueError("successor historical production closure missing")
    lock = frozen.json("mod/generation-lock.json")
    required = {
        classify.MIGRATION_PATH,
        prior["package"]["path"],
        classify.TASK6_PACKAGE,
        classify.TASK6_LOCK,
        "mod/generation-lock.json",
        *classify.INPUTS,
        *frozen_gate_paths(frozen),
        *lock["sources"],
        *(f"mod/{path}" for path in lock["files"]),
    }
    # Root-only presentation/evidence records are not execution inputs.
    excluded = {
        classify.CURRENT_INTAKE,
        classify.ROOT_PATH,
        classify.REPORT_PATH,
        prior["receipt_path"],
        receipt["junit"]["path"],
    }
    required.update(ref["path"] for ref in root["inputs"] if ref["path"] not in excluded)
    for path in sorted(required):
        if path not in frozen.bytes or discovery.encoded(frozen.reference(path)) not in bound:
            raise ValueError(f"successor historical complete production binding missing: {path}")
    for path, digest in lock["sources"].items():
        if frozen.hash(path) != digest:
            raise ValueError(f"successor historical production source drift: {path}")
    contracts = frozen.json(classify.MIGRATION_PATH)["objectives"]
    required_nodes = set(prior["witness_nodes"]) | {
        node for contract in contracts.values() for node in contract["witness_nodes"]
    }
    if required_nodes - set(selection):
        raise ValueError("successor historical prior/objective witness omitted")


def frozen_gate_paths(frozen: Any) -> set[str]:
    """Read the frozen declarative gate inventory without importing old code."""

    def strings(path: str, name: str) -> set[str]:
        if path not in frozen.bytes:
            raise ValueError("successor historical frozen gate source missing")
        tree = ast.parse(frozen.read(path), filename=path)
        for statement in tree.body:
            target: ast.expr
            value: ast.expr | None
            if isinstance(statement, ast.AnnAssign):
                target, value = statement.target, statement.value
            elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target, value = statement.targets[0], statement.value
            else:
                continue
            if (
                not isinstance(target, ast.Name)
                or target.id != name
                or not isinstance(value, ast.Tuple)
            ):
                continue
            result = set()
            for item in value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    result.add(item.value)
                elif (
                    isinstance(item, ast.Starred)
                    and isinstance(item.value, ast.Attribute)
                    and item.value.attr == "PROJECTOR_INPUTS"
                    and isinstance(item.value.value, ast.Name)
                    and item.value.value.id == "a4_discovery"
                ):
                    result.update(strings("tools/ci/a4_discovery.py", "PROJECTOR_INPUTS"))
                else:
                    raise ValueError(
                        "successor historical frozen gate source inventory unsupported"
                    )
            return result
        raise ValueError("successor historical frozen gate source inventory missing")

    return strings("tools/ci/a4_scope.py", "GATE_INPUTS")


def admit(
    sources: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    transition: dict[str, Any],
    *,
    frozen: Any,
) -> tuple[list[str], dict[str, Any]]:
    """Compare a reviewed permission with the actual independent production view."""
    if transition["before_sha256"] != discovery.digest(payload(before)) or transition[
        "after_sha256"
    ] != discovery.digest(payload(after)):
        raise ValueError("successor complete payload/authority hash drift")
    actual = differences(before, after)
    declared = [
        {key: item[key] for key in ("artifact", "identity", "before", "after")}
        for item in transition["changes"]
    ]
    if declared != actual:
        raise ValueError("successor undeclared/forged complete changed set")
    for name in ("targets", "predecessors"):
        if set(before[name]) - set(after[name]):
            raise ValueError("successor dropped stable discovery/predecessor ID")
    old, now = before["migration_writers"], after["migration_writers"]
    removed = set(old) - set(now)
    tombstones = {item["writer_id"]: item for item in transition["tombstones"]}
    if len(tombstones) != len(transition["tombstones"]) or set(tombstones) != removed:
        raise ValueError("successor removed writer lacks exact lineage/tombstone")
    registry = dict(before.get("successor_registry", {}))
    if any(identity in registry for identity in removed):
        raise ValueError("successor overwrote historical writer tombstone")
    for identity, item in tombstones.items():
        if (
            item["before_sha256"] != discovery.digest(old[identity])
            or not item["successor_ids"]
            or len(set(item["successor_ids"])) != len(item["successor_ids"])
            or set(item["successor_ids"]) - set(now)
        ):
            raise ValueError("successor writer lineage is stale or dangling")
        registry[identity] = {
            "status": "removed_pending_lineage_acceptance",
            "previous": old[identity],
            "lineage": item,
            "product_authority": False,
        }
    # Never revive a removed identity under another owner or overwrite its past.
    if set(registry) & set(now):
        raise ValueError("successor reused a tombstoned writer identity")
    for item in transition["changes"]:
        validate_authority(sources, frozen, before, after, transition, item)
    for ref in references(transition)[1:]:
        sources.verify(ref)
    changed = sorted(item["identity"] for item in actual if item["artifact"] == "migration_writers")
    return changed, registry


def referenced_row(sources: Any, reference: dict[str, str], artifact: str, identity: str) -> Any:
    """A JSON reference must name this exact object, never a whole attachment."""
    sources.verify(reference)
    pointer = identity.replace("~", "~0").replace("/", "~1")
    if reference["kind"] != "json" or reference["identity"] != f"{artifact}/{pointer}":
        raise ValueError("successor authority exact JSON object identity mismatch")
    node = sources.json(reference["path"])
    for token in reference["identity"].split("/"):
        node = node[token.replace("~1", "/").replace("~0", "~")]
    return node


def production_authority(
    sources: Any, authoritative: Any, reference: dict[str, str], *, historical: bool
) -> None:
    """Bind every real producer input, with no guessed Python-function lineage."""
    sources.verify(reference)
    if reference["kind"] != "file" or reference["identity"] != "whole_file":
        raise ValueError("successor authority requires exact production generation lock")
    lock = sources.json(reference["path"])
    if lock != authoritative.json("mod/generation-lock.json"):
        raise ValueError("successor authority production lock differs from exact endpoint")
    if not lock["sources"]:
        raise ValueError("successor authority production source closure empty")
    # Same source inventory as distribution.generation_lock, including any new
    # producer file; deleting an entry and re-signing the lock cannot omit it.
    patterns = (
        "src/pdx/**/*.py",
        "mod/decisions/*.toml",
        "research/vanilla-ai/1.15.0/*.txt",
        "research/vanilla-ai/1.15.0/*.json",
        "research/situated/*.json",
    )
    required = (
        set()
        if historical
        else {
            path.relative_to(authoritative.root).as_posix()
            for pattern in patterns
            for path in authoritative.root.glob(pattern)
            if path.is_file()
        }
    )
    required.update(
        path
        for path in authoritative.bytes
        if (
            (path.startswith("src/pdx/") and path.endswith(".py"))
            or re.fullmatch(r"mod/decisions/[^/]+\.toml", path)
            or re.fullmatch(r"research/vanilla-ai/1\.15\.0/[^/]+\.(txt|json)", path)
            or re.fullmatch(r"research/situated/[^/]+\.json", path)
        )
    )
    if set(lock["sources"]) != required:
        raise ValueError("successor authority complete production source inventory mismatch")
    for path, digest in lock["sources"].items():
        if authoritative.hash(path) != digest:
            raise ValueError(f"successor authority production source closure drift: {path}")


def validate_authority(
    sources: Any,
    frozen: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    transition: dict[str, Any],
    item: dict[str, Any],
) -> None:
    """Relate typed proof roles to the independently rebuilt actual endpoint."""
    artifact, identity = item["artifact"], item["identity"]
    side = "after" if item["after"]["present"] else "before"
    values = after if side == "after" else before
    row = values[artifact][identity]
    entries = item["authority"]
    keys = [(entry["role"], entry["artifact"], entry["identity"]) for entry in entries]
    if len(set(keys)) != len(keys) or any(entry["side"] != side for entry in entries):
        raise ValueError("successor authority duplicate role or endpoint-side mismatch")
    expected = {
        ("endpoint", artifact, identity),
        ("production", "generation_lock", "production_source_closure"),
    }
    if artifact == "migration_writers":
        expected.update({("producer", artifact, identity), ("context", artifact, identity)})
        expected.update(("getter", "facts", fact) for fact in row["fact_key_bindings"].values())
        expected.add(("native", "native_report", f"{row['native_source']}#{row['native_field']}"))
    if set(keys) != expected:
        raise ValueError("successor authority producer/context/getter/native closure mismatch")
    for entry in entries:
        role, reference = entry["role"], entry["reference"]
        if role == "production":
            production_authority(
                sources,
                sources if side == "after" else frozen,
                reference,
                historical=side == "before",
            )
        elif role == "native":
            if reference != transition["native_proof"]:
                raise ValueError("successor authority native report differs from normal proof")
            proof = sources.json(reference["path"])["native_treatments"]
            matched = [
                native
                for native in proof["rows"]
                if native["source"] == row["native_source"]
                and f"{native['definition']}.{native['field']}" == row["native_field"]
            ]
            if not matched or any(
                native["active_unknown_usage"]
                or not native["source_protection"]["context_closed"]
                or not native["source_protection"]["dependencies_closed"]
                or not (
                    native["source_protection"]["proven"]
                    or native["interface"]["control_authorized"]
                )
                for native in matched
            ):
                raise ValueError("successor authority exact native field/context proof missing")
        else:
            actual = referenced_row(sources, reference, entry["artifact"], entry["identity"])
            expected_row = values[entry["artifact"]][entry["identity"]]
            if actual != expected_row:
                raise ValueError("successor authority row differs from reconstructed endpoint")
            if role in {"producer", "context"}:
                required = {
                    "source",
                    "definition",
                    "consumer_id",
                    "chain_refs",
                    "evaluation_context",
                    "reader_context_bindings",
                    "fact_key_bindings",
                }
                if not required <= actual.keys() or not actual["evaluation_context"]:
                    raise ValueError("successor authority producer/context identity incomplete")


def native_protection(
    sources: Any,
    frozen: Any,
    before: dict[str, Any],
    after: dict[str, Any],
    transition: dict[str, Any],
) -> None:
    """Rebuild the existing normal production proof; intake cannot mask AST nodes."""
    from pdx.situated.audit import native_report  # noqa: PLC0415

    reference = transition["native_proof"]
    if reference["kind"] != "file" or reference["identity"] != "whole_file":
        raise ValueError("successor native proof must bind complete normal production report")
    sources.verify(reference)
    report = native_report()
    if report != sources.json(reference["path"]):
        raise ValueError(
            "successor native proof differs from independent normal production reconstruction"
        )
    validate_native(sources, frozen, before, after, report)


def validate_native(
    sources: Any, frozen: Any, before: dict[str, Any], after: dict[str, Any], report: dict[str, Any]
) -> None:
    """Check complete native source projections, retaining all non-target structure."""
    proof = report["native_treatments"]
    if proof["production_manifest_complete_asserted"] is not True or proof["receipt_issues"]:
        raise ValueError("successor native production proof incomplete")
    captured = sources.json(discovery.ROOT_PATH)["source_hashes"]
    old_files, files = before["migration_files"], after["migration_files"]
    if set(old_files) - set(files):
        raise ValueError("successor dropped a generated/native source")
    for path in files:
        raw = sources.read(f"mod/{path}")
        if discovery.sha(raw) != files[path]["generated_sha256"]:
            raise ValueError(f"successor generated/package byte identity drift: {path}")
        # The existing native report deliberately has engineering metadata,
        # whereas current_files validates the standard package metadata.
        # Its native proof applies to the identical script output bytes only.
        if not path.endswith(".txt"):
            continue
        if proof["production_hashes"].get(path) != discovery.sha(raw):
            raise ValueError(f"successor native proof generated byte identity drift: {path}")
        if path in old_files and raw == frozen.read(f"mod/{path}"):
            continue
        if path not in captured:
            # Original paths come from the immutable independent capture,
            # never an intake exclusion list. Generated-only helpers/media
            # still require the complete normal package/output hash above.
            if path in proof["source_hashes_verified"]:
                raise ValueError(f"successor native source omitted from capture: {path}")
            continue
        rows = [row for row in proof["rows"] if row["source"] == path]
        if not rows or proof["source_hashes_verified"].get(path) != captured[path]:
            raise ValueError(f"successor complete native source proof missing: {path}")
        for row in rows:
            protection = row["source_protection"]
            if (
                not protection["context_closed"]
                or not protection["dependencies_closed"]
                or protection["native_source_sha256"] != captured[path]
                or protection["effective_source_sha256"] != discovery.sha(raw)
                or row["active_unknown_usage"]
                or not (protection["proven"] or row["interface"]["control_authorized"])
            ):
                raise ValueError(
                    f"successor native tail/parent/sibling/dependency protection failed: {path}:{row['declaration_id']}"
                )
