"""Hand calculations at the production power-bloc proposal consumer."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules
from pdx import native_action_opportunities as native
from pdx.parser import parse_text
from pdx.situated import compiler

pytestmark = pytest.mark.integration
SOURCE = native.CANDIDATES["join_power_bloc"]
FIELD = "join_power_bloc.ai.propose_score"


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policy = compiler.compile_policy(dict(adapters.policies)[SOURCE], SOURCE, model)[0]
    selected = replace(
        adapters, policies=((SOURCE, policy),), initial_values=(), supply=None, scalar_values=()
    )
    inputs = decision_adapters.read_inputs(selected)
    files, metadata = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policy, files[SOURCE], inputs[SOURCE], metadata, model


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 20),
        ({"default": True}, 18),
        ({"net_surplus": -0.01}, 19),
        ({"war_defeat": True}, 19),
        ({"default": True, "net_surplus": -100}, 18),
        ({"default": True, "net_surplus": -100, "war_defeat": True}, 17),
        ({"net_surplus": -100, "war_defeat": True}, 18),
        ({"default": None}, 18),
        ({"net_surplus": None}, 19),
        ({"default": None, "net_surplus": None}, 18),
        ({"default": None, "net_surplus": None, "war_defeat": True}, 17),
        ({"default": None, "net_surplus": None, "cost_country_population": None}, 20),
        ({"default": None, "net_surplus": None, "cost_country_population": 0}, 18),
        ({"default": True, "war_defeat": True, "cost_country_population": None}, 17),
        ({"net_surplus": None, "war_defeat": True, "cost_country_population": None}, 19),
        ({"war_defeat": None}, 20),
        ({"loans": True, "debt_ratio": 0.01, "bankruptcy_horizon": 520}, 20),
    ],
)
def test_bounded_financing_and_independent_recovery_match_reference_and_actual_pdx(
    production, changes, expected
):
    policy, generated, _, _, _ = production
    values = {
        "default": False,
        "net_surplus": 0,
        "war_defeat": False,
        "cost_country_population": 100,
        **changes,
    }
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    assert 20 * reference.get(FIELD, ("native", 1))[1] == pytest.approx(expected)
    overlay = _overlay(generated, FIELD)
    facts = _facts(policy, values)
    assert _native_number(20, overlay, facts) == pytest.approx(expected)
    assert _native_number(0, overlay, facts) == 0


def test_production_ir_is_exact_actor_cost_with_no_fabricated_fee_or_foreign_read(production):
    policy, _, _, metadata, model = production
    assert {rule.id for rule in policy.rules} == {
        "native_action_bloc_default",
        "native_action_bloc_deficit",
        "native_action_bloc_recovery",
    }
    assert {reader.key for reader in policy.readers} == {
        "default",
        "net_surplus",
        "war_defeat",
        "cost_country_population",
    }
    assert all(reader.scope == "root" and not reader.path for reader in policy.readers)
    assert all(rule.semantic_role == "cost" for rule in policy.rules)
    groups = {rule.id: rule.contribution_group for rule in policy.rules}
    assert groups["native_action_bloc_default"] == groups["native_action_bloc_deficit"]
    assert groups["native_action_bloc_recovery"] != groups["native_action_bloc_default"]
    assert model.consumer_ir is not None
    writers = [writer for writer in model.consumer_ir.writers if writer.source == SOURCE]
    assert len(writers) == 3
    for writer in writers:
        context = writer.evaluation_context
        assert context is not None
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
            "root",
            "country",
            "actor",
        )
        assert not context.targets
        assert not context.auxiliary_scopes
        assert writer.legacy is not None
        assert writer.legacy.conservative_unknown_facts == next(
            rule.conservative_unknown_facts for rule in policy.rules if rule.id == writer.definition
        )
    consumers = metadata["consumers"]
    assert isinstance(consumers, list)
    assert len(consumers) == 1


def test_full_native_acceptance_leverage_cohesion_relations_and_effects_survive(production):
    _, generated, original, _, _ = production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    assert not parse_text(generated).errors
    assert _render(parse_text(stripped).root) == _render(parse_text(original).root)
    assert generated.count("# SITAI BEGIN information:") == 1
    assert "accept_score" not in _overlay(generated, FIELD)


def test_player_disabled_and_unanchored_unknown_actor_keep_original_score(production):
    policy, generated, original, _, _ = production
    values: dict[str, object] = {"default": True, "net_surplus": -100, "war_defeat": True}
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    overlay = _overlay(generated, FIELD)
    assert _native_number(20, overlay, _facts(policy, values, is_ai=False)) == 20
    facts = _facts(policy, dict.fromkeys(reader.key for reader in policy.readers))
    decoy = {"in_default": True, "net_total_income": -100, "total_population": 1000}
    facts["scope:target_country"] = decoy
    facts["scope:target"] = decoy
    facts["ROOT"]["owner"] = decoy
    assert _native_number(20, overlay, facts) == 20
    words = frozenset(
        decision_adapters.reader_evidence(decision_adapters.read_inputs(decision_adapters.load()))
    )
    assert (
        decision_rules.patch(
            original,
            replace(policy, enabled_domains=frozenset()),
            baseline=original,
            default_strategy=False,
            reader_words=words,
        )
        == original
    )
