"""Mechanism-based research preferences, without a fictional research invoice."""

from __future__ import annotations

import importlib
import importlib.util
import json
from typing import Any

import pytest
import technology_query_reference as technology_reference

from pdx import decision_rules
from pdx.situated import pdx_eval, programs

SOURCE = "common/technology/technologies/30_society.txt"


def _module():
    assert importlib.util.find_spec("pdx.technology_opportunities") is not None, (
        "mechanism-based technology opportunity generator is missing"
    )
    return importlib.import_module("pdx.technology_opportunities")


def _catalog():
    return {
        "schema": 1,
        "sources": {SOURCE: "a" * 64},
        "technologies": {
            "banking": {
                "source": SOURCE,
                "line": 1,
                "era": "era_1",
                "prerequisites": [],
                "modifier": {"country_loan_interest_rate_add": -0.25},
                "opportunities": [],
            },
            "analytical_philosophy": {
                "source": SOURCE,
                "line": 10,
                "era": "era_4",
                "prerequisites": [],
                "modifier": {"state_literacy_growth_add": 0.0002},
                "opportunities": [],
            },
            "centralization": {
                "source": SOURCE,
                "line": 20,
                "era": "era_1",
                "prerequisites": [],
                "modifier": {"state_tax_capacity_add": 25},
                "opportunities": [],
            },
            "macroeconomics": {
                "source": SOURCE,
                "line": 30,
                "era": "era_5",
                "prerequisites": [],
                "modifier": {
                    "country_max_companies_add": 1,
                    "state_market_access_price_impact": 0.05,
                },
                "opportunities": [],
            },
        },
        "goods": {},
        "buildings": {},
        "groups": {},
        "methods": {},
        "native_objects": {},
    }


def _derive():
    module = _module()
    catalog = _catalog()
    adapters = {
        "sources": catalog["sources"],
        "readers": {},
        "rules": [
            {"id": f"old_{key}", "source": SOURCE, "field": f"{key}.ai_weight"}
            for key in catalog["technologies"]
        ],
    }
    return module.derive(adapters, catalog)


def _policy(derived, technology):
    selected = [row for row in derived["rules"] if row["field"] == f"{technology}.ai_weight"]
    facts = {c["fact"] for row in selected for c in row["conditions"]}
    facts.update(
        c["value"]["fact"]
        for row in selected
        for c in row["conditions"]
        if isinstance(c["value"], dict)
    )
    return programs.enable(
        decision_rules.from_data(
            {
                "schema": 1,
                "baseline_sha256": "a" * 64,
                "domains": {row["domain"]: True for row in selected},
                "readers": {key: derived["readers"][key] for key in facts},
                "rules": [{k: v for k, v in row.items() if k != "source"} for row in selected],
            },
            source_sha256="b" * 64,
        ),
        source=SOURCE,
    )


def _reference(policy, values):
    result = decision_rules.evaluate(policy, values, is_ai=True)
    return next(iter(result.values()))[1] if result else 1.0


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"loans": True, "debt_ratio": 0.2}, 1.15),
        ({"loans": True, "debt_ratio": 0.6}, 1.22),
        ({"loans": True, "debt_ratio": None}, 1.15),
        ({"loans": False, "debt_ratio": 0.9}, 1.0),
        ({"loans": None, "debt_ratio": 0.9}, 1.0),
    ],
)
def test_interest_relief_uses_one_borrowing_cause_with_auxiliary_debt_tier(values, expected):
    assert _reference(_policy(_derive(), "banking"), values) == pytest.approx(expected)


def test_tax_capacity_need_is_local_shortfall_instead_of_national_bureaucracy():
    policy = _policy(_derive(), "centralization")
    assert _reference(policy, {"owned_incorporated_tax_shortfall": True}) == pytest.approx(1.15)
    assert _reference(policy, {"owned_incorporated_tax_shortfall": False, "bureaucracy": -500}) == 1
    assert _reference(policy, {"owned_incorporated_tax_shortfall": None}) == 1


def test_direct_literacy_benefit_has_no_default_peace_or_loan_gate():
    policy = _policy(_derive(), "analytical_philosophy")
    assert _reference(policy, {"literacy": 0.3}) == pytest.approx(1.25)
    assert _reference(policy, {"literacy": 0.8}) == 1
    assert _reference(policy, {"literacy": None}) == 1
    assert {r.key for r in policy.readers} == {"literacy"}


def test_macroeconomics_joins_company_capacity_and_actual_market_exposure():
    policy = _policy(_derive(), "macroeconomics")
    values = {
        "num_companies": 2,
        "max_num_companies": 2,
        "own_state_market_exposure": True,
        "own_state_deep_market_exposure": True,
    }
    # Company slot +.15 and market exposure +.10 are independent; exposure
    # foundation +.06 is a weaker tier, not another benefit.
    assert _reference(policy, values) == pytest.approx(1.25)
    assert _reference(policy, {**values, "max_num_companies": None}) == pytest.approx(1.18)
    assert _reference(policy, {"loans": True, "debt_ratio": 0.9}) == 1


def test_actual_pdx_numeric_program_matches_hand_computed_interest_tiers():
    policy = _policy(_derive(), "banking")
    program = policy.consumer_programs[0]
    readers = {reader.key: reader for reader in policy.readers}
    guards = {
        rule.id: "ROOT = { "
        + " ".join(
            readers[condition.fact].expression(condition.op, condition.value)
            for condition in rule.conditions
        )
        + " }"
        for rule in policy.rules
    }
    text = programs.render(
        program,
        guards=guards,
        ai_guard="ROOT = { is_ai = yes }",
        descriptions={},
        producer_markers={},
    )
    for debt, expected in ((0.2, 1.15), (0.6, 1.22), (None, 1.15)):
        observed = pdx_eval.select(
            text,
            {"ROOT": {"is_ai": True, "taking_loans": True, "scaled_debt": debt}},
        )
        assert observed.delta == pytest.approx(expected)


def _native_inputs():
    return {
        "common/technology/technologies/20_military.txt": """
artillery = { era = era_1 category = military ai_weight = { value = 1 } }
general_staff = { era = era_2 category = military ai_weight = { value = 2 } }
threshing_machine = { era = era_3 category = production ai_weight = { value = 1 } }
""",
        "common/goods/00_goods.txt": "iron = {} artillery = {} coal = {} gold = { tradeable = no }",
        "common/buildings/01_industry.txt": """
building_artillery_foundry = { production_method_groups = { pmg_cannons } }
building_wheat_farm = { production_method_groups = { pmg_automation } }
""",
        "common/production_method_groups/01_industry.txt": """
pmg_cannons = { production_methods = { pm_no_cannons pm_cannons } }
pmg_automation = { production_methods = { pm_no_automation pm_steam_threshers } }
""",
        "common/production_methods/01_industry.txt": """
pm_no_cannons = { building_modifiers = { workforce_scaled = { } } }
pm_cannons = { unlocking_technologies = { artillery }
 building_modifiers = { workforce_scaled = { goods_input_iron_add = 15 goods_output_artillery_add = 25 } } }
pm_no_automation = { building_modifiers = { workforce_scaled = { } } }
pm_steam_threshers = { unlocking_technologies = { threshing_machine }
 building_modifiers = { workforce_scaled = { goods_input_coal_add = 5 building_employment_laborers_add = -1500 } } }
""",
        "common/combat_unit_types/00_land_combat_unit_types.txt": """
combat_unit_type_skirmish_infantry = { unlocking_technologies = { general_staff }
 group = combat_unit_group_infantry upkeep_modifier = { goods_input_artillery_add = 1 }
 battle_modifier = { unit_offense_add = 30 } }
""",
    }


def test_native_inventory_distinguishes_supply_consumption_and_pure_labor_saving():
    catalog = _module().inventory(
        _native_inputs(),
        dict.fromkeys(
            ("artillery", "general_staff", "threshing_machine"),
            "common/technology/technologies/20_military.txt",
        ),
    )
    production = catalog["technologies"]["artillery"]["opportunities"]
    assert production[0]["outputs"] == {"artillery": 25.0}
    assert production[0]["inputs"] == {"iron": 15.0}
    assert catalog["technologies"]["general_staff"]["opportunities"] == []
    assert catalog["technologies"]["general_staff"]["military"][0]["goods"] == {"artillery": 1.0}
    labor = catalog["technologies"]["threshing_machine"]["opportunities"][0]
    assert labor["outputs"] == {}
    assert labor["labor_saved"] == 1500
    assert labor["prior"] == "pm_no_automation"


def test_native_inventory_rejects_duplicate_definition_and_broken_method_membership():
    inputs = _native_inputs()
    source = "common/production_methods/01_industry.txt"
    with pytest.raises(ValueError, match="重复"):
        _module().inventory(
            {**inputs, source: inputs[source] + "\npm_cannons = {}"},
            {"artillery": "common/technology/technologies/20_military.txt"},
        )
    source = "common/production_method_groups/01_industry.txt"
    with pytest.raises(ValueError, match="缺少引用"):
        _module().inventory(
            {**inputs, source: inputs[source].replace("pm_cannons", "pm_missing")},
            {"artillery": "common/technology/technologies/20_military.txt"},
        )


def test_repeated_native_modifier_containers_do_not_invent_merge_semantics():
    source = "common/technology/technologies/20_military.txt"
    inputs = _native_inputs()
    inputs[source] = inputs[source].replace(
        "artillery = {", "artillery = { modifier = { first = 1 } modifier = { second = 2 }"
    )
    row = _module().inventory(inputs, {"artillery": source})["technologies"]["artillery"]
    assert row["modifier"] == {}
    assert row["modifier_blocks"] == [{"first": 1.0}, {"second": 2.0}]


def test_labor_query_keeps_actual_method_employment_and_reserve_pool_on_same_state(monkeypatch):
    module = _module()
    catalog = module.inventory(
        _native_inputs(), {"threshing_machine": "common/technology/technologies/20_military.txt"}
    )
    monkeypatch.setattr(module, "_QUERY_CATALOG", catalog)
    query = module.query_from_reader(
        "any_scope_state",
        {
            "technology_query": "technology_use",
            "technology": "threshing_machine",
            "purpose": "labor",
        },
    )
    text = "ROOT = { " + module.render_query(query) + " }"
    parsed = __import__("pdx.parser", fromlist=["parse_text"]).parse_text(text)
    building = {
        "is_building_type": {(("argument", "building_wheat_farm"),): True},
        "has_active_production_method": {(("argument", "pm_no_automation"),): True},
        "level": 1,
        "occupancy": 0.9,
    }
    good_state = {
        "state_unemployment_rate": 0.01,
        "pop_type_percent_state": {(("target", "pop_type:peasants"),): 0.01},
        "any_scope_building": [building],
    }

    def value(states):
        return pdx_eval.condition(parsed.root, {"ROOT": {"any_scope_state": states}})

    assert value([good_state]) is True
    assert value([{**good_state, "state_unemployment_rate": 0.02}]) is False
    assert (
        value([{**good_state, "pop_type_percent_state": {(("target", "pop_type:peasants"),): 0.5}}])
        is False
    )
    assert (
        value(
            [
                {**good_state, "any_scope_building": []},
                {**good_state, "state_unemployment_rate": 0.3},
            ]
        )
        is False
    )
    assert value([{**good_state, "state_unemployment_rate": None}]) is None
    assert value([]) is False
    assert value(None) is None


def test_query_ids_and_method_membership_are_finite_and_render_is_pure(monkeypatch):
    module = _module()
    query = module.query_from_reader(
        "any_scope_building",
        {
            "technology_query": "existing_method",
            "building": "building_artillery_foundry",
            "method": "pm_cannons",
        },
    )
    from pathlib import Path

    def fail(*_args, **_kwargs):
        pytest.fail("query rendering read a file")

    monkeypatch.setattr(Path, "read_text", fail)
    assert "is_building_type = building_artillery_foundry" in module.render_query(query)
    with pytest.raises(ValueError):
        module.query_from_reader(
            "any_scope_building",
            {
                "technology_query": "existing_method",
                "building": "building_artillery_foundry",
                "method": "pm_scholastic_education",
            },
        )
    with pytest.raises(ValueError):
        module.query_from_reader(
            "any_country",
            {"technology_query": "existing_building", "building": "building_artillery_foundry"},
        )


def test_output_shortage_is_a_supply_opportunity_but_consuming_unit_is_not(monkeypatch):
    module = _module()
    source = "common/technology/technologies/20_military.txt"
    catalog = module.inventory(
        _native_inputs(), dict.fromkeys(("artillery", "general_staff", "threshing_machine"), source)
    )
    monkeypatch.setattr(module, "_QUERY_CATALOG", catalog)
    derived = module.derive({"sources": catalog["sources"], "readers": {}, "rules": []}, catalog)
    artillery = _policy(derived, "artillery")
    assert _reference(artillery, {"country_goods_artillery_balance": -1}) == pytest.approx(1.12)
    assert _reference(
        artillery, {"country_goods_artillery_balance": -1, "country_goods_artillery_price": 0.5}
    ) == pytest.approx(1.20)
    assert (
        _reference(
            artillery, {"country_goods_artillery_balance": 0, "country_goods_artillery_price": 0.5}
        )
        == 1
    )
    assert not any(
        c["fact"] == "country_goods_artillery_balance"
        for r in derived["rules"]
        if r["field"] == "general_staff.ai_weight"
        for c in r["conditions"]
    )
    staff = _policy(derived, "general_staff")
    assert _reference(staff, {"own_army": 10, "war": True}) == pytest.approx(1.15)
    assert _reference(staff, {"own_army": 0, "war": True}) == 1
    labor = _policy(derived, "threshing_machine")
    assert _reference(labor, {"technology_use_threshing_machine_labor": True}) == pytest.approx(
        1.12
    )
    assert _reference(labor, {"industrial_workforce": 0.8, "war": True}) == 1


@pytest.mark.parametrize("mutation", ["schema", "source", "membership", "legacy", "number"])
def test_frozen_catalog_rejects_malformed_or_drifting_records(tmp_path, mutation):
    module = _module()
    catalog = module.load_catalog()
    if mutation == "schema":
        catalog["schema"] = True
    elif mutation == "source":
        catalog["sources"]["../outside.txt"] = "a" * 64
    elif mutation == "membership":
        next(iter(catalog["groups"].values()))["methods"].append("pm_missing")
    elif mutation == "legacy":
        catalog["legacy_rules"].append(catalog["legacy_rules"][0])
    else:
        next(iter(catalog["methods"].values()))["outputs"]["iron"] = float("nan")
    path = tmp_path / "technology.toml"
    path.write_text(
        "schema = 1\nparameters = {}\ncatalog_json = '''" + json.dumps(catalog) + "'''\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        module.load_catalog(path)


def _query_values(technology, purpose, country):
    module = _module()
    query = module.TechnologyUseQuery(technology, purpose)
    spec = module.reader_spec(query)
    parsed = __import__("pdx.parser", fromlist=["parse_text"]).parse_text(
        "ROOT = { " + module.render_query(query) + " }"
    )
    assert not parsed.errors
    return technology_reference.evaluate(spec, country), pdx_eval.condition(
        parsed.root, {"ROOT": country}
    )


def _building_object(building, method="", level=1, occupancy=1):
    return {
        "is_building_type": {
            (("argument", identity),): identity == building
            for identity in technology_reference.BUILDING_IDENTITIES
        },
        "has_active_production_method": {
            (("argument", identity),): identity == method
            for identity in technology_reference.METHOD_IDENTITIES
        },
        "level": level,
        "occupancy": occupancy,
        "weekly_profit": 1,
    }


def _native_country_case(technology, purpose):
    """Construct actual objects from the independently loaded native artifact."""
    catalog = technology_reference.CATALOG
    country: dict[str, Any] = {
        "has_technology_researched": {
            (("argument", identity),): True
            for identity in set(catalog["technologies"])
            | {
                required
                for tech in catalog["technologies"].values()
                for row in tech["opportunities"]
                for required in row["requirements"]
            }
        },
        "has_law_or_variant": {},
        "market": {f"mg:{identity}": {"market_goods_delta": 0} for identity in catalog["goods"]},
    }
    for method in catalog["methods"].values():
        for law in method["law_gates"]["disallowing_laws"]:
            country["has_law_or_variant"][(("argument", f"law_type:{law}"),)] = False
        for law in method["law_gates"]["unlocking_laws"]:
            country["has_law_or_variant"][(("argument", f"law_type:{law}"),)] = True
    state = {
        "state_unemployment_rate": 0.01,
        "infrastructure_delta": -1,
        "pop_type_percent_state": {(("target", "pop_type:peasants"),): 0.01},
        "any_scope_building": [],
    }
    country["any_scope_state"] = [state]
    country["any_scope_building"] = []
    if purpose == "construction":
        country["any_scope_building"] = [_building_object("building_construction_sector")]
    elif purpose == "scale":
        # Native textile mills have economy of scale and ordinary clothes output.
        country["any_scope_building"] = [_building_object("building_textile_mill", level=20)]
        country["market"]["mg:clothes"]["market_goods_delta"] = -1
    elif purpose != "infrastructure_direct":
        candidates = technology_reference._members(technology, purpose)
        row = next(
            row
            for row in candidates
            if not purpose.endswith("_ready")
            or all(catalog["goods"][good]["market"] for good in row["inputs"])
        )
        building = _building_object(row["building"], row["prior"])
        country["any_scope_building"] = [building]
        state["any_scope_building"] = [building]
        if purpose.startswith("productive") or purpose == "throughput":
            good = next(g for g in row["outputs"] if catalog["goods"][g]["market"])
            country["market"][f"mg:{good}"]["market_goods_delta"] = -1
        elif purpose == "local_supply":
            good = next(g for g in row["outputs"] if catalog["goods"][g]["local"])
            state[f"sg:{good}"] = {"state_goods_pricier": 0.5}
        elif purpose == "resource":
            state["has_potential_resource"] = {(("argument", row["building"]),): True}
    return country


@pytest.mark.parametrize(
    ("technology", "purpose"),
    [
        ("arc_welding", "productive"),
        ("art_silk", "productive_ready"),
        ("automatic_bottle_blowers", "labor"),
        ("automatic_bottle_blowers", "labor_ready"),
        ("central_archives", "administration"),
        ("analytical_philosophy", "knowledge"),
        ("compression_ignition", "infrastructure"),
        ("combustion_engine", "local_supply"),
        ("cotton_gin", "throughput"),
        ("floating_harbor", "trade"),
        ("modern_sewerage", "construction"),
        ("prospecting", "resource"),
        ("modern_sewerage", "infrastructure_direct"),
        ("mechanized_workshops", "scale"),
    ],
)
def test_all_native_query_purposes_match_independent_object_oracle(technology, purpose):
    country = _native_country_case(technology, purpose)
    assert _query_values(technology, purpose, country) == (True, True)
    # Complete empty owned collections are a negative observation.
    assert _query_values(
        technology, purpose, {**country, "any_scope_state": [], "any_scope_building": []}
    ) == (False, False)
    assert _query_values(technology, purpose, {}) == (None, None)
    with pytest.raises(ValueError):
        _query_values(
            technology, purpose, {"any_scope_state": "malformed", "any_scope_building": "malformed"}
        )


def test_ready_input_missing_and_wrong_method_do_not_create_healthy_supply():
    country = _native_country_case("art_silk", "productive_ready")
    country["market"].pop("mg:wood")
    assert _query_values("art_silk", "productive_ready", country) == (None, None)
    country["market"]["mg:wood"] = {"market_goods_delta": -1}
    assert _query_values("art_silk", "productive_ready", country) == (False, False)
    assert _query_values("art_silk", "productive", country) == (True, True)
    country["any_scope_building"] = [_building_object("building_synthetics_plant", "pm_rayon")]
    assert _query_values("art_silk", "productive", country) == (False, False)


def test_explicit_absent_goods_scope_exits_query_while_unobserved_scope_is_unknown():
    country = _native_country_case("art_silk", "productive_ready")
    country["market"]["mg:wood"] = None
    assert _query_values("art_silk", "productive_ready", country) == (False, False)
    country["market"] = None
    assert _query_values("art_silk", "productive", country) == (False, False)
    country.pop("market")
    assert _query_values("art_silk", "productive", country) == (None, None)


def test_query_labor_and_local_goods_are_not_joined_across_owned_states():
    for technology, purpose in (
        ("automatic_bottle_blowers", "labor"),
        ("combustion_engine", "local_supply"),
    ):
        country = _native_country_case(technology, purpose)
        state = country["any_scope_state"][0]
        country["any_scope_state"] = [
            {**state, "any_scope_building": []},
            {
                "any_scope_building": state["any_scope_building"],
                "state_unemployment_rate": 1,
                "pop_type_percent_state": {(("target", "pop_type:peasants"),): 1},
                **{key: {"state_goods_pricier": 0} for key in state if key.startswith("sg:")},
            },
        ]
        assert _query_values(technology, purpose, country) == (False, False)


def test_complexity_rejects_real_expansion_and_rule_boundaries(monkeypatch):
    module = _module()
    rule = {"field": "test.ai_weight", "conditions": [{"fact": "a"}]}
    assert (
        module.validate_complexity({"readers": {}, "rules": [rule] * 32})["test.ai_weight"]["rules"]
        == 32
    )
    with pytest.raises(ValueError, match="静态预算"):
        module.validate_complexity({"readers": {}, "rules": [rule] * 33})
    with pytest.raises(ValueError, match="静态预算"):
        module.validate_complexity(
            {"readers": {}, "rules": [{**rule, "conditions": [{"fact": "a"}] * 161}]}
        )
    spec = module.reader_spec(module.TechnologyUseQuery("art_silk", "productive"))
    monkeypatch.setattr(module, "render_query", lambda _query: "OR = { " + " a = yes" * 161 + " }")
    with pytest.raises(ValueError, match="静态预算"):
        module.validate_complexity({"readers": {"a": spec}, "rules": [rule]})
    monkeypatch.setattr(module, "render_query", lambda _query: "AND = { " + " a = yes" * 160 + " }")
    assert (
        module.validate_complexity({"readers": {"a": spec}, "rules": [rule]})["test.ai_weight"][
            "expanded_leaves"
        ]
        == 160
    )
    monkeypatch.setattr(module, "render_query", lambda _query: "OR = { " + " AND = {}" * 161 + " }")
    with pytest.raises(ValueError, match="静态预算"):
        module.validate_complexity({"readers": {"a": spec}, "rules": [rule]})


def test_every_derived_query_has_an_independent_real_object_positive_fixture():
    module = _module()
    derived = module.derive({"sources": {}, "readers": {}, "rules": []})
    seen = set()
    for reader in derived["readers"].values():
        if "technology_query" not in reader.get("parameters", {}):
            continue
        country = technology_reference.realize_query_world(reader)
        expected = technology_reference.evaluate(reader, country)
        assert expected is True, reader["parameters"]
        query = module.query_from_reader(reader["engine"], reader["parameters"])
        assert _query_values(query.technology, query.purpose, country) == (True, True), reader[
            "parameters"
        ]
        seen.add(query.purpose)
    assert seen == {
        "productive",
        "productive_ready",
        "labor",
        "labor_ready",
        "administration",
        "knowledge",
        "infrastructure",
        "local_supply",
        "throughput",
        "trade",
        "construction",
        "resource",
        "infrastructure_direct",
        "scale",
    }


def test_ready_tier_preserves_short_output_of_the_actual_displaced_recipe():
    country = _native_country_case("chemical_bleaching", "productive_ready")
    country["any_scope_building"] = [_building_object("building_glassworks", "pm_ceramics")]
    country["market"]["mg:porcelain"]["market_goods_delta"] = -1
    country["market"]["mg:glass"]["market_goods_delta"] = -1
    assert _query_values("chemical_bleaching", "productive", country) == (True, True)
    assert _query_values("chemical_bleaching", "productive_ready", country) == (False, False)
    country["market"]["mg:glass"]["market_goods_delta"] = 0
    assert _query_values("chemical_bleaching", "productive_ready", country) == (True, True)
