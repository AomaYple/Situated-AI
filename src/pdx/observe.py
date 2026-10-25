"""Victoria 3 运行期证据采集和存档摘要。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .savegame import read_save as _read_structured_save

if TYPE_CHECKING:
    from collections.abc import Iterable

_VERSION_RE = re.compile(rb"(?<![A-Za-z0-9_])version\s*=\s*\"([^\"]+)\"")
_GAME_DATE_RE = re.compile(rb"(?<![A-Za-z0-9_])game_date\s*=\s*([^\s}]+)")
_MODS_RE = re.compile(rb"(?<![A-Za-z0-9_])mods\s*=\s*\{([^}]*)\}")
_DATE_RE = re.compile(rb"(?<![A-Za-z0-9_])date\s*=\s*([^\s}]+)")
_TICK_RE = re.compile(rb"(?<![A-Za-z0-9_])tick\s*=\s*([^\s}]+)")
_COUNTERS_RE = re.compile(rb"(?m)^\s*counters=\{(.*?)^\}", re.DOTALL)
_COUNTER_RE = re.compile(rb"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)=([-+]?\d+(?:\.\d+)?)\s*$")
_SITAI_RE = re.compile(rb"\b(sitai_[A-Za-z0-9_]+)\b")
_QUOTED_RE = re.compile(rb'"([^"\\]*(?:\\.[^"\\]*)*)"')
_COUNTRY_RE = re.compile(rb"(?m)^\tdefinition=\"([A-Z0-9_]+)\"\r?$")
_ENTRY_RE = re.compile(rb"(?m)^([0-9]+)=\{")


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").strip()


def _number(value: bytes) -> int | float | str:
    text = _decode(value)
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def _read_metadata_prefix(path: Path, *, limit: int = 64 * 1024 * 1024) -> bytes:
    marker = b"\nprovinces={"
    data = bytearray()
    total = 0
    with path.open("rb") as handle:
        while total < limit:
            chunk = handle.read(min(1024 * 1024, limit - total))
            if not chunk:
                break
            data.extend(chunk)
            total += len(chunk)
            at = data.find(marker)
            if at >= 0:
                return bytes(data[:at])
    return bytes(data)


def parse_save_metadata(path: Path) -> dict[str, Any]:
    """提取存档头、内部计数器、Mod 名称和 ``sitai_`` 变量。"""

    path = Path(path)
    prefix = _read_metadata_prefix(path)
    mods_match = _MODS_RE.search(prefix)
    counters: dict[str, int | float | str] = {}
    if match := _COUNTERS_RE.search(prefix):
        for item in _COUNTER_RE.finditer(match.group(1)):
            counters[item.group(1).decode("ascii")] = _number(item.group(2))
    return {
        "file": path.name,
        "version": _decode(m.group(1)) if (m := _VERSION_RE.search(prefix)) else None,
        "game_date": _decode(m.group(1)) if (m := _GAME_DATE_RE.search(prefix)) else None,
        "mods": [_decode(item) for item in _QUOTED_RE.findall(mods_match.group(1))]
        if mods_match
        else [],
        "date": _decode(m.group(1)) if (m := _DATE_RE.search(prefix)) else None,
        "tick": _number(m.group(1)) if (m := _TICK_RE.search(prefix)) else None,
        "counters": counters,
        "internal_counters": counters,
        "sitai_variables": sorted({m.group(1).decode("ascii") for m in _SITAI_RE.finditer(prefix)}),
        "metadata_complete": bool(re.search(rb"(?m)(?:^|\s)provinces\s*=\s*\{", prefix)),
    }


def read_save(path: Path, *, definitions: Iterable[str] = ("RUS", "NET")) -> dict[str, Any]:
    """读取完整文本存档，统一复用 ``pdx.savegame`` 的结构化解析器。"""

    return _read_structured_save(Path(path), definitions=tuple(definitions))


def _sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SaveCollector:
    """发现稳定写入的 autosave，并按内容签名去重。"""

    def __init__(
        self, save_dir: Path, *, archive_dir: Path | None = None, stable_seconds: float = 0.0
    ) -> None:
        self.save_dir = Path(save_dir)
        self.archive_dir = Path(archive_dir) if archive_dir else None
        self.stable_seconds = max(0.0, stable_seconds)
        self._candidates: dict[Path, tuple[int, int, str, float]] = {}
        self._emitted: set[tuple[int, int, str]] = set()

    def collect(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for path in sorted(self.save_dir.glob("autosave*.v3"), key=lambda p: p.name):
            try:
                stat = path.stat()
            except OSError:
                continue
            # The filesystem timestamp can have coarse resolution.  Include a
            # content digest so two same-sized saves written in one tick are
            # never collapsed into one evidence event.
            digest = _sha256(path)
            signature = (stat.st_size, stat.st_mtime_ns, digest)
            previous = self._candidates.get(path)
            now = time.monotonic()
            if previous is None or previous[:3] != signature:
                self._candidates[path] = (*signature, now)
                continue
            if self.stable_seconds > 0 and now - previous[3] < self.stable_seconds:
                continue
            if signature in self._emitted:
                continue
            try:
                summary = read_save(path)
            except (OSError, ValueError):
                try:
                    summary = {
                        "metadata": parse_save_metadata(path),
                        "countries": {},
                        "databases": {},
                    }
                except OSError:
                    continue
            event: dict[str, Any] = {
                "kind": "save",
                "path": path.name,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                **summary,
            }
            if self.archive_dir is not None:
                self.archive_dir.mkdir(parents=True, exist_ok=True)
                stamp = str(
                    event["metadata"].get("game_date")
                    or event["metadata"].get("tick")
                    or stat.st_mtime_ns
                )
                target = self.archive_dir / f"{path.stem}-{stamp}-{stat.st_mtime_ns}{path.suffix}"
                shutil.copy2(path, target)
                event["archive_path"] = target.name
                event["sha256"] = _sha256(target)
            self._emitted.add(signature)
            events.append(event)
        return events


class LogCollector:
    """以原始字节读取日志增量，正确处理截断和同大小替换。"""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self._state: dict[Path, tuple[int, int, int, str]] = {}

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def collect(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for path in sorted(self.log_dir.glob("*.log")):
            try:
                stat = path.stat()
                old_size, _old_mtime, offset, old_digest = self._state.get(path, (0, 0, 0, ""))
                digest = self._digest(path) if offset and stat.st_size == old_size else ""
                replaced = offset and stat.st_size == old_size and digest != old_digest
                if stat.st_size < offset or replaced:
                    offset = 0
                with path.open("rb") as handle:
                    handle.seek(offset)
                    data = handle.read()
                    new_offset = handle.tell()
                self._state[path] = (stat.st_size, stat.st_mtime_ns, new_offset, self._digest(path))
            except OSError:
                continue
            if data:
                events.append(
                    {
                        "path": path.name,
                        "offset": offset,
                        "data": data,
                        "text": data.decode("utf-8", errors="replace"),
                    }
                )
        return events


def _jsonable(record: dict[str, Any]) -> dict[str, Any]:
    return (
        {**record, "data": base64.b64encode(record["data"]).decode("ascii")}
        if isinstance(record.get("data"), bytes)
        else record
    )


class ObservationSession:
    def __init__(
        self,
        userdir: Path,
        output: Path,
        *,
        archive_saves: bool = False,
        stable_seconds: float = 0.0,
    ) -> None:
        self.userdir = Path(userdir).resolve()
        self.output = Path(output).resolve()
        if self.output == self.userdir or self.userdir in self.output.parents:
            raise ValueError("证据目录不能位于游戏用户目录内")
        if self.output.exists():
            raise ValueError("证据目录必须是尚未存在的新目录")
        self.output.mkdir(parents=True, exist_ok=True)
        self.saves = SaveCollector(
            self.userdir / "save games",
            archive_dir=self.output / "saves" if archive_saves else None,
            stable_seconds=stable_seconds,
        )
        self.logs = LogCollector(self.userdir / "logs")
        self.save_events: list[dict[str, Any]] = []
        self.log_events: list[dict[str, Any]] = []

    def poll(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        saves, logs = self.saves.collect(), self.logs.collect()
        self.save_events.extend(saves)
        self.log_events.extend(logs)
        if saves:
            with (self.output / "saves.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                for event in saves:
                    handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        if logs:
            root = self.output / "logs"
            root.mkdir(parents=True, exist_ok=True)
            with (self.output / "logs.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                for event in logs:
                    handle.write(
                        json.dumps(_jsonable(event), ensure_ascii=False, sort_keys=True) + "\n"
                    )
                    with (root / str(event["path"])).open("ab") as raw:
                        raw.write(event["data"])
        return saves, logs

    def finish(self) -> dict[str, Any]:
        report = build_report(self.save_events, self.log_events)
        _write_json(self.output / "report.json", report)
        (self.output / "report.md").write_text(
            render_report(report), encoding="utf-8", newline="\n"
        )
        return report


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _date_key(value: object) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in str(value).split(".")[:3])
        return (*parts, 0, 0, 0)[:3]  # type: ignore[return-value]
    except (TypeError, ValueError):
        return (0, 0, 0)


def build_report(
    save_events: list[dict[str, Any]], log_events: list[dict[str, Any]]
) -> dict[str, Any]:
    ordered = sorted(
        save_events,
        key=lambda event: (_date_key(event["metadata"].get("game_date")), event["mtime_ns"]),
    )
    first = ordered[0]["metadata"] if ordered else None
    last = ordered[-1]["metadata"] if ordered else None
    changes = []
    if len(ordered) >= 2:
        for tag in sorted(
            set(ordered[0].get("countries", {})) & set(ordered[-1].get("countries", {}))
        ):
            before, after = ordered[0]["countries"][tag], ordered[-1]["countries"][tag]
            country_changes = _flatten_changes(before, after)
            country_changes.sort(
                key=lambda item: (0 if item[0].startswith("budget.") else 1, item[0])
            )
            for field, before_value, after_value in country_changes:
                changes.append(
                    {
                        "country": tag,
                        "field": field,
                        "before": before_value,
                        "after": after_value,
                        # Keep a direct path entry for simple consumers while
                        # retaining the normalized fields for filtering.
                        field: {"before": before_value, "after": after_value},
                    }
                )
    return {
        "evidence": ["runtime", "snapshot", "inference"],
        "behavior_quality": "not_evaluated",
        "save_count": len(ordered),
        "log_chunk_count": len(log_events),
        "campaigns": [{"first_date": first.get("game_date"), "last_date": last.get("game_date")}]
        if first and last
        else [],
        "first_save": first,
        "last_save": last,
        "country_changes": changes,
        "error_lines_observed": sum(
            str(event.get("text", "")).count("\n")
            for event in log_events
            if event.get("path") == "error.log"
        ),
        "limits": [
            "存档差分描述状态变化，不证明 AI 决策因果。",
            "没有原版基线时，不比较 Mod 是否优于原版。",
        ],
    }


def _flatten_changes(
    before: object, after: object, prefix: str = ""
) -> list[tuple[str, object, object]]:
    if isinstance(before, dict) or isinstance(after, dict):
        left = before if isinstance(before, dict) else {}
        right = after if isinstance(after, dict) else {}
        changes: list[tuple[str, object, object]] = []
        for key in sorted(set(left) | set(right)):
            if key in {"id", "definition"}:
                continue
            field = f"{prefix}.{key}" if prefix else key
            changes.extend(_flatten_changes(left.get(key), right.get(key), field))
        return changes
    return [(prefix, before, after)] if before != after else []


def render_report(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Situated AI 运行观察报告",
            "",
            f"- 稳定存档：{report['save_count']}",
            f"- 日志增量块：{report['log_chunk_count']}",
            f"- 行为质量：{report['behavior_quality']}",
            "",
            "## 边界",
            "",
            *[f"- {item}" for item in report["limits"]],
            "",
        ]
    )
