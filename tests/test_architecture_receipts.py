"""Evidence kinds keep historical identity and engineering proof distinct from PDX."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
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
    for name, expected in (
        ("manifest.json", "7534d0d45f7c1aa2ebefec699ece385f5d61cdf793332eda6c9b8318aca65440"),
        ("A2-manifest.json", "500f6b57180a9ae57a6977c26f8ee32c17a64b56543b3f79bc1a7fb7f0cbfbb9"),
    ):
        relative = f"docs/design/archive/{name}"
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected
        receipts._archive_identity(
            root,
            {
                "path": relative,
                "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
            },
            a2=name == "A2-manifest.json",
        )


def test_全部归档原字节在没有Git对象的源码副本可核验(tmp_path, monkeypatch, request):
    source = Path(__file__).resolve().parents[1] / "docs/design/archive"
    target = tmp_path / "docs/design/archive"
    shutil.copytree(source, target)
    assert not (tmp_path / ".git").exists()

    def no_process(*_args, **_kwargs):
        pytest.fail("archive validation must not invoke Git or any external process")

    monkeypatch.setattr(subprocess, "run", no_process)
    total = 0
    for filename in ("manifest.json", "A2-manifest.json"):
        manifest = target / filename
        data = json.loads(manifest.read_bytes())
        receipts._archive_identity(
            tmp_path,
            {
                "path": manifest.relative_to(tmp_path).as_posix(),
                "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            },
            a2=filename == "A2-manifest.json",
        )
        for item in data.get("files", data.get("originals", [])):
            commit = item.get("commit", data.get("commit"))
            # Independent original-byte observation, without the production decoder.
            raw = gzip.decompress(
                (target / "objects" / commit / f"{item['sha256']}.gz").read_bytes()
            )
            assert len(raw) == item["bytes"]
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            total += 1
    assert total == 12
    import test_architecture_baseline_evidence as baseline

    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    capture = baseline.BaselineCapture(None)
    baseline.test_s0_archive_identity(capture, request)
    assert len(capture.cases["archive_identity"]) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "damaged",
        "truncated",
        "changed",
        "trailing",
        "concatenated",
        "oversized",
        "compressed_oversized",
        "commit",
        "sha",
        "size",
        "boolean_size",
        "path",
        "duplicate",
    ],
)
def test_本地归档对象拒绝损坏篡改和不规范身份(tmp_path, fault):
    raw = b"frozen evidence\n"
    digest = hashlib.sha256(raw).hexdigest()
    commit = "a" * 40
    row = {"path": "docs/design/old.md", "commit": commit, "sha256": digest, "bytes": len(raw)}
    files = [row]
    manifest = {"schema": 1, "role": "historical_reference_only", "files": files}
    target = tmp_path / f"docs/design/archive/objects/{commit}/{digest}.gz"
    target.parent.mkdir(parents=True)
    packed = gzip.compress(raw, mtime=0)
    if fault == "damaged":
        packed = b"broken gzip"
    elif fault == "truncated":
        packed = packed[:-1]
    elif fault == "changed":
        packed = gzip.compress(b"changed bytes!!\n", mtime=0)
    elif fault == "trailing":
        packed += b"\x00"
    elif fault == "concatenated":
        packed += gzip.compress(b"extra", mtime=0)
    elif fault == "oversized":
        packed = gzip.compress(b"x" * (len(raw) + 1), mtime=0)
    elif fault == "compressed_oversized":
        packed = b"x" * (receipts._ARCHIVE_MAX_BYTES + 1)
    elif fault == "commit":
        row["commit"] = "../escape"
    elif fault == "sha":
        row["sha256"] = "A" * 64
    elif fault == "size":
        row["bytes"] = receipts._ARCHIVE_MAX_BYTES + 1
    elif fault == "boolean_size":
        row["bytes"] = True
    elif fault == "path":
        row["path"] = "../escape"
    elif fault == "duplicate":
        files.append(dict(row))
    if fault != "missing":
        target.write_bytes(packed)
    reference = _write(tmp_path, "docs/design/archive/manifest.json", manifest)
    with pytest.raises(ValueError):
        receipts._archive_identity(tmp_path, reference)


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
