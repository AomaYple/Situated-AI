"""One actual damaged state gains bounded relief without changing native gates."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render

from pdx import config, decision_adapters, decision_interfaces, decision_rules
from pdx import decree_opportunities as decree
from pdx.lexer import tokenize
from pdx.model import Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, domain_coverage, programs, vanilla_inventory
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[decree.SOURCE]
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(original, decree.SOURCE, model)
    selected = replace(
        adapters,
        policies=((decree.SOURCE, policy),),
        initial_values=(),
        scalar_values=(),
        supply=None,
        event_programs=(),
        acceptance_programs=(),
    )
    inputs = decision_adapters.read_inputs(selected)
    generated, report = decision_adapters.build(
        selected, texts=inputs, consumer_ir=model.consumer_ir
    )
    native = _block(_block(parse_text(inputs[decree.SOURCE]).root, decree.DEFINITION), "ai_weight")
    actual = _block(
        _block(parse_text(generated[decree.SOURCE]).root, decree.DEFINITION), "ai_weight"
    )
    return policy, inputs, generated[decree.SOURCE], actual, native, model, report


def _facts(
    *, devastation=0.3, default=False, authority=0, sol=15, expected=15, political=False, ai=True
):
    country = {
        "is_ai": ai,
        "in_default": default,
        "authority": authority,
        "has_strategy": {
            (("argument", "ai_strategy_nationalist_agenda"),): political,
            (("argument", "ai_strategy_reactionary_agenda"),): False,
        },
    }
    state = {
        "devastation": devastation,
        "average_sol": sol,
        "average_expected_sol": expected,
        "owner": country,
    }
    return {"ROOT": state, "scope:country": country}


def _weight(block, facts):
    initial = block.first("value")
    assert initial is not None
    assert initial.value.unquoted == "0"
    body = "\n".join(_render(row) for row in block.assignments() if row.key != "value")
    return _native_number(0, body, facts)


def _reference(policy, facts):
    state = facts["ROOT"]
    values = {
        decree.DEVASTATION: state["devastation"],
        decree.DEFAULT: state["owner"]["in_default"],
        decree.CAPACITY: state["owner"]["authority"],
    }
    observed = decision_rules.evaluate(policy, values, is_ai=state["owner"]["is_ai"])
    return observed.get(decree.FIELD, (None, 0))[1]


@pytest.mark.parametrize(
    ("changes", "delta", "total"),
    [
        ({}, 40, 40),
        ({"sol": 16}, 40, 40),
        ({"sol": 14}, 40, 140),
        ({"devastation": 0.2}, 0, 0),
        ({"devastation": 0.200001}, 40, 40),
        ({"devastation": 0}, 0, 0),
        ({"devastation": 1}, 40, 40),
        ({"devastation": None}, 0, 0),
        ({"devastation": None, "sol": 14, "default": True}, 0, 100),
        ({"default": True}, 30, 30),
        ({"default": None}, 30, 30),
        ({"authority": -0.00001}, 30, 30),
        ({"authority": None}, 30, 30),
        ({"default": True, "authority": -1}, 20, 20),
        ({"default": None, "authority": None}, 20, 20),
        ({"default": True, "authority": None, "sol": 14}, 20, 120),
        ({"political": True}, 40, 20),
        ({"political": True, "sol": 14}, 40, 70),
        ({"political": True, "default": True, "authority": -1}, 20, 10),
        ({"ai": False}, 0, 0),
        ({"ai": False, "sol": 14, "political": True}, 0, 50),
    ],
)
def test_hand_computed_native_sol_disaster_cost_unknown_and_tail(production, changes, delta, total):
    policy, _, text, actual, native, _, _ = production
    facts = _facts(**changes)
    assert _reference(policy, facts) == delta
    assert _native_number(0, _overlay(text, decree.FIELD), facts) == delta
    assert _weight(actual, facts) == total
    native_expected = (
        100.0 if facts["ROOT"]["average_sol"] < facts["ROOT"]["average_expected_sol"] else 0.0
    )
    if changes.get("political"):
        native_expected *= 0.5
    assert _weight(native, facts) == native_expected


def test_structural_nonnegative_bound_and_one_shared_program(production):
    policy = production[0]
    assert len(policy.consumer_programs) == 1
    program = policy.consumer_programs[0]
    assert (program.lower, program.upper, program.operation, program.neutral) == (0, 40, "add", 0)
    assert len(program.groups) == 3
    assert {row.action_id for row in program.variants} == set(decree.RULES)
    scalar = programs.rule_scalar(program)
    assert (scalar.lower, scalar.upper) == (0, 40)
    # Every possible truth combination is bounded, even before correlating
    # each pressure release with the same state's observed disaster.
    for bits in range(8):
        guards = {key: bool(bits & (1 << index)) for index, key in enumerate(decree.RULES)}
        assert 0 <= programs.evaluate_scalar(scalar, guards) <= 40


def test_real_owner_foreign_country_and_other_state_decoys_cannot_supply_facts(production):
    actual = production[3]
    facts = _facts(devastation=0, default=True, authority=-1)
    facts["ROOT"]["owner"]["owned_states"] = [{"devastation": 1}]
    facts["scope:target_state"] = {"devastation": 1}
    facts["scope:target_country"] = {"in_default": False, "authority": 9999}
    facts["decree_relief_devastation"] = 1
    assert _weight(actual, facts) == 0
    facts["ROOT"]["devastation"] = 0.3
    # Native scope:country belongs to the original political branch. New
    # financing/capacity observations must keep using physical state.owner.
    facts["scope:country"] = _facts()["scope:country"]
    assert _weight(actual, facts) == 20
    facts["ROOT"]["owner"]["in_default"] = False
    assert _weight(actual, facts) == 30


def test_recovery_new_disaster_and_normal_borrowing_recompute_without_memory(production):
    policy, _, _, actual, _, _, _ = production
    facts = _facts()
    facts["ROOT"]["owner"].update(is_borrowing=True, debt_ratio=0.1, bankruptcy_horizon=52)
    for devastation, default, authority, expected in (
        (0.3, False, 0, 40),
        (0.3, True, -1, 20),
        (0, True, -1, 0),
        (0.3, False, -1, 30),
        (0.3, False, 0, 40),
    ):
        facts["ROOT"]["devastation"] = devastation
        facts["ROOT"]["owner"].update(in_default=default, authority=authority)
        assert _weight(actual, facts) == expected == _reference(policy, facts)


def test_full_original_tokens_eligibility_effect_cost_and_order_preserved(production):
    policy, inputs, text, actual, native, _, _ = production
    original = inputs[decree.SOURCE]
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(restored)] == [
        (t.kind, t.value) for t in tokenize(original)
    ]
    before = _block(parse_text(original).root, decree.DEFINITION)
    after = _block(parse_text(text).root, decree.DEFINITION)
    for field in ("unlocking_technologies", "state_trigger", "modifier"):
        assert decree._shape(_block(before, field)) == decree._shape(_block(after, field))
    before_cost, after_cost = before.first("cost"), after.first("cost")
    assert before_cost is not None
    assert after_cost is not None
    assert isinstance(before_cost.value, Scalar)
    assert isinstance(after_cost.value, Scalar)
    assert before_cost.value.unquoted == after_cost.value.unquoted == "50"
    assert decree._shape(actual)[-1] == decree._shape(native)[-1]
    assert _overlay(text, decree.FIELD).index(decree.RULES[0]) >= 0
    assert (
        decision_rules.patch(
            original, policy, baseline=original, default_strategy=False, enabled_domains=frozenset()
        )
        == original
    )
    assert (
        decision_rules.evaluate(
            policy, {decree.DEVASTATION: 0.3}, is_ai=True, enabled_domains=frozenset()
        )
        == {}
    )


@pytest.mark.parametrize("source", sorted(decree.SOURCES))
def test_current_installation_and_complete_source_drift_hard_failure(source):
    inputs = decree.frozen_inputs()
    assert inputs[source] == normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
    frozen = json.loads(decree.FROZEN.read_text(encoding="utf-8"))
    assert (
        frozen["raw_source_hashes"][source]
        == hashlib.sha256((config.GAME / source).read_bytes()).hexdigest()
    )
    inputs[source] += "\n# unrelated source drift\n"
    with pytest.raises(ValueError, match="完整原版来源漂移"):
        decree.verify_inputs(inputs)


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (decree.SOURCE, "devastation > 0.2", "devastation >= 0.2"),
        (decree.SOURCE, "state_tax_collection_mult = -0.5", "state_tax_collection_mult = 0.5"),
        (decree.SOURCE, "\tcost = 50", "\tcost = 1"),
        (decree.SOURCE, "average_sol < average_expected_sol", "average_sol > average_expected_sol"),
        (decree.SOURCE, "multiply = 0.5", "multiply = 0"),
        (decree.FINANCE, "in_default = no", "in_default = yes"),
        (
            decree.AUTHORITY,
            "authority >= define:NPolitics|IG_BOLSTER_COST",
            "authority < define:NPolitics|IG_BOLSTER_COST",
        ),
    ],
)
def test_repin_cannot_silently_change_native_semantic_contract(monkeypatch, source, old, new):
    inputs = decree.frozen_inputs()
    assert old in inputs[source]
    inputs[source] = inputs[source].replace(old, new)
    data = deepcopy(decree.load())
    data["sources"][source] = hashlib.sha256(inputs[source].encode()).hexdigest()
    monkeypatch.setattr(decree, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        decree.verify_inputs(inputs)


def test_actual_compiler_ir_context_adapter_role_and_reader_contracts(
    production, monkeypatch, tmp_path
):
    policy, _, text, _, _, model, report = production
    assert report["decree_opportunities_sha256"]
    consumers = [row for row in model.production_consumers if row.source == decree.SOURCE]
    assert len(consumers) == 1
    assert (
        consumers[0].max_delta,
        consumers[0].scalar_lower,
        consumers[0].scalar_upper,
        consumers[0].scalar_neutral,
        consumers[0].numeric_policy,
    ) == (40, 0, 40, 0, "delta_to_native")
    assert policy.native_root == "state"
    assert policy.actor_path == ("owner",)
    catalog = decision_interfaces.consumer(
        tuple(decree.FIELD.split(".")), ("owner",), source=decree.SOURCE, native_root="state"
    )
    assert catalog["role"] == "vanilla_state_decree_relative_weight"
    assert catalog["writer_unit"] == "weight_delta"
    assert catalog["placement"] == "before_native_decree_political_multiply_tail"
    rows = [w for w in model.consumer_ir.writers if w.source == decree.SOURCE]
    assert {w.definition for w in rows} == set(decree.RULES)
    for row in rows:
        assert row.evaluation_context == decree.evaluation_context()
        assert row.evaluation_context.actor_scope.name == "owner"
        assert row.evaluation_context.auxiliary_scopes[0].kind == "state"
        assert all(
            binding[1:] in {("root", "state", "auxiliary"), ("owner", "country", "actor")}
            for binding in row.reader_context_bindings
        )
    assert all(rule in text for rule in decree.RULES)
    before = decree.derive({})
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    assert decree.derive({}) == before


@pytest.mark.parametrize(
    ("source", "field", "actor", "root"),
    [
        (decree.SOURCE, "decree_road_maintenance.ai_weight", ("owner",), "state"),
        ("common/decrees/other.txt", decree.FIELD, ("owner",), "state"),
        (decree.SOURCE, decree.FIELD, (), "country"),
        (decree.SOURCE, decree.FIELD, ("owner",), "military_formation"),
    ],
)
def test_exact_decree_authorization_does_not_admit_other_source_field_or_root(
    source, field, actor, root
):
    with pytest.raises(ValueError):
        decision_interfaces.consumer(
            tuple(field.split(".")), actor, source=source, native_root=root
        )


def test_reader_scope_or_identity_tampering_fails_before_lowering(production):
    policy = production[0]
    readers = {r.key: r for r in policy.readers}
    for key, malformed in (
        (decree.DEVASTATION, replace(readers[decree.DEVASTATION], path=("owner",))),
        (decree.DEFAULT, replace(readers[decree.DEFAULT], path=())),
        (decree.CAPACITY, replace(readers[decree.CAPACITY], path=())),
        (decree.CAPACITY, replace(readers[decree.CAPACITY], key="foreign_authority")),
    ):
        with pytest.raises(ValueError):
            compiler.validate_context_readers(
                decree.FIELD,
                decree.evaluation_context(),
                {**readers, key: malformed},
                (),
                actor_path=("owner",),
                input_keys=(key,),
                source=decree.SOURCE,
                native_root="state",
            )


@pytest.fixture(scope="module")
def independent_inventory():
    return vanilla_inventory.discover(game=config.GAME)


def test_independent_original_inventory_and_real_policy_proof_reject_context_tampering(
    production, independent_inventory
):
    policy, _, _, _, _, model, _ = production
    rows = [
        s
        for s in independent_inventory.surfaces
        if (s.source, s.definition, s.field) == (decree.SOURCE, decree.DEFINITION, "ai_weight")
    ]
    assert len(rows) == 1
    surface = rows[0]
    assert (surface.actor_scope, surface.operation, surface.capability, surface.legal) == (
        "state",
        "relative_weight",
        "direct",
        True,
    )
    assert all(
        not s.legal
        for s in independent_inventory.surfaces
        if s.source == decree.SOURCE
        and s.field == "ai_weight"
        and s.definition != decree.DEFINITION
    )
    sources = {s: (config.GAME / s).read_bytes() for s in decree.SOURCES}
    proofs = domain_coverage._NativeBindingProofs(
        independent_inventory, sources, {decree.SOURCE: policy}
    )
    instances = [i for i in model.action_instances if i.source == decree.SOURCE]
    assert len(instances) == 3
    for instance in instances:
        assert proofs.context_issue(instance, surface, state_owner_proven=False) is None
        for malformed in (
            replace(instance, actor_scope="root"),
            replace(instance, operation="multiply"),
            replace(instance, consumer_field="decree_road_maintenance.ai_weight"),
            replace(instance, evaluation_context=None),
            replace(instance, value=999),
        ):
            assert proofs.context_issue(malformed, surface, state_owner_proven=False) is not None
    bad_sources = dict(sources)
    bad_sources[decree.FINANCE] += b"\n# drift\n"
    with pytest.raises(ValueError, match="独立盘点字节不一致"):
        domain_coverage._NativeBindingProofs(
            independent_inventory, bad_sources, {decree.SOURCE: policy}
        )
