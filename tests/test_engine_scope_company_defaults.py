"""Exact company fallback evidence preserves parent verification and source identity."""

from __future__ import annotations

import hashlib
import json

import pytest

from pdx.situated import engine_scope

pytestmark = pytest.mark.unit


def test_company_default_snapshot_requires_exact_missing_score_contract():
    assert hasattr(engine_scope, "company_default_snapshot")
    data = json.loads(engine_scope.company_default_snapshot())
    assert len(data["contracts"]) == 1
    contract = data["contracts"][0]
    assert contract["source_requirement"] == "exactly_missing_ai_weight_only"
    assert contract["explicit_empty_requirement"] == "reject_initializer"
    assert contract["default_value"] == 1
    assert contract["target"] == "definition_only:company_type"
    assert len(data["implicit_companies"]) == 26


@pytest.fixture
def company_defaults_game(tmp_path, monkeypatch):
    data = json.loads(engine_scope.company_default_snapshot())
    parent = json.loads(engine_scope.company_snapshot())
    game = tmp_path / "game"
    image = bytearray()
    for point in data["observations"]:
        point["file_offset"] = hex(len(image))
        image.extend(bytes.fromhex(point["bytes"]))
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(image)
    exe_contract = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}
    data["exe"] = parent["exe"] = exe_contract
    parent["observations"] = [{"label": "parent", "file_offset": "0x0", "bytes": image[:8].hex()}]
    for source in {*parent["script_hashes"], *data["script_hashes"]}:
        raw = source.encode()
        if source == "common/company_types/99_basic_companies.txt":
            raw = "\n".join(f"{row['id']} = {{}}" for row in data["implicit_companies"]).encode()
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        for manifest in (data, parent):
            if source in manifest["script_hashes"]:
                manifest["script_hashes"][source] = hashlib.sha256(raw).hexdigest()
    parent_path = tmp_path / "company-parent.json"
    path = tmp_path / "company-default.json"

    def freeze():
        parent_raw = json.dumps(parent).encode()
        parent_path.write_bytes(parent_raw)
        monkeypatch.setattr(engine_scope, "COMPANY_MANIFEST", parent_path)
        parent_digest = hashlib.sha256(parent_raw).hexdigest()
        monkeypatch.setattr(engine_scope, "COMPANY_MANIFEST_SHA256", parent_digest)
        data["parent_scope_manifest"]["sha256"] = parent_digest
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "COMPANY_DEFAULT_MANIFEST", path)
        monkeypatch.setattr(
            engine_scope, "COMPANY_DEFAULT_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest()
        )

    freeze()
    return game, exe, data, parent, freeze


@pytest.mark.parametrize(
    "member",
    [
        "field",
        "actor",
        "target",
        "operation",
        "capability",
        "consumer",
        "numeric_member",
        "empty_expression_member",
        "empty_expression_branch",
        "nonempty_expression_branch",
        "default_load",
        "default_global",
        "result_store",
        "result_return",
        "define_namespace",
        "define_key",
        "define_field",
        "define_source",
        "define_line",
        "default_value",
        "define_setter",
        "define_global_write",
        "define_binding",
        "define_registration",
        "actual_call",
        "nonpositive_rejection",
        "source_requirement",
        "explicit_empty_requirement",
        "explicit_nonpositive_requirement",
    ],
)
def test_repinning_another_default_member_cannot_authorize_replacement(
    company_defaults_game, member
):
    _, _, data, _, freeze = company_defaults_game
    data["contracts"][0][member] = "unproven"
    freeze()
    with pytest.raises(ValueError, match="公司缺省权重"):
        engine_scope.company_default_snapshot()


@pytest.mark.parametrize(
    "damage", ["id", "line", "missing", "duplicate", "parent", "source", "contracts"]
)
def test_default_definition_identity_and_parent_pin_cannot_be_replaced(
    company_defaults_game, damage
):
    _, _, data, _, freeze = company_defaults_game
    if damage in {"id", "line"}:
        data["implicit_companies"][0][damage] = "unproven"
    elif damage == "missing":
        data["implicit_companies"].pop()
    elif damage == "duplicate":
        data["implicit_companies"].append(data["implicit_companies"][0].copy())
    elif damage == "parent":
        data["parent_scope_manifest"]["path"] = "unproven.json"
    elif damage == "source":
        data["script_hashes"]["common/company_types/new.txt"] = data["script_hashes"].pop(
            "common/company_types/99_basic_companies.txt"
        )
    else:
        data["contracts"].append(data["contracts"][0].copy())
    freeze()
    with pytest.raises(ValueError, match="公司缺省权重"):
        engine_scope.company_default_snapshot()


def test_current_company_defaults_require_parent_and_both_actual_sources(company_defaults_game):
    game, _, _, _, _ = company_defaults_game
    proof = engine_scope.verify_company_defaults_game(game)
    assert proof.verified
    assert "common/defines/00_ai.txt" in proof.sources
    assert "common/company_types/99_basic_companies.txt" in proof.sources


def test_inventory_default_evidence_contains_actual_define_hash_and_parent(company_defaults_game):
    game, _, data, parent, _ = company_defaults_game
    inputs = {
        source: (game / source).read_bytes()
        for source in {*parent["script_hashes"], *data["script_hashes"]}
    }
    proof = engine_scope.company_default_evidence(game, inputs)
    assert proof.verified
    hashes = dict(proof.source_hashes)
    assert (
        hashes[f"@evidence/{engine_scope.COMPANY_DEFAULT_MANIFEST_ID}"]
        == engine_scope.COMPANY_DEFAULT_MANIFEST_SHA256
    )
    assert (
        hashes["common/defines/00_ai.txt"]
        == hashlib.sha256(inputs["common/defines/00_ai.txt"]).hexdigest()
    )
    assert (
        hashes[f"@evidence/{engine_scope.COMPANY_MANIFEST_ID}"]
        == engine_scope.COMPANY_MANIFEST_SHA256
    )


@pytest.mark.parametrize("damage", ["define", "parent", "missing", "extra"])
def test_inventory_default_evidence_does_not_infer_default_from_missing_or_drift(
    company_defaults_game, damage
):
    game, _, data, parent, _ = company_defaults_game
    inputs = {
        source: (game / source).read_bytes()
        for source in {*parent["script_hashes"], *data["script_hashes"]}
    }
    if damage == "define":
        inputs["common/defines/00_ai.txt"] = b"COMPANY_TYPE_DEFAULT_BASE_WEIGHT = 999"
    elif damage == "parent":
        source = next(
            key
            for key in parent["script_hashes"]
            if key != "common/company_types/99_basic_companies.txt"
        )
        inputs[source] += b"changed"
    elif damage == "missing":
        del inputs["common/defines/00_ai.txt"]
    else:
        inputs["dlc/extra/common/company_types/shadow.txt"] = b"company_basic_gold_mining = {}"
    assert not engine_scope.company_default_evidence(game, inputs).verified


@pytest.mark.parametrize("index", range(8))
def test_each_company_default_original_span_is_required(company_defaults_game, index):
    game, exe, data, parent, freeze = company_defaults_game
    raw = bytearray(exe.read_bytes())
    raw[int(data["observations"][index]["file_offset"], 16)] ^= 1
    exe.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    data["exe"]["sha256"] = parent["exe"]["sha256"] = digest
    parent["observations"][0]["bytes"] = raw[:8].hex()
    freeze()
    with pytest.raises(ValueError, match="字节不一致"):
        engine_scope.verify_company_defaults_game(game)


@pytest.mark.parametrize(
    "source",
    [
        "common/defines/00_ai.txt",
        "common/company_types/99_basic_companies.txt",
        "common/company_types/00_companies.txt",
    ],
)
def test_default_or_parent_source_drift_never_uses_frozen_fallback(company_defaults_game, source):
    game, _, _, parent, _ = company_defaults_game
    if source not in {"common/defines/00_ai.txt", "common/company_types/99_basic_companies.txt"}:
        source = next(
            key
            for key in parent["script_hashes"]
            if key != "common/company_types/99_basic_companies.txt"
        )
    (game / source).write_bytes(b"changed")
    with pytest.raises(ValueError):
        engine_scope.verify_company_defaults_game(game)
