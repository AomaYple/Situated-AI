"""Three complete health-law consumers compare specific gains and lost effects.

All deltas are bounded preference choices, never an estimate of money, actual
bureaucracy saved, population welfare, enactment chance, or successful reform.
Current laws describe existing effects; scoring a candidate does not enact it.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import pytest
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

pytestmark = pytest.mark.integration
SOURCE = "common/laws/01_health_system.txt"
LAWS = (
    "law_charitable_health_system",
    "law_private_health_insurance",
    "law_public_health_insurance",
)
FIELDS = tuple(f"{law}.ai_enact_weight_modifier" for law in LAWS)
RETIRED = {
    "law_charitable_health_system_ai_enact_weight_modifier",
    "law_private_health_insurance_ai_enact_weight_modifier",
    "law_public_health_insurance_ai_enact_weight_modifier",
    "coordinated_layered_civic_law_private_health_insurance",
    "coordinated_layered_civic_law_public_health_insurance",
}
PRIVATE = {"current_no_health": False, "current_private_health": True, "health_investment": 1}
CHARITY = {"current_no_health": False, "current_charitable_health": True, "health_investment": 1}
PUBLIC = {"current_no_health": False, "current_public_health": True, "health_investment": 1}
UNKNOWN = {
    "current_no_health": None,
    "current_private_health": None,
    "current_charitable_health": None,
    "current_public_health": None,
    "health_investment": None,
}
CRISIS = {"legitimacy": 20, "insurrection": True, "radical_share": 0.3}


def _values(changes):
    values = {
        "current_no_health": True,
        "current_private_health": False,
        "current_charitable_health": False,
        "current_public_health": False,
        "health_investment": 0,
        "average_sol": 7,
        "grain_price": 0.6,
        "grain_balance": -1,
        "bureaucracy": 1,
        "default": False,
        "war": False,
        "loans": False,
        "debt_ratio": 0.2,
        "net_surplus": 1,
        "income": 100,
        "legitimacy": 60,
        "insurrection": False,
        "radical_share": 0.1,
        "population": 1_000_000,
        "industrial_workforce": 0.2,
    }
    values.update(changes)
    # The old sol alias and the new average_sol observe exactly one engine
    # fact. Keeping their unknowns equal prevents a stale alias restoring it.
    values["sol"] = values["average_sol"]
    context = country_state.load()
    observed = {key: value for key, value in values.items() if key in context.readers}
    derived = country_state.derive(context, observed)["coordination"]
    values.update({f"coord_{key}": value for key, value in derived.items()})
    return values


# Each triple is (charity, private, public). The complete consumer includes
# every competing production rule. Numbers are handwritten, not derived from
# source predicates, evaluator output, or a second implementation of scoring.
CASES = [
    ({}, (10, 0, 12)),
    ({"loans": True}, (10, 0, 12)),
    ({"war": True}, (10, 0, 12)),
    ({"legitimacy": 0}, (10, 0, 12)),
    ({"bureaucracy": -1}, (2, -8, 4)),
    ({"bureaucracy": 0}, (10, 0, 12)),
    ({"default": True}, (4, -6, 6)),
    ({"bureaucracy": -1, "default": True}, (-4, -14, -2)),
    ({"bureaucracy": -1, "default": True, "war": True}, (-4, -14, -2)),
    ({"bureaucracy": None}, (10, 0, 12)),
    ({"default": None}, (10, 0, 12)),
    ({"grain_price": 0.5}, (0, 0, 12)),
    ({"grain_balance": 0}, (0, 0, 12)),
    ({"grain_price": None}, (0, 0, 12)),
    ({"grain_balance": None}, (0, 0, 12)),
    ({"average_sol": 10}, (10, 0, 0)),
    ({"average_sol": None}, (10, 0, 0)),
    ({"grain_price": None, "average_sol": None, "bureaucracy": -1}, (-8, -8, -8)),
    (PRIVATE, (0, 0, 12)),
    ({**PRIVATE, "bureaucracy": -1}, (0, 0, 4)),
    ({**PRIVATE, "default": True}, (0, 0, 6)),
    ({**PRIVATE, "bureaucracy": -1, "default": True}, (0, 0, -2)),
    ({**PRIVATE, "bureaucracy": -1, "health_investment": 0}, (0, 0, 12)),
    ({**PRIVATE, "bureaucracy": -1, "default": True, "health_investment": None}, (0, 0, 12)),
    ({**PRIVATE, "average_sol": None, "bureaucracy": -1}, (0, 0, -8)),
    (CHARITY, (0, -4, 6)),
    ({**CHARITY, "bureaucracy": -1}, (0, 0, 2)),
    ({**CHARITY, "bureaucracy": -1, "default": True}, (0, 0, -4)),
    ({**CHARITY, "health_investment": 0}, (0, 0, 10)),
    ({**CHARITY, "health_investment": None, "bureaucracy": -1, "default": True}, (0, 0, 10)),
    ({**CHARITY, "grain_price": None}, (0, 0, 10)),
    ({**CHARITY, "grain_price": None, "bureaucracy": -1}, (0, 4, 6)),
    ({**CHARITY, "average_sol": None}, (0, -4, -4)),
    ({**CHARITY, "average_sol": None, "bureaucracy": -1}, (0, 0, -8)),
    (PUBLIC, (0, -8, 0)),
    ({**PUBLIC, "bureaucracy": -1}, (0, -2, 0)),
    ({**PUBLIC, "bureaucracy": -1, "default": True}, (0, -2, 0)),
    ({**PUBLIC, "average_sol": 10}, (0, 0, 0)),
    ({**PUBLIC, "average_sol": None, "bureaucracy": -1}, (0, 6, 0)),
    ({**PUBLIC, "health_investment": 0, "bureaucracy": -1}, (0, 0, 0)),
    ({**PUBLIC, "health_investment": None, "bureaucracy": -1}, (0, 0, 0)),
    (UNKNOWN, (0, 0, 0)),
    ({**UNKNOWN, "bureaucracy": -1, "default": True}, (0, 0, 0)),
    (CRISIS, (0, -10, 2)),
    ({**CRISIS, "bureaucracy": -1, "default": True}, (-14, -24, -12)),
    ({**PUBLIC, **CRISIS, "bureaucracy": -1}, (-10, -12, -10)),
    ({"legitimacy": 20, "insurrection": True, "radical_share": None}, (10, 0, 12)),
    ({"candidate_selected": True, "law_enacting": True}, (10, 0, 12)),
]


@pytest.fixture(scope="module")
def source_policy():
    policy = dict(decision_adapters.load().policies)[SOURCE]
    return programs.enable(policy, source=SOURCE)


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_complete_source_health_reforms_match_handwritten_tradeoffs(
    source_policy, changes, expected
):
    actual = decision_rules.evaluate(source_policy, _values(changes), is_ai=True)
    assert tuple(actual.get(field, ("native", 0))[1] for field in FIELDS) == pytest.approx(expected)


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[SOURCE]
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(original, SOURCE, model)
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        initial_values=tuple(row for row in adapters.initial_values if row.source == SOURCE),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == SOURCE),
        supply=None,
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
    return original, policy, inputs[SOURCE], files[SOURCE], disabled


def _overlay(text, field):
    start = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", start)
    return "\n".join(text[start:end].splitlines()[1:])


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_complete_generated_health_reforms_match_handwritten_tradeoffs(
    production, changes, expected
):
    _original, policy, _native, generated, _disabled = production
    facts = _facts(policy, _values(changes))
    actual = []
    for field in FIELDS:
        selected = pdx_eval.select(_overlay(generated, field), facts)
        actual.append(selected.delta if selected.operation == "add" else 0)
    assert tuple(actual) == pytest.approx(expected)


def _syntax(node: Any):
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _syntax(node.value)
    assert isinstance(node, Block)
    return tuple(_syntax(child) for child in node.items)


def test_health_law_gates_petitions_technology_and_all_native_effects_stay_exact(production):
    _original, _policy, native, generated, _disabled = production
    stripped = re.sub(
        r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
        "",
        generated,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert _syntax(parse_text(stripped).root) == _syntax(parse_text(native).root)
    assert "medical_degrees" in generated
    assert "pharmaceuticals" in generated
    assert "add = 750" in generated
    assert "add = 1000" in generated


def test_player_disabled_and_unknown_current_law_preserve_local_neutrality(production):
    _original, policy, _native, generated, disabled = production
    assert disabled == {}
    values = _values({})
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    for field in FIELDS:
        assert (
            pdx_eval.select(
                _overlay(generated, field), _facts(policy, values, is_ai=False)
            ).operation
            is None
        )
    facts = _facts(policy, _values(UNKNOWN))
    facts["other_country"] = {
        "has_law_or_variant": {(("argument", "law_type:law_no_health_system"),): True}
    }
    for field in FIELDS:
        selected = pdx_eval.select(_overlay(generated, field), facts)
        assert selected.operation is None or selected.delta == 0


def test_no_generic_old_reward_survives_and_complete_fields_use_explicit_causes(production):
    original, policy, _native, _generated, _disabled = production
    assert not ({rule.id for rule in original.rules} & RETIRED)
    for field in FIELDS:
        rules = tuple(rule for rule in original.rules if ".".join(rule.field) == field)
        assert len(rules) < 32
        assert all(rule.contribution_group for rule in rules)
        consumer = next(item for item in policy.consumer_programs if ".".join(item.field) == field)
        assert {item.action_id for item in consumer.variants} == {rule.id for rule in rules}
