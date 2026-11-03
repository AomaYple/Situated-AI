"""Last two research supports: actual IG stance and an explicit weak market proxy."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/technology/technologies/30_society.txt"
FIELDS = {"anarchism.ai_weight", "paved_roads.ai_weight"}


@pytest.fixture(scope="module")
def production() -> tuple[Any, str, str]:
    adapters = decision_adapters.load()
    raw = dict(adapters.policies)[SOURCE]
    rules = tuple(rule for rule in raw.rules if ".".join(rule.field) in FIELDS)
    assert {".".join(rule.field) for rule in rules} == FIELDS
    assert len(rules) == 3
    keys = frozenset(key for rule in rules for key in rule.input_keys())
    raw = replace(
        raw,
        rules=rules,
        readers=tuple(reader for reader in raw.readers if reader.key in keys),
        enabled_domains=frozenset(rule.domain for rule in rules),
        semantic_ir=(),
        consumer_programs=(),
    )
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(raw, SOURCE, model)
    inputs = decision_adapters.read_inputs(adapters)
    selected = replace(
        adapters, policies=((SOURCE, policy),), initial_values=(), scalar_values=(), supply=None
    )
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return policy, inputs[SOURCE], files[SOURCE]


def _ig(stance: object, law: str = "law_anarchy") -> dict[str, object]:
    return {"law_stance": {(("law", "law_type:" + law),): stance}}


def _values(changes: Mapping[str, object]) -> dict[str, object]:
    return {
        "anarchy_interest_group_support": False,
        "current_anarchy": False,
        "current_cooperative_ownership": False,
        "market_automobile_total_consumption": 0,
        "country_goods_automobiles_balance": 0,
        **changes,
    }


def _engine(values: Mapping[str, object], groups: object, *, is_ai: bool = True) -> dict[str, Any]:
    return {
        "ROOT": {
            "is_ai": is_ai,
            "any_interest_group": groups,
            "has_law_or_variant": {
                (("argument", "law_type:law_anarchy"),): values.get("current_anarchy"),
                (("argument", "law_type:law_cooperative_ownership"),): values.get(
                    "current_cooperative_ownership"
                ),
            },
            "market": {
                "mg:automobiles": {
                    "market_goods_consumption": values.get("market_automobile_total_consumption"),
                    "market_goods_delta": values.get("country_goods_automobiles_balance"),
                }
            },
        }
    }


def _overlay(text: str, technology: str) -> str:
    start = text.index(f"# SITAI BEGIN information:{technology}.ai_weight")
    end = text.index(f"# SITAI END information:{technology}.ai_weight", start)
    return "\n".join(text[start:end].splitlines()[1:])


def _assert_result(production, technology, changes, groups, expected):
    policy, _native, generated = production
    values = _values(changes)
    result = pdx_eval.select(_overlay(generated, technology), _engine(values, groups))
    field = technology + ".ai_weight"
    program_id = "program_" + hashlib.sha256(f"{SOURCE}:{field}".encode()).hexdigest()[:16]
    assert (result.action_id, result.operation) == (program_id, "multiply")
    assert result.delta == pytest.approx(expected)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    if expected == 1:
        assert reference is None
    else:
        assert reference is not None
        assert reference[0] == program_id
        assert reference[1] == pytest.approx(expected)
    return result


IG_CASES: list[tuple[Mapping[str, object], object, float]] = [
    ({"anarchy_interest_group_support": True}, [_ig(1)], 1.04),
    (
        {"anarchy_interest_group_support": True, "current_cooperative_ownership": True},
        [_ig(1)],
        1.08,
    ),
    (
        {"anarchy_interest_group_support": True, "current_cooperative_ownership": None},
        [_ig(1)],
        1.04,
    ),
    ({"anarchy_interest_group_support": True, "current_anarchy": True}, [_ig(1)], 1),
    ({"anarchy_interest_group_support": True, "current_anarchy": None}, [_ig(1)], 1),
    ({"anarchy_interest_group_support": True}, [_ig(1), _ig(1)], 1.04),
    ({"anarchy_interest_group_support": True}, [{}, _ig(1)], 1.04),
    ({"anarchy_interest_group_support": True}, [_ig(-1), _ig(1)], 1.04),
    ({}, [_ig(0)], 1),
    ({}, [_ig(-1)], 1),
    ({}, [], 1),
    ({"anarchy_interest_group_support": None}, None, 1),
    ({"anarchy_interest_group_support": None}, [{}], 1),
    ({"anarchy_interest_group_support": None}, [_ig(1, "law_council_republic")], 1),
    ({"anarchy_interest_group_support": None}, [{"has_ideology": "ideology_populist"}], 1),
    ({"current_cooperative_ownership": True}, [_ig(0)], 1),
    ({"current_cooperative_ownership": True}, [], 1),
]


@pytest.mark.parametrize(("changes", "groups", "expected"), IG_CASES)
def test_handwritten_interest_group_actual_law_stance_and_same_cause_tiers(
    production, changes, groups, expected
):
    _assert_result(production, "anarchism", changes, groups, expected)


@pytest.mark.parametrize(
    ("consumption", "balance", "expected"),
    [
        (0, 0, 1),
        (0, 100, 1),
        (None, 100, 1),
        (100, None, 1),
        (None, None, 1),
        (1, -0.001, 1),
        (1, 0, 1.04),
        (0.001, 0, 1.04),
        (100, 100, 1.04),
        (10000, 10000, 1.04),
        (-1, 100, 1),
    ],
)
def test_handwritten_weak_market_car_opportunity_requires_actual_use_and_available_supply(
    production, consumption, balance, expected
):
    _assert_result(
        production,
        "paved_roads",
        {
            "market_automobile_total_consumption": consumption,
            "country_goods_automobiles_balance": balance,
        },
        [],
        expected,
    )


@pytest.mark.parametrize(
    "non_pop_source", ["public_motor_carriages", "truck_transport", "foreign_market_member"]
)
def test_market_opportunity_is_deliberately_weaker_than_observed_domestic_pop_benefit(
    production, non_pop_source
):
    # The scalar is actual total market consumption. This honest positive is
    # a limit witness: its direction is only a small market availability
    # opportunity, never evidence of this country's actual pop consumption.
    policy, _native, generated = production
    values = _values(
        {"market_automobile_total_consumption": 10, "country_goods_automobiles_balance": 1}
    )
    engine = _engine(values, [])
    engine["ROOT"]["actual_domestic_pop_automobile_consumption"] = 0
    engine["ROOT"]["total_consumption_source"] = non_pop_source
    result = pdx_eval.select(_overlay(generated, "paved_roads"), engine)
    assert result.delta == pytest.approx(1.04)
    assert decision_rules.evaluate(policy, values, is_ai=True)["paved_roads.ai_weight"][
        1
    ] == pytest.approx(1.04)


@pytest.mark.parametrize(
    ("technology", "changes", "groups", "expected"),
    [
        ("anarchism", {"anarchy_interest_group_support": True}, [_ig(1)], 1.04),
        (
            "anarchism",
            {"anarchy_interest_group_support": True, "current_cooperative_ownership": True},
            [_ig(1)],
            1.08,
        ),
        ("paved_roads", {"market_automobile_total_consumption": 1}, [], 1.04),
    ],
)
def test_country_root_player_off_and_research_does_not_imply_execution(
    production, technology, changes, groups, expected
):
    policy, _native, generated = production
    _assert_result(production, technology, changes, groups, expected)
    values = _values(changes)
    overlay = _overlay(generated, technology)
    assert pdx_eval.select(overlay, _engine(values, groups, is_ai=False)).operation is None
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    engine = _engine(values, groups)
    for key in (
        "candidate_selected",
        "law_enacted",
        "roads_built",
        "anarchism_researched",
        "authority",
        "is_in_government",
    ):
        engine["ROOT"][key] = True
    assert pdx_eval.select(overlay, engine).delta == pytest.approx(expected)
    engine["other_country"] = engine.pop("ROOT")
    engine["ROOT"] = {"is_ai": True}
    assert pdx_eval.select(overlay, engine).delta == 1


@pytest.mark.parametrize("groups", [True, [True], ["ig_trade_unions"]])
def test_ig_positive_boolean_or_label_cannot_replace_real_parameterized_objects(production, groups):
    _policy, _native, generated = production
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.select(_overlay(generated, "anarchism"), _engine(_values({}), groups))


def _tree(node: Any) -> Any:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.prefix, node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def test_original_costs_unlocks_effects_strategy_and_all_native_ast_are_preserved(production):
    _policy, native, generated = production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL | re.MULTILINE,
    )
    before, after = parse_text(native), parse_text(stripped)
    assert not before.errors
    assert not after.errors
    assert _tree(before.root) == _tree(after.root)


def test_typed_readers_prove_actual_information_identity_and_local_market_proxy_scope(production):
    policy, _native, generated = production
    readers = {reader.key: reader for reader in policy.readers}
    assert len(policy.consumer_programs) == 2
    assert len(readers) == 5
    ig = readers["anarchy_interest_group_support"]
    assert (ig.engine, ig.scope, ig.kind, ig.unit) == (
        "any_interest_group",
        "root",
        "boolean",
        "boolean",
    )
    assert dict(ig.parameters) == {"law": "law_anarchy"}
    assert readers["market_automobile_total_consumption"].path == ("market", "mg:automobiles")
    assert readers["market_automobile_total_consumption"].unit == "total_consumption_units"
    assert readers["country_goods_automobiles_balance"].path == ("market", "mg:automobiles")
    assert readers["country_goods_automobiles_balance"].unit == "sell_minus_buy_orders"
    assert {rule.contribution_group for rule in policy.rules} == {
        "supported_anarchy_option",
        "market_automobile_opportunity",
    }
    assert "law_stance" in _overlay(generated, "anarchism")
    assert "law_enactment_stance" not in _overlay(generated, "anarchism")
    assert "any_political_movement" not in _overlay(generated, "anarchism")
    assert "actual_domestic_pop_automobile_consumption" not in _overlay(generated, "paved_roads")


def test_disabled_module_emits_no_overrides(production):
    policy, _native, _generated = production
    adapters = decision_adapters.load()
    selected = replace(
        adapters, policies=((SOURCE, policy),), initial_values=(), scalar_values=(), supply=None
    )
    files, _ = decision_adapters.build(
        selected,
        texts=decision_adapters.read_inputs(adapters),
        enabled_domains=frozenset(),
    )
    assert files == {}
