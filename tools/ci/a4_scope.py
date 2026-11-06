"""A4 discovery, migration and fail-closed scope gates; never signs A2/A3 history.

Bootstrap is an initial inventory, not the A4-1 full consumer investigation.
Terminal evidence is checked against live bytes and replayed pytest identities.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from pdx.config import ROOT as GAME_ROOT
from pdx.config import game_version
from tools.ci import a4_classify, a4_discovery, a4_history
from tools.ci.a4_schema import (
    INVESTIGATION,
    RECEIPT,
    REFERENCE,
    SCHEMA,
    STRINGS,
    check_shape,
    goal_stage,
    pending_row,
)
from tools.ci.run_check import interpreter

ROOT = Path(__file__).resolve().parents[2]
LEDGER = "docs/design/A4实施台账.json"
PLANS = ("docs/design/架构主计划.md", "docs/design/架构子计划.md", "docs/design/架构深化计划.md")
MANIFEST = "docs/design/archive/A3-manifest.json"
SNAPSHOT = "research/vanilla-ai/1.15.0/structural.compact.json"
SUMMARY = "research/vanilla-ai/1.15.0/update-summary.json"
DISCOVERY_INDEX = "docs/design/A4发现源.json"
CANDIDATE = "e14028745e1563fdbbb34141c2ff2d2999d32f04"
PRODUCTION_BASE = "v3.2.0"
GATE_INPUTS: tuple[str, ...] = (
    "tools/ci/a4_scope.py",
    "tools/ci/a4_schema.py",
    "tools/ci/run_check.py",
    "tests/test_a4_scope.py",
    *a4_discovery.PROJECTOR_INPUTS,
    "tools/ci/a4_classify.py",
    "tests/test_a4_classify.py",
    "tests/test_a4_witness_arguments.py",
)
GATE_INPUTS = tuple(dict.fromkeys(GATE_INPUTS))
TERMINAL = {"verified", "retained", "unsupported", "indexed"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(root: Path, raw: str) -> Path:
    relative = PurePosixPath(raw)
    if not raw or "\\" in raw or ":" in raw or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe path: {raw}")
    path = (root / raw).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"unsafe path: {raw}")
    if not path.is_file():
        raise ValueError(f"missing path: {raw}")
    return path


class Sources:
    """Parse and hash each shared input once per gate, rather than once per row."""

    def __init__(self, root: Path, overrides: dict[str, bytes] | None = None):
        self.root = root
        self.bytes: dict[str, bytes] = dict(overrides or {})
        self.hashes: dict[str, str] = {}
        self.jsons: dict[str, Any] = {}
        self.python: dict[str, set[str]] = {}
        self.replayed: set[str] = set()

    def read(self, path: str) -> bytes:
        if path not in self.bytes:
            source = safe_path(self.root, path)
            if source.stat().st_size >= a4_discovery.MAX_FILE_BYTES:
                raise ValueError(f"oversized controlled source: {path}")
            self.bytes[path] = source.read_bytes()
        return self.bytes[path]

    def json(self, path: str) -> Any:
        if path not in self.jsons:
            self.jsons[path] = a4_discovery.strict_json(self.read(path))
        return self.jsons[path]

    def hash(self, path: str) -> str:
        """Hash each session's immutable byte snapshot once; identities still validate separately."""
        if path not in self.hashes:
            self.hashes[path] = sha(self.read(path))
        return self.hashes[path]

    def reference(
        self, path: str, identity: str = "whole_file", kind: str = "file"
    ) -> dict[str, str]:
        return {"path": path, "sha256": self.hash(path), "identity": identity, "kind": kind}

    def verify(self, reference: dict[str, str]) -> None:
        path = reference["path"]
        if reference["sha256"] != self.hash(path):
            raise ValueError(f"stale hash: {path}")
        identity = reference["identity"]
        if reference["kind"] == "file":
            if identity != "whole_file":
                raise ValueError(f"file identity must be whole_file: {path}")
        elif reference["kind"] == "json":
            node = self.json(path)
            for token in identity.split("/"):
                part = token.replace("~1", "/").replace("~0", "~")
                if not isinstance(node, dict) or part not in node:
                    raise ValueError(f"missing json identity: {path}:{identity}")
                node = node[part]
        else:
            if path not in self.python:
                tree = ast.parse(self.read(path), filename=path)
                names = set()
                for item in tree.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        names.add(item.name)
                        if isinstance(item, ast.ClassDef):
                            names.update(
                                f"{item.name}::{child.name}"
                                for child in item.body
                                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                            )
                self.python[path] = names
            if identity not in self.python[path]:
                raise ValueError(f"missing python identity: {path}:{identity}")


def git(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(
            f"git input failed: {arguments}: {result.stderr.decode('utf8', 'replace')}"
        )
    return result.stdout


def original_a3(sources: Sources) -> tuple[dict[str, str], list[dict[str, Any]]]:
    manifest = sources.json(MANIFEST)
    matches = [
        item for item in manifest["originals"] if item["path"] == "docs/design/A3实施台账.toml"
    ]
    if len(matches) != 1:
        raise ValueError("A3 original manifest identity missing")
    item = matches[0]
    path = "docs/design/archive/" + item["object"]
    raw = gzip.decompress(sources.read(path))
    if sha(raw) != item["sha256"] or len(raw) != item["bytes"]:
        raise ValueError("A3 original byte hash mismatch")
    old = tomllib.loads(raw.decode("utf8"))["obligations"]
    if len(old) != 96:
        raise ValueError("A3 original obligations coverage must remain 96")
    return sources.reference(path), old


def original_row_hashes(sources: Sources, original: dict[str, str]) -> dict[str, str]:
    raw = gzip.decompress(sources.read(original["path"]))
    blocks = re.split(rb"(?m)(?=^\[\[obligations\]\])", raw)[1:]
    result = {}
    for block in blocks:
        item = tomllib.loads(block.decode("utf8"))["obligations"][0]
        result[item["id"]] = sha(block)
    return result


def plan_goals(sources: Sources) -> dict[str, str]:
    goals = {}
    patterns = (
        r"^\| (G\d{2})\b",
        r"^\| (B\d{2}\.\d+)\b",
        r"^\| (R\d{2})\b",
        r"^\| (U\d{2})\b",
        r"^## (C\d+)\b",
    )
    for path in PLANS:
        text = sources.read(path).decode("utf8")
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.MULTILINE):
                goals[match[1]] = path
    expected = {"G": 8, "B": 64, "R": 12, "U": 10, "C": 11}
    if Counter(key[0] for key in goals) != expected:
        raise ValueError("plan goal discovery coverage changed; review scope before bootstrap")
    return goals


def production_paths(root: Path) -> list[str]:
    return a4_history.production_paths(git, root)


def changes(root: Path) -> list[dict[str, Any]]:
    return a4_history.changes(git, root, CANDIDATE, PRODUCTION_BASE)


def historical_reference(sources: Sources, path: str) -> dict[str, str]:
    if (sources.root / path).is_file():
        return sources.reference(path)
    token = path.replace("~", "~0").replace("/", "~1")
    return sources.reference(a4_history.HISTORY_PATH, f"paths/{token}", "json")


def discover(
    sources: Sources, old: list[dict[str, Any]], delta: list[dict[str, str]]
) -> list[dict[str, Any]]:
    found = []

    def add(origin: str, identity: str, path: str, goals: list[str]) -> None:
        found.append(
            {
                "id": f"D:{origin}:{identity}",
                "kind": "discovery",
                "origin": origin,
                "identity": identity,
                "source": historical_reference(sources, path),
                "goal_ids": goals,
            }
        )

    for goal, path in sorted(plan_goals(sources).items()):
        add("goal", goal, path, [goal])
    for item in old:
        add("a3", item["id"], MANIFEST, ["G01", "C1"])
    for item in delta:
        add("candidate", item["id"], item["path"], ["G01", "C1"])
    for section in sorted(sources.json(SNAPSHOT)["域"]):
        add("snapshot_section", section, SNAPSHOT, ["G02", "C1", "C10"])
    for path in sorted(
        set(production_paths(sources.root))
        | set(sources.json(a4_history.HISTORY_PATH)["registered_paths"])
    ):
        add("production_input", path, path, ["G01", "G07", "C1"])
    return found


def responsibility_stage(discovery: dict[str, Any], old: dict[str, Any]) -> tuple[str, str]:
    """Derive an intake's duty from its independent origin and original objective."""
    origin, identity = discovery["origin"], discovery["identity"]

    def original_stage(target: str) -> tuple[str, str]:
        # A3 C5/C6/C9 have different titles from the current C pages. Preserve
        # their frozen objectives instead of assigning by numeric suffix alone.
        stages = {
            "C1.1": "A4-1",
            "C2.1": "A4-2",
            "C3.1": "A4-2",
            "C4.1": "A4-2",
            "C5.1": "A4-2",
            "C6.1": "A4-4",
            "C7.1": "A4-5",
            "C8.1": "A4-6",
            "C9.1": "A4-6",
        }
        return stages.get(
            target, goal_stage(target.split(".", 1)[0])
        ), "index" if target == "C1.1" else "product"

    if origin == "a3":
        original = old[identity]
        return (
            ("A4-1", "current_migration")
            if original["status"] == "implemented"
            else original_stage(identity)
        )
    if origin == "goal":
        return goal_stage(identity), "index" if identity in {
            "G01",
            "G02",
            "G07",
            "C1",
        } else "product"
    if origin == "classification_product_mapping":
        family, target = identity.split(":", 1)
        if family == "migration_acceptance":
            return "A4-1", "current_migration"
        if family == "predecessors":
            return original_stage(target)
        if family == "targets":
            return (
                ("A4-1", "index")
                if target in {"G01", "G02", "G07"}
                else (goal_stage(target), "product")
            )
        raise ValueError("unknown classification responsibility")
    return "A4-1", "index"


def validate_responsibility_stages(
    rows: dict[str, Any],
    discoveries: dict[str, Any],
    old: dict[str, Any],
    duties: dict[str, Any] | None = None,
) -> None:
    for row in rows.values():
        required = {
            responsibility_stage(discoveries[identity], old)[0] for identity in row["discovery_ids"]
        }
        if required != {row["stage"]}:
            raise ValueError("wrong claimed responsibility stage; split mixed index/product duties")
    if duties is not None and (
        set(rows) != set(duties)
        or any(
            row["stage"] != duties[identity]["after"]
            or set(row["discovery_ids"]) != set(duties[identity]["discovery_ids"])
            for identity, row in rows.items()
        )
    ):
        raise ValueError("source-bound stage/intake responsibility mapping mismatch")


def installation_identity(game_root: Path) -> dict[str, Any]:
    version = game_version(game_root)
    if not version or "caligula_branch" not in version:
        raise ValueError("installation version identity missing")
    exe = game_root / "binaries/victoria3.exe"
    manifest = game_root.parents[1] / "appmanifest_529340.acf"
    if not exe.is_file() or not manifest.is_file():
        raise ValueError("installation EXE or Steam manifest missing")
    buildid = re.search(r'"buildid"\s+"(\d+)"', manifest.read_text(encoding="utf8"))
    if buildid is None:
        raise ValueError("Steam buildid missing")
    trees = []
    for relative in (
        "game/common",
        "game/events",
        "game/dlc",
        "game/dlc_metadata",
        "jomini",
        "clausewitz",
    ):
        directory = game_root / relative
        if not directory.is_dir():
            raise ValueError(f"installation input directory missing: {relative}")
        records = [
            f"{path.relative_to(game_root).as_posix()}\0{sha(path.read_bytes())}\n"
            for path in sorted(directory.rglob("*"))
            if path.is_file()
            and path.suffix.lower() in {".txt", ".yml", ".json", ".gui", ".asset", ".info"}
        ]
        trees.append(
            {"path": relative, "count": len(records), "sha256": sha("".join(records).encode())}
        )
    return {
        "root": game_root.as_posix(),
        "version": [{"key": k, "value": v} for k, v in sorted(version.items())],
        "exe_sha256": sha(exe.read_bytes()),
        "steam_manifest_sha256": sha(manifest.read_bytes()),
        "steam_buildid": buildid[1],
        "jomini_revision": "unknown: no separately exposed revision recorded; input trees hashed",
        "trees": trees,
    }


def bootstrap(
    root: Path,
    game_root: Path | None = None,
    *,
    frozen_installation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a scope ledger; explicit offline identities never certify a live installation."""
    if frozen_installation is not None and game_root is not None:
        raise ValueError("frozen installation and live game root cannot be combined")
    sources = Sources(root)
    original, old = original_a3(sources)
    delta = changes(root)
    discoveries = discover(sources, old, delta)
    installed = (
        frozen_installation
        if frozen_installation is not None
        else installation_identity(game_root or GAME_ROOT)
    )
    check_shape(installed, SCHEMA["freeze"]["installation"])
    version = {item["key"]: item["value"] for item in installed["version"]}
    target = version["caligula_branch"].removeprefix("release/")
    if sources.json(SNAPSHOT)["版本"] != version:
        raise ValueError("installation drift: update target plans and source snapshot first")
    investigation_refs, reports, catalogs = load_investigations(sources, target)
    discoveries.extend(item for report in reports for item in report["discoveries"])
    rows = [
        pending_row(item, target) for item in discoveries if item["origin"] != "native_projection"
    ]
    old_by_id = {item["id"]: item for item in old}
    for row, item in zip(
        rows, [d for d in discoveries if d["origin"] != "native_projection"], strict=True
    ):
        row["stage"] = responsibility_stage(item, old_by_id)[0]
    compact = compact_pending(catalogs, discoveries)
    original_hash = sha(gzip.decompress(sources.read(original["path"])))
    row_hashes = original_row_hashes(sources, original)
    migrations = [
        {
            "old_id": item["id"],
            "old_status": item["status"],
            "old_row_sha256": row_hashes[item["id"]],
            "original_sha256": original_hash,
            "decision": "reverify",
            "row_ids": [f"O:D:a3:{item['id']}"],
            "reason": f"旧范围「{item['title']}」({item['parent']})；当前源{', '.join(item['source_paths'])}；"
            f"原消费者调查：{item['consumer_investigation']}；1.14.5→{target}待重证，不继承{item['status']}。",
        }
        for item in old
    ]
    candidates = [
        {
            **item,
            "decision": "reverify",
            "row_ids": [f"O:D:candidate:{item['id']}"],
            "reason": f"{item['path']}：接收e140287候选及{PRODUCTION_BASE}至当前生产差异；当前输入hash已冻结，1.15消费者/父结构/关闭路径未重验。",
        }
        for item in delta
    ]
    inputs = sorted(
        {
            MANIFEST,
            SNAPSHOT,
            SUMMARY,
            DISCOVERY_INDEX,
            original["path"],
            *production_paths(root),
            *GATE_INPUTS,
            a4_history.HISTORY_PATH,
        }
    )
    data = {
        "schema": 2,
        "plan": "A4",
        "freeze": {
            "target_version": target,
            "plan_inputs": [sources.reference(path) for path in PLANS],
            "inputs": [sources.reference(path) for path in inputs],
            "a3_original": original,
            "candidate_commit": CANDIDATE,
            "production_base": PRODUCTION_BASE,
            "installation": installed,
        },
        "inventory": {
            "stage": "A4-1",
            "status": "pending",
            "reason": "初始发现只涵盖计划种子、A3逐项、Git候选/生产差异、快照全部section及生产输入；独立全量消费者/引用/DLC/角色/对象与新增联动调查尚未执行。",
            "scanned_directories": [item["path"] for item in installed["trees"]],
            "parse_failures": [],
            "unrecognized": ["A4-1 full parsing and reference crosscheck pending"],
            "duplicates": [],
            "crosscheck_receipts": [],
            "investigation_sources": investigation_refs,
            "dlc_ids": [],
        },
        "discoveries": discoveries,
        "rows": rows,
        "pending_rows": compact,
        "stale_history": [],
        "migrations": migrations,
        "candidate_changes": candidates,
        "receipts": [],
        "facts": [],
        "ports": [],
        "causes": [],
    }
    merge_inventory(data, reports)
    check_shape(data, SCHEMA)
    return data


def unique(items: list[dict[str, Any]], key: str, name: str) -> dict[str, dict[str, Any]]:
    result = {}
    for item in items:
        identity = item[key]
        if identity in result:
            raise ValueError(f"duplicate {name} ID: {identity}")
        result[identity] = item
    return result


def investigation_references(
    sources: Sources, references: list[dict[str, str]]
) -> list[dict[str, str]]:
    index = sources.json(DISCOVERY_INDEX)
    check_shape(index, {"schema": {1}, "plan": {"A4"}, "investigations": [REFERENCE]})
    expected = unique(index["investigations"], "path", "investigation source")
    actual = unique(references, "path", "investigation source")
    if actual != expected:
        raise ValueError("independent discovery source coverage mismatch")
    return references


def load_investigations(
    sources: Sources, version: str, references: list[dict[str, str]] | None = None
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The independent index is authoritative for bootstrap, validation and reconciliation."""
    index = sources.json(DISCOVERY_INDEX)
    check_shape(index, {"schema": {1}, "plan": {"A4"}, "investigations": [REFERENCE]})
    refs = investigation_references(
        sources, index["investigations"] if references is None else references
    )
    if a4_discovery.REPORT_PATH not in {ref["path"] for ref in refs}:
        raise ValueError("independent native projection report coverage missing")
    reports, catalogs = [], []
    for reference in refs:
        sources.verify(reference)
        report = sources.json(reference["path"])
        check_shape(report, INVESTIGATION)
        if report["source_version"] != version:
            raise ValueError("investigation mixed source version")
        if not report["source_inputs"] or not report["scanned_directories"]:
            raise ValueError("independent investigation source identity missing")
        for ref in report["source_inputs"]:
            if ref["path"] in {reference["path"], DISCOVERY_INDEX, LEDGER}:
                raise ValueError("self-referential investigation hash cycle")
            sources.verify(ref)
        if reference["path"] == a4_discovery.REPORT_PATH:
            catalogs.append(a4_discovery.validate_projection(sources, report))
        elif reference["path"] == a4_classify.REPORT_PATH:
            a4_classify.validate_classification(sources, report)
        elif any(item["origin"] == "native_projection" for item in report["discoveries"]):
            raise ValueError("native projection report identity mismatch")
        reports.append(report)
    return refs, reports, catalogs


def compact_pending(
    catalogs: list[dict[str, Any]], discoveries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = unique(discoveries, "id", "discovery")
    return [
        {
            "domain": group,
            "discovery_ids": members,
            "goal_ids": sorted({goal for member in members for goal in by_id[member]["goal_ids"]}),
            "source": by_id[members[0]]["source"],
        }
        for catalog in catalogs
        for group, members in catalog["groups"].items()
    ]


def expanded_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact records can only express pending; terminal states require explicit full ROWs."""
    rows = list(data["rows"])
    for item in data["pending_rows"]:
        discovery = {
            "id": item["domain"],
            "identity": item["domain"],
            "origin": "native_projection",
            "goal_ids": item["goal_ids"],
            "source": item["source"],
        }
        row = pending_row(discovery, data["freeze"]["target_version"])
        row.update(
            id=f"O:{item['domain']}", discovery_ids=item["discovery_ids"], domain=item["domain"]
        )
        rows.append(row)
    return rows


def validate_unresolved(rows: dict[str, dict[str, Any]], catalogs: list[dict[str, Any]]) -> None:
    mapped_domains: dict[str, set[str]] = {}
    for row in rows.values():
        for identity in row["discovery_ids"]:
            mapped_domains.setdefault(identity, set()).add(row["domain"])
    for catalog in catalogs:
        members = {
            identity
            for group in catalog["unresolved_groups"]
            for identity in catalog["groups"][group]
        }
        for row in rows.values():
            if members.intersection(row["discovery_ids"]) and conclusion(row) in TERMINAL:
                raise ValueError("unresolved aggregate/native member cannot be terminal")
        for domain, identities in catalog["groups"].items():
            if any(domain not in mapped_domains.get(identity, set()) for identity in identities):
                raise ValueError("raw-to-canonical triage mapping coverage mismatch")


def merge_inventory(data: dict[str, Any], reports: list[dict[str, Any]]) -> None:
    inventory = data["inventory"]
    for key in ("scanned_directories", "parse_failures", "unrecognized", "duplicates", "dlc_ids"):
        inventory[key] = sorted({item for report in reports for item in report[key]})
    inventory["status"] = "pending"
    inventory["reason"] = (
        "完整独立发现已登记；未知分类、生产writer调查、crosscheck与产品功能仍pending；投影不授予原生权限。"
    )


def validate_crosschecks(
    sources: Sources, data: dict[str, Any], reports: list[dict[str, Any]], stage: str
) -> None:
    receipts = unique(data["receipts"], "id", "receipt")
    required_ids = {identity for report in reports for identity in report["crosscheck_receipt_ids"]}
    if required_ids != set(data["inventory"]["crosscheck_receipts"]):
        raise ValueError("inventory/report crosscheck receipt mapping mismatch")
    if stage != "A4-0" and not required_ids:
        raise ValueError("independent crosscheck explicitly pending")
    for reference, report in zip(data["inventory"]["investigation_sources"], reports, strict=True):
        for identity in report["crosscheck_receipt_ids"]:
            if identity not in receipts:
                raise ValueError("missing inventory crosscheck receipt")
            needed = [reference, *report["source_inputs"]]
            # Selection is a controlled report input, never an arbitrary receipt-declared expected set.
            witnesses = [
                ref
                for ref in report["source_inputs"]
                if ref["kind"] == "python" and ref["path"].startswith("tests/")
            ]
            if not witnesses:
                raise ValueError("crosscheck lacks independent projector witness identities")
            nodes = [f"{ref['path']}::{ref['identity']}" for ref in witnesses]
            verify_receipt(sources, receipts[identity], needed, nodes)


def delivery_gate(stage: str) -> None:
    """Fail closed until actual external Git/CI/release/deployment verification exists."""
    if stage in {"A4-8", "all"}:
        raise ValueError(
            "A4-8 external delivery verification is not implemented; Git/CI/tag/Release/deployment evidence pending"
        )


def inventory_mappings(
    rows: dict[str, dict[str, Any]], reports: list[dict[str, Any]], stage: str
) -> None:
    """Index complete existence mappings even at A4-0; terminal checks follow selection."""
    indexes: dict[str, dict[str, list[dict[str, Any]]]] = {"consumer": {}, "writer": {}}
    for row in rows.values():
        for kind, index in indexes.items():
            identities = {row["domain"]}
            if kind == "consumer":
                identities.add(row["consumer"]["value"])
            else:
                identities.update(
                    f"{binding['writer']['path']}::{binding['writer']['identity']}"
                    for binding in row["writer_bindings"]
                )
            for identity in identities:
                index.setdefault(identity, []).append(row)
    for report in reports:
        for kind, index in indexes.items():
            for identity in report[f"{kind}_ids"]:
                matched = index.get(identity, [])
                if not matched:
                    raise ValueError(f"independent {kind} mapping coverage missing: {identity}")
                for row in matched:
                    if (stage in {"all", "A4-7", "A4-8"} or row["stage"] <= stage) and conclusion(
                        row
                    ) not in TERMINAL:
                        raise ValueError(f"nonterminal {kind} in selected stage: {identity}")


def conclusion(row: dict[str, Any]) -> str:
    state = (row["disposition"], row["interface_status"], row["obligation_status"])
    if state == ("implement", "verified", "verified"):
        return "verified"
    if (
        state[0] == "retain_native"
        and state[1] in {"verified", "native_handled"}
        and state[2] == "retained"
    ):
        return "retained"
    if state == ("unsupported", "unsupported", "retained"):
        return "unsupported"
    if state[2] in {"verified", "retained"}:
        raise ValueError(f"invalid terminal state combination: {row['id']}")
    return "nonterminal"


def witness_reference(sources: Sources, node_id: str) -> dict[str, str]:
    parts = node_id.split("::")
    if (
        len(parts) < 2
        or not parts[0].startswith("tests/")
        or not parts[-1].split("[")[0].startswith("test_")
    ):
        raise ValueError(f"witness must reference actual tests identity: {node_id}")
    identity = "::".join(parts[1:]).split("[")[0]
    reference = sources.reference(parts[0], identity, "python")
    sources.verify(reference)
    return reference


def run_tests(
    root: Path, nodes: list[str], bindings: list[dict[str, str]], output: Path
) -> dict[str, Any]:
    """Run exact identities, preserving failures/skips; never accepts caller supplied passed."""
    sources = Sources(root)
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("witness selection is empty or duplicated")
    for node in nodes:
        witness_reference(sources, node)
    for reference in bindings:
        sources.verify(reference)
    output.mkdir(parents=True, exist_ok=True)
    junit = output / "junit.xml"
    python = interpreter(root)
    command = [
        str(python),
        "-B",
        "-X",
        "utf8",
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "-q",
        "-p",
        "no:cacheprovider",
        *nodes,
        f"--junitxml={junit}",
    ]
    if len(subprocess.list2cmdline(command)) > 24000:
        # Pytest expands one argument per line. A single Windows command is
        # limited to 32767 characters, independently of the number of cases.
        if any("\n" in node or "\r" in node for node in nodes):
            raise ValueError("witness node contains an argument-file newline")
        arguments = output / "selection.args"
        arguments.write_text("\n".join(nodes) + "\n", encoding="utf8", newline="\n")
        bindings = [*bindings, sources.reference(arguments.relative_to(root).as_posix())]
        command = [*command[:11], f"@{arguments}", command[-1]]
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
    }
    process = subprocess.run(command, cwd=root, env=env, capture_output=True, check=False)
    (output / "pytest.log").write_bytes(process.stdout + process.stderr)
    if not junit.is_file():
        raise ValueError("witness runner produced no JUnit")
    passed, failed = junit_results(junit)
    # Re-read after the process; a passing run during source mutation is stale.
    after = Sources(root)
    for reference in bindings:
        after.verify(reference)
    return {
        "schema": 1,
        "id": sha(json.dumps([nodes, bindings], sort_keys=True).encode()),
        "command": command,
        "selection": nodes,
        "exit_code": process.returncode,
        "junit": {
            "path": junit.relative_to(root).as_posix(),
            "sha256": sha(junit.read_bytes()),
            "identity": "whole_file",
            "kind": "file",
        },
        "bindings": bindings,
        "passed": passed,
        "failed": failed,
    }


def junit_results(path: Path) -> tuple[list[str], list[str]]:
    tree = ET.parse(path)
    passed: list[str] = []
    failed: list[str] = []
    for case in tree.iter("testcase"):
        classname = case.attrib.get("classname", "").split(".")
        test_index = next(
            (i for i, value in enumerate(classname) if value.startswith("test_")), None
        )
        if test_index is None:
            raise ValueError("JUnit lacks actual test identity")
        module = "/".join(classname[: test_index + 1]) + ".py"
        suffix = "::".join([*classname[test_index + 1 :], case.attrib["name"]])
        node = f"{module}::{suffix}"
        (
            failed
            if any(child.tag in {"failure", "error", "skipped"} for child in case)
            else passed
        ).append(node)
    return passed, failed


def witness_command_refs(sources: Sources, receipt: dict[str, Any]) -> list[dict[str, str]]:
    """Accept only the exact canonical pytest argv or its hash-bound argument file."""
    fixed_prefix = [
        "-B",
        "-X",
        "utf8",
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    command, selection = receipt["command"], receipt["selection"]
    if (
        not command
        or Path(command[0]).resolve() != interpreter(sources.root).resolve()
        or not command[-1].startswith("--junitxml=")
        or any("\n" in node or "\r" in node for node in selection)
    ):
        raise ValueError("receipt command / selection mismatch")
    arguments = command[1:-1]
    if arguments == [*fixed_prefix, *selection]:
        return []
    if (
        arguments[: len(fixed_prefix)] != fixed_prefix
        or len(arguments) != len(fixed_prefix) + 1
        or not arguments[-1].startswith("@")
    ):
        raise ValueError("receipt command / selection mismatch")
    path = Path(arguments[-1][1:]).resolve()
    if not path.is_relative_to(sources.root.resolve()):
        raise ValueError("receipt argument file escapes repository")
    relative = path.relative_to(sources.root).as_posix()
    reference = sources.reference(relative)
    if reference not in receipt["bindings"] or sources.read(relative) != (
        "\n".join(selection) + "\n"
    ).encode("utf8"):
        raise ValueError("receipt argument file / selection hash mismatch")
    return [reference]


def verify_receipt(
    sources: Sources, stub: dict[str, str], needed: list[dict[str, str]], nodes: list[str]
) -> None:
    reference = {
        "path": stub["path"],
        "sha256": stub["sha256"],
        "kind": "file",
        "identity": "whole_file",
    }
    sources.verify(reference)
    receipt = sources.json(stub["path"])
    check_shape(receipt, RECEIPT)
    if (
        not receipt["command"]
        or Path(receipt["command"][0]).resolve() != interpreter(sources.root).resolve()
    ):
        raise ValueError("receipt interpreter does not match the controlled project interpreter")
    if receipt["id"] != stub["id"] or receipt["exit_code"] != 0 or receipt["failed"]:
        raise ValueError("failed test receipt")
    selection = receipt["selection"]
    if (
        set(nodes) - set(selection)
        or len(selection) != len(set(selection))
        or set(receipt["passed"]) != set(selection)
    ):
        raise ValueError("witness selection / passed identity mismatch")
    sources.verify(receipt["junit"])
    passed, failed = junit_results(safe_path(sources.root, receipt["junit"]["path"]))
    if failed or set(passed) != set(selection):
        raise ValueError("failed JUnit or missing witness")
    expected = {json.dumps(ref, sort_keys=True) for ref in needed}
    actual = {json.dumps(ref, sort_keys=True) for ref in receipt["bindings"]}
    if expected - actual:
        raise ValueError("receipt production/input/witness hash bindings mismatch")
    for binding in receipt["bindings"]:
        sources.verify(binding)
    for node in selection:
        witness = witness_reference(sources, node)
        if json.dumps(witness, sort_keys=True) not in actual:
            raise ValueError("receipt omits selected witness hash")
    # Stored passed/JUnit can be edited. Replay the exact live selection on every gate.
    witness_command_refs(sources, receipt)
    key = sha(json.dumps([selection, sorted(actual)], sort_keys=True).encode())
    if key not in sources.replayed:
        (sources.root / "tools/out").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="a4-replay-", dir=sources.root / "tools/out"
        ) as temporary:
            replay = run_tests(sources.root, selection, receipt["bindings"], Path(temporary))
        if replay["exit_code"] or replay["failed"] or set(replay["passed"]) != set(selection):
            raise ValueError("failed live witness replay")
        sources.replayed.add(key)


def terminal_evidence(
    row: dict[str, Any], sources: Sources, receipts: dict[str, dict[str, Any]], dlcs: list[str]
) -> None:
    state = conclusion(row)
    if state not in TERMINAL:
        return
    if not row["witness_paths"]:
        raise ValueError("terminal witness paths missing")
    if not row["input_hashes"] or not row["witnesses"] or not row["evidence_hashes"]:
        raise ValueError(f"terminal evidence missing: {row['id']}")
    for field in (
        "object",
        "scope",
        "role",
        "consumer",
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
        "relation",
    ):
        if row[field]["status"] == "pending":
            raise ValueError(f"terminal evidence pending semantic field {field}: {row['id']}")
    configurations = row["configurations"]
    if (
        not configurations
        or not any(c["enabled"] and not c["dlc_ids"] for c in configurations)
        or not any(not c["enabled"] for c in configurations)
    ):
        raise ValueError("missing base/DLC/disabled configuration coverage")
    if set(dlcs) - {dlc for c in configurations for dlc in c["dlc_ids"]}:
        raise ValueError("missing applicable DLC configuration coverage")
    all_cases = set(row["case_ids"])
    covered = set()
    for dimension, coverage in row["applicability"].items():
        if coverage["status"] == "pending":
            raise ValueError(f"missing applicability coverage: {dimension}")
        if coverage["status"] == "applicable" and not coverage["case_ids"]:
            raise ValueError(f"missing applicability cases: {dimension}")
        if set(coverage["case_ids"]) - all_cases:
            raise ValueError("dangling applicability case ID")
        covered.update(coverage["case_ids"])
    for configuration in configurations:
        if not configuration["case_ids"] or set(configuration["case_ids"]) - all_cases:
            raise ValueError("missing configuration case coverage")
    if not all_cases or all_cases - covered:
        raise ValueError("missing case dimension coverage")
    witnesses = unique(row["witnesses"], "node_id", "witness")
    witnessed = {case for item in witnesses.values() for case in item["case_ids"]}
    if witnessed != all_cases:
        raise ValueError("missing witness cases")
    refs = [*row["input_hashes"], *row["evidence_hashes"], *row["boundary_evidence"]]
    if state == "verified":
        if (
            not row["writer_bindings"]
            or not row["production_paths"]
            or not row["fact_ids"]
            or not row["port_ids"]
        ):
            raise ValueError("unwired writer / production / fact / port")
        for binding in row["writer_bindings"]:
            if (
                binding["object"] != row["object"]["value"]
                or not binding["fact_ids"]
                or not binding["port_ids"]
                or not binding["witness_ids"]
            ):
                raise ValueError("unwired writer object / fact / port / witness")
            if (
                set(binding["fact_ids"]) - set(row["fact_ids"])
                or set(binding["port_ids"]) - set(row["port_ids"])
                or set(binding["witness_ids"]) - set(witnesses)
            ):
                raise ValueError("dangling writer binding")
            if binding["production"]["path"] not in row["production_paths"] or not binding[
                "production"
            ]["path"].startswith("mod/"):
                raise ValueError("writer must bind actual Mod production")
            if binding["consumer"] not in row["input_hashes"]:
                raise ValueError("writer consumer missing exact input evidence")
            refs.extend(binding[key] for key in ("writer", "production", "consumer"))
    else:
        if not row["boundary_evidence"] or not any(
            ref["kind"] != "file" for ref in row["boundary_evidence"]
        ):
            raise ValueError("retain/unsupported exact boundary evidence missing")
        required = {"native_source", "parent_structure", "reference_closure", "disabled_path"}
        if state == "unsupported":
            required.add("interface_boundary")
        roles = {proof["role"] for proof in row["boundary_proofs"]}
        if required - roles:
            raise ValueError(
                "retain/unsupported boundary evidence lacks parent/closure/disabled/interface proof"
            )
        for proof in row["boundary_proofs"]:
            reference = proof["reference"]
            if (
                reference["kind"] != "json"
                or not reference["path"].startswith("research/vanilla-ai/")
                or len(reference["identity"].split("/")) < 3
            ):
                raise ValueError(
                    "boundary proof requires precise independently captured native identity"
                )
            refs.append(reference)
    for path in [*row["production_paths"], *row["witness_paths"]]:
        if path not in {ref["path"] for ref in refs} and path not in {
            node.split("::")[0] for node in witnesses
        }:
            raise ValueError("unhashed production / witness path")
    refs.extend(witness_reference(sources, node) for node in witnesses)
    for ref in refs:
        sources.verify(ref)
    needed = list({json.dumps(ref, sort_keys=True): ref for ref in refs}.values())
    grouped: dict[str, list[str]] = {}
    for node, witness in witnesses.items():
        grouped.setdefault(witness["receipt_id"], []).append(node)
    for identity, nodes in grouped.items():
        if identity not in receipts:
            raise ValueError("missing actual witness run receipt")
        verify_receipt(sources, receipts[identity], needed, nodes)


def validate(
    data: dict[str, Any],
    root: Path,
    *,
    stage: str = "all",
    check_installation: bool = False,
    source_overrides: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    check_shape(data, SCHEMA)
    if stage not in {"all", *(f"A4-{number}" for number in range(9))}:
        raise ValueError("unknown A4 stage")
    sources = Sources(root, source_overrides)
    a4_history.verify_history(sources, git, CANDIDATE, PRODUCTION_BASE)
    freeze = data["freeze"]
    if freeze["candidate_commit"] != CANDIDATE or freeze["production_base"] != PRODUCTION_BASE:
        raise ValueError("candidate / production base identity mismatch")
    original, old = original_a3(sources)
    if freeze["a3_original"] != original:
        raise ValueError("A3 original hash identity mismatch")
    for ref in [*freeze["plan_inputs"], *freeze["inputs"]]:
        sources.verify(ref)
    expected_inputs = {
        MANIFEST,
        SNAPSHOT,
        SUMMARY,
        DISCOVERY_INDEX,
        original["path"],
        *production_paths(root),
        *GATE_INPUTS,
        a4_history.HISTORY_PATH,
    }
    if {ref["path"] for ref in freeze["inputs"]} != expected_inputs or {
        ref["path"] for ref in freeze["plan_inputs"]
    } != set(PLANS):
        raise ValueError("freeze input coverage mismatch")
    version = {item["key"]: item["value"] for item in freeze["installation"]["version"]}
    if sources.json(SNAPSHOT)["版本"] != version or freeze["target_version"] != version[
        "caligula_branch"
    ].removeprefix("release/"):
        raise ValueError("mixed target version identity")
    if (
        check_installation
        and installation_identity(Path(freeze["installation"]["root"])) != freeze["installation"]
    ):
        raise ValueError("live installation identity hash drift")
    delta = changes(root)
    expected_discoveries = discover(sources, old, delta)
    _, investigations, catalogs = load_investigations(
        sources, freeze["target_version"], data["inventory"]["investigation_sources"]
    )
    checkpoint = sources.jsons.get("a4:classification-checkpoint")
    if stage != "A4-0" and not checkpoint and data["inventory"]["status"] != "verified":
        raise ValueError(
            "nonterminal inventory: A4-1 independent full inventory is pending or unresolved"
        )
    expected_discoveries.extend(item for report in investigations for item in report["discoveries"])
    actual = unique(data["discoveries"], "id", "discovery")
    expected = unique(expected_discoveries, "id", "discovery")
    # Investigation additions are allowed but cannot replace any independently derived seed.
    if set(expected) != set(actual):
        raise ValueError("independent discovery coverage missing")
    for identity, discovery in expected.items():
        if actual[identity] != discovery:
            raise ValueError(f"discovery source identity drift: {identity}")
    for discovery in actual.values():
        sources.verify(discovery["source"])
    migrations = unique(data["migrations"], "old_id", "A3 migration")
    if set(migrations) != {item["id"] for item in old}:
        raise ValueError("A3 migration coverage missing")
    original_hash = sha(gzip.decompress(sources.read(original["path"])))
    row_hashes = original_row_hashes(sources, original)
    for item in old:
        migrated = migrations[item["id"]]
        if (
            migrated["old_status"] != item["status"]
            or migrated["original_sha256"] != original_hash
            or migrated["old_row_sha256"] != row_hashes[item["id"]]
        ):
            raise ValueError("A3 historical identity hash drift")
    candidate = unique(data["candidate_changes"], "id", "candidate")
    for item in candidate.values():
        a4_history.validate_state(item["checkpoint"])
        a4_history.validate_state(item["current"])
    if set(candidate) != {item["id"] for item in delta}:
        raise ValueError("candidate change coverage missing")
    for item in delta:
        if any(candidate[item["id"]][key] != value for key, value in item.items()):
            raise ValueError("candidate change identity hash drift")
    rows = unique(expanded_rows(data), "id", "row")
    duties = sources.jsons.get("a4:stage-assignments", {})
    old_by_id = {item["id"]: item for item in old}
    validate_responsibility_stages(rows, expected, old_by_id, duties if checkpoint else None)
    validate_unresolved(rows, catalogs)
    inventory_mappings(rows, investigations, "A4-0")
    mapped = {identity for row in rows.values() for identity in row["discovery_ids"]}
    if mapped != set(actual) or any(not row["discovery_ids"] for row in rows.values()):
        raise ValueError("discovery to obligation mapping coverage missing / dangling")
    goals = set(plan_goals(sources))
    if {goal for row in rows.values() for goal in row["goal_ids"]} != goals:
        raise ValueError("goal mapping coverage missing / dangling")
    related_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows.values():
        for discovery_id in row["discovery_ids"]:
            related_rows.setdefault(discovery_id, []).append(row)
    for discovery in actual.values():
        if set(discovery["goal_ids"]) - goals:
            raise ValueError("dangling discovery goal ID")
        related = related_rows[discovery["id"]]
        if set(discovery["goal_ids"]) - {goal for row in related for goal in row["goal_ids"]}:
            raise ValueError("discovery goal mapping lost")
    for mapping in [*migrations.values(), *candidate.values()]:
        if not mapping["row_ids"] or set(mapping["row_ids"]) - set(rows):
            raise ValueError("migration mapping coverage missing / dangling")
    for identity, mapping in migrations.items():
        if not any(
            f"D:a3:{identity}" in rows[row_id]["discovery_ids"] for row_id in mapping["row_ids"]
        ):
            raise ValueError("A3 migration lost original discovery mapping")
    for identity, mapping in candidate.items():
        if not any(
            f"D:candidate:{identity}" in rows[row_id]["discovery_ids"]
            for row_id in mapping["row_ids"]
        ):
            raise ValueError("candidate lost discovery mapping")
    receipts = unique(data["receipts"], "id", "receipt")
    for key in ("facts", "ports", "causes"):
        registry = unique(data[key], "id", key)
        for entry in registry.values():
            sources.verify(entry["source"])
        row_field = {"facts": "fact_ids", "ports": "port_ids", "causes": "causal_ids"}[key]
        if any(set(row[row_field]) - set(registry) for row in rows.values()):
            raise ValueError(f"dangling {key} ID")
    conclusions = {}
    for identity, row in rows.items():
        if row["source_version"] != freeze["target_version"]:
            raise ValueError("mixed row source version")
        for path in [*row["source_paths"], *row["production_paths"], *row["witness_paths"]]:
            safe_path(root, path)
        for reference in [*row["input_hashes"], *row["evidence_hashes"], *row["boundary_evidence"]]:
            sources.verify(reference)
        if set(row["dependency_ids"]) - set(rows):
            raise ValueError("dangling dependency ID")
        if set(row["predecessor_ids"]) - (set(rows) | set(migrations)):
            raise ValueError("dangling predecessor ID")
        conclusions[identity] = conclusion(row)
        terminal_evidence(row, sources, receipts, data["inventory"]["dlc_ids"])
        if checkpoint and duties[identity]["responsibility"] in {"index", "current_migration"}:
            # Computed enabling acceptance never mutates a product ROW or grants
            # a producer permission. Future product rows remain independently pending.
            conclusions[identity] = "indexed"
    visited, active = set(), set()

    def visit(identity: str) -> None:
        if identity in active:
            raise ValueError("dependency cycle")
        if identity in visited:
            return
        active.add(identity)
        for dependency in rows[identity]["dependency_ids"]:
            visit(dependency)
            if conclusions[identity] in TERMINAL and conclusions[dependency] not in TERMINAL:
                raise ValueError("unclosed dependency invalidates terminal acceptance")
        active.remove(identity)
        visited.add(identity)

    for identity in rows:
        visit(identity)
    selected = (
        set(rows)
        if stage in {"all", "A4-7", "A4-8"}
        else {identity for identity, row in rows.items() if row["stage"] <= stage}
    )
    for identity in sorted(selected):
        if conclusions[identity] not in TERMINAL:
            raise ValueError(f"nonterminal obligation blocks {stage}: {identity}")
    if (
        stage != "A4-0"
        and not checkpoint
        and (
            data["inventory"]["status"] != "verified"
            or data["inventory"]["parse_failures"]
            or data["inventory"]["unrecognized"]
            or data["inventory"]["duplicates"]
            or not data["inventory"]["crosscheck_receipts"]
        )
    ):
        raise ValueError("A4-1 independent full inventory is pending or unresolved")
    validate_crosschecks(sources, data, investigations, "A4-0" if checkpoint else stage)
    if stage != "A4-0":
        if not investigations or (
            not checkpoint
            and any(
                report["parse_failures"] or report["unrecognized"] or report["duplicates"]
                for report in investigations
            )
        ):
            raise ValueError("independent full inventory source gaps")
        if set(data["inventory"]["dlc_ids"]) != {
            dlc for report in investigations for dlc in report["dlc_ids"]
        }:
            raise ValueError("independent DLC coverage mismatch")
        inventory_mappings(rows, investigations, "A4-0" if checkpoint else stage)
    delivery_gate(stage)
    return {
        "plan": "A4",
        "gate": stage,
        "evidence": "static_check",
        "discoveries": len(actual),
        "disposition_rows": len(rows),
        "product_implemented": sum(
            row["obligation_status"] == "implemented" for row in rows.values()
        ),
        "product_verified": list(conclusions.values()).count("verified"),
        "retained": list(conclusions.values()).count("retained"),
        "unsupported": list(conclusions.values()).count("unsupported"),
        "witness_receipts": len(receipts),
        "delivery": "pending",
        "future_pending": sum(conclusions[key] == "nonterminal" for key in set(rows) - selected),
        "inventory": data["inventory"]["status"],
        "index_checkpoint": checkpoint or {"status": "pending"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bootstrap", "validate", "witness", "reconcile"))
    parser.add_argument(
        "--execute", action="store_true", help="Publish a validated reconcile; default is preview"
    )
    parser.add_argument("--ledger", default=LEDGER)
    parser.add_argument("--stage", default="all")
    parser.add_argument(
        "--request", help="JSON containing selection and bindings for witness execution"
    )
    parser.add_argument("--output", default="tools/out/a4-witness")
    args = parser.parse_args()
    try:
        if args.action == "bootstrap":
            if (
                Path(args.ledger).is_absolute()
                or ".." in PurePosixPath(args.ledger).parts
                or "\\" in args.ledger
                or ":" in args.ledger
            ):
                raise ValueError("unsafe ledger output path")
            target = (ROOT / args.ledger).resolve()
            if not target.is_relative_to(ROOT) or target.exists():
                raise ValueError("bootstrap refuses overwrite; review migration instead")
            data = bootstrap(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8", newline="\n"
            )
            print(json.dumps(validate(data, ROOT, stage="A4-0"), ensure_ascii=False))
        elif args.action == "reconcile":
            from tools.ci.a4_reconcile import publish, reconcile  # noqa: PLC0415

            data = a4_discovery.strict_json(safe_path(ROOT, args.ledger).read_bytes())
            candidate, summary = reconcile(data, ROOT)
            if args.execute:
                if args.ledger != LEDGER:
                    raise ValueError("execute reconcile requires the authoritative ledger path")
                publish(ROOT, candidate, Sources(ROOT).json(DISCOVERY_INDEX))
            else:
                output = ROOT / "tools/out/a4-reconcile-preview.json"
                a4_discovery.write_json(output, candidate)
            print(json.dumps(summary, ensure_ascii=False))
        elif args.action == "witness":
            if not args.request:
                raise ValueError("witness requires --request")
            request = json.loads(safe_path(ROOT, args.request).read_bytes())
            check_shape(request, {"selection": STRINGS, "bindings": [REFERENCE]})
            output = (ROOT / args.output).resolve()
            allowed = (ROOT / "tools/out").resolve()
            if not output.is_relative_to(allowed) or output == allowed:
                raise ValueError("witness output must be below tools/out")
            receipt = run_tests(ROOT, request["selection"], request["bindings"], output)
            (output / "receipt.json").write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf8",
                newline="\n",
            )
            print(
                json.dumps(
                    {"receipt": str(output / "receipt.json"), "exit_code": receipt["exit_code"]},
                    ensure_ascii=False,
                )
            )
            return 0 if receipt["exit_code"] == 0 and not receipt["failed"] else 1
        else:
            data = json.loads(safe_path(ROOT, args.ledger).read_bytes())
            print(
                json.dumps(
                    validate(data, ROOT, stage=args.stage, check_installation=True),
                    ensure_ascii=False,
                )
            )
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as error:
        print(f"A4 gate failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
