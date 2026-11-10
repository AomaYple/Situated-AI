"""A complete textile employment slice; expectations are hand calculated."""

import tomllib
from copy import deepcopy

import pytest
from test_situated_building_joint import _generate
from test_situated_joint_witnesses import _facts
from test_situated_local_foundations import _overlay

from pdx import (
    building_opportunities,
    company_sectors,
    config,
    decision_adapters,
    decision_rules,
    version_contracts,
)
from pdx.situated import pdx_eval

pytestmark = pytest.mark.integration
FIELD = "building_textile_mill.ai_value"


@pytest.fixture(scope="module")
def production():
    return _generate("common/buildings/01_industry.txt", ("building_textile_mill", "ai_value"))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.18),  # output pressure .12 + independent employment .06
        ({"state_unemployment": 0.02}, 1.12),
        ({"state_unemployment": None}, 1.12),
        ({"state_owner_clothes_balance": 0}, 1),
        ({"state_owner_reserves": 0, "state_owner_loans": True}, 1.18),
        ({"pm_active_building_textile_mill_pm_handsewn_clothes": True}, 1.3),
        (
            {
                "pm_active_building_textile_mill_pm_handsewn_clothes": True,
                "state_owner_fabric_price": 0.6,
                "state_owner_fabric_balance": -1,
            },
            0.98,
        ),
        ({"state_owner_default": True}, 1.03),
        ({"state_unemployment": 0.01, "state_peasants_share": 0.01}, 1.04),
        ({"state_unemployment": 0.01, "state_peasants_share": 0.5}, 1.12),
        ({"state_unemployment": 0.01, "state_peasants_share": None}, 1.12),
    ],
)
def test_employment_and_local_labor_cost_match_real_pdx(production, changes, expected):
    policy, generated, _, _ = production
    values: dict[str, bool | float | None] = {r.key: None for r in policy.readers}
    values.update(
        state_unemployment=0.12,
        state_owner_clothes_balance=-1,
        state_owner_clothes_price=0.3,
        state_owner_default=False,
        state_owner_loans=False,
        state_infrastructure=0,
        state_market_access=1,
        state_owner_fabric_balance=0,
        state_owner_fabric_price=0.2,
    )
    values.update(changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(FIELD)
    overlay = _overlay(generated, FIELD)
    actual = pdx_eval.select(overlay, _facts(policy, dict(values)))
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert actual.delta == pytest.approx(expected)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert pdx_eval.select(overlay, _facts(policy, dict(values), is_ai=False)).operation is None
    assert 0 * actual.delta == 0
    facts = _facts(policy, dict(values))
    facts["ROOT"]["owner"]["state_unemployment_rate"] = 0.9
    facts["other_state"] = {"state_unemployment_rate": 0.9}
    assert pdx_eval.select(overlay, facts).delta == pytest.approx(expected)


def test_full_pmg_labor_lower_bound_and_invalidated_recipe():
    sector = building_opportunities._buildings(company_sectors.load_baseline())[
        "building_textile_mill"
    ]
    assert building_opportunities.employment_lower_bound(sector) == 500
    assert len(sector["groups"]) >= 3
    changed = deepcopy(sector)
    automation = next(
        m for g in changed["groups"] for m in g["methods"] if m["id"] == "pm_automatic_power_looms"
    )
    labor = next(
        m for m in automation["modifiers"] if m["key"] == "building_employment_laborers_add"
    )
    assert labor["value"] == -2500
    labor["value"] = -3500
    assert building_opportunities.employment_lower_bound(changed) <= 0
    baseline = deepcopy(company_sectors.load_baseline())
    for profile in baseline["profiles"].values():
        for candidate in profile["base_recipes"]:
            if candidate["id"] == "building_textile_mill":
                candidate.update(deepcopy(changed))
    raw = tomllib.loads((config.REPO / "mod/decisions/adapters.toml").read_text(encoding="utf-8"))
    if version_contracts.active_version() == "1.15.0":
        authority = decision_adapters.native_authority_115()
        assert set(raw["sources"]) == set(authority["sources"])
        raw["sources"] = dict(authority["sources"])
    with pytest.raises(ValueError, match="正劳动就业下界"):
        building_opportunities.derive(raw, baseline)


@pytest.mark.parametrize(
    ("method", "missing", "expected"),
    [
        ("pm_dye_workshops", {}, 1.3),
        ("pm_dye_workshops", {"state_owner_dye_balance": -1}, 1.26),
        ("pm_sewing_machines", {}, 1.3),
        ("pm_sewing_machines", {"state_owner_tools_balance": None}, 1.26),
        ("pm_electric_sewing_machines", {}, 1.3),
        ("pm_electric_sewing_machines", {"state_local_electricity_price": None}, 1.26),
        ("pm_electric_sewing_machines", {"state_local_electricity_price": 0.5}, 1.26),
    ],
)
def test_prepared_employment_requires_all_real_inputs_and_local_electricity(
    production, method, missing, expected
):
    policy, text, _, _ = production
    values: dict[str, bool | float | None] = {
        r.key: False if r.kind == "boolean" else 0 for r in policy.readers
    }
    values.update({r.key: 0.2 for r in policy.readers if r.key.endswith("_price")})
    values.update(
        state_unemployment=0.12,
        state_owner_clothes_balance=-1,
        state_owner_clothes_price=0.3,
        state_market_access=1,
    )
    values[f"pm_active_building_textile_mill_{method}"] = True
    values.update(missing)
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert result[FIELD][1] == pytest.approx(expected)
    actual = pdx_eval.select(_overlay(text, FIELD), _facts(policy, dict(values)))
    assert actual.delta == pytest.approx(expected)
    # A cheap country-market electricity observation cannot stand in for the
    # absent/expensive state electricity preparation reader.
    if "state_local_electricity_price" in missing:
        assert values["state_owner_electricity_price"] == 0.2


def test_textile_and_railway_keep_static_budget_with_one_recovery_variant(production):
    from pdx import decision_adapters

    policy = production[0]
    candidates = policy.groups()[("building_textile_mill", "ai_value")]
    assert len(candidates) == 32
    assert sum(len(r.conditions) + len(r.required_known_facts) for r in candidates) == 148
    railway = dict(decision_adapters.load().policies)[
        "common/buildings/11_private_infrastructure.txt"
    ]
    rows = railway.groups()[("building_railway", "ai_value")]
    assert len(rows) <= decision_rules.STATIC_BUDGET["candidates_per_field"]
    predicates = sum(len(r.conditions) + len(r.required_known_facts) for r in rows)
    assert predicates <= decision_rules.STATIC_BUDGET["predicates_per_field"]
    # Before integration, prove space for E4's one bounded recovery variant.
    if len(rows) == 31:
        assert len(rows) + 1 == decision_rules.STATIC_BUDGET["candidates_per_field"]
        assert predicates + 6 <= decision_rules.STATIC_BUDGET["predicates_per_field"]
