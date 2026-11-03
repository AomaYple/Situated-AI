"""声明式处境规则：同一来源生成原版脚本、参考结果和接口清单。

只修改明确登记的脚本值，在字段专属安全位置调整常规评分，再执行原版
拒绝、截断和特殊尾项。生产编译可显式启用类型化消费者贡献程序；未迁移的
RuleSet 输入保留历史兼容语义。没有读取依据时不生成，也不把静态依据当实机证据。
"""

from __future__ import annotations

import hashlib
import importlib
import math
import operator
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from . import config, decision_intents, decision_interfaces, observation_queries
from .lexer import ATOM, LBRACE, OP, RBRACE, tokenize
from .model import Block, Scalar
from .parser import parse_text
from .textio import normalized_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .country_state import CountryPolicy
    from .situated.decision_ir import ConsumerIRBundle, WriterDecisionIR
    from .situated.ir import ActionIR
    from .situated.programs import ConsumerProgram

SOURCE = config.REPO / "mod/decisions/information.toml"
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_SCOPES = frozenset({"root", "target_country", "target_state", "overlord", "interest_group"})
_OPS = {"=": operator.eq, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
# 静态增长护栏，不是游戏运行耗时承诺；扩大须重新冻结并测量候选。
STATIC_BUDGET = decision_intents.STATIC_BUDGET


def _country_state_module():
    return importlib.import_module("pdx.country_state")


def _finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True, slots=True)
class Reader:
    key: str
    engine: str
    scope: str
    unit: str
    kind: str
    argument: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    path: tuple[str, ...] = ()
    value_field: str | None = None
    parameters: tuple[tuple[str, str], ...] = ()

    def accepts(self, value: object) -> bool:
        if self.kind == "boolean":
            return type(value) is bool
        if not _finite(value) or not isinstance(value, (int, float)):
            return False
        return (self.minimum is None or value >= self.minimum) and (
            self.maximum is None or value <= self.maximum
        )

    def reference(self) -> str:
        """只为无参数数值 getter 生成具名引用，不接受外部自由表达式。"""
        if self.kind != "number" or self.argument or self.parameters or self.value_field:
            raise ValueError("比较右侧必须是无参数的数值 getter")
        scope = "ROOT" if self.scope == "root" else f"scope:{self.scope}"
        return ".".join((scope, *self.path, self.engine))

    def expression(self, op: str, value: bool | float | FactReference) -> str:
        if self.engine in observation_queries.QUERY_ENGINES:
            if self.kind != "boolean" or op != "=" or type(value) is not bool:
                raise ValueError("本国聚合查询只接受布尔等值条件")
            statement = observation_queries.render(
                observation_queries.from_reader(self.engine, dict(self.parameters))
            )
            return statement if value else f"NOT = {{ {statement} }}"
        if self.parameters and self.kind == "boolean":
            body = " ".join(f"{key} = {literal}" for key, literal in self.parameters)
            statement = f"{self.engine} = {{ {body} }}"
            return statement if value is True else f"NOT = {{ {statement} }}"
        if self.argument is not None:
            statement = f"{self.engine} = {self.argument}"
            return statement if value is True else f"NOT = {{ {statement} }}"
        literal = (
            f'"{value.expression}"'
            if isinstance(value, FactReference)
            else ("yes" if value else "no")
            if type(value) is bool
            else repr(value)
        )
        if self.value_field is not None:
            parameters = "".join(f"{key} = {item} " for key, item in self.parameters)
            return f"{self.engine} = {{ {parameters}{self.value_field} {op} {literal} }}"
        return f"{self.engine} {op} {literal}"


@dataclass(frozen=True, slots=True)
class FactReference:
    key: str
    expression: str


@dataclass(frozen=True, slots=True)
class Predicate:
    fact: str
    op: str
    value: bool | float | FactReference


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    domain: str
    field: tuple[str, ...]
    priority: int
    value: float
    conditions: tuple[Predicate, ...]
    why: str
    counterexample: str
    operation: str = "multiply"
    contexts: tuple[str, ...] = ()
    intent: str | None = None
    # Explicit benefit-tier inputs only; every other predicate remains core.
    auxiliary_facts: tuple[str, ...] = ()
    required_known_facts: tuple[str, ...] = ()
    contribution_group: str = ""

    def input_keys(self) -> frozenset[str]:
        return frozenset(
            set(self.required_known_facts)
            | {condition.fact for condition in self.conditions}
            | {
                condition.value.key
                for condition in self.conditions
                if isinstance(condition.value, FactReference)
            }
        )


@dataclass(frozen=True, slots=True)
class RuleSet:
    readers: tuple[Reader, ...]
    rules: tuple[Rule, ...]
    baseline_sha256: str
    source_sha256: str
    enabled_domains: frozenset[str]
    actor_path: tuple[str, ...] = ()
    strategy: decision_intents.Strategy | None = None
    semantic_ir: tuple[ActionIR, ...] = ()
    consumer_programs: tuple[ConsumerProgram, ...] = ()
    native_root: str = "country"

    def groups(
        self, enabled_domains: frozenset[str] | None = None
    ) -> dict[tuple[str, ...], list[Rule]]:
        groups: dict[tuple[str, ...], list[Rule]] = defaultdict(list)
        selected = self.enabled_domains if enabled_domains is None else enabled_domains
        if selected - {rule.domain for rule in self.rules}:
            raise ValueError("领域开关含未登记的名称")
        from .situated.ir import from_rule  # noqa: PLC0415

        semantic_rules = self.semantic_ir or tuple(
            from_rule(rule, source="rule_set") for rule in self.rules
        )
        for item in semantic_rules:
            rule = item.to_rule()
            if rule.domain in selected:
                groups[rule.field].append(rule)
        return {
            key: sorted(value, key=lambda rule: -rule.priority)
            for key, value in sorted(groups.items())
        }


def load(source: Path = SOURCE, *, strategy: decision_intents.Strategy | None = None) -> RuleSet:
    """严格解析版本锁定的规则；不接受自由脚本、隐式数值或重复优先级。"""
    raw = source.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    if source == SOURCE and strategy is None:
        strategy = decision_intents.load()
    return from_data(data, source_sha256=hashlib.sha256(raw).hexdigest(), strategy=strategy)


def from_data(
    data: dict, *, source_sha256: str, strategy: decision_intents.Strategy | None = None
) -> RuleSet:
    """解析共享规则结构；多文件适配器也使用同一验证和代码生成契约。"""
    if (
        set(data) - {"actor_path", "contexts", "native_root"}
        != {"schema", "baseline_sha256", "readers", "rules", "domains"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or not isinstance(data["readers"], dict)
        or not isinstance(data["rules"], list)
        or not isinstance(data["domains"], dict)
    ):
        raise ValueError("全域规则 schema 无效")
    if not isinstance(data["baseline_sha256"], str) or not re.fullmatch(
        r"[a-f0-9]{64}", data["baseline_sha256"]
    ):
        raise ValueError("全域规则必须锁定底本 SHA-256")
    actor_path = data.get("actor_path", [])
    if actor_path not in ([], ["owner"]):
        raise ValueError("AI 边界只支持国家根或有原版依据的所有者")
    native_root = data.get("native_root", "state" if actor_path else "country")
    if not isinstance(native_root, str) or (native_root, tuple(actor_path)) not in {
        ("country", ()),
        ("state", ("owner",)),
        ("military_formation", ("owner",)),
    }:
        raise ValueError("原生ROOT类型与AI所有者路径不一致")
    readers: dict[str, Reader] = {}
    for key, item in data["readers"].items():
        if (
            not isinstance(item, dict)
            or set(item)
            - {
                "engine",
                "scope",
                "unit",
                "kind",
                "argument",
                "minimum",
                "maximum",
                "path",
                "value_field",
                "parameters",
            }
            or not {"engine", "scope", "unit", "kind"} <= item.keys()
        ):
            raise ValueError("读取器字段无效")
        if (
            not _NAME.fullmatch(key)
            or key in readers
            or not isinstance(item["engine"], str)
            or (not _NAME.fullmatch(item["engine"]) and item["engine"] != "relations:root")
        ):
            raise ValueError("读取器名称无效")
        if (
            not isinstance(item["scope"], str)
            or item["scope"] not in _SCOPES
            or not isinstance(item["kind"], str)
            or item["kind"] not in {"boolean", "number"}
            or not isinstance(item["unit"], str)
            or not item["unit"]
        ):
            raise ValueError("读取器作用域、单位或类型无效")
        argument = item.get("argument")
        parameters = item.get("parameters", {})
        if not isinstance(parameters, dict):
            label = "复合布尔" if item["kind"] == "boolean" else "复合数值"
            raise ValueError(f"{label}读取器参数必须是映射")
        parameter_keys = {
            ("is_production_method_active", "boolean", None): {
                "building_type",
                "production_method",
            },
            ("pop_type_percent_country", "number", "percent"): {"pop_type"},
            ("radical_fraction", "number", "value"): {"pop_type"},
            ("loyalist_fraction", "number", "value"): {"pop_type"},
            ("has_diplomatic_pact", "boolean", None): {"who", "type"},
            ("has_treaty_alliance_with", "boolean", None): {"TARGET"},
            ("primary_cultures_percent_state", "number", "value"): {"target_country"},
            ("institution_investment_level", "number", "value"): {"institution"},
        }
        value_field = item.get("value_field")
        parameter_shape = (
            item["engine"],
            item["kind"],
            value_field if isinstance(value_field, str) else None,
        )
        local_query = item["engine"] in observation_queries.QUERY_ENGINES
        if local_query:
            if (
                item["kind"] != "boolean"
                or argument is not None
                or value_field is not None
                or item["scope"] != "root"
                or item.get("path")
                or item.get("minimum") is not None
                or item.get("maximum") is not None
                or item["unit"] != "boolean"
                or actor_path
            ):
                raise ValueError("本国聚合查询必须保持精确国家ROOT布尔签名")
            observation_queries.from_reader(item["engine"], parameters)
        if (
            parameters
            and not local_query
            and (
                argument is not None
                or set(parameters) != parameter_keys.get(parameter_shape)
                or any(
                    not isinstance(literal, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", literal)
                    for literal in parameters.values()
                )
            )
        ):
            label = "复合布尔" if item["kind"] == "boolean" else "复合数值"
            raise ValueError(f"{label}读取器只支持已登记的生产方式或人口类别参数")
        if value_field is not None and (
            not isinstance(value_field, str)
            or (item["engine"], item["kind"], value_field) not in parameter_keys
            or item["kind"] != "number"
            or argument is not None
        ):
            raise ValueError("复合数值读取器只支持已声明的 value 比较，不能混用布尔参数")
        if item["engine"] == "pop_type_percent_country" and (
            value_field != "percent" or not parameters
        ):
            raise ValueError("人口比例读取器必须声明 percent 和 pop_type 参数")
        if item["engine"] == "is_production_method_active" and not parameters:
            raise ValueError("复合布尔生产方式读取器必须声明完整参数")
        if item["engine"] == "institution_investment_level" and (
            value_field != "value" or not parameters
        ):
            raise ValueError("制度投资读取器必须声明 institution 参数及 value 比较")
        if item["engine"] == "has_diplomatic_pact" and (
            parameters.get("who") != "root"
            or parameters.get("type") not in {"embargo", "rivalry"}
            or item["scope"] not in {"target_country", "overlord"}
        ):
            raise ValueError("外交条约读取器必须使用目标国/宗主与当前国家的已登记条约")
        if item["engine"] == "has_treaty_alliance_with" and (
            parameters != {"TARGET": "root"} or item["scope"] not in {"target_country", "overlord"}
        ):
            raise ValueError("外交同盟读取器必须使用原版条约触发器及目标国/宗主与当前国家")
        if item["engine"] == "primary_cultures_percent_state" and (
            parameters != {"target_country": "root"} or value_field != "value"
        ):
            raise ValueError("州文化比例必须明确相对于当前国家")
        if item["engine"] in {"is_homeland_of_country_cultures", "owner"} and argument != "root":
            raise ValueError("州身份与所有者比较必须明确相对于当前国家")
        if item["engine"] in {"has_truce_with", "relations:root"} and (
            (
                item["scope"] not in {"target_country", "overlord"}
                and not (
                    key == "actual_overlord_relations"
                    and item["scope"] == "root"
                    and item.get("path") == ["overlord"]
                    and item["engine"] == "relations:root"
                    and item.get("minimum") == -100
                    and item.get("maximum") == 100
                    and not parameters
                    and value_field is None
                )
            )
            or (item["engine"] == "has_truce_with" and argument != "root")
            or (item["engine"] == "relations:root" and argument is not None)
        ):
            raise ValueError("双边关系读取器必须使用目标国/宗主与当前国家的已审计接口")
        bounds = [item[key] for key in ("minimum", "maximum") if key in item]
        if bounds and (
            item["kind"] != "number"
            or not all(_finite(value) for value in bounds)
            or item.get("minimum", -math.inf) > item.get("maximum", math.inf)
        ):
            raise ValueError("读取器范围必须是有序的有限数值")
        if argument is not None and (
            item["kind"] != "boolean"
            or not isinstance(argument, str)
            or not re.fullmatch(r"[a-z][a-z0-9_:]*", argument)
        ):
            raise ValueError("读取器参数无效")
        path = item.get("path", [])
        if (
            not isinstance(path, list)
            or len(path) > 3
            or any(
                not isinstance(part, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*)?", part)
                for part in path
            )
        ):
            raise ValueError("读取器路径必须是有界的具名作用域链")
        readers[key] = Reader(
            key=key,
            **{
                **item,
                "path": tuple(path),
                "parameters": tuple(sorted(parameters.items())),
            },
        )
    contexts = data.get("contexts", {})
    if not isinstance(contexts, dict) or any(
        not isinstance(name, str)
        or not _NAME.fullmatch(name)
        or not isinstance(conditions, list)
        or not conditions
        for name, conditions in contexts.items()
    ):
        raise ValueError("共享约束必须是具名非空条件列表")
    used_contexts: set[str] = set()
    rules: list[Rule] = []
    seen: set[str] = set()
    priorities: set[tuple[tuple[str, ...], int]] = set()
    for item in data["rules"]:
        if not isinstance(item, dict) or set(item) - {
            "operation",
            "contexts",
            "intent",
            "auxiliary_facts",
            "required_known_facts",
            "contribution_group",
        } != {
            "id",
            "domain",
            "field",
            "priority",
            "value",
            "conditions",
            "why",
            "counterexample",
        }:
            raise ValueError("规则字段缺失或多余")
        if not all(
            isinstance(item[key], str)
            and item[key].strip()
            and not any(character in item[key] for character in "\r\n")
            for key in ("id", "domain", "field", "why", "counterexample")
        ):
            raise ValueError("规则身份和依据不能为空")
        if (
            not _NAME.fullmatch(item["id"])
            or not _NAME.fullmatch(item["domain"])
            or item["id"] in seen
        ):
            raise ValueError("规则身份无效或重复")
        field = tuple(item["field"].split("."))
        if not field or any(not re.fullmatch(r"[a-z][a-z0-9_-]*", part) for part in field):
            raise ValueError("消费者字段路径无效")
        priority = item["priority"]
        if type(priority) is not int or (field, priority) in priorities:
            raise ValueError("同一消费者优先级必须唯一且为整数")
        operation = item.get("operation", "multiply")
        if "contribution_group" in item and (
            not isinstance(item["contribution_group"], str)
            or not _NAME.fullmatch(item["contribution_group"])
        ):
            raise ValueError("因果贡献组必须是明确的小写标识符")
        if operation not in ("multiply", "add") or not _finite(item["value"]):
            raise ValueError("规则必须为有限的倍率或增量")
        lower, upper = (0.5, 1.5) if operation == "multiply" else (-50, 50)
        if not lower <= item["value"] <= upper:
            raise ValueError("规则数值超过保守范围")
        names = item.get("contexts", [])
        if (
            not isinstance(names, list)
            or any(not isinstance(name, str) or name not in contexts for name in names)
            or len(set(names)) != len(names)
        ):
            raise ValueError("规则引用了未知或重复的共享约束")
        used_contexts.update(names)
        if not isinstance(item["conditions"], list):
            raise ValueError("规则条件必须是列表")
        intent = item.get("intent")
        if "intent" in item and (
            not isinstance(intent, str) or not _NAME.fullmatch(intent) or strategy is None
        ):
            raise ValueError("规则战略意图必须有显式共享定义")
        intent_conditions = strategy.expand(intent) if strategy is not None and intent else []
        expanded = (
            intent_conditions
            + [condition for name in names for condition in contexts[name]]
            + item["conditions"]
        )
        if not expanded:
            raise ValueError("规则不能无条件干预")
        predicates: list[Predicate] = []
        for condition in expanded:
            if (
                not isinstance(condition, dict)
                or set(condition) != {"fact", "op", "value"}
                or not isinstance(condition["fact"], str)
                or condition["fact"] not in readers
                or not isinstance(condition["op"], str)
                or condition["op"] not in _OPS
            ):
                raise ValueError("规则条件缺少读取器或比较操作无效")
            reader = readers[condition["fact"]]
            value = condition["value"]
            if isinstance(value, dict):
                if (
                    set(value) != {"fact"}
                    or not isinstance(value["fact"], str)
                    or value["fact"] not in readers
                    or value["fact"] == reader.key
                ):
                    raise ValueError("相对比较必须引用另一个已登记的数值事实")
                other = readers[value["fact"]]
                if reader.kind != "number" or other.kind != "number" or reader.unit != other.unit:
                    raise ValueError("相对比较的事实必须是相同单位的数值")
                predicate = Predicate(
                    condition["fact"], condition["op"], FactReference(other.key, other.reference())
                )
            else:
                if not reader.accepts(value) or (
                    reader.kind == "boolean" and condition["op"] != "="
                ):
                    raise ValueError("条件类型不匹配；布尔值只能等值比较")
                predicate = Predicate(**condition)
            if predicate not in predicates:
                predicates.append(predicate)
        required_known = item.get("required_known_facts", [])
        if (
            not isinstance(required_known, list)
            or ("required_known_facts" in item and not required_known)
            or any(
                not isinstance(key, str)
                or key not in readers
                or readers[key].engine.startswith("sitai_context_")
                or readers[key].engine == "has_variable"
                for key in required_known
            )
            or len(set(required_known)) != len(required_known)
        ):
            raise ValueError("核心知识声明必须是非空、唯一的实际读取器；不接受派生上下文或变量")
        auxiliary = item.get("auxiliary_facts", [])
        inputs = {p.fact for p in predicates} | {
            p.value.key for p in predicates if isinstance(p.value, FactReference)
        }
        hard_inputs = {c["fact"] for c in expanded[: len(expanded) - len(item["conditions"])]}
        hard_inputs.update(
            c["value"]["fact"]
            for c in expanded[: len(expanded) - len(item["conditions"])]
            if isinstance(c["value"], dict)
        )
        if (
            not isinstance(auxiliary, list)
            or any(not isinstance(key, str) or key not in inputs for key in auxiliary)
            or len(set(auxiliary)) != len(auxiliary)
            or set(auxiliary) & set(required_known)
            or (auxiliary and (set(auxiliary) == inputs or set(auxiliary) & hard_inputs))
            or (auxiliary and (item["value"] <= (1 if operation == "multiply" else 0)))
            or any(
                readers[key].engine
                in {
                    "in_default",
                    "taking_loans",
                    "is_production_method_active",
                    "owner",
                    "has_technology_researched",
                    "has_law_or_variant",
                    "can_enact_law",
                    "is_ai",
                }
                for key in auxiliary
                if isinstance(key, str) and key in readers
            )
        ):
            raise ValueError("辅助事实必须是收益升档的已用输入真子集，不能包含共享条件或硬资格")
        for predicate in predicates:
            dependencies = {predicate.fact} | (
                {predicate.value.key} if isinstance(predicate.value, FactReference) else set()
            )
            if dependencies & set(auxiliary) and not dependencies <= set(auxiliary):
                raise ValueError("辅助相对比较必须声明完整的事实依赖，不能混用核心和辅助输入")
        rules.append(
            Rule(
                **{
                    **item,
                    "field": field,
                    "conditions": tuple(predicates),
                    "value": float(item["value"]),
                    "contexts": tuple(names),
                    "auxiliary_facts": tuple(auxiliary),
                    "required_known_facts": tuple(required_known),
                }
            )
        )
        seen.add(item["id"])
        priorities.add((field, priority))
    used = {condition.fact for rule in rules for condition in rule.conditions}
    used.update(key for rule in rules for key in rule.required_known_facts)
    used.update(
        condition.value.key
        for rule in rules
        for condition in rule.conditions
        if isinstance(condition.value, FactReference)
    )
    if used_contexts != contexts.keys():
        raise ValueError("共享约束必须有实际消费者")
    if set(readers) != used or not rules:
        raise ValueError("规则和读取器必须有真实消费者，不保留未使用读取器")
    domains = {rule.domain for rule in rules}
    if set(data["domains"]) != domains or any(
        type(value) is not bool for value in data["domains"].values()
    ):
        raise ValueError("每个领域必须有明确布尔开关，不能缺失或多余")
    fields = sorted({rule.field for rule in rules})
    for parent, child in pairwise(fields):
        if child[: len(parent)] == parent:
            raise ValueError("消费者父子字段不能分别写入：" + ".".join(child))
    policy = RuleSet(
        tuple(readers[key] for key in sorted(readers)),
        tuple(sorted(rules, key=lambda rule: rule.id)),
        data["baseline_sha256"],
        source_sha256,
        frozenset(key for key, enabled in data["domains"].items() if enabled),
        tuple(actor_path),
        strategy if any(rule.intent is not None for rule in rules) else None,
        native_root=native_root,
    )
    decision_interfaces.validate(policy)
    for candidates in policy.groups(frozenset(domains)).values():
        if (
            len(candidates) > STATIC_BUDGET["candidates_per_field"]
            or sum(len(rule.conditions) + len(rule.required_known_facts) for rule in candidates)
            > STATIC_BUDGET["predicates_per_field"]
            or any(
                len(rule.conditions) + len(rule.required_known_facts)
                > STATIC_BUDGET["predicates_per_rule"]
                for rule in candidates
            )
        ):
            raise ValueError("规则超过静态复杂度预算；先复核语义和性能再调整预算")
    return policy


def evaluate(
    rules: RuleSet,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    enabled_domains: frozenset[str] | None = None,
) -> dict[str, tuple[str, float]]:
    """Compatibility adapter: lower the public RuleSet once before evaluation."""
    from .situated.ir import from_rule  # noqa: PLC0415

    semantic_ir = rules.semantic_ir or tuple(
        from_rule(rule, source="rule_set") for rule in rules.rules
    )
    return evaluate_ir(
        replace(rules, semantic_ir=semantic_ir),
        values,
        is_ai=is_ai,
        enabled_domains=enabled_domains,
    )


def evaluate_ir(
    rules: RuleSet,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    enabled_domains: frozenset[str] | None = None,
) -> dict[str, tuple[str, float]]:
    """输出字段的规则 ID/倍率；缺失、None、类型错或非有限输入回退原版。

    已启用的消费者程序联合评估正负方向，未知只跳过当前变体。
    原始兼容 RuleSet 仍按优先级短路，辅助升档缺证只尝试下一档。
    两种模式都不会把运行时未知值解释成假或健康。
    """
    if rules.rules and not rules.semantic_ir:
        raise ValueError("参考求值缺少完整 semantic IR")
    result: dict[str, tuple[str, float]] = {}
    if type(is_ai) is not bool:
        raise ValueError("玩家边界必须是明确布尔值")
    if not is_ai:
        return result
    if rules.consumer_programs:
        from .situated import programs  # noqa: PLC0415

        selected = rules.enabled_domains if enabled_domains is None else enabled_domains
        if selected - {rule.domain for rule in rules.rules}:
            raise ValueError("领域开关含未登记的名称")
        return programs.evaluate(rules, values, selected)
    readers = {reader.key: reader for reader in rules.readers}
    for field, candidates in rules.groups(enabled_domains).items():
        for rule in candidates:
            inputs = []
            for condition in rule.conditions:
                value = values.get(condition.fact)
                reference = condition.value
                right = (
                    values.get(reference.key) if isinstance(reference, FactReference) else reference
                )
                valid = readers[condition.fact].accepts(value) and (
                    not isinstance(reference, FactReference)
                    or readers[reference.key].accepts(right)
                )
                inputs.append((condition, value, right, valid))
            # 已知的假条件足以排除本候选，其他未知输入不影响下一候选。
            if any(
                valid
                and isinstance(value, (bool, int, float))
                and isinstance(right, (bool, int, float))
                and not _OPS[p.op](value, right)
                for p, value, right, valid in inputs
            ):
                continue
            if any(not readers[key].accepts(values.get(key)) for key in rule.required_known_facts):
                break
            if any(
                not valid and p.fact not in rule.auxiliary_facts
                for p, _value, _right, valid in inputs
            ):
                break
            if any(not valid for _p, _value, _right, valid in inputs):
                continue
            result[".".join(field)] = (rule.id, rule.value)
            break
    return result


def _block_at(root: Block, field: tuple[str, ...]) -> Block:
    block = root
    for part in field:
        matches = block.all(part)
        if len(matches) != 1 or not isinstance(matches[0].value, Block):
            raise ValueError(f"消费者必须为唯一原版脚本值块：{'.'.join(field)}")
        block = matches[0].value
    if not any(
        block.first(key) is not None
        for key in ("value", "add", "subtract", "multiply", "divide", "min", "max")
    ):
        raise ValueError(f"消费者不是已登记的数值块：{'.'.join(field)}")
    return block


def _offsets(text: str, fields: set[tuple[str, ...]]) -> dict[tuple[str, ...], int]:
    """使用词法路径定位闭括号，支持嵌套块、同行块、字符串和注释。"""
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    found: dict[tuple[str, ...], int] = {}
    stack: list[str] = []
    previous = None
    before_previous = None
    for token in tokenize(text):
        if token.kind == LBRACE:
            key = (
                before_previous.value
                if previous is not None
                and previous.kind == OP
                and before_previous is not None
                and before_previous.kind == ATOM
                else "<anonymous>"
            )
            stack.append(key)
        elif token.kind == RBRACE:
            path = tuple(stack)
            if path in fields:
                if path in found:
                    raise ValueError("消费者路径重复")
                found[path] = starts[token.line - 1] + token.col - 1
            stack.pop()
        before_previous, previous = previous, token
    if found.keys() != fields:
        raise ValueError("消费者闭括号定位不完整")
    return found


def _protected_offsets(
    text: str, fields: set[tuple[str, ...]], root: Block, prefix: tuple[str, ...]
) -> dict[tuple[str, ...], int]:
    """按词法地址定位已审计的安全边界，保留原版后置资格和数值范围。

    地址包含同名块的序号，不能把 subject_value 的四个 if 混为一处。
    这里只安排插入位置；原版字节及执行顺序都保留。
    """
    if not fields:
        return {}
    targets: dict[tuple[tuple[str, int], ...], tuple[tuple[str, ...], str]] = {}
    for field in fields:
        block = _block_at(root, field)
        mode = decision_interfaces.placement_contract(field)
        address = tuple((part, 0) for part in (*prefix, *field))
        if mode == "inside_regular_reachable_subject_branch_before_native_tail":
            branch = block.first("if")
            if branch is None or not isinstance(branch.value, Block):
                raise ValueError("属国消费者缺少原版常规可达性保护块")
            limit = branch.value.first("limit")
            # 除源 SHA 外逐字核对门的词法形状，禁止误选另一个 if。
            expected = "OR = { scope:target_country = { is_subject_of = root } can_reach_target_country = { TARGET_COUNTRY = scope:target_country } }"
            if limit is None or not isinstance(limit.value, Block):
                raise ValueError("属国消费者可达性保护形状漂移")

            def signature(node: Block) -> tuple:
                return tuple(
                    (
                        item.key,
                        item.op,
                        signature(item.value)
                        if isinstance(item.value, Block)
                        else getattr(item.value, "text", None),
                    )
                    for item in node.assignments()
                )

            if signature(limit.value) != signature(parse_text(expected).root):
                raise ValueError("属国消费者可达性保护形状漂移")
            targets[(*address, ("if", 0))] = (field, "end")
        elif mode == "before_native_market_reachability_and_clamp_tail":
            branches = block.all("if")
            if len(branches) != 5:
                raise ValueError("条约港消费者后置保护形状漂移")
            targets[(*address, ("if", 4))] = (field, "start")
        elif mode == "before_native_first_top_level_clamp_and_special_tail":
            clamp = next((item for item in block.assignments() if item.key in {"min", "max"}), None)
            if clamp is None:
                raise ValueError("消费者缺少已审计的原版截断边界")
            targets[(*address, (clamp.key, 0))] = (field, "start")
        elif mode == "before_native_terminal_zero_and_clamp_tail":
            statements = list(block.assignments())
            clamp_index = next(
                (index for index, item in enumerate(statements) if item.key in {"min", "max"}),
                0,
            )
            gate = statements[clamp_index - 1] if clamp_index else None
            if gate is None or gate.key != "if" or not isinstance(gate.value, Block):
                raise ValueError("战争目标缺少原版终结归零保护")
            zero = gate.value.first("multiply")
            if (
                zero is None
                or not isinstance(zero.value, Scalar)
                or zero.value.text not in {"0", "0.0"}
            ):
                raise ValueError("战争目标终结归零保护形状漂移")
            ordinal = sum(item.key == "if" for item in statements[:clamp_index]) - 1
            targets[(*address, ("if", ordinal))] = (field, "start")
        elif mode == "before_native_aggression_terminal_zero_tail":
            branches = block.all("if")
            aggression_ordinal = next(
                (
                    index
                    for index, branch in enumerate(branches)
                    if isinstance(branch.value, Block)
                    and any(
                        item.key == "multiply"
                        and isinstance(item.value, Scalar)
                        and item.value.text in {"0", "0.0"}
                        for item in branch.value.assignments()
                    )
                ),
                None,
            )
            if aggression_ordinal is None:
                raise ValueError("攻击倾向消费者缺少原版终结归零保护")
            targets[(*address, ("if", aggression_ordinal))] = (field, "start")
        else:
            raise ValueError("未登记的消费者插入保护")
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    stack: list[tuple[str, int]] = []
    counts: list[dict[str, int]] = [{}]
    pending: tuple[str, int] | None = None
    previous = None
    result = {}
    for token in tokenize(text):
        offset = starts[token.line - 1] + token.col - 1
        if token.kind == OP and previous is not None and previous.kind == ATOM:
            key = previous.value
            index = counts[-1].get(key, 0)
            counts[-1][key] = index + 1
            pending = (key, index)
            if (target := targets.get((*stack, pending))) is not None and target[1] == "start":
                result[target[0]] = starts[previous.line - 1] + previous.col - 1
        elif token.kind == LBRACE:
            stack.append(
                pending
                if previous is not None and previous.kind == OP and pending
                else ("<anonymous>", 0)
            )
            counts.append({})
            pending = None
        elif token.kind == RBRACE:
            if (target := targets.get(tuple(stack))) is not None and target[1] == "end":
                result[target[0]] = offset
            stack.pop()
            counts.pop()
            pending = None
        previous = token
    if result.keys() != fields:
        raise ValueError("原版保护边界定位不完整")
    return result


def insertion_offsets(
    text: str, fields: set[tuple[str, ...]], root: Block, prefix: tuple[str, ...] = ()
) -> dict[tuple[str, ...], int]:
    """复用字段级原版尾部合同，返回相对 ``root`` 的安全写入位置。"""

    protected = {
        field
        for field in fields
        if decision_interfaces.placement_contract(field) != "after_native_numeric_evaluation"
    }
    plain = fields - protected
    offsets = _offsets(text, {(*prefix, *field) for field in plain}) if plain else {}
    result = {field: offsets[(*prefix, *field)] for field in plain}
    result.update(_protected_offsets(text, protected, root, prefix))
    return result


def _scoped_conditions(conditions: Mapping[tuple[str, tuple[str, ...]], list[str]]) -> str:
    """共享同一条件组的作用域前缀；不跨候选缓存或改变未知值语义。"""
    # 每个节点存放本层条件及子作用域；避免同一 owner/market 被反复进入。
    roots: dict[str, dict] = {}
    for (scope, path), expressions in sorted(conditions.items()):
        name = "ROOT" if scope == "root" else f"scope:{scope}"
        node = roots.setdefault(name, {"expressions": [], "children": {}})
        for part in path:
            node = node["children"].setdefault(part, {"expressions": [], "children": {}})
        node["expressions"].extend(expressions)

    def render(name: str, node: dict) -> str:
        parts = list(dict.fromkeys(node["expressions"]))
        parts.extend(render(part, child) for part, child in node["children"].items())
        return f"exists = {name} {name} = {{ {' '.join(parts)} }}"

    scopes = []
    for name, node in roots.items():
        scopes.append(render(name, node))
    return " ".join(scopes)


def _reader_bounds(reader: Reader) -> list[str]:
    return [
        reader.expression(op, bound)
        for op, bound in ((">=", reader.minimum), ("<=", reader.maximum))
        if bound is not None
    ]


def patch(
    text: str,
    rules: RuleSet,
    *,
    baseline: str,
    enabled_domains: frozenset[str] | None = None,
    default_strategy: bool = True,
    reader_evidence: str = "",
    reader_words: frozenset[str] | None = None,
    country_policy: CountryPolicy | None = None,
    owned_triggers: frozenset[str] | set[str] | None = None,
    consumer_ir: ConsumerIRBundle | None = None,
    consumer_source: str | None = None,
) -> str:
    """向锁定底本的派生产物插入规则；关闭时逐字等价，不覆盖资格或值。"""
    if hashlib.sha256(normalized_text(baseline).encode()).hexdigest() != rules.baseline_sha256:
        raise ValueError("全域规则底本漂移，拒绝生成")
    parsed = parse_text(text)
    if parsed.errors or (default_strategy and parsed.top_keys != ["ai_strategy_default"]):
        raise ValueError("全域规则只接收可解析的锁定消费者")
    root = parsed.top_assignments[0].value if default_strategy else parsed.root
    if not isinstance(root, Block):
        raise ValueError("默认策略不是块")
    decision_interfaces.validate(rules)
    if consumer_ir is not None:
        from .situated.decision_ir import lower_legacy  # noqa: PLC0415

        rules = lower_legacy(
            rules, consumer_ir, source=str(consumer_source) if consumer_source is not None else None
        )
    groups = rules.groups(enabled_domains)
    bundle_writers: dict[tuple[str, str], WriterDecisionIR] = {}
    if consumer_ir is not None:
        raw_writers = getattr(consumer_ir, "writers", None)
        if raw_writers is None or consumer_source is None:
            raise ValueError("consumer_ir 接线必须同时提供 writers 和 consumer_source")
        bundle_writers = {
            (str(item.source), str(item.definition)): item
            for item in raw_writers
            if getattr(item, "kind", None) == "rule_action"
        }
        if not bundle_writers:
            raise ValueError(f"consumer_ir 没有来源 {consumer_source!r} 的 legacy writer")
        expected_source = str(consumer_source)
        if not any(source == expected_source for source, _ in bundle_writers):
            raise ValueError(f"consumer_ir 缺少来源 writer：{expected_source}")
        for field_rules in groups.values():
            for rule in field_rules:
                writer = bundle_writers.get((expected_source, rule.id))
                if writer is None:
                    raise ValueError(f"consumer_ir 缺少生产 writer：{expected_source}:{rule.id}")
                if (
                    getattr(writer, "field", None) != ".".join(rule.field)
                    or getattr(writer, "operation", None) != rule.operation
                    or not getattr(writer, "owner", None)
                ):
                    raise ValueError(
                        f"consumer_ir writer 与规则不一致：{expected_source}:{rule.id}"
                    )
    selected_reader_keys = {
        key for candidates in groups.values() for rule in candidates for key in rule.input_keys()
    }

    route_readers = {
        reader.key: reader
        for reader in rules.readers
        if reader.engine == "has_variable"
        and (reader.argument or "").startswith("sitai_route_")
        and reader.key in selected_reader_keys
    }
    coordination_readers = {
        reader.key: reader
        for reader in rules.readers
        if reader.engine.startswith("sitai_context_") and reader.key in selected_reader_keys
    }
    if route_readers:
        raise ValueError("持久 route 读取器已经退役，不能重建全国排他路线")
    if coordination_readers:
        if country_policy is None:
            raise ValueError("协调读取器必须显式提供 country_policy")
        country_state = _country_state_module()
        actual_triggers = set(country_state.owned_triggers(country_policy))
        supplied_triggers = actual_triggers if owned_triggers is None else set(owned_triggers)
        if (
            not supplied_triggers <= actual_triggers
            or not {reader.engine for reader in coordination_readers.values()} <= supplied_triggers
        ):
            raise ValueError("协调读取器不在 country_policy 所有权内")
    for field in groups:
        _block_at(root, field)
    prefix = ("ai_strategy_default",) if default_strategy else ()
    positions = {
        (*prefix, *field): position
        for field, position in insertion_offsets(text, set(groups), root, prefix).items()
    }
    readers = {reader.key: reader for reader in rules.readers}
    # 原版文本用例或逐字节锁定的引擎/脚本证据；两者均只是静态依据。
    words = (
        reader_words
        if reader_words is not None
        else frozenset(
            token.value for token in tokenize(baseline + reader_evidence) if token.kind == ATOM
        )
    )
    used_reader_keys = {
        key for candidates in groups.values() for rule in candidates for key in rule.input_keys()
    }
    if any(
        readers[key].engine
        in {
            "num_defensive_pacts",
            "wanted_army_size_script_value",
            "wanted_marines_size_script_value",
        }
        for key in used_reader_keys
    ):
        words |= decision_interfaces.proven_reader_words()

    for reader in rules.readers:
        if reader.key not in used_reader_keys:
            continue
        path_proven = all(
            part in words or (part.startswith("mg:") and part[3:] in words and "mg:grain" in words)
            for part in reader.path
        )
        if reader.key in coordination_readers:
            if not path_proven:
                raise ValueError(f"协调读取器没有锁定原版路径依据：{reader.key}")
            continue
        if reader.engine in observation_queries.QUERY_ENGINES:
            # Full AST/source proof is checked by the adapter build boundary;
            # numeric query parameters are not native vocabulary atoms.
            observation_queries.from_reader(reader.engine, dict(reader.parameters))
            continue
        if (
            reader.engine not in words
            or not path_proven
            or (reader.argument is not None and reader.argument not in words)
            or any(literal not in words for _, literal in reader.parameters)
        ):
            raise ValueError(f"读取器没有锁定原版依据：{reader.key}")
    if any(part not in words for part in rules.actor_path):
        raise ValueError("AI 所有者没有锁定原版依据")

    def guard_parts(rule):
        conditions: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
        valid: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
        false_conditions = []
        core_known = []
        conditions[("root", rules.actor_path)].append("is_ai = yes")
        for predicate in rule.conditions:
            reader = readers[predicate.fact]
            key = (reader.scope, reader.path)
            if reader.engine.startswith("sitai_context_"):
                expression = (
                    "always = no"
                    if country_policy is None or not country_policy.enabled
                    else f"{reader.engine} = {'yes' if predicate.value is True else 'no'}"
                )
            else:
                expression = reader.expression(predicate.op, predicate.value)
            bounds = _reader_bounds(reader)
            if (
                reader.engine.startswith("sitai_context_")
                and country_policy is not None
                and country_policy.enabled
            ):
                bounds.append(
                    "sitai_context_known_" + reader.engine.removeprefix("sitai_context_") + " = yes"
                )
            conditions[key].extend([*bounds, expression])
            valid[key].extend(bounds)
            false_parts = {key: [*bounds, f"NOT = {{ {expression} }}"]}
            if isinstance(predicate.value, FactReference):
                other = readers[predicate.value.key]
                other_key = (other.scope, other.path)
                other_bounds = _reader_bounds(other)
                conditions[other_key].extend(other_bounds)
                valid[other_key].extend(other_bounds)
                false_parts.setdefault(other_key, []).extend(other_bounds)
            false_conditions.append("AND = { " + _scoped_conditions(false_parts) + " }")
            if predicate.fact not in rule.auxiliary_facts:
                knowledge = {key: [*bounds, f"OR = {{ {expression} NOT = {{ {expression} }} }}"]}
                if isinstance(predicate.value, FactReference):
                    knowledge.setdefault(other_key, []).extend(other_bounds)
                core_known.append("AND = { " + _scoped_conditions(knowledge) + " }")
        for known_fact_key in rule.required_known_facts:
            reader = readers[known_fact_key]
            expression = (
                reader.expression("=", True)
                if reader.kind == "boolean"
                else reader.expression(">=", 0)
            )
            knowledge_expression = f"OR = {{ {expression} NOT = {{ {expression} }} }}"
            scope_key = (reader.scope, reader.path)
            known_terms = [*_reader_bounds(reader), knowledge_expression]
            conditions[scope_key].extend(known_terms)
            valid[scope_key].extend(known_terms)
            core_known.append("AND = { " + _scoped_conditions({scope_key: known_terms}) + " }")
        return conditions, valid, false_conditions, core_known

    program_fields = {}
    if rules.consumer_programs:
        from .situated import programs  # noqa: PLC0415

        programs.validate(rules)
        program_fields = {program.field: program for program in rules.consumer_programs}
        if set(groups) - set(program_fields):
            raise ValueError("贡献程序缺少实际生产字段")
    for field in sorted(groups, key=lambda field: positions[(*prefix, *field)], reverse=True):
        chunks = [f"\n\t\t# SITAI BEGIN information:{'.'.join(field)}\n"]
        if field in program_fields:
            guards, descriptions, producer_markers = {}, {}, {}
            for rule in groups[field]:
                conditions, _valid, _false, _core = guard_parts(rule)
                guards[rule.id] = _scoped_conditions(conditions)
                if (description := description_key(rule)) is not None:
                    descriptions[rule.id] = description
                writer = bundle_writers.get((str(consumer_source), rule.id))
                if writer is not None:
                    producer_markers[rule.id] = "".join(
                        f"\t\t\t\t# SITAI CHAIN {chain_id}/{link_id} writer={writer.writer_id}\n"
                        for chain_id, link_id in writer.chain_refs
                    )
            chunks.append(
                programs.render(
                    program_fields[field],
                    guards=guards,
                    ai_guard=_scoped_conditions({("root", rules.actor_path): ["is_ai = yes"]}),
                    descriptions=descriptions,
                    producer_markers=producer_markers,
                )
            )
            chunks.append(f"\t\t# SITAI END information:{'.'.join(field)}\n\t")
            position = positions[(*prefix, *field)]
            text = text[:position] + "".join(chunks) + text[position:]
            continue
        for index, rule in enumerate(groups[field]):
            conditions, valid, false_conditions, core_known = guard_parts(rule)
            branch = "if" if index == 0 else "else_if"
            writer = bundle_writers.get((str(consumer_source), rule.id))
            if writer is not None:
                for chain_id, link_id in writer.chain_refs:
                    chunks.append(
                        f"\t\t# SITAI CHAIN {chain_id}/{link_id} writer={writer.writer_id}\n"
                    )
            chunks.append(f"\t\t# {rule.id} [{rule.domain}]; {rule.why}\n")
            adjustment = repr(rule.value)
            if (description := description_key(rule)) is not None:
                adjustment = f"{{ value = {adjustment} desc = {description} }}"
            if rule.auxiliary_facts:
                # A write-free proof only enters a high tier when every benefit
                # predicate is proven. Unknown auxiliary evidence cannot write.
                chunks.append(
                    f"\t\t{branch} = {{ limit = {{ {_scoped_conditions(conditions)} }} "
                    f"if = {{ limit = {{ always = yes }} {rule.operation} = {adjustment} }} }}\n"
                )
            else:
                chunks.append(
                    f"\t\t{branch} = {{ limit = {{ {_scoped_conditions(conditions)} }} {rule.operation} = {adjustment} }}\n"
                )
            if index + 1 < len(groups[field]):
                # 已知假条件可继续下一候选；其余未知停止本字段干预。
                known_parts = list(false_conditions)
                valid_scope = (
                    " ".join(core_known) if rule.auxiliary_facts else _scoped_conditions(valid)
                )
                if valid_scope:
                    known_parts.append(f"AND = {{ {valid_scope} }}")
                known = " ".join(known_parts)
                chunks.append(
                    "\t\telse_if = { limit = { "
                    + _scoped_conditions({("root", rules.actor_path): ["is_ai = yes"]})
                    + f" NOT = {{ OR = {{ {known} }} }} }} multiply = 1.0 }}\n"
                )
        chunks.append(f"\t\t# SITAI END information:{'.'.join(field)}\n\t")
        position = positions[(*prefix, *field)]
        text = text[:position] + "".join(chunks) + text[position:]
    if parse_text(text).errors:
        raise ValueError("全域规则产物解析失败")
    return text


def description_key(rule: Rule) -> str | None:
    """只给原版要求说明的消费者产生稳定键；对应文案由生产本地化生成。"""
    return f"SITAI_RULE_{rule.id.upper()}_REASON" if rule.field[-1] == "state_value" else None


def contract(
    rules: RuleSet, *, owner: str = "information_rules", source: str | None = None
) -> dict[str, object]:
    """机器可读的实际生成覆盖；只列真实规则，实机全部保持待验。"""
    from .situated.programs import contract as program_contract  # noqa: PLC0415

    return {
        "schema": 1,
        "evidence": "static_vanilla_examples_and_generated_scripts",
        "behavior_verified": False,
        "runtime_state": "none",
        "refresh": "vanilla_consumer_evaluation",
        "invalidation": "no_cache_or_persistent_state",
        "lifecycle": {
            "enter_hold_exit": "recompute_from_current_inputs_at_vanilla_consumer_evaluation",
            "switching": "no_mod_owned_strategy_switch_or_periodic_hook",
            "cooldown_hysteresis_ttl": "not_applicable_no_mod_owned_persistent_state",
            "save_reload": "no_mod_state_to_serialize; re_evaluate_current_inputs",
            "disable": "regenerate_without_rules_and_restart; world_actions_are_not_reverted",
        },
        "visibility": "public_script_scopes_only",
        "actor": "root_country" if not rules.actor_path else f"root_{rules.native_root}_owner",
        "native_root": rules.native_root,
        "world_scans": 0,
        "strategy": rules.strategy.contract({rule.intent for rule in rules.rules if rule.intent})
        if rules.strategy is not None
        else None,
        "static_complexity_budget": dict(STATIC_BUDGET),
        "field_owners": {".".join(field): owner for field in rules.groups()},
        "maximum_cases_per_field": max(
            (len(items) for items in rules.groups().values()), default=0
        ),
        "merge": "signed_envelope_joint_consumer_program"
        if rules.consumer_programs
        else "first_matching_priority_adjustment_preserving_vanilla_eligibility",
        "unknown_policy": "preserve_unknown_and_fallback_vanilla",
        "baseline_sha256": rules.baseline_sha256,
        "source_sha256": rules.source_sha256,
        "enabled_domains": sorted(rules.enabled_domains),
        "active_rule_count": sum(len(values) for values in rules.groups().values()),
        "consumer_programs": (program_contract(rules) if rules.consumer_programs else None),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "interface_generator_sha256": hashlib.sha256(
            Path(decision_interfaces.__file__).read_bytes()
        ).hexdigest(),
        "readers": [
            {
                "key": reader.key,
                "engine": reader.engine,
                "scope": reader.scope,
                "unit": reader.unit,
                "kind": reader.kind,
                "argument": reader.argument,
                "minimum": reader.minimum,
                "maximum": reader.maximum,
                "path": list(reader.path),
                "value_field": reader.value_field,
                "parameters": dict(reader.parameters),
                "resolved_scope": decision_interfaces.reader_scope(
                    reader, rules.actor_path, native_root=rules.native_root
                ),
                "visibility": "public_script_scope",
                "update": "read_at_consumer_evaluation_no_cache",
                "cost": (
                    "owned_candidate_traversal_no_world_scan; engine_runtime_cost_unmeasured"
                    if reader.engine in observation_queries.QUERY_ENGINES
                    else "bounded_scope_chain_no_world_scan; engine_runtime_cost_unmeasured"
                ),
                "runtime_readability": "static_interface_signature; runtime_behavior_unverified",
            }
            for reader in rules.readers
        ],
        "rules": [
            {
                "id": rule.id,
                "domain": rule.domain,
                "field": ".".join(rule.field),
                "priority": rule.priority,
                "value": rule.value,
                "operation": rule.operation,
                "unit": "vanilla_score_points"
                if rule.operation == "add"
                else "dimensionless_multiplier",
                "calibration": "design_assumption; user_behavior_and_balance_review_pending",
                "consumer": decision_interfaces.consumer(
                    rule.field, rules.actor_path, source=source, native_root=rules.native_root
                ),
                "description_key": description_key(rule),
                "unknown": (
                    "unknown_local_variant_skipped_independent_groups_continue"
                    if rules.consumer_programs
                    else "auxiliary_unproven_try_lower_tier_core_unknown_preserve_vanilla"
                    if rule.auxiliary_facts
                    else "preserve_vanilla_and_block_lower_priority_if_not_known_false"
                ),
                **({"auxiliary_facts": list(rule.auxiliary_facts)} if rule.auxiliary_facts else {}),
                "arbitration": "variant_inside_signed_envelope_joint_consumer_program"
                if rules.consumer_programs
                else "one_complete_adjustment_not_an_increment_on_other_mod_rules",
                **(
                    {"required_known_facts": list(rule.required_known_facts)}
                    if rule.required_known_facts
                    else {}
                ),
                "inputs": sorted(
                    set(rule.required_known_facts)
                    | {condition.fact for condition in rule.conditions}
                    | {
                        condition.value.key
                        for condition in rule.conditions
                        if isinstance(condition.value, FactReference)
                    }
                ),
                "conditions": [
                    {
                        "fact": condition.fact,
                        "op": condition.op,
                        "value": {"fact": condition.value.key}
                        if isinstance(condition.value, FactReference)
                        else condition.value,
                    }
                    for condition in rule.conditions
                ],
                "contexts": list(rule.contexts),
                "intent": rule.intent,
                "why": rule.why,
                "counterexample": rule.counterexample,
            }
            for rule in rules.rules
        ],
        "cost_by_field": {
            ".".join(field): {
                "candidates": len(candidates),
                "predicates": sum(
                    len(rule.conditions) + len(rule.required_known_facts) for rule in candidates
                ),
                "scope_depth": max(
                    len(reader.path)
                    for reader in rules.readers
                    if any(reader.key in rule.input_keys() for rule in candidates)
                ),
                "engine_runtime_cost": "unmeasured; user_runtime_evidence_pending",
            }
            for field, candidates in rules.groups().items()
        },
    }
