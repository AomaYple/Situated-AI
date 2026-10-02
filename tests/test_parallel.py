"""``-n auto`` 的内存护栏：只测预算计算，不启动 worker。"""

from __future__ import annotations

import pytest

from pdx import parallel

pytestmark = pytest.mark.unit


def test_内存不足时至少保留一个worker() -> None:
    assert parallel.auto_worker_count(cpu=16, available=2048) == 1


def test_auto同时受可用内存和cpu限制() -> None:
    # (6144 - 2048) / 1536 = 2，CPU 还有余量。
    assert parallel.auto_worker_count(cpu=16, available=6144) == 2
    assert parallel.auto_worker_count(cpu=2, available=32_768) == 2


def test_显式worker数优先于预算(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITAI_XDIST_WORKERS", "7")
    assert parallel.auto_worker_count(cpu=2, available=2048) == 7


def test_xdist官方覆盖变量仍然有效(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "3")
    assert parallel.auto_worker_count(cpu=16, available=2048) == 3
