"""本机同卷目录的独占改名。"""

import ctypes
import errno
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def rename_no_replace(
    source: Path,
    destination: Path,
    *,
    src_dir_fd: int | None = None,
    dst_dir_fd: int | None = None,
) -> None:
    """目标已存在或文件系统缺少独占改名能力时拒绝。"""
    if sys.platform == "win32":
        if src_dir_fd is not None or dst_dir_fd is not None:
            raise ValueError("Windows 独占改名须使用完整路径")
        # Python 使用 MoveFileExW，未设置 REPLACE_EXISTING 或 COPY_ALLOWED。
        source.rename(destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "linux":
        function = getattr(libc, "renameat2", None)
        cwd_fd, flags = -100, 0x1  # AT_FDCWD, RENAME_NOREPLACE
    elif sys.platform == "darwin":
        function = getattr(libc, "renameatx_np", None)
        cwd_fd, flags = -2, 0x4  # AT_FDCWD, RENAME_EXCL
    else:
        function = None
        cwd_fd, flags = 0, 0
    if function is None:
        raise OSError(errno.ENOTSUP, "平台缺少独占目录改名")
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    if function(
        cwd_fd if src_dir_fd is None else src_dir_fd,
        os.fsencode(source if src_dir_fd is None else source.name),
        cwd_fd if dst_dir_fd is None else dst_dir_fd,
        os.fsencode(destination if dst_dir_fd is None else destination.name),
        flags,
    ):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
