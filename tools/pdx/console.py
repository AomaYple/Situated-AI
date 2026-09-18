"""控制台编码兜底。

为什么需要单独一个模块
----------------------
本机（中文 Windows）的控制台代码页是 GBK（cp936），而工具链的输出里有
emoji（``✅`` / ``❌``）与大量中文标点。GBK 表示不了这些码位，写入时会直接抛::

    UnicodeEncodeError: 'gbk' codec can't encode character '\\u2705'

关键在于：**重定向到管道或文件时同样会抛** —— 编码取自控制台代码页，
与 ``isatty()`` 无关。所以不能只对交互式终端做兜底。

为什么不能靠 rich
-----------------
rich 确实会为「老式 Windows 控制台」做降级，但那条分支依赖 ``isatty()``：
stdout 被重定向成管道时它走普通写入路径，异常照样冒出来。实测三种写法
（输出流是 GBK 编码的 ``TextIOWrapper``）**全部**抛 ``UnicodeEncodeError``::

    print("✅", file=gbk_stream)
    Console(file=gbk_stream).print("✅")
    Console(file=gbk_stream, legacy_windows=False).print("✅")

结论：rich 是**格式层**，编码兜底必须在它之前、在进程入口处做一次。
这也是本模块存在的唯一理由 —— 原先 7 个入口脚本各自抄了一份同样的
try/except，抄漏一个就有一个命令在 GBK 控制台上崩掉。

实现取舍
--------
* ``errors="replace"``：兜底之后仍可能遇到 UTF-8 也写不出去的字符
  （用户自定的 mod 名里可能有代理对残片），宁可显示成 ``?``
  也不让整条命令崩掉 —— 这是「显示层」的失败，不该升级成任务失败。
* 只改编码，不碰 ``line_buffering``：后者会改变进度输出的时序。
* 用 ``getattr`` 取 ``reconfigure`` 而不是直接调用：流的类型不止一种
  （``pythonw`` 下是 ``None``，pytest 的 capture 是自定义对象），
  没有这个方法本身不是错误，静默跳过即可。
"""

from __future__ import annotations

import contextlib
import sys


def enable_utf8_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8。

    幂等，重复调用无副作用；流不可重配置时静默跳过（见模块文档）。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # ValueError/OSError：流已关闭，或底层是管道且不支持改编码。
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")
