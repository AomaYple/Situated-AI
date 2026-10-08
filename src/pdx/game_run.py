"""实机实验的互斥、可恢复部署、相对时间等待与原始证据归档。

该模块管理实验资源；游戏的输入、窗口和启动仍由 game_auto 管理。
恢复失败时保留备份，报告失败而不消耗唯一可恢复副本。
"""

from __future__ import annotations

import hashlib
import json
import math
import mmap
import os
import posixpath
import re
import shutil
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import psutil
from filelock import FileLock, Timeout

from . import config, gametimer
from . import game_auto as ga
from .textio import deploy_tree

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


ERROR_MARKERS = (
    "Unexpected token",
    "Unknown effect",
    "Unknown trigger",
    "Invalid database object",
    "Mod metadata read error",
    "Duplicated key",
    "Undefined event target",
    "Invalid left side",
    "Script system error!",
    "Assertion failed",
)


class LogFindings(TypedDict):
    errors: dict[str, int]
    mounted: list[str]
    missing_mounts: list[str]
    unexpected_mounts: list[str]
    mod_errors: list[str]
    observer_warnings: list[str]


class LogCapture:
    """按文件身份追踪追加字节，轮转改名不会重复读；原轮转件另存。"""

    def __init__(self, source: Path, destination: Path) -> None:
        self.source = source
        self.destination = destination
        self.offsets: dict[tuple[int, int], int] = {}
        self.errors: list[str] = []

    def poll(self) -> None:
        self.destination.mkdir(parents=True, exist_ok=True)
        for stem in ("debug", "error"):
            for path in ga.rotated_logs(self.source, stem):
                try:
                    with path.open("rb") as incoming:
                        stat = os.fstat(incoming.fileno())
                        identity = (stat.st_dev, stat.st_ino)
                        offset = self.offsets.get(identity, 0)
                        if stat.st_size < offset:
                            raise RuntimeError(f"日志原地截断，完整性不确定：{path}")
                        incoming.seek(offset)
                        with (self.destination / f"{stem}.log").open("ab") as target:
                            while chunk := incoming.read(65536):
                                target.write(chunk)
                            self.offsets[identity] = incoming.tell()
                except FileNotFoundError:
                    continue
                except (OSError, RuntimeError) as exc:
                    message = f"持续日志归档失败：{exc}"
                    if message not in self.errors:
                        self.errors.append(message)


class TickTaskCapture:
    """复用引擎任务计时；控制台输入后立即还后台，CSV必须新生成且完整。"""

    def __init__(self, evidence: Path) -> None:
        self.path = gametimer.ticktask_default_path()
        self.evidence = evidence
        self.start_tick = ""
        self.background: dict[str, object] = {}

    def start(self, session: ga.SessionStart) -> None:
        speed_key = getattr(session, "speed_key", None)
        if session.speed_xy is None and speed_key is None:
            raise ValueError("计时窗口需要已验证的速度坐标或快捷键，以恢复控制台后的键盘焦点")
        self.path.unlink(missing_ok=True)
        hwnd = ga._live_window(session.hwnd)
        ga.ensure_foreground(hwnd, force=True)
        try:
            ga.press_key("space", force=True)
            time.sleep(1.5)
            if not ga.submit_console_command(hwnd, "clear_ticktask_timings", force=True):
                raise RuntimeError("引擎计时清零命令未提交")
            if speed_key is not None:
                # 控制台命令提交后，游戏窗口仍可能把键盘焦点留在 console_edit。
                # 鼠标速度分支天然会通过 click_client 夺回游戏焦点；快捷键分支也必须
                # 先点击速度表盘，再发送 5，否则最后的 space 会被控制台吃掉，窗口
                # 退到后台后游戏仍停在清零时刻。速度最终仍由快捷键设置，点击只用于
                # 重新聚焦并同时确认速度控件存在。
                point = ga.speed_widget_xy(hwnd, threshold=0.75) or ga.SPEED_V_XY
                ga.click_client(hwnd, *point, force=True)
                ga.press_key(speed_key, force=True)
            else:
                assert session.speed_xy is not None
                ga.click_client(hwnd, *session.speed_xy, force=True)
            time.sleep(0.8)
            before = ga.tick_mark()
            self.start_tick = before.tick
            ga.press_key("space", force=True)
        finally:
            handover = ga.switch_to_background(hwnd, session.previous)
            self.background = {
                "foreground_restored": handover.restored,
                "minimized": handover.minimized,
            }
        if not handover.minimized:
            raise RuntimeError("引擎计时窗口未成功退到后台")
        ga.wait_until_running(before, timeout=30)

    def finish(self, session: ga.SessionStart, *, timeout: float = 30) -> dict[str, object]:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("CSV等待超时必须为有限正数")
        hwnd = ga._live_window(session.hwnd)
        end_tick = ga.tick_mark().tick
        self.path.unlink(missing_ok=True)
        ga.ensure_foreground(hwnd, force=True)
        try:
            ga.press_key("space", force=True)
            time.sleep(1.5)
            if not ga.submit_console_command(hwnd, "dump_ticktask_timings", force=True):
                raise RuntimeError("引擎计时导出命令未提交")
        finally:
            ga.switch_to_background(hwnd, session.previous)
        deadline = time.monotonic() + timeout
        previous = None
        while time.monotonic() < deadline:
            if self.path.is_file():
                stat = self.path.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
                if stat.st_size and signature == previous:
                    target = self.evidence / self.path.name
                    shutil.copy2(self.path, target)
                    parsed = gametimer.parse_ticktask_file(target)
                    summary = gametimer.summarize_ticktask(target, parsed=parsed)
                    if (
                        not summary["header_present"]
                        or summary["bad_lines"]
                        or not summary["frames"]
                    ):
                        raise ValueError("新引擎计时CSV缺表头、存在坏行或没有完整帧")
                    with target.open("rb") as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    return {
                        "csv": str(target),
                        "sha256": digest,
                        "start_tick": self.start_tick,
                        "end_tick": end_tick,
                        "background": self.background,
                        "summary": summary,
                        "tasks": {
                            stat.task: {
                                "mean_ms": stat.mean_ms,
                                "total_ms": stat.total_ms,
                            }
                            for stat in gametimer.ticktask_task_stats(parsed)
                        },
                        "limits": (
                            "Engine tick-task samples, integer milliseconds; not renderer frame "
                            "latency or FPS. Clear is confirmed by UI submission only. Includes "
                            "brief console/focus handover at measurement boundaries."
                        ),
                    }
                previous = signature
            time.sleep(1)
        raise TimeoutError("导出后没有新的稳定引擎计时CSV")


class RunLock:
    """使用成熟跨平台库锁住一次会话；锁文件不删除以避免 inode 竞争。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.USERDIR / ".sitai-game.lock"
        self._lock = FileLock(self.path)

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError(f"已有另一个实机实验正在运行（锁：{self.path}）") from exc

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> RunLock:
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def hashes(root: Path) -> dict[str, str]:
    """分块哈希，避免把存档或大日志整体读进内存。"""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    return result


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)


LEGACY_SAVE_MARKERS = (
    b"setting_sitai_",
    b"je_sitai_",
    b"sitai_ru_",
    b"sitai_au_revolution_",
    b"sitai_brz_market_loss_",
    b"sitai_bv_alignment_",
    b"sitai_cn_intervention_",
    b"sitai_eg_debt_",
    b"sitai_pe_great_game_",
    b"sitai_sp_empire_remnant_",
    b"sitai_tr_defeat_",
)
LEGACY_SAVE_PATTERN = re.compile(
    rb"setting_sitai_|je_sitai_|sitai_(?:ru_|au_revolution_|brz_market_loss_|"
    rb"bv_alignment_|cn_intervention_|eg_debt_|pe_great_game_|sp_empire_remnant_|tr_defeat_)"
)


def save_header(path: Path) -> dict[str, str]:
    """只读取二进制存档的有限明文头，不改写原始存档字节。"""
    with path.open("rb") as stream:
        header = stream.read(65536)
    if not header.startswith(b"SAV"):
        raise ValueError("存档缺少已验证的SAV头；拒绝猜测压缩格式")
    result = {}
    for key in ("version", "game_date", "player"):
        match = re.search(rb"\b" + key.encode() + rb'\s*=\s*"?([^\s"{}]+)', header)
        if match:
            result[key] = match[1].decode("utf-8")
    if not result.get("game_date") or not result.get("version"):
        raise ValueError("存档头缺少日期或版本")
    if re.search(rb'settings\s*=\s*\{[^}]*""', header):
        result["invalid_rules"] = "empty game-rule reference"
    # 观察者的player_manager数据库为空；缺该结构时保持未知，不能默认当观察者。
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        found = set(LEGACY_SAVE_PATTERN.findall(data))
        legacy = tuple(marker.decode("ascii") for marker in LEGACY_SAVE_MARKERS if marker in found)
        if legacy:
            result["legacy_mod_state"] = ",".join(legacy)
        at = data.find(b"player_manager=")
        if at >= 0:
            result["observer"] = (
                "yes"
                if re.match(rb"player_manager=\{\s*database=\{\s*}\s*}", data[at : at + 4096])
                else "no"
            )
    return result


def validate_load_save_header(
    header: Mapping[str, str], *, expected_version: str, allow_save_upgrade: bool
) -> None:
    """在启动游戏前拒绝不适合作为迁移输入的存档。"""

    if header.get("version") != expected_version and not allow_save_upgrade:
        raise ValueError("检查点游戏版本不一致；升级实验需显式声明")
    if header.get("invalid_rules"):
        raise ValueError("存档包含空游戏规则引用；保留原件并重新生成干净检查点")
    if header.get("legacy_mod_state"):
        raise ValueError(
            "存档包含已停用 Mod 状态；先保留原件并完成状态迁移，拒绝把旧世界直接载入新生产逻辑"
        )
    if header.get("observer") != "yes":
        raise ValueError("固定检查点必须是观察者存档")


def wait_save_ready(
    path: Path, *, earliest: float, original_sha256: str | None = None, timeout: float = 60
) -> dict[str, str]:
    """等本局自动存档写完；不把旧存档或写到一半的文件当检查点。"""
    deadline = time.monotonic() + timeout
    previous: tuple[int, int] | None = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        try:
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            if signature != previous:
                previous, stable_since = signature, time.monotonic()
            elif time.monotonic() - stable_since >= 3:
                header = save_header(path)
                day = ga.tick_day(header["game_date"])
                current = ga.tick_day(ga.tick_mark().tick)
                if (
                    day is not None
                    and current is not None
                    and earliest - 31 <= day <= min(current, earliest + 31)
                ):
                    with path.open("rb") as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    if digest != original_sha256:
                        return header
        except (OSError, ValueError):
            previous = None
        time.sleep(1)
    raise TimeoutError(f"本局自动存档未就绪：{path}")


class Deployment:
    """精确恢复启用配置以及实验前已存在的同名目录。"""

    def __init__(self, userdir: Path, evidence: Path) -> None:
        self.userdir = userdir
        self.evidence = evidence
        self.content = userdir / "content_load.json"
        self.original: bytes | None = None
        self.config_claimed = False
        self.claims: list[tuple[Path, Path | None]] = []
        self.state_files: dict[Path, Path | None] = {}

    def snapshot_state(self) -> None:
        """保存游戏本身会改写的用户状态；副本按内容复用，避免重复大存档。"""
        paths = [
            self.userdir / name
            for name in (
                "pdx_settings.json",
                "continue_game.json",
                "game_data.json",
                "player/game_rules/presets.txt",
                "ticktask_timings.csv",
            )
        ]
        saves = self.userdir / "save games"
        paths.extend(
            saves / name for name in ("autosave.v3", *(f"autosave_{i}.v3" for i in range(1, 6)))
        )
        backup_root = self.evidence.parent / "original-state"
        backup_root.mkdir(parents=True, exist_ok=True)
        for path in paths:
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError(f"用户状态不允许符号链接：{path}")
            if not path.is_file():
                self.state_files[path] = None
                continue
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            backup = backup_root / digest
            if not backup.exists():
                temp = backup.with_suffix(".tmp")
                shutil.copy2(path, temp)
                temp.replace(backup)
            with backup.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise OSError(f"用户状态备份校验失败：{backup}")
            self.state_files[path] = backup

    def isolate_saves(self) -> None:
        """隔离菜单会扫描的旧存档，结束时整体归还，不修改存档字节。"""
        saves = self.userdir / "save games"
        if any(path.is_symlink() for path in (saves, *saves.parents)):
            raise ValueError("存档目录不允许符号链接")
        backup = self.evidence / "original-save-directory"
        if backup.exists():
            raise ValueError("存档目录备份已存在，拒绝覆盖")
        if saves.exists():
            shutil.move(str(saves), str(backup))
            self.claims.append((saves, backup))
        else:
            self.claims.append((saves, None))
        saves.mkdir(parents=True)
        write_json(
            self.evidence / "state-backups.json",
            {str(p): str(saved) if saved else None for p, saved in self.state_files.items()},
        )

    def deploy(self, sources: Mapping[str, Path]) -> list[Path]:
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.original = self.content.read_bytes() if self.content.exists() else None
        original = json.loads(self.original.decode("utf-8-sig")) if self.original else {}
        if self.original is not None:
            (self.evidence / "content_load.original.backup").write_bytes(self.original)
        self.config_claimed = True
        destinations: list[Path] = []
        for name, source in sources.items():
            if Path(name).name != name or name in {"", ".", ".."}:
                raise ValueError(f"mod 目录名无效：{name!r}")
            dest = self.userdir / "mod" / name
            if any(p.is_symlink() for p in (dest, *dest.parents)):
                raise ValueError(f"部署目标不允许符号链接：{dest}")
            saved = None
            if dest.exists():
                saved = ga.unused_path(
                    dest.with_name(dest.name + ".sitai-backup"), stamp=ga.archive_stamp()
                )
                dest.rename(saved)
            self.claims.append((dest, saved))
            deploy_tree(source, dest)
            destinations.append(dest)
        payload = {
            "enabledMods": [{"path": str(p)} for p in destinations],
            "disabledDLC": original.get("disabledDLC", []),
            "enabledUGC": [],
        }
        write_json(self.content, payload)
        return destinations

    def source_after_isolation(self, source: Path) -> Path:
        """原存档或目录已移动时精确映射源路径，不另复制唯一原件。"""
        source = source.resolve()
        for original, backup in reversed(self.claims):
            resolved_original = original.resolve()
            if backup is not None and source.is_relative_to(resolved_original):
                return backup / source.relative_to(resolved_original)
        return source

    def stage_save(self, source: Path) -> str:
        """以内容指纹命名实验存档；不覆盖任何不同内容的用户存档。"""
        source = self.source_after_isolation(source)
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        target = self.userdir / "save games" / f"sitai_checkpoint_{digest[:16]}.v3"
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError("实验存档目标不允许符号链接")
        if target.exists():
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError("实验存档命名冲突，保留原文件")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.state_files[target] = None
            shutil.copy2(source, target)
        return target.name

    def restore(self) -> list[str]:
        errors: list[str] = []
        remaining_state: dict[Path, Path | None] = {}
        for path, backup in self.state_files.items():
            try:
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temp = path.with_suffix(".sitai-restore.tmp")
                    shutil.copy2(backup, temp)
                    temp.replace(path)
            except OSError as exc:
                errors.append(f"恢复用户状态 {path}：{exc}")
                remaining_state[path] = backup
        self.state_files = remaining_state
        if self.config_claimed:
            try:
                if self.original is None:
                    self.content.unlink(missing_ok=True)
                else:
                    temp = self.content.with_suffix(".sitai-restore.tmp")
                    temp.write_bytes(self.original)
                    temp.replace(self.content)
                    if self.content.read_bytes() != self.original:
                        raise RuntimeError("配置字节恢复校验失败")
                self.config_claimed = False
            except OSError as exc:
                errors.append(f"恢复 {self.content}：{exc}")
        remaining: list[tuple[Path, Path | None]] = []
        for dest, saved in reversed(self.claims):
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                if saved is not None:
                    shutil.move(str(saved), str(dest))
            except OSError as exc:
                errors.append(f"恢复 {dest}（备份 {saved}）：{exc}")
                remaining.append((dest, saved))
        self.claims = list(reversed(remaining))
        return errors


def wait_progress(
    months: float,
    *,
    timeout: float = 3600,
    poll: float = 5,
    sample: Callable[[], None] | None = None,
    start_tick: str | None = None,
) -> dict[str, object]:
    """从指定或当前 tick 起推进 N 月；无 tick、倒退、超时均明确失败。

    实机启动流程会在首次确认运行后短暂测量前台/后台速率。调用方若把
    ``start_tick`` 传入首次运行证据，就不会把这段已经发生的游戏时间排除在
    行为窗口之外；离线调用仍默认从函数调用时刻取基线。
    """
    if any(not math.isfinite(v) or v <= 0 for v in (months, poll, timeout)):
        raise ValueError("月份、轮询和超时必须为有限正数")
    baseline_tick = start_tick or ga.tick_mark().tick
    start_day = ga.tick_day(baseline_tick)
    if start_day is None:
        raise RuntimeError("开始等待时没有可读 tick")
    deadline = time.monotonic() + timeout
    target_days = months * 365.25 / 12
    while True:
        tick = ga.tick_mark().tick
        day = ga.tick_day(tick)
        if day is not None and day < start_day:
            raise RuntimeError(f"游戏时间倒退：{baseline_tick} → {tick}")
        if sample is not None:
            sample()
        if day is not None and day - start_day >= target_days:
            return {"start": baseline_tick, "end": tick, "days": day - start_day, "reached": True}
        if time.monotonic() >= deadline:
            raise TimeoutError(f"未推进 {months} 月：{baseline_tick} → {tick}")
        time.sleep(min(poll, max(0, deadline - time.monotonic())))


def _normalize_mount_path(value: Path | str) -> str:
    """把日志和部署路径变成可跨平台比较的完整路径。

    游戏日志在 Windows 上可能使用反斜杠，而运行器在不同平台生成的
    ``Path`` 使用本机分隔符。这里不调用本机 ``Path.resolve``，避免在
    macOS/Linux 上把 Windows 日志误解释成相对路径；只做分隔符、重复
    分隔符和 ``.`` 段的词法规范化，大小写按游戏路径语义折叠。
    """
    text = str(value).strip().replace("\\", "/")
    return posixpath.normpath(text).casefold()


def _base_mount_allowlist() -> list[Path]:
    """返回本局允许的原版内容挂载；不把它们当成缺失项。

    游戏会逐项记录 ``jomini``、``clausewitz``、``game``、平台数据和 DLC。
    DLC 目录从当前安装读取，避免把 Workshop 或用户 mod 目录误当成原版。
    """
    roots = [
        config.CLAUSEWITZ,
        config.JOMINI,
        config.GAME,
        config.ROOT / "platform_specific_game_data",
    ]
    dlc = config.GAME / "dlc"
    with suppress(OSError):
        roots.extend(sorted((path for path in dlc.iterdir() if path.is_dir()), key=str))
    # 没有游戏树时，离线测试仍可调用日志解析；生产运行会在挂载门禁中
    # 通过缺失的候选/错误日志报告失败，而不是在这里抛出无关异常。
    return roots


def mount_allowlist(destinations: list[Path]) -> list[str]:
    """生成并冻结本局完整挂载允许列表（规范化路径）。"""
    return sorted(
        {_normalize_mount_path(path) for path in (*_base_mount_allowlist(), *destinations)}
    )


def _mounted_path(line: str) -> str | None:
    marker = "Mounted Data:"
    if marker not in line:
        return None
    value = line.split(marker, 1)[1].strip()
    return _normalize_mount_path(value) if value else None


def log_findings(
    logdir: Path,
    destinations: Sequence[Path | str],
    *,
    expected_mounts: Sequence[Path | str] | None = None,
) -> LogFindings:
    """仅解析本局归档；严格模式按完整允许列表拒绝额外挂载。

    ``expected_mounts`` 为空时保留旧的离线解析口径，只检查部署目标是否存在。
    实机运行必须传入 :func:`mount_allowlist` 的结果；这样历史报告可以被重新
    解析，但没有新允许列表的历史报告不会被追认为通过。
    """
    errors = dict.fromkeys(ERROR_MARKERS, 0)
    mounted: list[str] = []
    mounted_paths: set[str] = set()
    mod_errors: list[str] = []
    observer_warnings: list[str] = []
    for path in sorted(logdir.glob("*.log")):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if path.name.startswith("error"):
                    for marker in ERROR_MARKERS:
                        errors[marker] += line.count(marker)
                    if "sitai" in line.casefold():
                        if "Variable 'sitai_fiscal_risk' is used but is never set." in line:
                            observer_warnings.append(line.strip())
                        else:
                            mod_errors.append(line.strip())
                if "Mounted Data" in line:
                    raw = line.strip()
                    mounted.append(raw)
                    if (path_value := _mounted_path(raw)) is not None:
                        mounted_paths.add(path_value)
    expected = {_normalize_mount_path(path) for path in (expected_mounts or destinations)}
    required = list(expected_mounts) if expected_mounts is not None else destinations
    missing = [str(path) for path in required if _normalize_mount_path(path) not in mounted_paths]
    unexpected = sorted(mounted_paths - expected) if expected_mounts is not None else []
    return {
        "errors": errors,
        "mounted": mounted,
        "missing_mounts": missing,
        "unexpected_mounts": unexpected,
        "mod_errors": mod_errors,
        "observer_warnings": observer_warnings,
    }


def require_clean_report(report: dict) -> None:
    """配对必须采用完整门禁；不能仅凭历史ok字段接受漏判报告。"""
    if report.get("review", {}).get("mounts_verified") is False:
        raise ValueError("挂载隔离证据不足；旧报告缺少完整允许列表，不能作为严格通过")
    findings = report.get("log_findings", {})
    counts = findings.get("errors", {})
    if (
        not report.get("ok")
        or report.get("failure")
        or report.get("cleanup_errors")
        or not set(ERROR_MARKERS) <= counts.keys()
        or any(type(value) is not int or value != 0 for value in counts.values())
        or findings.get("mod_errors")
        or findings.get("missing_mounts")
        or findings.get("unexpected_mounts")
    ):
        raise ValueError("两臂实机门禁必须通过；旧口径需先核对原始归档")


def read_reviewed_report(path: Path) -> dict:
    """验证归档指纹并重新执行当前门禁；不修改历史报告或日志。"""
    report: dict = json.loads(path.read_text(encoding="utf-8"))
    logdir = path.parent / "logs"
    expected = report.get("log_hashes")
    if not expected or not logdir.is_dir() or hashes(logdir) != expected:
        raise ValueError("原始归档缺少完整日志指纹或指纹已变更；拒绝复核为通过")
    allowlist = report.get("mount_allowlist")
    mounts_verified = isinstance(allowlist, list) and bool(allowlist)
    if isinstance(allowlist, list) and allowlist:
        findings = log_findings(logdir, allowlist, expected_mounts=allowlist)
    else:
        # 历史报告只保存了 missing_mounts，无法从原始日志恢复当时的完整
        # 允许列表；保留原始字段供追溯，但禁止把它当作新的隔离门禁通过。
        findings = log_findings(logdir, [])
        findings["missing_mounts"] = report.get("log_findings", {}).get("missing_mounts", [])
        findings["unexpected_mounts"] = []
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report["review"] = {
        "report_sha256": digest,
        "original_ok": report.get("ok"),
        "logs_verified": True,
        "mounts_verified": mounts_verified,
    }
    report["log_findings"] = findings
    if (
        not mounts_verified
        or any(findings["errors"].values())
        or findings["mod_errors"]
        or findings["missing_mounts"]
        or findings["unexpected_mounts"]
    ):
        report["ok"] = False
        report.setdefault("failure", "当前门禁复核发现引擎错误或挂载隔离证据不足")
    return report


def graceful_stop(hwnd: int, *, timeout: float = 30) -> dict[str, object]:
    """先请求本会话窗口正常退出，让引擎完成日志写入；失败交给强制收尾。"""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("正常退出超时必须为有限正数")
    hwnd = ga._live_window(hwnd)
    pid = ga._window_pid(hwnd)
    expected = ga._OWNED_GAME_META.get(pid) if pid is not None else None
    if (
        pid not in ga._OWNED_GAME_PIDS
        or expected is None
        or not ga._owned_identity_matches(psutil.Process(pid), expected)
    ):
        raise RuntimeError("退出请求未核实本会话游戏进程身份，拒绝发送输入")
    ga.ensure_foreground(hwnd, force=True)
    ga.press_chord("alt+f4", force=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not ga._process_pids():
            return {"exited": True, "method": "window close request", "pid": pid}
        time.sleep(0.25)
    raise TimeoutError("窗口关闭请求后游戏未在期限内正常退出")


def run(
    sources: Mapping[str, Path],
    *,
    months: float,
    output: Path,
    analyze: Callable[[Path], object] | None = None,
    timeout: float = 3600,
    load_save: Path | None = None,
    keep_save: bool = False,
    allow_save_upgrade: bool = False,
    profile: bool = False,
) -> dict[str, object]:
    """运行隔离观察者局，成功与失败都保留不可覆盖的原始证据。"""
    if not math.isfinite(months) or months <= 0:
        raise ValueError("months 必须为有限正数")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout 必须为有限正数")
    if not sources or any(not path.is_dir() for path in sources.values()):
        raise ValueError("实验必须提供存在的 mod 源目录")
    with RunLock():
        ga.assert_no_game_running()
        evidence = ga.unused_path(output / ga.archive_stamp(), stamp=ga.archive_stamp())
        evidence.mkdir(parents=True)
        deployment = Deployment(config.USERDIR, evidence)
        report: dict[str, object] = {
            "evidence": str(evidence),
            "game_version": config.game_version(),
            "months": months,
            "source_hashes": {name: hashes(path) for name, path in sources.items()},
        }
        samples: list[dict[str, object]] = []
        previous = ga._foreground_window()
        original_input = ga.ALLOW_REAL_INPUT
        started = time.monotonic()
        cleanup_errors: list[str] = []
        destinations: list[Path] = []
        expected_mounts: list[str] | None = None
        capture = LogCapture(config.USERDIR / "logs", evidence / "logs")
        stop_monitor = threading.Event()
        monitor: threading.Thread | None = None
        phase = "startup"
        monitor_errors: list[str] = []
        profiler = TickTaskCapture(evidence) if profile else None
        session: ga.SessionStart | None = None

        def sample() -> None:
            rss = cpu = 0.0
            for pid in tuple(ga._OWNED_GAME_PIDS):
                try:
                    process = psutil.Process(pid)
                    identity = ga._OWNED_GAME_META.get(pid)
                    if identity is not None and not ga._owned_identity_matches(process, identity):
                        continue
                    with process.oneshot():
                        rss += process.memory_info().rss
                        times = process.cpu_times()
                        cpu += times.user + times.system
                except psutil.NoSuchProcess:
                    continue
            samples.append(
                {
                    "seconds": time.monotonic() - started,
                    "rss_mib": rss / 1024**2,
                    "cpu_seconds": cpu,
                    "phase": phase,
                    "tick": ga.tick_mark().tick,
                }
            )
            write_json(evidence / "live.json", samples[-1])

        def observe() -> None:
            next_sample = 0.0
            while not stop_monitor.is_set():
                try:
                    capture.poll()
                    if time.monotonic() >= next_sample:
                        sample()
                        next_sample = time.monotonic() + 5
                except Exception as exc:
                    monitor_errors.append(f"实机监测失败：{type(exc).__name__}: {exc}")
                    return
                stop_monitor.wait(0.25)

        try:
            for name, source in sources.items():
                if Path(name).name != name or name in {"", ".", ".."}:
                    raise ValueError(f"mod目录名无效：{name}")
                if any(p.is_symlink() for p in (source, *source.rglob("*"))):
                    raise ValueError(f"实验源不允许符号链接：{source}")
                if source.resolve() in evidence.resolve().parents:
                    raise ValueError("证据目录不能放在实验源内")
                shutil.copytree(source, evidence / "sources" / name)
            deployment.snapshot_state()
            deployment.isolate_saves()
            # 仅本局用干净预设；原件已按字节备份，收尾恢复。
            (config.USERDIR / "player/game_rules/presets.txt").unlink(missing_ok=True)
            report["quarantined"] = ga.quarantine_logs(evidence / "previous-logs")
            if ga.LAST_QUARANTINE_ERRORS:
                raise RuntimeError(f"日志隔离失败：{ga.LAST_QUARANTINE_ERRORS}")
            destinations = deployment.deploy(sources)
            report["deployed_hashes"] = {p.name: hashes(p) for p in destinations}
            expected_mounts = mount_allowlist(destinations)
            report["mount_allowlist"] = expected_mounts
            monitor = threading.Thread(target=observe, name="sitai-evidence", daemon=True)
            monitor.start()
            ga.ALLOW_REAL_INPUT = True
            save_name = None
            if load_save is not None:
                source_save = deployment.source_after_isolation(load_save)
                header = save_header(source_save)
                expected_version = config.game_version().get("caligula_branch", "").split("/")[-1]
                validate_load_save_header(
                    header,
                    expected_version=expected_version,
                    allow_save_upgrade=allow_save_upgrade,
                )
                staged_name = deployment.stage_save(source_save)
                save_name = Path(staged_name).stem
                with source_save.open("rb") as stream:
                    save_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
                report["loaded_save"] = {
                    "header": header,
                    "name": staged_name,
                    "sha256": save_sha256,
                    "upgrade_requested": allow_save_upgrade,
                }
            session = ga.run_session(scripted_tests=False, force=True, save_name=save_name)
            report["session"] = session.as_dict()
            if not session.rate_ok:
                raise RuntimeError("5 速验证失败")
            if load_save is not None:
                expected = ga.tick_day(header["game_date"])
                actual = ga.tick_day(session.advance.after) if session.advance else None
                if expected is None or actual is None or not 0 <= actual - expected <= 31:
                    raise RuntimeError("载入后的日期与检查点不一致，拒绝把新开局当重载")
            if profiler is not None:
                profiler.start(session)
            phase = "simulation"
            session_advance = getattr(session, "advance", None)
            activation_tick = session_advance.after if session_advance is not None else None
            progress = wait_progress(months, timeout=timeout, start_tick=activation_tick)
            progress["activation_tick"] = activation_tick
            progress["activation_source"] = "session.advance.after" if activation_tick else "wait_progress baseline"
            report["progress"] = progress
            if keep_save:
                end = ga.tick_day(str(progress["end"]))
                assert end is not None
                auto = config.USERDIR / "save games/autosave.v3"
                original = deployment.state_files.get(auto)
                report["checkpoint_ready"] = wait_save_ready(
                    auto, earliest=end, original_sha256=original.name if original else None
                )
                report["checkpoint_scope"] = "within 31 game days of completed window end"
                report["after_checkpoint_wait"] = ga.tick_mark().tick
            if profiler is not None:
                phase = "profiling"
                report["ticktask"] = profiler.finish(session)
        except Exception as exc:
            report["failure"] = f"{type(exc).__name__}: {exc}"
        except BaseException:
            report["failure"] = "实机实验被中断"
            raise
        finally:
            if session is not None:
                try:
                    report["shutdown"] = graceful_stop(session.hwnd)
                except Exception as exc:
                    cleanup_errors.append(
                        f"正常退出失败，执行强制收尾：{type(exc).__name__}: {exc}"
                    )
            try:
                ga.kill_owned_game()
            except Exception as exc:
                cleanup_errors.append(f"终止本局游戏：{type(exc).__name__}: {exc}")
            stopped = False
            try:
                stopped = not ga._process_pids()
            except Exception as exc:
                cleanup_errors.append(f"核实游戏进程退出：{type(exc).__name__}: {exc}")
            if not stopped:
                cleanup_errors.append(
                    "游戏进程仍存活；暂不移动日志、恢复配置或存档，原始备份已保留"
                )
            stop_monitor.set()
            if monitor is not None:
                monitor.join(timeout=10)
                if monitor.is_alive():
                    cleanup_errors.append("证据监测线程未退出；本局证据不完整")
                else:
                    try:
                        capture.poll()
                    except Exception as exc:
                        cleanup_errors.append(f"最终日志采集失败：{type(exc).__name__}: {exc}")
            cleanup_errors.extend(capture.errors)
            cleanup_errors.extend(monitor_errors)
            if stopped and keep_save and not report.get("failure"):
                try:
                    source_save = config.USERDIR / "save games/autosave.v3"
                    save = evidence / "saves/autosave.v3"
                    save.parent.mkdir(parents=True)
                    shutil.copy2(source_save, save)
                    report["checkpoint"] = {
                        "path": str(save),
                        "header": save_header(save),
                        "hashes": hashes(save.parent),
                    }
                    if save_header(save).get("invalid_rules"):
                        raise ValueError("本局检查点包含空游戏规则引用，未通过载入前置检查")
                except Exception as exc:
                    report.setdefault("failure", f"检查点归档失败：{type(exc).__name__}: {exc}")
            for name, action in (
                ("归档本局日志", lambda: ga.quarantine_logs(evidence / "logs-raw")),
                ("恢复配置与目录", deployment.restore),
                ("恢复原窗口", lambda: ga._set_foreground(previous) if previous else None),
            ):
                if not stopped and name != "恢复原窗口":
                    continue
                try:
                    result = action()
                    if name == "恢复配置与目录" and isinstance(result, list):
                        cleanup_errors.extend(str(item) for item in result)
                    if name == "归档本局日志" and ga.LAST_QUARANTINE_ERRORS:
                        cleanup_errors.extend(ga.LAST_QUARANTINE_ERRORS)
                except Exception as exc:
                    cleanup_errors.append(f"{name}：{type(exc).__name__}: {exc}")
            ga.ALLOW_REAL_INPUT = original_input
            findings = None
            try:
                (evidence / "logs").mkdir(parents=True, exist_ok=True)
                for path in (evidence / "logs-raw").glob("*.log"):
                    if not path.name.startswith(("debug", "error")):
                        try:
                            shutil.copy2(path, evidence / "logs" / path.name)
                        except OSError as exc:
                            cleanup_errors.append(f"复制归档日志 {path.name}：{exc}")
                report["raw_log_hashes"] = hashes(evidence / "logs-raw")
                report["log_hashes"] = hashes(evidence / "logs")
                report["log_findings"] = findings = log_findings(
                    evidence / "logs",
                    destinations,
                    expected_mounts=expected_mounts,
                )
            except Exception as exc:
                cleanup_errors.append(f"汇总本局证据：{type(exc).__name__}: {exc}")
            report["monitoring"] = {
                "log_poll_seconds": 0.25,
                "process_poll_seconds": 5,
                "scope": "owned game PID RSS and CPU; startup and simulation; sampled peaks, not frame-time measurements",
                "limits": "Polling captures known rotating files; rotations faster than the retention window may lose unseen bytes.",
            }
            report["cleanup_errors"] = cleanup_errors
            report["samples"] = samples
            report["wall_seconds"] = time.monotonic() - started
            if findings is not None and (
                any(findings["errors"].values())
                or findings["mod_errors"]
                or findings["missing_mounts"]
                or findings["unexpected_mounts"]
            ):
                report.setdefault("failure", "引擎错误或缺少本局挂载证据")
            if cleanup_errors:
                report.setdefault("failure", "实机收尾失败；备份已保留")
            if analyze is not None:
                try:
                    report["analysis"] = analyze(evidence / "logs")
                except Exception as exc:
                    report.setdefault("failure", f"日志分析失败：{exc}")
            report["ok"] = not report.get("failure")
            write_json(evidence / "report.json", report)
            write_json(output / "latest.json", report)
        return report
