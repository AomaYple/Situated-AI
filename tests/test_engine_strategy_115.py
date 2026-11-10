"""Current strategy permissions require independent exact field and type chains."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from pdx import version_contracts
from pdx.situated import engine_scope, engine_scope_115, engine_strategy_115

pytestmark = pytest.mark.unit


@pytest.fixture
def strategy_data():
    with version_contracts.select_version("1.15.0"):
        return json.loads(engine_scope.strategy_snapshot())


def test_current_strategy_is_independently_pinned_and_never_claims_runtime(strategy_data):
    path, identity, digest = engine_scope_115.manifest("strategy")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert identity == "research/situated/victoria3-1.15.0-strategy-scope.json"
    assert strategy_data["exe"]["sha256"] == engine_scope_115.EXE_SHA256
    assert strategy_data["runtime"] == "unknown"
    assert len(strategy_data["consumers"]) == 33
    assert len(strategy_data["observations"]) == 307
    assert strategy_data["rtti"]["parser_subobject"] == "0x20d8"
    assert strategy_data["consumers"]["weight"]["member_offset"] == "0xb8"
    assert strategy_data["consumers"]["possible"]["member_offset"] == "0x40"
    assert set(strategy_data["strategy_field_merges"]) == set(strategy_data["consumers"]) - {
        "weight",
        "possible",
    }


def test_change_law_chance_uses_first_nonzero_active_and_default_only_as_fallback(strategy_data):
    row = strategy_data["strategy_field_merges"]["change_law_chance"]
    operation = "first_nonzero_active_change_law_chance_else_default"
    assert strategy_data["consumers"]["change_law_chance"]["operation"] == operation
    assert row["operation"] == operation
    assert row["active_call"] == "0x1415e0eed"
    assert row["default_call"] == "0x1415e0f4c"
    assert row["active_nonzero_exit"] == "0x1415e0efc"
    assert "may be negative" in row["selection"]
    strategy_data["consumers"]["change_law_chance"]["operation"] = "additive_percentage_chance"
    with pytest.raises(ValueError, match="独立字段合同"):
        engine_strategy_115.validate(strategy_data)


def test_change_law_chance_default_and_active_labels_cannot_be_swapped(strategy_data):
    row = strategy_data["strategy_field_merges"]["change_law_chance"]
    row["default_call"], row["active_call"] = row["active_call"], row["default_call"]
    with pytest.raises(ValueError, match="独立字段合同"):
        engine_strategy_115.validate(strategy_data)


def test_current_strategy_missing_executable_cannot_borrow_historical_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", tmp_path / "must-not-read-old.json")
    with version_contracts.select_version("1.15.0"):
        proof = engine_scope.strategy_evidence(tmp_path / "game", {})
    _, identity, digest = engine_scope_115.manifest("strategy")
    assert not proof.verified
    assert not proof.consumers
    assert proof.source_hashes == ((f"@evidence/{identity}", digest),)


def test_current_strategy_snapshot_drift_is_rejected(tmp_path, monkeypatch):
    path, _, digest = engine_scope_115.manifest("strategy")
    changed = tmp_path / "changed.json"
    changed.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setitem(engine_scope_115.MANIFESTS, "strategy", (str(changed), digest))
    with version_contracts.select_version("1.15.0"), pytest.raises(ValueError, match="变化"):
        engine_scope.strategy_snapshot()


@pytest.mark.parametrize("field", tuple(engine_strategy_115._CONTRACTS["consumers"]))
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("actor_scope", "unknown"),
        ("target_scope", "scope:invented=country"),
        ("member_offset", "0x8"),
        ("parser_va", "0x141823040"),
        ("consumer_va", "0x141656424"),
        ("operation", "generic_score"),
    ],
)
def test_each_current_field_rejects_another_members_permission(strategy_data, field, key, value):
    row = strategy_data["consumers"][field]
    if row[key] == value:
        value = "unreviewed"
    row[key] = value
    with pytest.raises(ValueError, match="独立字段合同"):
        engine_strategy_115.validate(strategy_data)


@pytest.mark.parametrize(
    "section",
    [
        "rtti",
        "scope_key_registrations",
        "strategy_score_keys",
        "native_unprojected_contexts",
        "law_instance_type",
        "diplomatic_play_instance_type",
        "strategic_region_type",
        "institution_definition_sources",
        "institution_definitions",
        "stance_definition_sources",
        "stance_definitions",
        "strategy_field_merges",
    ],
)
def test_current_strategy_requires_complete_typed_and_merge_closure(strategy_data, section):
    del strategy_data[section][next(iter(strategy_data[section]))]
    with pytest.raises(ValueError, match="独立字段合同"):
        engine_strategy_115.validate(strategy_data)


@pytest.mark.parametrize("family", ["institution", "stance"])
def test_current_definition_bytes_cannot_disagree_with_definition_identity(strategy_data, family):
    sources = strategy_data[family + "_definition_bytes"]
    source = next(iter(sources))
    sources[source] += "20"
    with pytest.raises(ValueError, match="原始字节"):
        engine_strategy_115.validate(strategy_data)


def test_current_field_proof_requires_own_code_observation(strategy_data):
    changed = copy.deepcopy(strategy_data)
    address = int(changed["consumers"]["weight"]["consumer_va"], 16)
    changed["observations"] = [
        point
        for point in changed["observations"]
        if not int(point["va"], 16)
        <= address
        < int(point["va"], 16) + len(bytes.fromhex(point["bytes"]))
    ]
    with pytest.raises(ValueError, match=r"缺少真实观察：weight\.consumer_va"):
        engine_strategy_115.validate(changed)
