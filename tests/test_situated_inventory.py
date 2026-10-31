"""K0 原版决策面盘点合同。"""

from __future__ import annotations

import json

import pytest

from pdx.situated import inventory

pytestmark = pytest.mark.unit


def test_k0_inventory_has_stable_scope_and_verified_production_witnesses() -> None:
    first = inventory.discover()
    second = inventory.discover()
    assert first.scope_hash == second.scope_hash
    assert first.discovered_count == 1412
    assert first.status_counts == {"implemented": 1412}
    assert first.parse_failures == ()
    assert first.scope_hash
    assert all(item.disposition_id for item in first.surfaces)
    assert all(item.status == "implemented" for item in first.surfaces)
    assert any(item.evidence_state == "production_witnessed" for item in first.surfaces)


def test_k0_inventory_contains_legacy_rules_consumers_and_cards() -> None:
    result = inventory.discover()
    kinds = {item.kind for item in result.surfaces}
    assert kinds == {"legacy_rule", "consumer_contract", "action_card"}
    assert sum(item.kind == "legacy_rule" for item in result.surfaces) == 1401
    assert sum(item.kind == "consumer_contract" for item in result.surfaces) == 4
    assert sum(item.kind == "action_card" for item in result.surfaces) == 7


def test_k0_migration_preserves_every_legacy_rule() -> None:
    result = inventory.discover()
    migration = inventory.migration(inventory=result)
    assert len(migration.rows) == 1401
    assert migration.missing_old_rules == ()
    assert migration.duplicate_owners == ()
    assert migration.unclassified_rows == ()
    assert all(row.disposition == "migrate" for row in migration.rows)
    assert all(row.replacement_or_vanilla_tail for row in migration.rows)


def test_k0_json_contract_is_recomputable(tmp_path) -> None:
    inventory_path, migration_path = inventory.write(tmp_path)
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    migration_payload = json.loads(migration_path.read_text(encoding="utf-8"))
    assert payload["scope_hash"] == inventory.discover().scope_hash
    assert payload["discovered_count"] == sum(payload["status_counts"].values())
    assert len(migration_payload["rows"]) == 1401
