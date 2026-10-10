"""实验预算和任务身份须跨进程持久化，失败不能免费重置次数。"""

from __future__ import annotations

import json
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


def test_两次未枚举的模组错误也停止同场景(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    for pair in (1, 2):
        run_id = reserve(ledger, request(pair=pair), tmp_path / str(pair))
        ledger.finish(
            run_id,
            {
                "ok": False,
                "log_findings": {
                    "errors": {},
                    "mod_errors": [f"[12:00:0{pair}][script] Invalid custom invocation sitai_rule"],
                },
            },
            report_sha256="b" * 64,
        )
    with pytest.raises(ValueError, match="错误重复"):
        reserve(ledger, request(pair=3), tmp_path / "new")


def test_两次未分类资源错误也停止同场景(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    for pair in (1, 2):
        run_id = reserve(ledger, request(pair=pair), tmp_path / str(pair))
        ledger.finish(
            run_id,
            {
                "ok": False,
                "log_findings": {
                    "errors": {},
                    "unclassified_errors": [f"VFSOpen Error: missing texture {pair}"],
                },
            },
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


def published_failure(ledger, run_id, directory):
    from pdx import game_run

    row = next(row for row in ledger.runs("test-plan") if row["id"] == run_id)
    logs = directory / "logs"
    logs.mkdir(parents=True)
    (logs / "debug.log").write_text("Mounted Data: C:/base\n", encoding="utf-8")
    (logs / "error.log").write_text("Assertion failed: dead formation\n", encoding="utf-8")
    report = {
        "ok": False,
        "failure": "engine",
        "session_requested": True,
        "logs_isolated": True,
        "evidence": str(directory.resolve()),
        "game_version": {"caligula_branch": "release/1.14.5"},
        "loaded_save": {"sha256": "a" * 64},
        "mount_allowlist": ["C:/base"],
        "log_hashes": game_run.hashes(logs),
        "experiment": {
            "run_id": run_id,
            "plan_id": row["plan"],
            "scene_id": row["scene"],
            "arm": row["arm"],
            "pair": row["pair"],
            "manifest_sha256": ledger.manifest_sha256(run_id),
        },
    }
    path = directory / "report.json"
    game_run.write_json(path, report)
    return path


def test_发布报告后中断仍恢复错误停止事实但不拼接完成(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    first = reserve(ledger, request(), tmp_path / "one")
    path = published_failure(ledger, first, tmp_path / "one")
    ledger.interrupt_pending()
    row = ledger.runs("test-plan")[0]
    assert row["status"] == "interrupted"
    assert json.loads(row["errors"]) == ["Assertion failed"]
    assert row["report_sha"]
    assert path.exists()
    second = reserve(ledger, request(pair=2), tmp_path / "two")
    ledger.finish(
        second,
        {"ok": False, "log_findings": {"errors": {"Assertion failed": 1}}},
        report_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="错误重复"):
        reserve(ledger, request(pair=3), tmp_path / "three")


@pytest.mark.parametrize("problem", [None, "engine", "mod", "unclassified", "malformed", "mounted"])
def test_启动前结构化零错误报告可恢复而异常报告保持阻断(tmp_path, problem):
    from pdx import game_run

    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    run_id = reserve(ledger, request(), tmp_path / "one")
    path = published_failure(ledger, run_id, tmp_path / "one")
    logs = path.parent / "logs"
    for logfile in logs.glob("*.log"):
        logfile.unlink()
    report = json.loads(path.read_text(encoding="utf-8"))
    report.update(
        session_requested=False,
        logs_isolated=False,
        log_hashes={},
        log_findings=game_run.log_findings(logs, [], expected_mounts=["C:/base"]),
    )
    findings = report["log_findings"]
    assert findings
    assert findings["missing_mounts"]
    if problem == "engine":
        findings["errors"]["Assertion failed"] = 1
    elif problem == "mod":
        findings["mod_errors"] = ["invalid sitai_rule"]
    elif problem == "unclassified":
        findings["unclassified_errors"] = ["VFSOpen Error: missing texture"]
    elif problem == "malformed":
        findings["errors"]["Assertion failed"] = "0"
    elif problem == "mounted":
        findings["mounted"] = ["Mounted Data: C:/base"]
    game_run.write_json(path, report)
    restarted = ExperimentLedger(ledger.path)
    if problem is not None:
        with pytest.raises(ValueError, match="日志指纹"):
            restarted.interrupt_pending()
        assert restarted.runs("test-plan")[0]["status"] == "reserved"
    else:
        restarted.interrupt_pending()
        row = restarted.runs("test-plan")[0]
        assert row["status"] == "interrupted"
        assert json.loads(row["errors"]) == []
        assert row["report_sha"]
        assert restarted.used_arms("test-plan", "scene-a") == 1
        reserve(restarted, request(), tmp_path / "new-attempt")


@pytest.mark.parametrize("field", ["run_id", "manifest_sha256"])
def test_中断报告身份不符阻止下一局且不消除原记录(tmp_path, field):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    run_id = reserve(ledger, request(), tmp_path / "one")
    path = published_failure(ledger, run_id, tmp_path / "one")
    report = json.loads(path.read_text(encoding="utf-8"))
    report["experiment"][field] = "changed"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="身份"):
        ledger.interrupt_pending()
    assert ledger.runs("test-plan")[0]["status"] == "reserved"


def test_历史失败导入幂等且消耗预算和错误次数(tmp_path):
    old = ExperimentLedger(tmp_path / "old.sqlite3")
    run_id = reserve(old, request(), tmp_path / "prior")
    path = published_failure(old, run_id, tmp_path / "prior")
    ledger = ExperimentLedger(tmp_path / "new.sqlite3")
    for _ in range(2):
        ledger.import_prior_failure(
            request(),
            path,
            checkpoint_sha256="a" * 64,
            game_version={"caligula_branch": "release/1.14.5"},
        )
    assert ledger.used_arms("test-plan", "scene-a") == 1
    second = reserve(ledger, request(pair=2), tmp_path / "two")
    ledger.finish(
        second,
        {"ok": False, "log_findings": {"errors": {"Assertion failed": 1}}},
        report_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="错误重复"):
        reserve(ledger, request(pair=3), tmp_path / "three")


@pytest.mark.parametrize("change", ["checkpoint", "version", "log"])
def test_历史失败输入或日志不符不得导入(tmp_path, change):
    old = ExperimentLedger(tmp_path / "old.sqlite3")
    run_id = reserve(old, request(), tmp_path / "prior")
    path = published_failure(old, run_id, tmp_path / "prior")
    if change == "log":
        (path.parent / "logs/error.log").write_bytes(b"tampered")
    ledger = ExperimentLedger(tmp_path / "new.sqlite3")
    with pytest.raises(ValueError):
        ledger.import_prior_failure(
            request(),
            path,
            checkpoint_sha256="b" * 64 if change == "checkpoint" else "a" * 64,
            game_version={
                "caligula_branch": "changed" if change == "version" else "release/1.14.5"
            },
        )
    assert ledger.used_arms("test-plan", "scene-a") == 0


def test_历史导入不能绕过场景上限(tmp_path):
    old = ExperimentLedger(tmp_path / "old.sqlite3")
    run_id = reserve(old, request(), tmp_path / "prior")
    path = published_failure(old, run_id, tmp_path / "prior")
    ledger = ExperimentLedger(tmp_path / "new.sqlite3")
    for scene in ("one", "two", "three"):
        if scene == "three":
            with pytest.raises(ValueError, match="场景预算"):
                ledger.import_prior_failure(
                    request(scene),
                    path,
                    checkpoint_sha256="a" * 64,
                    game_version={"caligula_branch": "release/1.14.5"},
                )
        else:
            ledger.import_prior_failure(
                request(scene),
                path,
                checkpoint_sha256="a" * 64,
                game_version={"caligula_branch": "release/1.14.5"},
            )
    assert ledger.used_arms("test-plan", "three") == 0


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
