"""有限关系图：关系深度和循环在生成期硬失败。"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from .schema import ActionCard, Relation, RelationKind, UnknownPolicy

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class RuleRelationProjection:
    """A world-state relation delta owned by one existing exact rule writer."""

    source: str
    definition: str
    writer_id: str
    field: tuple[str, ...]
    operation: str
    port: str
    cause_id: str
    amount: float
    origins: tuple[str, ...]
    dependency_domain: str
    output_unit: str
    relation_source: str
    relation_target: str

    @property
    def guard_id(self) -> str:
        return f"{self.definition}__relation_{self.cause_id}"

    def validate(self) -> None:
        if (
            not self.source
            or not self.definition
            or not self.writer_id
            or not self.field
            or self.operation != "multiply"
            or self.output_unit != "multiplier_delta"
            or not re.fullmatch(r"[a-z][a-z0-9_]*", self.cause_id)
            or not self.port
            or not self.dependency_domain
            or not self.origins
            or len(set(self.origins)) != len(self.origins)
            or not math.isfinite(self.amount)
            or self.amount <= 0
            or not self.relation_source
            or not self.relation_target
        ):
            raise ValueError("规则关系投影缺少精确writer、正向倍率delta或规范来源合同")


def validate_execution(relation: Relation) -> None:
    """Only implemented entity/unknown policies may enter a numeric program."""
    if relation.scope != "root":
        raise ValueError("行动关系尚未实现非root实体映射")
    if relation.unknown_policy != "vanilla":
        raise ValueError("行动关系尚未实现非vanilla未知策略")
    if relation.cause_id and (
        not re.fullmatch(r"[a-z][a-z0-9_]*", relation.cause_id)
        or not relation.origins
        or not relation.condition_facts
    ):
        raise ValueError("行动关系因果身份必须绑定真实条件和来源")
    if (
        len(set(relation.origins)) != len(relation.origins)
        or any(not isinstance(origin, str) or not origin for origin in relation.origins)
        or (relation.origins and not relation.cause_id)
    ):
        raise ValueError("行动关系来源必须唯一且绑定明确因果身份")


def bind_origins(
    items: tuple[Relation, ...],
    origin_map: Mapping[str, tuple[str, ...]],
) -> tuple[Relation, ...]:
    """Resolve declared source ports to their canonical raw-reader closure.

    Cause identity stays explicit: sharing a raw observation alone never joins
    independent causal claims. The caller supplies the validated port closure.
    """
    result = []
    for item in items:
        validate_execution(item)
        if not item.cause_id:
            result.append(item)
            continue
        if any(origin not in origin_map for origin in (*item.origins, *item.condition_facts)):
            raise ValueError(f"行动关系引用未知来源端口：{item.source}->{item.target}")
        resolved = tuple(sorted({value for origin in item.origins for value in origin_map[origin]}))
        actual = tuple(
            sorted({value for fact in item.condition_facts for value in origin_map[fact]})
        )
        if not resolved or any(not isinstance(value, str) or not value for value in resolved):
            raise ValueError("行动关系原始来源闭包不能为空")
        if resolved != actual:
            raise ValueError("行动关系声明来源与真实条件闭包不一致")
        result.append(replace(item, origins=resolved))
    return tuple(result)


def relations(
    actions: tuple[ActionCard, ...],
    specs: Iterable[Mapping[str, object]] = (),
) -> tuple[Relation, ...]:
    metadata: dict[tuple[str, str, str], Relation] = {}
    for raw in specs:
        source, target, kind = (raw.get("source"), raw.get("target"), raw.get("kind"))
        strength = raw.get("strength", 1.0)
        scope = raw.get("scope", "root")
        condition_facts = raw.get("condition_facts", [])
        unknown_policy = raw.get("unknown_policy", "vanilla")
        cause_id = raw.get("cause_id", "")
        origins = raw.get("origins", [])
        if condition_facts and (
            not {"scope", "unknown_policy", "cause_id", "origins"} <= raw.keys()
            or not cause_id
            or not origins
        ):
            raise ValueError("现实行动关系必须显式声明作用域、未知、因果身份和来源")
        if (
            not all(isinstance(item, str) for item in (source, target, kind, scope, unknown_policy))
            or kind not in {"complements", "substitutes", "conflicts", "enables"}
            or isinstance(strength, bool)
            or not isinstance(strength, (int, float))
            or not math.isfinite(float(strength))
            or float(strength) <= 0
            or not isinstance(condition_facts, list)
            or any(not isinstance(item, str) for item in condition_facts)
            or scope not in {"root", "target_country", "target_state", "owner"}
            or unknown_policy not in {"vanilla", "conservative", "lower_tier"}
            or not isinstance(cause_id, str)
            or not isinstance(origins, list)
            or any(not isinstance(origin, str) for origin in origins)
        ):
            raise ValueError(f"行动关系元数据无效：{source} -> {target} ({kind})")
        source_name = cast("str", source)
        target_name = cast("str", target)
        kind_name: RelationKind = kind
        scope_name = scope
        unknown_name: UnknownPolicy = unknown_policy
        metadata_key = (source_name, target_name, kind_name)
        if metadata_key in metadata:
            raise ValueError(f"行动关系元数据重复：{metadata_key}")
        metadata[metadata_key] = Relation(
            source_name,
            target_name,
            kind_name,
            float(strength),
            scope_name,
            tuple(condition_facts),
            unknown_name,
            cause_id,
            tuple(origins),
        )
        validate_execution(metadata[metadata_key])
    action_ids = {item.id for item in actions}
    result: list[Relation] = []
    seen: set[tuple[str, str, str]] = set()
    for action in actions:
        for kind, targets in (
            ("complements", action.complements),
            ("substitutes", action.substitutes),
            ("conflicts", action.conflicts),
            ("enables", action.enables),
        ):
            for target in targets:
                if target not in action_ids:
                    raise ValueError(f"关系目标不存在：{action.id} -> {target}")
                key = (action.id, target, kind)
                if key in seen:
                    raise ValueError(f"行动关系重复：{action.id} -> {target} ({kind})")
                seen.add(key)
                relation_key = (action.id, target, kind)
                result.append(
                    metadata.get(
                        relation_key,
                        Relation(action.id, target, cast("RelationKind", kind), 1.0),
                    )
                )
    return tuple(result)


def validate(
    actions: tuple[ActionCard, ...],
    *,
    max_depth: int = 2,
    specs: Iterable[Mapping[str, object]] = (),
) -> None:
    graph: dict[str, set[str]] = defaultdict(set)
    relation_list = relations(actions, specs)
    for relation in relation_list:
        if not math.isfinite(relation.strength) or relation.strength <= 0:
            raise ValueError(f"行动关系强度无效：{relation.source} -> {relation.target}")
        # 只有有向 enables 关系禁止环；互补/替代/冲突是协调边，
        # 它们可以形成成对关系而不被误判成依赖环。
        if relation.kind == "enables":
            graph[relation.source].add(relation.target)
    visiting: set[str] = set()

    def walk_enables(node: str, depth: int) -> None:
        if depth > max_depth:
            raise ValueError(f"行动关系深度超过 {max_depth}：{node}")
        if node in visiting:
            raise ValueError(f"行动关系存在循环：{node}")
        visiting.add(node)
        for child in sorted(graph[node]):
            walk_enables(child, depth + 1)
        visiting.remove(node)

    for node in sorted(graph):
        walk_enables(node, 0)

    # 非使能关系允许成对登记，但仍受两级依赖上限约束。沿当前路径
    # 去重，避免 A↔B 的对称配对被误判成环。
    adjacency: dict[str, set[str]] = defaultdict(set)
    for relation in relation_list:
        adjacency[relation.source].add(relation.target)

    def walk_depth(node: str, depth: int, path: frozenset[str]) -> None:
        if depth > max_depth:
            raise ValueError(f"行动关系深度超过 {max_depth}：{node}")
        for child in sorted(adjacency[node] - path):
            walk_depth(child, depth + 1, path | {child})

    for node in sorted(adjacency):
        walk_depth(node, 0, frozenset({node}))

    pairs = {(item.source, item.target, item.kind) for item in relation_list}
    for source, target, kind in sorted(pairs):
        if (
            kind in {"complements", "substitutes", "conflicts"}
            and (
                target,
                source,
                kind,
            )
            not in pairs
        ):
            raise ValueError(f"行动关系缺少对称配对：{source} -> {target} ({kind})")
