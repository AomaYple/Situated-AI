"""Exact construction/institution evidence never grants adjacent engine scopes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

import pytest
from _frozen_reader_words import frozen_reader_words

from pdx import country_state, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, decision_ir, engine_scope, pdx_eval, vanilla_inventory

pytestmark = pytest.mark.unit


def test_snapshot_authorizes_only_exact_construction_and_institution_consumers():
    contracts = json.loads(engine_scope.strategy_snapshot())["consumers"]
    assert "wanted_construction_output" in contracts
    assert "institution_scores" in contracts
    construction = contracts["wanted_construction_output"]
    assert construction["actor_scope"] == "country"
    assert construction["target_scope"] == "none"
    assert construction["operation"] == "additive_construction_output_target"
    assert construction["consumer_va"] == "0x1418288e0"
    assert construction["member_offset"] == "0x16c0"
    institution = contracts["institution_scores"]
    assert institution["actor_scope"] == "country"
    assert institution["target_scope"] == "definition_only:institution_type"
    assert institution["operation"] == "additive_score"
    assert institution["consumer_va"] == "0x141826d9a"
    assert institution["member_offset"] == "0x3f0"
    assert (
        not {
            "wanted_construction_input_goods_surplus_ratio",
            "wanted_construction_ratio",
            "desired_tax_level",
            "max_institution_spending",
        }
        & contracts.keys()
    )


@pytest.fixture
def construction_institution_proof(tmp_path, monkeypatch):
    """Exercise file verification with all 28 observed spans in a compact image."""
    data = json.loads(engine_scope.strategy_snapshot())
    observations = data["observations"][120:148]
    image = bytearray()
    for point in observations:
        point["file_offset"] = hex(len(image))
        image.extend(bytes.fromhex(point["bytes"]))
    data["observations"] = observations
    exe = tmp_path / "binaries/victoria3.exe"
    exe.parent.mkdir()
    exe.write_bytes(image)
    data["exe"] = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)}
    game = tmp_path / "game"
    inputs = {}
    for index, source in enumerate(data["script_hashes"]):
        raw = f"strategy_{index} = {{ wanted_construction_output = 1 }}\n".encode()
        inputs[source] = raw
        data["script_hashes"][source] = hashlib.sha256(raw).hexdigest()
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    manifest = tmp_path / "strategy.json"

    for support_key in (
        "institution_definition_bytes",
        "stance_definition_bytes",
        "configured_default_script_bytes",
    ):
        for source, raw_hex in data[support_key].items():
            path = game / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes.fromhex(raw_hex))
            inputs[source] = bytes.fromhex(raw_hex)

    def freeze():
        raw = json.dumps(data).encode()
        manifest.write_bytes(raw)
        monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", manifest)
        monkeypatch.setattr(
            engine_scope, "STRATEGY_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest()
        )

    freeze()
    return game, exe, data, inputs, freeze


@pytest.mark.parametrize("field", ["wanted_construction_output", "institution_scores"])
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
def test_repinning_consumer_changes_cannot_grant_other_objects_or_members(
    construction_institution_proof, field, member
):
    game, _, data, inputs, freeze = construction_institution_proof
    if member == "field":
        data["consumers"][field + "_adjacent"] = data["consumers"].pop(field)
    else:
        data["consumers"][field][member] = "unproven"
    freeze()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_snapshot()
    with pytest.raises(ValueError, match="消费者字段合同"):
        engine_scope.strategy_evidence(game, inputs)


def test_production_verification_keeps_definition_identity_out_of_named_scopes(
    construction_institution_proof,
):
    game, _, _, _, _ = construction_institution_proof
    proof = engine_scope.verify_strategy_game(game)
    assert proof.verified
    by_field = {item.field: item for item in proof.consumers}
    institution = by_field["institution_scores"]
    assert (institution.actor, institution.target, institution.operation) == (
        "country",
        "definition_only:institution_type",
        "additive_score",
    )
    construction = by_field["wanted_construction_output"]
    assert (construction.actor, construction.target) == ("country", "none")
    assert "@engine/binaries/victoria3.exe:0x141826d9a" in institution.references
    assert "@engine/binaries/victoria3.exe:0x1418288e0" in construction.references


@pytest.mark.parametrize("index", range(28))
def test_each_added_original_byte_span_is_required(construction_institution_proof, index):
    game, exe, data, inputs, freeze = construction_institution_proof
    point = data["observations"][index]
    image = bytearray(exe.read_bytes())
    image[int(point["file_offset"], 16)] ^= 1
    exe.write_bytes(image)
    # Repinning the whole-image hash cannot bypass the observed raw bytes.
    data["exe"]["sha256"] = hashlib.sha256(image).hexdigest()
    freeze()
    with pytest.raises(ValueError, match="字节不一致"):
        engine_scope.strategy_evidence(game, inputs)


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_every_original_strategy_source_is_required_at_production_boundary(
    construction_institution_proof, index, damage
):
    game, _, data, _, _ = construction_institution_proof
    source = tuple(data["script_hashes"])[index]
    path = game / source
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"\nchanged = yes")
    with pytest.raises((ValueError, FileNotFoundError)):
        engine_scope.verify_strategy_game(game)


@pytest.mark.parametrize("damage", ["missing", "changed", "duplicate", "extra"])
def test_production_boundary_requires_exact_institution_definition_set(
    construction_institution_proof, damage
):
    game, _, data, _, _ = construction_institution_proof
    source = next(iter(data["institution_definition_sources"]))
    path = game / source
    if damage == "missing":
        path.unlink()
    elif damage == "changed":
        path.write_bytes(path.read_bytes() + b"\nchanged = {}")
    else:
        path = game / "dlc/fixture/in_game/common/institutions/shadow.txt"
        path.parent.mkdir(parents=True)
        path.write_text(
            "institution_schools = {}" if damage == "duplicate" else "future_institution = {}",
            encoding="utf-8",
        )
    with pytest.raises((ValueError, FileNotFoundError)):
        engine_scope.verify_strategy_game(game)


@pytest.mark.parametrize("field", ["wanted_construction_output", "institution_scores"])
def test_compiler_context_is_root_only_without_definition_as_a_script_object(field):
    context = compiler._frozen_strategy_contexts()[field]
    assert context.targets == context.auxiliary_scopes == ()
    assert context.actor_scope is not None
    assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
        "root",
        "country",
        "actor",
    )
    reader = decision_rules.Reader("need", "gdp", "root", "annual_gdp_currency", "number")
    reader_field = (
        field if field == "wanted_construction_output" else field + ".institution_schools"
    )
    assert compiler.validate_context_readers(
        reader_field, context, {"need": reader}, (), input_keys=("need",)
    ) == (("need", "root", "country", "actor"),)
    with pytest.raises(ValueError, match="ROOT"):
        compiler.validate_context_readers(
            reader_field, context, {"need": reader}, (), input_keys=("need",), actor_path=("owner",)
        )
    with pytest.raises(ValueError, match="上下文证据"):
        compiler.validate_context_readers(
            reader_field,
            context,
            {"need": replace(reader, scope="overlord")},
            (),
            input_keys=("need",),
        )
    target = decision_ir.ContextBinding("target_country", "country", "target", "fixture", 1)
    wrong = replace(context, targets=(target,), evidence=(*context.evidence, "fixture:1"))
    with pytest.raises(ValueError, match="精确冻结证据"):
        compiler.validate_context_readers(
            reader_field, wrong, {"need": reader}, (), input_keys=("need",)
        )


@pytest.mark.parametrize(
    "body",
    [
        "institution_scores = { institution_schools = { value = 10 } }",
        "institution_scores = { institution_schools = { value = 10 } institution_police = { value = 3 } }",
    ],
)
def test_inventory_institution_children_are_country_scores_and_map_is_structure(
    construction_institution_proof, body
):
    game, _, _, inputs, _ = construction_institution_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    source = next(iter(inputs))
    definition = parse_text(f"sample = {{ {body} }}").top_assignments[0]
    child = vanilla_inventory._scope(
        "ai_strategies",
        ("institution_scores", "institution_schools"),
        inputs,
        {},
        definition,
        source,
        strategy_proof=proof,
    )
    assert (child.actor, child.target, child.operation, child.capability) == (
        "country",
        "definition_only:institution_type",
        "additive_score",
        "direct",
    )
    container = vanilla_inventory._scope(
        "ai_strategies",
        ("institution_scores",),
        inputs,
        {},
        definition,
        source,
        strategy_proof=proof,
    )
    assert container.capability == "observation"
    assert container.operation == "institution_score_map"


@pytest.mark.parametrize(
    "body",
    [
        "institution_scores = 10",
        "institution_scores = { institution_schools = 10 }",
        "institution_scores = { institution_schools = { nested = { value = 10 } } }",
        "institution_scores = { institution_schools = { value = 10 } institution_schools = { value = 2 } }",
        "institution_scores = { REPLACE:institution_schools = { value = 10 } }",
        "REPLACE:institution_scores = { institution_schools = { value = 10 } }",
        "institution_scores = { future_institution = { value = 10 } }",
        "institution_scores = { institution_schools = { value = 10 } unknown = { value = 2 } }",
        "institution_scores = { institution_schools = { value = 10 } } institution_scores = {}",
    ],
)
def test_inventory_never_projects_institution_prefix_or_ambiguous_map(
    construction_institution_proof, body
):
    game, _, _, inputs, _ = construction_institution_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    source = next(iter(inputs))
    definition = parse_text(f"sample = {{ {body} }}").top_assignments[0]
    for field in [
        ("institution_scores",),
        ("institution_scores", "institution_schools"),
        ("institution_scores", "future_institution"),
        ("institution_scores", "institution_schools", "nested"),
    ]:
        scope = vanilla_inventory._scope(
            "ai_strategies",
            field,
            inputs,
            {},
            definition,
            source,
            strategy_proof=proof,
        )
        assert scope.capability == "pending"
        assert scope.actor == "unknown"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "prefixed", "scalar"])
def test_actual_institution_definition_identity_is_required(construction_institution_proof, damage):
    game, _, data, inputs, _ = construction_institution_proof
    proof = engine_scope.strategy_evidence(game, inputs)
    definition_source = next(iter(data["institution_definition_sources"]))
    if damage == "missing":
        inputs.pop(definition_source)
    elif damage == "duplicate":
        inputs["dlc/example/common/institutions/duplicate.txt"] = b"institution_schools = {}"
    elif damage == "prefixed":
        inputs[definition_source] = b"REPLACE:institution_schools = {}"
    else:
        inputs[definition_source] = b"institution_schools = 1"
    definition = parse_text(
        "sample = { institution_scores = { institution_schools = { value = 10 } } }"
    ).top_assignments[0]
    scope = vanilla_inventory._scope(
        "ai_strategies",
        ("institution_scores", "institution_schools"),
        inputs,
        {},
        definition,
        next(iter(inputs)),
        strategy_proof=proof,
    )
    assert scope.capability == "pending"


def test_all_actual_construction_institution_variants_bind_every_input_and_writer():
    model = compiler.load_model()
    assert model.consumer_ir is not None
    instances = {item.action_id: item for item in model.action_instances}
    selected = [
        row
        for row in model.consumer_ir.writers
        if row.field.removeprefix("ai_strategy_default.") == "wanted_construction_output"
        or row.field.removeprefix("ai_strategy_default.").startswith("institution_scores.")
    ]
    from collections import Counter

    assert Counter(row.field.removeprefix("ai_strategy_default.") for row in selected) == {
        "wanted_construction_output": 6,
        "institution_scores.institution_schools": 6,
        "institution_scores.institution_health_system": 7,
        "institution_scores.institution_social_security": 9,
        "institution_scores.institution_workplace_safety": 6,
        "institution_scores.institution_home_affairs": 6,
        "institution_scores.institution_police": 6,
        "institution_scores.institution_colonial_affairs": 2,
    }
    for writer in selected:
        instance = instances[writer.writer_id]
        assert writer.evaluation_context == instance.evaluation_context
        assert writer.evaluation_context is not None
        assert writer.evaluation_context.targets == writer.evaluation_context.auxiliary_scopes == ()
        assert {row[0] for row in writer.reader_context_bindings} == set(instance.condition_facts)
        assert writer.reader_context_bindings
        assert all(
            row[1:] == ("root", "country", "actor") for row in writer.reader_context_bindings
        )


@pytest.fixture(scope="module")
def numeric_production():
    source = "common/ai_strategies/00_default_strategy.txt"
    policy = decision_rules.load()
    rules = tuple(
        rule
        for rule in policy.rules
        if rule.id in {"fiscal_construction_guard", "remaining_school_catchup_need"}
    )
    assert len(rules) == 2
    keys = frozenset(key for rule in rules for key in rule.input_keys())
    policy = replace(
        policy,
        rules=rules,
        readers=tuple(r for r in policy.readers if r.key in keys),
        enabled_domains=frozenset(rule.domain for rule in rules),
        semantic_ir=(),
        consumer_programs=(),
    )
    model = compiler.load_model()
    compiled, _ = compiler.compile_policy(policy, "mod/decisions/information.toml", model)
    native = compiler.BASELINE.read_text(encoding="utf-8")
    generated = decision_rules.patch(
        native,
        compiled,
        baseline=native,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source="mod/decisions/information.toml",
        reader_words=frozen_reader_words(native),
    )
    return source, compiled, native, generated


def _numeric_overlay(text, field):
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    return "\n".join(text[begin:end].splitlines()[1:])


@pytest.mark.parametrize(
    ("field", "values", "root", "base", "expected"),
    [
        (
            "wanted_construction_output",
            {"default": True, "war": False},
            {"in_default": True, "is_at_war": False},
            100,
            75,
        ),
        (
            "institution_scores.institution_schools",
            {"literacy": 0.3, "population": 3000000},
            {"literacy_rate": 0.3, "total_population": 3000000},
            10,
            11,
        ),
    ],
)
def test_generated_numeric_targets_preserve_player_disabled_unknown_and_country_identity(
    numeric_production, field, values, root, base, expected
):
    _, policy, _, generated = numeric_production
    overlay = _numeric_overlay(generated, field)
    facts = {"ROOT": {"is_ai": True, **root}}
    result = pdx_eval.select(overlay, facts)
    reference = decision_rules.evaluate(policy, values, is_ai=True)[field]
    assert result.operation == "multiply"
    assert result.delta == pytest.approx(reference[1])
    assert base * result.delta == pytest.approx(expected)
    assert base * reference[1] == pytest.approx(expected)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert pdx_eval.select(overlay, {"ROOT": {**root, "is_ai": False}}).operation is None
    for key in root:
        changed = {**root, key: None, "is_ai": True}
        outcome = pdx_eval.select(overlay, {"ROOT": changed, "other_country": root})
        # War is no longer a shared all-known gate for observed default costs.
        # Schools still need the actual literacy and population observations.
        expected_partial = 0.75 if key == "is_at_war" else 1
        assert outcome.delta == pytest.approx(expected_partial)
    assert pdx_eval.select(overlay, {"ROOT": {"is_ai": True}, "other_country": root}).delta == 1
    # No scope can make a native terminal zero positive through this multiplier.
    assert 0 * result.delta == 0


def _syntax(node):
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _syntax(node.value)
    assert isinstance(node, Block)
    return tuple(_syntax(item) for item in node.items)


def test_generated_native_target_arithmetic_and_institution_values_survive(numeric_production):
    _, _, native, generated = numeric_production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL | re.MULTILINE,
    )
    before, after = parse_text(native), parse_text(stripped)
    assert not before.errors
    assert not after.errors
    assert _syntax(before.root) == _syntax(after.root)


@pytest.mark.parametrize(
    "field", ["wanted_construction_output", "institution_scores.institution_schools"]
)
def test_nonpredicate_actual_inputs_cannot_hide_an_unproven_scope(field):
    context = compiler._frozen_strategy_contexts()[field.split(".")[0]]
    readers = {
        "condition": decision_rules.Reader("condition", "is_at_war", "root", "boolean", "boolean"),
        "cost": decision_rules.Reader("cost", "gdp", "overlord", "annual_gdp_currency", "number"),
    }
    with pytest.raises(ValueError, match="上下文证据"):
        compiler.validate_context_readers(
            field, context, readers, (), input_keys=("condition", "cost")
        )
