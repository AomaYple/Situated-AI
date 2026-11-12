"""法律定义资格门的精确来源、形状和重复声明拒收合同。"""

import hashlib
import json
import struct

import pytest

from pdx import version_contracts
from pdx.situated import engine_scope, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def historical_engine_contract():
    """Synthetic historical fixtures must not borrow the current EXE identity."""
    with version_contracts.select_version("1.14.5"):
        yield


@pytest.fixture
def law_proof(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    for key in ("caligula_branch", "caligula_rev", "clausewitz_branch", "clausewitz_rev"):
        (tmp_path / f"{key}.txt").write_text(
            "release/1.14.5" if key == "caligula_branch" else "fixture", encoding="utf-8"
        )
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"fixed law image")
    source = "common/laws/sample.txt"
    inputs = {source: b"sample = { ai_will_do = { always = yes } }"}
    data = {
        "exe": {
            "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
            "bytes": exe.stat().st_size,
        },
        "contract": {
            "family": "laws",
            "hook": "ai_will_do",
            "actor": "country",
            "target": "definition_only:law_type",
            "operation": "eligibility",
            "capability": "direct",
            "named_targets_proven": [],
        },
        "script_hashes": {},
        "observations": [{"label": "point", "file_offset": "0x0", "bytes": "6669786564"}],
    }
    manifest = tmp_path / "law.json"

    def freeze():
        data["script_hashes"] = {source: hashlib.sha256(inputs[source]).hexdigest()}
        raw = json.dumps(data).encode()
        manifest.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "LAW_MANIFEST", manifest, raising=False)
        monkeypatch.setattr(
            engine_scope, "LAW_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest(), raising=False
        )

    freeze()
    monkeypatch.setattr(
        vanilla_inventory, "_inputs", lambda _: (dict(inputs), ("laws",), ("game",))
    )
    return game, exe, source, inputs, data, freeze


def test_law_predicate_proves_definition_identity_only(law_proof):
    game, *_ = law_proof
    result = vanilla_inventory.discover(game=game)
    row = result.surfaces[0]
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "country",
        "definition_only:law_type",
        "eligibility",
        "direct",
    )
    assert row.legal
    assert row.status == "pending"
    assert row.responsibility_step == "D4.06"
    assert row.getter is None
    assert "scope:law" not in row.target_scope
    assert any("0x141548e39" in ref for ref in row.scope_evidence)
    assert f"@evidence/{engine_scope.LAW_MANIFEST_ID}" in result.source_hashes


@pytest.mark.parametrize("change", ["missing_exe", "exe_drift", "script_drift", "missing_script"])
def test_missing_or_drifted_law_proof_stays_unknown(law_proof, change):
    game, exe, source, inputs, _, _ = law_proof
    if change == "missing_exe":
        exe.unlink()
    elif change == "exe_drift":
        exe.write_bytes(b"changed")
    elif change == "script_drift":
        inputs[source] += b"\n"
    else:
        inputs.clear()
    assert not engine_scope.law_evidence(game, inputs).verified


def test_new_source_remains_in_denominator_without_inheriting_proof(law_proof):
    game, _, _, inputs, _, _ = law_proof
    inputs["common/laws/new.txt"] = b"new = { ai_will_do = { always = yes } }"
    result = vanilla_inventory.discover(game=game)
    rows = {row.definition: row for row in result.surfaces}
    assert result.discovered_count == 2
    assert rows["sample"].legal
    assert rows["new"].capability == "pending"
    assert rows["new"].actor_scope == rows["new"].target_scope == "unknown"


@pytest.mark.parametrize(
    "declaration",
    [
        "sample = { ai_will_do = yes }",
        'sample = { ai_will_do = "yes" }',
        "sample = { ai_will_do = {} ai_will_do = {} }",
        "sample = { REPLACE:ai_will_do = {} }",
        "REPLACE:sample = { ai_will_do = {} }",
        "sample = { ai_possible = {} }",
        "sample = { ai_weight = {} }",
    ],
)
def test_law_unproven_shape_or_adjacent_field_stays_pending(law_proof, declaration):
    game, _, source, inputs, _, freeze = law_proof
    inputs[source] = declaration.encode()
    freeze()
    rows = vanilla_inventory.discover(game=game).surfaces
    assert rows
    assert all(row.capability == "pending" for row in rows)


@pytest.mark.parametrize(
    "override", ["sample = 1", "sample = {}", "REPLACE:sample = {}", "sample = { ai_will_do = {} }"]
)
@pytest.mark.parametrize("same_source", [False, True])
def test_duplicate_law_definition_blocks_all_sides(law_proof, override, same_source):
    game, _, source, inputs, _, freeze = law_proof
    if same_source:
        inputs[source] += b" " + override.encode()
        freeze()
    else:
        inputs["dlc/example/common/laws/override.txt"] = override.encode()
    result = vanilla_inventory.discover(game=game)
    assert result.surfaces
    assert all(row.capability == "pending" for row in result.surfaces)
    assert all(
        row.ambiguity == "duplicate_law_definition_merge_semantics_unknown"
        for row in result.surfaces
    )
    assert all(row.responsibility_step == "D0.03" for row in result.surfaces)
    assert len({row.declaration_id for row in result.surfaces}) == len(result.surfaces)


@pytest.mark.parametrize("corruption", ["manifest", "length", "bytes", "contract"])
def test_corrupt_law_attestation_is_error(law_proof, corruption):
    game, _, _, inputs, data, freeze = law_proof
    if corruption == "manifest":
        engine_scope.LAW_MANIFEST.write_bytes(b"{}")
    else:
        if corruption == "length":
            data["exe"]["bytes"] += 1
        elif corruption == "bytes":
            data["observations"][0]["bytes"] = "00"
        else:
            data["contract"]["target"] = "scope:law=law"
        freeze()
    with pytest.raises(ValueError, match="锁定法律作用域证据"):
        engine_scope.law_evidence(game, inputs)


def test_law_declaration_identity_survives_scope_reclassification(law_proof):
    game, exe, *_ = law_proof
    proven = vanilla_inventory.discover(game=game)
    exe.unlink()
    unknown = vanilla_inventory.discover(game=game)
    assert proven.discovered_count == unknown.discovered_count == 1
    assert proven.surfaces[0].declaration_id == unknown.surfaces[0].declaration_id
    assert proven.surfaces[0].surface_id != unknown.surfaces[0].surface_id
    assert unknown.surfaces[0].capability == "pending"


def test_frozen_law_manifest_retains_complete_source_and_control_flow_evidence():
    raw = engine_scope.LAW_MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == engine_scope.LAW_MANIFEST_SHA256
    data = json.loads(raw)
    assert data["evidence_category"] == "static_check"
    assert len(data["script_hashes"]) == 21
    assert data["inventory_snapshot"]["declarations"] == 59
    assert data["contract"]["named_targets_proven"] == []
    checks = {point["label"]: point for point in data["control_flow_checks"]}
    assert checks["candidate false skips current"]["target_va"] == "0x1415490d8"
    assert checks["law trigger wrapper"]["target_va"] == "0x14170c2a0"
    assert checks["CLawType constructor"]["target_va"] == "0x1417082b0"
    points = {point["label"]: point for point in data["observations"]}
    assert points["country-law-db-registration"]["va"] == "0x140efaf60"
    assert len(bytes.fromhex(points["country-law-creation"]["bytes"])) == 0x35F
    assert len(data["observations"]) >= 40


def test_frozen_law_control_flow_targets_follow_attested_instruction_bytes():
    data = json.loads(engine_scope.LAW_MANIFEST.read_bytes())
    points = data["observations"]
    for check in data["control_flow_checks"]:
        address = int(check["instruction_va"], 16)
        raw = bytes.fromhex(check["instruction_bytes"])
        assert raw[:1] == b"\xe8" or raw[:2] == b"\x0f\x84"
        displacement = struct.unpack_from("<i", raw, len(raw) - 4)[0]
        assert address + len(raw) + displacement == int(check["target_va"], 16)
        assert any(
            address - int(point["va"], 16) >= 0
            and bytes.fromhex(point["bytes"])[
                address - int(point["va"], 16) : address - int(point["va"], 16) + len(raw)
            ]
            == raw
            for point in points
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("family", "companies"),
        ("hook", "ai_weight"),
        ("actor", "law"),
        ("operation", "base_candidate_score"),
        ("capability", "indirect"),
        ("named_targets_proven", ["scope:law"]),
    ],
)
def test_law_attestation_cannot_authorize_an_adjacent_contract(law_proof, field, value):
    game, _, _, inputs, data, freeze = law_proof
    data["contract"][field] = value
    freeze()
    with pytest.raises(ValueError, match="锁定法律作用域证据的字段合同不一致"):
        engine_scope.law_evidence(game, inputs)


def test_verified_law_evidence_is_limited_to_frozen_sources(law_proof):
    game, exe, source, inputs, _, _ = law_proof
    evidence = engine_scope.law_evidence(game, inputs)
    assert evidence.verified
    assert evidence.sources == (source,)
    assert any("0x141548e39" in ref for ref in evidence.references)
    exe.unlink()
    unavailable = engine_scope.law_evidence(game, inputs)
    assert not unavailable.verified
    assert unavailable.sources == unavailable.references == ()
