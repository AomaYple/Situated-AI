"""测试并行度的跨平台内存护栏。

pytest-xdist 的 ``-n auto`` 默认只看 CPU 数量。对本项目来说，这会把
全量分析、真实语料和解析缓存同时复制到过多 worker。这里提供一个小而
可测的计算函数，由 ``tests/conftest.py`` 接到 xdist 的 auto worker hook。

默认参数依据仓库现有的 RSS 基线：每个重 worker 预留 1536 MiB，给操作系统、
编辑器和游戏留 2048 MiB。调用方仍可用 ``PYTEST_XDIST_AUTO_NUM_WORKERS``
或 ``SITAI_XDIST_WORKERS`` 显式覆盖，性能基准则继续使用 ``-n0``。
"""

from __future__ import annotations

import os
from typing import Final

import psutil

DEFAULT_RESERVE_MIB: Final = 2_048
DEFAULT_WORKER_MIB: Final = 1_536


def _positive_env(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def cpu_workers() -> int:
    """返回适合作为上限的 CPU worker 数。"""
    try:
        count = psutil.cpu_count(logical=False) or psutil.cpu_count()
    except (ImportError, OSError):  # pragma: no cover - 依赖缺失/系统拒绝查询
        count = os.cpu_count()
    return max(1, count or 1)


def available_mib() -> int:
    """读取当前可用物理内存，失败时返回 0（交给调用方保守处理）。"""
    try:
        return max(0, int(psutil.virtual_memory().available // (1024 * 1024)))
    except (ImportError, OSError):  # pragma: no cover - 依赖缺失/系统拒绝查询
        return 0


def auto_worker_count(
    *,
    cpu: int | None = None,
    available: int | None = None,
    reserve_mib: int = DEFAULT_RESERVE_MIB,
    worker_mib: int = DEFAULT_WORKER_MIB,
) -> int:
    """计算 ``-n auto`` 的 worker 数，同时受 CPU 和内存约束。

    ``available`` / ``cpu`` 参数让预算逻辑可以脱离真实机器做确定性测试。
    显式 ``SITAI_XDIST_WORKERS`` 优先于自动计算；不存在或非法时才走预算。
    """
    explicit = _positive_env("SITAI_XDIST_WORKERS")
    if explicit is None:
        explicit = _positive_env("PYTEST_XDIST_AUTO_NUM_WORKERS")
    if explicit is not None:
        return explicit

    cpu_limit = max(1, cpu if cpu is not None else cpu_workers())
    available_limit = available if available is not None else available_mib()
    if available_limit <= reserve_mib or worker_mib <= 0:
        return 1
    memory_limit = max(1, (available_limit - reserve_mib) // worker_mib)
    return max(1, min(cpu_limit, memory_limit))


__all__ = [
    "DEFAULT_RESERVE_MIB",
    "DEFAULT_WORKER_MIB",
    "auto_worker_count",
    "available_mib",
    "cpu_workers",
]
