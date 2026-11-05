"""Finite typed fact ports, consumed by existing rule/card scalar guards.

Ports contain observed predicates and pure boolean composition, never scores,
action outcomes or persistent state. Missing values remain unknown in the
reference evaluator. PDX exposes only proven true/false branches; conservative
cost fallback belongs to the common scalar program, not an unknown detector.
"""

from __future__ import annotations

import hashlib
import json
import math
import operator
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from .expressions import Truth, truth_all, truth_any, truth_not
from .relations import RuleRelationProjection, validate_execution

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pdx.decision_rules import Reader, Rule

    from .decision_ir import EvaluationContext, WriterDecisionIR
    from .schema import Relation

WriterKey = tuple[str, str]
ReaderKey = tuple[str, str]
_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
_META = {"domain", "entity", "entity_kind", "unit", "direction", "refresh", "unknown", "cost"}
_LEAF = {"reader_source", "reader_key", "reader", "op", "value"}
_OPS = {"=": operator.eq, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
_DIRECTIONS = {"need", "capacity", "opportunity", "risk", "cost", "commitment"}
_MAXIMUM_BUDGET = {"nodes": 256, "depth": 32, "expanded_leaves": 4096, "evaluation_cost": 16384}
DEFAULT_SOURCE = Path(__file__).resolve().parents[3] / "mod/decisions/domain_ports.toml"


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"端口 {label} 必须为非空文本")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def reader_signature(reader: Reader) -> dict[str, Any]:
    """Complete production reader identity; names and policy source are separate."""
    raw = asdict(reader)
    raw.pop("key")
    raw["path"] = list(reader.path)
    raw["parameters"] = [list(pair) for pair in reader.parameters]
    return {key: value for key, value in raw.items() if value is not None}


@dataclass(frozen=True, slots=True)
class Origin:
    identity: str
    reader_source: str
    reader_key: str
    signature: str
    entity: str
    entity_kind: str


@dataclass(frozen=True, slots=True)
class Port:
    id: str
    domain: str
    entity: str
    entity_kind: str
    direction: str
    unknown: str
    cost: int
    mode: str
    dependencies: tuple[str, ...] = ()
    reader_key: ReaderKey | None = None
    reader: Reader | None = None
    op: str = "="
    expected: bool | float = True


@dataclass(frozen=True, slots=True)
class PortUse:
    source: str
    definition: str
    port: str
    role: str
    selector: tuple[str, ...] = ()
    relation_cause: str = ""
    output_unit: str = ""
    dependency_domain: str = ""


@dataclass(frozen=True, slots=True)
class PortBinding:
    source: str
    definition: str
    port: str
    graph: PortGraph
    required_known: tuple[str, ...] = ()

    def evaluate(self, values: Mapping[str, object], readers: Mapping[str, Reader]) -> bool:
        self.graph.guard(self.source, self.definition, self.port)
        return self.graph.evaluate(
            self.port, {(self.source, key): value for key, value in values.items()}
        ) is True and all(readers[key].accepts(values.get(key)) for key in self.required_known)


@dataclass(frozen=True, slots=True)
class RuleRelationBinding:
    projection: RuleRelationProjection
    graph: PortGraph
    relation: Relation
    writer: WriterDecisionIR

    def validate(self, readers: Mapping[str, Reader]) -> None:
        item = self.projection
        item.validate()
        validate_execution(self.relation)
        use = next(
            (
                use
                for use in self.graph.uses
                if (use.source, use.definition, use.port, use.role)
                == (item.source, item.definition, item.port, "relation")
            ),
            None,
        )
        if (
            use is None
            or (use.relation_cause, use.output_unit, use.dependency_domain, use.selector)
            != (
                item.cause_id,
                item.output_unit,
                item.dependency_domain,
                self.relation.condition_facts,
            )
            or (
                item.cause_id,
                item.amount,
                item.origins,
                item.relation_source,
                item.relation_target,
            )
            != (
                self.relation.cause_id,
                self.relation.strength,
                self.relation.origins,
                self.relation.source,
                self.relation.target,
            )
            or (item.source, item.definition, item.writer_id, ".".join(item.field), item.operation)
            != (
                self.writer.source,
                self.writer.definition,
                self.writer.writer_id,
                self.writer.field,
                self.writer.operation,
            )
            or self.writer.kind != "rule_action"
            or self.writer.actor != "root"
            or self.writer.target != "none"
        ):
            raise ValueError("规则关系投影与原关系、端口use或唯一writer不一致")
        guard = self.graph.guard(item.source, item.definition, item.port)
        if guard.origins != item.origins or guard.unknown_policy != "vanilla":
            raise ValueError("规则关系投影原始来源或未知策略与实际端口不一致")
        for leaf in self.graph.leaves(item.port):
            if (
                leaf.reader is None
                or leaf.reader.scope != "root"
                or leaf.reader_key is None
                or leaf.reader.key not in readers
                or reader_signature(readers[leaf.reader.key]) != reader_signature(leaf.reader)
            ):
                raise ValueError("规则关系reader完整身份或ROOT实体与端口不一致")

    def evaluate(self, values: Mapping[str, object], readers: Mapping[str, Reader]) -> bool:
        self.validate(readers)
        raw = {
            leaf.reader_key: values.get(leaf.reader.key)
            for leaf in self.graph.leaves(self.projection.port)
            if leaf.reader is not None and leaf.reader_key is not None
        }
        return self.graph.evaluate(self.projection.port, raw) is True

    def guard(self, readers: Mapping[str, Reader]) -> str:
        self.validate(readers)
        item = self.projection
        return self.graph.guard(item.source, item.definition, item.port).when_true


@dataclass(frozen=True, slots=True)
class PortGuard:
    when_true: str
    when_false: str
    unknown_policy: str
    origins: tuple[str, ...]
    evaluation_cost: int


@dataclass(frozen=True, slots=True)
class PortGraph:
    ports: tuple[Port, ...]
    uses: tuple[PortUse, ...]
    topological: tuple[str, ...]
    origin_rows: tuple[tuple[str, tuple[Origin, ...]], ...]
    expansions: tuple[tuple[str, int], ...]
    costs: tuple[tuple[str, int], ...]

    def leaves(self, port_id: str) -> tuple[Port, ...]:
        by_id = {port.id: port for port in self.ports}
        node = by_id[port_id]
        if node.reader is not None:
            return (node,)
        return tuple(leaf for dependency in node.dependencies for leaf in self.leaves(dependency))

    def assert_predicates(
        self, port_id: str, predicates, readers: Mapping[str, Reader], *, mode: str = "all"
    ) -> None:
        """Only exact existing conjunction/disjunction substitutions are allowed."""
        node = next(port for port in self.ports if port.id == port_id)
        by_id = {port.id: port for port in self.ports}

        def flatten(key):
            item = by_id[key]
            if item.reader is not None:
                return [(reader_signature(item.reader), item.op, item.expected)]
            if item.mode != mode:
                raise ValueError("端口不能替换非等价生产谓词结构")
            return [entry for dep in item.dependencies for entry in flatten(dep)]

        expected = sorted(
            _canonical((reader_signature(readers[p.fact]), p.op, p.value)) for p in predicates
        )
        actual = sorted(_canonical(entry) for entry in flatten(node.id))
        if actual != expected:
            raise ValueError(f"端口与具体生产term谓词不等价: {port_id}")

    def origins(self, port_id: str) -> tuple[Origin, ...]:
        return dict(self.origin_rows)[port_id]

    def expanded_leaves(self, port_id: str) -> int:
        return dict(self.expansions)[port_id]

    def evaluate(
        self,
        port_id: str,
        values: Mapping[ReaderKey, object],
        *,
        predicate_values: Mapping[str, object] | None = None,
    ) -> Truth:
        """Accept original (source,key) values only, never caller aliases."""
        evaluated: dict[str, Truth] = {}
        by_id = {port.id: port for port in self.ports}
        for key in self.topological:
            port = by_id[key]
            if port.reader is not None and port.reader_key is not None:
                raw = values.get(port.reader_key)
                evaluated[key] = (
                    bool(_OPS[port.op](cast("float | bool", raw), port.expected))
                    if port.reader.accepts(raw)
                    else None
                )
                if port.reader_key not in values and predicate_values is not None:
                    observed = predicate_values.get(port.id)
                    if type(observed) is bool:
                        evaluated[key] = observed
            elif port.mode == "all":
                evaluated[key] = truth_all(tuple(evaluated[dep] for dep in port.dependencies))
            elif port.mode == "any":
                evaluated[key] = truth_any(tuple(evaluated[dep] for dep in port.dependencies))
            else:
                evaluated[key] = truth_not(evaluated[port.dependencies[0]])
        return evaluated[port_id]

    def guard(self, source: str, definition: str, port_id: str) -> PortGuard:
        """Lower only a declared actual writer use, retaining scoped readers."""
        if not any(
            (use.source, use.definition, use.port) == (source, definition, port_id)
            for use in self.uses
        ):
            raise ValueError(f"端口未声明 writer 使用: {source}:{definition}:{port_id}")
        rendered: dict[str, tuple[str, str]] = {}
        by_id = {port.id: port for port in self.ports}
        for key in self.topological:
            port = by_id[key]
            if port.reader is not None:
                reader = port.reader
                comparison = reader.expression(port.op, port.expected)
                bounds = [
                    reader.expression(op, bound)
                    for op, bound in ((">=", reader.minimum), ("<=", reader.maximum))
                    if bound is not None
                ]
                positive = " ".join((*bounds, comparison))
                negative = " ".join((*bounds, f"NOT = {{ {comparison} }}"))
                rendered[key] = (_scoped(reader, positive), _scoped(reader, negative))
            elif port.mode == "not":
                positive, negative = rendered[port.dependencies[0]]
                rendered[key] = negative, positive
            else:
                positive = " ".join(rendered[dep][0] for dep in port.dependencies)
                negative = " ".join(rendered[dep][1] for dep in port.dependencies)
                rendered[key] = (
                    f"{'AND' if port.mode == 'all' else 'OR'} = {{ {positive} }}",
                    f"{'OR' if port.mode == 'all' else 'AND'} = {{ {negative} }}",
                )
        positive, negative = rendered[port_id]
        return PortGuard(
            positive,
            negative,
            by_id[port_id].unknown,
            tuple(origin.identity for origin in self.origins(port_id)),
            dict(self.costs)[port_id],
        )

    def contract(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "ports": [asdict(port) for port in self.ports],
            "uses": [asdict(use) for use in self.uses],
            "topological": list(self.topological),
            "origins": {
                key: [asdict(origin) for origin in origins] for key, origins in self.origin_rows
            },
            "expanded_leaves": dict(self.expansions),
            "evaluation_cost": dict(self.costs),
            "persistent_state": False,
            "unknown_detection": False,
        }


def bind_rule_relations(
    graph: PortGraph,
    *,
    source: str,
    rules: tuple[Rule, ...],
    readers: Mapping[str, Reader],
    relations: tuple[Relation, ...],
    writers: Mapping[WriterKey, WriterDecisionIR],
) -> tuple[tuple[RuleRelationBinding, ...], tuple[Reader, ...]]:
    """Project existing world relations through declared exact rule uses."""
    selected = {rule.id: rule for rule in rules}
    actual_readers = dict(readers)
    bindings = []
    for use in graph.uses:
        if use.source != source or not use.relation_cause:
            continue
        rule = selected.get(use.definition)
        writer = writers.get((source, use.definition))
        matches = [item for item in relations if item.cause_id == use.relation_cause]
        if rule is None or writer is None or len(matches) != 1:
            raise ValueError("规则关系缺少唯一真实rule writer或已声明现实关系")
        relation = matches[0]
        validate_execution(relation)
        if (
            use.role != "relation"
            or use.output_unit != "multiplier_delta"
            or use.dependency_domain not in {item.domain for item in rules}
            or tuple(use.selector) != relation.condition_facts
            or relation.kind != "complements"
            or relation.strength <= 0
            or rule.semantic_role == "cost"
            or rule.operation != "multiply"
            or writer.kind != "rule_action"
            or writer.field != ".".join(rule.field)
            or writer.operation != rule.operation
            or writer.actor != "root"
            or writer.target != "none"
            or writer.evaluation_context is None
            or writer.evaluation_context.actor_scope is None
            or writer.evaluation_context.actor_scope.name != "root"
            or writer.evaluation_context.actor_scope.kind != "country"
        ):
            raise ValueError("规则关系投影实体、单位、来源条件或依赖领域不匹配")
        guard = graph.guard(source, use.definition, use.port)
        if guard.origins != relation.origins:
            raise ValueError("规则关系端口来源闭包与真实关系不一致")
        for leaf in graph.leaves(use.port):
            if leaf.reader is None:
                raise ValueError("规则关系端口缺少实际原始Reader")
            if leaf.reader.key in actual_readers and reader_signature(
                actual_readers[leaf.reader.key]
            ) != reader_signature(leaf.reader):
                raise ValueError("规则关系输入别名与现有Reader完整身份冲突")
            actual_readers[leaf.reader.key] = leaf.reader
        binding = RuleRelationBinding(
            RuleRelationProjection(
                source,
                use.definition,
                writer.writer_id,
                rule.field,
                rule.operation,
                use.port,
                relation.cause_id,
                relation.strength,
                relation.origins,
                use.dependency_domain,
                use.output_unit,
                relation.source,
                relation.target,
            ),
            graph,
            relation,
            writer,
        )
        binding.validate(actual_readers)
        bindings.append(binding)
    return tuple(bindings), tuple(actual_readers.values())


def _scoped(reader: Reader, condition: str) -> str:
    for name in reversed(reader.path):
        condition = f"exists = {name} {name} = {{ {condition} }}"
    anchor = "ROOT" if reader.scope == "root" else f"scope:{reader.scope}"
    return f"exists = {anchor} {anchor} = {{ {condition} }}"


def _port(key: str, row: Any, readers: Mapping[ReaderKey, Reader]) -> Port:
    if not _ID.fullmatch(key) or not isinstance(row, dict) or not row.keys() >= _META:
        raise ValueError(f"端口 ID/元数据不完整: {key}")
    for name in ("domain", "entity", "entity_kind"):
        _text(row[name], f"{key}.{name}")
    if row["unit"] != "flag" or row["direction"] not in _DIRECTIONS:
        raise ValueError(f"端口单位/方向无效: {key}")
    if row["refresh"] != "consumer" or row["unknown"] not in {
        "vanilla",
        "lower_tier",
        "conservative",
    }:
        raise ValueError(f"端口刷新/未知策略无效: {key}")
    if type(row["cost"]) is not int or row["cost"] < 1:
        raise ValueError(f"端口求值成本无效: {key}")
    modes = set(row) - _META
    kwargs: dict[str, Any] = {}
    if modes == _LEAF:
        ref = (_text(row["reader_source"], "reader_source"), _text(row["reader_key"], "reader_key"))
        reader = readers.get(ref)
        if reader is None or _canonical(row["reader"]) != _canonical(reader_signature(reader)):
            raise ValueError(f"端口 reader signature 不匹配实际生产: {key}")
        if row["entity"] != reader.scope:
            raise ValueError(f"端口实体与reader作用域不符: {key}")
        value, op = row["value"], row["op"]
        if op not in _OPS or (reader.kind == "boolean" and (op != "=" or type(value) is not bool)):
            raise ValueError(f"端口比较类型无效: {key}")
        if reader.kind != "boolean" and (
            type(value) not in (int, float) or not math.isfinite(value)
        ):
            raise ValueError(f"端口阈值单位/数值无效: {key}")
        kwargs.update(mode="leaf", reader_key=ref, reader=reader, op=op, expected=value)
    elif len(modes) == 1 and next(iter(modes)) in {"all", "any", "not"}:
        mode = next(iter(modes))
        refs = [row[mode]] if mode == "not" else row[mode]
        if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs):
            raise ValueError(f"端口依赖必须非空且唯一: {key}")
        kwargs.update(mode=mode, dependencies=tuple(_text(ref, "dependency") for ref in refs))
    else:
        raise ValueError(f"端口不允许自由表达式或额外字段: {key}")
    return Port(
        key,
        row["domain"],
        row["entity"],
        row["entity_kind"],
        row["direction"],
        row["unknown"],
        row["cost"],
        **kwargs,
    )


def from_data(
    data: Mapping[str, Any],
    *,
    readers: Mapping[ReaderKey, Reader],
    writers: Mapping[WriterKey, EvaluationContext],
) -> PortGraph:
    """Validate against actual caller-supplied policy readers and writer contexts."""
    if set(data) != {"schema", "limits", "ports", "uses"} or data["schema"] != 1:
        raise ValueError("端口源必须严格包含schema=1/limits/ports/uses")
    limits = data["limits"]
    if set(limits) != set(_MAXIMUM_BUDGET) or any(
        type(value) is not int or not 1 <= value <= _MAXIMUM_BUDGET[key]
        for key, value in limits.items()
    ):
        raise ValueError("端口预算必须为正整数")
    nodes = tuple(_port(key, row, readers) for key, row in data["ports"].items())
    if not nodes or len(nodes) > limits["nodes"]:
        raise ValueError("端口节点预算超限")
    by_id = {node.id: node for node in nodes}
    visiting: set[str] = set()
    order: list[str] = []
    origins: dict[str, tuple[Origin, ...]] = {}
    depth: dict[str, int] = {}
    expanded: dict[str, int] = {}
    costs: dict[str, int] = {}

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError(f"端口派生依赖有环: {key}")
        if key in origins:
            return
        if key not in by_id:
            raise ValueError(f"端口依赖不存在: {key}")
        if len(visiting) >= limits["depth"]:
            raise ValueError(f"端口深度预算超限: {key}")
        visiting.add(key)
        node = by_id[key]
        if node.reader is not None and node.reader_key is not None:
            signature = _canonical(reader_signature(node.reader))
            identity = hashlib.sha256(
                _canonical((signature, node.entity, node.entity_kind)).encode()
            ).hexdigest()
            origins[key] = (
                Origin(identity, *node.reader_key, signature, node.entity, node.entity_kind),
            )
            depth[key], expanded[key], costs[key] = 1, 1, node.cost
        else:
            for dep in node.dependencies:
                visit(dep)
                child = by_id[dep]
                if (child.entity, child.entity_kind) != (node.entity, node.entity_kind):
                    raise ValueError(f"端口派生实体混用: {key}/{dep}")
            unique = {
                origin.identity: origin for dep in node.dependencies for origin in origins[dep]
            }
            origins[key] = tuple(unique[name] for name in sorted(unique))
            depth[key] = 1 + max(depth[dep] for dep in node.dependencies)
            expanded[key] = sum(expanded[dep] for dep in node.dependencies)
            costs[key] = node.cost + sum(costs[dep] for dep in node.dependencies)
        if (
            depth[key] > limits["depth"]
            or expanded[key] > limits["expanded_leaves"]
            or costs[key] > limits["evaluation_cost"]
        ):
            raise ValueError(f"端口深度/展开预算超限: {key}")
        visiting.remove(key)
        order.append(key)

    for key in by_id:
        visit(key)
    uses = []
    used: set[str] = set()
    use_ids: set[tuple[str, str, str, str]] = set()
    for raw in data["uses"]:
        if (
            not isinstance(raw, dict)
            or set(raw)
            - {
                "source",
                "definition",
                "port",
                "role",
                "selector",
                "relation_cause",
                "output_unit",
                "dependency_domain",
            }
            or not set(raw) >= {"source", "definition", "port", "role"}
        ):
            raise ValueError("端口use必须绑定精确writer.source/definition/port/role")
        use = PortUse(
            **{name: _text(value, name) for name, value in raw.items() if name != "selector"},
            selector=tuple(raw.get("selector", ())),
        )
        projection_fields = (use.relation_cause, use.output_unit, use.dependency_domain)
        if any(projection_fields) and (use.role != "relation" or not all(projection_fields)):
            raise ValueError("规则关系use必须完整声明cause、输出单位和依赖领域")
        identity = (use.source, use.definition, use.port, use.role)
        if identity in use_ids:
            raise ValueError("端口writer use重复")
        use_ids.add(identity)
        context = writers.get((use.source, use.definition))
        if context is None or context.status != "observed":
            raise ValueError(f"端口缺少实际writer与可证上下文: {use.source}:{use.definition}")
        if use.port not in by_id or use.role not in _DIRECTIONS | {"relation"}:
            raise ValueError("端口use引用或角色无效")
        node = by_id[use.port]
        bindings = (context.actor_scope, *context.targets, *context.auxiliary_scopes)
        if not any(
            binding is not None and (binding.name, binding.kind) == (node.entity, node.entity_kind)
            for binding in bindings
        ):
            raise ValueError(f"端口实体与实际writer上下文不匹配: {use.port}")
        if use.role not in {node.direction, "relation"}:
            raise ValueError("端口use方向与声明角色不匹配")
        stack = [use.port]
        while stack:
            item = stack.pop()
            if item not in used:
                used.add(item)
                stack.extend(by_id[item].dependencies)
        uses.append(use)
    if unused := by_id.keys() - used:
        raise ValueError(f"存在未使用端口: {sorted(unused)}")
    return PortGraph(
        nodes,
        tuple(uses),
        tuple(order),
        tuple(origins.items()),
        tuple(expanded.items()),
        tuple(costs.items()),
    )


def load(
    path: Path = DEFAULT_SOURCE,
    *,
    readers: Mapping[ReaderKey, Reader],
    writers: Mapping[WriterKey, EvaluationContext],
) -> PortGraph:
    return from_data(
        tomllib.loads(path.read_text(encoding="utf-8")), readers=readers, writers=writers
    )
