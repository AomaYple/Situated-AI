"""仓库卫生 —— 直击「一次小编辑变成整文件重写」的那类事故。

为什么需要它
-----------
换行符。仓库里全是 LF（``.gitattributes`` 写着 ``eol=lf``），而 Windows 上
``Path.write_text(text)`` **默认把 ``\\n`` 翻译成 ``\\r\\n``**。
实测踩过：一次「改一个函数名」的脚本用 ``p.read_text()`` + ``p.write_text()``
重写了 ``tools/pdx/doc_tables.py``，文件从 LF 变成 CRLF ——
``git add`` 时 git 给出 ``CRLF will be replaced by LF`` 的警告，
提交后 diff 正常，但**本地工作树与索引长期不一致**（`git status` 反复报改动），
而真正的原因（漏了 ``newline="\\n"``）藏在一句警告里。

判定故意只看 ``\\r``：不比对行尾风格、不重排，避免这条检查本身变成噪声源。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pdx import config

if TYPE_CHECKING:
    from pathlib import Path

#: 参与检查的**源**目录（相对仓库根）。产物目录故意不在内，见模块 docstring。
_ROOTS = ("tools/pdx", "tools/tests", "docs", "research")
#: 目录之外的零散源文件（相对仓库根）。
_EXTRA_FILES = ("README.md", "tools/README.md", "pyproject.toml")
_SUFFIXES = (".py", ".md", ".toml", ".yml", ".yaml", ".json")


def _candidates() -> list[Path]:
    out: list[Path] = []
    for root in _ROOTS:
        base = config.REPO / root
        if base.is_dir():
            out.extend(p for p in base.rglob("*") if p.is_file() and p.suffix in _SUFFIXES)
    out.extend(p for name in _EXTRA_FILES if (p := config.REPO / name).is_file())
    return sorted(out)


def test_没有文件带_CRLF() -> None:
    """任何带 ``\\r\\n`` 的文件都点名报出来（含**第一个** CRLF 的行号）。"""
    bad: list[str] = []
    for path in _candidates():
        data = path.read_bytes()
        at = data.find(b"\r\n")
        if at < 0:
            continue
        line = data[:at].count(b"\n") + 1
        total = data.count(b"\r\n")
        bad.append(f"{path.relative_to(config.REPO)} 第 {line} 行（共 {total} 处）")
    assert not bad, (
        "以下文件带 CRLF —— 多半是 `write_text` 漏了 `newline='\\n'`：\n  " + "\n  ".join(bad[:10])
    )


def test_检查范围不为空() -> None:
    """元测试：目录改名后这条检查不能变成「扫了 0 个文件、永远通过」。"""
    files = _candidates()
    assert len(files) > 20, f"只扫到 {len(files)} 个文件 —— 检查范围多半失效了"


@pytest.mark.parametrize("root", _ROOTS)
def test_检查范围内的目录存在(root: str) -> None:
    assert (config.REPO / root).is_dir(), f"{root}/ 不见了 —— 上面那条检查会静默缩小范围"
