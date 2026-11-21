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
    """用当前进程可用的逻辑 CPU 数约束物理核心启发值。"""
    try:
        process_count = os.process_cpu_count()
    except OSError:  # pragma: no cover - 系统拒绝查询
        process_count = None

    # Windows 上标准库可能返回宿主逻辑 CPU 数，仍需核对进程亲和性。
    try:
        read_affinity = getattr(psutil.Process(), "cpu_affinity", None)
        affinity_count = len(read_affinity()) if callable(read_affinity) else 0
    except AttributeError, NotImplementedError, OSError, psutil.Error:
        affinity_count = 0
    if affinity_count:
        process_count = min(process_count, affinity_count) if process_count else affinity_count

    try:
        physical_count = psutil.cpu_count(logical=False)
    except ImportError, OSError, psutil.Error:  # pragma: no cover - 系统拒绝查询
        physical_count = None

    if physical_count and process_count:
        return min(physical_count, process_count)
    if count := physical_count or process_count:
        return count

    try:
        count = psutil.cpu_count()
    except ImportError, OSError, psutil.Error:  # pragma: no cover - 系统拒绝查询
        count = None
    return count or os.cpu_count() or 1


def available_mib() -> int:
    """读取当前可用物理内存，失败时返回 0（交给调用方保守处理）。"""
    try:
        return max(0, int(psutil.virtual_memory().available // (1024 * 1024)))
    except ImportError, OSError, psutil.Error:  # pragma: no cover - 系统拒绝查询
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
