"""锁定引擎证据的漂移/缺失拒收，不以相似字段或本机路径继承权限。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pdx.parser import parse_text
from pdx.situated import engine_scope, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.fixture
def proof_fixture(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    for name, value in {
        "caligula_branch": "release/1.14.5",
        "caligula_rev": "fixture",
        "clausewitz_branch": "fixture",
        "clausewitz_rev": "fixture",
    }.items():
        (tmp_path / f"{name}.txt").write_text(value, encoding="utf-8")
    executable = tmp_path / "binaries/victoria3.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"fixed-test-image\x05\x00\x00\x00\xc3")
    scripts = {"common/technology/technologies/sample.txt": b"sample = { ai_weight = 1 }\n"}
    data = {
        "exe": {
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "bytes": 21,
        },
        "script_hashes": {
            "common/technology/technologies/sample.txt": hashlib.sha256(
                b"sample = { ai_weight = 1 }\n"
            ).hexdigest()
        },
        "observations": [{"label": "scope tag", "file_offset": "0x10", "bytes": "05000000c3"}],
    }
    manifest = tmp_path / "proof.json"

    def freeze():
        raw = json.dumps(data).encode()
        manifest.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "MANIFEST", manifest)
        monkeypatch.setattr(engine_scope, "MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())

    freeze()
    return game, executable, scripts, data, freeze


def test_complete_pinned_evidence_proves_only_definition_identity(proof_fixture):
    game, _, inputs, _, _ = proof_fixture
    proof = engine_scope.technology_evidence(game, inputs)
    assert proof.verified
    assert "@engine/binaries/victoria3.exe" in dict(proof.source_hashes)
    definition = parse_text("sample = { ai_weight = { value = 1 } }").top_assignments[0]
    scope = vanilla_inventory._scope(
        "technology",
        ("ai_weight",),
        inputs,
        {},
        definition,
        "common/technology/technologies/sample.txt",
        technology_proof=proof,
    )
    assert (scope.actor, scope.target, scope.operation, scope.capability) == (
        "country",
        "definition_only:technology",
        "base_candidate_score",
        "direct",
    )
    assert "scope:technology" not in scope.target
    assert scope.evidence


@pytest.mark.parametrize("change", ["missing_exe", "exe_drift", "missing_script", "script_drift"])
def test_evidence_missing_or_drift_never_invents_scope(proof_fixture, change):
    game, executable, inputs, _, _ = proof_fixture
    if change == "missing_exe":
        executable.unlink()
    elif change == "exe_drift":
        executable.write_bytes(b"different engine")
    elif change == "missing_script":
        inputs.clear()
    else:
        inputs["common/technology/technologies/sample.txt"] = b"changed definition"
    proof = engine_scope.technology_evidence(game, inputs)
    assert proof.verified is False
    definition = parse_text("sample = { ai_weight = 1 }").top_assignments[0]
    scope = vanilla_inventory._scope(
        "technology",
        ("ai_weight",),
        inputs,
        {},
        definition,
        "common/technology/technologies/sample.txt",
        technology_proof=proof,
    )
    assert scope.actor == scope.target == "unknown"
    assert scope.capability == "pending"


@pytest.mark.parametrize("corruption", ["manifest_bytes", "length", "selected_bytes"])
def test_broken_frozen_attestation_is_an_error(proof_fixture, corruption):
    game, _, inputs, data, freeze = proof_fixture
    if corruption == "manifest_bytes":
        engine_scope.MANIFEST.write_bytes(b"{}")
    elif corruption == "length":
        data["exe"]["bytes"] = 22
        freeze()
    else:
        data["observations"][0]["bytes"] = "06000000c3"
        freeze()
    with pytest.raises(ValueError, match="锁定引擎作用域证据"):
        engine_scope.technology_evidence(game, inputs)


@pytest.mark.parametrize(
    ("directory", "field", "definition"),
    [
        ("company_types", ("ai_weight",), "sample = { ai_weight = 1 }"),
        ("technology", ("can_research",), "sample = { can_research = { always = yes } }"),
        ("technology", ("ai_weight",), "sample = { ai_weight = 1 ai_weight = 2 }"),
        ("technology", ("ai_weight",), "sample = 1"),
    ],
)
def test_proof_does_not_authorize_other_consumers_or_ambiguous_definitions(
    proof_fixture,
    directory,
    field,
    definition,
):
    game, _, inputs, _, _ = proof_fixture
    proof = engine_scope.technology_evidence(game, inputs)
    scope = vanilla_inventory._scope(
        directory,
        field,
        inputs,
        {},
        parse_text(definition).top_assignments[0],
        "common/technology/technologies/sample.txt",
        technology_proof=proof,
    )
    assert scope.capability == "pending"


def test_manifest_retains_raw_scope_and_formula_evidence():
    raw = engine_scope.MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == engine_scope.MANIFEST_SHA256
    data = json.loads(raw)
    assert data["consumer"] == {
        "directory": "technology",
        "field": "ai_weight",
        "actor_scope": "country",
        "target_scope": "definition_only:technology",
        "operation": "base_candidate_score",
        "capability": "direct",
    }
    assert data["exe"]["sha256"] == (
        "473186e8d8deba993651e0ae4cf02a003b02f5accb99b096a6a0a8bd9506cbaa"
    )
    points = {item["label"]: item for item in data["observations"]}
    assert points["country scope tag5 getter"]["bytes"] == "b805000000c3"
    assert points["AI three country scope slots context and value evaluator call"]["va"] == (
        "0x1415d0656"
    )
    assert data["interpretation"]["qualifier"].startswith("eligibility pre-check occurs BEFORE")
    assert len(data["limits"]) == 6
    assert all(not Path(key).is_absolute() for key in data["script_hashes"])


@pytest.mark.integration
def test_current_technology_scope_rechecks_actual_executable_and_all_sources():
    from pdx import config

    manifest = json.loads(engine_scope.MANIFEST.read_bytes())
    inputs = {source: (config.GAME / source).read_bytes() for source in manifest["script_hashes"]}
    proof = engine_scope.technology_evidence(config.GAME, inputs)
    assert proof.verified
    assert dict(proof.source_hashes)["@engine/binaries/victoria3.exe"] == manifest["exe"]["sha256"]
    assert proof.technology_sources == tuple(
        sorted(source for source in inputs if source.startswith("common/technology/technologies/"))
    )


def _discover_fixture(proof_fixture, monkeypatch):
    game, _, inputs, _, _ = proof_fixture
    monkeypatch.setattr(
        vanilla_inventory, "_inputs", lambda _: (dict(inputs), ("technology",), ("game",))
    )
    return vanilla_inventory.discover(game=game)


def test_new_unreviewed_source_does_not_inherit_pinned_source_proof(proof_fixture, monkeypatch):
    _, _, inputs, _, _ = proof_fixture
    inputs["common/technology/technologies/new.txt"] = b"unreviewed = { ai_weight = 1 }\n"
    result = _discover_fixture(proof_fixture, monkeypatch)
    rows = {row.definition: row for row in result.surfaces}
    assert rows["sample"].capability == "direct"
    assert rows["unreviewed"].capability == "pending"
    assert rows["unreviewed"].actor_scope == "unknown"
    assert result.discovered_count == 2


def test_cross_source_duplicate_technology_keeps_both_sides_pending(proof_fixture, monkeypatch):
    _, _, inputs, _, _ = proof_fixture
    inputs["common/technology/technologies/collision.txt"] = b"sample = { ai_weight = 2 }\n"
    result = _discover_fixture(proof_fixture, monkeypatch)
    assert result.discovered_count == 2
    assert result.legal_count == 0
    assert all(row.capability == "pending" for row in result.surfaces)
    assert all(
        row.ambiguity == "duplicate_technology_definition_merge_semantics_unknown"
        for row in result.surfaces
    )
    assert all(row.responsibility_step == "D0.03" for row in result.surfaces)
    assert len({row.declaration_id for row in result.surfaces}) == 2


def test_declaration_identity_survives_semantic_scope_rekey(proof_fixture, monkeypatch):
    proven = _discover_fixture(proof_fixture, monkeypatch)
    proof_fixture[1].unlink()
    unknown = _discover_fixture(proof_fixture, monkeypatch)
    assert proven.surfaces[0].surface_id != unknown.surfaces[0].surface_id
    assert proven.surfaces[0].declaration_id == unknown.surfaces[0].declaration_id
    assert (
        proven.as_dict()["surfaces"][0]["declaration_id"]
        == (unknown.as_dict()["surfaces"][0]["declaration_id"])
    )
    assert proven.scope_hash != unknown.scope_hash


@pytest.mark.parametrize("separator", [" ", "\n"])
def test_same_source_duplicate_without_weight_still_invalidates_first_definition(
    proof_fixture, monkeypatch, separator
):
    _, _, inputs, data, freeze = proof_fixture
    source = "common/technology/technologies/sample.txt"
    inputs[source] = (
        "sample = { ai_weight = 1 }" + separator + "sample = { era = era_5 }\n"
    ).encode()
    data["script_hashes"][source] = hashlib.sha256(inputs[source]).hexdigest()
    freeze()
    result = _discover_fixture(proof_fixture, monkeypatch)
    assert result.discovered_count == 1
    assert result.legal_count == 0
    assert result.surfaces[0].ambiguity == "duplicate_technology_definition_merge_semantics_unknown"
