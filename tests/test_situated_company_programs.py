"""Company plans: handwritten sector values and actual generated PDX witnesses.

Workforce share is a labor-structure proxy, not unemployment or vacancies.
Default is a national opportunity cost, not payment for founding a company.
Possible PM recipes establish shared inputs; they do not identify active PMs.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from pdx import config, country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
EUROPE = "common/company_types/00_companies_europe.txt"
AMERICA = "common/company_types/00_companies_mp1.txt"
# These are independent fixtures, not a production company/TAG classification.
COMPANIES = {
    "company_lkab": (EUROPE, "iron", "country_goods_tools_price", "building_iron_mine"),
    "company_ursus": (EUROPE, "engines", "country_goods_steel_price", "building_motor_industry"),
    "company_colt_firearms": (
        AMERICA,
        "small_arms",
        "country_goods_hardwood_price",
        "building_arms_industry",
    ),
}


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policies = {}
    for source in (EUROPE, AMERICA):
        raw = dict(adapters.policies)[source]
        fields = {(company, "ai_weight") for company, row in COMPANIES.items() if row[0] == source}
        rules = tuple(rule for rule in raw.rules if rule.field in fields)
        assert {rule.field for rule in rules} == fields
        keys = frozenset(key for rule in rules for key in rule.input_keys())
        raw = replace(
            raw,
            rules=rules,
            readers=tuple(reader for reader in raw.readers if reader.key in keys),
            enabled_domains=frozenset(rule.domain for rule in rules),
            semantic_ir=(),
            consumer_programs=(),
        )
        policies[source] = compiler.compile_policy(raw, source, model)[0]
    selected = replace(
        adapters,
        policies=tuple(policies.items()),
        initial_values=(),
        scalar_values=(),
        supply=None,
    )
    generated, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policies, inputs, generated, selected, model


def _values(policy, changes: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {
        reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers
    }
    values.update(changes)
    return values


def _engine(policy, values, *, is_ai=True):
    root: dict[str, Any] = {"is_ai": is_ai}
    for reader in policy.readers:
        assert reader.scope == "root"
        current = root
        for component in reader.path:
            current = current.setdefault(component, {})
        if reader.argument is not None or reader.parameters or reader.value_field is not None:
            parameters = dict(reader.parameters)
            if reader.argument is not None:
                parameters["argument"] = reader.argument
            current.setdefault(reader.engine, {})[tuple(sorted(parameters.items()))] = values[
                reader.key
            ]
        else:
            current[reader.engine] = values[reader.key]
    return {"ROOT": root}


def _overlay(text, company):
    marker = f"information:{company}.ai_weight"
    start = text.index(f"# SITAI BEGIN {marker}")
    end = text.index(f"# SITAI END {marker}", start)
    return "\n".join(text[start:end].splitlines()[1:])


def _assert_value(production, company, changes, expected):
    policies, _inputs, generated, _selected, _model = production
    source = COMPANIES[company][0]
    policy = policies[source]
    values = _values(policy, changes)
    field = f"{company}.ai_weight"
    identity = "program_" + hashlib.sha256(f"{source}:{field}".encode()).hexdigest()[:16]
    result = pdx_eval.select(_overlay(generated[source], company), _engine(policy, values))
    assert (result.action_id, result.operation) == (identity, "multiply")
    assert result.delta == pytest.approx(expected)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    if expected == 1:
        assert reference is None
    else:
        assert reference is not None
        assert reference[0] == identity
        assert reference[1] == pytest.approx(expected)


# Role aliases keep the same handwritten expectations across distinct recipes.
# Output price only upgrades an already observed shortage, never replaces it.
CASES = [
    ({}, 1),
    ({"balance": -1}, 1.12),
    ({"balance": 0}, 1),
    ({"balance": 1, "price": 0.5}, 1),
    ({"balance": None, "price": 0.5}, 1),
    ({"balance": -1, "price": None}, 1.12),
    ({"balance": -1, "price": 0.25}, 1.12),
    ({"balance": -1, "price": 0.251}, 1.20),
    ({"input": 0.25}, 1),
    ({"input": 0.251}, 0.85),
    ({"input": None}, 1),
    ({"balance": -1, "input": 0.5}, 0.97),
    ({"balance": -1, "price": 0.5, "input": 0.5}, 1.05),
    ({"industrial_workforce": 0.149}, 1),
    ({"industrial_workforce": 0.15}, 1.04),
    ({"industrial_workforce": None}, 1),
    ({"default": True}, 0.80),
    ({"default": None}, 1),
    ({"balance": -1, "default": True}, 0.92),
    ({"balance": -1, "price": None, "input": 0.5, "default": True}, 0.77),
    (
        {
            "balance": -1,
            "price": 0.5,
            "input": 0.5,
            "industrial_workforce": 0.15,
            "default": True,
        },
        0.89,
    ),
    ({"balance": -1, "price": 0.5, "industrial_workforce": 0.15}, 1.24),
    ({"input": 0.5, "default": True}, 0.65),
    ({"balance": None, "price": None, "input": None, "default": None}, 1),
]


@pytest.mark.parametrize("company", COMPANIES)
@pytest.mark.parametrize(("roles", "expected"), CASES)
def test_handwritten_company_joint_values_and_local_unknowns(production, company, roles, expected):
    _source, good, input_key, _building = COMPANIES[company]
    aliases = {
        "balance": f"country_goods_{good}_balance",
        "price": f"country_goods_{good}_price",
        "input": input_key,
    }
    changes = {aliases.get(key, key): value for key, value in roles.items()}
    _assert_value(production, company, changes, expected)


def _tree(node):
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def test_native_qualifications_targets_prosperity_and_weight_tail_are_unchanged(production):
    _policies, inputs, generated, _selected, _model = production
    for source, text in generated.items():
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            text,
            flags=re.DOTALL | re.MULTILINE,
        )
        before, after = parse_text(inputs[source]), parse_text(stripped)
        assert not before.errors
        assert not after.errors
        assert _tree(before.root) == _tree(after.root)
    for company, (source, _good, _input_key, building) in COMPANIES.items():
        definition = parse_text(inputs[source]).root.first(company)
        assert definition is not None
        assert isinstance(definition.value, Block)
        weight = definition.value.first("ai_weight")
        assert weight is not None
        assert isinstance(weight.value, Block)
        assert _tree(weight.value) == (("value", "=", "3"),)
        primary = definition.value.first("building_types")
        assert primary is not None
        assert isinstance(primary.value, Block)
        assert [item.unquoted for item in primary.value.scalars()] == [building]
        assert definition.value.first("ai_will_do") is not None


@pytest.mark.parametrize("company", COMPANIES)
def test_country_actor_player_off_and_foreign_candidate_decoys(production, company):
    policies, inputs, generated, selected, model = production
    source, good, input_key, _building = COMPANIES[company]
    policy = policies[source]
    assert policy.actor_path == ()
    values = _values(
        policy,
        {
            f"country_goods_{good}_balance": -1,
            f"country_goods_{good}_price": 0.5,
            input_key: 0.5,
            "default": True,
        },
    )
    overlay = _overlay(generated[source], company)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert pdx_eval.select(overlay, _engine(policy, values, is_ai=False)).operation is None
    foreign = _engine(policy, values)["ROOT"]
    decoys = {
        "ROOT": {"is_ai": True},
        "scope:target_country": foreign,
        "scope:target_state": {"owner": foreign},
        "company": foreign,
        "owner": foreign,
    }
    assert pdx_eval.select(overlay, decoys).delta == 1
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        enabled_domains=frozenset(),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    assert files == {}


def test_company_program_bounds_and_exact_reader_identity(production):
    policies, _inputs, _generated, _selected, model = production
    for company, (source, good, input_key, _building) in COMPANIES.items():
        policy = policies[source]
        program = next(
            item for item in policy.consumer_programs if item.field == (company, "ai_weight")
        )
        assert (program.lower, program.upper) == pytest.approx((0.65, 1.24))
        assert 0.60 <= program.lower <= program.upper <= 1.40
        rules = [rule for rule in policy.rules if rule.field == program.field]
        assert len(rules) == 5
        assert len({rule.contribution_group for rule in rules}) == 4
        assert all(rule.contribution_group for rule in rules)
        readers = {reader.key: reader for reader in policy.readers}
        for key, commodity, engine, unit in (
            (f"country_goods_{good}_balance", good, "market_goods_delta", "sell_minus_buy_orders"),
            (f"country_goods_{good}_price", good, "market_goods_pricier", "price_above_base_ratio"),
            (
                input_key,
                {
                    "company_lkab": "tools",
                    "company_ursus": "steel",
                    "company_colt_firearms": "hardwood",
                }[company],
                "market_goods_pricier",
                "price_above_base_ratio",
            ),
        ):
            reader = readers[key]
            assert (reader.scope, reader.path, reader.engine, reader.unit) == (
                "root",
                ("market", f"mg:{commodity}"),
                engine,
                unit,
            )
        worker = readers["industrial_workforce"]
        assert (worker.engine, worker.path, worker.value_field, worker.parameters) == (
            "pop_type_percent_country",
            (),
            "percent",
            (("pop_type", "laborers"),),
        )
        assert (worker.unit, worker.minimum, worker.maximum) == ("ratio", 0, 1)
        writers = [
            row
            for row in model.consumer_ir.writers
            if row.source == source and row.field == f"{company}.ai_weight"
        ]
        assert len(writers) == 5
        for row in writers:
            context = row.evaluation_context
            assert context is not None
            assert context.status == "observed"
            assert context.actor_scope is not None
            assert (context.actor_scope.name, context.actor_scope.kind) == ("root", "country")
            assert context.targets == ()


@pytest.mark.parametrize("company", COMPANIES)
def test_another_goods_or_population_query_cannot_supply_a_required_fact(production, company):
    policies, _inputs, generated, _selected, _model = production
    source, good, _input_key, _building = COMPANIES[company]
    policy = policies[source]
    values = _values(
        policy, {f"country_goods_{good}_balance": -1, f"country_goods_{good}_price": 0.5}
    )
    facts = _engine(policy, values)
    facts["ROOT"]["market"]["mg:unrelated_good"] = facts["ROOT"]["market"].pop(f"mg:{good}")
    facts["ROOT"]["pop_type_percent_country"] = {(("pop_type", "peasants"),): 0.9}
    assert pdx_eval.select(_overlay(generated[source], company), facts).delta == 1


@pytest.mark.parametrize("company", COMPANIES)
@pytest.mark.parametrize("native_score", [0, -3, 3])
def test_patch_preserves_native_zero_negative_and_numeric_tail(production, company, native_score):
    policies, inputs, _generated, selected, model = production
    source, good, _input_key, _building = COMPANIES[company]
    policy = policies[source]
    definition = parse_text(inputs[source]).root.first(company)
    assert definition is not None
    assert isinstance(definition.value, Block)
    weight = definition.value.first("ai_weight")
    assert weight is not None
    assert isinstance(weight.value, Block)
    initial = weight.value.first("value")
    assert initial is not None
    lines = inputs[source].splitlines(keepends=True)
    # Explicit synthetic derived input: it does not change the locked baseline
    # or attest that this zero/negative fixture occurs in vanilla.
    lines[initial.line - 1] = re.sub(
        r"value\s*=\s*3", f"value = {native_score}", lines[initial.line - 1], count=1
    )
    derived = "".join(lines)
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        overlays={source: derived},
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    patched = parse_text(files[source]).root.first(company)
    assert patched is not None
    assert isinstance(patched.value, Block)
    patched_weight = patched.value.first("ai_weight")
    assert patched_weight is not None
    assert isinstance(patched_weight.value, Block)
    assert _tree(patched_weight.value.items[0]) == ("value", "=", str(native_score))
    values = _values(
        policy, {f"country_goods_{good}_balance": -1, f"country_goods_{good}_price": 0.5}
    )
    result = pdx_eval.select(_overlay(files[source], company), _engine(policy, values))
    assert result.operation == "multiply"
    assert result.delta == pytest.approx(1.20)
    # The retained native nonpositive-rejection boundary cannot be crossed by
    # the generated positive multiplier. This is a numeric witness, not a game run.
    assert native_score * result.delta == pytest.approx({0: 0, -3: -3.6, 3: 3.6}[native_score])


def _assignments(block):
    for assignment in block.assignments():
        yield assignment
        if isinstance(assignment.value, Block):
            yield from _assignments(assignment.value)


@pytest.mark.parametrize(
    ("source", "methods", "input_good", "output_good"),
    [
        (
            "common/production_methods/03_mines.txt",
            (
                "pm_picks_and_shovels_building_iron_mine",
                "pm_atmospheric_engine_pump_building_iron_mine",
                "pm_condensing_engine_pump_building_iron_mine",
                "pm_diesel_pump_building_iron_mine",
            ),
            "tools",
            "iron",
        ),
        (
            "common/production_methods/01_industry.txt",
            ("pm_steam_engines", "pm_electric_engines", "pm_diesel_engines"),
            "steel",
            "engines",
        ),
        (
            "common/production_methods/01_industry.txt",
            ("pm_muskets", "pm_rifles", "pm_repeaters", "pm_bolt_action_rifles"),
            "hardwood",
            "small_arms",
        ),
    ],
)
def test_sector_input_is_shared_by_actual_native_base_recipes(
    source, methods, input_good, output_good
):
    filename = source.rsplit("/", 1)[1]
    building, group = {
        "iron": ("building_iron_mine", "pmg_mining_equipment_building_iron_mine"),
        "engines": ("building_motor_industry", "pmg_base_building_motor_industry"),
        "small_arms": ("building_arms_industry", "pmg_firearms_manufacturing"),
    }[output_good]
    buildings = parse_text(
        (config.GAME / "common/buildings" / filename).read_text(encoding="utf-8-sig")
    )
    building_definition = buildings.root.first(building)
    assert building_definition is not None
    assert isinstance(building_definition.value, Block)
    linked_groups = building_definition.value.first("production_method_groups")
    assert linked_groups is not None
    assert isinstance(linked_groups.value, Block)
    assert group in [item.unquoted for item in linked_groups.value.scalars()]
    groups = parse_text(
        (config.GAME / "common/production_method_groups" / filename).read_text(encoding="utf-8-sig")
    )
    group_definition = groups.root.first(group)
    assert group_definition is not None
    assert isinstance(group_definition.value, Block)
    linked_methods = group_definition.value.first("production_methods")
    assert linked_methods is not None
    assert isinstance(linked_methods.value, Block)
    assert [item.unquoted for item in linked_methods.value.scalars()] == list(methods)
    text = (config.GAME / source).read_text(encoding="utf-8-sig")
    parsed = parse_text(text)
    assert not parsed.errors
    for name in methods:
        method = parsed.root.first(name)
        assert method is not None, name
        assert isinstance(method.value, Block)
        modifiers = method.value.first("building_modifiers")
        assert modifiers is not None
        assert isinstance(modifiers.value, Block)
        recipe = {
            item.key: float(item.value.unquoted)
            for item in _assignments(modifiers.value)
            if isinstance(item.value, Scalar)
        }
        assert recipe[f"goods_input_{input_good}_add"] > 0
        assert recipe[f"goods_output_{output_good}_add"] > 0
        assert recipe["building_employment_laborers_add"] > 0
