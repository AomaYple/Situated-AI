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
            # ── 2026-09 修订：字符串**可以跨行** ──────────────────
            #
            # 这里原本是「遇到换行就当作未闭合、截断到行尾」。那个行为已被
            # 证据推翻：``gfx/map/map_object_data/lakes.txt`` 第 10 行
            # ``transform="4311.17 … 11.37`` 一直延续到第 25 行才闭合，
            # 且按「可跨行」重算该文件花括号完美配平；按旧规则则会让闭引号
            # 开启一段新的"字符串"，把中间的 ``}`` 全吞掉。
            #
            # 之所以长期没人发现，是因为旧的分析范围恰好不含 gfx 与 .asset，
            # 扩大范围才把这个潜在缺陷翻出来。
            #
            # 本文件是「参照实现」，参照的是**正确语义**而不是历史 bug ——
            # 因此同步修订，并把 token 的行号统一定为字符串**起始**行
            # （旧行为把自增后的行号写进 token，那是截断语义的副产物）。
            start = i
            start_line = line
            i += 1
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                i += 1
            span = text[start:i]
            # 行号按**整个跨度**里的换行数推进，而不是在循环里逐个累加。
            # 两者在「转义换行」（``"x\<换行>y"``）上会分道扬镳：循环里
            # ``i += 2`` 把那个换行一并跳过、不计数，而它确实是一个换行。
            # 统一按跨度统计，语义才自洽。
            newlines = span.count("\n")
            if newlines:
                line += newlines
                line_start = start + span.rfind("\n") + 1
            tokens.append(OracleToken(STRING, span, start_line, col))
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
