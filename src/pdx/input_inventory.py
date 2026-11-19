"""ENG-01 全根只读枚举；字节扫描完整不代表 raw 保全、解析或完整 epoch。

不使用旧脚本范围过滤分母。每个普通文件分块读取两次，分别检查打开前后
身份与元数据，并比较字节摘要；开始/结束另作完整目录枚举。此处不提供
文件系统快照或排他锁，不能证明最后一次观测之后没有写入。
"""

import ctypes
import hashlib
import json
import os
import shutil
import stat
from collections import Counter
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from dataclasses import asdict, dataclass, field, fields, replace
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from .input_contracts import (
    Diagnostic,
    InputContractError,
    InputIdentity,
    InputInventory,
    InventoryRecord,
    dumps_contract,
    file_set_digest,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO

ScanStatus = Literal["complete", "partial", "failed"]
_CHUNK_SIZE = 1024 * 1024
_POSIX_DIR_FD_OPEN_SUPPORTED = os.open in os.supports_dir_fd
# 已在锁定安装中验证 PDX 块结构的开发期资料类型。
PDX_RESOURCE_CATEGORIES = {
    ".bindings": "editor_data",
    ".compound": "asset_entity_dna",
    ".editordata": "editor_data",
    ".heightmap": "map_data",
    ".lines": "asset_entity_dna",
    ".map": "map_data",
    ".particle2": "asset_entity_dna",
    ".schematic": "asset_entity_dna",
    ".smv": "asset_entity_dna",
    ".vertical_borders": "map_data",
}
_CATEGORIES = {
    "gui": {".gui", ".layout"},
    "asset_entity_dna": {".asset", ".entity", ".dna", ".mesh", ".anim", ".gfx"},
    "localization": {".yml", ".yaml"},
    "structured_configuration": {".json", ".csv", ".toml", ".ini", ".cfg", ".xml"},
    "documentation": {".md", ".rst", ".html", ".htm", ".pdf", ".rtf"},
    "image_map": {".png", ".dds", ".tga", ".bmp", ".jpg", ".jpeg", ".tif", ".tiff"},
    "font": {".ttf", ".otf", ".woff", ".woff2"},
    "audio_video": {".wav", ".ogg", ".mp3", ".flac", ".opus", ".mp4", ".webm", ".bik"},
    "container": {".zip", ".7z", ".rar", ".pak", ".tar", ".gz", ".bz2", ".xz"},
    "binary": {".exe", ".dll", ".so", ".dylib", ".bin", ".pdb"},
    "pdx_script": {".txt", ".font", ".settings", ".profile", ".shortcuts", ".dlc"},
}


@dataclass(frozen=True, slots=True)
class InventorySummary:
    file_count: int
    regular_file_count: int
    known_bytes: int
    largest_file_bytes: int
    category_counts: tuple[tuple[str, int], ...]
    root_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class InventoryScan:
    """无 epoch 的观测；scan_status 仅指这轮枚举与原字节读取。

    records 的 completeness 保持 partial：未保全 raw，也未解析、解释、
    证明合法能力或生产接线。observed_paths 包括拒绝读取的链接/特殊节点；
    blocked_directories 是不能枚举的目录前沿，不冒充零个文件。
    """

    root: str
    source_layer: str
    authorization: str
    is_installation: bool
    records: tuple[InventoryRecord, ...]
    directories: tuple[str, ...]
    observed_paths: tuple[str, ...]
    blocked_directories: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    scan_status: ScanStatus
    file_set_sha256: str | None
    summary: InventorySummary

    @property
    def unassessed_fields(self) -> tuple[str, ...]:
        """适用于每一行；空关联集合不能冒充已证明不存在的关联。"""
        return (
            "raw_preservation",
            "parse",
            "semantic",
            "legality",
            "production",
            "package_associations",
            "dlc_identity_and_state",
            "override_priority",
        )


@dataclass(frozen=True, slots=True)
class _State:
    mode: int
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    attributes: int = field(compare=False)
    comparison_attributes: int


@dataclass(frozen=True, slots=True)
class _WindowsDirectoryState(_State):
    """保留原始 size；它不具备普通文件字节大小的比较合同。

    Python 的 st_size 字节语义只保证普通文件/符号链接。Windows 目录
    不借该报告值判断内容身份：完整子项集合、文件双摘要及目录其余状态
    仍参与盘点。POSIX 目录与普通文件继续使用 _State 的 size 比较。
    """

    size: int = field(compare=False)


@dataclass(frozen=True, slots=True)
class _Entry:
    kind: Literal["file", "link", "special", "unknown"]
    state: _State | None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(slots=True)
class _Enumeration:
    entries: dict[str, _Entry]
    directories: dict[str, _State]
    blocked: set[str]
    diagnostics: list[Diagnostic]


class _ObservationError(InputContractError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


def _diagnostic(code: str, path: str, detail: str) -> Diagnostic:
    return Diagnostic(code, f"{path!r}: {detail}", None)


def _state_change_details(before: _State, after: _State) -> dict[str, object]:
    """只构造证据，不决定是否漂移；保留原始/规范属性及比较参与信息。"""
    before_values, after_values = asdict(before), asdict(after)
    after_fields = {item.name: item for item in fields(after)}
    detail: dict[str, object] = {
        "before": before_values,
        "after": after_values,
        "changed_fields": {
            item.name: {
                "before": before_values[item.name],
                "after": after_values[item.name],
                "compared": item.compare or after_fields[item.name].compare,
            }
            for item in fields(before)
            if before_values[item.name] != after_values[item.name]
        },
    }
    if type(before) is not type(after):
        detail["state_type_change"] = {
            "before": type(before).__name__,
            "after": type(after).__name__,
            "compared": True,
        }
    return detail


def _directory_diagnostic(code: str, path: str, detail: dict[str, object]) -> Diagnostic:
    return Diagnostic(
        code,
        json.dumps({"path": path, **detail}, ensure_ascii=False, sort_keys=True, allow_nan=False),
        None,
    )


def _state(value: os.stat_result) -> _State:
    attributes = getattr(value, "st_file_attributes", 0)
    state_type = (
        _WindowsDirectoryState if os.name == "nt" and stat.S_ISDIR(value.st_mode) else _State
    )
    return state_type(
        value.st_mode,
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        attributes,
        attributes,
    )


def _is_link(value: _State) -> bool:
    return stat.S_ISLNK(value.mode) or bool(
        (value.attributes | value.comparison_attributes)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _path_state(path: Path) -> _State:
    """保留 Python 原始属性；Windows 比较项统一取安全元数据句柄的 FileBasicInfo。

    CPython 3.14.7 路径快路径来自 FileStatBasicByNameInfo，fstat 的原始
    属性却来自 BY_HANDLE_FILE_INFORMATION；不能将二者无条件逐位比较。
    不屏蔽任何属性位；所有规范属性仍逐位比较，任一来源的 REPARSE 都拒绝。
    """
    observed = _state(path.lstat())
    if (
        os.name == "nt"
        and not _is_link(observed)
        and (stat.S_ISDIR(observed.mode) or stat.S_ISREG(observed.mode))
    ):
        return replace(observed, comparison_attributes=_windows_path_attributes(path))
    return observed


def _handle_state(descriptor: int) -> _State:
    observed = _state(os.fstat(descriptor))
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415 -- Windows 专属句柄。

        return replace(
            observed,
            comparison_attributes=_windows_basic_attributes(msvcrt.get_osfhandle(descriptor)),
        )
    return observed


def _relative_is_valid(path: str) -> bool:
    return bool(path) and not (
        PurePosixPath(path).is_absolute()
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(character in path for character in ("\\", ":", "\x00"))
    )


def _check_components(path: Path) -> None:
    """从卷根检查全部父组件，不能先 resolve 而掩盖链接来源。"""
    for component in (*reversed(path.parents), path):
        if _is_link(_state(component.lstat())):
            raise _ObservationError("link_refused", f"拒绝链接/重解析点组件：{component}")


def _root_path(root: Path) -> Path:
    if ".." in root.parts:
        raise ValueError("安装/材料根不能包含路径穿越组件 '..'")
    return root.absolute()


def classify_path(relative: str) -> str:
    """分类只是文件格式启发式，不声称解析、语义或合法脚本能力。"""
    if not _relative_is_valid(relative):
        raise ValueError(f"不是可登记的相对 POSIX 路径：{relative!r}")
    path = PurePosixPath(relative)
    parts = tuple(part.casefold() for part in path.parts)
    if any(part in {"license", "licenses", "licences", "docs", "documentation"} for part in parts):
        return "documentation"
    if path.name.casefold().startswith(("license", "licence", "copying", "copyright", "readme")):
        return "documentation"
    suffix = path.suffix.casefold()
    for category, suffixes in _CATEGORIES.items():
        if suffix in suffixes:
            return category
    return PDX_RESOURCE_CATEGORIES.get(suffix, "unknown")


def _enumerate(root: Path) -> _Enumeration:
    result = _Enumeration({}, {}, set(), [])
    pending = [(root, ".")]
    seen_directories: set[tuple[int, int]] = set()
    while pending:
        directory, relative = pending.pop()
        try:
            _check_components(directory)
            before = _path_state(directory)
            if not stat.S_ISDIR(before.mode):
                raise _ObservationError("not_directory", "枚举根或目录已不是普通目录")
            identity = (before.device, before.inode)
            if before.inode and identity in seen_directories:
                raise _ObservationError("directory_cycle", "目录身份重复，拒绝目录循环")
            seen_directories.add(identity)
            result.directories[relative] = before
            entries: list[os.DirEntry[str]] = []
            try:
                with os.scandir(directory) as iterator:
                    # 不能 sorted(iterator)：迭代中途异常会丢掉已产出条目。
                    for entry in iterator:
                        entries.append(entry)  # noqa: PERF402 -- 必须保留异常前每个 yield。
            except OSError as error:
                result.blocked.add(relative)
                result.diagnostics.append(
                    _diagnostic("enumeration_failed", relative, f"{type(error).__name__}: {error}")
                )
            for entry in sorted(entries, key=lambda entry: entry.name):
                child_relative = entry.name if relative == "." else f"{relative}/{entry.name}"
                if not _relative_is_valid(child_relative):
                    result.entries[child_relative] = _Entry(
                        "unknown",
                        None,
                        (_diagnostic("invalid_path", child_relative, "schema 无法表示此路径"),),
                    )
                    continue
                try:
                    # Windows DirEntry.stat 的缓存可把 dev/ino 留成 0；权威枚举
                    # 必须重新 lstat，才能与打开句柄的真实身份逐项比较。
                    current = _path_state(Path(entry.path))
                    if _is_link(current):
                        problem = _diagnostic(
                            "link_refused", child_relative, "保留存在性，不读取也不遍历目标"
                        )
                        result.entries[child_relative] = _Entry("link", current, (problem,))
                    elif stat.S_ISDIR(current.mode):
                        pending.append((Path(entry.path), child_relative))
                    elif stat.S_ISREG(current.mode):
                        result.entries[child_relative] = _Entry("file", current)
                    else:
                        problem = _diagnostic(
                            "special_file_refused", child_relative, "非普通文件不读取"
                        )
                        result.entries[child_relative] = _Entry("special", current, (problem,))
                except (OSError, _ObservationError) as error:
                    code = error.code if isinstance(error, _ObservationError) else "stat_failed"
                    problem = _diagnostic(code, child_relative, f"{type(error).__name__}: {error}")
                    result.entries[child_relative] = _Entry("unknown", None, (problem,))
            _check_components(directory)
            after = _path_state(directory)
            if before != after:
                result.diagnostics.append(
                    _directory_diagnostic(
                        "directory_changed", relative, _state_change_details(before, after)
                    )
                )
        except (OSError, _ObservationError) as error:
            code = error.code if isinstance(error, _ObservationError) else "enumeration_failed"
            result.blocked.add(relative)
            result.diagnostics.append(
                _diagnostic(code, relative, f"{type(error).__name__}: {error}")
            )
    for observed_entry in result.entries.values():
        result.diagnostics.extend(observed_entry.diagnostics)
    folded: dict[str, str] = {}
    for relative in sorted((*result.entries, *result.directories)):
        previous = folded.setdefault(relative.casefold(), relative)
        if previous != relative:
            result.diagnostics.append(
                _diagnostic("case_collision", relative, f"与 {previous!r} 大小写折叠冲突")
            )
    return result


@lru_cache(maxsize=1)
def _windows_kernel32() -> Any:
    """标准 Windows API；动态 ctypes 函数签名仅在本边界设置一次。"""
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    library.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    library.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    library.CreateFileW.restype = wintypes.HANDLE
    library.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    library.GetFileInformationByHandleEx.restype = wintypes.BOOL
    library.CloseHandle.argtypes = (wintypes.HANDLE,)
    library.CloseHandle.restype = wintypes.BOOL
    return library


class _WindowsBasicInfo(ctypes.Structure):
    _fields_ = [
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("FileAttributes", wintypes.DWORD),
    ]


def _windows_handle_path(handle: int) -> str:
    """规范化真实 Windows 句柄路径；元数据和内容句柄共用。"""
    query = _windows_kernel32().GetFinalPathNameByHandleW
    length = query(handle, None, 0, 0)  # FILE_NAME_NORMALIZED | VOLUME_NAME_DOS
    if not length:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(length + 1)
    written = query(handle, buffer, len(buffer), 0)
    if not written:
        raise ctypes.WinError(ctypes.get_last_error())
    if written >= len(buffer):
        raise _ObservationError("opened_path_unverifiable", "句柄路径查询期间长度变化")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    return value.removeprefix("\\\\?\\")


def _windows_final_path(descriptor: int) -> str:
    """在任何 read 前查询实际打开对象，而非再次检查可被替换的路径。"""
    import msvcrt  # noqa: PLC0415 -- Windows 专属，POSIX 不导入。

    return _windows_handle_path(msvcrt.get_osfhandle(descriptor))


def _windows_basic_attributes(handle: int) -> int:
    """唯一可比较属性源：GetFileInformationByHandleEx(FileBasicInfo)。"""
    value = _WindowsBasicInfo()
    if not _windows_kernel32().GetFileInformationByHandleEx(
        handle, 0, ctypes.byref(value), ctypes.sizeof(value)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(value.FileAttributes)


def _windows_path_attributes(path: Path) -> int:
    """只读元数据打开，不跟随末级 reparse，核真实路径后取得规范属性。

    FILE_READ_ATTRIBUTES；FILE_SHARE_READ|WRITE|DELETE；OPEN_EXISTING；
    FILE_FLAG_OPEN_REPARSE_POINT|BACKUP_SEMANTICS，允许普通目录元数据查询。
    """
    kernel = _windows_kernel32()
    handle = kernel.CreateFileW(str(path), 0x80, 0x7, None, 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attributes = _windows_basic_attributes(handle)
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise _ObservationError("link_refused", "元数据句柄属于重解析点，拒绝取作普通文件属性")
        actual = _windows_handle_path(handle)
        if os.path.normcase(os.path.normpath(actual)) != os.path.normcase(str(path)):
            raise _ObservationError(
                "opened_path_mismatch",
                f"元数据句柄实际路径 {actual!r} 不等于授权路径 {str(path)!r}",
            )
        return attributes
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def _open_verified(path: Path) -> int:
    """返回在原字节读取前已核验边界的文件描述符；失败由此处关闭。

    Windows 以实际打开句柄的规范路径核对精确授权路径，父目录在组件检查
    后被 junction 替换时也不能进入读取。POSIX 从卷根开始逐组件使用固定
    dir_fd 与 O_NOFOLLOW，已打开目录不会重新按可替换的字符串路径寻址。
    """
    if os.name == "nt":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            try:
                actual = _windows_final_path(descriptor)
            except (OSError, AttributeError) as error:
                raise _ObservationError(
                    "opened_path_unverifiable", f"无法核验实际句柄路径：{error}"
                ) from error
            if os.path.normcase(os.path.normpath(actual)) != os.path.normcase(str(path)):
                raise _ObservationError(
                    "opened_path_mismatch", f"实际句柄路径 {actual!r} 不等于授权路径 {str(path)!r}"
                )
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if (
        os.name == "posix"
        and _POSIX_DIR_FD_OPEN_SUPPORTED
        and isinstance(nofollow, int)
        and isinstance(directory_flag, int)
        and isinstance(nonblock, int)
    ):
        directory_flags = os.O_RDONLY | directory_flag | nofollow
        with ExitStack() as opened_directories:
            directory = os.open(path.anchor, directory_flags)
            opened_directories.callback(os.close, directory)
            for component in path.parts[1:-1]:
                directory = os.open(component, directory_flags, dir_fd=directory)
                opened_directories.callback(os.close, directory)
            return os.open(path.name, os.O_RDONLY | nofollow | nonblock, dir_fd=directory)
    raise _ObservationError(
        "secure_open_unsupported", "此平台缺少可验证的安全打开能力，拒绝原字节读取"
    )


def _object_identity(state: _State) -> tuple[int, int, int, int, int, int]:
    # Windows 以路径后缀合成执行权限，且路径/句柄 API 的 ctime 含义
    # 不完全相同；跨 API 只比真实身份、类型、大小、mtime 和属性。
    return (
        state.device,
        state.inode,
        stat.S_IFMT(state.mode),
        state.size,
        state.modified_ns,
        state.comparison_attributes,
    )


@contextmanager
def open_inventory_source(root: Path, relative: str) -> Iterator[BinaryIO]:
    """唯一只读来源入口：打开前授权路径检查、读取前句柄核验、退出漂移核验。

    root 是调用方显式授权的目录；relative 必须是安全相对 POSIX 路径。
    context 只提供 rb 流，不创建/写入文件，调用方不得自行 close/detach。
    无安全打开能力/路径歧义/漂移抛 InputContractError；真实权限、打开或
    读取 OSError 原样传递。这里只核验一次读取会话，不创建 epoch 或快照。
    """
    if not _relative_is_valid(relative):
        raise InputContractError("invalid_path", f"不是安全相对 POSIX 路径：{relative!r}")
    try:
        root = _root_path(root)
    except ValueError as error:
        raise InputContractError("invalid_path", str(error)) from error
    _check_components(root)
    root_before = _path_state(root)
    if not stat.S_ISDIR(root_before.mode):
        raise _ObservationError("not_directory", "授权根必须是普通目录")
    path = root.joinpath(*relative.split("/"))
    _check_components(path)
    before = _path_state(path)
    if not stat.S_ISREG(before.mode):
        raise _ObservationError("file_type_changed", "读取前已不是普通文件")
    descriptor = _open_verified(path)
    try:
        opened = _handle_state(descriptor)
        if _is_link(opened):
            raise _ObservationError("link_refused", "已打开内容句柄报告重解析点")
        if _object_identity(opened) != _object_identity(before):
            raise _ObservationError("file_changed", "路径与已打开文件身份不符")
    except BaseException:
        os.close(descriptor)
        raise
    try:
        source_stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with source_stream as stream:
        try:
            yield stream
        finally:
            finished = _handle_state(stream.fileno())
            _check_components(path)
            after = _path_state(path)
            root_after = _path_state(root)
            if (
                opened != finished
                or before != after
                or (root_before.device, root_before.inode) != (root_after.device, root_after.inode)
            ):
                raise _ObservationError("file_changed", "读取会话期间文件状态或授权根身份变化")


def _hash_regular(root: Path, relative: str, chunk_size: int) -> tuple[int, str, _State]:
    """仅复用公共安全来源入口，哈希不维护另一套来源打开逻辑。"""
    with open_inventory_source(root, relative) as stream:
        opened = _handle_state(stream.fileno())
        digest = hashlib.sha256()
        count = 0
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            count += len(chunk)
        if count != opened.size:
            raise _ObservationError("file_changed", "读取字节数与已打开原件大小不符")
    return count, digest.hexdigest(), _path_state(root / relative)


def _record(
    relative: str, entry: _Entry, layer: str, root: Path, chunk_size: int, read_authorized: bool
) -> InventoryRecord:
    size = entry.state.size if entry.kind == "file" and entry.state is not None else None
    sha256 = None
    read_status: Literal["read", "failed", "not_read"] = "not_read"
    diagnostics = entry.diagnostics
    if not read_authorized:
        diagnostics += (
            _diagnostic("read_not_authorized", relative, "仅登记可见路径，不读取材料原字节"),
        )
    elif entry.kind == "file":
        try:
            size, sha256, observed = _hash_regular(root, relative, chunk_size)
            read_status = "read"
            if observed != entry.state:
                diagnostics += (
                    _diagnostic("file_changed", relative, "枚举与读取之间文件状态变化"),
                )
        except (OSError, _ObservationError) as error:
            code = error.code if isinstance(error, _ObservationError) else "read_failed"
            diagnostics += (_diagnostic(code, relative, f"{type(error).__name__}: {error}"),)
            read_status = "failed"
    return InventoryRecord(
        relative,
        size,
        sha256,
        classify_path(relative),
        layer,
        read_status,
        "not_attempted",
        None,
        diagnostics,
        (),
        (),
        (),
        "partial",
    )


def _scan(
    root: Path,
    *,
    source_layer: str,
    authorization: str,
    installation: bool,
    chunk_size: int,
    read_authorized: bool = True,
) -> InventoryScan:
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("chunk_size 必须是正整数")
    root = _root_path(root)
    start = _enumerate(root)
    records = {
        relative: _record(relative, entry, source_layer, root, chunk_size, read_authorized)
        for relative, entry in sorted(start.entries.items())
        if _relative_is_valid(relative)
    }
    diagnostics = list(start.diagnostics)
    for relative, record in records.items():
        if record.read_status != "read":
            continue
        try:
            size, digest, _ = _hash_regular(root, relative, chunk_size)
            if (size, digest) != (record.size, record.sha256):
                raise _ObservationError("content_changed", "两次流式读取的原字节摘要不同")
        except (OSError, _ObservationError) as error:
            code = (
                error.code if isinstance(error, _ObservationError) else "verification_read_failed"
            )
            problem = _diagnostic(code, relative, f"{type(error).__name__}: {error}")
            records[relative] = replace(record, diagnostics=(*record.diagnostics, problem))
    end = _enumerate(root)
    diagnostics.extend(end.diagnostics)
    for relative in sorted(start.entries.keys() | end.entries.keys()):
        initial, final = start.entries.get(relative), end.entries.get(relative)
        if initial == final:
            continue
        code = (
            "path_added" if initial is None else "path_removed" if final is None else "path_changed"
        )
        problem = _diagnostic(code, relative, "开始/结束枚举的路径或状态不同")
        diagnostics.append(problem)
        if initial is None and final is not None and _relative_is_valid(relative):
            records[relative] = InventoryRecord(
                relative,
                final.state.size if final.kind == "file" and final.state else None,
                None,
                classify_path(relative),
                source_layer,
                "not_read",
                "not_attempted",
                None,
                (*final.diagnostics, problem),
                (),
                (),
                (),
                "partial",
            )
        elif relative in records:
            record = records[relative]
            records[relative] = replace(record, diagnostics=(*record.diagnostics, problem))
    if start.directories != end.directories:
        diagnostics.append(
            _directory_diagnostic(
                "directory_set_changed",
                ".",
                {
                    "added": {
                        path: asdict(end.directories[path])
                        for path in sorted(end.directories.keys() - start.directories.keys())
                    },
                    "removed": {
                        path: asdict(start.directories[path])
                        for path in sorted(start.directories.keys() - end.directories.keys())
                    },
                    "changed": {
                        path: _state_change_details(start.directories[path], end.directories[path])
                        for path in sorted(start.directories.keys() & end.directories.keys())
                        if start.directories[path] != end.directories[path]
                    },
                },
            )
        )
    if installation and "game" not in start.directories:
        diagnostics.append(
            _diagnostic(
                "missing_installation_root",
                "game",
                "安装根缺少普通 game 目录，拒绝把内容子树冒充全安装",
            )
        )
    ordered = tuple(records[path] for path in sorted(records))
    for record in ordered:
        diagnostics.extend(record.diagnostics)
    diagnostics = list(dict.fromkeys(diagnostics))
    try:
        denominator = file_set_digest(ordered)
    except InputContractError:
        denominator = None
    observed_paths = tuple(sorted(start.entries.keys() | end.entries.keys()))
    if len(ordered) != len(observed_paths) or any(
        problem.code == "case_collision" for problem in diagnostics
    ):
        denominator = None
    status: ScanStatus = "complete"
    if diagnostics:
        status = "partial" if start.directories or ordered else "failed"
    known_sizes = [record.size for record in ordered if record.size is not None]
    summary = InventorySummary(
        len(observed_paths),
        sum(
            any(
                snapshot.entries.get(path, _Entry("unknown", None)).kind == "file"
                for snapshot in (start, end)
            )
            for path in observed_paths
        ),
        sum(known_sizes),
        max(known_sizes, default=0),
        tuple(sorted(Counter(record.category for record in ordered).items())),
        tuple(
            sorted(
                Counter(
                    record.path.split("/")[0] if "/" in record.path else "." for record in ordered
                ).items()
            )
        ),
    )
    return InventoryScan(
        root.as_posix(),
        source_layer,
        authorization,
        installation,
        ordered,
        tuple(sorted(start.directories.keys() | end.directories.keys())),
        observed_paths,
        tuple(sorted(start.blocked | end.blocked)),
        tuple(diagnostics),
        status,
        denominator,
        summary,
    )


def inventory_installation(installation: Path, *, chunk_size: int = _CHUNK_SIZE) -> InventoryScan:
    """枚举调用方指定的安装根全部入口；不发现路径、不读取外部材料。"""
    return _scan(
        installation,
        source_layer="installation",
        authorization="installation_read_only",
        installation=True,
        chunk_size=chunk_size,
    )


def inventory_material(
    root: Path,
    *,
    source_layer: str,
    authorization: str,
    read_authorized: bool,
    chunk_size: int = _CHUNK_SIZE,
) -> InventoryScan:
    """单独盘点调用方明确指定的 docs/Mod/存档/日志等来源。

    无读取授权时仅枚举并保留未读行。调用方仍需有目录枚举权限；本 API
    不授予复制/公开权限，也不把外部来源混入原版安装分母。
    """
    if not source_layer.strip() or source_layer.casefold() == "installation":
        raise ValueError("外部材料必须声明独立来源，不能使用 installation")
    if not authorization.strip() or type(read_authorized) is not bool:
        raise ValueError("必须显式声明材料授权说明和读取授权布尔值")
    return _scan(
        root,
        source_layer=source_layer,
        authorization=authorization,
        installation=False,
        chunk_size=chunk_size,
        read_authorized=read_authorized,
    )


@dataclass(frozen=True, slots=True)
class DirectorySummary:
    """只计直接子文件，所有目录相加恰好对上记录总数与已知字节。"""

    path: str
    file_count: int
    known_bytes: int
    category_counts: tuple[tuple[str, int], ...]
    blocked: bool


def summarize_directories(scan: InventoryScan) -> tuple[DirectorySummary, ...]:
    """保留空目录及失败前沿；blocked 不代表已证明子树没有文件。"""
    buckets: dict[str, list[InventoryRecord]] = {
        path: [] for path in (*scan.directories, *scan.blocked_directories)
    }
    for record in scan.records:
        parent = PurePosixPath(record.path).parent.as_posix()
        buckets.setdefault(parent, []).append(record)
    return tuple(
        DirectorySummary(
            path,
            len(records),
            sum(record.size for record in records if record.size is not None),
            tuple(sorted(Counter(record.category for record in records).items())),
            path in scan.blocked_directories,
        )
        for path, records in sorted(buckets.items())
    )


@dataclass(frozen=True, slots=True)
class LegacyScopeDisposition:
    path: str
    config_status: Literal["scriptable", "asset", "ignored", "excluded", "outside"]
    version_status: Literal["included", "excluded_suffix", "outside"]
    reasons: tuple[str, ...]


def compare_legacy_scope(scan: InventoryScan) -> tuple[LegacyScopeDisposition, ...]:
    """按现有常量/生产判定逐路径解释旧范围，不过滤本次分母。

    这里只评价旧范围的静态选择规则；不运行旧 scanner，也不宣称其读取或
    解析一定成功。包含这次因 schema 路径限制而不能构造合同的存在性行。
    """
    # 延迟导入避免纯枚举依赖 PDX parser 初始化；规则仍取唯一当前来源。
    from . import config  # noqa: PLC0415
    from .situated.version_inventory import (  # noqa: PLC0415
        CONTENT_ROOTS,
        IDENTITY_PATHS,
        TEXT_EXTENSIONS,
    )

    if not scan.is_installation:
        raise ValueError("旧安装范围只能与独立原版安装分母对账")
    rows = []
    for relative in scan.observed_paths:
        parts = PurePosixPath(relative).parts
        within_content = len(parts) > 1 and parts[0] in CONTENT_ROOTS
        content_parts = parts[1:] if within_content else parts
        suffix = PurePosixPath(relative).suffix.lower()
        status: Literal["scriptable", "asset", "ignored", "excluded", "outside"] = "outside"
        if content_parts and content_parts[0] in config.IGNORED_DIRS:
            status = "ignored"
        elif within_content and config.is_excluded(content_parts):
            status = "excluded"
        elif within_content and config.is_scriptable(content_parts, suffix):
            status = "scriptable"
        elif within_content and content_parts[0] in config.ASSET_DIRS:
            status = "asset"
        version: Literal["included", "excluded_suffix", "outside"] = "outside"
        if relative in IDENTITY_PATHS or (within_content and suffix in TEXT_EXTENSIONS):
            version = "included"
        elif within_content:
            version = "excluded_suffix"
        reasons = (
            f"config.py: SCRIPTABLE_DIRS/SCRIPTABLE_SUFFIXES, ASSET_DIRS, IGNORED_DIRS, EXCLUDED_SUBTREES -> {status}",
            f"situated/version_inventory.py: CONTENT_ROOTS/TEXT_EXTENSIONS/IDENTITY_PATHS -> {version}",
            "ENG-01: 存在性保留；旧范围处置不缩减分母，研究价值与解析另行评价",
        )
        rows.append(LegacyScopeDisposition(relative, status, version, reasons))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class CapacityEstimate:
    source_bytes: int
    largest_file_bytes: int
    staging_bytes: int
    retry_bytes: int
    recovery_bytes: int
    streaming_scratch_bytes: int
    metadata_reserve_bytes: int
    compression_saving_bytes: int
    lower_bound_bytes: int
    required_bytes: int | None
    diagnostics: tuple[Diagnostic, ...]


def estimate_capacity(
    scan: InventoryScan,
    *,
    staging_copies: int = 1,
    retry_copies: int = 1,
    recovery_copies: int = 1,
    metadata_reserve_bytes: int = 0,
) -> CapacityEstimate:
    """无压缩收益的字节容量预算；不完整扫描只给已知字节的下界。

    一个原件全集 + staging/retry/recovery 各指定份数 + 一个最大文件的
    临时空间。元数据/文件系统分配开销必须由调用方另给 reserve；不承诺
    估算等于实际占盘，也不申请、预留或写入目标卷。
    """
    amounts = (staging_copies, retry_copies, recovery_copies, metadata_reserve_bytes)
    if any(type(value) is not int or value < 0 for value in amounts):
        raise ValueError("副本数和元数据保留字节必须是非负整数")
    total = scan.summary.known_bytes
    largest = scan.summary.largest_file_bytes
    staging, retry, recovery = (total * copies for copies in amounts[:3])
    lower_bound = total + staging + retry + recovery + largest + metadata_reserve_bytes
    problems = []
    required: int | None = lower_bound
    if scan.scan_status != "complete" or any(record.size is None for record in scan.records):
        required = None
        problems.append(
            _diagnostic(
                "capacity_incomplete", ".", "存在未读、目录前沿或输入漂移，不能签署充分容量"
            )
        )
    if metadata_reserve_bytes == 0:
        problems.append(
            _diagnostic("metadata_reserve_unset", ".", "尚未预算元数据、分配单元和文件系统额外空间")
        )
    return CapacityEstimate(
        total,
        largest,
        staging,
        retry,
        recovery,
        largest,
        metadata_reserve_bytes,
        0,
        lower_bound,
        required,
        tuple(problems),
    )


@dataclass(frozen=True, slots=True)
class CapacityTarget:
    path: str
    volume: str | None
    available_bytes: int | None
    enough_for_estimate: bool | None
    write_access: Literal["unverified"]
    copy_authorized: bool
    access_boundary: str
    diagnostics: tuple[Diagnostic, ...]


def inspect_capacity_target(
    target: Path,
    estimate: CapacityEstimate,
    *,
    copy_authorized: bool,
    access_boundary: str,
) -> CapacityTarget:
    """只读检查一个既有候选本地目录，不以 os.access 冒充实际写入证明。

    卷身份采用平台 anchor；无 anchor 的 POSIX 平台另记 st_dev。调用方
    声明的复制边界原样保留，不推断第三方授权，也不创建探针或目录。
    """
    if type(copy_authorized) is not bool or not access_boundary.strip():
        raise ValueError("必须显式声明复制授权及访问/复制边界")
    target = _root_path(target)
    available = None
    volume = None
    problems = []
    try:
        if str(target).startswith(("\\\\", "//")):
            raise _ObservationError("nonlocal_target", "候选目标必须是本地卷，不能推断远程访问边界")
        _check_components(target)
        current = target.lstat()
        if not stat.S_ISDIR(current.st_mode):
            raise _ObservationError("not_directory", "候选目标必须是既有普通目录")
        volume = f"{target.anchor} (device={current.st_dev})"
        available = shutil.disk_usage(target).free
    except (OSError, _ObservationError) as error:
        code = error.code if isinstance(error, _ObservationError) else "target_inspection_failed"
        problems.append(_diagnostic(code, target.as_posix(), f"{type(error).__name__}: {error}"))
    enough = None
    if available is not None and estimate.required_bytes is not None:
        enough = available >= estimate.required_bytes
    return CapacityTarget(
        target.as_posix(),
        volume,
        available,
        enough,
        "unverified",
        copy_authorized,
        access_boundary,
        tuple(problems),
    )


def bind_inventory(scan: InventoryScan, identity: InputIdentity) -> InputInventory:
    """只绑定调用方提供的真实身份；本模块不合成 InputIdentity 或 epoch。

    返回合同始终 partial，因为本切片没有 raw 保全或解析/能力证明。
    此绑定不替代 validate_handoff 或对输入身份真实性的独立核验。
    """
    dumps_contract(identity)
    if not scan.is_installation or scan.file_set_sha256 is None:
        raise ValueError("只有无路径歧义的原版安装分母可以绑定输入身份")
    if (
        identity.file_count != len(scan.records)
        or identity.file_set_sha256 != scan.file_set_sha256
        or identity.installation_root != scan.root
    ):
        raise ValueError("调用方输入身份与本次安装根或分母不匹配")
    missing = _diagnostic(
        "raw_not_preserved", ".", "字节可读不等于 raw 已保全；完整 epoch 尚未建立"
    )
    return InputInventory(identity.epoch_id, scan.records, "partial", (*scan.diagnostics, missing))
