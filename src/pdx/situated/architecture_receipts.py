"""当前架构见证的来源、责任目录和工件身份核验。"""

from __future__ import annotations

import ast
import gzip
import hashlib
import json
import re
import zlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

PLAN_VERSION = "A2"
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


_ARCHIVE_MANIFESTS = (
    "docs/design/archive/manifest.json",
    "docs/design/archive/A2-manifest.json",
)
_ARCHIVE_MAX_BYTES = 16 * 1024 * 1024
