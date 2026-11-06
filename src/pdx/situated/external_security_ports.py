"""Bind exact existing external RuleSet consumers to the shared port compiler.

The caller supplies its frozen, reconciled exact consumer set and current
WriterDecisionIR objects. This module neither discovers sources nor invents
frames, relationship roles, runtime observations or scalar writer semantics.
Non-RuleSet acceptance/regional programs keep their existing native compiler.
"""

from __future__ import annotations

from dataclasses import replace

from . import consumer_ports, ports, programs


def bind(policies, *, selected_consumers, writers, hard_cap):
    """Return real bound policies and the measured finite shared graph batch.

    Every existing rule at a selected field participates, including independent
    costs and legacy unspecified roles. Exact role proof comes from the current
    writer, never from a country-shaped name or the reader's path alone.
    """
    selected = frozenset(selected_consumers)
    if not selected:
        raise ValueError("外部消费者精确集合不能为空")
    writer_rows = tuple(writers)
    index = {(w.source, w.definition): w for w in writer_rows if w.kind == "rule_action"}
    if len(index) != sum(w.kind == "rule_action" for w in writer_rows):
        raise ValueError("外部消费者writer身份重复")
    contexts, bindings = {}, {}
    proofs: dict[str | tuple[str, str], tuple[str, ...]] = {}
    for source, policy in policies:
        for rule in policy.rules:
            if (source, ".".join(rule.field)) not in selected:
                continue
            key = (source, rule.id)
            writer = index.get(key)
            if writer is None or writer.field != ".".join(rule.field):
                raise ValueError("外部消费者缺少精确现有writer")
            context = writer.evaluation_context
            if context is None or context.status != "observed":
                raise ValueError("外部消费者没有已证明frame")
            contexts[key] = context
            rows = tuple(writer.reader_context_bindings)
            required = rule.input_keys()
            if {r[0] for r in rows} != required:
                raise ValueError("外部消费者reader或参数对象闭包漂移")
            bindings[key] = rows
            for fact in required:
                proofs[(source, fact)] = tuple(context.evidence)
    batch = consumer_ports.derive(
        policies,
        selected_consumers=selected,
        contexts=contexts,
        reader_bindings=bindings,
        source_proofs=proofs,
        hard_cap=hard_cap,
    )
    result = []
    for source, policy in policies:
        replaced = {r.id for r in policy.rules if (source, ".".join(r.field)) in selected}
        attached = [b for b in policy.port_bindings if b.definition not in replaced]
        for rule in policy.rules:
            if rule.id not in replaced:
                continue
            graph = batch.writer_graph(source, rule.id)
            (use,) = graph.writer_uses(source, rule.id)
            attached.append(
                ports.PortBinding(
                    source,
                    rule.id,
                    use.port,
                    graph,
                    rule.required_known_facts,
                    use.role,
                    cost_predicates=rule.conditions if use.role == "cost" else (),
                    pressure_facts=rule.conservative_unknown_facts if use.role == "cost" else (),
                    unknown_cost_anchors=rule.unknown_cost_required_known_facts
                    if use.role == "cost"
                    else (),
                )
            )
        result.append(
            (source, programs.enable(replace(policy, port_bindings=tuple(attached)), source=source))
        )
    return tuple(result), batch
