"""Current R2 static budgets account for the actual production consumer output."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pdx import config, distribution, version_contracts
from pdx.parser import parse_text
from pdx.situated import network_profile, production_profile
from tools.ci import r2_profile_budget as budget


def test_duplicate_consumer_path_cannot_silently_pick_first():
    root = parse_text("a = { value = 1 } a = { value = 2 }").root
    with pytest.raises(ValueError, match="expected one block"):
        budget.select_block(root, ["a"])


def test_metrics_retain_repeated_operations_and_anonymous_blocks():
    root = parse_text("a = { add = 1 add = 2 any_scope_state = { b = { 1 2 } } { c = 3 } }").root
    metrics = budget.block_metrics(budget.select_block(root, ["a"]))
    assert metrics["duplicate_assignments"] == {"add": 1}
    assert metrics["query_forms"] == {"any_scope_state": 1}
    assert metrics["block_depth"] == 2
    assert metrics["assignments"] == 5


@pytest.fixture(scope="module")
def r2_baseline():
    return budget.r2_profile_baseline(config.ROOT)


@pytest.mark.integration
def test_r2_baseline_runs_actual_native_parser_compile_and_build(r2_baseline):
    assert r2_baseline["game_version"] == version_contracts.CURRENT_VERSION
    assert r2_baseline["evidence_kind"] == "static_check"
    assert len(r2_baseline["reader_authority"]["files"]) == 18
    assert len(r2_baseline["native_parsed_sources"]) > 3
    assert len(r2_baseline["generated_files"]) == 101
    assert {
        "common/decrees/00_decree.txt",
        "common/ai_strategies/00_default_strategy.txt",
        "common/diplomatic_actions/00_relations_actions.txt",
    } <= r2_baseline["generated_files"].keys()
    assert len(r2_baseline["programs"]) == 3
    assert "engine execution" in r2_baseline["runtime"]
    assert r2_baseline["generator_sources"]
    assert r2_baseline["budget_status"] == "passed", r2_baseline["budget_violations"]
    for row in r2_baseline["programs"]:
        assert row["network"]["dag_nodes"] > row["network"]["raw_facts"] > 0
        assert row["network"]["dag_edges"] > 0
        assert row["network"]["pre_expansion_expressions"]
        assert row["network"]["expanded_guard_nodes"] > 0
        assert row["overlay_ast"]["assignments"] > 0
        assert row["overlay_bytes"] > 0
        assert row["generated_file_bytes"] >= row["overlay_bytes"]
        assert row["original_consumer_ast"]["assignments"] > 0
        assert (
            row["generated_consumer_ast"]["assignments"]
            > row["original_consumer_ast"]["assignments"]
        )
        assert row["readers"]["declared"]
        assert row["readers"]["generated_occurrences"]
        for check in row["network"]["budget_checks"].values():
            assert check["passed"] is (check["actual"] <= check["limit"])
        for check in row["local_budget_checks"].values():
            assert check["passed"] is (check["actual"] <= check["limit"])
        objects = row["local_budget_checks"]["selected_candidates_per_evaluation"]
        assert objects == {"actual": 1, "limit": 1, "passed": True}
        assert row["local_budget_checks"]["additional_iterators"]["actual"] == 0


def test_r2_network_cost_uses_predeclared_limits_and_reports_excess():
    profile = production_profile.declared_profile()
    program = network_profile.compile_profile(profile)[0]
    tightened = replace(program.network.budget, max_bridges=1, max_edges=1, max_guard_nodes=1)
    result = budget.r2_program_metrics(
        replace(program, network=replace(program.network, budget=tightened))
    )
    assert result["declared_budget"]["max_bridges"] == 1
    assert result["budget_checks"]["max_bridges"]["passed"] is False
    assert result["budget_checks"]["max_edges"]["passed"] is False
    assert result["budget_checks"]["max_guard_nodes"]["passed"] is False


@pytest.mark.integration
def test_r2_metrics_read_actual_built_overlay_and_keep_violations(monkeypatch):
    build = distribution.package_inputs

    def modified(*args, **kwargs):
        policy, extensions, outputs = build(*args, **kwargs)
        path = "common/decrees/00_decree.txt"
        marker = f"# SITAI POLICY {version_contracts.CURRENT_VERSION} END a0-econ-road"
        original = outputs[path]
        text = original.decode("utf-8") if isinstance(original, bytes) else original
        assert marker in text
        injection = "every_country = { " + "nested = { " * 12 + "value = 1 " + "} " * 13
        outputs[path] = text.replace(marker, injection + "\n\t" + marker, 1)
        return policy, extensions, outputs

    monkeypatch.setattr(distribution, "package_inputs", modified)
    report = budget.r2_profile_baseline(config.ROOT)
    assert report["budget_status"] == "failed"
    violated = {item["budget"] for item in report["budget_violations"]}
    assert {
        "additional_iterators",
        "additional_global_scans",
        "additional_consumer_block_depth",
    } <= violated
    road = next(row for row in report["programs"] if row["consumer"] == "a0-econ-road")
    assert road["overlay_ast"]["query_forms"] == {"every_country": 1}


@pytest.mark.parametrize("violations", [[], [{"budget": "excess"}]])
def test_r2_budget_cli_emits_report_and_fails_on_excess(monkeypatch, capsys, violations):
    report = {"budget_violations": violations, "runtime": "unknown"}
    calls = []

    def baseline(game):
        calls.append(game)
        return report

    monkeypatch.setattr(budget, "r2_profile_baseline", baseline)
    assert budget.main([]) == int(bool(violations))
    assert calls == [config.ROOT]
    assert json.loads(capsys.readouterr().out) == report
