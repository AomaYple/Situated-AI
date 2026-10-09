"""``-n auto`` 的内存护栏：只测预算计算，不启动 worker。"""

from __future__ import annotations

import pytest
from conftest import pytest_xdist_auto_num_workers

from pdx import parallel

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate_worker_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """外部 CI worker 配置不能污染预算与覆盖优先级的单元测试。"""
    monkeypatch.delenv("SITAI_XDIST_WORKERS", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)


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


def test_项目覆盖变量优先于xdist官方变量(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITAI_XDIST_WORKERS", "2")
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "3")
    assert parallel.auto_worker_count(cpu=16, available=2048) == 2


def test_xdist官方覆盖变量在无游戏树时仍然有效(
    monkeypatch: pytest.MonkeyPatch, pytestconfig: pytest.Config
) -> None:
    monkeypatch.setattr("conftest.GAME_OK", False)
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "3")
    monkeypatch.setattr(parallel, "cpu_workers", lambda: 16)
    monkeypatch.setattr(parallel, "available_mib", lambda: 2048)
    assert pytest_xdist_auto_num_workers(pytestconfig) == 3


@pytest.mark.parametrize("reader", [parallel.cpu_workers, parallel.available_mib])
def test_psutil权限异常时资源查询安全回退(monkeypatch: pytest.MonkeyPatch, reader) -> None:
    if reader is parallel.cpu_workers:
        monkeypatch.setattr(
            parallel.psutil,
            "cpu_count",
            lambda **_kwargs: (_ for _ in ()).throw(parallel.psutil.AccessDenied(1)),
        )
        assert reader() >= 1
    else:
        monkeypatch.setattr(
            parallel.psutil,
            "virtual_memory",
            lambda: (_ for _ in ()).throw(parallel.psutil.AccessDenied(1)),
        )
        assert reader() == 0
