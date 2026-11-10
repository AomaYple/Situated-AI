"""Current strategy permissions require independent exact field and type chains."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from pdx import version_contracts
from pdx.situated import engine_scope, engine_scope_115, engine_strategy_115

pytestmark = pytest.mark.unit
_CURRENT_CONSUMERS = engine_strategy_115._CONTRACTS["consumers"]
assert isinstance(_CURRENT_CONSUMERS, dict)


@pytest.fixture
def strategy_data():
    with version_contracts.select_version("1.15.0"):
        return json.loads(engine_scope.strategy_snapshot())


@pytest.fixture
def current_strategy_image(monkeypatch, tmp_path):
    """Full current proof; compact offsets are failure instrumentation only."""
    with version_contracts.select_version("1.15.0"):
        game = tmp_path / "game"
        executable = tmp_path / "binaries/victoria3.exe"
        executable.parent.mkdir()
        data = json.loads(engine_scope.strategy_snapshot())
        image = bytearray()
        for point in data["observations"]:
            point["file_offset"] = hex(len(image))
            image.extend(bytes.fromhex(point["bytes"]))
        executable.write_bytes(image)
        data["exe"] = {
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "bytes": executable.stat().st_size,
        }
        for source in data["script_hashes"]:
            path = game / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.encode())
            data["script_hashes"][source] = hashlib.sha256(path.read_bytes()).hexdigest()
        for source in data["institution_definition_sources"]:
            path = game / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                bytes.fromhex(data["institution_definition_bytes"][source])
                if "institution_definition_bytes" in data
                else source.encode()
            )
            data["institution_definition_sources"][source] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        for source, raw_hex in data["stance_definition_bytes"].items():
            path = game / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes.fromhex(raw_hex))
        manifest = tmp_path / "manifest.json"

        def freeze():
            raw = json.dumps(data, indent=2).encode()
            manifest.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            if version_contracts.active_version() == "1.15.0":
                monkeypatch.setitem(engine_scope_115.MANIFESTS, "strategy", (str(manifest), digest))
            else:
                monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", manifest)
                monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST_SHA256", digest)

        freeze()
        yield game, executable, data, freeze


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


@pytest.mark.parametrize("field", tuple(_CURRENT_CONSUMERS))
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("actor_scope", "unknown"),
        ("target_scope", "scope:invented=country"),
        ("member_offset", "0x8"),
        ("parser_va", "0x141823040"),
        ("consumer_va", "0x141656424"),
        ("operation", "generic_score"),
        ("capability", "pending"),
        ("unit", "unproven"),
        ("field", "adjacent"),
    ],
)
def test_each_current_field_rejects_another_members_permission(
    current_strategy_image, field, key, value
):
    game, _, strategy_data, freeze = current_strategy_image
    row = strategy_data["consumers"][field]
    if key == "field":
        strategy_data["consumers"][field + "_adjacent"] = strategy_data["consumers"].pop(field)
    else:
        if row[key] == value:
            value = "unreviewed"
        row[key] = value
    freeze()
    with pytest.raises(ValueError, match="独立字段合同"):
        engine_strategy_115.validate(strategy_data)
    with pytest.raises(ValueError, match="独立字段合同"):
        engine_scope.strategy_snapshot()
    inputs = {source: (game / source).read_bytes() for source in strategy_data["script_hashes"]}
    with pytest.raises(ValueError, match="独立字段合同"):
        engine_scope.strategy_evidence(game, inputs)


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


@pytest.mark.parametrize("field", tuple(_CURRENT_CONSUMERS))
@pytest.mark.parametrize("member", ["parser_va", "consumer_va"])
def test_current_field_proof_requires_own_code_observation(strategy_data, field, member):
    changed = copy.deepcopy(strategy_data)
    address = int(changed["consumers"][field][member], 16)
    changed["observations"] = [
        point
        for point in changed["observations"]
        if not int(point["va"], 16)
        <= address
        < int(point["va"], 16) + len(bytes.fromhex(point["bytes"]))
    ]
    with pytest.raises(ValueError, match="缺少真实观察"):
        engine_strategy_115.validate(changed)


@pytest.mark.parametrize("index", range(307))
def test_every_current_observation_rejects_byte_tampering_after_exe_and_manifest_repin(
    current_strategy_image, index
):
    game, executable, data, freeze = current_strategy_image
    assert len(data["observations"]) == 307
    inputs = {source: (game / source).read_bytes() for source in data["script_hashes"]}
    assert engine_scope.strategy_evidence(game, inputs).verified
    image = bytearray(executable.read_bytes())
    image[int(data["observations"][index]["file_offset"], 16)] ^= 1
    executable.write_bytes(image)
    data["exe"]["sha256"] = hashlib.sha256(image).hexdigest()
    freeze()
    with pytest.raises(ValueError, match="字节不一致"):
        engine_scope.strategy_evidence(game, inputs)


@pytest.mark.parametrize(
    "field", ["wargoal_scores", "secret_goal_scores", "treaty_category_scores"]
)
@pytest.mark.parametrize("damage", ["unknown", "order", "duplicate", "missing"])
def test_current_ordered_score_keys_reject_repin(current_strategy_image, field, damage):
    _, _, data, freeze = current_strategy_image
    keys = data["strategy_score_keys"][field]
    if damage == "unknown":
        keys[0] = "adjacent_unreviewed"
    elif damage == "order":
        keys.reverse()
    elif damage == "duplicate":
        keys.append(keys[0])
    else:
        keys.pop()
    freeze()
    with pytest.raises(ValueError, match="独立字段合同"):
        engine_scope.strategy_snapshot()
