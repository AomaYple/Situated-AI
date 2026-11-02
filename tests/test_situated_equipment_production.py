"""Exact native ship choices pass through the shared production compiler."""

import re
from dataclasses import replace

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/ship_modifications/01_utility_modifications.txt"
FIELD = ("utility_mod_patrol_boats", "ai_weight")


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policies = tuple(
        (source, compiler.compile_policy(policy, source, model)[0])
        for source, policy in adapters.policies
        if source.startswith("common/ship_modifications/")
    )
    selected = replace(
        adapters, policies=policies, supply=None, initial_values=(), scalar_values=()
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return selected, inputs, files, model


def _tree(value):
    if isinstance(value, Scalar):
        return (value.text, value.quoted)
    if isinstance(value, Assignment):
        return (value.key, value.op, value.prefix, _tree(value.value))
    assert isinstance(value, Block)
    return tuple(_tree(item) for item in value.items)


def test_every_native_explicit_weight_has_exact_candidate_context_and_one_program(production):
    adapters, inputs, _, model = production
    native = {
        (source, definition.key, "ai_weight")
        for source, _ in adapters.policies
        for definition in parse_text(inputs[source]).top_assignments
        if isinstance(definition.value, Block) and definition.value.all("ai_weight")
    }
    actual = {
        (source, *program.field)
        for source, policy in adapters.policies
        for program in policy.consumer_programs
    }
    assert actual == native
    assert len(actual) == 263
    instances = [
        item
        for item in model.action_instances
        if item.source.startswith("common/ship_modifications/")
    ]
    assert instances
    for item in instances:
        context = item.evaluation_context
        assert context is not None
        assert context.status == "observed"
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind) == ("root", "country")
        assert {(scope.name, scope.kind, scope.role) for scope in context.targets} == {
            ("ship_modification_type", "ship_modification", "candidate")
        }


@pytest.mark.parametrize(
    ("price", "balance", "default", "expected"),
    [
        (-0.2, 10, False, 1.08),
        (-0.2, 10, True, 0.93),
        (0.6, -1, False, 0.80),
        (0.6, -1, True, 0.65),
        (None, -1, False, 0.90),
        (None, None, True, 0.85),
        (None, None, None, 1.0),
        (-0.2, 0, False, 1.08),
        (0, 0, False, 1.0),
    ],
)
def test_complete_ship_program_materials_and_default_are_joint_and_local(
    production, price, balance, default, expected
):
    adapters, _, files, _ = production
    policy = dict(adapters.policies)[SOURCE]
    values = {
        "country_goods_wood_price": price,
        "country_goods_wood_balance": balance,
        "default": default,
    }
    facts = {
        "ROOT": {
            "is_ai": True,
            "in_default": default,
            "market": {"mg:wood": {"market_goods_pricier": price, "market_goods_delta": balance}},
        }
    }
    program = next(item for item in policy.consumer_programs if item.field == FIELD)
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert reference.get(".".join(FIELD), ("", 1))[1] == pytest.approx(expected)
    actual = pdx_eval.select(pdx_eval.marked_block(files[SOURCE], program.action_id), facts)
    assert actual.delta == pytest.approx(expected)


def test_other_material_candidate_player_and_disabled_paths_remain_independent(production):
    adapters, inputs, files, _ = production
    policy = dict(adapters.policies)[SOURCE]
    values = {"country_goods_wood_price": -0.2, "country_goods_wood_balance": 10, "default": False}
    result = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert result[".".join(FIELD)][1] == pytest.approx(1.08)
    assert "utility_mod_extended_sick_bay.ai_weight" not in result
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    program = next(item for item in policy.consumer_programs if item.field == FIELD)
    assert (
        pdx_eval.select(
            pdx_eval.marked_block(files[SOURCE], program.action_id), {"ROOT": {"is_ai": False}}
        ).operation
        is None
    )
    disabled, _ = decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())
    assert disabled == {}


def test_original_doctrine_market_helpers_qualification_and_cost_ast_are_unchanged(production):
    _, inputs, files, _ = production
    for source, output in files.items():
        # Delete only the explicitly delimited new program. Compare the whole
        # remaining AST, including original helper order, zero branches, every
        # eligibility block, and actual construction/materiel quantities.
        restored = re.sub(
            r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
            "",
            output,
            flags=re.MULTILINE | re.DOTALL,
        )
        before, after = parse_text(inputs[source]), parse_text(restored)
        assert not before.errors
        assert not after.errors
        assert _tree(after.root) == _tree(before.root)
