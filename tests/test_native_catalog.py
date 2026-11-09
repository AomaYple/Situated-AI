"""Native catalog discovers native fields and dependencies without granting legality."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import pytest

from pdx.situated.native_catalog import build_native_catalog
from pdx.situated.version_inventory import canonical_json

if TYPE_CHECKING:
    from pathlib import Path


def _input(root: Path, sources: dict[str, str]) -> dict[str, Any]:
    files = []
    for name, text in sorted(sources.items()):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        path.write_bytes(raw)
        files.append(
            {
                "path": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "parse_status": "not_pdx" if name.endswith(".md") else "parsed",
            }
        )
    result: dict[str, Any] = {
        "schema": "situated-ai.native-inventory/1",
        "expected_version": "1.15.0",
        "version_identity": {"version_match": True},
        "files": files,
        "failures": [],
        "consumer_candidates": [],
    }
    _seal(result)
    return result


def _seal(inventory: dict[str, Any]) -> None:
    inventory.pop("inventory_sha256", None)
    inventory["inventory_sha256"] = hashlib.sha256(
        canonical_json(inventory).encode("utf-8")
    ).hexdigest()


def test_all_strategy_fields_and_non_ai_map_leaves_keep_occurrences(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path,
        {
            "game/common/ai_strategies/native.txt": """strategy = {
 icon = \"ignore.dds\"
 desired_tax_level = medium
 building_group_weights = { agriculture = 2 industry = { value = 3 } }
 secret_goal_scores = { conquer = { trigger = { always = yes } score = 10 } }
 institution_scores = { police = 1 police = 2 }
} """,
        },
    )
    catalog = build_native_catalog(tmp_path, inventory)
    rows = catalog["consumers"]
    direct = [row for row in rows if row["classification"] == "direct_candidate"]
    assert {row["field"] for row in direct} == {
        "desired_tax_level",
        "building_group_weights.agriculture",
        "building_group_weights.industry",
        "secret_goal_scores.conquer.score",
        "institution_scores.police",
    }
    duplicates = [row for row in direct if row["field"] == "institution_scores.police"]
    assert len(duplicates) == 2
    assert duplicates[0]["consumer_id"] != duplicates[1]["consumer_id"]
    assert duplicates[0]["source"]["address"] != duplicates[1]["source"]["address"]
    assert all(row["legality"] == "unknown" for row in rows)
    assert all(row["native_disposition"] == "native_retained" for row in rows)
    assert catalog["denominator"]["implementation_independent"] is True
    assert catalog["denominator"]["legal_consumers"] == "unknown"


def test_explicit_categories_docs_and_heuristics_are_distinct(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path,
        {
            "game/common/decrees/native.txt": "decree = { ai_weight = { value = 10 } }",
            "game/common/buildings/native.txt": "building = { ai_value = { value = 1 } }",
            "game/common/buildings/buildings.md": (
                "# base AI value\n# scope is state the building is located in\n"
                "ai_value = script value\n"
            ),
            "game/common/diplomatic_actions/native.txt": (
                "action = { ai = { accept_score = { value = 0 } will_propose = {} } }"
            ),
            "game/common/other/native.txt": "thing = { weight = 100 score = 2 }",
        },
    )
    candidate_path = "game/common/other/native.txt"
    digest = next(row["sha256"] for row in inventory["files"] if row["path"] == candidate_path)
    inventory["consumer_candidates"] = [
        {
            "path": candidate_path,
            "sha256": digest,
            "line": 1,
            "address": [0, 0],
            "parents": ["thing"],
            "key": "weight",
            "operator": "=",
        }
    ]
    _seal(inventory)
    catalog = build_native_catalog(tmp_path, inventory)
    rows = catalog["consumers"]
    assert {row["category"] for row in rows if row["classification"] == "direct_candidate"} == {
        "decrees",
        "buildings",
        "diplomatic_actions",
    }
    building = next(row for row in rows if row["category"] == "buildings")
    assert any("scope is state" in evidence["text"] for evidence in building["evidence"])
    assert building["semantics"]["actor_scope"] == "unknown"
    unrelated = next(row for row in rows if row["category"] == "other")
    assert unrelated["classification"] == "unresolved"
    assert "heuristic" in unrelated["discovery_rule"]
    assert unrelated["legality"] == "unknown"


def test_symbol_calls_chaining_cycles_unknown_and_duplicate_definitions(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path,
        {
            "game/common/ai_strategies/native.txt": (
                "strategy = { ai_weight = { value = root.first_value "
                "if = { limit = { can_act = yes } apply_action = yes } "
                "add = scripted_value:missing_value quoted = \"can_act\" "
                "value = \"missing_quoted\" } }"
            ),
            "game/common/script_values/native.txt": (
                "first_value = { value = second_value }\n"
                "second_value = { value = first_value }\n"
                "duplicate_value = 1 duplicate_value = 2\n"
            ),
            "game/common/scripted_triggers/native.txt": "can_act = { always = yes }",
            "game/common/scripted_effects/native.txt": (
                "apply_action = { add = duplicate_value }"
            ),
        },
    )
    catalog = build_native_catalog(tmp_path, inventory)
    references = catalog["references"]
    assert any(row["symbol"] == "can_act" and row["status"] == "resolved" for row in references)
    assert any(
        row["symbol"] == "apply_action" and row["status"] == "resolved" for row in references
    )
    assert any(
        row["symbol"] == "first_value" and row["expression"] == "root.first_value"
        for row in references
    )
    assert any(
        row["symbol"] == "missing_value" and row["status"] == "unresolved"
        for row in references
    )
    assert any(
        row["symbol"] == "can_act"
        and row["status"] == "observational"
        and row["syntax"] == "quoted_symbol_observation"
        for row in references
    )
    assert any(
        row["symbol"] == "missing_quoted"
        and row["status"] == "observational"
        and row["syntax"] == "quoted_symbol_observation"
        for row in references
    )
    assert any(
        row["symbol"] == "duplicate_value" and row["status"] == "ambiguous"
        for row in references
    )
    assert len(catalog["dependency_cycles"]) == 1
    assert catalog["dependency_cycles"][0]["symbols"] == ["first_value", "second_value"]
    strategy = next(row for row in catalog["consumers"] if row["field"] == "ai_weight")
    assert strategy["dependencies"]["status"] == "unresolved_or_cyclic"
    assert len(strategy["dependencies"]["reference_ids"]) == 6


def test_parse_failure_limits_are_preserved_and_cannot_prove_completeness(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path,
        {"game/common/ai_strategies/native.txt": "strategy = { ai_weight = { value = 1 }"},
    )
    inventory["files"][0]["parse_status"] = "partial"
    inventory["failures"] = [
        {"kind": "parse", "path": "game/common/ai_strategies/native.txt", "line": 1}
    ]
    _seal(inventory)
    catalog = build_native_catalog(tmp_path, inventory)
    assert catalog["status"] == "incomplete"
    assert catalog["failures"][0]["path"].endswith("native.txt")
    assert catalog["parse_failure_scopes"][0]["scope"] == "whole_file"
    assert catalog["consumers"][0]["source_validity"] == "partial"


def test_input_drift_and_tampering_fail_closed(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path, {"game/common/ai_strategies/native.txt": "strategy = { weight = 1 }"}
    )
    inventory["expected_version"] = "1.14.5"
    with pytest.raises(ValueError, match=r"identity|version"):
        build_native_catalog(tmp_path, inventory)
    inventory["expected_version"] = "1.15.0"
    (tmp_path / inventory["files"][0]["path"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="drift"):
        build_native_catalog(tmp_path, inventory)


def test_resealed_wrong_version_or_identity_match_is_rejected(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path, {"game/common/ai_strategies/native.txt": "strategy = { weight = 1 }"}
    )
    inventory["expected_version"] = "1.14.5"
    _seal(inventory)
    with pytest.raises(ValueError, match="version"):
        build_native_catalog(tmp_path, inventory)
    inventory["expected_version"] = "1.15.0"
    inventory["version_identity"]["version_match"] = False
    _seal(inventory)
    with pytest.raises(ValueError, match="version"):
        build_native_catalog(tmp_path, inventory)


def test_quoted_explicit_symbol_is_observational(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path,
        {
            "game/common/ai_strategies/native.txt": 'strategy = { weight = "scripted_value:foo" }',
            "game/common/script_values/native.txt": "foo = 1",
        },
    )
    catalog = build_native_catalog(tmp_path, inventory)
    assert any(
        row["syntax"] == "quoted_symbol_observation" and row["status"] == "observational"
        for row in catalog["references"]
    )


def test_symlinked_installation_root_is_rejected(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    link = tmp_path / "installation-link"
    try:
        link.symlink_to(source, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")
    inventory = _input(
        source, {"game/common/ai_strategies/native.txt": "strategy = { weight = 1 }"}
    )
    with pytest.raises(ValueError, match="installation root"):
        build_native_catalog(link, inventory)


def test_deterministic_catalog_does_not_read_mod_or_old_lock(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path, {"game/common/ai_strategies/native.txt": "strategy = { weight = 1 }"}
    )
    first = build_native_catalog(tmp_path, inventory)
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod/generation-lock.json").write_text("invalid", encoding="utf-8")
    second = build_native_catalog(tmp_path, inventory)
    assert canonical_json(first) == canonical_json(second)


def test_unlisted_content_is_detected_and_path_traversal_rejected(tmp_path: Path) -> None:
    inventory = _input(
        tmp_path, {"game/common/ai_strategies/native.txt": "strategy = { weight = 1 }"}
    )
    inventory["files"][0]["path"] = "../outside.txt"
    _seal(inventory)
    with pytest.raises(ValueError, match="path"):
        build_native_catalog(tmp_path, inventory)
