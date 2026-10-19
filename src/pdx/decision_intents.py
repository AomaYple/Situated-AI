"""把有界战略依赖图编译为现有 AND 谓词，不创建运行期战略状态。"""

from __future__ import annotations

import copy
import hashlib
import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import config

SOURCE = config.REPO / "mod/decisions/strategic.toml"
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
GRAPH_BUDGET = {"signals": 32, "intents": 32, "depth": 8}
# 原有规则生成护栏，decision_rules 继续公开同一对象；图展开不能绕开它。
STATIC_BUDGET = {"candidates_per_field": 32, "predicates_per_field": 160, "predicates_per_rule": 16}


@dataclass(frozen=True, slots=True)
class Intent:
    id: str
    requires: tuple[str, ...]
    signals: tuple[str, ...]
    conditions: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class Strategy:
    intents: tuple[Intent, ...]
    source_sha256: str

    def closure(self, names: set[str]) -> tuple[Intent, ...]:
        definitions = {intent.id: intent for intent in self.intents}
        selected: set[str] = set()

        def visit(name: str) -> None:
            if name not in definitions:
                raise ValueError(f"规则引用了未知战略意图：{name}")
            if name not in selected:
                selected.add(name)
                for dependency in definitions[name].requires:
                    visit(dependency)

        for name in sorted(names):
            visit(name)
        return tuple(intent for intent in self.intents if intent.id in selected)

    def expand(self, name: str) -> list[dict]:
        selected = self.closure({name})
        return copy.deepcopy(
            list(next(intent.conditions for intent in selected if intent.id == name))
        )

    def contract(self, names: set[str]) -> dict[str, object]:
        return {
            "source_sha256": self.source_sha256,
            "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "composition": "generation_time_and_dag; nonexclusive_current_input_constraints",
            "priority": "existing_per_field_rule_priority; one_adjustment",
            "graph_budget": dict(GRAPH_BUDGET),
            "intents": [
                {
                    "id": intent.id,
                    "requires": list(intent.requires),
                    "signals": list(intent.signals),
                    "conditions": copy.deepcopy(intent.conditions),
                }
                for intent in self.closure(names)
            ],
        }


def load(source: Path = SOURCE) -> Strategy:
    raw = source.read_bytes()
    return from_data(
        tomllib.loads(raw.decode("utf-8")), source_sha256=hashlib.sha256(raw).hexdigest()
    )


def _names(value: object, available: dict, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(name, str) or name not in available for name in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"战略{label}引用未知或重复名称")
    return tuple(value)


def _conditions(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("战略条件必须是列表")
    for condition in value:
        if (
            not isinstance(condition, dict)
            or set(condition) != {"fact", "op", "value"}
            or not isinstance(condition["fact"], str)
            or not _NAME.fullmatch(condition["fact"])
            or not isinstance(condition["op"], str)
            or condition["op"] not in {"=", "<", "<=", ">", ">="}
        ):
            raise ValueError("战略条件必须引用类型化事实和已登记比较")
        literal = condition["value"]
        if isinstance(literal, dict):
            if (
                set(literal) != {"fact"}
                or not isinstance(literal["fact"], str)
                or not _NAME.fullmatch(literal["fact"])
            ):
                raise ValueError("战略条件的相对比较引用无效")
        elif not isinstance(literal, (bool, int, float)):
            raise ValueError("战略条件只接受布尔、有限数值或事实引用")
        elif not isinstance(literal, bool):
            try:
                finite = math.isfinite(literal)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("战略条件只接受有限数值")
    return copy.deepcopy(value)


def from_data(data: dict, *, source_sha256: str) -> Strategy:
    """先验证全部图和展开预算，再由每个实际消费者验证事实类型和作用域。"""
    if (
        not isinstance(data, dict)
        or set(data) != {"schema", "signals", "intents"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or any(
            not isinstance(data[key], dict) or not data[key] or len(data[key]) > GRAPH_BUDGET[key]
            for key in ("signals", "intents")
        )
    ):
        raise ValueError("战略图 schema 或数量预算无效")
    signals, raw_intents = data["signals"], data["intents"]
    if any(
        not isinstance(name, str) or not _NAME.fullmatch(name) for name in (*signals, *raw_intents)
    ):
        raise ValueError("战略名称无效")
    parsed_signals = {name: _conditions(conditions) for name, conditions in signals.items()}
    if any(not conditions for conditions in parsed_signals.values()):
        raise ValueError("战略信号不能无条件成立")
    definitions: dict[str, tuple[tuple[str, ...], tuple[str, ...], list[dict]]] = {}
    for name, item in raw_intents.items():
        if not isinstance(item, dict) or set(item) - {"requires", "signals", "conditions"}:
            raise ValueError("战略意图定义字段无效")
        definitions[name] = (
            _names(item.get("requires", []), raw_intents, "依赖"),
            _names(item.get("signals", []), signals, "信号"),
            _conditions(item.get("conditions", [])),
        )
    if {signal for _, names, _ in definitions.values() for signal in names} != signals.keys():
        raise ValueError("战略信号必须有实际意图消费者")
    resolved: dict[str, Intent] = {}
    depths: dict[str, int] = {}

    def resolve(name: str, visiting: frozenset[str]) -> Intent:
        if name in visiting:
            raise ValueError("战略意图依赖成环")
        if name in resolved:
            return resolved[name]
        requires, names, own = definitions[name]
        dependencies = [resolve(key, visiting | {name}) for key in requires]
        depth = 1 + max((depths[key] for key in requires), default=0)
        if depth > GRAPH_BUDGET["depth"]:
            raise ValueError("战略意图超过依赖深度预算")
        conditions: list[dict] = []
        seen: set[tuple] = set()
        for group in (
            [item.conditions for item in dependencies]
            + [parsed_signals[key] for key in names]
            + [own]
        ):
            for predicate in group:
                literal = predicate["value"]
                # bool 与 0/1 在 Python 中相等，不能在类型门禁前把错误数值去掉。
                typed_value = (
                    ("fact", literal["fact"])
                    if isinstance(literal, dict)
                    else ("boolean", literal)
                    if type(literal) is bool
                    else ("number", literal)
                )
                key = (predicate["fact"], predicate["op"], typed_value)
                if key not in seen:
                    seen.add(key)
                    conditions.append(predicate)
                    if len(conditions) > STATIC_BUDGET["predicates_per_rule"]:
                        raise ValueError("战略意图展开超过既有谓词预算")
        if not conditions:
            raise ValueError("战略意图不能无条件成立")
        depths[name] = depth
        resolved[name] = Intent(name, requires, names, tuple(conditions))
        return resolved[name]

    for name in sorted(definitions):
        resolve(name, frozenset())
    return Strategy(tuple(resolved[name] for name in sorted(resolved)), source_sha256)
