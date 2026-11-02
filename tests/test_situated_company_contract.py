"""Company score scope: frozen history, current-game gate and adapter boundaries."""

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from pdx import config, decision_adapters, decision_interfaces
from pdx.situated import compiler, engine_scope
from pdx.textio import normalized_text

pytestmark = pytest.mark.unit
SOURCE = "common/company_types/sample.txt"


def _repin(monkeypatch, tmp_path, data):
    raw = json.dumps(data, indent=2).encode()
    path = tmp_path / "company-manifest.json"
    path.write_bytes(raw)
    monkeypatch.setattr(engine_scope, "COMPANY_MANIFEST", path)
    monkeypatch.setattr(engine_scope, "COMPANY_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())


def test_snapshot_context_has_exact_actor_line_definition_only_and_no_live_claim(
    monkeypatch, tmp_path
):
    raw = engine_scope.company_snapshot()
    expected = compiler._frozen_company_context()
    monkeypatch.setattr(config, "GAME", tmp_path / "absent-game")
    monkeypatch.setattr(
        engine_scope,
        "company_evidence",
        lambda *_: pytest.fail("frozen context must not verify current game bytes"),
    )
    monkeypatch.setattr(
        engine_scope,
        "verify_company_game",
        lambda *_: pytest.fail("frozen context must remain available without game"),
    )
    assert compiler._frozen_company_context() == expected
    assert expected.actor_scope is not None
    actor = expected.actor_scope
    assert (actor.name, actor.kind, actor.role, actor.source) == (
        "root",
        "country",
        "actor",
        engine_scope.COMPANY_MANIFEST_ID,
    )
    assert raw.decode().splitlines()[actor.line - 1].strip() == '"actor": "country",'
    assert expected.status == "observed"
    assert expected.targets == ()
    assert expected.auxiliary_scopes == ()
    assert f"{engine_scope.COMPANY_MANIFEST_ID}:definition_only:company_type" in expected.evidence
    assert any("evidence=frozen_engine_snapshot" in item for item in expected.evidence)
    assert not any(item.startswith("@engine/") for item in expected.evidence)


def test_company_snapshot_rejects_even_whitespace_byte_drift(monkeypatch, tmp_path):
    path = tmp_path / "company-manifest.json"
    path.write_bytes(engine_scope.company_snapshot() + b" ")
    monkeypatch.setattr(engine_scope, "COMPANY_MANIFEST", path)
    with pytest.raises(ValueError, match="公司作用域证据"):
        engine_scope.company_snapshot()
    with pytest.raises(ValueError, match="公司作用域证据"):
        compiler._frozen_company_context()


@pytest.mark.parametrize(
    "member",
    [
        "field",
        "actor",
        "target",
        "operation",
        "capability",
        "consumer",
        "actual_call",
        "numeric_member",
        "parser",
        "parser_receiver",
        "nonpositive_rejection",
    ],
)
def test_repinning_different_score_members_cannot_authorize_another_contract(
    monkeypatch, tmp_path, member
):
    data = json.loads(engine_scope.company_snapshot())
    row = next(row for row in data["contracts"] if row["field"] == "ai_weight")
    row[member] = "unproven"
    _repin(monkeypatch, tmp_path, data)
    with pytest.raises(ValueError, match="公司基础评分"):
        compiler._frozen_company_context()


@pytest.mark.parametrize("damage", ["missing", "duplicate", "only_eligibility"])
def test_frozen_context_requires_one_exact_score_field(monkeypatch, tmp_path, damage):
    data = json.loads(engine_scope.company_snapshot())
    score = next(row for row in data["contracts"] if row["field"] == "ai_weight")
    if damage == "duplicate":
        data["contracts"].append(copy.deepcopy(score))
    else:
        data["contracts"] = [row for row in data["contracts"] if row["field"] != "ai_weight"]
        if damage == "missing":
            data["contracts"] = []
    _repin(monkeypatch, tmp_path, data)
    with pytest.raises(ValueError, match="唯一作用域合同"):
        compiler._frozen_company_context()


@pytest.fixture
def current_company_game(monkeypatch, tmp_path):
    game = tmp_path / "game"
    executable = tmp_path / "binaries/victoria3.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"pinned-company-image")
    data = json.loads(engine_scope.company_snapshot())
    data["exe"] = {
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "bytes": executable.stat().st_size,
    }
    data["observations"] = [{"label": "call", "file_offset": "0x0", "bytes": b"pinned".hex()}]
    for index, source in enumerate(data["script_hashes"]):
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"company_fixture_{index} = {{ ai_weight = {{ value = 3 }} }}\n".encode())
        data["script_hashes"][source] = hashlib.sha256(path.read_bytes()).hexdigest()

    def freeze():
        _repin(monkeypatch, tmp_path, data)

    freeze()
    return game, executable, data, freeze


def test_current_company_game_verifies_every_locked_script_and_exe(current_company_game):
    game, executable, data, _freeze = current_company_game
    proof = engine_scope.verify_company_game(game)
    assert proof.verified
    assert set(proof.sources) == set(data["script_hashes"])
    assert len(proof.sources) == 22
    assert (
        dict(proof.source_hashes)["@engine/binaries/victoria3.exe"]
        == hashlib.sha256(executable.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "damage", ["exe_byte", "script_byte", "missing_exe", "missing_script", "size", "observation"]
)
def test_current_game_drift_fails_without_destroying_frozen_history(current_company_game, damage):
    game, executable, data, freeze = current_company_game
    context = compiler._frozen_company_context()
    script = game / next(iter(data["script_hashes"]))
    if damage == "exe_byte":
        executable.write_bytes(b"X" + executable.read_bytes()[1:])
    elif damage == "script_byte":
        script.write_bytes(b"X" + script.read_bytes()[1:])
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
        engine_scope.verify_company_game(game)
    if damage not in {"size", "observation"}:
        assert compiler._frozen_company_context() == context


@pytest.mark.parametrize(
    "directory", ["common/company_types", "dlc/fixture/in_game/common/company_types"]
)
def test_unlocked_company_shadow_cannot_pass_the_production_gate(current_company_game, directory):
    game, _executable, _data, _freeze = current_company_game
    shadow = game / directory / "new_override.txt"
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_text("company_fixture_0 = { ai_weight = { value = 100 } }\n", encoding="utf-8")
    with pytest.raises(ValueError):
        engine_scope.verify_company_game(game)


def test_company_model_and_writer_contexts_are_equal_without_game(monkeypatch, tmp_path):
    live = compiler.load_model()
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    monkeypatch.setattr(
        engine_scope,
        "verify_company_game",
        lambda *_: pytest.fail("model load is frozen, not live"),
    )
    offline = compiler.load_model()
    assert offline.source_sha256 == live.source_sha256
    assert offline.contract() == live.contract()
    assert offline.consumer_ir is not None
    by_id = {instance.action_id: instance for instance in offline.action_instances}
    writers = [
        row for row in offline.consumer_ir.writers if row.source.startswith("common/company_types/")
    ]
    assert writers
    for row in writers:
        assert row.field.endswith(".ai_weight")
        instance = by_id[row.writer_id]
        assert row.evaluation_context == instance.evaluation_context
        assert row.evaluation_context == compiler._frozen_company_context()
        assert {item[0] for item in row.reader_context_bindings} == set(instance.condition_facts)
        assert all(item[1:] == ("root", "country", "actor") for item in row.reader_context_bindings)


@pytest.mark.parametrize(
    ("source", "role", "evidence"),
    [
        (SOURCE, "vanilla_company_base_candidate_weight", engine_scope.COMPANY_MANIFEST_ID),
        (
            "common/technology/technologies/10_production.txt",
            "vanilla_research_candidate_weight",
            "common/technology/technologies/",
        ),
    ],
)
def test_ai_weight_metadata_is_source_aware(source, role, evidence):
    consumer = decision_interfaces.consumer(("candidate", "ai_weight"), (), source=source)
    assert consumer["role"] == role
    assert consumer["scope_evidence"] == evidence
    assert consumer["root"] == "country"
    assert consumer["placement"] == "after_native_numeric_evaluation"
    assert consumer["eligibility_costs_and_execution"] == "retained_vanilla"


def _adapter_source(
    tmp_path,
    *,
    field="sample.ai_weight",
    operation="multiply",
    value="1.12",
    extra="",
    actor="[]",
    native="sample = { ai_weight = { value = 3 } ai_will_do = { in_default = no } }\n",
):
    digest = hashlib.sha256(normalized_text(native).encode()).hexdigest()
    path = tmp_path / "adapters.toml"
    path.write_text(
        f'''schema = 1
[sources]
"{SOURCE}" = "{digest}"
"common/defines/00_ai.txt" = "{"0" * 64}"
[domains]
market = true
[readers.default]
engine = "in_default"
scope = "root"
unit = "boolean"
kind = "boolean"
[actors]
"{SOURCE}" = {actor}
[[rules]]
id = "company_fixture"
source = "{SOURCE}"
field = "{field}"
domain = "market"
priority = 1
operation = "{operation}"
value = {value}
conditions = [{{ fact = "default", op = "=", value = true }}]
why = "Explicit company score fixture"
counterexample = "Native gate and tail remain authoritative"
{extra}
''',
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_exact_company_score_adapter_loads_without_granting_other_fields(tmp_path):
    policy = dict(decision_adapters.load(_adapter_source(tmp_path)).policies)[SOURCE]
    assert policy.actor_path == ()
    assert len(policy.rules) == 1
    assert (policy.rules[0].field, policy.rules[0].operation) == (
        ("sample", "ai_weight"),
        "multiply",
    )


@pytest.mark.parametrize(
    "field",
    [
        "sample.ai_will_do",
        "sample.ai_construction_targets",
        "sample.ai_construction_targets.building_iron_mine.weight",
        "sample.ai_weight.value",
        "ai_weight",
        "sample.charter.ai_weight",
    ],
)
def test_company_adapter_rejects_eligibility_construction_and_nested_score_fields(tmp_path, field):
    with pytest.raises(ValueError, match="公司适配"):
        decision_adapters.load(_adapter_source(tmp_path, field=field))


@pytest.mark.parametrize("operation", ["add", "set"])
def test_company_score_does_not_accept_non_multiplicative_writes(tmp_path, operation):
    with pytest.raises(ValueError, match="公司适配"):
        decision_adapters.load(_adapter_source(tmp_path, operation=operation))


@pytest.mark.parametrize("value", ["0", "-0.1", "nan", "inf"])
def test_company_score_never_accepts_nonpositive_or_nonfinite_multiplier(tmp_path, value):
    with pytest.raises(ValueError):
        decision_adapters.load(_adapter_source(tmp_path, value=value))


@pytest.mark.parametrize("actor", ['["owner"]', '["target_country"]', '["company"]'])
def test_company_score_cannot_read_from_an_unproven_actor_path(tmp_path, actor):
    with pytest.raises(ValueError, match="AI 所有者"):
        decision_adapters.load(_adapter_source(tmp_path, actor=actor))


def test_building_initializer_cannot_be_reused_to_invent_a_company_default(tmp_path):
    extra = f'''[[initial_values]]
source = "{SOURCE}"
field = "sample.ai_weight"
define_source = "common/defines/00_ai.txt"
define = "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT"
'''
    with pytest.raises(ValueError, match="缺省评分"):
        decision_adapters.load(_adapter_source(tmp_path, extra=extra))


def test_building_scalar_wrapper_cannot_be_reused_for_company_scores(tmp_path):
    extra = f'''[[scalar_values]]
source = "{SOURCE}"
field = "sample.ai_weight"
'''
    with pytest.raises(ValueError, match="常量评分"):
        decision_adapters.load(_adapter_source(tmp_path, extra=extra))


def test_missing_explicit_native_score_cannot_be_initialized_implicitly(tmp_path):
    native = "sample = { ai_will_do = { in_default = no } }\n"
    adapters = decision_adapters.load(_adapter_source(tmp_path, native=native))
    selected = replace(adapters, sources=tuple(row for row in adapters.sources if row[0] == SOURCE))
    with pytest.raises(ValueError):
        decision_adapters.build(selected, texts={SOURCE: native})
