"""Independent score arithmetic and native trigger protection for cooperation."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import cooperation_opportunities as cooperation
from pdx import country_state, decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policy, _ = compiler.compile_policy(
        dict(adapters.policies)[cooperation.SOURCE], cooperation.SOURCE, model
    )
    selected = replace(
        adapters,
        policies=((cooperation.SOURCE, policy),),
        supply=None,
        initial_values=tuple(
            row for row in adapters.initial_values if row.source == cooperation.SOURCE
        ),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == cooperation.SOURCE),
    )
    inputs = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policy, files[cooperation.SOURCE], inputs


CASES = [
    ({}, 0, 0),
    ({"default": True}, 8, -8),
    ({"loans": True}, 0, 0),
    ({"loans": True, "debt_ratio": 0.5, "bankruptcy_horizon": 25}, 5, -5),
    ({"loans": True, "debt_ratio": 0.5, "bankruptcy_horizon": 26}, 0, 0),
    ({"loans": True, "debt_ratio": 0.3999, "bankruptcy_horizon": 1}, 0, 0),
    ({"default": True, "loans": True, "debt_ratio": 0.5, "bankruptcy_horizon": 1}, 8, -8),
    ({"war_defeat": True}, 6, -6),
    ({"influence": -0.001}, 0, -4),
    ({"default": True, "war_defeat": True, "influence": -1}, 14, -18),
    # Unknown financing cannot manufacture reconcile benefit, but the proven
    # target retains protect cost 8 plus independently observed recovery 6.
    ({"default": None, "war_defeat": True}, 6, -14),
    ({"default": True, "prospective_subject_population": None}, 0, 0),
    ({"default": True, "prospective_subject_population": 0}, 0, 0),
]


@pytest.mark.parametrize(("changes", "reconcile", "protect"), CASES)
def test_exact_target_score_manual_reference_and_generated_pdx(
    production, changes, reconcile, protect
):
    policy, generated, _ = production
    values = dict.fromkeys(reader.key for reader in policy.readers)
    values.update(
        prospective_subject_population=100,
        default=False,
        loans=False,
        debt_ratio=0.1,
        bankruptcy_horizon=52,
        war_defeat=False,
        influence=0,
    )
    values.update(changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    for name, expected in (("reconcile", reconcile), ("protect", protect)):
        field = cooperation.FIELDS[name]
        assert reference.get(field, ("native", 0))[1] == pytest.approx(expected)
        assert _native_number(
            0, _overlay(generated, field), _facts(policy, values)
        ) == pytest.approx(expected)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert (
        decision_rules.evaluate(replace(policy, enabled_domains=frozenset()), values, is_ai=True)
        == {}
    )


def test_complete_native_goal_trigger_and_score_order_survive(production):
    _, generated, inputs = production
    cooperation.verify_inputs(inputs)
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    native = _block(
        _block(parse_text(inputs[cooperation.SOURCE]).root, "ai_strategy_default"),
        "secret_goal_scores",
    )
    actual = _block(_block(parse_text(stripped).root, "ai_strategy_default"), "secret_goal_scores")
    for name, base in (("reconcile", 100), ("protect", 200)):
        original_goal, actual_goal = _block(native, name), _block(actual, name)
        assert _render(_block(actual_goal, "trigger")) == _render(_block(original_goal, "trigger"))
        assert _render(actual_goal) == _render(original_goal)
        field = cooperation.FIELDS[name]
        overlay = _overlay(generated, field)
        assert overlay
        assert _native_number(base, overlay, {"ROOT": {"is_ai": False}}) == base


def test_source_drift_cannot_authorize_new_cooperation_writes(production):
    _, _, inputs = production
    with pytest.raises(ValueError, match="漂移"):
        cooperation.verify_inputs(
            {**inputs, cooperation.SOURCE: inputs[cooperation.SOURCE] + "\n# drift"}
        )
