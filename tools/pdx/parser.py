"""PDX 脚本语法分析器：递归下降，产出 AST。

顶层判定完全依赖**花括号深度**，不依赖缩进 —— 这是正确的做法，也是本次
会话中修正 6121→6128 那类错误的关键。

为什么不用现成的解析器库（lark / pyparsing / PLY）
--------------------------------------------------
本项目的原则是「能用成熟库就不自己写」，所以这一条必须交代清楚。
PDX 的语法本身很简单（花括号 + ``键 运算符 值``），确实可以写成语法文件；
真正让通用解析器**不适用**的是下面四条**实测需求**：

1. **必须容错并返回部分结果**。6,250 个真实文件里有 **15 个**括号不平衡
   （``common/dna_data/`` 下若干历史人物文件引号未闭合）。通用解析器遇到
   语法错误通常是「抛异常 / 整棵丢弃」，而这些文件**其余部分仍然可用** ——
   全量分析不能因为它们少收 15 个文件的数据。
2. **必须保序保数地保留重复键**。295 个文件的**顶层**存在重复键，落在重复键
   上的条目共 **3,600 条**（``gfx/.../european.txt`` 里 ``variation`` 一个键
   出现 383 次）。多数解析器产出的树是「字典」语义，重复键会被静默覆盖成
   最后一个 —— 对这个项目而言那是**实打实的信息丢失**，而不是小事。
3. **必须精确复刻引擎的古怪行为**。行号归属、未闭合引号导致的**行号双重自增**
   这类细节，都要与旧实现逐个 token 对齐（``test_lexer_differential.py`` 在
   全部 6,250 个文件上比对 ``(kind, value, line, col)``）。换成通用解析器，
   这些行为要重新推导一遍，而**产物是逐字节冻结的**（黄金回归比对 sha256），
   任何归属差异都会让全部产物失效。
4. **本包刻意不引入第三方依赖**。``pdx/__init__.py`` 写明「纯标准库实现」——
   只有 CLI 外壳用 typer/rich。解析器是核心，把它绑到 lark 上会让
   「装个 Python 就能跑」变成「先装 lark」。

性能也不是理由之一：主正则词法器实测 **286 文件/秒**（6,250 个文件 21.9 秒，
含建 AST），已经够用；这一条列出来只是为了说明**没有**拿它当借口。

> 曾经尝试过 lark（相关包一度留在开发环境里），最终没有采用 —— 上面第 1、2 条
> 是硬约束，不是偏好。

容错策略
--------
不追求「要么全对要么报错」。遇到不平衡的括号时记录到 ``errors`` 并尽量
返回已解析的部分，因为游戏文件里存在被注释掩盖的畸形块，我们仍希望
拿到其余可用的数据。

已知限制
--------
``key =`` 之后紧接换行时，若下一行以标识符开头，语法上无法区分那是
**该键的值**还是**下一条语句**。本解析器按「是值」处理。真实 PDX 文件
不会这样写（值要么同行，要么是下一行的 ``{``），因此实践中无影响。
"""

from __future__ import annotations

from pathlib import Path

from .lexer import ATOM, EOF, LBRACE, OP, RBRACE, STRING, Token, tokenize
from .model import Assignment, Block, ParsedFile, Scalar

#: 引擎级功能前缀。键名前带这些前缀时，语义是「对已存在条目做注入/替换」
#: 而不是重新定义。已确认存在于 victoria3.exe 的字符串表中。
PREFIXES: tuple[str, ...] = (
    "REPLACE_OR_CREATE",
    "INJECT_OR_CREATE",
    "TRY_INJECT",
    "TRY_REPLACE",
    "REPLACE",
    "INJECT",
)

_PREFIX_SET = frozenset(PREFIXES)

#: 块结束的两种 token。提成模块级常量，而不是在热路径里写
#: ``kind in (RBRACE, EOF)`` —— 后者每次求值都要新建一个元组。
_TERMINATORS = (RBRACE, EOF)

#: 可以作为语句或值开头的两种 token。同上，提到模块级。
_WORDLIKE = (ATOM, STRING)

#: 解析单个文件时**可以合理容忍**的异常。
#:
#: 刻意*不*含 ``Exception`` —— 宽泛捕获会把代码 bug（打错属性名、
#: 类型不匹配）降级成「这个文件没解析成功」，是最难查的一类问题：
#: 它让错误静默地变成合法输出，还顺带让回归测试保持绿色。
#:
#: * ``OSError``            文件读不了（权限、被删、路径过长）
#: * ``RecursionError``     嵌套深度超出 Python 递归上限的病态文件
#: * ``UnicodeDecodeError`` 非 UTF-8 且替换解码也失败的极端情况
TOLERATED_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    RecursionError,
    UnicodeDecodeError,
)


def _split_prefix(word: str) -> tuple[str | None, str]:
    """把 ``INJECT:foo`` 拆成 ``("INJECT", "foo")``。

    注意 ``c:SWE`` 这类作用域引用不会被误拆 —— 只有头部是**已知前缀集合**
    里的词才认作功能前缀。
    """
    if ":" in word:
        head, _, rest = word.partition(":")
        if head in _PREFIX_SET and rest:
            return head, rest
    return None, word


class _Parser:
    """递归下降解析器。

    性能要点
    --------
    全量分析要对 3,782 个文件、约 560 万个 token 跑这里，热路径上任何一处
    多余开销都会被放大成秒级。三处刻意的写法（都经基准量化验证）：

    1. ``cur`` 是**普通属性**而不是 ``@property``。特性读要走一次描述符
       协议加一次 Python 函数调用；每消费一个 token 要读它好几次，
       这是最大的一笔按-token 计费的开销。改用属性后由 :meth:`advance`
       负责同步。
    2. :meth:`parse_value` **内联**进了 :meth:`parse_statement`。它原先
       被调用 139 万次，而函数体只有四个分支 —— 调用本身比干活还贵。
    3. ``errors.append`` 预先取出来存成 ``self._err``，省掉报错时的一次
       属性查找。

    另：早先这里还有个 ``expect()`` 方法和一个 ``path`` 属性，两者全项目
    零调用（覆盖率报告里长期挂着未覆盖行），已删除。
    """

    __slots__ = ("_err", "cur", "depth", "errors", "max_depth", "pos", "tokens")

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        #: 当前 token。由 :meth:`advance` 维护，不通过下标实时取。
        self.cur = tokens[0]
        self.errors: list[str] = []
        self._err = self.errors.append
        #: 当前花括号深度与见过的最大深度。
        #: 记录在这里，而不是事后遍历 AST —— 后者要为每个文件把整棵树
        #: 再递归走一遍（全量分析下是 58 万次块访问的纯重复劳动）。
        self.depth = 0
        self.max_depth = 0

    # ── token 辅助 ─────────────────────────────────────────
    def advance(self) -> Token:
        """返回当前 token 并前进一个。

        刻意维护 ``self.cur`` 而不是每次读 ``self.tokens[self.pos]``：
        ``tokens`` 必定以 EOF 收尾，且 EOF 不再前进，
        所以 ``self.pos`` 永远落在合法下标内。
        """
        tok = self.cur
        if tok.kind != EOF:
            self.pos += 1
            self.cur = self.tokens[self.pos]
        return tok

    # ── 语法 ──────────────────────────────────────────────
    def parse_root(self) -> Block:
        root = Block(line=1)
        items = root.items
        while self.cur.kind != EOF:
            before = self.pos
            item = self.parse_statement()
            if item is not None:
                items.append(item)
            if self.pos == before:  # 防御：绝不空转
                self.advance()
        return root

    def parse_block(self, line: int) -> Block:
        depth = self.depth + 1
        self.depth = depth
        # 不用 max()：热路径上它会多一次属性读，if 更快
        if depth > self.max_depth:  # noqa: PLR1730
            self.max_depth = depth

        block = Block(line=line)
        items = block.items
        while True:
            kind = self.cur.kind
            if kind in _TERMINATORS:
                break
            before = self.pos
            item = self.parse_statement()
            if item is not None:
                items.append(item)
            if self.pos == before:
                self.advance()
        if self.cur.kind == RBRACE:
            self.advance()
        else:
            self._err(f"第 {line} 行开始的块没有闭合的花括号")

        self.depth = depth - 1
        return block

    def parse_statement(self):
        """解析一条语句。``parse_value`` 已内联，见类文档。

        刻意**不带**「是否顶层」参数 —— 早先有个 ``top_level`` 形参，
        但函数体从未读过它。顶层与块内的区别完全由调用方
        （:meth:`parse_root` / :meth:`parse_block`）通过花括号深度决定。
        """
        tok = self.cur
        kind = tok.kind

        if kind == LBRACE:
            self.advance()
            return self.parse_block(tok.line)

        if kind == RBRACE:
            # 多余的右括号：上层会处理，这里不消费，避免吞掉
            return None

        if kind in _WORDLIKE:
            self.advance()
            # 下一个是运算符 → 赋值；否则是裸标量（列表元素）
            if self.cur.kind == OP:
                op = self.advance().value

                # ── 内联的 parse_value ──────────────────────
                vtok = self.cur
                vkind = vtok.kind
                value: Block | Scalar | None
                if vkind == LBRACE:
                    self.advance()
                    value = self.parse_block(vtok.line)
                elif vkind == STRING:
                    self.advance()
                    value = Scalar(text=vtok.value, quoted=True, line=vtok.line)
                elif vkind == ATOM:
                    self.advance()
                    value = Scalar(text=vtok.value, quoted=False, line=vtok.line)
                else:
                    # 空值：``key =`` 后面直接换行或遇到右括号
                    value = None

                if kind == STRING:
                    raw = tok.value
                    key = raw[1:-1] if len(raw) >= 2 else raw
                    prefix = None
                else:
                    prefix, key = _split_prefix(tok.value)
                return Assignment(key=key, op=op, value=value, prefix=prefix, line=tok.line)
            return Scalar(text=tok.value, quoted=(kind == STRING), line=tok.line)

        # 无法识别：消费掉，避免死循环
        self.advance()
        return None


def parse_text(text: str, path: str = "<text>") -> ParsedFile:
    """解析已读入的文本。"""
    had_bom = text.startswith("\ufeff")
    if had_bom:
        text = text[1:]
    comments: list[tuple[int, str]] = []
    tokens = tokenize(text, comments)
    parser = _Parser(tokens)
    root = parser.parse_root()

    # 字符串可以跨行，因此「没有闭引号」不再等同于「到行尾结束」——
    # 它表示整个文件在字符串中间就断了。这种情况必须显式报出来：
    # 旧实现会静默把它截断到行尾，产出一份看起来正常、实际错位的数据。
    #
    # 判据只对**末尾**那个 token 成立：未闭合的引号字符串必然一直吃到文件尾。
    # 长度检查是必须的 —— 空文件只有 EOF 一个 token（这里踩过 IndexError）。
    if len(tokens) >= 2:
        last = tokens[-2]
        if last.kind == STRING and not last.value.endswith('"'):
            parser._err("文件结束时仍有一个引号字符串没有闭合")
    return ParsedFile(
        path=path,
        root=root,
        had_bom=had_bom,
        errors=parser.errors,
        comments=comments,
        max_depth=parser.max_depth,
    )


def parse_file(path: str | Path) -> ParsedFile:
    """解析一个 PDX 文件。

    固定用 ``utf-8-sig`` 读取 —— 实测 ``common/`` 下 3024 个 .txt 中有
    3000 个带 BOM，这个编码名会**自动剥离**它，避免首键被污染成
    ``\\ufefffoo`` 或被行首匹配漏掉。
    """
    p = Path(path)
    raw = p.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # 极少数文件可能不是 UTF-8；用替换字符兜底，不中断整轮扫描
        text = raw.decode("utf-8", errors="replace")
    result = parse_text(text, str(p))
    result.had_bom = had_bom
    return result
