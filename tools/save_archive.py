"""后台按游戏日期归档 Victoria 3 自动存档。

这个工具只读取游戏已经写出的存档，不启动、暂停或控制游戏窗口。它从存档头读取
``game_date``，为指定的游戏日期保留最接近的月份；复制前要求文件连续两次检查保持
稳定，复制后以原子替换和大小校验落盘。归档目录应放在 ``tools/out`` 等被忽略的
位置，避免把本机运行态或百兆级存档提交进仓库。

运行参数与三平台说明见 ``tools/README.md``；``--help`` 列出全部选项。

程序会在全部目标归档完成、游戏进程退出或收到停止信号后写入 ``status.json``
并退出。``events.jsonl`` 记录每次候选更新、完成和跳过的原因。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass
from datetime import date as calendar_date
from pathlib import Path
from typing import Any

import psutil

DATE_RE = re.compile(rb"(?m)^\s*game_date\s*=\s*([^\s}]+)")
CAMPAIGN_RE = re.compile(rb'(?m)^playthrough_id\s*=\s*"([^"\r\n]+)"')
DEFAULT_TARGETS = ("1836.1.1", "1856.1.1", "1876.1.1", "1896.1.1", "1916.1.1", "1936.1.1")
DEFAULT_POLL_SECONDS = 3.0
DEFAULT_STABLE_SECONDS = 3.0
DEFAULT_WINDOW_MONTHS = 12
READ_HEAD_BYTES = 256 * 1024
COPY_BUFFER_BYTES = 8 * 1024 * 1024


def parse_date(value: str) -> tuple[int, int, int]:
    """解析 ``YYYY.M.D``，拒绝不完整或不可能的日期。"""

    parts = value.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"游戏日期必须是 YYYY.M.D：{value!r}")
    try:
        year, month, day = (int(item) for item in parts)
    except ValueError as exc:
        raise ValueError(f"游戏日期必须是数字：{value!r}") from exc
    try:
        calendar_date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"游戏日期超出范围：{value!r}") from exc
    return year, month, day


def month_number(date: tuple[int, int, int]) -> int:
    """将游戏日期转换为可比较的月份序号。"""

    return date[0] * 12 + date[1] - 1


def read_game_metadata(path: Path) -> tuple[str, str | None] | None:
    """只读取文本存档头中的日期和局标识；压缩格式需显式指定基线。"""

    with path.open("rb") as handle:
        data = handle.read(READ_HEAD_BYTES)
    if not data.startswith(b"SAV") or b"\nmeta_data={" not in data[:128]:
        return None
    match = DATE_RE.search(data)
    if not match:
        return None
    value = match.group(1).decode("ascii", errors="strict")
    parse_date(value)
    campaign = CAMPAIGN_RE.search(data)
    return value, campaign[1].decode("ascii") if campaign else None


def read_game_date(path: Path) -> str | None:
    """读取游戏日期，不解析百兆级正文。"""

    metadata = read_game_metadata(path)
    return metadata[0] if metadata else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(COPY_BUFFER_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_is_better(actual: str, current: str | None, target: str) -> bool:
    """判断新日期是否更接近目标；相同时优先较早的实际日期。"""

    target_month = month_number(parse_date(target))
    actual_month = month_number(parse_date(actual))
    if current is None:
        return True
    current_month = month_number(parse_date(current))
    target_day = calendar_date(*parse_date(target)).toordinal()
    actual_key = (
        abs(actual_month - target_month),
        abs(calendar_date(*parse_date(actual)).toordinal() - target_day),
        parse_date(actual),
    )
    current_key = (
        abs(current_month - target_month),
        abs(calendar_date(*parse_date(current)).toordinal() - target_day),
        parse_date(current),
    )
    return actual_key < current_key


@dataclass(frozen=True)
class FileSignature:
    size: int
    mtime_ns: int

    @classmethod
    def read(cls, path: Path) -> FileSignature:
        stat = path.stat()
        return cls(stat.st_size, stat.st_mtime_ns)


class SaveArchive:
    """维护目标日期、稳定性和候选副本。"""

    def __init__(
        self,
        userdir: Path,
        output: Path,
        targets: tuple[str, ...],
        *,
        pid: int | None = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        stable_seconds: float = DEFAULT_STABLE_SECONDS,
        window_months: int = DEFAULT_WINDOW_MONTHS,
        baselines: tuple[tuple[str, Path], ...] = (),
        cloud_dirs: tuple[Path, ...] = (),
        playthrough_id: str | None = None,
    ) -> None:
        self.userdir = userdir.expanduser().resolve()
        self.output = output.expanduser().resolve()
        self.cloud_dirs = tuple(path.expanduser().resolve() for path in cloud_dirs)
        if any(
            self.output == directory or directory in self.output.parents
            for directory in (self.userdir, *self.cloud_dirs)
        ):
            raise ValueError("归档输出不能位于游戏用户目录或云存档目录中")
        if self.output.exists():
            raise ValueError("归档输出必须是新目录，以免覆盖已有存档或状态")
        self.targets = tuple(dict.fromkeys(targets))
        if not self.targets:
            raise ValueError("至少需要一个目标日期")
        for target in self.targets:
            parse_date(target)
        self.target_months = {target: month_number(parse_date(target)) for target in self.targets}
        self.pid = pid
        self.poll_seconds = max(0.5, poll_seconds)
        self.stable_seconds = max(0.0, stable_seconds)
        self.window_months = max(0, window_months)
        self.playthrough_id = playthrough_id
        self.process_started_at = psutil.Process(pid).create_time() if pid is not None else None
        self.started_at = time.time()
        self.stop_requested = False
        self.signatures: dict[str, tuple[FileSignature, float]] = {}
        self.state: dict[str, dict[str, Any]] = {
            target: {"target": target, "status": "pending", "candidate": None}
            for target in self.targets
        }
        self.events_path = self.output / "events.jsonl"
        self.candidate_dir = self.output / "candidates"
        self.candidate_dir.mkdir(parents=True)
        self._write_status("running")
        for target, source in baselines:
            self._install_baseline(target, source)
        self._write_status("running")

    @property
    def save_dirs(self) -> tuple[Path, ...]:
        dirs = [self.userdir / "save games", *self.cloud_dirs]
        return tuple(dict.fromkeys(path for path in dirs if path.is_dir()))

    def _event(self, kind: str, **data: Any) -> None:
        payload = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, **data}
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_status(self, status: str) -> None:
        payload = {
            "status": status,
            "started_at": self.started_at,
            "updated_at": time.time(),
            "pid": self.pid,
            "playthrough_id": self.playthrough_id,
            "targets": self.state,
        }
        temporary = self.output / "status.json.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(self.output / "status.json")

    def _stable(self, path: Path) -> FileSignature | None:
        try:
            signature = FileSignature.read(path)
        except OSError:
            self.signatures.pop(str(path), None)
            return None
        now = time.monotonic()
        previous = self.signatures.get(str(path))
        if previous is None or previous[0] != signature:
            self.signatures[str(path)] = (signature, now)
            return None
        if now - previous[1] < self.stable_seconds:
            return None
        return signature

    def _copy_candidate(
        self, source: Path, target: str, actual: str, signature: FileSignature
    ) -> Path | None:
        destination = (
            self.candidate_dir / f"{target.replace('.', '_')}--{actual.replace('.', '_')}.v3"
        )
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            if FileSignature.read(source) != signature or read_game_metadata(source) != (
                actual,
                self.playthrough_id,
            ):
                raise OSError("存档在读取日期后发生变化")
            copied_digest = hashlib.sha256()
            with source.open("rb") as source_handle, temporary.open("wb") as dest_handle:
                for chunk in iter(lambda: source_handle.read(COPY_BUFFER_BYTES), b""):
                    copied_digest.update(chunk)
                    dest_handle.write(chunk)
                dest_handle.flush()
                os.fsync(dest_handle.fileno())
            after = FileSignature.read(source)
            if after != signature or temporary.stat().st_size != signature.size:
                temporary.unlink(missing_ok=True)
                self._event("copy_retry", target=target, actual=actual, reason="source_changed")
                return None
            digest = sha256(temporary)
            if digest != copied_digest.hexdigest() or read_game_metadata(temporary) != (
                actual,
                self.playthrough_id,
            ):
                raise OSError("副本内容或日期校验失败")
            temporary.replace(destination)
        except (OSError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            self._event("copy_retry", target=target, actual=actual, reason=repr(exc))
            return None
        old = self.state[target].get("candidate")
        if old and old.get("path") and old["path"] != destination.name:
            (self.candidate_dir / old["path"]).unlink(missing_ok=True)
        self.state[target]["candidate"] = {
            "path": destination.name,
            "actual_date": actual,
            "source": str(source),
            "size": signature.size,
            "sha256": digest,
        }
        self._event("candidate", target=target, actual=actual, path=destination.name, sha256=digest)
        return destination

    def _install_baseline(self, target: str, source: Path) -> None:
        """复制用户明确指定的开局档；允许它是压缩的 Steam 云存档。"""

        if target not in self.state:
            raise ValueError(f"基线目标未出现在 --target 中：{target}")
        source = source.expanduser().resolve()
        signature = FileSignature.read(source)
        destination = self.candidate_dir / f"{target.replace('.', '_')}--baseline{source.suffix}"
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            digest = sha256(source)
            with source.open("rb") as source_handle, temporary.open("wb") as dest_handle:
                shutil.copyfileobj(source_handle, dest_handle, COPY_BUFFER_BYTES)
                dest_handle.flush()
                os.fsync(dest_handle.fileno())
            if (
                FileSignature.read(source) != signature
                or temporary.stat().st_size != signature.size
                or sha256(temporary) != digest
            ):
                raise OSError(f"基线存档在复制期间发生变化或校验失败：{source}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        self.state[target]["candidate"] = {
            "path": destination.name,
            "actual_date": target,
            "source": str(source),
            "size": signature.size,
            "sha256": digest,
            "format": "原始用户指定存档（可能为 Steam 压缩格式）",
        }
        self.state[target]["status"] = "complete"
        self.state[target]["selected_date"] = target
        self._event(
            "baseline", target=target, source=str(source), path=destination.name, sha256=digest
        )

    def _observe_file(self, path: Path, signature: FileSignature, actual: str) -> None:
        actual_month = month_number(parse_date(actual))
        for target, target_month in self.target_months.items():
            row = self.state[target]
            if row["status"] != "pending":
                continue
            distance = abs(actual_month - target_month)
            if distance > self.window_months:
                continue
            current = (row.get("candidate") or {}).get("actual_date")
            if not candidate_is_better(actual, current, target):
                continue
            self._copy_candidate(path, target, actual, signature)

    def _finalize_passed_targets(self, latest_month: int | None) -> None:
        if latest_month is None:
            return
        for target, target_month in self.target_months.items():
            row = self.state[target]
            if row["status"] != "pending":
                continue
            candidate = row.get("candidate")
            exact = candidate is not None and parse_date(candidate["actual_date"]) == parse_date(
                target
            )
            window_passed = latest_month > target_month + self.window_months
            if candidate and (exact or window_passed):
                row["status"] = "complete"
                row["selected_date"] = candidate["actual_date"]
                self._event(
                    "complete",
                    target=target,
                    actual=candidate["actual_date"],
                    path=candidate["path"],
                )
            elif not candidate and window_passed:
                row["status"] = "unavailable"
                row["reason"] = "目标日期及允许窗口内没有稳定自动存档"
                self._event("unavailable", target=target, latest_month=latest_month)

    def poll(self) -> None:
        stable = []
        unsettled = False
        for directory in self.save_dirs:
            for path in sorted(directory.glob("*.v3")):
                signature = self._stable(path)
                if signature is None:
                    unsettled = True
                    continue
                try:
                    metadata = read_game_metadata(path)
                    if metadata and FileSignature.read(path) == signature:
                        stable.append((path, signature, *metadata))
                except (OSError, UnicodeError, ValueError):
                    continue
        if self.playthrough_id is None:
            local = [
                item
                for item in stable
                if item[0].parent == self.userdir / "save games"
                and item[0].name.startswith("autosave")
                and item[3]
            ]
            if local:
                self.playthrough_id = max(local, key=lambda item: item[1].mtime_ns)[3]
                self._event("campaign", playthrough_id=self.playthrough_id)
        latest_month = None
        for path, signature, actual, campaign in stable:
            if self.playthrough_id is None or campaign != self.playthrough_id:
                continue
            self._observe_file(path, signature, actual)
            latest_month = max(latest_month or 0, month_number(parse_date(actual)))
        if not unsettled:
            self._finalize_passed_targets(latest_month)
        self._write_status("running")

    def game_running(self) -> bool:
        if self.pid is None:
            return True
        try:
            process = psutil.Process(self.pid)
            return (
                process.is_running()
                and process.create_time() == self.process_started_at
                and process.name().lower() in {"victoria3.exe", "victoria3"}
            )
        except (psutil.Error, OSError):
            return False

    def run(self) -> int:
        self._event("start", targets=list(self.targets), save_dirs=[str(p) for p in self.save_dirs])
        status, code = "stopped", 130
        exit_deadline = None
        try:
            while not self.stop_requested:
                self.poll()
                if all(row["status"] in {"complete", "unavailable"} for row in self.state.values()):
                    success = all(row["status"] == "complete" for row in self.state.values())
                    status, code = (
                        ("complete", 0) if success else ("finished_with_missing_targets", 2)
                    )
                    break
                if self.pid is not None and not self.game_running():
                    # Let the last autosave finish its stability interval after
                    # process exit, then retain an explicitly approximate result.
                    if exit_deadline is None:
                        exit_deadline = time.monotonic() + self.stable_seconds + self.poll_seconds
                    if time.monotonic() >= exit_deadline:
                        self._finalize_passed_targets(10**9)
                        success = all(row["status"] == "complete" for row in self.state.values())
                        status, code = (
                            ("complete", 0) if success else ("game_exited_before_all_targets", 2)
                        )
                        self._event("stop", reason="game_exited")
                        break
                time.sleep(self.poll_seconds)
        except KeyboardInterrupt:
            self._event("stop", reason="keyboard_interrupt")
        except Exception as exc:
            status, code = "failed", 1
            self._event("error", reason=repr(exc))
            raise
        finally:
            self._write_status(status)
        return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--userdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", dest="targets", action="append", default=[])
    parser.add_argument("--pid", type=int)
    parser.add_argument(
        "--playthrough-id", help="限制为指定游戏局；默认从最新稳定本地 autosave 自动识别"
    )
    parser.add_argument(
        "--cloud-dir",
        action="append",
        default=[],
        type=Path,
        help="额外读取的 Steam 云存档目录；可重复传入，不会修改其中的文件",
    )
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--stable-seconds", type=float, default=DEFAULT_STABLE_SECONDS)
    parser.add_argument("--window-months", type=int, default=DEFAULT_WINDOW_MONTHS)
    parser.add_argument(
        "--baseline",
        action="append",
        default=[],
        metavar="DATE=PATH",
        help="复制一个用户明确指定的基线存档（可为压缩 Steam 存档）并视为已完成目标",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    targets = tuple(args.targets) or DEFAULT_TARGETS
    baselines: list[tuple[str, Path]] = []
    for item in args.baseline:
        target, separator, raw_path = item.partition("=")
        if not separator or not raw_path:
            raise SystemExit(f"--baseline 必须是 DATE=PATH：{item!r}")
        baselines.append((target, Path(raw_path)))
    collector = SaveArchive(
        args.userdir,
        args.output,
        targets,
        pid=args.pid,
        poll_seconds=args.poll_seconds,
        stable_seconds=args.stable_seconds,
        window_months=args.window_months,
        baselines=tuple(baselines),
        cloud_dirs=tuple(args.cloud_dir),
        playthrough_id=args.playthrough_id,
    )
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: setattr(collector, "stop_requested", True))
    return collector.run()


if __name__ == "__main__":
    raise SystemExit(main())
