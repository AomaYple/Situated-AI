"""从已验证的发布内容树部署固定 Mod；不修改播放集、存档或其他 Mod。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

from pdx import config, distribution

if TYPE_CHECKING:
    from collections.abc import Iterator


def reject_links(path: Path) -> None:
    """拒绝符号链接和 Windows junction/reparse point，包括已有祖先。"""
    for candidate in (path.absolute(), *path.absolute().parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"发布路径不允许链接或重解析点：{candidate}")


def tree_hashes(root: Path) -> dict[str, str]:
    """核对整个树，不跟随链接；文件集合也是部署合同的一部分。"""
    reject_links(root)
    hashes = {}
    for path in sorted(root.rglob("*")):
        reject_links(path)
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        elif not path.is_dir():
            raise ValueError(f"发布树含非常规文件：{path}")
    return hashes


def assert_game_stopped() -> None:
    """文件替换前检查游戏及 Paradox 启动器；不代替操作系统文件锁。"""
    names = {
        "victoria3",
        "victoria3.exe",
        "paradox launcher",
        "paradox launcher.exe",
        "paradox launcher v2",
        "paradox launcher v2.exe",
        "dowser",
        "dowser.exe",
    }
    for process in psutil.process_iter(["name"]):
        name = process.info.get("name")
        if name and name.casefold() in names:
            raise ValueError(f"游戏或启动器仍在运行：{name}；关闭后重新发布")


@contextmanager
def deployment_lock(userdir: Path, *, name: str = ".situated-ai-deploy.lock") -> Iterator[None]:
    """排他文件锁；崩溃遗留锁不自动抢占，避免两个部署同时替换目录。"""
    reject_links(userdir)
    userdir.mkdir(parents=True, exist_ok=True)
    lock = userdir / name
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"部署锁已存在：{lock}；核对没有发布进程后再移除遗留锁") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def _identity(root: Path) -> None:
    try:
        metadata = json.loads((root / distribution.METADATA_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"目录缺少可核实的 Mod 身份：{root}") from exc
    if not isinstance(metadata, dict) or metadata.get("id") != config.MOD_ID:
        raise ValueError(f"目录 Mod 身份不符，拒绝替换：{root}")


def deploy(content: Path, userdir: Path) -> dict[str, object]:
    """同卷暂存、逐文件核对、备份旧树和异常恢复；保留成功部署的恢复备份。"""
    assert_game_stopped()
    target = userdir / "mod" / distribution.INSTALL_DIRECTORY_NAME
    reject_links(target)
    expected = tree_hashes(content)
    _identity(content)
    if not expected:
        raise ValueError("发布内容树为空")
    source = content.resolve()
    resolved_target = target.resolve()
    if (
        source == resolved_target
        or source in resolved_target.parents
        or resolved_target in source.parents
    ):
        raise ValueError("部署源和目标必须是独立目录")
    with deployment_lock(userdir):
        backup = None
        if target.exists():
            _identity(target)
            if tree_hashes(target) == expected:
                return {"status": "unchanged", "target": str(target), "backup": None}
        # staging 和 backup 都在 Mod 扫描范围之外；userdir 与目标在同一卷。
        with tempfile.TemporaryDirectory(prefix=".sitai-stage-", dir=userdir) as temporary:
            staged = Path(temporary) / "content"
            shutil.copytree(content, staged)
            if tree_hashes(staged) != expected:
                raise ValueError("暂存部署内容与固定包不一致")
            assert_game_stopped()
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = userdir / ".situated-ai-backups" / uuid.uuid4().hex / target.name
                reject_links(backup)
                backup.parent.mkdir(parents=True)
                target.rename(backup)
            installed = False
            try:
                staged.rename(target)
                installed = True
                if tree_hashes(target) != expected:
                    raise ValueError("安装后逐文件核对失败")
            except BaseException as exc:
                try:
                    if installed:
                        target.rename(Path(temporary) / "failed-install")
                    if backup is not None:
                        backup.rename(target)
                except OSError as recovery:
                    raise OSError(
                        f"部署恢复失败；旧树保存在 {backup}，目标={target}：{recovery}"
                    ) from exc
                raise
        return {
            "status": "succeeded",
            "target": str(target),
            "backup": str(backup) if backup else None,
            "file_count": len(expected),
        }
