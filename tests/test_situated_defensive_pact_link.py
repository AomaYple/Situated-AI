"""LJ10 本国条款计数与净流量压力：手写预期、完整消费者 PDX。"""

import hashlib
from dataclasses import replace

import pytest
from _frozen_reader_words import frozen_reader_words

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.situated import compiler, joint_chain_contract, pdx_eval

pytestmark = pytest.mark.unit
INFO = "mod/decisions/information.toml"
FIELD = "wanted_army_size"
RULE = "lj10_defensive_pact_flow_pressure"
PROGRAM = "program_" + hashlib.sha256(f"{INFO}:{FIELD}".encode()).hexdigest()[:16]


def test_pact_reader_is_an_exact_local_country_signature():
    reader = decision_rules.Reader(
        "defensive_pact_articles",
        "num_defensive_pacts",
        "root",
        "treaty_article_count",
        "number",
        minimum=0,
    )
    assert decision_interfaces.reader_scope(reader, ()) == "country"


def test_pact_signal_is_really_wired_to_army_consumer():
    policy = decision_rules.load()
    rule = next((row for row in policy.rules if row.id == RULE), None)
    assert rule is not None
    assert rule.field == (FIELD,)
    assert rule.value == 0.95


@pytest.mark.parametrize(
    "engine",
    ["num_defensive_pacts", "wanted_army_size_script_value", "wanted_marines_size_script_value"],
)
@pytest.mark.parametrize(
    "change",
    [
        {"scope": "target_country"},
        {"path": ("owner",)},
        {"argument": "c:RUS"},
        {"parameters": (("country", "c:RUS"),)},
        {"value_field": "value"},
        {"maximum": 100},
        {"kind": "boolean"},
        {"unit": "currency"},
    ],
)
def test_reader_rejects_unproven_signature_changes(engine, change):
    reader = next(row for row in decision_rules.load().readers if row.engine == engine)
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(replace(reader, **change), ())


@pytest.mark.parametrize(
    "engine",
    ["num_defensive_pacts", "wanted_army_size_script_value", "wanted_marines_size_script_value"],
)
def test_reader_rejects_state_actor_and_changed_minimum(engine):
    reader = next(row for row in decision_rules.load().readers if row.engine == engine)
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(reader, ("owner",))
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(replace(reader, minimum=1), ())


def test_pinned_reader_manifest_is_checked_before_returning_words(monkeypatch, tmp_path):
    # This mutation targets the historical artifact explicitly; the independent
    # current manifest has its own corruption tests in test_engine_reader_115.
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.14.5")
    assert decision_interfaces.proven_reader_words() == frozenset(
        {
            "num_defensive_pacts",
            "wanted_army_size_script_value",
            "wanted_marines_size_script_value",
        }
    )
    path = tmp_path / "evidence.json"
    path.write_bytes(decision_interfaces._LJ10_EVIDENCE.read_bytes() + b" ")
    monkeypatch.setattr(decision_interfaces, "_LJ10_EVIDENCE", path)
    with pytest.raises(ValueError, match="冻结证据字节漂移"):
        decision_interfaces.proven_reader_words()


def _values(**changes):
    return {
        "war": False,
        "default": False,
        "net_surplus": -1,
        "defensive_pact_articles": 1,
        "army": 50,
        "infamy": 0,
        "gdp": 1,
        "bureaucracy": 0,
        "native_army_capacity": 101,
        "native_marine_capacity": 1,
        **changes,
    }


@pytest.fixture(scope="module")
def generated():
    original = decision_rules.load()
    rules = tuple(row for row in original.rules if row.field == (FIELD,))
    keys = {key for row in rules for key in row.input_keys()}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(row for row in original.readers if row.key in keys),
        enabled_domains=frozenset(row.domain for row in rules),
        semantic_ir=(),
    )
    model = compiler.load_model()
    assert model.consumer_ir is not None
    compiled = compiler.compile_policy(policy, INFO, model)[0]
    native = compiler.baseline_path().read_text(encoding="utf-8")
    text = decision_rules.patch(
        native,
        compiled,
        baseline=native,
        # The three LJ10 readers are proven by the pinned research manifest;
        # adapters intentionally do not own this local evidence source.
        reader_words=frozen_reader_words(native),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    return compiled, pdx_eval.marked_block(text, PROGRAM), model


def _facts(values, *, is_ai=True):
    policy = decision_rules.load()
    root = {"is_ai": is_ai}
    for reader in policy.readers:
        if reader.key not in values:
            continue
        value = values[reader.key]
        if not reader.path and not reader.argument and not reader.parameters:
            root[reader.engine] = value
    return {"ROOT": root}


CASES = [
    ("positive", {}, 0.95),
    ("broken_link", {"defensive_pact_articles": 0}, None),
    ("cost_pressure_relief", {"net_surplus": 0}, None),
    ("positive_flow", {"net_surplus": 0.00001}, None),
    ("flow_boundary_below", {"net_surplus": -0.00001}, 0.95),
    ("more_pressure", {"net_surplus": -1000}, 0.95),
    ("more_articles_not_stack", {"defensive_pact_articles": 100}, 0.95),
    ("zero_native_target", {"native_army_capacity": 1, "native_marine_capacity": 1}, None),
    ("negative_native_target", {"native_army_capacity": 1, "native_marine_capacity": 2}, None),
    (
        "positive_native_boundary",
        {"native_army_capacity": 1.00001, "native_marine_capacity": 1},
        0.95,
    ),
    # Observed war now proves the base demand despite this fixture's negative
    # flow and zero administrative balance: 1 + .08 = 1.08.
    ("wartime_defense", {"war": True}, 1.08),
    ("default_recovery", {"default": True}, 0.85),
    ("peace_capacity_has_no_war_demand", {"net_surplus": 1, "bureaucracy": 1}, None),
    (
        "defense_capacity",
        {"war": True, "net_surplus": 1, "bureaucracy": 1},
        1.2,
    ),
    # Independent opposite directions: 1 + (1.10 - 1) + (0.95 - 1) = 1.05.
    ("explicit_threat", {"army": 49, "infamy": 26}, 1.05),
    ("borrowed_not_default", {"loans": True}, 0.95),
    ("low_literacy_unrelated", {"literacy": 0.01}, 0.95),
    (
        "selected_pact_not_relationship",
        {"defensive_pact_articles": 0, "candidate_selected": True},
        None,
    ),
    (
        "selected_pact_not_observation",
        {"defensive_pact_articles": None, "candidate_selected": True},
        None,
    ),
]


@pytest.mark.parametrize(("case", "changes", "expected"), CASES, ids=[row[0] for row in CASES])
def test_complete_army_chain_reference_and_actual_pdx(generated, case, changes, expected):
    policy, overlay, _ = generated
    values = _values(**changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(FIELD)
    actual = pdx_eval.select(overlay, _facts(values))
    if expected is None:
        assert reference is None, case
    else:
        assert reference is not None, case
        assert reference[0] == PROGRAM, case
        assert reference[1] == pytest.approx(expected), case
    factor = actual.delta if actual.operation == "multiply" else 1
    assert factor == pytest.approx(expected or 1), case
    if expected:
        assert actual.action_id == PROGRAM
    assert factor > 0
    assert 0 * factor == 0
    native_target = values["native_army_capacity"] - values["native_marine_capacity"]
    if native_target <= 0:
        assert native_target * factor == native_target


@pytest.mark.parametrize(
    "key",
    [
        "war",
        "default",
        "net_surplus",
        "defensive_pact_articles",
        "native_army_capacity",
        "native_marine_capacity",
    ],
)
@pytest.mark.parametrize("unknown", [None, float("nan"), float("inf"), "invalid"])
def test_every_core_unknown_is_local_native_fallback(generated, key, unknown):
    policy, overlay, _ = generated
    values = _values(**{key: unknown})
    assert decision_rules.evaluate(policy, values, is_ai=True).get(FIELD) is None
    actual = pdx_eval.select(overlay, _facts(values))
    assert actual.operation is None or (actual.operation == "multiply" and actual.delta == 1)


@pytest.mark.parametrize("unknown", [None, float("nan"), float("inf"), "invalid"])
def test_unknown_pact_does_not_erase_known_threat(generated, unknown):
    policy, overlay, _ = generated
    values = _values(army=49, infamy=26, defensive_pact_articles=unknown)
    reference = decision_rules.evaluate(policy, values, is_ai=True)[FIELD]
    assert reference[0] == PROGRAM
    assert reference[1] == pytest.approx(1.10)
    actual = pdx_eval.select(overlay, _facts(values))
    assert actual.action_id == PROGRAM
    assert actual.operation == "multiply"
    assert actual.delta == pytest.approx(1.10)


def test_player_disabled_and_foreign_decoys_do_not_create_local_relationship(generated):
    policy, overlay, _ = generated
    values = _values()
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert pdx_eval.select(overlay, _facts(values, is_ai=False)).fallback == "vanilla"
    facts = _facts(_values(defensive_pact_articles=0))
    facts["scope:target_country"] = {"num_defensive_pacts": 10}
    facts["ROOT"]["candidate_selected"] = True
    actual = pdx_eval.select(overlay, facts)
    assert actual.action_id == PROGRAM
    assert actual.operation == "multiply"
    assert actual.delta == 1


def test_lj10_has_exact_production_chain_provenance(generated):
    _, _, model = generated
    assert model.consumer_ir is not None
    policies = {INFO: decision_rules.load(), **dict(decision_adapters.load().policies)}
    rows = joint_chain_contract.build_strict(model.consumer_ir, policies)
    link = next(row for row in rows if row.spec.chain_id == "LJ10")
    assert link.spec.rule_id == RULE
    assert link.spec.status == "observed_static_only"
    assert link.spec.max_hops == 1
    assert "selected" not in link.spec.completion_state
    assert {row.key for row in link.spec.readers} == {
        "war",
        "default",
        "net_surplus",
        "defensive_pact_articles",
        "native_army_capacity",
        "native_marine_capacity",
    }
    joint_chain_contract.validate_links(rows, model.consumer_ir)
    bad_reader = replace(link.spec.readers[-1], scope="target_country")
    bad = replace(link, spec=replace(link.spec, readers=(*link.spec.readers[:-1], bad_reader)))
    with pytest.raises(ValueError, match=r"读取器|来源|漂移"):
        joint_chain_contract.validate_links(tuple(bad if row is link else row for row in rows))


@pytest.mark.parametrize("layer", ["writer", "legacy"])
@pytest.mark.parametrize("attribute", ["key", "expression"])
def test_relative_reference_identity_cannot_drift_between_source_and_writer(
    generated, layer, attribute
):
    _, _, model = generated
    bundle = model.consumer_ir
    policies = ((INFO, decision_rules.load()), *decision_adapters.load().policies)
    writer = next(row for row in bundle.writers if row.definition == RULE)
    predicates = list(writer.predicates if layer == "writer" else writer.legacy.predicates)
    fact, operator, reference = predicates[-1]
    assert isinstance(reference, decision_rules.FactReference)
    predicates[-1] = (fact, operator, replace(reference, **{attribute: "wrong_identity"}))
    altered = (
        replace(writer, predicates=tuple(predicates))
        if layer == "writer"
        else replace(writer, legacy=replace(writer.legacy, predicates=tuple(predicates)))
    )
    damaged = replace(
        bundle, writers=tuple(altered if row is writer else row for row in bundle.writers)
    )
    with pytest.raises(ValueError, match="writer 语义漂移"):
        joint_chain_contract.bind_bundle(damaged, policies)
