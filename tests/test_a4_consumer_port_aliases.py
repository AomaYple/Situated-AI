"""Complete original identity pooling and executable alias counterexamples."""

from dataclasses import replace

import pytest

from pdx import decision_rules as rules
from pdx.situated import consumer_ports as cp
from pdx.situated import decision_ir as di
from pdx.situated import ports, programs

SOURCE = "common/laws/01_education_system.txt"


def build(*, rhs=False, cost=False, proof=False, role=False):
    a = rules.Reader("a", "test_number", "root", "points", "number")
    b = replace(a, key="b")
    readers = [a, b]
    if rhs:
        c = replace(a, key="c", engine="test_cap")
        d = replace(c, key="d")
        readers += [c, d]
    rs = []
    for i, key in enumerate(("a", "b")):
        right = rules.FactReference(("c", "d")[i], readers[i + 2].reference()) if rhs else 5
        rs.append(
            rules.Rule(
                f"rule_{key}",
                "education",
                ("law_test", "ai_enact_weight_modifier"),
                i,
                0.9 if cost else 1.1,
                (rules.Predicate(key, ">", right),),
                "test",
                "test",
                contribution_group=f"cause_{key}",
                semantic_role="cost" if cost else "unspecified",
                conservative_unknown_facts=(key,) if cost else (),
            )
        )
    policy = rules.RuleSet(tuple(readers), tuple(rs), "1" * 64, "2" * 64, frozenset({"education"}))
    actor = di.ContextBinding(
        "owner" if role else "root", "country", "actor", "fixture/context.txt", 1
    )
    alternate_actor = (
        di.ContextBinding("root", "state", "actor", "fixture/context.txt", 1) if role else actor
    )
    aux = di.ContextBinding("owner", "country", "auxiliary", "fixture/context.txt", 1)
    contexts = {
        (SOURCE, r.id): di.EvaluationContext(
            alternate_actor if role and r.id == "rule_b" else actor,
            auxiliary_scopes=(aux,) if role and r.id == "rule_b" else (),
            evidence=("fixture/context.txt:1",),
        )
        for r in rs
    }
    bindings = {
        (SOURCE, r.id): tuple(
            (
                k,
                "owner" if role else "root",
                "country",
                "auxiliary" if role and r.id == "rule_b" else "actor",
            )
            for k in r.input_keys()
        )
        for r in rs
    }
    proofs: dict[str | tuple[str, str], tuple[str, ...]] = {SOURCE: ("fixture/getter.txt:1",)}
    if proof:
        proofs[(SOURCE, "b")] = ("fixture/other-getter.txt:1",)
    batch = cp.derive(
        ((SOURCE, policy),),
        selected_consumers={(SOURCE, ".".join(rs[0].field))},
        contexts=contexts,
        reader_bindings=bindings,
        source_proofs=proofs,
        hard_cap={"ports": 8, "origins": 8, "uses": 2, "partitions": 1},
    )
    graph = batch.writer_graph(SOURCE, "rule_b")
    port_bindings = tuple(
        ports.PortBinding(
            SOURCE,
            r.id,
            graph.writer_uses(SOURCE, r.id)[0].port,
            graph,
            role="cost" if cost else "condition",
            cost_predicates=r.conditions if cost else (),
            pressure_facts=r.conservative_unknown_facts,
        )
        for r in rs
    )
    for r, binding in zip(rs, port_bindings, strict=True):
        binding.validate(r, {r.key: r for r in readers})
    return policy, batch, port_bindings


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"b": 6}, True),
        ({"b": None}, False),
        ({"a": 6, "b": 6}, True),
        ({"a": None, "b": None}, False),
    ],
)
def test_alias_values_keep_unknown(values, expected):
    policy, batch, bindings = build()
    assert len(batch.origin_pool) == batch.ports_count == 1
    assert bindings[1].evaluate(values, {r.key: r for r in policy.readers}) is expected
    assert len(bindings[1].graph.origins(bindings[1].port)) == 1


@pytest.mark.parametrize("values", [{"a": 6, "b": None}, {"a": None, "b": 6}, {"a": 6, "b": 7}])
def test_conflicting_aliases_rejected(values):
    policy, _batch, bindings = build()
    with pytest.raises(ValueError, match="别名值冲突"):
        bindings[1].evaluate(values, {r.key: r for r in policy.readers})


@pytest.mark.parametrize("change", ["proof", "role"])
def test_distinct_complete_identity_is_not_pooled(change):
    policy, batch, bindings = build(**{change: True})
    assert len(batch.origin_pool) == batch.ports_count == 2
    assert bindings[0].port != bindings[1].port
    assert bindings[0].evaluate({"a": 6, "b": None}, {r.key: r for r in policy.readers})
    assert not bindings[1].evaluate({"a": 6, "b": None}, {r.key: r for r in policy.readers})


def test_typed_rhs_alias_and_conflict():
    policy, batch, bindings = build(rhs=True)
    readers = {r.key: r for r in policy.readers}
    assert len(batch.origin_pool) == 2
    assert batch.ports_count == 1
    assert bindings[1].evaluate({"b": 6, "d": 5}, readers)
    assert not bindings[1].evaluate({"b": 6, "d": None}, readers)
    with pytest.raises(ValueError, match="别名值冲突"):
        bindings[1].evaluate({"b": 6, "c": 5, "d": None}, readers)


def test_cost_guard_uses_real_alias_pressure_and_unknown():
    policy, _batch, bindings = build(cost=True)
    readers = {r.key: r for r in policy.readers}
    assert bindings[1].cost_values({"b": 4}, readers) == (True, True)
    assert bindings[1].cost_values({"b": None}, readers) == (True, False)
    assert "NOT = { test_number > 5 }" in bindings[1].cost_guard()
    assert " a " not in bindings[1].cost_guard()
    assert " b " not in bindings[1].cost_guard()
    with pytest.raises(ValueError, match="别名值冲突"):
        bindings[1].cost_values({"a": 4, "b": None}, readers)


def test_plain_cost_preserves_known_guard_and_local_unknown():
    policy, _batch, bindings = build(cost=True)
    policy = replace(
        policy, rules=tuple(replace(r, conservative_unknown_facts=()) for r in policy.rules)
    )
    bindings = tuple(replace(b, pressure_facts=()) for b in bindings)
    policy = programs.enable(replace(policy, port_bindings=bindings), source=SOURCE)
    assert rules.evaluate_ir(policy, {"a": 6, "b": 6}, is_ai=True)[
        "law_test.ai_enact_weight_modifier"
    ][1] == pytest.approx(0.8)
    assert rules.evaluate_ir(policy, {"a": None, "b": None}, is_ai=True) == {}
    assert all(b.role == "cost" for b in policy.port_bindings)


def army_comparison(*, unit="battalions", target_role="target"):
    own = rules.Reader("own_army", "army_size", "root", "battalions", "number", minimum=0)
    target = replace(own, key="target_army", scope="target_country", unit=unit)
    rule = rules.Rule(
        "conquer_state_security",
        "security",
        ("conquer_state", "value"),
        1,
        3,
        (rules.Predicate("target_army", "<", rules.FactReference("own_army", own.reference())),),
        "test",
        "test",
    )
    policy = rules.RuleSet((own, target), (rule,), "1" * 64, "2" * 64, frozenset({"security"}))
    actor = di.ContextBinding("root", "country", "actor", "fixture/native-army.txt", 1)
    target_binding = di.ContextBinding(
        "target_country", "country", target_role, "fixture/native-army.txt", 2
    )
    context = di.EvaluationContext(
        actor,
        targets=(target_binding,),
        evidence=("fixture/native-army.txt:1", "fixture/native-army.txt:2"),
    )
    batch = cp.derive(
        ((SOURCE, policy),),
        selected_consumers={(SOURCE, "conquer_state.value")},
        contexts={(SOURCE, rule.id): context},
        reader_bindings={
            (SOURCE, rule.id): (
                ("own_army", "root", "country", "actor"),
                ("target_army", "target_country", "country", target_role),
            )
        },
        source_proofs={SOURCE: ("fixture/exact-army-proof",)},
        hard_cap={"ports": 1, "origins": 2, "uses": 1, "partitions": 1},
    )
    graph = batch.writer_graph(SOURCE, rule.id)
    return policy, graph, graph.writer_uses(SOURCE, rule.id)[0].port


@pytest.mark.parametrize(
    ("own", "target", "expected"),
    [(10, 5, True), (5, 10, False), (10, 10, False), (None, 5, None), (10, None, None)],
)
def test_exact_existing_army_comparison_preserves_each_object(own, target, expected):
    policy, graph, pid = army_comparison()
    assert (
        graph.evaluate(pid, {(SOURCE, "own_army"): own, (SOURCE, "target_army"): target})
        is expected
    )
    assert {(o.entity, o.observation.roles) for o in graph.origins(pid)} == {
        ("root", ("actor",)),
        ("target_country", ("target",)),
    }
    graph.assert_predicates(pid, policy.rules[0].conditions, {r.key: r for r in policy.readers})
    from pdx.parser import parse_text
    from pdx.situated import pdx_eval

    assert (
        pdx_eval.condition(
            parse_text(graph.guard(SOURCE, "conquer_state_security", pid).when_true).root,
            {
                "ROOT": {"army_size": own},
                "scope:target_country": {"army_size": target},
                "scope:enemy_country": {"army_size": 999},
            },
        )
        is expected
    )


@pytest.mark.parametrize("changes", [{"unit": "ships"}, {"target_role": "auxiliary"}])
def test_cross_object_army_unit_or_role_substitution_rejected(changes):
    with pytest.raises(ValueError):
        army_comparison(**changes)
