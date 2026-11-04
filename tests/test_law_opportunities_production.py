"""Six complete legal sources agree with independent current-world witnesses."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules, law_opportunities
from pdx.parser import parse_text
from pdx.situated import compiler, migration_baseline, pdx_eval

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    sources = law_opportunities.load()["sources"]
    policies = tuple(
        (source, compiler.compile_policy(policy, source, model)[0])
        for source, policy in adapters.policies
        if source in sources
    )
    selected = replace(
        adapters, policies=policies, supply=None, initial_values=(), scalar_values=()
    )
    inputs = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    disabled, _ = decision_adapters.build(
        selected,
        texts=inputs,
        enabled_domains=frozenset(),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return dict(policies), files, inputs, model, disabled


def _values(policy, changes):
    values = {
        reader.key: False if reader.kind == "boolean" else max(reader.minimum or 0, 0)
        for reader in policy.readers
    }
    values.update(changes)
    return values


CASES = [
    ("law_proportional_taxation", {}, [], 0),
    (
        "law_proportional_taxation",
        {"legitimacy": 10, "insurrection": True, "radical_share": 0.3},
        [],
        -10,
    ),
    ("law_proportional_taxation", {}, [("law_proportional_taxation", 0.1)], 6),
    ("law_proportional_taxation", {}, [("law_proportional_taxation", 0.25)], 10),
    (
        "law_proportional_taxation",
        {"legitimacy": 10, "insurrection": True, "radical_share": 0.3},
        [("law_proportional_taxation", 0.1)],
        -4,
    ),
    ("law_proportional_taxation", {"legitimacy": None}, [("law_proportional_taxation", 0.1)], 6),
    (
        "law_proportional_taxation",
        {"bureaucracy": -1, "law_context_current_law_consumption_based_taxation": True},
        [("law_proportional_taxation", 0.1)],
        0,
    ),
    ("law_proportional_taxation", {}, [("law_graduated_taxation", 0.25)], 0),
    ("law_free_trade", {"law_context_current_law_mercantilism": True, "grain_balance": -1}, [], 8),
    (
        "law_free_trade",
        {"law_context_current_law_mercantilism": True, "grain_balance": -1, "grain_price": 0.3},
        [],
        15,
    ),
    (
        "law_free_trade",
        {"law_context_current_law_mercantilism": True, "grain_balance": -1, "grain_price": None},
        [],
        8,
    ),
    ("law_tenant_farmers", {"law_context_current_law_serfdom": True, "peasant_share": 0.6}, [], 12),
    (
        "law_interventionism",
        {"law_context_current_law_traditionalism": True, "tools_balance": -1, "bureaucracy": -1},
        [],
        4,
    ),
]


@pytest.mark.parametrize(("law", "changes", "movements", "expected"), CASES)
def test_actual_generated_complete_legal_consumer_matches_handwritten_cases(
    production, law, changes, movements, expected
):
    policies, files, _, _, _ = production
    source = law_opportunities.load()["candidates"][law]
    policy = policies[source]
    values = _values(policy, changes)
    for reader in policy.readers:
        if reader.engine == "any_political_movement":
            params = dict(reader.parameters)
            values[reader.key] = any(
                candidate == params["law"] and support >= float(params["minimum_support"])
                for candidate, support in movements
            )
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(
        f"{law}.ai_enact_weight_modifier"
    )
    assert (reference[1] if reference else 0) == pytest.approx(expected)
    facts = _facts(policy, values)
    laws = law_opportunities.load()["candidates"]
    facts["ROOT"]["any_political_movement"] = [
        {
            "law_enactment_stance": {
                (("law", "law_type:" + item),): int(item == candidate) for item in laws
            },
            "political_movement_support": support,
        }
        for candidate, support in movements
    ]
    facts["ROOT"]["any_scope_state"] = []
    observed = pdx_eval.select(_overlay(files[source], f"{law}.ai_enact_weight_modifier"), facts)
    assert observed.delta == pytest.approx(expected)


def test_all_37_consumers_and_exact_historical_successors_are_live(production):
    policies, files, inputs, model, disabled = production
    assert all(source not in disabled for source in law_opportunities.load()["sources"])
    for law, source in law_opportunities.load()["candidates"].items():
        rules = [
            row for row in policies[source].rules if row.field == (law, "ai_enact_weight_modifier")
        ]
        assert rules
        assert all(row.id.startswith(("law_context_", "political_capacity_law_")) for row in rules)
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            files[source],
            flags=re.DOTALL,
        )
        assert _render(_block(parse_text(inputs[source]).root, law)) == _render(
            _block(parse_text(stripped).root, law)
        )
    retired = migration_baseline.validated_retirements(model.consumer_ir)
    assert (
        "common/laws/01_taxation.txt",
        "law_proportional_taxation_ai_enact_weight_modifier",
    ) in retired
    assert ("common/laws/02_migration.txt", "structural_migration_opening") in retired


def test_player_unknown_and_disabled_preserve_native_paths(production):
    policies, files, _, _, _ = production
    for law, source in law_opportunities.load()["candidates"].items():
        policy = policies[source]
        values = _values(policy, {})
        overlay = _overlay(files[source], f"{law}.ai_enact_weight_modifier")
        assert pdx_eval.select(overlay, _facts(policy, values, is_ai=False)).operation is None
        assert pdx_eval.select(overlay, {}).operation is None
        assert not decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset())
