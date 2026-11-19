"""PDX 脚本的数据模型。

设计要点（每一条都对应实际踩过的坑，见模块内注释）：

* ``prefix`` 保留 ``INJECT:`` / ``REPLACE:`` 等引擎级功能前缀。
* 行号一律记录，便于把发现的问题指回原文。
* ``Scalar.text`` 保留原始字面量，不做类型推断 —— PDX 里
  ``yes`` / ``no`` / 数字 / 标识符在语法层面没有区别，语义由使用处决定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from collections.abc import Iterator


class ParseError(Exception):
    """文件无法解析（花括号不平衡等）。"""

    def __init__(self, message: str, path: str, line: int = 0) -> None:
        super().__init__(f"{path}:{line}: {message}")
        self.detail = message
        self.path = path
        self.line = line


@dataclass(slots=True)
class Scalar:
    """一个原子值：标识符、数字、字符串字面量或带引号的文本。"""

    text: str
    quoted: bool = False
    line: int = 0

    @property
    def unquoted(self) -> str:
        """去掉外层引号后的文本。"""
        if self.quoted and len(self.text) >= 2 and self.text[0] == '"':
            return self.text[1:-1]
        return self.text

    def __str__(self) -> str:  # pragma: no cover - 便于调试
        return self.text


@dataclass(slots=True)
class Block:
    """花括号块。``items`` 里可以混合赋值、匿名子块与裸标量（列表）。"""

    items: list[Node] = field(default_factory=list)
    line: int = 0

    # ── 遍历辅助 ───────────────────────────────────────────
    def assignments(self) -> Iterator[Assignment]:
        for it in self.items:
            if isinstance(it, Assignment):
                yield it

    def keys(self) -> list[str]:
        return [a.key for a in self.assignments()]

    def first(self, key: str) -> Assignment | None:
        for a in self.assignments():
            if a.key == key:
                return a
        return None

    def all(self, key: str) -> list[Assignment]:
        return [a for a in self.assignments() if a.key == key]

    def scalars(self) -> Iterator[Scalar]:
        """裸标量，即列表形式 ``key = { a b c }`` 里的元素。"""
        for it in self.items:
            if isinstance(it, Scalar):
                yield it

    def __len__(self) -> int:
        return len(self.items)


@dataclass(slots=True)
class Assignment:
    """``key <op> value`` 形式的一条语句。"""

    key: str
    op: str
    value: Block | Scalar | None
    prefix: str | None = None
    line: int = 0

    @property
    def is_block(self) -> bool:
        return isinstance(self.value, Block)

    @property
    def is_variable(self) -> bool:
        """是否为 ``@变量`` 定义，而非数据条目。

        PDX 里 ``@name = 12`` 是脚本变量（用于公式），语义上**不是**
        一条数据库条目。``00_defines.txt`` 顶部就有 22 个这样的定义，
        把它们混进命名空间计数会让 75 变成 97。
        """
        return self.key.startswith("@")

    @property
    def is_namespace(self) -> bool:
        """是否为命名空间块：大写字母开头、非变量、且是块。"""
        return not self.is_variable and self.is_block and self.key[:1].isupper()

    @property
    def full_key(self) -> str:
        """带前缀的完整键名，例如 ``REPLACE:foo``。"""
        return f"{self.prefix}:{self.key}" if self.prefix else self.key


Node = Assignment | Block | Scalar

type ParseStatus = Literal["complete", "partial", "failed"]


class ParseDiagnostic(TypedDict):
    """可按类别与源位置查找的语法诊断。"""

    kind: str
    line: int
    column: int


@dataclass(slots=True)
class ParsedFile:
    """一个已解析的 PDX 文件。"""

    path: str
    root: Block
    encoding: str = "utf-8-sig"
    had_bom: bool = False
    errors: list[str] = field(default_factory=list)
    #: 文件里的全部 ``#`` 注释，``(行号, 原文)`` 按出现顺序。
    #:
    #: 注释此前被整体丢弃，但原版脚本里的注释往往是对字段**唯一的说明**
    #: （官方 .md 覆盖不到的字段只能看它）。保留它等于把官方写在旁边的
    #: 文档一起留下来。由 :func:`pdx.lexer.tokenize` 顺带收集，
    #: token 流本身不受影响。
    comments: list[tuple[int, str]] = field(default_factory=list)
    #: 最大花括号嵌套深度，用于完整性自检。
    #:
    #: **由解析器在解析时记录**，不是事后遍历 AST 算出来的 ——
    #: 后者要为每个文件把整棵树再递归走一遍，而深度在解析过程中本来就已知。
    #: 语义与旧实现一致：根为 0，每进一层块加 1，匿名块同样计入。
    max_depth: int = 0
    diagnostics: list[ParseDiagnostic] = field(default_factory=list)
    #: AST 未接纳的 token，保留 (kind, value, line, column)，不含文件尾标记。
    unconsumed_tokens: list[tuple[str, str, int, int]] = field(default_factory=list)
    token_count: int = 0
    decoding_error: str | None = None

    @property
    def parse_status(self) -> ParseStatus:
        """说明解码和语法完整性，替换解码得到的树仍标记为失败。"""
        if self.decoding_error is not None:
            return "failed"
        if self.diagnostics or self.errors or self.unconsumed_tokens:
            return "partial"
        return "complete"

    @property
    def consumed_token_count(self) -> int:
        return self.token_count - len(self.unconsumed_tokens)

    def require_complete(self) -> None:
        """需要完整输入的读取方可在使用 AST 前显式核验。"""
        status = self.parse_status
        if status == "complete":
            return
        line = 0
        if self.decoding_error is not None:
            detail = self.decoding_error
        elif self.diagnostics:
            first = self.diagnostics[0]
            line = first["line"]
            detail = f"{first['kind']}（第 {line} 行第 {first['column']} 列）"
        elif self.errors:
            detail = "；".join(self.errors)
        else:
            kind, _, line, column = self.unconsumed_tokens[0]
            detail = f"未接纳 {kind}（第 {line} 行第 {column} 列）"
        raise ParseError(f"parse_status={status}: {detail}", self.path, line)

    # ── 便捷视图 ───────────────────────────────────────────
    @property
    def top_keys(self) -> list[str]:
        """顶层键名（不含前缀）。**包含** ``@变量``，如实反映文件内容。"""
        return [a.key for a in self.root.assignments()]

    @property
    def top_assignments(self) -> list[Assignment]:
        return list(self.root.assignments())

    def namespace_blocks(self) -> list[Assignment]:
        """命名空间块：大写开头、非变量、是块。用于 defines 统计。"""
        return [a for a in self.root.assignments() if a.is_namespace]

    def variables(self) -> list[Assignment]:
        """``@变量`` 定义。"""
        return [a for a in self.root.assignments() if a.is_variable]

    def prefixed(self) -> list[Assignment]:
        """带功能前缀的顶层赋值。"""
        return [a for a in self.root.assignments() if a.prefix]
