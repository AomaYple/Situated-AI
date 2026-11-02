"""国家定义字段仅接受固定引擎和精确来源的证据。"""

import hashlib
import json

import pytest

from pdx.parser import parse_text
from pdx.situated import engine_scope, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.fixture
def country_proof(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    for name, value in {
        "caligula_branch": "release/1.14.5",
        "caligula_rev": "fixture",
        "clausewitz_branch": "fixture",
        "clausewitz_rev": "fixture",
    }.items():
        (tmp_path / f"{name}.txt").write_text(value, encoding="utf-8")
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"fixed country image")
    source = "common/country_creation/sample.txt"
    inputs = {source: b"sample = { ai_will_do = { always = yes } }\n"}
    data = {
        "exe": {
            "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
            "bytes": exe.stat().st_size,
        },
        "script_hashes": {source: hashlib.sha256(inputs[source]).hexdigest()},
        "observations": [{"label": "point", "file_offset": "0x0", "bytes": "6669786564"}],
    }
    manifest = tmp_path / "country.json"

    def freeze():
        raw = json.dumps(data).encode()
        manifest.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "COUNTRY_MANIFEST", manifest)
        monkeypatch.setattr(
            engine_scope, "COUNTRY_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest()
        )

    freeze()
    monkeypatch.setattr(
        vanilla_inventory, "_inputs", lambda _: (dict(inputs), ("country_creation",), ("game",))
    )
    return game, exe, source, inputs, data, freeze


@pytest.mark.parametrize("family", ["country_creation", "country_formation"])
def test_exact_country_contract(country_proof, family):
    game, _, source, inputs, _, _ = country_proof
    proof = engine_scope.country_evidence(game, inputs)
    definition = parse_text("sample = { ai_will_do = { always = yes } }").top_assignments[0]
    scope = vanilla_inventory._scope(
        family, ("ai_will_do",), inputs, {}, definition, source, country_proof=proof
    )
    expected = "direct" if family == "country_creation" else "pending"
    assert scope.capability == expected
    if expected == "direct":
        assert (scope.actor, scope.target, scope.operation) == (
            "country",
            "definition_only:country_creation",
            "eligibility",
        )


@pytest.mark.parametrize("change", ["missing_exe", "exe_drift", "missing_script", "script_drift"])
def test_missing_or_drifted_evidence_stays_pending(country_proof, change):
    game, exe, source, inputs, _, _ = country_proof
    if change == "missing_exe":
        exe.unlink()
    elif change == "exe_drift":
        exe.write_bytes(b"drift")
    elif change == "missing_script":
        inputs.clear()
    else:
        inputs[source] = b"changed"
    assert not engine_scope.country_evidence(game, inputs).verified


@pytest.mark.parametrize(
    "override",
    [
        "sample = { ai_will_do = { always = no } }",
        "REPLACE:sample = { ai_will_do = { always = no } }",
        "sample = 1",
        "sample = { possible = { always = yes } }",
    ],
)
@pytest.mark.parametrize("separator", [" ", "\n"])
def test_same_name_override_invalidates_all_sides(country_proof, override, separator):
    game, _, source, inputs, data, freeze = country_proof
    inputs[source] = ("sample = { ai_will_do = { always = yes } }" + separator + override).encode()
    data["script_hashes"][source] = hashlib.sha256(inputs[source]).hexdigest()
    freeze()
    result = vanilla_inventory.discover(game=game)
    assert result.surfaces
    assert all(row.capability == "pending" for row in result.surfaces)
    # Declaration identity is independent of inferred scope and REPLACE syntax.
    assert len({row.declaration_id for row in result.surfaces}) == len(result.surfaces)
    assert sorted(row.declaration_occurrence for row in result.surfaces) == list(
        range(1, len(result.surfaces) + 1)
    )


def test_new_source_does_not_inherit(country_proof):
    game, _, _, inputs, _, _ = country_proof
    inputs["common/country_creation/new.txt"] = b"other = { ai_will_do = { always = yes } }"
    rows = {row.definition: row for row in vanilla_inventory.discover(game=game).surfaces}
    assert rows["sample"].capability == "direct"
    assert rows["other"].capability == "pending"


def test_formation_has_independent_exact_source(country_proof):
    game, _, _, inputs, data, freeze = country_proof
    source = "common/country_formation/sample.txt"
    inputs[source] = b"formed = { ai_will_do = { always = yes } }"
    data["script_hashes"][source] = hashlib.sha256(inputs[source]).hexdigest()
    freeze()
    rows = {row.definition: row for row in vanilla_inventory.discover(game=game).surfaces}
    assert (
        rows["formed"].actor_scope,
        rows["formed"].target_scope,
        rows["formed"].operation,
        rows["formed"].capability,
    ) == ("country", "definition_only:country_formation", "eligibility", "direct")


@pytest.mark.parametrize(
    "override",
    [
        "sample = { ai_will_do = { always = no } }",
        "REPLACE:sample = 1",
        "sample = { possible = { always = yes } }",
    ],
)
def test_cross_source_override_invalidates_both_sides(country_proof, override):
    game, _, _, inputs, _, _ = country_proof
    inputs["common/country_creation/new.txt"] = override.encode()
    result = vanilla_inventory.discover(game=game)
    assert result.surfaces
    assert all(row.capability == "pending" for row in result.surfaces)


@pytest.mark.parametrize(
    "declaration",
    [
        "sample = { ai_will_do = {} ai_will_do = {} }",
        "REPLACE:sample = { ai_will_do = {} }",
        "sample = 1",
    ],
)
def test_ambiguous_declaration_is_not_proven(country_proof, declaration):
    game, _, source, inputs, _, _ = country_proof
    proof = engine_scope.country_evidence(game, inputs)
    definition = parse_text(declaration).top_assignments[0]
    scope = vanilla_inventory._scope(
        "country_creation", ("ai_will_do",), inputs, {}, definition, source, country_proof=proof
    )
    assert scope.capability == "pending"


@pytest.mark.parametrize("corruption", ["manifest", "length", "bytes"])
def test_corrupt_attestation_is_error(country_proof, corruption):
    game, _, _, inputs, data, freeze = country_proof
    if corruption == "manifest":
        engine_scope.COUNTRY_MANIFEST.write_bytes(b"{}")
    elif corruption == "length":
        data["exe"]["bytes"] += 1
        freeze()
    else:
        data["observations"][0]["bytes"] = "00"
        freeze()
    with pytest.raises(ValueError, match="锁定国家定义作用域证据"):
        engine_scope.country_evidence(game, inputs)


def test_frozen_manifest_keeps_raw_evidence():
    raw = engine_scope.COUNTRY_MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == engine_scope.COUNTRY_MANIFEST_SHA256
    data = json.loads(raw)
    assert data["exe"]["bytes"] == 97774200
    assert len(data["script_hashes"]) == 3
    assert len(data["observations"]) >= 55
    assert {c["family"] for c in data["contracts"]} == {"country_creation", "country_formation"}
