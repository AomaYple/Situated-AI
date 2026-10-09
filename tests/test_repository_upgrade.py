"""全仓整理的功能、属性、故障、可逆性与交付契约测试。"""

from __future__ import annotations

import codecs
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdx import distribution, normalize_repo, performance, repo_audit, textio


@given(st.text())
def test_normalization_idempotent(text):
    normalized = textio.normalized_text(text)
    assert textio.normalized_text(normalized) == normalized
    assert "\r" not in normalized


@pytest.mark.parametrize(
    ("raw", "method"),
    [
        (codecs.BOM_UTF8 + b"a\r\nb\r", "utf-8"),
        ("a\r\nb".encode("utf-16"), "utf-16-bom"),
        ("a\r\nb".encode("utf-32"), "utf-32-bom"),
        (b"a\xff\r\n", "utf-8-invalid-bytes-escaped"),
    ],
)
def test_normalize_explicit_encodings(raw, method):
    result, selected = normalize_repo.normalize_bytes(raw, ".txt")
    assert selected == method
    assert result is not None
    result.decode("utf-8")
    assert not result.startswith(codecs.BOM_UTF8)
    assert b"\r" not in result


@pytest.mark.parametrize(
    ("suffix", "raw"),
    [(".png", b"abc"), (".lib", b"abc"), (".bin", b"abc"), ("", b"\0\xff"), (".unknown", b"\xff")],
)
def test_binary_untouched(suffix, raw):
    result, _ = normalize_repo.normalize_bytes(raw, suffix)
    assert result is None


def test_backup_restore_and_edit_conflict(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "notes.md"
    original = codecs.BOM_UTF8 + b"hello\r\n"
    path.write_bytes(original)
    backup = tmp_path / "originals.zip"
    changes = normalize_repo.normalize(source, backup)
    assert len(changes) == 1
    assert path.read_bytes() == b"hello\n"
    with zipfile.ZipFile(backup) as archive:
        assert archive.read("notes.md") == original
    path.write_bytes(b"edited\n")
    with pytest.raises(ValueError, match="再次编辑"):
        normalize_repo.restore(source, backup)
    assert path.read_bytes() == b"edited\n"
    path.write_bytes(b"hello\n")
    assert normalize_repo.restore(source, backup) == 1
    assert path.read_bytes() == original
    with pytest.raises(FileExistsError):
        normalize_repo.normalize(source, backup)


def test_restore_rejects_traversal(tmp_path):
    backup = tmp_path / "bad.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("RESTORE-MANIFEST.json", json.dumps([{"path": "../outside.txt"}]))
    with pytest.raises(ValueError, match="越界"):
        normalize_repo.restore(tmp_path / "source", backup)


@given(st.binary(max_size=1024), st.integers(min_value=1, max_value=64))
def test_stream_inspection_matches_bytes(raw, chunk_size):
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "input.bin"
        path.write_bytes(raw)
        result = repo_audit.inspect_bytes(path, chunk_size=chunk_size)
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["bytes"] == len(raw)
    assert result["cr"] == raw.count(b"\r")
    assert result["nul"] == raw.count(b"\0")
    assert result["bom"] == raw.startswith(codecs.BOM_UTF8)
    try:
        raw.decode("utf-8")
        utf8 = True
    except UnicodeDecodeError:
        utf8 = False
    assert result["utf8"] == utf8


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        (".venv/Lib/a.py", "third_party_environment"),
        (".pytest_cache/a", "cache"),
        ("v3-parse-cache-abc/a", "cache"),
        ("research/official-docs/a.md", "third_party_mirror"),
        (".agent-teams/state.json", "local_runtime"),
        ("tools/out/a.py", "raw_evidence"),
        ("tools/probe/zz_console_probe/a.txt", "raw_evidence"),
        ("tools/probe/frozen/a.py.frozen", "frozen_evidence"),
        ("tools/probe/a.png", "binary_asset"),
        ("tests/a.py", "test"),
        ("src/pdx/a.py", "source"),
        ("mod/common/a.txt", "generated"),
        ("docs/a.md", "documentation"),
        ("pyproject.toml", "configuration_or_data"),
    ],
)
def test_categories(path, kind):
    assert repo_audit.category(path) == kind


def test_inventory_includes_ignored_and_python_errors(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8", newline="\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "raw.txt").write_bytes(b"raw\r\n")
    (tmp_path / "bad.py").write_text("def broken(\n", encoding="utf-8", newline="\n")
    (tmp_path / "good.py").write_text(
        "import json\ndef foo():\n    return 1\n", encoding="utf-8", newline="\n"
    )
    result = repo_audit.inventory(tmp_path)
    files = result["files"]
    assert isinstance(files, list)
    records = {r["path"]: r for r in files}
    assert records["ignored/raw.txt"]["git"] == "ignored"
    assert records["ignored/raw.txt"]["encoding_issues"] == ["cr"]
    assert "python_error" in records["bad.py"]
    assert records["good.py"]["python"]["functions"] == 1
    assert result["read_errors"] == []
    assert all(not p.startswith(".git/") for p in records)


@pytest.mark.parametrize(
    "name", ["../x.txt", "/x.txt", "C:/x.txt", "a\\b.txt", "a/../b.txt", "./x.txt", "a//b.txt", ""]
)
def test_distribution_rejects_unsafe_paths(name):
    with pytest.raises(ValueError):
        distribution.payloads({name: "x"})


def test_zip_deterministic_manifest_and_game_encoding(tmp_path):
    files = {
        "common/a.txt": "\ufeffx = 1\r\n",
        "localization/a.yml": "l_english:\n",
        ".metadata/metadata.json": "{}\n",
        "notes.md": "readme\n",
    }
    a = distribution.write_zip(files, tmp_path / "a.zip")
    b = distribution.write_zip(dict(reversed(list(files.items()))), tmp_path / "b.zip")
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as archive:
        assert archive.read("common/a.txt") == codecs.BOM_UTF8 + b"x = 1\n"
        assert archive.read(".metadata/metadata.json") == b"{}\n"
        manifest = json.loads(archive.read("DISTRIBUTION-MANIFEST.json"))
        for name, expected in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected


def test_deploy_preserves_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"x = 1\n")
    (source / "a.png").write_bytes(b"\0\xff")
    destination = tmp_path / "deployed"
    assert len(textio.deploy_tree(source, destination)) == 2
    assert (source / "a.txt").read_bytes() == b"x = 1\n"
    assert (destination / "a.txt").read_bytes() == codecs.BOM_UTF8 + b"x = 1\n"
    assert (destination / "a.png").read_bytes() == b"\0\xff"
    with pytest.raises(ValueError, match="之外"):
        textio.deploy_tree(source, source / "child")


def test_performance_measurement_and_regression_contract():
    result = performance.measure(lambda: (1, 2), rounds=2)
    samples = result["samples_s"]
    assert isinstance(samples, list)
    assert len(samples) == 2
    baseline = {"environment": {}, "workloads": {"a": result}}
    assert performance.regressions(baseline, baseline) == []
    changed = {
        "environment": {},
        "workloads": {
            "a": {
                **result,
                "result_sha256": "bad",
                "median_s": float(str(result["median_s"])) * 2,
                "python_peak_bytes": int(str(result["python_peak_bytes"])) * 2 + 1,
            }
        },
    }
    assert len(performance.regressions(baseline, changed)) == 3
    assert performance.regressions(baseline, {"environment": {"different": True}})
    with pytest.raises(ValueError):
        performance.measure(lambda: None, rounds=0)
    with pytest.raises(ValueError):
        performance.regressions(baseline, baseline, tolerance=-1)


def test_measure_command_reports_failure_and_memory(tmp_path):
    result = performance.command(
        [
            sys.executable,
            "-c",
            "import time; a=bytearray(1000000); print('hello'); time.sleep(0.1)",
        ],
        tmp_path / "ok.log",
        interval=0.01,
    )
    assert result["exit_code"] == 0
    assert int(str(result["samples"])) > 0
    assert int(str(result["sampled_tree_peak_rss_bytes"])) > 0
    assert b"hello" in (tmp_path / "ok.log").read_bytes()
    result = performance.command(
        [sys.executable, "-c", "raise SystemExit(3)"], tmp_path / "bad.log"
    )
    assert result["exit_code"] == 3
    with pytest.raises(ValueError):
        performance.command([], tmp_path / "x.log", timeout=0)


def test_command_timeout_kills_its_own_child(tmp_path):
    result = performance.command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path / "timeout.log",
        timeout=0.1,
        interval=0.01,
    )
    assert result["timed_out"]
    assert result["exit_code"] != 0


def test_stage_timings_preserve_nested_intervals_without_summing_overlap():
    moments = iter([10.0, 11.0, 12.0, 14.0, 16.0])
    timings = performance.StageTimings(clock=lambda: next(moments))
    with timings.phase("outer"), timings.phase("inner"):
        pass
    assert timings.intervals == [
        {"name": "inner", "start_s": 2.0, "end_s": 4.0, "wall_s": 2.0, "status": "ok"},
        {"name": "outer", "start_s": 1.0, "end_s": 6.0, "wall_s": 5.0, "status": "ok"},
    ]


def test_stage_timings_record_interrupt_and_propagate_it():
    moments = iter([0.0, 1.0, 3.0])
    timings = performance.StageTimings(clock=lambda: next(moments))
    with pytest.raises(KeyboardInterrupt), timings.phase("copy"):
        raise KeyboardInterrupt("cancelled")
    assert timings.intervals == [
        {
            "name": "copy",
            "start_s": 1.0,
            "end_s": 3.0,
            "wall_s": 2.0,
            "status": "failed",
            "error": "KeyboardInterrupt: cancelled",
        }
    ]


def test_measure_rejects_nondeterminism_in_any_timed_round():
    values = iter(["stable", "different", "stable", "stable"])
    with pytest.raises(ValueError, match="不确定"):
        performance.measure(lambda: next(values), rounds=3)
