"""生成不带旧仪器状态的原版观察者固定检查点。

这个入口只在 Windows + 本地 Victoria 3 实机上运行。它临时清空本地
``content_load.json`` 的启用 Mod，使用仓库已有的 ``game_auto`` 快捷键闭环
进入观察者局，在暂停状态下保存检查点，复制到仓库证据目录，再逐字节恢复
用户原有配置并删除用户存档目录中的临时文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from pdx import config
from pdx import game_auto as ga
from pdx.game_run import (
    Deployment,
    RunLock,
    hashes,
    log_findings,
    mount_allowlist,
    save_header,
    validate_load_save_header,
    write_json,
)

SAVE_NAME = "sitai_clean_observer_checkpoint"
OUT_DIR = config.OUT / "checkpoints"
CONTENT_LOAD = config.USERDIR / "content_load.json"
SAVE_DIR = config.USERDIR / "save games"
RULE_PRESETS = config.USERDIR / "player" / "game_rules" / "presets.txt"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _vanilla_content_load() -> bytes:
    return (
        json.dumps(
            {"enabledMods": [], "disabledDLC": [], "enabledUGC": []},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _wait_paused(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not ga.is_running(2.0).advanced:
            return
        time.sleep(0.25)
    raise ga.GameAutoError("保存检查点前游戏没有进入暂停状态")


def _wait_save(path: Path, *, previous_sha256: str | None, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    previous: tuple[int, int] | None = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        try:
            stat = path.stat()
            signature = stat.st_size, stat.st_mtime_ns
            if signature != previous:
                previous, stable_since = signature, time.monotonic()
            elif stat.st_size > 0 and time.monotonic() - stable_since >= 3:
                save_header(path)
                if previous_sha256 is not None and _sha256(path) == previous_sha256:
                    time.sleep(0.5)
                    continue
                return
        except (OSError, ValueError):
            previous = None
        time.sleep(0.5)
    raise ga.GameAutoError(f"游戏没有在期限内写出检查点：{path}")


def make_checkpoint(*, output: Path = OUT_DIR, name: str = SAVE_NAME) -> dict[str, Any]:
    """运行一次原版观察者局并返回固定检查点证据。"""

    if sys.platform != "win32":
        raise ga.WindowsOnlyError("生成实机观察者检查点需要 Windows GUI 输入后端")
    if not name or any(char in name for char in "/\\:") or name in {".", ".."}:
        raise ValueError("检查点名称必须是单个文件名")
    if output.resolve().is_relative_to(SAVE_DIR.resolve()):
        raise ValueError("检查点证据不能写入临时用户存档目录")
    with RunLock(CONTENT_LOAD.parent / ".sitai-game.lock"):
        return _make_checkpoint(output=output, name=name)


def _make_checkpoint(*, output: Path, name: str) -> dict[str, Any]:
    """复用实机运行器的持久备份和目录事务；未备份的原件绝不删除。"""
    ga.assert_no_game_running()
    Deployment.recover_pending(SAVE_DIR.parent)
    previous = ga._foreground_window()
    output.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="session-", dir=output))
    deployment = Deployment(SAVE_DIR.parent, evidence)
    deployment.content = CONTENT_LOAD
    session: ga.SessionStart | None = None
    result: dict[str, Any] = {
        "evidence": str(evidence),
        "kind": "vanilla_checkpoint_preparation",
        "game_version": config.game_version(),
        "content_load": "vanilla_only",
        "source_hashes": {},
        "deployed_hashes": {},
        "session_requested": False,
        "logs_isolated": False,
        "mount_allowlist": mount_allowlist([]),
        "ok": False,
    }
    target = output / f"{name}.v3"
    temporary = evidence / "saves" / "checkpoint.v3"
    try:
        if target.exists():
            raise FileExistsError(f"检查点已存在，拒绝覆盖证据：{target}")
        deployment.snapshot_state()
        deployment.isolate_saves()
        deployment.isolate_logs()
        result["logs_isolated"] = True
        deployment.deploy({})
        CONTENT_LOAD.write_bytes(_vanilla_content_load())
        RULE_PRESETS.unlink(missing_ok=True)
        autosave = SAVE_DIR / "autosave.v3"
        previous_sha256 = _sha256(autosave) if autosave.is_file() else None
        result["session_requested"] = True
        hwnd, old_foreground = ga.launch_to_foreground(
            scripted_tests=False, timeout=float(ga.WINDOW_TIMEOUT)
        )
        settle = ga.wait_for_boot_settle(timeout=float(ga.LOBBY_TIMEOUT))
        session = ga.start_session(
            hwnd,
            old_foreground,
            settle=settle,
            force=True,
            keep_foreground=True,
            loaded_observer=False,
        )
        if not session.rate_ok:
            raise ga.GameAutoError(f"观察者局 5 速验证失败：{session.rate}")
        ga.ensure_foreground(session.hwnd, force=True)
        ga.press_key("space", force=True)
        _wait_paused()
        if not ga.submit_console_command(session.hwnd, "save", force=True):
            raise ga.GameAutoError("保存检查点的控制台命令没有提交成功")
        _wait_save(autosave, previous_sha256=previous_sha256)
        header = save_header(autosave)
        expected_version = config.game_version().get("caligula_branch", "").split("/")[-1]
        validate_load_save_header(
            header,
            expected_version=expected_version,
            allow_save_upgrade=False,
        )
        if header.get("observer") != "yes":
            raise ga.GameAutoError(f"检查点不是观察者存档：{header}")
        digest = _sha256(autosave)
        temporary.parent.mkdir(parents=True)
        shutil.copyfile(autosave, temporary)
        if _sha256(temporary) != digest or _sha256(autosave) != digest:
            raise ga.GameAutoError("复制期间检查点发生变化，保留临时证据并拒绝发布")
        result.update(
            {
                "path": str(target),
                "sha256": digest,
                "bytes": temporary.stat().st_size,
                "header": header,
                "session": session.as_dict(),
                "state_evidence": str(evidence),
                "checkpoint": {"header": header, "hashes": {temporary.name: digest}},
            }
        )
    except BaseException as exc:
        result["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        cleanup_errors: list[str] = []
        try:
            ga.kill_owned_game()
        except Exception as exc:
            cleanup_errors.append(f"终止游戏失败；保留原件和实验目录：{exc}")
        if getattr(ga, "LAST_KILL_ALIVE", ()):
            cleanup_errors.append("游戏仍存活；保留原件和实验目录，不执行恢复")
        try:
            if ga._process_pids():
                cleanup_errors.append("独立核实游戏仍存活；保留原件和实验目录")
        except Exception as exc:
            cleanup_errors.append(f"无法核实游戏退出；保留原件和实验目录：{exc}")
        if not cleanup_errors:
            # 全目录归还由 Deployment 负责；顶级日志另保留标准原始归档。
            try:
                if any(original == SAVE_DIR.parent / "logs" for original, _ in deployment.claims):
                    ga.quarantine_logs(evidence / "logs")
                    cleanup_errors.extend(ga.LAST_QUARANTINE_ERRORS)
            except Exception as exc:
                cleanup_errors.append(f"检查点日志归档失败：{exc}")
            cleanup_errors.extend(deployment.restore())
        result["cleanup_errors"] = cleanup_errors
        try:
            result["log_hashes"] = hashes(evidence / "logs")
            findings = log_findings(
                evidence / "logs", [], expected_mounts=result["mount_allowlist"]
            )
            result["log_findings"] = findings
            result["ok"] = not (
                result.get("failure")
                or cleanup_errors
                or not result["log_hashes"]
                or any(findings["errors"].values())
                or findings["mod_errors"]
                or findings["missing_mounts"]
                or findings["unexpected_mounts"]
                or findings["unclassified_errors"]
            )
        except Exception as exc:
            result["failure"] = f"检查点日志门禁失败：{exc}"
        write_json(evidence / "report.json", result)
        write_json(
            evidence / "cleanup.json",
            {"cleaned": not cleanup_errors, "errors": cleanup_errors},
        )
        if previous:
            with suppress(Exception):
                ga._set_foreground(previous)
        if cleanup_errors:
            raise RuntimeError(f"检查点收尾失败；原始备份保留于 {evidence}：{cleanup_errors}")
    if not result["ok"]:
        raise ga.GameAutoError(f"检查点生成局未通过严格门禁；存档仅保留在证据目录：{evidence}")
    try:
        # RunLock 只约束项目入口；外部写入者仍可能在运行期间创建同名文件。
        # 独占创建保证发布不会覆写后出现的用户文件或旧证据。
        with temporary.open("rb") as source, target.open("xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        if _sha256(target) != result["sha256"]:
            raise ga.GameAutoError("检查点发布副本指纹不符；保留现场")
        result["published"] = True
    except Exception as exc:
        result.update(ok=False, published=False, failure=f"检查点发布失败：{exc}")
        raise
    finally:
        write_json(evidence / "report.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成原版观察者固定检查点")
    parser.add_argument("--output", type=Path, default=OUT_DIR)
    parser.add_argument("--name", default=SAVE_NAME)
    args = parser.parse_args(argv)
    evidence = make_checkpoint(output=args.output, name=args.name)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
