"""A3 自主目标的需求、融资、陆军暴露和战败恢复共同参与真实消费者。"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import compiler

pytestmark = pytest.mark.integration
SOURCE = "common/ai_strategies/00_default_strategy.txt"
AUTONOMY = "ai_strategy_default.wargoal_scores.increase_autonomy"
INDEPENDENCE = "ai_strategy_default.wargoal_scores.independence"
FIELDS = (AUTONOMY, INDEPENDENCE)


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policy, _ = compiler.compile_policy(dict(adapters.policies)[SOURCE], SOURCE, model)
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        initial_values=tuple(row for row in adapters.initial_values if row.source == SOURCE),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == SOURCE),
    )
    native = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected,
        texts=native,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return policy, files[SOURCE], native[SOURCE], model


def _values(policy, changes):
    # All unrelated observations are unknown, not invented healthy defaults.
    values = dict.fromkeys(reader.key for reader in policy.readers)
    values.update(
        actor_is_target_subject=True,
        liberty=0,
        default=False,
        loans=False,
        debt_ratio=0.1,
        bankruptcy_horizon=52,
        own_army=10,
        target_army=10,
        war_defeat=False,
    )
    values.update(changes)
    return values


# Hand calculations use deviations from 1. Financing variants share one cause;
# independent security and recovery costs add once to the strongest need tier.
CASES = [
    ({}, 1, 1),
    ({"liberty": 75}, 1.10, 1.10),
    ({"liberty": 90}, 1.18, 1.18),
    ({"default": True}, 0.90, 0.80),
    ({"target_army": 11}, 0.95, 0.85),
    ({"war_defeat": True}, 0.95, 0.90),
    ({"loans": True, "debt_ratio": 0.8, "bankruptcy_horizon": 25.99}, 0.92, 0.85),
    ({"loans": True, "debt_ratio": 0.8, "bankruptcy_horizon": 26}, 1, 1),
    ({"loans": True, "debt_ratio": 0.3999, "bankruptcy_horizon": 1}, 1, 1),
    ({"liberty": 90, "loans": True}, 1.18, 1.18),
    ({"liberty": 90, "default": True}, 1.08, 0.98),
    ({"liberty": 90, "default": True, "war": True}, 1.08, 0.98),
    (
        {"liberty": 90, "default": True, "target_army": 20, "war_defeat": True},
        0.98,
        0.73,
    ),
    ({"default": True, "target_army": 20, "war_defeat": True}, 0.80, 0.55),
    (
        {"default": True, "loans": True, "debt_ratio": 0.8, "bankruptcy_horizon": 1},
        0.90,
        0.80,
    ),
    ({"liberty": None, "default": True, "war_defeat": True}, 0.85, 0.70),
    ({"liberty": 90, "own_army": None, "default": True}, 1.08, 0.98),
    ({"liberty": 90, "target_army": None, "war_defeat": True}, 1.13, 1.08),
    ({"actor_is_target_subject": False, "liberty": 100, "default": True}, 1, 1),
    ({"actor_is_target_subject": None, "liberty": 100, "default": True}, 1, 1),
]


@pytest.mark.parametrize(("changes", "autonomy", "independence"), CASES)
def test_hand_calculated_causes_match_reference_and_actual_pdx(
    production, changes, autonomy, independence
):
    policy, generated, _native, _model = production
    values = _values(policy, changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    facts = _facts(policy, values)
    for field, expected in zip(FIELDS, (autonomy, independence), strict=True):
        assert reference.get(field, ("native", 1))[1] == pytest.approx(expected)
        assert _native_number(1, _overlay(generated, field), facts) == pytest.approx(expected)


def test_exact_army_and_identity_readers_cannot_borrow_foreign_decoys(production):
    policy, generated, _native, _model = production
    readers = {reader.key: reader for reader in policy.readers}
    assert (readers["own_army"].engine, readers["own_army"].scope) == ("army_size", "root")
    assert (readers["target_army"].engine, readers["target_army"].scope) == (
        "army_size",
        "target_country",
    )
    assert readers["own_army"].unit == readers["target_army"].unit == "battalions"
    identity = readers["actor_is_target_subject"]
    assert (identity.engine, identity.scope, identity.argument) == (
        "is_subject_of",
        "root",
        "scope:target_country",
    )
    decision_interfaces.validate(policy)
    facts = _facts(policy, _values(policy, {"liberty": 90, "target_army": None}))
    facts["scope:overlord"] = {"army_size": 1000}
    facts["other_country"] = {"army_size": 1000}
    for field in FIELDS:
        assert _native_number(1, _overlay(generated, field), facts) == pytest.approx(1.18)
    facts["scope:target_country"]["army_size"] = 20
    assert _native_number(1, _overlay(generated, AUTONOMY), facts) == pytest.approx(1.13)
    assert _native_number(1, _overlay(generated, INDEPENDENCE), facts) == pytest.approx(1.03)
    # Reversing the actual relationship is not the same action evaluation.
    facts["ROOT"]["is_subject_of"] = {(("argument", "scope:target_country"),): False}
    facts["scope:target_country"]["is_subject_of"] = {(("argument", "root"),): True}
    for field in FIELDS:
        assert _native_number(1, _overlay(generated, field), facts) == 1


def test_native_base_and_special_zero_survive_complete_ordered_ast(production):
    policy, generated, native, _model = production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    original_root, retained_root = parse_text(native), parse_text(stripped)
    assert not original_root.errors
    assert not retained_root.errors
    original = _block(_block(original_root.root, "ai_strategy_default"), "wargoal_scores")
    retained = _block(_block(retained_root.root, "ai_strategy_default"), "wargoal_scores")
    for field in FIELDS:
        key = field.split(".")[-1]
        assert _render(_block(original, key)) == _render(_block(retained, key))
        base = _block(original, key).first("value")
        assert base is not None
        assert _render(base) == "value = 100"
        values = _values(policy, {"liberty": 90, "default": True, "target_army": 20})
        expected = 103 if field == AUTONOMY else 83
        assert _native_number(100, _overlay(generated, field), _facts(policy, values)) == (
            pytest.approx(expected)
        )
    independence = _block(original, "independence")
    for branch in independence.all("if")[:2]:
        # Execute the original terminal operation once its original country
        # predicate matched. The full untouched predicate is proved above.
        assert isinstance(branch.value, Block)
        terminal = _block(branch.value, "limit")
        assert "c:BIC" in _render(terminal) or "c:DEI" in _render(terminal)
        zero = branch.value.first("multiply")
        assert zero is not None
        assert _render(zero) == "multiply = 0.0"
        for changes in ({"liberty": 90}, {"default": True, "war_defeat": True}):
            facts = _facts(policy, _values(policy, changes))
            body = _render(zero) + "\n" + _overlay(generated, INDEPENDENCE)
            assert _native_number(100, body, facts) == 0


def test_players_disabled_and_absent_core_scope_keep_native(production):
    policy, generated, native, model = production
    values = _values(
        policy, {"liberty": 90, "default": True, "target_army": 20, "war_defeat": True}
    )
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    for field in FIELDS:
        overlay = _overlay(generated, field)
        assert _native_number(100, overlay, _facts(policy, values, is_ai=False)) == 100
        assert _native_number(100, overlay, {"ROOT": {"is_ai": True}}) == 100
    disabled = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        enabled_domains=frozenset(),
        reader_words=decision_interfaces.proven_reader_words(),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=SOURCE,
    )
    assert disabled == native
