"""Independent, object-specific witnesses for prepared productive research."""

from __future__ import annotations

import copy
import json
import tomllib

import pytest

from pdx import config
from pdx import technology_opportunities as production
from pdx.parser import parse_text
from pdx.situated import pdx_eval

candidate = production
CATALOG = json.loads(
    tomllib.loads(
        (config.REPO / "mod/decisions/technology_opportunities.toml").read_text(encoding="utf-8")
    )["catalog_json"]
)


def world():
    # Fixed raw-native textile recipe: sewing -> electric sewing adds
    # copper2/dye10/electricity10/tools3 and clothes40. This fixture does not
    # call the query selector, derive(), or the production reference scorer.
    building = {
        "is_building_type": {
            (("argument", key),): key == "building_textile_mill" for key in CATALOG["buildings"]
        },
        "has_active_production_method": {
            (("argument", key),): key == "pm_sewing_machines" for key in CATALOG["methods"]
        },
        "level": 1,
    }
    state = {
        "any_scope_building": [building],
        "sg:electricity": {"state_goods_pricier": 0.25},
    }
    return {
        "any_scope_state": [state],
        "any_scope_building": [building],
        "has_technology_researched": {
            (("argument", key),): True for key in CATALOG["technologies"]
        },
        "has_law_or_variant": {
            (("argument", f"law_type:{key}"),): False
            for method in CATALOG["methods"].values()
            for key in method["law_gates"]["disallowing_laws"]
        },
        "market": {
            f"mg:{key}": {"market_goods_delta": -1 if key == "clothes" else 0}
            for key in CATALOG["goods"]
        },
    }


def evaluate(module, data, purpose="productive_ready"):
    query = module.TechnologyUseQuery("electrical_capacitors", purpose)
    parsed = parse_text("ROOT = { " + module.render_query(query) + " }")
    assert not parsed.errors
    return pdx_eval.condition(parsed.root, {"ROOT": data})


def test_real_local_recipe_can_be_ready_without_labor_tightness():
    data = world()
    assert evaluate(candidate, data) is True
    assert evaluate(candidate, data, "productive") is True
    assert "state_unemployment_rate" not in candidate.render_query(
        candidate.TechnologyUseQuery("electrical_capacitors", "productive_ready")
    )


@pytest.mark.parametrize(
    ("price", "expected"), [(0.24999, True), (0.25, True), (0.25001, False), (None, None)]
)
def test_price_boundary_and_unknown_exit_only_prepared_tier(price, expected):
    data = world()
    data["any_scope_state"][0]["sg:electricity"]["state_goods_pricier"] = price
    assert evaluate(candidate, data) is expected
    assert evaluate(candidate, data, "productive") is True


@pytest.mark.parametrize("good", ["copper", "dye", "tools"])
@pytest.mark.parametrize(("balance", "expected"), [(-0.001, False), (0, True), (None, None)])
def test_each_real_added_market_input_keeps_its_own_requirement(good, balance, expected):
    data = world()
    data["market"][f"mg:{good}"]["market_goods_delta"] = balance
    assert evaluate(candidate, data) is expected
    assert evaluate(candidate, data, "productive") is True


def test_local_electricity_cannot_join_another_states_factory():
    data = world()
    original = data["any_scope_state"][0]
    data["any_scope_state"] = [
        {**original, "any_scope_building": []},
        {
            "any_scope_building": original["any_scope_building"],
            "sg:electricity": {"state_goods_pricier": 0.3},
        },
    ]
    assert evaluate(candidate, data) is False


def test_foreign_or_already_adopted_factory_does_not_prove_prepared_use():
    data = world()
    data["any_scope_state"][0]["any_scope_building"] = []
    assert evaluate(candidate, data) is False
    data = world()
    data["any_scope_state"][0]["any_scope_building"][0]["has_active_production_method"] = {
        (("argument", key),): key == "pm_electric_sewing_machines" for key in CATALOG["methods"]
    }
    assert evaluate(candidate, data) is False


def test_output_need_exits_and_native_prerequisite_is_not_an_overlay_qualification():
    data = world()
    data["market"]["mg:clothes"]["market_goods_delta"] = 0
    assert evaluate(candidate, data) is False
    data = world()
    data["has_technology_researched"][(("argument", "electrical_generation"),)] = False
    # This is a preference query. Research eligibility is native and must not
    # be confused with it; the candidate prerequisite remains in the catalog.
    assert evaluate(candidate, data) is True
    assert (
        "electrical_generation" in CATALOG["technologies"]["electrical_capacitors"]["prerequisites"]
    )


def test_reader_and_complete_source_closure_follow_actual_state_join():
    query = candidate.TechnologyUseQuery("electrical_capacitors", "productive_ready")
    spec = candidate.reader_spec(query)
    assert spec["engine"] == "any_scope_state"
    assert candidate.query_from_reader(spec["engine"], spec["parameters"]) == query
    assert "common/company_types/00_companies_soi.txt" in candidate.required_query_sources(query)


def test_reference_world_is_not_mutated():
    data = world()
    frozen = copy.deepcopy(data)
    evaluate(candidate, data)
    assert data == frozen
