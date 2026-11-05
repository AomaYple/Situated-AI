"""Exact enum score children bind actual targets without authorizing containers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace

import pytest

from pdx import decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, engine_scope, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "field",
    [
        "wargoal_scores",
        "secret_goal_scores",
        "wanted_navy_size",
        "ship_construction_output_multiplier",
    ],
)
def test_new_exact_strategy_consumers_have_proven_country_root(field):
    data = json.loads(engine_scope.strategy_snapshot())
    assert data["consumers"][field]["actor_scope"] == "country"
    assert data["consumers"][field]["capability"] == "direct"
    context = compiler._frozen_strategy_contexts()[field]
    assert context.actor_scope is not None
    assert context.actor_scope.kind == "country"
    expected = (
        [("target_country", "country"), ("target_state", "state")]
        if field == "wargoal_scores"
        else [("target_country", "country")]
        if field == "secret_goal_scores"
        else []
    )
    assert [(row.name, row.kind) for row in context.targets] == expected
    assert context.auxiliary_scopes == ()


@pytest.fixture
def goal_proof(tmp_path, monkeypatch):
    data = json.loads(engine_scope.strategy_snapshot())
    assert len(data["observations"]) >= 388
    points = data["observations"][169:325]
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
    for source in data["script_hashes"]:
        raw = b"sample = { wargoal_scores = { annex_country = { value = 10 } } }"
        inputs[source] = raw
        data["script_hashes"][source] = hashlib.sha256(raw).hexdigest()
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
    return game, exe, data, inputs, freeze


@pytest.mark.parametrize("index", range(156))
def test_every_goal_and_navy_exact_span_is_required_even_with_repin(goal_proof, index):
    game, exe, data, inputs, freeze = goal_proof
    raw = bytearray(exe.read_bytes())
    raw[int(data["observations"][index]["file_offset"], 16)] ^= 1
    exe.write_bytes(raw)
    data["exe"]["sha256"] = hashlib.sha256(raw).hexdigest()
    freeze()
    with pytest.raises(ValueError, match="字节不一致"):
        engine_scope.strategy_evidence(game, inputs)


@pytest.mark.parametrize(
    "field",
    [
        "wargoal_scores",
        "secret_goal_scores",
        "wanted_navy_size",
        "ship_construction_output_multiplier",
    ],
)
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
def test_repinning_exact_goal_or_navy_consumer_does_not_grant_adjacent_fields(
    goal_proof, field, member
):
    game, _, data, inputs, freeze = goal_proof
    if member == "field":
        data["consumers"][field + "_adjacent"] = data["consumers"].pop(field)
    else:
        data["consumers"][field][member] = "unknown"
    freeze()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_snapshot()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_evidence(game, inputs)


@pytest.mark.parametrize(("field", "count"), [("wargoal_scores", 34), ("secret_goal_scores", 9)])
@pytest.mark.parametrize("damage", ["unknown", "order", "duplicate", "missing"])
def test_enum_keys_are_exact_ordered_original_identities(goal_proof, field, count, damage):
    _, _, data, _, freeze = goal_proof
    keys = data["strategy_score_keys"][field]
    assert len(keys) == count
    if damage == "unknown":
        keys[0] = "adjacent_unknown"
    elif damage == "order":
        keys.reverse()
    elif damage == "duplicate":
        keys.append(keys[0])
    else:
        keys.pop()
    freeze()
    with pytest.raises(ValueError, match="枚举"):
        engine_scope.strategy_snapshot()


@pytest.mark.parametrize(
    ("family", "key"), [("wargoal_scores", "annex_country"), ("secret_goal_scores", "antagonize")]
)
def test_only_exact_ordinary_numeric_score_child_is_a_consumer(goal_proof, family, key):
    game, _, _, inputs, _ = goal_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    numeric = "value = 10"
    inner = (
        numeric
        if family == "wargoal_scores"
        else f"trigger = {{ always = no }} score = {{ {numeric} }}"
    )
    definition = parse_text(
        f"sample = {{ {family} = {{ {key} = {{ {inner} }} }} }}"
    ).top_assignments[0]
    numeric_path = (family, key) if family == "wargoal_scores" else (family, key, "score")
    source = next(iter(inputs))
    scope = vanilla_inventory._scope(
        "ai_strategies", numeric_path, inputs, {}, definition, source, strategy_proof=proof
    )
    assert (scope.actor, scope.operation, scope.capability) == (
        "country",
        "additive_score",
        "direct",
    )
    for path in [(family,), (family, key)] if family == "secret_goal_scores" else [(family,)]:
        row = vanilla_inventory._scope(
            "ai_strategies", path, inputs, {}, definition, source, strategy_proof=proof
        )
        assert row.actor == "definition_structure"
        assert row.capability == "observation"
    for path in [(family, key, "trigger"), (*numeric_path, "nested"), (family, "future_unknown")]:
        row = vanilla_inventory._scope(
            "ai_strategies", path, inputs, {}, definition, source, strategy_proof=proof
        )
        assert row.capability != "direct"


@pytest.mark.parametrize("family", ["wargoal_scores", "secret_goal_scores"])
@pytest.mark.parametrize(
    "damage",
    [
        "unknown",
        "duplicate",
        "prefix",
        "scalar",
        "nested",
        "duplicate_map",
        "prefixed_map",
        "duplicate_score",
    ],
)
def test_invalid_map_shapes_cannot_inherit_parent_country_scope(goal_proof, family, damage):
    game, _, _, inputs, _ = goal_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    key = "annex_country" if family == "wargoal_scores" else "antagonize"
    child = (
        "value = 10"
        if family == "wargoal_scores"
        else "trigger = { always = yes } score = { value = 10 }"
    )
    entry = f"{key} = {{ {child} }}"
    if damage == "unknown":
        entry = f"future_unknown = {{ {child} }}"
    elif damage == "duplicate":
        entry += " " + entry
    elif damage == "prefix":
        entry = "REPLACE:" + entry
    elif damage == "scalar":
        entry = f"{key} = 10"
    elif damage == "nested":
        entry = f"{key} = {{ nested = {{ {child} }} }}"
    elif damage == "duplicate_score":
        entry = (
            f"{key} = {{ score = {{ value = 10 }} score = {{ value = 20 }} }}"
            if family == "secret_goal_scores"
            else f"{key} = {{ score = {{ value = 10 }} }}"
        )
    body = f"{family} = {{ {entry} }}"
    if damage == "duplicate_map":
        body += " " + body
    elif damage == "prefixed_map":
        body = "REPLACE:" + body
    definition = parse_text(f"sample = {{ {body} }}").top_assignments[0]
    path = (family, key) if family == "wargoal_scores" else (family, key, "score")
    row = vanilla_inventory._scope(
        "ai_strategies", path, inputs, {}, definition, next(iter(inputs)), strategy_proof=proof
    )
    assert row.capability == "pending"


def test_all_actual_goal_and_navy_writer_inputs_bind_exactly_proven_objects():
    model = compiler.load_model()
    assert model.consumer_ir is not None
    instances = {row.action_id: row for row in model.action_instances}
    selected = [
        writer
        for writer in model.consumer_ir.writers
        if writer.field.removeprefix("ai_strategy_default.").split(".")[0]
        in {
            "wargoal_scores",
            "secret_goal_scores",
            "wanted_navy_size",
            "ship_construction_output_multiplier",
        }
    ]
    assert Counter(
        writer.field.removeprefix("ai_strategy_default.").split(".")[0] for writer in selected
    ) == {
        "wargoal_scores": 74,
        "secret_goal_scores": 27,
        "wanted_navy_size": 7,
        "ship_construction_output_multiplier": 4,
    }
    for writer in selected:
        instance = instances[writer.writer_id]
        assert writer.evaluation_context == instance.evaluation_context
        assert writer.evaluation_context is not None
        assert {row[0] for row in writer.reader_context_bindings} == set(instance.condition_facts)
        assert all(
            row[1:] in {("root", "country", "actor"), ("target_country", "country", "target")}
            for row in writer.reader_context_bindings
        )


@pytest.mark.parametrize("family", ["wargoal_scores", "secret_goal_scores"])
def test_goal_maps_reject_extra_missing_targets_even_when_current_rule_uses_root_only(family):
    context = compiler._frozen_strategy_contexts()[family]
    field = (
        "wargoal_scores.annex_country"
        if family == "wargoal_scores"
        else "secret_goal_scores.antagonize.score"
    )
    reader = decision_rules.Reader("war", "is_at_war", "root", "boolean", "boolean")
    with pytest.raises(ValueError, match="精确冻结证据"):
        compiler.validate_context_readers(
            field, replace(context, targets=()), {"war": reader}, (), input_keys=("war",)
        )


def test_optional_play_is_explicitly_unprojected_and_never_a_reader_grant():
    data = json.loads(engine_scope.strategy_snapshot())
    play = data["native_unprojected_contexts"]["wargoal_scores"]["diplomatic_play"]
    assert play["status"] == "unprojected_unknown"
    assert play["reader_authorization"] is False
    context = compiler._frozen_strategy_contexts()["wargoal_scores"]
    reader = decision_rules.Reader("war", "is_at_war", "diplomatic_play", "boolean", "boolean")
    with pytest.raises(ValueError, match="上下文证据"):
        compiler.validate_context_readers(
            "wargoal_scores.annex_country", context, {"war": reader}, (), input_keys=("war",)
        )
