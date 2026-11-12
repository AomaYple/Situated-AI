"""The current pact reader cannot borrow historical permissions or value units."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import replace

import pytest

from pdx import config, decision_interfaces, decision_rules, distribution, version_contracts
from pdx.situated import engine_reader_115, engine_scope_115, joint_chain_contract
from pdx.situated import production_profile as native


@pytest.mark.integration
def test_current_reader_has_independent_executable_and_native_source_identity():
    data = json.loads(engine_reader_115.snapshot())
    assert len(data["observations"]) == 34
    assert len(data["script_hashes"]) == 8
    assert data["flag_map"]["is_defensive_pact_index"] == 1
    hashes = dict(engine_reader_115.verify_game(config.GAME))
    assert hashes["@engine/binaries/victoria3.exe"] == (
        engine_scope_115.EXE_SHA256_1151
        if version_contracts.active_version() == "1.15.1"
        else engine_scope_115.EXE_SHA256
    )


def test_current_reader_and_joint_chain_use_barracks_levels_without_rewriting_history(monkeypatch):
    original = decision_rules.SOURCE.read_bytes()
    historical = tomllib.loads(original.decode())
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.15.0")
    current = decision_rules.load()
    readers = {reader.key: reader for reader in current.readers}
    for key in ("native_army_capacity", "native_marine_capacity"):
        reader = readers[key]
        assert reader.unit == "barracks_levels"
        assert decision_interfaces.reader_scope(reader, ()) == "country"
        signature = joint_chain_contract._expected_reader_signature(key)
        assert signature is not None
        assert signature[7] == "barracks_levels"
        with pytest.raises(ValueError, match="单位"):
            decision_interfaces.reader_scope(replace(reader, unit="battalions"), ())
        assert historical["readers"][key]["unit"] == "battalions"
    assert decision_rules.SOURCE.read_bytes() == original
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.14.5")
    old = {reader.key: reader for reader in decision_rules.load().readers}
    assert old["native_army_capacity"].unit == "battalions"
    signature = joint_chain_contract._expected_reader_signature("native_army_capacity")
    assert signature is not None
    assert signature[7] == "battalions"
    assert current.source_sha256 != decision_rules.load().source_sha256


def test_current_discovery_never_opens_historical_getter_manifest(monkeypatch):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.15.0")
    monkeypatch.setattr(
        decision_interfaces, "_LJ10_EVIDENCE", config.REPO / "absent-old-proof.json"
    )
    assert decision_interfaces.proven_reader_words() == frozenset(
        {"num_defensive_pacts", *engine_reader_115.NATIVE_VALUES}
    )


@pytest.mark.parametrize(
    "damage",
    ["foreign-scope", "wrong-unit", "active-runtime", "old-exe", "flag-index", "old-strategy"],
)
def test_rebound_reader_evidence_cannot_expand_permission(tmp_path, monkeypatch, damage):
    data = json.loads(engine_reader_115.snapshot())
    if damage == "foreign-scope":
        data["reader"]["scope"] = "target_country"
    elif damage == "wrong-unit":
        data["positive_native_guard"]["readers"][0]["unit"] = "battalions"
    elif damage == "active-runtime":
        data["runtime"] = "verified"
    elif damage == "old-exe":
        data["exe"]["sha256"] = "0" * 64
    elif damage == "flag-index":
        data["flag_map"]["is_defensive_pact_index"] = 0
    else:
        data["parent_scope_manifest"]["sha256"] = "0" * 64
    raw = json.dumps(data).encode()
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(raw)
    monkeypatch.setitem(
        (
            engine_scope_115.MANIFESTS_1151
            if version_contracts.active_version() == "1.15.1"
            else engine_scope_115.MANIFESTS
        ),
        "defensive-pact-reader",
        (str(candidate), hashlib.sha256(raw).hexdigest()),
    )
    with pytest.raises(ValueError, match="exact reader or native-value contract drift"):
        engine_reader_115.snapshot()


@pytest.mark.parametrize(
    ("section", "field", "impostor"),
    [
        ("flag_map", "is_defensive_pact_index", True),
        ("flag_map", "is_defensive_pact_index", 1.0),
        ("exe", "bytes", float(engine_scope_115.EXE_BYTES)),
    ],
)
def test_rebound_reader_integer_identity_rejects_equal_nonintegers(
    tmp_path, monkeypatch, section, field, impostor
):
    data = json.loads(engine_reader_115.snapshot())
    data[section][field] = impostor
    raw = json.dumps(data).encode()
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(raw)
    monkeypatch.setitem(
        (
            engine_scope_115.MANIFESTS_1151
            if version_contracts.active_version() == "1.15.1"
            else engine_scope_115.MANIFESTS
        ),
        "defensive-pact-reader",
        (str(candidate), hashlib.sha256(raw).hexdigest()),
    )
    with pytest.raises(ValueError, match="exact reader or native-value contract drift"):
        engine_reader_115.snapshot()


@pytest.mark.integration
def test_current_original_value_drift_blocks_getter_proof(tmp_path):
    data = json.loads(engine_reader_115.snapshot())
    game = tmp_path / "game"
    for source in data["script_hashes"]:
        target = game / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((config.GAME / source).read_bytes())
    executable = tmp_path / "binaries/victoria3.exe"
    executable.parent.mkdir()
    os.link(config.GAME.parent / "binaries/victoria3.exe", executable)
    target = game / "common/script_values/ai_script_values.txt"
    target.write_bytes(target.read_bytes() + b"\n# changed named-value source\n")
    with pytest.raises(ValueError, match="installed source or executable drift"):
        engine_reader_115.verify_game(game)


@pytest.mark.integration
def test_broad_online_generation_checks_current_reader_closure(monkeypatch):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.15.0")
    monkeypatch.setattr(distribution, "production_configuration", lambda **_: (None, None))

    def reject(_):
        raise ValueError("current reader drift")

    monkeypatch.setattr(engine_reader_115, "verify_game", reject)
    with pytest.raises(ValueError, match="current reader drift"):
        distribution.package_inputs()


def test_three_consumer_profile_has_no_legacy_reader_dependency(monkeypatch):
    def reject(*_, **__):
        raise AssertionError("three-consumer profile must not require the legacy getter")

    monkeypatch.setattr(engine_reader_115, "snapshot", reject)
    monkeypatch.setattr(engine_reader_115, "verify_game", reject)
    with version_contracts.select_version("1.15.0"):
        profile = native.load_profile(native.BASELINE_ROOT)
        files = distribution.profile_outputs(profile)
    assert "common/decrees/00_decree.txt" in files
