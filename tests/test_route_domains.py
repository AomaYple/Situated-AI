from __future__ import annotations

from dataclasses import replace

import pytest
from test_country_state import Script, facts

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_intents,
    decision_interfaces,
    decision_rules,
)

ROUTES = ("fiscal_recovery", "stability", "defense", "industry", "education", "maritime")


@pytest.fixture(scope="module")
def adapter_set():
    return decision_adapters.load(strategy=decision_intents.load())


def _route_rows(adapter_set):
    rows = []
    for source, policy in adapter_set.policies:
        for rule in policy.rules:
            if rule.id.startswith("coordinated_route_"):
                route = next(route for route in ROUTES if f"coordinated_route_{route}_" in rule.id)
                rows.append((route, source, policy, rule))
    return rows


def _satisfying(rule):
    values = {}
    for condition in rule.conditions:
        assert not isinstance(condition.value, decision_rules.FactReference)
        value = condition.value
        if condition.op == ">":
            value += 1
        elif condition.op == "<":
            value -= 1
        values[condition.fact] = value
    return values


def test_all_routes_have_real_consumer_fields_and_root_scope(adapter_set):
    rows = _route_rows(adapter_set)
    assert {route for route, *_ in rows} == set(ROUTES)
    assert len(rows) >= 12
    for _route, source, policy, rule in rows:
        assert policy.actor_path == ()
        assert rule.field
        assert rule.field[0] == "ai_strategy_default" or source.startswith(
            "common/technology/technologies/"
        )
        consumer = decision_interfaces.consumer(rule.field, policy.actor_path)
        assert consumer["eligibility_costs_and_execution"] == "retained_vanilla"


@pytest.mark.skipif(not config.GAME.is_dir(), reason="游戏目录不可用")
def test_route_readers_are_owned_and_compiled_to_active_guards(adapter_set):
    expected = {f"sitai_route_{route}" for route in ROUTES}
    used = set()
    for _source, policy in adapter_set.policies:
        for reader in policy.readers:
            if reader.key.startswith("route_"):
                used.add(reader.argument)
                assert reader.engine == "has_variable"
                assert reader.scope == "root"
                assert reader.argument in expected
    assert used == expected

    country = country_state.load()
    files, _metadata = decision_adapters.build(
        adapter_set,
        country_policy=country,
        owned_variables=set(country_state.owned_variables(country)),
        owned_triggers=set(country_state.owned_triggers(country)),
    )
    for route in ROUTES:
        token = f"sitai_route_{route}_active = yes"
        assert any(token in text for text in files.values())


@pytest.mark.parametrize("is_ai", [True, False])
def test_route_rules_preserve_player_boundary_and_disabled_domains(adapter_set, is_ai):
    for _route, _source, policy, rule in _route_rows(adapter_set):
        isolated = replace(policy, rules=(rule,), enabled_domains=frozenset({rule.domain}))
        values = _satisfying(rule)
        expected = {".".join(rule.field): (rule.id, rule.value)} if is_ai else {}
        assert decision_rules.evaluate(isolated, values, is_ai=is_ai) == expected
        assert (
            decision_rules.evaluate(isolated, values, is_ai=True, enabled_domains=frozenset()) == {}
        )


def test_route_unknown_and_false_inputs_fall_back_to_vanilla(adapter_set):
    for _route, _source, policy, rule in _route_rows(adapter_set):
        isolated = replace(policy, rules=(rule,), enabled_domains=frozenset({rule.domain}))
        values = _satisfying(rule)
        route_fact = next(
            condition.fact for condition in rule.conditions if condition.fact.startswith("route_")
        )
        assert decision_rules.evaluate(isolated, {**values, route_fact: False}, is_ai=True) == {}
        assert decision_rules.evaluate(isolated, {**values, route_fact: None}, is_ai=True) == {}


def test_route_rules_use_first_match_without_accumulation(adapter_set):
    for _route, _source, policy, rule in _route_rows(adapter_set):
        isolated = replace(policy, rules=(rule,), enabled_domains=frozenset({rule.domain}))
        lower = replace(rule, id=f"{rule.id}_lower", priority=rule.priority - 1)
        arbitration = replace(isolated, rules=(lower, rule))
        values = _satisfying(rule)
        assert decision_rules.evaluate(arbitration, values, is_ai=True) == {
            ".".join(rule.field): (rule.id, rule.value)
        }


def test_route_direction_is_bounded_and_cross_domain():
    adapter_set = decision_adapters.load(strategy=decision_intents.load())
    rows = _route_rows(adapter_set)
    by_route = {route: [rule for _r, _s, _p, rule in rows if _r == route] for route in ROUTES}
    assert any(rule.operation == "add" and rule.value < 0 for rule in by_route["fiscal_recovery"])
    assert any(rule.operation == "multiply" and rule.value > 1 for rule in by_route["defense"])
    assert any(rule.operation == "multiply" and rule.value > 1 for rule in by_route["education"])
    assert any(rule.operation == "add" and rule.value > 0 for rule in by_route["maritime"])
    assert len({rule.field for _route, _source, _policy, rule in rows}) >= 9


def _consumer_values(policy, country_values, script):
    """Complete, healthy consumer inputs; actor aliases use the same country facts."""
    values = {}
    for reader in policy.readers:
        if reader.key.startswith("route_"):
            route = reader.key.removeprefix("route_")
            values[reader.key] = script.trigger(
                script.triggers[f"sitai_route_{route}_active"], country_values
            )
        elif reader.scope == "root" and reader.key in country_values:
            values[reader.key] = country_values[reader.key]
        elif reader.kind == "boolean":
            values[reader.key] = False
        else:
            values[reader.key] = max(reader.minimum or 0, min(reader.maximum or 100, 1))
    values.update(
        {
            k: v
            for k, v in {
                "bankruptcy_horizon": 100,
                "national_gdp": 10000000,
                "candidate_gdp": 1000000,
                "own_army": 100,
                "own_navy": country_values["navy"],
                "target_army": 10,
                "target_navy": 1,
                "target_relations": 0,
                "current_infamy": 0,
                "radical_share": 0.1,
                "prospective_subject_population": 100000,
                "prospective_overlord_population": 3000000,
            }.items()
            if k in values
        }
    )
    return values


@pytest.mark.parametrize(
    ("route", "overrides"),
    [
        ("defense", {"war": True}),
        ("fiscal_recovery", {"debt_ratio": 0.65}),
        ("stability", {"insurrection": True}),
        ("industry", {}),
        ("education", {"literacy": 0.3}),
        ("maritime", {"industrial_route": False, "expansion_route": True}),
    ],
)
def test_generated_country_state_reaches_complete_production_rules(adapter_set, route, overrides):
    country = country_state.load()
    inputs = facts(**overrides)
    script = Script(country)
    assert script.update(inputs, 0) == route
    assert country_state.advance(country, inputs, None, day=0).route == route
    policies = [("information", decision_rules.load()), *adapter_set.policies]
    expected: set[str] = set()
    matched: set[str] = set()
    for source, policy in policies:
        candidates = [
            rule
            for rule in policy.rules
            if rule.id.startswith(
                f"coordinated_route_{route}_" if source != "information" else f"route_{route}_"
            )
        ]
        if not candidates:
            continue
        values = _consumer_values(policy, inputs, script)
        result = decision_rules.evaluate(policy, values, is_ai=True)
        for rule in candidates:
            expected.add(rule.id)
            if result.get(".".join(rule.field)) == (rule.id, rule.value):
                matched.add(rule.id)
    assert expected
    assert expected == matched, expected - matched


@pytest.mark.parametrize(
    "overrides",
    [
        {"default": True},
        {"net_surplus": -1},
        {"net_surplus": 0},
        {"net_surplus": None},
        {"bureaucracy": -1},
        {"bureaucracy": 0},
        {"bureaucracy": None},
    ],
)
def test_emergency_defense_keeps_survival_but_does_not_fund_new_capacity(adapter_set, overrides):
    country = country_state.load()
    inputs = facts(war=True, **overrides)
    script = Script(country)
    assert script.update(inputs, 0) == "defense"
    assert country_state.advance(country, inputs, None, day=0).route == "defense"
    rejected = {
        "route_defense_army_capacity",
        "coordinated_route_defense_supply_ships",
        "coordinated_route_defense_ship_construction",
    }
    matched: set[str] = set()
    for _source, policy in [("information", decision_rules.load()), *adapter_set.policies]:
        values = _consumer_values(policy, inputs, script)
        matched.update(
            row[0] for row in decision_rules.evaluate(policy, values, is_ai=True).values()
        )
    assert not matched & rejected
    assert "coordinated_route_defense_colonial_commitment" in matched


@pytest.mark.parametrize(
    ("navy", "income", "expected"),
    [(24, 2000, None), (25, 2000, "maritime"), (30, 0, None), (30, None, None)],
)
def test_maritime_requires_proven_projection_and_income(navy, income, expected):
    country = country_state.load()
    inputs = facts(industrial_route=False, expansion_route=True, navy=navy, income=income)
    script = Script(country)
    assert script.update(inputs, 0) == expected
    assert country_state.advance(country, inputs, None, day=0).route == expected
    if expected:
        weaker = {**inputs, "navy": 24}
        assert not script.trigger(script.triggers["sitai_route_maritime_active"], weaker)
        assert country_state.advance(country, weaker, None, day=30).route is None
