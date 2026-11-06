"""Exact art construction: real recipe, owner market and independent PDX witnesses."""

from __future__ import annotations

import copy
import hashlib
import re
import tomllib
from dataclasses import replace

import pytest

from pdx import building_opportunities, company_sectors, config, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs
from pdx.textio import normalized_text

SOURCE = "common/buildings/06_urban_center.txt"
FIELD = ("building_art_academy", "ai_value")
PINNED = "0e29718640dbabdbc6748d2a9e7f7e5f88aa053eafcb84a4cc0927846c08f5b9"


@pytest.fixture(scope="module")
def raw():
    return tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))


def test_exact_registration_reuses_all_mandatory_art_methods_and_owner_context(raw):
    baseline = company_sectors.load_baseline()
    derived = building_opportunities.derive(raw, baseline)
    art = [r for r in derived["rules"] if r["field"] == ".".join(FIELD)]
    assert not any(r["field"] == ".".join(FIELD) for r in raw["rules"])
    assert len(art) == 4
    assert [r["value"] for r in art] == [1.08, 1.12, 0.85, 0.9]
    assert art[0]["conditions"] == [
        {"fact": "state_owner_fine_art_balance", "op": "<", "value": 0.0}
    ]
    assert art[1]["conditions"] == [
        {"fact": "state_owner_fine_art_balance", "op": "<", "value": 0.0},
        {"fact": "state_owner_fine_art_price", "op": ">", "value": 0.25},
    ]
    assert raw["actors"][SOURCE] == ["owner"]
    assert derived["readers"]["state_owner_fine_art_balance"] == {
        "engine": "market_goods_delta",
        "scope": "root",
        "kind": "number",
        "unit": "sell_minus_buy_orders",
        "path": ["owner", "market", "mg:fine_art"],
    }
    sectors = [
        sector
        for profile in baseline["profiles"].values()
        for sector in profile["base_recipes"]
        if sector["id"] == "building_art_academy"
    ]
    assert sectors
    for sector in sectors:
        assert sector["source"] == SOURCE
        methods = [m for g in sector["groups"] if g["base"] for m in g["methods"]]
        assert {m["id"] for m in methods} == {
            "pm_traditional_art",
            "pm_realist_art",
            "pm_photographic_art",
            "pm_film_art",
        }
        assert all(m["outputs"] == ["fine_art"] for m in methods)


def test_numeric_parameter_api_remains_independent_of_explicit_registration():
    assert building_opportunities.load_parameters() == {
        "priority_base": 80000.0,
        "shortage_balance": 0.0,
        "output_price_threshold": 0.25,
        "demand_multiplier": 1.08,
        "pressure_multiplier": 1.12,
        "default_multiplier": 0.85,
        "infrastructure_multiplier": 0.90,
    }


@pytest.mark.parametrize("damage", ["missing_source", "hash", "actor", "seed", "foreign_source"])
def test_registered_art_source_context_and_single_writer_fail_closed(raw, damage):
    broken = copy.deepcopy(raw)
    if damage == "missing_source":
        del broken["sources"][SOURCE]
    elif damage == "hash":
        broken["sources"][SOURCE] = "0" * 64
    elif damage == "actor":
        broken["actors"][SOURCE] = []
    else:
        broken["rules"].append(
            {
                "source": SOURCE if damage == "seed" else "common/buildings/01_industry.txt",
                "field": ".".join(FIELD),
            }
        )
    with pytest.raises(ValueError):
        building_opportunities.derive(broken)


@pytest.mark.parametrize(
    "damage", ["duplicate", "arbitrary_field", "arbitrary_source", "extra_key"]
)
def test_registration_rejects_arbitrary_duplicate_or_extended_records(
    tmp_path, monkeypatch, raw, damage
):
    text = building_opportunities.PARAMETERS.read_text(encoding="utf-8")
    if damage == "duplicate":
        text += (
            '\n[[consumers]]\nsource = "' + SOURCE + '"\nfield = "building_art_academy.ai_value"\n'
        )
    elif damage == "arbitrary_field":
        text = text.replace("building_art_academy.ai_value", "building_urban_center.ai_value")
    elif damage == "arbitrary_source":
        text = text.replace(SOURCE, "common/buildings/01_industry.txt")
    else:
        text = text.replace(
            'field = "building_art_academy.ai_value"',
            'field = "building_art_academy.ai_value"\nvalue = 1.08',
        )
    path = tmp_path / "parameters.toml"
    path.write_text(text, encoding="utf-8", newline="\n")
    monkeypatch.setattr(building_opportunities, "PARAMETERS", path)
    with pytest.raises(ValueError, match="消费者"):
        building_opportunities.derive(raw)


@pytest.fixture(scope="module")
def production():
    if not (config.GAME / SOURCE).is_file():
        pytest.skip("需要锁定原版完整消费者与配方原件")
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[SOURCE]
    assert original.native_root == "state"
    assert original.actor_path == ("owner",)
    rules = tuple(rule for rule in original.rules if rule.field == FIELD)
    keys = {key for rule in rules for key in rule.input_keys()}
    policy = programs.enable(
        replace(
            original,
            rules=rules,
            readers=tuple(r for r in original.readers if r.key in keys),
            semantic_ir=(),
            consumer_programs=(),
            enabled_domains=frozenset({"market"}),
        ),
        source=SOURCE,
    )
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        event_programs=(),
        acceptance_programs=(),
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _ = decision_adapters.build(selected, texts=inputs)
    return policy, files[SOURCE], selected, inputs


@pytest.mark.parametrize(
    ("balance", "price", "default", "infrastructure", "expected"),
    [
        (-1, None, None, None, 1.08),
        (-1, 0.25, False, 0, 1.08),
        (-1, 0.250001, False, 0, 1.12),
        (-1, 0.75, True, -1, 0.87),
        (-1, None, True, None, 0.93),
        (-1, None, None, -1, 0.98),
        (-1, None, True, -1, 0.83),
        (0, 0.75, False, 0, 1.0),
        (None, 0.75, False, 0, 1.0),
        (None, 0.75, True, -1, 0.75),
        (1, 0.75, False, 0, 1.0),
    ],
)
def test_hand_numbers_match_actual_production_pdx_with_independent_owner_facts(
    production, balance, price, default, infrastructure, expected
):
    policy, text, _, _ = production
    values = {
        "state_owner_fine_art_balance": balance,
        "state_owner_fine_art_price": price,
        "state_owner_default": default,
        "state_infrastructure": infrastructure,
    }
    root = {
        "owner": {
            "is_ai": True,
            "in_default": default,
            "taking_loans": True,
            "bureaucracy": -100,
            "literacy_rate": 0.01,
            "market": {
                "mg:fine_art": {"market_goods_delta": balance, "market_goods_pricier": price}
            },
        },
        "infrastructure_delta": infrastructure,
        "market": {"mg:fine_art": {"market_goods_delta": -999, "market_goods_pricier": 0.75}},
        "is_production_method_active": {"building_art_academy": {"pm_film_art": False}},
    }
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert reference.get(".".join(FIELD), ("", 1))[1] == pytest.approx(expected)
    program = policy.consumer_programs[0]
    generated = pdx_eval.select(pdx_eval.marked_block(text, program.action_id), {"ROOT": root})
    assert generated.delta == pytest.approx(expected)


def _shape(node):
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _shape(node.value)
    if isinstance(node, Block):
        return tuple(_shape(child) for child in node.items)
    if isinstance(node, Scalar):
        return str(node)
    return str(node)


def test_native_full_definition_order_romanticism_metternich_and_other_buildings_preserved(
    production,
):
    _, text, _, inputs = production
    native = normalized_text(inputs[SOURCE])
    assert hashlib.sha256(native.encode()).hexdigest() == PINNED
    restored = re.sub(
        r"\t\t# SITAI BEGIN information:building_art_academy\.ai_value\n.*?"
        r"\t\t# SITAI END information:building_art_academy\.ai_value\n",
        "",
        text,
        flags=re.DOTALL,
    )
    assert _shape(parse_text(restored).root) == _shape(parse_text(native).root)
    art = next(row.value for row in parse_text(native).top_assignments if row.key == FIELD[0])
    assert isinstance(art, Block)
    assert _shape(art.all("unlocking_technologies")[0].value) == ("romanticism",)
    score = art.all("ai_value")[0].value
    assert isinstance(score, Block)
    assert [row.key for row in score.assignments()] == ["value", "if", "if", "if"]
    assert _shape(score.all("value")[0].value) == "1000"
    assert "has_journal_entry = je_metternich" in native
    assert "add = 500" in native
    branches = score.all("if")
    for row, expected in zip(branches, ("500", "1000", "1000"), strict=True):
        assert isinstance(row.value, Block)
        addition = row.value.first("add")
        assert addition is not None
        assert str(addition.value) == expected
    assert "ai_ukraine_renaissance_accelerate" in native
    assert "is_homeland = cu:ukrainian" in native
    assert "ai_belarus_renaissance_accelerate" in native
    assert "is_homeland = cu:byelorussian" in native
    assert "has_journal_entry = je_tp_tsar_crown_of_perfection" in native
    assert "NOT = { has_variable = je_tp_tsar_crown_of_perfection_button_1_complete }" in native
    assert "is_capital = yes" in native
    assert text.count("# SITAI BEGIN") == 1


def test_player_disable_foreign_market_and_source_drift_counterexamples(production):
    policy, text, adapters, inputs = production
    values = {
        "state_owner_fine_art_balance": -1,
        "state_owner_fine_art_price": 0.75,
        "state_owner_default": True,
        "state_infrastructure": -1,
    }
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    program = policy.consumer_programs[0]
    branch = pdx_eval.marked_block(text, program.action_id)
    facts = {
        "ROOT": {
            "is_ai": True,
            "owner": {
                "is_ai": False,
                "market": {"mg:fine_art": {"market_goods_delta": -1, "market_goods_pricier": 0.75}},
            },
        }
    }
    assert pdx_eval.select(branch, facts).operation is None
    foreign = {
        "ROOT": {
            "owner": {"is_ai": True, "market": {}},
            "market": {"mg:fine_art": {"market_goods_delta": -1, "market_goods_pricier": 0.75}},
        },
        "scope:foreign_country": {"market": {"mg:fine_art": {"market_goods_delta": -1}}},
    }
    assert pdx_eval.select(branch, foreign).delta == 1
    files, _ = decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())
    assert files == {}
    broken = {**inputs, SOURCE: inputs[SOURCE] + "\n"}
    with pytest.raises(ValueError, match="原件漂移"):
        decision_adapters.build(adapters, texts=broken)
