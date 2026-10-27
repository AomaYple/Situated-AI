from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import country_state, decision_report, decision_rules, decisions, distribution


def _route_rules() -> tuple[decision_rules.RuleSet, str]:
    baseline = "ai_strategy_default = { wanted_construction_output = { value = 1 } }\n"
    data = {
        "schema": 1,
        "baseline_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "domains": {"economy": True},
        "readers": {
            "route": {
                "engine": "has_variable",
                "scope": "root",
                "unit": "boolean",
                "kind": "boolean",
                "argument": "sitai_route_industry",
            },
        },
        "rules": [
            {
                "id": "route_rule",
                "domain": "economy",
                "field": "wanted_construction_output",
                "priority": 300,
                "value": 1.2,
                "conditions": [{"fact": "route", "op": "=", "value": True}],
                "why": "industry route",
                "counterexample": "route inactive",
            }
        ],
    }
    return decision_rules.from_data(data, source_sha256="a" * 64), baseline


def test_route_reader_requires_explicit_country_policy():
    rules, baseline = _route_rules()
    with pytest.raises(ValueError, match="country_policy"):
        decision_rules.patch(baseline, rules, baseline=baseline)


def test_route_reader_expands_to_active_guard_and_owned_contract():
    rules, baseline = _route_rules()
    policy = country_state.load()
    rendered = decision_rules.patch(
        baseline,
        rules,
        baseline=baseline,
        country_policy=policy,
        reader_evidence="has_variable",
        owned_variables={"sitai_route_industry"},
        owned_triggers={"sitai_route_industry_active"},
    )
    assert "sitai_route_industry_active = yes" in rendered
    assert "has_variable = sitai_route_industry" not in rendered
    assert "is_ai = yes" in rendered


def test_decisions_build_with_country_policy_declares_stateful_module():
    policy = decisions.load()
    country = country_state.load()
    files = decisions.build(policy, country_policy=country)
    metadata = json.loads(files[".metadata/metadata.json"])
    assert "country_state" in metadata["enabled_modules"]
    assert metadata["module_contract"]["country_state"]["stateful"] is True
    assert metadata["module_contract"]["country_state"]["ttl_or_none"] == 100
    assert any(name.endswith("sitai_country_triggers.txt") for name in files)


def test_owned_variables_cannot_approve_unknown_or_cooldown_readers():
    rules, baseline = _route_rules()
    for argument in ("sitai_route_invented", "sitai_route_cooldown"):
        changed = replace(rules, readers=(replace(rules.readers[0], argument=argument),))
        with pytest.raises(ValueError, match=r"所有权|合同"):
            decision_rules.patch(
                baseline,
                changed,
                baseline=baseline,
                country_policy=country_state.load(),
                owned_variables={argument},
                owned_triggers={argument + "_active"},
                reader_evidence="has_variable " + argument,
            )


def test_route_false_uses_guard_negation_and_disabled_never_uses_stale_variable():
    rules, baseline = _route_rules()
    false_rule = replace(
        rules.rules[0], conditions=(replace(rules.rules[0].conditions[0], value=False),)
    )
    rendered = decision_rules.patch(
        baseline,
        replace(rules, rules=(false_rule,)),
        baseline=baseline,
        country_policy=country_state.load(),
        reader_evidence="has_variable",
    )
    assert "NOT = { sitai_route_industry_active = yes }" in rendered
    disabled = replace(country_state.load(), enabled=False)
    rendered = decision_rules.patch(
        baseline,
        rules,
        baseline=baseline,
        country_policy=disabled,
        reader_evidence="has_variable",
    )
    assert "always = no" in rendered
    assert "sitai_route_industry_active = yes" not in rendered
    rendered = decision_rules.patch(
        baseline,
        replace(rules, rules=(false_rule,)),
        baseline=baseline,
        country_policy=disabled,
        reader_evidence="has_variable",
    )
    assert "always = no" in rendered
    assert "sitai_route_industry_active" not in rendered


def test_state_contract_and_fingerprint_are_shared_by_offline_report():
    metadata = decision_report.source_metadata()
    expected = country_state.contract(country_state.load())
    assert metadata["country_state"] == expected
    assert metadata["country_coordination"]["state_contract"] == expected
    assert (
        metadata["source_fingerprint"]["country_state_source_sha256"] == expected["source_sha256"]
    )
    broken = json.loads(json.dumps(metadata))
    broken["country_state"]["variable_ttl_days"] += 1
    assert any("country_state" in issue for issue in decision_report.validate(broken))


def test_generation_lock_discovers_new_state_source_and_generator():
    lock = json.loads(distribution.generation_lock({}))
    assert "src/pdx/country_state.py" in lock["sources"]
    assert "mod/decisions/country_state.toml" in lock["sources"]
