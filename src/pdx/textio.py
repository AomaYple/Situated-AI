"""仓库文本无 BOM；仅在游戏部署边界添加 UTF-8 BOM。"""

from __future__ import annotations

import codecs
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

GAME_SUFFIXES = frozenset({".txt", ".yml"})


def normalized_text(text: str) -> str:
    """只归一编码标记与换行，不改变空白、末尾换行和正文。"""
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def text_bytes(text: str, *, game: bool = False) -> bytes:
    raw = normalized_text(text).encode("utf-8")
    return codecs.BOM_UTF8 + raw if game else raw


def deploy_tree(source: Path, destination: Path) -> list[Path]:
    """复制独立部署树；源码保持不变，游戏脚本和本地化恰好加一个 BOM。"""
    for path in (source, destination, *destination.parents):
        if path.is_symlink():
            raise ValueError(f"部署路径不允许符号链接：{path}")
    source = source.resolve()
    destination = destination.resolve()
    if destination == source or source in destination.parents or destination in source.parents:
        raise ValueError("部署目录必须在源码目录之外")
    paths = sorted(source.rglob("*"))
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"部署源不允许符号链接：{path}")
        target = destination / path.relative_to(source)
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError(f"部署目标不允许符号链接：{target}")
    written: list[Path] = []
    for path in paths:
        if not path.is_file():
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = path.read_bytes()
        if path.suffix.lower() in GAME_SUFFIXES:
            raw = text_bytes(raw.decode("utf-8-sig"), game=True)
        target.write_bytes(raw)
        written.append(target)
    return written
