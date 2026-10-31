"""受限但独立的 PDX 行动求值器。

该模块只解释行动内核生成的条件/增量子集。它不导入或调用
``decision_rules.evaluate``、仲裁器或其它 Python 参考选择器；生成文本先解析为
AST，再由这里按三值逻辑求值。遇到未登记的脚本结构会显式失败，避免把不支持的
引擎语义误判成通过。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text

from .expressions import truth_all, truth_any, truth_not

Truth = Literal[True, False, None]
_MARKER = re.compile(r"^\s*# (?:(?:ACTION )?)([a-z][a-z0-9_]*) \[[a-z][a-z0-9_]*\];")
_CONDITION_KEYS = frozenset({"AND", "OR", "NOT", "ROOT"})
_NUMERIC_OPS = frozenset({"=", "<", "<=", ">", ">="})


class UnsupportedPdxError(RuntimeError):
    """生成文本包含独立求值器尚未支持的结构。"""


@dataclass(frozen=True, slots=True)
class PdxDecision:
    action_id: str | None
    operation: str | None
    delta: float
    fallback: Literal["selected", "vanilla", "unknown"]


def _literal(value: Scalar) -> bool | float | str:
    text = value.unquoted
    if text == "yes":
        return True
    if text == "no":
        return False
    try:
        number = float(text)
    except ValueError:
        return text
    if not math.isfinite(number):
        raise UnsupportedPdxError("PDX 数字不是有限值")
    return number


def _scalar(assignment: Assignment, *, label: str) -> Scalar:
    if not isinstance(assignment.value, Scalar):
        raise UnsupportedPdxError(f"{label} 必须使用标量")
    return assignment.value


def _compare(left: object, operator: str, right: object) -> Truth:
    if operator not in _NUMERIC_OPS:
        raise UnsupportedPdxError(f"不支持的条件运算符：{operator}")
    if type(left) is bool or type(right) is bool:
        if type(left) is not bool or type(right) is not bool:
            return None
    elif type(left) not in (int, float) or type(right) not in (int, float):
        return None
    if operator == "=":
        return left == right
    left_number = float(left) if isinstance(left, (int, float)) else 0.0
    right_number = float(right) if isinstance(right, (int, float)) else 0.0
    if operator == "<":
        return left_number < right_number
    if operator == "<=":
        return left_number <= right_number
    if operator == ">":
        return left_number > right_number
    return left_number >= right_number


def _condition(
    block: Block, facts: Mapping[str, object | None], *, mode: Literal["all", "any"] = "all"
) -> Truth:
    values: list[Truth] = []
    for item in block.items:
        if not isinstance(item, Assignment):
            raise UnsupportedPdxError("条件块包含匿名或裸值")
        if item.key in {"AND", "OR", "NOT", "ROOT"}:
            if not isinstance(item.value, Block):
                raise UnsupportedPdxError(f"{item.key} 条件必须是块")
            nested_mode: Literal["all", "any"] = "any" if item.key == "OR" else "all"
            nested = _condition(item.value, facts, mode=nested_mode)
            if item.key == "NOT":
                values.append(truth_not(nested))
            else:
                values.append(nested)
            continue
        if isinstance(item.value, Scalar):
            if item.key not in facts or facts[item.key] is None:
                values.append(None)
                continue
            actual = facts[item.key]
            expected = _literal(_scalar(item, label=item.key))
            values.append(_compare(actual, item.op, expected))
            continue
        raise UnsupportedPdxError(f"未登记的 PDX 条件：{item.key}")
    if not values:
        return True
    return truth_any(tuple(values)) if mode == "any" else truth_all(tuple(values))


def condition(block: Block, facts: Mapping[str, object | None]) -> Truth:
    """独立求值一个 ``limit`` 内的条件块。"""

    return _condition(block, facts)


def _number(assignment: Assignment) -> float:
    scalar = _scalar(assignment, label=assignment.key)
    value = _literal(scalar)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnsupportedPdxError(f"{assignment.key} 必须是数值")
    return float(value)


def _effect_delta(branch: Block, facts: Mapping[str, object | None]) -> tuple[str, float]:
    operation: Assignment | None = None
    for item in branch.assignments():
        if item.key in {"add", "multiply"}:
            if operation is not None:
                raise UnsupportedPdxError("一个行动分支包含多个顶层写入")
            operation = item
    if operation is None:
        raise UnsupportedPdxError("行动分支缺少写入")
    delta = _number(operation)
    for nested in branch.all("if"):
        if not isinstance(nested.value, Block):
            raise UnsupportedPdxError("嵌套 if 必须是块")
        limit = nested.value.first("limit")
        if limit is None or not isinstance(limit.value, Block):
            raise UnsupportedPdxError("嵌套 if 缺少 limit 块")
        result = condition(limit.value, facts)
        if result is True:
            nested_write = next(
                (item for item in nested.value.assignments() if item.key == "add"), None
            )
            if nested_write is None:
                raise UnsupportedPdxError("嵌套 if 缺少 add")
            delta += _number(nested_write)
        elif result is None:
            raise UnsupportedPdxError("嵌套条件未知，不能静默解释")
    return operation.key, delta


def evaluate(
    text: str, facts: Mapping[str, object | None], *, path: str = "<generated>"
) -> tuple[PdxDecision, ...]:
    """求值生成的行动 overlay，返回按字段顺序的决策。"""

    parsed = parse_text(text, path=path)
    if parsed.errors:
        raise UnsupportedPdxError("生成文本无法解析：" + "; ".join(parsed.errors))
    markers = [match.group(1) for line in text.splitlines() if (match := _MARKER.match(line))]
    branches = [item for item in parsed.root.assignments() if item.key in {"if", "else_if"}]
    if len(markers) != len(branches):
        raise UnsupportedPdxError("行动标记与分支数量不一致")
    decisions: list[PdxDecision] = []
    for action_id, branch_assignment in zip(markers, branches, strict=True):
        if not isinstance(branch_assignment.value, Block):
            raise UnsupportedPdxError("行动分支不是块")
        limit = branch_assignment.value.first("limit")
        if limit is None or not isinstance(limit.value, Block):
            raise UnsupportedPdxError("行动分支缺少 limit 块")
        result = condition(limit.value, facts)
        if result is True:
            operation, delta = _effect_delta(branch_assignment.value, facts)
            decisions.append(PdxDecision(action_id, operation, delta, "selected"))
        elif result is None:
            decisions.append(PdxDecision(action_id, None, 0.0, "unknown"))
        else:
            decisions.append(PdxDecision(action_id, None, 0.0, "vanilla"))
    return tuple(decisions)


def marked_block(text: str, action_id: str, *, path: str = "<generated>") -> str:
    """提取一个带 ``# id [domain];`` 标记的生产分支。"""

    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _MARKER.match(line)
        if match is None or match.group(1) != action_id:
            continue
        start = index + 1
        while start < len(lines) and not lines[start].strip():
            start += 1
        if start >= len(lines):
            raise UnsupportedPdxError(f"行动标记后没有分支：{action_id}")
        depth = 0
        seen = False
        end = start
        for end in range(start, len(lines)):
            current = lines[end]
            depth += current.count("{") - current.count("}")
            seen = seen or "{" in current
            if seen and depth <= 0:
                break
        return f"# ACTION {action_id} [generated];\n" + "\n".join(lines[start : end + 1])
    raise UnsupportedPdxError(f"找不到行动标记：{action_id} in {path}")


def select(
    text: str, facts: Mapping[str, object | None], *, path: str = "<generated>"
) -> PdxDecision:
    """按生成的 ``if/else_if`` 顺序选择一个分支。"""

    decisions = evaluate(text, facts, path=path)
    for item in decisions:
        if item.fallback == "selected":
            return item
        if item.fallback == "unknown":
            return PdxDecision(item.action_id, None, 0.0, "unknown")
    return PdxDecision(None, None, 0.0, "vanilla")


__all__ = [
    "PdxDecision",
    "UnsupportedPdxError",
    "condition",
    "evaluate",
    "marked_block",
    "select",
]
