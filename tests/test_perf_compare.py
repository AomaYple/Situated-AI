"""性能对照探针的恢复与进程所有权回归测试。

这些用例不启动 Victoria 3，只验证性能探针最容易污染用户环境的边界：
运行前已有同名 mod、配置写入中断、收尾步骤失败，以及 Ctrl+C/SIGTERM。
"""

from __future__ import annotations

import importlib.util
import json
import signal
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

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
    assert not cleanup.backup_path.exists()


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
