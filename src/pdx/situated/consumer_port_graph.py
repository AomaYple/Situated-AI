"""Indexed facade preserving the explicit graph and finite consumer partitions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from . import ports as port_types


@dataclass(frozen=True, slots=True)
class ConsumerPortGraph:
    ports: tuple[port_types.Port, ...]
    uses: tuple[port_types.PortUse, ...]
    explicit_uses: tuple[port_types.PortUse, ...]
    topological: tuple[str, ...]
    _nodes: Mapping[str, port_types.Port]
    _port_graph: Mapping[str, port_types.PortGraph]
    _writer_uses: Mapping[tuple[str, str], tuple[port_types.PortUse, ...]]
    _source_uses: Mapping[str, tuple[port_types.PortUse, ...]]
    _use_graph: Mapping[tuple[str, str, str], port_types.PortGraph]
    metrics: Mapping[str, int | bool]

    def __post_init__(self):
        if (
            self.metrics.get("explicit_uses") != len(self.explicit_uses)
            or self.uses[: len(self.explicit_uses)] != self.explicit_uses
        ):
            raise ValueError("combined显式消费者身份或顺序漂移")

    def node(self, port_id):
        return self._nodes[port_id]

    def writer_uses(self, source, definition):
        return self._writer_uses.get((source, definition), ())

    def source_uses(self, source):
        return self._source_uses.get(source, ())

    def leaves(self, port_id):
        return self._port_graph[port_id].leaves(port_id)

    def origins(self, port_id):
        return self._port_graph[port_id].origins(port_id)

    def expanded_leaves(self, port_id):
        return self._port_graph[port_id].expanded_leaves(port_id)

    def validate_origins(self, port_id):
        return self._port_graph[port_id].validate_origins(port_id)

    def assert_predicates(self, port_id, predicates, readers, *, mode="all"):
        return self._port_graph[port_id].assert_predicates(port_id, predicates, readers, mode=mode)

    def evaluate(self, port_id, values, *, predicate_values=None):
        return self._port_graph[port_id].evaluate(
            port_id, values, predicate_values=predicate_values
        )

    def guard(self, source, definition, port_id):
        key = (source, definition, port_id)
        if key not in self._use_graph:
            raise ValueError("端口未声明精确writer使用")
        return self._use_graph[key].guard(source, definition, port_id)

    def _render_guard(self, port_id):
        return self._port_graph[port_id]._render_guard(port_id)

    def contract(self):
        return {
            "schema": 2,
            "kind": "explicit_graph_and_finite_consumer_partitions",
            "metrics": dict(self.metrics),
            "ports": [node.id for node in self.ports],
            "uses": [
                {"source": u.source, "definition": u.definition, "port": u.port, "role": u.role}
                for u in self.uses
            ],
            "persistent_state": False,
            "unknown_detection": False,
        }


def combine(explicit, batch, *, rules_by_writer, readers_by_source, expected_global=None):
    """Retain existing explicit uses and replace equivalent generated duplicates.

    The explicit graph must already have passed its original declared limits.
    Partition construction separately checks its own actual finite total cap.
    The combined result measures real identity intersections and reachability.
    """
    graphs = (explicit, *(graph for key, graph in batch.partitions))
    explicit_guards = {
        (u.source, u.definition): u
        for u in explicit.uses
        if u.role in {"need", "capacity", "recovery", "cost"}
    }
    nodes: dict[str, port_types.Port] = {}
    port_graph: dict[str, port_types.PortGraph] = {}
    uses: list[port_types.PortUse] = []
    by_writer: dict[tuple[str, str], list[port_types.PortUse]] = {}
    by_source: dict[str, list[port_types.PortUse]] = {}
    use_graph: dict[tuple[str, str, str], port_types.PortGraph] = {}
    reached: set[str] = set()
    before_nodes: set[str] = set()
    skipped = 0
    for graph in graphs:
        before_nodes.update(node.id for node in graph.ports)
        for use in graph.uses:
            key = (use.source, use.definition)
            if graph is not explicit and key in explicit_guards:
                rule = rules_by_writer[key]
                readers = readers_by_source[use.source]
                existing = explicit_guards[key]
                explicit.assert_predicates(existing.port, rule.conditions, readers)
                graph.assert_predicates(use.port, rule.conditions, readers)
                if (existing.role == "cost") != (use.role == "cost"):
                    raise ValueError("显式消费者成本角色不能被降级")
                skipped += 1
                continue
            exact = (use.source, use.definition, use.port)
            if exact in use_graph:
                raise ValueError("combined精确writer use重复")
            use_graph[exact] = graph
            uses.append(use)
            by_writer.setdefault(key, []).append(use)
            by_source.setdefault(use.source, []).append(use)
            for pid in graph._index.closures[use.port]:
                node = graph.node(pid)
                if pid in nodes and nodes[pid] != node:
                    raise ValueError("combined端口ID冲突")
                nodes.setdefault(pid, node)
                port_graph.setdefault(pid, graph)
                reached.add(pid)
    # Stable combined topological order; reuse every actual partition's order.
    order = []
    ordered = set()
    for graph in graphs:
        for pid in graph.topological:
            if pid in reached and pid not in ordered:
                if any(dep not in ordered for dep in nodes[pid].dependencies):
                    raise ValueError("combined存在DAG悬边或顺序漂移")
                ordered.add(pid)
                order.append(pid)
    origins = {o.identity: o for pid in nodes for o in port_graph[pid].origins(pid)}
    explicit_origins = {o.identity for p in explicit.ports for o in explicit.origins(p.id)}
    batch_origins = {o.identity for o in batch.origin_pool}
    metrics = {
        "ports": len(nodes),
        "origins": len(origins),
        "uses": len(uses),
        "consumer_partitions": len(batch.partitions),
        "explicit_ports": len(explicit.ports),
        "explicit_uses": len(explicit.uses),
        "explicit_origins": len(explicit_origins),
        "batch_ports": batch.ports_count,
        "batch_origins": len(batch.origin_pool),
        "batch_uses": batch.uses_count,
        "shared_port_ids": len({p.id for p in explicit.ports} & set(batch.by_port)),
        "shared_origin_ids": len(explicit_origins & batch_origins),
        "replaced_equivalent_generated_uses": skipped,
        "removed_unreachable_after_duplicate_uses": len(before_nodes - reached),
        "dangling": 0,
        "unreachable": 0,
        "DAG": True,
    }
    if expected_global is not None and any(metrics[k] != v for k, v in expected_global.items()):
        raise ValueError(f"combined实际有限全集与冻结总量漂移: {metrics}")
    return ConsumerPortGraph(
        tuple(nodes[pid] for pid in order),
        tuple(uses),
        tuple(explicit.uses),
        tuple(order),
        MappingProxyType(nodes),
        MappingProxyType(port_graph),
        MappingProxyType({k: tuple(v) for k, v in by_writer.items()}),
        MappingProxyType({k: tuple(v) for k, v in by_source.items()}),
        MappingProxyType(use_graph),
        MappingProxyType(metrics),
    )
