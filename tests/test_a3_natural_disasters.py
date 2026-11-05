"""Complete disaster pairs, exact source semantics, independent native AIWeight execution."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from pdx import config, observation_queries
from pdx import event_opportunities as event
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval
from pdx.textio import normalized_text

pytestmark = pytest.mark.unit


def _block(parent, key):
    rows = parent.all(key)
    assert len(rows) == 1
    assert isinstance(rows[0].value, Block)
    return rows[0].value


def _options(text, name):
    return event._options(_block(parse_text(text).root, name))


def _weight(block, facts):
    weight = float(block.first("base").value.unquoted)
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


@pytest.fixture(scope="module")
def production():
    inputs = event.frozen_inputs()
    plans = tuple(row for row in event.compile_programs() if row.option in event.DISASTER_OPTIONS)
    generated = event.patch(inputs)
    return inputs, plans, generated


def _facts(index, *, population=1000, default=False, farms=None, saved=True, ai=True):
    state = {"state_population": population, "any_scope_building": farms}
    return {
        "is_ai": ai,
        "in_default": default,
        "scope:" + event.DISASTER_SCOPES[index]: state if saved else None,
    }


def _observed_farm(farms, threshold):
    if farms is None:
        return None
    unknown = False
    for farm in farms:
        occupancy = farm.get("occupancy")
        qualification = farm.get("is_farm_building")
        if qualification is True and isinstance(occupancy, (int, float)) and occupancy >= threshold:
            return True
        if qualification is None or (qualification is True and occupancy is None):
            unknown = True
    return None if unknown else False


def _reference_values(facts, index):
    state = facts.get("scope:" + event.DISASTER_SCOPES[index])
    prefix = "disaster_" + event.DISASTER_SCOPES[index]
    return {
        prefix + "_exists": state is not None,
        prefix + "_population": state.get("state_population") if state else None,
        "disaster_default": facts.get("in_default"),
        prefix + "_farm_qualified": _observed_farm(state.get("any_scope_building"), 0.1)
        if state
        else None,
        prefix + "_farm_high": _observed_farm(state.get("any_scope_building"), 0.5)
        if state
        else None,
    }


# Hand-computed from independent declared benefits and recurring cost tiers:
# ordinary +/-10, mega +/-20, crop +/-9 throughput +/-3 welfare;
# high ordinary +/-4, mega +/-8, crop +/-6; paid solvent recurring costs 4/10/2.
@pytest.mark.parametrize(
    ("index", "weak", "strong", "distressed"),
    [
        (0, (40, 56), (36, 60), (40, 52)),
        (1, (40, 56), (36, 60), (40, 52)),
        (2, (30, 60), (22, 68), (30, 50)),
        (3, (30, 60), (22, 68), (30, 50)),
        (4, (38, 60), (32, 66), (38, 58)),
        (5, (40, 58), (36, 62), (40, 56)),
        (6, (40, 58), (36, 62), (40, 56)),
        (7, (30, 60), (22, 68), (30, 50)),
    ],
)
def test_complete_pairs_hand_computed_numeric_outputs(production, index, weak, strong, distressed):
    _, plans, generated = production
    options = _options(generated[event.DISASTERS], event.DISASTER_EVENTS[index])
    selected = tuple(row for row in plans if row.event == event.DISASTER_EVENTS[index])
    low_farms = [{"is_farm_building": True, "occupancy": 0.1}]
    high_farms = [{"is_farm_building": True, "occupancy": 0.5}]
    cases = [
        (_facts(index, farms=low_farms), weak),
        (_facts(index, population=100000, farms=high_farms), strong),
        (_facts(index, default=True, farms=low_farms), distressed),
        (_facts(index, default=None, farms=low_farms), distressed),
        (_facts(index, saved=False), (50, 50)),
        (_facts(index, population=None, farms=high_farms), (50, 50)),
        (_facts(index, population=0, farms=high_farms), (50, 50)),
    ]
    if index == 4:
        empty_farms: list[list[dict[str, object]] | None] = [
            [],
            None,
            [{}],
            [{"is_farm_building": True, "occupancy": 0.09}],
            [{"is_farm_building": False, "occupancy": 1}],
        ]
        cases.extend((_facts(index, farms=farms), (50, 50)) for farms in empty_farms)
        cases.append((_facts(index, farms=[{}, *low_farms]), weak))
    for facts, expected in cases:
        reference = event.evaluate(
            _reference_values(facts, index), is_ai=True, consumer_programs=selected
        )
        actual = tuple(_weight(_block(option, "ai_chance"), facts) for option in options.values())
        assert actual == expected
        assert tuple(reference.values()) == expected
        assert all(0 < value < 100 for value in actual)


def test_saved_scope_isolation_and_player_disabled_paths(production):
    inputs, plans, generated = production
    for index, name in enumerate(event.DISASTER_EVENTS):
        options = _options(generated[event.DISASTERS], name)
        facts = _facts(index, saved=False)
        facts["scope:target_state"] = {"state_population": 1000000}
        facts["owner"] = {"state_population": 1000000}
        facts["disaster_population"] = 1000000
        facts["any_scope_state"] = [{"state_population": 1000000}]
        for other in event.DISASTER_SCOPES:
            if other != event.DISASTER_SCOPES[index]:
                facts["scope:" + other] = {"state_population": 1000000}
        assert tuple(
            _weight(_block(option, "ai_chance"), facts) for option in options.values()
        ) == (50, 50)
        facts["is_ai"] = False
        assert tuple(
            _weight(_block(option, "ai_chance"), facts) for option in options.values()
        ) == (0, 0)
    assert all(plan.evaluate({}, is_ai=False) == 0 for plan in plans)
    assert event.patch(inputs, enabled_domains=frozenset()) == {}
    assert event.evaluate({}, is_ai=True, enabled_domains=frozenset()) == {}


def test_all_original_text_and_complete_effect_ast_restored_exactly(production):
    inputs, plans, generated = production
    restored = generated[event.DISASTERS]
    for plan in plans:
        assert restored.count(event.render(plan)) == 1
        restored = restored.replace(event.render(plan), "")
    assert restored == inputs[event.DISASTERS]
    native = parse_text(inputs[event.DISASTERS]).root
    modified = parse_text(generated[event.DISASTERS]).root
    for name in event.DISASTER_EVENTS:
        original, patched = (
            _options(inputs[event.DISASTERS], name),
            _options(generated[event.DISASTERS], name),
        )
        assert tuple(original) == (name + ".a", name + ".b")
        assert original[name + ".a"].first("default_option").value.unquoted == "yes"
        assert not original[name + ".b"].all("default_option")
        for option, before in original.items():
            after = Block([item for item in patched[option].items if item.key != "ai_chance"])
            assert event._shape(before) == event._shape(after)
            assert not before.all("ai_chance")
        for section in ("trigger", "immediate"):
            assert event._shape(_block(_block(native, name), section)) == event._shape(
                _block(_block(modified, name), section)
            )


def test_exact_cost_effects_krakatoa_and_coastal_earthquake_qualification(production):
    inputs, _, _ = production
    modifiers = parse_text(inputs[event.PLAGUE_MODIFIERS]).root
    root = parse_text(inputs[event.DISASTERS]).root
    for index, name in enumerate(event.DISASTER_EVENTS):
        options = _options(inputs[event.DISASTERS], name)
        relief = _block(options[name + ".b"], "add_modifier")
        size = "large" if index in {2, 3, 7} else "medium" if index in {0, 1} else "small"
        assert relief.first("multiplier").value.unquoted == "money_amount_multiplier_" + size
        assert relief.first("days").value.unquoted == (
            "normal_modifier_time" if size == "large" else "short_modifier_time"
        )
        assert (
            _block(modifiers, relief.first("name").value.unquoted)
            .first("country_expenses_add")
            .value.unquoted
            == "1"
        )
        if index not in {4, 6}:
            scope = "scope:" + event.DISASTER_SCOPES[index] + ".state_region"
            assert _block(options[name + ".a"], scope).first("add_devastation").value.unquoted == (
                "40" if size == "large" else "20"
            )
            assert _block(options[name + ".b"], scope).first("add_devastation").value.unquoted == (
                "20" if size == "large" else "10"
            )
    for modifier, amount in (
        ("modifier_crop_failure", "-0.6"),
        ("modifier_crop_failure_relief_effect", "-0.3"),
    ):
        assert all(
            _block(modifiers, modifier)
            .first("building_group_bg_" + group + "_throughput_add")
            .value.unquoted
            == amount
            for group in ("agriculture", "plantations")
        )
    assert (
        _block(modifiers, "modifier_crop_failure_relief_effect")
        .first("state_welfare_payments_add")
        .value.unquoted
        == "0.15"
    )
    sixth = _block(_block(_block(root, event.DISASTER_EVENTS[5]), "trigger"), "any_scope_state")
    assert sixth.first("is_coastal").value.unquoted == "yes"
    assert (
        _block(sixth, "state_region").first("has_harvest_condition").value.unquoted == "earthquake"
    )
    seventh = _options(inputs[event.DISASTERS], event.DISASTER_EVENTS[6])
    for suffix in ("a", "b"):
        branch = _block(seventh[event.DISASTER_EVENTS[6] + "." + suffix], "if")
        assert _block(branch, "limit").first("has_variable").value.unquoted == "krakatoa_uni_var"
        if suffix == "b":
            assert tuple(row.key for row in branch.assignments()) == ("limit",)


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        ("DISASTERS", "add_devastation = 40", "add_devastation = 41"),
        ("DISASTERS", "occupancy >= 0.1", "occupancy >= 0.01"),
        ("DISASTERS", "days = short_modifier_time", "days = normal_modifier_time"),
        ("DISASTERS", "has_variable = krakatoa_uni_var", "has_variable = wrong_flag"),
        (
            "DISASTERS",
            "global_var:number_of_mega_eruptions > 3",
            "global_var:number_of_mega_eruptions > 4",
        ),
        (
            "PLAGUE_MODIFIERS",
            "building_group_bg_agriculture_throughput_add = -0.6",
            "building_group_bg_agriculture_throughput_add = -0.5",
        ),
        ("EVENT_VALUES", "short_modifier_time = 913", "short_modifier_time = 914"),
        ("EVENT_VALUES", "multiply = 0.15", "multiply = 0.16"),
        ("YEARLY", "3 = natural_disaster_events.6", "4 = natural_disaster_events.6"),
        ("STATE_POPULATION", "state_population < 100000", "state_population > 100000"),
    ],
)
def test_semantic_repin_rejected_independently(production, monkeypatch, source, old, new):
    source = getattr(event, source)
    inputs = dict(production[0])
    assert old in inputs[source]
    inputs[source] = inputs[source].replace(old, new)
    data = deepcopy(event.load())
    data["sources"][source] = hashlib.sha256(inputs[source].encode()).hexdigest()
    monkeypatch.setattr(event, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        event.verify_inputs(inputs)


def test_complete_live_sources_catalog_context_and_typed_queries(production):
    inputs, plans, _ = production
    assert inputs == {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in inputs
    }
    frozen = json.loads(event.FROZEN.read_text(encoding="utf-8"))
    assert frozen["raw_source_hashes"] == {
        source: hashlib.sha256((config.GAME / source).read_bytes()).hexdigest() for source in inputs
    }
    for plan in plans:
        context = plan.evaluation_context()
        assert context.actor_scope.kind == "country"
        assert context.auxiliary_scopes[0].name == plan.identity.saved_state
        assert plan.writer_ir().validate_event_program() is plan
        catalog = event.consumer_catalog()[plan.option]
        assert (
            catalog["default_weight"] == "unknown_not_inferred; intentional_new_explicit_ai_policy"
        )
        assert catalog["cost_semantics"]["kind"] == "country_expenses_add"
        assert plan.identity.explicit
    for mode in ("qualified", "high"):
        query = observation_queries.from_reader(
            "any_scope_building", {event.DISASTER_QUERY_PARAMETER: mode}
        )
        assert isinstance(query, event.DisasterFarmQuery)
        compiled = observation_queries.compile_query(query, inputs)
        assert compiled.actor == "state"
        assert compiled.local_collections == ("saved_state_buildings",)
        assert compiled.world_scans == 0
        assert compiled.expression == event.render_disaster_query(query)


def test_malformed_identity_program_set_policy_bounds_and_queries_rejected(production):
    inputs, plans, _ = production
    with pytest.raises(ValueError, match="注册"):
        _ = replace(plans[0], option="natural_disaster_events.9.a").source
    with pytest.raises(ValueError, match="集合"):
        event.patch(inputs, consumer_programs=event.compile_programs()[:-1])
    with pytest.raises(ValueError, match="最终限幅"):
        event.render(replace(plans[0], scalar=replace(plans[0].scalar, lower=49, upper=51)))
    for engine, params in (
        ("any_scope_state", {event.DISASTER_QUERY_PARAMETER: "high"}),
        ("any_scope_building", {event.DISASTER_QUERY_PARAMETER: "all"}),
        ("any_scope_building", {event.DISASTER_QUERY_PARAMETER: "high", "threshold": "0"}),
    ):
        with pytest.raises(ValueError, match="查询"):
            event.disaster_query_from_reader(engine, params)


def test_sequence_recomputes_exact_scope_exposure_and_financing_without_memory(production):
    _, _, generated = production
    options = _options(generated[event.DISASTERS], event.DISASTER_EVENTS[0])
    sequence = [
        (_facts(0), (40, 56)),
        (_facts(0, population=100000), (36, 60)),
        (_facts(0, population=100000, default=True), (36, 56)),
        (_facts(0, saved=False), (50, 50)),
        (_facts(0), (40, 56)),
    ]
    for facts, expected in sequence:
        assert (
            tuple(_weight(_block(option, "ai_chance"), facts) for option in options.values())
            == expected
        )


@pytest.mark.parametrize("source", ["DISASTERS", "YEARLY", "EVENT_VALUES", "STATE_POPULATION"])
def test_complete_added_source_drift_fails_even_outside_consumed_event(production, source):
    source = getattr(event, source)
    with pytest.raises(ValueError, match="来源漂移"):
        event.verify_inputs({**production[0], source: production[0][source] + "\n# drift\n"})


def test_normal_low_debt_borrowing_and_krakatoa_flag_do_not_manufacture_costs_or_benefits(
    production,
):
    options = _options(production[2][event.DISASTERS], event.DISASTER_EVENTS[6])
    baseline = _facts(6)
    expected = (40, 58)
    for facts in (
        baseline,
        {
            **baseline,
            "taking_loans": True,
            "scaled_debt": 0.1,
            "has_variable": {(("argument", "krakatoa_uni_var"),): True},
        },
    ):
        assert (
            tuple(_weight(_block(option, "ai_chance"), facts) for option in options.values())
            == expected
        )
    # Native absolute damage changes 20->10 to10->0, while paired mitigation
    # remains10 and the actual country recurring expense remains present.


@pytest.mark.integration
def test_shared_model_has_all_sixteen_exact_disaster_programs_and_unique_reader_contracts():
    from pdx import decision_adapters, decision_interfaces
    from pdx.situated import compiler

    model = compiler.load_model()
    configured = decision_adapters.load()
    plans = tuple(row for row in configured.event_programs if row.option in event.DISASTER_OPTIONS)
    assert len(plans) == 16
    assert model.consumer_ir is not None
    writers = tuple(row for row in model.consumer_ir.writers if row.kind == "event_program")
    assert len(writers) == 21
    assert {row.definition for row in writers} == set(event.POLICIES)
    instances = tuple(row for row in model.action_instances if row.source == event.DISASTERS)
    assert {row.rule_id for row in instances} == set(event.DISASTER_OPTIONS)
    contracts = [row for row in model.observation_contracts if row[0] == event.DISASTERS]
    assert len(contracts) == 19  # 8 local exists +8 populations +root default +2 crop
    assert len({(source, key) for source, key, _ in contracts}) == 19
    for plan in plans:
        assert all(
            decision_interfaces.reader_scope(reader, ()) in {"state", "country"}
            for reader in plan.readers()
            if reader.engine != "exists"
        )
        own_keys = {reader.key for reader in plan.readers() if reader.scope != "root"}
        assert plan.identity.saved_state is not None
        assert all(plan.identity.saved_state in key for key in own_keys)
        own_missing: dict[str, object] = {"disaster_default": False}
        for other in event.DISASTER_SCOPES:
            if other != plan.identity.saved_state:
                own_missing["disaster_" + other + "_exists"] = True
                own_missing["disaster_" + other + "_population"] = 1000000
                own_missing["disaster_" + other + "_farm_qualified"] = True
                own_missing["disaster_" + other + "_farm_high"] = True
        assert plan.evaluate(own_missing, is_ai=True) == 50


def test_reader_interfaces_do_not_grant_wrong_saved_state_country_getter_or_query_scope(production):
    from pdx import decision_interfaces

    plans = production[1]
    population = next(
        reader for reader in plans[0].readers() if reader.engine == "state_population"
    )
    farm = next(
        reader
        for plan in plans
        if plan.event == "natural_disaster_events.5"
        for reader in plan.readers()
        if reader.engine == "any_scope_building"
    )
    for malformed in (
        replace(population, scope="root"),
        replace(population, scope="flood_state"),
        replace(population, maximum=100),
        replace(population, unit="ratio"),
        replace(farm, scope="root"),
        replace(farm, scope="earthquake_state"),
    ):
        with pytest.raises(ValueError, match="灾害"):
            decision_interfaces.reader_scope(malformed, ())
