"""Real country research consumers keep knowledge and paper preparation distinct."""

from copy import deepcopy

import pytest
from test_situated_building_joint import _generate
from test_situated_local_foundations import _overlay
from test_technology_opportunities import _building_object

from pdx import decision_rules, technology_opportunities
from pdx.situated import pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/technology/technologies/30_society.txt"


@pytest.fixture(scope="module", params=["dialectics", "analytical_philosophy"])
def production(request):
    technology = request.param
    return technology, _generate(SOURCE, (technology, "ai_weight"))


@pytest.mark.parametrize(
    ("paper", "method", "expected"),
    [
        ({"market_goods_delta": 0, "market_goods_pricier": 0.25}, "pm_scholastic_education", 1.12),
        ({"market_goods_delta": -1, "market_goods_pricier": 0.1}, "pm_scholastic_education", 1.08),
        ({"market_goods_delta": 0, "market_goods_pricier": 0.26}, "pm_scholastic_education", 1.08),
        ({"market_goods_delta": 0}, "pm_scholastic_education", 1.08),
        (None, "pm_scholastic_education", 1.08),
        (
            {"market_goods_delta": 0, "market_goods_pricier": 0.1},
            "pm_analytical_philosophy_department",
            1,
        ),
    ],
)
def test_actual_research_pdx_knowledge_ready_tiers(production, paper, method, expected):
    technology, (policy, text, _, _inputs) = production
    # Analytical philosophy also has a direct education benefit (+.25).
    # Its independent literacy gain survives every paper/method variant.
    if technology == "analytical_philosophy":
        expected += 0.25
    values = {r.key: None for r in policy.readers}
    values["literacy"] = 0.3
    observed = {
        "is_ai": True,
        "literacy_rate": 0.3,
        "any_scope_building": [_building_object("building_university", method)],
        "market": {"mg:paper": paper},
        "has_technology_researched": {},
    }
    # Query booleans for reference semantics come from the independent object
    # oracle; generated PDX reads the original objects directly.
    import technology_query_reference as oracle

    for reader in policy.readers:
        if dict(reader.parameters).get("technology_query"):
            values[reader.key] = oracle.evaluate(reader, observed)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(f"{technology}.ai_weight")
    actual = pdx_eval.select(_overlay(text, f"{technology}.ai_weight"), {"ROOT": observed})
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert actual.delta == pytest.approx(expected)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    observed["is_ai"] = False
    assert (
        pdx_eval.select(_overlay(text, f"{technology}.ai_weight"), {"ROOT": observed}).operation
        is None
    )
    assert 0 * actual.delta == 0


def test_native_university_query_drift_and_independent_deltas(production):
    technology, (policy, _text, _adapters, inputs) = production
    query = technology_opportunities.TechnologyUseQuery(technology, "knowledge_ready")
    proof = technology_opportunities.compile_query(query, inputs)
    assert proof.actor == "country"
    assert proof.world_scans == 0
    catalog = technology_opportunities.load_catalog()
    rows = [
        r
        for r in catalog["technologies"][technology]["opportunities"]
        if r["building"] == "building_university"
    ]
    expected = (
        {"pm_scholastic_education": (5, 0.5)}
        if technology == "dialectics"
        else {"pm_scholastic_education": (10, 1), "pm_philosophy_department": (5, 0.5)}
    )
    assert {
        r["prior"]: (r["inputs"]["paper"], r["services"]["country_weekly_innovation_add"])
        for r in rows
    } == expected
    changed = deepcopy(inputs)
    pm_source = "common/production_methods/07_government.txt"
    changed[pm_source] = changed[pm_source].replace(
        "goods_input_paper_add = 15", "goods_input_paper_add = 16"
    )
    assert changed[pm_source] != inputs[pm_source]
    with pytest.raises(ValueError, match="来源漂移"):
        technology_opportunities.compile_query(query, changed)
    programs = [p for p in policy.consumer_programs if p.field == (technology, "ai_weight")]
    assert len(programs) == 1


def test_no_university_keeps_direct_education_and_foreign_university_is_irrelevant(production):
    technology, (_policy, text, _, _) = production
    observed = {
        "is_ai": True,
        "literacy_rate": 0.3,
        "any_scope_building": [],
        "market": {"mg:paper": {"market_goods_delta": 100, "market_goods_pricier": 0.1}},
    }
    facts = {
        "ROOT": observed,
        "other_country": {
            "any_scope_building": [
                _building_object("building_university", "pm_scholastic_education")
            ]
        },
    }
    expected = 1.25 if technology == "analytical_philosophy" else 1
    assert pdx_eval.select(_overlay(text, f"{technology}.ai_weight"), facts).delta == pytest.approx(
        expected
    )
    # A real intermediate prior is an opportunity only for the higher method.
    observed["any_scope_building"] = [
        _building_object("building_university", "pm_philosophy_department")
    ]
    assert pdx_eval.select(_overlay(text, f"{technology}.ai_weight"), facts).delta == pytest.approx(
        1.37 if technology == "analytical_philosophy" else 1
    )
    observed["literacy_rate"] = 0.8
    assert pdx_eval.select(_overlay(text, f"{technology}.ai_weight"), facts).delta == 1
