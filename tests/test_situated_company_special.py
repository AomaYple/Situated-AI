"""Independent native-company and default-score evidence, not gameplay acceptance.

The byte witnesses connect the empty numeric expression to the real define.
They authorize only an exactly missing source field, never a zero-score rewrite.
Special-sector inventory assertions do not claim that a sector plan is implemented.
"""

import hashlib
import json
import struct
from pathlib import Path

import pytest

from pdx import company_sectors, config, decision_adapters, decision_rules, version_contracts
from pdx.model import Block, Scalar
from pdx.parser import parse_text

MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "research/situated/victoria3-1.14.5-company-default-scope.json"
)
MANIFEST_SHA = "3295f597b36c531ca9ae671240bae0f0fa6a698ca9a67cf2c095927bd0378c6e"
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
    raw = MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA
    return json.loads(raw)


def _observation(evidence, label):
    rows = [row for row in evidence["observations"] if row["label"] == label]
    assert len(rows) == 1
    return int(rows[0]["va"], 16), bytes.fromhex(rows[0]["bytes"])


def _rip(va, raw, start, size, displacement):
    return va + start + size + struct.unpack_from("<i", raw, start + displacement)[0]


@pytest.mark.unit
def test_default_contract_has_exact_source_boundary_and_independent_parent(evidence):
    parent = evidence["parent_scope_manifest"]
    path = MANIFEST.parents[2] / parent["path"]
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
def test_empty_expression_branch_loads_define_global_and_returns_it(evidence):
    va, raw = _observation(evidence, "company empty expression default branch")
    assert va == 0x14169A3D0
    assert raw == bytes.fromhex(
        "498bf0488bfa488d999003000083bba800000000750f488b051b863304488902e93c010000"
    )
    assert raw[20] == 0x75
    assert 0x14169A3E4 + 2 + raw[21] == 0x14169A3F5
    assert _rip(va, raw, 22, 7, 3) == 0x1459D2A08
    assert raw[29:32] == bytes.fromhex("488902")  # write the loaded score to [rdx]
    assert _rip(va, raw, 32, 5, 1) == 0x14169A531
    tail_va, tail = _observation(evidence, "company score return")
    assert tail_va == 0x14169A531
    assert tail[:3] == bytes.fromhex("488bc7")  # return the original result pointer
    assert tail[-1] == 0xC3


@pytest.mark.unit
def test_define_bridge_uses_same_global_and_exact_namespace_key(evidence):
    va, raw = _observation(evidence, "define namespace key and global bridge")
    assert va == 0x140975A70
    assert raw[3:6] == bytes.fromhex("4c8d0d")
    assert _rip(va, raw, 3, 7, 3) == 0x1459D2A08
    assert _rip(va, raw, 10, 7, 3) == 0x1445169FC
    assert _rip(va, raw, 17, 7, 3) == 0x144520C18
    namespace_va, namespace = _observation(evidence, "NAI namespace literal")
    key_va, key = _observation(evidence, "default weight key literal")
    assert (namespace_va, namespace) == (0x1445169FC, b"NAI\0")
    assert key_va == 0x144520C18
    assert key.rstrip(b"\0") == b"COMPANY_TYPE_DEFAULT_BASE_WEIGHT"
    setter_va, setter = _observation(evidence, "define typed setter and global write")
    assert setter[54:57] == bytes.fromhex("488905")
    assert _rip(setter_va, setter, 54, 7, 3) == 0x1459D2A08


@pytest.mark.unit
def test_nonempty_numeric_path_keeps_country_scope_and_original_evaluator(evidence):
    va, raw = _observation(evidence, "company score country numeric evaluation")
    assert va == 0x14169A432
    assert raw[:10] == bytes.fromhex("b8050000006689442430")
    assert raw[-11:-5] == bytes.fromhex("488bd7488bcb")
    assert _rip(va, raw, len(raw) - 5, 5, 1) == 0x140D9F820


@pytest.fixture(scope="module")
def native():
    if not config.GAME.is_dir():
        pytest.skip("locked Victoria 3 installation unavailable")
    inputs = company_sectors.read_inputs(config.GAME)
    profiles = company_sectors.derive(inputs)["profiles"]
    return inputs, profiles


@pytest.mark.integration
def test_current_exe_and_scripts_match_independent_default_witnesses(evidence):
    if version_contracts.active_version() == "1.15.0":
        from pdx.situated import engine_scope_115

        path, _identity, digest = engine_scope_115.manifest("company-default")
        frozen = path.read_bytes()
        assert hashlib.sha256(frozen).hexdigest() == digest
        evidence = json.loads(frozen)
    executable = config.GAME.parent / evidence["exe"]["path"]
    if not executable.is_file():
        pytest.skip("locked Victoria 3 Windows executable unavailable")
    raw = executable.read_bytes()
    assert len(raw) == evidence["exe"]["bytes"]
    assert hashlib.sha256(raw).hexdigest() == evidence["exe"]["sha256"]
    for row in evidence["observations"]:
        start = int(row["file_offset"], 16)
        expected = bytes.fromhex(row["bytes"])
        assert raw[start : start + len(expected)] == expected
    for source, expected_sha in evidence["script_hashes"].items():
        assert hashlib.sha256((config.GAME / source).read_bytes()).hexdigest() == expected_sha


@pytest.mark.unit
@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
def test_company_consumer_metadata_names_selected_independent_scope_evidence(version):
    from pdx.situated import engine_scope

    with version_contracts.select_version(version):
        source, policy = next(
            (source, policy)
            for source, policy in decision_adapters.load().policies
            if source.startswith("common/company_types/")
        )
        contract = decision_rules.contract(policy, owner="consumer_adapters", source=source)
        path, identity, digest = engine_scope._company_manifest()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        assert engine_scope.company_snapshot() == path.read_bytes()
        assert identity == f"research/situated/victoria3-{version}-company-scope.json"
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
    current = version_contracts.active_version() == "1.15.0"
    migrated_shipyards = {"company_ap_moller", "company_sudamericana_de_vapores"}
    if current:
        expected -= migrated_shipyards
    actual = {
        name
        for name, row in profiles.items()
        if row["explicit_weight"] and not row["market_outputs"]
    }
    assert actual == expected
    assert len(actual) == (23 if current else 25)
    for building, names in SPECIAL_GROUPS.items():
        for name in names:
            if current and name in migrated_shipyards:
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
    assert any(
        row["good"] == good and row["reason"] == reason for row in profiles[company]["native_only"]
    )


@pytest.mark.integration
def test_merchant_marine_is_ordinary_good_but_port_has_outputless_option(native):
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
    assert port["potential_outputs"] == ["merchant_marine"]
    assert port["market_outputs"] == []
