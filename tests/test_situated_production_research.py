"""Research demand is not payment for the production methods it may unlock."""

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
SOURCE = "common/technology/technologies/10_production.txt"
GENERIC = [
    "aniline",
    "arc_welding",
    "art_silk",
    "atmospheric_engine",
    "automatic_bottle_blowers",
    "baking_powder",
    "bessemer_process",
    "canneries",
    "chemical_bleaching",
    "combustion_engine",
    "compression_ignition",
    "conveyors",
    "cotton_gin",
    "crystal_glass",
    "distillation",
    "dough_rollers",
    "dynamite",
    "electric_arc_process",
    "electric_railway",
    "electrical_capacitors",
    "electrical_generation",
    "enclosure",
    "flash_freezing",
    "fractional_distillation",
    "improved_fertilizer",
    "intensive_agriculture",
    "lathe",
    "manufacturies",
    "mechanical_tools",
    "mechanized_farming",
    "mechanized_workshops",
    "nitrogen_fixation",
    "nitroglycerin",
    "oil_turbine",
    "open_hearth_process",
    "pasteurization",
    "plastics",
    "pneumatic_tools",
    "prospecting",
    "pumpjacks",
    "radio",
    "railways",
    "reinforced_concrete",
    "rotary_valve_engine",
    "rubber_mastication",
    "sericulture",
    "shaft_mining",
    "shift_work",
    "steam_donkey",
    "steam_turbine",
    "steel_railway_cars",
    "steelworking",
    "telephone",
    "threshing_machine",
    "vacuum_canning",
    "vulcanization",
    "watertube_boiler",
]


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy = compiler.compile_policy(dict(adapters.policies)[SOURCE], SOURCE, model)[0]
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


def _values(policy, changes: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {r.key: False if r.kind == "boolean" else 0 for r in policy.readers}
    values.update(changes)
    return values


def _context(policy, values, *, is_ai=True):
    # Complete empty collections prove that no productive/labor-use option
    # exists in these market-only scenarios; aggregate booleans are not objects.
    root: dict[str, Any] = {
        "is_ai": is_ai,
        "any_scope_state": [],
        "any_scope_building": [],
    }
    for reader in policy.readers:
        assert reader.scope == "root"
        if reader.engine in {"any_scope_state", "any_scope_building"}:
            continue
        target = root
        for component in reader.path:
            target = target.setdefault(component, {})
        if reader.argument is not None or reader.parameters or reader.value_field is not None:
            params = dict(reader.parameters)
            if reader.argument is not None:
                params["argument"] = reader.argument
            target.setdefault(reader.engine, {})[tuple(sorted(params.items()))] = values[reader.key]
        else:
            target[reader.engine] = values[reader.key]
    return {"ROOT": root}


def _overlay(text, technology):
    marker = f"information:{technology}.ai_weight"
    start = text.index(f"# SITAI BEGIN {marker}")
    end = text.index(f"# SITAI END {marker}", start)
    return "\n".join(text[start:end].splitlines()[1:])


@pytest.mark.parametrize(
    "changes",
    [
        {"industrial": True},
        {"industrial": True, "default": True, "loans": True, "war": True},
        {
            "industrial": True,
            "default": None,
            "loans": None,
            "war": None,
            "net_surplus": -100,
            "bureaucracy": -100,
            "literacy": 0,
            "legitimacy": 0,
            "insurrection": True,
        },
    ],
)
def test_retired_industrial_route_alone_never_invents_concrete_research_demand(production, changes):
    policy, _native, generated = production
    values = _values(policy, changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    for technology in GENERIC:
        field = f"{technology}.ai_weight"
        assert field not in reference, technology
        result = pdx_eval.select(_overlay(generated, technology), _context(policy, values))
        assert result.operation == "multiply"
        assert result.delta == 1, technology


@pytest.mark.parametrize("industrial", [False, None])
def test_no_concrete_demand_is_inferred_from_crisis_or_unknown_route(production, industrial):
    policy, _native, generated = production
    values = _values(policy, {"industrial": industrial, "default": True, "war": True})
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    for technology in GENERIC:
        assert f"{technology}.ai_weight" not in reference
        assert pdx_eval.select(_overlay(generated, technology), _context(policy, values)).delta == 1


@pytest.mark.parametrize(
    ("technology", "good"),
    [
        ("atmospheric_engine", "engines"),
        ("intensive_agriculture", "grain"),
        ("mechanical_tools", "tools"),
        ("shaft_mining", "iron"),
        ("aniline", "dye"),
    ],
)
def test_concrete_shortage_research_survives_default_and_unknown_fiscal_facts(
    production, technology, good
):
    policy, _native, generated = production
    for default in (True, None):
        balance, price = f"country_goods_{good}_balance", f"country_goods_{good}_price"
        changes = {
            "default": default,
            "loans": True,
            "war": True,
            "bureaucracy": -100,
            "literacy": 0,
            "legitimacy": 0,
            "insurrection": True,
            balance: -1,
            price: 0.5,
        }
        values = _values(policy, changes)
        reference = decision_rules.evaluate(policy, values, is_ai=True)
        assert reference[f"{technology}.ai_weight"][1] == pytest.approx(1.2)
        actual = pdx_eval.select(_overlay(generated, technology), _context(policy, values))
        assert actual.delta == pytest.approx(1.2)
        for key, expected in ((price, 1.12), (balance, 1)):
            unknown = {**values, key: None}
            selection = decision_rules.evaluate(policy, unknown, is_ai=True).get(
                f"{technology}.ai_weight"
            )
            assert (selection[1] if selection else 1) == pytest.approx(expected)
            actual = pdx_eval.select(_overlay(generated, technology), _context(policy, unknown))
            assert actual.delta == pytest.approx(expected)


def _tree(node):
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def test_research_preserves_all_native_definitions_and_player_boundary(production):
    policy, native, generated = production
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
    values = _values(policy, {"industrial": True, "default": True, "war": True})
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    for technology in GENERIC:
        overlay = _overlay(generated, technology)
        assert pdx_eval.select(overlay, _context(policy, values, is_ai=False)).operation is None
        assert (
            pdx_eval.select(
                overlay, {"ROOT": {"is_ai": True}, "other": _context(policy, values)}
            ).delta
            == 1
        )
