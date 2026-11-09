"""A0 evidence must enumerate identities without promoting old proofs."""

from __future__ import annotations

import json
import sys

import pytest

from pdx.parser import parse_text
from pdx.situated import compiler
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
    source = {
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
    assert all(row["consumer_wiring"] == "not_connected_1.15" for row in result["rows"])
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
    source = {
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
