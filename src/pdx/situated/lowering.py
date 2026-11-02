"""独立检查已生成 PDX 文本中的行动见证。"""

from __future__ import annotations

import re
from collections.abc import Iterable  # noqa: TC003
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import Assignment, Block, Scalar  # noqa: TID252
from ..parser import parse_text  # noqa: TID252

if TYPE_CHECKING:
    from .ir import ActionIR

_MARKER = re.compile(
    r"^\s*#\s+(?:(?:ACTION\s+)?([a-z][a-z0-9_]*)|([a-z][a-z0-9_]*))\s+\[[a-z][a-z0-9_]*\];"
)
_WRITE = re.compile(r"\b(multiply|add)\s*=\s*(?:\{\s*value\s*=\s*)?(-?[0-9]+(?:\.[0-9]+)?)")


@dataclass(frozen=True, slots=True)
class LoweringWitness:
    action_id: str
    source: str
    operation: str
    value: float
    parsed: bool


@dataclass(frozen=True, slots=True)
class ASTWitness:
    """独立 AST 见证，不调用 Python 参考求值器。"""

    action_id: str
    source: str
    has_limit: bool
    has_write: bool
    nested_condition_count: int
    parsed: bool


def _block_text(lines: list[str], start: int) -> str:
    depth = 0
    started = False
    parts: list[str] = []
    for line in lines[start:]:
        parts.append(line)
        depth += line.count("{") - line.count("}")
        started = started or "{" in line
        if started and depth <= 0:
            break
    return "\n".join(parts)


def _transparent_write(item: Assignment) -> bool:
    """Recognise only the exact unconditional wrapper emitted by lowering.

    A direct numeric write is valid.  The auxiliary branch may add one
    transparent ``if`` whose sole limit is ``always = yes``; arbitrary
    nested conditions and writes inside a limit block must not satisfy
    the witness, because they can change runtime semantics.
    """

    if item.op != "=" or item.prefix is not None:
        return False
    if item.key in {"add", "multiply"}:
        value = item.value
        if isinstance(value, Block):
            values = value.all("value")
            value = (
                values[0].value
                if len(values) == 1 and values[0].op == "=" and values[0].prefix is None
                else None
            )
        return isinstance(value, Scalar) and bool(
            re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value.text)
        )
    if item.key != "if" or not isinstance(item.value, Block):
        return False
    nested = list(item.value.assignments())
    limits = [child for child in nested if child.key == "limit" and child.is_block]
    writes = [child for child in nested if child.key in {"add", "multiply"}]
    if len(limits) != 1 or len(writes) != 1 or len(item.value.items) != 2:
        return False
    limit = limits[0].value
    assert isinstance(limit, Block)
    limit_items = list(limit.assignments())
    if (
        len(limit.items) != 1
        or len(limit_items) != 1
        or limit_items[0].key != "always"
        or limit_items[0].op != "="
        or limit_items[0].prefix is not None
        or limits[0].op != "="
        or limits[0].prefix is not None
    ):
        return False
    always = limit_items[0].value
    return isinstance(always, Scalar) and always.text == "yes" and _transparent_write(writes[0])


def ast_witnesses(texts: dict[str, str]) -> tuple[ASTWitness, ...]:
    """从生成文本 AST 独立检查 action 块的 limit/write 结构。"""

    result: list[ASTWitness] = []
    for source, text in sorted(texts.items()):
        lines = text.splitlines()
        for index, line in enumerate(lines):
            marker = _MARKER.match(line)
            if marker is None:
                continue
            action_id = marker.group(1) or marker.group(2)
            block = _block_text(lines, index + 1)
            parsed = parse_text(block, path=f"{source}:{index + 1}")
            if parsed.errors:
                raise ValueError(f"行动 AST 无法解析：{source}:{index + 1}")
            root = next(
                (item for item in parsed.root.assignments() if item.key in {"if", "else_if"}), None
            )
            if root is None or not isinstance(root.value, Block):
                result.append(ASTWitness(action_id, source, False, False, 0, True))
                continue
            assignments = list(root.value.assignments())
            has_limit = any(item.key == "limit" and item.is_block for item in assignments)

            has_write = any(_transparent_write(item) for item in assignments)
            nested = sum(
                1 for item in assignments if item.key in {"if", "else_if"} and item.is_block
            )
            result.append(ASTWitness(action_id, source, has_limit, has_write, nested, True))
    return tuple(result)


def ast_mismatches(texts: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.action_id
            for item in ast_witnesses(texts)
            if not item.has_limit or not item.has_write
        )
    )


def witnesses(texts: dict[str, str]) -> tuple[LoweringWitness, ...]:
    result: list[LoweringWitness] = []
    for source, text in sorted(texts.items()):
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"PDX 产物无法解析：{source}")
        lines = text.splitlines()
        for index, line in enumerate(lines):
            marker = _MARKER.match(line)
            if marker is None:
                continue
            action_id = marker.group(1) or marker.group(2)
            next_marker = next(
                (pos for pos in range(index + 1, len(lines)) if _MARKER.match(lines[pos])),
                len(lines),
            )
            write = _WRITE.search("\n".join(lines[index:next_marker]))
            if write is None:
                continue
            result.append(
                LoweringWitness(
                    action_id=action_id,
                    source=source,
                    operation=write.group(1),
                    value=float(write.group(2)),
                    parsed=True,
                )
            )
    return tuple(result)


def missing(ir: Iterable[ActionIR], texts: dict[str, str]) -> tuple[str, ...]:
    found = {item.action_id for item in witnesses(texts)}
    return tuple(item.action_id for item in ir if item.action_id not in found)


def mismatches(ir: Iterable[ActionIR], texts: dict[str, str]) -> tuple[str, ...]:
    expected = {item.action_id: item for item in ir}
    problems: list[str] = []
    for item in witnesses(texts):
        wanted = expected.get(item.action_id)
        if wanted is None:
            continue
        if item.operation != wanted.operation or item.value != wanted.value:
            problems.append(item.action_id)
    return tuple(sorted(problems))


__all__ = [
    "ASTWitness",
    "LoweringWitness",
    "ast_mismatches",
    "ast_witnesses",
    "mismatches",
    "missing",
    "witnesses",
]
