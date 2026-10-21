"""Victoria 3 原版文件引用的机械核对。

为什么需要它
------------
Mod 作者可以用 `v3 citations <路径...>` 核对说明文件中的原版文件引用，提前发现拼写、
子路径、行号和 basename 歧义。它不判断被引内容是否支持文字结论，也不替代锁定原版
接口门禁；生产生成由 `modguard` 负责。

口径（写在明处）
----------------
* 引用写法：``文件名:行号`` 或 ``文件名:起-止``（例如 ``content_1_modifiers.txt:1462-1470``）；
* 文件名允许带子路径（``common/defines/00_defines.txt:12``），也允许只写 basename；
* 解析范围：默认在**游戏内容层** ``config.GAME`` 下按 basename 建索引（一次遍历、缓存）；
  带子路径的引用直接按相对路径探；**仓库内**文件也按相对路径解析；
* 行号校验：``1 <= 行号 <= 文件行数``；
* 唯一性：basename 在索引里命中多个路径时，**只有显式写了子路径才算可解析**，
  否则报"歧义"（这是最容易骗过人的一类引用）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import config

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

#: 引用：``名字:行号`` / ``名字:起-止``。
#:
#: ⚠️ 名字里**必须**有扩展名（`.txt` / `.gui` / `.py` / `.md` / `.toml`）——
#: 否则 `03_political_strategies.txt:528-544` 没问题，而 `P2:F9` 这种非文件引用
#: （文档章节号）会被误当成引用。实测 why 里两类都写，所以这条限定是必须的。
CITATION_RE = re.compile(
    # ⚠️ 名字里**可以带空格**：原版历史文件就叫 `rus - russia.txt`（实测：写全路径时
    # 扫描器原样不认，报 4 条假 missing）。首字符仍限死非空格，避免从行首一路吃过来。
    r"(?P<file>[0-9A-Za-z_./\\-][0-9A-Za-z_./\\ -]*?\.(?:txt|gui|asset|font|layout|settings|profile|shortcuts|py|md|toml|json|yml))"
    r":(?P<start>\d+)(?:-(?P<end>\d+))?"
)

#: 建索引时跳过的目录名（大且无用：图形资源、着色器缓存）。
SKIP_DIRS = frozenset(
    {
        "binaries",
        "launcher",
        "platform_specific_game_data",
        "shadercache",
        "__pycache__",
        ".git",
        "logs",
        "crashes",
        "screenshots",
    }
)

CONTENT_ROOTS = ("game", "jomini", "clausewitz")


@dataclass(frozen=True, slots=True)
class Citation:
    """一条引用 + 它的核对结论。"""

    file: str
    start: int
    end: int
    where: str  #: 引用出现在哪个文件的哪一段（人读用）
    resolved: str  #: 解析到的绝对路径；没解析到是空串
    status: str  #: ok / missing / ambiguous / out_of_range
    detail: str  #: 一句话说明（歧义时列出候选）

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def describe(self) -> str:
        head = f"{self.file}:{self.start}" + (f"-{self.end}" if self.end != self.start else "")
        return f"{self.status:12s} {head}  ← {self.where}  {self.detail}".rstrip()


def _index(root: Path) -> dict[str, list[Path]]:
    """``basename -> [绝对路径…]``。"""
    index: dict[str, list[Path]] = {}
    if not root.is_dir():
        return index
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        index.setdefault(path.name, []).append(path)
    return index


_INDEX_CACHE: dict[Path, dict[str, list[Path]]] = {}


def game_index(root: Path | None = None) -> dict[str, list[Path]]:
    """游戏内容层的 basename 索引（进程内缓存；``clear_cache()`` 可清）。"""
    base = root or config.GAME
    if base not in _INDEX_CACHE:
        _INDEX_CACHE[base] = _index(base)
    return _INDEX_CACHE[base]


def _content_roots(root: Path | None) -> tuple[tuple[str, Path], ...]:
    """返回引用扫描所见的内容根；显式 ``root`` 时保持旧的单根语义。"""
    if root is not None:
        return (("game", root),)
    return (
        ("game", config.GAME),
        ("jomini", config.JOMINI),
        ("clausewitz", config.CLAUSEWITZ),
    )


def _all_content_hits(name: str) -> list[tuple[str, Path]]:
    # 绝大多数档案引用都指向 game；先查 game，命中后不为一次引用扫描
    # 整棵 Jomini/Clausewitz 树建立索引。只有 game 没有该 basename 时，
    # 才按需探查引擎层，显式 ``jomini/...`` 仍走直接路径。
    game_hits = [("game", path) for path in game_index(config.GAME).get(name, [])]
    if game_hits:
        return game_hits
    hits: list[tuple[str, Path]] = []
    for label, base in _content_roots(None)[1:]:
        hits.extend((label, path) for path in game_index(base).get(name, []))
    return hits


def clear_cache() -> None:
    _INDEX_CACHE.clear()


def _line_count(path: Path) -> int:
    """文件行数（``errors='replace'``：个别原版文件不是干净 UTF-8）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return len(text.splitlines())


def _resolve(name: str, *, root: Path | None = None) -> tuple[Path | None, str, str]:
    """把引用里的文件名解析成唯一个文件；返回 ``(路径|None, 状态, 说明)``。"""
    cleaned = name.replace("\\", "/")
    roots = _content_roots(root)
    base = roots[0][1]
    if "/" in cleaned:
        head, rel = cleaned.split("/", 1)
        selected = dict(roots).get(head)
        if selected is not None:
            base = selected
            cleaned = rel
        direct = base / cleaned
        if direct.is_file():
            return (direct, "ok", "")
        # 带子路径也可能是"仓库内文件"的写法
        repo = config.REPO / cleaned
        if repo.is_file():
            return (repo, "ok", "")
        return (None, "missing", f"{base / cleaned} 不存在（也试过 {repo}）")
    if root is not None:
        hits = [("game", path) for path in game_index(base).get(cleaned, [])]
    else:
        hits = _all_content_hits(cleaned)
    if not hits:
        repo = config.REPO / cleaned
        if repo.is_file():
            return (repo, "ok", "")
        return (None, "missing", f"{base} 下没有任何文件叫这个名字")
    if len(hits) > 1:
        sample = "、".join(
            f"{label}/{path.relative_to(dict(roots).get(label, base))}" for label, path in hits[:4]
        )
        return (
            None,
            "ambiguous",
            f"同名 {len(hits)} 个：{sample}…（引用要么写子路径，要么换一个）",
        )
    return (hits[0][1], "ok", "")


def scan_text(text: str, *, where: str, root: Path | None = None) -> list[Citation]:
    """扫一段文本（通常是整个数据源文件）里的全部引用并逐条核对。"""
    found: list[Citation] = []
    # 一次扫描只读同一文件一次；缓存不跨调用，后续编辑绝不复用旧行数。
    line_counts: dict[Path, int] = {}
    for match in CITATION_RE.finditer(text):
        name = match.group("file").strip()
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        path, status, detail = _resolve(name, root=root)
        resolved = str(path) if path else ""
        if status == "ok" and path is not None:
            if path not in line_counts:
                line_counts[path] = _line_count(path)
            lines = line_counts[path]
            if not (1 <= start <= lines) or not (1 <= end <= lines):
                status = "out_of_range"
                detail = f"文件只有 {lines} 行"
            elif end < start:
                status = "out_of_range"
                detail = f"起止反了（{start}-{end}）"
        found.append(
            Citation(
                file=name,
                start=start,
                end=end,
                where=where,
                resolved=resolved,
                status=status,
                detail=detail,
            )
        )
    return found


def scan_file(path: Path, *, root: Path | None = None) -> list[Citation]:
    """扫一个文件（数据源 / 文档）里的全部引用。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return scan_text(text, where=path.name, root=root)


def scan_paths(paths: Iterable[Path], *, root: Path | None = None) -> list[Citation]:
    """扫一批文件（目录会展开成它下面的数据源 / 文档）。"""
    found: list[Citation] = []
    for path in _expand(paths):
        found.extend(scan_file(path, root=root))
    return found


def _expand(paths: Iterable[Path]) -> Iterator[Path]:
    suffixes = {
        ".toml",
        ".md",
        ".txt",
        ".py",
        ".gui",
        ".asset",
        ".font",
        ".layout",
        ".settings",
        ".profile",
        ".shortcuts",
        ".yml",
        ".json",
    }
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix in suffixes:
                    yield child
        elif path.is_file():
            yield path


def summarize(citations: Iterable[Citation]) -> dict[str, object]:
    """按状态计数 + 列出问题条目（给 CLI / 测试用）。"""
    items = list(citations)
    by_status: dict[str, int] = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
    return {
        "total": len(items),
        "by_status": by_status,
        "problems": [item for item in items if not item.ok],
    }


__all__ = [
    "CITATION_RE",
    "Citation",
    "clear_cache",
    "game_index",
    "scan_file",
    "scan_paths",
    "scan_text",
    "summarize",
]
