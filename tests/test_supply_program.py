"""Enum supply programs preserve scarcity semantics and reject identity drift."""

import json
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from pdx import country_state, decision_adapters, decision_rules, decisions
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval
from pdx.situated.decision_ir import ConsumerIRBundle, WriterDecisionIR
from pdx.situated.supply_program import SOURCE, SupplyAction, SupplyProgram

pytestmark = pytest.mark.unit


def _writer(program):
    return WriterDecisionIR(
        writer_id=program.writer_id,
        kind="supply_program",
        source=program.source,
        definition=program.good,
        consumer_id=program.consumer_id,
        field=program.field,
        actor="root",
        target="market_goods",
        operation="append",
        vanilla_tail="preserve",
        owner="supply_plan",
        supply_program=program,
    )


@pytest.fixture(scope="module")
def program():
    return SupplyProgram(SupplyAction(SOURCE, "tools", 0.25))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "wants_high_supply"),
        ({"price": 0.25}, None),
        ({"price": 0.25000001}, "wants_high_supply"),
        ({"delta": 0}, None),
        ({"delta": 1}, None),
        ({"is_ai": False}, None),
        ({"is_ai": None}, None),
        ({"market_present": False}, None),
        ({"market_present": None}, None),
        ({"good_present": False}, None),
        ({"good_present": None}, None),
        ({"price": None}, None),
        ({"delta": None}, None),
    ],
)
def test_reference_matches_independent_actual_enum_trigger(program, changes, expected):
    values = {
        "is_ai": True,
        "price": 0.5,
        "delta": -1,
        "market_present": True,
        "good_present": True,
    }
    values.update(changes)
    parsed = parse_text(program.render())
    assert not parsed.errors
    row = parsed.root.first("tools")
    assert row is not None
    assert isinstance(row.value, Block)
    stance = row.value.first("stance")
    trigger = row.value.first("trigger")
    assert stance is not None
    assert isinstance(stance.value, Scalar)
    assert trigger is not None
    assert isinstance(trigger.value, Block)
    country = {"is_ai": values["is_ai"]}
    if values["market_present"] is True:
        market = {}
        if values["good_present"] is True:
            market["mg:tools"] = {
                "market_goods_pricier": values["price"],
                "market_goods_delta": values["delta"],
            }
        country["market"] = market
    active = pdx_eval.condition(trigger.value, country)
    assert (stance.value.text if active is True else None) == expected
    assert program.evaluate(**values) == expected


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), 10**1000])
def test_invalid_core_values_fall_back_locally(program, bad):
    assert program.evaluate(is_ai=True, price=bad, delta=-1) is None
    assert program.evaluate(is_ai=True, price=0.5, delta=bad) is None


def test_disabled_program_adds_no_stance(program):
    assert program.evaluate(is_ai=True, price=0.5, delta=-1, enabled=False) is None
    plan = decision_adapters.SupplyPlan(SOURCE, ("tools",), 0.25)
    bundle = ConsumerIRBundle(1, (), (_writer(program),))
    assert decision_adapters._supply_programs(plan, bundle, enabled=False) == ()
    # A partial adapter build may omit supply while sharing the complete IR.
    assert decision_adapters._supply_programs(None, bundle, enabled=False) == ()
    assert (
        decision_adapters._supply_programs(None, ConsumerIRBundle(1, (), ()), enabled=False) == ()
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "common/ai_strategies/other.txt"},
        {"good": "tools.bad"},
        {"price_threshold": True},
        {"price_threshold": 0},
        {"price_threshold": float("inf")},
        {"price_threshold": 1},
    ],
)
def test_action_configuration_requires_exact_typed_identity(program, changes):
    with pytest.raises(ValueError):
        replace(program.action, **changes)


def test_plan_is_immutable_and_reference_renderer_contract_share_instance(program):
    with pytest.raises(FrozenInstanceError):
        program.action.good = "glass"
    plan = decision_adapters.SupplyPlan(SOURCE, ("tools",), 0.25)
    bundle = ConsumerIRBundle(1, (), (_writer(program),))
    selected = decision_adapters._supply_programs(plan, bundle, enabled=True)
    assert selected[0] is program
    row = bundle.as_dict()["writers"][0]
    assert row["supply_program"] == program.as_dict()
    assert row["operation"] == "append"
    assert row["supply_program"]["value_kind"] == "enum"
    assert bundle.as_dict()["supply_program_writer_count"] == 1
    assert bundle.as_dict()["legacy_writer_count"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"writer_id": "supply_glass"},
        {"source": "common/ai_strategies/other.txt"},
        {"definition": "glass"},
        {"consumer_id": "goods_stances.glass"},
        {"field": "ai_strategy_default.goods_stances.glass"},
        {"actor": "owner"},
        {"target": "target_country"},
        {"operation": "add"},
        {"owner": "consumer_adapters"},
        {"kind": "rule_action"},
        {"vanilla_tail": "replace"},
    ],
)
@pytest.mark.parametrize("enabled", [False, True])
def test_wrong_writer_identity_or_scope_is_rejected(program, changes, enabled):
    writer = replace(_writer(program), **changes)
    bundle = ConsumerIRBundle(1, (), (writer,))
    plan = decision_adapters.SupplyPlan(SOURCE, ("tools",), 0.25)
    with pytest.raises(ValueError):
        bundle.as_dict()
    with pytest.raises(ValueError):
        decision_adapters._supply_programs(plan, bundle, enabled=enabled)
    with pytest.raises(ValueError):
        decision_adapters._supply_programs(None, bundle, enabled=False)


def test_missing_duplicate_or_drifted_programs_cannot_fall_back_to_second_author(program):
    plan = decision_adapters.SupplyPlan(SOURCE, ("tools",), 0.25)
    writer = _writer(program)
    drift = _writer(replace(program, action=replace(program.action, price_threshold=0.5)))
    for rows in ((), (writer, writer), (drift,)):
        bundle = ConsumerIRBundle(1, (), rows)
        with pytest.raises(ValueError):
            decision_adapters._supply_programs(plan, bundle, enabled=True)
    with pytest.raises(ValueError, match="重复"):
        replace(plan, goods=("tools", "tools")).actions()


@pytest.mark.parametrize(
    "field",
    ["ai_strategy_default.goods_stances", "ai_strategy_default.goods_stances.tools.weight"],
)
def test_enum_owner_ledger_keeps_parent_child_guard(program, field):
    writer = _writer(program)
    other = WriterDecisionIR(
        "other",
        "rule_action",
        SOURCE,
        "other",
        "other",
        field,
        "root",
        "none",
        "add",
        "preserve",
        "supply_plan",
    )
    with pytest.raises(ValueError, match="父子"):
        ConsumerIRBundle(1, (), (writer, other)).as_dict()


def test_production_compiler_contains_each_configured_enum_once():
    plan = decision_adapters.load().supply
    assert plan is not None
    bundle = compiler.load_model().consumer_ir
    assert bundle is not None
    programs = decision_adapters._supply_programs(plan, bundle, enabled=True)
    assert len(programs) == len(plan.goods) == 33
    assert tuple(program.good for program in programs) == plan.goods
    rows = [writer for writer in bundle.writers if writer.kind == "supply_program"]
    assert all(
        writer.supply_program is program for writer, program in zip(rows, programs, strict=True)
    )
    assert all(writer.operation == "append" and writer.owner == "supply_plan" for writer in rows)


def _stance_ast(text):
    parsed = parse_text(text)
    assert not parsed.errors
    strategy = parsed.root.first("ai_strategy_default")
    assert strategy is not None
    assert isinstance(strategy.value, Block)
    stances = strategy.value.first("goods_stances")
    assert stances is not None
    assert isinstance(stances.value, Block)

    def without_lines(value):
        if isinstance(value, dict):
            return {key: without_lines(item) for key, item in value.items() if key != "line"}
        if isinstance(value, list):
            return [without_lines(item) for item in value]
        return value

    return without_lines(asdict(stances.value))


def _assert_no_produced_supply(files):
    metadata = json.loads(files[".metadata/metadata.json"])
    bundle = metadata["situated_actions"]["consumer_ir"]
    assert bundle["supply_program_writer_count"] == 0
    assert all(writer["kind"] != "supply_program" for writer in bundle["writers"])
    assert all("supply_program" not in writer for writer in bundle["writers"])
    assert not any(
        field.startswith("ai_strategy_default.goods_stances") for field in bundle["field_owners"]
    )
    assert not any(
        field.startswith(SOURCE + ":ai_strategy_default.goods_stances")
        for field in bundle["source_field_owners"]
    )
    assert "supply_plan" not in metadata.get("default_field_owners", {}).values()
    actual = files[SOURCE]
    assert "# SITAI BEGIN supply:goods_stances" not in actual
    assert _stance_ast(actual) == _stance_ast(decisions.baseline_path().read_text(encoding="utf-8"))
    return metadata


def test_real_build_without_adapters_has_no_supply_writer_or_stance():
    files = decisions.build()
    metadata = _assert_no_produced_supply(files)
    assert "consumer_adapters" not in metadata


@pytest.mark.integration
def test_real_build_with_market_disabled_has_no_supply_writer_or_stance():
    adapters = decision_adapters.load()
    assert adapters.supply is not None
    disabled = replace(
        adapters,
        policies=tuple(
            (source, replace(policy, enabled_domains=policy.enabled_domains - {"market"}))
            for source, policy in adapters.policies
        ),
    )
    files = decisions.build(
        extensions=decisions.load_extensions(profile="release"),
        information_rules=decision_rules.load(),
        consumer_adapters=disabled,
        country_policy=country_state.load(),
    )
    metadata = _assert_no_produced_supply(files)
    assert metadata["consumer_adapters"]["supply_plan"] is None
    assert all(
        row["owner"] != "supply_plan" for row in metadata["consumer_adapters"]["field_owners"]
    )
