"""受限但独立的 PDX 行动求值器。

该模块只解释行动内核生成的条件/增量子集。它不导入或调用
``decision_rules.evaluate``、仲裁器或其它 Python 参考选择器；生成文本先解析为
AST，再由这里按三值逻辑求值。遇到未登记的脚本结构会显式失败，避免把不支持的
引擎语义误判成通过。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text

from .expressions import truth_all, truth_any, truth_not

Truth = Literal[True, False, None]
_MARKER = re.compile(r"^\s*# (?:(?:ACTION )?)([a-z][a-z0-9_]*) \[[a-z][a-z0-9_]*\];")
_SCOPES = frozenset(
    {
        "ROOT",
        "owner",
        "market",
        "overlord",
        "scope:target_state",
        "scope:target_country",
        "scope:overlord",
        "scope:interest_group",
    }
)
_GOODS_SCOPE = re.compile(r"(?:mg|sg):[a-z][a-z0-9_]*\Z")
_INTEREST_GROUP_SCOPE = re.compile(r"ig:ig_[a-z][a-z0-9_]*\Z")
_REFERENCE = re.compile(r"(?:ROOT|scope:[a-z][a-z0-9_]*)(?:\.[a-z][a-z0-9_]*)+\Z")
_NUMERIC_OPS = frozenset({"=", "<", "<=", ">", ">="})
_PARAMETER_QUERIES = frozenset(
    {
        "has_diplomatic_pact",
        "has_law_or_variant",
        "has_strategy",
        "has_technology_researched",
        "has_treaty_alliance_with",
        "has_truce_with",
        "has_variable",
        "is_homeland_of_country_cultures",
        "owner",
        "is_production_method_active",
        "is_subject_of",
        "pop_type_percent_country",
        "primary_cultures_percent_state",
        "radical_fraction",
        "has_institution",
        "institution_investment_level",
        "is_building_type",
        "has_active_production_method",
        "law_enactment_stance",
        "law_stance",
    }
)
_PARAMETER_QUERY_BLOCKS: dict[str, tuple[frozenset[str], str | None]] = {
    "has_diplomatic_pact": (frozenset({"who", "type"}), None),
    "has_treaty_alliance_with": (frozenset({"TARGET"}), None),
    "pop_type_percent_country": (frozenset({"pop_type"}), "percent"),
    "primary_cultures_percent_state": (frozenset({"target_country"}), "value"),
    "radical_fraction": (frozenset(), "value"),
    "institution_investment_level": (frozenset({"institution"}), "value"),
    "law_enactment_stance": (frozenset({"law"}), "value"),
    "law_stance": (frozenset({"law"}), "value"),
}


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


def _parameter_query(assignment: Assignment, facts: Mapping[str, object | None]) -> Truth:
    """Evaluate the two explicitly supported parameterized vanilla queries.

    The generated PDX keeps the engine's parameter block intact.  Fixtures use
    a typed mapping under the query name, so a missing parameter or a missing
    mapping remains unknown rather than becoming a global boolean.
    """

    if assignment.op != "=":
        raise UnsupportedPdxError(f"参数化查询 {assignment.key} 必须使用等号")
    if assignment.key == "is_production_method_active":
        if not isinstance(assignment.value, Block):
            raise UnsupportedPdxError("is_production_method_active 必须使用参数块")
        if any(not isinstance(item, Assignment) for item in assignment.value.items):
            raise UnsupportedPdxError("is_production_method_active 参数块含非赋值项")
        production_parameters = _parameter_block(
            assignment.value, allowed={"building_type", "production_method"}
        )
        if set(production_parameters) != {"building_type", "production_method"}:
            raise UnsupportedPdxError("is_production_method_active 参数不完整")
        # PDX identifiers may contain hyphens; preserve the source spelling.
        if any(
            not re.fullmatch(r"[a-z][a-z0-9_-]*", value) for value in production_parameters.values()
        ):
            raise UnsupportedPdxError("is_production_method_active 参数身份无效")
        result = facts.get(assignment.key)
        if result is None:
            return None
        if not isinstance(result, Mapping):
            raise UnsupportedPdxError("is_production_method_active 观测值必须是映射")
        current: object = result
        for name in (
            production_parameters["building_type"],
            production_parameters["production_method"],
        ):
            if current is None:
                return None
            if not isinstance(current, Mapping):
                raise UnsupportedPdxError("is_production_method_active 观测映射形状无效")
            current = current.get(name)
        if current is not None and type(current) is not bool:
            raise UnsupportedPdxError("is_production_method_active 结果必须是布尔或未知")
        return current

    parameters: dict[str, str]
    value_field: str | None = None
    value_op: str | None = None
    expected: float | None = None
    if isinstance(assignment.value, Scalar):
        if assignment.key in _PARAMETER_QUERY_BLOCKS:
            raise UnsupportedPdxError(f"参数化查询 {assignment.key} 必须使用参数块")
        argument = assignment.value.unquoted
        if argument in {"yes", "no"} or not re.fullmatch(r"[a-z][a-z0-9_:-]*", argument):
            raise UnsupportedPdxError(f"参数化查询 {assignment.key} 参数身份无效")
        parameters = {"argument": argument}
    elif isinstance(assignment.value, Block):
        block_shape = _PARAMETER_QUERY_BLOCKS.get(assignment.key)
        if block_shape is None:
            raise UnsupportedPdxError(f"参数化查询 {assignment.key} 不支持参数块形状")
        items = list(assignment.value.assignments())
        if len(items) != len(assignment.value.items):
            raise UnsupportedPdxError(f"参数化查询 {assignment.key} 含非赋值参数")
        value_items = [item for item in items if item.key in {"value", "percent"}]
        parameter_items = [item for item in items if item not in value_items]
        if len(value_items) > 1:
            raise UnsupportedPdxError(f"参数化查询 {assignment.key} 的数值字段重复")
        allowed, required_value = block_shape
        parameters = _parameter_block(Block([*parameter_items]), allowed=set(allowed))
        if set(parameters) != set(allowed):
            raise UnsupportedPdxError(f"参数化查询 {assignment.key} 参数不完整")
        if value_items:
            value_field = value_items[0].key
            value_op = value_items[0].op
            if value_field not in {"value", "percent"} or value_op not in _NUMERIC_OPS:
                raise UnsupportedPdxError(f"参数化查询 {assignment.key} 的数值比较无效")
            if required_value != value_field:
                raise UnsupportedPdxError(f"参数化查询 {assignment.key} 数值字段不匹配")
            if assignment.key in {"law_enactment_stance", "law_stance"}:
                if _scalar(value_items[0], label="law stance").unquoted != "neutral":
                    raise UnsupportedPdxError("法律运动立场仅支持相对 neutral 的有序比较")
                expected = 0.0
            else:
                expected = _number(value_items[0])
        elif required_value is not None:
            raise UnsupportedPdxError(f"参数化查询 {assignment.key} 缺少数值比较")
    else:
        raise UnsupportedPdxError(f"参数化查询 {assignment.key} 参数必须是标量或块")

    identity = tuple(sorted(parameters.items()))
    result = facts.get(assignment.key)
    if result is None:
        return None
    if not isinstance(result, Mapping):
        raise UnsupportedPdxError(f"参数化查询 {assignment.key} 必须是按完整参数身份索引的映射")
    observed = result.get(identity)
    if value_field is not None:
        if observed is None:
            return None
        if type(observed) not in (int, float) or not math.isfinite(float(observed)):
            raise UnsupportedPdxError(f"参数化查询 {assignment.key} 数值观测必须有限或未知")
        return _compare(observed, cast("str", value_op), expected)
    if observed is not None and type(observed) is not bool:
        raise UnsupportedPdxError(f"参数化查询 {assignment.key} 结果必须是布尔或未知")
    return observed


def _parameter_block(block: Block, *, allowed: set[str] | None) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for item in block.assignments():
        if allowed is not None and item.key not in allowed:
            raise UnsupportedPdxError(f"参数化查询出现未登记参数：{item.key}")
        if item.op != "=" or item.prefix is not None or not isinstance(item.value, Scalar):
            raise UnsupportedPdxError("参数化查询参数必须是标量赋值")
        literal = item.value.unquoted
        if not re.fullmatch(r"[a-z][a-z0-9_:-]*", literal):
            raise UnsupportedPdxError("参数化查询参数身份无效")
        if item.key in parameters:
            raise UnsupportedPdxError(f"参数化查询参数重复：{item.key}")
        parameters[item.key] = literal
    return parameters


def _resolve_reference(expression: str, root: Mapping[str, object | None]) -> object | None:
    if not _REFERENCE.fullmatch(expression):
        raise UnsupportedPdxError(f"未登记的 fact reference：{expression}")
    head, *path = expression.split(".")
    if head == "ROOT":
        current: object | None = root.get("ROOT")
    else:
        current = root.get(head)
    for part in path:
        if current is None:
            return None
        if not isinstance(current, Mapping):
            raise UnsupportedPdxError(f"fact reference 路径不是映射：{expression}")
        current = current.get(part)
    return current


def _compare(left: object, operator: str, right: object) -> Truth:
    if operator not in _NUMERIC_OPS:
        raise UnsupportedPdxError(f"不支持的条件运算符：{operator}")
    if type(left) is bool or type(right) is bool:
        if type(left) is not bool or type(right) is not bool:
            return None
    elif type(left) not in (int, float) or type(right) not in (int, float):
        return None
    else:
        left_number = float(cast("int | float", left))
        right_number = float(cast("int | float", right))
        if not math.isfinite(left_number) or not math.isfinite(right_number):
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
    block: Block,
    facts: Mapping[str, object | None],
    *,
    mode: Literal["all", "any"] = "all",
    root: Mapping[str, object | None] | None = None,
) -> Truth:
    # Flat fixtures explicitly describe the initial ROOT context. Bind it once
    # at the entry, so regrouping AND/OR never changes scope resolution. A
    # provided ROOT (including None) always wins over flat decoy facts.
    anchor = ({"ROOT": facts} if "ROOT" not in facts else facts) if root is None else root

    def scope(name: str) -> tuple[bool, Mapping[str, object | None] | None]:
        context = anchor if name == "ROOT" else facts
        if name not in context:
            return False, None
        value = context[name]
        if value is not None and not isinstance(value, Mapping):
            raise UnsupportedPdxError(f"作用域 {name} 必须是映射或明确缺失")
        return True, value

    values: list[Truth] = []
    for item in block.items:
        if not isinstance(item, Assignment):
            raise UnsupportedPdxError("条件块包含匿名或裸值")
        if item.key in {
            "any_political_movement",
            "any_interest_group",
            "any_scope_state",
            "any_scope_building",
        }:
            if item.op != "=" or item.prefix is not None or not isinstance(item.value, Block):
                raise UnsupportedPdxError("本国集合查询必须是普通赋值块")
            collection = facts.get(item.key)
            if collection is None:
                values.append(None)
                continue
            if not isinstance(collection, (list, tuple)) or any(
                not isinstance(candidate, Mapping) for candidate in collection
            ):
                raise UnsupportedPdxError("本国集合观测必须是完整对象列表，不能预先传入聚合布尔")
            values.append(
                truth_any(
                    tuple(
                        _condition(item.value, candidate, root=anchor) for candidate in collection
                    )
                )
            )
            continue
        if item.key in {"AND", "OR", "NOT"}:
            if not isinstance(item.value, Block):
                raise UnsupportedPdxError(f"{item.key} 条件必须是块")
            nested_mode: Literal["all", "any"] = "any" if item.key == "OR" else "all"
            nested = _condition(item.value, facts, mode=nested_mode, root=anchor)
            if item.key == "NOT":
                values.append(truth_not(nested))
            else:
                values.append(nested)
            continue
        if isinstance(item.value, Block) and (
            item.key in _SCOPES
            or _GOODS_SCOPE.fullmatch(item.key)
            or _INTEREST_GROUP_SCOPE.fullmatch(item.key)
        ):
            if item.op not in {"=", "?="}:
                raise UnsupportedPdxError(f"作用域 {item.key} 必须是赋值或可选赋值块")
            known, scoped = scope(item.key)
            if not known:
                values.append(None)
                continue
            if scoped is None:
                # Optional scope null behavior is not established by our
                # supported subset. Preserve uncertainty; an explicit exists
                # guard can still disprove the enclosing conjunction.
                values.append(None if item.op == "?=" else False)
                continue
            values.append(_condition(item.value, scoped, root=anchor))
            continue
        if item.key == "exists":
            name = _scalar(item, label="exists").unquoted
            if item.op != "=" or (
                name not in _SCOPES
                and not _GOODS_SCOPE.fullmatch(name)
                and not _INTEREST_GROUP_SCOPE.fullmatch(name)
            ):
                raise UnsupportedPdxError(f"未登记的存在性作用域：{name}")
            known, scoped = scope(name)
            values.append(scoped is not None if known else None)
            continue
        if item.key == "always":
            literal = _literal(_scalar(item, label="always"))
            if item.op != "=" or type(literal) is not bool:
                raise UnsupportedPdxError("always 必须是 yes/no 常量")
            values.append(literal)
            continue
        if item.key in _PARAMETER_QUERIES:
            values.append(_parameter_query(item, facts))
            continue
        if isinstance(item.value, Scalar):
            if item.key not in facts or facts[item.key] is None:
                values.append(None)
                continue
            actual = facts[item.key]
            scalar = _scalar(item, label=item.key)
            expected: object = _literal(scalar)
            if isinstance(expected, str) and _REFERENCE.fullmatch(expected):
                expected = _resolve_reference(expected, anchor)
            values.append(_compare(actual, item.op, expected))
            continue
        if isinstance(item.value, Block) and item.key in _PARAMETER_QUERIES:
            values.append(_parameter_query(item, facts))
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


def _numeric_value(assignment: Assignment, facts: Mapping[str, object | None]) -> float:
    """Interpret the generated numeric AST independently of the compiler.

    PDX script values execute operations in source order. Conditional blocks
    update the surrounding numeric accumulator; nested value blocks have a
    separate accumulator. Unknown optional conditions do not prove a branch.
    """
    if isinstance(assignment.value, Scalar):
        return _number(assignment)
    if not isinstance(assignment.value, Block):
        raise UnsupportedPdxError("数值表达式必须是标量或块")
    initial = assignment.value.first("value")
    if initial is None:
        raise UnsupportedPdxError("数值表达式缺少 value 初值")

    def execute(block: Block, value: float) -> float:
        chain_open = False
        selected = False
        for item in block.assignments():
            if item.key in {"value", "limit"}:
                continue
            if item.key in {"if", "else_if", "else"}:
                if not isinstance(item.value, Block):
                    raise UnsupportedPdxError("数值条件必须是块")
                if item.key == "if":
                    chain_open, selected = True, False
                elif not chain_open:
                    raise UnsupportedPdxError("数值 else 分支缺少前置 if")
                limit = item.value.first("limit")
                if item.key == "else":
                    state: Truth = True
                    chain_open = False
                elif limit is None or not isinstance(limit.value, Block):
                    raise UnsupportedPdxError("数值条件缺少 limit")
                else:
                    state = condition(limit.value, facts)
                if not selected and state is True:
                    value = execute(item.value, value)
                    selected = True
                continue
            chain_open = False
            if item.key == "desc":
                _scalar(item, label="desc")
                continue
            if item.key not in {"add", "subtract", "multiply", "divide", "min", "max"}:
                raise UnsupportedPdxError(f"不支持的数值操作：{item.key}")
            amount = _numeric_value(item, facts)
            if item.key == "add":
                value += amount
            elif item.key == "subtract":
                value -= amount
            elif item.key == "multiply":
                value *= amount
            elif item.key == "divide":
                if amount == 0:
                    raise UnsupportedPdxError("数值表达式除零")
                value /= amount
            elif item.key == "min":
                value = max(value, amount)
            elif item.key == "max":
                value = min(value, amount)
        return value

    return execute(assignment.value, _numeric_value(initial, facts))


def _effect_delta(branch: Block, facts: Mapping[str, object | None]) -> tuple[str, float]:
    operations = [item for item in branch.assignments() if item.key in {"add", "multiply"}]
    if len(operations) != 1:
        raise UnsupportedPdxError("一个行动分支必须有且只有一个顶层写入")
    operation = operations[0]
    delta = _numeric_value(operation, facts)
    # Legacy branches can carry an optional conditional addition beside the
    # primary scalar write. Numeric value blocks handle their own conditions.
    for nested in branch.all("if"):
        if not isinstance(nested.value, Block):
            raise UnsupportedPdxError("嵌套 if 必须是块")
        limit = nested.value.first("limit")
        if limit is None or not isinstance(limit.value, Block):
            raise UnsupportedPdxError("嵌套 if 缺少 limit 块")
        if condition(limit.value, facts) is True:
            additions = nested.value.all("add")
            if len(additions) != 1:
                raise UnsupportedPdxError("嵌套 if 必须有一个 add")
            delta += _numeric_value(additions[0], facts)
    return operation.key, delta


def evaluate(
    text: str, facts: Mapping[str, object | None], *, path: str = "<generated>"
) -> tuple[PdxDecision, ...]:
    """求值生成的行动 overlay，返回按字段顺序的决策。"""

    parsed = parse_text(text, path=path)
    if parsed.errors:
        raise UnsupportedPdxError("生成文本无法解析：" + "; ".join(parsed.errors))
    lines = text.splitlines()
    markers: dict[int, str] = {}
    for index, line in enumerate(lines):
        match = _MARKER.match(line)
        if match is None:
            continue
        branch_line = index + 1
        while branch_line < len(lines) and not lines[branch_line].strip():
            branch_line += 1
        markers[branch_line + 1] = match.group(1)

    def walk(block: Block, ancestor_marker: str | None = None) -> list[PdxDecision]:
        results: list[PdxDecision] = []
        matched = False
        chain_open = False
        for assignment in block.assignments():
            if assignment.key not in {"if", "else_if", "else"}:
                raise UnsupportedPdxError(f"未登记的行动分支：{assignment.key}")
            if assignment.key == "if":
                matched = False
                chain_open = True
            elif not chain_open:
                raise UnsupportedPdxError(f"{assignment.key} 分支缺少前置 if")
            if assignment.key == "else":
                chain_open = False
            if matched:
                continue
            if not isinstance(assignment.value, Block):
                raise UnsupportedPdxError("行动分支不是块")
            limit = assignment.value.first("limit")
            if assignment.key == "else":
                state: Truth = True
            elif limit is None or not isinstance(limit.value, Block):
                raise UnsupportedPdxError("行动分支缺少 limit 块")
            else:
                state = condition(limit.value, facts)
            writes = any(item.key in {"add", "multiply"} for item in assignment.value.assignments())
            if writes:
                action_id = markers.get(assignment.line, ancestor_marker)
                if action_id is None:
                    raise UnsupportedPdxError("行动分支缺少身份标记")
                if state is True:
                    operation, delta = _effect_delta(assignment.value, facts)
                    results.append(PdxDecision(action_id, operation, delta, "selected"))
                    return results
                if state is None:
                    results.append(PdxDecision(action_id, None, 0.0, "unknown"))
                    return results
                results.append(PdxDecision(action_id, None, 0.0, "vanilla"))
                continue
            # A write-free proof enters a tier only when its condition is true.
            # Unproven cost/benefit partitions continue along their outer chain;
            # writing branches above still stop on generic unknown conditions.
            if state is True:
                nested = Block(
                    [
                        item
                        for item in assignment.value.items
                        if not isinstance(item, Assignment) or item.key != "limit"
                    ]
                )
                results.extend(walk(nested, markers.get(assignment.line, ancestor_marker)))
                matched = True
        return results

    return tuple(walk(parsed.root))


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
        branch = "\n".join(lines[start : end + 1])
        parsed = parse_text(branch, path=path)
        if parsed.errors:
            raise UnsupportedPdxError("生成分支无法解析：" + "; ".join(parsed.errors))
        first = next(parsed.root.assignments(), None)
        if first is not None and first.key == "else_if":
            # A writer fragment loses the preceding production branch. Give
            # this isolated witness an explicit, impossible predecessor while
            # keeping the generic PDX evaluator strict about orphan else_if.
            return (
                f"# ACTION {action_id} [context];\n"
                "if = { limit = { always = no } }\n"
                f"# ACTION {action_id} [generated];\n{branch}"
            )
        return f"# ACTION {action_id} [generated];\n" + branch
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
