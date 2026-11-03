"""Stateless country facts and independently interpreted generated coordination."""

from __future__ import annotations

import operator
import tomllib
from dataclasses import replace

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


class Script:
    """Independent interpreter of actual generated stateless PDX predicates."""

    def __init__(self, policy):
        parsed = {path: parse_text(text) for path, text in country_state.files(policy).items()}
        assert all(not item.errors for item in parsed.values())
        self.triggers = {
            a.key: a.value
            for a in parsed["common/scripted_triggers/sitai_country_triggers.txt"].top_assignments
        }
        self.readers = [dict(reader, key=key) for key, reader in policy.readers.items()]
        self.ai = True

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


def test_state_has_twelve_dimensions_units_and_unknowns(policy):
    result = country_state.derive(policy, facts())
    assert len(result["dimensions"]) == 12
    assert result["dimensions"]["fiscal"]["facts"]["net_surplus"] == 100
    assert result["dimensions"]["fiscal"]["readers"]["net_surplus"]["unit"] == "currency_per_week"
    missing = country_state.derive(policy, {})
    assert all(item["status"] == "unknown" for item in missing["dimensions"].values())
    assert {"eligible", "budgets"}.isdisjoint(result)
    assert country_state.contract(policy)["persistent_variables"] == []
    assert country_state.contract(policy)["evaluation"] == "vanilla_consumer_demand"


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True, "high"])
def test_invalid_numeric_facts_fail_closed(policy, value):
    with pytest.raises(ValueError):
        country_state.derive(policy, facts(literacy=value))


def test_invalid_or_missing_inputs_do_not_manufacture_health(policy):
    assert (
        country_state.derive(policy, facts(literacy=None))["dimensions"]["education"]["status"]
        == "partial"
    )
    invalid: tuple[object, ...] = (facts(war="no"), {"invented_fact": 1}, [], None)
    for values in invalid:
        with pytest.raises(ValueError):
            country_state.derive(policy, values)


def test_unknown_and_positive_parameterized_native_memory_keep_same_evidence(policy):
    for actual, expected in ((None, None), (False, None), (True, True)):
        result = country_state.derive(
            policy, facts(war_defeat=actual, industrial_route=False, resource_route=False)
        )
        assert result["coordination"]["need_reconstruction"] is expected
        assert result["facts"]["war_defeat"] is actual
    assert policy.readers["war_defeat"]["argument"] == "recently_lost_war"


def test_native_strategy_mapping_keeps_exact_arguments(policy):
    result = country_state.derive(
        policy, {"has_strategy": {"ai_strategy_resource_expansion": True}}
    )
    assert result["facts"]["resource_route"] is True
    assert result["facts"]["industrial_route"] is None
    assert result["coordination"]["need_industry"] is True
    with pytest.raises(ValueError):
        country_state.derive(policy, {"has_strategy": {"ai_strategy_resource_expansion": 1}})


def test_generation_has_no_route_writers_clocks_or_hooks(policy):
    generated = country_state.files(policy)
    assert set(generated) == {"common/scripted_triggers/sitai_country_triggers.txt"}
    text = next(iter(generated.values()))
    assert "sitai_context_" in text
    for retired in (
        "sitai_route_",
        "set_variable",
        "remove_variable",
        "sitai_refresh_country",
        "on_monthly_pulse_country",
    ):
        assert retired not in text
    assert all(name.startswith("sitai_context_") for name in country_state.owned_triggers(policy))
    assert not any(
        hasattr(country_state, name)
        for name in ("ROUTES", "HOOKS", "RuntimeState", "advance", "owned_variables")
    )


def test_disabled_and_player_paths_cannot_generate_positive_country_interventions(policy):
    disabled = replace(policy, enabled=False)
    assert country_state.files(disabled) == {}
    for candidate, is_ai in ((disabled, True), (policy, False)):
        state = country_state.derive(candidate, facts(war=True, insurrection=True), is_ai=is_ai)
        assert not any(state["coordination"].values())
        assert all(
            not item["known"]
            for rows in state["typed_state"].values()
            if isinstance(rows, list)
            for item in rows
        )


@pytest.mark.parametrize(
    "key", ["routes", "budgets", "variable_ttl_days", "switch_cooldown_days", "update_days"]
)
def test_retired_source_fields_cannot_silently_restore_lifecycle(policy, key):
    data = tomllib.loads(country_state.SOURCE.read_text(encoding="utf-8"))
    data[key] = {} if key in {"routes", "budgets"} else 30
    with pytest.raises(ValueError, match="schema"):
        country_state.from_data(data)


def test_independent_political_and_war_needs_coexist_without_history(policy):
    script = Script(policy)
    for legitimacy in (20, 30):
        values = facts(war=True, insurrection=True, legitimacy=legitimacy)
        result = country_state.derive(policy, values)["coordination"]
        assert result["need_political"] is result["need_security"] is True
        for need in ("political", "security"):
            assert script.trigger(script.triggers["sitai_context_need_" + need], values)
    # The real stateless political need retains its existing <35 definition;
    # the migrated revolution consumer intentionally uses its former entry <25.
    values = facts(war=True, insurrection=False, legitimacy=35)
    assert not script.trigger(script.triggers["sitai_context_need_political"], values)
    assert script.trigger(script.triggers["sitai_context_need_security"], values)
