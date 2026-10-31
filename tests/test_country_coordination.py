"""分层协调的三值回退和生成边界测试。"""

from __future__ import annotations

import json
import random
from copy import deepcopy
from dataclasses import replace

import pytest
from test_country_state import Script

from pdx import country_coordination, country_state
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


def test_unknown_core_facts_do_not_grant_capacity(policy):
    result = country_coordination.evaluate(policy, {"war": False}, is_ai=True)
    assert not any(result.values())


def test_recovery_preempts_other_capacities(policy):
    result = country_coordination.evaluate(policy, facts(default=True, debt_ratio=0.9), is_ai=True)
    assert result["layer_recovery"]
    assert not result["development"]
    assert not result["stable_capacity"]
    assert not result["expansion_capacity"]


def test_typed_state_bridge_preserves_local_unknowns(policy):
    result = country_coordination.evaluate_typed(policy, facts(war=True, literacy=None), is_ai=True)
    security = next(item for item in result.needs if item.id == "need_security")
    education = next(item for item in result.needs if item.id == "need_education")
    assert security.known
    assert security.value is True
    assert education.known is False
    assert education.value is None
    assert result.as_dict()["unknown_policy"] == "unknown_never_inferred_false"


def test_unknown_recovery_can_use_proven_lower_capacity(policy):
    # A missing auxiliary high-tier fact must not manufacture an expansion signal.
    values = facts(default=None, debt_ratio=0.1, net_surplus=100, bureaucracy=0)
    result = country_coordination.evaluate(policy, values, is_ai=True)
    assert not result["layer_foundation"]
    assert not result["development"]
    assert not result["layer_expansion"]


def test_need_unknown_is_safe_and_need_false_is_not_a_signal(policy):
    unknown = country_coordination.evaluate(policy, facts(literacy=None), is_ai=True)
    assert not unknown["need_education"]
    false = country_coordination.evaluate(policy, facts(literacy=0.8), is_ai=True)
    assert not false["need_education"]


def test_disabled_and_player_paths_are_empty(policy):
    disabled = replace(policy, enabled=False)
    assert not any(country_coordination.evaluate(disabled, facts()).values())
    assert not any(country_coordination.evaluate(policy, facts(), is_ai=False).values())
    assert country_coordination.triggers(disabled) == ""


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(capacities=[]),
        lambda data: data["capacities"].update(recovery=[]),
        lambda data: data["needs"].update(fiscal={"when": [], "why": ""}),
    ],
)
def test_malformed_coordination_rejected(policy, mutation):
    data = deepcopy(policy.data["coordination"])
    mutation(data)
    with pytest.raises(ValueError):
        country_coordination.normalize(data, policy.readers)


def test_contract_marks_behavior_as_static_only(policy):
    contract = country_coordination.contract(policy)
    assert contract["persistent_variables"] == 0
    assert contract["world_scans"] == 0
    assert contract["typed_state"]["producer"].endswith("derive_typed")
    assert contract["evidence"] == "static_check"
    assert contract["behavior_verified"] is False


def test_generated_context_triggers_have_known_guards(policy):
    text = country_coordination.triggers(policy)
    parsed = parse_text(text)
    assert not parsed.errors
    assert "sitai_context_layer_expansion" in text
    assert "sitai_context_known_layer_expansion" in text
    assert "sitai_context_known_need_industry" in text


def test_serialized_contract_is_identical(policy):
    contract = country_coordination.contract(policy)
    assert json.loads(json.dumps(contract)) == contract


def test_high_capacity_unknown_degrades_only_to_proven_lower_layer(policy):
    values = facts(legitimacy=None)
    result = country_coordination.evaluate(policy, values)
    assert result["expansion_capacity"] is None
    assert result["layer_expansion"] is False
    assert result["layer_stable"] is True
    assert result["layer_foundation"] is False
    result = country_coordination.evaluate(policy, facts(bureaucracy=None))
    assert result["stable_capacity"] is None
    assert result["layer_stable"] is False
    assert result["layer_foundation"] is True


def test_low_capacity_is_not_a_permanent_development_veto(policy):
    values = facts(loans=True, debt_ratio=0.1, net_surplus=-5, bureaucracy=-100, legitimacy=20)
    result = country_coordination.evaluate(policy, values)
    assert result["layer_foundation"] is True
    assert result["need_administrative"] is True
    assert result["need_political"] is True
    assert result["need_fiscal"] is True


def test_generated_coordination_matches_independent_pdx_interpreter(policy):
    script = Script(policy)
    rng = random.Random(6173)
    choices: dict[str, list] = {
        "default": [False, True, None],
        "war": [False, True, None],
        "debt_ratio": [0.1, 0.2, 0.5, 0.75, None],
        "net_surplus": [-1, 0, 100, None],
        "bureaucracy": [-1, 0, 100, None],
        "legitimacy": [20, 35, 60, None],
        "insurrection": [False, True, None],
        "literacy": [0.2, 0.5, 0.8, None],
        "population": [0, 100_000, None],
        "income": [-1, 0, 100, None],
        "industrial_route": [False, True, None],
        "resource_route": [False, True, None],
        "expansion_route": [False, True, None],
        "war_defeat": [False, True, None],
        "navy": [0, 25, None],
    }
    for _ in range(300):
        values = facts(**{key: rng.choice(options) for key, options in choices.items()})
        result = country_coordination.evaluate(policy, values)
        assert sum(result["layer_" + layer] is True for layer in country_coordination.LAYERS) <= 1
        for name, expected in result.items():
            assert script.trigger(script.triggers[country_coordination.PREFIX + name], values) == (
                expected is True
            ), (name, values)
            assert script.trigger(
                script.triggers[country_coordination.PREFIX + "known_" + name], values
            ) == (expected is not None), (name, values)


@pytest.mark.parametrize("need", ["industry", "reconstruction", "overseas"])
def test_optional_need_unknown_keeps_raw_unknown_without_positive_evidence(policy, need):
    values = facts(
        industrial_route=False, resource_route=False, war_defeat=False, expansion_route=False
    )
    result = country_coordination.evaluate(policy, values)

    assert result["need_" + need] is None
    assert result.get("evidence_need_" + need) is False


@pytest.mark.parametrize(
    ("need", "overrides"),
    [
        ("industry", {"resource_route": True}),
        ("reconstruction", {"war_defeat": True, "war": False}),
        ("overseas", {"expansion_route": True, "navy": 30, "subject": False}),
    ],
)
def test_optional_need_positive_evidence_is_available_to_consumers(policy, need, overrides):
    result = country_coordination.evaluate(policy, facts(**overrides))

    assert result["need_" + need] is True
    assert result.get("evidence_need_" + need) is True


def test_optional_evidence_known_is_ai_gated_in_generated_pdx(policy):
    script = Script(policy)
    values = facts(
        industrial_route=False, resource_route=False, war_defeat=False, expansion_route=False
    )
    for need in ("industry", "reconstruction", "overseas"):
        name = "sitai_context_evidence_need_" + need
        known = "sitai_context_known_evidence_need_" + need
        assert name in script.triggers
        assert known in script.triggers
        assert not script.trigger(script.triggers[name], values)
        assert script.trigger(script.triggers[known], values)
        script.ai = False
        assert not script.trigger(script.triggers[name], values)
        assert not script.trigger(script.triggers[known], values)
        script.ai = True
