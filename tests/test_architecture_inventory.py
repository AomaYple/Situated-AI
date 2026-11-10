"""A0 evidence must enumerate identities without promoting old proofs."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from typing import Any

import pytest

from pdx.parser import parse_text
from pdx.situated import compiler, network_profile, production_profile, r2_reader_authority
from pdx.version_contracts import active_version, select_version
from tools.ci import architecture_inventory as inventory


def test_declarations_keep_namespaces_positions_and_old_disposition():
    rows = inventory.declaration_rows(
        {
            "readers": {"same": {"scope": "root"}},
            "actions": [{"id": "same"}, {"id": "same"}],
            "bindings": [{"binding_id": "old", "disposition": "migrate"}],
        },
        "mod/decisions/example.toml",
    )
    assert len(rows) == 4
    assert len({(row["kind"], row["original_pointer"]) for row in rows}) == 4
    assert {row["disposition"] for row in rows} == {"pending_reproof"}
    assert all(row["automatic_inheritance"] is False for row in rows)
    old = next(row for row in rows if row["id"] == "old")
    assert old["original"]["disposition"] == "migrate"


def test_duplicate_consumer_path_cannot_silently_pick_first():
    root = parse_text("a = { value = 1 } a = { value = 2 }").root
    with pytest.raises(ValueError, match="expected one block"):
        inventory.select_block(root, ["a"])


def test_fact_source_requires_exact_assignment_and_preserves_context():
    raw = b'# literacy_rate = 8\na = { not_literacy_rate = 3 text = "literacy_rate" literacy_rate > 0.5 }'
    rows = inventory.source_occurrences(raw, "native.txt", "literacy_rate")
    assert len(rows) == 1
    assert rows[0]["parents"] == ["a"]
    assert rows[0]["operator"] == ">"
    assert rows[0]["value"] == "0.5"
    assert rows[0]["line"] == 2


def test_metrics_retain_repeated_operations_and_anonymous_blocks():
    root = parse_text("a = { add = 1 add = 2 any_scope_state = { b = { 1 2 } } { c = 3 } }").root
    metrics = inventory.block_metrics(inventory.select_block(root, ["a"]))
    assert metrics["duplicate_assignments"] == {"add": 1}
    assert metrics["query_forms"] == {"any_scope_state": 1}
    assert metrics["block_depth"] == 2
    assert metrics["assignments"] == 5


def test_actor_coverage_cannot_filter_unreachable_tags_or_dynamic_countries(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "fact_sources", lambda _game: [])
    source: dict[str, Any] = {
        "inventory_sha256": "a" * 64,
        "actor_universe": {
            "actors": ["ZZZ", "AAA"],
            "definitions": [{"actor": "AAA", "source": {"path": "countries.txt", "line": 1}}],
            "runtime_actor_set": "unknown",
        },
        "failures": [],
    }
    result = inventory.observation_inventory(source, tmp_path)
    assert result["static_rows"] == 6
    assert result["dynamic_rows"] == 3
    assert {row["actor"] for row in result["rows"]} == {"AAA", "ZZZ", "*DYNAMIC_COUNTRY*"}
    assert all(row["consumer_wiring"] == "not_assessed_by_A0_enumeration" for row in result["rows"])
    assert all(row["runtime_observation"] == "unknown" for row in result["rows"])
    assert all(row["ttl"] == "this_consumer_evaluation" for row in result["rows"])
    assert result["excluded_actors"] == []


def test_failures_retained_with_selected_source_blocking_and_external_limits():
    paths = [
        inventory.SLICES[0]["source"],
        "game/common/dna_data/example.txt",
        "game/gfx/models/portraits/example.asset",
        "game/licenses/software/example.txt",
        "game/unexpected.txt",
    ]
    rows = inventory.classify_failures({"failures": [{"path": path} for path in paths]})
    assert len(rows) == len(paths)
    assert rows[0]["impact"] == "blocks_selected_consumer_contract"
    assert rows[-1]["impact"] == "unclassified_requires_review"
    assert all("not_suppressed" in row["disposition"] for row in rows)
    missing = inventory.classify_failures({"failures": [{"kind": "unknown"}]})
    assert missing[0]["impact"] == "unclassified_requires_review"


def test_migration_uses_expanded_compiler_writers_and_reader_shapes(monkeypatch):
    with select_version("1.14.5"):
        model = compiler.load_model()
    monkeypatch.setattr(compiler, "load_model", lambda: model)
    result = inventory.migration_inventory()
    writers = [row for row in result["rows"] if row["kind"] == "compiled_writer"]
    assert model.consumer_ir is not None
    assert {row["id"] for row in writers} == {item.writer_id for item in model.consumer_ir.writers}
    readers = [row for row in result["rows"] if row["kind"] == "compiled_reader_binding"]
    assert len(readers) == len(model.observation_contracts)
    assert len(readers) > result["counts"]["declared_reader"]
    assert all(row["frozen_signature"] for row in readers)
    assert all(row["disposition"] == "pending_reproof" for row in result["rows"])
    assert result["counts"]["compiled_action"] == len(model.action_instances)
    assert result["counts"]["declared_binding"] == len(model.binding_rows)


def test_measure_keeps_failure_output_and_command_tree_rss():
    result = inventory.measure(
        [sys.executable, "-B", "-c", "print('expected failure'); raise SystemExit(3)"]
    )
    assert result["exit_code"] == 3
    assert "expected failure" in result["output"]
    assert result["wall_seconds"] > 0
    assert result["samples"] >= 1
    assert result["rss_measurement"] == "sampled_lower_bound; observer_excluded"


def test_measure_uses_selected_game_root_even_with_inherited_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("V3_ROOT", str(tmp_path / "wrong-game"))
    game = tmp_path / "selected-game"
    result = inventory.measure(
        [sys.executable, "-B", "-c", "import os; print(os.environ['V3_ROOT'])"], game=game
    )
    assert result["exit_code"] == 0
    assert result["V3_ROOT"] == str(game.resolve())
    assert result["output"].strip() == str(game.resolve())


@pytest.mark.parametrize("parent_version", ["1.14.5", "1.15.0"])
@pytest.mark.parametrize("selected_version", ["1.14.5", "1.15.0"])
def test_measure_explicit_contract_reaches_the_real_child(
    monkeypatch, parent_version, selected_version
):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", parent_version)
    result = inventory.measure(
        [
            sys.executable,
            "-B",
            "-c",
            "from pdx.version_contracts import active_version; print(active_version())",
        ],
        contract_version=selected_version,
    )
    assert result["exit_code"] == 0
    assert result["V3_CONTRACT_PROFILE"] == selected_version
    assert result["output"].strip() == selected_version
    assert active_version() == parent_version


@pytest.mark.parametrize("parent_version", ["1.14.5", "1.15.0"])
def test_offline_worker_keeps_the_real_historical_model(
    monkeypatch, capsys, tmp_path, parent_version
):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", parent_version)
    inventory.worker("offline_model", tmp_path)
    observed = json.loads(capsys.readouterr().out)
    assert observed["contract_version"] == "1.14.5"
    assert observed["action_instances"] == 5742
    assert observed["writers"] == 5775
    assert active_version() == parent_version


@pytest.mark.parametrize("parent_version", ["1.14.5", "1.15.0"])
@pytest.mark.parametrize("r2", [False, True])
def test_measurement_can_write_outside_repository_with_bound_input(
    monkeypatch, tmp_path, r2, parent_version
):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", parent_version)
    output = tmp_path / "output"
    source = tmp_path / "inventory.json"
    source.write_bytes(b"{}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "architecture_inventory",
            "--game-root",
            str(tmp_path / "game"),
            "--inventory",
            str(source),
            "--output",
            str(output),
            "--measure",
        ]
        + (["--r2"] if r2 else []),
    )
    monkeypatch.setattr(inventory, "validate_inventory", lambda *_: None)
    monkeypatch.setattr(inventory, "migration_inventory", lambda: {"counts": {}})
    monkeypatch.setattr(
        inventory, "observation_inventory", lambda *_: {"actor_count": 0, "rows": []}
    )
    monkeypatch.setattr(inventory, "static_samples", lambda *_: {"samples": []})
    monkeypatch.setattr(inventory, "configuration_inventory", lambda *_: {})
    monkeypatch.setattr(inventory, "objectives", lambda *_: {})
    monkeypatch.setattr(inventory, "capability_inventory", lambda *_: {})
    monkeypatch.setattr(
        inventory, "r2_profile_baseline", lambda *_: {"budget_violations": [], "actual_r2": True}
    )
    calls = []
    selected_versions = []

    def measured(command, **kwargs):
        calls.append(command)
        selected_versions.append(kwargs.get("contract_version"))
        # A failing old generator remains a failing workload in the receipt.
        return {"output": "measured", "exit_code": 3 if "modgen" in command else 0}

    monkeypatch.setattr(inventory, "measure", measured)
    assert inventory.main() == 0
    cost = json.loads((output / "cost-baseline.json").read_text(encoding="utf-8"))
    assert cost["input_inventory_sha256"] == inventory.digest(b"{}")
    for measurement in cost["measurements"]:
        assert (output / measurement["log"]).read_text(encoding="utf-8") == "measured"
    assert len(calls) == (4 if r2 else 3)
    assert selected_versions == ["1.15.0", "1.14.5", "1.14.5"] + (["1.15.0"] if r2 else [])
    assert [row["contract_version"] for row in cost["measurements"]] == selected_versions
    assert cost["parallelism"] == 1
    assert (
        next(row for row in cost["measurements"] if row["id"] == "old_generator_on_local_1.15")[
            "exit_code"
        ]
        == 3
    )
    assert any(command[-1] == "r2_profile" for command in calls) is r2
    static = json.loads((output / "static-baseline.json").read_text(encoding="utf-8"))
    if r2:
        assert static["r2_profile"]["actual_r2"] is True
        assert cost["r2_profile"] == static["r2_profile"]
    else:
        assert "r2_profile" not in static
        assert cost["r2_profile"] is None


def test_configuration_output_cannot_overwrite_input(monkeypatch, tmp_path):
    source = tmp_path / "configuration-baseline.json"
    source.write_bytes(b"{}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "architecture_inventory",
            "--game-root",
            str(tmp_path / "game"),
            "--inventory",
            str(source),
            "--output",
            str(tmp_path),
        ],
    )
    with pytest.raises(ValueError, match="overwrite input inventory"):
        inventory.main()
    assert source.read_bytes() == b"{}"


def test_json_and_scan_identity_reject_untrusted_or_drifted_inputs(tmp_path):
    with pytest.raises(ValueError, match="duplicate JSON key"):
        inventory.read_inventory(b'{"schema": 1, "schema": 2}')
    with pytest.raises(ValueError, match="output"):
        inventory.validate_output(tmp_path, tmp_path / "evidence")
    required = {spec["source"] for spec in inventory.SLICES}
    required.update(item[4] for item in inventory.FACTS)
    required.add("launcher/launcher-settings.json")
    files = []
    for name in sorted(required):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"a = { value = 1 }")
        files.append(
            {"path": name, "sha256": inventory.digest(path.read_bytes()), "parse_status": "parsed"}
        )
    source: dict[str, Any] = {
        "schema": "situated-ai.native-inventory/1",
        "expected_version": "1.15.0",
        "files": files,
        "version_identity": {
            "version_match": True,
            "launcher": {"path": "launcher/launcher-settings.json", "sha256": files[-1]["sha256"]},
            "files": [],
        },
        "failures": [{"path": "game/common/dna_data/limited.txt"}],
        "actor_universe": {"actors": [], "definitions": []},
        "scanner": {
            "module": "pdx.situated.version_inventory",
            "sources": [
                {
                    "path": "src/pdx/parser.py",
                    "sha256": inventory.digest((inventory.ROOT / "src/pdx/parser.py").read_bytes()),
                }
            ],
        },
    }

    def seal():
        source.pop("inventory_sha256", None)
        raw = (json.dumps(source, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        source["inventory_sha256"] = inventory.digest(raw)

    seal()
    inventory.validate_inventory(source, tmp_path)
    source["version_identity"]["version_match"] = False
    seal()
    with pytest.raises(ValueError, match="version identity"):
        inventory.validate_inventory(source, tmp_path)
    source["version_identity"]["version_match"] = True
    source["expected_version"] = "1.14.5"
    seal()
    with pytest.raises(ValueError, match="schema/version"):
        inventory.validate_inventory(source, tmp_path)
    source["expected_version"] = "1.15.0"
    scanner_source = source["scanner"]["sources"][0]
    expected_hash = scanner_source["sha256"]
    scanner_source["sha256"] = "0" * 64
    seal()
    with pytest.raises(ValueError, match="scanner source drift"):
        inventory.validate_inventory(source, tmp_path)
    scanner_source["sha256"] = expected_hash
    seal()
    source["expected_version"] = "1.14.5"
    with pytest.raises(ValueError, match="fingerprint"):
        inventory.validate_inventory(source, tmp_path)
    source["expected_version"] = "1.15.0"
    seal()
    (tmp_path / inventory.SLICES[0]["source"]).write_bytes(b"drift")
    with pytest.raises(ValueError, match="drift"):
        inventory.validate_inventory(source, tmp_path)
    (tmp_path / inventory.SLICES[0]["source"]).write_bytes(b"a = { value = 1 }")
    files.append(files[0])
    seal()
    with pytest.raises(ValueError, match="duplicate"):
        inventory.validate_inventory(source, tmp_path)


def test_r2_capabilities_reject_partial_drifted_and_missing_context(monkeypatch, tmp_path):
    relative = "game/capability.txt"
    documentation = "game/contract.md"
    monkeypatch.setattr(inventory, "R2_CAPABILITY_SOURCES", {relative: ("influence",)})
    monkeypatch.setattr(inventory, "R2_DOCUMENTATION_ANCHORS", {documentation: ("root country",)})
    (tmp_path / "game").mkdir()
    (tmp_path / relative).write_bytes(b"a = { will_propose = { influence < 200 } }")
    (tmp_path / documentation).write_bytes(b"AI root country")
    source: dict[str, Any] = {
        "inventory_sha256": "a" * 64,
        "files": [
            {
                "path": relative,
                "parse_status": "parsed",
                "sha256": inventory.digest((tmp_path / relative).read_bytes()),
            },
            {
                "path": documentation,
                "parse_status": "not_pdx",
                "sha256": inventory.digest((tmp_path / documentation).read_bytes()),
            },
        ],
    }
    result = inventory.capability_inventory(source, tmp_path)
    assignment = next(row for row in result["sources"] if row["path"] == relative)["assignments"][
        "influence"
    ][0]
    assert assignment["parents"] == ["a", "will_propose"]
    assert result["runtime"] == "unknown; game not started"
    assert result["proposed_minimum"]["consumer_extension_required"] is False
    files: Any = source["files"]
    files[0]["parse_status"] = "partial"
    with pytest.raises(ValueError, match="incomplete capability"):
        inventory.capability_inventory(source, tmp_path)
    files[0]["parse_status"] = "parsed"
    (tmp_path / relative).write_bytes(b"changed")
    with pytest.raises(ValueError, match="capability source drift"):
        inventory.capability_inventory(source, tmp_path)
    files[0]["sha256"] = inventory.digest(b"changed")
    with pytest.raises(ValueError, match="assignment missing"):
        inventory.capability_inventory(source, tmp_path)


def test_scanner_identity_failure_requires_rescan_not_asset_classification():
    result = inventory.classify_failures(
        {"failures": [{"kind": "scanner_source_changed_during_scan", "path": "src/pdx/parser.py"}]}
    )
    assert result[0]["impact"] == "blocks_source_identity; rescan_required"


@pytest.fixture(scope="module")
def r2_baseline():
    # The independently frozen original reader closure is a real versioned
    # input. No installation-wide scan or game process is needed by this test.
    return inventory.r2_profile_baseline(r2_reader_authority.FROZEN_ROOT)


def test_r2_baseline_runs_actual_native_parser_compile_and_build(r2_baseline):
    assert r2_baseline["game_version"] == "1.15.0"
    assert r2_baseline["evidence_kind"] == "actual_offline_compile_and_generation"
    assert len(r2_baseline["reader_authority"]["files"]) == 17
    assert len(r2_baseline["native_parsed_sources"]) > 3
    assert len(r2_baseline["generated_files"]) == 3
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
    profile = production_profile.load_profile(production_profile.BASELINE_ROOT)
    program = network_profile.compile_profile(profile)[0]
    tightened = replace(program.network.budget, max_bridges=1, max_edges=1, max_guard_nodes=1)
    result = inventory.r2_program_metrics(
        replace(program, network=replace(program.network, budget=tightened))
    )
    assert result["declared_budget"]["max_bridges"] == 1
    assert result["budget_checks"]["max_bridges"]["passed"] is False
    assert result["budget_checks"]["max_edges"]["passed"] is False
    assert result["budget_checks"]["max_guard_nodes"]["passed"] is False


def test_r2_metrics_read_actual_built_overlay_and_keep_violations(monkeypatch):
    build = network_profile.build

    def modified(*args, **kwargs):
        outputs = build(*args, **kwargs)
        path = "common/decrees/00_decree.txt"
        marker = "# SITAI POLICY 1.15.0 END a0-econ-road"
        # Native tail queries must be excluded, but a newly emitted world
        # iterator cannot hide behind the compiler's otherwise valid program.
        injection = "every_country = { " + "nested = { " * 12 + "value = 1 " + "} " * 13
        outputs[path] = outputs[path].replace(marker, injection + "\n\t" + marker)
        return outputs

    monkeypatch.setattr(network_profile, "build", modified)
    report = inventory.r2_profile_baseline(r2_reader_authority.FROZEN_ROOT)
    assert report["budget_status"] == "failed"
    violated = {item["budget"] for item in report["budget_violations"]}
    assert "additional_iterators" in violated
    assert "additional_global_scans" in violated
    assert "additional_consumer_block_depth" in violated
    road = next(row for row in report["programs"] if row["consumer"] == "a0-econ-road")
    assert road["overlay_ast"]["query_forms"] == {"every_country": 1}


@pytest.mark.parametrize("parent_version", ["1.14.5", "1.15.0"])
@pytest.mark.parametrize("violations", [[], [{"budget": "excess"}]])
def test_r2_worker_emits_budget_receipt_and_fails_on_excess(
    monkeypatch, capsys, tmp_path, violations, parent_version
):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", parent_version)
    report = {"budget_violations": violations, "runtime": "unknown"}
    calls = []

    def baseline(game):
        calls.append((game, active_version()))
        return report

    monkeypatch.setattr(inventory, "r2_profile_baseline", baseline)
    if violations:
        with pytest.raises(ValueError, match="exceeds declared budgets"):
            inventory.worker("r2_profile", tmp_path)
    else:
        inventory.worker("r2_profile", tmp_path)
    assert calls == [(tmp_path, "1.15.0")]
    assert json.loads(capsys.readouterr().out) == report
    assert active_version() == parent_version
