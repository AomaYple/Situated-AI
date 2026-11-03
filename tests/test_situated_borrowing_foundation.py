"""借款不禁止基础机会；已观察配方、投入、偿付和物流共同参与。"""

import re
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.unit
TARGETS = [
    ("common/buildings/01_industry.txt", "tooling_workshop", "tools", "pm_crude_tools", "wood"),
    (
        "common/buildings/03_mines.txt",
        "iron_mine",
        "iron",
        "pm_picks_and_shovels_building_iron_mine",
        "tools",
    ),
    (
        "common/buildings/03_mines.txt",
        "coal_mine",
        "coal",
        "pm_picks_and_shovels_building_coal_mine",
        "tools",
    ),
]


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    policies = {}
    for source, policy in adapters.policies:
        fields = {f"building_{target}.ai_value" for s, target, *_ in TARGETS if s == source}
        if not fields:
            continue
        rules = tuple(r for r in policy.rules if ".".join(r.field) in fields)
        keys = {key for rule in rules for key in rule.input_keys()}
        policies[source] = replace(
            policy,
            rules=rules,
            readers=tuple(r for r in policy.readers if r.key in keys),
            semantic_ir=(),
            enabled_domains=frozenset(r.domain for r in rules),
        )
    model = compiler.load_model()
    policies = {
        source: compiler.compile_policy(policy, source, model)[0]
        for source, policy in policies.items()
    }
    return adapters, policies


def _values(policy, target, good, pm, **changes):
    values: dict[str, Any] = {r.key: False if r.kind == "boolean" else 0 for r in policy.readers}
    values.update({r.key: 0.2 for r in policy.readers if r.key.endswith("_price")})
    values.update(
        {
            "state_owner_loans": True,
            f"pm_active_building_{target}_{pm}": True,
            f"state_owner_{good}_price": 0.3,
            f"state_owner_{good}_balance": -1,
        }
    )
    values.update(changes)
    return values


def _facts(policy, values, *, ai=True):
    root: dict[str, Any] = {}
    for reader in policy.readers:
        node = root
        for part in reader.path:
            node = node.setdefault(part, {})
        observed = values.get(reader.key)
        if reader.engine == "is_production_method_active":
            params = dict(reader.parameters)
            node.setdefault(reader.engine, {}).setdefault(params["building_type"], {})[
                params["production_method"]
            ] = observed
        elif reader.argument is not None or reader.parameters:
            params = dict(reader.parameters)
            if reader.argument is not None:
                params["argument"] = reader.argument
            node.setdefault(reader.engine, {})[tuple(sorted(params.items()))] = observed
        else:
            node[reader.engine] = observed
        if reader.engine.startswith("sitai_context_"):
            node[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                observed is not None
            )
    root.setdefault("owner", {})["is_ai"] = ai
    return {"ROOT": root}


def _overlay(text, field):
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    lines: list[str] = []
    for line in text[begin:end].splitlines()[1:]:
        if line.lstrip().startswith(("if =", "else_if =")) and (
            not lines or not lines[-1].lstrip().startswith("# ")
        ):
            lines.append("# borrowing_unknown_guard [test]; retain native")
        lines.append(line)
    return "\n".join(lines)


def _tree(node):
    if hasattr(node, "unquoted"):
        return node.unquoted
    if hasattr(node, "key"):
        return (node.key, node.op, _tree(node.value))
    return tuple(_tree(item) for item in node.items)


@pytest.fixture(scope="module")
def generated(production):
    adapters, policies = production
    model = compiler.load_model()
    assert model.consumer_ir is not None
    compiled = tuple((s, compiler.compile_policy(p, s, model)[0]) for s, p in policies.items())
    selected = replace(
        adapters,
        policies=compiled,
        initial_values=tuple(
            row
            for row in adapters.initial_values
            if row.source in policies and row.field in {r.field for r in policies[row.source].rules}
        ),
        scalar_values=tuple(
            row
            for row in adapters.scalar_values
            if row[0] in policies and row[1] in {r.field for r in policies[row[0]].rules}
        ),
        supply=None,
    )
    inputs = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return inputs, files


@pytest.mark.parametrize(("source", "target", "good", "pm", "cost"), TARGETS)
@pytest.mark.parametrize(
    "scenario",
    [
        "borrow",
        "no_loans",
        "cost",
        "exit",
        "default",
        "loans_unknown",
        "pm_unknown",
        "infra_unknown",
        "cost_unknown",
        "player",
        "price_threshold",
        "price_above_threshold",
        "infra_deficit",
        "candidate_only",
    ],
)
def test_complete_field_borrowing_and_cost_reference(
    production, source, target, good, pm, cost, scenario
):
    policy = production[1][source]
    values = _values(policy, target, good, pm)
    factor = 1.2
    if scenario == "no_loans":
        values["state_owner_loans"] = False
        factor = 1.2
    elif scenario == "cost":
        values.update({f"state_owner_{cost}_price": 0.6, f"state_owner_{cost}_balance": -1})
        factor = 1.0
    elif scenario == "exit":
        values[f"state_owner_{good}_balance"] = 0
        factor = 1
    elif scenario == "default":
        values["state_owner_default"] = True
        factor = 1.05
    elif scenario.endswith("unknown"):
        key = {
            "loans_unknown": "state_owner_loans",
            "pm_unknown": f"pm_active_building_{target}_{pm}",
            "infra_unknown": "state_infrastructure",
            "cost_unknown": f"state_owner_{cost}_price",
        }[scenario]
        values[key] = None
        factor = 1.12 if scenario == "pm_unknown" else 1.2
    elif scenario == "player":
        factor = 1
    elif scenario == "price_threshold":
        values[f"state_owner_{good}_price"] = 0.25
        factor = 1.08
    elif scenario == "price_above_threshold":
        values[f"state_owner_{good}_price"] = 0.251
    elif scenario == "infra_deficit":
        values["state_infrastructure"] = -0.001
        factor = 1.1
    elif scenario == "candidate_only":
        values.update(candidate_selected=True, construction_queued=True)
    result = decision_rules.evaluate(policy, values, is_ai=scenario != "player").get(
        f"building_{target}.ai_value"
    )
    assert (result[1] if result else 1) == pytest.approx(factor)
    if scenario in {"borrow", "candidate_only", "price_above_threshold"}:
        assert result is not None
        assert result[0].startswith("program_")
        assert result[1] == pytest.approx(1.2)


@pytest.mark.integration
@pytest.mark.parametrize(("source", "target", "good", "pm", "cost"), TARGETS)
@pytest.mark.parametrize(
    "scenario", ["borrow", "cost", "exit", "unknown", "player", "missing_owner"]
)
def test_actual_pdx_preserves_borrowing_cost_and_scopes(
    production, generated, source, target, good, pm, cost, scenario
):
    policy = production[1][source]
    values = _values(policy, target, good, pm)
    expected = 1.2
    if scenario == "cost":
        values.update({f"state_owner_{cost}_price": 0.6, f"state_owner_{cost}_balance": -1})
        expected = 1.0
    elif scenario == "exit":
        values[f"state_owner_{good}_balance"] = 0
        expected = 1
    elif scenario == "unknown":
        values["state_owner_loans"] = None
        expected = 1.2
    facts = _facts(policy, values, ai=scenario != "player")
    if scenario == "missing_owner":
        del facts["ROOT"]["owner"]
    if scenario in {"player", "missing_owner"}:
        expected = 1
    observed = pdx_eval.select(_overlay(generated[1][source], f"building_{target}.ai_value"), facts)
    factor = observed.delta if observed.operation == "multiply" else 1
    assert factor == pytest.approx(expected)


@pytest.mark.integration
def test_disabled_mod_and_qualification_tail_remain_native(production, generated):
    inputs, files = generated
    for source, target, *_ in TARGETS:
        native = parse_text(inputs[source]).root.first(f"building_{target}")
        clean = re.sub(
            r"[^\S\n]*# SITAI BEGIN information:[^\n]*\n.*?[^\S\n]*# SITAI END information:[^\n]*(?:\n|$)",
            "",
            files[source],
            flags=re.DOTALL,
        )
        clean = re.sub(
            r"ai_value = \{ value = ([0-9]+(?:\.[0-9]+)?) # SITAI wrapped-scalar:[^\n]*\s*\}",
            r"ai_value = \1",
            clean,
        )
        output = parse_text(clean).root.first(f"building_{target}")
        assert native is not None
        assert output is not None
        assert isinstance(native.value, Block)
        assert isinstance(output.value, Block)
        assert _tree(native) == _tree(output)
        if target == "coal_mine":
            ai_value = native.value.first("ai_value")
            assert ai_value is not None
            assert "geographic_region_korea" in str(_tree(ai_value))
            assert "c:JAP" in str(_tree(ai_value))
            assert "2000" in str(_tree(ai_value))

    disabled, _ = decision_adapters.build(production[0], texts=inputs, enabled_domains=frozenset())
    assert disabled == {}


@pytest.mark.parametrize(("source", "target", "good", "pm", "cost"), TARGETS)
def test_fiscal_insolvency_does_not_bypass_real_input_cost(
    production, source, target, good, pm, cost
):
    policy = production[1][source]
    values = _values(policy, target, good, pm, state_owner_default=True)
    values.update({f"state_owner_{cost}_price": 0.6, f"state_owner_{cost}_balance": -1})
    result = decision_rules.evaluate(policy, values, is_ai=True)[f"building_{target}.ai_value"]
    # Demand +.20, observed input -.20 and default -.15 all participate.
    assert result[1] == pytest.approx(0.85)
    assert result[0].startswith("program_")


@pytest.mark.integration
@pytest.mark.parametrize(("source", "target", "good", "pm", "cost"), TARGETS)
@pytest.mark.parametrize("missing", ["method_false", "method_unknown", "demand_resolved"])
def test_candidate_or_queue_cannot_replace_actual_recipe_or_need(
    production, generated, source, target, good, pm, cost, missing
):
    policy = production[1][source]
    values = _values(policy, target, good, pm)
    if missing == "method_false":
        values[f"pm_active_building_{target}_{pm}"] = False
    elif missing == "method_unknown":
        values[f"pm_active_building_{target}_{pm}"] = None
    else:
        values[f"state_owner_{good}_balance"] = 0
    # These represent a pending intention, never an observation of completion.
    values.update(candidate_selected=True, construction_queued=True)
    before = deepcopy(values)
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    expected = 1.12 if missing in {"method_false", "method_unknown"} else 1.0
    result = reference.get(f"building_{target}.ai_value")
    assert (result[1] if result else 1) == pytest.approx(expected)
    assert reference == decision_rules.evaluate(
        policy,
        {k: v for k, v in values.items() if k not in {"candidate_selected", "construction_queued"}},
        is_ai=True,
    )
    assert values == before
    facts = _facts(policy, values)
    facts["ROOT"].update(candidate_selected=True, construction_queued=True)
    before_facts = deepcopy(facts)
    actual = pdx_eval.select(_overlay(generated[1][source], f"building_{target}.ai_value"), facts)
    assert (actual.delta if actual.operation == "multiply" else 1) == pytest.approx(expected)
    assert values == before
    assert facts == before_facts
