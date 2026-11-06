"""Finite consumer partitions over the existing typed ports and scalar guards.

No values, outcome scores, engine state, role inference, or unknown detector is
introduced. Caller supplies actual validated policies and exact reader-object
bindings; a frozen selected source/field set bounds intake.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from pdx import building_defaults, decision_interfaces
from pdx.decision_rules import FactReference, Predicate, Reader, RuleSet

from . import decision_ir, engine_scope, ports
from .evidence import Observation

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def selected_consumers(data: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    if (
        set(data) != {"schema", "scope", "semantics", "sources", "hard_cap", "consumers"}
        or data["schema"] != 1
    ):
        raise ValueError("经济消费者有限selector schema无效")
    if (
        data["scope"] != ["B01", "B02", "B03", "B04"]
        or data["semantics"] != "exact_existing_predicate_guard_only; unspecified_remains_pending"
    ):
        raise ValueError("经济消费者selector不能扩展语义范围")
    if data["hard_cap"] != {"ports": 3544, "origins": 1806, "uses": 3601, "partitions": 505}:
        raise ValueError("经济消费者batch硬总cap漂移")
    rows = data["consumers"]
    if any(set(row) != {"source", "field"} for row in rows):
        raise ValueError("经济消费者必须声明精确source/field")
    selected = tuple((row["source"], row["field"]) for row in rows)
    if (
        len(selected) != 505
        or len(set(selected)) != len(selected)
        or len(data["sources"]) != 50
        or sorted({s for s, f in selected}) != data["sources"]
    ):
        raise ValueError("经济消费者冻结全集、来源或重复身份漂移")
    return selected


def selected_proven_consumers(data: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Read the frozen exact intake; runtime discovery must equal this set."""
    if (
        set(data) != {"schema", "scope", "semantics", "sources", "hard_cap", "consumers"}
        or data["schema"] != 1
        or data["scope"] != "all_current_observed_ruleset_contexts"
        or data["semantics"] != "exact_existing_predicate_guard_only; unspecified_remains_pending"
        or data["hard_cap"] != {"ports": 4737, "origins": 2290, "uses": 6152, "partitions": 965}
    ):
        raise ValueError("全量已证明RuleSet消费者精确selector或硬总cap漂移")
    rows = data["consumers"]
    if any(set(row) != {"source", "field"} for row in rows):
        raise ValueError("全量已证明消费者必须声明精确source/field")
    selected = tuple((row["source"], row["field"]) for row in rows)
    if (
        len(selected) != 965
        or len(set(selected)) != len(selected)
        or len(data["sources"]) != 90
        or sorted({source for source, _field in selected}) != data["sources"]
    ):
        raise ValueError("全量已证明RuleSet消费者冻结全集、来源或重复身份漂移")
    return selected


def evaluation_contexts() -> tuple[decision_ir.EvaluationContext, decision_ir.EvaluationContext]:
    """Use the already frozen complete native frame proofs; no engine read."""
    raw = building_defaults.snapshot()
    data = json.loads(raw)
    frame = data["contract"]["frame"]
    if frame != {
        "type": "state",
        "type_tag": "0x4c",
        "root": "candidate_state",
        "current": "candidate_state",
        "from": "candidate_state",
        "injected_investor_country": False,
        "injected_target_building": False,
    }:
        raise ValueError("建筑script州frame精确合同漂移")
    roles = data["contract"]["roles"]
    if (
        roles["state_owner"] != "candidate_state+0xed8; independently resolved country"
        or roles["payer"] != "unresolved"
    ):
        raise ValueError("建筑owner独立解析或payer边界漂移")
    text = raw.decode("utf-8")
    line = text.count("\n", 0, text.index('"type": "state"', text.index('"frame":'))) + 1
    owner_line = text.count("\n", 0, text.index('"state_owner":', text.index('"roles":'))) + 1
    source = building_defaults.MANIFEST_ID
    state = decision_ir.ContextBinding("root", "state", "actor", source, line)
    owner = decision_ir.ContextBinding("owner", "country", "auxiliary", source, owner_line)
    building = decision_ir.EvaluationContext(
        state,
        auxiliary_scopes=(owner,),
        evidence=(
            f"{source}:{line}",
            f"{source}:{owner_line}",
            f"{source}:sha256={hashlib.sha256(raw).hexdigest()}",
            f"{source}:script_ROOT_state;owner_auxiliary;candidate_country_and_payer_unresolved",
        ),
    )
    raw = engine_scope.MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != engine_scope.MANIFEST_SHA256:
        raise ValueError("科技country frame证据漂移")
    data = json.loads(raw)
    if data["consumer"] != {
        "directory": "technology",
        "field": "ai_weight",
        "actor_scope": "country",
        "target_scope": "definition_only:technology",
        "operation": "base_candidate_score",
        "capability": "direct",
    }:
        raise ValueError("科技精确country候选frame合同漂移")
    text = raw.decode("utf-8")
    line = text.count("\n", 0, text.index('"actor_scope": "country"')) + 1
    source = engine_scope.MANIFEST_ID
    country = decision_ir.ContextBinding("root", "country", "actor", source, line)
    technology = decision_ir.EvaluationContext(
        country,
        evidence=(
            f"{source}:{line}",
            f"{source}:sha256={engine_scope.MANIFEST_SHA256}",
            f"{source}:definition_only:technology;no_saved_target_scope",
        ),
    )
    return building, technology


def validate_context_readers(
    source: str,
    field: str,
    context: decision_ir.EvaluationContext,
    readers: Mapping[str, Reader],
    predicates: tuple[Predicate, ...],
    *,
    actor_path: tuple[str, ...],
    native_root: str | None,
    input_keys: tuple[str, ...],
    evidenced_contexts: tuple[decision_ir.EvaluationContext, decision_ir.EvaluationContext]
    | None = None,
) -> tuple[tuple[str, str, str, str], ...]:
    building, technology = (
        evaluation_contexts() if evidenced_contexts is None else evidenced_contexts
    )
    is_building = source.startswith("common/buildings/")
    expected = building if is_building else technology
    if (
        context != expected
        or native_root != ("state" if is_building else "country")
        or actor_path != (("owner",) if is_building else ())
    ):
        raise ValueError("经济消费者script ROOT/owner精确上下文漂移")
    parts = tuple(field.split("."))
    if len(parts) != 2 or parts[-1] != ("ai_value" if is_building else "ai_weight"):
        raise ValueError("经济消费者没有精确已证明字段")
    keys = (
        set(input_keys)
        | {p.fact for p in predicates}
        | {p.value.key for p in predicates if isinstance(p.value, FactReference)}
    )
    result = []
    for key in sorted(keys):
        reader = readers[key]
        decision_interfaces.reader_scope(
            reader, actor_path, native_root=native_root, source=source, field=parts, context=context
        )
        if reader.scope != "root":
            raise ValueError("经济消费者没有额外saved scope授权")
        if is_building and reader.path and reader.path[0] == "owner":
            binding = (key, "owner", "country", "auxiliary")
        else:
            if (
                is_building
                and reader.path
                and reader.path[0] not in {"sg:electricity", "sg:transportation"}
            ):
                raise ValueError("建筑reader路径偏离精确州本地/owner")
            if not is_building and reader.path and reader.path[0] != "market":
                raise ValueError("科技reader路径偏离精确country")
            binding = (key, "root", "state" if is_building else "country", "actor")
        result.append(binding)
    return tuple(result)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _id(value: Any) -> str:
    return "consumer_" + hashlib.sha256(_canonical(value).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsumerPartitions:
    partitions: tuple[tuple[tuple[str, str], ports.PortGraph], ...]
    origin_pool: tuple[ports.Origin, ...]
    ports_count: int
    uses_count: int
    by_consumer: Mapping[tuple[str, str], ports.PortGraph]
    by_writer: Mapping[tuple[str, str], ports.PortGraph]
    by_port: Mapping[str, ports.Port]

    def graph(self, source: str, field: str) -> ports.PortGraph:
        return self.by_consumer[(source, field)]

    def writer_graph(self, source: str, definition: str) -> ports.PortGraph:
        return self.by_writer[(source, definition)]


def derive(
    policies: tuple[tuple[str, RuleSet], ...],
    *,
    selected_consumers: Iterable[tuple[str, str]],
    contexts: Mapping[tuple[str, str], decision_ir.EvaluationContext],
    reader_bindings: Mapping[tuple[str, str], tuple[tuple[str, str, str, str], ...]],
    source_proofs: Mapping[str | tuple[str, str], tuple[str, ...]],
    hard_cap: Mapping[str, int],
) -> ConsumerPartitions:
    """Construct the actual bounded shared graph once from caller-validated IR.

    Building owner identity comes only from exact reader_bindings. Reader.scope
    and path retain the script evaluation frame used by the existing renderer;
    observation object records the actual country/state separately.
    """
    selected = frozenset(selected_consumers)
    by_policy = dict(policies)
    if len(by_policy) != len(policies):
        raise ValueError("消费者policy source重复")
    chosen = []
    actual = set()
    seen = set()
    reader_map: dict[tuple[str, str], Reader] = {}
    proofs: dict[tuple[str, str, tuple[str, str, str]], set[str]] = defaultdict(set)
    for source, policy in policies:
        for reader in policy.readers:
            reader_map[(source, reader.key)] = reader
        for rule in policy.rules:
            consumer = (source, ".".join(rule.field))
            if consumer not in selected:
                continue
            writer_key = (source, rule.id)
            if writer_key in seen:
                raise ValueError("消费者writer身份重复")
            seen.add(writer_key)
            context = contexts.get(writer_key)
            if context is None or context.status != "observed":
                raise ValueError("消费者缺少精确observed上下文")
            binding_rows = reader_bindings.get(writer_key, ())
            if len(set(binding_rows)) != len(binding_rows):
                raise ValueError("消费者reader对象绑定重复")
            legal = {
                (b.name, b.kind, b.role)
                for b in (context.actor_scope, *context.targets, *context.auxiliary_scopes)
                if b is not None
            }
            grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
            for reader_key, entity, kind, binding_role in binding_rows:
                binding = (entity, kind, binding_role)
                if binding not in legal:
                    raise ValueError("消费者reader对象/角色没有精确合法上下文")
                grouped[reader_key].append(binding)
            bindings: dict[str, tuple[str, str, str]] = {}
            for reader_key, objects in grouped.items():
                reader = reader_map[(source, reader_key)]
                # Argument objects are retained and validated as context input;
                # the getter observation has one primary scoped object/role.
                primary = [obj for obj in objects if obj[0] == reader.scope]
                if len(objects) == 1:
                    bindings[reader_key] = objects[0]
                elif len(primary) == 1:
                    bindings[reader_key] = primary[0]
                else:
                    raise ValueError("消费者reader缺少唯一主观测对象")
            for condition in rule.conditions:
                condition_keys = (
                    (condition.fact, condition.value.key)
                    if isinstance(condition.value, FactReference)
                    else (condition.fact,)
                )
                for reader_key in condition_keys:
                    if reader_key not in bindings or bindings[reader_key] not in legal:
                        raise ValueError("消费者reader对象/角色没有精确合法上下文")
                    signature = ports.reader_signature(reader_map[(source, reader_key)])
                    alias = (source, _canonical(signature), bindings[reader_key])
                    proofs[alias].update(context.evidence)
            chosen.append((source, policy, rule, context, bindings))
            actual.add(consumer)
    if actual != selected:
        raise ValueError("消费者冻结全集缺失或额外")
    origin_pool: dict[str, ports.Origin] = {}
    original_inputs: dict[tuple[str, str, tuple[str, str, str]], str] = {}
    origin_aliases: dict[str, set[tuple[str, str]]] = defaultdict(set)
    # Freeze aliases by the complete Observation identity before building ports.
    # Same getter spelling alone cannot cross proof, object, role or policy SHA.
    for source, policy, rule, _context, bindings in chosen:
        keys = {p.fact for p in rule.conditions} | {
            p.value.key for p in rule.conditions if isinstance(p.value, FactReference)
        }
        for key in sorted(keys):
            reader = reader_map[(source, key)]
            binding = bindings[key]
            origin_signature = ports._canonical(ports.reader_signature(reader))
            alias = (source, _canonical(ports.reader_signature(reader)), binding)
            proof = set(source_proofs.get((source, key), source_proofs.get(source, ())))
            proof.update(proofs[alias])
            observation = Observation(
                source,
                policy.source_sha256,
                origin_signature,
                binding[0],
                binding[1],
                (binding[2],),
                tuple(sorted(proof)),
                reader.unit,
                "consumer",
                "preserve_unknown",
                1,
            )
            row = ports.Origin(
                observation.identity,
                source,
                key,
                origin_signature,
                binding[0],
                binding[1],
                observation,
            )
            previous = origin_pool.setdefault(row.identity, row)
            if previous.observation != row.observation:
                raise ValueError("消费者原始观测池身份冲突")
            if row.reader_key < previous.reader_key:
                origin_pool[row.identity] = row
            original_inputs[(source, key, binding)] = row.identity
            origin_aliases[row.identity].add((source, key))
    node_pool: dict[str, ports.Port] = {}
    part_data: dict[tuple[str, str], dict[str, Any]] = {}
    for source, _policy, rule, context, bindings in chosen:
        if context.actor_scope is None:
            raise ValueError("消费者缺少已证明的script actor frame")
        consumer = (source, ".".join(rule.field))
        part = part_data.setdefault(
            consumer,
            {
                "nodes": {},
                "uses": [],
                "origins": {},
                "expanded": {},
                "costs": {},
                "order": [],
                "predicate_count": 0,
            },
        )
        role = (
            "cost"
            if rule.semantic_role == "cost" and rule.conservative_unknown_facts
            else "condition"
        )
        unknown = (
            "conservative" if role == "cost" and rule.conservative_unknown_facts else "vanilla"
        )
        leaves = []
        for condition in rule.conditions:
            left = reader_map[(source, condition.fact)]
            right = (
                reader_map[(source, condition.value.key)]
                if isinstance(condition.value, FactReference)
                else None
            )
            if right is not None and (left.scope, left.path, left.unit) != (
                right.scope,
                right.path,
                right.unit,
            ):
                field = ".".join(rule.field).removeprefix("ai_strategy_default.")
                exact_roles = {
                    ("navy_size", "ships", "treaty_port_value"): "auxiliary",
                    ("navy_size", "ships", "wargoal_scores.colonization_rights"): "target",
                    ("gdp", "annual_gdp_currency", "subject_value"): "target",
                }
                target_role = exact_roles.get((left.engine, left.unit, field), "target")
                exact_existing_comparison = (
                    left.kind == right.kind == "number"
                    and left.engine == right.engine
                    and left.unit == right.unit
                    and (
                        (left.engine, left.unit) == ("army_size", "battalions")
                        or (
                            source == "common/ai_strategies/00_default_strategy.txt"
                            and (left.engine, left.unit, field) in exact_roles
                        )
                    )
                    and not left.path
                    and not right.path
                    and not left.parameters
                    and not right.parameters
                    and left.argument is right.argument is None
                    and {left.scope, right.scope} == {"root", "target_country"}
                    and bindings[left.key]
                    == (left.scope, "country", "actor" if left.scope == "root" else target_role)
                    and bindings[right.key]
                    == (right.scope, "country", "actor" if right.scope == "root" else target_role)
                )
                if not exact_existing_comparison:
                    raise ValueError("消费者typed RHS对象或单位不一致")
            origin_rows = []
            for reader in (left, right) if right is not None else (left,):
                binding = bindings[reader.key]
                origin_rows.append(origin_pool[original_inputs[(source, reader.key, binding)]])
            binding = bindings[left.key]
            canonical_left = reader_map[(source, origin_rows[0].reader_key)]
            canonical_right = reader_map[(source, origin_rows[1].reader_key)] if right else None
            payload = (
                source,
                tuple(o.identity for o in origin_rows),
                condition.op,
                None if right else condition.value,
                unknown,
            )
            pid = _id(payload)
            node = ports.Port(
                pid,
                "existing_predicate",
                context.actor_scope.name,
                context.actor_scope.kind,
                role,
                unknown,
                1,
                "leaf",
                reader_key=(source, canonical_left.key),
                reader=canonical_left,
                reference_key=(source, canonical_right.key)
                if canonical_right is not None
                else None,
                reference_reader=canonical_right,
                op=condition.op,
                expected=0 if isinstance(condition.value, FactReference) else condition.value,
                observation_object=binding,
                reference_object=bindings[right.key] if right else None,
                reader_aliases=tuple(sorted(origin_aliases[origin_rows[0].identity])),
                reference_aliases=tuple(sorted(origin_aliases[origin_rows[1].identity]))
                if right
                else (),
            )
            if pid in node_pool and node_pool[pid] != node:
                raise ValueError("消费者端口池身份冲突")
            node_pool.setdefault(pid, node)
            if pid not in part["nodes"]:
                part["nodes"][pid] = node
                part["origins"][pid] = tuple(origin_rows)
                part["expanded"][pid] = len(origin_rows)
                part["costs"][pid] = len(origin_rows)
                part["order"].append(pid)
            leaves.append(pid)
        if not leaves:
            raise ValueError("消费者规则缺少真实谓词")
        if len(set(leaves)) != len(leaves):
            raise ValueError("消费者规则重复同一谓词")
        if len(leaves) == 1:
            root = leaves[0]
        else:
            root = _id((source, tuple(leaves), role, unknown, "all"))
            node = ports.Port(
                root,
                "existing_predicate",
                context.actor_scope.name,
                context.actor_scope.kind,
                role,
                unknown,
                1,
                "all",
                dependencies=tuple(leaves),
            )
            node_pool.setdefault(root, node)
            if root not in part["nodes"]:
                part["nodes"][root] = node
                origins = {o.identity: o for pid in leaves for o in part["origins"][pid]}
                part["origins"][root] = tuple(origins[k] for k in sorted(origins))
                part["expanded"][root] = sum(part["expanded"][pid] for pid in leaves)
                part["costs"][root] = 1 + sum(part["costs"][pid] for pid in leaves)
                part["order"].append(root)
        part["uses"].append(ports.PortUse(source, rule.id, root, role))
        part["predicate_count"] += len(rule.conditions)
    if any(
        len(v["nodes"]) > 256
        or v["predicate_count"] > 160
        or max(v["expanded"].values()) > 4096
        or max(v["costs"].values()) > 16384
        for v in part_data.values()
    ):
        raise ValueError("消费者分区或production predicate硬预算超限")
    counts = {
        "ports": len(node_pool),
        "origins": len(origin_pool),
        "uses": len(chosen),
        "partitions": len(part_data),
    }
    if set(hard_cap) != set(counts) or any(counts[k] > hard_cap[k] for k in counts):
        raise ValueError(f"消费者有限全集总cap超限: {counts}")
    partitions = []
    writer_index = {}
    port_index: dict[str, ports.Port] = {}
    for consumer, part in sorted(part_data.items()):
        graph = ports.PortGraph(
            tuple(part["nodes"].values()),
            tuple(part["uses"]),
            tuple(part["order"]),
            tuple(part["origins"].items()),
            tuple(part["expanded"].items()),
            tuple(part["costs"].items()),
        )
        partitions.append((consumer, graph))
        for use in graph.uses:
            writer_index[(use.source, use.definition)] = graph
        for node in graph.ports:
            port_index.setdefault(node.id, node)
    return ConsumerPartitions(
        tuple(partitions),
        tuple(origin_pool[k] for k in sorted(origin_pool)),
        len(node_pool),
        len(chosen),
        MappingProxyType(dict(partitions)),
        MappingProxyType(writer_index),
        MappingProxyType(port_index),
    )
