"""``pdx.console`` 的用例（此前是唯一没有专门测试的模块）。

为什么值得测：这是**进程入口处的编码兜底**，一旦它自己失效，所有命令在 GBK 控制台上
都会以 ``UnicodeEncodeError`` 崩掉（模块文档里记了三种 rich 写法也救不回来的实测）。
覆盖点正好是那几条容易漏的分支：流没有 ``reconfigure``（``pythonw`` 下是 ``None``）、
``reconfigure`` 抛 ``ValueError``/``OSError``（流已关闭 / 管道不支持）、以及幂等。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from pdx import console

pytestmark = pytest.mark.unit


class _Stream:
    """记账用的假流：记下每次 `reconfigure` 的参数。"""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, str]] = []
        self._raises = raises

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises


def test_两个流都被切到_utf8_且_errors_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = _Stream(), _Stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    console.enable_utf8_stdio()

    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_没有_reconfigure_的流静默跳过(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pythonw` 下 `sys.stdout` 是 `None`；pytest 的 capture 对象也可能没有这个方法。"""
    out = _Stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", None)  # None 连 getattr 都拿不到 reconfigure

    console.enable_utf8_stdio()  # 不抛就是过

    assert out.calls, "另一个流仍然要被处理"


def test_流对象没有该方法也不炸(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", SimpleNamespace())  # 没有 reconfigure
    monkeypatch.setattr(sys, "stderr", SimpleNamespace())
    console.enable_utf8_stdio()


@pytest.mark.parametrize("exc", [ValueError("stream closed"), OSError("pipe")])
def test_reconfigure_抛错被吞掉(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """流已关闭 / 管道不支持改编码 —— 这是**显示层**的失败，不该升级成任务失败。"""
    out, err = _Stream(raises=exc), _Stream(raises=exc)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    console.enable_utf8_stdio()  # 不抛就是过

    assert len(out.calls) == 1
    assert len(err.calls) == 1, "每个流各试一次"


def test_幂等(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = _Stream(), _Stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    console.enable_utf8_stdio()
    console.enable_utf8_stdio()

    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}] * 2, "调用两次不改变结果"
