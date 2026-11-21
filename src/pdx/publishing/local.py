"""Resumable, exact-byte installation of a frozen Mod release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
lazy import ctypes

from pdx import distribution

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def checked_path(path: Path) -> Path:
    """Reject links, Windows junctions, and noncanonical path components."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"需要绝对且规范的路径：{path}")
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"发布路径不能经过链接或重解析点：{part}")
    return path


def tree(root: Path) -> dict[str, bytes] | None:
    """Read every file and empty directory, preserving the absent distinction."""
    checked_path(root)
    if not root.exists():
        return None
    if not root.is_dir():
        raise ValueError(f"本地 Mod 路径必须是目录：{root}")
    result: dict[str, bytes] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError(f"本地 Mod 目录包含链接：{path}")
            name = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
                result[name + "/"] = b""
            elif stat.S_ISREG(info.st_mode):
                result[name] = path.read_bytes()
            else:
                raise ValueError(f"本地 Mod 目录包含特殊文件：{path}")
    return result


def tree_digest(files: Mapping[str, bytes] | None) -> str:
    if files is None:
        return "absent"
    rows = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _expected_tree(files: Mapping[str, bytes]) -> dict[str, bytes]:
    expected = dict(files)
    for name in files:
        for parent in PurePosixPath(name).parents:
            if parent.parts:
                expected[parent.as_posix() + "/"] = b""
    return expected


def _write_tree(root: Path, files: Mapping[str, bytes]) -> None:
    root.mkdir()
    for name, raw in files.items():
        path = root.joinpath(*PurePosixPath(name).parts)
        if name.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)


def _rename_exclusive(source: Path, destination: Path) -> None:
    """Atomically rename a directory only when the destination is absent."""
    platform = sys.platform
    if platform == "win32":
        source.rename(destination)
        return
    library = ctypes.CDLL(None, use_errno=True)
    source_raw = os.fsencode(source)
    destination_raw = os.fsencode(destination)
    if platform == "linux" and hasattr(library, "renameat2"):
        # Both paths are absolute. AT_FDCWD is ignored for either path.
        rename = library.renameat2
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(-100, source_raw, -100, destination_raw, 1)  # RENAME_NOREPLACE
    elif platform == "darwin" and hasattr(library, "renamex_np"):
        rename = library.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(source_raw, destination_raw, 4)  # RENAME_EXCL
    else:
        raise OSError("此系统未提供本地发布需要的无覆盖重命名")
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def _launcher_state(target: Path) -> dict[str, object]:
    launcher = target.parent.parent / "content_load.json"
    try:
        checked_path(launcher)
        if not launcher.is_file():
            return {"path": str(launcher), "status": "unknown"}
        raw = launcher.read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
        enabled = data.get("enabledMods") if isinstance(data, dict) else None
        if isinstance(enabled, list) and all(
            isinstance(row, dict) and isinstance(row.get("path"), str) for row in enabled
        ):
            return {
                "path": str(launcher),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "enabled": any(Path(row["path"]) == target for row in enabled),
            }
    except ValueError, OSError:
        pass
    return {"path": str(launcher), "status": "unknown"}


def inspect_local(
    user_mod_root: Path,
    previous_sha256: str | None,
    *,
    files: Mapping[str, bytes] | None = None,
    previous: Mapping[str, object] | None = None,
    backup_root: Path | None = None,
    operation_id: str | None = None,
) -> dict[str, object]:
    root = checked_path(user_mod_root)
    if not root.is_dir():
        raise ValueError("--local-root 必须是已存在的用户 mod 根目录")
    target = root / distribution.INSTALL_DIRECTORY_NAME
    actual = tree_digest(tree(target))
    desired_tree = _expected_tree(files) if files is not None else None
    desired = tree_digest(desired_tree) if desired_tree is not None else None
    interrupted = False
    activated = bool(previous and previous.get("status") in {"activated", "verified"})
    if desired_tree is not None and operation_id is not None and backup_root is not None:
        switch = _switch_path(root, operation_id)
        retired, backup = _transaction_prestate(
            switch, backup_root, desired_tree, previous_sha256, previous or {}
        )
        interrupted = actual == "absent" and retired is not None
        activated = activated or _may_be_activated(switch, previous or {})
        if previous and activated and previous.get("backup_path") and backup is None:
            raise ValueError("原件备份已消失")
        if retired is not None and actual not in {"absent", desired}:
            raise ValueError("本地目标与旧目录恢复点同时存在")
    if previous_sha256 is None:
        status = "needs_confirmation"
    elif activated and actual != desired:
        status = "conflict"
    elif actual in {previous_sha256, desired} or interrupted:
        status = "ready"
    else:
        status = "conflict"
    return {
        "status": status,
        "target": str(target),
        "observed_tree_sha256": actual,
        "release_tree_sha256": desired,
        "launcher": _launcher_state(target),
    }


def _switch_path(root: Path, operation_id: str) -> Path:
    if re.fullmatch(r"[a-z0-9-]+", operation_id) is None:
        raise ValueError("本地发布事务标识格式不符")
    return checked_path(root / f".situated-ai-publish-{operation_id}")


def _may_be_activated(switch: Path, previous: Mapping[str, object]) -> bool:
    # Once staging has moved to the target, a crash before the checkpoint can
    # leave the old checkpoint on disk. Treat missing staging as ambiguous.
    return previous.get("status") == "switch_prepared" and tree(switch / "staging") is None


def _transaction_prestate(
    switch: Path,
    backup_root: Path,
    desired: Mapping[str, bytes],
    previous_sha256: str | None,
    previous: Mapping[str, object],
) -> tuple[dict[str, bytes] | None, dict[str, bytes] | None]:
    if switch.exists() and previous.get("switch_path") != str(switch):
        raise ValueError("发现其他本地安装事务目录")
    if switch.exists() and {path.name for path in switch.iterdir()} - {"staging", "previous"}:
        raise ValueError("本地安装事务目录含额外文件")
    retired = tree(switch / "previous")
    if retired is not None and tree_digest(retired) != previous_sha256:
        raise ValueError("旧目录恢复点与显式确认摘要不符")
    backup = tree(backup_root / "local-previous")
    if backup is not None and tree_digest(backup) != previous_sha256:
        raise ValueError("本地原件备份内容不符")
    staged_backup = tree(backup_root / ".local-previous-staging")
    staged_release = tree(switch / "staging")
    if staged_backup is not None and tree_digest(staged_backup) != previous_sha256:
        raise ValueError("本地原件备份暂存内容不符，保留恢复材料")
    if staged_release is not None and staged_release != desired:
        raise ValueError("本地发布暂存内容不符，保留恢复材料")
    return retired, backup


def install(
    files: Mapping[str, bytes],
    user_mod_root: Path,
    expected_previous_digest: str,
    backup_root: Path,
    operation_id: str,
    previous: Mapping[str, object],
    checkpoint: Callable[[Mapping[str, object]], None],
) -> dict[str, object]:
    target = checked_path(user_mod_root / distribution.INSTALL_DIRECTORY_NAME)
    switch = _switch_path(user_mod_root, operation_id)
    staging = switch / "staging"
    retired = switch / "previous"
    backup = checked_path(backup_root / "local-previous")
    desired = _expected_tree(files)
    desired_sha = tree_digest(desired)
    actual = tree(target)
    original, original_backup = _transaction_prestate(
        switch, backup_root, desired, expected_previous_digest, previous
    )
    before = _launcher_state(target)
    state: dict[str, object] = {
        "target": str(target),
        "previous_sha256": expected_previous_digest,
        "release_tree_sha256": desired_sha,
        "switch_path": str(switch),
        "backup_path": str(backup)
        if expected_previous_digest not in {"absent", desired_sha}
        else None,
        "launcher_before": previous.get("launcher_before", before),
    }

    def record(status: str) -> None:
        checkpoint({**state, "status": status})

    if actual != desired:
        if previous.get("status") in {"activated", "verified"} or _may_be_activated(
            switch, previous
        ):
            raise ValueError("已验证的本地发布目录被修改，拒绝再次替换")
        if original is None:
            original = actual
        elif actual is not None:
            raise ValueError("本地目标与旧目录恢复点同时存在")
        if tree_digest(original) != expected_previous_digest:
            raise ValueError("本地目标树与显式确认摘要不符，拒绝覆盖")
        record("preparing")
        if original is not None and original_backup is None:
            backup_stage = checked_path(backup_root / ".local-previous-staging")
            if not backup_stage.exists():
                _write_tree(backup_stage, original)
            if tree(backup_stage) != original:
                raise ValueError("本地原件备份回读失败")
            _rename_exclusive(backup_stage, backup)
        switch.mkdir(exist_ok=True)
        if not staging.exists():
            _write_tree(staging, desired)
        if tree(staging) != desired or tree(target) != actual:
            raise ValueError("本地目录在切换前发生变化")
        record("switch_prepared")
        if actual is not None:
            _rename_exclusive(target, retired)
        try:
            moved = tree(retired)
            if moved != original:
                if moved is not None and tree(target) is None:
                    _rename_exclusive(retired, target)
                raise ValueError("实际迁移的旧目录与确认原件不符")
            if tree(target) is not None:
                raise ValueError("本地目录在切换期间被其他程序创建")
            _rename_exclusive(staging, target)
        except ValueError, OSError:
            if actual is not None and tree(target) is None and tree(retired) == actual:
                _rename_exclusive(retired, target)
            raise
    if tree(target) != desired:
        raise ValueError("本地安装回读不符，旧目录保留在恢复点")
    if (
        expected_previous_digest not in {"absent", desired_sha}
        and tree_digest(tree(backup)) != expected_previous_digest
    ):
        raise ValueError("已部署，但原件备份与确认摘要不符")
    record("activated")
    if retired.exists():
        if tree(retired) != original:
            raise ValueError("旧目录发生变化，保留恢复点")
        shutil.rmtree(retired)
    if switch.exists():
        switch.rmdir()
    after = _launcher_state(target)
    return {
        **state,
        "status": "verified",
        "manifest_sha256": hashlib.sha256(files[distribution.MANIFEST_NAME]).hexdigest(),
        "launcher_after": after,
    }
