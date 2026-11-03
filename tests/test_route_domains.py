"""Retired national routes become observed, independent consumer-local causes."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from _frozen_reader_words import frozen_reader_words
from test_situated_joint_witnesses import _facts
from test_situated_social_governance_joint import _overlay

from pdx import country_state, decision_adapters, decision_rules
from pdx.situated import compiler, pdx_eval

INFO = "mod/decisions/information.toml"


@pytest.fixture(scope="module")
def production():
    source = decision_rules.load()
    model = compiler.load_model()
    # This witness exercises these two consumers. The complete information
    # policy is generated separately by the integration writer oracle.
    rules = tuple(
        rule
        for rule in source.rules
        if rule.field in {("revolution_aversion",), ("wanted_army_size",)}
    )
    keys = frozenset(key for rule in rules for key in rule.input_keys())
    selected = replace(
        source,
        rules=rules,
        readers=tuple(reader for reader in source.readers if reader.key in keys),
        enabled_domains=frozenset(rule.domain for rule in rules),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy, _ = compiler.compile_policy(selected, INFO, model)
    adapters = decision_adapters.load()
    native = compiler.BASELINE.read_text(encoding="utf-8")
    words = frozen_reader_words(native)
    generated = decision_rules.patch(
        native,
        policy,
        baseline=native,
        reader_words=words,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    return source, policy, generated, adapters, model


def _values(changes):
    values = {
        "war": False,
        "default": False,
        "loans": False,
        "debt_ratio": 0.3,
        "net_surplus": 1,
        "bureaucracy": 1,
        "legitimacy": 60,
        "insurrection": False,
        "income": 100,
        "defensive_pact_articles": 0,
        "native_army_capacity": 100,
        "native_marine_capacity": 20,
    }
    values.update(changes)
    country = country_state.load()
    coordination = country_state.derive(
        country, {k: v for k, v in values.items() if k in country.readers}
    )["coordination"]
    values.update({"coord_" + key: value for key, value in coordination.items()})
    return values


@pytest.mark.parametrize(
    ("field", "changes", "expected"),
    [
        ("revolution_aversion", {}, 1),
        ("revolution_aversion", {"insurrection": True}, 1.2),
        ("revolution_aversion", {"legitimacy": 24.999}, 1.2),
        ("revolution_aversion", {"legitimacy": 25}, 1),
        ("revolution_aversion", {"legitimacy": 30}, 1),
        ("revolution_aversion", {"legitimacy": 20, "insurrection": True}, 1.2),
        ("revolution_aversion", {"war": True, "legitimacy": 20, "insurrection": True}, 1.2),
        (
            "revolution_aversion",
            {"war": True, "legitimacy": 20, "insurrection": True, "default": True},
            1.25,
        ),
        ("revolution_aversion", {"legitimacy": None, "insurrection": True}, 1.2),
        ("revolution_aversion", {"legitimacy": 20, "insurrection": None}, 1.2),
        ("revolution_aversion", {"legitimacy": None, "insurrection": None}, 1),
        ("wanted_army_size", {"war": True}, 1.2),
        ("wanted_army_size", {"war": True, "bureaucracy": None}, 1.12),
        ("wanted_army_size", {"war": True, "net_surplus": None}, 1.11),
        (
            "wanted_army_size",
            {"war": True, "net_surplus": None, "bureaucracy": None, "default": None},
            1.08,
        ),
        ("wanted_army_size", {"war": True, "default": True, "bureaucracy": None}, 0.93),
        ("wanted_army_size", {"war": False, "net_surplus": -1, "defensive_pact_articles": 1}, 0.95),
        ("wanted_army_size", {"war": True, "net_surplus": -1, "defensive_pact_articles": 1}, 1.11),
        ("wanted_army_size", {"war": None, "net_surplus": -1, "defensive_pact_articles": 1}, 1),
    ],
)
def test_local_crisis_war_and_pact_match_hand_values_and_actual_pdx(
    production, field, changes, expected
):
    _source, policy, generated, _adapters, _model = production
    values = _values(changes)
    result = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    assert (1 if result is None else result[1]) == pytest.approx(expected)
    observed = pdx_eval.select(_overlay(generated, field), _facts(policy, values))
    assert (1 if observed.operation is None else observed.delta) == pytest.approx(expected)


def test_resolved_production_has_no_retired_routes_but_retains_actual_strategy_observations(
    production,
):
    source, _policy, generated, adapters, model = production
    policies = [source, *(policy for _path, policy in adapters.policies)]
    for policy in policies:
        assert not any(
            reader.engine == "has_variable" and (reader.argument or "").startswith("sitai_route_")
            for reader in policy.readers
        )
        assert not any(
            rule.id.startswith(("route_", "coordinated_route_")) for rule in policy.rules
        )
    assert not any(fact.trigger.startswith("has_variable = sitai_route_") for fact in model.facts)
    assert "sitai_route_" not in generated
    assert (
        next(reader for reader in source.readers if reader.key == "industrial_route").argument
        == "ai_strategy_industrial_expansion"
    )
    assert {rule.id for rule in source.rules if rule.field == ("revolution_aversion",)} == {
        "political_default_risk",
        "political_insurrection_aversion",
        "political_legitimacy_crisis_aversion",
        "coordinated_layered_information_revolution_recovery",
    }


def test_war_and_domestic_crisis_both_apply_in_one_observation(production):
    _source, policy, generated, _adapters, _model = production
    values = _values({"war": True, "insurrection": True})
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert result["wanted_army_size"][1] == pytest.approx(1.2)
    assert result["revolution_aversion"][1] == pytest.approx(1.2)
    for field in ("wanted_army_size", "revolution_aversion"):
        assert pdx_eval.select(
            _overlay(generated, field), _facts(policy, values)
        ).delta == pytest.approx(1.2)


def test_same_cause_crisis_tiers_do_not_stack_and_player_unknown_remain_native(production):
    _source, policy, generated, _adapters, _model = production
    values = _values({"default": True, "insurrection": True, "legitimacy": 20, "war": True})
    assert decision_rules.evaluate(policy, values, is_ai=True)["revolution_aversion"][
        1
    ] == pytest.approx(1.25)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    for field in ("wanted_army_size", "revolution_aversion"):
        overlay = _overlay(generated, field)
        assert pdx_eval.select(overlay, {}).operation is None
        assert pdx_eval.select(overlay, _facts(policy, values, is_ai=False)).operation is None
    assert not re.search(r"set_variable|remove_variable", generated)
