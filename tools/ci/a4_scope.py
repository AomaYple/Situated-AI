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
from tools.ci.a4_schema import (
    INVESTIGATION,
    RECEIPT,
    REFERENCE,
    SCHEMA,
    STRINGS,
    check_shape,
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
GATE_INPUTS = (
    "tools/ci/a4_scope.py",
    "tools/ci/a4_schema.py",
    "tools/ci/run_check.py",
    "tests/test_a4_scope.py",
)
TERMINAL = {"verified", "retained", "unsupported"}


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

    def __init__(self, root: Path):
        self.root = root
        self.bytes: dict[str, bytes] = {}
        self.jsons: dict[str, Any] = {}
        self.python: dict[str, set[str]] = {}
        self.replayed: set[str] = set()

    def read(self, path: str) -> bytes:
        if path not in self.bytes:
            self.bytes[path] = safe_path(self.root, path).read_bytes()
        return self.bytes[path]

    def json(self, path: str) -> Any:
        if path not in self.jsons:
            self.jsons[path] = json.loads(self.read(path))
        return self.jsons[path]

    def reference(
        self, path: str, identity: str = "whole_file", kind: str = "file"
    ) -> dict[str, str]:
        return {"path": path, "sha256": sha(self.read(path)), "identity": identity, "kind": kind}

    def verify(self, reference: dict[str, str]) -> None:
        path = reference["path"]
        if reference["sha256"] != sha(self.read(path)):
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
    return sorted(
        git(root, "ls-files", "src/pdx", "mod/decisions", "mod/generation-lock.json")
        .decode("utf8")
        .splitlines()
    )


def changes(root: Path) -> list[dict[str, str]]:
    result = []
    checkpoint = (
        git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", CANDIDATE)
        .decode()
        .splitlines()
    )
    current = (
        git(root, "diff", "--name-only", PRODUCTION_BASE, "--", "src/pdx", "mod/decisions")
        .decode()
        .splitlines()
    )
    paths = sorted(set(checkpoint + current))
    process = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input="".join(f"{CANDIDATE}:{path}\n" for path in paths).encode(),
        capture_output=True,
        check=False,
    )
    if process.returncode:
        raise ValueError("candidate blob discovery failed")
    blobs = {}
    offset = 0
    for path in paths:
        end = process.stdout.index(b"\n", offset)
        header = process.stdout[offset:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError(f"candidate blob missing: {path}")
        size = int(header[2])
        blobs[path] = process.stdout[end + 1 : end + 1 + size]
        offset = end + size + 2
    diffs = {
        "checkpoint": sha(git(root, "diff", f"{CANDIDATE}^", CANDIDATE)),
        "production_delta": sha(
            git(root, "diff", PRODUCTION_BASE, "--", "src/pdx", "mod/decisions")
        ),
    }
    for origin, paths in (("checkpoint", checkpoint), ("production_delta", current)):
        for path in sorted(paths):
            candidate = blobs[path]
            now = safe_path(root, path).read_bytes()
            result.append(
                {
                    "id": f"{origin}:{path}",
                    "path": path,
                    "checkpoint_sha256": sha(candidate),
                    "current_sha256": sha(now),
                    "diff_sha256": diffs[origin],
                }
            )
    return result


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
                "source": sources.reference(path),
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
    for path in production_paths(sources.root):
        add("production_input", path, path, ["G01", "G07", "C1"])
    return found


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
    rows = [pending_row(item, target) for item in discoveries]
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
        }
    )
    data = {
        "schema": 1,
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
            "investigation_sources": [],
            "dlc_ids": [],
        },
        "discoveries": discoveries,
        "rows": rows,
        "migrations": migrations,
        "candidate_changes": candidates,
        "receipts": [],
        "facts": [],
        "ports": [],
        "causes": [],
    }
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


def delivery_gate(stage: str) -> None:
    """Fail closed until actual external Git/CI/release/deployment verification exists."""
    if stage in {"A4-8", "all"}:
        raise ValueError(
            "A4-8 external delivery verification is not implemented; Git/CI/tag/Release/deployment evidence pending"
        )


def inventory_mappings(
    rows: dict[str, dict[str, Any]], reports: list[dict[str, Any]], stage: str
) -> None:
    """Require complete discovery mapping; only the selected phase must be terminal."""
    for report in reports:
        for kind in ("consumer", "writer"):
            for identity in report[f"{kind}_ids"]:
                matched = []
                for row in rows.values():
                    identities = {row["domain"]}
                    if kind == "consumer":
                        identities.add(row["consumer"]["value"])
                    else:
                        identities.update(
                            f"{binding['writer']['path']}::{binding['writer']['identity']}"
                            for binding in row["writer_bindings"]
                        )
                    if identity in identities:
                        matched.append(row)
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
    if receipt["command"][1:-1] != [*fixed_prefix, *selection] or not receipt["command"][
        -1
    ].startswith("--junitxml="):
        raise ValueError("receipt command / selection mismatch")
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
    data: dict[str, Any], root: Path, *, stage: str = "all", check_installation: bool = False
) -> dict[str, Any]:
    check_shape(data, SCHEMA)
    if stage not in {"all", *(f"A4-{number}" for number in range(9))}:
        raise ValueError("unknown A4 stage")
    sources = Sources(root)
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
    investigations = []
    for reference in investigation_references(sources, data["inventory"]["investigation_sources"]):
        sources.verify(reference)
        report = sources.json(reference["path"])
        check_shape(report, INVESTIGATION)
        if report["source_version"] != freeze["target_version"]:
            raise ValueError("investigation mixed source version")
        for source_input in report["source_inputs"]:
            sources.verify(source_input)
        if not report["source_inputs"] or not report["scanned_directories"]:
            raise ValueError("independent investigation source identity missing")
        expected_discoveries.extend(report["discoveries"])
        investigations.append(report)
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
    if set(candidate) != {item["id"] for item in delta}:
        raise ValueError("candidate change coverage missing")
    for item in delta:
        if any(candidate[item["id"]][key] != value for key, value in item.items()):
            raise ValueError("candidate change identity hash drift")
    rows = unique(data["rows"], "id", "row")
    mapped = {identity for row in rows.values() for identity in row["discovery_ids"]}
    if mapped != set(actual) or any(not row["discovery_ids"] for row in rows.values()):
        raise ValueError("discovery to obligation mapping coverage missing / dangling")
    goals = set(plan_goals(sources))
    if {goal for row in rows.values() for goal in row["goal_ids"]} != goals:
        raise ValueError("goal mapping coverage missing / dangling")
    for discovery in actual.values():
        if set(discovery["goal_ids"]) - goals:
            raise ValueError("dangling discovery goal ID")
        related = [row for row in rows.values() if discovery["id"] in row["discovery_ids"]]
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
    if stage != "A4-0" and (
        data["inventory"]["status"] != "verified"
        or data["inventory"]["parse_failures"]
        or data["inventory"]["unrecognized"]
        or data["inventory"]["duplicates"]
        or not data["inventory"]["crosscheck_receipts"]
    ):
        raise ValueError("A4-1 independent full inventory is pending or unresolved")
    if stage != "A4-0":
        if not investigations or any(
            report["parse_failures"] or report["unrecognized"] or report["duplicates"]
            for report in investigations
        ):
            raise ValueError("independent full inventory source gaps")
        if set(data["inventory"]["dlc_ids"]) != {
            dlc for report in investigations for dlc in report["dlc_ids"]
        }:
            raise ValueError("independent DLC coverage mismatch")
        inventory_mappings(rows, investigations, stage)
        for identity in data["inventory"]["crosscheck_receipts"]:
            if identity not in receipts:
                raise ValueError("missing inventory crosscheck receipt")
            receipt = sources.json(receipts[identity]["path"])
            verify_receipt(sources, receipts[identity], receipt["bindings"], receipt["selection"])
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
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bootstrap", "validate", "witness"))
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
