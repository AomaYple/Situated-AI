"""Historical identities need explicit, source-bound current dispositions."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from pdx.version_contracts import select_version
from tools.ci import architecture_inventory as a0
from tools.ci import migration_dispositions as migration


def test_cli_help_script_and_module_entries_are_equivalent():
    root = Path(__file__).resolve().parents[1]
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    outputs = []
    for entry in (
        (str(root / "tools/ci/migration_dispositions.py"),),
        ("-m", "tools.ci.migration_dispositions"),
    ):
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", *entry, "--help"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        outputs.append(result.stdout)
    # Python 3.14 renders the script and -m invocation differently in usage.
    # Their description and complete option contracts must still be identical.
    assert outputs[0].split("\n\n", 1)[1] == outputs[1].split("\n\n", 1)[1]
    assert "--inventory" in outputs[0]
    assert "--game-root" in outputs[0]
    assert "--output" in outputs[0]


@pytest.fixture
def sample():
    old = {
        "kind": "compiled_writer",
        "id": "old-writer",
        "original_source": "common/example.txt",
        "original_pointer": "example-rule",
        "consumer_field": "example.ai_weight",
        "actor": "root",
        "target": "none",
        "operation": "multiply",
        "disposition": "pending_reproof",
    }
    historical = {"rows": [old], "counts": {"compiled_writer": 1}, "sources": []}
    authority: dict[str, Any] = {
        "historical_rows_sha256": migration.fingerprint(historical["rows"]),
        "historical_counts": historical["counts"],
        "historical_sources": [],
        "historical_generated_sources": {"common/example.txt": "a" * 64},
        "exceptions": [],
        "scope_decision": {
            "r2_production_consumers": [row["id"].lower() for row in a0.SLICES],
            "policy_source": "mod/decisions/action_network_115.toml",
            "rationale": "Old policies have no R2 write permission; retain native behavior.",
        },
    }
    r2 = {
        "source": authority["scope_decision"]["policy_source"],
        "consumers": [
            {
                "id": row["id"].lower(),
                "source": row["source"],
                "field": row["field"],
                "action": f"new-{row['id'].lower()}",
                "bridges": [f"bridge-{row['id'].lower()}"],
            }
            for row in a0.SLICES
        ],
        "native_preservation": [
            {"source": row["source"], "restored_equals_native": True} for row in a0.SLICES
        ],
    }
    return historical, copy.deepcopy(historical), authority, r2


def test_identity_retention_grants_no_production_permission(sample):
    historical, current, authority, r2 = sample
    report = migration.review(*sample)
    row = report["rows"][0]
    assert row["original"] == historical["rows"][0]
    assert row["original_record_sha256"] == migration.fingerprint(historical["rows"][0])
    assert row["engineering_disposition"] == "identity_retained_in_compatibility_compiler"
    assert row["r2_disposition"] == "retired_from_r2_policy_native_retained"
    assert row["r2_mapping"] is None
    assert row["r2_business_semantics_inherited"] is False
    assert row["runtime"] == "unknown"
    assert historical == current
    assert not authority["exceptions"]
    assert len(r2["consumers"]) == 3


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "contradictory"])
def test_missing_duplicate_and_contradictory_dispositions_fail(sample, mutation):
    expected = migration.review(*sample)
    actual = copy.deepcopy(expected)
    if mutation == "missing":
        actual["rows"].clear()
    elif mutation == "duplicate":
        actual["rows"].append(actual["rows"][0])
    else:
        actual["rows"][0]["r2_disposition"] = "replaced_by_action_bridge_policy"
    with pytest.raises(ValueError, match=r"disposition|duplicate"):
        migration.validate_report(actual, expected)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("original_source", "common/other.txt"),
        ("consumer_field", "other.ai_weight"),
        ("operation", "add"),
        ("id", "renamed-writer"),
    ],
)
def test_changed_source_field_or_writer_requires_an_explicit_exception(sample, field, value):
    _, current, _, _ = sample
    current["rows"][0][field] = value
    with pytest.raises(ValueError, match="unreviewed engineering"):
        migration.review(*sample)


def test_reviewed_version_replacement_is_exact_and_cannot_bless_later_drift(sample):
    historical, current, authority, _ = sample
    current["rows"][0]["operation"] = "add"
    authority["exceptions"] = [
        {
            "identity": list(migration.identity(historical["rows"][0])),
            "historical_sha256": migration.fingerprint(
                migration.semantic_record(historical["rows"][0])
            ),
            "current_sha256": migration.fingerprint(migration.semantic_record(current["rows"][0])),
            "engineering_disposition": "version_specific_replacement",
            "rationale": "Reviewed exact operator change, without inheriting old numerical policy.",
        }
    ]
    assert (
        migration.review(*sample)["rows"][0]["engineering_disposition"]
        == "version_specific_replacement"
    )
    current["rows"][0]["target"] = "different-target"
    with pytest.raises(ValueError, match="unreviewed engineering"):
        migration.review(*sample)


def test_exact_new_consumer_field_maps_to_action_and_bridges(sample):
    historical, current, authority, r2 = sample
    point = r2["consumers"][1]
    for data in (historical, current):
        row = data["rows"][0]
        row["original_source"] = point["source"].removeprefix("game/")
        row["consumer_field"] = ".".join(point["field"])
    authority["historical_rows_sha256"] = migration.fingerprint(historical["rows"])
    authority["historical_generated_sources"][point["source"].removeprefix("game/")] = "b" * 64
    row = migration.review(*sample)["rows"][0]
    assert row["r2_disposition"] == "replaced_by_action_bridge_policy"
    assert row["r2_mapping"]["bridges"] == point["bridges"]
    r2["consumers"][1]["field"] = ["different"]
    with pytest.raises(ValueError, match="R2 policy"):
        migration.review(*sample)


def test_information_field_redirect_requires_explicit_old_and_new_identities(sample):
    historical, current, authority, r2 = sample
    for data in (historical, current):
        row = data["rows"][0]
        row["original_source"] = "mod/decisions/information.toml"
        row["consumer_field"] = "institution_scores.institution_schools"
    authority["historical_rows_sha256"] = migration.fingerprint(historical["rows"])
    authority["historical_generated_sources"]["decisions/information.toml"] = "b" * 64
    authority["physical_redirects"] = [
        {
            "historical_source": "mod/decisions/information.toml",
            "historical_field": ["institution_scores", "institution_schools"],
            "r2_consumer": "a0-pol-schools",
            "rationale": "Historical information consumer lowers to the default strategy school score.",
        }
    ]
    assert migration.review(*sample)["rows"][0]["r2_mapping"] == r2["consumers"][1]
    authority["physical_redirects"].append(authority["physical_redirects"][0])
    with pytest.raises(ValueError, match="contradictory historical"):
        migration.review(*sample)


def test_historical_source_and_authority_byte_drift_are_rejected(sample, tmp_path):
    historical, _, authority, _ = sample
    historical["sources"] = [{"path": "old.toml", "sha256": "a" * 64}]
    authority["historical_sources"] = [{"path": "old.toml", "sha256": "b" * 64}]
    with pytest.raises(ValueError, match="declaration source drift"):
        migration.review(*sample)
    path = tmp_path / "authority.json"
    path.write_bytes(migration.AUTHORITY.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="authority byte drift"):
        migration.load_authority(path)


def test_original_scan_failures_cannot_disappear_or_overlap_consumed_files():
    authority = migration.load_authority()
    expected = authority["original_scan_failures"]
    native = {
        "files": [
            {
                "path": row["failure"]["path"],
                "sha256": row["source_sha256"],
                "bytes": row["source_bytes"],
            }
            for row in expected
        ],
        "failures": [row["failure"] for row in expected],
    }
    rows = migration.failure_dispositions(native, authority, set())
    assert len(rows) == 17
    assert Counter(row["failure"]["path"].split("/")[2] for row in rows)["software"] == 1
    assert all(row["global_catalog"] == "incomplete" for row in rows)
    assert all(row["consumed_reader_writer_overlap"] == [] for row in rows)
    with pytest.raises(ValueError, match="overlaps consumed"):
        migration.failure_dispositions(native, authority, {rows[0]["failure"]["path"]})
    native["files"][0]["sha256"] = "changed"
    with pytest.raises(ValueError, match="source/diagnostic drift"):
        migration.failure_dispositions(native, authority, set())
    native["failures"].pop()
    with pytest.raises(ValueError, match="disappeared"):
        migration.failure_dispositions(native, authority, set())


def test_non_common_native_sources_enter_the_complete_consumed_closure():
    source = "events/law_events/state_atheism.txt"
    current = {"rows": [], "native_adapter_sources": {"events/adapter.txt": "b" * 64}}
    r2 = {"reader_authority": {"files": [{"path": "jomini/common/engine.txt"}]}}
    hashes = {source: "a" * 64, "@engine/context": "c" * 64, "@evidence/schema": "d" * 64}
    consumed = migration.consumed_sources(current, r2, hashes)
    assert consumed == {"game/" + source, "game/events/adapter.txt", "jomini/common/engine.txt"}
    failure = {"path": "game/" + source, "kind": "decode_or_parse", "error": "ParseError"}
    authority = {
        "original_scan_failures": [
            {"failure": failure, "source_sha256": "a" * 64, "source_bytes": 3}
        ]
    }
    native = {
        "files": [{"path": "game/" + source, "sha256": "a" * 64, "bytes": 3}],
        "failures": [failure],
    }
    with pytest.raises(ValueError, match="overlaps consumed"):
        migration.failure_dispositions(native, authority, consumed)


def test_native_retained_disposition_requires_all_three_preservation_proofs(sample):
    sample[3]["native_preservation"].pop()
    with pytest.raises(ValueError, match="R2 policy"):
        migration.review(*sample)


def test_dynamic_wildcard_cannot_be_lost_duplicated_or_substituted():
    observation: dict[str, Any] = {
        "actor_count": 835,
        "dynamic_rows": 3,
        "runtime_actor_set": "unknown",
        "rows": [{"actor": "*DYNAMIC_COUNTRY*", "slice_id": row["id"]} for row in a0.SLICES],
    }
    assert migration.actor_boundary(observation)["dynamic_rows"] == 3
    observation["rows"][2] = observation["rows"][0]
    with pytest.raises(ValueError, match="dynamic country"):
        migration.actor_boundary(observation)


def test_consumed_native_source_sha_is_checked_independently(tmp_path):
    path = tmp_path / "game/common/example.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"example = {}\n")
    native = {
        "files": [{"path": "game/common/example.txt", "sha256": a0.digest(path.read_bytes())}]
    }
    assert len(migration.current_sources(native, {"game/common/example.txt"}, tmp_path)) == 1
    path.write_bytes(b"example = { changed = yes }\n")
    with pytest.raises(ValueError, match="source identity drift"):
        migration.current_sources(native, {"game/common/example.txt"}, tmp_path)


def test_historical_artifact_bytes_cannot_be_refreshed_from_current_output(tmp_path):
    path = tmp_path / "mod/common/example.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"historical frozen output\n")
    authority = {
        "historical_generated_sources": {"common/example.txt": a0.digest(path.read_bytes())}
    }
    migration.validate_historical_artifacts(authority, tmp_path)
    path.write_bytes(b"new output\n")
    with pytest.raises(ValueError, match="historical generated artifact drift"):
        migration.validate_historical_artifacts(authority, tmp_path)


def test_actual_r2_proves_native_retention_and_rejects_protected_edits():
    from pdx.situated import network_profile, production_profile

    with select_version("1.15.0"):
        profile = production_profile.load_profile(production_profile.BASELINE_ROOT)
        generated = network_profile.build(profile)
        rows = migration.native_preservation(profile, generated, production_profile.BASELINE_ROOT)
        assert len(rows) == 3
        assert all(row["restored_equals_native"] is True for row in rows)
        source = profile.declarations[0].source.removeprefix("game/")
        generated[source] += "\n# protected native text changed\n"
        with pytest.raises(ValueError, match="altered protected native"):
            migration.native_preservation(profile, generated, production_profile.BASELINE_ROOT)
        generated["common/extra-override.txt"] = "unexpected = {}"
        with pytest.raises(ValueError, match="output file set"):
            migration.native_preservation(profile, generated, production_profile.BASELINE_ROOT)


def test_historical_denominator_ignores_a_current_ambient_profile(monkeypatch):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.15.0")
    historical = a0.migration_inventory(version="1.14.5")
    authority = migration.load_authority()
    migration.validate_historical(historical, authority)
    assert len(historical["rows"]) == 22258
    assert json.loads(json.dumps(historical["rows"]))[0]["disposition"] == "pending_reproof"
    manifest = json.loads(
        (a0.ROOT / "research/situated/1.14.5/generated/manifest.json").read_text(encoding="utf-8")
    )
    assert historical["strategy_sources"] == [
        {
            "original_source": "mod/" + row["path"],
            "source_location": "research/situated/1.14.5/generated/" + row["path"],
            "sha256": row["sha256"],
            "bytes": row["bytes"],
        }
        for row in manifest["files"]
    ]
    original_paths = {row["path"] for row in authority["historical_sources"]}
    assert {row["path"] for row in historical["sources"]} == original_paths
    assert {
        path.relative_to(a0.ROOT).as_posix() for path in (a0.ROOT / "mod/decisions").glob("*.toml")
    } > original_paths


def test_current_inventory_includes_current_declarations():
    current = a0.migration_inventory(version="1.15.1")
    expected = {
        path.relative_to(a0.ROOT).as_posix() for path in (a0.ROOT / "mod/decisions").glob("*.toml")
    }
    assert {row["path"] for row in current["sources"]} == expected
    assert all(
        row["source_location"] == row["original_source"] for row in current["strategy_sources"]
    )


@pytest.mark.parametrize("damage", ["missing", "extra", "changed"])
def test_historical_inventory_rejects_strategy_source_drift(tmp_path, damage):
    authority = migration.load_authority()
    for row in authority["historical_sources"]:
        destination = tmp_path / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((a0.ROOT / row["path"]).read_bytes())
    archive = "research/situated/1.14.5/generated/"
    strategies = [
        name
        for name in authority["historical_generated_sources"]
        if name.startswith("common/ai_strategies/")
    ]
    for name in strategies:
        destination = tmp_path / archive / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((a0.ROOT / archive / name).read_bytes())
    original = tmp_path / archive / strategies[0]
    if damage == "missing":
        original.unlink()
    elif damage == "extra":
        (original.parent / "unexpected.txt").write_bytes(b"unexpected = {}\n")
    else:
        original.write_bytes(original.read_bytes() + b"\n# drift\n")
    with pytest.raises(ValueError, match=r"historical strategy source (set )?drift"):
        a0.migration_inventory(tmp_path, version="1.14.5")


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_historical_inventory_rejects_missing_or_changed_original_declarations(tmp_path, damage):
    authority = migration.load_authority()
    for row in authority["historical_sources"]:
        source = a0.ROOT / row["path"]
        destination = tmp_path / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    original = tmp_path / authority["historical_sources"][0]["path"]
    expected: type[FileNotFoundError] | type[ValueError]
    if damage == "missing":
        original.unlink()
        expected = FileNotFoundError
    else:
        original.write_bytes(original.read_bytes() + b"\n# drift\n")
        expected = ValueError
    with pytest.raises(expected):
        a0.migration_inventory(tmp_path, version="1.14.5")
