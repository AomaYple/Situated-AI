"""部署恢复专用的持久记录与原件指纹；文件操作仍由 Deployment 单独负责。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def plain_path(path: Path) -> None:
    """恢复路径不可经过链接，避免记录重放到别处。"""
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        # Windows Python 3.11 已有 st_reparse_tag，包括 junction。
        if part.is_symlink() or getattr(info, "st_reparse_tag", 0) in {0xA0000003, 0xA000000C}:
            raise ValueError(f"恢复路径不允许链接：{path}")


@contextmanager
def temporary_file(target: Path) -> Iterator[Path]:
    """独占随机临时文件，不覆盖用户已有的同名临时文件。"""
    plain_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".sitai-", suffix=".tmp", dir=target.parent)
    os.close(descriptor)
    temporary = target.parent / name
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def move_directory(source: Path, target: Path) -> None:
    """只做同文件系统重命名，不退化为复制再删除。"""
    plain_path(source)
    plain_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_dev != target.parent.stat().st_dev:
        raise OSError("目录移动跨文件系统，拒绝非原子复制删除")
    if target.exists():
        raise FileExistsError(f"目录移动目标已存在：{target}")
    source.rename(target)


def digest(path: Path) -> str:
    plain_path(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tree_digest(path: Path) -> str:
    """包括空目录、文件名与内容，不跟随目录链接。"""
    plain_path(path)
    if not path.is_dir():
        raise ValueError(f"原件不是目录：{path}")
    manifest = []
    for child in sorted(path.rglob("*")):
        plain_path(child)
        manifest.append(
            (child.relative_to(path).as_posix(), digest(child) if child.is_file() else None)
        )
    return hashlib.sha256(json.dumps(manifest, ensure_ascii=False).encode("utf-8")).hexdigest()


def durable_json(path: Path, value: object) -> None:
    """先刷写记录再发布；不承诺断电或硬件故障恢复。"""
    plain_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    plain_path(temporary)
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
