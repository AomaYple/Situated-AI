"""Current building defaults require independent PE and exact native shape evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os

import pytest

from pdx import config, decision_adapters
from pdx.situated import engine_building_115, engine_scope_115


@pytest.mark.integration
def test_current_building_default_verifies_both_native_define_branches_and_executable():
    data = json.loads(engine_building_115.snapshot())
    contract = data["contracts"][0]
    assert len(engine_building_115.authorized_fields()) == 11
    assert {row["value"] for row in contract["default_branches"]} == {1000}
    assert contract["selection"] == "valid_template_else_self"
    assert len(data["observations"]) == 37
    hashes = dict(engine_building_115.verify_game(config.GAME))
    assert hashes["@engine/binaries/victoria3.exe"] == engine_scope_115.EXE_SHA256
    assert hashes["common/defines/00_ai.txt"] == data["script_hashes"]["common/defines/00_ai.txt"]


@pytest.mark.parametrize(
    "damage",
    ["native-pin", "extra-field", "scope", "template-selection", "government-default", "runtime"],
)
def test_rebound_manifest_cannot_expand_exact_initializer_contract(tmp_path, monkeypatch, damage):
    data = json.loads(engine_building_115.snapshot())
    if damage == "native-pin":
        data["native_authority"]["sha256"] = "0" * 64
    elif damage == "extra-field":
        row = copy.deepcopy(data["implicit_buildings"][0])
        row["field"] = "building_company_headquarter.ai_value"
        data["implicit_buildings"].append(row)
    elif damage == "scope":
        data["contracts"][0]["actor"] = "country"
    elif damage == "template-selection":
        data["contracts"][0]["selection"] = "always_self"
    elif damage == "government-default":
        data["contracts"][0]["default_branches"][1]["value"] = 500
    else:
        data["runtime"] = "verified"
    raw = json.dumps(data).encode()
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(raw)
    monkeypatch.setitem(
        engine_scope_115.MANIFESTS,
        "building-default",
        (str(candidate), hashlib.sha256(raw).hexdigest()),
    )
    with pytest.raises(ValueError, match="exact initializer contract drift"):
        engine_building_115.snapshot()


def test_missing_engine_manifest_blocks_adapter_loading(monkeypatch, tmp_path):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.15.0")
    _, digest = engine_scope_115.MANIFESTS["building-default"]
    monkeypatch.setitem(
        engine_scope_115.MANIFESTS, "building-default", (str(tmp_path / "absent.json"), digest)
    )
    with pytest.raises(FileNotFoundError):
        decision_adapters.load()


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["source", "missing-executable", "wrong-executable"])
def test_installed_drift_blocks_initializer_proof(tmp_path, damage):
    data = json.loads(engine_building_115.snapshot())
    game = tmp_path / "game"
    for source in data["script_hashes"]:
        target = game / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((config.GAME / source).read_bytes())
    executable = tmp_path / "binaries/victoria3.exe"
    executable.parent.mkdir()
    if damage == "source":
        os.link(config.GAME.parent / "binaries/victoria3.exe", executable)
        source = game / "common/defines/00_ai.txt"
        source.write_bytes(
            source.read_bytes().replace(
                b"GOVERNMENT_BUILDING_BASE_VALUE = 1000", b"GOVERNMENT_BUILDING_BASE_VALUE = 999"
            )
        )
    elif damage == "wrong-executable":
        executable.write_bytes(b"different engine")
    with pytest.raises(ValueError, match="installed source or executable drift"):
        engine_building_115.verify_game(game)
