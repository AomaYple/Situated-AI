"""词法分析器的**冻结预言机**（oracle）。

为什么要有这个文件
------------------
性能优化最容易犯的错，是把「看起来等价」当成「等价」。逐字符 Python 循环
改成 :mod:`re` 主正则扫描能快数倍，但两者的边界行为（未闭合引号、孤立
反斜杠、``?`` 单字符、BOM、行号自增时机）极难靠肉眼确认一致。

因此把**优化前的实现原封不动**留在这里当作参照物，用
:mod:`test_lexer_differential` 在真实语料（数百万 token）上逐 token 比对。
新实现只要有一个 token 的 ``(kind, value, line, col)`` 不同，测试立刻失败。

约束
----
* **禁止修改本文件**。它代表已被验证过的行为基线；要改就是改语义，
  必须同步更新真实语料上手算过的期望值，而不是让预言机迁就新实现。
* 本文件**不导入** :mod:`pdx.lexer`。刻意复制而非继承，避免新实现
  把 bug 传染给参照物（那样差分测试会双双通过，毫无意义）。
* 比较时用 ``tuple(token)`` 而不是 token 对象，这样连 ``Token`` 的字段
  顺序变化也能被差分测试发现。
"""

from __future__ import annotations

from typing import NamedTuple

# token 类型（与 pdx.lexer 同名同值，但独立定义）
LBRACE = "LBRACE"
RBRACE = "RBRACE"
OP = "OP"
ATOM = "ATOM"
STRING = "STRING"
EOF = "EOF"

_OPERATORS = ("?=", "==", "!=", ">=", "<=", "=", ">", "<")

_WHITESPACE = " \t\r\n\f\v"
_OP_START = set("=!<>?")


class OracleToken(NamedTuple):
    kind: str
    value: str
    line: int
    col: int


def oracle_tokenize(text: str) -> list[OracleToken]:
    """优化前的逐字符实现，逐行照抄。"""
    tokens: list[OracleToken] = []
    i = 0
    n = len(text)
    line = 1
    line_start = 0

    while i < n:
        ch = text[i]

        if ch == "\n":
            line += 1
            i += 1
            line_start = i
            continue

        if ch in _WHITESPACE:
            i += 1
            continue

        if ch == "\ufeff":
            i += 1
            continue

        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue

        col = i - line_start + 1

        if ch == "{":
            tokens.append(OracleToken(LBRACE, ch, line, col))
            i += 1
            continue
        if ch == "}":
            tokens.append(OracleToken(RBRACE, ch, line, col))
            i += 1
            continue

        if ch == '"':
            start = i
            i += 1
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                if c == "\n":
                    line += 1
                    line_start = i + 1
                    break
                i += 1
            tokens.append(OracleToken(STRING, text[start:i], line, col))
            continue

        if ch in _OP_START:
            matched = None
            for op in _OPERATORS:
                if text.startswith(op, i):
                    matched = op
                    break
            if matched:
                tokens.append(OracleToken(OP, matched, line, col))
                i += len(matched)
                continue

        start = i
        while i < n:
            c = text[i]
            if c in _WHITESPACE or c in "{}#\"" or c in _OP_START:
                break
            i += 1
        if i == start:
            i += 1
        tokens.append(OracleToken(ATOM, text[start:i], line, col))

    tokens.append(OracleToken(EOF, "", line, 1))
    return tokens


def oracle_tuples(text: str) -> list[tuple[str, str, int, int]]:
    """转成纯元组，便于与任意实现的输出做闭包比较。"""
    return [tuple(t) for t in oracle_tokenize(text)]  # type: ignore[misc]
