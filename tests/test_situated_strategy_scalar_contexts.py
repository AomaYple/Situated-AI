"""Each remaining scalar has an exact member, actual country and native merge contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import config, decision_rules, version_contracts
from pdx.parser import parse_text
from pdx.situated import compiler, engine_scope, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.fixture
def historical_strategy_contract():
    """Only synthetic revision attacks use the reviewed historical schema."""
    with version_contracts.select_version("1.14.5"):
        yield


FIELDS = (
    "aggression",
    "nationalization_desire",
    "max_active_stances",
    "wanted_marines",
    "economic_vs_government_spending_balance",
    "target_marine_formation_size",
    "unacceptable_infamy_level",
    "undesirable_infamy_level",
    "diplomatic_play_neutrality",
    "diplomatic_play_boldness",
)


def test_r6_is_an_append_only_revision_with_ten_exact_consumers():
    data = json.loads(
        (
            engine_scope.REPO / "research/situated/victoria3-1.14.5-strategy-scope-r6.json"
        ).read_bytes()
    )
    assert len(data["consumers"]) == 29
    assert len(data["observations"]) == 388
    parent = json.loads(
        (
            engine_scope.REPO / "research/situated/victoria3-1.14.5-strategy-scope-r5.json"
        ).read_bytes()
    )
    assert data["observations"][:325] == parent["observations"]
    assert all(data["consumers"][key] == value for key, value in parent["consumers"].items())


@pytest.fixture
def scalar_proof(tmp_path, monkeypatch, historical_strategy_contract):
    data = json.loads(engine_scope.strategy_snapshot())
    points = data["observations"][325:388]
    assert len(points) == 63
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
        inputs[source] = b"sample = {}"
        data["script_hashes"][source] = hashlib.sha256(inputs[source]).hexdigest()
    path = tmp_path / "strategy.json"

    def freeze():
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", path)
        monkeypatch.setattr(
            engine_scope, "STRATEGY_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest()
        )

    freeze()
    return game, exe, data, inputs, freeze


@pytest.mark.parametrize("index", range(63))
def test_every_scalar_and_play_identity_span_is_checked_after_exe_repin(scalar_proof, index):
    game, exe, data, inputs, freeze = scalar_proof
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
def test_exact_scalar_contracts_fail_closed_after_manifest_repin(scalar_proof, field, member):
    game, _, data, inputs, freeze = scalar_proof
    if member == "field":
        data["consumers"][field + "_adjacent"] = data["consumers"].pop(field)
    else:
        data["consumers"][field][member] = "unknown"
    freeze()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_snapshot()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_evidence(game, inputs)


@pytest.mark.parametrize(
    "member",
    [
        "scope_tag",
        "native_type",
        "type_descriptor_va",
        "link_type_descriptor_va",
        "link_col_va",
        "link_vftable_va",
        "link_method_va",
        "resolver_va",
    ],
)
def test_play_instance_type_is_not_accepted_by_tag_guess(scalar_proof, member):
    _, _, data, _, freeze = scalar_proof
    data["diplomatic_play_instance_type"][member] = "unknown"
    freeze()
    with pytest.raises(ValueError, match="博弈实例"):
        engine_scope.strategy_snapshot()


@pytest.mark.parametrize("field", FIELDS)
def test_scalar_contexts_bind_exact_objects_and_country_root(field):
    context = compiler._frozen_strategy_contexts()[field]
    reader = decision_rules.Reader("war", "is_at_war", "root", "boolean", "boolean")
    assert compiler.validate_context_readers(
        field, context, {"war": reader}, (), input_keys=("war",)
    ) == (("war", "root", "country", "actor"),)
    assert [(row.name, row.kind, row.role) for row in context.targets] == (
        [("target_country", "country", "target")] if field == "aggression" else []
    )
    assert [(row.name, row.kind, row.role) for row in context.auxiliary_scopes] == (
        [("diplomatic_play", "diplomatic_play", "auxiliary")]
        if field == "diplomatic_play_boldness"
        else []
    )
    with pytest.raises(ValueError, match="ROOT"):
        compiler.validate_context_readers(
            field, context, {"war": reader}, (), input_keys=("war",), actor_path=("owner",)
        )


@pytest.mark.parametrize("field", ["aggression", "diplomatic_play_boldness"])
def test_root_only_rule_cannot_erase_actual_additional_objects(field):
    context = compiler._frozen_strategy_contexts()[field]
    reader = decision_rules.Reader("war", "is_at_war", "root", "boolean", "boolean")
    with pytest.raises(ValueError, match="精确冻结证据"):
        compiler.validate_context_readers(
            field,
            replace(context, targets=(), auxiliary_scopes=()),
            {"war": reader},
            (),
            input_keys=("war",),
        )


def test_play_object_evidence_grants_no_play_getter():
    context = compiler._frozen_strategy_contexts()["diplomatic_play_boldness"]
    reader = decision_rules.Reader("war", "is_at_war", "diplomatic_play", "boolean", "boolean")
    with pytest.raises(ValueError, match="getter"):
        compiler.validate_context_readers(
            "diplomatic_play_boldness", context, {"war": reader}, (), input_keys=("war",)
        )


def test_native_non_additive_contracts_are_explicit():
    data = json.loads(engine_scope.strategy_snapshot())
    assert {
        data["consumers"][field]["operation"]
        for field in ("unacceptable_infamy_level", "undesirable_infamy_level")
    } == {"first_positive_infamy_limit_override"}
    assert (
        data["consumers"]["diplomatic_play_neutrality"]["operation"]
        == "additive_positive_active_neutrality"
    )
    assert (
        data["consumers"]["diplomatic_play_boldness"]["operation"]
        == "native_randomized_additive_boldness"
    )
    assert "colonial_interest_ratio" not in data["consumers"]


@pytest.mark.parametrize("field", FIELDS)
def test_inventory_requires_each_exact_scalar_source_and_ordinary_child(scalar_proof, field):
    game, _, data, inputs, _ = scalar_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    source = next(iter(inputs))
    definition = parse_text(f"sample = {{ {field} = {{ value = 10 }} }}").top_assignments[0]

    def scope(*, path=(field,), row=definition, evidence=proof, origin=source):
        return vanilla_inventory._scope(
            "ai_strategies", path, inputs, {}, row, origin, strategy_proof=evidence
        )

    actual = scope()
    expected = data["consumers"][field]
    assert (actual.actor, actual.target, actual.operation, actual.capability) == (
        expected["actor_scope"],
        expected["target_scope"],
        expected["operation"],
        "direct",
    )
    assert scope(evidence=None).capability == "pending"
    assert scope(evidence=replace(proof, verified=False)).capability == "pending"
    assert scope(origin="common/ai_strategies/adjacent.txt").capability == "pending"
    assert scope(path=(field + "_adjacent",)).capability == "pending"
    assert scope(path=(field, "nested")).capability == "pending"
    for content in (
        "sample = {}",
        f"sample = {{ {field} = {{}} {field} = {{}} }}",
        f"sample = {{ {field} ?= {{}} }}",
        f"sample ?= {{ {field} = {{}} }}",
    ):
        assert scope(row=parse_text(content).top_assignments[0]).capability == "pending"


@pytest.fixture(scope="module")
def scalar_model():
    return compiler.load_model()


def _assert_scalar_writer_bindings(writer, instance, card):
    expected = (
        {
            *card.requires_all,
            *card.requires_any,
            *card.blocked_by,
            *card.exit_when,
            *card.consumes,
            *(term.fact for term in card.rank_terms),
            *(term.fact for term in (*card.commitment_when, *card.political_when)),
            *(fact for relation in card.relations for fact in relation.condition_facts),
        }
        if card is not None
        else set(instance.condition_facts)
    )
    assert writer.evaluation_context == instance.evaluation_context
    assert writer.evaluation_context is not None
    assert {row[0] for row in writer.reader_context_bindings} == expected
    assert all(
        row[1:] in {("root", "country", "actor"), ("target_country", "country", "target")}
        for row in writer.reader_context_bindings
    )


def test_all_actual_scalar_writers_bind_every_input_and_share_the_instance_context(
    scalar_model, monkeypatch, tmp_path
):
    model = scalar_model
    assert model.consumer_ir is not None
    instances = {row.action_id: row for row in model.action_instances}
    writers = [
        writer
        for writer in model.consumer_ir.writers
        if writer.field.removeprefix("ai_strategy_default.") in FIELDS
    ]
    default_source = "rule_action_common_ai_strategies_00_default_strategy_txt_"
    assert {writer.writer_id for writer in writers} == {
        "card_diplomatic_aggression_guard",
        "card_diplomatic_boldness_window",
        "card_education_and_research",
        "card_fiscal_recovery",
        "card_industrial_foundation",
        "card_wartime_defense",
        *(
            default_source + "ai_strategy_default_" + field
            for field in (
                "target_marine_formation_size",
                "unacceptable_infamy_level",
                "undesirable_infamy_level",
                "wanted_marines",
            )
        ),
        default_source + "coordinated_layered_fiscal_nationalization",
        default_source + "coordinated_layered_naval_target_marine_formation_size_overseas",
        default_source + "coordinated_layered_naval_wanted_marines_overseas",
        default_source + "structural_ownership_financial_cost",
        "rule_action_mod_decisions_information_toml_coordinated_layered_information_stances_overseas",
        "rule_action_mod_decisions_information_toml_diplomatic_overextension",
    }
    assert len(writers) == 16
    cards = {"card_" + row.action_id: row for row in model.decision_ir}
    for writer in writers:
        instance = instances[writer.writer_id]
        _assert_scalar_writer_bindings(writer, instance, cards.get(writer.writer_id))
    monkeypatch.setattr(config, "GAME", tmp_path / "absent")
    offline = compiler.load_model()
    assert offline.consumer_ir is not None
    assert offline.consumer_ir.writers == model.consumer_ir.writers


def test_card_binding_cannot_drop_a_real_support_input_outside_condition_facts(scalar_model):
    model = scalar_model
    writer = next(
        row
        for row in model.consumer_ir.writers
        if row.writer_id == "card_diplomatic_aggression_guard"
    )
    instance = next(row for row in model.action_instances if row.action_id == writer.writer_id)
    card = next(row for row in model.decision_ir if row.action_id == "diplomatic_aggression_guard")
    assert "support_military" not in instance.condition_facts
    assert "support_military" in {row[0] for row in writer.reader_context_bindings}
    damaged = replace(
        writer,
        reader_context_bindings=tuple(
            row for row in writer.reader_context_bindings if row[0] != "support_military"
        ),
    )
    with pytest.raises(AssertionError):
        _assert_scalar_writer_bindings(damaged, instance, card)
