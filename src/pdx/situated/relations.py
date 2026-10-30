"""有限关系图：关系深度和循环在生成期硬失败。"""

from __future__ import annotations

from collections import defaultdict
from typing import cast

from .schema import ActionCard, Relation, RelationKind


def relations(actions: tuple[ActionCard, ...]) -> tuple[Relation, ...]:
    action_ids = {item.id for item in actions}
    result: list[Relation] = []
    for action in actions:
        for kind, targets in (
            ("complements", action.complements),
            ("substitutes", action.substitutes),
            ("conflicts", action.conflicts),
            ("enables", ()),
        ):
            for target in targets:
                if target not in action_ids:
                    raise ValueError(f"关系目标不存在：{action.id} -> {target}")
                result.append(Relation(action.id, target, cast("RelationKind", kind), 1.0))
    return tuple(result)


def validate(actions: tuple[ActionCard, ...], *, max_depth: int = 2) -> None:
    graph: dict[str, set[str]] = defaultdict(set)
    for relation in relations(actions):
        graph[relation.source].add(relation.target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str, depth: int) -> None:
        if depth > max_depth:
            raise ValueError(f"行动关系深度超过 {max_depth}：{node}")
        if node in visiting:
            raise ValueError(f"行动关系存在循环：{node}")
        if node in visited:
            return
        visiting.add(node)
        for child in sorted(graph[node]):
            walk(child, depth + 1)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        walk(node, 0)
