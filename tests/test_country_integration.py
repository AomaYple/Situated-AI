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


@pytest.mark.parametrize(
    "argument",
    [
        "sitai_route_industry",
        "sitai_route_stability",
        "sitai_route_cooldown",
        "sitai_route_invented",
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_retired_route_readers_are_rejected_even_with_country_policy(argument, enabled):
    rules, baseline = _route_rules()
    changed = replace(rules, readers=(replace(rules.readers[0], argument=argument),))
    for policy in (None, replace(country_state.load(), enabled=enabled)):
        with pytest.raises(ValueError, match=r"route|路线|退役"):
            decision_rules.patch(
                baseline,
                changed,
                baseline=baseline,
                country_policy=policy,
                reader_evidence="has_variable " + argument,
            )


def test_decisions_build_declares_stateless_country_module():
    files = decisions.build(decisions.load(), country_policy=country_state.load())
    metadata = json.loads(files[".metadata/metadata.json"])
    assert "country_state" in metadata["enabled_modules"]
    contract = metadata["module_contract"]["country_state"]
    assert contract["stateful"] is False
    assert contract["direct_read"] is True
    assert contract["ttl_or_none"] is None
    assert contract["hooks"] == []
    assert "common/scripted_triggers/sitai_country_triggers.txt" in files
    assert "common/scripted_effects/sitai_country_effects.txt" not in files
    assert "common/on_actions/sitai_country_on_actions.txt" not in files


def test_state_contract_and_fingerprint_are_shared_by_offline_report():
    metadata = decision_report.source_metadata()
    expected = country_state.contract(country_state.load())
    assert metadata["country_state"] == expected
    assert metadata["country_coordination"]["state_contract"] == expected
    assert (
        metadata["source_fingerprint"]["country_state_source_sha256"] == expected["source_sha256"]
    )
    broken = json.loads(json.dumps(metadata))
    broken["country_state"]["persistent_variables"] = ["sitai_route_industry"]
    assert any("country_state" in issue for issue in decision_report.validate(broken))


def test_generation_lock_discovers_new_state_source_and_generator():
    lock = json.loads(distribution.generation_lock({}))
    assert "src/pdx/country_state.py" in lock["sources"]
    assert "mod/decisions/country_state.toml" in lock["sources"]
