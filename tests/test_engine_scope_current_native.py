"""Current native proof transport, semantic mutations and real installation gates."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, cast

import pytest

from pdx import config
from pdx.situated import engine_scope

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

FAMILIES = {
    "STRATEGY": "strategy_evidence",
    "COMPANY": "company_evidence",
    "COMPANY_DEFAULT": "company_default_evidence",
    "LAW": "law_evidence",
    "COUNTRY": "country_evidence",
}
LIVE = (
    "verify_strategy_game",
    "verify_company_game",
    "verify_company_defaults_game",
    "verify_law_game",
    "verify_country_game",
)


def _data(family):
    return json.loads(getattr(engine_scope, f"{family}_MANIFEST").read_bytes())


def _repin(tmp_path, monkeypatch, family, data):
    raw = json.dumps(data).encode()
    path = tmp_path / f"{family}.json"
    path.write_bytes(raw)
    monkeypatch.setattr(engine_scope, f"{family}_MANIFEST", path)
    monkeypatch.setattr(engine_scope, f"{family}_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())


@pytest.fixture
def current_strategy(tmp_path, monkeypatch):
    data = _data("STRATEGY")
    image = bytearray()
    for point in data["observations"]:
        point["file_offset"] = hex(len(image))
        image.extend(bytes.fromhex(point["bytes"]))
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(image)
    data["exe"] = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}
    game = tmp_path / "game"
    for index, source in enumerate(data["script_hashes"]):
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = f"strategy_{index} = {{ weight = 1 }}".encode()
        path.write_bytes(raw)
        data["script_hashes"][source] = hashlib.sha256(raw).hexdigest()
    for key in (
        "institution_definition_bytes",
        "stance_definition_bytes",
        "configured_default_script_bytes",
    ):
        for source, raw in data[key].items():
            path = game / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes.fromhex(raw))
    _repin(tmp_path, monkeypatch, "STRATEGY", data)
    return game, data


@pytest.mark.unit
def test_strategy_support_sources_do_not_become_strategy_sources(current_strategy):
    game, data = current_strategy
    proof = engine_scope.verify_strategy_game(game)
    assert proof.verified
    assert set(proof.strategy_sources) == set(data["script_hashes"])
    assert len(proof.strategy_sources) == 5
    assert set(data["supporting_script_hashes"]) <= dict(proof.source_hashes).keys()


@pytest.mark.unit
def test_current_native_merge_and_tuple_semantics_stay_distinct():
    data = json.loads(engine_scope.strategy_snapshot())
    consumers = data["consumers"]
    merges = data["strategy_field_merges"]
    assert len(consumers) == 33
    assert len(merges) == 31
    assert consumers["change_law_chance"]["operation"] == "override_percentage_chance"
    assert merges["change_law_chance"]["evaluation_order"] == (
        "active until first nonzero; default only on exhaustion"
    )
    assert (
        merges["min_law_chance_to_pass"]["evaluation_order"]
        == (merges["change_law_chance"]["evaluation_order"])
    )
    for field in ("revolution_aversion", "max_progressiveness", "max_regressiveness"):
        assert merges[field]["active_selection"] == "first nonzero replaces default"
    for field in ("unacceptable_infamy_level", "undesirable_infamy_level"):
        assert merges[field]["active_selection"] == "first strictly positive replaces default"
    assert (
        "nonpositive active contributions skipped"
        in merges["diplomatic_play_neutrality"]["interpretation"]
    )
    assert "PRNG scaling and rounding" in merges["diplomatic_play_boldness"]["native_randomness"]
    assert "default prepended" in merges["strategic_region_stance_type_scores"]["evaluation_order"]
    assert consumers["possible"]["member_offset"] == "0x40"
    assert consumers["possible"]["parser_va"] == "0x141824162"
    tuples = {row["field"]: row["evaluation_slots"] for row in data["additional_scalar_consumers"]}
    assert tuples["possible"] == ["actor", "null", "actor", "context"]
    assert tuples["weight"] == ["actor", "actor", "actor", "context"]
    assert (
        data["native_unprojected_contexts"]["wargoal_scores"]["diplomatic_play"][
            "reader_authorization"
        ]
        is False
    )


@pytest.mark.unit
@pytest.mark.parametrize("source", tuple(_data("STRATEGY")["supporting_script_hashes"]))
@pytest.mark.parametrize("damage", ["missing", "drift"])
def test_current_support_bytes_are_required(current_strategy, source, damage):
    game, _ = current_strategy
    path = game / source
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"\n# drift")
    with pytest.raises((ValueError, FileNotFoundError)):
        engine_scope.verify_strategy_game(game)


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "common/ai_strategies/extra.txt",
        "dlc/extra/in_game/common/ai_strategies/override.txt",
        "common/institutions/override.txt",
        "dlc/extra/in_game/common/institutions/override.txt",
        "common/ai_strategic_region_stance_types/override.txt",
    ],
)
def test_current_source_additions_and_duplicate_definitions_fail(current_strategy, source):
    game, data = current_strategy
    assert engine_scope.verify_strategy_game(game).verified
    path = game / source
    path.parent.mkdir(parents=True, exist_ok=True)
    original = next(iter(data["script_hashes"]))
    path.write_bytes((game / original).read_bytes())
    with pytest.raises(ValueError, match="原件集合"):
        engine_scope.verify_strategy_game(game)


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "common/institutions/extra.txt",
        "dlc/example/in_game/common/institutions/override.txt",
        "common/ai_strategic_region_stance_types/extra.txt",
        "dlc/example/in_game/common/ai_strategic_region_stance_types/override.txt",
    ],
)
def test_direct_strategy_evidence_closes_support_definition_sets(current_strategy, source):
    game, data = current_strategy
    inputs = {path.relative_to(game).as_posix(): path.read_bytes() for path in game.rglob("*.txt")}
    proof = engine_scope.strategy_evidence(game, inputs)
    assert proof.verified
    assert set(proof.strategy_sources) == set(data["script_hashes"])
    inputs[source] = inputs[next(iter(data["institution_definition_sources"]))]
    assert not engine_scope.strategy_evidence(game, inputs).verified


@pytest.fixture
def current_law(tmp_path, monkeypatch):
    data = _data("LAW")
    image = bytearray()
    for point in data["observations"]:
        point["file_offset"] = hex(len(image))
        image.extend(bytes.fromhex(point["bytes"]))
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(image)
    data["exe"] = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}
    inputs = {}
    for index, source in enumerate(data["all_law_source_hashes"]):
        inputs[source] = f"law_{index} = {{}}".encode()
        digest = hashlib.sha256(inputs[source]).hexdigest()
        data["all_law_source_hashes"][source] = digest
        if source in data["script_hashes"]:
            data["script_hashes"][source] = digest
    _repin(tmp_path, monkeypatch, "LAW", data)
    return tmp_path / "game", inputs, data


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    sorted(set(_data("LAW")["all_law_source_hashes"]) - set(_data("LAW")["script_hashes"])),
)
@pytest.mark.parametrize("damage", ["missing", "drift"])
def test_direct_law_evidence_requires_every_nonpredicate_source(current_law, source, damage):
    game, inputs, data = current_law
    proof = engine_scope.law_evidence(game, inputs)
    assert proof.verified
    assert len(proof.sources) == 21
    assert set(proof.sources) == set(data["script_hashes"])
    assert set(data["all_law_source_hashes"]) <= dict(proof.source_hashes).keys()
    if damage == "missing":
        inputs.pop(source)
    else:
        inputs[source] += b"# drift"
    assert not engine_scope.law_evidence(game, inputs).verified


@pytest.mark.unit
@pytest.mark.parametrize(
    "source", ["common/laws/extra.txt", "dlc/example/in_game/common/laws/override.txt"]
)
def test_direct_law_evidence_rejects_new_and_duplicate_source_overrides(current_law, source):
    game, inputs, _ = current_law
    assert engine_scope.law_evidence(game, inputs).verified
    inputs[source] = next(iter(inputs.values()))
    assert not engine_scope.law_evidence(game, inputs).verified


@pytest.mark.unit
@pytest.mark.parametrize("family", tuple(FAMILIES))
@pytest.mark.parametrize(
    "damage",
    [
        "exe_unknown",
        "observation_unknown",
        "cross_family",
        "missing_exe_hash",
        "exe_wrong_size_type",
        "exe_bool_size",
        "exe_bad_hash",
        "exe_wrong_path",
        "exe_wrong_shape",
        "observation_wrong_shape",
        "observation_missing_bytes",
        "observation_wrong_label",
        "observation_bad_offset",
        "observation_bad_bytes",
        "observation_partial_pe_pair",
        "script_map_wrong_shape",
        "script_bad_hash",
        "script_unsafe_path",
        "static_metadata_wrong_shape",
    ],
)
def test_public_evidence_rejects_unknown_or_malformed_transport_after_repin(
    tmp_path, monkeypatch, family, damage
):
    data = _data(family)
    source = next(iter(data["script_hashes"]))
    if damage == "exe_unknown":
        data["exe"]["foreign_scope"] = "prospective_country"
    elif damage == "observation_unknown":
        data["observations"][0]["foreign_scope"] = "saved_scope"
    elif damage == "cross_family":
        key = "parent_scope_manifest" if family == "LAW" else "all_law_source_hashes"
        data[key] = {"foreign_scope": "unauthorized"}
    elif damage == "missing_exe_hash":
        data["exe"].pop("sha256")
    elif damage == "exe_wrong_size_type":
        data["exe"]["bytes"] = "99988600"
    elif damage == "exe_bool_size":
        data["exe"]["bytes"] = True
    elif damage == "exe_bad_hash":
        data["exe"]["sha256"] = "unknown"
    elif damage == "exe_wrong_path":
        data["exe"]["path"] = "../foreign.exe"
    elif damage == "exe_wrong_shape":
        data["exe"] = []
    elif damage == "observation_wrong_shape":
        data["observations"][0] = []
    elif damage == "observation_missing_bytes":
        data["observations"][0].pop("bytes")
    elif damage == "observation_wrong_label":
        data["observations"][0]["label"] = {"foreign_scope": "saved_scope"}
    elif damage == "observation_bad_offset":
        data["observations"][0]["file_offset"] = -1
    elif damage == "observation_bad_bytes":
        data["observations"][0]["bytes"] = "0xz"
    elif damage == "observation_partial_pe_pair":
        data["observations"][0].pop("rva")
    elif damage == "script_map_wrong_shape":
        data["script_hashes"] = []
    elif damage == "script_bad_hash":
        data["script_hashes"][source] = "unknown"
    elif damage == "script_unsafe_path":
        data["script_hashes"]["../" + source] = data["script_hashes"].pop(source)
    else:
        data["limits"] = {"foreign_scope": "saved_scope"}
    _repin(tmp_path, monkeypatch, family, data)
    with pytest.raises(ValueError, match="不一致"):
        getattr(engine_scope, FAMILIES[family])(tmp_path / "absent-game", {})


@pytest.mark.unit
@pytest.mark.parametrize("family", tuple(FAMILIES))
def test_public_evidence_rejects_duplicate_json_keys_after_repin(tmp_path, monkeypatch, family):
    raw = (
        json.dumps(_data(family))
        .replace('"sha256":', '"sha256": "duplicate", "sha256":', 1)
        .encode()
    )
    path = tmp_path / "duplicate.json"
    path.write_bytes(raw)
    monkeypatch.setattr(engine_scope, f"{family}_MANIFEST", path)
    monkeypatch.setattr(engine_scope, f"{family}_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="重复字段"):
        getattr(engine_scope, FAMILIES[family])(tmp_path / "absent-game", {})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("family", "damage"),
    [
        ("COMPANY_DEFAULT", "parent_extra"),
        ("COMPANY_DEFAULT", "parent_wrong_shape"),
        ("COMPANY_DEFAULT", "parent_invalid_hash"),
        ("LAW", "complete_map_wrong_shape"),
        ("LAW", "complete_map_invalid_hash"),
        ("LAW", "complete_map_missing_predicate"),
        ("COUNTRY", "image_base_wrong_shape"),
    ],
)
def test_public_evidence_checks_family_specific_transport_records(
    tmp_path, monkeypatch, family, damage
):
    data = _data(family)
    if damage == "parent_extra":
        data["parent_scope_manifest"]["foreign_scope"] = "saved_scope"
    elif damage == "parent_wrong_shape":
        data["parent_scope_manifest"] = []
    elif damage == "parent_invalid_hash":
        data["parent_scope_manifest"]["sha256"] = "unknown"
    elif damage == "complete_map_wrong_shape":
        data["all_law_source_hashes"] = []
    elif damage == "complete_map_invalid_hash":
        source = next(iter(data["all_law_source_hashes"]))
        data["all_law_source_hashes"][source] = {"foreign_scope": "saved_scope"}
    elif damage == "complete_map_missing_predicate":
        data["all_law_source_hashes"].pop(next(iter(data["script_hashes"])))
    else:
        data["exe"]["image_base"] = []
    _repin(tmp_path, monkeypatch, family, data)
    with pytest.raises(ValueError, match="不一致"):
        getattr(engine_scope, FAMILIES[family])(tmp_path / "absent-game", {})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "member"),
    [
        (field, member)
        for field, contract in _data("STRATEGY")["consumers"].items()
        for member in contract
    ],
)
def test_every_current_consumer_member_rejects_repinning(tmp_path, monkeypatch, field, member):
    data = _data("STRATEGY")
    data["consumers"][field][member] = "foreign_scope_or_operation"
    _repin(tmp_path, monkeypatch, "STRATEGY", data)
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_snapshot()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("family", "block"),
    [
        (family, block)
        for family, blocks in engine_scope._NATIVE_CONTRACT_HASHES.items()
        for block in blocks
    ],
)
def test_every_current_semantic_block_remains_independently_pinned(family, block):
    data = _data(family)
    data[block] = {"unauthorized": "foreign reader or altered native merge"}
    with pytest.raises(ValueError, match="不一致"):
        engine_scope._validate_native_contracts(data, family, "native")


@pytest.mark.unit
@pytest.mark.parametrize("family", tuple(FAMILIES))
def test_unknown_contract_metadata_cannot_grant_a_new_scope(family):
    data = _data(family)
    data["new_scope"] = "prospective_country"
    with pytest.raises(ValueError, match="未知字段"):
        engine_scope._validate_native_contracts(data, family, "native")


@pytest.mark.unit
def test_duplicate_json_contract_keys_are_rejected():
    with pytest.raises(ValueError, match="重复字段"):
        engine_scope._manifest_data(b'{"consumers":{"possible":{},"possible":{}}}')


@pytest.mark.unit
@pytest.mark.parametrize("family", ["COMPANY", "COUNTRY", "LAW"])
@pytest.mark.parametrize("damage", ["extra", "dlc_duplicate", "missing", "drift"])
def test_live_family_gates_reject_changed_complete_source_sets(
    tmp_path, monkeypatch, family, damage
):
    data = _data(family)
    image = bytearray()
    for point in data["observations"]:
        point["file_offset"] = hex(len(image))
        image.extend(bytes.fromhex(point["bytes"]))
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(image)
    data["exe"] = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}
    game = tmp_path / "game"
    sources = data.get("all_law_source_hashes", data["script_hashes"])
    for index, source in enumerate(sources):
        raw = f"definition_{index} = {{ ai_will_do = {{ always = yes }} }}".encode()
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        sources[source] = hashlib.sha256(raw).hexdigest()
        if source in data["script_hashes"]:
            data["script_hashes"][source] = sources[source]
    _repin(tmp_path, monkeypatch, family, data)
    api = cast(
        "Callable[[Path], engine_scope.CompanyScopeEvidence | engine_scope.CountryScopeEvidence | engine_scope.LawScopeEvidence]",
        {
            "COMPANY": engine_scope.verify_company_game,
            "COUNTRY": engine_scope.verify_country_game,
            "LAW": engine_scope.verify_law_game,
        }[family],
    )
    assert api(game).verified
    # Law tests deliberately damage one of the four files without ai_will_do.
    source = next(iter(set(sources) - set(data["script_hashes"])), next(iter(sources)))
    path = game / source
    if damage == "missing":
        path.unlink()
    elif damage == "drift":
        path.write_bytes(path.read_bytes() + b"# changed")
    else:
        added = source.rsplit("/", 1)[0] + "/extra.txt"
        if damage == "dlc_duplicate":
            added = "dlc/example/in_game/" + added
        extra = game / added
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_bytes(path.read_bytes())
    with pytest.raises((ValueError, FileNotFoundError)):
        api(game)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("family", "index"),
    [(family, index) for family in FAMILIES for index in range(len(_data(family)["observations"]))],
)
def test_all_current_raw_spans_reject_byte_corruption_after_exe_repin(
    tmp_path, monkeypatch, family, index
):
    data = _data(family)
    image = bytearray()
    for point in data["observations"]:
        point["file_offset"] = hex(len(image))
        image.extend(bytes.fromhex(point["bytes"]))
    image[int(data["observations"][index]["file_offset"], 16)] ^= 1
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(image)
    data["exe"] = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}
    _repin(tmp_path, monkeypatch, family, data)
    with pytest.raises(ValueError, match="字节不一致"):
        getattr(engine_scope, FAMILIES[family])(tmp_path / "game", {})


@pytest.mark.integration
@pytest.mark.parametrize("api", LIVE)
def test_current_native_proof_against_real_installation(api):
    game = config.GAME
    if not game.is_dir() or not (game.parent / "binaries/victoria3.exe").is_file():
        pytest.skip("real Victoria 3 installation unavailable")
    proof = getattr(engine_scope, api)(game)
    assert proof.verified
    assert dict(proof.source_hashes)["@engine/binaries/victoria3.exe"] == (
        "473186e8d8deba993651e0ae4cf02a003b02f5accb99b096a6a0a8bd9506cbaa"
    )
    assert any(source.startswith("common/") for source in dict(proof.source_hashes))
