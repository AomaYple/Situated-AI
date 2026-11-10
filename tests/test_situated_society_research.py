"""S2 society research: actual consumers, handwritten joint values and local unknowns.

Thresholds are design choices. Population, living standards and radical share
are declared proxies, not observations of urban congestion, institution caps,
malaria opportunities or the origin of political-movement radicals.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules, version_contracts
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/technology/technologies/30_society.txt"
ADMIN = ("psychiatry", "psychoanalysis", "behaviorism")
FINANCE = ("mutual_funds", "international_exchange_standards")
HEALTH = ("quinine", "malaria_prevention")
LABOR = ("labor_movement", "human_rights")
URBAN = ("urbanization", "urban_planning", "steel_frame_buildings", "elevator")
WELFARE = ("democracy", "egalitarianism", "feminism")
TECHNOLOGIES = (
    *ADMIN,
    *FINANCE,
    *HEALTH,
    *LABOR,
    *URBAN,
    *WELFARE,
    "postal_savings",
    "corporatism",
    "socialism",
    "mass_propaganda",
)


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


def _values(policy: Any, changes: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {
        reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers
    }
    values.update(sol=20, literacy=0.8)
    values.update(changes)
    return values


def _engine(policy: Any, values: dict[str, object], *, is_ai: bool = True) -> dict[str, Any]:
    root: dict[str, Any] = {"is_ai": is_ai}
    for reader in policy.readers:
        assert reader.scope == "root"
        current = root
        for component in reader.path:
            current = current.setdefault(component, {})
        observed = values.get(reader.key)
        if reader.argument is not None or reader.parameters or reader.value_field is not None:
            parameters = dict(reader.parameters)
            if reader.argument is not None:
                parameters["argument"] = reader.argument
            current.setdefault(reader.engine, {})[tuple(sorted(parameters.items()))] = observed
        else:
            current[reader.engine] = observed
    return {"ROOT": root}


def _overlay(text: str, technology: str) -> str:
    start = text.index(f"# SITAI BEGIN information:{_field(technology)}")
    end = text.index(f"# SITAI END information:{_field(technology)}", start)
    return "\n".join(text[start:end].splitlines()[1:])


def _assert_result(production, technology: str, changes: Mapping[str, object], expected: float):
    policy, _native, generated = production
    values = _values(policy, changes)
    actual = pdx_eval.select(_overlay(generated, technology), _engine(policy, values))
    assert (actual.action_id, actual.operation) == (_program_id(technology), "multiply")
    assert actual.delta == pytest.approx(expected)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(_field(technology))
    if expected == 1:
        assert reference is None
    else:
        assert reference is not None
        assert reference[0] == _program_id(technology)
        assert reference[1] == pytest.approx(expected)
    return actual


CASES: list[tuple[str, Mapping[str, object], float]] = []
CASES += [
    (technology, changes, expected)
    for technology in ADMIN
    for changes, expected in (
        ({"bureaucracy": -1}, 1.15),
        ({"bureaucracy": 0}, 1),
        ({"bureaucracy": None}, 1),
        ({"bureaucracy": -1, "default": True, "war": True, "literacy": None}, 1.15),
    )
]

# New consumers use actual workplace capacity or battle-war-support effects.
# Their expected-SOL side effect is an independent negative contribution.
CASES += [
    ("socialism", changes, expected)
    for changes, expected in (
        ({"industrial_workforce": 0.15, "sol": 10, "literacy": 0.4}, 1.15),
        ({"industrial_workforce": 0.15, "sol": 10, "literacy": 0.5}, 1.07),
        ({"industrial_workforce": 0.149, "sol": 10, "literacy": 0.5}, 0.92),
        ({"industrial_workforce": 0.2, "sol": 12, "literacy": 0.5}, 1),
        ({"industrial_workforce": None, "sol": 10, "literacy": 0.5}, 0.92),
        ({"industrial_workforce": 0.2, "sol": 10, "literacy": None}, 1.15),
        ({"industrial_workforce": 0.2, "sol": None, "literacy": 0.5}, 1),
        (
            {
                "industrial_workforce": 0.2,
                "sol": 10,
                "literacy": 0.5,
                "war": True,
                "default": True,
                "loans": True,
            },
            1.07,
        ),
    )
]
CASES += [
    ("mass_propaganda", changes, expected)
    for changes, expected in (
        ({"war": True, "sol": 12, "literacy": 0.5}, 1.15),
        ({"war": True, "sol": 10, "literacy": 0.5}, 1.07),
        ({"war": False, "sol": 10, "literacy": 0.5}, 0.92),
        ({"war": None, "sol": 10, "literacy": 0.5}, 0.92),
        ({"war": True, "sol": 10, "literacy": None}, 1.15),
        ({"war": True, "sol": None, "literacy": 0.5}, 1.15),
        ({"war": None, "sol": None, "literacy": None}, 1),
        ({"war": True, "default": True, "loans": True}, 1.15),
    )
]
CASES += [
    (technology, {"sol": sol, "literacy": 0.4}, expected)
    for technology in WELFARE
    for sol, expected in ((7, 1.12), (8, 1.08), (11.999, 1.08), (12, 1), (None, 1))
]
CASES += [
    ("egalitarianism", changes, expected)
    for changes, expected in (
        ({"sol": 7, "literacy": 0.5}, 1.04),
        ({"sol": 10, "literacy": 0.5}, 1),
        ({"sol": 7, "literacy": None}, 1.12),
        ({"sol": None, "literacy": 0.5}, 1),
        ({"sol": 7, "literacy": 0.5, "default": True, "war": True}, 1.04),
    )
]
CASES += [
    (technology, changes, expected)
    for technology in FINANCE
    for changes, expected in (
        ({"loans": True, "debt_ratio": 0.2}, 1.15),
        ({"loans": True, "debt_ratio": 0.599}, 1.15),
        ({"loans": True, "debt_ratio": 0.6}, 1.22),
        ({"loans": True, "debt_ratio": None}, 1.15),
        ({"loans": False, "debt_ratio": 0.9}, 1),
        ({"loans": None, "debt_ratio": 0.9}, 1),
        ({"loans": True, "debt_ratio": 0.9, "default": True, "war": True}, 1.22),
    )
]
CASES += [
    ("postal_savings", {"skilled_workforce": share}, expected)
    for share, expected in ((0.019, 1), (0.02, 1.08), (0.049, 1.08), (0.05, 1.12), (None, 1))
]
CASES += [
    (technology, {"sol": sol}, expected)
    for technology in HEALTH
    for sol, expected in ((7, 1.15), (8, 1.10), (11.999, 1.10), (12, 1), (None, 1))
]
CASES += [
    (technology, changes, expected)
    for technology in LABOR
    for changes, expected in (
        ({"current_child_labor": True, "literacy": 0.499}, 1.12),
        ({"current_child_labor": True, "literacy": 0.6}, 1),
        ({"current_child_labor": False, "literacy": 0.4}, 1),
        ({"current_child_labor": None, "literacy": 0.4}, 1),
        ({"current_child_labor": True, "literacy": None}, 1),
        ({"industrial_workforce": 0.15, "sol": 10, "literacy": 0.4}, 1.15),
        ({"industrial_workforce": 0.149, "sol": 10, "literacy": 0.4}, 1),
        ({"industrial_workforce": 0.2, "sol": 12}, 1),
        ({"industrial_workforce": None, "sol": 10, "literacy": 0.4}, 1),
        ({"current_child_labor": True, "literacy": 0.55, "sol": None}, 1.12),
        ({"industrial_workforce": 0.2, "sol": 10, "literacy": None}, 1.15),
    )
]
# Independent child-education and workplace contributions add. The actual
# expected-SOL modifier creates a separate negative contribution only for labor_movement.
CASES += [
    (
        "labor_movement",
        {"current_child_labor": True, "literacy": 0.55, "industrial_workforce": 0.2, "sol": 10},
        1.19,
    ),
    (
        "human_rights",
        {"current_child_labor": True, "literacy": 0.55, "industrial_workforce": 0.2, "sol": 10},
        1.27,
    ),
    ("labor_movement", {"literacy": 0.5, "sol": 10}, 0.92),
    ("labor_movement", {"literacy": 0.499, "sol": 10}, 1),
    ("labor_movement", {"literacy": 0.5, "sol": 12}, 1),
    (
        "labor_movement",
        {"current_child_labor": None, "literacy": 0.55, "industrial_workforce": 0.2, "sol": 10},
        1.07,
    ),
    (
        "human_rights",
        {"current_child_labor": None, "literacy": 0.55, "industrial_workforce": 0.2, "sol": 10},
        1.15,
    ),
]
CASES += [
    ("corporatism", changes, expected)
    for changes, expected in (
        ({"radical_share": 0.149, "insurrection": True}, 1),
        ({"radical_share": 0.15}, 1.08),
        ({"radical_share": 0.25, "insurrection": True}, 1.12),
        ({"radical_share": 0.25, "insurrection": None}, 1.08),
        ({"radical_share": None, "insurrection": True}, 1),
    )
]
CASES += [
    (technology, changes, expected)
    for technology in URBAN
    for changes, expected in (
        ({"population": 1999999}, 1),
        ({"population": 2000000}, 1.10),
        ({"population": None}, 1),
        (
            {
                "population": 2000000,
                "literacy": 0,
                "bureaucracy": -1,
                "net_surplus": -1,
                "default": True,
                "loans": True,
                "war": True,
            },
            1.10,
        ),
        (
            {
                "population": 2000000,
                "industrial_workforce": 0.15,
                "bureaucracy": 0,
                "net_surplus": 1,
            },
            1.18,
        ),
        (
            {
                "population": 2000000,
                "industrial_workforce": None,
                "bureaucracy": 0,
                "net_surplus": 1,
            },
            1.10,
        ),
        (
            {
                "population": 2000000,
                "industrial_workforce": 0.15,
                "bureaucracy": None,
                "net_surplus": 1,
            },
            1.10,
        ),
        (
            {
                "population": 2000000,
                "industrial_workforce": 0.15,
                "bureaucracy": 0,
                "net_surplus": None,
            },
            1.10,
        ),
        (
            {
                "population": 2000000,
                "industrial_workforce": 0.15,
                "bureaucracy": 0,
                "net_surplus": 0,
            },
            1.10,
        ),
    )
]


@pytest.mark.parametrize(("technology", "changes", "expected"), CASES)
def test_handwritten_contributions_match_complete_compiled_reference_and_actual_pdx(
    production, technology, changes, expected
):
    _assert_result(production, technology, changes, expected)


POSITIVES = [
    *((technology, {"bureaucracy": -1}, 1.15) for technology in ADMIN),
    *((technology, {"loans": True, "debt_ratio": 0.6}, 1.22) for technology in FINANCE),
    *((technology, {"sol": 7}, 1.15) for technology in HEALTH),
    *((technology, {"current_child_labor": True, "literacy": 0.4}, 1.12) for technology in LABOR),
    *((technology, {"population": 2000000}, 1.10) for technology in URBAN),
    ("postal_savings", {"skilled_workforce": 0.05}, 1.12),
    ("corporatism", {"radical_share": 0.25, "insurrection": True}, 1.12),
    *((technology, {"sol": 7, "literacy": 0.4}, 1.12) for technology in WELFARE),
    ("socialism", {"industrial_workforce": 0.2, "sol": 10, "literacy": 0.4}, 1.15),
    ("mass_propaganda", {"war": True}, 1.15),
]


@pytest.mark.parametrize(("technology", "changes", "expected"), POSITIVES)
def test_player_off_candidate_and_other_country_boundaries(
    production, technology, changes, expected
):
    policy, _native, generated = production
    actual = _assert_result(production, technology, changes, expected)
    values = _values(policy, changes)
    overlay = _overlay(generated, technology)
    player = pdx_eval.select(overlay, _engine(policy, values, is_ai=False))
    assert player.operation is None
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    annotated = {**values, "candidate_selected": True, "construction_queued": True}
    assert pdx_eval.select(overlay, _engine(policy, annotated)) == actual
    facts = _engine(policy, values)
    facts["other_country"] = facts.pop("ROOT")
    facts["ROOT"] = {"is_ai": True, "candidate_selected": True}
    decoy = pdx_eval.select(overlay, facts)
    assert (decoy.action_id, decoy.operation, decoy.delta) == (
        _program_id(technology),
        "multiply",
        1,
    )


def _tree(node: Any) -> Any:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def test_all_native_prerequisites_costs_strategy_culture_and_on_researched_tails_are_retained(
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
    assert _tree(after.root) == _tree(before.root)


def test_disabled_module_patches_exactly_no_native_source(production):
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


def test_explicit_causal_groups_and_actual_country_reader_identities(production):
    policy, _native, _generated = production
    assert len(policy.rules) == 39
    assert len(policy.consumer_programs) == 20
    assert all(rule.contribution_group for rule in policy.rules)
    readers = {reader.key: reader for reader in policy.readers}
    assert set(readers) == {
        "bureaucracy",
        "loans",
        "debt_ratio",
        "skilled_workforce",
        "sol",
        "current_child_labor",
        "literacy",
        "industrial_workforce",
        "radical_share",
        "insurrection",
        "population",
        "net_surplus",
        "war",
    }
    assert all(reader.scope == "root" and reader.path == () for reader in readers.values())
    for key, pop_type in (
        ("skilled_workforce", "machinists"),
        ("industrial_workforce", "laborers"),
    ):
        reader = readers[key]
        current = version_contracts.active_version() == "1.15.0"
        assert (
            reader.engine,
            reader.value_field,
            dict(reader.parameters),
            reader.unit,
            reader.minimum,
            reader.maximum,
        ) == (
            "pop_type_percent_country",
            "value" if current else "percent",
            {"target": "pop_type:" + pop_type} if current else {"pop_type": pop_type},
            "ratio",
            0,
            1,
        )
    child = readers["current_child_labor"]
    assert (child.engine, child.argument) == (
        "has_law_or_variant",
        "law_type:law_child_labor_allowed",
    )
    assert readers["radical_share"].engine == "radical_fraction"
    assert readers["radical_share"].value_field == "value"
    assert (readers["population"].engine, readers["population"].unit) == (
        "total_population",
        "persons",
    )
    assert readers["bureaucracy"].unit == "capacity_balance"
    assert readers["debt_ratio"].unit == "debt_to_credit_ratio"
    assert readers["net_surplus"].unit == "currency_per_week"


@pytest.mark.parametrize(
    ("technology", "reader_key", "wrong_pop_type"),
    [
        ("postal_savings", "skilled_workforce", "laborers"),
        ("labor_movement", "industrial_workforce", "peasants"),
        ("human_rights", "industrial_workforce", "machinists"),
        ("socialism", "industrial_workforce", "peasants"),
    ],
)
def test_another_population_query_cannot_supply_the_required_observation(
    production, technology, reader_key, wrong_pop_type
):
    policy, _native, generated = production
    values = _values(policy, {reader_key: 0.2, "sol": 10, "literacy": 0.4})
    facts = _engine(policy, values)
    reader = next(reader for reader in policy.readers if reader.key == reader_key)
    observations = facts["ROOT"][reader.engine]
    observations.pop(tuple(reader.parameters))
    other_population = (
        (("target", "pop_type:" + wrong_pop_type),)
        if version_contracts.active_version() == "1.15.0"
        else (("pop_type", wrong_pop_type),)
    )
    observations[other_population] = 0.2
    result = pdx_eval.select(_overlay(generated, technology), facts)
    assert result.delta == 1


def test_research_benefits_are_grounded_in_actual_vanilla_modifiers(production):
    _policy, native, _generated = production
    root = parse_text(native).root
    effects = {
        **dict.fromkeys(ADMIN, ("state_bureaucracy_population_base_cost_factor_mult", -0.05)),
        **dict.fromkeys(FINANCE, ("country_loan_interest_rate_add", -0.02)),
        **dict.fromkeys(HEALTH, ("country_institution_health_system_max_investment_add", 1)),
        "postal_savings": ("state_machinists_investment_pool_efficiency_mult", 0.15),
        "labor_movement": ("country_institution_workplace_safety_max_investment_add", 3),
        "human_rights": ("country_institution_social_security_max_investment_add", 1),
        "corporatism": ("state_radicals_from_political_movements_mult", -0.1),
        "urbanization": ("state_infrastructure_from_population_add", 2),
        "urban_planning": ("state_infrastructure_from_population_add", 1),
        "steel_frame_buildings": ("state_infrastructure_from_population_add", 1),
        "elevator": ("state_infrastructure_from_population_add", 1),
        "socialism": ("country_institution_workplace_safety_max_investment_add", 2),
        "mass_propaganda": ("country_war_support_battles_increase_mult", 0.25),
        "democracy": ("country_institution_social_security_max_investment_add", 2),
        "egalitarianism": ("country_institution_social_security_max_investment_add", 1),
        "feminism": ("country_institution_social_security_max_investment_add", 1),
    }
    for technology, (effect, expected) in effects.items():
        definition = root.first(technology)
        assert definition is not None
        assert isinstance(definition.value, Block)
        modifier = definition.value.first("modifier")
        assert modifier is not None
        assert isinstance(modifier.value, Block)
        value = modifier.value.first(effect)
        assert value is not None
        assert isinstance(value.value, Scalar)
        assert float(value.value.unquoted) == expected


@pytest.mark.parametrize(
    "technology", ["labor_movement", "socialism", "egalitarianism", "mass_propaganda"]
)
def test_expectation_cost_exists_in_actual_vanilla_and_matches_only_its_causal_group(
    production, technology
):
    policy, native, _generated = production
    definition = parse_text(native).root.first(technology)
    assert definition is not None
    assert isinstance(definition.value, Block)
    modifier = definition.value.first("modifier")
    assert modifier is not None
    assert isinstance(modifier.value, Block)
    effect = modifier.value.first("state_expected_sol_from_literacy")
    assert effect is not None
    assert isinstance(effect.value, Scalar)
    assert float(effect.value.unquoted) == 1
    costs = [
        rule
        for rule in policy.rules
        if ".".join(rule.field) == _field(technology) and rule.value < 1
    ]
    assert len(costs) == 1
    assert costs[0].contribution_group == "reform_expectation"
    assert costs[0].value == 0.92


@pytest.mark.parametrize("technology", URBAN)
def test_population_capacity_rule_does_not_claim_unobserved_construction_payment(
    production, technology
):
    policy, native, _generated = production
    definition = parse_text(native).root.first(technology)
    assert definition is not None
    assert isinstance(definition.value, Block)
    modifier = definition.value.first("modifier")
    assert modifier is not None
    assert isinstance(modifier.value, Block)
    for key in (
        "state_building_construction_sector_max_level_add",
        "country_max_weekly_construction_progress_add",
    ):
        effect = modifier.value.first(key)
        assert effect is not None
        assert isinstance(effect.value, Scalar)
        assert float(effect.value.unquoted) > 0
    rules = [rule for rule in policy.rules if ".".join(rule.field) == _field(technology)]
    assert {rule.contribution_group for rule in rules} == {
        "population_urban_capacity",
        "observed_urban_absorption",
    }
    foundation = next(
        rule for rule in rules if rule.contribution_group == "population_urban_capacity"
    )
    assert foundation.input_keys() == frozenset({"population"})
    _assert_result(
        production,
        technology,
        {
            "population": 2000000,
            "industrial_workforce": None,
            "bureaucracy": None,
            "net_surplus": None,
            "default": True,
            "war": True,
            "literacy": None,
        },
        1.10,
    )
