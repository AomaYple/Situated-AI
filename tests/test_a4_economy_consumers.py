"""Actual economy consumers with literal causal deltas and native AST protection."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_situated_joint_witnesses import _facts
from test_technology_opportunities import _building_object, _native_country_case

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

GOV = "common/buildings/07_government.txt"
MINES = "common/buildings/03_mines.txt"
TECH = "common/technology/technologies/30_society.txt"
FIELDS = {
    GOV: {("building_university", "ai_value")},
    MINES: {("building_copper_mine", "ai_value")},
    TECH: {("dialectics", "ai_weight")},
}


@pytest.fixture(scope="module")
def generated():
    model = compiler.load_model()
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    words = (
        frozenset(decision_adapters.reader_evidence(inputs))
        | decision_interfaces.proven_reader_words()
    )
    policies = {}
    texts = {}
    for source, original in adapters.policies:
        if source not in FIELDS:
            continue
        rules = tuple(r for r in original.rules if r.field in FIELDS[source])
        keys = {key for rule in rules for key in rule.input_keys()}
        selected = replace(
            original,
            rules=rules,
            readers=tuple(r for r in original.readers if r.key in keys),
            enabled_domains=frozenset(r.domain for r in rules),
        )
        policy, _ = compiler.compile_policy(selected, source, model)
        native = inputs[source]
        if source == MINES:
            native = decision_adapters._initialize(
                native,
                [
                    r
                    for r in adapters.initial_values
                    if r.source == source and r.field in FIELDS[source]
                ],
                inputs,
                {},
            )
        texts[source] = decision_rules.patch(
            native,
            policy,
            baseline=inputs[source],
            reader_words=words,
            country_policy=country_state.load(),
            consumer_ir=model.consumer_ir,
            consumer_source=source,
            default_strategy=False,
        )
        policies[source] = policy
    return model, policies, texts, inputs


def assert_value(generated, source, field, values, expected, base, native_world=None):
    _model, policies, texts, _inputs = generated
    policy = policies[source]
    observed = decision_rules.evaluate_ir(policy, values, is_ai=True).get(".".join(field), ("", 1))[
        1
    ]
    assert observed == pytest.approx(expected)
    root = parse_text(texts[source]).root
    parent = root.first(field[0])
    assert parent is not None
    assert isinstance(parent.value, Block)
    block = parent.value.first(field[1])
    assert block is not None
    ai_facts = _facts(policy, values)
    player_facts = _facts(policy, values, is_ai=False)
    if source == GOV:
        # The native field executes in the candidate state's current scope;
        # the generated overlay retains the same explicit ROOT state.
        ai_facts = {**ai_facts["ROOT"], **ai_facts}
        player_facts = {**player_facts["ROOT"], **player_facts}
    if native_world is not None:
        ai_facts["ROOT"] = {
            **native_world,
            **{
                k: v
                for k, v in ai_facts["ROOT"].items()
                if k not in {"any_scope_building", "any_scope_state", "market"}
            },
        }
        player_facts["ROOT"] = {**ai_facts["ROOT"], "is_ai": False}
    ai_value = pdx_eval._numeric_value(block, ai_facts)
    player_value = pdx_eval._numeric_value(block, player_facts)
    assert ai_value == pytest.approx(base * expected)
    assert player_value == pytest.approx(base)
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=frozenset()) == {}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.10),
        ({"state_owner_innovation": 100}, 1),
        ({"state_owner_innovation": None}, 1),
        ({"state_owner_innovation_cap": None}, 1),
        ({"state_owner_innovation_cap": -5, "state_owner_innovation": 0}, 1),
        ({"state_owner_literacy": 0.4}, 1.20),
        ({"state_owner_literacy": 0.4, "state_owner_academia_completed": True}, 1.25),
        ({"state_owner_default": True}, 0.95),
        (
            {
                "pm_active_building_university_pm_scholastic_education": True,
                "state_owner_paper_balance": -1,
                "state_owner_paper_price": 1,
            },
            0.9,
        ),
    ],
)
def test_university_independent_need_qualification_cost(generated, changes, expected):
    values = {
        "state_owner_innovation": 80,
        "state_owner_innovation_cap": 100,
        "state_owner_literacy": 0.8,
        "state_owner_default": False,
        "state_owner_academia_completed": False,
        "state_owner_paper_balance": 0,
        "state_owner_paper_price": 0,
        "pm_active_building_university_pm_scholastic_education": False,
        "pm_active_building_university_pm_philosophy_department": False,
        "pm_active_building_university_pm_analytical_philosophy_department": False,
    }
    values.update(changes)
    assert_value(generated, GOV, ("building_university", "ai_value"), values, expected, 2000)


@pytest.mark.parametrize(
    ("balance", "price", "expected"),
    [(-1, None, 1.08), (-1, 0.25, 1.08), (-1, 0.25001, 1.12), (0, 1, 1), (None, 1, 1)],
)
def test_copper_supply_tiers_and_unknown_without_repeated_native_cost(
    generated, balance, price, expected
):
    assert_value(
        generated,
        MINES,
        ("building_copper_mine", "ai_value"),
        {"state_owner_copper_balance": balance, "state_owner_copper_price": price},
        expected,
        1000,
    )
    policy = generated[1][MINES]
    assert {r.contribution_group for r in policy.rules} == {"copper_supply_need"}
    assert len(policy.rules) == 2


def test_normal_native_parents_only_receive_owned_insertions(generated):
    _model, _policies, texts, inputs = generated
    for source, text in texts.items():
        stripped = re.sub(
            r"\n[ \t]*# SITAI BEGIN information:[^\n]+\n.*?# SITAI END information:[^\n]+\n[ \t]*",
            "",
            text,
            flags=re.DOTALL,
        )
        # Removing owned blocks must preserve every native AST node. University
        # scalar wrapping and exact copper initializer are the only new AST forms.
        actual = parse_text(stripped).root
        native = parse_text(inputs[source]).root
        assert not parse_text(text).errors

        def shape(node):
            from pdx.model import Assignment, Block

            if isinstance(node, Assignment):
                return (node.key, node.op, node.prefix, shape(node.value))
            if isinstance(node, Block):
                return tuple(shape(i) for i in node.items)
            assert isinstance(node, Scalar)
            return (node.text, node.quoted)

        for original in native.items:
            assert isinstance(original, Assignment)
            if getattr(original, "key", None) not in {f[0] for f in FIELDS[source]}:
                assert shape(original) == shape(actual.first(original.key))
        for field in FIELDS[source]:
            old_parent, new_parent = native.first(field[0]), actual.first(field[0])
            assert old_parent is not None
            assert new_parent is not None
            before, after = old_parent.value, new_parent.value
            assert isinstance(before, Block)
            assert isinstance(after, Block)
            for item in before.items:
                assert isinstance(item, Assignment)
                if item.key != field[1]:
                    assert shape(item) == shape(after.first(item.key))


@pytest.mark.parametrize(
    ("innovation", "cap", "ready", "expected"),
    [
        (80, 100, False, 1.08),
        (80, 100, True, 1.12),
        (100, 100, True, 1),
        (None, 100, True, 1),
        (80, None, True, 1),
        (0, -5, True, 1),
    ],
)
def test_knowledge_use_exact_cap_gate_and_alternative_tiers(
    generated, innovation, cap, ready, expected
):
    policy = generated[1][TECH]
    values = {
        "innovation": innovation,
        "innovation_cap": cap,
        "technology_use_dialectics_knowledge": True,
        "technology_use_dialectics_knowledge_ready": ready,
        "schools_present": False,
        "schools_investment": 0,
    }
    world = _native_country_case("dialectics", "knowledge_ready")
    world["any_scope_building"] = [
        _building_object("building_university", "pm_scholastic_education")
    ]
    if not ready:
        world["market"]["mg:paper"]["market_goods_pricier"] = 0.26
    assert_value(
        generated, TECH, ("dialectics", "ai_weight"), values, expected, 1, native_world=world
    )
    actual_rules = [r for r in policy.rules if r.id.endswith(("_knowledge", "_knowledge_ready"))]
    assert len(actual_rules) == 2
    assert not any(p.fact == "literacy" for r in actual_rules for p in r.conditions)
