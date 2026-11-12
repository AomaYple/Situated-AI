"""Diagnostic checkpoint sharing must not interrupt core resource sampling."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pdx import config
from tools.ci import test_suite

pytestmark = pytest.mark.unit


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBASELINE_OUT", str(tmp_path))
    monkeypatch.setenv("MEMBASELINE_TAG", "full")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "isolated")
    spec = importlib.util.spec_from_file_location(
        "mem_baseline_progress_test",
        config.REPO / "tools" / "ci" / "mem_baseline.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checkpoint(mem):
    progress = mem._InprocProgress()
    progress.set_phase("initial")
    progress.sample(*mem._inproc_snapshot())
    progress.flush(force=True)
    mem._INPROC_RUNTIME["progress"] = progress
    return progress


def run_two_samples(mem):
    waits = []

    def wait(timeout):
        waits.append(timeout)
        return len(waits) > 2

    mem._INPROC_STOP = SimpleNamespace(wait=wait, set=lambda: None)
    mem._inproc_sampler()
    assert len(mem._INPROC["series"]) == 2


@pytest.mark.skipif(os.name != "nt", reason="real Windows reader sharing contract")
def test_held_reader_defers_without_stopping_sampling_and_recovers(mem):
    progress = checkpoint(mem)
    old = json.loads(progress.path.read_bytes())
    progress.set_phase("held-reader")
    progress.last_flush = float("-inf")
    with progress.path.open("r", encoding="utf-8"):
        run_two_samples(mem)
        assert not mem._INPROC["errors"]
        assert progress.replace_deferred == 1
        assert progress.replace_pending
        assert progress.temporary.exists()
        assert json.loads(progress.path.read_bytes())["journal_seq"] == old["journal_seq"]
        assert json.loads(progress.temporary.read_bytes())["journal_seq"] > old["journal_seq"]
    progress.flush(force=True)
    assert not progress.replace_pending
    assert not progress.temporary.exists()
    events = [json.loads(line) for line in progress.events_path.read_text().splitlines()]
    sequences = [row["seq"] for row in events]
    assert sequences == list(range(1, progress.seq + 1))
    assert len([row for row in events if row["event"] == "checkpoint_deferred"]) == 1
    assert any(row["event"] == "phase" and row["phase"] == "held-reader" for row in events)
    assert not mem._INPROC["errors"]
    mem.pytest_sessionfinish(SimpleNamespace(testscollected=1), 0)
    final = Path(mem.os.environ["MEMBASELINE_OUT"]) / "inproc-full-isolated.json"
    payload = json.loads(final.read_bytes())
    assert payload["exitstatus"] == 0
    assert payload["errors"] == []
    assert payload["progress_diagnostics"]["checkpoint_replace_pending"] is False
    assert payload["progress_diagnostics"]["checkpoint_replace_deferred"] == 1


@pytest.mark.parametrize(
    ("windows", "winerror", "deferred"),
    [(True, 5, True), (True, 32, True), (True, 33, False), (True, None, False), (False, 32, False)],
)
def test_only_windows_replace_sharing_permissions_are_deferred(
    mem, monkeypatch, windows, winerror, deferred
):
    progress = checkpoint(mem)
    error = PermissionError(13, "held target")
    monkeypatch.setattr(error, "winerror", winerror, raising=False)

    def denied(*_args):
        raise error

    monkeypatch.setattr(mem, "_IS_WIN", windows)
    progress._replace = denied
    if deferred:
        progress.flush(force=True)
        assert progress.replace_pending
        assert progress.replace_deferred == 1
    else:
        with pytest.raises(PermissionError) as raised:
            progress.flush(force=True)
        assert raised.value is error
        assert not progress.replace_pending


def test_nonsharing_progress_error_preserves_sampling_and_final_gate_failure(mem):
    progress = checkpoint(mem)

    def no_space(*_args):
        raise OSError(28, "no space left")

    progress._replace = no_space
    progress.last_flush = float("-inf")
    run_two_samples(mem)
    assert mem._INPROC_RUNTIME["progress"] is None
    assert len(mem._INPROC["errors"]) == 1
    assert mem._INPROC["errors"][0].startswith("PROGRESS-ERROR OSError(28")
    mem.pytest_sessionfinish(SimpleNamespace(testscollected=1), 0)
    output = Path(mem.os.environ["MEMBASELINE_OUT"])
    final = json.loads((output / "inproc-full-isolated.json").read_bytes())
    assert final["errors"] == mem._INPROC["errors"]
    with pytest.raises(ValueError, match="进程内采样失败：isolated"):
        test_suite._resource_evidence(output, {})


def test_nonsharing_final_flush_error_still_writes_failed_final_evidence(mem):
    progress = checkpoint(mem)

    def no_space(*_args):
        raise OSError(28, "no space left")

    progress._replace = no_space
    mem.pytest_sessionfinish(SimpleNamespace(testscollected=1), 0)
    final = Path(mem.os.environ["MEMBASELINE_OUT"]) / "inproc-full-isolated.json"
    payload = json.loads(final.read_bytes())
    assert payload["exitstatus"] == 0
    assert payload["errors"]
    assert payload["errors"][0].startswith("PROGRESS-ERROR OSError(28")


@pytest.mark.parametrize("code", [5, 32])
def test_final_access_denial_fails_but_explicit_sharing_is_only_diagnostic(mem, monkeypatch, code):
    progress = checkpoint(mem)
    error = PermissionError(13, "held target")
    monkeypatch.setattr(error, "winerror", code, raising=False)

    def denied(*_args):
        raise error

    monkeypatch.setattr(mem, "_IS_WIN", True)
    progress._replace = denied
    mem.pytest_sessionfinish(SimpleNamespace(testscollected=1), 0)
    final = Path(mem.os.environ["MEMBASELINE_OUT"]) / "inproc-full-isolated.json"
    payload = json.loads(final.read_bytes())
    assert payload["exitstatus"] == 0
    assert payload["progress_diagnostics"]["checkpoint_replace_pending"] is True
    assert payload["progress_diagnostics"]["checkpoint_replace_deferred"] == 1
    events = [json.loads(line) for line in progress.events_path.read_text().splitlines()]
    assert [row["seq"] for row in events] == list(range(1, progress.seq + 1))
    assert len([row for row in events if row["event"] == "checkpoint_deferred"]) == 1
    if code == 5:
        assert len(payload["errors"]) == 1
        assert payload["errors"][0].startswith("PROGRESS-ERROR PermissionError")
    else:
        assert payload["errors"] == []


def test_sharing_error_does_not_clear_an_unrecovered_access_denial(mem, monkeypatch):
    progress = checkpoint(mem)
    access = PermissionError(13, "ambiguous access denied")
    monkeypatch.setattr(access, "winerror", 5, raising=False)
    sharing = PermissionError(13, "sharing violation")
    monkeypatch.setattr(sharing, "winerror", 32, raising=False)
    errors = iter([access, sharing])

    def denied(*_args):
        raise next(errors)

    monkeypatch.setattr(mem, "_IS_WIN", True)
    progress._replace = denied
    progress.flush(force=True)
    assert progress.replace_access_denials == 1
    mem.pytest_sessionfinish(SimpleNamespace(testscollected=1), 0)
    final = Path(mem.os.environ["MEMBASELINE_OUT"]) / "inproc-full-isolated.json"
    payload = json.loads(final.read_bytes())
    assert payload["progress_diagnostics"]["checkpoint_access_denials"] == 1
    assert len(payload["errors"]) == 1
    assert payload["errors"][0].startswith("PROGRESS-ERROR PermissionError")


def test_successful_replacement_clears_access_denial_before_final_sharing(mem, monkeypatch):
    progress = checkpoint(mem)
    access = PermissionError(13, "transient access denied")
    monkeypatch.setattr(access, "winerror", 5, raising=False)
    sharing = PermissionError(13, "sharing violation")
    monkeypatch.setattr(sharing, "winerror", 32, raising=False)
    replace = progress._replace
    calls = []

    def replace_or_deny(*args):
        calls.append(args)
        if len(calls) == 1:
            raise access
        if len(calls) == 3:
            raise sharing
        replace(*args)

    monkeypatch.setattr(mem, "_IS_WIN", True)
    progress._replace = replace_or_deny
    progress.flush(force=True)
    assert progress.replace_access_denials == 1
    progress.flush(force=True)
    assert progress.replace_access_denials == 0
    mem.pytest_sessionfinish(SimpleNamespace(testscollected=1), 0)
    final = Path(mem.os.environ["MEMBASELINE_OUT"]) / "inproc-full-isolated.json"
    payload = json.loads(final.read_bytes())
    assert payload["progress_diagnostics"]["checkpoint_access_denials"] == 0
    assert payload["progress_diagnostics"]["checkpoint_replace_pending"] is True
    assert payload["errors"] == []


def test_repeated_access_denial_is_bounded_and_keeps_core_sampler(mem, monkeypatch):
    progress = checkpoint(mem)
    error = PermissionError(13, "permanent access denied")
    monkeypatch.setattr(error, "winerror", 5, raising=False)

    def denied(*_args):
        raise error

    monkeypatch.setattr(mem, "_IS_WIN", True)
    progress._replace = denied
    for _ in range(2):
        progress.flush(force=True)
    progress.last_flush = float("-inf")
    run_two_samples(mem)
    assert progress.replace_access_denials == 3
    assert mem._INPROC_RUNTIME["progress"] is None
    assert len(mem._INPROC["errors"]) == 1
    assert mem._INPROC["errors"][0].startswith("PROGRESS-ERROR PermissionError")
    mem.pytest_sessionfinish(SimpleNamespace(testscollected=1), 0)
    output = Path(mem.os.environ["MEMBASELINE_OUT"])
    payload = json.loads((output / "inproc-full-isolated.json").read_bytes())
    assert payload["progress_diagnostics"]["checkpoint_replace_pending"] is True
    assert payload["progress_diagnostics"]["checkpoint_replace_deferred"] == 3
    assert payload["progress_diagnostics"]["checkpoint_access_denials"] == 3
    with pytest.raises(ValueError, match="进程内采样失败：isolated"):
        test_suite._resource_evidence(output, {})


def test_failed_journal_append_restores_queued_events(mem):
    progress = checkpoint(mem)
    progress.set_phase("must-survive")
    pending = list(progress.events)
    original_open = progress._open

    def cannot_append(path, *args, **kwargs):
        if path == progress.events_path:
            raise OSError(28, "no space left")
        return original_open(path, *args, **kwargs)

    progress._open = cannot_append
    with pytest.raises(OSError, match="no space left"):
        progress.flush(force=True)
    assert progress.events == pending
