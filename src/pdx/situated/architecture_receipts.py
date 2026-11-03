"""A2 阶段证据合同：核对来源与退出证据，不代跑功能或外部发布。"""

from __future__ import annotations

import ast
import gzip
import hashlib
import json
import math
import re
import subprocess
import zipfile
import zlib
from collections import Counter
from dataclasses import asdict
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, TypeGuard

from ..parser import parse_bytes  # noqa: TID252
from .native_treatments import _digest, _resolve
from .receipts import StageReceipt, digest, validate_receipt

if TYPE_CHECKING:
    from .vanilla_inventory import VanillaInventory

PLAN_VERSION = "A2"
PLAN_PATH = Path("docs/design/架构主计划.md")
SUBPLAN_PATH = Path("docs/design/架构子计划.md")
RECEIPT_PATH = Path("docs/design/exec/架构阶段收据.json")
STAGE_DEPENDENCIES = {
    "S0": (),
    "S1": ("S0",),
    "S2": ("S1",),
    "S3": ("S1",),
    "S4": ("S2", "S3"),
    "S5": ("S4",),
    "S6": ("S5",),
}
ENGINEERING_STAGES = tuple(stage for stage in STAGE_DEPENDENCIES if stage != "S6")
STAGE_DIRECTIONS = {
    "S0": ("B0",),
    "S1": ("B1",),
    "S2": ("B2", "B3", "B4"),
    "S3": ("B5", "B6"),
    "S4": ("B0", "B1", "B7"),
    "S5": ("B0", "B7", "B8"),
    "S6": ("B8",),
}
# Stable strategic outcomes, not implementation names, thresholds or functions.
STAGE_REQUIREMENTS = {
    "S0": ("archive_identity", "independent_scope", "known_failures_migration"),
    "S1": (
        "production_chain",
        "joint_benefit_cost",
        "local_unknown",
        "units_direction",
        "single_cap_native_tail",
        "independent_pdx_witness",
    ),
    "S2": (
        "economy_fiscal_construction",
        "society_education_knowledge",
        "politics_governance_identity",
        "cost_saturation_unknown_counterexamples",
    ),
    "S3": (
        "market_trade_company_diplomacy",
        "military_security_recovery",
        "complete_target_context",
        "observed_feedback_opportunity_cost",
    ),
    "S4": (
        "legal_scope_disposition",
        "legacy_migration",
        "single_owner_no_bypass",
        "cross_domain_relations",
    ),
    "S5": (
        "whole_mod_functional_review",
        "native_integration",
        "full_regression_resources",
        "quality_hygiene_package",
    ),
    "S6": ("merged_ci", "tag_release_zip_sha", "workshop_copy", "deployment_rollback_cleanup"),
}
FUNCTIONAL_STAGES = frozenset({"S1", "S2", "S3", "S4"})
WITNESS_ROLES = frozenset({"positive", "negative", "unknown", "disabled", "player", "native_tail"})
_HASH = re.compile(r"[a-f0-9]{64}\Z")
REQUIREMENT_DIRECTIONS = {
    (stage, requirement): STAGE_DIRECTIONS[stage][0]
    for stage, requirements in STAGE_REQUIREMENTS.items()
    for requirement in requirements
}
REQUIREMENT_DIRECTIONS.update(
    {
        ("S2", "society_education_knowledge"): "B3",
        ("S2", "politics_governance_identity"): "B4",
        ("S3", "military_security_recovery"): "B6",
        ("S3", "observed_feedback_opportunity_cost"): "B6",
        ("S4", "single_owner_no_bypass"): "B1",
        ("S4", "cross_domain_relations"): "B7",
        ("S5", "whole_mod_functional_review"): "B7",
        ("S5", "full_regression_resources"): "B8",
        ("S5", "quality_hygiene_package"): "B8",
    }
)


def source_snapshot(root: Path) -> dict[str, str]:
    """Freeze current production, checks and tests; outputs are not input sources."""
    paths = {
        path
        for directory in ("src/pdx", "tests", "tools/ci", "mod")
        for path in (root / directory).rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".toml", ".json", ".txt", ".yml", ".png"}
        and "__pycache__" not in path.parts
    }
    paths.update(
        root / name
        for name in ("pyproject.toml", "requirements.lock", "pytest.ini", ".coveragerc")
        if (root / name).is_file()
    )
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def _path(root: Path, name: Any) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or PurePosixPath(name).is_absolute()
        or PureWindowsPath(name).drive
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError(f"noncanonical artifact path: {name!r}")
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"artifact escapes root: {name}")
    return path


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(path: Path) -> dict[str, Any]:
    if path.name.endswith(".json.gz"):
        try:
            raw = gzip.decompress(path.read_bytes()).decode("utf-8")
        except (OSError, EOFError, UnicodeError, zlib.error) as exc:
            raise ValueError(f"invalid compressed JSON receipt: {path.name}") from exc
    else:
        raw = path.read_text(encoding="utf-8")
    value = json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON receipt must be an object")
    return value


def _artifact(root: Path, ref: Any) -> Path:
    if (
        not isinstance(ref, dict)
        or not isinstance(ref.get("sha256"), str)
        or not _HASH.fullmatch(ref["sha256"])
    ):
        raise ValueError("artifact requires path and SHA-256")
    path = _path(root, ref.get("path"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        raise ValueError(f"stale artifact: {ref['path']}")
    return path


def _strings(value: Any, *, nonempty: bool = False) -> TypeGuard[list[str]]:
    return (
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(isinstance(item, str) and item for item in value)
        and len(set(value)) == len(value)
    )


def _test_identity(root: Path, ref: Any) -> str:
    if not isinstance(ref, dict) or not isinstance(ref.get("nodeid"), str):
        raise ValueError("test requires a nodeid")
    nodeid = str(ref["nodeid"])
    file, *names = nodeid.split("::")
    if not file.startswith("tests/") or not names:
        raise ValueError(f"not a specific test identity: {nodeid}")
    path = _artifact(root, {"path": file, "sha256": ref.get("sha256")})
    body = ast.parse(path.read_text(encoding="utf-8")).body
    for name in names:
        plain = name.split("[", 1)[0]
        matches = [
            node
            for node in body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == plain
        ]
        if len(matches) != 1:
            raise ValueError(f"test identity is missing or ambiguous: {nodeid}")
        body = matches[0].body
    if not names[-1].split("[", 1)[0].startswith("test_"):
        raise ValueError(f"not a test function: {nodeid}")
    return nodeid


def _open_issues(value: Any, path: str = "result") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            where = f"{path}.{key}"
            if key.removesuffix("_count") in {
                "pending",
                "blocked",
                "unknown",
                "unclassified",
                "parse_failures",
                "unimplemented",
                "failures",
                "open_items",
            } and child not in ([], {}, 0):
                issues.append(where)
            if key == "status" and child not in {
                "passed",
                "verified",
                "complete",
                "implemented",
                "engine_unexposed",
                "retained_native",
                "observation",
            }:
                issues.append(f"{where}={child}")
            issues.extend(_open_issues(child, where))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(_open_issues(child, f"{path}[{index}]"))
    return issues


def _evidence(
    root: Path, stage: str, row: dict[str, Any], snapshot_hash: str, scope_hash: str
) -> list[str]:
    """Bind one requirement to actual production/generated/test/result identities."""
    issues: list[str] = []
    try:
        requirement = row["requirement_id"]
        evidence_id = row["evidence_id"]
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("evidence_id missing")
        if row.get("direction") != REQUIREMENT_DIRECTIONS.get((stage, requirement)):
            raise ValueError("direction outside fixed stage responsibilities")
        if row.get("oracle") != "independent":
            raise ValueError("independent expected-result source missing")
        kind = _evidence_kind(stage, requirement)
        if row.get("evidence_kind", kind) != kind:
            raise ValueError("evidence kind does not match the strategic requirement")
        artifact_fields = (
            ("production", "generated", "consumers") if kind == "pdx" else ("artifacts",)
        )
        if kind != "pdx":
            artifacts = row.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                raise ValueError("requirement-specific artifact identities missing")
            for ref in artifacts:
                _artifact(root, ref)
        for field, prefixes in (
            ("production", ("src/pdx/", "mod/decisions/", "tools/ci/")),
            ("generated", ("mod/",)),
        ):
            if kind != "pdx":
                continue
            refs = row.get(field)
            if not isinstance(refs, list) or not refs:
                raise ValueError(f"{field} artifact identities missing")
            for ref in refs:
                path = _artifact(root, ref).relative_to(root).as_posix()
                if not path.startswith(prefixes):
                    raise ValueError(f"{field} path outside declared role: {path}")
                if field == "generated" and path.startswith("mod/decisions/"):
                    raise ValueError("source TOML is not a generated consumer")
        consumers = row.get("consumers") if kind == "pdx" else []
        if not isinstance(consumers, list) or (kind == "pdx" and not consumers):
            raise ValueError("generated field/expression identities missing")
        # One validation invocation sees one frozen byte identity per generated
        # file. Reuse its parsed tree across physical fields, never across calls.
        parsed_consumers = {}
        for consumer in consumers:
            if not isinstance(consumer, dict) or consumer.get("path") not in {
                ref["path"] for ref in row["generated"]
            }:
                raise ValueError("consumer is outside bound generated artifacts")
            source = consumer["path"]
            if source not in parsed_consumers:
                parsed_consumers[source] = parse_bytes(
                    _path(root, source).read_bytes(), path=source
                )
            parsed = parsed_consumers[source]
            if parsed.errors:
                raise ValueError("generated consumer source does not parse")
            node, state = _resolve(parsed.root, consumer["definition"], consumer["field"])
            if node is None or state != "found" or consumer.get("ast_sha256") != _digest(node):
                raise ValueError("generated consumer field/expression identity mismatch")
        tests = row.get("tests")
        if not isinstance(tests, list) or not tests:
            raise ValueError("specific test identities missing")
        ids = [_test_identity(root, ref) for ref in tests]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate test identity")
        result = _json(_artifact(root, row.get("result")))
        expected = {
            "schema": 1,
            "plan_version": PLAN_VERSION,
            "stage_id": stage,
            "requirement_id": requirement,
            "evidence_id": evidence_id,
            "source_snapshot_sha256": snapshot_hash,
            "scope_hash": scope_hash,
            "evidence_category": "static_check",
            "status": "passed",
        }
        if any(
            type(result.get(key)) is not type(value) or result.get(key) != value
            for key, value in expected.items()
        ):
            raise ValueError("result identity/source/scope/status mismatch")
        if any(result.get(field) != row[field] for field in artifact_fields):
            raise ValueError("result does not bind actual production/generated identities")
        if result.get("evidence_kind", kind) != kind:
            raise ValueError("result evidence kind mismatch")
        if kind == "archive":
            if result.get("archive_manifest") not in row["artifacts"]:
                raise ValueError("archive manifest is outside bound artifacts")
            _archive_identity(root, result["archive_manifest"])
        cases = result.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ValueError("result contains no executed cases")
        observed = "generated" if kind == "pdx" else "observed"
        if any(
            not isinstance(case, dict)
            or case.get("outcome") != "passed"
            or case.get("expected_origin") != "independent"
            or case.get("nodeid") not in ids
            for case in cases
        ):
            raise ValueError("failed/skipped/unknown/nonindependent witness")
        if any(
            not isinstance(case.get("input"), dict)
            or not case["input"]
            or any(field not in case for field in ("expected", "reference", observed))
            or digest(case["expected"]) != digest(case["reference"])
            or digest(case["expected"]) != digest(case[observed])
            for case in cases
        ):
            raise ValueError(
                "independent expected/reference/generated output comparison missing or unequal"
            )
        if {case["nodeid"] for case in cases} != set(ids):
            raise ValueError("test/result execution identity mismatch")
        case_ids = [case.get("case_id") for case in cases]
        if not _strings(case_ids, nonempty=True):
            raise ValueError("missing or duplicate case IDs")
        if kind == "pdx" and not {case.get("role") for case in cases} >= WITNESS_ROLES:
            raise ValueError("functional positive/cost/unknown/disable/player/tail roles missing")
        if kind == "pdx" and len({digest(case["expected"]) for case in cases}) < 2:
            raise ValueError("functional witness shows no actual output distinction")
        if kind == "pdx":
            identities = {
                (consumer["path"], consumer["definition"], consumer["field"])
                for consumer in consumers
            }
            by_consumer: dict[tuple[str, str, str], list[dict[str, Any]]] = {
                identity: [] for identity in identities
            }
            for case in cases:
                bound = case.get("consumers")
                if (
                    not isinstance(bound, list)
                    or len(bound) != 1
                    or not isinstance(bound[0], dict)
                    or set(bound[0]) != {"path", "definition", "field"}
                    or any(not isinstance(value, str) or not value for value in bound[0].values())
                ):
                    raise ValueError("each functional case must bind one exact consumer")
                identity = (bound[0]["path"], bound[0]["definition"], bound[0]["field"])
                if identity not in by_consumer:
                    raise ValueError("case consumer outside bound generated identities")
                by_consumer[identity].append(case)
            for identity, witnesses in by_consumer.items():
                if not {case.get("role") for case in witnesses} >= WITNESS_ROLES:
                    raise ValueError(f"consumer functional roles missing: {identity}")
                if len({digest(case["expected"]) for case in witnesses}) < 2:
                    raise ValueError(f"consumer has no actual output distinction: {identity}")
        if result.get("open_items") != []:
            raise ValueError("result has unclosed functional items")
        # Business observations may contain unknown/disabled values. Execution
        # metadata still has to close, independently of outcome="passed".
        issues.extend(_open_issues({key: value for key, value in result.items() if key != "cases"}))
        for index, case in enumerate(cases):
            metadata = {
                key: value
                for key, value in case.items()
                if key not in {"input", "expected", "reference", "generated", "observed"}
            }
            issues.extend(_open_issues(metadata, f"result.cases[{index}]"))
        if stage == "S5" and requirement == "full_regression_resources":
            full = _json(_artifact(root, result.get("full_acceptance")))
            if (
                full.get("ok") is not True
                or type(full.get("exit_code")) is not int
                or full["exit_code"] != 0
                or full.get("errors") != []
                or not full.get("collection", {}).get("nodeids")
                or not full.get("resources")
                or not full.get("verdict")
                or any(item.get("ok") is not True for item in full["verdict"])
                or full.get("coverage", {}).get("branch") is not True
            ):
                raise ValueError(
                    "current full-acceptance identity/coverage/resource evidence missing"
                )
            _full_acceptance(full)
    except (KeyError, OSError, UnicodeError, TypeError, ValueError, AttributeError) as exc:
        issues.append(f"evidence:{exc}")
    return issues


def _evidence_kind(stage: str, requirement: str) -> str:
    if stage in FUNCTIONAL_STAGES or (
        stage == "S5" and requirement in {"whole_mod_functional_review", "native_integration"}
    ):
        return "pdx"
    return {
        ("S0", "archive_identity"): "archive",
        ("S0", "independent_scope"): "scope",
        ("S0", "known_failures_migration"): "migration",
        ("S5", "full_regression_resources"): "regression",
        ("S5", "quality_hygiene_package"): "engineering",
    }.get((stage, requirement), "delivery")


def _archive_bytes(root: Path, commit: str, name: str) -> bytes:
    """Read the frozen Git object without changing the worktree or refs."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{name}"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("historical Git object read timed out") from exc
    if result.returncode:
        raise ValueError(f"historical Git object unavailable:{commit}:{name}")
    return result.stdout


def _archive_identity(root: Path, ref: Any) -> None:
    if not isinstance(ref, dict) or ref.get("path") != "docs/design/archive/manifest.json":
        raise ValueError("archive evidence must bind the authoritative archive manifest")
    manifest = _json(_artifact(root, ref))
    files = manifest.get("files")
    if (
        manifest.get("schema") != 1
        or manifest.get("role") != "historical_reference_only"
        or not isinstance(files, list)
        or not files
    ):
        raise ValueError("archive manifest identity/files missing")
    identities: set[tuple[str, str]] = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("invalid archive identity")
        name = _path(root, item.get("path")).relative_to(root).as_posix()
        commit = item.get("commit")
        if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("archive requires a frozen commit identity")
        identity = commit, name
        if identity in identities:
            raise ValueError("duplicate archive identity")
        identities.add(identity)
        raw = _archive_bytes(root, commit, name)
        if (
            type(item.get("bytes")) is not int
            or item["bytes"] != len(raw)
            or item.get("sha256") != hashlib.sha256(raw).hexdigest()
        ):
            raise ValueError(f"historical archive bytes mismatch:{name}")


def _full_acceptance(full: dict[str, Any]) -> None:
    """Check existing suite-report identities and measured results, not a new budget."""
    groups = full.get("groups")
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError("full-acceptance must identify exactly one full run")
    group = groups[0]
    if not isinstance(group, dict) or group.get("tag") != "full" or group.get("exit_code") != 0:
        raise ValueError("full-run identity or exit status invalid")
    for field in ("wall_s", "peak_total_mb", "per_worker_peak_mb", "samples"):
        value = group.get(field)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"full-run measured resource missing:{field}")
    if type(group.get("n_workers")) is not int or group["n_workers"] < 0:
        raise ValueError("full-run worker identity missing")
    if any(
        group.get(field)
        for field in ("timed_out", "killed_by_watchdog", "sampler_errors", "execution_error")
    ):
        raise ValueError("full run contains resource/execution failures")
    collection = full["collection"]
    nodes = collection["nodeids"]
    if not _strings(nodes, nonempty=True) or any(
        collection.get(field) for field in ("mismatches",)
    ):
        raise ValueError("full-run collection identity invalid")
    if any(
        Counter(collection.get(field, [])) != Counter(nodes) for field in ("started", "finished")
    ):
        raise ValueError("full-run execution identities differ from collection")
    tests = full.get("tests")
    if (
        not isinstance(tests, dict)
        or tests.get("tests") != len(nodes)
        or any(tests.get(field) != 0 for field in ("errors", "failures"))
        or tests.get("unknown_skip_reasons") != []
    ):
        raise ValueError("full-run JUnit evidence is missing or failed")
    coverage = full["coverage"]
    for field in ("percent", "floor"):
        value = coverage.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 100:
            raise ValueError("full-run measured coverage is missing")
    if (
        coverage["percent"] < coverage["floor"]
        or coverage.get("failed_modules") != []
        or coverage.get("missing_modules") != []
    ):
        raise ValueError("full-run coverage gate failed")
    resources = full["resources"]
    if not resources.get("inproc") or not resources.get("peak_pairs"):
        raise ValueError("full-run dual resource evidence is missing")


def _fresh_native_report() -> dict[str, Any]:
    """Reuse the independent production audit, including its complete byte manifest."""
    from .audit import native_report  # noqa: PLC0415

    return native_report()


def _typed_native_report(
    root: Path, data: Any, inventory: VanillaInventory | None, snapshot_hash: str
) -> tuple[dict[str, Any], list[str]]:
    """A stored report is evidence only while a fresh audit reproduces it exactly."""
    try:
        if not isinstance(data, dict) or inventory is None:
            raise ValueError("fresh inventory/report reference unavailable")
        report = _json(_artifact(root, data.get("typed_report")))
        expected = {
            "schema": 1,
            "plan_version": PLAN_VERSION,
            "evidence_category": "static_check",
            "source_snapshot_sha256": snapshot_hash,
        }
        if any(
            type(report.get(k)) is not type(v) or report.get(k) != v for k, v in expected.items()
        ):
            raise ValueError("typed report source/schema identity mismatch")
        fresh = _fresh_native_report()
        if fresh.get("source_snapshot_sha256") != snapshot_hash:
            raise ValueError("fresh audit source snapshot mismatch")
        payload = report.get("native_treatments")
        if not isinstance(payload, dict) or digest(payload) != digest(
            fresh.get("native_treatments")
        ):
            raise ValueError("typed report differs from fresh production/native audit")
        expected = {
            "baseline_id": inventory.baseline_id,
            "scope_hash": inventory.scope_hash,
            "denominator": inventory.discovered_count,
            "source_hashes_verified": {
                name: sha
                for name, sha in inventory.source_hashes.items()
                if not name.startswith("@")
            },
            "production_manifest_complete_asserted": True,
        }
        if any(
            type(payload.get(k)) is not type(v) or payload.get(k) != v for k, v in expected.items()
        ):
            raise ValueError("typed report baseline/source/manifest identity mismatch")
        manifest = payload.get("production_hashes")
        if (
            not isinstance(manifest, dict)
            or not manifest
            or any(
                not isinstance(sha, str) or not _HASH.fullmatch(sha) for sha in manifest.values()
            )
        ):
            raise ValueError("typed report complete production manifest missing")
        for name in manifest:
            _path(root, name)
        return payload, []
    except (KeyError, OSError, UnicodeError, TypeError, ValueError, AttributeError) as exc:
        return {}, [f"native typed report:{exc}"]


def _native_scope(
    data: Any,
    inventory: VanillaInventory | None,
    known_evidence: set[str],
    typed_report: dict[str, Any],
    report_issues: list[str],
    evidence_consumers: dict[str, set[tuple[str, str, str]]],
) -> dict[str, Any]:
    issues = list(report_issues)
    remaining: list[str] = []
    if inventory is None:
        return {
            "ready": False,
            "closed": False,
            "issues": ["fresh native inventory unavailable"],
            "remaining": [],
        }
    if not isinstance(data, dict):
        data = {}
    expected = {
        "baseline_id": inventory.baseline_id,
        "scope_hash": inventory.scope_hash,
        "denominator": inventory.discovered_count,
        "source_hashes": inventory.source_hashes,
    }
    if any(
        type(data.get(key)) is not type(value) or data.get(key) != value
        for key, value in expected.items()
    ):
        issues.append("native scope identity/denominator/source hashes mismatch")
    # Discovery can faithfully expose unknown scope and assign its unresolved
    # responsibility to a later stage. That does not close the final scope.
    if inventory.parse_failures:
        issues.append("native parse failure")
    assignments = data.get("assignments")
    if not isinstance(assignments, list):
        assignments = []
        issues.append("native assignments missing")
    surfaces = {surface.declaration_id: surface for surface in inventory.surfaces}
    report_rows = typed_report.get("rows", [])
    if not isinstance(report_rows, list):
        report_rows = []
    report_ids = [row.get("declaration_id") for row in report_rows if isinstance(row, dict)]
    if (
        len(report_ids) != len(report_rows)
        or any(not isinstance(identity, str) for identity in report_ids)
        or Counter(report_ids) != Counter(surface.declaration_id for surface in inventory.surfaces)
    ):
        issues.append("typed native denominator has missing/duplicate/extra declarations")
    treatments = {
        row["declaration_id"]: row
        for row in report_rows
        if isinstance(row, dict) and isinstance(row.get("declaration_id"), str)
    }
    for identity, surface in surfaces.items():
        row = treatments.get(identity, {})
        if (
            type(row.get("declaration_occurrence")) is not int
            or row.get("declaration_occurrence") != surface.declaration_occurrence
            or row.get("context_sha256") != digest(asdict(surface))
        ):
            issues.append(f"typed native context/occurrence mismatch:{identity}")
    ids = [item.get("declaration_id") for item in assignments if isinstance(item, dict)]
    if (
        len(ids) != len(assignments)
        or any(not isinstance(item, str) for item in ids)
        or len(set(ids)) != len(ids)
        or set(ids) != set(surfaces)
    ):
        issues.append("native assignment denominator has missing/duplicate/extra declarations")
    missing = sorted(set(surfaces) - {item for item in ids if isinstance(item, str)})
    for item in assignments:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("declaration_id"), str)
            or item["declaration_id"] not in surfaces
        ):
            continue
        identity = item["declaration_id"]
        surface = surfaces[identity]
        context = json.loads(json.dumps(asdict(surface)))
        if item.get("context_sha256", digest(item.get("context"))) != digest(context) or (
            "context" in item and digest(item["context"]) != digest(context)
        ):
            issues.append(f"native context mismatch:{identity}")
        if item.get("stage") not in ("S1", "S2", "S3", "S4"):
            issues.append(f"native responsibility stage missing:{identity}")
        status = item.get("status")
        if status == "pending":
            remaining.append(identity)
            continue
        treatment = treatments.get(identity, {})
        protection = treatment.get("source_protection", {})
        protected = (
            isinstance(protection, dict)
            and protection.get("proven") is True
            and protection.get("status") == "retained"
            and protection.get("dependencies_closed") is True
            and protection.get("context_closed") is True
            and protection.get("issues") == []
        )
        active_unknown = treatment.get("active_unknown_usage") is not False
        refs = item.get("evidence_ids")
        implementation = (
            surface.legal
            and treatment.get("implemented_numeric") is True
            and _strings(refs, nonempty=True)
            and any(
                (f"mod/{surface.source}", surface.definition, surface.field)
                in evidence_consumers.get(ref, set())
                for ref in refs
            )
        )
        permitted = not active_unknown and (
            (status == "implemented" and implementation)
            or (status == "retained_native" and protected)
            or (status == "observation" and surface.capability == "observation" and protected)
            or (status == "engine_unexposed" and surface.capability == "unexposed" and protected)
        )
        if not permitted or not _strings(refs, nonempty=True) or not set(refs) <= known_evidence:
            issues.append(
                f"native disposition unproven (legal omissions cannot become unsupported):{identity}"
            )
    return {
        "ready": not issues,
        "closed": not issues and not remaining,
        "issues": issues,
        "remaining": sorted(set(remaining) | set(missing)),
        "missing_declarations": missing,
        "inventory_pending": inventory.pending_count,
        "unknown_scopes": list(inventory.unknown_scopes),
        "parse_failures": list(inventory.parse_failures),
    }


def _delivery(root: Path, value: Any, snapshot_hash: str) -> list[str]:
    """Verify local delivery bytes and captured external identities; never publish."""
    try:
        if not isinstance(value, dict) or value.get("status") != "verified":
            raise ValueError("delivery is pending")
        commit = value.get("merge_commit")
        if (
            not isinstance(commit, str)
            or not re.fullmatch(r"[a-f0-9]{40}", commit)
            or value.get("tag_commit") != commit
            or not isinstance(value.get("tag"), str)
            or not value["tag"]
        ):
            raise ValueError("merge/tag commit identity missing or inconsistent")
        capture = _json(_artifact(root, value.get("publication_result")))
        for key in (
            "merge_commit",
            "tag_commit",
            "tag",
            "pull_request_url",
            "release_url",
            "workshop_url",
        ):
            if not value.get(key) or capture.get(key) != value[key]:
                raise ValueError(f"publication output identity mismatch:{key}")
        if (
            capture.get("plan_version") != PLAN_VERSION
            or capture.get("source_snapshot_sha256") != snapshot_hash
            or capture.get("ci_status") != "passed"
            or capture.get("status") != "published"
        ):
            raise ValueError("publication/CI result is not current A2 delivery evidence")
        package = _artifact(root, value.get("zip"))
        _package_contract(package)
        checksum = _artifact(root, value.get("checksum"))
        if checksum.read_text(encoding="utf-8").strip().split() != [
            value["zip"]["sha256"],
            package.name,
        ]:
            raise ValueError("ZIP checksum output does not match actual package")
        deployment = value.get("deployment")
        if not isinstance(deployment, dict) or not isinstance(deployment.get("root"), str):
            raise ValueError("deployment root missing")
        target = Path(deployment["root"])
        if not target.is_absolute() or not target.is_dir():
            raise ValueError("actual deployment directory unavailable")
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if (
                not names
                or len({name.casefold() for name in names}) != len(names)
                or archive.testzip()
            ):
                raise ValueError("ZIP file identities/CRC invalid")
            for name in names:
                path = _path(target, name)
                if path.read_bytes() != archive.read(name):
                    raise ValueError(f"deployed bytes differ from ZIP:{name}")
            actual = {
                path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
            }
            if actual != set(names):
                raise ValueError("deployment has missing or residual files")
        launcher = deployment.get("launcher")
        if not isinstance(launcher, dict) or not isinstance(launcher.get("path"), str):
            raise ValueError("actual launcher output missing")
        launcher_path = Path(launcher["path"])
        if not launcher_path.is_absolute() or hashlib.sha256(
            launcher_path.read_bytes()
        ).hexdigest() != launcher.get("sha256"):
            raise ValueError("launcher output bytes mismatch")
        if target.as_posix() not in launcher_path.read_text(encoding="utf-8-sig").replace(
            "\\", "/"
        ):
            raise ValueError("launcher does not point at actual deployment")
        for field in ("workshop_copy", "rollback_instructions", "cleanup_result"):
            _artifact(root, value.get(field))
        cleanup = _json(_artifact(root, value["cleanup_result"]))
        if cleanup.get("status") != "complete" or cleanup.get("remaining") != []:
            raise ValueError("cleanup output remains incomplete")
    except (
        KeyError,
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
        AttributeError,
        zipfile.BadZipFile,
    ) as exc:
        return [f"delivery:{exc}"]
    return []


def _package_contract(path: Path) -> None:
    # Reuse exact current payload and generation checks: a valid historical ZIP
    # cannot sign a new candidate. Inputs rebuild in memory without file writes.
    from .. import distribution  # noqa: PLC0415, TID252

    distribution.validate_package(path)


def stage_report(root: Path, inventory: VanillaInventory | None) -> dict[str, Any]:
    """Read only A2 machine receipts; prose and legacy D receipts cannot close A2."""
    plan_issues: list[str] = []
    try:
        data = _json(root / RECEIPT_PATH)
    except (OSError, UnicodeError, ValueError) as exc:
        data = {}
        plan_issues.append(f"A2 machine receipt unavailable:{exc}")
    snapshot = source_snapshot(root)
    snapshot_hash = digest(snapshot)
    if (
        data.get("schema") != 1
        or type(data.get("schema")) is not int
        or data.get("plan_version") != PLAN_VERSION
    ):
        plan_issues.append("A2 schema/plan identity mismatch")
    for key, expected in (("plan", PLAN_PATH), ("subplan", SUBPLAN_PATH)):
        try:
            ref = data.get(key)
            if not isinstance(ref, dict) or ref.get("path") != expected.as_posix():
                raise ValueError(f"{key} path is not current A2 source")
            text = _artifact(root, ref).read_text(encoding="utf-8")
            if not re.search(r"\bA2\b", text):
                raise ValueError(f"{key} does not identify A2")
            required = STAGE_DEPENDENCIES if key == "plan" else {f"B{i}": () for i in range(9)}
            for identity in required:
                pattern = rf"^\| {identity} " if key == "plan" else rf"^## {identity} "
                if not re.search(pattern, text, re.MULTILINE):
                    raise ValueError(f"{key} fixed responsibility missing:{identity}")
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            plan_issues.append(str(exc))
    if not snapshot or data.get("source_snapshot") != snapshot:
        plan_issues.append("current production/test/check source snapshot mismatch")
    payloads: dict[str, dict[str, Any]] = {}
    raw_stages = data.get("stages")
    if not isinstance(raw_stages, list):
        raw_stages = []
        plan_issues.append("stages must be an exact list")
    ids = [item.get("stage_id") for item in raw_stages if isinstance(item, dict)]
    if (
        len(ids) != len(raw_stages)
        or any(not isinstance(item, str) for item in ids)
        or len(set(ids)) != len(ids)
        or set(ids) != set(STAGE_DEPENDENCIES)
    ):
        plan_issues.append("missing/duplicate/extra A2 stage identity")
    for item in raw_stages:
        if (
            isinstance(item, dict)
            and isinstance(item.get("stage_id"), str)
            and item["stage_id"] in STAGE_DEPENDENCIES
        ):
            payloads[item["stage_id"]] = item
    declared_closed = data.get("closed_stages")
    actual_closed = [
        stage for stage in STAGE_DEPENDENCIES if payloads.get(stage, {}).get("status") == "verified"
    ]
    if not _strings(declared_closed) or set(declared_closed) != set(actual_closed):
        plan_issues.append("closed_stages is not exactly the verified stage set")
    evidence_ids: list[Any] = []
    evidence_consumers: dict[str, set[tuple[str, str, str]]] = {}
    for stage, payload in payloads.items():
        records = payload.get("evidence")
        if not isinstance(records, list):
            plan_issues.append("stage evidence must be a list")
            continue
        evidence_ids.extend(item.get("evidence_id") for item in records if isinstance(item, dict))
        for item in records:
            if not isinstance(item, dict) or not isinstance(item.get("evidence_id"), str):
                continue
            if (
                item.get("requirement_id") not in STAGE_REQUIREMENTS[stage]
                or _evidence_kind(stage, item["requirement_id"]) != "pdx"
                or _evidence(
                    root, stage, item, snapshot_hash, inventory.scope_hash if inventory else ""
                )
            ):
                continue
            consumers = item.get("consumers", [])
            if not isinstance(consumers, list):
                continue
            evidence_consumers[item["evidence_id"]] = {
                (consumer["path"], consumer["definition"], consumer["field"])
                for consumer in consumers
                if isinstance(consumer, dict)
                and all(
                    isinstance(consumer.get(key), str) for key in ("path", "definition", "field")
                )
            }
    if any(not isinstance(item, str) or not item for item in evidence_ids) or len(
        set(evidence_ids)
    ) != len(evidence_ids):
        plan_issues.append("evidence IDs must be globally unique")
    typed_report, report_issues = _typed_native_report(
        root, data.get("native_scope"), inventory, snapshot_hash
    )
    native = _native_scope(
        data.get("native_scope"),
        inventory,
        {item for item in evidence_ids if isinstance(item, str)},
        typed_report,
        report_issues,
        evidence_consumers,
    )
    stages: dict[str, Any] = {}
    valid_evidence: set[str] = set()
    for stage, dependencies in STAGE_DEPENDENCIES.items():
        payload = payloads.get(stage, {})
        issues: list[str] = []
        row: dict[str, Any] = {
            "status": payload.get("status", "unknown"),
            "ready": False,
            "dependencies": list(dependencies),
            "issues": issues,
            "sha256": digest(payload) if payload else None,
            "scope_hash": payload.get("scope_hash"),
        }
        stages[stage] = row
        if payload.get("status") != "verified":
            issues.append(f"stage not verified:{payload.get('status', 'missing')}")
        if payload.get("directions") != list(STAGE_DIRECTIONS[stage]):
            issues.append("fixed direction responsibilities mismatch")
        if payload.get("dependencies") != list(dependencies):
            issues.append("fixed stage dependencies mismatch")
        if inventory is None or payload.get("scope_hash") != inventory.scope_hash:
            issues.append("stage/fresh native scope hash mismatch")
        issues.extend(
            f"unclosed {field}"
            for field in ("pending", "blocked", "unclassified", "failures")
            if payload.get(field) != []
        )
        try:
            receipt = StageReceipt(
                stage,
                payload["status"],
                payload["input_hashes"],
                tuple(payload["output_paths"]),
                tuple(payload["evidence_ids"]),
                tuple(payload["dependencies"]),
                tuple(payload["failures"]),
            )
            issues.extend(
                item
                for item in validate_receipt(receipt, strict=True)
                if not (stage == "S0" and item == "dependencies")
            )
            for name, sha in receipt.input_hashes.items():
                _artifact(root, {"path": name, "sha256": sha})
            issues.extend(
                f"output missing:{path}"
                for path in receipt.output_paths
                if not _path(root, path).is_file()
            )
        except (KeyError, OSError, UnicodeError, TypeError, ValueError, AttributeError) as exc:
            issues.append(f"stage receipt:{exc}")
        requirements = payload.get("requirements")
        if not isinstance(requirements, list):
            requirements = []
        requirements_ids = [
            item.get("requirement_id") for item in requirements if isinstance(item, dict)
        ]
        if (
            len(requirements_ids) != len(requirements)
            or any(not isinstance(item, str) for item in requirements_ids)
            or Counter(requirements_ids) != Counter(STAGE_REQUIREMENTS[stage])
        ):
            issues.append("missing/duplicate/extra strategic exit requirement")
        local_evidence = payload.get("evidence")
        if not isinstance(local_evidence, list):
            local_evidence = []
            issues.append("stage evidence must be a list")
        local_ids = [item.get("evidence_id") for item in local_evidence if isinstance(item, dict)]
        if payload.get("evidence_ids") != local_ids:
            issues.append("stage evidence identity list mismatch")
        for item in local_evidence:
            if (
                not isinstance(item, dict)
                or item.get("requirement_id") not in STAGE_REQUIREMENTS[stage]
            ):
                issues.append("invalid requirement evidence identity")
                continue
            problems = _evidence(
                root, stage, item, snapshot_hash, inventory.scope_hash if inventory else ""
            )
            issues.extend(problems)
            if not problems:
                valid_evidence.add(item["evidence_id"])
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            refs = requirement.get("evidence_ids")
            matching = {
                item["evidence_id"]
                for item in local_evidence
                if isinstance(item, dict)
                and item.get("requirement_id") == requirement.get("requirement_id")
            }
            if (
                requirement.get("status") != "verified"
                or not _strings(refs, nonempty=True)
                or set(refs) != matching
                or not set(refs) <= valid_evidence
            ):
                issues.append(
                    f"strategic exit lacks verified production witness:{requirement.get('requirement_id')}"
                )
        hashes = payload.get("dependency_hashes")
        if not isinstance(hashes, dict) or set(hashes) != set(dependencies):
            issues.append("dependency receipt hash identities mismatch")
            hashes = {}
        issues.extend(
            f"dependency not closed or stale:{dependency}"
            for dependency in dependencies
            if not stages[dependency]["ready"]
            or hashes.get(dependency) != digest(payloads.get(dependency, {}))
        )
        if not native["ready"] or (stage in {"S4", "S5", "S6"} and not native["closed"]):
            issues.append("native scope/responsibility closure incomplete")
        if stage == "S6":
            issues.extend(_delivery(root, data.get("delivery"), snapshot_hash))
        row["ready"] = not issues and not plan_issues
    # Dispositions must refer to valid evidence, not simply a declared ID.
    native = _native_scope(
        data.get("native_scope"),
        inventory,
        valid_evidence,
        typed_report,
        report_issues,
        evidence_consumers,
    )
    for stage, row in stages.items():
        if not native["ready"] or (stage in {"S4", "S5", "S6"} and not native["closed"]):
            row["ready"] = False
            if "native scope/responsibility closure incomplete" not in row["issues"]:
                row["issues"].append("native scope/responsibility closure incomplete")
    engineering_ready = (
        not plan_issues
        and native["closed"]
        and all(stages[stage]["ready"] for stage in ENGINEERING_STAGES)
    )
    ready = engineering_ready and stages["S6"]["ready"]
    return {
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "engineering_status": "ready" if engineering_ready else "blocked",
        "engineering_ready": engineering_ready,
        "plan_version": PLAN_VERSION,
        "receipt_path": RECEIPT_PATH.as_posix(),
        "dependency_source": PLAN_PATH.as_posix(),
        "plan_issues": plan_issues,
        "source_snapshot_sha256": snapshot_hash,
        "stages": stages,
        "native_scope": native,
        "missing_receipts": [stage for stage in STAGE_DEPENDENCIES if stage not in payloads],
        "unfinished_stages": [stage for stage, row in stages.items() if not row["ready"]],
        "engineering_unfinished_stages": [
            stage for stage in ENGINEERING_STAGES if not stages[stage]["ready"]
        ],
        "business_complete": False,
        "limits": [
            "receipt integrity is not an independent rerun or game behavior proof",
            "native preservation is separate from strategic functional exit witnesses",
            "external publication identities are captured outputs, not a live service check",
        ],
    }
