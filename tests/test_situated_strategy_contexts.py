"""Frozen engine contexts remain distinct from verification of current game bytes."""

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import config, decision_adapters, decision_rules, version_contracts
from pdx.situated import (
    actions,
    compiler,
    decision_ir,
    engine_scope,
    engine_scope_115,
    evidence,
    relations,
    support_signals,
)
from pdx.situated.schema import RankTerm, Relation

pytestmark = pytest.mark.unit


@pytest.fixture
def historical_strategy_contract():
    with version_contracts.select_version("1.14.5"):
        yield


@pytest.mark.parametrize(
    ("field", "target", "actor_line", "target_line", "address"),
    [
        ("recklessness", "target_country", 43, 44, "0x1416452bf"),
        ("wargoal_maneuvers_fraction", "enemy_country", 75, 76, "0x141647b8f"),
    ],
)
def test_snapshot_context_uses_actual_manifest_lines_without_live_claim(
    monkeypatch,
    tmp_path,
    field,
    target,
    actor_line,
    target_line,
    address,
    historical_strategy_contract,
):
    snapshot = compiler._frozen_strategy_contexts()
    monkeypatch.setattr(config, "GAME", tmp_path / "absent-game")
    monkeypatch.setattr(
        engine_scope,
        "strategy_evidence",
        lambda *_: pytest.fail("loading frozen contexts must not inspect the current EXE"),
    )
    assert compiler._frozen_strategy_contexts() == snapshot
    assert set(snapshot) == {
        "treaty_category_scores",
        "strategic_region_stance_type_scores",
        "wanted_num_supply_ships",
        "max_ship_design_complexity",
        "recklessness",
        "wargoal_maneuvers_fraction",
        "wanted_construction_output",
        "institution_scores",
        "min_law_chance_to_pass",
        "wargoal_scores",
        "secret_goal_scores",
        "wanted_navy_size",
        "ship_construction_output_multiplier",
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
    }
    context = snapshot[field]
    assert context.status == "observed"
    assert context.actor_scope is not None
    assert context.actor_scope.line == actor_line
    assert context.targets[0].line == target_line
    assert context.targets[0].name == target
    lines = engine_scope.STRATEGY_MANIFEST.read_text(encoding="utf-8").splitlines()
    assert lines[actor_line - 1].strip() == '"actor_scope": "country",'
    assert lines[target_line - 1].strip() == f'"target_scope": "scope:{target}=country",'
    assert all(
        binding.source == engine_scope.STRATEGY_MANIFEST_ID
        for binding in (
            context.actor_scope,
            *context.targets,
        )
    )
    assert f"{engine_scope.STRATEGY_MANIFEST_ID}:consumer={field}:va={address}" in context.evidence
    assert any("evidence=frozen_engine_snapshot" in item for item in context.evidence)
    assert not any(item.startswith("@engine/") for item in context.evidence)


def test_snapshot_rejects_manifest_byte_drift(monkeypatch, tmp_path, historical_strategy_contract):
    path = tmp_path / "manifest.json"
    path.write_bytes(engine_scope.STRATEGY_MANIFEST.read_bytes() + b" ")
    monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", path)
    with pytest.raises(ValueError, match="策略作用域证据"):
        compiler._frozen_strategy_contexts()


@pytest.mark.parametrize(
    "member",
    ["actor_scope", "target_scope", "operation", "capability", "unit", "consumer_va", "field"],
)
def test_repinning_a_changed_consumer_cannot_authorize_another_contract(
    monkeypatch, tmp_path, member, historical_strategy_contract
):
    data = json.loads(engine_scope.STRATEGY_MANIFEST.read_bytes())
    entry = data["consumers"]["recklessness"]
    if member == "field":
        data["consumers"]["another_field"] = data["consumers"].pop("recklessness")
    else:
        entry[member] = "unproven"
    raw = json.dumps(data, indent=2).encode()
    path = tmp_path / "manifest.json"
    path.write_bytes(raw)
    monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", path)
    monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="消费者字段合同"):
        compiler._frozen_strategy_contexts()


@pytest.mark.parametrize("field", ["recklessness", "wargoal_maneuvers_fraction"])
def test_engine_context_requires_exact_target_and_country_root_without_adding_getters(field):
    context = compiler._frozen_strategy_contexts()[field]
    reader = decision_rules.Reader("need", "gdp", "root", "annual_gdp_currency", "number")
    assert compiler.validate_context_readers(
        field, context, {"need": reader}, (), input_keys=("need",)
    ) == (("need", "root", "country", "actor"),)
    for path in (("owner",), ("owner", "owner")):
        with pytest.raises(ValueError, match="ROOT"):
            compiler.validate_context_readers(field, context, {"need": reader}, (), actor_path=path)
    wrong = replace(
        context,
        targets=(
            decision_ir.ContextBinding(
                "target_state",
                "state",
                "target",
                context.targets[0].source,
                context.targets[0].line,
            ),
        ),
    )
    with pytest.raises(ValueError, match="精确冻结证据"):
        compiler.validate_context_readers(field, wrong, {"need": reader}, (), input_keys=("need",))
    with pytest.raises(ValueError, match="真实读取器"):
        compiler.validate_context_readers(field, context, {}, (), input_keys=("missing",))
    foreign = replace(reader, scope="overlord")
    with pytest.raises(ValueError, match="上下文证据"):
        compiler.validate_context_readers(
            field, context, {"need": foreign}, (), input_keys=("need",)
        )
    if field == "wargoal_maneuvers_fraction":
        with pytest.raises(ValueError, match="getter"):
            compiler.validate_context_readers(
                field,
                context,
                {"need": replace(reader, scope="enemy_country")},
                (),
                input_keys=("need",),
            )


def test_named_country_object_cannot_be_substituted_or_retyped_as_auxiliary():
    context = compiler._frozen_strategy_contexts()["recklessness"]
    target = context.targets[0]
    reader = decision_rules.Reader(
        "related",
        "is_subject_of",
        "root",
        "boolean",
        "boolean",
        argument="scope:target_country",
    )
    assert compiler.validate_context_readers(
        "recklessness", context, {"related": reader}, (), input_keys=("related",)
    ) == (
        ("related", "root", "country", "actor"),
        ("related", "target_country", "country", "target"),
    )
    for damaged in (
        replace(reader, argument="scope:target_state"),
        replace(reader, argument="scope:enemy_country"),
        replace(reader, path=("owner",)),
    ):
        with pytest.raises(ValueError, match="读取器"):
            compiler.validate_context_readers(
                "recklessness", context, {"related": damaged}, (), input_keys=("related",)
            )
    wrong = replace(context, targets=(), auxiliary_scopes=(replace(target, role="auxiliary"),))
    with pytest.raises(ValueError, match="精确冻结证据"):
        compiler.validate_context_readers(
            "recklessness", wrong, {"related": reader}, (), input_keys=("related",)
        )


@pytest.fixture(scope="module")
def card_inputs():
    declared = evidence.load(compiler.FACTS)
    consumers, cards = actions.load(compiler.ACTIONS)
    sources = compiler._load_supporting_sources()
    signals = support_signals.load(
        sources,
        compiler._reader_facts(declared),
        cards,
        reader_shapes=compiler._reader_shapes(declared),
    )
    links = relations.relations(cards, sources["relations.toml"].get("relations", []))
    rows = {row.action_id: row for row in decision_ir.compile_decisions(cards, consumers, links)}
    readers = (
        *decision_rules.load().readers,
        *(reader for _, policy in decision_adapters.load().policies for reader in policy.readers),
    )
    return declared, signals, rows, readers


def test_cards_bind_cost_exit_relation_and_support_alias_inputs(card_inputs):
    declared, signals, rows, readers = card_inputs
    context = compiler._frozen_strategy_contexts()["recklessness"]
    expected = {
        "diplomatic_opening": {
            "peace",
            "no_default",
            "stable_legitimacy",
            "subject",
            "support_diplomatic",
            "infamy",
            "war",
            "default",
        },
        "diplomatic_restraint": {"war", "peace"},
    }
    for name, keys in expected.items():
        bindings = compiler._action_context_readers(rows[name], context, declared, signals, readers)
        assert {row[0] for row in bindings} == keys
        assert all(row[1:] == ("root", "country", "actor") for row in bindings)


@pytest.mark.parametrize(
    "damage", ["cost", "exit", "rank", "relation", "alias", "scalar", "object", "unit"]
)
def test_card_context_rejects_unproven_actual_inputs(card_inputs, damage):
    declared, signals, rows, readers = card_inputs
    row = rows["diplomatic_opening"]
    context = compiler._frozen_strategy_contexts()["recklessness"]
    if damage == "cost":
        row = replace(row, consumes=(*row.consumes, "missing"))
    elif damage == "exit":
        row = replace(row, exit_when=(*row.exit_when, "missing"))
    elif damage == "rank":
        row = replace(row, rank_terms=(RankTerm("missing", "security", 1, "flag"),))
    elif damage == "relation":
        # Production opening has no relation; inject a real relation-shaped
        # input so this guard still reaches reader validation after migrations.
        row = replace(
            row,
            relations=(
                Relation(
                    row.action_id,
                    "diplomatic_restraint",
                    "complements",
                    0.025,
                    condition_facts=("missing",),
                ),
            ),
        )
    elif damage == "alias":
        signals = replace(
            signals,
            signals=tuple(
                replace(item, source_fact="missing") if item.alias == "support_diplomatic" else item
                for item in signals.signals
            ),
        )
    elif damage == "scalar":
        declared = tuple(
            replace(item, scope="target_state") if item.id == "stable_legitimacy" else item
            for item in declared
        )
    else:
        readers = tuple(
            replace(item, **({"scope": "overlord"} if damage == "object" else {"unit": "currency"}))
            if item.key == "infamy"
            else item
            for item in readers
        )
    with pytest.raises(ValueError, match="读取器"):
        compiler._action_context_readers(row, context, declared, signals, readers)


def test_production_instances_and_writers_share_frozen_context_offline(monkeypatch, tmp_path):
    live = compiler.load_model()
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    offline = compiler.load_model()
    assert offline.source_sha256 == live.source_sha256
    assert offline.contract() == live.contract()
    assert offline.consumer_ir is not None
    by_id = {instance.action_id: instance for instance in offline.action_instances}
    selected = [
        writer
        for writer in offline.consumer_ir.writers
        if writer.field
        in {
            "recklessness",
            "ai_strategy_default.wargoal_maneuvers_fraction",
        }
    ]
    assert len(selected) == 3
    for writer in selected:
        instance = by_id[writer.writer_id]
        assert writer.evaluation_context == instance.evaluation_context
        assert writer.evaluation_context is not None
        assert writer.evaluation_context.status == "observed"
        assert writer.reader_context_bindings
        if writer.kind == "rule_action":
            assert {row[0] for row in writer.reader_context_bindings} == set(
                instance.condition_facts
            )
    assert all(
        instance.evaluation_context is not None
        for instance in offline.action_instances
        if instance.consumer_field.endswith("min_law_chance_to_pass")
    )


@pytest.fixture
def current_game_fixture(monkeypatch, tmp_path):
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
        if version_contracts.is_115():
            registry = (
                engine_scope_115.MANIFESTS_1151
                if version_contracts.active_version() == "1.15.1"
                else engine_scope_115.MANIFESTS
            )
            monkeypatch.setitem(registry, "strategy", (str(manifest), digest))
        else:
            monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST", manifest)
            monkeypatch.setattr(engine_scope, "STRATEGY_MANIFEST_SHA256", digest)

    freeze()
    return game, executable, data, freeze


@pytest.mark.parametrize(
    "damage", ["exe_byte", "script_byte", "missing_exe", "missing_script", "size", "observation"]
)
def test_current_engine_verification_rejects_precise_byte_and_presence_drift(
    current_game_fixture, damage
):
    game, executable, data, freeze = current_game_fixture
    snapshot = compiler._frozen_strategy_contexts()
    proof = engine_scope.verify_strategy_game(game)
    assert proof.verified
    assert len(proof.strategy_sources) == 5
    script = game / next(iter(data["script_hashes"]))
    if damage == "exe_byte":
        raw = executable.read_bytes()
        executable.write_bytes(b"X" + raw[1:])
    elif damage == "script_byte":
        raw = script.read_bytes()
        script.write_bytes(b"X" + raw[1:])
    elif damage == "missing_exe":
        executable.unlink()
    elif damage == "missing_script":
        script.unlink()
    elif damage == "size":
        data["exe"]["bytes"] += 1
        freeze()
    else:
        data["observations"][0]["bytes"] = b"changed".hex()
        freeze()
    with pytest.raises((ValueError, FileNotFoundError)):
        engine_scope.verify_strategy_game(game)
    if damage not in {"size", "observation"}:
        # Frozen historical evidence remains available, but cannot make the
        # failed current-game gate pass or claim live verification.
        assert compiler._frozen_strategy_contexts() == snapshot
