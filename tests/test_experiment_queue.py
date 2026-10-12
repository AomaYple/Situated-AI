"""实验预算和任务身份须跨进程持久化，失败不能免费重置次数。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import replace

import pytest

from pdx.experiment_queue import ExperimentLedger, RunRequest, assess_compatibility

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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plan_id", ""),
        ("plan_id", " plan"),
        ("scene_id", None),
        ("scene_id", "scene\n"),
        ("arm", "unknown"),
        ("arm", True),
        ("arm", []),
        ("purpose", "unknown"),
        ("purpose", True),
        ("purpose", []),
        ("pair", True),
        ("pair", 1.0),
        ("pair", 0),
        ("max_scenes", True),
        ("max_scenes", 1.0),
        ("max_scenes", 3),
        ("max_pairs", True),
        ("max_pairs", 3.0),
        ("max_pairs", 4),
        ("max_months", True),
        ("max_months", "6"),
        ("max_months", float("nan")),
        ("max_months", float("inf")),
        ("max_months", 0),
        ("max_months", 7),
        ("min_available_mib", True),
        ("min_available_mib", float("nan")),
        ("min_available_mib", -1),
    ],
)
def test_用途预算严格拒绝参数反例(field, value):
    with pytest.raises(ValueError, match="预算"):
        replace(request(), **{field: value}).limits()


@pytest.mark.parametrize("purpose", ["instrument", "reconnaissance", "M3-A", "M3-B"])
def test_M3各用途都保留六个月上限(purpose):
    assert replace(request(), purpose=purpose).limits()["max_months"] == 6
    with pytest.raises(ValueError, match="预算"):
        replace(request(), purpose=purpose, max_months=6.01).limits()


@pytest.mark.parametrize("months", [6, 23.99, 121, True, float("nan")])
def test_正式M4窗口有下限和有界硬上限(months):
    with pytest.raises(ValueError, match="预算"):
        replace(request(), purpose="M4", max_months=months).limits()


def test_正式M4早后期各三对失败也计预算(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    formal = replace(request(), purpose="M4", max_months=24)
    for scene in ("early", "late"):
        for pair in range(1, 4):
            for attempt in range(2):
                arm = "vanilla"
                run_id = ledger.reserve(
                    replace(formal, scene_id=scene, arm=arm, pair=pair),
                    manifest={"checkpoint": "a" * 64, "months": 24},
                    evidence=tmp_path / f"{scene}-{pair}-{arm}-{attempt}",
                )
                ledger.finish(run_id, {"ok": False}, report_sha256="b" * 64)
    restarted = ExperimentLedger(ledger.path)
    assert len(restarted.runs("test-plan")) == 12
    with pytest.raises(ValueError, match="运行预算"):
        restarted.reserve(
            replace(formal, scene_id="late"), manifest={"months": 24}, evidence=tmp_path / "extra"
        )
    with pytest.raises(ValueError, match="场景预算"):
        restarted.reserve(
            replace(formal, scene_id="third"), manifest={"months": 24}, evidence=tmp_path / "third"
        )


@pytest.mark.parametrize("manifest", [{}, {"months": True}, {"months": 23}, {"months": 25}])
def test_正式M4实际窗口必须冻结且匹配预算(tmp_path, manifest):
    with pytest.raises(ValueError, match="窗口"):
        ExperimentLedger(tmp_path / "ledger.sqlite3").reserve(
            replace(request(), purpose="M4", max_months=24),
            manifest=manifest,
            evidence=tmp_path / "run",
        )


def test_M4噪声默认六个月且最多三次原版准备(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    noise = replace(request(), purpose="M4-noise", arm="vanilla")
    assert noise.max_months == 6
    for pair in range(1, 4):
        run_id = reserve(ledger, replace(noise, pair=pair), tmp_path / str(pair))
        ledger.finish(run_id, {"ok": False}, report_sha256="b" * 64)
    with pytest.raises(ValueError, match="运行预算"):
        reserve(ledger, noise, tmp_path / "fourth")
    for changed in (replace(noise, arm="fiscal"), replace(noise, max_months=121)):
        with pytest.raises(ValueError, match="预算"):
            changed.limits()
    assert replace(request(), purpose="safety", arm="vanilla", max_months=24).limits()


def test_M4噪声可显式登记长期同窗口但仍只有三次单臂预算(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    noise = replace(request(), purpose="M4-noise", arm="vanilla", max_months=24)
    assert noise.limits()["max_months"] == 24
    assert replace(noise, max_months=120).limits()["max_months"] == 120
    for pair in range(1, 4):
        run_id = ledger.reserve(
            replace(noise, pair=pair),
            manifest={"checkpoint": "a" * 64, "months": 24},
            evidence=tmp_path / str(pair),
        )
        ledger.finish(run_id, {"ok": False}, report_sha256="b" * 64)
    with pytest.raises(ValueError, match="运行预算"):
        ledger.reserve(
            noise, manifest={"checkpoint": "a" * 64, "months": 24}, evidence=tmp_path / "extra"
        )
    with pytest.raises(ValueError, match="预算"):
        replace(noise, max_months=121).limits()


def stop_manifest():
    return {
        "checkpoint": "a" * 64,
        "environment": {
            "game": {"caligula_branch": "release/1.14.5", "content_sha256": "b" * 64},
            "language": "l_english",
            "tools": {"analyzer.py": "c" * 64},
        },
        "game_hashes": {"common/ai_strategies/00_default.txt": "b" * 64},
        "probe_sources": {"instrument": "d" * 64},
        "sources": {"instrument": "d" * 64, "sitai_decision_candidate": "e" * 64},
        "months": 1,
    }


def two_failures(ledger, tmp_path, manifest=None):
    manifest = stop_manifest() if manifest is None else manifest
    for index in range(2):
        req = replace(request(), plan_id=f"old-{index}", scene_id=f"renamed-{index}")
        run_id = ledger.reserve(req, manifest=manifest, evidence=tmp_path / f"failed-{index}")
        ledger.finish(
            run_id,
            {"ok": False, "log_findings": {"errors": {"Assertion failed": 1}}},
            report_sha256="b" * 64,
        )


@pytest.mark.parametrize("purpose", ["instrument", "M3-A", "M4-noise", "M4"])
def test_错误停止事实跨用途计划和场景共享(tmp_path, purpose):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    two_failures(ledger, tmp_path)
    manifest = stop_manifest()
    manifest["months"] = 24 if purpose == "M4" else 1
    req = replace(
        request(),
        plan_id="new-plan",
        scene_id="new-scene",
        purpose=purpose,
        arm="vanilla",
        max_months=24 if purpose == "M4" else 6,
    )
    with pytest.raises(ValueError, match="错误重复"):
        ExperimentLedger(ledger.path).reserve(req, manifest=manifest, evidence=tmp_path / "new")
    assert ledger.runs("new-plan") == []


@pytest.mark.parametrize("change", ["tools", "candidate", "labels", "unknown", "missing", "bool"])
def test_无法证明新前提的变化不刷新停止事实(tmp_path, change):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    two_failures(ledger, tmp_path)
    manifest = stop_manifest()
    if change == "tools":
        manifest["environment"]["tools"] = {"renamed.py": "f" * 64}
    elif change == "candidate":
        manifest["sources"]["sitai_decision_candidate"] = "f" * 64
    elif change == "labels":
        manifest.update(plan_id="different", scene_id="different", months=2)
    elif change == "unknown":
        manifest["dynamic_dependency"] = "f" * 64
    elif change == "missing":
        manifest = {}
    else:
        manifest = {"checkpoint": True, "environment": {"game": True, "language": True}}
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


@pytest.mark.parametrize("change", ["checkpoint", "game-version", "game-hash", "language"])
def test_真实输入或环境不同可登记新计划(tmp_path, change):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    two_failures(ledger, tmp_path)
    manifest = stop_manifest()
    if change == "checkpoint":
        manifest["checkpoint"] = "f" * 64
    elif change == "game-version":
        manifest["environment"]["game"]["caligula_branch"] = "release/1.14.6"
    elif change == "game-hash":
        manifest["game_hashes"]["common/ai_strategies/00_default.txt"] = "f" * 64
    elif change == "language":
        manifest["environment"]["language"] = "l_simp_chinese"
    assert ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


@pytest.mark.parametrize(
    "change", ["aggregate", "add", "remove", "replace-scope", "missing-map", "invalid-map"]
)
def test_观测依赖集合或聚合指纹变化不刷新停止事实(tmp_path, change):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    previous = stop_manifest()
    previous["game_hashes"]["common/laws/00_laws.txt"] = "c" * 64
    two_failures(ledger, tmp_path, previous)
    manifest = json.loads(json.dumps(previous))
    manifest["environment"]["game"]["content_sha256"] = "f" * 64
    if change == "add":
        manifest["game_hashes"]["localization/english/politics_l_english.yml"] = "d" * 64
    elif change == "remove":
        del manifest["game_hashes"]["common/laws/00_laws.txt"]
    elif change == "replace-scope":
        manifest["game_hashes"] = {"common/new_scope.txt": "d" * 64}
    elif change == "missing-map":
        del manifest["game_hashes"]
    elif change == "invalid-map":
        manifest["game_hashes"] = {"../outside.txt": "f" * 64}
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")
    assert ledger.runs("test-plan") == []


def test_旧聚合记录缺单文件map不能因新增map刷新停止事实(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    previous = stop_manifest()
    del previous["game_hashes"]
    two_failures(ledger, tmp_path, previous)
    manifest = stop_manifest()
    manifest["environment"]["game"]["content_sha256"] = "f" * 64
    manifest["game_hashes"]["common/ai_strategies/00_default.txt"] = "f" * 64
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


def test_旧附表聚合上下文不解锁停止事实(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    assert ledger.runs("legacy") == []
    context = {
        "checkpoint": "a" * 64,
        "game:caligula_branch": "release/1.14.5",
        "game:content_sha256": "b" * 64,
    }
    with closing(sqlite3.connect(ledger.path)) as database, database:
        for index in range(2):
            evidence = str((tmp_path / f"prior-{index}/report.json").resolve())
            database.execute(
                "INSERT INTO prior_failures VALUES (?,?,?,?,?)",
                ("legacy", "old", evidence, "b" * 64, json.dumps(["Assertion failed"])),
            )
            database.execute(
                "INSERT INTO prior_failure_contexts VALUES (?,?)", (evidence, json.dumps(context))
            )
    manifest = stop_manifest()
    manifest["environment"]["game"]["content_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


def legacy_failures_with_originals(tmp_path, *, context=None, checkpoint="a" * 64):
    from pdx import game_run

    ledger = ExperimentLedger(tmp_path / "legacy.sqlite3")
    ledger.runs("none")
    for index in range(2):
        old = ExperimentLedger(tmp_path / f"old-{index}.sqlite3")
        directory = tmp_path / f"prior-{index}"
        run_id = reserve(old, request(), directory)
        path = published_failure(old, run_id, directory)
        report = json.loads(path.read_text(encoding="utf-8"))
        report["loaded_save"]["sha256"] = checkpoint
        report["language"] = "l_english"
        sources = directory / "sources/observer"
        sources.mkdir(parents=True)
        (sources / "observer.txt").write_bytes(b"frozen observer")
        report["source_hashes"] = {"observer": game_run.hashes(sources)}
        game_run.write_json(path, report)
        with closing(sqlite3.connect(ledger.path)) as database, database:
            database.execute(
                "INSERT INTO prior_failures VALUES (?,?,?,?,?)",
                (
                    "legacy",
                    "scene",
                    str(path.resolve()),
                    game_run.file_sha(path),
                    '["Assertion failed"]',
                ),
            )
            if context is not None:
                database.execute(
                    "INSERT INTO prior_failure_contexts VALUES (?,?)",
                    (str(path.resolve()), json.dumps(context)),
                )
    return ledger


@pytest.mark.parametrize("context", [None, {}])
@pytest.mark.parametrize("different_input", [False, True])
def test_旧未知上下文只读复核原件后按真实检查点停止(tmp_path, context, different_input):
    ledger = legacy_failures_with_originals(tmp_path, context=context)
    with closing(sqlite3.connect(ledger.path)) as database:
        originals = {
            table: database.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("prior_failures", "prior_failure_contexts")
        }
    manifest = stop_manifest()
    if different_input:
        manifest["checkpoint"] = "f" * 64
        assert ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")
    else:
        # 资源/探针或候选变化不能证明断言错误的前提解除。
        manifest["probe_sources"]["zz_sitai_resource_baseline"] = "f" * 64
        manifest["simulation"] = {"diagnostic": "f" * 64}
        with pytest.raises(ValueError, match="错误重复"):
            ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")
    with closing(sqlite3.connect(ledger.path)) as database:
        for table, rows in originals.items():
            assert database.execute(f"SELECT * FROM {table}").fetchall() == rows


@pytest.mark.parametrize(
    "damage",
    [
        "missing-report",
        "report-sha",
        "missing-logs",
        "log-sha",
        "checkpoint",
        "game",
        "game-unknown",
        "missing-sources",
        "source-sha",
        "source-extra",
        "source-traversal",
        "input-sha",
    ],
)
def test_旧未知上下文原件缺证或指纹改变继续保守停止(tmp_path, damage):
    from pdx import game_run

    ledger = legacy_failures_with_originals(tmp_path)
    for index in range(2):
        directory = tmp_path / f"prior-{index}"
        path = directory / "report.json"
        if damage == "missing-report":
            path.unlink()
        elif damage == "report-sha":
            path.write_bytes(path.read_bytes() + b" ")
        elif damage == "missing-logs":
            (directory / "logs/error.log").unlink()
        elif damage == "log-sha":
            (directory / "logs/error.log").write_bytes(b"changed")
        elif damage == "source-sha":
            (directory / "sources/observer/observer.txt").write_bytes(b"changed")
        elif damage == "source-extra":
            (directory / "sources/observer/extra.txt").write_bytes(b"extra")
        elif damage == "input-sha":
            (directory / "input.v3").write_bytes(b"different checkpoint")
        else:
            report = json.loads(path.read_text(encoding="utf-8"))
            if damage == "missing-sources":
                del report["source_hashes"]
            elif damage == "source-traversal":
                report["source_hashes"] = {"../observer": {"observer.txt": "b" * 64}}
            else:
                report["loaded_save" if damage == "checkpoint" else "game_version"] = (
                    {"unrecognized": "value"} if damage == "game-unknown" else {}
                )
            game_run.write_json(path, report)
            with closing(sqlite3.connect(ledger.path)) as database, database:
                database.execute(
                    "UPDATE prior_failures SET report_sha=? WHERE evidence=?",
                    (game_run.file_sha(path), str(path.resolve())),
                )
    manifest = stop_manifest()
    manifest["checkpoint"] = "f" * 64
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


@pytest.mark.parametrize("artifact", ["report", "logs", "sources", "input"])
def test_恢复旧上下文时原件并发变化仍保守停止(tmp_path, monkeypatch, artifact):
    from pdx import experiment_queue

    checkpoint = hashlib.sha256(b"checkpoint").hexdigest()
    ledger = legacy_failures_with_originals(tmp_path, checkpoint=checkpoint)
    for index in range(2):
        (tmp_path / f"prior-{index}/input.v3").write_bytes(b"checkpoint")
    original = experiment_queue._stop_context

    def change_after_context(manifest):
        result = original(manifest)
        if manifest.get("checkpoint") == checkpoint:
            for index in range(2):
                directory = tmp_path / f"prior-{index}"
                changed = {
                    "report": directory / "report.json",
                    "logs": directory / "logs/error.log",
                    "sources": directory / "sources/observer/observer.txt",
                    "input": directory / "input.v3",
                }[artifact]
                changed.write_bytes(changed.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(experiment_queue, "_stop_context", change_after_context)
    manifest = stop_manifest()
    manifest["checkpoint"] = "f" * 64
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


def test_保留归档输入字节匹配时可恢复旧检查点(tmp_path):
    checkpoint = hashlib.sha256(b"checkpoint").hexdigest()
    ledger = legacy_failures_with_originals(tmp_path, checkpoint=checkpoint)
    for index in range(2):
        (tmp_path / f"prior-{index}/input.v3").write_bytes(b"checkpoint")
    assert ledger.reserve(request(), manifest=stop_manifest(), evidence=tmp_path / "new")


@pytest.mark.parametrize(
    "value",
    [None, {}, [], True, {"../outside.txt": "b" * 64}, {"common/file.txt": "not-sha"}],
)
def test_旧报告声明畸形游戏指纹不能由检查点差异解锁(tmp_path, value):
    from pdx import game_run

    ledger = legacy_failures_with_originals(tmp_path)
    for index in range(2):
        path = tmp_path / f"prior-{index}/report.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["game_hashes"] = value
        game_run.write_json(path, report)
        with closing(sqlite3.connect(ledger.path)) as database, database:
            database.execute(
                "UPDATE prior_failures SET report_sha=? WHERE evidence=?",
                (game_run.file_sha(path), str(path.resolve())),
            )
    manifest = stop_manifest()
    manifest["checkpoint"] = "f" * 64
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


@pytest.mark.parametrize(
    "change", ["add", "remove", "replace", "dangling-link", "dangling-link-simulated"]
)
def test_旧归档输入读后增删或身份变化保持保守停止(tmp_path, monkeypatch, change):
    import os
    import stat
    from pathlib import Path

    from pdx import experiment_queue

    checkpoint = hashlib.sha256(b"checkpoint").hexdigest()
    ledger = legacy_failures_with_originals(tmp_path, checkpoint=checkpoint)
    for index in range(2):
        path = tmp_path / f"prior-{index}/input.v3"
        if change in {"remove", "replace"}:
            path.write_bytes(b"checkpoint")
        elif change == "dangling-link":
            probe = tmp_path / f"link-probe-{index}"
            try:
                probe.symlink_to(tmp_path / "missing-target")
            except OSError as exc:
                pytest.skip(f"当前平台未授予符号链接能力：{exc}")
            probe.unlink()
    original = experiment_queue._stop_context
    recovered = 0
    links = set()
    original_lstat = Path.lstat

    def linked_lstat(path, *args, **kwargs):
        if path in links:
            return os.stat_result((stat.S_IFLNK | 0o777, 1, 1, 1, 0, 0, 1, 0, 0, 0))
        return original_lstat(path, *args, **kwargs)

    if change == "dangling-link-simulated":
        monkeypatch.setattr(Path, "lstat", linked_lstat)

    def change_after_context(manifest):
        nonlocal recovered
        result = original(manifest)
        if manifest.get("checkpoint") == checkpoint:
            path = tmp_path / f"prior-{recovered}/input.v3"
            recovered += 1
            if change == "remove":
                path.unlink(missing_ok=True)
            elif change == "replace":
                replacement = path.with_suffix(".replacement")
                replacement.write_bytes(b"checkpoint")
                replacement.replace(path)
            elif change == "add":
                path.write_bytes(b"checkpoint")
            elif change == "dangling-link-simulated":
                links.add(path)
            else:
                path.symlink_to(tmp_path / "missing-target")
        return result

    monkeypatch.setattr(experiment_queue, "_stop_context", change_after_context)
    manifest = stop_manifest()
    manifest["checkpoint"] = "f" * 64
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


def test_共有原版文件变化即使集合增删仍可登记新前提(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    previous = stop_manifest()
    previous["game_hashes"]["common/laws/00_laws.txt"] = "c" * 64
    two_failures(ledger, tmp_path, previous)
    manifest = stop_manifest()
    manifest["game_hashes"]["common/ai_strategies/00_default.txt"] = "f" * 64
    manifest["game_hashes"]["localization/english/politics_l_english.yml"] = "d" * 64
    assert ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "new")


def test_旧SQLite版本化迁移保持原行和保守停止事实(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("CREATE TABLE plans(id TEXT PRIMARY KEY,limits_json TEXT NOT NULL)")
        database.execute(
            "CREATE TABLE runs(id TEXT PRIMARY KEY,plan TEXT,scene TEXT,arm TEXT,pair INTEGER,"
            "manifest TEXT,evidence TEXT,status TEXT,report_sha TEXT,errors TEXT)"
        )
        database.execute(
            "CREATE TABLE prior_failures(plan TEXT,scene TEXT,evidence TEXT,report_sha TEXT,"
            "errors TEXT,PRIMARY KEY(plan,scene,evidence))"
        )
        database.execute("INSERT INTO plans VALUES (?,?)", ("old-plan", "old frozen limits"))
        database.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "old-run",
                "old-plan",
                "old-scene",
                "control",
                1,
                json.dumps({"checkpoint": "a" * 64}),
                str(tmp_path / "run"),
                "rejected",
                "b" * 64,
                json.dumps(["Assertion failed"]),
            ),
        )
        database.execute(
            "INSERT INTO prior_failures VALUES (?,?,?,?,?)",
            (
                "old-plan",
                "old-scene",
                str(tmp_path / "prior/report.json"),
                "c" * 64,
                json.dumps(["Assertion failed"]),
            ),
        )
        originals = {
            table: database.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("plans", "runs", "prior_failures")
        }
    script = """
from pathlib import Path
import sys
from pdx.experiment_queue import ExperimentLedger, RunRequest
ledger = ExperimentLedger(Path(sys.argv[1]))
try:
    ledger.reserve(RunRequest('new', 'renamed', 'control'),
                   manifest={'checkpoint': 'a'*64}, evidence=Path(sys.argv[1]).parent/'new')
except ValueError as error:
    assert '错误重复' in str(error)
else:
    raise AssertionError('legacy stop lost')
assert ledger.used_arms('old-plan', 'old-scene') == 2
"""
    child = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(path)],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    with closing(sqlite3.connect(path)) as database, database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 1
        for table, rows in originals.items():
            assert database.execute(f"SELECT * FROM {table}").fetchall() == rows


def test_较新账本版本拒绝写入(tmp_path):
    path = tmp_path / "newer.sqlite3"
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="版本"):
        reserve(ExperimentLedger(path), request(), tmp_path / "new")
    with closing(sqlite3.connect(path)) as database, database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 999


def test_同一历史原件跨登记只计一局但与新局共享停止事实(tmp_path):
    old = ExperimentLedger(tmp_path / "old.sqlite3")
    run_id = reserve(old, request(), tmp_path / "prior")
    path = published_failure(old, run_id, tmp_path / "prior")
    ledger = ExperimentLedger(tmp_path / "new.sqlite3")
    for plan in ("one", "two"):
        ledger.import_prior_failure(
            replace(request(), plan_id=plan),
            path,
            checkpoint_sha256="a" * 64,
            game_version={"caligula_branch": "release/1.14.5"},
        )
    second = reserve(ledger, request(), tmp_path / "new-run")
    ledger.finish(
        second,
        {"ok": False, "log_findings": {"errors": {"Assertion failed": 1}}},
        report_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="错误重复"):
        reserve(ledger, replace(request(), plan_id="three"), tmp_path / "third")


@pytest.mark.parametrize("change", ["file-content", "added-file", "simulation"])
def test_探针诊断变化缺因果映射仍不能重开原版错误(tmp_path, change):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    manifest = stop_manifest()
    manifest["probe_sources"] = {"instrument": {"events/probe.txt": "d" * 64}}
    manifest["simulation"] = {"config": {"settings.txt": "e" * 64}}
    two_failures(ledger, tmp_path, manifest)
    changed = json.loads(json.dumps(manifest))
    if change == "file-content":
        changed["probe_sources"]["instrument"]["events/probe.txt"] = "f" * 64
    elif change == "added-file":
        changed["probe_sources"]["instrument"]["common/new.txt"] = "f" * 64
    else:
        changed["simulation"]["config"]["settings.txt"] = "f" * 64
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(request(), manifest=changed, evidence=tmp_path / "new")


def test_数据库迁移失败原状态可由新连接恢复(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("CREATE TABLE plans(id TEXT PRIMARY KEY,limits_json TEXT NOT NULL)")
        database.execute("INSERT INTO plans VALUES ('legacy','original')")
    original = sqlite3.connect

    class MigrationFailure(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if "CREATE TABLE IF NOT EXISTS prior_failure_contexts" in sql:
                raise sqlite3.OperationalError("injected migration failure")
            return super().execute(sql, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(
            sqlite3,
            "connect",
            lambda *args, **kwargs: original(*args, factory=MigrationFailure, **kwargs),
        )
        with pytest.raises(sqlite3.OperationalError, match="migration failure"):
            ExperimentLedger(path).runs("legacy")
    with closing(sqlite3.connect(path)) as database, database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 0
        assert database.execute("SELECT * FROM plans").fetchall() == [("legacy", "original")]
        assert database.execute("SELECT name FROM sqlite_master WHERE name='runs'").fetchall() == []
    assert reserve(ExperimentLedger(path), request(), tmp_path / "new")
    with closing(sqlite3.connect(path)) as database, database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 1


def test_历史原件换计划不能接受改写报告或重复导入已登记局(tmp_path):
    from pdx import game_run

    original = ExperimentLedger(tmp_path / "original.sqlite3")
    run_id = reserve(original, request(), tmp_path / "prior")
    path = published_failure(original, run_id, tmp_path / "prior")
    version = {"caligula_branch": "release/1.14.5"}
    with pytest.raises(ValueError, match="重复计次"):
        original.import_prior_failure(
            replace(request(), plan_id="renamed"),
            path,
            checkpoint_sha256="a" * 64,
            game_version=version,
        )
    ledger = ExperimentLedger(tmp_path / "new.sqlite3")
    ledger.import_prior_failure(request(), path, checkpoint_sha256="a" * 64, game_version=version)
    report = json.loads(path.read_text(encoding="utf-8"))
    report["additional_note"] = "changed"
    game_run.write_json(path, report)
    with pytest.raises(ValueError, match="发生改变"):
        ledger.import_prior_failure(
            replace(request(), plan_id="renamed"),
            path,
            checkpoint_sha256="a" * 64,
            game_version=version,
        )


def compatibility_manifest():
    manifest = stop_manifest()
    manifest["environment"].update(disabled_dlc=[], mount_allowlist=["C:/base"])
    manifest.update(
        timeout=3600,
        profile=False,
        allow_save_upgrade=False,
        keep_save=False,
        provenance={
            "schema": 1,
            "files": {"C:/tools/analyzer.py": "c" * 64},
            "callback": {"path": "C:/tools/analyzer.py", "sha256": "c" * 64},
            "runtime": {
                "python": "3.14.7",
                "platform": "Windows-10",
                "libraries": {"psutil": "7.2.2", "pywin32": None},
            },
            "dependency_scope": "conservative-full",
        },
        observation={
            "version": "readonly-1",
            "package": "natural-response",
            "observers": ["PRU", "FRA"],
        },
    )
    return manifest


def test_完整冻结事实相同仅判兼容而不授权样本复用():
    original = compatibility_manifest()
    before = json.loads(json.dumps(original))
    current = json.loads(json.dumps(original))
    result = assess_compatibility(original, current)
    assert result["state"] == "reusable"
    assert result["compatible"] is True
    assert result["requires_qualification_review"] is True
    assert result["sample_reuse_authorized"] is False
    assert result["changed_fields"] == result["missing_fields"] == result["invalid_fields"] == []
    assert original == before == current


@pytest.mark.parametrize(
    "field",
    [
        "checkpoint",
        "sources",
        "probe_sources",
        "game",
        "language",
        "disabled_dlc",
        "mount_allowlist",
        "months",
        "observation",
        "profile",
        "timeout",
    ],
)
def test_已识别运行输入观测窗口改变必须重跑(field):
    original = compatibility_manifest()
    current = json.loads(json.dumps(original))
    if field == "checkpoint":
        current[field] = "f" * 64
    elif field in {"sources", "probe_sources"}:
        current[field]["instrument"] = {"events/probe.txt": "f" * 64}
    elif field == "game":
        current["environment"]["game"]["content_sha256"] = "f" * 64
    elif field == "language":
        current["environment"]["language"] = "l_simp_chinese"
    elif field == "disabled_dlc":
        current["environment"][field] = ["dlc-optional"]
    elif field == "mount_allowlist":
        current["environment"][field].append("C:/dlc/optional")
    elif field == "months":
        current[field] = 2
    elif field == "observation":
        current[field]["version"] = "readonly-2"
    elif field == "profile":
        current[field] = True
    else:
        current[field] = 1800
    result = assess_compatibility(original, current)
    assert result["state"] == "must-rerun"
    assert result["compatible"] is False
    assert result["changed_fields"]


@pytest.mark.parametrize("change", ["tools", "callback", "metadata", "analysis-profile"])
def test_未审核工具或回调改变不能冒称只需重解析(change):
    original = compatibility_manifest()
    current = json.loads(json.dumps(original))
    if change == "tools":
        current["environment"]["tools"]["analyzer.py"] = "f" * 64
    elif change == "callback":
        current["callback"] = "custom.analyze"
    elif change == "analysis-profile":
        current["analysis_profile"] = {"analysis_only": True, "reviewed": True}
    else:
        current["extra"] = "changed"
    result = assess_compatibility(original, current)
    assert result["state"] == "unknown"
    assert result["reasons"] == ["manifest.change_scope_unreviewed"]
    assert result["changed_fields"]


@pytest.mark.parametrize("value", [True, False, {}, [], {"custom": "f" * 64}])
def test_未审核动态依赖声明即使未变也无法判断(value):
    manifest = compatibility_manifest()
    manifest["dynamic_dependencies"] = value
    result = assess_compatibility(manifest, manifest)
    assert result["state"] == "unknown"
    assert result["reasons"] == ["manifest.dynamic_dependencies_unreviewed"]


@pytest.mark.parametrize("field", ["disabled_dlc", "mount_allowlist"])
@pytest.mark.parametrize("value", [None, True, {}, [True], ["repeated", "repeated"]])
def test_DLC和挂载缺证或结构无效不能兼容(field, value):
    manifest = compatibility_manifest()
    manifest["environment"][field] = value
    result = assess_compatibility(manifest, manifest)
    assert result["state"] == "unknown"
    assert f"environment.{field}" in result["invalid_fields"]


@pytest.mark.parametrize("change", ["callback", "scope", "runtime", "files", "null-callback"])
def test_执行来源未知或改变保持兼容性未知(change):
    original = compatibility_manifest()
    current = json.loads(json.dumps(original))
    provenance = current["provenance"]
    if change == "callback":
        provenance["callback"]["sha256"] = "f" * 64
        provenance["files"][provenance["callback"]["path"]] = "f" * 64
    elif change == "scope":
        provenance["dependency_scope"] = "unknown"
    elif change == "runtime":
        provenance["runtime"]["libraries"]["psutil"] = "8.0"
    elif change == "files":
        provenance["files"]["C:/tools/dynamic.py"] = "d" * 64
    else:
        provenance["callback"] = None
    assert assess_compatibility(original, current)["state"] == "unknown"
    if change in {"scope", "null-callback"}:
        assert assess_compatibility(current, current)["state"] == "unknown"


@pytest.mark.parametrize(
    "field", ["checkpoint", "probe_sources", "months", "observation", "tools", "game-hash"]
)
def test_旧证据缺关键字段不能由相同内容判为兼容(field):
    manifest = compatibility_manifest()
    if field == "tools":
        del manifest["environment"]["tools"]
    elif field == "game-hash":
        del manifest["environment"]["game"]["content_sha256"]
    else:
        del manifest[field]
    result = assess_compatibility(manifest, manifest)
    assert result["state"] == "unknown"
    assert result["missing_fields"] or result["invalid_fields"]


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "1"])
def test_兼容性字段拒绝布尔和非有限窗口(value):
    manifest = compatibility_manifest()
    manifest["months"] = value
    assert assess_compatibility(manifest, manifest)["state"] == "unknown"


def test_冻结资格上下文的观测契约可读取且改变仍需重跑():
    original = compatibility_manifest()
    observation = original.pop("observation")
    original["qualification"] = {"context": {"observation": observation}}
    current = json.loads(json.dumps(original))
    assert assess_compatibility(original, current)["state"] == "reusable"
    current["qualification"]["context"]["observation"]["observers"] = ["PRU", "GBR"]
    result = assess_compatibility(original, current)
    assert result["state"] == "must-rerun"
    assert "qualification.context.observation.observers" in result["changed_fields"]


def test_账本来源缺失兼容性未知且不改变冻结与停止事实(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    manifest = compatibility_manifest()
    assert assess_compatibility(None, manifest)["state"] == "unknown"
    run_id = ledger.reserve(request(), manifest=manifest, evidence=tmp_path / "one")
    ledger.finish(run_id, {"ok": False}, report_sha256="b" * 64)
    previous = json.loads(ledger.runs("test-plan")[-1]["manifest"])
    result = assess_compatibility(previous, manifest)
    assert result["state"] == "reusable"
    changed = json.loads(json.dumps(manifest))
    changed["environment"]["tools"]["analyzer.py"] = "f" * 64
    assert assess_compatibility(previous, changed)["state"] == "unknown"
    with pytest.raises(ValueError, match="冻结输入"):
        ledger.reserve(request(pair=2), manifest=changed, evidence=tmp_path / "two")
    assert len(ledger.runs("test-plan")) == 1


@pytest.mark.parametrize("purpose", ["instrument", "M4-noise", "M4"])
@pytest.mark.parametrize("error", ["Assertion failed", "unclassified-error"])
def test_无关政治诊断或候选变化不能跨用途刷新引擎错误(tmp_path, purpose, error):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    manifest = stop_manifest()
    manifest["probe_sources"]["politics"] = {"events/diagnostic.txt": "e" * 64}
    for index in range(2):
        run_id = ledger.reserve(
            replace(request(), plan_id=f"old-{index}"),
            manifest=manifest,
            evidence=tmp_path / str(index),
        )
        ledger.finish(
            run_id,
            {"ok": False, "log_findings": {"errors": {error: 1}}},
            report_sha256="b" * 64,
        )
    changed = json.loads(json.dumps(manifest))
    changed["probe_sources"]["politics"]["events/diagnostic.txt"] = "f" * 64
    changed["sources"]["sitai_decision_candidate"] = "f" * 64
    changed["simulation"] = {"diagnostic": "f" * 64}
    changed["months"] = 24 if purpose == "M4" else 1
    req = replace(
        request(),
        plan_id="renamed-plan",
        scene_id="renamed-scene",
        arm="vanilla",
        purpose=purpose,
        max_months=24 if purpose == "M4" else 6,
    )
    with pytest.raises(ValueError, match="错误重复"):
        ledger.reserve(req, manifest=changed, evidence=tmp_path / "new")


def test_旧附表探针和诊断上下文字段不能成为隐式重开依据(tmp_path):
    ledger = ExperimentLedger(tmp_path / "legacy.sqlite3")
    ledger.runs("none")
    with closing(sqlite3.connect(ledger.path)) as database, database:
        for index in range(2):
            evidence = str(tmp_path / str(index) / "report.json")
            database.execute(
                "INSERT INTO prior_failures VALUES (?,?,?,?,?)",
                (f"old-{index}", "old-scene", evidence, "b" * 64, '["Assertion failed"]'),
            )
            database.execute(
                "INSERT INTO prior_failure_contexts VALUES (?,?)",
                (
                    evidence,
                    json.dumps(
                        {
                            "checkpoint": "a" * 64,
                            "probe:politics": "e" * 64,
                            "simulation:diagnostic": "e" * 64,
                        }
                    ),
                ),
            )
    changed = stop_manifest()
    changed["probe_sources"] = {"politics": "f" * 64}
    changed["simulation"] = {"diagnostic": "f" * 64}
    with pytest.raises(ValueError, match="错误重复"):
        ExperimentLedger(ledger.path).reserve(
            request(), manifest=changed, evidence=tmp_path / "new"
        )
    assert ledger.runs("test-plan") == []


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("Assertion failed", "Assertion failed"),
        ("VFSOpen Error", "unclassified-error"),
        ("Mod error", "unclassified-mod-error"),
        ("future-error", "unclassified-error"),
        (True, "unclassified-error"),
        (None, "unclassified-error"),
    ],
)
@pytest.mark.parametrize("findings", [None, {}, {"errors": {}}, {"errors": []}])
def test_连续损坏归档仍保留早停守卫错误且跨计划停止(tmp_path, kind, expected, findings):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    for index in range(2):
        req = replace(request(), plan_id=f"damaged-{index}", scene_id=f"renamed-{index}")
        run_id = reserve(ledger, req, tmp_path / str(index))
        report = {
            "ok": False,
            "early_stop": {"kind": kind, "log": "error.log", "context": "guard saw error"},
            "cleanup_errors": ["汇总本局证据：归档损坏"],
            "log_hashes": {},
        }
        if findings is not None:
            report["log_findings"] = findings
        ledger.finish(run_id, report, report_sha256="b" * 64)
        assert expected in json.loads(ledger.runs(req.plan_id)[0]["errors"])
    with pytest.raises(ValueError, match="错误重复"):
        reserve(
            ExperimentLedger(ledger.path),
            replace(request(), plan_id="third", scene_id="new"),
            tmp_path / "third",
        )


def test_实时守卫与最终日志同一错误只计该局一次(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    run_id = reserve(ledger, request(), tmp_path / "first")
    ledger.finish(
        run_id,
        {
            "ok": False,
            "early_stop": {"kind": "Assertion failed"},
            "log_findings": {"errors": {"Assertion failed": 2}},
        },
        report_sha256="b" * 64,
    )
    assert json.loads(ledger.runs("test-plan")[0]["errors"]) == ["Assertion failed"]
    assert reserve(ledger, replace(request(), plan_id="second"), tmp_path / "second")


def test_噪声与正式控制窗口不符不得判为可复用():
    noise = compatibility_manifest()
    control = json.loads(json.dumps(noise))
    noise["months"] = 6
    control["months"] = 24
    result = assess_compatibility(noise, control)
    assert result["state"] == "must-rerun"
    assert result["compatible"] is False
    assert result["sample_reuse_authorized"] is False


@pytest.mark.parametrize("purpose", ["M3-A", "M3-B", "M4"])
@pytest.mark.parametrize(
    "status", ["missing", "reserved", "rejected", "complete-without-originals"]
)
def test_正式候选不能仅靠控制状态或跨配对控制派发(tmp_path, purpose, status):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    req = replace(
        request(),
        purpose=purpose,
        arm="vanilla" if purpose == "M4" else "control",
        max_months=24 if purpose == "M4" else 6,
    )
    manifest = {"checkpoint": "a" * 64, "months": 24 if purpose == "M4" else 1}
    if status != "missing":
        run_id = ledger.reserve(req, manifest=manifest, evidence=tmp_path / "control")
        if status != "reserved":
            ledger.finish(
                run_id, {"ok": status == "complete-without-originals"}, report_sha256="b" * 64
            )
    with pytest.raises(ValueError, match="控制先行"):
        ledger.reserve(
            replace(req, arm="candidate"), manifest=manifest, evidence=tmp_path / "candidate"
        )
    with pytest.raises(ValueError, match="控制先行"):
        ledger.reserve(
            replace(req, arm="candidate", pair=2),
            manifest=manifest,
            evidence=tmp_path / "other-pair",
        )
    assert len(ledger.runs(req.plan_id)) == (status != "missing")


def formal_control_bundle(tmp_path):
    from test_experiment_evidence import _bundle, _validate

    from pdx import game_run

    original = _bundle(tmp_path / "qualification")
    qualified = _validate(original)
    assert qualified["allowed"], qualified
    registration = json.loads(original["registration_path"].read_text(encoding="utf-8"))
    raw_report = json.loads(original["run_path"].read_text(encoding="utf-8"))
    req = RunRequest(
        registration["plan_id"],
        registration["scene_id"],
        "control",
        purpose="M3-A",
    )
    manifest = {
        "checkpoint": registration["checkpoint_sha256"],
        "sources": registration["arm_source_hashes"]["control"],
        "probe_sources": {
            key: value
            for key, value in registration["source_hashes"].items()
            if key != "sitai_decision_candidate"
        },
        "environment": {
            "game": {
                **raw_report["game_version"],
                "content_sha256": hashlib.sha256(
                    json.dumps(raw_report["game_hashes"], sort_keys=True).encode("utf-8")
                ).hexdigest(),
            },
            "language": registration["language"],
            "disabled_dlc": [],
        },
        "months": 1,
        "qualification": qualified,
        "qualification_report": str(original["path"].resolve()),
        "qualification_registration_sha256": game_run.file_sha(original["registration_path"]),
    }
    candidate = json.loads(json.dumps(manifest))
    candidate["sources"] = registration["arm_source_hashes"]["neutrality"]
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    directory = tmp_path / "control"
    run_id = ledger.reserve(req, manifest=manifest, evidence=directory)
    shutil.copytree(original["run_path"].parent, directory)
    raw_report.update(
        evidence=str(directory.resolve()),
        qualification_report=str(original["path"].resolve()),
        checkpoint_preflight={
            "sha256": registration["checkpoint_sha256"],
            "qualification": qualified,
        },
        experiment={
            "run_id": run_id,
            "plan_id": req.plan_id,
            "scene_id": req.scene_id,
            "arm": req.arm,
            "pair": req.pair,
            "purpose": req.purpose,
            "limits": req.limits(),
            "manifest_sha256": ledger.manifest_sha256(run_id),
        },
    )
    path = directory / "report.json"
    game_run.write_json(path, raw_report)
    return ledger, req, candidate, path, original


def finish_control(ledger, req, path):
    from pdx import game_run

    row = ledger.runs(req.plan_id)[-1]
    ledger.finish(
        row["id"],
        json.loads(path.read_text(encoding="utf-8")),
        report_sha256=game_run.file_sha(path),
    )


def test_当前控制原件合格才允许正式M3候选(tmp_path):
    ledger, req, manifest, path, _original = formal_control_bundle(tmp_path)
    finish_control(ledger, req, path)
    run_id = ledger.reserve(
        replace(req, arm="neutrality"), manifest=manifest, evidence=tmp_path / "candidate"
    )
    assert ledger.runs(req.plan_id)[-1]["id"] == run_id


@pytest.mark.parametrize(
    "damage",
    [
        "report-sha",
        "identity",
        "source",
        "log",
        "qualification",
        "shared-opportunity",
        "window",
        "pair",
        "purpose",
        "game-content",
    ],
)
def test_控制原件身份或机会失效时拒绝正式候选(tmp_path, damage):
    from pdx import game_run

    ledger, req, manifest, path, _original = formal_control_bundle(tmp_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    if damage == "report-sha":
        finish_control(ledger, req, path)
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    else:
        if damage == "identity":
            report["experiment"]["run_id"] = "other-run"
        elif damage == "source":
            next((path.parent / "sources").rglob("*.txt")).write_text("changed", encoding="utf-8")
        elif damage == "log":
            (path.parent / "logs/error.log").write_text("Assertion failed\n", encoding="utf-8")
        elif damage == "qualification":
            report["checkpoint_preflight"]["qualification"] = {"allowed": True}
        elif damage == "shared-opportunity":
            debug = path.parent / "logs/debug.log"
            raw = debug.read_text(encoding="utf-8").replace("PRU;CAN_INIT;yes", "PRU;CAN_INIT;no")
            debug.write_text(raw, encoding="utf-8")
            report["log_hashes"] = game_run.hashes(debug.parent)
        elif damage == "window":
            report["progress"]["end"] = "1838.2.1"
        elif damage == "pair":
            report["experiment"]["pair"] = 2
        elif damage == "game-content":
            report["game_hashes"][next(iter(report["game_hashes"]))] = "0" * 64
        else:
            report["experiment"]["purpose"] = "instrument"
        game_run.write_json(path, report)
        finish_control(ledger, req, path)
    with pytest.raises(ValueError, match="控制先行"):
        ledger.reserve(
            replace(req, arm="neutrality"), manifest=manifest, evidence=tmp_path / "candidate"
        )
    assert len(ledger.runs(req.plan_id)) == 1


@pytest.mark.parametrize("damage", ["missing-sha", "duplicate"])
def test_控制冻结指纹或唯一性缺失时拒绝候选(tmp_path, damage):
    ledger, req, manifest, path, _original = formal_control_bundle(tmp_path)
    finish_control(ledger, req, path)
    with closing(sqlite3.connect(ledger.path)) as database, database:
        if damage == "missing-sha":
            database.execute("UPDATE runs SET report_sha=NULL")
        else:
            # 模拟旧账本或人工合并产生的重复完成事实，不能任意挑一条信任。
            database.execute(
                "INSERT INTO runs SELECT ?,plan,scene,arm,pair,manifest,?,status,report_sha,errors "
                "FROM runs",
                ("duplicate-control", str((tmp_path / "duplicate").resolve())),
            )
    with pytest.raises(ValueError, match="控制先行"):
        ledger.reserve(
            replace(req, arm="neutrality"), manifest=manifest, evidence=tmp_path / "candidate"
        )
    assert len(ledger.runs(req.plan_id)) == (2 if damage == "duplicate" else 1)


@pytest.mark.parametrize("identity", ["plan", "scene"])
def test_其他计划或场景控制不能满足本次候选(tmp_path, identity):
    ledger, req, manifest, path, _original = formal_control_bundle(tmp_path)
    finish_control(ledger, req, path)
    candidate = replace(req, arm="neutrality")
    candidate = replace(candidate, **{f"{identity}_id": f"other-{identity}"})
    with pytest.raises(ValueError, match="控制先行"):
        ledger.reserve(candidate, manifest=manifest, evidence=tmp_path / "candidate")
    assert len(ledger.runs(req.plan_id)) == 1
    if identity == "plan":
        assert ledger.runs(candidate.plan_id) == []


@pytest.mark.parametrize("artifact", ["report", "source", "log"])
def test_独立控制复核后原件改变也拒绝候选(tmp_path, monkeypatch, artifact):
    from pdx import experiment_evidence

    ledger, req, manifest, path, _original = formal_control_bundle(tmp_path)
    finish_control(ledger, req, path)
    original_review = experiment_evidence.review_control

    def review_then_change(*args, **kwargs):
        reviewed = original_review(*args, **kwargs)
        assert reviewed["allowed"], reviewed
        changed = {
            "report": path,
            "source": next((path.parent / "sources").rglob("*.txt")),
            "log": path.parent / "logs/debug.log",
        }[artifact]
        changed.write_bytes(changed.read_bytes() + b"\n")
        return reviewed

    monkeypatch.setattr(experiment_evidence, "review_control", review_then_change)
    with pytest.raises(ValueError, match="复核中变化"):
        ledger.reserve(
            replace(req, arm="neutrality"), manifest=manifest, evidence=tmp_path / "candidate"
        )
    assert len(ledger.runs(req.plan_id)) == 1
