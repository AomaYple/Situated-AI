"""公司字段逐成员作用域；相邻字段和新声明不得继承许可。"""

import hashlib
import json

import pytest
from _engine_evidence import compact_image, current_manifest, repin_manifest
from conftest import configure_current_identity

from pdx.situated import engine_scope, engine_scope_115, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.fixture
def company_proof(tmp_path, monkeypatch):
    configure_current_identity(tmp_path, monkeypatch)
    game = tmp_path / "game"
    game.mkdir()
    source = "common/company_types/sample.txt"
    inputs = {source: b"sample = { ai_will_do = { always = yes } ai_weight = { value = 1 } }\n"}
    data = current_manifest("company")
    executable = compact_image(tmp_path, data)

    def freeze():
        data["script_hashes"] = {source: hashlib.sha256(inputs[source]).hexdigest()}
        repin_manifest(monkeypatch, tmp_path / "proof.json", "company", data)

    freeze()
    monkeypatch.setattr(
        vanilla_inventory, "_inputs", lambda _: (dict(inputs), ("company_types",), ("game",))
    )

    # The default initializer has its own attestation and parent identity.
    monkeypatch.setattr(
        engine_scope,
        "company_default_evidence",
        lambda *_: engine_scope.CompanyScopeEvidence(False, ()),
    )

    return game, executable, source, inputs, data, freeze


def test_company_fields_have_separate_exact_operations(company_proof):
    game, *_ = company_proof
    rows = {row.field: row for row in vanilla_inventory.discover(game=game).surfaces}
    for field, operation in (("ai_will_do", "eligibility"), ("ai_weight", "base_candidate_score")):
        assert (rows[field].actor_scope, rows[field].target_scope, rows[field].operation) == (
            "country",
            "definition_only:company_type",
            operation,
        )
        assert rows[field].capability == "direct"


@pytest.mark.parametrize("change", ["missing_exe", "exe_drift", "script_drift", "new_source"])
def test_drift_does_not_inherit_company_scope(company_proof, change):
    game, exe, source, inputs, _, _ = company_proof
    if change == "missing_exe":
        exe.unlink()
    elif change == "exe_drift":
        exe.write_bytes(b"changed")
    elif change == "script_drift":
        inputs[source] += b"\n"
    else:
        inputs["common/company_types/new.txt"] = inputs.pop(source)
    assert all(
        row.capability == "pending" for row in vanilla_inventory.discover(game=game).surfaces
    )


@pytest.mark.parametrize(
    "override", ["sample = 1", "REPLACE:sample = {}", "sample = { ai_weight = 2 }"]
)
def test_company_cross_source_shadowing_invalidates_all(company_proof, override):
    game, _, _, inputs, _, _ = company_proof
    inputs["common/company_types/new.txt"] = override.encode()
    result = vanilla_inventory.discover(game=game)
    assert all(row.capability == "pending" for row in result.surfaces)
    assert all(row.ambiguity for row in result.surfaces)


@pytest.mark.parametrize(
    "declaration",
    [
        "REPLACE:sample = { ai_weight = {} }",
        "sample = { ai_weight = {} ai_weight = {} }",
        "sample = { ai_will_do = yes }",
        "sample = { ai_possible = {} }",
    ],
)
def test_company_ambiguous_or_adjacent_field_is_not_proven(company_proof, declaration):
    game, _, source, inputs, _, freeze = company_proof
    inputs[source] = declaration.encode()
    freeze()
    assert all(
        row.capability == "pending" for row in vanilla_inventory.discover(game=game).surfaces
    )


@pytest.mark.parametrize("corruption", ["manifest", "length", "bytes"])
def test_company_corrupt_attestation_is_error(company_proof, corruption):
    game, _, _, _, data, freeze = company_proof
    if corruption == "manifest":
        engine_scope_115.manifest("company")[0].write_bytes(b"{}")
    else:
        if corruption == "length":
            data["exe"]["bytes"] += 1
        else:
            data["observations"][0]["sha256"] = "0" * 64
        freeze()
    with pytest.raises(ValueError, match="锁定公司作用域证据"):
        vanilla_inventory.discover(game=game)


def test_company_frozen_attestation_has_separate_members():
    raw = engine_scope_115.manifest("company")[0].read_bytes()
    assert hashlib.sha256(raw).hexdigest() == engine_scope_115.manifest("company")[2]
    data = json.loads(raw)
    contracts = {row["field"]: row for row in data["contracts"]}
    assert contracts["ai_will_do"]["trigger_member"] == "0x318"
    assert contracts["ai_weight"]["numeric_member"] == "0x390"
    assert len(data["script_hashes"]) == 23
    assert len(data["observations"]) == 20
