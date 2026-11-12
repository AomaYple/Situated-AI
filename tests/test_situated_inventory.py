"""K0 原版决策面盘点合同。"""

from __future__ import annotations

import json

import pytest
from _situated_sources import production_policy_sources

from pdx import config, version_contracts
from pdx.situated import inventory

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def structure_inventory_has_no_live_game(request, monkeypatch, tmp_path):
    """Pure structure/denominator checks never trigger a live full production build."""
    if request.node.get_closest_marker("integration") is None:
        monkeypatch.setattr(config, "GAME", tmp_path / "unavailable-game")


@pytest.mark.integration
def test_k0_inventory_has_stable_scope_and_verified_production_witnesses() -> None:
    with version_contracts.select_version("1.15.1"):
        first = inventory.discover()
        second = inventory.discover()
    assert first.scope_hash == second.scope_hash
    assert first.discovered_count >= 1412
    assert first.status_counts == {"implemented": first.discovered_count}
    assert first.parse_failures == ()
    assert first.scope_hash
    assert all(item.disposition_id for item in first.surfaces)
    assert all(item.status == "implemented" for item in first.surfaces)
    assert any(item.evidence_state == "production_witnessed" for item in first.surfaces)


def test_k0_inventory_contains_legacy_rules_consumers_and_cards() -> None:
    result = inventory.discover()
    kinds = {item.kind for item in result.surfaces}
    assert kinds == {"legacy_rule", "consumer_contract", "action_card"}
    # Compare every downstream identity with the complete upstream policy inputs.
    # The helper separately checks the independent authored TOML subset.
    assert sum(item.kind == "legacy_rule" for item in result.surfaces) == len(
        production_policy_sources().rules
    )
    assert {
        (item.source, item.definition, item.field)
        for item in result.surfaces
        if item.kind == "legacy_rule"
    } == production_policy_sources().rules
    assert sum(item.kind == "consumer_contract" for item in result.surfaces) >= 8
    assert sum(item.kind == "action_card" for item in result.surfaces) >= 11


def test_k0_migration_preserves_every_current_production_rule() -> None:
    result = inventory.discover()
    migration = inventory.migration(inventory=result)
    assert len(migration.rows) == len(production_policy_sources().rules)
    assert migration.missing_old_rules == ()
    assert migration.duplicate_owners == ()
    assert migration.unclassified_rows == ()
    assert all(row.disposition == "migrate" for row in migration.rows)
    assert all(row.replacement_or_vanilla_tail for row in migration.rows)
    assert migration.missing_old_rules == ()
    assert migration.duplicate_owners == ()
    assert all(row.binding_id for row in migration.rows)


def test_k0_json_contract_is_recomputable(tmp_path) -> None:
    inventory_path, migration_path = inventory.write(tmp_path)
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    migration_payload = json.loads(migration_path.read_text(encoding="utf-8"))
    assert payload["scope_hash"] == inventory.discover().scope_hash
    assert payload["discovered_count"] == sum(payload["status_counts"].values())
    assert len(migration_payload["rows"]) == len(production_policy_sources().rules)


def test_k0_equivalent_baseline_at_another_path_preserves_legacy_rule_denominator(tmp_path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_bytes(inventory.BASELINE.read_bytes())
    result = inventory.discover(baseline=baseline)
    assert sum(item.kind == "legacy_rule" for item in result.surfaces) == len(
        production_policy_sources().rules
    )
    assert len(inventory.migration(baseline=baseline, inventory=result).rows) == len(
        production_policy_sources().rules
    )


def test_k0_invalid_alternate_baseline_keeps_strict_model_validation(tmp_path) -> None:
    baseline = tmp_path / "broken-baseline.txt"
    baseline.write_text("ai_strategy_default = {", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="默认策略底本无法解析"):
        inventory.discover(baseline=baseline)


def test_current_inventory_keeps_failed_generation_pending(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    with version_contracts.select_version("1.15.1"):
        result = inventory.discover()
    assert result.status_counts == {"pending": result.discovered_count}
    assert all(surface.evidence_state != "production_witnessed" for surface in result.surfaces)


def test_historical_inventory_cannot_borrow_current_mod_tree(monkeypatch, tmp_path):
    # This is the actual current tree, not invented historical evidence.
    metadata = json.loads((config.REPO / "mod/.metadata/metadata.json").read_text(encoding="utf-8"))
    assert metadata["supported_game_version"] == "1.15.1"
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    with version_contracts.select_version("1.14.5"):
        result = inventory.discover()
    assert result.status_counts == {"pending": result.discovered_count}
    assert all(surface.evidence_state != "production_witnessed" for surface in result.surfaces)
