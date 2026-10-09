"""性能对照探针的恢复与进程所有权回归测试。

这些用例不启动 Victoria 3，只验证性能探针最容易污染用户环境的边界：
运行前已有同名 mod、配置写入中断、收尾步骤失败，以及 Ctrl+C/SIGTERM。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from pdx import config

pytestmark = pytest.mark.unit

_SCRIPT = config.REPO / "tools" / "probe" / "perf_compare.py"


@pytest.fixture(autouse=True)
def _isolate_probe_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 动态导入的探针每个用例都有独立目录，收尾测试不能覆盖真实实机证据。
    monkeypatch.setattr(config, "OUT", tmp_path / "probe-out")
    from pdx import game_auto

    monkeypatch.setattr(game_auto, "_process_pids", list)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("probe_perf_compare", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _state(
    module: Any, tmp_path: Path, killer: Callable[[], list[int]]
) -> tuple[Any, Any, Path, Path]:
    module.LOGS = tmp_path / "logs"
    module.LOGS.mkdir()
    module.OUT_DIR = tmp_path / "out"
    content = tmp_path / "content_load.json"
    content.write_bytes(b'{"enabledMods": []}\n')
    backup = module._make_backup(content)
    target = tmp_path / "mod" / "sitai_probe"
    target.mkdir(parents=True)
    (target / "original.txt").write_text("用户原有文件", encoding="utf-8", newline="\n")
    cleanup = module.PerfCleanup(
        content_path=content,
        backup_path=backup,
        generated_paths=(target,),
        killer=killer,
    )
    cleanup.claim_existing_paths()
    return module, cleanup, content, target


def test_清零后恢复运行先读tick而不是盲按空格(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        module.ga,
        "click_client",
        lambda hwnd, x, y, **_kwargs: calls.append(("click", hwnd, x, y)),
    )
    monkeypatch.setattr(module.ga, "speed_widget_xy", lambda _hwnd: (17, 19))
    monkeypatch.setattr(
        module.ga,
        "_step_unpause",
        lambda hwnd, **kwargs: (
            calls.append(("unpause", hwnd, kwargs)) or ("已确认运行", False, None)
        ),
    )

    assert module.resume_after_clear(7, speed_xy=(11, 13)) == "已确认运行"
    assert calls[0] == ("click", 7, 11, 13)
    assert calls[1][0] == "unpause"
    assert calls[1][2]["key_timeout"] == 30.0
    assert calls[1][2]["run_timeout"] == 30.0

    calls.clear()
    assert module.resume_after_clear(8, speed_xy=None) == "已确认运行"
    assert calls[0] == ("click", 8, 17, 19)
    assert calls[1][0] == "unpause"


def test_固定检查点只读复制并记录摘要(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    source = tmp_path / "source.v3"
    source.write_bytes(b"SAV\x00fixed-checkpoint")
    destination = tmp_path / "save games"
    monkeypatch.setattr(
        module,
        "save_header",
        lambda _path: {"version": "1.14.5", "game_date": "1838.1.1", "observer": "yes"},
    )
    monkeypatch.setattr(module.config, "game_version", lambda: {"caligula_branch": "1.14.5"})

    def no_validate(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(module, "validate_load_save_header", no_validate)

    name, evidence = module.stage_checkpoint(source, destination)

    assert name.startswith("sitai_checkpoint_")
    staged = destination / evidence["name"]
    assert staged.read_bytes() == source.read_bytes()
    assert evidence["sha256"]
    assert evidence["header"]["game_date"] == "1838.1.1"
    assert source.read_bytes() == b"SAV\x00fixed-checkpoint"


def test_固定检查点缺失时拒绝启动(tmp_path: Path) -> None:
    module = _load()
    with pytest.raises(FileNotFoundError, match="固定检查点不存在"):
        module.stage_checkpoint(tmp_path / "missing.v3", tmp_path / "save games")


def test_固定检查点在隔离存档目录前保留源字节(tmp_path: Path) -> None:
    module = _load()
    source = tmp_path / "save games" / "autosave.v3"
    source.parent.mkdir()
    source.write_bytes(b"SAV\x00user-checkpoint")

    copy, original = module.preserve_checkpoint_source(source)

    assert original == source.resolve()
    assert copy.read_bytes() == source.read_bytes()
    shutil.rmtree(copy.parent)
    assert source.read_bytes() == b"SAV\x00user-checkpoint"


def test_收尾恢复运行前同名目录和content_load且幂等(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "out")
    calls: list[str] = []

    def fake_killer() -> list[int]:
        calls.append("kill")
        return [123]

    _module, cleanup, content, target = _state(module, tmp_path, fake_killer)

    target.mkdir(parents=True)
    (target / "generated.txt").write_text("本次生成", encoding="utf-8", newline="\n")
    content.write_bytes(b'{"enabledMods": ["temporary"]}\n')

    assert cleanup.run(reason="test") == ()
    assert cleanup.run(reason="second-call") == ()
    assert calls == ["kill"]
    assert content.read_bytes() == b'{"enabledMods": []}\n'
    assert (target / "original.txt").read_text(encoding="utf-8") == "用户原有文件"
    assert not (target / "generated.txt").exists()
    report = json.loads((tmp_path / "out" / "cleanup.json").read_text(encoding="utf-8"))
    assert report["reason"] == "test"
    assert report["errors"] == []


def test_收尾恢复运行前存档目录而不保留实验存档(tmp_path: Path) -> None:
    module = _load()
    content = tmp_path / "content_load.json"
    content.write_bytes(b"{}\n")
    saves = tmp_path / "save games"
    saves.mkdir()
    (saves / "user.v3").write_bytes(b"user-save")
    cleanup = module.PerfCleanup(
        content_path=content,
        backup_path=module._make_backup(content),
        generated_paths=(saves,),
        killer=list,
    )
    cleanup.claim_existing_paths()
    saves.mkdir()
    (saves / "experiment.v3").write_bytes(b"experiment")

    assert cleanup.run(reason="save-isolation") == ()
    assert (saves / "user.v3").read_bytes() == b"user-save"
    assert not (saves / "experiment.v3").exists()


def test_收尾第二次重试不会删除第一次已经恢复的用户目录(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "out")
    content = tmp_path / "content_load.json"
    content.write_bytes(b"original-config")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "user.txt").write_bytes(b"first-user-data")
    (second / "user.txt").write_bytes(b"second-user-data")
    cleanup = module.PerfCleanup(
        content_path=content,
        backup_path=module._make_backup(content),
        generated_paths=(first, second),
        killer=list,
    )
    cleanup.claim_existing_paths()
    for path in (first, second):
        path.mkdir()
        (path / "generated.txt").write_bytes(b"generated")

    original_restore = cleanup._restore_path
    failed_once = False

    def fail_second_restore(backup: Path, path: Path) -> None:
        nonlocal failed_once
        if path == second and not failed_once:
            failed_once = True
            raise OSError("模拟暂时性占用")
        original_restore(backup, path)

    monkeypatch.setattr(cleanup, "_restore_path", fail_second_restore)

    first_errors = cleanup.run(reason="first-attempt")
    assert first_errors
    assert (first / "user.txt").read_bytes() == b"first-user-data"
    assert not (first / "generated.txt").exists()

    second_errors = cleanup.run(reason="retry")
    assert second_errors == ()
    assert (first / "user.txt").read_bytes() == b"first-user-data"
    assert (second / "user.txt").read_bytes() == b"second-user-data"
    assert not (first / "generated.txt").exists()
    assert not (second / "generated.txt").exists()


def test_收尾恢复规则预设时重建被游戏移除的父目录(tmp_path: Path) -> None:
    module = _load()
    content = tmp_path / "content_load.json"
    content.write_bytes(b"{}\n")
    presets = tmp_path / "player" / "game_rules" / "presets.txt"
    presets.parent.mkdir(parents=True)
    presets.write_bytes(b"user-rules")
    cleanup = module.PerfCleanup(
        content_path=content,
        backup_path=module._make_backup(content),
        generated_paths=(presets,),
        killer=list,
    )
    cleanup.claim_existing_paths()
    shutil.rmtree(presets.parent.parent)

    assert cleanup.run(reason="preset-isolation") == ()
    assert presets.read_bytes() == b"user-rules"


def test_终止游戏异常时不恢复或删除仍可能被使用的资源(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "out")

    def broken_killer() -> list[int]:
        raise RuntimeError("模拟进程权限错误")

    _module, cleanup, content, target = _state(module, tmp_path, broken_killer)
    target.mkdir(parents=True)
    (target / "generated.txt").write_text("本次生成", encoding="utf-8", newline="\n")
    content.write_bytes(b"temporary")

    errors = cleanup.run(reason="exception")
    assert any("终止本次游戏" in error for error in errors)
    assert content.read_bytes() == b"temporary"
    assert (cleanup.path_backups[target] / "original.txt").is_file()
    assert (target / "generated.txt").exists()
    assert cleanup.backup_path.exists()
    assert cleanup.cleaned is False


def test_游戏仍存活时保留实验资源和可恢复原件(tmp_path, monkeypatch):
    module = _load()
    _module, cleanup, content, target = _state(module, tmp_path, list)
    target.mkdir()
    (target / "generated.txt").write_bytes(b"experiment")
    content.write_bytes(b"running-state")
    monkeypatch.setattr(module.ga, "LAST_KILL_ALIVE", (123,))
    errors = cleanup.run(reason="kill-failed")
    assert errors
    assert content.read_bytes() == b"running-state"
    assert (target / "generated.txt").exists()
    assert cleanup.backup_path.exists()
    assert cleanup.path_backups[target].exists()
    assert not cleanup.cleaned


def test_独立检查发现残留进程时不能信任空的终止报告(tmp_path, monkeypatch):
    module = _load()
    _, cleanup, content, target = _state(module, tmp_path, list)
    target.mkdir()
    (target / "generated").write_bytes(b"running")
    content.write_bytes(b"running")
    monkeypatch.setattr(module.ga, "LAST_KILL_ALIVE", [])
    monkeypatch.setattr(module.ga, "_process_pids", lambda: [123])
    assert cleanup.run(reason="independent-check")
    assert content.read_bytes() == b"running"
    assert (cleanup.path_backups[target] / "original.txt").exists()
    assert (target / "generated").exists()


def test_认领中途失败绝不删除尚未备份的原件(tmp_path, monkeypatch):
    module = _load()
    content = tmp_path / "content_load.json"
    content.write_bytes(b"original")
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "user").write_bytes(b"first")
    (second / "user").write_bytes(b"second")
    cleanup = module.PerfCleanup(content, module._make_backup(content), (first, second), list)
    move = module.shutil.move

    def fail_second(source, dest):
        if Path(source) == second:
            raise OSError("backup failed")
        return move(source, dest)

    with monkeypatch.context() as patch:
        patch.setattr(module.shutil, "move", fail_second)
        with pytest.raises(OSError, match="backup failed"):
            cleanup.claim_existing_paths()
    assert cleanup.run(reason="partial-claim") == ()
    assert (first / "user").read_bytes() == b"first"
    assert (second / "user").read_bytes() == b"second"


def test_报告写入失败后仍能安全重试收尾(tmp_path, monkeypatch):
    module = _load()
    _, cleanup, content, target = _state(module, tmp_path, list)
    target.mkdir()
    original = cleanup._write_report

    def fail_report():
        cleanup.errors.append("report unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(cleanup, "_write_report", fail_report)
        assert cleanup.run(reason="first")
    assert not cleanup.backup_path.exists()
    assert cleanup.content_restored
    assert cleanup._write_report == original
    assert cleanup.run(reason="retry") == ()
    assert content.read_bytes() == b'{"enabledMods": []}\n'
    assert (target / "original.txt").exists()


def test_信号处理器先收尾再抛出对应退出异常(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "out")
    _module, cleanup, _content, _target = _state(module, tmp_path, list)
    registered: dict[int, Callable[[int, object], object]] = {}

    monkeypatch.setattr(module.signal, "getsignal", lambda _signum: signal.SIG_DFL)

    def fake_signal(signum: int, handler: Callable[[int, object], object]) -> object:
        registered[signum] = handler
        return signal.SIG_DFL

    monkeypatch.setattr(module.signal, "signal", fake_signal)
    restore = module._install_cleanup_handlers(cleanup)

    with pytest.raises(KeyboardInterrupt):
        registered[signal.SIGINT](signal.SIGINT, None)
    assert cleanup.cleaned

    with pytest.raises(SystemExit) as exc_info:
        registered[signal.SIGTERM](signal.SIGTERM, None)
    assert exc_info.value.code == 128 + signal.SIGTERM
    restore()


def test_清理期间再次收到信号不会中断恢复(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "out")
    _module, cleanup, content, target = _state(module, tmp_path, list)
    target.mkdir(parents=True)
    (target / "generated.txt").write_text("本次生成", encoding="utf-8", newline="\n")
    content.write_bytes(b"temporary")

    registered: dict[int, Callable[[int, object], object]] = {}
    monkeypatch.setattr(module.signal, "getsignal", lambda _signum: signal.SIG_DFL)

    def fake_signal(signum: int, handler: Callable[[int, object], object]) -> object:
        registered[signum] = handler
        return signal.SIG_DFL

    monkeypatch.setattr(module.signal, "signal", fake_signal)
    restore = module._install_cleanup_handlers(cleanup)

    def killer_with_nested_signal() -> list[int]:
        registered[signal.SIGTERM](signal.SIGTERM, None)
        return []

    cleanup.killer = killer_with_nested_signal
    with pytest.raises(KeyboardInterrupt):
        registered[signal.SIGINT](signal.SIGINT, None)

    assert cleanup.cleaned
    assert not cleanup.running
    assert cleanup.deferred_signals == ["SIGTERM"]
    assert content.read_bytes() == b'{"enabledMods": []}\n'
    assert (target / "original.txt").is_file()
    assert not (target / "generated.txt").exists()
    assert not cleanup.backup_path.exists()
    restore()


def test_窗口日期判据比较日历日期并保留原始tick() -> None:
    module = _load()
    same = [
        {"label": "vanilla", "index": 1, "advanced": {"from": "1836.1.1", "to": "1837.1.1"}},
        {"label": "ours", "index": 1, "advanced": {"from": "1836.1.1.12", "to": "1837.1.1.6"}},
    ]
    verdict = module.window_control_verdict(same)
    assert verdict.ok
    assert verdict.pairs == 1
    assert verdict.comparisons[0]["comparable"] is True
    assert verdict.comparisons[0]["from"]["ours"] == "1836.1.1.12"
    assert verdict.comparisons[0]["calendar_from"]["ours"] == "1836.1.1"

    mismatch = [
        *same[:1],
        {"label": "ours", "index": 1, "advanced": {"from": "1836.1.2", "to": "1837.1.1"}},
    ]
    failed = module.window_control_verdict(mismatch)
    assert not failed.ok
    assert failed.pairs == 1
    assert "窗口不同" in failed.problems[0]

    missing = [
        same[0],
        {"label": "ours", "index": 1, "advanced": {"from": "<读不到>", "to": "1837.1.1"}},
    ]
    missing_verdict = module.window_control_verdict(missing)
    assert not missing_verdict.ok
    assert "ours.from" in missing_verdict.problems[0]


def test_固定检查点窗口按日历月初平移并拒绝无效日期() -> None:
    module = _load()
    assert module._shift_to_month_start("1836.2.1", 4) == "1836.6.1"
    assert module._shift_to_month_start("1836.6.1", 36) == "1839.6.1"
    assert module._calendar_date("1836.6.1.12") == "1836.6.1"
    assert module._calendar_date("1836.13.1") is None
    assert module._calendar_key("1839.10.1") > module._calendar_key("1839.6.1")
    with pytest.raises(ValueError, match="无效游戏日期"):
        module._shift_to_month_start("1836.invalid.1", 4)


def test_固定窗口轮询不会每次都采集资源或扫描错误日志(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    clock = [0.0]
    ticks = [0]
    samples: list[dict[str, object]] = []
    scans = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    def tick_mark() -> Any:
        ticks[0] += 1
        date = "1836.1.1" if ticks[0] < 52 else "1836.1.2"
        return SimpleNamespace(tick=date)

    monkeypatch.setattr(module.ga, "tick_mark", tick_mark)
    monkeypatch.setattr(module.ga, "_live_window", lambda _hwnd: True)

    def scan() -> Any:
        scans[0] += 1
        return SimpleNamespace(readable=True, errors=(), files=(), unreadable=(), benign=())

    monkeypatch.setattr(module, "scan_game_errors", scan)
    monkeypatch.setattr(
        module,
        "_resource_sample",
        lambda started: {"seconds": round(clock[0] - started, 2)},
    )

    result = module._wait_months(
        1,
        1.0,
        timeout=20.0,
        samples=samples,
        started=0.0,
        end_date="1836.1.2",
    )

    assert result["to"] == "1836.1.2"
    assert len(samples) <= 3  # 初始、每5秒、窗口结束；不是每次0.1秒轮询
    assert scans[0] <= 3  # 初始、每5秒健康检查、窗口结束


def test_dump_ticktask文件缺失时有限重试并最终返回次数(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    target = tmp_path / "ticktask_timings.csv"
    calls: list[str] = []
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    def submit(*_args: object, **_kwargs: object) -> bool:
        calls.append("dump")
        if len(calls) == 2:
            target.write_text("header\n", encoding="utf-8")
        return True

    monkeypatch.setattr(module.ga, "submit_console_command", submit)
    assert module.dump_ticktask_csv(1, target, max_attempts=3, attempt_timeout=1.0) == 2
    assert calls == ["dump", "dump"]


def test_dump_ticktask文件一直缺失时返回最大重试次数(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    target = tmp_path / "ticktask_timings.csv"
    calls: list[str] = []
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(
        module.ga,
        "submit_console_command",
        lambda *_args, **_kwargs: calls.append("dump") or True,
    )
    assert module.dump_ticktask_csv(1, target, max_attempts=2, attempt_timeout=1.0) == 2
    assert calls == ["dump", "dump"]


def test_error_log扫描区分真实错误无害错误和未生成(tmp_path: Path) -> None:
    module = _load()
    old_log = tmp_path / "error.1.log"
    current_log = tmp_path / "error.log"
    old_log.write_text(
        "SITAI Journal entry has redundant loc for sitai_goal\n",
        encoding="utf-8",
        newline="\n",
    )
    current_log.write_text(
        "[error] SITAI script error in common/sitai_bad.txt\n",
        encoding="utf-8",
        newline="\n",
    )
    scan = module.scan_game_errors(tmp_path)
    assert scan.readable is True
    assert scan.files == (str(old_log), str(current_log))
    assert scan.errors == ("[error] SITAI script error in common/sitai_bad.txt",)
    assert len(scan.benign) == 1
    assert module.scan_game_errors(tmp_path / "empty").readable is None


def test_report_table剔除不可用于性能结论的性能臂(tmp_path: Path) -> None:
    module = _load()
    csv = tmp_path / "vanilla.csv"
    csv.write_text(
        "frame,task,time_ms\n1,RecalculateModifierNodes,2\n", encoding="utf-8", newline="\n"
    )
    reports = [
        {
            "label": "vanilla",
            "index": 1,
            "csv": str(csv),
            "summary": {"per_frame_total_ms": {"mean": 4.0}},
            "performance_usable": True,
        },
        {
            "label": "ours",
            "index": 1,
            "csv": str(tmp_path / "missing.csv"),
            "summary": {"per_frame_total_ms": {"mean": 5.0}},
            "performance_usable": False,
            "performance_invalid_reasons": ["error.log 命中属于本 mod 的真实错误"],
        },
    ]
    table = module.report_table(reports)
    vanilla = table["by_label"]["vanilla"]
    assert vanilla["per_frame_mean"] == 4.0
    assert vanilla["task_mean"] is None
    assert vanilla["rss_peak_mib"] is None
    assert vanilla["cpu_seconds"] is None
    assert vanilla["wall_seconds"] is None
    assert vanilla["resource_samples"] == 0
    assert vanilla["runs"] == 1
    assert "delta" not in table
    assert table["invalid_runs"][0]["label"] == "ours"


def test_跨进程锁拒绝第二个持有者(tmp_path: Path) -> None:
    module = _load()
    first = module.RunLock(tmp_path / "probe.lock")
    second = module.RunLock(tmp_path / "probe.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="另一个实机实验"):
            second.acquire()
    finally:
        first.release()
        second.release()


def test_报告写入失败会让_cleaned_为假(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    _module, cleanup, _content, _target = _state(module, tmp_path, list)

    def fail_write(_path: Path, *_args: object, **_kwargs: object) -> None:
        raise OSError("只读")

    monkeypatch.setattr(Path, "write_text", fail_write)
    cleanup.run(reason="report-failure")
    assert cleanup.cleaned is False
    assert any("写入收尾报告" in error for error in cleanup.errors)


def _performance_report(
    label: str,
    index: int,
    csv: Path,
    *,
    days: float = 30.0,
    wall: float = 60.0,
    rss: float = 100.0,
    cpu: float = 20.0,
) -> dict[str, object]:
    return {
        "label": label,
        "index": index,
        "csv": str(csv),
        "summary": {"per_frame_total_ms": {"mean": 4.0}},
        "advanced": {"from": "1836.1.1", "to": "1836.2.1", "days": days},
        "samples": [
            {"rss_mib": rss - 1, "cpu_seconds": cpu - 1},
            {"rss_mib": rss, "cpu_seconds": cpu},
        ],
        "wall_seconds": wall,
        "performance_usable": True,
    }


def test_report_table_聚合资源和游戏日吞吐并计算差分(tmp_path: Path) -> None:
    module = _load()
    csv = tmp_path / "timings.csv"
    csv.write_text(
        "frame,task,milliseconds,calls,longest_lock\n1,RecalculateModifierNodes,2,1,0\n",
        encoding="utf-8",
        newline="\n",
    )
    reports = [
        _performance_report("vanilla", index, csv, wall=60 + index, rss=100 + index)
        for index in range(1, 4)
    ] + [
        _performance_report("ours", index, csv, wall=66 + index, rss=110 + index)
        for index in range(1, 4)
    ]
    table = module.report_table(reports, required_pairs=3)
    vanilla = table["by_label"]["vanilla"]
    assert vanilla["runs"] == 3
    assert vanilla["rss_peak_mib"] == 102.0
    assert vanilla["rss_start_mib"] == 101.0
    assert vanilla["rss_end_mib"] == 102.0
    assert vanilla["rss_change_mib"] == 1.0
    assert vanilla["cpu_seconds"] == 20.0
    assert vanilla["wall_seconds"] == 62.0
    assert vanilla["game_days"] == 30.0
    assert vanilla["wall_seconds_per_game_day"] == round(62.0 / 30.0, 4)
    assert vanilla["resource_samples"] == 6
    assert table["m4_gate"] == {"required_pairs": 3, "ok": True, "reasons": []}
    assert table["delta"]["rss_peak_mib"] == 10.0
    assert table["delta"]["wall_seconds_per_game_day"] == round(6.0 / 30.0, 4)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([800, 900, 1000], 200.0),
        ([800, 700, 1000], None),
        ([800], None),
        ([None, 900, 1000], None),
        ([800, 900, float("inf")], None),
    ],
)
def test_进程累计CPU必须使用窗口有效首尾差(tmp_path, values, expected):
    module = _load()
    report = _performance_report("vanilla", 1, tmp_path / "missing.csv", wall=999)
    report["resource_cpu_basis"] = "process_lifetime"
    report["measurement_wall_seconds"] = 60.0
    report["samples"] = [{"rss_mib": 100.0, "cpu_seconds": value} for value in values]
    metrics = module._sample_metrics(report)
    assert metrics["cpu_seconds"] == expected
    assert metrics["wall_seconds"] == 60.0
    assert metrics["wall_seconds_per_game_day"] == 2.0


def test_report_table_资源样本缺失时拒绝正式门禁但保留探索读数(tmp_path: Path) -> None:
    module = _load()
    csv = tmp_path / "timings.csv"
    csv.write_text(
        "frame,task,milliseconds,calls,longest_lock\n1,RecalculateModifierNodes,2,1,0\n",
        encoding="utf-8",
        newline="\n",
    )
    reports: list[dict[str, object]] = []
    for label in ("vanilla", "ours"):
        for index in range(1, 4):
            report = _performance_report(label, index, csv)
            if label == "ours" and index == 2:
                report["samples"] = []
            reports.append(report)
    table = module.report_table(reports, required_pairs=3)
    assert table["by_label"]["ours"]["runs"] == 3
    assert table["m4_gate"]["ok"] is False
    assert any("ours #2 缺少指标" in reason for reason in table["m4_gate"]["reasons"])
    assert "delta" not in table  # 门禁失败时不生成正式成对差分


def test_report_table_重复或缺失编号不能形成正式结论(tmp_path: Path) -> None:
    module = _load()
    csv = tmp_path / "timings.csv"
    csv.write_text(
        "frame,task,milliseconds,calls,longest_lock\n1,RecalculateModifierNodes,2,1,0\n",
        encoding="utf-8",
        newline="\n",
    )
    reports = [
        _performance_report("vanilla", 1, csv),
        _performance_report("vanilla", 1, csv),
        _performance_report("vanilla", 3, csv),
        _performance_report("ours", 1, csv),
        _performance_report("ours", 2, csv),
        _performance_report("ours", 3, csv),
    ]
    table = module.report_table(reports, required_pairs=3)
    assert table["m4_gate"]["ok"] is False
    assert any("重复实验编号" in reason for reason in table["m4_gate"]["reasons"])
    assert "delta" not in table


def test_window_control_正式门禁拒绝少于三组和重复臂() -> None:
    module = _load()
    one = {
        "label": "vanilla",
        "index": 1,
        "advanced": {"from": "1836.1.1", "to": "1837.1.1"},
    }
    reports = [one, {**one, "label": "ours"}, {**one, "label": "ours"}]
    verdict = module.window_control_verdict(reports, required_pairs=3)
    assert verdict.ok is False
    assert any("重复出现" in problem for problem in verdict.problems)
    assert any("1..3" in problem for problem in verdict.problems)
