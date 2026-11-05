"""Independent physical witnesses versus emitted five-option PDX; no shared registration bypass."""

import hashlib
import itertools
import json
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

import pytest

from pdx import decision_interfaces, observation_queries
from pdx import event_opportunities as event
from pdx.model import Block, Scalar
from pdx.parser import parse_text

NATIVE_INPUTS = json.loads(event.FROZEN.read_text(encoding="utf-8"))["inputs"]
NATIVE_GROUPS: dict[str, str | None] = {}
NATIVE_BUILDINGS = {}
for row in parse_text(
    NATIVE_INPUTS["common/building_groups/00_building_groups.txt"]
).root.assignments():
    if isinstance(row.value, Block):
        parent = row.value.all("parent_group")
        parent_value = parent[0].value if parent else None
        assert parent_value is None or isinstance(parent_value, Scalar)
        NATIVE_GROUPS[row.key] = parent_value.unquoted if parent_value is not None else None
for source in (
    "common/buildings/02_agro.txt",
    "common/buildings/04_plantations.txt",
    "common/buildings/09_misc_resource.txt",
    "common/buildings/12_subsistence.txt",
):
    for row in parse_text(NATIVE_INPUTS[source]).root.assignments():
        if isinstance(row.value, Block):
            group_value = row.value.all("building_group")[0].value
            assert isinstance(group_value, Scalar)
            NATIVE_BUILDINGS[row.key] = group_value.unquoted


def real_group_chain(building_type):
    group: str | None = NATIVE_BUILDINGS[building_type]
    chain = []
    while group is not None:
        assert group not in chain
        chain.append(group)
        group = NATIVE_GROUPS[group]
    return chain


def real_throughput_exposure(building_type):
    return bool(set(real_group_chain(building_type)) & {"bg_agriculture", "bg_plantations"})


def money(gdp, size):
    # Independent implementation of the pinned AST; exact .5 is not an engine rounding acceptance claim.
    step, ratio = (1000, Decimal("0.0000005")) if size == "large" else (100, Decimal("0.0000025"))
    return max(
        100, int((Decimal(str(gdp)) * ratio).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * step
    )


def world(**changes):
    value = {
        "exists": True,
        "owned": True,
        "optimization": 0,
        "buildings": [],
        "buildings_complete": True,
        "goods": {},
        "gdp": 2_000_000,
        "income": 2000,
        "default": False,
    }
    value.update(changes)
    return value


def trigger(block, w, scope="root", *, ai=True, building=None, good=None):
    """Small PDX interpreter of actual AST and physical objects, not production guards."""
    rows = block.assignments()

    def conjunction(values):
        values = list(values)
        return False if False in values else None if None in values else True

    def disjunction(values):
        values = list(values)
        return True if True in values else None if None in values else False

    def one(row):
        key, value = row.key, row.value
        if isinstance(value, Block):
            if key in {"OR", "or"}:
                return disjunction(one(part) for part in value.assignments())
            if key == "NOT":
                result = trigger(value, w, scope, ai=ai, building=building, good=good)
                return None if result is None else not result
            if key == "scope:hokkaido_state_scope":
                return w["exists"] is True and trigger(value, w, "state", ai=ai)
            if key == "any_scope_building":
                assert scope == "state"
                result = disjunction(
                    trigger(value, w, "building", ai=ai, building=b) for b in w["buildings"]
                )
                return True if result is True else result if w["buildings_complete"] else None
            if key == "market":
                return trigger(value, w, "market", ai=ai)
            if key.startswith("mg:"):
                target = key[3:]
                return target in w["goods"] and trigger(value, w, "good", ai=ai, good=target)
            pytest.fail(f"Unsupported block {key}")
        assert isinstance(value, Scalar)
        operand = value.unquoted
        if key == "is_ai":
            return ai is True
        if key == "exists":
            return (
                w["exists"] is True if operand.startswith("scope:") else operand[3:] in w["goods"]
            )
        if key == "owner":
            assert scope == "state"
            assert operand == "root"
            return w["owned"] is True
        if key == "has_variable":
            return w["optimization"] is not None
        if key == "var:optimization_counter_var":
            return w["optimization"] == int(operand)
        if key == "has_building":
            found = any(b["type"] == operand for b in w["buildings"])
            return True if found else False if w["buildings_complete"] else None
        if key == "is_building_type":
            return building["type"] == operand
        if key == "is_building_group":
            # Real source group + parent closure, never a fixture's farm label.
            return operand in real_group_chain(building["type"])
        if key == "in_default":
            return w["default"] is False
        if key in {"level", "occupancy"}:
            number = building.get(key)
            threshold = float(operand)
        elif key == "net_fixed_income":
            number = w["income"]
            threshold = money(w["gdp"], operand.removeprefix("money_amount_multiplier_"))
        elif key in {"market_goods_delta", "market_goods_pricier"}:
            number = w["goods"][good].get("delta" if key.endswith("delta") else "price")
            threshold = float(operand)
        else:
            pytest.fail(f"Unsupported scalar {key}")
        if type(number) not in {int, float}:
            return False
        return {
            ">": number > threshold,
            ">=": number >= threshold,
            "<": number < threshold,
            "=": number == threshold,
        }[row.op]

    return conjunction(one(row) for row in rows)


def observations(plan, w):
    result = {"hokkaido_exists": w["exists"], "hokkaido_owned": w["owned"]}
    for reader in plan.readers():
        if reader.engine == "hokkaido_observation":
            query = event.hokkaido_query_from_reader(reader.engine, dict(reader.parameters))
            body = parse_text(event.render_hokkaido_query(query)).root
            scope = "root" if reader.scope == "root" else "state"
            result[reader.key] = trigger(body, w, scope)
    return result


def reference(w):
    """Independent declared preference arithmetic on physical world state."""
    result = dict(zip(event.HOKKAIDO_OPTIONS, (10, 70, 5, 10, 10), strict=True))
    core = w["exists"] is True and w["owned"] is True
    for name in result:
        size = "large" if name.endswith(".a") else "medium"
        covered = (
            w["default"] is False
            and type(w["income"]) in {int, float}
            and w["income"] > money(w["gdp"], size)
        )
        result[name] -= 1 if covered else 2
    if not core:
        return result
    crops = [b for b in w["buildings"] if real_throughput_exposure(b["type"])]
    if w["optimization"] == 0 and any(b.get("occupancy", -1) >= 0.1 for b in crops):
        result["hokkaido_events.3.a"] += 2
        if any(b.get("occupancy", -1) >= 0.5 for b in crops):
            result["hokkaido_events.3.a"] += 2
    wheat = [b for b in w["buildings"] if b["type"] == "building_wheat_farm"]
    if wheat:
        result["hokkaido_events.3.b"] -= 8
        if any(b.get("level", -1) > 3 for b in wheat):
            result["hokkaido_events.3.b"] -= 20
        if any(b.get("occupancy", -1) >= 0.5 for b in wheat):
            result["hokkaido_events.3.b"] -= 4
    for suffix, good in (("b", "grain"), ("c", "dye"), ("e", "opium"), ("g", "wine")):
        goods = w["goods"].get(good, {})
        if goods.get("delta", 0) < 0 and (suffix != "b" or (w["buildings_complete"] and not wheat)):
            result["hokkaido_events.3." + suffix] += 2
            if goods.get("price", 0) > 0.25:
                result["hokkaido_events.3." + suffix] += 2
    return result


@pytest.fixture(scope="module")
def candidate():
    inputs = event.frozen_inputs()
    plans = tuple(p for p in event.compile_programs() if p.identity.family == "hokkaido")
    outputs = event.patch(inputs, enabled_families=frozenset({"hokkaido"}))
    parent = event._block(parse_text(outputs[event.HOKKAIDO]).root, event.HOKKAIDO_EVENT)
    return inputs, plans, outputs, event._options(parent)


@pytest.mark.parametrize(
    ("exists", "owned", "default", "size", "occupancy", "demand"),
    tuple(
        itertools.product(
            (True, False),
            (True, False),
            (True, False),
            (0, 2, 3, 4, 100),
            (0.1, 0.5),
            (False, True),
        )
    ),
)
def test_physical_world_independent_arithmetic_and_pdx(
    candidate, exists, owned, default, size, occupancy, demand
):
    _, plans, _, options = candidate
    buildings = (
        [{"type": "building_wheat_farm", "group": "farm", "level": size, "occupancy": occupancy}]
        if size
        else []
    )
    goods = (
        {g: {"delta": -1, "price": 0.5} for g in ("grain", "dye", "opium", "wine")}
        if demand
        else {}
    )
    w = world(exists=exists, owned=owned, default=default, buildings=buildings, goods=goods)
    expected = reference(w)
    for plan in plans:
        base = (10, 70, 5, 10, 10)[event.HOKKAIDO_OPTIONS.index(plan.option)]
        assert base + plan.evaluate(observations(plan, w), is_ai=True) == expected[plan.option]
        chance = event._block(options[plan.option], "ai_chance")
        weight = float(base)
        for row in chance.all("modifier"):
            modifier = row.value
            assert isinstance(modifier, Block)
            if trigger(event._block(modifier, "trigger"), w):
                amount = modifier.all("add")[0].value
                assert isinstance(amount, Scalar)
                weight += float(amount.unquoted)
        assert weight == expected[plan.option]
        assert base + plan.evaluate(observations(plan, w), is_ai=False) == base
        assert base + plan.evaluate(observations(plan, w), is_ai=True, enabled=False) == base


def test_auxiliary_unknown_retains_basic_need_and_independent_cost(candidate):
    _, plans, _, _ = candidate
    dye = next(p for p in plans if p.option.endswith(".c"))
    values: dict[str, object] = {
        "hokkaido_exists": True,
        "hokkaido_owned": True,
        "hokkaido_dye_demand": True,
    }
    assert (
        dye.evaluate(values, is_ai=True) == 0
    )  # +2 basic -2 expense; unknown price/finance exits locally.
    values["hokkaido_owned"] = None
    assert dye.evaluate(values, is_ai=True) == -2
    rice = plans[1]
    assert (
        rice.evaluate(
            {"hokkaido_exists": True, "hokkaido_owned": True, "hokkaido_wheat": True}, is_ai=True
        )
        == -10
    )
    crops = plans[0]
    assert (
        crops.evaluate(
            {
                "hokkaido_exists": True,
                "hokkaido_owned": True,
                "hokkaido_optimization_zero": True,
                "hokkaido_crops": True,
            },
            is_ai=True,
        )
        == 0
    )


@pytest.mark.parametrize(
    ("gdp", "medium", "large"),
    [
        (599999, 100, 100),
        (600001, 200, 100),
        (999999, 200, 100),
        (1000001, 300, 1000),
        (2999999, 700, 1000),
        (3000001, 800, 2000),
    ],
)
def test_actual_distinct_fee_rounding_boundaries(candidate, gdp, medium, large):
    assert money(gdp, "medium") == medium
    assert money(gdp, "large") == large
    _, plans, _, _ = candidate
    w = world(gdp=gdp, income=(medium + large) / 2)
    for plan in plans:
        expected = reference(w)[plan.option]
        base = (10, 70, 5, 10, 10)[event.HOKKAIDO_OPTIONS.index(plan.option)]
        assert base + plan.evaluate(observations(plan, w), is_ai=True) == expected


def test_all_original_bytes_and_variables_eligibility_effects_tail_preserved(candidate):
    inputs, plans, outputs, _ = candidate
    output = outputs[event.HOKKAIDO]
    for plan in plans:
        output = output.replace(event.render(plan), "")
    assert output == inputs[event.HOKKAIDO]
    assert event.patch(inputs, enabled_families=frozenset()) == {}
    assert event.patch(inputs, enabled_domains=frozenset()) == {}
    original = event._block(parse_text(inputs[event.HOKKAIDO]).root, event.HOKKAIDO_EVENT)
    counter = event._block(
        event._block(
            event._block(event._block(original, "immediate"), "s:STATE_HOKKAIDO"),
            "random_scope_state",
        ),
        "set_variable",
    )
    counter_value = counter.all("value")[0].value
    assert isinstance(counter_value, Scalar)
    assert counter_value.unquoted == "0"
    for suffix in ("b", "c", "e", "g"):
        option = event._options(original)[event.HOKKAIDO_EVENT + "." + suffix]
        assert option.all("trigger")
        assert option.all("set_variable")


def test_complete_source_pin_and_atomic_identity(candidate):
    inputs, _, _, _ = candidate
    changed = dict(inputs)
    changed[event.HOKKAIDO] += "\n# tail drift\n"
    with pytest.raises(ValueError, match="完整原版来源漂移"):
        event.verify_inputs(changed)
    plans = event.compile_programs()
    assert len(plans) == 28
    with pytest.raises(ValueError, match="程序集合"):
        event.patch(inputs, consumer_programs=plans[:-1])
    with pytest.raises(ValueError, match="程序集合"):
        event.patch(inputs, consumer_programs=(*plans[:-1], plans[0]))
    for bad in ("", "free_script", "wheat_profit", "world_population"):
        with pytest.raises(ValueError, match="精确固定有界事实"):
            event.render_hokkaido_query(event.HokkaidoQuery(bad))
    frozen = json.loads(event.FROZEN.read_text(encoding="utf-8"))
    for name in event.HOKKAIDO_SOURCES:
        assert hashlib.sha256(inputs[name].encode()).hexdigest() == frozen["source_hashes"][name]


def test_optimization_is_not_accumulated_and_empty_potential_not_production(candidate):
    _, plans, _, _ = candidate
    crop = {"type": "building_wheat_farm", "group": "farm", "level": 1, "occupancy": 0.5}
    assert plans[0].evaluate(observations(plans[0], world(buildings=[crop])), is_ai=True) == 3
    assert (
        plans[0].evaluate(
            observations(plans[0], world(buildings=[crop], optimization=1)), is_ai=True
        )
        == -1
    )
    assert plans[0].evaluate(observations(plans[0], world()), is_ai=True) == -1
    for plan in plans[2:]:
        assert plan.evaluate(observations(plan, world()), is_ai=True) == -1


def test_narrow_query_contracts_bound_to_current_local_objects(candidate):
    inputs, plans, _, _ = candidate
    for plan in plans:
        for reader in plan.readers():
            if reader.engine != "hokkaido_observation":
                continue
            query = event.hokkaido_query_from_reader(reader.engine, dict(reader.parameters))
            compiled = event.compile_hokkaido_query(query, inputs)
            assert compiled.world_scans == 0
            assert compiled.actor == ("country" if reader.scope == "root" else "state")
            assert "set_variable" not in compiled.expression
    for plan in plans:
        context = plan.evaluation_context()
        assert context.actor_scope.name == "root"
        assert context.auxiliary_scopes[0].name == "hokkaido_state_scope"
        assert context.auxiliary_scopes[0].kind == "state"
        assert plan.writer_ir().validate_event_program() == plan


@pytest.mark.parametrize(
    ("suffix", "good"), [("b", "grain"), ("c", "dye"), ("e", "opium"), ("g", "wine")]
)
def test_one_basic_good_need_can_participate_without_price_or_other_needs(candidate, suffix, good):
    _, plans, _, _ = candidate
    plan = next(p for p in plans if p.option.endswith("." + suffix))
    w = world(goods={good: {"delta": -1}})
    assert plan.evaluate(observations(plan, w), is_ai=True) == 1
    w["goods"] = {good: {"delta": 1, "price": 0.5}}
    assert plan.evaluate(observations(plan, w), is_ai=True) == -1


@pytest.mark.parametrize(
    ("building_type", "expected"),
    [
        ("building_wheat_farm", 3),
        ("building_vineyard", 3),
        ("building_dye_plantation", 3),
        ("building_opium_plantation", 3),
        ("building_subsistence_farm", 3),
        ("building_subsistence_orchard", 3),
        ("building_subsistence_rice_farm", 3),
        ("building_subsistence_fishing_village", 3),
        ("building_livestock_ranch", -1),
        ("building_rubber_plantation", -1),
        ("building_subsistence_pasture", -1),
        ("building_logging_camp", -1),
    ],
)
def test_existing_operating_plantation_or_farm_is_real_throughput_exposure(
    candidate, building_type, expected
):
    _, plans, _, _ = candidate
    w = world(
        buildings=[
            {
                "type": building_type,
                "group": "deliberately_wrong_fixture_label",
                "level": 4,
                "occupancy": 0.5,
            }
        ]
    )
    assert plans[0].evaluate(observations(plans[0], w), is_ai=True) == expected


def test_group_query_closure_is_complete_and_independent_of_ranching_and_rubber(candidate):
    _, plans, _, _ = candidate
    known_groups = {
        group
        for group in NATIVE_GROUPS
        if any(
            group in real_group_chain(kind) and real_throughput_exposure(kind)
            for kind in NATIVE_BUILDINGS
        )
    }
    assert known_groups == {
        "bg_agriculture",
        "bg_staple_crops",
        "bg_subsistence_agriculture",
        "bg_plantations",
    }
    assert not real_throughput_exposure("building_livestock_ranch")
    assert not real_throughput_exposure("building_rubber_plantation")
    assert real_throughput_exposure("building_subsistence_farm")
    plan = plans[0]
    for kind in NATIVE_BUILDINGS:
        w = world(buildings=[{"type": kind, "occupancy": 0.5, "level": 4}])
        expected = 3 if real_throughput_exposure(kind) else -1
        assert plan.evaluate(observations(plan, w), is_ai=True) == expected


@pytest.mark.parametrize(
    ("complete", "level", "expected_absent", "expected_delta"),
    [
        (False, 0, None, -1),
        (True, 0, True, 1),
        (False, 2, False, -13),
        (True, 2, False, -13),
        (False, 4, False, -33),
        (True, 4, False, -33),
    ],
)
def test_incomplete_building_inventory_is_never_inverted_to_absence(
    candidate, complete, level, expected_absent, expected_delta
):
    _, plans, _, options = candidate
    rice = plans[1]
    buildings = [{"type": "building_wheat_farm", "occupancy": 0.5, "level": level}] if level else []
    w = world(buildings=buildings, buildings_complete=complete, goods={"grain": {"delta": -1}})
    values = observations(rice, w)
    assert values["hokkaido_wheat_absent"] is expected_absent
    assert rice.evaluate(values, is_ai=True) == expected_delta
    # Lowered PDX runs through the same independent three-valued AST engine;
    # it does not receive precomputed production guard booleans.
    chance = event._block(options[rice.option], "ai_chance")
    total = 70.0
    for row in chance.all("modifier"):
        assert isinstance(row.value, Block)
        if trigger(event._block(row.value, "trigger"), w) is True:
            amount = row.value.all("add")[0].value
            assert isinstance(amount, Scalar)
            total += float(amount.unquoted)
    assert total == 70 + expected_delta


def test_positive_crop_witness_survives_incomplete_inventory(candidate):
    _, plans, _, _ = candidate
    w = world(
        buildings=[{"type": "building_wheat_farm", "occupancy": 0.5, "level": 2}],
        buildings_complete=False,
    )
    assert plans[0].evaluate(observations(plans[0], w), is_ai=True) == 3
    w["buildings"] = []
    values = observations(plans[0], w)
    assert values["hokkaido_crops"] is None
    assert plans[0].evaluate(values, is_ai=True) == -1


def test_compiled_absence_query_explicitly_requires_complete_negative_evidence(candidate):
    inputs, _, _, _ = candidate
    compiled = event.compile_hokkaido_query(event.HokkaidoQuery("wheat_absent"), inputs)
    assert "complete_known_wheat_absence=true" in compiled.unknown_policy
    assert "known_wheat_witness=false" in compiled.unknown_policy
    assert "never_negate_unknown_to_true" in compiled.unknown_policy


def test_budget_comparison_is_strict_and_other_facts_do_not_erase_it(candidate):
    _, plans, _, _ = candidate
    for plan in plans:
        size = "large" if plan.option.endswith(".a") else "medium"
        expense = money(2_000_000, size)
        for income, expected in ((expense - 0.001, -2), (expense, -2), (expense + 0.001, -1)):
            w = world(exists=False, income=income)
            assert plan.evaluate(observations(plan, w), is_ai=True) == expected


@pytest.mark.parametrize("observation", tuple(event.HOKKAIDO_QUERIES))
def test_production_query_bridge_and_complete_scope_authorization(candidate, observation):
    inputs, plans, _, _ = candidate
    reader, plan = next(
        (reader, plan)
        for plan in plans
        for reader in plan.readers()
        if dict(reader.parameters).get(event.HOKKAIDO_QUERY_PARAMETER) == observation
    )
    query = observation_queries.from_reader(reader.engine, dict(reader.parameters))
    compiled = observation_queries.compile_query(query, inputs)
    assert observation_queries.required_sources(query) == tuple(sorted(event.HOKKAIDO_SOURCES))
    assert compiled.expression == observation_queries.render(query)
    assert reader.expression("=", True) == compiled.expression
    assert "hokkaido_observation" not in compiled.expression
    assert (
        decision_interfaces.reader_scope(
            reader, (), source=plan.source, field=plan.field_path, context=plan.evaluation_context()
        )
        == compiled.actor
    )


@pytest.mark.parametrize(
    "change",
    [
        {"key": "forged"},
        {"scope": "root"},
        {"engine": "any_scope_building"},
        {"parameters": ((event.HOKKAIDO_QUERY_PARAMETER, "crops_high"),)},
        {"parameters": ((event.HOKKAIDO_QUERY_PARAMETER, "crops"), ("extra", "yes"))},
        {"parameters": ((event.HOKKAIDO_QUERY_PARAMETER, "crops"),) * 2},
        {"path": ("owner",)},
        {"argument": "root"},
        {"unit": "ratio"},
        {"kind": "number"},
        {"minimum": 0},
        {"maximum": 1},
        {"value_field": "value"},
    ],
)
def test_production_reader_rejects_signature_mutations(candidate, change):
    _, plans, _, _ = candidate
    plan = plans[0]
    reader = next(reader for reader in plan.readers() if reader.key == "hokkaido_crops")
    with pytest.raises(ValueError, match="北海道读取器"):
        decision_interfaces.reader_scope(
            replace(reader, **change),
            (),
            source=plan.source,
            field=plan.field_path,
            context=plan.evaluation_context(),
        )


def test_production_reader_rejects_wrong_option_source_context_and_root(candidate):
    _, plans, _, _ = candidate
    plan = plans[0]
    reader = next(reader for reader in plan.readers() if reader.key == "hokkaido_crops")
    exact = {"source": plan.source, "field": plan.field_path, "context": plan.evaluation_context()}
    for changes in (
        {"source": event.SOL},
        {"field": plans[1].field_path},
        {"context": None},
        {
            "context": next(
                p for p in event.compile_programs() if p.identity.family == "sol_response"
            ).evaluation_context()
        },
        {"native_root": "state"},
    ):
        with pytest.raises(ValueError, match="北海道读取器"):
            decision_interfaces.reader_scope(reader, (), **{**exact, **changes})
    with pytest.raises(ValueError, match="北海道读取器"):
        decision_interfaces.reader_scope(reader, ("owner",), **exact)
    with pytest.raises(ValueError, match="北海道读取器"):
        decision_interfaces.reader_scope(reader, ())
    # A forged writer cannot transplant the new state context into an old family.
    legacy = next(p for p in event.compile_programs() if p.identity.family == "healthcare")
    with pytest.raises(ValueError, match="事件writer"):
        replace(
            legacy.writer_ir(), evaluation_context=plan.evaluation_context()
        ).validate_event_program()


def test_old_families_keep_their_exact_source_contracts():
    for plan in event.compile_programs():
        expected = (
            event.HOKKAIDO_SOURCES
            if plan.identity.family == "hokkaido"
            else event.SOL_SOURCES
            if plan.identity.family == "sol_response"
            else event.LEGACY_SOURCES
        )
        assert set(event.required_program_sources(plan)) == set(expected)
        if plan.identity.family != "hokkaido":
            assert event.HOKKAIDO not in event.required_program_sources(plan)
            assert all(not reader.key.startswith("hokkaido_") for reader in plan.readers())
