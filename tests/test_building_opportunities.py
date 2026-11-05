"""Independent recipe consensus and state-owner construction opportunity witnesses."""

import copy
import tomllib
from typing import Any

import pytest

from pdx import building_opportunities, company_sectors, config, decision_rules
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.unit
BUILDINGS = "common/buildings/fixture.txt"
GROUPS = "common/production_method_groups/fixture.txt"
METHODS = "common/production_methods/fixture.txt"


@pytest.fixture
def baseline():
    definitions = {
        "building_mine": "mining optional",
        "building_dual": "dual",
        "building_shipyard": "ships",
        "building_power": "power",
        "building_gold": "gold",
        "building_service": "service",
        "building_optional": "optional",
    }
    inputs = {
        "common/company_types/fixture.txt": "\n".join(
            f"company_{building} = {{ building_types = {{ {building} }} ai_weight = {{ value = 1 }} }}"
            for building in definitions
        ),
        BUILDINGS: "\n".join(
            f"{building} = {{ ai_value = 1 production_method_groups = {{ {groups} }} }}"
            for building, groups in definitions.items()
        ),
        GROUPS: """
mining = { production_methods = { pick pump } }
optional = { production_methods = { disabled luxury } }
dual = { production_methods = { combined } }
ships = { production_methods = { sailing steam } }
power = { production_methods = { electricity } }
gold = { production_methods = { gold } }
service = { production_methods = { disabled } }
""",
        METHODS: """
pick = { building_modifiers = { workforce_scaled = { goods_output_iron_add = 20 } } }
pump = { building_modifiers = { workforce_scaled = { goods_output_iron_add = 40 goods_output_coal_add = 1 } } }
disabled = { }
luxury = { building_modifiers = { workforce_scaled = { goods_output_luxury_clothes_add = 10 } } }
combined = { building_modifiers = { workforce_scaled = { goods_output_iron_add = 10 goods_output_coal_add = 10 } } }
sailing = { building_modifiers = { workforce_scaled = { goods_output_clippers_add = 10 } } }
steam = { building_modifiers = { workforce_scaled = { goods_output_steamers_add = 10 } } }
electricity = { building_modifiers = { workforce_scaled = { goods_output_electricity_add = 10 } } }
gold = { building_modifiers = { workforce_scaled = { goods_output_gold_add = 10 } } }
""",
        "common/goods/fixture.txt": "\n".join(
            f"{good} = {{ cost = 10 }}"
            for good in ("iron", "coal", "luxury_clothes", "clippers", "steamers")
        )
        + "\nelectricity = { cost = 10 local = yes }\ngold = { cost = 10 fixed_price = yes tradeable = no }",
        "common/defines/fixture.txt": "NAI = { COMPANY_TYPE_DEFAULT_BASE_WEIGHT = 1 }",
    }
    return company_sectors.derive(inputs)


@pytest.fixture
def adapters(baseline):
    return {
        "sources": {BUILDINGS: baseline["sources"][BUILDINGS]},
        "readers": {},
        "rules": [
            {"source": BUILDINGS, "field": f"{building}.ai_value"}
            for building in (
                "building_mine",
                "building_dual",
                "building_shipyard",
                "building_power",
                "building_gold",
                "building_service",
                "building_optional",
                "building_not_in_company_baseline",
            )
        ],
    }


def test_existing_building_shortage_has_an_independent_basic_opportunity(adapters, baseline):
    derived = building_opportunities.derive(adapters, baseline)
    rules = [
        rule
        for rule in derived["rules"]
        if rule["field"] == "building_mine.ai_value"
        and rule["contribution_group"] == "building_output_demand"
    ]
    assert [rule["value"] for rule in rules] == [1.08, 1.12]
    assert rules[0]["conditions"] == [{"fact": "state_owner_iron_balance", "op": "<", "value": 0.0}]
    assert rules[1]["conditions"] == [
        {"fact": "state_owner_iron_balance", "op": "<", "value": 0.0},
        {"fact": "state_owner_iron_price", "op": ">", "value": 0.25},
    ]
    assert {rule["contribution_group"] for rule in rules} == {"building_output_demand"}


def _derive(adapters, baseline, **kwargs):
    return building_opportunities.derive(adapters, baseline, **kwargs)


def _policy(derived, building):
    rows = [rule for rule in derived["rules"] if rule["field"] == f"{building}.ai_value"]
    keys = {condition["fact"] for rule in rows for condition in rule["conditions"]}
    readers = {key: value for key, value in derived["readers"].items() if key in keys}
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": derived["sources"][BUILDINGS],
            "domains": {"market": True},
            "actor_path": ["owner"],
            "readers": readers,
            "rules": [
                {key: value for key, value in row.items() if key != "source"} for row in rows
            ],
        },
        source_sha256="0" * 64,
    )
    return programs.enable(policy, source=BUILDINGS)


def _joint(derived, changes, expected, *, building="building_mine", is_ai=True, enabled=True):
    policy = _policy(derived, building)
    values = {reader.key: None for reader in policy.readers}
    values.update(changes)
    actual = decision_rules.evaluate(
        policy,
        values,
        is_ai=is_ai,
        enabled_domains=frozenset({"market"}) if enabled else frozenset(),
    ).get(f"{building}.ai_value")
    assert (actual[1] if actual else 1.0) == pytest.approx(expected)
    guards = {}
    readers = {reader.key: reader for reader in policy.readers}
    for rule in policy.rules:
        terms = []
        for condition in rule.conditions:
            reader = readers[condition.fact]
            term = reader.expression(condition.op, condition.value)
            for scope in reversed(reader.path):
                term = f"{scope} = {{ {term} }}"
            terms.append(f"ROOT = {{ {term} }}")
        if enabled:
            guards[rule.id] = " ".join(terms)
    text = programs.render(
        policy.consumer_programs[0],
        guards=guards,
        ai_guard="ROOT = { owner = { is_ai = yes } }",
        descriptions={},
        producer_markers={},
    )
    state: dict[str, Any] = {
        "is_ai": not is_ai,
        "owner": {
            "is_ai": is_ai,
            "num_loans": 10,
            "literacy_rate": 0.01,
            "bureaucracy": -100,
            "market": {},
        },
        # A country-shaped ROOT decoy cannot satisfy state-owner observations.
        "market": {"mg:iron": {"market_goods_delta": -999, "market_goods_pricier": 0.75}},
    }
    for reader in policy.readers:
        scope = state
        for part in reader.path:
            scope = scope.setdefault(part, {})
        scope[reader.engine] = values[reader.key]
    result = pdx_eval.select(text, {"ROOT": state})
    assert (result.delta if result.fallback == "selected" else 1.0) == pytest.approx(expected)
    if not is_ai:
        assert result.fallback == "vanilla"
        assert result.action_id is None


@pytest.mark.parametrize(
    ("balance", "price", "expected"),
    [
        (-1, None, 1.08),
        (-1, 0.25, 1.08),
        (-1, 0.250001, 1.12),
        (-1, 0.75, 1.12),
        (0, 0.75, 1.0),
        (1, 0.75, 1.0),
        (None, 0.75, 1.0),
        (None, None, 1.0),
    ],
)
def test_handwritten_values_and_generated_pdx_with_loans_low_admin_and_no_pm(
    adapters, baseline, balance, price, expected
):
    derived = _derive(adapters, baseline)
    _joint(
        derived,
        {
            "state_owner_iron_balance": balance,
            "state_owner_iron_price": price,
            "state_owner_default": False,
            "state_infrastructure": 0,
        },
        expected,
    )
    assert not any(
        token in key
        for key in derived["readers"]
        for token in ("loan", "literacy", "bureaucracy", "pm_active")
    )


@pytest.mark.parametrize("is_ai", [True, False])
def test_owner_ai_guard_does_not_read_state_or_country_decoy(adapters, baseline, is_ai):
    _joint(
        _derive(adapters, baseline),
        {"state_owner_iron_balance": -1, "state_owner_iron_price": 0.5},
        1.12 if is_ai else 1.0,
        is_ai=is_ai,
    )


def test_two_goods_and_low_high_tiers_share_one_demand_cause(adapters, baseline):
    derived = _derive(adapters, baseline)
    _joint(
        derived,
        {
            "state_owner_iron_balance": -1,
            "state_owner_iron_price": 0.5,
            "state_owner_coal_balance": -1,
            "state_owner_coal_price": 0.6,
        },
        1.12,
        building="building_dual",
    )
    _joint(
        derived,
        {"state_owner_iron_balance": -1, "state_owner_coal_balance": None},
        1.08,
        building="building_dual",
    )
    _joint(
        derived,
        {
            "state_owner_iron_balance": -1,
            "state_owner_iron_price": 0.5,
            "state_owner_coal_balance": -1,
            "state_owner_coal_price": 0.6,
            "state_owner_default": True,
            "state_infrastructure": -1,
        },
        0.87,
        building="building_dual",
    )


@pytest.mark.parametrize(
    ("balance", "price", "default", "infrastructure", "expected"),
    [
        (-1, None, True, 0, 0.93),
        (-1, None, False, -1, 0.98),
        (-1, None, True, -1, 0.83),
        (-1, 0.5, True, -1, 0.87),
        (-1, None, None, -1, 0.98),
        (-1, None, True, None, 0.93),
        (-1, None, None, None, 1.08),
        (0, 0.5, True, -1, 0.75),
        (None, 0.5, True, -1, 0.75),
        (0, 0.5, None, -1, 0.90),
        (-1, None, False, 0, 1.08),
        (-1, None, False, -0.000001, 0.98),
    ],
)
def test_actual_independent_costs_combine_and_unknown_only_exits_its_own_cost(
    adapters, baseline, balance, price, default, infrastructure, expected
):
    _joint(
        _derive(adapters, baseline),
        {
            "state_owner_iron_balance": balance,
            "state_owner_iron_price": price,
            "state_owner_default": default,
            "state_infrastructure": infrastructure,
        },
        expected,
    )


@pytest.mark.parametrize(("is_ai", "enabled"), [(False, True), (True, False), (False, False)])
def test_real_costs_and_demand_preserve_owner_player_and_off_paths(
    adapters, baseline, is_ai, enabled
):
    _joint(
        _derive(adapters, baseline),
        {
            "state_owner_iron_balance": -1,
            "state_owner_iron_price": 0.5,
            "state_owner_default": True,
            "state_infrastructure": -100,
        },
        1.0,
        is_ai=is_ai,
        enabled=enabled,
    )


def test_cost_rules_are_one_per_covered_consumer_and_not_per_good(adapters, baseline):
    derived = _derive(adapters, baseline)
    for building in ("building_mine", "building_dual"):
        costs = [
            rule
            for rule in derived["rules"]
            if rule["field"] == f"{building}.ai_value"
            and rule["contribution_group"] != "building_output_demand"
        ]
        assert [
            (rule["contribution_group"], rule["value"], rule["conditions"]) for rule in costs
        ] == [
            (
                "building_financing_pressure",
                0.85,
                [{"fact": "state_owner_default", "op": "=", "value": True}],
            ),
            (
                "building_infrastructure_pressure",
                0.90,
                [{"fact": "state_infrastructure", "op": "<", "value": 0.0}],
            ),
        ]
    assert {rule["field"] for rule in derived["rules"]} == {
        "building_mine.ai_value",
        "building_dual.ai_value",
    }


@pytest.mark.parametrize("reader", ["state_owner_default", "state_infrastructure"])
def test_exact_cost_reader_signature_is_reused_and_drift_rejected(adapters, baseline, reader):
    derived = _derive(adapters, baseline)
    adapters["readers"] = copy.deepcopy(derived["readers"])
    assert _derive(adapters, baseline) == derived
    adapters["readers"][reader]["path"] = ["market"]
    with pytest.raises(ValueError, match="reader"):
        _derive(adapters, baseline)


def test_common_outputs_do_not_use_method_union_or_optional_recipe(adapters, baseline):
    derived = _derive(adapters, baseline)
    covered = {row["building"]: row["goods"] for row in derived["covered"]}
    assert covered == {"building_dual": ["coal", "iron"], "building_mine": ["iron"]}
    assert set(derived["readers"]) == {
        "state_owner_coal_balance",
        "state_owner_coal_price",
        "state_owner_iron_balance",
        "state_owner_iron_price",
        "state_owner_default",
        "state_infrastructure",
    }
    reasons = {(row["building"], row["reason"]) for row in derived["uncovered"]}
    assert ("building_shipyard", "no_common_output_across_base_methods") in reasons
    assert ("building_optional", "no_mandatory_output_recipe_group") in reasons
    assert ("building_service", "no_mandatory_output_recipe_group") in reasons
    assert ("building_not_in_company_baseline", "missing_verified_building_recipe") in reasons
    assert ("building_gold", "non_market_output_requires_native_evidence") in reasons
    assert ("building_power", "non_market_output_requires_native_evidence") in reasons


def test_derive_never_creates_missing_consumers_or_mutates_inputs(adapters, baseline):
    before = copy.deepcopy((adapters, baseline))
    derived = _derive(adapters, baseline)
    assert (adapters, baseline) == before
    assert "initial_values" not in derived
    assert {rule["field"] for rule in derived["rules"]} <= {
        row["field"] for row in adapters["rules"]
    }
    assert not _derive({**adapters, "rules": []}, baseline)["rules"]


def test_exact_state_owner_readers_are_reused_and_drift_is_rejected(adapters, baseline):
    derived = _derive(adapters, baseline)
    adapters["readers"] = copy.deepcopy(derived["readers"])
    assert _derive(adapters, baseline) == derived
    adapters["readers"]["state_owner_iron_balance"]["path"] = ["market", "mg:iron"]
    with pytest.raises(ValueError, match="reader"):
        _derive(adapters, baseline)


@pytest.mark.parametrize("mutation", ["hash", "source", "identity", "conflict", "missing_source"])
def test_source_and_definition_drift_fail_closed(adapters, baseline, mutation):
    if mutation == "hash":
        adapters["sources"][BUILDINGS] = "0" * 64
    elif mutation == "source":
        adapters["rules"][0]["source"] = "common/buildings/elsewhere.txt"
        adapters["sources"]["common/buildings/elsewhere.txt"] = "0" * 64
    elif mutation == "identity":
        baseline["profiles"]["company_building_mine"]["base_recipes"][0]["id"] = "different"
    elif mutation == "conflict":
        adapters["rules"].append({"source": METHODS, "field": "building_mine.ai_value"})
        baseline["profiles"]["company_building_dual"]["base_recipes"][0] = copy.deepcopy(
            baseline["profiles"]["company_building_mine"]["base_recipes"][0]
        )
    else:
        adapters["sources"].clear()
    with pytest.raises(ValueError):
        _derive(adapters, baseline)


def test_duplicate_adapter_rules_do_not_duplicate_opportunities(adapters, baseline):
    derived = _derive(adapters, baseline)
    adapters["rules"].extend(copy.deepcopy(adapters["rules"]))
    assert _derive(adapters, baseline) == derived


def test_varying_mandatory_outputs_require_an_exact_registered_active_method(adapters, baseline):
    reader: dict[str, Any] = {
        "engine": "is_production_method_active",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {"building_type": "building_shipyard", "production_method": "sailing"},
    }
    key = "pm_active_building_shipyard_sailing"
    adapters["readers"][key] = reader
    derived = _derive(adapters, baseline)
    assert derived["conditional_covered"] == [
        {
            "building": "building_shipyard",
            "source": BUILDINGS,
            "field": "building_shipyard.ai_value",
            "method": "sailing",
            "good": "clippers",
            "reader": key,
        }
    ]
    rules = [rule for rule in derived["rules"] if rule["field"] == "building_shipyard.ai_value"]
    assert len(rules) == 3
    assert rules[0]["conditions"] == [
        {"fact": key, "op": "=", "value": True},
        {"fact": "state_owner_clippers_balance", "op": "<", "value": 0.0},
    ]
    assert rules[0]["value"] == 1.08
    assert "state_owner_steamers_balance" not in derived["readers"]
    assert "contexts" not in rules[0]
    reader["parameters"]["building_type"] = "building_mine"
    with pytest.raises(ValueError, match="active PM reader"):
        _derive(adapters, baseline)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("priority_base", True),
        ("priority_base", 1),
        ("shortage_balance", 1),
        ("output_price_threshold", 0),
        ("output_price_threshold", float("nan")),
        ("demand_multiplier", 1),
        ("pressure_multiplier", 1.01),
        ("pressure_multiplier", 2),
        ("default_multiplier", 1),
        ("default_multiplier", 0),
        ("default_multiplier", True),
        ("infrastructure_multiplier", 1),
        ("infrastructure_multiplier", float("nan")),
    ],
)
def test_invalid_parameters_fail(adapters, baseline, key, value):
    with pytest.raises(ValueError):
        building_opportunities.derive(
            adapters, baseline, parameters={**building_opportunities.load_parameters(), key: value}
        )


def test_default_baseline_route_reuses_existing_loader(adapters, baseline, monkeypatch):
    calls = []

    def load():
        calls.append(True)
        return baseline

    monkeypatch.setattr(company_sectors, "load_baseline", load)
    assert building_opportunities.derive(adapters) == building_opportunities.derive(
        adapters, baseline
    )
    assert calls == [True]


@pytest.mark.parametrize("key", ["schema", "profiles", "sources"])
def test_malformed_baseline_uses_explicit_failure(adapters, baseline, key):
    del baseline[key]
    with pytest.raises(ValueError):
        _derive(adapters, baseline)


def test_unknown_source_with_no_hash_does_not_pass_a_missing_equality(adapters, baseline):
    adapters["sources"]["common/buildings/absent.txt"] = None
    adapters["rules"][0]["source"] = "common/buildings/absent.txt"
    with pytest.raises(ValueError, match="哈希"):
        _derive(adapters, baseline)


def test_locked_recipe_consensus_keeps_actual_building_output_differences():
    raw = tomllib.loads((config.REPO / "mod/decisions/adapters.toml").read_text(encoding="utf-8"))
    derived = building_opportunities.derive(raw)
    covered = {row["building"]: row["goods"] for row in derived["covered"]}
    assert covered["building_food_industry"] == ["groceries"]
    assert covered["building_textile_mill"] == ["clothes"]
    assert covered["building_automotive_industry"] == ["automobiles"]
    assert covered["building_electrics_industry"] == ["telephones"]
    assert covered["building_livestock_ranch"] == ["fabric", "meat"]
    assert covered["building_whaling_station"] == ["meat", "oil"]
    assert "building_shipyard" not in covered
    assert "building_gold_mine" not in covered
    assert "building_railway" not in covered
    assert covered["building_art_academy"] == ["fine_art"]
    assert len(covered) == 42
    assert len([r for r in derived["rules"] if not r["id"].startswith("building_local_")]) == 178
    assert len(derived["readers"]) >= 78
    assert {(row["method"], row["good"]) for row in derived["conditional_covered"]} == {
        ("pm_basic_shipbuilding", "clippers"),
        ("pm_complex_shipbuilding", "clippers"),
        ("pm_metal_shipbuilding", "steamers"),
        ("pm_arc_welding_shipbuilding", "steamers"),
    }
    assert {rule["field"] for rule in derived["rules"]} <= {
        rule["field"] for rule in raw["rules"]
    } | {"building_art_academy.ai_value"}
    for key, reader in derived["readers"].items():
        if (
            key not in {"state_owner_default", "state_infrastructure"}
            and not key.startswith("pm_active_")
            and not reader["path"][0].startswith("sg:")
        ):
            assert reader["path"][:2] == ["owner", "market"]
        if key in raw["readers"]:
            assert reader == raw["readers"][key]
