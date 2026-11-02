"""The exact threshold consumer binds a country law instance, never its type."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, decision_ir, engine_scope, vanilla_inventory

pytestmark = pytest.mark.unit


def test_min_law_contract_has_country_actor_and_actual_law_instance():
    data = json.loads(engine_scope.strategy_snapshot())
    contract = data["consumers"]["min_law_chance_to_pass"]
    assert contract == {
        "actor_scope": "country",
        "target_scope": "scope:law=law",
        "operation": "override_pass_chance_threshold",
        "capability": "direct",
        "unit": "pass_chance",
        "consumer_va": "0x141646d23",
        "parser_va": "0x1416418b2",
        "member_offset": "0x9b8",
    }
    assert len(data["observations"]) == 325
    assert data["law_instance_type"]["scope_tag"] == "0x31"
    assert data["law_instance_type"]["native_type"] == "CCountryLaw"


@pytest.fixture
def min_law_proof(tmp_path, monkeypatch):
    data = json.loads(engine_scope.strategy_snapshot())
    points = data["observations"][148:169]
    assert len(points) == 21
    image = bytearray()
    for point in points:
        point["file_offset"] = hex(len(image))
        image.extend(bytes.fromhex(point["bytes"]))
    data["observations"] = points
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(image)
    data["exe"] = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}
    game = tmp_path / "game"
    inputs = {}
    for index, source in enumerate(data["script_hashes"]):
        raw = f"strategy_{index} = {{ min_law_chance_to_pass = {{ value = 50 }} }}".encode()
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        inputs[source] = raw
        data["script_hashes"][source] = hashlib.sha256(raw).hexdigest()
    for source in data["institution_definition_sources"]:
        raw = "\n".join(f"{key} = {{}}" for key in data["institution_definitions"]).encode()
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        data["institution_definition_sources"][source] = hashlib.sha256(raw).hexdigest()
    manifest = tmp_path / "strategy.json"

    def freeze():
        raw = json.dumps(data).encode()
        manifest.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", manifest)
        monkeypatch.setattr(
            engine_scope, "STRATEGY_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest()
        )

    freeze()
    return game, exe, data, inputs, freeze


@pytest.mark.parametrize(
    "member",
    [
        "actor_scope",
        "target_scope",
        "operation",
        "capability",
        "unit",
        "consumer_va",
        "parser_va",
        "member_offset",
        "field",
    ],
)
def test_repinning_min_law_contract_cannot_authorize_another_scope(min_law_proof, member):
    game, _, data, inputs, freeze = min_law_proof
    if member == "field":
        data["consumers"]["min_law_chance_to_pass_adjacent"] = data["consumers"].pop(
            "min_law_chance_to_pass"
        )
    else:
        data["consumers"]["min_law_chance_to_pass"][member] = "unproven"
    freeze()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_snapshot()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_evidence(game, inputs)


@pytest.mark.parametrize("index", range(21))
def test_every_law_instance_type_and_override_byte_span_is_required(min_law_proof, index):
    game, exe, data, inputs, freeze = min_law_proof
    image = bytearray(exe.read_bytes())
    image[int(data["observations"][index]["file_offset"], 16)] ^= 1
    exe.write_bytes(image)
    data["exe"]["sha256"] = hashlib.sha256(image).hexdigest()
    freeze()
    with pytest.raises(ValueError, match="字节不一致"):
        engine_scope.strategy_evidence(game, inputs)


def test_min_law_inventory_uses_only_verified_exact_field(min_law_proof):
    game, _, _, inputs, _ = min_law_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    source = next(iter(inputs))
    definition = parse_text("sample = { min_law_chance_to_pass = { value = 50 } }").top_assignments[
        0
    ]
    scope = vanilla_inventory._scope(
        "ai_strategies",
        ("min_law_chance_to_pass",),
        inputs,
        {},
        definition,
        source,
        strategy_proof=proof,
    )
    assert (scope.actor, scope.target, scope.operation, scope.capability) == (
        "country",
        "scope:law=law",
        "override_pass_chance_threshold",
        "direct",
    )
    for field in [("min_law_chance_to_pass_adjacent",), ("min_law_chance_to_pass", "nested")]:
        rejected = vanilla_inventory._scope(
            "ai_strategies", field, inputs, {}, definition, source, strategy_proof=proof
        )
        assert rejected.capability == "pending"
    assert engine_scope.verify_strategy_game(game).verified


def test_min_law_compiler_binds_law_as_auxiliary_and_all_actual_root_inputs():
    context = compiler._frozen_strategy_contexts()["min_law_chance_to_pass"]
    assert context.targets == ()
    assert [(item.name, item.kind, item.role) for item in context.auxiliary_scopes] == [
        ("law", "law", "auxiliary")
    ]
    assert context.actor_scope is not None
    assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
        "root",
        "country",
        "actor",
    )
    model = compiler.load_model()
    assert model.consumer_ir is not None
    instances = {item.action_id: item for item in model.action_instances}
    selected = [
        writer
        for writer in model.consumer_ir.writers
        if writer.field.endswith("min_law_chance_to_pass")
    ]
    assert len(selected) == 3
    for writer in selected:
        instance = instances[writer.writer_id]
        assert writer.evaluation_context == instance.evaluation_context == context
        assert {row[0] for row in writer.reader_context_bindings} == set(instance.condition_facts)
        assert all(
            row[1:] == ("root", "country", "actor") for row in writer.reader_context_bindings
        )


@pytest.mark.parametrize("damage", ["definition", "target", "missing", "extra"])
def test_min_law_rejects_type_or_role_substitution_even_for_root_only_readers(damage):
    context = compiler._frozen_strategy_contexts()["min_law_chance_to_pass"]
    law = context.auxiliary_scopes[0]
    if damage == "definition":
        with pytest.raises(ValueError, match="绑定名称、类型或角色无效"):
            replace(context, auxiliary_scopes=(replace(law, kind="law_type"),))
        return
    if damage == "target":
        with pytest.raises(ValueError, match="绑定名称、类型或角色无效"):
            replace(context, targets=(replace(law, role="target"),), auxiliary_scopes=())
        return
    if damage == "missing":
        wrong = replace(context, auxiliary_scopes=())
    else:
        wrong = replace(
            context,
            auxiliary_scopes=(
                *context.auxiliary_scopes,
                decision_ir.ContextBinding("target_country", "country", "auxiliary", "fixture", 1),
            ),
            evidence=(*context.evidence, "fixture:1"),
        )
    reader = decision_rules.Reader("gdp", "gdp", "root", "annual_gdp_currency", "number")
    with pytest.raises(ValueError, match="精确冻结证据"):
        compiler.validate_context_readers(
            "min_law_chance_to_pass", wrong, {"gdp": reader}, (), input_keys=("gdp",)
        )


def test_min_law_does_not_authorize_country_reader_on_law_or_offset_actor():
    context = compiler._frozen_strategy_contexts()["min_law_chance_to_pass"]
    reader = decision_rules.Reader("gdp", "gdp", "law", "annual_gdp_currency", "number")
    with pytest.raises(ValueError, match="作用域 getter"):
        compiler.validate_context_readers(
            "min_law_chance_to_pass", context, {"gdp": reader}, (), input_keys=("gdp",)
        )
    with pytest.raises(ValueError, match="ROOT"):
        compiler.validate_context_readers(
            "min_law_chance_to_pass",
            context,
            {"gdp": replace(reader, scope="root")},
            (),
            input_keys=("gdp",),
            actor_path=("owner",),
        )
