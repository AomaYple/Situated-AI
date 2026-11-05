"""r7 exact map keys, complete evaluation objects and native same-field merges."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import decision_rules
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import compiler, engine_scope, vanilla_inventory

pytestmark = pytest.mark.unit
FIELDS = (
    "treaty_category_scores",
    "strategic_region_stance_type_scores",
    "wanted_num_supply_ships",
    "max_ship_design_complexity",
)
MAPS = ((FIELDS[0], "trade"), (FIELDS[1], "stance_conquer_region"))


def test_r7_preserves_r6_original_bytes_and_every_existing_observation():
    old_path = engine_scope.REPO / "research/situated/victoria3-1.14.5-strategy-scope-r6.json"
    raw = old_path.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "39b41be99801353ea76c64a1f6c0dbe4c8debe725f52488b045e4a5de8d7d528"
    )
    old = json.loads(raw)
    historical = engine_scope.REPO / "research/situated/victoria3-1.14.5-strategy-scope-r7.json"
    assert (
        hashlib.sha256(historical.read_bytes()).hexdigest()
        == "3f295f0a1a8fc1bd964ebe0949f81352de60fb3f28fa0b761358ba154aeab3f1"
    )
    data = json.loads(historical.read_bytes())
    assert len(data["consumers"]) == 33
    assert len(data["observations"]) == 452
    assert data["observations"][:388] == old["observations"]
    assert all(data["consumers"][key] == value for key, value in old["consumers"].items())
    assert set(data["revision"]["added_consumers"]) == set(FIELDS)
    assert "colonial_interest_ratio" not in data["consumers"]


@pytest.fixture
def proof(tmp_path, monkeypatch):
    data = json.loads(engine_scope.strategy_snapshot())
    points = data["observations"][388:]
    image = bytearray()
    for point in points:
        point["file_offset"] = hex(len(image))
        image.extend(bytes.fromhex(point["bytes"]))
    data["observations"] = points
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(image)
    data["exe"] = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}
    inputs = {}
    for source in data["script_hashes"]:
        inputs[source] = b"active = {}"
        data["script_hashes"][source] = hashlib.sha256(inputs[source]).hexdigest()
    path = tmp_path / "strategy.json"

    for support_key in (
        "institution_definition_bytes",
        "stance_definition_bytes",
        "configured_default_script_bytes",
    ):
        for source, raw_hex in data[support_key].items():
            inputs[source] = bytes.fromhex(raw_hex)

    def freeze():
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", path)
        monkeypatch.setattr(
            engine_scope, "STRATEGY_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest()
        )

    freeze()
    return tmp_path / "game", exe, data, inputs, freeze


@pytest.mark.parametrize("index", range(64))
def test_each_new_raw_span_is_checked_after_exe_repin(proof, index):
    game, exe, data, inputs, freeze = proof
    raw = bytearray(exe.read_bytes())
    raw[int(data["observations"][index]["file_offset"], 16)] ^= 1
    exe.write_bytes(raw)
    data["exe"]["sha256"] = hashlib.sha256(raw).hexdigest()
    freeze()
    with pytest.raises(ValueError, match="字节不一致"):
        engine_scope.strategy_evidence(game, inputs)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize(
    "member",
    [
        "actor_scope",
        "target_scope",
        "operation",
        "unit",
        "capability",
        "parser_va",
        "member_offset",
        "consumer_va",
        "field",
    ],
)
def test_new_exact_contracts_fail_closed_even_after_manifest_repin(proof, field, member):
    _, _, data, _, freeze = proof
    if member == "field":
        data["consumers"][field + "_adjacent"] = data["consumers"].pop(field)
    else:
        data["consumers"][field][member] = "unknown"
    freeze()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_snapshot()


@pytest.mark.parametrize(
    "metadata",
    [
        "strategic_region_type",
        "stance_definition_sources",
        "stance_definitions",
        "strategy_field_merges",
    ],
)
def test_object_identity_definition_set_and_real_active_merge_are_pinned(proof, metadata):
    _, _, data, _, freeze = proof
    data[metadata] = {}
    freeze()
    with pytest.raises(ValueError, match="证据不一致"):
        engine_scope.strategy_snapshot()


@pytest.mark.parametrize("damage", ["unknown", "order", "duplicate", "missing"])
def test_treaty_enum_is_exact_native_order(proof, damage):
    _, _, data, _, freeze = proof
    keys = data["strategy_score_keys"][FIELDS[0]]
    assert keys == [
        "economy",
        "trade",
        "military",
        "military_defense",
        "ideology",
        "expansion",
        "power_bloc",
        "other",
        "none",
    ]
    if damage == "unknown":
        keys[0] = "unknown"
    elif damage == "order":
        keys.reverse()
    elif damage == "duplicate":
        keys.append(keys[0])
    else:
        keys.pop()
    freeze()
    with pytest.raises(ValueError, match="枚举"):
        engine_scope.strategy_snapshot()


@pytest.mark.parametrize(("family", "key"), MAPS)
@pytest.mark.parametrize(
    "damage",
    ["unknown", "duplicate", "prefix", "scalar", "nested", "duplicate_map", "prefixed_map"],
)
def test_map_rejects_unknown_duplicate_and_substitute_shapes(family, key, damage):
    data = json.loads(engine_scope.strategy_snapshot())
    keys = frozenset(
        data["stance_definitions"] if family == FIELDS[1] else data["strategy_score_keys"][family]
    )
    entry = f"{key} = {{ value = 1 }}"
    if damage == "unknown":
        entry = "unknown = { value = 1 }"
    elif damage == "duplicate":
        entry += " " + entry
    elif damage == "prefix":
        entry = "REPLACE:" + entry
    elif damage == "scalar":
        entry = f"{key} = 1"
    elif damage == "nested":
        entry = f"{key} = {{ nested = {{ value = 1 }} }}"
    body = f"{family} = {{ {entry} }}"
    if damage == "duplicate_map":
        body += " " + body
    elif damage == "prefixed_map":
        body = "REPLACE:" + body
    definition = parse_text(f"active = {{ {body} }}").top_assignments[0]
    assert vanilla_inventory._strategy_score_map(definition, family, keys) is None


@pytest.mark.parametrize("field", FIELDS)
def test_new_contexts_keep_complete_objects_and_all_readers(field):
    context = compiler._frozen_strategy_contexts()[field]
    reader = decision_rules.Reader("war", "is_at_war", "root", "boolean", "boolean")
    path = (
        f"{field}.trade"
        if field == FIELDS[0]
        else f"{field}.stance_conquer_region"
        if field == FIELDS[1]
        else field
    )
    assert compiler.validate_context_readers(
        path, context, {"war": reader}, (), input_keys=("war",)
    ) == (("war", "root", "country", "actor"),)
    if field == FIELDS[1]:
        assert [(a.name, a.kind, a.role) for a in context.targets] == [
            ("target_region", "strategic_region", "target")
        ]
        assert [(a.name, a.kind, a.role) for a in context.auxiliary_scopes] == [
            ("region_score", "scalar", "auxiliary")
        ]
        for changed in [replace(context, targets=()), replace(context, auxiliary_scopes=())]:
            with pytest.raises(ValueError, match="精确冻结"):
                compiler.validate_context_readers(
                    path, changed, {"war": reader}, (), input_keys=("war",)
                )
    with pytest.raises(ValueError, match="ROOT"):
        compiler.validate_context_readers(
            path, context, {"war": reader}, (), input_keys=("war",), actor_path=("owner",)
        )
    with pytest.raises(ValueError, match="缺少真实读取器"):
        compiler.validate_context_readers(path, context, {}, (), input_keys=("war",))


@pytest.mark.parametrize("scope", ["target_region", "region_score"])
def test_region_and_scalar_objects_grant_no_unproven_getter(scope):
    context = compiler._frozen_strategy_contexts()[FIELDS[1]]
    reader = decision_rules.Reader("war", "is_at_war", scope, "boolean", "boolean")
    with pytest.raises(ValueError, match="getter"):
        compiler.validate_context_readers(
            FIELDS[1] + ".stance_conquer_region", context, {"war": reader}, (), input_keys=("war",)
        )


@pytest.mark.parametrize(("family", "key"), MAPS)
def test_parent_and_non_exact_child_paths_never_become_numeric_contexts(family, key):
    context = compiler._frozen_strategy_contexts()[family]
    for path in [family, f"{family}.{key}_adjacent", f"{family}.{key}.value"]:
        with pytest.raises(ValueError, match="精确枚举"):
            compiler.validate_context_readers(path, context, {}, ())


def test_shipmod_context_keeps_candidate_and_all_root_readers():
    contexts = compiler._frozen_ship_modification_contexts()
    assert len(contexts) == 263
    context = next(iter(contexts.values()))
    assert [(a.name, a.kind, a.role) for a in context.targets] == [
        ("ship_modification_type", "ship_modification", "candidate")
    ]
    reader = decision_rules.Reader("default", "in_default", "root", "boolean", "boolean")
    assert compiler.validate_context_readers(
        "ship_modification.ai_weight", context, {"default": reader}, (), input_keys=("default",)
    ) == (("default", "root", "country", "actor"),)
    with pytest.raises(ValueError, match="精确冻结"):
        compiler.validate_context_readers(
            "ship_modification.ai_weight",
            replace(context, targets=()),
            {"default": reader},
            (),
            input_keys=("default",),
        )
    with pytest.raises(ValueError, match="ROOT"):
        compiler.validate_context_readers(
            "ship_modification.ai_weight",
            context,
            {"default": reader},
            (),
            input_keys=("default",),
            actor_path=("owner",),
        )
    with pytest.raises(ValueError, match="getter"):
        compiler.validate_context_readers(
            "ship_modification.ai_weight",
            context,
            {"default": replace(reader, scope="ship_modification_type")},
            (),
            input_keys=("default",),
        )


@pytest.mark.parametrize(("family", "key"), MAPS)
def test_exact_child_projection_preserves_parent_and_accepts_nondefault_identity(
    proof, monkeypatch, family, key
):
    game, _, data, inputs, _ = proof
    verified = engine_scope.strategy_evidence(game, inputs)
    if family == FIELDS[1]:
        source = "common/ai_strategic_region_stance_types/00_test.txt"
        raw = b"stance_conquer_region = {}"
        data["stance_definition_sources"] = {source: hashlib.sha256(raw).hexdigest()}
        data["supporting_script_hashes"] = dict(data["stance_definition_sources"])
        data["stance_definitions"] = {key: {"source": source, "line": 1}}
        inputs[source] = raw
        monkeypatch.setattr(engine_scope, "strategy_snapshot", lambda: json.dumps(data).encode())
    source = next(iter(data["script_hashes"]))
    definition = parse_text(
        f"active_other_strategy = {{ {family} = {{ {key} = {{ value = 1 }} }} }}"
    ).top_assignments[0]
    assert isinstance(definition.value, Block)
    rows = dict(vanilla_inventory._candidates("ai_strategies", definition.value))
    assert (family,) in rows
    assert (family, key) in rows
    parent = vanilla_inventory._scope(
        "ai_strategies", (family,), inputs, {}, definition, source, strategy_proof=verified
    )
    leaf = vanilla_inventory._scope(
        "ai_strategies", (family, key), inputs, {}, definition, source, strategy_proof=verified
    )
    assert (parent.actor, parent.capability) == ("definition_structure", "observation")
    assert (leaf.actor, leaf.target, leaf.operation, leaf.capability) == (
        "country",
        data["consumers"][family]["target_scope"],
        data["consumers"][family]["operation"],
        "direct",
    )
    assert f"{source}:{rows[(family, key)].line}" in leaf.evidence
    if family == FIELDS[1]:
        assert "common/ai_strategic_region_stance_types/00_test.txt:1" in leaf.evidence
    for path in [(family, key, "value"), (family, key + "_unknown")]:
        assert (
            vanilla_inventory._scope(
                "ai_strategies", path, inputs, {}, definition, source, strategy_proof=verified
            ).capability
            != "direct"
        )


@pytest.mark.parametrize(
    "damage",
    [
        "source_missing",
        "source_extra",
        "source_drift",
        "definition_duplicate",
        "definition_prefixed",
        "definition_scalar",
    ],
)
def test_stance_definition_sources_and_exact_unique_ast_are_required(monkeypatch, damage):
    data = json.loads(engine_scope.strategy_snapshot())
    source = "common/ai_strategic_region_stance_types/00_test.txt"
    raw = b"stance_conquer_region = {}"
    if damage == "definition_duplicate":
        raw += b" stance_conquer_region = {}"
    elif damage == "definition_prefixed":
        raw = b"REPLACE:stance_conquer_region = {}"
    elif damage == "definition_scalar":
        raw = b"stance_conquer_region = 1"
    data["stance_definition_sources"] = {source: hashlib.sha256(raw).hexdigest()}
    data["supporting_script_hashes"] = dict(data["stance_definition_sources"])
    data["stance_definitions"] = {"stance_conquer_region": {"source": source, "line": 1}}
    inputs = {source: raw}
    if damage == "source_missing":
        inputs.clear()
    elif damage == "source_extra":
        inputs[source.replace("00_test", "01_override")] = raw
    elif damage == "source_drift":
        inputs[source] += b" # changed"
    monkeypatch.setattr(engine_scope, "strategy_snapshot", lambda: json.dumps(data).encode())
    assert vanilla_inventory._stance_definitions(inputs) == {}


@pytest.mark.parametrize("damage", ["missing", "extra", "drift"])
def test_production_strategy_gate_requires_complete_stance_file_set(proof, damage):
    game, _, data, inputs, _ = proof
    for source, raw in inputs.items():
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    source = next(iter(data["stance_definition_sources"]))
    path = game / source
    assert engine_scope.verify_strategy_game(game).verified
    if damage == "missing":
        path.unlink()
    elif damage == "extra":
        (path.parent / "01_override.txt").write_bytes(path.read_bytes())
    else:
        path.write_bytes(path.read_bytes() + b" # drift")
    with pytest.raises((ValueError, FileNotFoundError)):
        engine_scope.verify_strategy_game(game)


def test_every_actual_new_strategy_and_shipmod_writer_binds_complete_inputs(monkeypatch, tmp_path):
    from pdx import config

    model = compiler.load_model()
    assert model.consumer_ir is not None
    instances = {row.action_id: row for row in model.action_instances}
    strategy = [
        writer
        for writer in model.consumer_ir.writers
        if writer.field.removeprefix("ai_strategy_default.").split(".")[0] in FIELDS
    ]
    equipment = [
        writer
        for writer in model.consumer_ir.writers
        if writer.evaluation_context
        and any(
            binding.name == "ship_modification_type"
            for binding in writer.evaluation_context.targets
        )
    ]
    from collections import Counter

    assert Counter(
        w.field.removeprefix("ai_strategy_default.").split(".")[0] for w in strategy
    ) == {
        "treaty_category_scores": 13,
        "strategic_region_stance_type_scores": 3,
        "wanted_num_supply_ships": 3,
        "max_ship_design_complexity": 1,
    }
    assert len(equipment) == 1517
    for writer in [*strategy, *equipment]:
        instance = instances[writer.writer_id]
        assert instance.actor_scope == "root"
        assert instance.evaluation_context == writer.evaluation_context
        assert writer.evaluation_context is not None
        assert writer.reader_context_bindings
        assert {binding[0] for binding in writer.reader_context_bindings} == set(
            instance.condition_facts
        )
        assert all(
            binding[1:] == ("root", "country", "actor")
            for binding in writer.reader_context_bindings
        )
        if writer.field.removeprefix("ai_strategy_default.").startswith(FIELDS[1] + "."):
            assert {binding.name for binding in writer.evaluation_context.targets} == {
                "target_region"
            }
            assert {binding.name for binding in writer.evaluation_context.auxiliary_scopes} == {
                "region_score"
            }
    monkeypatch.setattr(config, "GAME", tmp_path / "absent")
    offline = compiler.load_model()
    assert offline.consumer_ir is not None
    assert offline.consumer_ir.writers == model.consumer_ir.writers
