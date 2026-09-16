"""文件系统扫描：清单、计数、体积。

这一层只做「看得到什么」，不做解析。解析在 :mod:`pdx.extract`。
所有统计口径集中在此，避免不同脚本各算一套导致数字对不上。
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

#: 文本类扩展名（可解析、可用文本工具处理）
TEXT_SUFFIXES = frozenset(
    {
        ".txt", ".md", ".gui", ".yml", ".yaml", ".csv", ".json",
        ".settings", ".profile", ".font", ".info", ".asset", ".html",
    }
)


@dataclass(slots=True)
class FileEntry:
    path: Path
    size: int
    suffix: str


@dataclass(slots=True)
class DirStats:
    """一个目录的统计结果。"""

    name: str
    path: Path
    files: int = 0
    dirs: int = 0
    size: int = 0
    text_files: int = 0
    binary_files: int = 0
    by_suffix: Counter = field(default_factory=Counter)

    @property
    def size_mb(self) -> float:
        return round(self.size / (1024 * 1024), 2)


def walk_files(root: Path, suffix: str | None = None) -> Iterator[FileEntry]:
    """递归产出文件条目。

    用 ``os.scandir`` 手动递归，比 ``Path.rglob`` 快 —— 在 2.7 万文件的
    树上差距明显。跳过符号链接，避免意外穿越。
    """
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            if suffix and not entry.name.endswith(suffix):
                                continue
                            st = entry.stat(follow_symlinks=False)
                            yield FileEntry(
                                path=Path(entry.path),
                                size=st.st_size,
                                suffix=Path(entry.name).suffix.lower(),
                            )
                    except OSError:
                        # 沙箱可能拒绝个别条目；跳过而非中断整轮扫描
                        continue
        except OSError:
            continue


def stats_for(path: Path, *, deep: bool = True) -> DirStats:
    """统计单个目录。``deep=False`` 时只统计直接子项。"""
    st = DirStats(name=path.name, path=path)
    if not path.is_dir():
        return st

    if not deep:
        try:
            with os.scandir(path) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        st.dirs += 1
                    elif e.is_file(follow_symlinks=False):
                        st.files += 1
                        st.size += e.stat(follow_symlinks=False).st_size
        except OSError:
            pass
        return st

    for f in walk_files(path):
        st.files += 1
        st.size += f.size
        st.by_suffix[f.suffix] += 1
        if f.suffix in TEXT_SUFFIXES:
            st.text_files += 1
        else:
            st.binary_files += 1
    st.dirs = sum(1 for _ in _walk_dirs(path))
    return st


def _walk_dirs(root: Path) -> Iterator[Path]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        p = Path(entry.path)
                        yield p
                        stack.append(p)
        except OSError:
            continue


def subdir_stats(root: Path, *, deep: bool = True) -> list[DirStats]:
    """统计 root 下每个直接子目录，按名称排序。"""
    out: list[DirStats] = []
    try:
        with os.scandir(root) as it:
            names = sorted(
                e.name for e in it if e.is_dir(follow_symlinks=False)
            )
    except OSError:
        return out
    for name in names:
        out.append(stats_for(root / name, deep=deep))
    return out


def count_files(root: Path, suffix: str | None = None) -> int:
    return sum(1 for _ in walk_files(root, suffix))


def total_size(root: Path) -> int:
    return sum(f.size for f in walk_files(root))


def find_by_name(root: Path, patterns: Iterable[str]) -> list[Path]:
    """按文件名子串查找（大小写不敏感）。"""
    lowered = [p.lower() for p in patterns]
    hits: list[Path] = []
    for f in walk_files(root):
        n = f.path.name.lower()
        if any(p in n for p in lowered):
            hits.append(f.path)
    return sorted(hits)
