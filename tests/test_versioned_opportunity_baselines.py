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
    ("module", "count"),
    [(equipment_opportunities, 271), (treaty_opportunities, 34), (mobilization_opportunities, 15)],
)
def test_current_opportunity_artifacts_pin_the_full_candidate_denominator(module, count):
    raw = module.baseline_path().read_bytes()
    assert module.baseline_path().parent.name == version_contracts.CURRENT_VERSION
    assert hashlib.sha256(raw).hexdigest() == module.baseline_sha256()
    assert len(module.load_baseline()["candidates"]) == count


def test_equipment_materials_reconstruct_current_native_baskets():
    current = equipment_opportunities.load_baseline()
    candidates = current["candidates"]
    assert candidates["ship_mod_aircraft_carrier_armor_high"]["construction_goods"] == {
        "steel": "435"
    }
    assert "copper" in candidates["ship_mod_early_troop_ship_armor_high"]["ordinary_goods"]
    assert "oil" in candidates["ship_mod_dreadnought_propulsion_light"]["ordinary_goods"]
    assert candidates["ship_mod_iron_frigate_guns_high"]["ordinary_goods"] == ["artillery"]


def test_technology_query_catalog_accounts_for_current_and_native_retained_technologies():
    catalog = technology_opportunities._query_catalog()
    assert "copper" in catalog["goods"]
    assert len(catalog["sources"]) == 83
    assert len(catalog["technologies"]) == 135
    assert len(catalog["native_retained"]) == 44
    assert set(catalog["technologies"]).isdisjoint(catalog["native_retained"])


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
