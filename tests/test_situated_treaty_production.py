"""Complete production treaty programs, native tails and strict input identities."""

from __future__ import annotations

import copy
import re
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules, treaty_opportunities
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, decision_ir, pdx_eval

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def production():
    original = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    # Compile all source policies, retaining all competitors and source metadata.
    policies = tuple(
        (source, compiler.compile_policy(policy, source, model)[0])
        for source, policy in original.policies
    )
    assert len(policies) == len(original.policies)
    assert len(policies) >= 69
    compiled = replace(original, policies=policies)
    inputs = decision_adapters.read_inputs(original)
    country = country_state.load()
    files, _ = decision_adapters.build(
        compiled, texts=inputs, country_policy=country, consumer_ir=model.consumer_ir
    )
    disabled, _ = decision_adapters.build(
        compiled,
        texts=inputs,
        country_policy=country,
        consumer_ir=model.consumer_ir,
        enabled_domains=frozenset(),
    )
    baseline = treaty_opportunities.load_baseline()
    derived = treaty_opportunities.derive({"sources": {}, "readers": {}, "rules": []}, baseline)
    return original, compiled, model, inputs, files, disabled, derived


def _selection(production, article):
    _, adapters, _, _, files, _, derived = production
    row = next(row for row in derived["covered"] if row["id"] == article)
    source = row["source"]
    policy = dict(adapters.policies)[source]
    program = next(
        item for item in policy.consumer_programs if ".".join(item.field) == row["field"]
    )
    return row, policy, pdx_eval.marked_block(files[source], program.action_id)


def _facts(values, *, is_ai=True):
    root = {"is_ai": is_ai}
    for fact, engine in (
        ("treaty_influence", "influence"),
        ("war", "is_at_war"),
        ("default", "in_default"),
        ("is_diplomatic_play_target", "is_diplomatic_play_target"),
    ):
        if fact in values:
            root[engine] = values[fact]
    return {"ROOT": root}


def test_seven_actual_fields_have_complete_programs_and_strict_root_contexts(production):
    original, adapters, model, _, files, disabled, derived = production
    expected = {(row["source"], row["field"]) for row in derived["covered"]}
    assert len(expected) == 7
    assert {source for source, _ in adapters.policies} == {
        source for source, _ in original.policies
    }
    assert disabled == {}
    actual = {
        (source, ".".join(program.field))
        for source, policy in adapters.policies
        if source.startswith("common/treaty_articles/")
        for program in policy.consumer_programs
    }
    assert actual == expected
    assert not any("ship_transfer" in source for source in files)
    instances = [
        item for item in model.action_instances if item.source.startswith("common/treaty_articles/")
    ]
    assert len(instances) == 21
    assert {(item.source, item.consumer_field) for item in instances} == expected
    for item in instances:
        context = item.evaluation_context
        assert context is not None
        assert context.status == "observed"
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
            "root",
            "country",
            "actor",
        )
        assert context.targets == ()
        assert context.auxiliary_scopes == ()
        assert any("treaty-opportunities.json" in evidence for evidence in context.evidence)
    for row in derived["covered"]:
        source, policy = next(
            (source, policy) for source, policy in original.policies if source == row["source"]
        )
        compiled = dict(adapters.policies)[source]
        assert {rule.id for rule in policy.rules} == {rule.id for rule in compiled.rules}
        program = next(
            item for item in compiled.consumer_programs if ".".join(item.field) == row["field"]
        )
        assert {variant.action_id for variant in program.variants} == {
            rule.id for rule in policy.rules if ".".join(rule.field) == row["field"]
        }


@pytest.mark.parametrize(
    ("article", "values", "expected"),
    [
        ("alliance", {}, 1.0),
        ("alliance", {"is_diplomatic_play_target": True}, 1.15),
        ("alliance", {"is_diplomatic_play_target": True, "war": True}, 1.0),
        (
            "alliance",
            {
                "is_diplomatic_play_target": True,
                "war": True,
                "default": True,
                "treaty_influence": -1,
            },
            0.65,
        ),
        ("alliance", {"war": True, "default": True, "treaty_influence": -1}, 0.50),
        (
            "alliance",
            {
                "is_diplomatic_play_target": True,
                "war": None,
                "default": None,
                "treaty_influence": None,
            },
            1.15,
        ),
        ("alliance", {"is_diplomatic_play_target": None, "war": True}, 0.85),
        ("alliance", {"treaty_influence": 100}, 0.90),
        ("defensive_pact", {"treaty_influence": 100}, 1.0),
        ("defensive_pact", {"is_diplomatic_play_target": True, "default": True}, 1.0),
        (
            "guarantee_independence",
            {
                "is_diplomatic_play_target": True,
                "war": True,
                "default": True,
                "treaty_influence": 50,
            },
            0.85,
        ),
        ("guarantee_independence", {"treaty_influence": 49}, 0.90),
        ("no_tolls", {"treaty_influence": 20}, 0.90),
        ("no_strait_closure", {"treaty_influence": -1}, 0.80),
        ("toll_exemption", {"treaty_influence": 20}, 1.0),
        (
            "strait_access",
            {
                "default": True,
                "war": True,
                "is_diplomatic_play_target": True,
                "treaty_influence": 10,
            },
            1.0,
        ),
    ],
)
def test_complete_production_program_matches_handwritten_tradeoffs(
    production, article, values, expected
):
    row, policy, overlay = _selection(production, article)
    # No rule/reader subsets: both reference and generated file came from all
    # production competitors in all native source policies.
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert reference.get(row["field"], ("native", 1.0))[1] == pytest.approx(expected)
    observations = _facts(values)
    actual = pdx_eval.select(overlay, observations)
    assert (actual.delta if actual.operation == "multiply" else 1.0) == pytest.approx(expected)
    observations["ROOT"].update(candidate_selected=True, treaty_signed=True, taking_loans=True)
    observations["scope:target_country"] = {"influence": -500, "in_default": True}
    observations["scope:source_country"] = {"is_at_war": True}
    assert pdx_eval.select(overlay, observations) == actual


@pytest.mark.parametrize(
    "article",
    [
        "alliance",
        "defensive_pact",
        "guarantee_independence",
        "toll_exemption",
        "no_tolls",
        "strait_access",
        "no_strait_closure",
    ],
)
def test_actual_caller_player_foreign_and_unknown_paths_keep_native(production, article):
    _, policy, overlay = _selection(production, article)
    values = {
        "is_diplomatic_play_target": True,
        "treaty_influence": -1,
        "default": True,
        "war": True,
    }
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert pdx_eval.select(overlay, _facts(values, is_ai=False)).operation is None
    unknown = pdx_eval.select(
        overlay, {"ROOT": {"is_ai": True}, "other_country": _facts(values)["ROOT"]}
    )
    assert unknown.operation is None or unknown.delta == 1


def _tree(value):
    if isinstance(value, Scalar):
        return value.text, value.quoted
    if isinstance(value, Assignment):
        return value.key, value.op, value.prefix, _tree(value.value)
    assert isinstance(value, Block)
    return tuple(_tree(item) for item in value.items)


def test_real_native_qualification_cost_and_every_ordered_tail_are_unchanged(production):
    _, _, _, inputs, files, _, derived = production
    for source in {row["source"] for row in derived["covered"]}:
        restored = re.sub(
            r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
            "",
            files[source],
            flags=re.MULTILINE | re.DOTALL,
        )
        before, after = parse_text(inputs[source]), parse_text(restored)
        assert not before.errors
        assert not after.errors
        assert _tree(before.root) == _tree(after.root)
        assert files[source].count("# SITAI BEGIN information:") == 1


@pytest.mark.parametrize(("native_zero", "expected"), [(False, 1.76), (True, 0.0)])
def test_full_production_strait_grievance_and_final_native_zero_remain_ordered(
    production, native_zero, expected
):
    _, _, _, _, files, _, _ = production
    row, _, _ = _selection(production, "toll_exemption")
    definition = parse_text(files[row["source"]]).root.first("toll_exemption")
    assert definition is not None
    assert isinstance(definition.value, Block)
    ai = definition.value.first("ai")
    assert ai is not None
    assert isinstance(ai.value, Block)
    weight = ai.value.first("proposal_weight")
    assert weight is not None
    assert isinstance(weight.value, Block)
    cloned = copy.deepcopy(weight.value)
    assert [item.key for item in cloned.assignments()] == ["value", "add", "if", "if"]
    addition = cloned.items[1]
    assert isinstance(addition, Assignment)
    assert isinstance(addition.value, Block)
    formula = addition.value.items[0]
    assert isinstance(formula, Assignment)
    assert isinstance(formula.value, Scalar)
    assert formula.value.unquoted == "strait_toll_grievance_against(scope:source_country)"
    formula.value = Scalar("30")
    terminal = cloned.items[2]
    assert isinstance(terminal, Assignment)
    assert isinstance(terminal.value, Block)
    limit = terminal.value.first("limit")
    assert limit is not None
    # Supply outcomes for native formula/predicate calls outside this limited
    # interpreter; retain their actual numeric add, scale and terminal reset.
    limit.value = Block([Assignment("always", "=", Scalar("yes" if native_zero else "no"))])
    assert pdx_eval._numeric_value(
        Assignment("multiply", "=", cloned), _facts({"treaty_influence": -1})
    ) == pytest.approx(expected)


@pytest.mark.parametrize("mutation", ["alias", "cross_source", "operation"])
def test_production_compile_rejects_field_source_or_operation_aliases(production, mutation):
    original, _, model, _, _, _, _ = production
    source = "common/treaty_articles/00_alliance.txt"
    policy = dict(original.policies)[source]
    if mutation == "alias":
        policy = replace(
            policy,
            rules=(
                replace(policy.rules[0], field=("alliance", "ai", "proposal_weight_alias")),
                *policy.rules[1:],
            ),
        )
    elif mutation == "cross_source":
        source = "common/treaty_articles/01_defensive_pact.txt"
    else:
        policy = replace(
            policy, rules=(replace(policy.rules[0], operation="add"), *policy.rules[1:])
        )
    with pytest.raises(ValueError):
        compiler.compile_policy(policy, source, model)


@pytest.mark.parametrize("mutation", ["engine", "unit", "path", "minimum", "scope"])
def test_production_compiler_rejects_same_reader_name_with_changed_identity(production, mutation):
    original, _, model, _, _, _, _ = production
    source = "common/treaty_articles/00_alliance.txt"
    policy = dict(original.policies)[source]
    reader = next(reader for reader in policy.readers if reader.key == "treaty_influence")
    changes: dict[str, dict[str, Any]] = {
        "engine": {"engine": "bureaucracy"},
        "unit": {"unit": "currency"},
        "path": {"path": ("owner",)},
        "minimum": {"minimum": 0},
        "scope": {"scope": "target_country"},
    }
    broken = replace(reader, **changes[mutation])
    mutated = replace(
        policy, readers=tuple(broken if row.key == reader.key else row for row in policy.readers)
    )
    with pytest.raises(ValueError, match="reader"):
        compiler.compile_policy(mutated, source, model)


@pytest.mark.parametrize("mutation", ["target", "auxiliary", "actor_path"])
def test_observed_treaty_context_refuses_extra_objects_or_changed_actor(production, mutation):
    original, _, model, _, _, _, _ = production
    source = "common/treaty_articles/00_alliance.txt"
    policy = dict(original.policies)[source]
    instance = next(item for item in model.action_instances if item.source == source)
    context = instance.evaluation_context
    assert context is not None
    binding = decision_ir.ContextBinding(
        "target_country",
        "country",
        "target" if mutation == "target" else "auxiliary",
        "test-forbidden-extra-scope",
        1,
    )
    if mutation == "target":
        context = replace(
            context,
            targets=(binding,),
            evidence=(*context.evidence, "test-forbidden-extra-scope:1"),
        )
    elif mutation == "auxiliary":
        context = replace(
            context,
            auxiliary_scopes=(binding,),
            evidence=(*context.evidence, "test-forbidden-extra-scope:1"),
        )
    with pytest.raises(ValueError):
        compiler.validate_context_readers(
            "treaty.ai.proposal_weight",
            context,
            {reader.key: reader for reader in policy.readers},
            tuple(condition for rule in policy.rules for condition in rule.conditions),
            actor_path=("owner",) if mutation == "actor_path" else (),
        )
