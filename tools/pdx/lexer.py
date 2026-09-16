"""PDX 脚本词法分析器。

把文本切成 token 流。设计约束来自对 1.14.2 实际文件的观察：

注释与引号
    ``#`` 到行尾是注释。剥离必须**引号感知** —— 字符串字面量里可能含 ``#``。
    这一步必须在花括号计数**之前**完成，因为原版有大量被注释掉的整块定义
    （``00_flag_definitions.txt`` 就有 21 行注释内含花括号，不剥离会让深度漂移）。

缩进无语义
    官方文件混用 tab、2 空格、4 空格，甚至有顶层键完全不缩进的，
    也有本该缩进却没缩进的。**因此不使用缩进做任何判断。**

运算符
    ``=`` ``?=`` ``==`` ``!=`` ``>`` ``<`` ``>=`` ``<=`` 都要识别。
    ``key =`` 与值分行是合法的，token 流天然支持。

键名字符集
    **不枚举字符类**。键名允许连字符（全库 32 个）、点号、冒号
    （``c:SWE``、``unit_type:foo``）。只要不是空白、括号、运算符或引号，
    都算标识符字符。
"""

from __future__ import annotations

from dataclasses import dataclass

# token 类型
LBRACE = "LBRACE"
RBRACE = "RBRACE"
OP = "OP"
ATOM = "ATOM"
STRING = "STRING"
EOF = "EOF"

# 长的优先，保证 ?= 不会被切成 ? 和 =
_OPERATORS = ("?=", "==", "!=", ">=", "<=", "=", ">", "<")

_WHITESPACE = " \t\r\n\f\v"
_OP_START = set("=!<>?")


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


def tokenize(text: str) -> list[Token]:
    """把 PDX 文本切成 token 列表，末尾带一个 EOF。

    ``text`` 应已由调用方以 ``utf-8-sig`` 读取，BOM 已被剥离。
    若仍残留 BOM，这里会把它当普通字符吞掉，避免污染首个键名。
    """
    tokens: list[Token] = []
    i = 0
    n = len(text)
    line = 1
    line_start = 0

    while i < n:
        ch = text[i]

        # ── 换行：更新行号 ────────────────────────────────
        if ch == "\n":
            line += 1
            i += 1
            line_start = i
            continue

        # ── 空白 ─────────────────────────────────────────
        if ch in _WHITESPACE:
            i += 1
            continue

        # ── BOM 兜底（正常路径不会走到） ────────────────────
        if ch == "\ufeff":
            i += 1
            continue

        # ── 注释：吞到行尾，引号感知 ───────────────────────
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue

        col = i - line_start + 1

        # ── 花括号 ───────────────────────────────────────
        if ch == "{":
            tokens.append(Token(LBRACE, ch, line, col))
            i += 1
            continue
        if ch == "}":
            tokens.append(Token(RBRACE, ch, line, col))
            i += 1
            continue

        # ── 带引号字符串 ──────────────────────────────────
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
                    # 未闭合的引号：原版不该出现，容错为到此为止
                    line += 1
                    line_start = i + 1
                    break
                i += 1
            tokens.append(Token(STRING, text[start:i], line, col))
            continue

        # ── 运算符 ───────────────────────────────────────
        if ch in _OP_START:
            matched = None
            for op in _OPERATORS:
                if text.startswith(op, i):
                    matched = op
                    break
            if matched:
                tokens.append(Token(OP, matched, line, col))
                i += len(matched)
                continue

        # ── 标识符 / 数字 / 其他原子 ───────────────────────
        start = i
        while i < n:
            c = text[i]
            if c in _WHITESPACE or c in "{}#\"" or c in _OP_START:
                break
            i += 1
        if i == start:
            # 单个无法识别的字符（例如孤立的 ? !），原样产出避免死循环
            i += 1
        tokens.append(Token(ATOM, text[start:i], line, col))

    tokens.append(Token(EOF, "", line, 1))
    return tokens
