"""原版观察者固定检查点生成器的离线回归。

这些用例不启动 Victoria 3；它们只验证一次性实机工具最重要的安全边界：
vanilla 配置字节、用户存档与规则预设的备份恢复，以及非 Windows 平台的明确拒绝。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from pdx import config

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_SCRIPT = config.REPO / "tools" / "probe" / "make_clean_checkpoint.py"


@pytest.fixture(autouse=True)
def _isolate_output_and_processes(tmp_path, monkeypatch):
    from pdx import game_auto

    monkeypatch.setattr(config, "OUT", tmp_path / "probe-out")
    monkeypatch.setattr(game_auto, "_process_pids", list)
    monkeypatch.setattr(game_auto, "LAST_KILL_ALIVE", [])
    monkeypatch.setattr(sys, "platform", "win32")


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("probe_make_clean_checkpoint", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vanilla_content_load是无bom的最小配置() -> None:
    module = _load()
    payload = module._vanilla_content_load()

    assert payload.startswith(b"{")
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert payload.endswith(b"\n")
    assert json.loads(payload) == {
        "enabledMods": [],
        "disabledDLC": [],
        "enabledUGC": [],
    }


def test_make_checkpoint在非windows平台明确拒绝(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setattr(module.sys, "platform", "linux")

    with pytest.raises(module.ga.WindowsOnlyError, match="Windows GUI"):
        module.make_checkpoint(output=tmp_path)


def test_make_checkpoint恢复配置规则和全部用户存档(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    content = tmp_path / "content_load.json"
    content.write_bytes(b'{"enabledMods":["user-mod"]}\r\n')
    presets = tmp_path / "player" / "game_rules" / "presets.txt"
    presets.parent.mkdir(parents=True)
    presets.write_bytes(b"user rules\r\n")
    save_dir = tmp_path / "save games"
    save_dir.mkdir()
    user_save = save_dir / "user.v3"
    old_autosave = save_dir / "autosave.v3"
    user_save.write_bytes(b"SAV-user")
    old_autosave.write_bytes(b"SAV-old-autosave")
    output = tmp_path / "evidence"

    monkeypatch.setattr(module, "CONTENT_LOAD", content)
    monkeypatch.setattr(module, "RULE_PRESETS", presets)
    monkeypatch.setattr(module, "SAVE_DIR", save_dir)
    monkeypatch.setattr(module, "OUT_DIR", output)
    monkeypatch.setattr(module.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(module.ga, "_foreground_window", lambda: 456)
    monkeypatch.setattr(module.ga, "_set_foreground", lambda _hwnd: None)
    monkeypatch.setattr(
        module.ga,
        "launch_to_foreground",
        lambda **_kwargs: (123, 456),
    )
    monkeypatch.setattr(module.ga, "wait_for_boot_settle", lambda **_kwargs: object())

    class FakeSession:
        hwnd = 123
        rate_ok = True
        rate = 5.0

        def as_dict(self) -> dict[str, object]:
            return {"speed_days_per_second": self.rate, "speed_ok": self.rate_ok}

    monkeypatch.setattr(module.ga, "start_session", lambda *_args, **_kwargs: FakeSession())
    monkeypatch.setattr(module.ga, "ensure_foreground", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.ga, "press_key", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module.ga,
        "is_running",
        lambda *_args, **_kwargs: SimpleNamespace(advanced=False),
    )
    monkeypatch.setattr(module.ga, "kill_owned_game", list)

    def fake_save_command(_hwnd: int, command: str, **_kwargs: object) -> bool:
        assert command == "save"
        old_autosave.write_bytes(b"SAV-new-checkpoint")
        return True

    monkeypatch.setattr(module.ga, "submit_console_command", fake_save_command)
    monkeypatch.setattr(
        module,
        "save_header",
        lambda _path: {"version": "1.14.5", "game_date": "1836.2.1", "observer": "yes"},
    )
    validated: list[dict[str, object]] = []

    def fake_validate(header: dict[str, object], **_kwargs: object) -> None:
        validated.append(header)

    monkeypatch.setattr(module, "validate_load_save_header", fake_validate)

    evidence = module.make_checkpoint(output=output, name="offline-test")

    target = output / "offline-test.v3"
    assert target.read_bytes() == b"SAV-new-checkpoint"
    assert evidence["path"] == str(target)
    assert evidence["bytes"] == len(b"SAV-new-checkpoint")
    assert evidence["sha256"]
    assert evidence["content_load"] == "vanilla_only"
    assert evidence["session"] == {"speed_days_per_second": 5.0, "speed_ok": True}
    assert validated == [{"version": "1.14.5", "game_date": "1836.2.1", "observer": "yes"}]

    assert content.read_bytes() == b'{"enabledMods":["user-mod"]}\r\n'
    assert presets.read_bytes() == b"user rules\r\n"
    assert user_save.read_bytes() == b"SAV-user"
    assert old_autosave.read_bytes() == b"SAV-old-autosave"
    assert sorted(path.name for path in save_dir.glob("*.v3")) == ["autosave.v3", "user.v3"]


def test_make_checkpoint恢复原本不存在的规则预设(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    content = tmp_path / "content_load.json"
    content.write_bytes(b"{}\n")
    presets = tmp_path / "player" / "game_rules" / "presets.txt"
    save_dir = tmp_path / "save games"
    save_dir.mkdir()
    output = tmp_path / "evidence"
    monkeypatch.setattr(module, "CONTENT_LOAD", content)
    monkeypatch.setattr(module, "RULE_PRESETS", presets)
    monkeypatch.setattr(module, "SAVE_DIR", save_dir)
    monkeypatch.setattr(module, "OUT_DIR", output)
    monkeypatch.setattr(module.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(module.ga, "_foreground_window", lambda: None)
    monkeypatch.setattr(module.ga, "launch_to_foreground", lambda **_kwargs: (1, 0))
    monkeypatch.setattr(module.ga, "wait_for_boot_settle", lambda **_kwargs: object())

    class FakeSession:
        hwnd = 1
        rate_ok = True
        rate = 5.0

        def as_dict(self) -> dict[str, object]:
            return {}

    monkeypatch.setattr(module.ga, "start_session", lambda *_args, **_kwargs: FakeSession())
    monkeypatch.setattr(module.ga, "ensure_foreground", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.ga, "press_key", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module.ga, "is_running", lambda *_args, **_kwargs: SimpleNamespace(advanced=False)
    )
    monkeypatch.setattr(module.ga, "kill_owned_game", list)
    monkeypatch.setattr(
        module.ga,
        "submit_console_command",
        lambda *_args, **_kwargs: (save_dir / "autosave.v3").write_bytes(b"new") or True,
    )
    monkeypatch.setattr(
        module,
        "save_header",
        lambda _path: {"version": "1.14.5", "game_date": "1836.2.1", "observer": "yes"},
    )
    monkeypatch.setattr(module, "validate_load_save_header", lambda *_args, **_kwargs: None)

    module.make_checkpoint(output=output, name="missing-presets")

    assert not presets.exists()
    assert content.read_bytes() == b"{}\n"


@pytest.mark.parametrize("failure", ["launch", "backup", "kill", "alive", "check"])
def test_检查点部分失败保护原件(tmp_path, monkeypatch, failure):
    module = _load()
    user = tmp_path / "user"
    saves = user / "save games"
    saves.mkdir(parents=True)
    (saves / "nested").mkdir()
    (saves / "nested" / "manual.bin").write_bytes(b"unique-save")
    content = user / "content_load.json"
    content.write_bytes(b"{}\r\n")
    presets = user / "player/game_rules/presets.txt"
    presets.parent.mkdir(parents=True)
    presets.write_bytes(b"rules")
    output = tmp_path / "evidence"
    monkeypatch.setattr(module, "CONTENT_LOAD", content)
    monkeypatch.setattr(module, "RULE_PRESETS", presets)
    monkeypatch.setattr(module, "SAVE_DIR", saves)
    monkeypatch.setattr(module.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(module.ga, "_foreground_window", lambda: None)
    monkeypatch.setattr(module.ga, "kill_owned_game", list)

    def fail(*_args, **_kwargs):
        raise OSError("injected failure")

    monkeypatch.setattr(module.ga, "launch_to_foreground", fail)
    if failure == "backup":
        monkeypatch.setattr(module.Deployment, "snapshot_state", fail)
    elif failure == "kill":
        monkeypatch.setattr(module.ga, "kill_owned_game", fail)
    elif failure == "alive":
        monkeypatch.setattr(module.ga, "_process_pids", lambda: [123])
    elif failure == "check":
        monkeypatch.setattr(module.ga, "_process_pids", fail)
    with pytest.raises((OSError, RuntimeError), match=r"failure|收尾失败"):
        module.make_checkpoint(output=output)
    if failure in {"launch", "backup"}:
        assert (saves / "nested/manual.bin").read_bytes() == b"unique-save"
        assert presets.read_bytes() == b"rules"
        assert content.read_bytes() == b"{}\r\n"
    else:
        backup = next(output.glob("session-*/original-save-directory"))
        assert (backup / "nested/manual.bin").read_bytes() == b"unique-save"
        assert not (saves / "nested/manual.bin").exists()
        report = json.loads(next(output.glob("session-*/cleanup.json")).read_bytes())
        assert not report["cleaned"]


@pytest.mark.parametrize("name", ["../outside", "a/b", "a\\b", "a:b", ".", "..", ""])
def test_检查点拒绝越界名称(tmp_path, name):
    with pytest.raises(ValueError, match="单个文件名"):
        _load().make_checkpoint(output=tmp_path, name=name)


def test_检查点证据不能随用户存档隔离删除(tmp_path, monkeypatch):
    module = _load()
    monkeypatch.setattr(module, "SAVE_DIR", tmp_path)
    with pytest.raises(ValueError, match="用户存档目录"):
        module.make_checkpoint(output=tmp_path / "evidence")


def test_存档持续变化不能被当作完整检查点(tmp_path, monkeypatch):
    module = _load()
    save = tmp_path / "autosave.v3"
    save.write_bytes(b"SAV-partial")
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def grow(seconds):
        clock[0] += seconds
        save.write_bytes(save.read_bytes() + b"x")

    monkeypatch.setattr(module.time, "sleep", grow)
    monkeypatch.setattr(module, "save_header", lambda _path: {})
    with pytest.raises(module.ga.GameAutoError, match="期限"):
        module._wait_save(save, previous_sha256=None, timeout=5)
