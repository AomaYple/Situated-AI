"""只生成维修图标的诊断资源挂载；字节审计不证明模拟无扰动或正式资格。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
from typing import TYPE_CHECKING

from pdx import config, decisions, deployment_state
from pdx.lexer import tokenize

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE = "gfx/interface/icons/generic_icons/repairing.dds"
_TARGET = "gfx/interface/icons/alert_icons/repairing.dds"
_GUI = "gui/texticons.gui"
_BOUNDARY = (
    "仅证明本地字节、来源与缺失引用；不证明模拟无扰动、AI 行为质量或正式资格；不豁免任何日志错误。"
)


def _supported_game_version(game: Path) -> str:
    """读取传入安装的版本，沿用现有 metadata 的裸版本格式。"""
    version = config.game_version(game.parent)
    if not isinstance(version, dict):
        raise ValueError("无法读取资源诊断 metadata 的游戏版本")
    branch = version.get("caligula_branch")
    if isinstance(branch, str) and branch.strip():
        value = branch.strip().rsplit("/", 1)[-1]
    else:
        raw = version.get("version")
        value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        raise ValueError("无法读取资源诊断 metadata 的游戏版本")
    return value


def _plain(path: Path) -> None:
    deployment_state.plain_path(path)
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if getattr(info, "st_reparse_tag", 0):
            raise ValueError(f"资源诊断路径不允许重解析点：{path}")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError(f"资源诊断路径不允许特殊文件：{path}")


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read(path: Path) -> tuple[bytes, str, tuple[int, ...]]:
    _plain(path)
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"资源诊断原件不是普通文件：{path}")
        if before.st_nlink != 1:
            raise ValueError(f"资源诊断原件不允许硬链接：{path}")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read()
            after = os.fstat(stream.fileno())
        sha = deployment_state.digest(path)
        _plain(path)
        signature = _signature(before)
        # Windows 的路径 stat 与句柄 fstat 对 ctime 的语义可能不同；
        # 路径和句柄分别比较完整签名，跨接口只比较身份、模式、大小和 mtime。
        if (
            _signature(path.stat()) != signature
            or _signature(opened) != _signature(after)
            or _signature(opened)[:5] != signature[:5]
            or sha != hashlib.sha256(data).hexdigest()
        ):
            raise ValueError(f"资源诊断原件读取期间发生变化：{path}")
        return data, sha, signature
    except OSError as exc:
        raise ValueError(f"资源诊断无法读取原件：{path}：{exc}") from exc


def _dds(data: bytes) -> None:
    if len(data) <= 128 or data[:4] != b"DDS ":
        raise ValueError("维修图标不是带完整头部和载荷的 DDS")
    header = struct.unpack_from("<31I", data, 4)
    if (
        header[0] != 124
        or header[1] & 0x1007 != 0x1007
        or not 0 < header[2] <= 16384
        or not 0 < header[3] <= 16384
        or header[18] != 32
        or not header[19] & (0x4 | 0x40)
        or not header[26] & 0x1000
        or (data[84:88] == b"DX10" and len(data) <= 148)
    ):
        raise ValueError("维修图标 DDS 头部不合理")


def _missing(path: Path) -> None:
    _plain(path)
    if path.exists():
        raise ValueError(f"原版维修图标目标已存在，不适用诊断挂载：{path}")


def write(output: Path, game: Path) -> dict:
    """独占创建诊断 Mod；已有输出拒绝覆盖，失败保留现场且不删除未知文件。"""
    _plain(output)
    _plain(game)
    protected = [game, config.ROOT, config.USERDIR]
    if game.name.lower() == "game":
        protected.append(game.parent)
    destination = output.resolve()
    if any(destination.is_relative_to(root.resolve()) for root in protected):
        raise ValueError("资源诊断输出不能位于游戏安装或用户原件目录内")
    if output.exists():
        raise ValueError(f"资源诊断输出已存在，拒绝覆盖：{output}")
    target = game / _TARGET
    _missing(target)
    gui_data, gui_sha, gui_signature = _read(game / _GUI)
    try:
        tokens = tokenize(gui_data.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ValueError("原版 texticons.gui 不是有效 UTF-8") from exc
    if not any(
        key.kind == "ATOM"
        and key.value == "texture"
        and operator.value == "="
        and value.value == f'"{_TARGET}"'
        for key, operator, value in zip(tokens, tokens[1:], tokens[2:], strict=False)
    ):
        raise ValueError("原版 texticons.gui 没有实际引用缺失的维修图标 texture")
    data, source_sha, source_signature = _read(game / _SOURCE)
    _dds(data)
    for path, sha, signature in (
        (game / _SOURCE, source_sha, source_signature),
        (game / _GUI, gui_sha, gui_signature),
    ):
        _plain(path)
        if _signature(path.stat()) != signature or deployment_state.digest(path) != sha:
            raise ValueError(f"资源诊断原件生成前发生变化：{path}")
    _missing(target)
    _plain(output)
    try:
        output.mkdir(parents=True, exist_ok=False)
        icon = output / _TARGET
        icon.parent.mkdir(parents=True)
        _plain(icon)
        with icon.open("xb") as stream:
            stream.write(data)
        output_sha = deployment_state.digest(icon)
        if output_sha != source_sha:
            raise ValueError("资源诊断输出字节与原件 SHA 不一致")
        manifest = {
            "schema": "sitai-resource-baseline-v1",
            "purpose": "diagnostic-resource-only",
            "source": {"path": _SOURCE, "sha256": source_sha},
            "gui": {"path": _GUI, "sha256": gui_sha},
            "output": {"path": _TARGET, "sha256": output_sha},
            "copied_bytes": len(data),
            "boundary": _BOUNDARY,
        }
        metadata = decisions.metadata_payload()
        metadata.update(
            name="SITAI 维修图标诊断资源",
            id="zz_sitai_resource_baseline",
            version="1.0.0",
            supported_game_version=_supported_game_version(game),
            short_description=_BOUNDARY,
            game_custom_data={
                "multiplayer_synchronized": False,
                "resource_baseline": manifest,
            },
        )
        metadata_path = output / ".metadata/metadata.json"
        metadata_path.parent.mkdir()
        _plain(metadata_path)
        with metadata_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        for path, sha, signature in (
            (game / _SOURCE, source_sha, source_signature),
            (game / _GUI, gui_sha, gui_signature),
        ):
            _plain(path)
            if _signature(path.stat()) != signature or deployment_state.digest(path) != sha:
                raise ValueError(f"资源诊断原件写入期间发生变化（现场保留）：{path}")
        _missing(target)
        members = set()
        for child in output.rglob("*"):
            _plain(child)
            if child.is_file():
                members.add(child.relative_to(output).as_posix())
        if members != {_TARGET, ".metadata/metadata.json"}:
            raise ValueError("资源诊断输出存在未知成员（现场保留）")
    except OSError as exc:
        raise ValueError(f"资源诊断无法独占创建输出（现场保留）：{output}：{exc}") from exc
    return manifest
