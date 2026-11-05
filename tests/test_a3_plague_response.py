"""Intentional complete plague policy, independently executed from actual AIWeight AST."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from pdx import config, observation_queries
from pdx import event_opportunities as event
from pdx.lexer import tokenize
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval
from pdx.textio import normalized_text

pytestmark = pytest.mark.unit
MODIFIERS = ("plague_modifier", "plague_lockdown_mod", "plague_measures_mod")


def _block(parent, key):
    rows = parent.all(key)
    assert len(rows) == 1
    assert isinstance(rows[0].value, Block)
    return rows[0].value


def _options(text):
    parent = _block(parse_text(text).root, event.PLAGUE_EVENT)
    return {row.value.first("name").value.unquoted: row.value for row in parent.all("option")}


def _weight(block, facts):
    base = block.first("base")
    assert base is not None
    assert isinstance(base.value, Scalar)
    weight = float(base.value.unquoted)
    for row in block.assignments():
        if row.key == "base":
            continue
        assert row.key == "modifier"
        assert isinstance(row.value, Block)
        amount = row.value.first("add")
        assert amount is not None
        assert isinstance(amount.value, Scalar)
        if pdx_eval.condition(_block(row.value, "trigger"), facts) is True:
            weight += float(amount.value.unquoted)
    return weight


def _state(*, infected=True, lockdown=False, measures=False):
    return {
        "has_modifier": {
            (("argument", modifier),): value
            for modifier, value in zip(MODIFIERS, (infected, lockdown, measures), strict=True)
        }
    }


def _observed_any(states, modifiers):
    """Handwritten three-valued existential; independent of rendered queries."""
    if states is None:
        return None
    unknown = False
    for state in states:
        seen = [
            state.get("has_modifier", {}).get((("argument", modifier),)) for modifier in modifiers
        ]
        if any(value is True for value in seen):
            return True
        unknown |= any(value is None for value in seen)
    return None if unknown else False


def _facts(*, states=None, lockdown=False, measures=False, default=False, ai=True):
    return {
        "is_ai": ai,
        "any_scope_state": states,
        "in_default": default,
        "has_variable": {
            (("argument", "plague_lockdown"),): lockdown,
            (("argument", "plague_measures"),): measures,
        },
    }


@pytest.fixture(scope="module")
def production():
    inputs = event.frozen_inputs()
    plans = tuple(plan for plan in event.compile_programs() if plan.option in event.PLAGUE_OPTIONS)
    generated = event.patch(inputs)
    return inputs, plans, generated, _options(generated[event.PLAGUE])


CASES = [
    ({"states": [_state()]}, (58, 56, 36)),
    ({"states": [_state()], "default": True}, (46, 50, 36)),
    ({"states": [_state()], "default": None}, (46, 50, 36)),
    ({"states": [_state(infected=False)]}, (50, 50, 50)),
    ({"states": None}, (50, 50, 50)),
    ({"states": []}, (50, 50, 50)),
    ({"states": [_state(lockdown=True)], "lockdown": True}, (62, 56, 44)),
    ({"states": [_state(measures=True)], "measures": True}, (58, 60, 40)),
    (
        {"states": [_state(lockdown=True, measures=True)], "lockdown": True, "measures": True},
        (62, 60, 44),
    ),
    ({"states": [_state(infected=False, lockdown=True)], "lockdown": True}, (50, 50, 64)),
    ({"states": [_state(infected=False, measures=True)], "measures": True}, (50, 50, 60)),
    ({"states": [], "lockdown": True, "measures": True}, (50, 50, 56)),
    ({"states": [_state(infected=None, lockdown=True)], "lockdown": True}, (50, 50, 58)),
    ({"states": [_state()], "lockdown": None, "measures": None}, (58, 56, 36)),
    ({"states": [{}, _state()]}, (58, 56, 36)),
    ({"states": [{}], "lockdown": True}, (50, 50, 50)),
]


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_all_three_handwritten_tradeoffs_match_shared_program_and_actual_native_ast(
    production, changes, expected
):
    _, plans, _, options = production
    facts = _facts(**changes)
    values = {
        "plague_infected": _observed_any(facts["any_scope_state"], (MODIFIERS[0],)),
        "plague_restricted": _observed_any(facts["any_scope_state"], MODIFIERS[1:]),
        "plague_lockdown": _observed_any(facts["any_scope_state"], (MODIFIERS[1],)),
        "plague_response_lockdown": changes.get("lockdown", False),
        "plague_response_measures": changes.get("measures", False),
        "plague_default": changes.get("default", False),
    }
    reference = event.evaluate(values, is_ai=True, consumer_programs=plans)
    for option, wanted in zip(event.PLAGUE_OPTIONS, expected, strict=True):
        assert reference[option] == wanted
        actual = _weight(_block(options[option], "ai_chance"), facts)
        assert actual == wanted
        assert 0 < actual < 100  # No epidemic state can remove an original option.


def test_new_policy_is_explicit_and_does_not_claim_unknown_native_default_equivalence(production):
    inputs, plans, _, options = production
    native = _options(inputs[event.PLAGUE])
    assert tuple(native) == event.PLAGUE_OPTIONS
    assert all(not option.all("ai_chance") for option in native.values())
    assert all(plan.scalar.neutral == 50 for plan in plans)
    for name in event.PLAGUE_OPTIONS:
        chance = _block(options[name], "ai_chance")
        assert chance.first("base").value.unquoted == "0"
        base_policy = chance.all("modifier")[0].value
        assert base_policy.first("add").value.unquoted == "50"
        assert _block(base_policy, "trigger").first("is_ai").value.unquoted == "yes"
        metadata = event.consumer_catalog()[name]
        assert "unknown" in metadata["default_weight"]
        assert "new_explicit" in metadata["placement"]
        assert metadata["target_scope"] == "none"


def test_player_and_disabled_preserve_original_option_paths_and_effects(production):
    inputs, plans, _, options = production
    facts = _facts(states=[_state(lockdown=True)], lockdown=True, default=True, ai=False)
    assert all(
        _weight(_block(options[name], "ai_chance"), facts) == 0 for name in event.PLAGUE_OPTIONS
    )
    assert all(plan.evaluate({}, is_ai=False) == 0 for plan in plans)
    assert event.evaluate({}, is_ai=False) == {}
    assert event.patch(inputs, enabled_domains=frozenset()) == {}
    assert event.evaluate({}, is_ai=True, enabled_domains=frozenset()) == {}
    # A player never consumes AIWeight. Unknown omitted native numeric weight is
    # deliberately not asserted to equal the new policy's zero contribution.


def test_full_original_text_and_all_random_effects_and_scope_writes_are_byte_preserved(production):
    inputs, _, generated, _ = production
    for source, text in generated.items():
        restored = text
        for plan in event.compile_programs():
            if plan.source == source:
                assert restored.count(event.render(plan)) == 1
                restored = restored.replace(event.render(plan), "")
        assert restored == inputs[source]
        assert [(t.kind, t.value) for t in tokenize(restored)] == [
            (t.kind, t.value) for t in tokenize(inputs[source])
        ]
    # Country flags can coexist: native counterpart removals remain in state scope.
    native = _options(inputs[event.PLAGUE])
    for name in event.PLAGUE_OPTIONS[:2]:
        assert not native[name].all("remove_variable")
        assert _block(native[name], "every_scope_state").all("if")
    assert native[event.PLAGUE_OPTIONS[1]].first("default_option").value.unquoted == "yes"


def test_foreign_state_and_response_decoys_do_not_supply_local_observations(production):
    _, _, _, options = production
    facts = _facts(states=[], default=False)
    facts["scope:target_country"] = _facts(states=[_state(lockdown=True)], lockdown=True)
    facts["owner"] = _facts(states=[_state()], measures=True)
    facts["plague_infected"] = True
    assert [
        _weight(_block(options[name], "ai_chance"), facts) for name in event.PLAGUE_OPTIONS
    ] == [50, 50, 50]


def test_recovery_and_later_outbreak_recompute_from_same_program_without_sticky_state(production):
    _, _, _, options = production
    sequence = [
        (_facts(states=[_state()], default=False), (58, 56, 36)),
        (_facts(states=[_state(lockdown=True)], lockdown=True), (62, 56, 44)),
        (_facts(states=[_state(infected=False, lockdown=True)], lockdown=True), (50, 50, 64)),
        (_facts(states=[], lockdown=False), (50, 50, 50)),
        (_facts(states=[_state()], default=True), (46, 50, 36)),
    ]
    for facts, expected in sequence:
        actual = tuple(
            _weight(_block(options[name], "ai_chance"), facts) for name in event.PLAGUE_OPTIONS
        )
        assert actual == expected


def test_normal_low_debt_borrowing_is_not_a_global_health_action_prohibition(production):
    options = production[3]
    facts = _facts(states=[_state()], default=False)
    facts.update(is_borrowing=True, debt_ratio=0.1, bankruptcy_horizon=52, average_sol=5)
    assert tuple(
        _weight(_block(options[name], "ai_chance"), facts) for name in event.PLAGUE_OPTIONS
    ) == (58, 56, 36)


@pytest.mark.parametrize("source", sorted(event.load()["sources"]))
def test_complete_source_drift_fails_even_if_unrelated_event_text_changes(production, source):
    inputs = production[0]
    with pytest.raises(ValueError, match="来源漂移"):
        event.patch({**inputs, source: inputs[source] + "\n# drift\n"})


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (
            event.PLAGUE_MODIFIERS,
            "building_throughput_add = -0.5",
            "building_throughput_add = -0.05",
        ),
        (event.PLAGUE_DECISION, "days = 182", "days = 1"),
        (event.PLAGUE_EFFECTS, "add = -3", "add = 3"),
        (event.PLAGUE, "default_option = yes", "default_option = no"),
        (event.FINANCE, "in_default = no", "in_default = yes"),
    ],
)
def test_semantic_direction_cost_cooldown_and_default_cannot_be_silently_repinned(
    production, monkeypatch, source, old, new
):
    inputs = dict(production[0])
    assert old in inputs[source]
    inputs[source] = inputs[source].replace(old, new)
    data = deepcopy(event.load())
    data["sources"][source] = hashlib.sha256(inputs[source].encode()).hexdigest()
    monkeypatch.setattr(event, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        event.verify_inputs(inputs)


def test_fixed_query_readers_contexts_and_current_installation_proof(production):
    inputs, plans, _, _ = production
    assert inputs == {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in inputs
    }
    frozen = json.loads(event.FROZEN.read_text(encoding="utf-8"))
    assert frozen["raw_source_hashes"] == {
        source: hashlib.sha256((config.GAME / source).read_bytes()).hexdigest() for source in inputs
    }
    for mode in ("infected", "restricted", "lockdown"):
        query = observation_queries.from_reader("any_scope_state", {event.QUERY_PARAMETER: mode})
        assert isinstance(query, event.PlagueStateQuery)
        compiled = observation_queries.compile_query(query, inputs)
        assert compiled.expression == event.render_query(query)
        assert compiled.local_collections == ("owned_states",)
        assert compiled.world_scans == 0
        assert dict(compiled.source_hashes) == {
            source: hashlib.sha256(inputs[source].encode()).hexdigest()
            for source in event.LEGACY_SOURCES
        }
        # SOL's later evidence does not expand the older epidemic query's
        # permissions or make its fifteen-source contract depend on that family.
        legacy = {source: inputs[source] for source in event.LEGACY_SOURCES}
        assert observation_queries.compile_query(query, legacy) == compiled
    for plan in plans:
        assert plan.evaluation_context().auxiliary_scopes == ()
        assert len(plan.readers()) == 6
        assert all(row[1:] == ("root", "country", "actor") for row in plan.reader_bindings())
        assert plan.writer_ir().validate_event_program() == plan


def test_production_instances_expose_their_own_event_facts():
    from pdx import decision_adapters, decision_rules
    from pdx.situated import action_instances

    adapters = decision_adapters.load()
    instances = action_instances.build(decision_rules.load(), adapters)
    actual = {row.rule_id: row for row in instances if row.kind == "event_program"}
    assert set(actual) == {program.option for program in adapters.event_programs}
    for program in adapters.event_programs:
        instance = actual[program.option]
        assert instance.condition_facts == tuple(reader.key for reader in program.readers())
        assert instance.evaluation_context == program.evaluation_context()
    assert "plague_infected" in actual[event.PLAGUE_OPTIONS[0]].condition_facts
    assert "opponent_clout" not in actual[event.PLAGUE_OPTIONS[0]].condition_facts


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("any_country", {event.QUERY_PARAMETER: "infected"}),
        ("any_scope_state", {event.QUERY_PARAMETER: "country_infected"}),
        ("any_scope_state", {event.QUERY_PARAMETER: "infected", "modifier": "foreign_modifier"}),
    ],
)
def test_queries_reject_foreign_collections_free_modifier_or_wrong_mode(engine, parameters):
    with pytest.raises(ValueError):
        observation_queries.from_reader(engine, parameters)


def test_complete_policy_set_and_linear_bounds_hard_fail_if_missing_or_binding_clamp(production):
    inputs, plans, _, _ = production
    with pytest.raises(ValueError, match="集合"):
        event.patch(inputs, consumer_programs=event.compile_programs()[:-1])
    with pytest.raises(ValueError, match="最终限幅"):
        event.render(replace(plans[0], scalar=replace(plans[0].scalar, lower=49, upper=51)))
