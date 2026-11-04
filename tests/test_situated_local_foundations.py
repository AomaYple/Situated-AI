"""完整联合消费者：基础需求独立，真实投入升档，成本同时参与。"""

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
    ("common/buildings/07_government.txt", "university", "paper", "pm_scholastic_education", 80),
    ("common/buildings/11_private_infrastructure.txt", "railway", "coal", "pm_early_trains", 6000),
    ("common/buildings/01_industry.txt", "food_industry", "grain", "pm_bakery", 4000),
    ("common/buildings/01_industry.txt", "textile_mill", "fabric", "pm_handsewn_clothes", 4000),
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


def _values(policy, target, pm):
    values: dict[str, Any] = {r.key: False if r.kind == "boolean" else 0 for r in policy.readers}
    values.update({r.key: 0.2 for r in policy.readers if r.key.endswith("_price")})
    values.update(
        state_owner_loans=True,
        state_owner_academia_completed=True,
        state_owner_literacy=0.3,
        # This fixture isolates the existing demand/input foundation. Known
        # abundant peasants exclude the independent D3 tight-labor cost, which
        # has separate full-consumer boundary/unknown witnesses.
        state_peasants_share=0.5,
    )
    values[f"pm_active_building_{target}_{pm}"] = True
    if target == "railway":
        values["state_infrastructure"] = -1
    elif target in {"food_industry", "textile_mill"}:
        good = "groceries" if target == "food_industry" else "clothes"
        values[f"state_owner_{good}_price"] = 0.3
        values[f"state_owner_{good}_balance"] = -1
    return values


@pytest.mark.parametrize(("source", "target", "cost", "pm", "priority"), TARGETS)
def test_borrowing_direct_need_reaches_real_foundation(
    production, source, target, cost, pm, priority
):
    policy = production[1][source]
    values = _values(policy, target, pm)
    before = deepcopy(values)
    result = decision_rules.evaluate(policy, values, is_ai=True)
    expected = 1.2 if target in {"university", "railway"} else 1.12
    assert result[f"building_{target}.ai_value"][1] == pytest.approx(expected)
    assert policy.consumer_programs
    assert values == before


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


@pytest.mark.integration
@pytest.mark.parametrize(("source", "target", "cost", "pm", "priority"), TARGETS)
@pytest.mark.parametrize(
    "scenario",
    [
        "base",
        "input_cost",
        "input_unknown",
        "need_resolved",
        "loan_unknown",
        "loan_false",
        "player",
        "missing_owner",
        "unrelated",
        "candidate_false",
        "candidate_unknown",
        "cost_edge",
        "need_edge",
        "need_above",
        "default",
        "cost_above_edge",
        "cost_balance_unknown",
    ],
)
def test_complete_field_and_actual_pdx_local_foundation(
    production, generated, source, target, cost, pm, priority, scenario
):
    policy = production[1][source]
    values = _values(policy, target, pm)
    expected = 1.2 if target in {"university", "railway"} else 1.12
    actual_key = f"pm_active_building_{target}_{pm}"
    if scenario == "input_cost":
        values.update({f"state_owner_{cost}_price": 0.6, f"state_owner_{cost}_balance": -1})
        expected = {"university": 0.95, "railway": 0.9}.get(target, 0.92)
    elif scenario == "input_unknown":
        values[f"state_owner_{cost}_price"] = None
        expected = {"university": 1.15, "railway": 1.1}.get(target, 1.12)
    elif scenario == "need_resolved":
        if target == "university":
            values["state_owner_literacy"] = 0.5
        elif target == "railway":
            values["state_infrastructure"] = 0
        else:
            values[
                f"state_owner_{'groceries' if target == 'food_industry' else 'clothes'}_balance"
            ] = 0
        values.update(candidate_selected=True, construction_queued=True)
        expected = 1
    elif scenario == "loan_unknown":
        values["state_owner_loans"] = None
    elif scenario == "loan_false":
        values["state_owner_loans"] = False
        expected = 1.2
    elif scenario in {"player", "missing_owner"}:
        expected = 1
    elif scenario == "unrelated":
        values.update(bureaucracy=-100, legitimacy=0, war=True, candidate_selected=True)
    elif scenario in {"candidate_false", "candidate_unknown"}:
        values[actual_key] = False if scenario == "candidate_false" else None
        values.update(candidate_selected=True, construction_queued=True)
        expected = {"university": 1.15, "railway": 1.1}.get(target, 1.12)
    elif scenario == "default":
        values["state_owner_default"] = True
        expected = 1.05 if target in {"university", "railway"} else 0.97
    elif scenario == "cost_above_edge":
        values[f"state_owner_{cost}_price"] = 0.251
        expected = {"university": 1.15, "railway": 1.1}.get(target, 1.12)
    elif scenario == "cost_balance_unknown":
        values[f"state_owner_{cost}_balance"] = None
        expected = {"university": 1.15, "railway": 1.1}.get(target, 1.12)
    elif scenario == "cost_edge":
        values[f"state_owner_{cost}_price"] = 0.25
    elif scenario in {"need_edge", "need_above"}:
        if target == "university":
            values["state_owner_literacy"] = 0.5 if scenario == "need_edge" else 0.501
        elif target == "railway":
            values["state_infrastructure"] = 0 if scenario == "need_edge" else 0.001
        else:
            values[
                f"state_owner_{'groceries' if target == 'food_industry' else 'clothes'}_balance"
            ] = 0 if scenario == "need_edge" else 0.001
        expected = 1
    before = deepcopy(values)
    reference = decision_rules.evaluate(
        policy, values, is_ai=scenario not in {"player", "missing_owner"}
    ).get(f"building_{target}.ai_value")
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert values == before
    facts = _facts(policy, values, ai=scenario != "player")
    facts["ROOT"].update(candidate_selected=True, construction_queued=True)
    if scenario == "missing_owner":
        del facts["ROOT"]["owner"]
    before_facts = deepcopy(facts)
    result = pdx_eval.select(_overlay(generated[1][source], f"building_{target}.ai_value"), facts)
    assert (result.delta if result.operation == "multiply" else 1) == pytest.approx(expected)
    assert facts == before_facts
    assert values == before


@pytest.mark.integration
def test_all_native_building_semantics_and_disabled_output_remain(production, generated):
    inputs, files = generated
    for source, target, *_ in TARGETS:
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
        native = parse_text(inputs[source]).root.first(f"building_{target}")
        output = parse_text(clean).root.first(f"building_{target}")
        assert native is not None
        assert output is not None
        assert isinstance(native.value, Block)
        assert isinstance(output.value, Block)
        if native.value.first("ai_value") is None:
            # A missing scalar is initialized from the locked vanilla define,
            # independently checked against that input rather than discarded.
            value = output.value.first("ai_value")
            assert value is not None
            expected = next(
                row
                for row in production[0].initial_values
                if row.source == source and row.field[0] == f"building_{target}"
            )
            defined = parse_text(inputs[expected.define_source]).root
            block = defined.first(expected.define[0])
            assert block is not None
            assert isinstance(block.value, Block)
            base = block.value.first(expected.define[1])
            assert base is not None
            assert _tree(value.value) == (("value", "=", _tree(base.value)),)
            assert tuple(_tree(item) for item in native.value.items) == tuple(
                _tree(item)
                for item in output.value.items
                if getattr(item, "key", None) != "ai_value"
            )
        else:
            assert _tree(native) == _tree(output)
    disabled, _ = decision_adapters.build(production[0], texts=inputs, enabled_domains=frozenset())
    assert disabled == {}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "cost", "pm"),
    [("food_industry", "grain", "pm_bakery"), ("textile_mill", "fabric", "pm_handsewn_clothes")],
)
@pytest.mark.parametrize("unemployment", [0.099, 0.1, None])
def test_existing_employment_high_tier_wins_but_is_not_required_for_base(
    production, generated, target, cost, pm, unemployment
):
    source = "common/buildings/01_industry.txt"
    policy = production[1][source]
    values = _values(policy, target, pm)
    values.update(state_unemployment=unemployment, state_owner_loans=False, state_owner_reserves=1)
    expected = 1.3 if unemployment is not None and unemployment >= 0.1 else 1.2
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(
        f"building_{target}.ai_value"
    )
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    observed = pdx_eval.select(
        _overlay(generated[1][source], f"building_{target}.ai_value"), _facts(policy, values)
    )
    assert (observed.delta if observed.operation == "multiply" else 1) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("engine_price", "engine_balance", "expected"),
    [(0.25, 0, 1.2), (0.251, 0, 1.1), (0.6, -1, 0.9), (None, 0, 1.1)],
)
def test_railway_checks_second_real_input_without_infrastructure_surplus_gate(
    production, generated, engine_price, engine_balance, expected
):
    source = "common/buildings/11_private_infrastructure.txt"
    policy = production[1][source]
    values = _values(policy, "railway", "pm_early_trains")
    values.update(
        state_owner_engines_price=engine_price, state_owner_engines_balance=engine_balance
    )
    reference = decision_rules.evaluate(policy, values, is_ai=True).get("building_railway.ai_value")
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    observed = pdx_eval.select(
        _overlay(generated[1][source], "building_railway.ai_value"), _facts(policy, values)
    )
    assert (observed.delta if observed.operation == "multiply" else 1) == pytest.approx(expected)
