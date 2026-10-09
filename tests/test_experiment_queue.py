"""实验预算和任务身份须跨进程持久化，失败不能免费重置次数。"""

from __future__ import annotations

import subprocess
import sys

import pytest

from pdx.experiment_queue import ExperimentLedger, RunRequest

pytestmark = pytest.mark.unit


def request(scene="scene-a", arm="control", pair=1):
    return RunRequest(plan_id="test-plan", scene_id=scene, arm=arm, pair=pair)


def reserve(ledger, req, evidence):
    return ledger.reserve(req, manifest={"checkpoint": "a" * 64}, evidence=evidence)


def test_重复任务拒绝派发但失败重试有新身份(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    first = reserve(ledger, request(), tmp_path / "run-a")
    with pytest.raises(ValueError, match="未完成"):
        reserve(ledger, request(), tmp_path / "run-b")
    ledger.finish(first, {"ok": False, "failure": "input"}, report_sha256="b" * 64)
    second = reserve(ledger, request(), tmp_path / "run-c")
    assert first != second
    assert len(ledger.runs("test-plan")) == 2


def test_两次相同引擎错误停止同场景(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    for pair in (1, 2):
        run_id = reserve(ledger, request(pair=pair), tmp_path / str(pair))
        ledger.finish(
            run_id,
            {"ok": False, "log_findings": {"errors": {"Script system error!": 1}}},
            report_sha256="b" * 64,
        )
    with pytest.raises(ValueError, match="错误重复"):
        reserve(ledger, request(pair=3), tmp_path / "new")


def test_失败消耗预算且更改预算不能事后追认(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    for index in range(6):
        run_id = reserve(ledger, request(pair=index % 3 + 1), tmp_path / str(index))
        ledger.finish(run_id, {"ok": False}, report_sha256="b" * 64)
    with pytest.raises(ValueError, match="预算"):
        reserve(ledger, request(pair=3), tmp_path / "over-budget")
    with pytest.raises(ValueError, match="冻结"):
        reserve(
            ledger,
            RunRequest(plan_id="test-plan", scene_id="new", arm="control", max_months=5),
            tmp_path / "changed",
        )


def test_新进程对象保持场景上限和完整任务不可覆盖(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = ExperimentLedger(path)
    for scene in ("one", "two"):
        run_id = reserve(ledger, request(scene), tmp_path / scene)
        ledger.finish(run_id, {"ok": True}, report_sha256="b" * 64)
    restarted = ExperimentLedger(path)
    with pytest.raises(ValueError, match="场景预算"):
        reserve(restarted, request("three"), tmp_path / "third")
    with pytest.raises(ValueError, match="已完成"):
        reserve(restarted, request("one"), tmp_path / "overwrite")


def test_源改变或证据目录复用均拒绝(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    run_id = reserve(ledger, request(), tmp_path / "same")
    ledger.finish(run_id, {"ok": False}, report_sha256="b" * 64)
    with pytest.raises(ValueError, match="输入"):
        ledger.reserve(request(), manifest={"checkpoint": "changed"}, evidence=tmp_path / "other")
    with pytest.raises(ValueError, match="证据"):
        reserve(ledger, request(pair=2), tmp_path / "same")


@pytest.mark.parametrize("field", ["months", "profile", "keep_save", "sources"])
def test_跨配对仍冻结运行条件和每臂源码(tmp_path, field):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    manifest = {
        "checkpoint": "a",
        "months": 1,
        "profile": False,
        "keep_save": False,
        "sources": {"a": "b"},
    }
    first = ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "one")
    ledger.finish(first, {"ok": False}, report_sha256="b" * 64)
    changed = dict(manifest)
    changed[field] = "changed"
    with pytest.raises(ValueError, match="输入"):
        ledger.reserve(request(pair=2), manifest=changed, evidence=tmp_path / "two")


@pytest.mark.parametrize("limits", [{"max_pairs": 4}, {"max_scenes": 3}])
def test_请求不能扩大本轮硬预算(limits):
    with pytest.raises(ValueError, match="预算"):
        RunRequest(plan_id="plan", scene_id="scene", arm="control", **limits).limits()


@pytest.mark.parametrize("edge", ["before", "after"])
def test_账本提交中断由新连接重建预算(tmp_path, edge):
    path = tmp_path / "ledger.sqlite3"
    script = r"""
import os, sqlite3, sys
from pathlib import Path
from pdx.experiment_queue import ExperimentLedger, RunRequest
original = sqlite3.connect
class Connection(sqlite3.Connection):
    def commit(self):
        if sys.argv[2] == 'before': os._exit(99)
        super().commit()
        os._exit(99)
sqlite3.connect = lambda *args, **kwargs: original(*args, factory=Connection, **kwargs)
ExperimentLedger(Path(sys.argv[1])).reserve(
    RunRequest(plan_id='test-plan', scene_id='scene-a', arm='control'),
    manifest={'checkpoint': 'a'*64}, evidence=Path(sys.argv[1]).parent/'interrupted')
"""
    child = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(path), edge],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 99, child.stderr
    restarted = ExperimentLedger(path)
    assert len(restarted.runs("test-plan")) == (edge == "after")
    restarted.interrupt_pending()
    reserve(restarted, request(), tmp_path / "new-attempt")
    assert len(restarted.runs("test-plan")) == 1 + (edge == "after")
