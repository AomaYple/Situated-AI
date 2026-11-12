"""Archived S0 capture cannot sign current native inputs as historical A2 evidence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
import test_architecture_baseline_evidence as baseline_tests

from pdx import version_contracts

pytestmark = pytest.mark.unit


def _request():
    registered = []
    request = SimpleNamespace(
        config=SimpleNamespace(
            getoption=lambda _name, default=0: default,
            pluginmanager=SimpleNamespace(register=lambda *args: registered.append(args)),
        )
    )
    return request, registered


def test_current_s0_capture_rejects_before_creating_output(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline_tests, "ROOT", tmp_path)
    monkeypatch.setenv("SITAI_S0_EVIDENCE_OUTPUT", "tools/out/s0-current")
    request, registered = _request()
    with (
        version_contracts.select_version("1.15.0"),
        pytest.raises(pytest.UsageError, match=r"historical.*1\.14\.5"),
    ):
        cast("Any", baseline_tests.baseline_capture).__wrapped__(request)
    assert not (tmp_path / "tools/out/s0-current").exists()
    assert registered == []


def test_historical_s0_capture_retains_output_and_plugin_route(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline_tests, "ROOT", tmp_path)
    monkeypatch.setattr(baseline_tests.receipts, "source_snapshot", lambda _root: {})
    monkeypatch.setenv("SITAI_S0_EVIDENCE_OUTPUT", "tools/out/s0-historical")
    request, registered = _request()
    with version_contracts.select_version("1.14.5"):
        capture = cast("Any", baseline_tests.baseline_capture).__wrapped__(request)
    assert isinstance(capture, baseline_tests.BaselineCapture)
    assert capture.output == (tmp_path / "tools/out/s0-historical").resolve()
    assert capture.output is not None
    assert capture.output.is_dir()
    assert registered == [(capture, "architecture-s0-local-capture")]


def test_current_s0_assertions_run_without_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline_tests, "ROOT", tmp_path)
    monkeypatch.delenv("SITAI_S0_EVIDENCE_OUTPUT", raising=False)
    request, registered = _request()
    with version_contracts.select_version("1.15.0"):
        capture = cast("Any", baseline_tests.baseline_capture).__wrapped__(request)
    assert capture.output is None
    assert registered == []
    assert not (tmp_path / "tools/out").exists()


@pytest.fixture(autouse=True)
def _historical_1150_contract():
    """Keep the exact archived witness under its original version identity."""
    with version_contracts.select_version("1.15.0"):
        yield
