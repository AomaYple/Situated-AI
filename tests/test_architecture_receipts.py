"""Evidence kinds keep historical identity and engineering proof distinct from PDX."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pdx.situated import architecture_receipts as receipts

pytestmark = pytest.mark.unit


def _write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8", newline="\n")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def archive_evidence(tmp_path, monkeypatch):
    raw = b"frozen evidence\n"
    archive = _write(
        tmp_path,
        "docs/design/archive/manifest.json",
        {
            "schema": 1,
            "role": "historical_reference_only",
            "files": [
                {
                    "path": "docs/design/old.md",
                    "commit": "a" * 40,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
            ],
        },
    )
    test = tmp_path / "tests/test_history.py"
    test.parent.mkdir()
    test.write_text("def test_identity():\n    assert True\n", encoding="utf-8", newline="\n")
    row = {
        "requirement_id": "archive_identity",
        "evidence_id": "archive.1",
        "direction": "B0",
        "oracle": "independent",
        "evidence_kind": "archive",
        "artifacts": [archive],
        "tests": [
            {
                "nodeid": "tests/test_history.py::test_identity",
                "sha256": hashlib.sha256(test.read_bytes()).hexdigest(),
            }
        ],
    }
    result = {
        "schema": 1,
        "plan_version": "A2",
        "stage_id": "S0",
        "requirement_id": row["requirement_id"],
        "evidence_id": row["evidence_id"],
        "source_snapshot_sha256": "b" * 64,
        "scope_hash": "c" * 64,
        "evidence_category": "static_check",
        "evidence_kind": "archive",
        "status": "passed",
        "artifacts": [archive],
        "archive_manifest": archive,
        "cases": [
            {
                "case_id": "frozen",
                "nodeid": row["tests"][0]["nodeid"],
                "outcome": "passed",
                "expected_origin": "independent",
                "input": {"commit": "a" * 40},
                "expected": {"unchanged": True},
                "reference": {"unchanged": True},
                "observed": {"unchanged": True},
            }
        ],
        "open_items": [],
    }
    row["result"] = _write(tmp_path, "tools/out/archive.json", result)
    monkeypatch.setattr(receipts, "_archive_bytes", lambda *_args: raw, raising=False)
    return tmp_path, row, result, raw


def test_S0归档核对真实历史字节且无需生成消费者(archive_evidence):
    root, row, _result, _raw = archive_evidence
    assert receipts._evidence(root, "S0", row, "b" * 64, "c" * 64) == []


def test_仓库归档manifest匹配实际冻结Git对象():
    root = Path(__file__).resolve().parents[1]
    name = "docs/design/archive/manifest.json"
    receipts._archive_identity(
        root,
        {
            "path": name,
            "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
        },
    )


@pytest.mark.parametrize(
    "fault", ["historical_bytes", "duplicate", "missing", "unsafe", "commit", "case", "kind"]
)
def test_归档身份和观察见证不能由哈希存在替代(archive_evidence, monkeypatch, fault):
    root, row, result, _raw = archive_evidence
    manifest = json.loads((root / row["artifacts"][0]["path"]).read_text(encoding="utf-8"))
    if fault == "historical_bytes":
        monkeypatch.setattr(
            receipts, "_archive_bytes", lambda *_args: b"different\n", raising=False
        )
    elif fault == "duplicate":
        manifest["files"].append(manifest["files"][0])
    elif fault == "missing":
        manifest["files"] = []
    elif fault == "unsafe":
        manifest["files"][0]["path"] = "../escape"
    elif fault == "commit":
        manifest["files"][0]["commit"] = "HEAD"
    elif fault == "case":
        result["cases"][0]["observed"] = {"unchanged": False}
    else:
        row["evidence_kind"] = "pdx"
    row["artifacts"] = [_write(root, "docs/design/archive/manifest.json", manifest)]
    result["artifacts"] = row["artifacts"]
    result["archive_manifest"] = row["artifacts"][0]
    row["result"] = _write(root, "tools/out/archive.json", result)
    assert receipts._evidence(root, "S0", row, "b" * 64, "c" * 64)
