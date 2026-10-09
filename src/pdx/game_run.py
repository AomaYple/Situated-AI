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
from typing import TYPE_CHECKING, Any, TypedDict

import psutil
from filelock import FileLock, Timeout

from . import checkpoint_catalog, config, gametimer
from . import game_auto as ga
from .deployment_state import digest as file_sha
from .deployment_state import durable_json, move_directory, plain_path, temporary_file, tree_digest
from .experiment_queue import ExperimentLedger
from .performance import StageTimings
from .textio import deploy_tree

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from .experiment_queue import RunRequest


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
OBSERVER_WARNING = "Variable 'sitai_fiscal_risk' is used but is never set."


class LiveLogGuard:
    """只检查新 error 字节，跨块/轮转保留匹配；单文件状态有界。

    完整错误类别一旦出现就记首错；未枚举的 sitai 错误等行结束再判，
    避免把尚未写完的已知财政警告误判。最终仍全量复核原始归档。
    """

    needles = tuple((marker, marker.encode()) for marker in ERROR_MARKERS)
    warning = OBSERVER_WARNING.encode()
    overlap = max(len(warning), *(len(needle) for _, needle in needles)) - 1
    mod_pattern = re.compile(rb"sitai", re.IGNORECASE)

    def __init__(self) -> None:
        self.failure: dict[str, str] | None = None
        self.states: dict[tuple[int, int], tuple[bytes, bool, bool, bytes]] = {}

    def feed(self, name: str, identity: tuple[int, int], chunk: bytes) -> None:
        if not name.startswith("error") or self.failure is not None:
            return
        tail, mod, benign, context = self.states.get(identity, (b"", False, False, b""))
        window = tail + chunk
        for marker, needle in self.needles:
            if needle in window:
                self._fail(marker, name, window[:512])
                return
        # 大多数行没有 Mod 标记；只定位标记所在行，避免逐行做十次 Python 搜索。
        first_end = window.find(b"\n")
        if mod and first_end >= 0 and not (benign or self.warning in window[:first_end]):
            self._fail("Mod error", name, context)
            return
        previous_end = -1
        for match in self.mod_pattern.finditer(window):
            if match.start() <= previous_end:
                continue
            start = window.rfind(b"\n", 0, match.start()) + 1
            end = window.find(b"\n", match.start())
            if end < 0:
                break
            previous_end = end
            if self.warning not in window[start:end] and not (start == 0 and benign):
                self._fail("Mod error", name, window[start : min(end, start + 512)])
                return
        start = window.rfind(b"\n") + 1
        remaining = window[start:]
        self.states[identity] = (
            remaining[-self.overlap :],
            (mod if start == 0 else False) or self.mod_pattern.search(remaining) is not None,
            (benign if start == 0 else False) or self.warning in remaining,
            (context + chunk)[:512] if start == 0 else remaining[:512],
        )

    def _fail(self, kind: str, name: str, context: bytes) -> None:
        self.failure = {
            "kind": kind,
            "log": name,
            "context": context.decode("utf-8", errors="replace"),
        }


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
        self.guard = LiveLogGuard()

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
                                self.guard.feed(path.name, identity, chunk)
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
    with temporary_file(path) as temporary:
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
    # 原版新局会在规则列表首位保留一个空占位，随后跟着一串有效规则；
    # 只有整个列表确实只有空字符串时，才是不可重放的空规则引用。
    if re.search(rb'settings\s*=\s*\{\s*""\s*\}', header):
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
    path: Path,
    *,
    earliest: float,
    original_sha256: str | None = None,
    timeout: float = 60,
    check: Callable[[], None] | None = None,
) -> dict[str, str]:
    """等本局自动存档写完；不把旧存档或写到一半的文件当检查点。"""
    deadline = time.monotonic() + timeout
    previous: tuple[int, int] | None = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        if check is not None:
            check()
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
        plain_path(userdir)
        plain_path(evidence)
        userdir, evidence = userdir.resolve(), evidence.resolve()
        self.userdir = userdir
        self.evidence = evidence
        self.content = userdir / "content_load.json"
        self.original: bytes | None = None
        self.config_claimed = False
        self.claims: list[tuple[Path, Path | None]] = []
        self.state_files: dict[Path, Path | None] = {}
        self.claim_info: dict[str, dict[str, Any]] = {}
        self.journal = evidence / "deployment.json"
        self.active = userdir / ".sitai-active-deployment.json"
        self.original_digest: str | None = None
        token = hashlib.sha256(str(evidence).encode("utf-8")).hexdigest()[:16]
        self.recovery_root = userdir / ".sitai-recovery" / token
        self._published: str | None = None

    def _persist(self) -> None:
        """所有外部副作用前先发布可独立重建的意图。调用方持有 RunLock。"""
        plain_path(self.active)
        pending = self.config_claimed or bool(self.claims) or bool(self.state_files)
        value = {
            "schema": 1,
            "userdir": str(self.userdir.resolve()),
            "evidence": str(self.evidence.resolve()),
            "pending": pending,
            "config_claimed": self.config_claimed,
            "original_digest": self.original_digest,
            "state_files": {str(p): str(b) if b else None for p, b in self.state_files.items()},
            "claims": [[str(p), str(b) if b else None] for p, b in self.claims],
            "claim_info": self.claim_info,
        }
        serialized = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if serialized != self._published:
            durable_json(self.journal, value)
            self._published = serialized
        if pending:
            if self.active.exists():
                active = json.loads(self.active.read_text(encoding="utf-8"))
                if active.get("evidence") != str(self.evidence.resolve()):
                    raise RuntimeError("存在尚未恢复的部署，拒绝覆盖恢复指针")
            else:
                durable_json(self.active, {"schema": 1, "evidence": str(self.evidence.resolve())})
        elif self.active.exists():
            active = json.loads(self.active.read_text(encoding="utf-8"))
            if active.get("evidence") == str(self.evidence.resolve()):
                self.active.unlink()

    @classmethod
    def load(cls, userdir: Path, evidence: Path) -> Deployment:
        """从磁盘重建，不推测 PID 所属、不杀进程、不拼接中断的运行。"""
        plain_path(userdir)
        plain_path(evidence)
        result = cls(userdir, evidence)
        plain_path(result.journal)
        value = json.loads(result.journal.read_text(encoding="utf-8"))
        if (
            value.get("schema") != 1
            or value.get("userdir") != str(userdir.resolve())
            or value.get("evidence") != str(evidence.resolve())
        ):
            raise ValueError("部署记录身份或版本不符")
        result.config_claimed = value["config_claimed"]
        result.original_digest = value["original_digest"]
        if result.original_digest is not None:
            original_backup = evidence / "content_load.original.backup"
            if file_sha(original_backup) != result.original_digest:
                raise ValueError("配置原件备份指纹不符")
            result.original = original_backup.read_bytes()
        for target, backup_name in value["state_files"].items():
            path = Path(target)
            plain_path(path)
            if not path.resolve().is_relative_to(userdir.resolve()):
                raise ValueError("状态恢复路径越界")
            backup = Path(backup_name) if backup_name is not None else None
            if backup is not None:
                plain_path(backup)
                if backup.parent.resolve() != (evidence.parent / "original-state").resolve():
                    raise ValueError("状态备份路径越界")
                if file_sha(backup) != backup.name:
                    raise ValueError("状态备份指纹不符")
            result.state_files[path] = backup
        for target, backup_name in value["claims"]:
            dest = Path(target)
            plain_path(dest)
            if (
                dest.resolve() != (userdir / "save games").resolve()
                and dest.parent.resolve() != (userdir / "mod").resolve()
            ):
                raise ValueError("目录恢复路径越界")
            saved = Path(backup_name) if backup_name is not None else None
            if saved is not None:
                plain_path(saved)
                if not (
                    saved.resolve() == (result.recovery_root / "original-save-directory").resolve()
                    or (
                        saved.parent == dest.parent
                        and saved.name.startswith(dest.name + ".sitai-backup")
                    )
                ):
                    raise ValueError("目录备份路径越界")
            info = value["claim_info"][target]
            archive = Path(info["archive"])
            plain_path(archive)
            if archive.parent.resolve() != (result.recovery_root / "recovered-output").resolve():
                raise ValueError("运行输出归档路径越界")
            result.claims.append((dest, saved))
            result.claim_info[str(dest)] = info
        return result

    @classmethod
    def recover_pending(cls, userdir: Path) -> None:
        """调用方先持有运行锁并证明没有游戏进程，失败阻断下一次部署。"""
        active = userdir / ".sitai-active-deployment.json"
        plain_path(active)
        if not active.exists():
            return
        value = json.loads(active.read_text(encoding="utf-8"))
        if value.get("schema") != 1:
            raise ValueError("恢复指针版本不符")
        deployment = cls.load(userdir, Path(value["evidence"]))
        errors = deployment.restore()
        durable_json(
            deployment.evidence / "recovery-result.json",
            {
                "schema": 1,
                "recovered": not errors,
                "errors": errors,
                "limits": "Interrupted sessions are not complete runs; logs are not stitched.",
            },
        )
        if errors:
            raise RuntimeError(f"上次部署恢复失败，拒绝启动新局：{errors}")

    def _claim(self, dest: Path, saved: Path | None) -> None:
        original = tree_digest(dest) if saved is not None else None
        self.claims.append((dest, saved))
        token = hashlib.sha256(str(dest.resolve()).encode("utf-8")).hexdigest()[:16]
        self.claim_info[str(dest)] = {
            "original": original,
            "phase": "intent",
            "archive": str(self.recovery_root / "recovered-output" / token),
        }
        self._persist()

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
        plain_path(backup_root)
        backup_root.mkdir(parents=True, exist_ok=True)
        for path in paths:
            plain_path(path)
            if not path.is_file():
                self.state_files[path] = None
                continue
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            backup = backup_root / digest
            plain_path(backup)
            if not backup.exists():
                temp = backup.with_suffix(".tmp")
                plain_path(temp)
                shutil.copy2(path, temp)
                temp.replace(backup)
            with backup.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise OSError(f"用户状态备份校验失败：{backup}")
            self.state_files[path] = backup
        # 此前只创建副本，尚未移动或改写原件。一次发布完整恢复意图。
        self._persist()

    def isolate_saves(self) -> None:
        """隔离菜单会扫描的旧存档，结束时整体归还，不修改存档字节。"""
        saves = self.userdir / "save games"
        if any(path.is_symlink() for path in (saves, *saves.parents)):
            raise ValueError("存档目录不允许符号链接")
        backup = self.recovery_root / "original-save-directory"
        if backup.exists():
            raise ValueError("存档目录备份已存在，拒绝覆盖")
        if saves.exists():
            self._claim(saves, backup)
            move_directory(saves, backup)
        else:
            self._claim(saves, None)
        self.claim_info[str(saves)]["phase"] = "moved"
        self._persist()
        saves.mkdir(parents=True)
        write_json(
            self.evidence / "state-backups.json",
            {str(p): str(saved) if saved else None for p, saved in self.state_files.items()},
        )

    def deploy(self, sources: Mapping[str, Path]) -> list[Path]:
        self.evidence.mkdir(parents=True, exist_ok=True)
        plain_path(self.content)
        self.original = self.content.read_bytes() if self.content.exists() else None
        original = json.loads(self.original.decode("utf-8-sig")) if self.original else {}
        if self.original is not None:
            plain_path(self.evidence / "content_load.original.backup")
            (self.evidence / "content_load.original.backup").write_bytes(self.original)
            self.original_digest = file_sha(self.evidence / "content_load.original.backup")
            if self.original_digest != hashlib.sha256(self.original).hexdigest():
                raise OSError("配置原件备份校验失败")
        self.config_claimed = True
        self._persist()
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
            self._claim(dest, saved)
            if saved is not None:
                move_directory(dest, saved)
            self.claim_info[str(dest)]["phase"] = "moved"
            self._persist()
            deploy_tree(source, dest)
            self.claim_info[str(dest)]["phase"] = "deployed"
            self._persist()
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
            self._persist()
            with temporary_file(target) as temp:
                shutil.copy2(source, temp)
                if file_sha(temp) != digest:
                    raise OSError("检查点副本指纹不符")
                temp.replace(target)
        return target.name

    def restore(self) -> list[str]:
        errors: list[str] = []
        failed_state: set[Path] = set()
        for path, backup in list(self.state_files.items()):
            try:
                plain_path(path)
                if backup is None and not path.exists():
                    del self.state_files[path]
                    continue
                self._persist()
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    if file_sha(backup) != backup.name:
                        raise OSError(f"用户状态备份指纹不符：{backup}")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with temporary_file(path) as temp:
                        shutil.copy2(backup, temp)
                        temp.replace(path)
                    if file_sha(path) != backup.name:
                        raise OSError(f"恢复后的用户状态指纹不符：{path}")
                del self.state_files[path]
                self._persist()
            except (OSError, ValueError) as exc:
                failed_state.add(path)
                errors.append(f"恢复用户状态 {path}：{exc}")
        if self.config_claimed:
            try:
                plain_path(self.content)
                self._persist()
                if self.original is None:
                    self.content.unlink(missing_ok=True)
                else:
                    if (
                        file_sha(self.evidence / "content_load.original.backup")
                        != self.original_digest
                    ):
                        raise RuntimeError("配置原件备份指纹不符")
                    with temporary_file(self.content) as temp:
                        temp.write_bytes(self.original)
                        temp.replace(self.content)
                    if self.content.read_bytes() != self.original:
                        raise RuntimeError("配置字节恢复校验失败")
                self.config_claimed = False
                self._persist()
            except (OSError, ValueError, RuntimeError) as exc:
                errors.append(f"恢复 {self.content}：{exc}")
        for dest, saved in reversed(self.claims.copy()):
            try:
                plain_path(dest)
                if any(path.is_relative_to(dest) for path in (*self.state_files, *failed_state)):
                    raise OSError("子文件恢复未完成，保留隔离目录和原件备份")
                info = self.claim_info[str(dest)]
                archive = Path(info["archive"])
                plain_path(archive)
                original_present = dest.exists() and tree_digest(dest) == info["original"]
                # 中断在移动之前或恢复原件之后：只接受完整原件，不能删除它。
                if not (original_present and info["phase"] in {"intent", "restoring"}):
                    if saved is not None:
                        if not saved.exists():
                            raise FileNotFoundError(
                                f"原件备份缺失，保留目标且拒绝重复清理：{saved}"
                            )
                        if tree_digest(saved) != info["original"]:
                            raise OSError(f"原件备份指纹不符，保留现场：{saved}")
                    info["phase"] = "restoring"
                    self._persist()
                    if dest.exists():
                        if archive.exists():
                            raise OSError(f"运行输出归档已存在且目标仍有内容，拒绝覆盖：{archive}")
                        archive.parent.mkdir(parents=True, exist_ok=True)
                        move_directory(dest, archive)
                    if saved is not None:
                        move_directory(saved, dest)
                        if tree_digest(dest) != info["original"]:
                            raise OSError(f"恢复目录指纹不符：{dest}")
                self.claims.remove((dest, saved))
                self._persist()
            except (OSError, ValueError) as exc:
                errors.append(f"恢复 {dest}（备份 {saved}）：{exc}")
        if not errors:
            self._persist()
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
                        if OBSERVER_WARNING in line:
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
    experiment: RunRequest | None = None,
    prior_failure_reports: tuple[Path, ...] = (),
) -> dict[str, object]:
    """运行隔离观察者局，成功与失败都保留不可覆盖的原始证据。"""
    if not math.isfinite(months) or months <= 0:
        raise ValueError("months 必须为有限正数")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout 必须为有限正数")
    if not sources or any(not path.is_dir() for path in sources.values()):
        raise ValueError("实验必须提供存在的 mod 源目录")
    if prior_failure_reports and experiment is None:
        raise ValueError("导入历史失败必须有冻结实验身份")
    with RunLock():
        ga.assert_no_game_running()
        Deployment.recover_pending(config.USERDIR)
        evidence = ga.unused_path(output / ga.archive_stamp(), stamp=ga.archive_stamp())
        evidence.mkdir(parents=True)
        deployment = Deployment(config.USERDIR, evidence)
        timings = StageTimings()
        source_hashes = timings.call(
            "input_fingerprints", lambda: {name: hashes(path) for name, path in sources.items()}
        )
        game_version = config.game_version()
        report: dict[str, object] = {
            "evidence": str(evidence),
            "deployment_journal": str(deployment.journal),
            "recovery_root": str(deployment.recovery_root),
            "game_version": game_version,
            "months": months,
            "source_hashes": source_hashes,
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
        ledger: ExperimentLedger | None = None
        run_id: str | None = None
        checkpoint: dict[str, Any] | None = None
        logs_isolated = False
        session_requested = False

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

        def check_health() -> None:
            failure = capture.guard.failure
            if failure is not None:
                report["early_stop"] = {
                    **failure,
                    "seconds": time.monotonic() - started,
                    "tick": ga.tick_mark().tick,
                    "phase": phase,
                }
                raise RuntimeError(f"实时错误门禁：{failure['kind']} ({failure['log']})")
            if capture.errors or monitor_errors:
                raise RuntimeError("实时证据采集失败，停止推进并保留现场")

        try:
            if load_save is not None:
                expected_version = config.game_version().get("caligula_branch", "").split("/")[-1]
                checkpoint = timings.call(
                    "checkpoint_preflight",
                    checkpoint_catalog.inspect,
                    load_save,
                    expected_version=expected_version,
                    allow_save_upgrade=allow_save_upgrade,
                )
                preflight = checkpoint_catalog.preflight(
                    checkpoint,
                    purpose=experiment.purpose if experiment else "safety",
                    months=months,
                )
                report["checkpoint_preflight"] = checkpoint
                report["experiment_preflight"] = preflight
                write_json(
                    evidence / "preflight.json", {"checkpoint": checkpoint, "decision": preflight}
                )
                if not preflight["allowed"]:
                    raise ValueError(f"检查点预检拒绝：{preflight['reasons']}")
            if experiment is not None:
                experiment.limits()
                if checkpoint is None or months > experiment.max_months:
                    raise ValueError("有预算实验必须提供检查点且不得超过冻结月份")
                available = psutil.virtual_memory().available / 1024**2
                report["available_memory_mib"] = available
                if available < experiment.min_available_mib:
                    raise RuntimeError("可用内存不足预登记资源预算，暂不启动游戏")
                ledger = ExperimentLedger(config.USERDIR / ".sitai-experiments.sqlite3")
                ledger.interrupt_pending()
                for path in prior_failure_reports:
                    ledger.import_prior_failure(
                        experiment,
                        path,
                        checkpoint_sha256=checkpoint["sha256"],
                        game_version=game_version,
                    )
                used = ledger.used_arms(experiment.plan_id, experiment.scene_id)
                preflight = checkpoint_catalog.preflight(
                    checkpoint, purpose=experiment.purpose, months=months, used_arms=used
                )
                report["experiment_preflight"] = preflight
                write_json(
                    evidence / "preflight.json", {"checkpoint": checkpoint, "decision": preflight}
                )
                if not preflight["allowed"]:
                    raise ValueError(f"实验预算预检拒绝：{preflight['reasons']}")
                run_id = ledger.reserve(
                    experiment,
                    manifest={
                        "checkpoint": checkpoint["sha256"],
                        "sources": source_hashes,
                        "probe_sources": {
                            k: v
                            for k, v in source_hashes.items()
                            if k != "sitai_decision_candidate"
                        },
                        "environment": {
                            "game": report["game_version"],
                            "tools": {
                                p.name: file_sha(p)
                                for p in sorted(Path(__file__).parent.glob("*.py"))
                            },
                        },
                        "months": months,
                        "timeout": timeout,
                        "profile": profile,
                        "allow_save_upgrade": allow_save_upgrade,
                        "keep_save": keep_save,
                        "prior_failure_reports": {
                            str(p.resolve()): file_sha(p) for p in prior_failure_reports
                        },
                    },
                    evidence=evidence,
                )
                report["experiment"] = {
                    "run_id": run_id,
                    "plan_id": experiment.plan_id,
                    "scene_id": experiment.scene_id,
                    "arm": experiment.arm,
                    "pair": experiment.pair,
                    "purpose": experiment.purpose,
                    "limits": experiment.limits(),
                    "manifest_sha256": ledger.manifest_sha256(run_id),
                }
                write_json(evidence / "task.json", report["experiment"])
            frozen_sources = {}
            for name, source in sources.items():
                if Path(name).name != name or name in {"", ".", ".."}:
                    raise ValueError(f"mod目录名无效：{name}")
                if any(p.is_symlink() for p in (source, *source.rglob("*"))):
                    raise ValueError(f"实验源不允许符号链接：{source}")
                if source.resolve() in evidence.resolve().parents:
                    raise ValueError("证据目录不能放在实验源内")
                timings.call("source_archive", shutil.copytree, source, evidence / "sources" / name)
                frozen = evidence / "sources" / name
                if hashes(frozen) != source_hashes[name]:
                    raise ValueError("源在内容冻结后发生变化，拒绝部署")
                frozen_sources[name] = frozen
            timings.call("user_state_backup", deployment.snapshot_state)
            timings.call("save_isolation", deployment.isolate_saves)
            # 仅本局用干净预设；原件已按字节备份，收尾恢复。
            (config.USERDIR / "player/game_rules/presets.txt").unlink(missing_ok=True)
            report["quarantined"] = ga.quarantine_logs(evidence / "previous-logs")
            if ga.LAST_QUARANTINE_ERRORS:
                raise RuntimeError(f"日志隔离失败：{ga.LAST_QUARANTINE_ERRORS}")
            logs_isolated = True
            destinations = timings.call("deployment", deployment.deploy, frozen_sources)
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
                staged_name = timings.call("checkpoint_staging", deployment.stage_save, source_save)
                save_name = Path(staged_name).stem
                with source_save.open("rb") as stream:
                    save_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
                if checkpoint is not None and save_sha256 != checkpoint["sha256"]:
                    raise ValueError("检查点在预检后发生内容变化，拒绝启动")
                report["loaded_save"] = {
                    "header": header,
                    "name": staged_name,
                    "sha256": save_sha256,
                    "upgrade_requested": allow_save_upgrade,
                }
            session_requested = True
            session = timings.call(
                "startup_load",
                ga.run_session,
                scripted_tests=False,
                force=True,
                save_name=save_name,
            )
            report["session"] = session.as_dict()
            check_health()
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
            progress = timings.call(
                "simulation",
                wait_progress,
                months,
                timeout=timeout,
                start_tick=activation_tick,
                sample=check_health,
            )
            progress["activation_tick"] = activation_tick
            progress["activation_source"] = (
                "session.advance.after" if activation_tick else "wait_progress baseline"
            )
            report["progress"] = progress
            if keep_save:
                end = ga.tick_day(str(progress["end"]))
                assert end is not None
                auto = config.USERDIR / "save games/autosave.v3"
                original = deployment.state_files.get(auto)
                report["checkpoint_ready"] = timings.call(
                    "checkpoint_wait",
                    wait_save_ready,
                    auto,
                    earliest=end,
                    original_sha256=original.name if original else None,
                    check=check_health,
                )
                report["checkpoint_scope"] = "within 31 game days of completed window end"
                report["after_checkpoint_wait"] = ga.tick_mark().tick
            check_health()
            if profiler is not None:
                phase = "profiling"
                report["ticktask"] = timings.call("profiling", profiler.finish, session)
        except Exception as exc:
            report["failure"] = f"{type(exc).__name__}: {exc}"
        except BaseException:
            report["failure"] = "实机实验被中断"
            raise
        finally:
            if session is not None:
                try:
                    report["shutdown"] = timings.call("shutdown", graceful_stop, session.hwnd)
                except Exception as exc:
                    cleanup_errors.append(
                        f"正常退出失败，执行强制收尾：{type(exc).__name__}: {exc}"
                    )
            try:
                timings.call("forced_shutdown", ga.kill_owned_game)
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
                elif logs_isolated:
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
                if name == "归档本局日志" and not logs_isolated:
                    continue
                if not stopped and name != "恢复原窗口":
                    continue
                try:
                    result = timings.call(name, action)
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
                "error_stop": "Incremental error-log guard; simulation checks every 5s, save wait every 1s; blocking startup is checked on return. Final full-log validation remains mandatory.",
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
            report["session_requested"] = session_requested
            report["logs_isolated"] = logs_isolated
            if analyze is not None and session_requested:
                try:
                    report["analysis"] = timings.call("analysis", analyze, evidence / "logs")
                except Exception as exc:
                    report.setdefault("failure", f"日志分析失败：{exc}")
            report["ok"] = not report.get("failure")
            report["stage_timings"] = timings.intervals
            report["pipeline_wall_seconds"] = time.monotonic() - timings.started
            report["timing_scope"] = (
                "stage intervals include input hashes through analysis; overlaps are not summed; "
                "legacy wall_seconds excludes initial hashes and analysis; report writes excluded"
            )
            write_json(evidence / "report.json", report)
            if ledger is not None and run_id is not None:
                ledger.finish(run_id, report, report_sha256=file_sha(evidence / "report.json"))
            write_json(output / "latest.json", report)
        return report
