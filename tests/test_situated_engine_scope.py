"""锁定引擎证据的漂移/缺失拒收，不以相似字段或本机路径继承权限。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from _engine_evidence import compact_image, current_manifest, repin_manifest
from conftest import configure_current_identity

from pdx.parser import parse_text
from pdx.situated import engine_scope, engine_scope_115, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.fixture
def proof_fixture(tmp_path, monkeypatch):
    configure_current_identity(tmp_path, monkeypatch)
    game = tmp_path / "game"
    game.mkdir()
    source = "common/technology/technologies/sample.txt"
    inputs = {source: b"sample = { ai_weight = 1 }\n"}
    data = current_manifest("technology")
    executable = compact_image(tmp_path, data)

    def freeze():
        data["script_hashes"] = {source: hashlib.sha256(inputs[source]).hexdigest()}
        repin_manifest(monkeypatch, tmp_path / "proof.json", "technology", data)

    freeze()
    return game, executable, inputs, data, freeze


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
        engine_scope_115.manifest("technology")[0].write_bytes(b"{}")
    elif corruption == "length":
        data["exe"]["bytes"] += 1
        freeze()
    else:
        data["observations"][0]["sha256"] = "0" * 64
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


def test_manifest_retains_scope_and_formula_evidence():
    data = current_manifest("technology")
    assert data["consumer"] == {
        "directory": "technology",
        "field": "ai_weight",
        "actor_scope": "country",
        "target_scope": "definition_only:technology",
        "operation": "base_candidate_score",
        "capability": "direct",
    }
    assert data["contract"]["country_tag"] == 5
    assert data["reference_sites"] == ["0x1418d5e49", "0x1417b6650", "0x1415ea010"]
    assert len(data["observations"]) == 23
    assert all(not Path(key).is_absolute() for key in data["script_hashes"])


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
