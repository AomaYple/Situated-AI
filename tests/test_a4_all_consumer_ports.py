"""Normal compiler owns all observed RuleSet guards; finite relative object pairs."""

import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from pdx import decision_adapters, decision_rules
from pdx.decision_rules import FactReference, Predicate, Reader, Rule, RuleSet
from pdx.situated import compiler, consumer_ports, decision_ir

SOURCE = "common/ai_strategies/00_default_strategy.txt"


def relative_graph(engine, unit, field, role, *, source=SOURCE):
    own = Reader("own", engine, "root", unit, "number", minimum=0)
    target = replace(own, key="target", scope="target_country")
    rule = Rule(
        "relative",
        "economy",
        tuple(field.split(".")),
        1,
        1.1,
        (Predicate("target", "<", FactReference("own", own.reference())),),
        "test",
        "test",
    )
    policy = RuleSet((own, target), (rule,), "1" * 64, "2" * 64, frozenset({"economy"}))
    actor = decision_ir.ContextBinding("root", "country", "actor", "fixture/native.txt", 1)
    other = decision_ir.ContextBinding("target_country", "country", role, "fixture/native.txt", 2)
    context = decision_ir.EvaluationContext(
        actor,
        targets=(other,) if role == "target" else (),
        auxiliary_scopes=(other,) if role != "target" else (),
        evidence=("fixture/native.txt:1", "fixture/native.txt:2"),
    )
    batch = consumer_ports.derive(
        ((source, policy),),
        selected_consumers={(source, field)},
        contexts={(source, rule.id): context},
        reader_bindings={
            (source, rule.id): (
                ("own", "root", "country", "actor"),
                ("target", "target_country", "country", role),
            )
        },
        source_proofs={source: ("fixture/native-getters.txt:1",)},
        hard_cap={"ports": 1, "origins": 2, "uses": 1, "partitions": 1},
    )
    graph = batch.writer_graph(source, rule.id)
    return graph, graph.writer_uses(source, rule.id)[0].port


@pytest.mark.parametrize(
    ("engine", "unit", "field", "role"),
    [
        ("navy_size", "ships", "ai_strategy_default.treaty_port_value", "auxiliary"),
        ("navy_size", "ships", "ai_strategy_default.wargoal_scores.colonization_rights", "target"),
        ("gdp", "annual_gdp_currency", "ai_strategy_default.subject_value", "target"),
    ],
)
@pytest.mark.parametrize(
    ("own", "target", "expected"),
    [(10, 5, True), (5, 10, False), (10, 10, False), (None, 5, None), (10, None, None)],
)
def test_exact_existing_cross_object_getters(engine, unit, field, role, own, target, expected):
    graph, port = relative_graph(engine, unit, field, role)
    assert graph.evaluate(port, {(SOURCE, "own"): own, (SOURCE, "target"): target}) is expected
    assert {(o.entity, o.observation.roles) for o in graph.origins(port)} == {
        ("root", ("actor",)),
        ("target_country", (role,)),
    }


@pytest.mark.parametrize(
    ("engine", "unit", "field", "role", "source"),
    [
        ("navy_size", "ships", "ai_strategy_default.treaty_port_value", "target", SOURCE),
        ("navy_size", "ships", "ai_strategy_default.subject_value", "target", SOURCE),
        ("gdp", "ships", "ai_strategy_default.subject_value", "target", SOURCE),
        ("gdp", "annual_gdp_currency", "ai_strategy_default.subject_value", "auxiliary", SOURCE),
        (
            "gdp",
            "annual_gdp_currency",
            "ai_strategy_default.subject_value",
            "target",
            "fixture/other.txt",
        ),
    ],
)
def test_cross_object_getters_reject_unproved_field_source_unit_and_role(
    engine, unit, field, role, source
):
    with pytest.raises(ValueError, match="typed RHS"):
        relative_graph(engine, unit, field, role, source=source)


@pytest.mark.integration
def test_normal_compiler_attaches_executable_guards_to_all_observed_rulesets():
    model = compiler.load_model()
    policies = (
        ("mod/decisions/information.toml", decision_rules.load()),
        *decision_adapters.load().policies,
    )
    assert model.consumer_ir is not None
    writers = {(w.source, w.definition): w for w in model.consumer_ir.writers}
    selected = set(
        consumer_ports.selected_proven_consumers(
            tomllib.loads(
                (Path(compiler.DECISIONS) / "consumer_ports.toml").read_text(encoding="utf-8")
            )
        )
    )
    actual = set()
    count = 0
    for source, policy in policies:
        compiled, _contract = compiler.compile_policy(policy, source, model)
        bound = {b.definition: b for b in compiled.port_bindings}
        readers = {r.key: r for r in compiled.readers}
        for rule in compiled.rules:
            writer = writers[(source, rule.id)]
            if writer.evaluation_context is None or writer.evaluation_context.status != "observed":
                continue
            actual.add((source, ".".join(rule.field)))
            binding = bound[rule.id]
            binding.validate(rule, readers)
            assert binding.contribution in writer.port_contributions
            assert any(
                rule.id == variant.action_id
                for p in compiled.consumer_programs
                for variant in p.variants
            )
            count += 1
    assert actual == selected
    assert count == 6152
