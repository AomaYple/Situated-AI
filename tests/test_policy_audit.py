from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import country_parameters, decision_adapters, decision_rules, policy_audit


def _policy() -> decision_rules.RuleSet:
    baseline = "ai_strategy_default = { wanted_construction_output = { value = 1 } }\n"
    data = {
        "schema": 1,
        "baseline_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "domains": {"economy": True},
        "readers": {
            "income": {
                "engine": "fixed_income",
                "scope": "root",
                "unit": "currency_per_week",
                "kind": "number",
                "minimum": 0,
            },
            "war": {
                "engine": "is_at_war",
                "scope": "root",
                "unit": "boolean",
                "kind": "boolean",
            },
        },
        "rules": [
            {
                "id": "income_rule",
                "domain": "economy",
                "field": "wanted_construction_output",
                "priority": 10,
                "value": 1.2,
                "conditions": [
                    {"fact": "income", "op": ">", "value": 0},
                    {"fact": "war", "op": "=", "value": False},
                ],
                "why": "有收入时发展",
                "counterexample": "战争或未知收入回退原版",
            }
        ],
    }
    return decision_rules.from_data(data, source_sha256="a" * 64, strategy=None)


def test_reference_evaluate_has_satisfying_violating_unknown_and_player_cases():
    policy = _policy()
    row = policy_audit.audit_rule(policy, policy.rules[0], consumer="synthetic")
    assert row["range"] == {"lower": 0.5, "upper": 1.5}
    assert row["checks"]["satisfying"]["matched"] is True
    assert row["checks"]["violating"]["matched"] is False
    assert row["checks"]["unknown"]["matched"] is False
    assert row["checks"]["player"]["matched"] is False
    assert row["checks"]["invalid"]["matched"] is False
    assert {item["value"] for item in row["sensitivity"]} == {0.5, 1.2, 1.5}
    assert all(
        item["matched"] and item["adjustment"] == item["value"] for item in row["sensitivity"]
    )


def test_audit_rejects_empty_rule_set_and_invalid_values():
    policy = _policy()
    empty = replace(policy, rules=())
    with pytest.raises(ValueError, match="不能为空"):
        policy_audit.audit_rule(empty, policy.rules[0], consumer="synthetic")
    with pytest.raises(ValueError, match="不在规则集"):
        policy_audit.audit_rule(
            policy, replace(policy.rules[0], id="missing"), consumer="synthetic"
        )
    with pytest.raises(ValueError, match="范围"):
        policy_audit._parameter_points(replace(policy.rules[0], value=float("nan")))


def test_production_report_is_deterministic_and_separates_declared_from_used():
    first = policy_audit.build(measure=False)
    second = policy_audit.build(measure=False)
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )
    assert first["rules"]
    assert first["reader_usage"]["declared"] >= first["reader_usage"]["referenced"]
    assert first["reader_usage"]["vanilla_catalog"]["size"] is None
    assert first["resource_measurement"]["static_evidence_only"] is True
    assert first["consumers"]
    assert all(
        {
            "consumer",
            "id",
            "field",
            "domain",
            "operation",
            "value",
            "range",
            "conditions",
            "why",
            "counterexample",
        }
        <= row.keys()
        for row in first["rules"]
    )


def test_markdown_report_contains_scope_and_limits(tmp_path):
    report = policy_audit.build(measure=False)
    output = tmp_path / "parameter-report.md"
    policy_audit.write_report(output, report)
    text = output.read_text(encoding="utf-8")
    assert "参数注册" in text
    assert "static_evidence_only" in text
    assert "vanilla_catalog" in text


def test_relative_comparison_fixture_uses_distinct_valid_same_unit_values():
    policy = _policy()
    income = policy.readers[0]
    other = replace(income, key="other")
    condition = decision_rules.Predicate(
        income.key, ">", decision_rules.FactReference(other.key, other.reference())
    )
    rule = replace(policy.rules[0], conditions=(condition,))
    policy = replace(policy, readers=(income, other), rules=(rule,))
    row = policy_audit.audit_rule(policy, rule, consumer="relative")
    assert (
        row["checks"]["satisfying"]["inputs"][income.key]
        > row["checks"]["satisfying"]["inputs"][other.key]
    )
    assert row["conditions"][0]["value"] == {"fact": "other"}
    assert all(not result for point in row["sensitivity"] for result in point["fallbacks"].values())


def test_contradictory_or_missing_reader_contract_cannot_be_reported_as_passed():
    policy = _policy()
    rule = replace(
        policy.rules[0],
        conditions=(
            decision_rules.Predicate("war", "=", True),
            decision_rules.Predicate("war", "=", False),
        ),
    )
    with pytest.raises(ValueError, match="无法构造满足"):
        policy_audit.audit_rule(replace(policy, rules=(rule,)), rule, consumer="contradictory")
    with pytest.raises(ValueError, match="缺少"):
        policy_audit.audit_rule(replace(policy, readers=()), policy.rules[0], consumer="missing")


def test_exact_production_counts_are_computed_from_source_not_discovery_index():
    report = policy_audit.build(measure=False)
    info = decision_rules.load()
    adapters = decision_adapters.load()
    assert len(report["rules"]) == len(info.rules) + sum(
        len(policy.rules) for _, policy in adapters.policies
    )
    assert report["field_count"] == len(info.groups()) + sum(
        len(policy.groups()) for _, policy in adapters.policies
    )
    usage = report["reader_usage"]
    assert usage["per_consumer_declaration_slots"] == len(info.readers) + sum(
        len(policy.readers) for _, policy in adapters.policies
    )
    assert usage["unique_signatures"] == len(usage["signatures"])
    assert usage["duplicate_signature_count"] > 0


def test_resource_measurement_preserves_callers_tracemalloc():
    import tracemalloc

    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="独占"):
            policy_audit.build(measure=True)
        assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()


def test_cli_writes_only_requested_output_and_reports_invalid_configuration(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    assert policy_audit.main(["--out", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["resource_measurement"]["measured"] is True
    assert list(tmp_path.iterdir()) == [output]

    def broken_load():
        raise ValueError("bad configuration")

    monkeypatch.setattr(decision_rules, "load", broken_load)
    with pytest.raises(ValueError, match="bad configuration"):
        policy_audit.build(measure=True)
    import tracemalloc

    assert not tracemalloc.is_tracing()


def test_broken_reference_result_cannot_be_hidden(monkeypatch):
    policy = _policy()
    monkeypatch.setattr(decision_rules, "evaluate", lambda *_args, **_kwargs: {})
    with pytest.raises(ValueError, match="满足输入没有命中"):
        policy_audit.audit_rule(policy, policy.rules[0], consumer="broken")


def test_country_registry_covers_routes_budgets_thresholds_and_lifecycle():
    report = country_parameters.audit()
    paths = {tuple(row["path"]) for row in report["parameters"]}
    assert {("variable_ttl_days",), ("switch_cooldown_days",), ("update_days",)} <= paths
    assert {"routes", "budgets"} <= {path[0] for path in paths}
    assert {path[1] for path in paths if path[0] == "routes"} == {
        "defense",
        "fiscal_recovery",
        "stability",
        "industry",
        "education",
        "maritime",
    }
    assert all(
        row["why"] and row["counterexample"] and row["sensitivity"] for row in report["parameters"]
    )
    assert {name: row["route"] for name, row in report["scenarios"].items()} == {
        "Russia_education": "education",
        "Russia_war": "defense",
        "Netherlands_maritime": "maritime",
        "Prussia_industry": "industry",
        "Austria_stability": "stability",
        "France_fiscal": "fiscal_recovery",
        "small_admin_shortage": None,
        "landlocked": None,
        "colonial_subject": None,
        "default_and_war": "defense",
    }
