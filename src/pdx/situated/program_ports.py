"""Typed predicate ports for existing scalar programs, never a second scorer.

Scalar groups/effects, role envelopes and native tails remain owned by the
original program. This bridge only lowers/evaluates its exact local predicates
through the same consumer_ports and PortGraph used by ordinary RuleSets.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from pdx.decision_rules import Rule, RuleSet

from . import consumer_ports, ports


@dataclass(frozen=True, slots=True)
class ProgramPorts:
    source: str
    definition: str
    graph: ports.PortGraph
    guards: tuple[tuple[str, str], ...]
    guard_roles: tuple[tuple[str, str], ...]

    def render(self):
        return {
            key: self.graph.guard(self.source, self.definition, pid).when_true
            for key, pid in self.guards
        }

    def evaluate(self, values):
        original = {(self.source, key): value for key, value in values.items()}
        return {key: self.graph.evaluate(pid, original) is True for key, pid in self.guards}

    def contributions(self, writer):
        by_port = {pid: dict(self.guard_roles)[key] for key, pid in self.guards}
        return tuple(
            replace(ports.contribution(writer, use, self.graph), semantic_role=by_port[use.port])
            for use in self.graph.writer_uses(self.source, self.definition)
        )

    def as_dict(self):
        return {
            "guards": dict(self.guards),
            "guard_roles": dict(self.guard_roles),
            "graph": self.graph.contract(),
        }


def bind(
    *,
    scalar,
    source,
    definition,
    context,
    readers,
    reader_bindings,
    predicates,
    guard_roles,
    source_sha256,
    source_proofs,
    domain,
):
    """Bind each existing scalar guard exactly once, with its actual cause.

    The intermediate Rule rows transport predicates only. Their values are never
    rendered or evaluated, and their temporary writer IDs do not enter ConsumerIR.
    """
    if set(guard_roles) != set(predicates) or any(
        not isinstance(role, str) or role not in {"cost", "benefit", "unspecified"}
        for role in guard_roles.values()
    ):
        raise ValueError("scalar每个guard必须有精确显式semantic role，不能从数值推断")
    guard_causes: dict[str, str] = {}
    for group in scalar.groups:
        for term in group.terms:
            for key in (term.id, *(effect.guard for effect in term.effects)):
                row = group.id
                if key in guard_causes and guard_causes[key] != row:
                    raise ValueError("scalar谓词被不等价因果组复用")
                guard_causes[key] = row
    if set(predicates) != set(guard_causes):
        raise ValueError("scalar实际guard与typed port谓词全集不一致")
    rules = tuple(
        Rule(
            key,
            domain,
            tuple(source_field.split(".")),
            index,
            scalar.neutral,
            tuple(rows),
            "existing scalar predicate",
            "retain original scalar/native tail",
            operation=scalar.operation,
            contribution_group=guard_causes[key],
        )
        for index, (key, rows) in enumerate(predicates.items())
        for source_field in (definition,)
    )
    policy = RuleSet(tuple(readers), rules, source_sha256, source_sha256, frozenset({domain}))
    contexts = {(source, rule.id): context for rule in rules}
    bindings = {
        (source, rule.id): tuple(row for row in reader_bindings if row[0] in rule.input_keys())
        for rule in rules
    }
    batch = consumer_ports.derive(
        ((source, policy),),
        selected_consumers={(source, definition)},
        contexts=contexts,
        reader_bindings=bindings,
        source_proofs={source: tuple(source_proofs)},
        hard_cap={"ports": 128, "origins": 64, "uses": 32, "partitions": 1},
    )
    ((_, graph),) = batch.partitions
    roots = tuple((use.definition, use.port) for use in graph.uses)
    by_port: dict[str, str] = {}
    for guard, pid in roots:
        role = guard_roles[guard]
        if pid in by_port and by_port[pid] != role:
            raise ValueError("相同scalar端口不能携带冲突semantic role")
        by_port[pid] = role
    graph = replace(
        graph,
        uses=tuple(
            replace(
                use,
                definition=definition,
                role="condition",
                relation_cause=guard_causes[use.definition],
            )
            for use in graph.uses
        ),
    )
    return ProgramPorts(source, definition, graph, roots, tuple(guard_roles.items()))
