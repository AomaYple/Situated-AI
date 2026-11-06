"""Reviewed static-type lifecycle closes twelve exact named initializers."""

from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from pdx import building_defaults, config, decision_adapters
from pdx.parser import parse_text

EXISTING = (
    ("01_industry", "building_arms_industry"),
    ("01_industry", "building_artillery_foundry"),
    ("02_agro", "building_livestock_ranch"),
    ("09_misc_resource", "building_logging_camp"),
    ("09_misc_resource", "building_rubber_plantation"),
    ("09_misc_resource", "building_fishing_wharf"),
    ("09_misc_resource", "building_whaling_station"),
    ("09_misc_resource", "building_oil_rig"),
    ("04_plantations", "building_coffee_plantation"),
    ("04_plantations", "building_sugar_plantation"),
    ("04_plantations", "building_banana_plantation"),
    ("03_mines", "building_copper_mine"),
)


@pytest.fixture(scope="module")
def current_inputs():
    return json.loads(
        (config.REPO / "research/vanilla-ai/1.15.0/production-inputs.json").read_bytes()
    )["inputs"]


@pytest.mark.parametrize(("stem", "identity"), EXISTING)
def test_exact_static_initializer_retains_full_parent_and_only_inserts_1000(
    current_inputs, stem, identity
):
    source = f"common/buildings/{stem}.txt"
    item = decision_adapters.InitialValue(
        source,
        (identity, "ai_value"),
        "common/defines/00_ai.txt",
        ("NAI", "PRODUCTION_BUILDING_BASE_VALUE"),
    )
    original = current_inputs[source]
    rendered = decision_adapters._initialize(original, [item], current_inputs, {})
    fragment = (
        f"\n\t# SITAI BEGIN initialized:{identity}.ai_value\n"
        "\tai_value = { value = 1000 }\n"
        f"\t# SITAI END initialized:{identity}.ai_value\n"
    )
    assert rendered.count(fragment) == 1
    assert rendered.replace(fragment, "", 1) == original
    assert not parse_text(rendered).errors


def test_accepted_sentinel_slots_and_getter_select_local_or_reference_member():
    data = json.loads((config.REPO / building_defaults.SELECTOR_ID).read_bytes())
    observations = {row["label"]: bytes.fromhex(row["bytes"]) for row in data["observations"]}
    # Independently read instruction atoms: xor al,al;ret versus mov al,1;ret.
    assert observations["reference-false-thunk"] == b"\x32\xc0\xc3"
    assert observations["reference-true-thunk"] == b"\xb0\x01\xc3"
    # Read +158, call slot0, branch on false; select reference or self; +560.
    assert (
        bytes.fromhex("488b8958010000488b01ff1084c07409488b8358010000eb03488bc3488db060050000")
        in observations["building-ai-getter"]
    )
    assert data["contract"]["dynamic_local_writer_permission"] is False
    assert data["contract"]["copper_initializer_permission"] is True
    assert set(data["contract"]["initializer_ids"]) == {identity for _, identity in EXISTING}
    assert data["contract"]["partial_leaf_prefixes"]["parser-preload-tail-thunk"] == [21, 20]
    assert len(data["contract"]["runtime_fragments"]) == 24


@pytest.mark.parametrize("identity", ["building_invented", "building_iron_mine"])
def test_scoped_static_evidence_does_not_authorize_new_type(current_inputs, identity):
    source = "common/buildings/03_mines.txt"
    parent = parse_text(current_inputs[source]).root.first("building_copper_mine")
    assert parent is not None
    with pytest.raises(ValueError, match="唯一缺省父结构/类别"):
        building_defaults.validate_initializer(
            source,
            (identity, "ai_value"),
            "common/defines/00_ai.txt",
            ("NAI", "PRODUCTION_BUILDING_BASE_VALUE"),
            parent,
        )


@pytest.mark.parametrize(
    "fault", ["source", "parent", "type", "selector", "permission", "exe", "span", "lineage"]
)
def test_static_selector_rejects_semantic_drift_after_outer_proof_repin(
    tmp_path, monkeypatch, fault
):
    data = json.loads((config.REPO / building_defaults.SELECTOR_ID).read_bytes())
    if fault == "source":
        data["script_hashes"]["common/buildings/01_industry.txt"] = "0" * 64
    elif fault == "parent":
        data["exact_types"][0]["parent_sha256"] = "0" * 64
    elif fault == "type":
        data["exact_types"][0]["source_kind"] = "dynamic_hq"
    elif fault == "selector":
        data["contract"]["source_selector"]["default_validity"] = True
    elif fault == "permission":
        data["contract"]["initializer_ids"].append("building_copper_mine")
    elif fault == "exe":
        data["exe"]["sha256"] = "0" * 64
    elif fault == "span":
        data["observations"][0]["bytes"] = "00"
    else:
        data["lineage"]["reviewed_candidate_sha256"] = "0" * 64
    raw = json.dumps(data).encode()
    proof = tmp_path / "selector.json"
    proof.write_bytes(raw)
    monkeypatch.setattr(building_defaults, "_SELECTOR", proof)
    monkeypatch.setattr(building_defaults, "_SELECTOR_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="静态表达式源精确合同漂移"):
        building_defaults.snapshot()


def test_default_proof_rejects_changed_static_source_reference_after_outer_repin(
    tmp_path, monkeypatch
):
    data = json.loads(building_defaults.MANIFEST.read_bytes())
    data["contract"]["expression_source"]["proof"] = "research/situated/other.json"
    raw = json.dumps(data).encode()
    proof = tmp_path / "defaults.json"
    proof.write_bytes(raw)
    monkeypatch.setattr(building_defaults, "MANIFEST", proof)
    monkeypatch.setattr(building_defaults, "MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="精确原生合同漂移"):
        building_defaults.snapshot()


@pytest.fixture(scope="module")
def copied_game(tmp_path_factory):
    if not (config.GAME / "common").is_dir():
        pytest.skip("requires pinned current installation")
    root = tmp_path_factory.mktemp("building-selector")
    game = root / "game"
    data = json.loads(building_defaults.MANIFEST.read_bytes())
    for source in data["script_hashes"]:
        destination = game / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config.GAME / source, destination)
    (root / "binaries").mkdir()
    shutil.copyfile(config.GAME.parent / "binaries/victoria3.exe", root / "binaries/victoria3.exe")
    return game


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["source", "exe"])
def test_existing_verify_game_rejects_real_source_or_executable_drift(copied_game, fault):
    path = (
        copied_game / "common/buildings/01_industry.txt"
        if fault == "source"
        else copied_game.parent / "binaries/victoria3.exe"
    )
    with path.open("r+b") as stream:
        original = stream.read(1)
        stream.seek(0)
        stream.write(bytes([original[0] ^ 1]))
    try:
        with pytest.raises(ValueError, match="原版或EXE与锁定证据不一致"):
            building_defaults.verify_game(copied_game)
    finally:
        with path.open("r+b") as stream:
            stream.write(original)
