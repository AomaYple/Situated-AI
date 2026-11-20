"""Independent native-company and default-score evidence, not gameplay acceptance.

The byte witnesses connect the empty numeric expression to the real define.
They authorize only an exactly missing source field, never a zero-score rewrite.
Special-sector inventory assertions do not claim that a sector plan is implemented.
"""

import hashlib
import json

import pytest

from pdx import company_sectors, config, decision_adapters, decision_rules
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import engine_scope_115

BASIC_NAMES = frozenset(
    [
        "agriculture_1",
        "agriculture_2",
        "chemicals",
        "colonial_plantations_1",
        "colonial_plantations_2",
        "electrics",
        "fabrics",
        "fishing",
        "food",
        "forestry",
        "gold_mining",
        "home_goods",
        "metal_mining",
        "metalworks",
        "mineral_mining",
        "motors",
        "munitions",
        "oil",
        "paper",
        "shipyards",
        "silk_and_dye",
        "steel",
        "textiles",
        "weapons",
        "wine_and_fruit",
    ]
)
IMPLICIT = {f"company_basic_{name}" for name in BASIC_NAMES} | {"company_construction_power_bloc"}
SPECIAL_GROUPS = {
    "building_railway": (
        "company_cfr",
        "company_cordoba_railway",
        "company_egyptian_rail",
        "company_great_indian_railway",
        "company_gwr",
        "company_imperial_ethiopian_railways",
        "company_iranian_state_railway",
        "company_orient_express",
        "company_prussian_state_railways",
        "company_sao_paulo_railway",
        "company_tashkent_railroad",
    ),
    "building_power_plant": (
        "company_calcutta_electric",
        "company_eea",
        "company_electricidad_de_caracas",
        "company_hanseong_jeongi_hoesa",
        "company_ingolstadt_electrical_company",
        "company_siam_electrical_company_limited",
        "company_tokyo_electric_light_company",
    ),
    "building_port": (
        "company_ap_moller",
        "company_sudamericana_de_vapores",
        "company_white_star_line",
    ),
    "building_gold_mine": ("company_de_beers",),
}
MIXED_SPECIAL = {
    "company_lanfang_kongsi": {"building_gold_mine", "building_port"},
    "company_panama_company": {"building_trade_center", "building_port"},
    "company_suez_company": {"building_trade_center", "building_port"},
}


@pytest.fixture(scope="module")
def evidence():
    path, _, digest = engine_scope_115.manifest("company-default")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    return json.loads(raw)


@pytest.mark.unit
def test_default_contract_has_exact_source_boundary_and_independent_parent(evidence):
    parent = evidence["parent_scope_manifest"]
    path = config.REPO / parent["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == parent["sha256"]
    assert evidence["evidence_category"] == "static_check"
    assert {row["id"] for row in evidence["implicit_companies"]} == IMPLICIT
    assert len(evidence["implicit_companies"]) == 26
    assert len(evidence["contracts"]) == 1
    contract = evidence["contracts"][0]
    assert (contract["actor"], contract["target"], contract["field"]) == (
        "country",
        "definition_only:company_type",
        "ai_weight",
    )
    assert contract["default_value"] == 1
    assert contract["source_requirement"] == "exactly_missing_ai_weight_only"
    assert contract["explicit_empty_requirement"] == "reject_initializer"
    assert contract["explicit_nonpositive_requirement"] == "preserve_native_score_and_rejection"


@pytest.mark.unit
def test_default_branch_and_define_bridge_are_covered_by_current_ranges(evidence):
    contract = evidence["contracts"][0]
    intervals = {row["label"]: row for row in evidence["observations"]}
    for label, fields in (
        (
            "company empty expression branch and default load",
            ("empty_expression_branch", "default_load", "result_store"),
        ),
        ("company numeric evaluator", ("consumer", "nonempty_expression_branch", "result_return")),
        ("define typed setter and exact global write", ("define_setter", "define_global_write")),
        ("define namespace/key/global bridge", ("define_binding",)),
        ("define namespace/key/global registration", ("define_registration",)),
    ):
        region = intervals[label]
        start = int(region["va"], 16)
        for field in fields:
            assert start <= int(contract[field], 16) < start + region["size"], (label, field)
    for label, literal in (
        ("NAI namespace NUL literal", b"NAI\0"),
        ("company default key NUL literal", b"COMPANY_TYPE_DEFAULT_BASE_WEIGHT\0"),
    ):
        region = intervals[label]
        assert region["size"] == len(literal)
        assert region["sha256"] == hashlib.sha256(literal).hexdigest()


@pytest.fixture(scope="module")
def native():
    if not config.GAME.is_dir():
        pytest.skip("需要锁定原版：游戏目录不可用")
    inputs = company_sectors.read_inputs(config.GAME)
    profiles = company_sectors.derive(inputs)["profiles"]
    return inputs, profiles


@pytest.mark.integration
def test_current_exe_and_scripts_match_independent_default_witnesses(evidence):
    executable = config.GAME.parent / evidence["exe"]["path"]
    if not executable.is_file():
        pytest.skip("locked Victoria 3 Windows executable unavailable")
    raw = executable.read_bytes()
    assert len(raw) == evidence["exe"]["bytes"]
    assert hashlib.sha256(raw).hexdigest() == evidence["exe"]["sha256"]
    for row in evidence["observations"]:
        start = int(row["file_offset"], 16)
        window = raw[start : start + row["size"]]
        assert len(window) == row["size"]
        assert hashlib.sha256(window).hexdigest() == row["sha256"]
    for source, expected_sha in evidence["script_hashes"].items():
        assert hashlib.sha256((config.GAME / source).read_bytes()).hexdigest() == expected_sha


@pytest.mark.unit
def test_company_consumer_metadata_names_selected_independent_scope_evidence():
    from pdx.situated import engine_scope

    source, policy = next(
        (source, policy)
        for source, policy in decision_adapters.load().policies
        if source.startswith("common/company_types/")
    )
    contract = decision_rules.contract(policy, owner="consumer_adapters", source=source)
    path, identity, digest = engine_scope._company_manifest()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert engine_scope.company_snapshot() == path.read_bytes()
    assert identity == "research/situated/1.15.2/engine-company.json"
    rules = contract["rules"]
    assert isinstance(rules, list)
    assert rules
    for rule in rules:
        assert isinstance(rule, dict)
        assert rule["consumer"]["scope_evidence"] == identity
        assert rule["consumer"]["role"] == "vanilla_company_base_candidate_weight"


@pytest.mark.integration
def test_implicit_population_and_native_define_are_exact(native):
    inputs, profiles = native
    assert {name for name, row in profiles.items() if not row["explicit_weight"]} == IMPLICIT
    basic = parse_text(inputs["common/company_types/99_basic_companies.txt"]).root
    assert {row.key for row in basic.assignments()} == IMPLICIT
    for row in basic.assignments():
        assert isinstance(row.value, Block)
        assert row.value.all("ai_weight") == []
        assert len(row.value.all("possible")) == 1
        assert len(row.value.all("ai_will_do")) == 1
    defines = parse_text(inputs["common/defines/00_ai.txt"]).root.all("NAI")
    assert len(defines) == 1
    assert isinstance(defines[0].value, Block)
    default = defines[0].value.all("COMPANY_TYPE_DEFAULT_BASE_WEIGHT")
    assert len(default) == 1
    assert isinstance(default[0].value, Scalar)
    assert default[0].value.unquoted == "1"


@pytest.mark.integration
def test_special_population_has_real_primary_sectors_not_extension_inventions(native):
    _inputs, profiles = native
    expected = set(MIXED_SPECIAL)
    for names in SPECIAL_GROUPS.values():
        expected.update(names)
    migrated_shipyards = {"company_ap_moller", "company_sudamericana_de_vapores"}
    expected -= migrated_shipyards
    # Anchorage now supplies local services; every base-port PM produces
    # goods, so the port recipe includes merchant-marine market outputs.
    expected -= {"company_white_star_line", *MIXED_SPECIAL}
    actual = {
        name
        for name, row in profiles.items()
        if row["explicit_weight"] and not row["market_outputs"]
    }
    assert actual == expected
    assert len(actual) == 19
    for building, names in SPECIAL_GROUPS.items():
        for name in names:
            if name in migrated_shipyards:
                assert profiles[name]["primary"] == ["building_shipyard"]
                assert profiles[name]["market_outputs"] == ["clippers", "steamers"]
            else:
                assert profiles[name]["primary"] == [building]
    for name, buildings in MIXED_SPECIAL.items():
        assert set(profiles[name]["primary"]) == buildings


@pytest.mark.integration
@pytest.mark.parametrize(
    ("company", "good", "reason"),
    [
        ("company_gwr", "transportation", "local_good_requires_state_market_evidence"),
        ("company_calcutta_electric", "electricity", "local_good_requires_state_market_evidence"),
        ("company_de_beers", "gold", "fixed_price_good_retains_native_mechanism"),
        ("company_white_star_line", None, "no_mandatory_output_recipe_group"),
        ("company_suez_company", None, "no_goods_output_native_service"),
    ],
)
def test_special_recipe_exclusions_have_independent_native_causes(native, company, good, reason):
    _inputs, profiles = native
    if company == "company_white_star_line":
        good, reason = "services", "local_good_requires_state_market_evidence"
    assert any(
        row["good"] == good and row["reason"] == reason for row in profiles[company]["native_only"]
    )


@pytest.mark.integration
def test_merchant_marine_and_versioned_port_outputs_retain_native_options(native):
    inputs, profiles = native
    goods = []
    for source, text in inputs.items():
        if source.startswith("common/goods/"):
            goods.extend(parse_text(text).root.all("merchant_marine"))
    assert len(goods) == 1
    assert isinstance(goods[0].value, Block)
    for flag in ("local", "fixed_price"):
        assert goods[0].value.all(flag) == []
    assert goods[0].value.all("tradeable") == []
    # White Star remains a real port consumer in both versions. The two
    # current shipyard companies are checked independently above.
    port = profiles["company_white_star_line"]["base_recipes"][0]
    # Independent exact AST witnesses for the newly productive anchorage,
    # all four native base methods, and the local-services exclusion.
    methods = parse_text(inputs["common/production_methods/11_private_infrastructure.txt"]).root
    group_entry = parse_text(
        inputs["common/production_method_groups/07_government.txt"]
    ).root.first("pmg_base_building_port")
    assert group_entry is not None
    assert isinstance(group_entry.value, Block)
    method_list = group_entry.value.first("production_methods")
    assert method_list is not None
    assert isinstance(method_list.value, Block)
    names = [node.text for node in method_list.value.scalars()]
    assert names == ["pm_anchorage", "pm_basic_port", "pm_industrial_port", "pm_modern_port"]
    for name, good, quantity in (
        ("pm_anchorage", "services", "0.5"),
        ("pm_basic_port", "merchant_marine", "9"),
        ("pm_industrial_port", "merchant_marine", "20"),
        ("pm_modern_port", "merchant_marine", "30"),
    ):
        method = methods.first(name)
        assert method is not None
        assert isinstance(method.value, Block)
        modifiers = method.value.first("building_modifiers")
        assert modifiers is not None
        assert isinstance(modifiers.value, Block)
        workforce = modifiers.value.first("workforce_scaled")
        assert workforce is not None
        assert isinstance(workforce.value, Block)
        output = workforce.value.first(f"goods_output_{good}_add")
        assert output is not None
        assert isinstance(output.value, Scalar)
        assert output.value.unquoted == quantity
    assert port["potential_outputs"] == ["merchant_marine", "services"]
    assert port["market_outputs"] == ["merchant_marine"]
    service = parse_text(inputs["common/goods/00_goods.txt"]).root.first("services")
    assert service is not None
    assert isinstance(service.value, Block)
    local = service.value.first("local")
    assert local is not None
    assert isinstance(local.value, Scalar)
    assert local.value.unquoted == "yes"
