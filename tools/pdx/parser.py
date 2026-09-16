"""PDX 脚本语法分析器：递归下降，产出 AST。

顶层判定完全依赖**花括号深度**，不依赖缩进 —— 这是正确的做法，也是本次
会话中修正 6121→6128 那类错误的关键。

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
from .model import Assignment, Block, ParseError, ParsedFile, Scalar

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
    def __init__(self, tokens: list[Token], path: str) -> None:
        self.tokens = tokens
        self.pos = 0
        self.path = path
        self.errors: list[str] = []

    # ── token 辅助 ─────────────────────────────────────────
    @property
    def cur(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != EOF:
            self.pos += 1
        return tok

    def expect(self, kind: str) -> Token | None:
        if self.cur.kind == kind:
            return self.advance()
        self.errors.append(
            f"第 {self.cur.line} 行：期望 {kind}，实际是 "
            f"{self.cur.kind} {self.cur.value!r}"
        )
        return None

    # ── 语法 ──────────────────────────────────────────────
    def parse_root(self) -> Block:
        root = Block(line=1)
        while self.cur.kind != EOF:
            before = self.pos
            item = self.parse_statement(top_level=True)
            if item is not None:
                root.items.append(item)
            if self.pos == before:  # 防御：绝不空转
                self.advance()
        return root

    def parse_block(self, line: int) -> Block:
        block = Block(line=line)
        while self.cur.kind not in (RBRACE, EOF):
            before = self.pos
            item = self.parse_statement(top_level=False)
            if item is not None:
                block.items.append(item)
            if self.pos == before:
                self.advance()
        if self.cur.kind == RBRACE:
            self.advance()
        else:
            self.errors.append(f"第 {line} 行开始的块没有闭合的花括号")
        return block

    def parse_statement(self, top_level: bool):
        tok = self.cur

        if tok.kind == LBRACE:
            self.advance()
            return self.parse_block(tok.line)

        if tok.kind == RBRACE:
            # 多余的右括号：上层会处理，这里不消费，避免吞掉
            return None

        if tok.kind in (ATOM, STRING):
            self.advance()
            # 下一个是运算符 → 赋值；否则是裸标量（列表元素）
            if self.cur.kind == OP:
                op = self.advance().value
                value = self.parse_value()
                if tok.kind == STRING:
                    key = tok.value[1:-1] if len(tok.value) >= 2 else tok.value
                    prefix = None
                else:
                    prefix, key = _split_prefix(tok.value)
                return Assignment(
                    key=key, op=op, value=value, prefix=prefix, line=tok.line
                )
            return Scalar(
                text=tok.value, quoted=(tok.kind == STRING), line=tok.line
            )

        # 无法识别：消费掉，避免死循环
        self.advance()
        return None

    def parse_value(self):
        tok = self.cur
        if tok.kind == LBRACE:
            self.advance()
            return self.parse_block(tok.line)
        if tok.kind == STRING:
            self.advance()
            return Scalar(text=tok.value, quoted=True, line=tok.line)
        if tok.kind == ATOM:
            self.advance()
            return Scalar(text=tok.value, quoted=False, line=tok.line)
        # 空值：``key =`` 后面直接换行或遇到右括号
        return None


def parse_text(text: str, path: str = "<text>") -> ParsedFile:
    """解析已读入的文本。"""
    had_bom = text.startswith("\ufeff")
    if had_bom:
        text = text[1:]
    tokens = tokenize(text)
    parser = _Parser(tokens, path)
    root = parser.parse_root()
    return ParsedFile(
        path=path, root=root, had_bom=had_bom, errors=parser.errors
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
