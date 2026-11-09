"""有限关系图：关系深度和循环在生成期硬失败。"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING, cast

from .schema import ActionCard, Relation, RelationKind, UnknownPolicy

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .core_contracts import EvaluationSchedule, FactSpec, SituationSnapshot


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
        )
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
    orphaned = set(metadata) - {(item.source, item.target, item.kind) for item in result}
    if orphaned:
        raise ValueError(f"行动关系元数据未绑定行动卡：{sorted(orphaned)}")
    return tuple(result)


def condition_state(relation: Relation, values: Mapping[str, object]) -> bool | None:
    """读取关系自身的世界事实，缺失或非布尔值保持 unknown。"""

    if not relation.condition_facts:
        return True
    states = tuple(
        values.get(name) if type(values.get(name)) is bool else None
        for name in relation.condition_facts
    )
    if any(item is False for item in states):
        return False
    return None if any(item is None for item in states) else True


def observed_condition(
    relation: Relation,
    snapshot: SituationSnapshot,
    facts: tuple[FactSpec, ...],
    schedule: EvaluationSchedule,
) -> bool | None:
    """在合法对象和当前时点读取条件；不把候选资格当作完成证据。

    这是观察入口，不是第二份关系数值政策；未知时不假造低档强度或免费成本。
    当前 Relation 没有跨时点寿命字段，因此只允许当前快照，存档后重新观察。
    """
    if (
        relation.kind not in {"complements", "substitutes", "conflicts", "enables"}
        or relation.scope not in {"root", "target_state", "target_country"}
        or type(relation.strength) not in (int, float)
        or not math.isfinite(relation.strength)
        or relation.strength <= 0
        or relation.unknown_policy not in {"vanilla", "conservative", "lower_tier"}
        or len(set(relation.condition_facts)) != len(relation.condition_facts)
    ):
        raise ValueError("关系观察合同无效或缺少合法对象映射")
    snapshot.validate(facts, schedule)
    declared = {item.id: item for item in facts}
    for name in relation.condition_facts:
        spec = declared.get(name)
        if spec is None or spec.kind != "boolean" or snapshot.consumer_id not in spec.consumer_ids:
            raise ValueError(f"关系条件缺少已接线布尔事实：{name}")
        if relation.scope == "root" and spec.binding != "actor":
            raise ValueError(f"关系条件对象映射不一致：{name}")
        if relation.scope == "target_state" and (
            spec.binding != "target" or spec.entity_kind != "state"
        ):
            raise ValueError(f"关系条件对象映射不一致：{name}")
        if relation.scope == "target_country" and (
            spec.binding != "target" or spec.entity_kind != "country"
        ):
            raise ValueError(f"关系条件对象映射不一致：{name}")
        if relation.scope not in {"root", "target_state", "target_country"}:
            raise ValueError("关系 owner 映射缺少合法转换证明")
    if not relation.condition_facts:
        return None
    return condition_state(
        relation,
        {
            item.spec_id: item.value if item.usable_at(snapshot.time) else None
            for item in snapshot.observations
        },
    )


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
