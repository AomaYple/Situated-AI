"""Subprocess readback must validate every byte and expose all original failures."""

import hashlib

import pytest
from _artifact_readback import assert_artifacts_readback


@pytest.mark.parametrize(
    ("suffix", "raw", "error"),
    [
        (".json", b'{"x":"\xff"}', "UnicodeDecodeError"),
        (".json", b'{"x":1} trailing', "JSONDecodeError"),
        (".json", b"[]", "顶层应为对象"),
        (".md", b"ordinary text", "应是 Markdown"),
        (".md", b"# heading\xff", "UnicodeDecodeError"),
    ],
)
def test_failed_readback_preserves_input_and_full_error_identity(tmp_path, suffix, raw, error):
    path = tmp_path / ("damaged" + suffix)
    path.write_bytes(raw)
    before = hashlib.sha256(raw).hexdigest()
    with pytest.raises(AssertionError) as failure:
        assert_artifacts_readback({"damaged artifact": path}, timeout_s=10)
    message = str(failure.value)
    assert error in message
    assert "Traceback (most recent call last)" in message
    assert "damaged artifact" in message
    assert str(path) in message
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_readback_checks_later_file_after_complete_valid_unicode_json(tmp_path):
    first = tmp_path / "valid.json"
    first.write_text('{"unicode":"测试𐀀","nested":[{"x":true}]}', encoding="utf-8")
    second = tmp_path / "report.md"
    second.write_text("  # Heading\n", encoding="utf-8")
    assert_artifacts_readback({"first": first, "second": second}, timeout_s=10)
    second.write_text("not markdown", encoding="utf-8")
    with pytest.raises(AssertionError, match="second 应是 Markdown"):
        assert_artifacts_readback({"first": first, "second": second}, timeout_s=10)


def test_child_budget_reuses_authoritative_limit_and_rejects_peak(monkeypatch, capsys):
    from _artifact_readback import _check_memory

    from tools.ci import mem_baseline as mem

    monkeypatch.setattr(mem, "_self_read", lambda: (1.0, mem.BUDGET_PER_WORKER_MB + 1, 1.0))
    with pytest.raises(AssertionError, match="memory budget exceeded"):
        _check_memory()
    assert str(mem.BUDGET_PER_WORKER_MB) in capsys.readouterr().out


def test_readback_timeout_terminates_and_reaps_child_tree(tmp_path, monkeypatch):
    import subprocess

    import psutil

    child = tmp_path / "hang.py"
    child.write_text("import time; time.sleep(30)", encoding="utf-8")
    real_popen = subprocess.Popen
    pids = []

    def hanging_popen(command, **kwargs):
        process = real_popen([*command[:4], str(child)], **kwargs)
        pids.append(process.pid)
        return process

    monkeypatch.setattr(subprocess, "Popen", hanging_popen)
    with pytest.raises(subprocess.TimeoutExpired):
        assert_artifacts_readback({}, timeout_s=0.2)
    assert pids
    assert not any(psutil.pid_exists(pid) for pid in pids)
