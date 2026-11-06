"""Finite typed fact ports, consumed by existing rule/card scalar guards.

Ports contain observed predicates and pure boolean composition, never scores,
action outcomes or persistent state. Missing values remain unknown in the
reference evaluator. PDX exposes only proven true/false branches; conservative
cost fallback belongs to the common scalar program, not an unknown detector.
"""

from __future__ import annotations

import json
import math
import operator
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from .evidence import Observation
from .expressions import Truth, truth_all, truth_any, truth_not
from .relations import RuleRelationProjection, validate_execution

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pdx.decision_rules import Reader, Rule

    from .decision_ir import EvaluationContext, WriterDecisionIR
    from .ir import ActionIR
    from .schema import Relation

WriterKey = tuple[str, str]
ReaderKey = tuple[str, str]
_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
_META = {"domain", "entity", "entity_kind", "unit", "direction", "refresh", "unknown", "cost"}
_LEAF = {"reader_source", "reader_key", "reader", "op", "value"}
_OPS = {"=": operator.eq, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
_DIRECTIONS = {"need", "capacity", "opportunity", "risk", "cost", "commitment", "recovery"}
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
    observation: Observation


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
    reference_key: ReaderKey | None = None
    reference_reader: Reader | None = None
    op: str = "="
    expected: bool | float = True
    unit: str = "flag"
    refresh: str = "consumer"
    observation_object: tuple[str, str, str] | None = None
    reference_object: tuple[str, str, str] | None = None
    reader_aliases: tuple[ReaderKey, ...] = ()
    reference_aliases: tuple[ReaderKey, ...] = ()


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
class PortContribution:
    writer_id: str
    consumer_id: str
    field: str
    actor: str
    target: str
    operation: str
    output_unit: str
    semantic_direction: str
    causal_id: str
    origins: tuple[str, ...]
    unknown: str
    native_cost: str
    binding_role: str = ""
    semantic_role: str = "unspecified"


def contribution(writer: WriterDecisionIR, use: PortUse, graph: PortGraph) -> PortContribution:
    if (writer.source, writer.definition) != (use.source, use.definition):
        raise ValueError("端口贡献缺少精确生产writer")
    node = graph.node(use.port)
    context = writer.evaluation_context
    if context is None or context.status != "observed":
        raise ValueError("端口贡献缺少实际observed求值上下文")
    bindings = (context.actor_scope, *context.targets, *context.auxiliary_scopes)
    for origin in graph.origins(use.port):
        if not any(
            binding is not None
            and (binding.name, binding.kind, (binding.role,))
            == (origin.entity, origin.entity_kind, origin.observation.roles)
            for binding in bindings
        ):
            raise ValueError("端口贡献原始观测对象/角色不能映射到实际writer")
    cause = use.relation_cause or (
        writer.legacy.contribution_group
        if writer.legacy is not None
        else writer.action.cause_group
        if writer.action is not None
        else ""
    )
    return PortContribution(
        writer.writer_id,
        writer.consumer_id,
        writer.field,
        writer.actor,
        writer.target,
        writer.operation,
        "multiplier_delta" if writer.operation == "multiply" else "additive_delta",
        use.role,
        cause,
        tuple(origin.identity for origin in graph.origins(use.port)),
        node.unknown,
        "retain_native_cost; supplemental_new_commitment_pressure"
        if use.role == "cost"
        else "retain_native_cost",
        use.role,
        writer.legacy.semantic_role if writer.legacy is not None else "unspecified",
    )


@dataclass(frozen=True, slots=True)
class PortBinding:
    source: str
    definition: str
    port: str
    graph: PortGraph
    required_known: tuple[str, ...] = ()
    role: str = "need"
    contribution: PortContribution | None = None
    writer: WriterDecisionIR | None = None
    cost_predicates: tuple[Any, ...] = ()
    pressure_facts: tuple[str, ...] = ()
    unknown_cost_anchors: tuple[str, ...] = ()

    def validate(self, rule: Rule, readers: Mapping[str, Reader]) -> None:
        self.graph.assert_predicates(self.port, rule.conditions, readers)
        if self.required_known != rule.required_known_facts:
            raise ValueError("端口核心已知输入与实际规则不一致")
        if self.contribution is not None and (
            self.contribution.field != ".".join(rule.field)
            or self.contribution.operation != rule.operation
            or self.contribution.causal_id != rule.contribution_group
            or self.contribution.semantic_direction != self.role
            or self.contribution.origins
            != tuple(origin.identity for origin in self.graph.origins(self.port))
        ):
            raise ValueError(
                "端口贡献consumer/单位/方向/因果身份与执行规则不一致，不能重复借用另一原因"
            )
        if self.writer is not None:
            uses = [
                use
                for use in self.graph.writer_uses(self.source, self.definition)
                if (use.port, use.role) == (self.port, self.role)
            ]
            if len(uses) != 1 or self.contribution != contribution(
                self.writer, uses[0], self.graph
            ):
                raise ValueError("端口贡献与实际唯一writer的consumer/对象/角色/单位合同漂移")
        if self.role == "cost":
            if not rule.conservative_unknown_facts:
                if (
                    rule.semantic_role != "cost"
                    or (self.cost_predicates and self.cost_predicates != rule.conditions)
                    or self.pressure_facts
                    or self.unknown_cost_anchors
                ):
                    raise ValueError("普通成本端口必须保持精确已知谓词与局部未知退出")
                return
            if (
                rule.semantic_role != "cost"
                or (self.cost_predicates and self.cost_predicates != rule.conditions)
                or (self.cost_predicates and self.pressure_facts != rule.conservative_unknown_facts)
                or (
                    self.cost_predicates
                    and self.unknown_cost_anchors != rule.unknown_cost_required_known_facts
                )
                or (
                    not self.cost_predicates
                    and set(rule.conservative_unknown_facts) != {p.fact for p in rule.conditions}
                )
                or (not self.cost_predicates and rule.unknown_cost_required_known_facts)
                or self.graph.guard(self.source, self.definition, self.port).unknown_policy
                != "conservative"
            ):
                raise ValueError("成本端口必须绑定原有core/proven-cheap/else-conservative合同")
        elif rule.semantic_role == "cost" and (
            rule.conservative_unknown_facts or self.role != "condition"
        ):
            raise ValueError("成本不能使用普通need/recovery守卫")

    def evaluate(self, values: Mapping[str, object], readers: Mapping[str, Reader]) -> bool:
        self.graph.guard(self.source, self.definition, self.port)
        return self.graph.evaluate(
            self.port, {(self.source, key): value for key, value in values.items()}
        ) is True and all(readers[key].accepts(values.get(key)) for key in self.required_known)

    def cost_values(
        self, values: Mapping[str, object], readers: Mapping[str, Reader]
    ) -> tuple[bool, bool]:
        if self.role != "cost":
            raise ValueError("非成本端口不能替换成本核心与免除守卫")
        self.graph.evaluate(self.port, {(self.source, key): value for key, value in values.items()})
        if self.cost_predicates:
            # Reuse the existing scalar program's proven core/pressure/anchor
            # contract. Ports only provide equivalent original observations.
            from types import SimpleNamespace  # noqa: PLC0415

            from .ir import PredicateIR  # noqa: PLC0415
            from .programs import _cost_guard_values  # noqa: PLC0415

            item = SimpleNamespace(
                required_known_facts=self.required_known,
                predicates=tuple(PredicateIR(p.fact, p.op, p.value) for p in self.cost_predicates),
                conservative_unknown_facts=self.pressure_facts,
                unknown_cost_required_known_facts=self.unknown_cost_anchors,
            )
            return _cost_guard_values(cast("ActionIR", item), values, readers)
        raw = {(self.source, key): value for key, value in values.items()}
        core = all(readers[key].accepts(values.get(key)) for key in self.required_known)
        return core, self.graph.evaluate(self.port, raw) is False

    def cost_guard(self) -> str:
        """Known false pressure alone waives cost; core false never substitutes."""
        if not self.cost_predicates:
            return self.graph.guard(self.source, self.definition, self.port).when_false
        declared = set(self.pressure_facts)
        branches = []
        for leaf in self.graph.leaves(self.port):
            if leaf.reader is None or not (
                {leaf.reader.key, *(key for source, key in leaf.reader_aliases)} & declared
            ):
                continue
            # Leaf guard is a declared same-writer closure, without inventing
            # new graph uses or permitting a different writer's leaf.
            branches.append(self.graph._render_guard(leaf.id)[1])
        return "OR = { " + " ".join(f"AND = {{ {part} }}" for part in branches) + " }"


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
class _GraphIndex:
    by_id: Mapping[str, Port]
    by_writer: Mapping[WriterKey, tuple[PortUse, ...]]
    by_source: Mapping[str, tuple[PortUse, ...]]
    origin_rows: Mapping[str, tuple[Origin, ...]]
    expansions: Mapping[str, int]
    costs: Mapping[str, int]
    closures: Mapping[str, tuple[str, ...]]
    leaves: Mapping[str, tuple[Port, ...]]


@dataclass(frozen=True, slots=True)
class PortGraph:
    ports: tuple[Port, ...]
    uses: tuple[PortUse, ...]
    topological: tuple[str, ...]
    origin_rows: tuple[tuple[str, tuple[Origin, ...]], ...]
    expansions: tuple[tuple[str, int], ...]
    costs: tuple[tuple[str, int], ...]
    _index: _GraphIndex = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_id = {port.id: port for port in self.ports}
        if len(by_id) != len(self.ports) or len(set(self.topological)) != len(self.topological):
            raise ValueError("端口节点或拓扑身份重复")
        if set(self.topological) != set(by_id):
            raise ValueError("端口拓扑身份缺失")
        by_writer: dict[WriterKey, list[PortUse]] = {}
        by_source: dict[str, list[PortUse]] = {}
        use_ids = set()
        for use in self.uses:
            identity = (use.source, use.definition, use.port, use.role)
            if identity in use_ids or use.port not in by_id:
                raise ValueError("端口writer use重复或悬边")
            use_ids.add(identity)
            by_writer.setdefault((use.source, use.definition), []).append(use)
            by_source.setdefault(use.source, []).append(use)
        closures: dict[str, tuple[str, ...]] = {}
        leaves: dict[str, tuple[Port, ...]] = {}
        rank = {key: position for position, key in enumerate(self.topological)}
        for key in self.topological:
            node = by_id[key]
            if any(dep not in closures for dep in node.dependencies):
                raise ValueError("端口拓扑顺序、依赖悬边或DAG合同漂移")
            reachable = {key}
            for dep in node.dependencies:
                reachable.update(closures[dep])
            closures[key] = tuple(sorted(reachable, key=rank.__getitem__))
            leaves[key] = (
                (node,)
                if node.reader is not None
                else tuple(leaf for dep in node.dependencies for leaf in leaves[dep])
            )
        for label, values in (
            ("origins", self.origin_rows),
            ("expansions", self.expansions),
            ("costs", self.costs),
        ):
            mapped = dict(values)
            if len(mapped) != len(values) or set(mapped) != set(by_id):
                raise ValueError(f"端口{label}完整身份缺失或重复")
        object.__setattr__(
            self,
            "_index",
            _GraphIndex(
                MappingProxyType(by_id),
                MappingProxyType({key: tuple(value) for key, value in by_writer.items()}),
                MappingProxyType({key: tuple(value) for key, value in by_source.items()}),
                MappingProxyType(dict(self.origin_rows)),
                MappingProxyType(dict(self.expansions)),
                MappingProxyType(dict(self.costs)),
                MappingProxyType(closures),
                MappingProxyType(leaves),
            ),
        )

    def node(self, port_id: str) -> Port:
        return self._index.by_id[port_id]

    def writer_uses(self, source: str, definition: str) -> tuple[PortUse, ...]:
        return self._index.by_writer.get((source, definition), ())

    def source_uses(self, source: str) -> tuple[PortUse, ...]:
        return self._index.by_source.get(source, ())

    def validate_origins(self, port_id: str) -> None:
        for leaf in self.leaves(port_id):
            expected = {
                key: reader
                for key, reader in (
                    (leaf.reader_key, leaf.reader),
                    (leaf.reference_key, leaf.reference_reader),
                )
                if key is not None and reader is not None
            }
            rows = self.origins(leaf.id)
            if len(rows) != len(expected):
                raise ValueError("端口缺少比较两侧的完整原始观测")
            for origin in rows:
                reader = expected.get((origin.reader_source, origin.reader_key))
                if reader is None:
                    raise ValueError("端口原始叶观测未绑定比较两侧")
                signature = _canonical(reader_signature(reader))
                observation = origin.observation
                expected_object = (
                    leaf.reference_object
                    if (origin.reader_source, origin.reader_key) == leaf.reference_key
                    and leaf.reference_object is not None
                    else leaf.observation_object
                )
                if (
                    leaf.unit != "flag"
                    or leaf.refresh != "consumer"
                    or origin.identity != observation.identity
                    or origin.signature != signature
                    or observation.getter != signature
                    or observation.original_unit != reader.unit
                    or observation.source != origin.reader_source
                    or observation.timing != leaf.refresh
                    or (observation.entity, observation.entity_kind)
                    != (expected_object[:2] if expected_object else (leaf.entity, leaf.entity_kind))
                    or (expected_object is not None and observation.roles != (expected_object[2],))
                ):
                    raise ValueError("端口原始观测完整身份/单位/对象/时机漂移")

    def leaves(self, port_id: str) -> tuple[Port, ...]:
        return self._index.leaves[port_id]

    def assert_predicates(
        self, port_id: str, predicates, readers: Mapping[str, Reader], *, mode: str = "all"
    ) -> None:
        """Only exact existing conjunction/disjunction substitutions are allowed."""
        node = self.node(port_id)
        by_id = self._index.by_id

        def flatten(key):
            item = by_id[key]
            if item.reader is not None:
                right = (
                    {"reader": reader_signature(item.reference_reader)}
                    if item.reference_reader is not None
                    else item.expected
                )
                return [(reader_signature(item.reader), item.op, right)]
            if item.mode != mode:
                raise ValueError("端口不能替换非等价生产谓词结构")
            return [entry for dep in item.dependencies for entry in flatten(dep)]

        from pdx.decision_rules import FactReference  # noqa: PLC0415

        expected = sorted(
            _canonical(
                (
                    reader_signature(readers[p.fact]),
                    p.op,
                    {"reader": reader_signature(readers[p.value.key])}
                    if isinstance(p.value, FactReference)
                    else p.value,
                )
            )
            for p in predicates
        )
        actual = sorted(_canonical(entry) for entry in flatten(node.id))
        if actual != expected:
            raise ValueError(f"端口与具体生产term谓词不等价: {port_id}")

    def origins(self, port_id: str) -> tuple[Origin, ...]:
        return self._index.origin_rows[port_id]

    def expanded_leaves(self, port_id: str) -> int:
        return self._index.expansions[port_id]

    def evaluate(
        self,
        port_id: str,
        values: Mapping[ReaderKey, object],
        *,
        predicate_values: Mapping[str, object] | None = None,
    ) -> Truth:
        """Accept original (source,key) values only, never caller aliases."""
        self.validate_origins(port_id)
        evaluated: dict[str, Truth] = {}
        by_id = self._index.by_id

        def original_value(primary, aliases):
            present = [values[key] for key in (aliases or (primary,)) if key in values]
            if not present:
                return None
            first = present[0]
            if any(type(value) is not type(first) or value != first for value in present[1:]):
                raise ValueError("同一完整原始观测的别名值冲突，不能以known覆盖unknown")
            return first

        for key in self._index.closures[port_id]:
            port = by_id[key]
            if port.reader is not None and port.reader_key is not None:
                raw = original_value(port.reader_key, port.reader_aliases)
                right = (
                    original_value(port.reference_key, port.reference_aliases)
                    if port.reference_key
                    else port.expected
                )
                evaluated[key] = (
                    bool(_OPS[port.op](cast("float | bool", raw), cast("float | bool", right)))
                    if port.reader.accepts(raw)
                    and (port.reference_reader is None or port.reference_reader.accepts(right))
                    else None
                )
                if (
                    not any(
                        alias in values for alias in (port.reader_aliases or (port.reader_key,))
                    )
                    and predicate_values is not None
                ):
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
        self.validate_origins(port_id)
        if not any(
            (use.source, use.definition, use.port) == (source, definition, port_id)
            for use in self.writer_uses(source, definition)
        ):
            raise ValueError(f"端口未声明 writer 使用: {source}:{definition}:{port_id}")
        positive, negative = self._render_guard(port_id)
        return PortGuard(
            positive,
            negative,
            self.node(port_id).unknown,
            tuple(origin.identity for origin in self.origins(port_id)),
            self._index.costs[port_id],
        )

    def _render_guard(self, port_id: str) -> tuple[str, str]:
        rendered: dict[str, tuple[str, str]] = {}
        by_id = self._index.by_id
        for key in self._index.closures[port_id]:
            port = by_id[key]
            if port.reader is not None:
                reader = port.reader
                from pdx.decision_rules import FactReference  # noqa: PLC0415

                right = (
                    FactReference(port.reference_reader.key, port.reference_reader.reference())
                    if port.reference_reader is not None
                    else port.expected
                )
                comparison = reader.expression(port.op, right)
                bounds = [
                    reader.expression(op, bound)
                    for op, bound in ((">=", reader.minimum), ("<=", reader.maximum))
                    if bound is not None
                ]
                positive = " ".join((*bounds, comparison))
                negative = " ".join((*bounds, f"NOT = {{ {comparison} }}"))
                right_known = ""
                if port.reference_reader is not None:
                    rhs = port.reference_reader
                    checks = " ".join(
                        rhs.expression(op, bound)
                        for op, bound in ((">=", rhs.minimum), ("<=", rhs.maximum))
                        if bound is not None
                    )
                    right_known = _scoped(rhs, checks) + " "
                rendered[key] = (
                    right_known + _scoped(reader, positive),
                    right_known + _scoped(reader, negative),
                )
            elif port.mode == "not":
                positive, negative = rendered[port.dependencies[0]]
                rendered[key] = negative, positive
            else:
                # A scoped leaf is two adjacent conditions (exists + scope).
                # Preserve that conjunction when it becomes an OR operand;
                # otherwise existence alone can waive a real financing cost.
                positive = " ".join(
                    f"AND = {{ {rendered[dep][0]} }}" if port.mode == "any" else rendered[dep][0]
                    for dep in port.dependencies
                )
                negative = " ".join(
                    f"AND = {{ {rendered[dep][1]} }}" if port.mode == "all" else rendered[dep][1]
                    for dep in port.dependencies
                )
                shared = self._conjunctive_leaf_guard(port) if key == port_id else None
                rendered[key] = (
                    shared
                    if shared is not None
                    else f"{'AND' if port.mode == 'all' else 'OR'} = {{ {positive} }}",
                    f"{'OR' if port.mode == 'all' else 'AND'} = {{ {negative} }}",
                )
        return rendered[port_id]

    def _conjunctive_leaf_guard(self, port: Port) -> str | None:
        """Share scope prefixes only in a conjunction of direct scalar leaves.

        Prefix existence, reader bounds and comparisons remain conjuncts.  The
        established rule renderer owns the scope trie.  Reference RHS and the
        article input alias keep their exact original renderer, as do all
        negative/any/not branches and required-known/cost fallback envelopes.
        """
        leaves = tuple(self._index.by_id[key] for key in port.dependencies)
        if (
            port.mode != "all"
            or not leaves
            or any(
                leaf.mode != "leaf"
                or leaf.reader is None
                or leaf.reference_reader is not None
                or leaf.reader.scope == "article_input_market_goods"
                for leaf in leaves
            )
        ):
            return None
        from collections import defaultdict  # noqa: PLC0415

        from pdx.decision_rules import _scoped_conditions  # noqa: PLC0415

        conditions: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
        for leaf in leaves:
            reader = leaf.reader
            assert reader is not None
            expressions = [
                reader.expression(op, bound)
                for op, bound in ((">=", reader.minimum), ("<=", reader.maximum))
                if bound is not None
            ]
            expressions.append(reader.expression(leaf.op, leaf.expected))
            conditions[(reader.scope, reader.path)].extend(expressions)
        return _scoped_conditions(conditions)

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
    for use in graph.source_uses(source):
        if not use.relation_cause:
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
    if reader.scope == "article_input_market_goods":
        if (
            reader.engine,
            reader.kind,
            reader.unit,
            reader.argument,
            reader.path,
            reader.parameters,
            reader.value_field,
        ) != ("market_goods_delta", "number", "sell_minus_buy_orders", None, (), (), None):
            raise ValueError("条约输入市场商品别名只允许精确现有delta读取器")
        anchor = '"scope:article.input_market_goods(root)"'
    else:
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
    if modes in (_LEAF, (_LEAF - {"value"}) | {"value_fact", "value_reader"}):
        ref = (_text(row["reader_source"], "reader_source"), _text(row["reader_key"], "reader_key"))
        reader = readers.get(ref)
        if reader is None or _canonical(row["reader"]) != _canonical(reader_signature(reader)):
            raise ValueError(f"端口 reader signature 不匹配实际生产: {key}")
        if row["entity"] != reader.scope:
            raise ValueError(f"端口实体与reader作用域不符: {key}")
        value, op = row.get("value"), row["op"]
        if "value_fact" in row:
            right_key = (ref[0], _text(row["value_fact"], "value_fact"))
            right = readers.get(right_key)
            if (
                right is None
                or right_key == ref
                or _canonical(row["value_reader"]) != _canonical(reader_signature(right))
                or reader.kind != "number"
                or right.kind != "number"
                or (reader.unit, reader.scope, reader.path) != (right.unit, right.scope, right.path)
                or op not in _OPS
            ):
                raise ValueError(f"相对端口必须绑定同对象同单位精确数值Reader: {key}")
            right.reference()
            kwargs.update(reference_key=right_key, reference_reader=right)
            value = 0.0  # unused literal slot; RHS always comes from reference_reader
        if op not in _OPS or (reader.kind == "boolean" and (op != "=" or type(value) is not bool)):
            raise ValueError(f"端口比较类型无效: {key}")
        if reader.kind != "boolean" and (
            type(value) not in (int, float) or not math.isfinite(cast("int | float", value))
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
    source_hashes: Mapping[str, str],
    source_proofs: Mapping[str | ReaderKey, tuple[str, ...]],
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
    # Index exact leaf aliases and each bounded actual use once. Do not cross
    # every raw observation with every use and every node to discover contexts.
    context_uses: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for raw_use in data["uses"]:
        stack, reached = [raw_use["port"]], set()
        aliases = set()
        while stack:
            member = stack.pop()
            if member in reached or member not in by_id:
                continue
            reached.add(member)
            candidate = by_id[member]
            stack.extend(candidate.dependencies)
            if candidate.reader is not None and candidate.reader_key is not None:
                aliases.add(
                    (
                        candidate.reader_key[0],
                        _canonical(reader_signature(candidate.reader)),
                        candidate.entity,
                        candidate.entity_kind,
                    )
                )
        for alias in aliases:
            context_uses.setdefault(alias, []).append(raw_use)

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
            roles: set[str] = set()
            context_proofs: set[str] = set()
            proof = set(
                source_proofs.get(node.reader_key, source_proofs.get(node.reader_key[0], ()))
            )
            alias = (node.reader_key[0], signature, node.entity, node.entity_kind)
            for raw_use in context_uses.get(alias, ()):
                context = writers.get((raw_use["source"], raw_use["definition"]))
                if context is None or context.status != "observed":
                    raise ValueError("原始观测缺少实际writer可证上下文")
                bindings = (context.actor_scope, *context.targets, *context.auxiliary_scopes)
                matching = [
                    binding
                    for binding in bindings
                    if binding is not None
                    and (binding.name, binding.kind) == (node.entity, node.entity_kind)
                ]
                if len(matching) != 1:
                    raise ValueError("原始观测实体/角色与writer上下文不匹配")
                roles.add(matching[0].role)
                proof.update(context.evidence)
                context_proofs.update(context.evidence)
            origin_inputs = [(node.reader_key, node.reader)]
            if node.reference_key is not None and node.reference_reader is not None:
                origin_inputs.append((node.reference_key, node.reference_reader))
            original_rows = []
            for reader_key, original_reader in origin_inputs:
                signature = _canonical(reader_signature(original_reader))
                original_proof = set(
                    source_proofs.get(reader_key, source_proofs.get(reader_key[0], ()))
                )
                original_proof.update(context_proofs)
                original_observation = Observation(
                    reader_key[0],
                    source_hashes.get(reader_key[0], ""),
                    signature,
                    node.entity,
                    node.entity_kind,
                    tuple(sorted(roles)),
                    tuple(sorted(original_proof)),
                    original_reader.unit,
                    node.refresh,
                    "preserve_unknown",
                    node.cost,
                )
                original_rows.append(
                    Origin(
                        original_observation.identity,
                        *reader_key,
                        signature,
                        node.entity,
                        node.entity_kind,
                        original_observation,
                    )
                )
            origins[key] = tuple(original_rows)
            depth[key], expanded[key], costs[key] = (
                1,
                len(origin_inputs),
                node.cost * len(origin_inputs),
            )
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

    # Diagnose malformed declared edges before unrelated unused leaves need a
    # legal consumer context. Every node still must be reached below.
    for key in dict.fromkeys([*(use["port"] for use in data["uses"]), *by_id]):
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
    source_hashes: Mapping[str, str],
    source_proofs: Mapping[str | ReaderKey, tuple[str, ...]],
) -> PortGraph:
    return from_data(
        tomllib.loads(path.read_text(encoding="utf-8")),
        readers=readers,
        writers=writers,
        source_hashes=source_hashes,
        source_proofs=source_proofs,
    )
