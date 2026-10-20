"""检查点预检不能把可载入、未知机会与实际行为资格混为一谈。"""

from __future__ import annotations

import hashlib
import json
import shutil
from typing import Any

import pytest

from pdx import checkpoint_catalog, game_run
from pdx.textio import text_bytes

pytestmark = pytest.mark.unit


def save(path, *, version="1.14.5", extra=b""):
    path.write_bytes(
        ('SAV0100\nmeta_data={version="' + version + '" game_date=1836.2.1}\n').encode()
        + b"player_manager={database={}}\n"
        + extra
    )
    return path


def test_有效观察者不代表已知机会(tmp_path):
    path = save(tmp_path / "clean.v3")
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["state"] == "opportunity-unknown"
    assert result["instrument_suitable"] is True
    assert result["opportunity_count"] is None
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert checkpoint_catalog.preflight(result, purpose="instrument", months=1)["allowed"]
    assert not checkpoint_catalog.preflight(result, purpose="M3-B", months=1)["allowed"]


@pytest.mark.parametrize("extra", [b"setting_sitai_old=yes", b'settings={""}'])
def test_旧状态和空规则拒绝且保留证据(tmp_path, extra):
    path = save(tmp_path / "bad.v3", extra=extra)
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["state"] == "rejected"
    assert result["reasons"]
    assert result["sha256"]
    assert path.exists()


def test_版本不同仅显式升级仪器可用(tmp_path):
    path = save(tmp_path / "old.v3", version="1.14.4")
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert not checkpoint_catalog.preflight(result, purpose="instrument", months=1)["allowed"]
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5", allow_save_upgrade=True)
    assert result["state"] == "instrument-suitable"
    assert not checkpoint_catalog.preflight(result, purpose="M3-A", months=1)["allowed"]


@pytest.mark.parametrize("months", [0, -1, float("nan"), float("inf"), 7])
def test_探索预算不接受无限或超额(tmp_path, months):
    result = checkpoint_catalog.inspect(save(tmp_path / "clean.v3"), expected_version="1.14.5")
    assert not checkpoint_catalog.preflight(result, purpose="reconnaissance", months=months)[
        "allowed"
    ]


def test_正式证据不能由未知或评分结果提名(tmp_path):
    result = checkpoint_catalog.inspect(save(tmp_path / "clean.v3"), expected_version="1.14.5")
    for purpose in ("M3-A", "M3-B"):
        decision = checkpoint_catalog.preflight(result, purpose=purpose, months=6)
        assert not decision["allowed"]
        assert "opportunity.unverified" in decision["reasons"]


def origin(tmp_path, *, clean=True):
    """冻结真实报告结构，原日志与源文件独立留存供当前门禁复核。"""
    root = tmp_path / "run"
    path = root / "saves" / "autosave.v3"
    path.parent.mkdir(parents=True)
    save(path)
    logdir = root / "logs"
    logdir.mkdir()
    (logdir / "debug.log").write_bytes(b"Mounted Data: base\nMounted Data: probe\n")
    (logdir / "error.log").write_bytes(b"" if clean else b"Assertion failed: bad world\n")
    source = root / "sources" / "probe" / "observer.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"observer = yes\n")
    raw = source.read_bytes()
    report: dict[str, Any] = {
        "ok": True,  # 故意保留历史误判，须以归档重新核验。
        "cleanup_errors": [],
        "checkpoint": {"hashes": {path.name: game_run.file_sha(path)}},
        "loaded_save": {"sha256": "a" * 64, "header": {"observer": "yes"}},
        "game_version": {"caligula_branch": "release/1.14.5"},
        "mount_allowlist": ["base", "probe"],
        "source_hashes": {"probe": {source.name: hashlib.sha256(raw).hexdigest()}},
        "deployed_hashes": {
            "probe": {source.name: hashlib.sha256(text_bytes(raw.decode(), game=True)).hexdigest()}
        },
        "log_hashes": game_run.hashes(logdir),
        "log_findings": game_run.log_findings(
            logdir, ["base", "probe"], expected_mounts=["base", "probe"]
        ),
    }
    report_path = root / "report.json"
    game_run.write_json(report_path, report)
    return path, report_path


def test_失败局输出不能只凭观察者头放行(tmp_path):
    path, report = origin(tmp_path, clean=False)
    original = path.read_bytes(), report.read_bytes()
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["state"] == "rejected"
    assert result["instrument_suitable"] is False
    assert "origin.not_clean" in result["reasons"]
    assert not checkpoint_catalog.preflight(result, purpose="safety", months=1)["allowed"]
    assert (path.read_bytes(), report.read_bytes()) == original


def test_干净来源只放行仪器且区分载入与输出指纹(tmp_path):
    path, report = origin(tmp_path)
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["instrument_suitable"] is True
    assert result["formal_pair_suitable"] is False
    assert result["origin_reports"][0]["path"] == str(report.resolve())
    assert result["sha256"] != "a" * 64
    assert result["opportunity_count"] is None


@pytest.mark.parametrize("damage", ["log", "source", "digest", "missing_cleanup", "malformed"])
def test_来源损坏或缺证据不静默放行(tmp_path, damage):
    path, report_path = origin(tmp_path)
    if damage == "log":
        (report_path.parent / "logs" / "error.log").write_bytes(b"changed\n")
    elif damage == "source":
        (report_path.parent / "sources" / "probe" / "observer.txt").write_bytes(b"changed\n")
    elif damage == "malformed":
        report_path.write_bytes(b"[]")
    else:
        report = json.loads(report_path.read_bytes())
        if damage == "digest":
            report["checkpoint"]["hashes"][path.name] = "b" * 64
        else:
            report.pop("cleanup_errors")
        game_run.write_json(report_path, report)
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["state"] == "rejected"
    assert result["instrument_suitable"] is False
    assert result["origin_reports"]
    assert result["origin_reports"][0]["sha256"] == game_run.file_sha(report_path)


def test_失败存档复制改名仍由内容关联拒绝(tmp_path):
    path, _ = origin(tmp_path, clean=False)
    copy = tmp_path / "renamed.v3"
    shutil.copyfile(path, copy)
    result = checkpoint_catalog.catalog(tmp_path, expected_version="1.14.5")
    assert result["state_counts"] == {"rejected": 2}
    assert all(row["instrument_suitable"] is False for row in result["entries"])
    assert all(row["origin_reports"] for row in result["entries"])
    assert copy.exists()
    assert path.exists()


def test_缺少日志的报告仍保留输出指纹和拒绝原因(tmp_path):
    path, report_path = origin(tmp_path)
    shutil.rmtree(report_path.parent / "logs")
    result = checkpoint_catalog.catalog(tmp_path, expected_version="1.14.5")
    assert result["reports"][0]["output_sha256"] == [game_run.file_sha(path)]
    assert result["entries"][0]["state"] == "rejected"


def test_局部来源指纹匹配也不能覆盖其他失败来源(tmp_path):
    path, _ = origin(tmp_path)
    failed_root = tmp_path / "other"
    failed_root.mkdir()
    origin(failed_root, clean=False)
    result = checkpoint_catalog.catalog(tmp_path, expected_version="1.14.5")
    assert all(row["state"] == "rejected" for row in result["entries"])
    assert len(result["entries"][0]["origin_reports"]) == 2
    assert path.exists()


def test_空的外部报告列表不能绕过局部失败来源(tmp_path):
    path, _ = origin(tmp_path, clean=False)
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5", origin_reports=[])
    assert result["state"] == "rejected"
    assert "origin.not_clean" in result["reasons"]


@pytest.mark.parametrize(
    "field", ["loaded_save_header", "game_version", "source_hashes", "log_findings"]
)
def test_嵌套报告结构损坏保留指纹且拒绝而不是崩溃(tmp_path, field):
    path, report_path = origin(tmp_path)
    report = json.loads(report_path.read_bytes())
    if field == "loaded_save_header":
        report["loaded_save"]["header"] = []
    else:
        report[field] = []
    game_run.write_json(report_path, report)
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["instrument_suitable"] is False
    assert result["origin_reports"][0]["sha256"] == game_run.file_sha(report_path)
    assert result["origin_reports"][0]["output_sha256"] == [game_run.file_sha(path)]


def test_实验存档局部来源报告缺失拒绝而不是当作普通外部存档(tmp_path):
    path, report_path = origin(tmp_path)
    report_path.unlink()
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["state"] == "rejected"
    assert "origin.output_unverified" in result["reasons"]
    assert "origin.not_clean" in result["reasons"]


@pytest.mark.parametrize(
    "damage", [None, "vfs", "source", "missing_cleanup", "header", "output", "version", "loaded"]
)
def test_原版新局检查点来源独立复核不伪造载入或行为资格(tmp_path, damage):
    path, report_path = origin(tmp_path)
    path = path.rename(path.with_name("checkpoint.v3"))
    shutil.rmtree(report_path.parent / "sources")
    logs = report_path.parent / "logs"
    (logs / "debug.log").write_bytes(b"Mounted Data: base\n")
    if damage == "vfs":
        (logs / "error.log").write_bytes(b"VFSOpen Error: missing texture\n")
    report: dict[str, Any] = {
        "kind": "vanilla_checkpoint_preparation",
        "ok": True,
        "content_load": "vanilla_only",
        "session_requested": True,
        "logs_isolated": True,
        "cleanup_errors": [],
        "source_hashes": {},
        "deployed_hashes": {},
        "game_version": {"caligula_branch": "release/1.14.5"},
        "mount_allowlist": ["base"],
        "log_hashes": game_run.hashes(logs),
        "checkpoint": {
            "header": game_run.save_header(path),
            "hashes": {path.name: game_run.file_sha(path)},
        },
    }
    if damage == "source":
        report["source_hashes"] = {"undeclared": {"file.txt": "a" * 64}}
    elif damage == "missing_cleanup":
        report.pop("cleanup_errors")
    elif damage == "header":
        report["checkpoint"]["header"]["observer"] = "no"
    elif damage == "output":
        path.write_bytes(path.read_bytes() + b"changed")
    elif damage == "version":
        report["game_version"]["caligula_branch"] = "release/1.15"
    elif damage == "loaded":
        report["loaded_save"] = {"sha256": "a" * 64}
    game_run.write_json(report_path, report)
    original = report_path.read_bytes()
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert report_path.read_bytes() == original
    assert result["instrument_suitable"] is (damage is None)
    assert result["formal_pair_suitable"] is False
    assert result["opportunity_count"] is None
    assert result["origin_reports"][0]["clean"] is (damage is None)
    origin_row = result["origin_reports"][0]
    if origin_row["clean"]:
        assert origin_row.get("checkpoint_sha256") == result["sha256"]


def mod_preparation(tmp_path, *, legacy=False):
    """新局实际产出，不伪造 loaded_save；保留来源与完整收尾字段。"""
    path, report_path = origin(tmp_path)
    report = json.loads(report_path.read_bytes())
    report.pop("loaded_save")
    report.update(
        session_requested=True,
        logs_isolated=True,
        checkpoint_ready=game_run.save_header(path),
        session={"automation_phase": "complete", "speed_ok": True},
        progress={"reached": True},
        source_reread={"verified": True},
    )
    report["checkpoint"]["header"] = game_run.save_header(path)
    if not legacy:
        report["kind"] = "mod_checkpoint_preparation"
    game_run.write_json(report_path, report)
    return path, report_path


@pytest.mark.parametrize("legacy", [False, True])
def test_Mod新局检查点可供安全重载但不追认行为报告(tmp_path, legacy):
    from pdx import m3a_screen

    path, report_path = mod_preparation(tmp_path, legacy=legacy)
    original = path.read_bytes(), report_path.read_bytes()
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["instrument_suitable"] is True
    assert result["formal_pair_suitable"] is False
    assert result["opportunity_count"] is None
    assert result["origin_reports"][0]["kind"] == "mod_checkpoint_preparation"
    for purpose in ("safety", "instrument"):
        assert checkpoint_catalog.preflight(result, purpose=purpose, months=1)["allowed"]
    for purpose in ("M3-A", "M3-B", "M4"):
        assert not checkpoint_catalog.preflight(result, purpose=purpose, months=24)["allowed"]
    facts = m3a_screen.load_report(report_path)
    assert not facts.clean
    assert "loaded_save.sha256_missing" in facts.gate_reasons
    assert (path.read_bytes(), report_path.read_bytes()) == original


@pytest.mark.parametrize(
    "damage",
    [
        "source",
        "deployed",
        "logs",
        "missing_log_hash",
        "missing_cleanup",
        "failed_cleanup",
        "failure",
        "error",
        "mount",
        "missing_finding",
        "header",
        "version",
        "output",
        "checkpoint_name",
        "checkpoint_ready",
        "session",
        "progress",
        "session_requested",
        "logs_isolated",
        "missing_checkpoint",
        "loaded_save",
        "experiment",
    ],
)
def test_Mod检查点来源缺证或损坏仍拒绝且保留原件(tmp_path, damage):
    path, report_path = mod_preparation(tmp_path)
    report = json.loads(report_path.read_bytes())
    if damage == "source":
        (report_path.parent / "sources/probe/observer.txt").write_bytes(b"changed\n")
    elif damage == "deployed":
        report["deployed_hashes"]["probe"]["observer.txt"] = "b" * 64
    elif damage == "logs":
        (report_path.parent / "logs/error.log").write_bytes(b"changed\n")
    elif damage == "missing_log_hash":
        report.pop("log_hashes")
    elif damage == "missing_cleanup":
        report.pop("cleanup_errors")
    elif damage == "failed_cleanup":
        report["cleanup_errors"] = ["restore failed"]
    elif damage == "failure":
        report["failure"] = "failed run"
    elif damage == "error":
        report["log_findings"]["errors"]["Script system error!"] = 1
    elif damage == "mount":
        report["mount_allowlist"].append("undeclared")
    elif damage == "missing_finding":
        report["log_findings"].pop("mod_errors")
    elif damage == "header":
        report["checkpoint"]["header"]["observer"] = "no"
    elif damage == "version":
        report["game_version"]["caligula_branch"] = "release/1.15"
    elif damage == "output":
        path.write_bytes(path.read_bytes() + b"changed")
    elif damage == "checkpoint_name":
        report["checkpoint"]["hashes"] = {"../autosave.v3": game_run.file_sha(path)}
    elif damage == "checkpoint_ready":
        report["checkpoint_ready"]["game_date"] = "1840.1.1"
    elif damage == "session":
        report["session"]["automation_phase"] = "failed"
    elif damage == "progress":
        report["progress"]["reached"] = False
    elif damage in {"session_requested", "logs_isolated"}:
        report.pop(damage)
    elif damage == "missing_checkpoint":
        report.pop("checkpoint")
    elif damage == "loaded_save":
        report["loaded_save"] = {"sha256": "a" * 64}
    elif damage == "experiment":
        report["experiment"] = {"purpose": "M3-A"}
    game_run.write_json(report_path, report)
    original = path.read_bytes(), report_path.read_bytes()
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["instrument_suitable"] is False
    assert result["state"] == "rejected"
    assert (path.read_bytes(), report_path.read_bytes()) == original


def test_Mod检查点不接受正式资格晋升(tmp_path, monkeypatch):
    from pdx import experiment_evidence

    path, _ = mod_preparation(tmp_path)
    monkeypatch.setattr(
        experiment_evidence, "validate", lambda *_a, **_k: {"allowed": True, "reasons": []}
    )
    result = checkpoint_catalog.inspect(
        path,
        expected_version="1.14.5",
        qualification_report=tmp_path / "qualification.json",
        purpose="M3-A",
    )
    assert result["instrument_suitable"] is True
    assert result["formal_pair_suitable"] is False
    assert "origin.diagnostic_only" in result["reasons"]


def test_噪声准备只占三次单臂预算():
    checkpoint = {"instrument_suitable": True, "state": "instrument-suitable"}
    result = checkpoint_catalog.preflight(checkpoint, purpose="M4-noise", months=1, used_arms=2)
    assert result["allowed"]
    assert result["remaining_arms"] == 1
    result = checkpoint_catalog.preflight(checkpoint, purpose="M4-noise", months=1, used_arms=3)
    assert not result["allowed"]
    assert result["remaining_arms"] == 0


@pytest.mark.parametrize("months", [6, 23, 121])
def test_正式性能入口保留长期窗口(months):
    checkpoint = {"instrument_suitable": True, "formal_pair_suitable": True, "formal_purpose": "M4"}
    result = checkpoint_catalog.preflight(checkpoint, purpose="M4", months=months)
    assert "budget.m4_window" in result["reasons"]
