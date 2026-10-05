"""性能对照探针的恢复与进程所有权回归测试。

这些用例不启动 Victoria 3，只验证性能探针最容易污染用户环境的边界：
运行前已有同名 mod、配置写入中断、收尾步骤失败，以及 Ctrl+C/SIGTERM。
"""

from __future__ import annotations

import importlib.util
import json
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from pdx import config

pytestmark = pytest.mark.unit

_SCRIPT = config.REPO / "tools" / "probe" / "perf_compare.py"


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


def test_单项清理失败不阻断其它恢复步骤(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert content.read_bytes() == b'{"enabledMods": []}\n'
    assert (target / "original.txt").is_file()
    assert not (target / "generated.txt").exists()
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


def test_窗口日期判据要求每一对首末日期完全一致() -> None:
    module = _load()
    same = [
        {"label": "vanilla", "index": 1, "advanced": {"from": "1836.1.1", "to": "1837.1.1"}},
        {"label": "ours", "index": 1, "advanced": {"from": "1836.1.1", "to": "1837.1.1"}},
    ]
    verdict = module.window_control_verdict(same)
    assert verdict.ok
    assert verdict.pairs == 1
    assert verdict.comparisons[0]["comparable"] is True

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
    assert table["by_label"] == {"vanilla": {"per_frame_mean": 4.0, "task_mean": None, "runs": 1}}
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
