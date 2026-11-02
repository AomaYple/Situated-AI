"""Ten reachable society slices with real owned collections and handwritten results.

Anarchism and paved roads retain native behavior: pre-research movement demand
and actual automobile consumption respectively remain unproved.
"""

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
ART = ("romanticism", "realism", "camera", "film")
PREVIOUS = {
    "realism": "pm_traditional_art",
    "camera": "pm_realist_art",
    "film": "pm_photographic_art",
}
MARKET = ("stock_exchange", "zeppelins")
TECHNOLOGIES = (
    *ART,
    *MARKET,
    "organized_sports",
    "multilateral_alliances",
    "international_relations",
    "international_trade",
)
QUERY_FACTS = {
    "own_state_market_exposure",
    "own_state_deep_market_exposure",
    "own_traditional_art",
    "own_realist_art",
    "own_photographic_art",
    "free_trade_movement_support",
    "mercantilism_movement_support",
}


def _field(technology: str) -> str:
    return f"{technology}.ai_weight"


def _program_id(technology: str) -> str:
    return "program_" + hashlib.sha256(f"{SOURCE}:{_field(technology)}".encode()).hexdigest()[:16]


@pytest.fixture(scope="module")
def production() -> tuple[Any, str, str]:
    adapters = decision_adapters.load()
    raw = dict(adapters.policies)[SOURCE]
    fields = {_field(technology) for technology in TECHNOLOGIES}
    rules = tuple(rule for rule in raw.rules if ".".join(rule.field) in fields)
    assert {".".join(rule.field) for rule in rules} == fields
    assert len(rules) == 23
    keys = frozenset(key for rule in rules for key in rule.input_keys())
    raw = replace(
        raw,
        rules=rules,
        readers=tuple(r for r in raw.readers if r.key in keys),
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
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policy, inputs[SOURCE], files[SOURCE]


def _building(
    method: str, *, level: float = 1, building: str = "building_art_academy"
) -> dict[str, object]:
    return {
        "is_building_type": {(("argument", building),): True},
        "has_active_production_method": {(("argument", method),): True},
        "level": level,
    }


def _movement(law: str, *, stance: float = 1, support: float = 0.10) -> dict[str, object]:
    return {
        "law_enactment_stance": {(("law", "law_type:" + law),): stance},
        "political_movement_support": support,
    }


def _values(changes: Mapping[str, object]) -> dict[str, object]:
    return {
        "country_goods_fine_art_balance": 0,
        "country_goods_fine_art_price": 0,
        "prestige": 0,
        "num_alliances": 0,
        "is_diplomatic_play_target": False,
        "is_diplomatic_play_initiator": False,
        "current_free_trade": False,
        "current_mercantilism": False,
        **dict.fromkeys(QUERY_FACTS, False),
        **changes,
    }


def _engine(
    values: Mapping[str, object],
    collections: Mapping[str, object] | None = None,
    *,
    is_ai: bool = True,
) -> dict[str, Any]:
    # Engine collections are real object lists, never the flat reference bools.
    root: dict[str, Any] = {
        "is_ai": is_ai,
        "market": {
            "mg:fine_art": {
                "market_goods_delta": values.get("country_goods_fine_art_balance"),
                "market_goods_pricier": values.get("country_goods_fine_art_price"),
            }
        },
        "prestige": values.get("prestige"),
        "num_alliances": values.get("num_alliances"),
        "is_diplomatic_play_target": values.get("is_diplomatic_play_target"),
        "is_diplomatic_play_initiator": values.get("is_diplomatic_play_initiator"),
        "has_law_or_variant": {
            (("argument", "law_type:law_free_trade"),): values.get("current_free_trade"),
            (("argument", "law_type:law_mercantilism"),): values.get("current_mercantilism"),
        },
        "any_scope_state": [],
        "any_scope_building": [],
        "any_political_movement": [],
    }
    root.update(collections or {})
    for key in (
        "candidate_selected",
        "building_completed",
        "law_enacted",
        "war",
        "default",
        "bureaucracy",
        "net_surplus",
    ):
        if key in values:
            root[key] = values[key]
    return {"ROOT": root}


def _overlay(text: str, technology: str) -> str:
    start = text.index(f"# SITAI BEGIN information:{_field(technology)}")
    end = text.index(f"# SITAI END information:{_field(technology)}", start)
    return "\n".join(text[start:end].splitlines()[1:])


def _assert_result(
    production,
    technology: str,
    changes: Mapping[str, object],
    collections: Mapping[str, object],
    expected: float,
):
    policy, _native, generated = production
    values = _values(changes)
    result = pdx_eval.select(_overlay(generated, technology), _engine(values, collections))
    assert (result.action_id, result.operation) == (_program_id(technology), "multiply")
    assert result.delta == pytest.approx(expected)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(_field(technology))
    if expected == 1:
        assert reference is None
    else:
        assert reference is not None
        assert reference[0] == _program_id(technology)
        assert reference[1] == pytest.approx(expected)
    return result


CASES: list[tuple[str, Mapping[str, object], Mapping[str, object], float]] = [
    (technology, changes, {}, expected)
    for technology in ART
    for changes, expected in (
        ({"country_goods_fine_art_balance": -1}, 1.08),
        ({"country_goods_fine_art_balance": -1, "country_goods_fine_art_price": 0.25}, 1.08),
        ({"country_goods_fine_art_balance": -1, "country_goods_fine_art_price": 0.251}, 1.12),
        ({"country_goods_fine_art_balance": 0, "country_goods_fine_art_price": 1}, 1),
        ({"country_goods_fine_art_balance": None, "country_goods_fine_art_price": 1}, 1),
        ({"country_goods_fine_art_balance": -1, "country_goods_fine_art_price": None}, 1.08),
        (
            {
                "country_goods_fine_art_balance": -1,
                "default": True,
                "war": True,
                "bureaucracy": -100,
                "net_surplus": -100,
                "paper_balance": -100,
                "tools_balance": -100,
                "electricity_balance": -100,
            },
            1.08,
        ),
    )
]
for technology, method in PREVIOUS.items():
    fact = {
        "realism": "own_traditional_art",
        "camera": "own_realist_art",
        "film": "own_photographic_art",
    }[technology]
    CASES += [
        (
            technology,
            {"country_goods_fine_art_balance": -1, fact: True},
            {"any_scope_building": [_building(method)]},
            1.12,
        ),
        (
            technology,
            {"country_goods_fine_art_balance": -1, "country_goods_fine_art_price": 0.3, fact: True},
            {"any_scope_building": [_building(method)]},
            1.16,
        ),
        (
            technology,
            {"country_goods_fine_art_balance": 0, fact: True},
            {"any_scope_building": [_building(method)]},
            1,
        ),
        (technology, {"country_goods_fine_art_balance": -1}, {"any_scope_building": []}, 1.08),
        (
            technology,
            {"country_goods_fine_art_balance": -1, fact: None},
            {"any_scope_building": None},
            1.08,
        ),
        (
            technology,
            {"country_goods_fine_art_balance": -1, fact: None},
            {"any_scope_building": [{}]},
            1.08,
        ),
        (
            technology,
            {"country_goods_fine_art_balance": -1, fact: None},
            {"any_scope_building": [_building(method, level=0)]},
            1.08,
        ),
        (
            technology,
            {"country_goods_fine_art_balance": -1, fact: None},
            {"any_scope_building": [_building(method, building="building_university")]},
            1.08,
        ),
    ]
CASES += [
    ("organized_sports", {"prestige": prestige}, {}, expected)
    for prestige, expected in (
        (0, 1),
        (49.999, 1),
        (50, 1.04),
        (99.999, 1.04),
        (100, 1.08),
        (None, 1),
        (-1, 1),
    )
]
CASES += [
    ("multilateral_alliances", changes, {}, expected)
    for changes, expected in (
        ({"num_alliances": 1}, 1.08),
        ({"num_alliances": 2}, 1.08),
        ({"is_diplomatic_play_target": True}, 1.08),
        ({"is_diplomatic_play_initiator": True}, 1.08),
        ({"is_diplomatic_play_target": True, "is_diplomatic_play_initiator": True}, 1.08),
        ({"num_alliances": 1, "is_diplomatic_play_target": True}, 1.16),
        ({"num_alliances": None, "is_diplomatic_play_initiator": True}, 1.08),
        (
            {
                "num_alliances": 1,
                "is_diplomatic_play_target": None,
                "is_diplomatic_play_initiator": None,
            },
            1.08,
        ),
        (
            {
                "num_alliances": None,
                "is_diplomatic_play_target": None,
                "is_diplomatic_play_initiator": None,
            },
            1,
        ),
        ({"war": True, "infamy": 100}, 1),
    )
]
CASES += [
    ("international_relations", changes, {}, expected)
    for changes, expected in (
        ({"is_diplomatic_play_target": True}, 1.08),
        ({"is_diplomatic_play_target": False}, 1),
        ({"is_diplomatic_play_target": None}, 1),
        ({"is_diplomatic_play_initiator": True, "war": True}, 1),
    )
]
CASES += [
    (technology, changes, {"any_scope_state": states}, expected)
    for technology in MARKET
    for changes, states, expected in (
        ({}, [], 1),
        ({}, [{"market_access": 1}], 1),
        ({"own_state_market_exposure": True}, [{"market_access": 0.999}], 1.06),
        ({"own_state_market_exposure": True}, [{"market_access": 0.9}], 1.06),
        (
            {"own_state_market_exposure": True, "own_state_deep_market_exposure": True},
            [{"market_access": 0.899}],
            1.10,
        ),
        (
            {"own_state_market_exposure": True, "own_state_deep_market_exposure": True},
            [{"market_access": 1}, {"market_access": 0.8}],
            1.10,
        ),
        ({"own_state_market_exposure": None, "own_state_deep_market_exposure": None}, None, 1),
        ({"own_state_market_exposure": None, "own_state_deep_market_exposure": None}, [{}], 1),
        (
            {"own_state_market_exposure": True, "own_state_deep_market_exposure": True},
            [{}, {"market_access": 0.8}],
            1.10,
        ),
    )
]
for law in ("free_trade", "mercantilism"):
    fact = law + "_movement_support"
    current = "current_" + law
    CASES += [
        ("international_trade", changes, {"any_political_movement": movements}, expected)
        for changes, movements, expected in (
            ({fact: True}, [_movement("law_" + law)], 1.08),
            ({fact: True, current: True}, [_movement("law_" + law)], 1),
            ({fact: True, current: None}, [_movement("law_" + law)], 1),
            ({}, [_movement("law_" + law, support=0.099)], 1),
            ({}, [_movement("law_" + law, stance=0)], 1),
            ({}, [_movement("law_" + law, stance=-1)], 1),
            ({fact: None}, [{}], 1),
            ({fact: None}, None, 1),
            ({fact: True}, [{}, _movement("law_" + law)], 1.08),
            ({}, [], 1),
        )
    ]
CASES += [
    (
        "international_trade",
        {"free_trade_movement_support": True, "mercantilism_movement_support": True},
        {"any_political_movement": [_movement("law_free_trade"), _movement("law_mercantilism")]},
        1.08,
    )
]


@pytest.mark.parametrize(("technology", "changes", "collections", "expected"), CASES)
def test_handwritten_business_values_match_reference_and_real_pdx_collections(
    production, technology, changes, collections, expected
):
    _assert_result(production, technology, changes, collections, expected)


@pytest.mark.parametrize(
    ("technology", "fact", "future_method"),
    [
        ("realism", "own_traditional_art", "pm_realist_art"),
        ("camera", "own_realist_art", "pm_photographic_art"),
        ("film", "own_photographic_art", "pm_film_art"),
    ],
)
def test_candidate_new_method_does_not_supply_observed_previous_method(
    production, technology, fact, future_method
):
    _assert_result(
        production,
        technology,
        {"country_goods_fine_art_balance": -1, fact: None},
        {"any_scope_building": [_building(future_method)]},
        1.08,
    )


@pytest.mark.parametrize("other_law", ["law_agrarianism", "law_protectionism"])
def test_unrelated_law_stance_does_not_supply_trade_policy_identity(production, other_law):
    _assert_result(
        production,
        "international_trade",
        {"free_trade_movement_support": None, "mercantilism_movement_support": None},
        {"any_political_movement": [_movement(other_law)]},
        1,
    )


@pytest.mark.parametrize("adopted", ["free_trade", "mercantilism"])
def test_adopted_trade_policy_exits_only_its_own_supported_branch(production, adopted):
    _assert_result(
        production,
        "international_trade",
        {
            "free_trade_movement_support": True,
            "mercantilism_movement_support": True,
            "current_" + adopted: True,
        },
        {"any_political_movement": [_movement("law_free_trade"), _movement("law_mercantilism")]},
        1.08,
    )


POSITIVES = [
    *((technology, {"country_goods_fine_art_balance": -1}, {}, 1.08) for technology in ART),
    *(
        (
            technology,
            {"own_state_market_exposure": True},
            {"any_scope_state": [{"market_access": 0.95}]},
            1.06,
        )
        for technology in MARKET
    ),
    ("organized_sports", {"prestige": 100}, {}, 1.08),
    ("multilateral_alliances", {"num_alliances": 1, "is_diplomatic_play_target": True}, {}, 1.16),
    ("international_relations", {"is_diplomatic_play_target": True}, {}, 1.08),
    (
        "international_trade",
        {"free_trade_movement_support": True},
        {"any_political_movement": [_movement("law_free_trade")]},
        1.08,
    ),
]


@pytest.mark.parametrize(("technology", "changes", "collections", "expected"), POSITIVES)
def test_country_root_player_off_and_research_is_not_adoption(
    production, technology, changes, collections, expected
):
    policy, _native, generated = production
    result = _assert_result(production, technology, changes, collections, expected)
    values = _values(changes)
    overlay = _overlay(generated, technology)
    assert pdx_eval.select(overlay, _engine(values, collections, is_ai=False)).operation is None
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        pdx_eval.select(
            overlay,
            _engine(
                {
                    **values,
                    "candidate_selected": True,
                    "building_completed": True,
                    "law_enacted": True,
                },
                collections,
            ),
        )
        == result
    )
    facts = _engine(values, collections)
    facts["other_country"] = facts.pop("ROOT")
    facts["ROOT"] = {"is_ai": True}
    assert pdx_eval.select(overlay, facts).delta == 1


@pytest.mark.parametrize(
    ("technology", "engine"),
    [
        ("realism", "any_scope_building"),
        ("stock_exchange", "any_scope_state"),
        ("international_trade", "any_political_movement"),
    ],
)
def test_precomputed_boolean_cannot_replace_real_owned_collection(production, technology, engine):
    _policy, _native, generated = production
    facts = _engine(_values({"country_goods_fine_art_balance": -1}), {engine: True})
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.select(_overlay(generated, technology), facts)


def _tree(node: Any) -> Any:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def test_native_effects_prerequisites_cultures_strategy_and_other_fields_are_unchanged(
    production,
):
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


def test_all_ten_techs_have_real_native_effect_or_exact_unlocking_business(production):
    _policy, native, _generated = production
    root = parse_text(native).root
    effects = {
        **{technology: {"country_prestige_mult": 0.05} for technology in ART},
        "organized_sports": {"country_prestige_mult": 0.1},
        "stock_exchange": {"state_market_access_price_impact": 0.1},
        "zeppelins": {"state_market_access_price_impact": 0.05},
        "multilateral_alliances": {
            "country_infamy_generation_mult": -0.25,
            "country_diplomatic_play_maneuvers_mult": 0.5,
            "country_allow_multiple_alliances_bool": "yes",
        },
    }
    for technology, expected in effects.items():
        definition = root.first(technology)
        assert definition is not None
        assert isinstance(definition.value, Block)
        modifier = definition.value.first("modifier")
        assert modifier is not None
        assert isinstance(modifier.value, Block)
        observed = {}
        for assignment in modifier.value.assignments():
            assert isinstance(assignment.value, Scalar)
            value = assignment.value.unquoted
            observed[assignment.key] = value if value == "yes" else float(value)
        assert observed == expected
    for technology in ("international_trade", "international_relations"):
        definition = root.first(technology)
        assert definition is not None
        assert isinstance(definition.value, Block)
        assert definition.value.first("modifier") is None


def test_typed_reader_signatures_are_exact_and_do_not_hide_collection_or_payment_gates(production):
    policy, _native, generated = production
    assert len(policy.consumer_programs) == 10
    readers = {reader.key: reader for reader in policy.readers}
    for key in ("country_goods_fine_art_balance", "country_goods_fine_art_price"):
        assert readers[key].path == ("market", "mg:fine_art")
    assert readers["prestige"].unit == "prestige_points"
    assert readers["num_alliances"].unit == "alliance_count"
    assert all(readers[key].scope == "root" for key in readers)
    assert set(readers) == {
        "country_goods_fine_art_balance",
        "country_goods_fine_art_price",
        "prestige",
        "num_alliances",
        "is_diplomatic_play_target",
        "is_diplomatic_play_initiator",
        "current_free_trade",
        "current_mercantilism",
        *QUERY_FACTS,
    }
    for technology in ART:
        rules = [r for r in policy.rules if r.field == (technology, "ai_weight")]
        assert all(r.value > 1 for r in rules)
        assert any(r.input_keys() == {"country_goods_fine_art_balance"} for r in rules)
        assert "paper" not in _overlay(generated, technology)
    art_rules = [
        r
        for r in policy.rules
        if r.field[0] in PREVIOUS and r.contribution_group == "observed_art_base"
    ]
    assert len(art_rules) == 3
    assert (
        len({r.contribution_group for r in policy.rules if r.field[0] == "multilateral_alliances"})
        == 2
    )
    assert dict(readers["own_traditional_art"].parameters) == {
        "building": "building_art_academy",
        "method": "pm_traditional_art",
        "min_level": "1",
    }
    assert dict(readers["free_trade_movement_support"].parameters) == {
        "law": "law_free_trade",
        "minimum_support": "0.10",
    }


def test_disabled_module_emits_no_override(production):
    policy, _native, _generated = production
    adapters = decision_adapters.load()
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        initial_values=(),
        scalar_values=(),
        supply=None,
    )
    files, _ = decision_adapters.build(
        selected, texts=decision_adapters.read_inputs(adapters), enabled_domains=frozenset()
    )
    assert files == {}
