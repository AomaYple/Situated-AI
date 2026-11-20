"""Current PE contracts bind reviewed fields to one installed build."""

from __future__ import annotations

import hashlib
import json
import re
from functools import partial

import pytest
from _engine_evidence import compact_image, current_manifest, repin_manifest

from pdx import version_contracts
from pdx.situated import (
    engine_building_115,
    engine_reader_115,
    engine_scope,
    engine_scope_115,
    engine_strategy_115,
    engine_strategy_1152,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "kind",
    [
        "building-default",
        "company",
        "company-default",
        "country-definition",
        "defensive-pact-reader",
        "law",
        "strategy",
        "technology",
    ],
)
def test_current_engine_manifest_pins_digest_only_ranges(kind):
    path, identity, digest = engine_scope_115.manifest(kind)
    exe_digest, exe_size = engine_scope_115.executable_identity()
    raw = path.read_bytes()
    data = json.loads(raw)
    assert identity == f"research/situated/{version_contracts.CURRENT_VERSION}/engine-{kind}.json"
    assert hashlib.sha256(raw).hexdigest() == digest
    assert (data["exe"]["sha256"], data["exe"]["bytes"]) == (exe_digest, exe_size)
    assert data["runtime"] == "unknown"
    assert data["evidence_category"] == "static_check"
    assert data["observations"]
    for point in data["observations"]:
        assert set(point) == {"label", "va", "rva", "file_offset", "size", "sha256"}
        assert int(point["va"], 16) - int(point["rva"], 16) == int(data["exe"]["image_base"], 16)
        assert type(point["size"]) is int
        assert 0 < int(point["file_offset"], 16) + point["size"] <= exe_size
        assert re.fullmatch(r"[a-f0-9]{64}", point["sha256"])


@pytest.mark.parametrize("mutation", ["executable", "observation", "active_call"])
def test_current_strategy_rejects_changes_even_if_the_json_is_repinned(mutation):
    strategy = json.loads(engine_scope.strategy_snapshot())
    assert len(strategy["consumers"]) == 33
    if mutation == "executable":
        strategy["exe"]["bytes"] -= 1
    elif mutation == "observation":
        strategy["observations"] = [
            point for point in strategy["observations"] if "33 token paths" not in point["label"]
        ]
    else:
        row = strategy["strategy_field_merges"]["change_law_chance"]
        row["active_call"], row["default_call"] = row["default_call"], row["active_call"]
    with pytest.raises(ValueError):
        engine_strategy_115.validate(strategy)


@pytest.mark.parametrize(
    ("kind", "reader", "parent"),
    [
        ("building-default", engine_building_115.verify_game, None),
        ("company", engine_scope.verify_company_game, None),
        ("company-default", engine_scope.verify_company_defaults_game, "company"),
        ("country-definition", engine_scope.country_evidence, None),
        ("defensive-pact-reader", engine_reader_115.verify_game, "strategy"),
        ("law", engine_scope.law_evidence, None),
        ("technology", engine_scope.technology_evidence, None),
    ],
)
def test_current_engine_reader_rejects_rebound_executable_with_changed_range(
    tmp_path, monkeypatch, kind, reader, parent
):
    data = current_manifest(kind)
    manifests = {kind: data}
    if parent is not None:
        manifests[parent] = current_manifest(parent)
    executable = compact_image(tmp_path, *manifests.values())
    game = tmp_path / "game"
    inputs = {}
    for manifest in manifests.values():
        source_maps = [manifest["script_hashes"]]
        if manifest is manifests.get("strategy"):
            assert isinstance(manifest, dict)
            for key in ("institution_definition_sources", "stance_definition_sources"):
                sources = manifest[key]
                monkeypatch.setitem(engine_strategy_1152.CONTRACTS, key, sources)
                source_maps.append(sources)
        for sources in source_maps:
            for source in sources:
                path = game / source
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = source.encode("utf-8")
                path.write_bytes(raw)
                inputs[source] = raw
                sources[source] = hashlib.sha256(raw).hexdigest()

    def repin_inputs(patches, image):
        digest = hashlib.sha256(image).hexdigest()
        for manifest in manifests.values():
            manifest["exe"]["sha256"] = digest
        patches.setattr(engine_scope_115, "executable_identity", lambda: (digest, len(image)))
        if parent is not None:
            _, identity, _ = engine_scope_115.manifest(parent)
            parent_digest = repin_manifest(
                patches, tmp_path / f"{parent}.json", parent, manifests[parent]
            )
            data["parent_scope_manifest"] = {"path": identity, "sha256": parent_digest}
        repin_manifest(patches, tmp_path / f"{kind}.json", kind, data)

    inventory_reader = kind in {"country-definition", "law", "technology"}
    read_proof = partial(reader, game, inputs) if inventory_reader else partial(reader, game)
    image = bytearray(executable.read_bytes())
    with monkeypatch.context() as patches:
        repin_inputs(patches, image)
        proof = read_proof()
        if inventory_reader:
            assert proof.verified
        else:
            assert proof

    # Rebind the outer identities while keeping the selected observation's digest.
    point = data["observations"][0]
    image[int(point["file_offset"], 16)] ^= 1
    executable.write_bytes(image)
    repin_inputs(monkeypatch, image)
    with pytest.raises(ValueError, match=re.escape(f"字节不一致：{point['label']}")):
        read_proof()
