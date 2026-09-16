"""Steam Workshop / 本地 mod 的分析。

取代原先靠临时命令手工统计的做法。回答这些问题：

* 每个 mod 改了什么（顶层目录、文件数、体积）
* 哪些 mod 覆盖了原版文件（相对路径与原版重名）
* 哪些 mod 新增了自有文件
* 功能前缀（``INJECT:`` / ``REPLACE:`` 等）的总体使用情况
* mod 元数据（``.metadata/metadata.json``）

注意「零路径重叠」这条结论对本机 23 个 mod 成立，但**不是普遍规律** ——
它只是说明这些 mod 恰好都用新增文件而非覆盖。分析工具要如实报告，
不能把这个观察当成前提。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import GAME, LOCAL_MODS, WORKSHOP
from .cache import parse_cached
from .scan import walk_files

METADATA_REL = Path(".metadata") / "metadata.json"


@dataclass(slots=True)
class ModInfo:
    """一个 mod 的画像。"""

    root: Path
    steam_id: str = ""
    name: str = ""
    version: str = ""
    supported_game_version: str = ""
    description: str = ""
    multiplayer_synced: bool | None = None
    #: 顶层条目（目录名或根级文件名）
    top_entries: list[str] = field(default_factory=list)
    files: int = 0
    size: int = 0
    #: 覆盖原版的文件（相对路径）
    overrides: list[str] = field(default_factory=list)
    #: 新增的文件（相对路径）
    additions: list[str] = field(default_factory=list)
    #: 功能前缀统计
    prefixes: Counter = field(default_factory=Counter)
    #: 带前缀的示例：(前缀, 键, 相对路径)
    prefix_samples: list[tuple[str, str, str]] = field(default_factory=list)
    #: 每个数据目录改动的原版条目数
    touched_vanilla: Counter = field(default_factory=Counter)
    #: 每个数据目录新增的条目数
    added_entries: Counter = field(default_factory=Counter)

    @property
    def size_mb(self) -> float:
        return round(self.size / (1024 * 1024), 2)

    @property
    def target(self) -> str:
        return self.steam_id or self.root.name

    def summary(self) -> dict[str, object]:
        return {
            "目标": self.target,
            "名称": self.name,
            "支持版本": self.supported_game_version,
            "文件": self.files,
            "覆盖原版": len(self.overrides),
            "新增": len(self.additions),
            "前缀使用": sum(self.prefixes.values()),
        }


def read_metadata(root: Path) -> dict:
    """读 mod 的 ``.metadata/metadata.json``。字段与官方格式一致。"""
    path = root / METADATA_REL
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def analyse_mod(root: Path, *, vanilla: Path | None = None) -> ModInfo:
    """分析一个 mod 目录。``vanilla`` 为游戏 ``game/`` 目录，用于判定覆盖。"""
    vanilla = vanilla or GAME
    info = ModInfo(root=root, steam_id=root.name if root.parent == WORKSHOP else "")

    meta = read_metadata(root)
    if meta:
        info.name = str(meta.get("name", ""))
        info.version = str(meta.get("version", ""))
        info.supported_game_version = str(meta.get("supported_game_version", ""))
        info.description = str(meta.get("short_description", ""))
        gcd = meta.get("game_custom_data") or {}
        if isinstance(gcd, dict) and "multiplayer_synchronized" in gcd:
            info.multiplayer_synced = bool(gcd["multiplayer_synchronized"])

    tops: set[str] = set()
    mdir = root / ".metadata"

    for f in walk_files(root):
        # 跳过 .metadata 自身
        try:
            rel = f.path.relative_to(root)
        except ValueError:
            continue
        if mdir in f.path.parents or rel.parts and rel.parts[0] == ".metadata":
            continue

        info.files += 1
        info.size += f.size
        tops.add(rel.parts[0])

        rel_str = str(rel).replace("\\", "/")
        if (vanilla / rel).is_file():
            info.overrides.append(rel_str)
        else:
            info.additions.append(rel_str)

        if f.suffix == ".txt":
            _scan_prefixes(f.path, rel_str, vanilla, info)

    info.top_entries = sorted(tops)
    info.overrides.sort()
    info.additions.sort()
    return info


def _scan_prefixes(
    path: Path, rel_str: str, vanilla: Path, info: ModInfo
) -> None:
    """统计一个 mod 文件里的顶层条目：区分「改原版」与「新增」。"""
    try:
        pf = parse_cached(path)
    except Exception:
        return

    vanilla_file = vanilla / rel_str
    for a in pf.top_assignments:
        if a.prefix:
            info.prefixes[a.prefix] += 1
            if len(info.prefix_samples) < 400:
                info.prefix_samples.append((a.prefix, a.key, rel_str))

        # 归类到「改了原版条目」还是「新增条目」
        if vanilla_file.is_file():
            try:
                vpf = parse_cached(vanilla_file)
                vanilla_keys = set(vpf.top_keys)
            except Exception:
                vanilla_keys = set()
            bucket = (
                info.touched_vanilla if a.key in vanilla_keys else info.added_entries
            )
        else:
            bucket = info.added_entries
        bucket[rel_str.split("/")[0]] += 1


def discover_mods(
    *, include_local: bool = True, include_workshop: bool = True
) -> list[Path]:
    """列出所有 mod 根目录。"""
    roots: list[Path] = []
    if include_workshop and WORKSHOP.is_dir():
        roots += sorted(p for p in WORKSHOP.iterdir() if p.is_dir())
    if include_local and LOCAL_MODS.is_dir():
        roots += sorted(
            p for p in LOCAL_MODS.iterdir() if p.is_dir() and not p.name.startswith(".")
        )
    return roots


def analyse_all(**kwargs) -> list[ModInfo]:
    """分析全部 mod，按目标名排序。"""
    out = [analyse_mod(r, **kwargs) for r in discover_mods()]
    return sorted(out, key=lambda m: m.target)


def aggregate_prefixes(mods: list[ModInfo]) -> Counter:
    total: Counter = Counter()
    for m in mods:
        total.update(m.prefixes)
    return total


def vanilla_prefix_count(vanilla: Path | None = None) -> Counter:
    """统计**原版**使用功能前缀的次数。

    实测为 0 —— 这套机制是专供 mod 的。这项检查用来防止结论被
    悄悄推翻：如果哪天原版开始使用，这里会立刻反映出来。
    """
    vanilla = vanilla or GAME
    total: Counter = Counter()
    for f in walk_files(vanilla, suffix=".txt"):
        try:
            pf = parse_cached(f.path)
        except Exception:
            continue
        for a in pf.top_assignments:
            if a.prefix:
                total[a.prefix] += 1
    return total
