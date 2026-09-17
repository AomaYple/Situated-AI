"""PDX 脚本词法分析器。

设计约束来自对 1.14.3 实际文件的观察：

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

实现方式
--------
用**一条主正则**配合 :func:`re.finditer` 扫描，而不是逐字符的 Python 循环。

实测依据：旧实现里 ``tokenize`` 的自身耗时（``tottime``）是全程序最大的
单项，达 9.25 秒，占 cProfile 总时长的 23%。逐字符循环的每一次迭代都要做
若干次 Python 层的比较与分支；换成主正则后，扫描工作在 C 层完成，
Python 只在**每个 token** 上执行一次循环体。

正确性由 ``tools/tests/test_lexer_differential.py`` 保证：它把本节实现与
优化前的逐字符版本（``_oracle_lexer.py``）在全部 4,400 个真实文件上逐
token 比对 ``(kind, value, line, col)``。**未闭合引号导致的行号双重自增**
这类古怪行为也被刻意复刻，见 ``_scan_string``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# token 类型
LBRACE = "LBRACE"
RBRACE = "RBRACE"
OP = "OP"
ATOM = "ATOM"
STRING = "STRING"
EOF = "EOF"

#: 长的优先，保证 ``?=`` 不会被切成 ``?`` 和 ``=``
_OPERATORS = ("?=", "==", "!=", ">=", "<=", "=", ">", "<")

#: 只有这几种 ASCII 空白算空白。刻意**不用** ``\s`` ——
#: Python 的 ``\s`` 是 Unicode 感知的，会把 NBSP 等也算进去，
#: 而原实现只认这几个字符，用 ``\s`` 会悄悄改变切分结果。
_WS = " \t\r\n\f\v"

#: 主扫描正则。各分支的**顺序即优先级**。
#:
#: * ``ws``      空白与 BOM
#: * ``comment`` ``#`` 到行尾（**不含**换行符）
#: * ``string``  字符串主体 + 收尾。收尾单独放进 ``quote`` 组，见下
#: * ``atom``    键名 / 数字 / 其他原子
#: * ``other``   兜底单字符（孤立的 ``?`` ``!``）
#:
#: **字符串可以跨行。** 这是 2026-09 覆盖面审计时修正的一处**真实语义错误**：
#: 最初实现遇到字符串里的换行就当作「未闭合」终止，注释里还写着
#: 「原版不该出现，容错为到此为止」—— 那个判断是错的。
#:
#: 证据：``gfx/map/map_object_data/lakes.txt`` 里
#: ``transform="4311.17 … 11.37``（第 10 行开引号）一直延续到第 25 行才闭合。
#: 按「可跨行」重算，该文件花括号完美配平（最终深度 0）；按旧规则则会
#: 让闭引号开启一段新的"字符串"、把中间的 ``}`` 全吞掉，导致 20 个
#: gfx/.asset 文件报「块没有闭合」。
#:
#: 之所以长期没暴露，是因为旧的分析范围恰好不含 gfx 与 .asset ——
#: 扩大范围才把这个潜在缺陷翻出来。
#:
#: **``quote`` 组为什么必须存在**：闭引号是被**消费**掉的，事后看
#: ``text[end-1]`` 无法区分「闭引号」与「转义引号 ``\"``」——
#: ``"abc"\n`` 与 ``"a\"\n`` 的末字符都是 ``"``，前者已闭合、后者没有。
_TOKEN_RE = re.compile(
    rf"""
      (?P<ws>[{_WS}\ufeff]+)
    | (?P<comment>\#[^\n]*)
    | (?P<lbrace>\{{)
    | (?P<rbrace>\}})
    | (?P<string>"(?:\\[\s\S]|\\$|[^"\\])*(?P<quote>"|$))
    | (?P<op>\?=|==|!=|>=|<=|=|>|<)
    | (?P<atom>[^{_WS}{{}}#"=!<>?]+)
    | (?P<other>[\s\S])
    """,
    re.VERBOSE,
)

#: 分组编号在导入期从正则里反查。**不写死数字** —— 那样一改正则就会静默错位。
_G = _TOKEN_RE.groupindex
_G_WS = _G["ws"]
_G_COMMENT = _G["comment"]
_G_LBRACE = _G["lbrace"]
_G_RBRACE = _G["rbrace"]
_G_STRING = _G["string"]
_G_QUOTE = _G["quote"]
_G_OP = _G["op"]


@dataclass(slots=True)
class Token:
    """一个词法单元。

    用 ``@dataclass(slots=True)`` 而不是 ``NamedTuple``：

    实测（CPython 3.14.7，构造 100 万次）::

        NamedTuple                  0.299 s
        @dataclass(slots=True)      0.203 s
        @dataclass(slots=True, frozen=True)  0.501 s

    全量分析要构造约 340 万个 Token，这一项差 1.5 倍。
    注意**冻结版本反而最慢** —— 早先这里换成 NamedTuple 时给出的
    「NamedTuple 快数倍」的理由，经复测并不成立（当时的对照物是 frozen 版本）。
    """

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

    性能取舍
    --------
    复杂度性质与逐字符版**不同**：逐字符版是「Python 层 O(字节数)」，
    本版是「Python 层 O(token 数) + C 层 O(字节数)」。因此胜负取决于
    **字节/token 比值**（实测）::

        字节/token   场景                 变化
        2.5 ~ 4      合成高密度微基准     +32% ~ +86%（更慢）
        8.4          真实语料平均         −6%
        42           真实稀疏文件         −52%

    真实 PDX 脚本是稀疏的（大量空白、注释、长标识符），所以本版在实际
    负载上更快；合成微基准的 token 密度是真实文件的十几倍，结论会反过来
    —— **不要用合成数据判断这一层的优化效果**。

    实现上刻意避开三处按 token 计费的开销：

    1. 用 ``match.lastindex``（整数）而不是 ``lastgroup``（字符串）分派；
       组号在导入期由 ``groupindex`` 反查，不写死数字
    2. 不调 ``match.start()`` —— 正则的兜底分支能匹配任意单字符，
       所以 ``finditer`` 的每个匹配必然紧接上一个的结尾，起点可以自己推
    3. 空白分支先用 ``find`` 探一次换行；绝大多数空白块里没有换行，
       这样能跳过 ``count`` + ``rfind`` 两次扫描
    """
    tokens: list[Token] = []
    append = tokens.append
    line = 1
    line_start = 0
    start = 0  # 上一个匹配的结尾，也就是这一个的起点

    for match in _TOKEN_RE.finditer(text):
        index = match.lastindex
        end = match.end()

        # ── 空白：行号在这里推进 ──────────────────────────
        if index == _G_WS:
            if text.find("\n", start, end) >= 0:
                line += text.count("\n", start, end)
                line_start = text.rfind("\n", start, end) + 1
            start = end
            continue

        # ── 注释：吞到行尾。引号感知由 string 分支优先匹配来保证 ──
        if index == _G_COMMENT:
            start = end
            continue

        col = start - line_start + 1

        if index == _G_STRING:
            # 字符串可以跨行（见 _TOKEN_RE 的说明），因此它自己也可能推进
            # 行号 —— 空白分支不再是唯一会改 line 的地方。
            #
            # token 的 line 记的是**起始**行，所以在更新之前取。
            token_line = line
            if text.find("\n", start, end) >= 0:
                line += text.count("\n", start, end)
                line_start = text.rfind("\n", start, end) + 1
            append(Token(STRING, text[start:end], token_line, col))
        elif index == _G_LBRACE:
            append(Token(LBRACE, "{", line, col))
        elif index == _G_RBRACE:
            append(Token(RBRACE, "}", line, col))
        elif index == _G_OP:
            append(Token(OP, text[start:end], line, col))
        else:
            # atom 与兜底的单字符，旧实现里都是 ATOM
            append(Token(ATOM, text[start:end], line, col))

        start = end

    append(Token(EOF, "", line, 1))
    return tokens
