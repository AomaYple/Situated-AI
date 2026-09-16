"""测试辅助：结构化指纹。

为什么需要它
------------
比较两个 :class:`~pdx.model.ParsedFile` 时，**行号与列号是噪声**。
做变形测试（加注释、换缩进、CRLF 化）时行号必然变化，但语义没变。
直接比 dataclass 会全部失败，比的就不是我们关心的东西了。

因此 :func:`signature` 把 AST 投影成**只保留语义**的嵌套元组：
键名、运算符、前缀、标量字面量与是否带引号、块的嵌套结构。
行号、列号、以及 ``quoted`` 之外的词法细节一律丢弃。
"""

from __future__ import annotations

from pdx.model import Assignment, Block, ParsedFile, Scalar

#: 递归深度上限，防止构造出的畸形 AST 把测试挂死
_MAX_DEPTH = 60


def node_signature(node: object, depth: int = 0) -> object:
    """把一个 AST 节点投影成语义指纹（不含行号/列号）。"""
    if depth > _MAX_DEPTH:  # pragma: no cover - 正常输入不会触发
        return ("<too-deep>",)

    if node is None:
        return None
    if isinstance(node, Block):
        return ("block", tuple(node_signature(i, depth + 1) for i in node.items))
    if isinstance(node, Assignment):
        return (
            "assign",
            node.prefix,
            node.key,
            node.op,
            node_signature(node.value, depth + 1),
        )
    if isinstance(node, Scalar):
        return ("scalar", node.text, node.quoted)
    raise TypeError(f"未知节点类型：{type(node)!r}")  # pragma: no cover


def signature(pf: ParsedFile) -> object:
    """整个文件的语义指纹。"""
    return node_signature(pf.root)


def top_signature(pf: ParsedFile) -> list[tuple[str, str, str]]:
    """只需顶层时的轻量指纹：``(前缀, 键, 运算符)`` 列表。"""
    return [(a.prefix or "", a.key, a.op) for a in pf.root.assignments()]


def entry_keys(pf: ParsedFile) -> set[str]:
    """数据条目键集合（排除 ``@变量``）。"""
    return {a.key for a in pf.root.assignments() if not a.is_variable}


def variable_keys(pf: ParsedFile) -> set[str]:
    """``@变量`` 键集合。"""
    return {a.key for a in pf.root.assignments() if a.is_variable}
