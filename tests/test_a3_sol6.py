"""Bread riots: real two-option effects, independent arithmetic and PDX witnesses."""

from __future__ import annotations

import hashlib
import itertools
import math
from dataclasses import replace

import pytest

from pdx import event_opportunities as event
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import programs


@pytest.fixture(scope="module")
def production():
    inputs = event.frozen_inputs()
    plans = event.compile_programs()
    outputs = event.patch(inputs, consumer_programs=plans)
    root = parse_text(outputs[event.SOL]).root
    parent = next(row.value for row in root.assignments() if row.key == "sol_events.6")
    assert isinstance(parent, Block)
    options = {
        next(
            row.value.unquoted
            for row in option.value.assignments()
            if row.key == "name" and isinstance(row.value, Scalar)
        ): option.value
        for option in parent.assignments()
        if option.key == "option" and isinstance(option.value, Block)
    }
    return inputs, plans, outputs, options


def _observations(population=99999, default=False, *, exists=True, owned=True):
    return {
        "sol_response_state_exists": exists,
        "sol_response_state_owned": owned,
        "sol_response_state_population": population,
        "sol_response_default": default,
    }


def _reference(values):
    """Independent declared policy; never use production guards or scalar IR."""
    population = values.get("sol_response_state_population")
    valid = False
    try:
        valid = (
            values.get("sol_response_state_exists") is True
            and values.get("sol_response_state_owned") is True
            and type(population) in {int, float}
            and math.isfinite(population)
            and population >= 1
        )
    except OverflowError:
        valid = False
    welfare = 18 + (6 if population >= 100000 else 0) if valid else 0
    avoided_radicals = 6 if valid else 0
    financing = 12 if values.get("sol_response_default") is False else 32
    difference = welfare + avoided_radicals - financing
    return {"sol_events.6.a": 50.0 + difference, "sol_events.6.b": 50.0 - difference}


def _trigger(block, values, *, is_ai, state=False):
    """Interpret the emitted trigger AST against independently typed getter inputs."""
    for row in block.assignments():
        if row.key == "scope:slums_state":
            assert isinstance(row.value, Block)
            if values.get("sol_response_state_exists") is not True or not _trigger(
                row.value, values, is_ai=is_ai, state=True
            ):
                return False
            continue
        assert isinstance(row.value, Scalar)
        operand = row.value.unquoted
        if row.key == "is_ai":
            assert row.op == "="
            assert operand == "yes"
            if is_ai is not True:
                return False
        elif row.key == "exists":
            assert row.op == "="
            assert operand == "scope:slums_state"
            assert not state
            if values.get("sol_response_state_exists") is not True:
                return False
        elif row.key == "owner":
            assert row.op == "="
            assert operand == "root"
            assert state
            if values.get("sol_response_state_owned") is not True:
                return False
        elif row.key == "state_population":
            assert row.op == ">="
            assert state
            population = values.get("sol_response_state_population")
            if type(population) not in {int, float}:
                return False
            try:
                if not math.isfinite(population) or population < float(operand):
                    return False
            except OverflowError:
                return False
        elif row.key == "in_default":
            assert row.op == "="
            assert operand == "no"
            assert not state
            if values.get("sol_response_default") is not False:
                return False
        else:
            pytest.fail(f"Unexpected generated trigger: {row.key}")
    return True


def _generated_weight(option, values, *, is_ai=True):
    chance = option.all("ai_chance")
    assert len(chance) == 1
    assert isinstance(chance[0].value, Block)
    chance = chance[0].value
    assert len(chance.all("base")) == 1
    base = chance.all("base")[0].value
    assert isinstance(base, Scalar)
    total = float(base.unquoted)
    for row in chance.assignments():
        if row.key == "base":
            continue
        assert row.key == "modifier"
        assert isinstance(row.value, Block)
        modifier = row.value
        assert [part.key for part in modifier.assignments()] == ["trigger", "add"]
        addition = modifier.all("add")[0].value
        assert isinstance(addition, Scalar)
        if _trigger(modifier.all("trigger")[0].value, values, is_ai=is_ai):
            total += float(addition.unquoted)
    return total


@pytest.mark.parametrize(
    ("population", "default", "expected"),
    [
        (99999, False, (62, 38)),
        (99999, True, (42, 58)),
        (100000, False, (68, 32)),
        (100000, None, (48, 52)),
        (1, None, (42, 58)),
    ],
)
def test_finance_and_exact_exposure_change_the_real_pair(production, population, default, expected):
    _, plans, _, options = production
    values = _observations(population, default)
    reference = _reference(values)
    assert tuple(reference.values()) == expected
    for plan in plans[-2:]:
        assert plan.evaluate(values, is_ai=True) == reference[plan.option]
        assert _generated_weight(options[plan.option], values) == reference[plan.option]


@pytest.mark.parametrize("projection", ["reference", "generated_pdx"])
@pytest.mark.parametrize("default", [None, True, False])
@pytest.mark.parametrize(
    "missing_state_fact",
    [
        {"sol_response_state_exists": None},
        {"sol_response_state_exists": False},
        {"sol_response_state_owned": None},
        {"sol_response_state_owned": False},
        {"sol_response_state_population": None},
        {"sol_response_state_population": float("nan")},
        {"sol_response_state_population": True},
    ],
)
def test_missing_state_benefit_preserves_independent_country_expense(
    production, projection, default, missing_state_fact
):
    _, plans, _, options = production
    values = {**_observations(default=default), **missing_state_fact}
    # Native a unconditionally charges ROOT, independently of its saved state.
    expected = (38, 62) if default is False else (18, 82)
    actual = tuple(
        plan.evaluate(values, is_ai=True)
        if projection == "reference"
        else _generated_weight(options[plan.option], values)
        for plan in plans[-2:]
    )
    assert actual == expected


def test_independent_boundary_unknown_matrix_equals_actual_generated_ast(production):
    _, plans, _, options = production
    populations = [
        None,
        True,
        False,
        -1,
        0,
        0.999,
        1,
        99999,
        100000,
        100001,
        float("nan"),
        float("inf"),
        -float("inf"),
        "100000",
        10**400,
    ]
    seen = []
    for population, default, exists, owned in itertools.product(
        populations, [None, False, True], [None, False, True], [None, False, True]
    ):
        values = _observations(population, default, exists=exists, owned=owned)
        reference = _reference(values)
        for plan in plans[-2:]:
            actual = plan.evaluate(values, is_ai=True)
            assert actual == reference[plan.option]
            assert _generated_weight(options[plan.option], values) == reference[plan.option]
            seen.append(actual)
        assert sum(reference.values()) == 100
    assert (min(seen), max(seen)) == (18, 82)


def test_independent_causes_keep_welfare_and_radicals_when_finance_reverses(production):
    _, plans, _, _ = production
    plan = plans[-2]
    assert len(plan.scalar.groups) == 3
    assert len({group.id for group in plan.scalar.groups}) == 3
    assert [float(group.terms[0].amount) for group in plan.scalar.groups] == [18, 6, -32]
    assert [
        float(group.terms[0].effects[0].amount)
        for group in plan.scalar.groups
        if group.terms[0].effects
    ] == [6, 20]
    low = plan.evaluate(_observations(), is_ai=True)
    # Removing either independently valued native benefit must affect the output.
    for index, benefit in [(0, 18), (1, 6)]:
        scalar = replace(
            plan.scalar, groups=tuple(g for i, g in enumerate(plan.scalar.groups) if i != index)
        )
        altered = replace(plan, scalar=scalar)
        assert altered.evaluate(_observations(), is_ai=True) == low - benefit
    assert plan.evaluate(_observations(default=True), is_ai=True) == low - 20


def test_exact_saved_scope_isolated_from_unrelated_health_and_country(production):
    _, plans, _, options = production
    values = _observations()
    baseline = _reference(values)
    values.update(
        {
            "other_state_population": 90000000,
            "state_mortality": 999,
            "plague_infected": True,
            "average_sol": 2,
            "country_tag": "GBR",
        }
    )
    assert _reference(values) == baseline
    for plan in plans[-2:]:
        assert plan.evaluate(values, is_ai=True) == baseline[plan.option]
        assert _generated_weight(options[plan.option], values) == baseline[plan.option]


@pytest.mark.parametrize("is_ai", [False, None])
def test_player_or_unknown_ai_emits_no_policy(production, is_ai):
    _, plans, _, options = production
    assert event.evaluate(_observations(), is_ai=is_ai, consumer_programs=plans[-2:]) == {}
    assert all(
        _generated_weight(option, _observations(), is_ai=is_ai) == 0 for option in options.values()
    )


def test_domain_and_family_disabled_restore_complete_native_source(production):
    inputs, plans, outputs, _ = production
    assert event.patch(inputs, enabled_domains=frozenset(), consumer_programs=plans) == {}
    disabled = event.patch(
        inputs, enabled_families=event.FAMILIES - {"sol_response"}, consumer_programs=plans
    )
    assert event.SOL not in disabled
    assert {**inputs, **disabled}[event.SOL] == inputs[event.SOL]
    assert disabled == {source: text for source, text in outputs.items() if source != event.SOL}
    assert (
        event.evaluate(
            _observations(), is_ai=True, enabled_families=event.FAMILIES - {"sol_response"}
        )
        .keys()
        .isdisjoint(event.SOL_OPTIONS)
    )
    with pytest.raises(ValueError, match="family"):
        event.patch(inputs, enabled_families=frozenset({"invented"}))


def test_every_overlay_removal_restores_native_and_exact_player_effects(production):
    inputs, plans, outputs, options = production
    restored = dict(outputs)
    for plan in plans:
        overlay = event.render(plan)
        assert restored[plan.source].count(overlay) == 1
        restored[plan.source] = restored[plan.source].replace(overlay, "", 1)
    assert restored == {source: inputs[source] for source in outputs}
    native = event._options(event._block(parse_text(inputs[event.SOL]).root, "sol_events.6"))
    for name, option in options.items():
        preserved = Block(
            [
                row
                for row in option.items
                if not isinstance(row, Assignment) or row.key != "ai_chance"
            ]
        )
        assert event._shape(preserved) == event._shape(native[name])
    assert event._shape(event._block(options["sol_events.6.a"], "add_modifier")) == (
        ("name", "=", "starvation_palliative_modifier"),
        ("multiplier", "=", "money_amount_multiplier_small"),
        ("days", "=", "normal_modifier_time"),
    )
    radical = event._block(
        event._block(options["sol_events.6.b"], "scope:slums_state"), "add_radicals_in_state"
    )
    assert event._shape(radical) == (("strata", "=", "lower"), ("value", "=", "medium_radicals"))


def test_exact_source_context_and_legacy_contracts(production):
    inputs, plans, _, _ = production
    assert len(plans) == 23
    assert len(event.LEGACY_SOURCES) == 15
    assert len(event.SOL_SOURCES) == 9
    assert len(inputs) == 20
    legacy_inputs = {name: inputs[name] for name in event.LEGACY_SOURCES}
    query = event.PlagueStateQuery("infected")
    assert set(event.required_query_sources(query)) == event.LEGACY_SOURCES
    assert len(event.compile_query(query, legacy_inputs).source_hashes) == 15
    for plan in plans[:21]:
        assert set(plan.as_dict()["source_hashes"]) == event.LEGACY_SOURCES
    for plan in plans[-2:]:
        assert set(plan.as_dict()["source_hashes"]) == event.SOL_SOURCES
        assert plan.identity.saved_state == "slums_state"
        assert plan.writer_id == "event_sol_response_" + plan.option[-1]
        context = plan.evaluation_context()
        assert context.actor_scope.kind == "country"
        assert context.actor_scope.source == event.SOL_JOURNAL_GROUP
        assert context.auxiliary_scopes[0].source == event.SOL
        assert {r.engine for r in plan.readers()} == {
            "exists",
            "owner",
            "state_population",
            "in_default",
        }
        assert [row[2:] for row in plan.reader_bindings()] == [
            ("country", "actor"),
            ("state", "auxiliary"),
            ("state", "auxiliary"),
            ("country", "actor"),
        ]
    event.verify_sol_inputs({name: inputs[name] for name in event.SOL_SOURCES})


@pytest.mark.parametrize("source", sorted(event.SOL_SOURCES))
def test_full_native_source_hash_drift_is_rejected(production, source):
    inputs, _, _, _ = production
    altered = dict(inputs)
    altered[source] += "\n# drift\n"
    with pytest.raises(ValueError, match="来源漂移"):
        event.verify_inputs(altered)


@pytest.mark.parametrize(
    "mutation", ["effect", "option_name", "duplicate_weight", "random", "cooldown", "sibling"]
)
def test_rehashing_source_cannot_authorize_native_parent_mutation(
    production, monkeypatch, mutation
):
    inputs, _, _, _ = production
    altered = dict(inputs)
    source = event.SOL
    text = altered[source]
    start = text.index("sol_events.6 = {")
    prefix, parent = text[:start], text[start:]
    changes = {
        "effect": ("value = medium_radicals", "value = small_radicals"),
        "option_name": ("name = sol_events.6.a", "name = sol_events.6.b"),
        "duplicate_weight": (
            "name = sol_events.6.a",
            "name = sol_events.6.a ai_chance = { base = 1 } ai_chance = { base = 2 }",
        ),
        "random": ("is_capital = yes", "is_capital = no"),
        "cooldown": ("days = normal_modifier_time", "days = short_modifier_time"),
        "sibling": ("name = sol_events.6.b", "name = sol_events.6.c"),
    }
    old, new = changes[mutation]
    assert old in parent
    altered[source] = prefix + parent.replace(old, new, 1)
    settings = event.load()
    settings["sources"][source] = hashlib.sha256(altered[source].encode()).hexdigest()
    monkeypatch.setattr(event, "load", lambda: settings)
    with pytest.raises(ValueError, match="完整父事件AST漂移"):
        event.verify_sol_inputs(altered)


def test_pair_is_atomic_and_renderer_proves_conservative_interval(production):
    inputs, plans, _, _ = production
    for selected in [
        plans[:-1],
        (*plans, plans[-1]),
        (*plans[:-1], replace(plans[-1], option="sol_events.6.a")),
    ]:
        with pytest.raises(ValueError, match="集合"):
            event.patch(inputs, consumer_programs=selected)
    for plan in plans[-2:]:
        assert isinstance(plan.scalar, programs.ScalarProgram)
        assert (plan.scalar.lower, plan.scalar.upper) == (12, 88)
        event.render(plan)
        # The shared state core correlates benefit terms; the renderer must
        # still reject each option's narrower reachable-only interval.
        lower, upper = (18, 68) if plan.option.endswith(".a") else (32, 82)
        narrowed = replace(plan, scalar=replace(plan.scalar, lower=lower, upper=upper))
        with pytest.raises(ValueError, match="最终限幅"):
            event.render(narrowed)
