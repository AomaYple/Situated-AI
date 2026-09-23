"""数据源里 ``文件:行号`` 引用的**机械核对**（P10 从纪律变成可执行检查）。

为什么需要它
------------
`ru_defeat.toml` / `tr_defeat.toml` 的每条 `why` 都靠「原版某文件某一行就是这么写的」
立论（P10：每个数字都要有依据）。但闸门 ⑤ 只能查 `why` **非空** —— 它查不出
"行号是编的"。一份 28 KB 的档案里有几十条引用，人眼逐条核不可持续：

* 文件名打错（`00_code_static_modifiers.txt` 写成 `00_static_modifiers.txt`）；
* 行号越界（文件只有 300 行，引了 `:322`）；
* 文件名在游戏里**不唯一**（`modifiers.txt` 有几十个同名的），于是"那条依据"根本指不到唯一一行。

这个模块把这三件事变成一次 `v3 citations` 就能看到的表。**它不做语义判断**：
"那一行真的支持这条 why 吗"仍然要人看 —— 这里只保证"引用的东西**存在且唯一**"，
把人的注意力从"找文件"挪到"读内容"。

口径（写在明处）
----------------
* 引用写法：``文件名:行号`` 或 ``文件名:起-止``（例如 ``content_1_modifiers.txt:1462-1470``）；
* 文件名允许带子路径（``common/defines/00_defines.txt:12``），也允许只写 basename；
* 解析范围：默认在**游戏内容层** ``config.GAME`` 下按 basename 建索引（一次遍历、缓存）；
  带子路径的引用直接按相对路径探；**仓库内**文件（``modgen.py:123`` 这类）也认；
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
    r"(?P<file>[0-9A-Za-z_./\\-][0-9A-Za-z_./\\ -]*?\.(?:txt|gui|py|md|toml|json|yml))"
    r":(?P<start>\d+)(?:-(?P<end>\d+))?"
)

#: 建索引时跳过的目录名（大且无用：图形资源、着色器缓存）。
SKIP_DIRS = frozenset({"gfx", "sound", "music", "shadercache", "__pycache__", ".git"})


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


def clear_cache() -> None:
    _INDEX_CACHE.clear()


def _line_count(path: Path) -> int:
    """文件行数（``errors='replace'``：个别原版文件不是干净 UTF-8）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return len(text.splitlines())


def _resolve(name: str, *, root: Path | None = None) -> tuple[Path | None, str, str]:
    """把引用里的文件名解析成唯一个文件；返回 ``(路径|None, 状态, 说明)``。"""
    base = root or config.GAME
    cleaned = name.replace("\\", "/")
    if "/" in cleaned:
        direct = base / cleaned
        if direct.is_file():
            return (direct, "ok", "")
        # 带子路径也可能是"仓库内文件"的写法
        repo = config.REPO / cleaned
        if repo.is_file():
            return (repo, "ok", "")
        return (None, "missing", f"{base / cleaned} 不存在（也试过 {repo}）")
    hits = game_index(base).get(cleaned, [])
    if not hits:
        repo = config.REPO / cleaned
        if repo.is_file():
            return (repo, "ok", "")
        return (None, "missing", f"{base} 下没有任何文件叫这个名字")
    if len(hits) > 1:
        sample = "、".join(str(p.relative_to(base)) for p in hits[:4])
        return (
            None,
            "ambiguous",
            f"同名 {len(hits)} 个：{sample}…（引用要么写子路径，要么换一个）",
        )
    return (hits[0], "ok", "")


def scan_text(text: str, *, where: str, root: Path | None = None) -> list[Citation]:
    """扫一段文本（通常是整个数据源文件）里的全部引用并逐条核对。"""
    found: list[Citation] = []
    for match in CITATION_RE.finditer(text):
        name = match.group("file").strip()
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        path, status, detail = _resolve(name, root=root)
        resolved = str(path) if path else ""
        if status == "ok" and path is not None:
            lines = _line_count(path)
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
    suffixes = {".toml", ".md", ".txt", ".py"}
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
