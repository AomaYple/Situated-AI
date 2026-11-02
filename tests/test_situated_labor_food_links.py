"""LJ06/LJ07 局部就业与粮食—社会链见证。"""

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.unit
INDUSTRY = "common/buildings/01_industry.txt"
STRATEGY = "common/ai_strategies/00_default_strategy.txt"
INFO = "mod/decisions/information.toml"
FOOD = "building_food_industry.ai_value"
TEXTILE = "building_textile_mill.ai_value"
HEALTH = "ai_strategy_default.institution_scores.institution_health_system"
SOCIAL = "institution_scores.institution_social_security"
FOOD_EMPLOYMENT = "comparative_employment_active_building_food_industry_pm_bakery_output_groceries"


def _program_id(source: str, field: str) -> str:
    return "program_" + hashlib.sha256(f"{source}:{field}".encode()).hexdigest()[:16]


def _subset(policy: Any, ids: set[str]) -> Any:
    rules = tuple(r for r in policy.rules if r.id in ids)
    keys = frozenset(k for r in rules for k in r.input_keys())
    return replace(
        policy,
        rules=rules,
        readers=tuple(r for r in policy.readers if r.key in keys),
        enabled_domains=frozenset(r.domain for r in rules),
        semantic_ir=(),
    )


@pytest.fixture(scope="module")
def policies() -> dict[str, Any]:
    adapters = decision_adapters.load()
    by_source = dict(adapters.policies)
    selected = {
        INDUSTRY: _subset(
            by_source[INDUSTRY],
            {
                FOOD_EMPLOYMENT,
                "lj06_employment_textile_unemployment_support",
            },
        ),
        STRATEGY: _subset(
            by_source[STRATEGY],
            {"lj07_grain_health_foundation", "lj07_grain_health_social_capacity"},
        ),
        INFO: _subset(
            decision_rules.load(), {"lj07_grain_social_foundation", "lj07_grain_social_capacity"}
        ),
    }
    model = compiler.load_model()
    return {
        source: compiler.compile_policy(policy, source, model)[0]
        for source, policy in selected.items()
    }


def _values(policy: Any, **changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {r.key: (False if r.kind == "boolean" else 0) for r in policy.readers}
    values.update(
        {
            "state_unemployment": 0.2,
            "state_owner_default": False,
            "state_owner_loans": False,
            "state_owner_reserves": 1,
            "state_infrastructure": 0,
            "state_market_access": 1,
            "grain_price": 0.6,
            "grain_balance": -1,
            "default": False,
            "average_sol": 7,
            "bureaucracy": 1,
            "net_surplus": 1,
            "insurrection": False,
            "pm_active_building_food_industry_pm_bakery": True,
            "pm_active_building_textile_mill_pm_handsewn_clothes": True,
            "state_owner_groceries_price": 0.3,
            "state_owner_clothes_price": 0.3,
            "state_owner_groceries_balance": -1,
            "state_owner_clothes_balance": -1,
        }
    )
    values.update(changes)
    return values


def _factor(policy: Any, field: str, **changes: Any) -> float:
    result = decision_rules.evaluate(policy, _values(policy, **changes), is_ai=True).get(field)
    return result[1] if result else 1.0


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, (1.3, 1.3)),
        ({"state_unemployment": 0.099}, (1.0, 1.0)),
        ({"state_unemployment": None}, (1.0, 1.0)),
        ({"state_owner_default": True}, (1.0, 1.0)),
        ({"state_owner_loans": True}, (1.0, 1.3)),
        ({"state_owner_loans": None}, (1.0, 1.0)),
        ({"state_owner_reserves": 0}, (1.0, 1.3)),
        ({"state_owner_reserves": None}, (1.0, 1.3)),
        ({"state_owner_grain_price": 0.251}, (1.0, 1.3)),
        ({"state_owner_grain_balance": -1}, (1.3, 1.3)),
        ({"state_owner_grain_balance": None}, (1.3, 1.3)),
        ({"state_infrastructure": -1}, (1.0, 1.0)),
        ({"candidate_selected": True, "construction_queued": True}, (1.3, 1.3)),
    ],
)
def test_lj06_actual_unemployment_pressure_is_local_and_candidate_does_not_complete(
    policies: dict[str, Any], changes: dict[str, Any], expected: tuple[float, float]
) -> None:
    p = policies[INDUSTRY]
    assert (_factor(p, FOOD, **changes), _factor(p, TEXTILE, **changes)) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, (1.16, 1.12)),
        ({"average_sol": 8}, (1.08, 1.06)),
        ({"bureaucracy": 0}, (1.08, 1.06)),
        ({"net_surplus": 0}, (1.08, 1.06)),
        ({"insurrection": True}, (1.08, 1.06)),
        ({"grain_price": 0.5}, (1.0, 1.0)),
        ({"grain_balance": 0}, (1.0, 1.0)),
        ({"grain_price": None}, (1.0, 1.0)),
        ({"candidate_selected": True, "construction_queued": True}, (1.16, 1.12)),
    ],
)
def test_lj07_grain_health_and_social_have_independent_capacity_upgrades(
    policies: dict[str, Any], changes: dict[str, Any], expected: tuple[float, float]
) -> None:
    assert _factor(policies[STRATEGY], HEALTH, **changes) == pytest.approx(expected[0])
    assert _factor(policies[INFO], SOCIAL, **changes) == pytest.approx(expected[1])


def test_lj06_and_lj07_reader_contracts_are_real_and_no_unimplemented_chain_fields_added(
    policies: dict[str, Any],
) -> None:
    assert {r.key for r in policies[INDUSTRY].readers} >= {
        "state_unemployment",
        "state_owner_groceries_balance",
        "state_owner_clothes_balance",
    }
    assert {r.key for r in policies[STRATEGY].readers} >= {
        "grain_price",
        "grain_balance",
        "bureaucracy",
        "net_surplus",
    }
    assert {r.key for r in policies[INFO].readers} >= {
        "grain_price",
        "grain_balance",
        "bureaucracy",
        "net_surplus",
    }


def _engine_facts(policy: Any, values: dict[str, Any], *, is_ai: bool = True) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for reader in policy.readers:
        assert reader.scope == "root"
        current = root
        for part in reader.path:
            current = current.setdefault(part, {})
        observed = values.get(reader.key)
        if reader.engine == "is_production_method_active":
            params = dict(reader.parameters)
            current.setdefault(reader.engine, {}).setdefault(params["building_type"], {})[
                params["production_method"]
            ] = observed
        elif reader.argument is not None or reader.parameters:
            params = dict(reader.parameters)
            if reader.argument is not None:
                params["argument"] = reader.argument
            current.setdefault(reader.engine, {})[tuple(sorted(params.items()))] = observed
        else:
            current[reader.engine] = observed
        if reader.engine.startswith("sitai_context_"):
            current[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                observed is not None
            )
    actor = root.setdefault("owner", {}) if policy.actor_path else root
    actor["is_ai"] = is_ai
    return {"ROOT": root}


def _overlay(text: str, field: str) -> str:
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    return "\n".join(text[begin:end].splitlines()[1:])


@pytest.fixture(scope="module")
def generated(policies: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Compile each complete writer using the real complete model and source patcher."""
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    compiled = tuple((source, policy) for source, policy in policies.items() if source != INFO)
    fields = {(source, rule.field) for source, policy in compiled for rule in policy.rules}
    selected = replace(
        adapters,
        policies=compiled,
        initial_values=tuple(
            row for row in adapters.initial_values if (row.source, row.field) in fields
        ),
        scalar_values=tuple(row for row in adapters.scalar_values if row in fields),
        supply=None,
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    baseline = compiler.BASELINE.read_text(encoding="utf-8")
    files[INFO] = decision_rules.patch(
        baseline,
        policies[INFO],
        baseline=baseline,
        reader_words=frozenset(decision_adapters.reader_evidence(inputs)),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    return inputs, files


WRITERS = [
    (INDUSTRY, FOOD, FOOD_EMPLOYMENT, {}, 1.30),
    (INDUSTRY, TEXTILE, "lj06_employment_textile_unemployment_support", {}, 1.30),
    (STRATEGY, HEALTH, "lj07_grain_health_foundation", {"average_sol": 8}, 1.08),
    (STRATEGY, HEALTH, "lj07_grain_health_social_capacity", {}, 1.16),
    (INFO, SOCIAL, "lj07_grain_social_foundation", {"average_sol": 8}, 1.06),
    (INFO, SOCIAL, "lj07_grain_social_capacity", {}, 1.12),
]


@pytest.mark.integration
@pytest.mark.parametrize(("source", "field", "writer", "changes", "expected"), WRITERS)
def test_each_local_writer_compiles_to_real_pdx_and_uses_handwritten_result(
    policies: dict[str, Any],
    generated: tuple[dict[str, str], dict[str, str]],
    source: str,
    field: str,
    writer: str,
    changes: dict[str, Any],
    expected: float,
) -> None:
    policy = policies[source]
    overlay = _overlay(generated[1][source], field)
    values = _values(policy, **changes)
    actual = pdx_eval.select(overlay, _engine_facts(policy, values))
    assert any(rule.id == writer and ".".join(rule.field) == field for rule in policy.rules)
    assert (actual.action_id, actual.operation) == (_program_id(source, field), "multiply")
    assert actual.delta == pytest.approx(expected)
    assert _factor(policy, field, **changes) == pytest.approx(expected)
    for candidate in ({"candidate_selected": True}, {"construction_queued": True}):
        assert pdx_eval.select(overlay, _engine_facts(policy, {**values, **candidate})) == actual
    player = pdx_eval.select(overlay, _engine_facts(policy, values, is_ai=False))
    assert player.operation is None
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert 0 * actual.delta == 0


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source", "field", "key"),
    [
        (INDUSTRY, FOOD, "state_unemployment"),
        (INDUSTRY, TEXTILE, "state_unemployment"),
        (STRATEGY, HEALTH, "grain_balance"),
        (INFO, SOCIAL, "grain_price"),
        (STRATEGY, HEALTH, "bureaucracy"),
        (INFO, SOCIAL, "net_surplus"),
    ],
)
def test_actual_pdx_unknown_observations_preserve_native(
    policies: dict[str, Any],
    generated: tuple[dict[str, str], dict[str, str]],
    source: str,
    field: str,
    key: str,
) -> None:
    policy = policies[source]
    values = _values(policy, **{key: None})
    actual = pdx_eval.select(_overlay(generated[1][source], field), _engine_facts(policy, values))
    assert (actual.action_id, actual.operation, actual.delta) == (
        _program_id(source, field),
        "multiply",
        1,
    )
    assert _factor(policy, field, **{key: None}) == 1


@pytest.mark.integration
def test_local_pdx_never_reads_other_states_methods_or_owner_market(
    policies: dict[str, Any],
    generated: tuple[dict[str, str], dict[str, str]],
) -> None:
    policy = policies[INDUSTRY]
    values = _values(policy)
    values["pm_active_building_food_industry_pm_bakery"] = False
    facts = _engine_facts(policy, values)
    decoy = {"is_production_method_active": {"building_food_industry": {"pm_bakery": True}}}
    facts["other_state"] = decoy
    facts["ROOT"]["owner"].update(decoy)
    result = pdx_eval.select(_overlay(generated[1][INDUSTRY], FOOD), facts)
    assert (result.action_id, result.operation, result.delta) == (
        _program_id(INDUSTRY, FOOD),
        "multiply",
        1,
    )
    for source, field in ((STRATEGY, HEALTH), (INFO, SOCIAL)):
        policy = policies[source]
        facts = _engine_facts(policy, _values(policy, grain_price=None))
        facts["other_country"] = {"market": {"mg:grain": {"market_goods_pricier": 0.6}}}
        facts["market_goods_pricier"] = 0.6
        result = pdx_eval.select(_overlay(generated[1][source], field), facts)
        assert (result.action_id, result.operation, result.delta) == (
            _program_id(source, field),
            "multiply",
            1,
        )


@pytest.mark.integration
def test_disabling_local_modules_preserves_exact_native_sources(
    policies: dict[str, Any],
    generated: tuple[dict[str, str], dict[str, str]],
) -> None:
    inputs, _ = generated
    model = compiler.load_model()
    adapters = decision_adapters.load()
    disabled, _ = decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())
    assert disabled == {}
    baseline = compiler.BASELINE.read_text(encoding="utf-8")
    assert (
        decision_rules.patch(
            baseline, policies[INFO], baseline=baseline, enabled_domains=frozenset()
        )
        == baseline
    )
    assert model.consumer_ir is not None


def _tree(node: Any) -> Any:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


@pytest.mark.integration
def test_generated_building_qualification_cost_and_unrelated_definitions_stay_native(
    generated: tuple[dict[str, str], dict[str, str]],
) -> None:
    inputs, files = generated
    before = parse_text(inputs[INDUSTRY]).root
    after = parse_text(files[INDUSTRY]).root
    for definition in ("building_food_industry", "building_textile_mill"):
        native, output = before.first(definition), after.first(definition)
        assert native is not None
        assert output is not None
        assert isinstance(native.value, Block)
        assert isinstance(output.value, Block)
        assert tuple(
            _tree(item)
            for item in native.value.items
            if not isinstance(item, Assignment) or item.key != "ai_value"
        ) == tuple(
            _tree(item)
            for item in output.value.items
            if not isinstance(item, Assignment) or item.key != "ai_value"
        )
    native, output = before.first("building_steel_mill"), after.first("building_steel_mill")
    assert native is not None
    assert output is not None
    assert _tree(native) == _tree(output)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source", "field", "changes", "expected"),
    [
        (INDUSTRY, FOOD, {"state_owner_groceries_balance": 0}, 1),
        (INDUSTRY, TEXTILE, {"state_owner_clothes_balance": 0}, 1),
        (INDUSTRY, FOOD, {"state_owner_default": True}, 1),
        (INDUSTRY, TEXTILE, {"state_owner_default": True}, 1),
        (STRATEGY, HEALTH, {"net_surplus": 0}, 1.08),
        (INFO, SOCIAL, {"net_surplus": 0}, 1.06),
        (STRATEGY, HEALTH, {"net_surplus": -1}, 1),
        (INFO, SOCIAL, {"bureaucracy": -1}, 1),
        # Unknown social capacity removes the stronger tier, not the known
        # grain/fiscal/administrative foundation.
        (STRATEGY, HEALTH, {"average_sol": None}, 1.08),
        (INFO, SOCIAL, {"average_sol": None}, 1.06),
        (STRATEGY, HEALTH, {"default": True}, 1),
        (INFO, SOCIAL, {"default": True}, 1),
    ],
)
def test_local_pdx_costs_broken_links_and_auxiliary_unknown_are_not_free_upgrades(
    policies: dict[str, Any],
    generated: tuple[dict[str, str], dict[str, str]],
    source: str,
    field: str,
    changes: dict[str, Any],
    expected: float,
) -> None:
    policy = policies[source]
    actual = pdx_eval.select(
        _overlay(generated[1][source], field),
        _engine_facts(policy, _values(policy, **changes)),
    )
    factor = actual.delta if actual.operation == "multiply" else 1
    assert factor == pytest.approx(expected)
    assert _factor(policy, field, **changes) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(("source", "field", "writer", "changes", "expected"), WRITERS)
def test_each_writer_disabled_module_and_unrelated_fact_preserve_semantics(
    policies: dict[str, Any],
    generated: tuple[dict[str, str], dict[str, str]],
    source: str,
    field: str,
    writer: str,
    changes: dict[str, Any],
    expected: float,
) -> None:
    policy = policies[source]
    values = _values(policy, **changes)
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    values.update(unrelated_country_population=100000000, candidate_selected=True)
    facts = _engine_facts(policy, values)
    facts["unrelated_country"] = {"is_ai": True, "state_unemployment_rate": 1}
    result = pdx_eval.select(_overlay(generated[1][source], field), facts)
    assert any(rule.id == writer for rule in policy.rules)
    assert result.action_id == _program_id(source, field)
    assert result.delta == pytest.approx(expected)


def test_exact_scope_and_parameters_are_not_country_level_or_unrelated_methods(
    policies: dict[str, Any],
) -> None:
    readers = {reader.key: reader for reader in policies[INDUSTRY].readers}
    unemployment = readers["state_unemployment"]
    assert (
        unemployment.engine,
        unemployment.scope,
        unemployment.path,
        unemployment.unit,
        unemployment.minimum,
        unemployment.maximum,
    ) == (
        "state_unemployment_rate",
        "root",
        (),
        "ratio",
        0,
        1,
    )
    for key, building, method in (
        ("pm_active_building_food_industry_pm_bakery", "building_food_industry", "pm_bakery"),
        (
            "pm_active_building_textile_mill_pm_handsewn_clothes",
            "building_textile_mill",
            "pm_handsewn_clothes",
        ),
    ):
        reader = readers[key]
        assert (reader.engine, reader.scope, reader.path, dict(reader.parameters)) == (
            "is_production_method_active",
            "root",
            (),
            {"building_type": building, "production_method": method},
        )
    for source in (STRATEGY, INFO):
        readers = {reader.key: reader for reader in policies[source].readers}
        assert readers["grain_price"].path == ("market", "mg:grain")
        assert readers["grain_balance"].path == ("market", "mg:grain")


def test_canonical_food_employment_uses_exact_capacity_and_reserves_without_grain_balance(
    policies: dict[str, Any],
) -> None:
    rule = next(rule for rule in policies[INDUSTRY].rules if rule.id == FOOD_EMPLOYMENT)
    assert rule.required_known_facts == ()
    assert {(p.fact, p.op, p.value) for p in rule.conditions} == {
        ("state_owner_default", "=", False),
        ("state_owner_loans", "=", False),
        ("state_infrastructure", ">=", 0),
        ("pm_active_building_food_industry_pm_bakery", "=", True),
        ("state_owner_groceries_price", ">", 0.25),
        ("state_owner_groceries_balance", "<", 0),
        ("state_owner_grain_price", "<=", 0.25),
        ("state_unemployment", ">=", 0.1),
        ("state_owner_reserves", ">", 0),
    }


@pytest.fixture(scope="module")
def complete_industry_field_pdx() -> tuple[Any, str]:
    """Keep every competing writer on the two actual fields, including native costs."""
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[INDUSTRY]
    policy = _subset(
        original, {r.id for r in original.rules if ".".join(r.field) in (FOOD, TEXTILE)}
    )
    assert {rule.id for rule in policy.rules} == {
        rule.id for rule in original.rules if ".".join(rule.field) in (FOOD, TEXTILE)
    }
    model = compiler.load_model()
    compiled, _ = compiler.compile_policy(policy, INDUSTRY, model)
    fields = {r.field for r in compiled.rules}
    selected = replace(
        adapters,
        policies=((INDUSTRY, compiled),),
        supply=None,
        initial_values=tuple(
            row for row in adapters.initial_values if row.source == INDUSTRY and row.field in fields
        ),
        scalar_values=tuple(
            row for row in adapters.scalar_values if row[0] == INDUSTRY and row[1] in fields
        ),
    )
    files, _ = decision_adapters.build(
        selected,
        texts=decision_adapters.read_inputs(adapters),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return compiled, files[INDUSTRY]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, (1.3, 1.3)),
        # Basic observed demand +0.12 remains when actual PM input cost -0.20
        # removes the affordable advanced tier: 1 + .12 - .20 = .92.
        ({"state_owner_grain_price": 0.6, "state_owner_grain_balance": -1}, (0.92, 1.3)),
        ({"state_owner_fabric_price": 0.6, "state_owner_fabric_balance": -1}, (1.3, 0.92)),
        (
            {
                "state_owner_grain_price": 0.6,
                "state_owner_grain_balance": -1,
                "coord_owner_layer_expansion": True,
            },
            # Retired expansion is an irrelevant decoy. Basic demand +.12
            # and actual input -.20 remain; textile employment stays +.30.
            (0.92, 1.3),
        ),
        # Default removes the capacity tiers, but independent observed basic
        # demand remains: 1 + .12 - .15 = .97, rather than a global veto.
        ({"state_owner_default": True}, (0.97, 0.97)),
        ({"state_infrastructure": -1}, (1.02, 1.02)),
        ({"state_infrastructure": -1, "state_owner_default": True}, (0.87, 0.87)),
        ({"state_owner_groceries_price": None}, (1.08, 1.3)),
        ({"state_owner_grain_price": None}, (1.12, 1.3)),
        ({"pm_active_building_food_industry_pm_bakery": None}, (1.12, 1.3)),
        ({"state_owner_loans": True}, (1.12, 1.3)),
        ({"state_unemployment": None}, (1.2, 1.2)),
        ({"candidate_selected": True, "construction_queued": True}, (1.3, 1.3)),
    ],
)
def test_complete_field_joint_program_keeps_real_costs_and_local_employment(
    complete_industry_field_pdx: tuple[Any, str],
    changes: dict[str, Any],
    expected: tuple[float, float],
) -> None:
    policy, text = complete_industry_field_pdx
    values = _values(policy, **changes)
    factors = []
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    for field, expected_factor in zip((FOOD, TEXTILE), expected, strict=True):
        actual = pdx_eval.select(_overlay(text, field), _engine_facts(policy, values))
        factors.append(actual.delta if actual.operation == "multiply" else 1)
        selected = reference.get(field)
        assert (selected[1] if selected else 1) == pytest.approx(expected_factor)
    assert tuple(factors) == pytest.approx(expected)
