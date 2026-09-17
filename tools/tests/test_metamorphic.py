"""变形测试（metamorphic testing）。

思路
----
很多正确的性质没法直接断言「输出等于某个值」，但可以断言
**「输入做某种语义保持的变换后，输出必须不变」**。
这比手写用例强的地方在于：变换可以随机施加在随机生成的文档上，
覆盖面远超人工枚举。

这里施加的变换全部是 PDX 语法保证无语义的：
注释、缩进、制表符、BOM、CRLF、空行、键值间的空白。
只要有任何一条让解析结果变了，就说明解析器违反了语法约定。

比对用 :func:`_helpers.signature`（不含行号/列号）—— 加注释必然改变行号，
那是噪声，不是语义。
"""

from __future__ import annotations

import pytest
from _helpers import entry_keys, signature, variable_keys
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pdx.parser import parse_text

pytestmark = pytest.mark.property

# ── 文档生成 ────────────────────────────────────────────────
#: 只用最保守的字符集 —— 本文件的目的是检验**不变性**，
#: 不是检验词法边界（那由 test_lexer_differential.py 负责）。
_KEY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_", min_size=1, max_size=8
)
_VAL = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_.-", min_size=1, max_size=8)


@st.composite
def pdx_docs(draw) -> str:
    """生成语法上干净、行行自平衡的 PDX 文档。"""
    n = draw(st.integers(min_value=1, max_value=8))
    lines: list[str] = []
    for _ in range(n):
        k = draw(_KEY)
        v = draw(_VAL)
        form = draw(st.integers(min_value=0, max_value=3))
        if form == 0:
            lines.append(f"{k} = {v}")
        elif form == 1:
            lines.append(f'{k} = "{v}"')
        elif form == 2:
            lines.append(f"{k} = {{ {v} = 1 }}")
        else:
            lines.append(f"@{k} = {v}")
    return "\n".join(lines) + "\n"


def _parsed_sig(text: str):
    return signature(parse_text(text, "<m>"))


# ── 变换 ────────────────────────────────────────────────────
def _add_blank_lines(doc: str) -> str:
    return doc.replace("\n", "\n\n")


def _add_indent(doc: str) -> str:
    return "\n".join(("    " + ln) if ln else ln for ln in doc.split("\n"))


def _spaces_to_tabs(doc: str) -> str:
    return doc.replace(" ", "\t")


def _collapse_spaces(doc: str) -> str:
    """把 ``k = v`` 压成 ``k=v`` —— 空白在 PDX 里无语义。"""
    return doc.replace(" = ", "=").replace("{ ", "{").replace(" }", "}")


def _to_crlf(doc: str) -> str:
    return doc.replace("\n", "\r\n")


def _add_bom(doc: str) -> str:
    return "\ufeff" + doc


def _add_full_line_comments(doc: str) -> str:
    """在每行之间插入整行注释，并在文件末尾追加注释。"""
    out: list[str] = []
    for i, ln in enumerate(doc.split("\n")):
        out.append(f"# 第 {i} 段注释")
        out.append(ln)
    out.append("# 结尾注释")
    return "\n".join(out)


def _add_trailing_comments(doc: str) -> str:
    """给每个非空行加行尾注释。"""
    return "\n".join((ln + "  # 说明") if ln.strip() else ln for ln in doc.split("\n"))


def _add_trailing_whitespace(doc: str) -> str:
    return "\n".join(ln + "   \t" if ln.strip() else ln for ln in doc.split("\n"))


#: 全部「语义保持」变换
PRESERVING = {
    "空行": _add_blank_lines,
    "缩进": _add_indent,
    "空格转制表符": _spaces_to_tabs,
    "去掉键值间空白": _collapse_spaces,
    "CRLF": _to_crlf,
    "BOM": _add_bom,
    "整行注释": _add_full_line_comments,
    "行尾注释": _add_trailing_comments,
    "行尾空白": _add_trailing_whitespace,
}


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(doc=pdx_docs())
def test_语义保持变换不改变解析结果(doc: str) -> None:
    """9 种变换，任意一种施加后语义指纹都必须一致。"""
    base = _parsed_sig(doc)
    for name, fn in PRESERVING.items():
        assert _parsed_sig(fn(doc)) == base, f"变换《{name}》改变了语义"


@settings(max_examples=80, deadline=None)
@given(doc=pdx_docs())
def test_多种变换叠加仍不改变结果(doc: str) -> None:
    """单个变换不变不代表组合起来不变（变换之间可能互相干扰）。"""
    base = _parsed_sig(doc)
    combined = doc
    for fn in PRESERVING.values():
        combined = fn(combined)
    assert _parsed_sig(combined) == base


@settings(max_examples=100, deadline=None)
@given(doc=pdx_docs(), extra=st.lists(_KEY, min_size=1, max_size=4))
def test_新增变量定义不改变数据条目(doc: str, extra: list[str]) -> None:
    """``@变量`` 是脚本变量，不是数据条目。

    这条直接对应一个真实踩过的错：``00_defines.txt`` 顶部 22 个 ``@变量``
    曾被误计成命名空间，把块数从 75 变成 97。
    """
    before = parse_text(doc, "<m>")
    after = parse_text(doc + "\n".join(f"@{k} = 1" for k in extra) + "\n", "<m>")
    assert entry_keys(after) == entry_keys(before)
    assert variable_keys(after) >= variable_keys(before)


@settings(max_examples=100, deadline=None)
@given(doc=pdx_docs())
def test_注释掉一行即从条目中消失(doc: str) -> None:
    """反向性质：把某行变成注释，其顶层键必须消失。

    这条能抓住「注释剥离不彻底」——例如把 ``#`` 当成普通字符吞进键名。

    按**行号**定位而不是按内容匹配 —— 否则文档里两行内容相同时
    （``A = 0`` 出现两次）会把两行一起注释掉，键数少 2 而不是 1。
    """
    lines = doc.split("\n")
    idxs = [i for i, ln in enumerate(lines) if ln.strip()]
    if not idxs:
        return
    idx = hash(doc) % len(idxs)
    row = idxs[idx]

    commented = list(lines)
    commented[row] = "# " + commented[row]
    before = parse_text(doc, "<m>")
    after = parse_text("\n".join(commented), "<m>")

    before_keys = [a.key for a in before.root.assignments()]
    after_keys = [a.key for a in after.root.assignments()]
    assert len(after_keys) == len(before_keys) - 1
    assert after_keys != before_keys


@settings(max_examples=80, deadline=None)
@given(doc=pdx_docs())
def test_按行切分后拼接的键序等于各段键序之并(doc: str) -> None:
    """拼接不变性：行行自平衡时，分段解析再拼接，顶层键序应完全一致。

    ``parse_text`` 的容错策略允许返回「部分结果」，因此这里只在
    两段都无错时才比较 —— 否则比的是容错行为，不是语法。
    """
    lines = [ln for ln in doc.split("\n") if ln.strip()]
    if len(lines) < 2:
        return
    cut = len(lines) // 2
    head = "\n".join(lines[:cut]) + "\n"
    tail = "\n".join(lines[cut:]) + "\n"

    ph, pt = parse_text(head, "<h>"), parse_text(tail, "<t>")
    if ph.errors or pt.errors:
        return
    joined = parse_text(head + tail, "<j>")
    assert not joined.errors
    assert [a.key for a in joined.root.assignments()] == [a.key for a in ph.root.assignments()] + [
        a.key for a in pt.root.assignments()
    ]


@settings(max_examples=80, deadline=None)
@given(doc=pdx_docs())
def test_重排行序不改变条目集合(doc: str) -> None:
    """顺序可能影响列表语义，但**条目集合**必须与顺序无关。"""
    lines = [ln for ln in doc.split("\n") if ln.strip()]
    base = parse_text(doc, "<m>")
    flipped = parse_text("\n".join(reversed(lines)) + "\n", "<m>")
    assert not flipped.errors
    assert entry_keys(flipped) == entry_keys(base)
    assert variable_keys(flipped) == variable_keys(base)
