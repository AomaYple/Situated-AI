"""实机资源事务与失败判据的无游戏测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pdx import game_run

pytestmark = pytest.mark.unit


@pytest.fixture
def deployment(tmp_path):
    user = tmp_path / "user"
    user.mkdir()
    content = user / "content_load.json"
    content.write_bytes(b'{"disabledDLC": ["dlc"]}\r\n')
    return game_run.Deployment(user, tmp_path / "evidence")


def test_已有目录和配置逐字节恢复(deployment, tmp_path):
    original = deployment.content.read_bytes()
    dest = deployment.userdir / "mod" / "probe"
    dest.mkdir(parents=True)
    (dest / "owned.txt").write_bytes(b"original\r\n")
    source = tmp_path / "source"
    source.mkdir()
    (source / "probe.txt").write_text("hello\n", encoding="utf-8")
    deployment.deploy({"probe": source})
    assert (dest / "probe.txt").read_bytes() == b"\xef\xbb\xbfhello\n"
    assert deployment.restore() == []
    assert deployment.content.read_bytes() == original
    assert (dest / "owned.txt").read_bytes() == b"original\r\n"
    assert not (dest / "probe.txt").exists()
    assert deployment.restore() == []


def test_部署中途异常仍可恢复原目录(deployment, tmp_path, monkeypatch):
    dest = deployment.userdir / "mod" / "probe"
    dest.mkdir(parents=True)
    (dest / "old").write_bytes(b"old")

    def fail(_source, target):
        target.mkdir()
        (target / "partial").write_bytes(b"partial")
        raise OSError("deploy failed")

    monkeypatch.setattr(game_run, "deploy_tree", fail)
    with pytest.raises(OSError, match="deploy failed"):
        deployment.deploy({"probe": tmp_path})
    assert deployment.restore() == []
    assert (dest / "old").read_bytes() == b"old"
    assert not (dest / "partial").exists()


def test_缺失配置恢复为缺失(deployment, tmp_path):
    deployment.content.unlink()
    source = tmp_path / "source"
    source.mkdir()
    deployment.deploy({"probe": source})
    assert deployment.content.exists()
    assert deployment.restore() == []
    assert not deployment.content.exists()


@pytest.mark.parametrize("name", ["..", ".", "", "../outside", "a/b"])
def test_部署拒绝越界目录名(deployment, tmp_path, name):
    with pytest.raises(ValueError, match="目录名"):
        deployment.deploy({name: tmp_path})
    assert deployment.restore() == []


def test_恢复失败保留可重试副本(deployment, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "probe.txt").write_bytes(b"probe")
    dest = deployment.userdir / "mod" / "probe"
    dest.mkdir(parents=True)
    (dest / "old").write_bytes(b"old")
    deployment.deploy({"probe": source})
    saved = deployment.claims[0][1]
    with monkeypatch.context() as patch:
        patch.setattr(
            game_run.shutil, "rmtree", lambda _p: (_ for _ in ()).throw(OSError("locked"))
        )
        assert deployment.restore()
        assert saved.is_dir()
        assert deployment.claims
    assert deployment.restore() == []
    assert (dest / "old").is_file()


def test_共享锁拒绝第二个实验(tmp_path):
    with (
        game_run.RunLock(tmp_path / "run.lock"),
        pytest.raises(RuntimeError, match="另一个实机实验"),
        game_run.RunLock(tmp_path / "run.lock"),
    ):
        pytest.fail("应被拒绝")
    with game_run.RunLock(tmp_path / "run.lock"):
        pass


def test_相对等待从当前日期计量(monkeypatch):
    ticks = iter(["1900.1.1", "1900.1.1", "1900.2.5"])
    monkeypatch.setattr(game_run.ga, "tick_mark", lambda: SimpleNamespace(tick=next(ticks)))
    monkeypatch.setattr(game_run.time, "sleep", lambda _seconds: None)
    result = game_run.wait_progress(1)
    assert result["start"] == "1900.1.1"
    assert result["end"] == "1900.2.5"
    assert result["reached"]


@pytest.mark.parametrize("tick", ["", "1899.12.1", "1900.1.1"])
def test_无tick倒退超时明确失败(monkeypatch, tick):
    values = iter(["1900.1.1", tick])
    clock = iter([0, 2])
    monkeypatch.setattr(game_run.ga, "tick_mark", lambda: SimpleNamespace(tick=next(values)))
    monkeypatch.setattr(game_run.time, "monotonic", lambda: next(clock))
    with pytest.raises((RuntimeError, TimeoutError)):
        game_run.wait_progress(1, timeout=1)


@pytest.mark.parametrize("months", [float("nan"), float("inf"), 0, -1])
def test_无效等待时长拒绝执行(months):
    with pytest.raises(ValueError):
        game_run.wait_progress(months)


def test_挂载要求完整路径且错误只来自错误日志(tmp_path):
    destination = Path("C:/mods/probe")
    (tmp_path / "debug.log").write_text(
        "Mounted Data: C:\\mods\\probe\nUnknown effect example\n", encoding="utf-8"
    )
    (tmp_path / "error.log").write_text("Unknown effect bad\n", encoding="utf-8")
    findings = game_run.log_findings(tmp_path, [destination])
    assert findings["errors"]["Unknown effect"] == 1
    assert findings["missing_mounts"] == []
    assert game_run.log_findings(tmp_path, [Path("C:/other/probe")])["missing_mounts"]


def test_未列举的本模组错误也不能漏过门禁(tmp_path):
    (tmp_path / "error.log").write_text(
        "Invalid custom invocation sitai_market_rule\nVariable 'sitai_fiscal_risk' is used but is never set.\n"
        "Script system error!\nError: root trigger [ Scoped object of type 'country' is not valid ]\nAssertion failed: unexpected engine state\n",
        encoding="utf-8",
    )
    findings = game_run.log_findings(tmp_path, [])
    assert findings["mod_errors"] == ["Invalid custom invocation sitai_market_rule"]
    assert len(findings["observer_warnings"]) == 1
    assert findings["errors"]["Script system error!"] == 1
    assert findings["errors"]["Assertion failed"] == 1


def test_证据分块哈希和原子json(tmp_path):
    raw = b"x" * 1024
    (tmp_path / "sample").write_bytes(raw)
    assert game_run.hashes(tmp_path)["sample"] == hashlib.sha256(raw).hexdigest()
    game_run.write_json(tmp_path / "report.json", {"name": "中文"})
    assert json.loads((tmp_path / "report.json").read_bytes()) == {"name": "中文"}
    assert b"\r" not in (tmp_path / "report.json").read_bytes()


def test_游戏改写的用户状态和自动存档可恢复(deployment):
    settings = deployment.userdir / "pdx_settings.json"
    settings.write_bytes(b'{"original":true}\r\n')
    saves = deployment.userdir / "save games"
    saves.mkdir()
    original = saves / "autosave.v3"
    original.write_bytes(b"original binary\0")
    deployment.snapshot_state()
    settings.write_bytes(b"changed")
    original.write_bytes(b"new simulation")
    generated = saves / "autosave_1.v3"
    generated.write_bytes(b"new")
    assert deployment.restore() == []
    assert settings.read_bytes() == b'{"original":true}\r\n'
    assert original.read_bytes() == b"original binary\0"
    assert not generated.exists()


def test_内容相同的状态备份复用(deployment):
    settings = deployment.userdir / "pdx_settings.json"
    settings.write_bytes(b"same")
    deployment.snapshot_state()
    saved = deployment.state_files[settings]
    assert deployment.restore() == []
    deployment.snapshot_state()
    assert deployment.state_files[settings] == saved


@pytest.mark.parametrize(
    "phase", ["startup", "wait", "analyze", "archive", "capture", "process", "summary"]
)
def test_整体会话失败不吞错误且恢复用户资源(tmp_path, monkeypatch, phase):
    user = tmp_path / "user"
    user.mkdir()
    original = b'{"disabledDLC": []}\r\n'
    (user / "content_load.json").write_bytes(original)
    source = tmp_path / "source"
    source.mkdir()
    (source / "test.txt").write_bytes(b"test\n")
    monkeypatch.setattr(game_run.config, "USERDIR", user)
    monkeypatch.setattr(game_run.config, "game_version", lambda: {"version": "test"})
    monkeypatch.setattr(game_run.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(game_run.ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(game_run.ga, "_process_pids", list)
    monkeypatch.setattr(game_run.ga, "kill_owned_game", lambda: None)
    monkeypatch.setattr(game_run.ga, "LAST_QUARANTINE_ERRORS", [])
    monkeypatch.setattr(game_run, "graceful_stop", lambda *_a, **_k: {"exited": True})

    def fail(*_a, **_k):
        raise RuntimeError("controlled failure")

    if phase == "process":
        monkeypatch.setattr(game_run.ga, "_process_pids", fail)
    if phase == "capture":
        monkeypatch.setattr(game_run.LogCapture, "poll", fail)
    if phase == "summary":
        original_hashes = game_run.hashes

        def failing_hashes(path):
            if path.name == "logs-raw":
                fail()
            return original_hashes(path)

        monkeypatch.setattr(game_run, "hashes", failing_hashes)

    def quarantine(destination):
        if phase == "archive" and destination.name == "logs-raw":
            fail()
        destination.mkdir(parents=True)
        (destination / "debug.log").write_text(
            f"Mounted Data: {user / 'mod/probe'}\n", encoding="utf-8"
        )
        return []

    monkeypatch.setattr(game_run.ga, "quarantine_logs", quarantine)
    session = SimpleNamespace(hwnd=123, rate_ok=True, as_dict=lambda: {"test": True})
    monkeypatch.setattr(
        game_run.ga, "run_session", fail if phase == "startup" else lambda **_k: session
    )
    monkeypatch.setattr(
        game_run, "wait_progress", fail if phase == "wait" else lambda *_a, **_k: {"reached": True}
    )
    report = game_run.run(
        {"probe": source},
        months=1,
        output=tmp_path / "output",
        analyze=fail if phase == "analyze" else None,
    )
    assert not report["ok"]
    assert report["failure"]
    assert isinstance(report["cleanup_errors"], list)
    if phase == "process":
        # 未确认进程退出时保留挂载与恢复副本，避免移动运行中的文件。
        assert (user / "mod/probe").exists()
        assert any("进程" in error for error in report["cleanup_errors"])
    else:
        assert (user / "content_load.json").read_bytes() == original
        assert not (user / "mod/probe").exists()
    if phase in {"capture", "archive", "process", "summary"}:
        assert any("controlled failure" in error for error in report["cleanup_errors"])
    assert (Path(str(report["evidence"])) / "report.json").is_file()


def test_游戏未退出时保留配置和存档备份不覆盖运行状态(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    (user / "content_load.json").write_bytes(b'{"original":true}')
    source = tmp_path / "source"
    source.mkdir()
    (source / "test.txt").write_bytes(b"test\n")
    monkeypatch.setattr(game_run.config, "USERDIR", user)
    monkeypatch.setattr(game_run.config, "game_version", dict)
    monkeypatch.setattr(game_run.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(game_run.ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(game_run.ga, "_process_pids", lambda: [123])
    monkeypatch.setattr(game_run.ga, "kill_owned_game", lambda: None)
    monkeypatch.setattr(game_run.ga, "quarantine_logs", lambda _p: [])
    monkeypatch.setattr(game_run.ga, "LAST_QUARANTINE_ERRORS", [])
    monkeypatch.setattr(
        game_run.ga, "run_session", lambda **_k: (_ for _ in ()).throw(RuntimeError("startup"))
    )
    report = game_run.run({"probe": source}, months=1, output=tmp_path / "output")
    assert report["cleanup_errors"]
    assert (user / "mod/probe").exists()
    assert json.loads((user / "content_load.json").read_bytes())["enabledMods"]
    assert (
        Path(str(report["evidence"])) / "content_load.original.backup"
    ).read_bytes() == b'{"original":true}'


def test_固定检查点读取有限头且部署后可清理(deployment, tmp_path):
    source = tmp_path / "checkpoint.v3"
    raw = (
        b'SAV0100\nmeta_data={ version="1.14.5" game_date=1836.4.1 player=NONE }\n'
        + b"\x00\xff" * 100000
    )
    source.write_bytes(raw)
    assert game_run.save_header(source) == {
        "version": "1.14.5",
        "game_date": "1836.4.1",
        "player": "NONE",
    }
    name = deployment.stage_save(source)
    staged = deployment.userdir / "save games" / name
    assert staged.read_bytes() == raw
    assert deployment.restore() == []
    assert not staged.exists()
    assert source.read_bytes() == raw


def test_存档命名冲突不覆盖用户内容(deployment, tmp_path):
    source = tmp_path / "checkpoint.v3"
    source.write_bytes(b"checkpoint")
    name = deployment.stage_save(source)
    target = deployment.userdir / "save games" / name
    assert deployment.restore() == []
    target.write_bytes(b"other")
    with pytest.raises(ValueError, match="冲突"):
        deployment.stage_save(source)
    assert target.read_bytes() == b"other"


@pytest.mark.parametrize("raw", [b"PKZIP", b'SAV0100 version="1.14.5"'])
def test_未知或不完整的存档头拒绝猜测(tmp_path, raw):
    path = tmp_path / "unknown.v3"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        game_run.save_header(path)


def test_存档空规则和非观察者状态可在启动前发现(tmp_path):
    path = tmp_path / "save.v3"
    path.write_bytes(
        b'SAV0100\nversion="1.14.5" game_date=1836.4.1 settings={ "" }\nplayer_manager={database={1={country=42}}}'
    )
    header = game_run.save_header(path)
    assert header["observer"] == "no"
    assert header["invalid_rules"]


def test_自动存档等待稳定且排除本局之前的副本(tmp_path, monkeypatch):
    path = tmp_path / "save.v3"
    path.write_bytes(b'SAV0100\nversion="1.14.5" game_date=1836.4.1\nplayer_manager={database={}}')
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(game_run.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        game_run.time, "sleep", lambda value: setattr(clock, "now", clock.now + value)
    )
    monkeypatch.setattr(game_run.ga, "tick_mark", lambda: SimpleNamespace(tick="1836.4.15"))
    earliest = game_run.ga.tick_day("1836.3.1")
    assert earliest is not None
    assert game_run.wait_save_ready(path, earliest=earliest, timeout=6)["game_date"] == "1836.4.1"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(TimeoutError):
        game_run.wait_save_ready(path, earliest=earliest, original_sha256=digest, timeout=6)


def test_检查点不能接受结束日期超过31天的未来存档(tmp_path, monkeypatch):
    path = tmp_path / "save.v3"
    path.write_bytes(b'SAV0100\nversion="1.14.5" game_date=1900.2.11\nplayer_manager={database={}}')
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(game_run.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        game_run.time, "sleep", lambda value: setattr(clock, "now", clock.now + value)
    )
    monkeypatch.setattr(game_run.ga, "tick_mark", lambda: SimpleNamespace(tick="1900.3.1"))
    end = game_run.ga.tick_day("1900.1.10")
    assert end is not None
    with pytest.raises(TimeoutError):
        game_run.wait_save_ready(path, earliest=end, timeout=6)


def test_正常退出先核实所有权再请求关闭并等待退出(monkeypatch):
    events = []
    monkeypatch.setattr(game_run.ga, "_live_window", lambda hwnd: hwnd)
    monkeypatch.setattr(game_run.ga, "ensure_foreground", lambda *_a, **_k: events.append("front"))
    monkeypatch.setattr(game_run.ga, "press_chord", lambda *_a, **_k: events.append("close"))
    monkeypatch.setattr(game_run.ga, "_process_pids", list)
    monkeypatch.setattr(game_run.ga, "_window_pid", lambda _: 123)
    monkeypatch.setattr(game_run.ga, "_OWNED_GAME_PIDS", {123})
    monkeypatch.setattr(game_run.ga, "_OWNED_GAME_META", {123: object()})
    monkeypatch.setattr(game_run.ga, "_owned_identity_matches", lambda *_: True)
    monkeypatch.setattr(game_run.psutil, "Process", lambda _: object())
    result = game_run.graceful_stop(123, timeout=1)
    assert result["exited"]
    assert events == ["front", "close"]


def test_退出请求未生效必须超时而不假报日志已完整(monkeypatch):
    monkeypatch.setattr(game_run.ga, "_live_window", lambda hwnd: hwnd)
    monkeypatch.setattr(game_run.ga, "ensure_foreground", lambda *_a, **_k: None)
    monkeypatch.setattr(game_run.ga, "press_chord", lambda *_a, **_k: None)
    monkeypatch.setattr(game_run.ga, "_process_pids", lambda: [123])
    monkeypatch.setattr(game_run.ga, "_window_pid", lambda _: 123)
    monkeypatch.setattr(game_run.ga, "_OWNED_GAME_PIDS", {123})
    monkeypatch.setattr(game_run.ga, "_OWNED_GAME_META", {123: object()})
    monkeypatch.setattr(game_run.ga, "_owned_identity_matches", lambda *_: True)
    monkeypatch.setattr(game_run.psutil, "Process", lambda _: object())
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(game_run.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        game_run.time, "sleep", lambda value: setattr(clock, "now", clock.now + value)
    )
    with pytest.raises(TimeoutError):
        game_run.graceful_stop(123, timeout=1)


def test_持续日志跨轮转无重复且不改原日志(tmp_path):
    source, target = tmp_path / "live", tmp_path / "captured"
    source.mkdir()
    log = source / "debug.log"
    log.write_bytes(b"start\n")
    capture = game_run.LogCapture(source, target)
    capture.poll()
    with log.open("ab") as stream:
        stream.write(b"middle\n")
    log.rename(source / "debug.1.log")
    log.write_bytes(b"end\n")
    capture.poll()
    capture.poll()
    assert (target / "debug.log").read_bytes() == b"start\nmiddle\nend\n"
    assert (source / "debug.1.log").read_bytes() == b"start\nmiddle\n"
    assert log.read_bytes() == b"end\n"
    assert capture.errors == []


def test_持续日志原地截断不能悄悄当完整(tmp_path):
    source = tmp_path / "live"
    source.mkdir()
    log = source / "error.log"
    log.write_bytes(b"original error\n")
    capture = game_run.LogCapture(source, tmp_path / "capture")
    capture.poll()
    log.write_bytes(b"short")
    capture.poll()
    assert any("截断" in e for e in capture.errors)


@pytest.mark.parametrize("argument", ["timeout", "poll"])
def test_轮询和超时也拒绝非有限参数(argument):
    with pytest.raises(ValueError):
        game_run.wait_progress(
            1,
            timeout=float("nan") if argument == "timeout" else 1,
            poll=float("nan") if argument == "poll" else 1,
        )


def test_隔离旧存档菜单并在实验结束完整归还(deployment):
    saves = deployment.userdir / "save games"
    saves.mkdir()
    old = saves / "user-legacy.v3"
    old.write_bytes(b"unaltered user save")
    deployment.evidence.mkdir()
    deployment.isolate_saves()
    assert not old.exists()
    (saves / "experiment.v3").write_bytes(b"new")
    assert deployment.restore() == []
    assert old.read_bytes() == b"unaltered user save"
    assert not (saves / "experiment.v3").exists()
    assert not (deployment.evidence / "original-save-directory").exists()


def test_原有引擎计时文件逐字节恢复(deployment):
    csv = deployment.userdir / "ticktask_timings.csv"
    original = b"\xef\xbb\xbfprevious\r\n"
    csv.write_bytes(original)
    deployment.snapshot_state()
    csv.write_bytes(b"experiment\n")
    assert deployment.restore() == []
    assert csv.read_bytes() == original


def test_载入用户原存档目录内文件可在隔离后精确定位(deployment):
    save = deployment.userdir / "save games/nested/user.v3"
    save.parent.mkdir(parents=True)
    raw = (
        b'SAV0100\nmeta_data={ version="1.14.5" game_date=1836.4.1 }\nplayer_manager={database={}}'
    )
    save.write_bytes(raw)
    deployment.evidence.mkdir()
    deployment.isolate_saves()
    relocated = deployment.source_after_isolation(save)
    assert not save.exists()
    assert game_run.save_header(relocated)["observer"] == "yes"
    staged = deployment.stage_save(save)
    assert (deployment.userdir / "save games" / staged).read_bytes() == raw
    assert deployment.restore() == []
    assert save.read_bytes() == raw
    assert not (deployment.userdir / "save games" / staged).exists()


@pytest.fixture
def ticktask_capture(tmp_path, monkeypatch):
    path = tmp_path / "user.csv"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    monkeypatch.setattr(game_run.gametimer, "ticktask_default_path", lambda: path)
    events = []
    monkeypatch.setattr(game_run.time, "sleep", lambda *_: None)
    monkeypatch.setattr(game_run.ga, "_live_window", lambda hwnd: hwnd)
    monkeypatch.setattr(game_run.ga, "ensure_foreground", lambda *_a, **_k: events.append("front"))
    monkeypatch.setattr(game_run.ga, "press_key", lambda *_a, **_k: events.append("key"))
    monkeypatch.setattr(game_run.ga, "click_client", lambda *_a, **_k: events.append("focus"))
    monkeypatch.setattr(game_run.ga, "tick_mark", lambda: SimpleNamespace(tick="1836.6.1"))

    def background(*_):
        events.append("background")
        return SimpleNamespace(restored=True, minimized=True)

    monkeypatch.setattr(game_run.ga, "switch_to_background", background)
    monkeypatch.setattr(
        game_run.ga, "wait_until_running", lambda *_a, **_k: events.append("verified-running")
    )
    session = SimpleNamespace(hwnd=1, previous=2, speed_xy=(3, 4))
    return game_run.TickTaskCapture(evidence), session, events


def test_清零控制台后立即还后台再核实推进(ticktask_capture, monkeypatch):
    capture, session, events = ticktask_capture
    capture.path.write_bytes(b"previous")
    monkeypatch.setattr(game_run.ga, "submit_console_command", lambda *_a, **_k: True)
    capture.start(session)
    assert not capture.path.exists()
    assert events == ["front", "key", "focus", "key", "background", "verified-running"]
    assert capture.background["minimized"]


def test_键盘速度会在控制台清零后重新夺回游戏焦点(ticktask_capture, monkeypatch):
    capture, _session, events = ticktask_capture
    session = SimpleNamespace(hwnd=1, previous=2, speed_xy=None, speed_key="5")
    monkeypatch.setattr(game_run.ga, "submit_console_command", lambda *_a, **_k: True)
    capture.start(session)
    assert events == ["front", "key", "key", "key", "background", "verified-running"]


def test_清零失败也归还窗口且不开始计时(ticktask_capture, monkeypatch):
    capture, session, events = ticktask_capture
    monkeypatch.setattr(game_run.ga, "submit_console_command", lambda *_a, **_k: False)
    with pytest.raises(RuntimeError, match="清零"):
        capture.start(session)
    assert events[-1] == "background"
    assert "verified-running" not in events


@pytest.mark.parametrize("bad", [False, True])
def test_导出必须是新生成且可完整解析的文件(ticktask_capture, monkeypatch, bad):
    capture, session, events = ticktask_capture
    capture.path.write_bytes(b"old-valid-file")
    raw = (
        b"frame,task,milliseconds,calls,longest_lock\n100,UpdateAI,2,1,0\n"
        if not bad
        else b"not a ticktask file\n"
    )

    def submit(*_a, **_k):
        assert not capture.path.exists()
        capture.path.write_bytes(raw)
        return True

    monkeypatch.setattr(game_run.ga, "submit_console_command", submit)
    if bad:
        with pytest.raises(ValueError, match="CSV"):
            capture.finish(session)
    else:
        result = capture.finish(session)
        assert result["summary"]["frames"] == 1
        assert result["sha256"] == hashlib.sha256(raw).hexdigest()
        assert result["tasks"]["UpdateAI"]["mean_ms"] == 2
    assert events[-1] == "background"


def test_复核旧成功报告发现漏判但不改原件(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "error.log").write_bytes(b"Script system error!\n")
    path = tmp_path / "report.json"
    original = {
        "ok": True,
        "log_hashes": game_run.hashes(logs),
        "log_findings": {"missing_mounts": []},
    }
    game_run.write_json(path, original)
    raw = path.read_bytes()
    result = game_run.read_reviewed_report(path)
    assert not result["ok"]
    assert result["review"]["original_ok"]
    assert result["log_findings"]["errors"]["Script system error!"] == 1
    assert path.read_bytes() == raw
    (logs / "error.log").write_bytes(b"modified\n")
    with pytest.raises(ValueError, match="指纹"):
        game_run.read_reviewed_report(path)


def test_干净归档复核保留成功且缺指纹不能默认通过(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "error.log").write_bytes(b"")
    path = tmp_path / "report.json"
    game_run.write_json(path, {"ok": True, "log_hashes": game_run.hashes(logs)})
    result = game_run.read_reviewed_report(path)
    game_run.require_clean_report(result)
    game_run.write_json(path, {"ok": True})
    with pytest.raises(ValueError, match="指纹"):
        game_run.read_reviewed_report(path)


def test_后期检查点不能接受早期但已写完的自动存档(tmp_path, monkeypatch):
    path = tmp_path / "autosave.v3"
    path.write_bytes(
        b'SAV0100\nmeta_data={version="1.14.5" game_date=1840.7.1}\nplayer_manager={database={}}'
    )
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(game_run.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        game_run.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds)
    )
    monkeypatch.setattr(game_run.ga, "tick_mark", lambda: SimpleNamespace(tick="1900.2.1"))
    end = game_run.ga.tick_day("1900.1.10")
    assert end is not None
    with pytest.raises(TimeoutError, match="自动存档"):
        game_run.wait_save_ready(path, earliest=end, timeout=5)


@pytest.mark.parametrize("ready", [True, False])
def test_完整运行按结束日期归档检查点且失败也恢复用户状态(tmp_path, monkeypatch, ready):
    import shutil

    user = tmp_path / "user"
    user.mkdir()
    content = user / "content_load.json"
    original = b'{"disabledDLC":[]}\r\n'
    content.write_bytes(original)
    settings = user / "pdx_settings.json"
    settings.write_bytes(b"original settings\r\n")
    source = tmp_path / "source"
    source.mkdir()
    (source / ".metadata").mkdir()
    (source / ".metadata/metadata.json").write_bytes(b"{}\n")
    monkeypatch.setattr(game_run.config, "USERDIR", user)
    monkeypatch.setattr(game_run.ga, "_OWNED_GAME_PIDS", set())
    monkeypatch.setattr(game_run.ga, "_OWNED_GAME_META", {})
    monkeypatch.setattr(game_run.ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(game_run.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(game_run.ga, "kill_owned_game", lambda: None)
    monkeypatch.setattr(game_run.ga, "_process_pids", list)
    monkeypatch.setattr(game_run.ga, "LAST_QUARANTINE_ERRORS", [])
    monkeypatch.setattr(game_run.ga, "tick_mark", lambda: SimpleNamespace(tick="1900.2.1"))

    def quarantine(destination):
        destination.mkdir(parents=True, exist_ok=True)
        for path in (user / "logs").glob("*.log"):
            shutil.move(str(path), str(destination / path.name))
        return []

    monkeypatch.setattr(game_run.ga, "quarantine_logs", quarantine)

    def start(**_kwargs):
        logs = user / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "system.log").write_text(f"Mounted Data: {user / 'mod/test'}\n", encoding="utf-8")
        settings.write_bytes(b"changed by game")
        return SimpleNamespace(hwnd=123, rate_ok=True, as_dict=dict)

    monkeypatch.setattr(game_run.ga, "run_session", start)
    monkeypatch.setattr(game_run, "graceful_stop", lambda *_a, **_k: {"exited": True})
    monkeypatch.setattr(
        game_run,
        "wait_progress",
        lambda *_a, **_k: {"start": "1840.7.1", "end": "1900.1.10", "reached": True},
    )

    def checkpoint(path, *, earliest, original_sha256):
        assert earliest == game_run.ga.tick_day("1900.1.10")
        assert original_sha256 is None
        if not ready:
            raise TimeoutError("自动存档仍处于早期")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            b'SAV0100\nmeta_data={version="1.14.5" game_date=1900.1.10}\nplayer_manager={database={}}'
        )
        return game_run.save_header(path)

    monkeypatch.setattr(game_run, "wait_save_ready", checkpoint)
    report = game_run.run({"test": source}, months=714, output=tmp_path / "out", keep_save=True)
    assert report["ok"] is ready
    assert report["cleanup_errors"] == []
    assert content.read_bytes() == original
    assert settings.read_bytes() == b"original settings\r\n"
    assert not (user / "mod/test").exists()
    assert not (user / "save games/autosave.v3").exists()
    assert isinstance(report["evidence"], str)
    evidence = Path(report["evidence"])
    if ready:
        assert game_run.save_header(evidence / "saves/autosave.v3")["game_date"] == "1900.1.10"
    else:
        assert isinstance(report["failure"], str)
        assert "早期" in report["failure"]
        assert not (evidence / "saves/autosave.v3").exists()
