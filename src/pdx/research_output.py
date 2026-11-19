"""Publish derived evidence to an empty local destination as one directory."""

import ctypes
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import ExitStack, contextmanager, suppress
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from .committed_raw import RawEvidenceError
from .native_rename import rename_no_replace

if TYPE_CHECKING:
    from collections.abc import Iterator

_POSIX_API: Any = os


def _absolute(value: Path) -> Path:
    if ".." in value.parts:
        raise RawEvidenceError("invalid_target", "目标路径不能包含 '..'")
    return value.absolute()


def _link(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, "st_file_attributes", 0) & 0x400)


def _windows_library() -> Any:
    if sys.platform != "win32":
        raise OSError("Windows 原生句柄 API 不可用")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    kernel.GetDriveTypeW.restype = wintypes.UINT
    return kernel


def _windows_last_error() -> OSError:
    if sys.platform != "win32":
        return OSError("Windows 原生句柄 API 不可用")
    return ctypes.WinError(ctypes.get_last_error())


def _windows_path(kernel: Any, handle: int) -> str:
    count = kernel.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not count:
        raise _windows_last_error()
    buffer = ctypes.create_unicode_buffer(count + 1)
    written = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if not written or written >= len(buffer):
        raise RawEvidenceError("unverifiable_target", "目标句柄路径查询失败或变化")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    return value.removeprefix("\\\\?\\")


_LINUX_LOCAL_FILESYSTEMS = frozenset(
    {
        "ext2",
        "ext3",
        "ext4",
        "xfs",
        "btrfs",
        "zfs",
        "tmpfs",
        "ramfs",
        "overlay",
        "vfat",
        "exfat",
        "ntfs",
        "ntfs3",
        "fuseblk",
        "f2fs",
    }
)
_DARWIN_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"


def _linux_mount_is_local(root: Path, mountinfo: str) -> bool:
    """Use the deepest matching mount, rejecting unknown or conflicting types."""
    matches: dict[int, set[str]] = {}
    for line in mountinfo.splitlines():
        head, separator, tail = line.partition(" - ")
        fields, filesystem = head.split(), tail.split()
        if not separator or len(fields) < 6 or not filesystem:
            return False
        mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4]))
        if root.is_relative_to(mount):
            matches.setdefault(len(mount.parts), set()).add(filesystem[0])
    return bool(matches) and matches[max(matches)] <= _LINUX_LOCAL_FILESYSTEMS


def _darwin_volume_is_local(root: Path) -> bool:
    """Query Apple's public kCFURLVolumeIsLocalKey, which is a CFBoolean."""
    try:
        framework = ctypes.CDLL(_DARWIN_CORE_FOUNDATION)
        resource_key = ctypes.c_void_p.in_dll(framework, "kCFURLVolumeIsLocalKey")
        create_url = framework.CFURLCreateFromFileSystemRepresentation
        copy_property = framework.CFURLCopyResourcePropertyForKey
        get_type = framework.CFGetTypeID
        get_boolean_type = framework.CFBooleanGetTypeID
        get_boolean = framework.CFBooleanGetValue
        release = framework.CFRelease
    except (AttributeError, OSError, ValueError) as error:
        raise RawEvidenceError("unverifiable_target", "无法查询 macOS 目标卷的本地属性") from error

    create_url.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_ubyte)
    create_url.restype = ctypes.c_void_p
    copy_property.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    )
    copy_property.restype = ctypes.c_ubyte
    get_type.argtypes = (ctypes.c_void_p,)
    get_type.restype = ctypes.c_ulong
    get_boolean_type.argtypes = ()
    get_boolean_type.restype = ctypes.c_ulong
    get_boolean.argtypes = (ctypes.c_void_p,)
    get_boolean.restype = ctypes.c_ubyte
    release.argtypes = (ctypes.c_void_p,)
    release.restype = None

    path_bytes = os.fsencode(root)
    url = create_url(None, path_bytes, len(path_bytes), 1)
    if not url:
        raise RawEvidenceError("unverifiable_target", "无法标识 macOS 目标卷")
    value = ctypes.c_void_p()
    try:
        if (
            not resource_key
            or not copy_property(url, resource_key, ctypes.byref(value), None)
            or not value.value
            or get_type(value) != get_boolean_type()
        ):
            raise RawEvidenceError("unverifiable_target", "无法核验 macOS 目标卷是否本地")
        return bool(get_boolean(value))
    finally:
        if value.value:
            release(value)
        release(url)


def _check_local(root: Path) -> None:
    if str(root).startswith(("\\\\", "//")):
        raise RawEvidenceError("nonlocal_target", "拒绝网络目标")
    if sys.platform == "win32":
        if _windows_library().GetDriveTypeW(root.anchor) not in {3, 6}:
            raise RawEvidenceError("nonlocal_target", "目标必须是固定本地卷或内存卷")
    elif sys.platform == "linux":
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        if not _linux_mount_is_local(root, mountinfo):
            raise RawEvidenceError("nonlocal_target", "挂载类型无法证明为本机证据卷")
    elif sys.platform == "darwin":
        if not _darwin_volume_is_local(root):
            raise RawEvidenceError("nonlocal_target", "macOS 目标卷未标为本地")
    else:
        raise RawEvidenceError("unsupported_platform", "平台没有安全证据写入实现")


def validate_local_output(root: Path) -> None:
    """Check the local volume and every Git worktree containing the output."""
    _check_local(root.parent)
    for parent in root.parents:
        git = parent / ".git"
        if git.exists() or git.is_symlink():
            _check_repository_output(root, parent)


def _check_repository_output(root: Path, repository: Path) -> None:
    if root.is_relative_to(repository):
        relative = root.relative_to(repository).as_posix()
        ignored = subprocess.run(
            ["git", "-C", str(repository), "check-ignore", "--quiet", "--", relative + "/"],
            capture_output=True,
            check=False,
        )
        tracked = subprocess.run(
            ["git", "-C", str(repository), "ls-files", "-z", "--", relative],
            capture_output=True,
            check=False,
        )
        if ignored.returncode != 0 or tracked.returncode != 0 or tracked.stdout:
            raise RawEvidenceError("tracked_target", "仓库内证据目标必须被忽略且不含受控文件")


class _DirectoryPins:
    """固定目标目录身份；POSIX 逐组件 dir_fd，Windows 禁写/删除共享句柄。

    Windows 持有每个目录的 FILE_READ_ATTRIBUTES 句柄，仅共享读取，从而
    阻止目录替换和重解析点写入；不是仅依赖 lstat 的先查后写。
    """

    def __init__(self, root: Path, parent: _DirectoryPins | None = None) -> None:
        self.root = root
        self.stack = ExitStack()
        self.directories: dict[Path, tuple[int, int, int]] = (
            {} if parent is None else parent.directories.copy()
        )
        self.kernel: Any
        if parent is not None:
            self.kernel = parent.kernel
        else:
            self.kernel = _windows_library() if sys.platform == "win32" else None

    def __enter__(self) -> Self:
        try:
            for path in (*reversed(self.root.parents), self.root):
                self._pin(path)
        except BaseException:
            self.stack.close()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self.stack.close()

    def _pin(self, path: Path) -> int:
        if path in self.directories:
            return self.directories[path][0]
        before = path.lstat()
        if _link(before) or not stat.S_ISDIR(before.st_mode):
            raise RawEvidenceError("link_refused", f"目标组件不是普通目录：{path}")
        if self.kernel is not None:
            # OPEN_EXISTING | BACKUP_SEMANTICS | OPEN_REPARSE_POINT；禁止 write/delete 共享。
            descriptor = int(self.kernel.CreateFileW(str(path), 0x80, 1, None, 3, 0x02200000, None))
            if descriptor == ctypes.c_void_p(-1).value:
                raise _windows_last_error()
            self.stack.callback(self.kernel.CloseHandle, descriptor)
            actual = _windows_path(self.kernel, descriptor)
            if os.path.normcase(os.path.normpath(actual)) != os.path.normcase(str(path)):
                raise RawEvidenceError("target_changed", "已固定目录句柄不等于授权路径")
        elif os.name == "posix" and all(
            hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW")
        ):
            flags = int(os.O_RDONLY | _POSIX_API.O_DIRECTORY | _POSIX_API.O_NOFOLLOW)
            descriptor = (
                os.open(path, flags)
                if path == path.parent
                else os.open(path.name, flags, dir_fd=self.directories[path.parent][0])
            )
            self.stack.callback(os.close, descriptor)
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise RawEvidenceError("target_changed", "固定目录期间身份发生变化")
        else:
            raise RawEvidenceError("unsupported_platform", "平台缺少安全目录写入能力")
        after = path.lstat()
        if _link(after) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise RawEvidenceError("target_changed", "目录固定前后身份变化")
        self.directories[path] = (descriptor, after.st_dev, after.st_ino)
        return descriptor

    def check(self) -> None:
        for path, (_, device, inode) in self.directories.items():
            current = path.lstat()
            if _link(current) or (current.st_dev, current.st_ino) != (device, inode):
                raise RawEvidenceError("target_changed", f"目标父组件已被替换：{path}")

    def create_member(self, parent: Path, name: str) -> int:
        self.check()
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = (
            os.open(parent / name, flags, 0o600)
            if self.kernel is not None
            else os.open(
                name, flags | _POSIX_API.O_NOFOLLOW, 0o600, dir_fd=self.directories[parent][0]
            )
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RawEvidenceError("special_file_refused", "目标已不是普通文件")
            if self.kernel is not None:
                if sys.platform != "win32":
                    raise OSError("Windows 原生文件句柄 API 不可用")
                import msvcrt  # noqa: PLC0415

                actual = _windows_path(self.kernel, msvcrt.get_osfhandle(descriptor))
                if os.path.normcase(os.path.normpath(actual)) != os.path.normcase(
                    str(parent / name)
                ):
                    raise RawEvidenceError("target_changed", "实际写入句柄越出授权路径")
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor


class LocalEvidenceOutput:
    """Publish a new output using handles to the checked directory identities."""

    def __init__(self, root: Path, pins: _DirectoryPins) -> None:
        self.root = root
        self._pins = pins

    def publish(self, files: tuple[tuple[Path, str], ...], marker: bytes, *, scratch: Path) -> Path:
        pins = self._pins
        pins.check()
        validate_local_output(self.root)
        with _DirectoryPins(scratch) as scratch_pins:
            same_volume = scratch_pins.directories[scratch][1] == pins.directories[pins.root][1]
            # 系统暂存区异卷时，改用通过 Git 忽略核验的同卷兄弟目录。
            with _output_stage(scratch_pins if same_volume else pins) as stage:
                self._publish_stage(stage, files, marker)
        return self.root / "COMPLETE.json"

    @staticmethod
    def _write_stage(
        pins: _DirectoryPins, files: tuple[tuple[Path, str], ...], marker: bytes
    ) -> os.stat_result:
        for source, expected in files:
            digest = hashlib.sha256()
            with (
                source.open("rb") as stream,
                os.fdopen(pins.create_member(pins.root, source.name), "wb") as output,
            ):
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != expected:
                raise RawEvidenceError("write_verification_failed", source.name)

        with os.fdopen(pins.create_member(pins.root, "COMPLETE.json"), "wb") as stream:
            stream.write(marker)
            stream.flush()
            os.fsync(stream.fileno())
            return os.fstat(stream.fileno())

    def _publish_stage(
        self, stage: _DirectoryPins, files: tuple[tuple[Path, str], ...], marker: bytes
    ) -> None:
        payload = stage.root / "payload"
        destination = self._pins
        source_fd = None if stage.kernel is not None else stage.directories[stage.root][0]
        target_fd = (
            None if stage.kernel is not None else destination.directories[destination.root][0]
        )
        _mkdir_output_member(payload, source_fd)
        with ExitStack() as payload_scope:
            payload_pins = payload_scope.enter_context(_DirectoryPins(payload, stage))
            marker_stat = self._write_stage(payload_pins, files, marker)
            handle, device, inode = payload_pins.directories[payload]
            payload_pins.check()
            # Windows 禁止删除共享。MoveFileExW 前关闭 payload 句柄，继续固定私有暂存父目录。
            if source_fd is None:
                payload_scope.close()
            else:
                os.fsync(handle)
            stage.check()
            destination.check()
            _check_output_identity(payload, (device, inode))
            rename_no_replace(payload, self.root, src_dir_fd=source_fd, dst_dir_fd=target_fd)
            try:
                if source_fd is not None and target_fd is not None:
                    os.fsync(source_fd)
                    os.fsync(target_fd)
                destination.check()
                _check_output_identity(self.root, (device, inode))
            except OSError, RawEvidenceError:
                if source_fd is not None:
                    with suppress(FileNotFoundError):
                        current = os.stat("COMPLETE.json", dir_fd=handle, follow_symlinks=False)
                        if os.path.samestat(current, marker_stat):
                            os.unlink("COMPLETE.json", dir_fd=handle)
                            os.fsync(handle)
                raise


def _check_output_identity(path: Path, identity: tuple[int, int]) -> None:
    state = path.lstat()
    if _link(state) or (state.st_dev, state.st_ino) != identity:
        raise RawEvidenceError("target_changed", f"研究目录身份已变化：{path}")


def _mkdir_output_member(path: Path, parent_fd: int | None) -> None:
    if parent_fd is None:
        path.mkdir(mode=0o700)
    else:
        os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)


@contextmanager
def _output_stage(parent: _DirectoryPins) -> Iterator[_DirectoryPins]:
    """用已固定父目录创建私有容器，清理只向容器内操作。"""
    path = parent.root / f".sitai-research-{uuid.uuid4().hex}.tmp"
    validate_local_output(path)
    parent.check()
    parent_fd = None if parent.kernel is not None else parent.directories[parent.root][0]
    _mkdir_output_member(path, parent_fd)
    identity = None
    try:
        with _DirectoryPins(path, parent) as stage:
            handle, device, inode = stage.directories[path]
            if parent_fd is not None:
                state = os.fstat(handle)
                if state.st_uid != _POSIX_API.geteuid() or stat.S_IMODE(state.st_mode) & 0o077:
                    raise RawEvidenceError("target_changed", f"研究暂存目录权限已变化：{path}")
            identity = (device, inode)
            try:
                yield stage
            finally:
                # 只在固定的私有容器内清理尚未发布的 payload。
                payload = path / "payload"
                with suppress(FileNotFoundError):
                    if parent_fd is None:
                        shutil.rmtree(payload)
                    else:
                        shutil.rmtree(payload.name, dir_fd=handle)
    finally:
        if identity is not None:
            with suppress(FileNotFoundError):
                _check_output_identity(path, identity)
                if parent_fd is None:
                    path.rmdir()
                else:
                    os.rmdir(path.name, dir_fd=parent_fd)


@contextmanager
def open_local_evidence_output(root: Path) -> Iterator[LocalEvidenceOutput]:
    """Hold every parent during preparation and reserve the output only at publication."""
    root = _absolute(root)
    with _DirectoryPins(root.parent) as pins:
        pins.check()
        validate_local_output(root)
        pins.check()
        yield LocalEvidenceOutput(root, pins)
