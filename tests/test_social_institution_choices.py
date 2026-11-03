"""Social investment follows observed living/food need, not legitimacy repair.

The complete physical consumer retains all real demand tiers and independent
financing/administration costs. Native laws, variants and score AST stay native.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from test_remaining_joint_consumers import _block, _native_number, _render
from test_situated_joint_witnesses import _facts
from test_situated_social_governance_joint import _overlay, _syntax

from pdx import config, country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
INFO = "mod/decisions/information.toml"
FIELD = "institution_scores.institution_social_security"
RETIRED = "coordinated_layered_information_social_stable"


@pytest.fixture(scope="module")
def production():
    source = decision_rules.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    compiled, _ = compiler.compile_policy(source, INFO, model)
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    native = compiler.BASELINE.read_text(encoding="utf-8")
    words = (
        frozenset(decision_adapters.reader_evidence(inputs))
        | decision_interfaces.proven_reader_words()
    )

    def patch(enabled=None):
        return decision_rules.patch(
            native,
            compiled,
            baseline=native,
            reader_words=words,
            country_policy=country_state.load(),
            consumer_ir=model.consumer_ir,
            consumer_source=INFO,
            enabled_domains=enabled,
        )

    return source, compiled, native, patch(), patch(frozenset()), model


def _values(changes: dict[str, Any]) -> dict[str, Any]:
    values = {
        "default": False,
        "war": False,
        "loans": False,
        "debt_ratio": 0.3,
        "bankruptcy_horizon": 52,
        "net_surplus": 1,
        "income": 100,
        "bureaucracy": 1,
        "legitimacy": 60,
        "insurrection": False,
        "population": 1_000_000,
        "average_sol": 25,
        "grain_price": 0.2,
        "grain_balance": 0,
    }
    values.update(changes)
    policy = country_state.load()
    coordination = country_state.derive(
        policy, {key: value for key, value in values.items() if key in policy.readers}
    )["coordination"]
    values.update({f"coord_{key}": value for key, value in coordination.items()})
    return values


# Literal expected factors are independent hand sums: strongest same-need tier
# plus each independent negative deviation, with one consumer cap.
CASES = [
    ({}, 1),
    ({"legitimacy": 20}, 1),
    ({"insurrection": True}, 1),
    ({"legitimacy": 20, "insurrection": True}, 1),
    ({"average_sol": 7}, 1.08),
    ({"average_sol": 7, "legitimacy": 20}, 1.08),
    ({"average_sol": 8, "legitimacy": 20}, 1),
    ({"average_sol": 7, "population": 2_000_000}, 1.10),
    ({"grain_price": 0.500001, "grain_balance": -1}, 1.06),
    ({"grain_price": 0.5, "grain_balance": -1}, 1),
    ({"grain_price": 0.6, "grain_balance": 0}, 1),
    ({"average_sol": 7, "grain_price": 0.6, "grain_balance": -1}, 1.12),
    (
        {"average_sol": 7, "grain_price": 0.6, "grain_balance": -1, "insurrection": True},
        1.08,
    ),
    ({"average_sol": 7, "bureaucracy": -1}, 0.98),
    ({"average_sol": 7, "default": True}, 0.88),
    ({"average_sol": 7, "default": True, "bureaucracy": -1}, 0.78),
    ({"average_sol": 7, "default": True, "bureaucracy": -1, "war": True}, 0.83),
    ({"average_sol": 7, "bureaucracy": None}, 1.08),
    ({"average_sol": 7, "default": None}, 1.08),
    ({"average_sol": None, "bureaucracy": -1, "legitimacy": 20}, 0.9),
    ({"average_sol": None, "legitimacy": 20}, 1),
    ({"population": None, "average_sol": 7, "legitimacy": 20}, 1),
    ({"average_sol": None, "grain_price": 0.6, "grain_balance": -1}, 1.06),
    ({"grain_price": None, "grain_balance": -1}, 1),
    ({"grain_price": 0.6, "grain_balance": None}, 1),
    ({"average_sol": 7, "loans": True, "war": True}, 1.08),
    ({"average_sol": 7, "legitimacy": None, "insurrection": None}, 1.08),
]


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_complete_social_consumer_matches_independent_hand_values_and_generated_pdx(
    production, changes, expected
):
    _source, policy, _native, generated, _disabled, _model = production
    values = _values(changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(FIELD, ("native", 1))[1]
    overlay = _overlay(generated, FIELD)
    facts = _facts(policy, values)
    observed = pdx_eval.select(overlay, facts)
    assert reference == pytest.approx(expected)
    assert (observed.delta if observed.operation else 1) == pytest.approx(expected)
    generated_field = _block(
        _block(_block(parse_text(generated).root, "ai_strategy_default"), "institution_scores"),
        "institution_social_security",
    )
    # Project the complete generated numeric block into the interpreter's
    # action shell. Its native value=10 is already the sole initializer.
    script = (
        "# ACTION social_native_consumer [native]; complete numeric consumer\n"
        "if = { limit = { always = yes } multiply = " + _render(generated_field) + " }"
    )
    complete = pdx_eval.select(script, {**facts["ROOT"], **facts})
    assert complete.delta == pytest.approx(10 * expected)


def test_only_real_same_need_tiers_and_independent_costs_remain(production):
    source, policy, _native, _generated, _disabled, _model = production
    rules = {rule.id: rule for rule in source.rules if ".".join(rule.field) == FIELD}
    assert RETIRED not in rules
    assert set(rules) == {
        "lj04_welfare_zero_administration_foundation",
        "social_welfare_population_pressure",
        "social_welfare_local_foundation",
        "lj07_grain_social_foundation",
        "lj07_grain_social_capacity",
        "administrative_cost_guard",
        "social_security_direct_living_pressure",
        "social_security_administrative_pressure",
        "social_security_default_pressure",
    }
    for rule in rules.values():
        if rule.value > 1:
            assert {condition.fact for condition in rule.conditions} & {
                "average_sol",
                "grain_price",
            }
            assert rule.contribution_group == "social_security_need"
    assert {rule.contribution_group for rule in rules.values() if rule.value < 1} == {
        "institution_financing_pressure",
        "institution_administrative_pressure",
    }
    program = next(row for row in policy.consumer_programs if ".".join(row.field) == FIELD)
    assert {row.action_id for row in program.variants} == set(rules)


def test_player_disabled_unknown_wrong_country_and_full_native_ast_are_preserved(production):
    _source, policy, native, generated, disabled, _model = production
    values = _values({"average_sol": 7, "default": True, "bureaucracy": -1})
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert decision_rules.evaluate(policy, {}, is_ai=True) == {}
    assert disabled == native
    overlay = _overlay(generated, FIELD)
    assert pdx_eval.select(overlay, _facts(policy, values, is_ai=False)).operation is None
    foreign = _facts(policy, values)["ROOT"]
    unknown = pdx_eval.select(overlay, {"ROOT": {"is_ai": True}, "other_country": foreign})
    assert unknown.operation is None or unknown.delta == 1
    assert _native_number(0, overlay, _facts(policy, values)) == 0
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    before, after = parse_text(native), parse_text(stripped)
    assert not before.errors
    assert not after.errors
    assert _syntax(before.root) == _syntax(after.root)


def test_native_social_institution_mechanism_is_welfare_and_food_without_legitimacy():
    path = config.GAME / "common/institutions/00_institutions.txt"
    if not path.is_file():
        pytest.skip("requires installed locked native institution source")
    modifiers = _block(
        _block(
            parse_text(path.read_text(encoding="utf-8-sig")).root, "institution_social_security"
        ),
        "modifier",
    )
    assert (
        _render(modifiers) == "{ state_welfare_payments_add = 0.2 state_food_security_add = 0.02 }"
    )
