"""Migrated opportunity evidence retains both versions and complete native inputs."""

from __future__ import annotations

import hashlib

import pytest

from pdx import (
    config,
    equipment_opportunities,
    mobilization_opportunities,
    technology_opportunities,
    treaty_opportunities,
    version_contracts,
)


@pytest.mark.parametrize(
    "module", [equipment_opportunities, treaty_opportunities, mobilization_opportunities]
)
def test_artifact_and_pin_follow_the_explicit_version_without_rewriting_history(module):
    original = module.BASELINE.read_bytes()
    with version_contracts.select_version("1.14.5"):
        assert module.baseline_path() == module.BASELINE
        assert hashlib.sha256(original).hexdigest() == module.baseline_sha256()
        historical = module.load_baseline()
    with version_contracts.select_version("1.15.0"):
        assert module.baseline_path() != module.BASELINE
        assert (
            hashlib.sha256(module.baseline_path().read_bytes()).hexdigest()
            == module.baseline_sha256()
        )
        migrated = module.load_baseline()
    assert module.BASELINE.read_bytes() == original
    assert set(migrated["candidates"]) == set(historical["candidates"])


def test_115_equipment_materials_reconstruct_the_changed_native_baskets():
    with version_contracts.select_version("1.15.0"):
        current = equipment_opportunities.load_baseline()
    candidates = current["candidates"]
    assert candidates["ship_mod_aircraft_carrier_armor_high"]["construction_goods"] == {
        "steel": "435"
    }
    assert "copper" in candidates["ship_mod_early_troop_ship_armor_high"]["ordinary_goods"]
    assert "oil" in candidates["ship_mod_dreadnought_propulsion_light"]["ordinary_goods"]
    assert candidates["ship_mod_iron_frigate_guns_high"]["ordinary_goods"] == ["artillery"]


def test_technology_query_catalog_does_not_leak_between_version_contexts():
    with version_contracts.select_version("1.14.5"):
        historical = technology_opportunities._query_catalog()
        assert "copper" not in historical["goods"]
    with version_contracts.select_version("1.15.0"):
        migrated = technology_opportunities._query_catalog()
        assert "copper" in migrated["goods"]
        assert len(migrated["sources"]) == 83
        assert len(migrated["technologies"]) == 135
        assert len(migrated["native_retained"]) == 44
        assert set(migrated["technologies"]).isdisjoint(migrated["native_retained"])
    with version_contracts.select_version("1.14.5"):
        assert technology_opportunities._query_catalog() is historical


@pytest.mark.integration
def test_selected_technology_catalog_rebuilds_all_mechanisms_and_consumer_dispositions():
    selected = technology_opportunities.load_catalog()
    inputs = {
        source: (config.GAME / source).read_text(encoding="utf-8-sig")
        for source in selected["sources"]
    }
    assert technology_opportunities.verify_inputs(inputs) == {
        key: value for key, value in selected.items() if key != "legacy_rules"
    }
