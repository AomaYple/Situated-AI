"""策略消费者的逐字段范围与漂移/重复防护。"""

from __future__ import annotations

import hashlib
import json

import pytest

from pdx.parser import parse_text
from pdx.situated import engine_scope, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.fixture
def strategy_proof(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    for key in ("caligula_branch", "caligula_rev", "clausewitz_branch", "clausewitz_rev"):
        (tmp_path / f"{key}.txt").write_text(
            "release/1.14.5" if key == "caligula_branch" else "fixture", encoding="utf-8"
        )
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"fixed strategy image")
    source = "common/ai_strategies/sample.txt"
    inputs = {source: b"sample = { weight = 1 wanted_army_size = 10 }\n"}
    data = json.loads(engine_scope.STRATEGY_MANIFEST.read_text(encoding="utf-8"))
    data["exe"] = {"sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "bytes": 20}
    data["script_hashes"] = {source: hashlib.sha256(inputs[source]).hexdigest()}
    data["observations"] = [{"label": "fixture", "file_offset": "0x0", "bytes": b"fixed".hex()}]
    manifest = tmp_path / "strategy.json"

    for support_key in (
        "institution_definition_bytes",
        "stance_definition_bytes",
        "configured_default_script_bytes",
    ):
        for source, raw_hex in data[support_key].items():
            inputs[source] = bytes.fromhex(raw_hex)

    def freeze():
        raw = json.dumps(data).encode()
        manifest.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", manifest)
        monkeypatch.setattr(
            engine_scope, "STRATEGY_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest()
        )

    freeze()
    return game, exe, inputs, data, freeze


@pytest.mark.parametrize(
    ("field", "target", "operation", "capability"),
    [
        ("weight", "definition_only:ai_strategy", "base_candidate_score", "direct"),
        ("possible", "definition_only:ai_strategy", "eligibility", "direct"),
        ("wanted_army_size", "none", "additive_army_size_target", "direct"),
        (
            "recklessness",
            "scope:target_country=country",
            "additive_strength_estimate_multiplier",
            "direct",
        ),
        ("max_progressiveness", "none", "override_progressiveness_limit", "direct"),
        ("max_regressiveness", "none", "override_regressiveness_limit", "direct"),
        ("change_law_chance", "none", "override_percentage_chance", "direct"),
        (
            "wargoal_maneuvers_fraction",
            "scope:enemy_country=country",
            "additive_maneuvers_fraction",
            "direct",
        ),
        (
            "obligation_value",
            "scope:target_country=country",
            "additive_obligation_valuation",
            "direct",
        ),
        ("min_law_chance_to_pass", "scope:law=law", "override_pass_chance_threshold", "direct"),
        ("revolution_aversion", "none", "override_revolution_aversion", "direct"),
        ("subject_value", "scope:target_country=country", "additive_subject_valuation", "direct"),
        ("become_subject_value", "scope:overlord=country", "additive_subject_valuation", "direct"),
    ],
)
def test_each_strategy_field_keeps_its_own_proven_contract(
    strategy_proof, field, target, operation, capability
):
    game, _, inputs, _, _ = strategy_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    scope = vanilla_inventory._scope(
        "ai_strategies",
        (field,),
        inputs,
        {},
        parse_text(f"sample = {{ {field} = 1 }}").top_assignments[0],
        next(iter(inputs)),
        strategy_proof=proof,
    )
    assert (scope.actor, scope.target, scope.operation, scope.capability) == (
        "country",
        target,
        operation,
        capability,
    )
    assert scope.evidence


@pytest.mark.parametrize("change", ["missing_exe", "exe_drift", "missing_script", "script_drift"])
def test_strategy_proof_missing_or_drift_is_not_inherited(strategy_proof, change):
    game, exe, inputs, _, _ = strategy_proof
    if change == "missing_exe":
        exe.unlink()
    elif change == "exe_drift":
        exe.write_bytes(b"drift")
    elif change == "missing_script":
        inputs.clear()
    else:
        inputs[next(iter(inputs))] = b"drift"
    assert not engine_scope.strategy_evidence(game, inputs).verified


@pytest.mark.parametrize(
    "field",
    ["colonial_interest_ratio", "wanted_construction_ratio", "desired_tax_level", "future"],
)
def test_adjacent_unproven_fields_do_not_inherit_country(strategy_proof, field):
    game, _, inputs, _, _ = strategy_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    scope = vanilla_inventory._scope(
        "ai_strategies",
        (field,),
        inputs,
        {},
        parse_text(f"sample = {{ {field} = 1 }}").top_assignments[0],
        next(iter(inputs)),
        strategy_proof=proof,
    )
    assert scope.actor == "unknown"
    assert scope.capability == "pending"


@pytest.mark.parametrize("separator", [" ", "\n"])
def test_same_source_duplicate_strategy_without_field_invalidates_first(
    strategy_proof, monkeypatch, separator
):
    game, _, inputs, data, freeze = strategy_proof
    source = next(iter(inputs))
    inputs[source] = f"sample = {{ weight = 1 }}{separator}sample = {{ icon = x }}".encode()
    data["script_hashes"][source] = hashlib.sha256(inputs[source]).hexdigest()
    freeze()
    monkeypatch.setattr(
        vanilla_inventory, "_inputs", lambda _: (dict(inputs), ("ai_strategies",), ("game",))
    )
    inventory = vanilla_inventory.discover(game=game)
    rows = [row for row in inventory.surfaces if "/common/ai_strategies/" in "/" + row.source]
    assert len(rows) == 1
    assert inventory.legal_count == 0
    assert rows[0].ambiguity == "duplicate_strategy_definition_merge_semantics_unknown"


@pytest.mark.parametrize(
    "override", ["sample = { weight = 2 }", "sample = { icon = x }", "sample = 1"]
)
def test_other_source_duplicate_blocks_original_even_without_its_field(
    strategy_proof, monkeypatch, override
):
    game, _, inputs, _, _ = strategy_proof
    inputs["dlc/example/in_game/common/ai_strategies/collision.txt"] = override.encode()
    monkeypatch.setattr(
        vanilla_inventory, "_inputs", lambda _: (dict(inputs), ("ai_strategies",), ("game",))
    )
    inventory = vanilla_inventory.discover(game=game)
    assert inventory.legal_count == 0
    rows = [row for row in inventory.surfaces if "/common/ai_strategies/" in "/" + row.source]
    assert rows
    assert all(row.capability == "pending" for row in rows)
    assert all(
        row.ambiguity == "duplicate_strategy_definition_merge_semantics_unknown" for row in rows
    )


def test_new_source_and_nested_field_cannot_inherit_definition_proof(strategy_proof):
    game, _, inputs, _, _ = strategy_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    for source, field in [
        ("common/ai_strategies/new.txt", ("weight",)),
        (next(iter(inputs)), ("outer", "weight")),
    ]:
        scope = vanilla_inventory._scope(
            "ai_strategies",
            field,
            inputs,
            {},
            parse_text("sample = { weight = 1 }").top_assignments[0],
            source,
            strategy_proof=proof,
        )
        assert scope.actor == "unknown"
        assert scope.capability == "pending"


@pytest.mark.parametrize(
    "declaration",
    ["sample = 1", "sample = { weight = 1 weight = 2 }", "REPLACE:sample = { weight = 1 }"],
)
def test_ambiguous_definition_or_field_is_not_proven(strategy_proof, declaration):
    game, _, inputs, _, _ = strategy_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    scope = vanilla_inventory._scope(
        "ai_strategies",
        ("weight",),
        inputs,
        {},
        parse_text(declaration).top_assignments[0],
        next(iter(inputs)),
        strategy_proof=proof,
    )
    assert scope.capability == "pending"


@pytest.mark.parametrize("corruption", ["manifest_bytes", "length", "selected_bytes"])
def test_corrupt_attestation_is_a_hard_error(strategy_proof, corruption):
    game, _, inputs, data, freeze = strategy_proof
    if corruption == "manifest_bytes":
        engine_scope.STRATEGY_MANIFEST.write_bytes(b"{}")
    elif corruption == "length":
        data["exe"]["bytes"] += 1
        freeze()
    else:
        data["observations"][0]["bytes"] = "00"
        freeze()
    with pytest.raises(ValueError, match="锁定策略作用域证据"):
        engine_scope.strategy_evidence(game, inputs)


def test_frozen_manifest_preserves_distinct_scope_keys_and_operation_units():
    raw = engine_scope.STRATEGY_MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == engine_scope.STRATEGY_MANIFEST_SHA256
    data = json.loads(raw)
    contracts = data["consumers"]
    assert len(contracts) == 33
    assert contracts["recklessness"]["target_scope"] == "scope:target_country=country"
    assert contracts["wargoal_maneuvers_fraction"]["target_scope"] == "scope:enemy_country=country"
    assert contracts["become_subject_value"]["target_scope"] == "scope:overlord=country"
    assert contracts["min_law_chance_to_pass"]["target_scope"] == "scope:law=law"
    assert contracts["min_law_chance_to_pass"]["capability"] == "direct"
    assert contracts["weight"]["unit"] == "candidate_score"
    assert contracts["change_law_chance"]["unit"] == "percentage_points"
    assert contracts["wargoal_maneuvers_fraction"]["unit"] == "fraction"


def test_production_strategy_verification_reads_actual_files(strategy_proof):
    game, _, inputs, _, _ = strategy_proof
    for source, raw in inputs.items():
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    proof = engine_scope.verify_strategy_game(game)
    assert proof.verified
    assert engine_scope.strategy_snapshot() == engine_scope.STRATEGY_MANIFEST.read_bytes()


@pytest.mark.parametrize("damage", ["exe", "script", "missing_exe", "missing_script"])
def test_production_strategy_verification_never_uses_offline_fallback(strategy_proof, damage):
    game, exe, inputs, _, _ = strategy_proof
    for source, raw in inputs.items():
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    if damage == "exe":
        exe.write_bytes(b"changed engine")
    elif damage == "script":
        path.write_bytes(b"changed script")
    elif damage == "missing_exe":
        exe.unlink()
    else:
        path.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        engine_scope.verify_strategy_game(game)
