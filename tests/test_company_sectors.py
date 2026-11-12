"""Independent company recipe fixtures, handwritten values and frozen drift."""

import copy
import json
from typing import Any

import pytest

from pdx import company_sectors, config, decision_rules, version_contracts
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.unit
COMPANY = "common/company_types/fixture.txt"
BUILDING = "common/buildings/fixture.txt"
GROUP = "common/production_method_groups/fixture.txt"
METHOD = "common/production_methods/fixture.txt"
GOODS = "common/goods/fixture.txt"
DEFINE = "common/defines/fixture.txt"


@pytest.fixture
def inputs():
    return {
        COMPANY: """
company_lkab = { building_types = { mine } extension_building_types = { steelworks } ai_weight = { value = 3 } }
company_ursus = { building_types = { motor } ai_weight = { value = 3 } }
company_colt_firearms = { building_types = { arms } ai_weight = { value = 3 } }
textile = { building_types = { textile } ai_weight = { value = 3 } }
mixed = { building_types = { mine motor } ai_weight = { value = 3 } }
basic = { building_types = { mine } }
gold_company = { building_types = { gold_mine } ai_weight = { value = 3 } }
local_company = { building_types = { power } ai_weight = { value = 3 } }
service_company = { building_types = { port } ai_weight = { value = 3 } }
marine_company = { building_types = { shipping } ai_weight = { value = 3 } }
skilled_company = { building_types = { academy } ai_weight = { value = 3 } }
""",
        BUILDING: """
mine = { production_method_groups = { mining explosives } }
motor = { production_method_groups = { motors } }
arms = { production_method_groups = { guns } }
steelworks = { production_method_groups = { steel } }
textile = { production_method_groups = { clothes luxury } }
gold_mine = { production_method_groups = { gold } }
power = { production_method_groups = { electricity } }
port = { production_method_groups = { service } }
shipping = { production_method_groups = { marine } }
academy = { production_method_groups = { art } }
""",
        GROUP: """
mining = { production_methods = { pick pump } }
explosives = { production_methods = { disabled dynamite } }
motors = { production_methods = { steam diesel } }
guns = { production_methods = { musket rifle } }
steel = { production_methods = { steelmaking } }
clothes = { production_methods = { handsewn sewing } }
luxury = { production_methods = { disabled luxury } }
gold = { production_methods = { gold } }
electricity = { production_methods = { power } }
service = { production_methods = { port } }
marine = { production_methods = { marine } }
art = { production_methods = { art } }
""",
        METHOD: """
pick = { building_modifiers = { workforce_scaled = { goods_input_tools_add = 5 goods_output_iron_add = 20 } level_scaled = { building_employment_laborers_add = 4000 } } }
pump = { building_modifiers = { workforce_scaled = { goods_input_tools_add = 10 goods_input_coal_add = 10 goods_output_iron_add = 40 } level_scaled = { building_employment_laborers_add = 3000 } } }
disabled = { }
dynamite = { building_modifiers = { workforce_scaled = { goods_input_explosives_add = 10 goods_output_iron_add = 10 } } }
steam = { building_modifiers = { workforce_scaled = { goods_input_steel_add = 30 goods_output_engines_add = 40 } level_scaled = { building_employment_laborers_add = 2500 } } }
diesel = { building_modifiers = { workforce_scaled = { goods_input_steel_add = 50 goods_input_oil_add = 50 goods_output_engines_add = 120 } level_scaled = { building_employment_laborers_add = 2000 } } }
musket = { building_modifiers = { workforce_scaled = { goods_input_hardwood_add = 10 goods_input_iron_add = 10 goods_output_small_arms_add = 30 } level_scaled = { building_employment_laborers_add = 4000 } } }
rifle = { building_modifiers = { workforce_scaled = { goods_input_hardwood_add = 10 goods_input_steel_add = 10 goods_input_tools_add = 5 goods_output_small_arms_add = 50 } level_scaled = { building_employment_laborers_add = 3000 } } }
steelmaking = { building_modifiers = { workforce_scaled = { goods_input_iron_add = 40 goods_output_steel_add = 65 } } }
handsewn = { building_modifiers = { workforce_scaled = { goods_input_fabric_add = 40 goods_output_clothes_add = 45 } level_scaled = { building_employment_laborers_add = 4500 } } }
sewing = { building_modifiers = { workforce_scaled = { goods_input_fabric_add = 60 goods_input_dye_add = 10 goods_output_clothes_add = 100 } level_scaled = { building_employment_laborers_add = 3000 } } }
luxury = { building_modifiers = { workforce_scaled = { goods_input_silk_add = 10 goods_output_luxury_clothes_add = 30 } } }
gold = { building_modifiers = { workforce_scaled = { goods_output_gold_add = 10 } level_scaled = { building_employment_laborers_add = 3000 } } }
power = { building_modifiers = { workforce_scaled = { goods_input_coal_add = 20 goods_output_electricity_add = 50 } } }
port = { building_modifiers = { workforce_scaled = { goods_input_merchant_marine_add = 10 } } }
marine = { building_modifiers = { workforce_scaled = { goods_input_wood_add = 10 goods_output_merchant_marine_add = 20 } } }
art = { building_modifiers = { workforce_scaled = { goods_input_paper_add = 10 goods_output_fine_art_add = 5 } level_scaled = { building_employment_academics_add = 1000 } } }
""",
        GOODS: "\n".join(
            f"{good} = {{ cost = 50 }}"
            for good in (
                "tools",
                "iron",
                "coal",
                "explosives",
                "steel",
                "engines",
                "oil",
                "hardwood",
                "small_arms",
                "fabric",
                "dye",
                "clothes",
                "silk",
                "luxury_clothes",
                "wood",
                "paper",
                "fine_art",
                "merchant_marine",
            )
        )
        + "\ngold = { cost = 100 fixed_price = yes tradeable = no }\nelectricity = { cost = 30 local = yes }\n",
        DEFINE: "NAI = { COMPANY_TYPE_DEFAULT_BASE_WEIGHT = 1 }\n",
    }


def _policy_readers(readers):
    selected = copy.deepcopy(readers)
    if version_contracts.is_115():
        from pdx.situated.engine_reader_115 import project_population_readers

        project_population_readers(selected)
    return selected


def _policy(derived, company):
    source = derived["profiles"][company]["source"]
    rows = [row for row in derived["rules"] if row["field"] == f"{company}.ai_weight"]
    keys = {predicate["fact"] for row in rows for predicate in row["conditions"]}
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": derived["sources"][source],
            "domains": {"market": True},
            "readers": _policy_readers(
                {key: value for key, value in derived["readers"].items() if key in keys}
            ),
            "rules": [
                {key: value for key, value in row.items() if key != "source"} for row in rows
            ],
        },
        source_sha256="0" * 64,
    )
    return programs.enable(policy, source=source)


def _assert_joint(derived, company, changes, expected, *, observations=None, is_ai=True):
    policy = _policy(derived, company)
    values = {reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers}
    values.update(changes)
    actual = decision_rules.evaluate(policy, values, is_ai=is_ai).get(f"{company}.ai_weight")
    assert (actual[1] if actual else 1) == pytest.approx(expected)
    readers = {reader.key: reader for reader in policy.readers}
    guards = {}
    for rule in policy.rules:
        conditions = []
        for predicate in rule.conditions:
            reader = readers[predicate.fact]
            expression = reader.expression(predicate.op, predicate.value)
            for scope in reversed(reader.path):
                expression = f"{scope} = {{ {expression} }}"
            conditions.append(f"ROOT = {{ {expression} }}")
        guards[rule.id] = " ".join(conditions)
    text = programs.render(
        policy.consumer_programs[0],
        guards=guards,
        ai_guard="ROOT = { is_ai = yes }",
        descriptions={},
        producer_markers={},
    )
    root: dict[str, Any] = {"is_ai": is_ai, **(observations or {})}
    for reader in policy.readers:
        current = root
        for part in reader.path:
            current = current.setdefault(part, {})
        if "company_query" in dict(reader.parameters):
            continue
        if reader.parameters:
            current[reader.engine] = {tuple(reader.parameters): values[reader.key]}
        else:
            current[reader.engine] = values[reader.key]
    result = pdx_eval.select(text, {"ROOT": root})
    if is_ai:
        assert result.delta == pytest.approx(expected)
    else:
        assert expected == 1
        assert result.fallback == "vanilla"
        assert result.action_id is None
        assert result.operation is None


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
def test_company_fixture_binds_selected_population_without_mutating_derivation(
    inputs, monkeypatch, version
):
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, version)
    derived = company_sectors.derive(inputs)
    historical_readers = copy.deepcopy(derived["readers"])
    _assert_joint(derived, "company_lkab", {"industrial_workforce": 0.15}, 1.04)
    assert derived["readers"] == historical_readers


@pytest.fixture
def special_inputs(inputs):
    inputs[COMPANY] += """
railco = { building_types = { building_railway } ai_weight = { value = 3 } }
powerco = { building_types = { building_power_plant } ai_weight = { value = 3 } }
portco = { building_types = { building_port } ai_weight = { value = 3 } }
combinedco = { building_types = { building_railway building_power_plant building_port } ai_weight = { value = 3 } }
goldco = { building_types = { building_gold_mine } ai_weight = { value = 3 } }
tradeco = { building_types = { building_trade_center } ai_weight = { value = 3 } }
businessmixed = { building_types = { building_gold_mine building_trade_center } ai_weight = { value = 3 } }
"""
    inputs[BUILDING] += """
building_railway = { production_method_groups = { rail } }
building_power_plant = { production_method_groups = { electric } }
building_port = { production_method_groups = { ports } }
building_gold_mine = { production_method_groups = { businessgold } }
building_trade_center = { production_method_groups = { businesstrade } }
"""
    inputs[GROUP] += """
rail = { production_methods = { rail } }
electric = { production_methods = { electric } }
ports = { production_methods = { pm_anchorage pm_basic_port pm_industrial_port pm_modern_port } }
businessgold = { production_methods = { businessgold } }
businesstrade = { production_methods = { businesstrade } }
"""
    inputs[METHOD] += """
rail = { building_modifiers = { workforce_scaled = { goods_input_engines_add = 5 goods_output_transportation_add = 20 } } }
electric = { building_modifiers = { workforce_scaled = { goods_input_engines_add = 6 goods_output_electricity_add = 50 } } }
pm_anchorage = { }
pm_basic_port = { building_modifiers = { workforce_scaled = { goods_input_clippers_add = 6 goods_output_merchant_marine_add = 9 } } }
pm_industrial_port = { building_modifiers = { workforce_scaled = { goods_input_steamers_add = 5 goods_input_coal_add = 5 goods_output_merchant_marine_add = 20 } } }
pm_modern_port = { building_modifiers = { workforce_scaled = { goods_input_steamers_add = 5 goods_input_oil_add = 10 goods_output_merchant_marine_add = 30 } } }
businessgold = { building_modifiers = { workforce_scaled = { goods_input_tools_add = 5 goods_output_gold_add = 8 } } country_modifiers = { workforce_scaled = { country_minting_add = 250 } } }
businesstrade = { state_modifiers = { workforce_scaled = { state_weekly_trades_add = 1 state_trade_capacity_add = 10 } } }
"""
    inputs[GOODS] += (
        "\ntransportation = { cost = 30 local = yes }\nclippers = { cost = 60 }\nsteamers = { cost = 70 }\n"
    )
    return inputs


def _observed_building(kind, method=None):
    result: dict[str, Any] = {
        "is_building_type": {
            (("argument", name),): name == kind
            for name in (
                "building_railway",
                "building_power_plant",
                "building_port",
                "building_gold_mine",
                "building_trade_center",
            )
        },
        "level": 1,
    }
    result["has_active_production_method"] = {
        (("argument", name),): name == method
        for name in ("pm_basic_port", "pm_industrial_port", "pm_modern_port")
    }
    return result


def test_local_rail_and_power_have_real_benefit_and_independent_input_cost(special_inputs):
    derived = company_sectors.derive(special_inputs)
    rail_state = {
        "any_scope_building": [_observed_building("building_railway")],
        "infrastructure_delta": -1,
        "sg:transportation": {"state_goods_pricier": 0.5},
    }
    power_state = {
        "any_scope_building": [_observed_building("building_power_plant")],
        "sg:electricity": {"state_goods_pricier": 0.6},
    }
    for company, low, high, state in (
        ("railco", "company_rail_need", "company_rail_pressure", rail_state),
        ("powerco", "company_power_need", "company_power_pressure", power_state),
    ):
        assert any(row["field"] == f"{company}.ai_weight" for row in derived["rules"])
        _assert_joint(
            derived,
            company,
            {low: True, high: True, "country_goods_engines_price": 0.5},
            1.05,
            observations={"any_scope_state": [state]},
        )
        _assert_joint(
            derived,
            company,
            {low: None, high: None, "country_goods_engines_price": 0.5},
            0.85,
            observations={},
        )


@pytest.mark.parametrize(
    ("method", "reader", "expensive", "irrelevant"),
    [
        ("pm_basic_port", "company_port_basic", "clippers", "steamers"),
        ("pm_industrial_port", "company_port_industrial", "coal", "oil"),
        ("pm_modern_port", "company_port_modern", "oil", "clippers"),
    ],
)
def test_port_shortage_and_pm_specific_input_cost_join_one_program(
    special_inputs, method, reader, expensive, irrelevant
):
    derived = company_sectors.derive(special_inputs)
    assert any(row["field"] == "portco.ai_weight" for row in derived["rules"])
    facts = {
        reader: True,
        "country_goods_merchant_marine_balance": -1,
        f"country_goods_{expensive}_price": 0.5,
    }
    objects = {"any_scope_building": [_observed_building("building_port", method)]}
    _assert_joint(derived, "portco", facts, 0.97, observations=objects)
    _assert_joint(
        derived,
        "portco",
        {
            reader: True,
            "country_goods_merchant_marine_balance": -1,
            f"country_goods_{irrelevant}_price": 0.5,
        },
        1.12,
        observations=objects,
    )
    _assert_joint(
        derived,
        "portco",
        {"country_goods_merchant_marine_balance": -1, f"country_goods_{expensive}_price": 0.5},
        1,
        observations={"any_scope_building": [_observed_building("building_port", "pm_anchorage")]},
    )


def test_independent_special_sectors_share_demand_but_join_distinct_input_costs(special_inputs):
    derived = company_sectors.derive(special_inputs)
    rows = [row for row in derived["rules"] if row["field"] == "combinedco.ai_weight"]
    demand = [row for row in rows if row["contribution_group"] == "company_output_demand"]
    assert len(demand) == 10  # rail/power 2 each; three active port methods 2 each
    assert not any(
        row["fact"] == "country_goods_electricity_price"
        for rule in rows
        for row in rule["conditions"]
    )
    assert not any(
        row["fact"] == "country_goods_transportation_balance"
        for rule in rows
        for row in rule["conditions"]
    )
    facts = {
        "company_rail_need": True,
        "company_rail_pressure": True,
        "company_power_need": True,
        "company_power_pressure": True,
        "company_port_basic": True,
        "country_goods_merchant_marine_balance": -1,
        "country_goods_merchant_marine_price": 0.5,
        "country_goods_engines_price": 0.5,
        "country_goods_clippers_price": 0.5,
    }
    state = {
        "any_scope_building": [
            _observed_building("building_railway"),
            _observed_building("building_power_plant"),
        ],
        "infrastructure_delta": -1,
        "sg:transportation": {"state_goods_pricier": 0.5},
        "sg:electricity": {"state_goods_pricier": 0.6},
    }
    _assert_joint(
        derived,
        "combinedco",
        facts,
        0.90,  # 1 + .20 demand - .15 engines - .15 clippers
        observations={
            "any_scope_state": [state],
            "any_scope_building": [_observed_building("building_port", "pm_basic_port")],
        },
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"country_goods_steamers_price": 0.5}, 0.85),
        ({"country_goods_steamers_price": 0.5, "country_goods_coal_price": 0.5}, 0.70),
        ({"country_goods_steamers_price": None, "country_goods_coal_price": 0.5}, 0.85),
    ],
)
def test_same_ship_input_across_active_port_methods_is_one_physical_cost(
    special_inputs, changes, expected
):
    derived = company_sectors.derive(special_inputs)
    _assert_joint(
        derived,
        "portco",
        {"company_port_industrial": True, "company_port_modern": True, **changes},
        expected,
        observations={
            "any_scope_building": [
                _observed_building("building_port", "pm_industrial_port"),
                _observed_building("building_port", "pm_modern_port"),
            ]
        },
    )


@pytest.mark.parametrize(
    ("price", "low", "high", "expected"),
    [
        (0.25, False, False, 1),
        (0.251, True, False, 1.12),
        (0.5, True, False, 1.12),
        (0.501, True, True, 1.20),
    ],
)
def test_local_power_price_tiers_have_strict_boundaries(special_inputs, price, low, high, expected):
    derived = company_sectors.derive(special_inputs)
    state = {
        "any_scope_building": [_observed_building("building_power_plant")],
        "sg:electricity": {"state_goods_pricier": price},
    }
    _assert_joint(
        derived,
        "powerco",
        {"company_power_need": low, "company_power_pressure": high},
        expected,
        observations={"any_scope_state": [state]},
    )


def test_special_program_player_and_disabled_domain_preserve_original(special_inputs):
    derived = company_sectors.derive(special_inputs)
    state = {
        "any_scope_building": [_observed_building("building_railway")],
        "infrastructure_delta": -1,
        "sg:transportation": {"state_goods_pricier": 0.6},
    }
    _assert_joint(
        derived,
        "railco",
        {
            "company_rail_need": True,
            "company_rail_pressure": True,
            "country_goods_engines_price": 0.5,
        },
        1,
        observations={"any_scope_state": [state]},
        is_ai=False,
    )
    policy = _policy(derived, "railco")
    assert (
        decision_rules.evaluate(
            policy, {"company_rail_need": True}, is_ai=True, enabled_domains=frozenset()
        )
        == {}
    )
    original = special_inputs[COMPANY]
    assert (
        decision_rules.patch(
            original, policy, baseline=original, enabled_domains=frozenset(), default_strategy=False
        )
        == original
    )


@pytest.mark.parametrize(
    ("company", "output", "required", "optional"),
    [
        ("company_lkab", "iron", "tools", "coal"),
        ("company_ursus", "engines", "steel", "oil"),
        ("company_colt_firearms", "small_arms", "hardwood", "tools"),
    ],
)
def test_handwritten_three_sectors_preserve_actual_recipe_differences(
    inputs, company, output, required, optional
):
    derived = company_sectors.derive(inputs)
    profile = derived["profiles"][company]
    assert profile["market_outputs"] == [output]
    assert profile["common_inputs"] == [required]
    assert optional not in profile["common_inputs"]
    assert profile["employs_laborers"] is True
    assert len([row for row in derived["rules"] if row["field"] == profile["field"]]) == 5
    _assert_joint(derived, company, {f"country_goods_{output}_balance": -1}, 1.12)
    _assert_joint(
        derived,
        company,
        {f"country_goods_{output}_balance": -1, f"country_goods_{required}_price": 0.5},
        0.97,
    )
    _assert_joint(
        derived,
        company,
        {
            f"country_goods_{output}_balance": -1,
            f"country_goods_{output}_price": 0.5,
            f"country_goods_{required}_price": 0.5,
            "industrial_workforce": 0.15,
            "default": True,
        },
        0.89,
    )
    _assert_joint(
        derived,
        company,
        {
            f"country_goods_{output}_balance": -1,
            f"country_goods_{output}_price": None,
            f"country_goods_{required}_price": None,
            "default": None,
        },
        1.12,
    )


def test_multisector_demand_deduplicates_but_distinct_material_costs_join(inputs):
    derived = company_sectors.derive(inputs)
    assert derived["profiles"]["mixed"]["market_outputs"] == ["engines", "iron"]
    assert derived["profiles"]["mixed"]["common_inputs"] == ["steel", "tools"]
    _assert_joint(
        derived,
        "mixed",
        {
            "country_goods_iron_balance": -1,
            "country_goods_engines_balance": -1,
            "country_goods_iron_price": 0.5,
            "country_goods_engines_price": 0.5,
            "country_goods_tools_price": 0.5,
            "country_goods_steel_price": 0.5,
            "industrial_workforce": 0.15,
            "default": True,
        },
        0.74,  # 1 + .20 demand + .04 labor - .15 steel - .15 tools - .20 default
    )


def test_source_tier_limits_are_not_a_private_company_aggregate_clamp(inputs):
    derived = company_sectors.derive(
        inputs,
        parameters={**company_sectors.DEFAULTS, "outer_lower": 0.7, "outer_upper": 1.21},
    )
    _assert_joint(
        derived,
        "mixed",
        {
            "country_goods_iron_balance": -1,
            "country_goods_iron_price": 0.5,
            "industrial_workforce": 0.15,
        },
        1.24,  # Individually allowed .20 and .04 contributions join before the shared cap.
    )
    _assert_joint(
        derived,
        "mixed",
        {
            "country_goods_tools_price": 0.5,
            "country_goods_steel_price": 0.5,
            "default": True,
        },
        0.50,  # Independent materials and solvency may cross the per-tier lower bound.
    )


def test_all_companies_in_one_source_load_as_one_real_rule_set_with_unique_priorities(inputs):
    derived = company_sectors.derive(inputs)
    priorities = [row["priority"] for row in derived["rules"]]
    assert priorities == list(range(50000, 50000 + len(priorities)))
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": derived["sources"][COMPANY],
            "domains": {"market": True},
            "readers": _policy_readers(derived["readers"]),
            "rules": [
                {key: value for key, value in row.items() if key != "source"}
                for row in derived["rules"]
            ],
        },
        source_sha256="0" * 64,
    )
    compiled = programs.enable(policy, source=COMPANY)
    assert len(compiled.rules) == len(derived["rules"])
    assert {item.field for item in compiled.consumer_programs} == {
        ("company_lkab", "ai_weight"),
        ("company_ursus", "ai_weight"),
        ("company_colt_firearms", "ai_weight"),
        ("textile", "ai_weight"),
        ("mixed", "ai_weight"),
        ("marine_company", "ai_weight"),
        ("skilled_company", "ai_weight"),
    }


def test_extensions_and_optional_recipe_outputs_never_become_current_primary(inputs):
    derived = company_sectors.derive(inputs)
    assert derived["profiles"]["company_lkab"]["extensions"] == ["steelworks"]
    assert derived["profiles"]["company_lkab"]["market_outputs"] == ["iron"]
    textile = derived["profiles"]["textile"]
    assert textile["potential_outputs"] == ["clothes", "luxury_clothes"]
    assert textile["market_outputs"] == ["clothes"]
    assert textile["common_inputs"] == ["fabric"]
    assert "country_goods_silk_price" not in derived["readers"]
    assert "country_goods_luxury_clothes_balance" not in derived["readers"]


def test_hyphen_normalization_cannot_merge_two_native_company_identities(inputs):
    changed = dict(inputs)
    changed[COMPANY] += (
        "\ncompany_russo-baltic = { building_types = { mine } ai_weight = { value = 3 } }"
        "\ncompany_russo_baltic = { building_types = { mine } ai_weight = { value = 3 } }"
    )
    with pytest.raises(ValueError, match="规则ID后冲突"):
        company_sectors.derive(changed)


def test_no_company_tag_or_name_branch_and_input_order_does_not_matter(inputs):
    before = company_sectors.derive(inputs)
    assert company_sectors.derive(dict(reversed(list(inputs.items())))) == before
    changed = dict(inputs)
    changed[COMPANY] = changed[COMPANY].replace("company_lkab", "unhistorical_name")
    after = company_sectors.derive(changed)
    left = copy.deepcopy(before["profiles"]["company_lkab"])
    right = copy.deepcopy(after["profiles"]["unhistorical_name"])
    for item in (left, right):
        item.pop("id")
        item.pop("field")
    assert left == right


def test_unproven_synthetic_default_remains_registered_without_invented_score_or_rule(inputs):
    derived = company_sectors.derive(inputs)
    assert derived["counts"]["companies"] == 11
    assert derived["counts"]["implicit_weight"] == 1
    profile = derived["profiles"]["basic"]
    assert profile["explicit_weight"] is False
    assert profile["default_define"] == {
        "source": DEFINE,
        "field": "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT",
        "value": 1,
    }
    assert not any(row["field"] == "basic.ai_weight" for row in derived["rules"])


@pytest.fixture
def authorized_default_inputs(inputs, monkeypatch):
    # This fixture deliberately preserves the historical reviewed line 1049.
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, "1.14.5")
    inputs = dict(inputs)
    inputs.pop(COMPANY)
    inputs.pop(DEFINE)
    inputs["common/company_types/99_basic_companies.txt"] = (
        "\n" * 1048 + "company_basic_steel = { building_types = { mine } }\n"
    )
    inputs["common/defines/00_ai.txt"] = "NAI = { COMPANY_TYPE_DEFAULT_BASE_WEIGHT = 1 }\n"
    return inputs


def test_exact_frozen_missing_company_uses_market_template_and_exposes_initializer(
    authorized_default_inputs,
):
    derived = company_sectors.derive(authorized_default_inputs)
    assert len(derived["rules"]) == 5
    assert {row["field"] for row in derived["rules"]} == {"company_basic_steel.ai_weight"}
    assert company_sectors.initialized_fields(derived) == [
        {
            "source": "common/company_types/99_basic_companies.txt",
            "field": "company_basic_steel.ai_weight",
            "define_source": "common/defines/00_ai.txt",
            "define": "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT",
        }
    ]
    _assert_joint(derived, "company_basic_steel", {"country_goods_iron_balance": -1}, 1.12)
    _assert_joint(
        derived,
        "company_basic_steel",
        {"country_goods_iron_balance": -1, "country_goods_tools_price": 0.5},
        0.97,
    )


@pytest.mark.parametrize("damage", ["company", "source", "line", "define_source", "local_output"])
def test_default_initialization_requires_exact_identity_and_real_market_output(
    authorized_default_inputs, damage
):
    inputs = authorized_default_inputs
    source = "common/company_types/99_basic_companies.txt"
    if damage == "company":
        inputs[source] = inputs[source].replace("company_basic_steel", "new_company")
    elif damage == "source":
        inputs[COMPANY] = inputs.pop(source)
    elif damage == "line":
        inputs[source] = "\n" + inputs[source]
    elif damage == "define_source":
        inputs[DEFINE] = inputs.pop("common/defines/00_ai.txt")
    else:
        inputs[GOODS] = inputs[GOODS].replace(
            "iron = { cost = 50 }", "iron = { cost = 50 local = yes }"
        )
    derived = company_sectors.derive(inputs)
    assert derived["rules"] == []
    assert company_sectors.initialized_fields(derived) == []


@pytest.mark.parametrize("weight", ["{}", "{ value = 0 }", "{ value = -3 }", "{ value = 3 }"])
def test_explicit_empty_zero_negative_and_positive_scores_never_become_initializers(
    authorized_default_inputs, weight
):
    source = "common/company_types/99_basic_companies.txt"
    authorized_default_inputs[source] = authorized_default_inputs[source].replace(
        "building_types = { mine }", f"building_types = {{ mine }} ai_weight = {weight}"
    )
    derived = company_sectors.derive(authorized_default_inputs)
    assert derived["profiles"]["company_basic_steel"]["explicit_weight"] is True
    assert company_sectors.initialized_fields(derived) == []


def test_frozen_default_rules_cannot_survive_identity_drift_offline(
    authorized_default_inputs, tmp_path, monkeypatch
):
    path = _freeze(tmp_path, monkeypatch, authorized_default_inputs)
    frozen = company_sectors.load_baseline()
    assert len(frozen["rules"]) == 5
    assert len(company_sectors.initialized_fields(frozen)) == 1
    disk = json.loads(path.read_text(encoding="utf-8"))
    disk["profiles"]["company_basic_steel"]["line"] += 1
    path.write_text(company_sectors._canonical(disk), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match=r"模板|读取器"):
        company_sectors.load_baseline()


@pytest.mark.parametrize(
    ("company", "good", "reason"),
    [
        ("gold_company", "gold", "fixed_price_good_retains_native_mechanism"),
        ("local_company", "electricity", "local_good_requires_state_market_evidence"),
        ("service_company", None, "no_goods_output_native_service"),
    ],
)
def test_special_goods_and_service_keep_native_path_without_fake_prices(
    inputs, company, good, reason
):
    derived = company_sectors.derive(inputs)
    profile = derived["profiles"][company]
    assert profile["market_outputs"] == []
    assert any(item["good"] == good and item["reason"] == reason for item in profile["native_only"])
    assert not any(row["field"] == profile["field"] for row in derived["rules"])
    if good:
        assert not any(f"country_goods_{good}_" in key for key in derived["readers"])


def test_merchant_marine_is_not_excluded_by_name_and_laborers_need_real_jobs(inputs):
    derived = company_sectors.derive(inputs)
    assert derived["profiles"]["marine_company"]["market_outputs"] == ["merchant_marine"]
    assert "country_goods_merchant_marine_balance" in derived["readers"]
    assert derived["profiles"]["skilled_company"]["employs_laborers"] is False
    assert not any(
        row["field"] == "skilled_company.ai_weight"
        and row["contribution_group"] == "company_labor_structure"
        for row in derived["rules"]
    )


@pytest.mark.parametrize("family", [COMPANY, BUILDING, GROUP, METHOD, GOODS, DEFINE])
def test_missing_input_family_fails_explicitly(inputs, family):
    inputs.pop(family)
    with pytest.raises(ValueError):
        company_sectors.derive(inputs)


@pytest.mark.parametrize(
    ("source", "text"),
    [
        (COMPANY, "company_lkab = {}"),
        (BUILDING, "mine = {}"),
        (GROUP, "mining = {}"),
        (METHOD, "pick = {}"),
        (GOODS, "iron = {}"),
        (DEFINE, "NAI = { COMPANY_TYPE_DEFAULT_BASE_WEIGHT = 1 }"),
    ],
)
def test_duplicate_definitions_and_consumed_define_are_never_order_resolved(inputs, source, text):
    inputs[source] += "\n" + text
    with pytest.raises(ValueError):
        company_sectors.derive(inputs)


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (COMPANY, "building_types = { mine }", "building_types = { missing }"),
        (BUILDING, "mining explosives", "missing explosives"),
        (GROUP, "pick pump", "missing pump"),
        (METHOD, "goods_output_iron_add", "goods_output_missing_add"),
        (COMPANY, "building_types = { mine }", "building_types = { mine mine }"),
        (COMPANY, "company_lkab =", "REPLACE:company_lkab ="),
        (METHOD, "goods_output_iron_add = 20", "goods_output_iron_add = nan"),
        (
            METHOD,
            "goods_output_iron_add = 20",
            "goods_output_iron_add = 20 goods_output_iron_add = 40",
        ),
        (METHOD, "workforce_scaled", "if"),
        (DEFINE, "= 1", "= 2"),
    ],
)
def test_missing_ambiguous_or_unconditional_recipe_assumptions_fail(inputs, source, old, new):
    inputs[source] = inputs[source].replace(old, new, 1)
    with pytest.raises(ValueError):
        company_sectors.derive(inputs)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("shortage_balance", 1),
        ("output_price_threshold", 0),
        ("input_price_threshold", 0.8),
        ("laborers_share_threshold", 1.1),
        ("demand_multiplier", 1.3),
        ("input_multiplier", 0),
        ("default_multiplier", 1.1),
        ("workforce_multiplier", True),
        ("outer_lower", 0.9),
        ("outer_upper", 1.1),
        ("input_multiplier", float("nan")),
        ("priority_base", 49999),
        ("priority_base", 50000.5),
    ],
)
def test_parameters_are_one_complete_finite_bounded_contract(inputs, key, value):
    parameters = {**company_sectors.DEFAULTS, key: value}
    with pytest.raises(ValueError):
        company_sectors.derive(inputs, parameters=parameters)


def _freeze(tmp_path, monkeypatch, inputs):
    # These mutation fixtures exercise the historical schema-2 reference
    # representation. They are not a fake installed 1.15 game and must not
    # bypass its live authority gate to manufacture a schema-3 attestation.
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, "1.14.5")
    monkeypatch.setattr(company_sectors, "BASELINE", tmp_path / "baseline.json")
    game = tmp_path / "game"
    for source, text in inputs.items():
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return company_sectors.write_baseline(game)


def test_explicit_baseline_write_load_and_independent_rederive_are_equal(
    inputs, tmp_path, monkeypatch
):
    path = _freeze(tmp_path, monkeypatch, inputs)
    derived = company_sectors.derive(inputs)
    assert company_sectors.load_baseline() == derived
    assert company_sectors.verify_baseline(inputs) == derived
    assert company_sectors.read_inputs(tmp_path / "game") == inputs
    assert company_sectors.verify_game(tmp_path / "game") == derived
    raw = path.read_bytes()
    assert not raw.startswith(bytes.fromhex("efbbbf"))
    assert b"\r" not in raw
    assert "verified" not in json.loads(raw)


def test_reference_format_round_trip_is_equal_without_mutating_runtime_contract(inputs):
    runtime = company_sectors.derive(inputs)
    original = copy.deepcopy(runtime)
    frozen = company_sectors._freeze(runtime)
    assert runtime == original
    assert runtime["schema"] == 1
    assert frozen["schema"] == 2
    assert len(frozen["building_profiles"]) == runtime["counts"]["primary_buildings"]
    assert frozen["profiles"]["company_lkab"]["base_recipes"] == ["mine"]
    assert frozen["profiles"]["mixed"]["base_recipes"] == ["mine", "motor"]
    parsed = json.loads(company_sectors._canonical(frozen))
    restored = company_sectors._thaw(parsed)
    assert company_sectors._validate_runtime(restored) == original
    assert restored["schema"] == 1
    assert "building_profiles" not in restored
    mine = restored["profiles"]["company_lkab"]["base_recipes"][0]
    assert mine is restored["profiles"]["basic"]["base_recipes"][0]
    assert mine is restored["profiles"]["mixed"]["base_recipes"][0]
    assert mine is parsed["building_profiles"]["mine"]


def test_loaded_profiles_share_the_exact_canonical_building_object(inputs, tmp_path, monkeypatch):
    _freeze(tmp_path, monkeypatch, inputs)
    restored = company_sectors.load_baseline()
    assert (
        restored["profiles"]["company_lkab"]["base_recipes"][0]
        is restored["profiles"]["basic"]["base_recipes"][0]
    )
    assert (
        restored["profiles"]["company_ursus"]["base_recipes"][0]
        is restored["profiles"]["mixed"]["base_recipes"][1]
    )


def test_conflicting_runtime_copies_cannot_freeze_under_one_building_identity(inputs):
    runtime = company_sectors.derive(inputs)
    duplicate = copy.deepcopy(runtime["profiles"]["basic"]["base_recipes"][0])
    duplicate["groups"][0]["methods"][0]["modifiers"][0]["value"] = 999
    runtime["profiles"]["basic"]["base_recipes"][0] = duplicate
    with pytest.raises(ValueError, match="冲突的重复定义"):
        company_sectors._freeze(runtime)


@pytest.mark.parametrize(
    "damage",
    [
        "unknown",
        "missing",
        "duplicate",
        "order",
        "inline",
        "identity",
        "unused",
        "table_type",
        "duplicate_json_key",
    ],
)
def test_reference_format_rejects_bad_references_and_duplicate_definitions(
    inputs, tmp_path, monkeypatch, damage
):
    path = _freeze(tmp_path, monkeypatch, inputs)
    raw = path.read_text(encoding="utf-8")
    frozen = json.loads(raw)
    if damage == "unknown":
        frozen["profiles"]["company_lkab"]["base_recipes"] = ["unknown"]
    elif damage == "missing":
        frozen["building_profiles"].pop("mine")
    elif damage == "duplicate":
        frozen["profiles"]["company_lkab"]["base_recipes"] = ["mine", "mine"]
    elif damage == "order":
        frozen["profiles"]["mixed"]["base_recipes"] = ["motor", "mine"]
    elif damage == "inline":
        frozen["profiles"]["company_lkab"]["base_recipes"] = [frozen["building_profiles"]["mine"]]
    elif damage == "identity":
        frozen["building_profiles"]["mine"]["id"] = "motor"
    elif damage == "unused":
        frozen["building_profiles"]["unused"] = {
            **frozen["building_profiles"]["mine"],
            "id": "unused",
        }
    elif damage == "table_type":
        frozen["building_profiles"] = []
    else:
        path.write_text(
            raw.replace('"building_profiles": {', '"building_profiles": { "mine": {},', 1),
            encoding="utf-8",
            newline="\n",
        )
    if damage != "duplicate_json_key":
        path.write_text(company_sectors._canonical(frozen), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        company_sectors.load_baseline()


@pytest.mark.parametrize(
    "section", ["profiles", "rules", "readers", "sources", "parameters", "counts"]
)
def test_frozen_sections_cannot_self_attest_or_drift(inputs, tmp_path, monkeypatch, section):
    path = _freeze(tmp_path, monkeypatch, inputs)
    data = json.loads(path.read_bytes())
    if section == "profiles":
        data[section]["company_lkab"]["verified"] = True
    elif section == "rules":
        data[section][0]["value"] = 1.5
    elif section == "readers":
        data[section]["default"]["scope"] = "company"
    elif section == "sources":
        data[section][COMPANY] = "0" * 64
    elif section == "parameters":
        data[section]["demand_multiplier"] = 1.13
    else:
        data[section]["explicit_weight"] = 999
    path.write_text(company_sectors._canonical(data), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        company_sectors.verify_baseline(inputs)


@pytest.mark.parametrize("damage", ["whitespace", "extra_key", "missing_key", "bool_schema"])
def test_frozen_format_and_keys_are_strict(inputs, tmp_path, monkeypatch, damage):
    path = _freeze(tmp_path, monkeypatch, inputs)
    data = json.loads(path.read_bytes())
    if damage == "whitespace":
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        if damage == "extra_key":
            data["verified"] = True
        elif damage == "missing_key":
            data.pop("sources")
        else:
            data["schema"] = True
        path.write_text(company_sectors._canonical(data), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        company_sectors.load_baseline()


def test_actual_source_or_added_shadow_cannot_reuse_frozen_profile(inputs, tmp_path, monkeypatch):
    _freeze(tmp_path, monkeypatch, inputs)
    original = company_sectors.load_baseline()
    inputs[METHOD] = inputs[METHOD].replace(
        "goods_input_tools_add = 5", "goods_input_tools_add = 6", 1
    )
    with pytest.raises(ValueError, match="漂移"):
        company_sectors.verify_baseline(inputs)
    assert company_sectors.load_baseline() == original
    inputs["dlc/fixture/in_game/common/company_types/shadow.txt"] = "company_lkab = {}"
    with pytest.raises(ValueError):
        company_sectors.verify_baseline(inputs)


@pytest.mark.parametrize(
    ("family", "declaration"),
    [
        ("company_types", "company_lkab = { building_types = { mine } }"),
        ("buildings", "mine = { production_method_groups = { mining } }"),
        ("production_method_groups", "mining = { production_methods = { pick } }"),
        ("production_methods", "pick = { }"),
        ("goods", "iron = { cost = 1 }"),
        ("defines", "NAI = { COMPANY_TYPE_DEFAULT_BASE_WEIGHT = 100 }"),
        ("production_methods", "new_unused_method = { }"),
    ],
)
@pytest.mark.parametrize("prefix", ["", "dlc/fixture/in_game/"])
def test_production_game_reinventory_rejects_new_sources_and_cross_source_shadows(
    inputs, tmp_path, monkeypatch, family, declaration, prefix
):
    _freeze(tmp_path, monkeypatch, inputs)
    game = tmp_path / "game"
    source = f"{prefix}common/{family}/new_file.txt"
    path = game / source
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(declaration, encoding="utf-8", newline="\n")
    assert source in company_sectors.read_inputs(game)
    with pytest.raises(ValueError):
        company_sectors.verify_game(game)


@pytest.mark.parametrize("damage", ["claim", "missing_pm", "pm_type", "false_base", "profile_type"])
def test_offline_load_rejects_untrusted_nested_claims_without_current_game(
    inputs, tmp_path, monkeypatch, damage
):
    path = _freeze(tmp_path, monkeypatch, inputs)
    data = json.loads(path.read_bytes())
    profile = data["profiles"]["company_lkab"]
    group = data["building_profiles"][profile["base_recipes"][0]]["groups"][0]
    if damage == "claim":
        profile["verified"] = True
    elif damage == "missing_pm":
        group["methods"] = []
    elif damage == "pm_type":
        group["methods"][0] = None
    elif damage == "false_base":
        group["base"] = False
    else:
        profile["base_recipes"] = [None]
    path.write_text(company_sectors._canonical(data), encoding="utf-8", newline="\n")
    monkeypatch.setattr(config, "GAME", tmp_path / "absent-game")
    with pytest.raises(ValueError):
        company_sectors.load_baseline()


@pytest.mark.integration
def test_locked_full_company_scope_has_handwritten_department_and_default_denominators():
    inputs = {
        path.relative_to(config.GAME).as_posix(): path.read_text(encoding="utf-8-sig")
        for family in (
            "company_types",
            "buildings",
            "production_method_groups",
            "production_methods",
            "goods",
            "defines",
        )
        for path in (config.GAME / "common" / family).glob("*.txt")
    }
    installed_version = config.game_version()["caligula_branch"].removeprefix("release/")
    with version_contracts.select_version(installed_version):
        derived = company_sectors.derive(inputs)
    # Independent AST inventory of each exact installed release; these values
    # are handwritten witnesses, never copied from derive() at assertion time.
    expected_counts = {
        "1.14.5": {
            "companies": 221,
            "explicit_weight": 195,
            "implicit_weight": 26,
            "primary_buildings": 48,
        },
        "1.15.0": {
            "companies": 231,
            "explicit_weight": 205,
            "implicit_weight": 26,
            "primary_buildings": 49,
        },
        "1.15.1": {
            "companies": 231,
            "explicit_weight": 205,
            "implicit_weight": 26,
            "primary_buildings": 49,
        },
    }[installed_version]
    assert derived["counts"] == expected_counts
    for company, output, required in (
        ("company_lkab", "iron", "tools"),
        ("company_ursus", "engines", "steel"),
        ("company_colt_firearms", "small_arms", "hardwood"),
        ("company_j_p_coats", "clothes", "fabric"),
    ):
        profile = derived["profiles"][company]
        assert profile["market_outputs"] == [output]
        assert profile["common_inputs"] == [required]
    assert derived["profiles"]["company_basic_steel"]["common_inputs"] == ["coal", "iron"]
    assert derived["profiles"]["company_basic_metalworks"]["common_inputs"] == []
    assert any(row["field"] == "company_basic_steel.ai_weight" for row in derived["rules"])
    with version_contracts.select_version(installed_version):
        initialized = company_sectors.initialized_fields(derived)
    assert len(initialized) == 26
    assert any(row["field"] == "company_basic_gold_mining.ai_weight" for row in initialized)
    assert len({row["field"] for row in derived["rules"]}) == expected_counts["companies"]
    assert any(row["field"] == "company_de_beers.ai_weight" for row in derived["rules"])
    gaps = company_sectors.unsupported_facets(derived)
    assert gaps == []
    with version_contracts.select_version(installed_version):
        assert len(company_sectors.query_source_hashes(derived)) == 14


@pytest.mark.parametrize(
    ("company", "building", "prefix"),
    [("goldco", "building_gold_mine", "gold"), ("tradeco", "building_trade_center", "trade")],
)
def test_gold_and_trade_operating_business_benefits_use_real_same_building(
    special_inputs, company, building, prefix
):
    derived = company_sectors.derive(special_inputs)
    assert any(row["field"] == f"{company}.ai_weight" for row in derived["rules"])
    obj = {
        **_observed_building(building),
        "weekly_profit": 1,
        "occupancy": 0.9,
        "cash_reserves_ratio": 0.6,
    }
    facts = {f"company_{prefix}_need": True, f"company_{prefix}_pressure": True}
    _assert_joint(derived, company, facts, 1.20, observations={"any_scope_building": [obj]})
    _assert_joint(
        derived, company, facts, 1, observations={"any_scope_building": [obj]}, is_ai=False
    )
    assert not any(key.startswith("country_goods_gold_") for key in derived["readers"])
    assert not any(row["company"] == company for row in company_sectors.unsupported_facets(derived))


def test_gold_tools_cost_and_solvency_remain_independent_of_unknown_or_strong_business(
    special_inputs,
):
    derived = company_sectors.derive(special_inputs)
    obj = {**_observed_building("building_gold_mine"), "weekly_profit": 1, "occupancy": 0.75}
    _assert_joint(
        derived,
        "goldco",
        {
            "company_gold_need": True,
            "company_gold_pressure": None,
            "country_goods_tools_price": 0.5,
        },
        0.97,
        observations={"any_scope_building": [obj]},
    )
    _assert_joint(
        derived,
        "goldco",
        {
            "company_gold_need": None,
            "company_gold_pressure": None,
            "country_goods_tools_price": 0.5,
        },
        0.85,
    )
    obj.update({"occupancy": 0.9, "cash_reserves_ratio": 0.6})
    _assert_joint(
        derived,
        "goldco",
        {
            "company_gold_need": True,
            "company_gold_pressure": True,
            "country_goods_tools_price": 0.5,
            "default": True,
        },
        0.85,
        observations={"any_scope_building": [obj]},
    )


def test_gold_and_trade_opportunities_select_one_business_cause_not_two_rewards(special_inputs):
    derived = company_sectors.derive(special_inputs)
    objects = [
        {
            **_observed_building(kind),
            "weekly_profit": 1,
            "occupancy": 0.9,
            "cash_reserves_ratio": 0.6,
        }
        for kind in ("building_gold_mine", "building_trade_center")
    ]
    facts = {
        "company_gold_need": True,
        "company_gold_pressure": True,
        "company_trade_need": True,
        "company_trade_pressure": True,
    }
    _assert_joint(
        derived, "businessmixed", facts, 1.20, observations={"any_scope_building": objects}
    )
