"""Company local opportunities: typed queries, native provenance and real objects."""

import hashlib
import re
from pathlib import Path
from typing import Any, cast

import pytest

from pdx import company_observations as queries
from pdx import config
from pdx.parser import parse_text
from pdx.situated import pdx_eval
from pdx.textio import normalized_text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "engine", "parameters", "expected"),
    [
        (
            queries.RailInfrastructure(),
            "any_scope_state",
            {"company_query": "rail_infrastructure"},
            "any_scope_state = { any_scope_building = { is_building_type = building_railway level >= 1 } infrastructure_delta < 0 }",
        ),
        (
            queries.RailInfrastructure(0.25),
            "any_scope_state",
            {"company_query": "rail_infrastructure", "minimum_price": "0.25"},
            "any_scope_state = { any_scope_building = { is_building_type = building_railway level >= 1 } infrastructure_delta < 0 sg:transportation = { state_goods_pricier > 0.25 } }",
        ),
        (
            queries.PowerScarcity(0.5),
            "any_scope_state",
            {"company_query": "power_scarcity", "minimum_price": "0.5"},
            "any_scope_state = { any_scope_building = { is_building_type = building_power_plant level >= 1 } sg:electricity = { state_goods_pricier > 0.5 } }",
        ),
        (
            queries.PortMethod("pm_industrial_port"),
            "any_scope_building",
            {"company_query": "port_method", "method": "pm_industrial_port"},
            "any_scope_building = { is_building_type = building_port has_active_production_method = pm_industrial_port level >= 1 }",
        ),
    ],
)
def test_reader_round_trip_and_handwritten_templates(query, engine, parameters, expected):
    assert queries.from_reader(engine, parameters) == query
    assert queries.render(query) == expected
    spec = queries.reader_spec(query)
    assert spec["engine"] == engine
    assert spec["parameters"] == parameters
    assert spec["scope"] == "root"
    assert spec["kind"] == spec["unit"] == "boolean"
    assert not parse_text(expected).errors


@pytest.mark.unit
@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("any_scope_state", {}),
        ("any_scope_state", {"company_query": "power_scarcity"}),
        ("any_scope_state", {"company_query": "rail_infrastructure", "country": "foreign"}),
        ("any_scope_state", {"company_query": "power_scarcity", "minimum_price": "0"}),
        ("any_scope_state", {"company_query": "power_scarcity", "minimum_price": "0.76"}),
        ("any_scope_state", {"company_query": "power_scarcity", "minimum_price": ".25"}),
        ("any_scope_state", {"company_query": "power_scarcity", "minimum_price": "NaN"}),
        ("any_scope_state", {"company_query": "power_scarcity", "minimum_price": "1e-1"}),
        ("any_scope_state", {"company_query": "power_scarcity", "minimum_price": True}),
        (
            "any_scope_state",
            {"company_query": "power_scarcity", "minimum_price": "0.25 } always=yes"},
        ),
        ("any_scope_building", {"company_query": "port_method", "method": "pm_anchorage"}),
        ("any_scope_building", {"company_query": "port_method", "method": "pm_unknown"}),
        (
            "any_scope_building",
            {"company_query": "port_method", "method": "pm_basic_port", "level": "0"},
        ),
        ("any_scope_state", {"company_query": "port_method", "method": "pm_basic_port"}),
        ("any_scope_building", {"company_query": "rail_infrastructure"}),
    ],
)
def test_reader_boundary_rejects_extra_scopes_bad_units_and_unproductive_pm(engine, parameters):
    with pytest.raises(ValueError):
        queries.from_reader(engine, cast("Any", parameters))


@pytest.mark.unit
@pytest.mark.parametrize("value", [True, False, 0, -0.1, 0.751, float("nan"), float("inf"), "0.25"])
def test_typed_price_boundary_is_finite_numeric_proportional_threshold(value):
    with pytest.raises(ValueError):
        queries.render(queries.PowerScarcity(cast("Any", value)))


@pytest.mark.unit
def test_rendering_has_no_io_and_cannot_accept_unregistered_dataclasses(monkeypatch):
    def fail(*_args, **_kwargs):
        pytest.fail("pure query rendering attempted filesystem I/O")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)
    assert queries.render(
        queries.from_reader("any_scope_state", {"company_query": "rail_infrastructure"})
    )
    with pytest.raises(ValueError):
        queries.render(cast("Any", object()))


def _building(kind="building_railway", method=None, level=1):
    result = {
        "is_building_type": {
            (("argument", "building_railway"),): kind == "building_railway",
            (("argument", "building_power_plant"),): kind == "building_power_plant",
            (("argument", "building_port"),): kind == "building_port",
        },
        "level": level,
    }
    if method is not None:
        result["has_active_production_method"] = {
            (("argument", name),): method == name for name in queries.PORT_METHODS
        }
    return result


def _evaluate(query, root, **decoys):
    parsed = parse_text("ROOT = { " + queries.render(query) + " }")
    assert not parsed.errors
    return pdx_eval.condition(parsed.root, {"ROOT": root, **decoys})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (None, None),
        ([], False),
        ([{}], None),
        ([{"any_scope_building": [], "infrastructure_delta": -1}], False),
        ([{"any_scope_building": [_building()], "infrastructure_delta": 0}], False),
        ([{"any_scope_building": [_building()], "infrastructure_delta": -0.01}], True),
        ([{"any_scope_building": [_building(level=0)], "infrastructure_delta": -1}], False),
        ([{"any_scope_building": [_building("building_port")], "infrastructure_delta": -1}], False),
    ],
)
def test_rail_need_is_owned_existing_capacity_in_same_state(states, expected):
    decoy = {"any_scope_building": [_building()], "infrastructure_delta": -100}
    assert (
        _evaluate(
            queries.RailInfrastructure(), {"any_scope_state": states}, any_scope_state=[decoy]
        )
        is expected
    )


@pytest.mark.unit
def test_rail_high_tier_cannot_pool_deficit_and_price_from_different_states():
    deficit = {
        "any_scope_building": [_building()],
        "infrastructure_delta": -1,
        "sg:transportation": {"state_goods_pricier": 0.1},
    }
    costly = {
        "any_scope_building": [_building()],
        "infrastructure_delta": 0,
        "sg:transportation": {"state_goods_pricier": 0.6},
    }
    query = queries.RailInfrastructure(0.25)
    assert _evaluate(query, {"any_scope_state": [deficit, costly]}) is False
    assert (
        _evaluate(
            query,
            {"any_scope_state": [{**deficit, "sg:transportation": {"state_goods_pricier": 0.25}}]},
        )
        is False
    )
    assert (
        _evaluate(
            query,
            {"any_scope_state": [{**deficit, "sg:transportation": {"state_goods_pricier": 0.251}}]},
        )
        is True
    )
    assert (
        _evaluate(
            query,
            {
                "any_scope_state": [
                    {"any_scope_building": [_building()], "infrastructure_delta": -1}
                ]
            },
        )
        is None
    )


@pytest.mark.unit
def test_power_local_price_and_owned_power_plant_must_share_state():
    query = queries.PowerScarcity(0.25)
    plant = {
        "any_scope_building": [_building("building_power_plant")],
        "sg:electricity": {"state_goods_pricier": 0.1},
    }
    expensive = {"any_scope_building": [], "sg:electricity": {"state_goods_pricier": 0.6}}
    assert _evaluate(query, {"any_scope_state": [plant, expensive]}) is False
    assert (
        _evaluate(
            query, {"any_scope_state": [{**plant, "sg:electricity": {"state_goods_pricier": 0.3}}]}
        )
        is True
    )
    assert (
        _evaluate(
            query,
            {
                "any_scope_state": [plant],
                "market": {"mg:electricity": {"market_goods_pricier": 0.75}},
            },
        )
        is False
    )


@pytest.mark.unit
def test_port_method_requires_owned_same_building_type_method_and_positive_level():
    query = queries.PortMethod("pm_basic_port")
    assert (
        _evaluate(query, {"any_scope_building": [_building("building_port", "pm_basic_port")]})
        is True
    )
    assert (
        _evaluate(query, {"any_scope_building": [_building("building_port", "pm_anchorage")]})
        is False
    )
    assert (
        _evaluate(query, {"any_scope_building": [_building("building_port", "pm_basic_port", 0)]})
        is False
    )
    assert (
        _evaluate(
            query,
            {
                "any_scope_building": [
                    _building("building_port", "pm_modern_port"),
                    _building("building_power_plant", "pm_basic_port"),
                ]
            },
        )
        is False
    )
    assert (
        _evaluate(
            query,
            {"any_scope_building": []},
            any_scope_building=[_building("building_port", "pm_basic_port")],
        )
        is False
    )


@pytest.fixture(scope="module")
def native_texts():
    if not config.GAME.is_dir():
        pytest.skip("locked Victoria 3 unavailable")
    return {
        source: (config.GAME / source).read_text(encoding="utf-8-sig")
        for source in queries.SOURCE_HASHES
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    "query",
    [
        queries.RailInfrastructure(),
        queries.RailInfrastructure(0.25),
        queries.PowerScarcity(0.5),
        queries.PortMethod("pm_basic_port"),
        queries.PortMethod("pm_modern_port"),
    ],
)
def test_current_native_chain_has_complete_hash_and_object_transition_provenance(
    native_texts, query
):
    compiled = queries.compile_query(query, native_texts)
    assert compiled.expression == queries.render(query)
    assert compiled.actor == "country"
    assert compiled.kind == "boolean"
    assert compiled.world_scans == 0
    assert compiled.references
    assert (
        "owned_states" in compiled.local_collections
        or "owned_buildings" in compiled.local_collections
    )
    assert set(dict(compiled.source_hashes)) == set(queries.required_sources(query))
    assert "missing_collection=unknown" in compiled.unknown_policy


@pytest.mark.integration
@pytest.mark.parametrize(
    "damage",
    ["missing", "hash", "false_collection_chain", "false_price_scope", "false_port_recipe"],
)
def test_missing_or_rehashed_broken_native_type_chains_cannot_authorize_query(
    native_texts, monkeypatch, damage
):
    texts = dict(native_texts)
    query = (
        queries.PortMethod("pm_basic_port")
        if damage == "false_port_recipe"
        else queries.RailInfrastructure(0.25)
    )
    source = queries.required_sources(query)[0]
    if damage == "missing":
        texts.pop(source)
    elif damage == "hash":
        texts[source] += "\n# drift\n"
    else:
        source, old, new = {
            "false_collection_chain": (
                "common/company_types/00_companies_soi.txt",
                "level >= 5",
                "level >= 6",
            ),
            "false_price_scope": (
                "common/buildings/11_private_infrastructure.txt",
                "sg:transportation",
                "sg:gold",
            ),
            "false_port_recipe": (
                "common/production_methods/11_private_infrastructure.txt",
                "goods_output_merchant_marine_add = 9",
                "goods_output_gold_add = 9",
            ),
        }[damage]
        assert old in texts[source]
        texts[source] = texts[source].replace(old, new)
        monkeypatch.setitem(
            queries.source_hashes(),
            source,
            hashlib.sha256(normalized_text(texts[source]).encode()).hexdigest(),
        )
    with pytest.raises(ValueError):
        queries.compile_query(query, texts)


@pytest.mark.integration
@pytest.mark.parametrize("methods", ["", "pm_early_trains", "pm_early_trains pm_early_trains"])
def test_rail_group_cannot_pass_vacuously_or_with_missing_or_duplicate_methods(
    native_texts, monkeypatch, methods
):
    texts = dict(native_texts)
    source = "common/production_method_groups/11_private_infrastructure.txt"
    texts[source], count = re.subn(
        r"(pmg_base_building_railway\s*=\s*\{.*?production_methods\s*=\s*)\{[^}]*\}",
        lambda match: match[1] + "{ " + methods + " }",
        texts[source],
        count=1,
        flags=re.DOTALL,
    )
    assert count == 1
    monkeypatch.setitem(
        queries.source_hashes(),
        source,
        hashlib.sha256(normalized_text(texts[source]).encode()).hexdigest(),
    )
    with pytest.raises(ValueError, match="铁路"):
        queries.compile_query(queries.RailInfrastructure(), texts)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("building", "tier", "expected"),
    [
        (
            "building_gold_mine",
            "base",
            "any_scope_building = { is_building_type = building_gold_mine weekly_profit > 0 occupancy >= 0.75 level >= 1 }",
        ),
        (
            "building_gold_mine",
            "strong",
            "any_scope_building = { is_building_type = building_gold_mine weekly_profit > 0 cash_reserves_ratio > 0.5 occupancy >= 0.9 level >= 1 }",
        ),
        (
            "building_trade_center",
            "base",
            "any_scope_building = { is_building_type = building_trade_center weekly_profit > 0 occupancy >= 0.75 level >= 1 }",
        ),
        (
            "building_trade_center",
            "strong",
            "any_scope_building = { is_building_type = building_trade_center weekly_profit > 0 cash_reserves_ratio > 0.5 occupancy >= 0.9 level >= 1 }",
        ),
    ],
)
def test_existing_business_is_a_finite_real_operation_not_a_capacity_shortage(
    building, tier, expected
):
    params = {"company_query": "existing_business", "building": building, "tier": tier}
    query = queries.from_reader("any_scope_building", params)
    assert queries.render(query) == expected
    assert queries.reader_spec(query)["parameters"] == params


@pytest.mark.unit
@pytest.mark.parametrize(
    "changes",
    [
        {"building": "building_gold_field"},
        {"building": "building_railway"},
        {"building": "building_gold_mine } always = yes"},
        {"tier": "high"},
        {"tier": True},
        {"minimum_level": "10"},
        {"country": "foreign"},
        {"weekly_profit": "0"},
    ],
)
def test_business_reader_accepts_only_two_fixed_building_ids_and_tiers(changes):
    params = {
        "company_query": "existing_business",
        "building": "building_gold_mine",
        "tier": "base",
        **changes,
    }
    with pytest.raises(ValueError):
        queries.from_reader("any_scope_building", cast("Any", params))


@pytest.mark.unit
@pytest.mark.parametrize("building", [None, [], True, "building_gold_field"])
def test_typed_business_rejects_nonidentity_buildings(building):
    with pytest.raises(ValueError):
        queries.render(queries.ExistingBusiness(cast("Any", building)))


@pytest.mark.unit
@pytest.mark.parametrize("strong", [0, 1, "true", None])
def test_typed_business_tier_is_an_exact_boolean(strong):
    with pytest.raises(ValueError):
        queries.render(queries.ExistingBusiness("building_gold_mine", cast("Any", strong)))


@pytest.mark.unit
@pytest.mark.parametrize("building", ["building_gold_mine", "building_trade_center"])
@pytest.mark.parametrize(
    ("profit", "occupancy", "cash", "level", "base", "strong"),
    [
        (1, 0.75, 0.6, 1, True, False),
        (1, 0.9, 0.5, 1, True, False),
        (1, 0.9, 0.501, 1, True, True),
        (0, 1, 1, 1, False, False),
        (-1, 1, 1, 1, False, False),
        (1, 0.749, 1, 1, False, False),
        (1, 0.9, None, 1, True, None),
        (None, 0.9, 1, 1, None, None),
        (1, 0.9, 1, 0, False, False),
    ],
)
def test_business_tiers_use_same_owned_positive_profit_capacity_and_cash(
    building, profit, occupancy, cash, level, base, strong
):
    obj = {
        "is_building_type": {(("argument", building),): True},
        "weekly_profit": profit,
        "occupancy": occupancy,
        "cash_reserves_ratio": cash,
        "level": level,
    }
    for tier, expected in (("base", base), ("strong", strong)):
        query = queries.from_reader(
            "any_scope_building",
            {"company_query": "existing_business", "building": building, "tier": tier},
        )
        assert _evaluate(query, {"any_scope_building": [obj]}) is expected
        assert _evaluate(query, {"any_scope_building": []}, any_scope_building=[obj]) is False


@pytest.mark.unit
def test_business_high_tier_does_not_pool_profit_and_cash_from_distinct_operations():
    query = queries.ExistingBusiness("building_gold_mine", True)
    profitable = {
        "is_building_type": {(("argument", "building_gold_mine"),): True},
        "weekly_profit": 1,
        "occupancy": 0.9,
        "cash_reserves_ratio": 0.1,
        "level": 1,
    }
    wealthy = {**profitable, "weekly_profit": -1, "cash_reserves_ratio": 1}
    assert _evaluate(query, {"any_scope_building": [profitable, wealthy]}) is False
    assert (
        _evaluate(query, {"any_scope_building": [{**profitable, "cash_reserves_ratio": 0.6}]})
        is True
    )


@pytest.mark.integration
@pytest.mark.parametrize("building", ["building_gold_mine", "building_trade_center"])
def test_current_business_query_compiles_full_operating_and_production_chain(
    native_texts, building
):
    query = queries.from_reader(
        "any_scope_building",
        {"company_query": "existing_business", "building": building, "tier": "strong"},
    )
    compiled = queries.compile_query(query, native_texts)
    assert compiled.expression == queries.render(query)
    assert compiled.local_collections == ("owned_buildings",)
    assert any("weekly_profit" in item for item in compiled.scope_chain)


@pytest.mark.integration
@pytest.mark.parametrize(
    "damage", ["gold_minting", "gold_input", "trade_service", "business_template"]
)
def test_rehashed_broken_gold_minting_inputs_and_trade_service_cannot_authorize_business(
    native_texts, monkeypatch, damage
):
    texts = dict(native_texts)
    source, old, new = {
        "gold_minting": (
            "common/production_methods/03_mines.txt",
            "country_minting_add = 250",
            "country_minting_add = 0",
        ),
        "gold_input": (
            "common/production_methods/03_mines.txt",
            "goods_input_tools_add = 5",
            "goods_input_wood_add = 5",
        ),
        "trade_service": (
            "common/production_methods/11_private_infrastructure.txt",
            "state_trade_capacity_add = 10",
            "state_trade_capacity_add = 0",
        ),
        "business_template": (
            "common/journal_entries/00_opium.txt",
            "weekly_profit > 0",
            "weekly_profit < 0",
        ),
    }[damage]
    assert old in texts[source]
    texts[source] = texts[source].replace(old, new)
    monkeypatch.setitem(
        queries.source_hashes(),
        source,
        hashlib.sha256(normalized_text(texts[source]).encode()).hexdigest(),
    )
    building = "building_trade_center" if damage == "trade_service" else "building_gold_mine"
    query = queries.from_reader(
        "any_scope_building",
        {"company_query": "existing_business", "building": building, "tier": "base"},
    )
    with pytest.raises(ValueError):
        queries.compile_query(query, texts)


@pytest.mark.unit
@pytest.mark.parametrize("strong", [False, True])
def test_trade_pressure_is_explicit_finite_query_and_keeps_positive_business(strong):
    query = queries.TradeBusinessPressure(strong)
    params = {"company_query": "trade_business_pressure", "tier": "strong" if strong else "base"}
    assert queries.from_reader("any_scope_building", params) == query
    assert queries.reader_spec(query)["parameters"] == params
    assert (
        queries.render(query)
        == "any_scope_building = { is_building_type = building_trade_center level >= 1 weekly_profit < 0"
        + (" cash_reserves_ratio < 0.25" if strong else "")
        + " }"
    )
    positive = queries.render(queries.ExistingBusiness("building_trade_center", strong))
    assert "weekly_profit > 0" in positive
    assert "occupancy >=" in positive
    for changes in ({"tier": "high"}, {"country": "foreign"}, {"building": "building_gold_mine"}):
        with pytest.raises(ValueError):
            queries.from_reader("any_scope_building", {**params, **changes})


def _trade(profit=-1, cash=0.1, level=1):
    return {
        "is_building_type": {(("argument", "building_trade_center"),): True},
        "level": level,
        "weekly_profit": profit,
        "cash_reserves_ratio": cash,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("members", "base", "strong"),
    [
        (None, None, None),
        ([], False, False),
        ([{}], None, None),
        ([_trade()], True, True),
        ([_trade(0)], False, False),
        ([_trade(1)], False, False),
        ([_trade(cash=0.25)], True, False),
        ([_trade(cash=None)], True, None),
        ([_trade(profit=None)], None, None),
        ([_trade(level=0)], False, False),
        ([_trade(cash=0.8), _trade(profit=1)], True, False),
        ([_trade(cash=0.8), {}], True, None),
    ],
)
def test_trade_pressure_same_member_unknown_and_finite_boundaries(members, base, strong):
    root = {"any_scope_building": members}
    assert _evaluate(queries.TradeBusinessPressure(), root) is base
    assert _evaluate(queries.TradeBusinessPressure(True), root) is strong


@pytest.mark.integration
@pytest.mark.parametrize("strong", [False, True])
def test_trade_pressure_locks_native_numeric_reader_sources_and_actual_chain(native_texts, strong):
    query = queries.TradeBusinessPressure(strong)
    result = queries.compile_query(query, native_texts)
    assert result.local_collections == ("owned_buildings",)
    assert result.world_scans == 0
    assert "building:weekly_profit[currency_per_week]<0" in result.scope_chain
    assert result.unknown_policy == queries.UNKNOWN_POLICY
    broken = dict(native_texts)
    source = "common/journal_entries/00_opium.txt"
    broken[source] += "# drift"
    with pytest.raises(ValueError, match="漂移"):
        queries.compile_query(query, broken)


@pytest.mark.integration
@pytest.mark.parametrize("company", ["company_panama_company", "company_suez_company"])
def test_full_trade_company_program_combines_port_and_loss_with_actual_objects(company):
    from dataclasses import replace

    from pdx import company_sectors, decision_adapters, decision_rules
    from pdx.situated import programs

    data = company_sectors.load_baseline()
    profile = data["profiles"][company]
    original = dict(decision_adapters.load().policies)[profile["source"]]
    rules = tuple(r for r in original.rules if r.field == (company, "ai_weight"))
    keys = {key for rule in rules for key in rule.input_keys()}
    policy = programs.enable(
        replace(
            original,
            rules=rules,
            readers=tuple(r for r in original.readers if r.key in keys),
            enabled_domains=frozenset(r.domain for r in rules),
            semantic_ir=(),
            consumer_programs=(),
        ),
        source=profile["source"],
    )
    text = (config.GAME / profile["source"]).read_text(encoding="utf-8-sig")
    patched = decision_rules.patch(
        text,
        policy,
        baseline=text,
        default_strategy=False,
        reader_words=frozenset(
            {r.engine for r in policy.readers}
            | {x for r in policy.readers for x in r.path}
            | {"mg:grain"}
        ),
    )
    overlay = pdx_eval.marked_block(patched, policy.consumer_programs[0].action_id)
    assert (
        len([r for r in rules if r.contribution_group == "company_trade_operating_pressure"]) == 2
    )
    base = {reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers}
    port = {
        "is_building_type": {
            (("argument", "building_trade_center"),): False,
            (("argument", "building_port"),): True,
        },
        "level": 1,
        "has_active_production_method": {
            (("argument", "pm_basic_port"),): True,
            (("argument", "pm_industrial_port"),): False,
            (("argument", "pm_modern_port"),): False,
        },
    }
    for members, loss, low_cash, expected in (
        ([port], False, False, 1.12),
        ([port, _trade(cash=0.8)], True, False, 1.07),
        ([port, _trade()], True, True, 1.02),
        ([port, _trade(cash=0.8), _trade(profit=1)], True, False, 1.07),
    ):
        values = {
            **base,
            "company_port_basic": True,
            "country_goods_merchant_marine_balance": -1,
            "company_trade_loss": loss,
            "company_trade_loss_low_cash": low_cash,
        }
        assert decision_rules.evaluate_ir(policy, values, is_ai=True)[f"{company}.ai_weight"][
            1
        ] == pytest.approx(expected)
        root: dict[str, Any] = {
            "is_ai": True,
            "in_default": False,
            "any_scope_building": members,
            "market": {},
        }
        # Literal independent market values keep every unrelated input neutral.
        for good in ("merchant_marine", "clippers", "steamers", "coal", "oil"):
            root["market"][f"mg:{good}"] = {
                "market_goods_delta": -1 if good == "merchant_marine" else 0,
                "market_goods_pricier": 0,
            }
        actual = pdx_eval.select(overlay, {"ROOT": root})
        assert actual.delta == pytest.approx(expected)
        root["is_ai"] = False
        assert pdx_eval.select(overlay, {"ROOT": root}).operation is None
    assert (
        decision_rules.patch(
            text, policy, baseline=text, default_strategy=False, enabled_domains=frozenset()
        )
        == text
    )
    # A healthy operation A may coexist with a loss-making operation B.
    healthy = {**_trade(profit=1, cash=0.8), "occupancy": 0.95}
    values = {
        **base,
        "company_trade_need": True,
        "company_trade_pressure": True,
        "company_trade_loss": True,
        "company_trade_loss_low_cash": True,
    }
    root = {
        "is_ai": True,
        "in_default": False,
        "any_scope_building": [healthy, _trade()],
        "market": {},
    }
    expected = 1.1  # strongest business opportunity .20 minus operating risk .10
    assert decision_rules.evaluate_ir(policy, values, is_ai=True)[f"{company}.ai_weight"][
        1
    ] == pytest.approx(expected)
    assert pdx_eval.select(overlay, {"ROOT": root}).delta == pytest.approx(expected)
    # Actual native nonpositive scores remain nonpositive through positive scale.
    from pdx.model import Assignment, Block, Scalar

    definition = parse_text(patched).root.first(company)
    assert definition is not None
    assert isinstance(definition.value, Block)
    weight = definition.value.first("ai_weight")
    assert weight is not None
    assert isinstance(weight.value, Block)
    for native in (0, -3, 3):
        import copy

        numeric = copy.deepcopy(weight.value)
        initial = numeric.first("value")
        assert initial is not None
        initial.value = Scalar(str(native))
        assert pdx_eval._numeric_value(
            Assignment("multiply", "=", numeric), {"ROOT": root}
        ) == pytest.approx(native * expected)
    # Removing only our marker preserves native history/slots/refusal/tails.
    restored = re.sub(
        r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
        "",
        patched,
        flags=re.MULTILINE | re.DOTALL,
    )

    def tree(node):
        from pdx.model import Assignment, Scalar

        if isinstance(node, Scalar):
            return node.text, node.quoted
        if isinstance(node, Assignment):
            return node.key, node.op, node.prefix, tree(node.value)
        assert isinstance(node, Block)
        return tuple(tree(x) for x in node.items)

    assert tree(parse_text(restored).root) == tree(parse_text(text).root)
