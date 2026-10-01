"""平台专属仪器的明确失败边界；纯解析和图像处理不依赖 Win32。"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import NoReturn


class WindowsOnlyError(RuntimeError):
    """请求了本平台不能提供的 Windows 实机操作。"""


class UnavailableWindowsModule(ModuleType):
    """允许模块装配和纯函数导入；首次真实访问系统 API 时明确报错。"""

    def __getattr__(self, name: str) -> NoReturn:
        raise WindowsOnlyError(
            f"{self.__name__}.{name} 是 Windows 专属实机接口；当前平台 {sys.platform}。"
            "解析、生成、离线校验和图像处理可正常使用。"
        )


def require_windows(operation: str) -> None:
    if sys.platform != "win32":
        raise WindowsOnlyError(f"{operation} 仅支持 Windows 实机；当前平台 {sys.platform}")
