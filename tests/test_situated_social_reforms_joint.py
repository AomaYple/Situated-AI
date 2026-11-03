"""Nine complete law consumers compare native marginal gains and losses.

Scores are bounded preferences. SoL and occupational shares are need/exposure
proxies, not recipients, money, casualties, jobs lost, or enactment probability.
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
from pdx.situated import compiler, migration_baseline, pdx_eval, programs

pytestmark = pytest.mark.integration
WELFARE = "common/laws/02_welfare.txt"
LABOR = "common/laws/02_labor_rights.txt"
CHILDREN = "common/laws/02_childrens_rights.txt"
EDUCATION = "common/laws/01_education_system.txt"
TARGETS = {
    WELFARE: ("law_poor_laws", "law_wage_subsidies", "law_old_age_pension"),
    LABOR: ("law_regulatory_bodies", "law_worker_protections"),
    CHILDREN: ("law_restricted_child_labor", "law_compulsory_primary_school"),
    EDUCATION: ("law_private_schools", "law_religious_schools"),
}
CRISIS = {"legitimacy": 20, "insurrection": True, "radical_share": 0.3}
POOR = {"social_security_present": True, "current_poor_laws": True, "social_security_investment": 1}
WAGE = {
    "social_security_present": True,
    "current_wage_subsidies": True,
    "social_security_investment": 1,
}
PENSION = {
    "social_security_present": True,
    "current_old_age_pension": True,
    "social_security_investment": 1,
}
REGULATORY = {
    "current_no_workers_rights": False,
    "current_regulatory_bodies": True,
    "workplace_safety_present": True,
    "workplace_safety_investment": 1,
}
PROTECTIONS = {
    "current_no_workers_rights": False,
    "current_worker_protections": True,
    "workplace_safety_present": True,
    "workplace_safety_investment": 1,
}
RESTRICTED = {"current_child_labor": False, "current_restricted_child_labor": True}
COMPULSORY = {"current_child_labor": False, "current_compulsory_primary_school": True}
PRIVATE = {
    "current_no_schools": False,
    "current_private_schools": True,
    "schools_present": True,
    "schools_investment": 1,
}
RELIGIOUS = {
    "current_no_schools": False,
    "current_religious_schools": True,
    "schools_present": True,
    "schools_investment": 1,
}
PUBLIC = {
    "current_no_schools": False,
    "current_public_schools": True,
    "schools_present": True,
    "schools_investment": 1,
}


def _values(changes):
    values = {
        "social_security_present": False,
        "workplace_safety_present": False,
        "schools_present": False,
        "social_security_investment": 0,
        "workplace_safety_investment": 0,
        "schools_investment": 0,
        "current_poor_laws": False,
        "current_wage_subsidies": False,
        "current_old_age_pension": False,
        "current_no_workers_rights": True,
        "current_regulatory_bodies": False,
        "current_worker_protections": False,
        "current_child_labor": True,
        "current_restricted_child_labor": False,
        "current_compulsory_primary_school": False,
        "current_no_schools": True,
        "current_private_schools": False,
        "current_religious_schools": False,
        "current_public_schools": False,
        "current_terakoya": False,
        "sol": 10,
        "literacy": 0.3,
        "industrial_workforce": 0.2,
        "peasant_share": 0.5,
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
        "union_clout": 0.2,
        "union_approval": -1,
        "union_government": False,
    }
    values.update(changes)
    values["average_sol"] = values["sol"]
    context = country_state.load()
    raw = {key: value for key, value in values.items() if key in context.readers}
    values.update(
        {
            f"coord_{key}": value
            for key, value in country_state.derive(context, raw)["coordination"].items()
        }
    )
    return values


# Literal expected scores are hand sums of independent native mechanisms.
CASES = [
    (WELFARE, {}, (12, 13, 10)),
    (WELFARE, {"sol": 12}, (0, -3, -8)),
    (WELFARE, {"industrial_workforce": 0.1}, (12, 16, 18)),
    (WELFARE, {"industrial_workforce": None}, (12, 16, 18)),
    (WELFARE, {"bureaucracy": -1}, (4, 5, 2)),
    (WELFARE, {"default": True}, (6, 7, 4)),
    (WELFARE, {"bureaucracy": -1, "default": True, **CRISIS}, (-12, -11, -14)),
    (WELFARE, {"bureaucracy": None, "default": None}, (12, 13, 10)),
    (WELFARE, {"sol": None, "bureaucracy": -1}, (-8, -11, -16)),
    (WELFARE, POOR, (0, 5, 4)),
    (WELFARE, {**POOR, "social_security_investment": 3}, (0, 7, 8)),
    (WELFARE, {**POOR, "bureaucracy": -1}, (0, 5, 4)),
    (WELFARE, {**POOR, "default": True}, (0, 5, -2)),
    (WELFARE, {**POOR, "default": True, "social_security_investment": 3}, (0, 7, -2)),
    (WELFARE, {**POOR, "social_security_investment": None, "default": True}, (0, 0, 0)),
    (WELFARE, WAGE, (-3, 0, 4)),
    (WELFARE, {**WAGE, "social_security_investment": 3}, (-5, 0, 8)),
    (WELFARE, PENSION, (-12, -10, 0)),
    (WELFARE, {**PENSION, "social_security_investment": 3}, (-16, -14, 0)),
    (WELFARE, {**PENSION, "default": True}, (-6, -4, 0)),
    (WELFARE, {**PENSION, "default": True, "social_security_investment": 3}, (-6, -4, 0)),
    (WELFARE, {**PENSION, "sol": None}, (8, 6, 0)),
    (WELFARE, {"social_security_present": True}, (0, 0, 0)),
    (WELFARE, {"social_security_present": None, "default": True, "bureaucracy": -1}, (0, 0, 0)),
    (LABOR, {}, (12, 16)),
    (LABOR, {"industrial_workforce": 0.25}, (16, 20)),
    (LABOR, {"industrial_workforce": 0}, (0, 8)),
    (LABOR, {"industrial_workforce": None}, (0, 8)),
    (LABOR, {"sol": 12}, (12, 8)),
    (LABOR, {"bureaucracy": -1}, (4, 8)),
    (LABOR, {"bureaucracy": -1, "default": True, **CRISIS}, (-6, -2)),
    (LABOR, REGULATORY, (0, 4)),
    (LABOR, {**REGULATORY, "workplace_safety_investment": 3}, (0, 6)),
    (LABOR, {**REGULATORY, "bureaucracy": -1, "default": True}, (0, 4)),
    (LABOR, PROTECTIONS, (-4, 0)),
    (LABOR, {**PROTECTIONS, "workplace_safety_investment": 3}, (-6, 0)),
    (LABOR, {**PROTECTIONS, "sol": 12}, (4, 0)),
    (LABOR, {**REGULATORY, "workplace_safety_investment": None}, (0, 0)),
    (LABOR, {"current_no_workers_rights": None, "workplace_safety_present": None}, (0, 0)),
    (CHILDREN, {}, (6, 4)),
    (CHILDREN, {"schools_present": True}, (10, 10)),
    (CHILDREN, {"sol": 7}, (2, 0)),
    (CHILDREN, {"sol": 12}, (14, 18)),
    (CHILDREN, {"sol": None}, (14, 18)),
    (CHILDREN, {"industrial_workforce": 0.1}, (2, 0)),
    (CHILDREN, {"industrial_workforce": None, "peasant_share": None}, (-8, -14)),
    (CHILDREN, {"industrial_workforce": 0.1, "peasant_share": 0.6}, (6, 4)),
    (CHILDREN, {"industrial_workforce": None, "peasant_share": 0.1}, (2, 0)),
    (CHILDREN, {"schools_present": True, "literacy": None}, (6, 4)),
    (CHILDREN, {"schools_present": True, "bureaucracy": -1, "default": True, **CRISIS}, (0, 0)),
    (CHILDREN, RESTRICTED, (0, 4)),
    (CHILDREN, {**RESTRICTED, "schools_present": True}, (0, 7)),
    (CHILDREN, {**RESTRICTED, "sol": 7}, (0, 0)),
    (CHILDREN, COMPULSORY, (-4, 0)),
    (CHILDREN, {**COMPULSORY, "schools_present": True}, (-8, 0)),
    (CHILDREN, {**COMPULSORY, "sol": 7}, (0, 0)),
    (CHILDREN, {**COMPULSORY, "sol": 12}, (-12, 0)),
    (CHILDREN, {"current_child_labor": None, "current_restricted_child_labor": None}, (0, 0)),
    (EDUCATION, {}, (8, 12)),
    (EDUCATION, {"sol": 15}, (12, 12)),
    (EDUCATION, {"sol": None}, (8, 12)),
    (EDUCATION, {"literacy": 0.5}, (0, 0)),
    (EDUCATION, {"bureaucracy": -1, "default": True, **CRISIS}, (-16, -12)),
    (EDUCATION, PRIVATE, (0, 10)),
    (EDUCATION, {**PRIVATE, "peasant_share": 0.6}, (0, 14)),
    (EDUCATION, {**PRIVATE, "bureaucracy": -1}, (0, 6)),
    (EDUCATION, {**PRIVATE, "sol": 15, "bureaucracy": -1}, (0, -4)),
    (EDUCATION, {**PRIVATE, "schools_investment": None}, (0, 0)),
    (EDUCATION, RELIGIOUS, (-10, 0)),
    (EDUCATION, {**RELIGIOUS, "peasant_share": 0.6}, (-14, 0)),
    (EDUCATION, {**RELIGIOUS, "bureaucracy": -1}, (-6, 0)),
    (EDUCATION, PUBLIC, (-12, -6)),
    (EDUCATION, {**PUBLIC, "peasant_share": 0.6}, (-16, -6)),
    (EDUCATION, {**PUBLIC, "bureaucracy": -1}, (-4, -2)),
    (EDUCATION, {**PUBLIC, "sol": 15, "bureaucracy": -1}, (8, -2)),
    (EDUCATION, {**PRIVATE, "current_terakoya": True, "schools_present": False}, (0, 0)),
    (EDUCATION, {**PRIVATE, "current_terakoya": None}, (0, 0)),
    (EDUCATION, {"current_no_schools": None, "schools_present": None, "default": True}, (0, 0)),
]


# Missing core law/institution observations cannot invent a new system or erase
# the independently known political crisis.
CASES.extend(
    (
        source,
        {
            **{key: None for key in _values({}) if key.startswith("current_")},
            "social_security_present": None,
            "workplace_safety_present": None,
            "schools_present": None,
            "social_security_investment": None,
            "workplace_safety_investment": None,
            "schools_investment": None,
            "bureaucracy": -1,
            "default": True,
            **CRISIS,
        },
        tuple(-10 for _law in laws),
    )
    for source, laws in TARGETS.items()
)


@pytest.fixture(scope="module")
def source_policies():
    return {
        source: programs.enable(policy, source=source)
        for source, policy in decision_adapters.load().policies
        if source in TARGETS
    }


def _scores(policy, values, source):
    actual = decision_rules.evaluate(policy, values, is_ai=True)
    return tuple(
        actual.get(f"{law}.ai_enact_weight_modifier", ("native", 0))[1] for law in TARGETS[source]
    )


@pytest.mark.parametrize(("source", "changes", "expected"), CASES)
def test_complete_source_social_reforms_match_handwritten_tradeoffs(
    source_policies, source, changes, expected
):
    assert _scores(source_policies[source], _values(changes), source) == pytest.approx(expected)


@pytest.mark.parametrize("source", TARGETS)
@pytest.mark.parametrize(
    "changes",
    [
        {"war": True},
        {"loans": True},
        {"net_surplus": -1},
        {"legitimacy": 40},
        {"radical_share": 0.3},
        {"debt_ratio": 0.8},
    ],
)
def test_ordinary_pressure_never_restores_old_common_capacity_gate(
    source_policies, source, changes
):
    expected = {WELFARE: (12, 13, 10), LABOR: (12, 16), CHILDREN: (6, 4), EDUCATION: (8, 12)}[
        source
    ]
    assert _scores(source_policies[source], _values(changes), source) == pytest.approx(expected)


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policies = {
        source: compiler.compile_policy(original[source], source, model)[0] for source in TARGETS
    }
    selected = replace(
        adapters,
        policies=tuple(policies.items()),
        initial_values=tuple(row for row in adapters.initial_values if row.source in TARGETS),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] in TARGETS),
        supply=None,
    )
    inputs = decision_adapters.read_inputs(selected)
    generated, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    disabled, _ = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        enabled_domains=frozenset(),
    )
    return original, policies, inputs, generated, disabled, model


def _overlay(text, field):
    start = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", start)
    return "\n".join(text[start:end].splitlines()[1:])


@pytest.mark.parametrize(("source", "changes", "expected"), CASES)
def test_complete_production_social_reforms_match_independent_pdx_witnesses(
    production, source, changes, expected
):
    _original, policies, _inputs, generated, _disabled, _model = production
    values = _values(changes)
    assert _scores(policies[source], values, source) == pytest.approx(expected)
    facts = _facts(policies[source], values)
    actual = []
    for law in TARGETS[source]:
        selected = pdx_eval.select(
            _overlay(generated[source], f"{law}.ai_enact_weight_modifier"), facts
        )
        actual.append(selected.delta if selected.operation == "add" else 0)
    assert tuple(actual) == pytest.approx(expected)


@pytest.mark.parametrize("source", TARGETS)
@pytest.mark.parametrize(
    "changes",
    [
        {"war": True},
        {"loans": True},
        {"net_surplus": -1},
        {"legitimacy": 40},
        {"radical_share": 0.3},
        {"debt_ratio": 0.8},
    ],
)
def test_production_normal_borrowing_war_and_correlated_pressure_keep_direct_needs(
    production, source, changes
):
    expected = {
        WELFARE: (12, 13, 10),
        LABOR: (12, 16),
        CHILDREN: (6, 4),
        EDUCATION: (8, 12),
    }[source]
    test_complete_production_social_reforms_match_independent_pdx_witnesses(
        production, source, changes, expected
    )


def _pdx(node):
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        assert node.prefix is None
        return f"{node.key} {node.op} {_pdx(node.value)}"
    assert isinstance(node, Block)
    return "{ " + " ".join(_pdx(child) for child in node.items) + " }"


def _native_score(text, law, facts):
    parsed = parse_text(text)
    assert not parsed.errors
    candidate = parsed.root.first(law)
    assert candidate is not None
    assert isinstance(candidate.value, Block)
    field = candidate.value.first("ai_enact_weight_modifier")
    assert field is not None
    assert isinstance(field.value, Block)
    program = (
        "# native_score [political];\n"
        "if = { limit = { always = yes } add = " + _pdx(field.value) + " }"
    )
    return pdx_eval.select(program, facts).delta


@pytest.mark.parametrize(
    ("source", "law", "delta"),
    [
        (WELFARE, "law_poor_laws", 12),
        (WELFARE, "law_wage_subsidies", 13),
        (WELFARE, "law_old_age_pension", 10),
        (LABOR, "law_regulatory_bodies", 12),
        (LABOR, "law_worker_protections", 16),
        (CHILDREN, "law_restricted_child_labor", 6),
        (CHILDREN, "law_compulsory_primary_school", 4),
        (EDUCATION, "law_private_schools", 8),
        (EDUCATION, "law_religious_schools", 12),
    ],
)
@pytest.mark.parametrize("petition", [False, True])
def test_full_native_numeric_scores_add_joint_delta_without_erasing_petitions(
    production, source, law, delta, petition
):
    _original, policies, inputs, generated, _disabled, _model = production
    values = _values({})
    facts = _facts(policies[source], values)
    facts.update(facts["ROOT"])
    facts["ai_has_enact_weight_modifier_journal_entries"] = petition
    facts["has_journal_entry"] = {}
    facts["country_has_state_religion"] = "none"
    native = (500 if source == EDUCATION else 0) + (750 if petition else 0)
    assert _native_score(inputs[source], law, facts) == native
    assert _native_score(generated[source], law, facts) == native + delta
    facts["ROOT"]["is_ai"] = False
    assert _native_score(generated[source], law, facts) == native


@pytest.mark.parametrize(
    ("law", "journal", "native", "delta"),
    [
        ("law_private_schools", "je_sick_man_education", 1000, 8),
        ("law_religious_schools", "je_sick_man_education", 1000, 12),
        ("law_religious_schools", "je_elevate_buddhism", 1500, 12),
    ],
)
def test_school_native_journal_additions_keep_source_order_and_joint_delta(
    production, law, journal, native, delta
):
    _original, policies, inputs, generated, _disabled, _model = production
    facts = _facts(policies[EDUCATION], _values({}))
    facts.update(facts["ROOT"])
    facts["ai_has_enact_weight_modifier_journal_entries"] = False
    facts["has_journal_entry"] = {(("argument", journal),): True}
    facts["country_has_state_religion"] = "none"
    assert _native_score(inputs[EDUCATION], law, facts) == native
    assert _native_score(generated[EDUCATION], law, facts) == native + delta


def _syntax(node: Any):
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _syntax(node.value)
    assert isinstance(node, Block)
    return tuple(_syntax(child) for child in node.items)


@pytest.mark.parametrize("source", TARGETS)
def test_native_qualifications_effects_lifecycle_and_score_tails_remain_exact(production, source):
    _original, _policies, inputs, generated, _disabled, _model = production
    stripped = re.sub(
        r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
        "",
        generated[source],
        flags=re.MULTILINE | re.DOTALL,
    )
    assert _syntax(parse_text(stripped).root) == _syntax(parse_text(inputs[source]).root)


@pytest.mark.parametrize("source", TARGETS)
def test_players_and_disabled_domains_preserve_complete_original_consumers(production, source):
    _original, policies, _inputs, generated, disabled, _model = production
    assert disabled == {}
    policy = policies[source]
    values = _values({"bureaucracy": -1, "default": True, **CRISIS})
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    for law in TARGETS[source]:
        assert (
            pdx_eval.select(
                _overlay(generated[source], f"{law}.ai_enact_weight_modifier"),
                _facts(policy, values, is_ai=False),
            ).operation
            is None
        )


def test_real_historical_replacements_keep_consumer_identities_and_remove_hidden_gates(production):
    original, policies, _inputs, _generated, _disabled, model = production
    migration_baseline.validate_bundle(model.consumer_ir)
    for source, laws in TARGETS.items():
        for law in laws:
            field = f"{law}.ai_enact_weight_modifier"
            rules = [rule for rule in original[source].rules if ".".join(rule.field) == field]
            assert all(
                rule.contribution_group and rule.intent != "supported_development" for rule in rules
            )
            assert all(not rule.contexts for rule in rules if rule.value > 0)
            consumer = next(
                item for item in policies[source].consumer_programs if ".".join(item.field) == field
            )
            assert {item.action_id for item in consumer.variants} == {rule.id for rule in rules}


def test_new_child_law_argument_requires_actual_locked_native_source():
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    source = "events/law_events/children_rights_events.txt"
    evidence = decision_adapters.reader_evidence({source: inputs[source]})
    assert evidence["law_type:law_restricted_child_labor"]["source"] == source
    drifted = {**inputs, source: inputs[source] + "\n# drift\n"}
    with pytest.raises(ValueError, match="原件漂移"):
        decision_adapters.read_inputs(adapters, texts=drifted)
    missing = {name: text for name, text in inputs.items() if name != source}
    with pytest.raises(ValueError, match="缺少锁定游戏原件"):
        decision_adapters.read_inputs(adapters, texts=missing)
