"""Country lifecycle and independently interpreted generated runtime contracts."""

from __future__ import annotations

import operator
import random
import tomllib
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state
from pdx.model import Block, Scalar
from pdx.parser import parse_text


@pytest.fixture(scope="module")
def policy():
    return country_state.load()


def facts(**overrides):
    return {
        "war": False,
        "default": False,
        "loans": False,
        "debt_ratio": 0.1,
        "net_surplus": 100,
        "bureaucracy": 150,
        "legitimacy": 60,
        "literacy": 0.7,
        "population": 3_000_000,
        "navy": 30,
        "industrial_route": True,
        "resource_route": False,
        "expansion_route": False,
        "insurrection": False,
        "war_defeat": False,
        "subject": False,
        "artillery_tech": True,
        "income": 2000,
        **overrides,
    }


def test_state_has_twelve_dimensions_units_and_unknowns(policy):
    result = country_state.derive(policy, facts())
    assert len(result["dimensions"]) == 12
    assert result["dimensions"]["fiscal"]["facts"]["net_surplus"] == 100
    assert result["dimensions"]["fiscal"]["readers"]["net_surplus"]["unit"] == "currency_per_week"
    assert result["budgets"] == {"fiscal": 2, "administrative": 2, "security": 2}
    missing = country_state.derive(policy, {})
    assert all(item["status"] == "unknown" for item in missing["dimensions"].values())
    assert all(value is None for value in missing["budgets"].values())
    assert not any(missing["eligible"].values())
    assert len(country_state.contract(policy)["persistent_variables"]) == 7


@pytest.mark.parametrize("value", ["0", True, [], float("nan"), float("inf"), 10**1000, -0.1, 1.1])
def test_malformed_numeric_facts_are_rejected(policy, value):
    with pytest.raises(ValueError):
        country_state.derive(policy, facts(literacy=value))


def test_missing_is_unknown_but_unknown_types_are_rejected(policy):
    assert (
        country_state.derive(policy, facts(literacy=None))["dimensions"]["education"]["status"]
        == "partial"
    )
    with pytest.raises(ValueError):
        country_state.derive(policy, facts(war="no"))
    with pytest.raises(ValueError):
        country_state.derive(policy, {"invented_fact": 1})


def test_entry_and_hold_thresholds_differ(policy):
    assert (
        country_state.advance(
            policy, facts(literacy=0.55, industrial_route=False), None, day=0
        ).route
        is None
    )
    entered = country_state.advance(policy, facts(literacy=0.45), None, day=0)
    assert entered.route == "education"
    assert country_state.advance(policy, facts(literacy=0.55), entered, day=90).route == "education"
    assert country_state.advance(policy, facts(literacy=0.61), entered, day=30).route is None


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"industrial_route": False, "resource_route": True}, "industry"),
        ({"legitimacy": 20, "insurrection": False}, "stability"),
    ],
)
def test_secondary_country_facts_drive_routes(policy, overrides, expected):
    result = country_state.advance(policy, facts(**overrides), None, day=0)
    assert result.route == expected


def test_subjects_do_not_claim_maritime_route_without_independent_status(policy):
    result = country_state.advance(
        policy,
        facts(subject=True, industrial_route=False, resource_route=False, expansion_route=True),
        None,
        day=0,
    )
    assert result.route is None


def test_cooldown_is_not_refreshed_by_monthly_maintenance(policy):
    first = country_state.advance(policy, facts(), None, day=0)
    assert first.route == "industry"
    assert first.cooldown_until == 62
    day30 = country_state.advance(policy, facts(literacy=0.3), first, day=30)
    assert day30.route == "industry"
    assert day30.cooldown_until == 62
    day60 = country_state.advance(policy, facts(literacy=0.3), day30, day=60)
    assert day60.route == "industry"
    assert day60.cooldown_until == 62
    day90 = country_state.advance(policy, facts(literacy=0.3), day60, day=90)
    assert day90.route == "education"
    assert day90.cooldown_until == 152


def test_emergency_priority_preempts_cooldown(policy):
    old = country_state.advance(policy, facts(), None, day=0)
    fiscal = country_state.advance(policy, facts(default=True, insurrection=True), old, day=1)
    assert fiscal.route == "fiscal_recovery"
    war = country_state.advance(
        policy, facts(war=True, default=True, insurrection=True), fiscal, day=2
    )
    assert war.route == "defense"
    assert war.cooldown_until == 64
    stable = country_state.advance(policy, facts(insurrection=True), war, day=3)
    assert stable.route == "stability"


def test_capability_loss_and_unknown_bypass_cooldown(policy):
    old = country_state.advance(policy, facts(), None, day=0)
    assert country_state.advance(policy, facts(bureaucracy=-1), old, day=1).route is None
    assert country_state.advance(policy, {}, old, day=1).route is None


def test_budgets_bound_route_cost_and_only_one_route_wins(policy):
    no_admin = country_state.derive(
        policy, facts(bureaucracy=-1, literacy=0.1, expansion_route=True)
    )
    assert no_admin["budgets"]["administrative"] == 0
    assert not no_admin["eligible"]["education"]
    assert not no_admin["eligible"]["maritime"]
    result = country_state.advance(policy, facts(literacy=0.1, expansion_route=True), None, day=0)
    assert result.route == "education"
    assert result.reserved_budget == {"fiscal": 1, "administrative": 1, "security": 0}


def test_disabled_policy_never_reports_route_eligibility(policy):
    disabled = replace(policy, enabled=False)
    result = country_state.derive(disabled, facts())
    assert result["is_ai"] is True
    assert not any(result["eligible"].values())


def test_parameterized_negative_route_predicate_is_rejected(policy):
    data = tomllib.loads(country_state.SOURCE.read_text(encoding="utf-8"))
    data["routes"]["industry"]["enter"][0].append(
        {"fact": "industrial_route", "op": "=", "value": False}
    )
    with pytest.raises(ValueError, match="带参数布尔路线事实"):
        country_state.from_data(data)


def test_administrative_budget_has_distinct_capacity_tiers(policy):
    assert country_state.derive(policy, facts(bureaucracy=-1))["budgets"]["administrative"] == 0
    assert country_state.derive(policy, facts(bureaucracy=0))["budgets"]["administrative"] == 1
    assert country_state.derive(policy, facts(bureaucracy=100))["budgets"]["administrative"] == 2


def test_disabled_and_player_do_not_refresh_and_expire(policy):
    old = country_state.advance(policy, facts(), None, day=0)
    assert old.expires_day == 100
    disabled = country_state.advance(policy, {}, old, day=99, enabled=False)
    player = country_state.advance(policy, {}, old, day=99, is_ai=False)
    assert disabled.route == player.route == old.route
    assert disabled.expires_day == player.expires_day == old.expires_day
    assert disabled.cooldown_until == player.cooldown_until == 0
    assert "sitai_route_cooldown" not in (disabled.variables or {})
    assert country_state.advance(policy, {}, old, day=100, enabled=False).route is None
    assert country_state.advance(policy, {}, old, day=100, is_ai=False).route is None
    assert not any(country_state.derive(policy, facts(), is_ai=False)["eligible"].values())
    assert all(not value for value in country_state.files(replace(policy, enabled=False)).values())


@pytest.mark.parametrize("mode", ["player", "disabled", "policy_disabled"])
def test_cooldown_only_state_expires_without_refresh(policy, mode):
    script = Script(policy)
    old = country_state.advance(policy, facts(), None, day=0)
    assert script.update(facts(), 0) == "industry"
    old = country_state.advance(policy, facts(bureaucracy=-1), old, day=1)
    assert script.update(facts(bureaucracy=-1), 1) is None
    assert old.route is None
    assert old.cooldown_until == 62
    kwargs = {"is_ai": False} if mode == "player" else {"enabled": False}
    if mode == "policy_disabled":
        policy = replace(policy, enabled=False)
        kwargs = {}
    for day in (30, 61, 62, 100):
        old = country_state.advance(policy, {}, old, day=day, **kwargs)
        script.update({}, day, is_ai=False)
        assert set(old.variables or {}) == set(script.variables)
        assert old.cooldown_until == (62 if day < 62 else 0)


def test_route_loss_preserves_cooldown_and_war_waits_for_refresh(policy):
    script = Script(policy)
    assert script.update(facts(), 0) == "industry"
    # 两次 hook 之间事实改变只影响实时消费者，不隐式调用刷新效果。
    script.day = 1
    assert not script.trigger(script.triggers["sitai_route_industry_active"], facts(war=True))
    assert script.trigger(script.triggers["sitai_route_defense_candidate"], facts(war=True))
    assert not script.trigger(script.triggers["sitai_route_defense_active"], facts(war=True))
    assert script.update(facts(war=True), 30) == "defense"
    script = Script(policy)
    assert script.update(facts(), 0) == "industry"
    assert script.update(facts(bureaucracy=-1), 1) is None
    assert script.update(facts(literacy=0.3), 30) is None
    assert script.update(facts(literacy=0.3), 62) == "education"


def test_old_save_bad_state_day_and_switch_fail_explicitly(policy):
    assert country_state.advance(policy, facts(), None, day=0).route == "industry"
    for old in [
        country_state.RuntimeState("invented", 100, 62),
        country_state.RuntimeState("industry", None, 62),
    ]:
        with pytest.raises(ValueError):
            country_state.advance(policy, facts(), old, day=30)
    for day in [True, -1, 1.5]:
        with pytest.raises(ValueError):
            country_state.advance(policy, facts(), None, day=day)
    with pytest.raises(ValueError):
        country_state.advance(policy, facts(), None, day=1, enabled="yes")


@pytest.mark.parametrize(
    "bad",
    [
        {"route": "industry", "expires_day": "100"},
        {"route": "industry", "expires_day": 1, "updated_day": 2},
        {"route": "industry", "expires_day": 100, "reserved_budget": {"fiscal": 3}},
        {"route": "industry", "expires_day": 100, "variables": {"x": 1}},
    ],
)
def test_old_save_shape_is_strict(policy, bad):
    with pytest.raises(ValueError):
        country_state.advance(policy, facts(), bad, day=2)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "ttl",
        "duplicate",
        "reader",
        "scope",
        "predicate",
        "cost",
        "threshold",
        "priority",
    ],
)
def test_malformed_configuration_fails_closed(mutation):
    data = tomllib.loads(country_state.SOURCE.read_text(encoding="utf-8"))
    if mutation == "unknown":
        data["script"] = "every_country = {}"
    elif mutation == "ttl":
        data["variable_ttl_days"] = 61
    elif mutation == "duplicate":
        data["dimensions"]["education"]["facts"].append("literacy")
    elif mutation == "reader":
        data["dimensions"]["education"]["facts"].append("made_up")
    elif mutation == "scope":
        data["dimensions"]["education"]["facts"].append("target_port")
    elif mutation == "predicate":
        data["routes"]["education"]["enter"] = {"script": "anything"}
    elif mutation == "cost":
        data["routes"]["education"]["cost"]["fiscal"] = 3
    elif mutation == "threshold":
        data["routes"]["education"]["enter"] = {
            "fact": "literacy",
            "op": "<",
            "value": float("nan"),
        }
    elif mutation == "priority":
        data["routes"]["industry"]["priority"] = data["routes"]["education"]["priority"]
    with pytest.raises(ValueError):
        country_state.from_data(data)


class Script:
    """Independent evaluator of the generated PDX subset, including TTL effects."""

    def __init__(self, policy):
        parsed = {path: parse_text(text) for path, text in country_state.files(policy).items()}
        assert all(not item.errors for item in parsed.values())
        self.triggers = {
            a.key: a.value
            for a in parsed["common/scripted_triggers/sitai_country_triggers.txt"].top_assignments
        }
        self.effects = {
            a.key: a.value
            for a in parsed["common/scripted_effects/sitai_country_effects.txt"].top_assignments
        }
        self.readers, self.variables, self.day, self.ai = (
            [dict(reader, key=key) for key, reader in policy.readers.items()],
            {},
            0,
            True,
        )

    def trigger(self, block, values):
        assert isinstance(block, Block)
        outcomes = []
        for item in block.assignments():
            key, value = item.key, item.value
            if key in {"AND", "OR", "NOT"}:
                assert isinstance(value, Block)
                tests = [self.trigger(Block([a]), values) for a in value.assignments()]
                result = (
                    any(tests) if key == "OR" else not all(tests) if key == "NOT" else all(tests)
                )
            elif key in self.triggers:
                result = self.trigger(self.triggers[key], values)
            elif key == "is_ai":
                assert isinstance(value, Scalar)
                result = self.ai == (value.text == "yes")
            elif (
                key == "has_variable"
                and isinstance(value, Scalar)
                and value.text.startswith("sitai_route_")
            ):
                result = self.variables.get(value.text, 0) > self.day
            else:
                assert isinstance(value, Scalar)
                matches = [
                    r
                    for r in self.readers
                    if r["engine"] == key
                    and (r.get("argument") is None or r.get("argument") == value.text)
                ]
                assert len(matches) == 1, key
                reader = matches[0]
                actual = values.get(reader["key"])
                if actual is None:
                    result = False
                else:
                    expected = (
                        True
                        if reader.get("argument")
                        else value.text == "yes"
                        if reader["kind"] == "boolean"
                        else float(value.text)
                    )
                    result = {
                        "=": operator.eq,
                        "<": operator.lt,
                        "<=": operator.le,
                        ">": operator.gt,
                        ">=": operator.ge,
                    }[item.op](actual, expected)
            outcomes.append(result)
        return all(outcomes)

    def effect(self, block, values):
        assert isinstance(block, Block)
        branch = False
        for item in block.assignments():
            if item.key in {"if", "else_if", "else"}:
                assert isinstance(item.value, Block)
                if item.key == "if":
                    branch = False
                limit = item.value.first("limit")
                if not branch and (limit is None or self.trigger(limit.value, values)):
                    branch = True
                    self.effect(
                        Block([a for a in item.value.assignments() if a.key != "limit"]), values
                    )
            elif item.key == "remove_variable":
                assert isinstance(item.value, Scalar)
                self.variables.pop(item.value.text, None)
            elif item.key == "set_variable":
                assert isinstance(item.value, Block)
                fields = {}
                for assignment in item.value.assignments():
                    assert isinstance(assignment.value, Scalar)
                    fields[assignment.key] = assignment.value.text
                assert set(fields) == {"name", "value", "days"}
                self.variables[fields["name"]] = self.day + int(fields["days"])
            elif item.key in self.effects:
                self.effect(self.effects[item.key], values)
            else:
                raise AssertionError(item.key)

    def update(self, values, day, *, is_ai=True):
        self.day, self.ai = day, is_ai
        self.variables = {key: expiry for key, expiry in self.variables.items() if expiry > day}
        self.effect(self.effects["sitai_refresh_country_routes"], values)
        routes = [
            key.removeprefix("sitai_route_")
            for key in self.variables
            if key != "sitai_route_cooldown"
        ]
        assert len(routes) <= 1
        return routes[0] if routes else None


def test_generated_runtime_matches_reference_transitions(policy):
    script, previous = Script(policy), None
    cases = [
        (0, facts()),
        (30, facts(literacy=0.3)),
        (60, facts(literacy=0.3)),
        (90, facts(literacy=0.3)),
        (91, facts(default=True)),
        (92, facts(war=True, default=True)),
        (93, facts(insurrection=True)),
        (120, facts(literacy=0.55)),
        (150, facts(industrial_route=False)),
        (180, facts(expansion_route=True)),
        (210, facts(bureaucracy=-1)),
        (240, {}),
    ]
    for day, values in cases:
        previous = country_state.advance(policy, values, previous, day=day)
        assert script.update(values, day) == previous.route
        if previous.route and f"sitai_route_{previous.route}" in script.variables:
            assert script.variables[f"sitai_route_{previous.route}"] == previous.expires_day
        if previous.cooldown_until > day:
            assert script.variables.get("sitai_route_cooldown") == previous.cooldown_until
        else:
            assert "sitai_route_cooldown" not in script.variables


def test_generated_consumer_guard_rechecks_ability_and_player(policy):
    script = Script(policy)
    assert script.update(facts(), 0) == "industry"
    active = script.triggers["sitai_route_industry_active"]
    assert script.trigger(active, facts())
    assert not script.trigger(active, facts(bureaucracy=-1))
    script.ai = False
    assert not script.trigger(active, facts())
    script.update(facts(war=True), 30, is_ai=False)
    assert "sitai_route_defense" not in script.variables
    script.update(facts(), 100, is_ai=False)
    assert not script.variables


def test_generated_hook_and_static_growth_budget(policy):
    generated = country_state.files(policy)
    hooks = parse_text(generated["common/on_actions/sitai_country_on_actions.txt"])
    assert {"on_monthly_pulse_country", "on_country_default"} <= set(hooks.top_keys)
    assert all(len(text) < 50_000 for text in generated.values())
    text = "\n".join(generated.values())
    assert "every_country" not in text
    assert "random_country" not in text
    assert "$" not in text
    assert "var:" not in text


def test_generated_hold_survives_expired_cooldown(policy):
    script = Script(policy)
    old = country_state.advance(policy, facts(literacy=0.45), None, day=0)
    assert script.update(facts(literacy=0.45), 0) == "education"
    held = country_state.advance(policy, facts(literacy=0.55), old, day=90)
    assert script.update(facts(literacy=0.55), 90) == held.route == "education"
    assert script.variables["sitai_route_education"] == held.expires_day == 190


def test_generated_nonmonotonic_budget_and_zero_cost_unknowns():
    data = tomllib.loads(country_state.SOURCE.read_text(encoding="utf-8"))
    # A higher proven tier remains usable even when a lower tier is not proven.
    data["budgets"]["administrative"]["1"][0][0]["value"] = 200
    changed = country_state.from_data(data)
    values = facts(bureaucracy=150)
    assert country_state.derive(changed, values)["budgets"]["administrative"] == 2
    assert (
        Script(changed).update(values, 0)
        == country_state.advance(changed, values, None, day=0).route
        == "industry"
    )
    data["routes"]["industry"]["cost"] = dict.fromkeys(("fiscal", "administrative", "security"), 0)
    changed = country_state.from_data(data)
    values = facts(bureaucracy=None, debt_ratio=None, navy=None)
    assert (
        Script(changed).update(values, 0)
        == country_state.advance(changed, values, None, day=0).route
        == "industry"
    )


@pytest.mark.parametrize("seed", [19, 71, 20261027])
def test_generated_timelines_match_independent_reference(policy, seed):
    rng = random.Random(seed)
    script, old, day = Script(policy), None, 0
    choices: dict[str, list[Any]] = {
        "war": [False, True, None],
        "default": [False, True, None],
        "loans": [False, True, None],
        "debt_ratio": [None, 0, 0.39, 0.4, 0.59, 0.6, 0.7, 1.2],
        "net_surplus": [None, -1, 0, 1, 100],
        "bureaucracy": [None, -1, 0, 200],
        "literacy": [None, 0, 0.49, 0.5, 0.59, 0.6, 1],
        "population": [None, 0, 1, 3_000_000],
        "navy": [None, 0, 1, 24, 25],
        "industrial_route": [False, True, None],
        "expansion_route": [False, True, None],
        "insurrection": [False, True, None],
    }
    for _ in range(120):
        day += rng.choice([1, 29, 30, 62, 100, 101])
        values = facts(**{key: rng.choice(options) for key, options in choices.items()})
        ai = rng.random() > 0.1
        old = country_state.advance(policy, values, old, day=day, is_ai=ai)
        assert script.update(values, day, is_ai=ai) == old.route
        if old.route:
            assert script.variables[f"sitai_route_{old.route}"] == old.expires_day
        assert script.variables.get("sitai_route_cooldown", 0) == (
            old.cooldown_until if old.cooldown_until > day else 0
        )
