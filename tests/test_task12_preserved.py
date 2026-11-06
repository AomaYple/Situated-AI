"""Exact existing roles/lifecycles retained while the external delta is prepared."""

import re
from dataclasses import replace

import pytest
import test_a3_military_assistance as assistance
import test_a3_military_commitments as commitments
import test_a3_regional_resources as regional
import test_a3_subject_dependence as dependence
import test_a3_treaty_acceptance as tariffs
from test_remaining_joint_consumers import _native_number, _overlay
from test_situated_joint_witnesses import _facts

from pdx import (
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
)
from pdx import (
    treaty_acceptance_opportunities as acceptance,
)
from pdx import war_pressure_opportunities as pressure
from pdx.lexer import tokenize
from pdx.parser import parse_text
from pdx.situated import programs


@pytest.fixture(scope="module")
def treaty_texts():
    native = acceptance.frozen_inputs()
    return native, {
        p.definition: acceptance.patch(native, consumer_program=p)[p.source]
        for p in acceptance.compile_programs()
    }


@pytest.mark.parametrize("definition", tuple(acceptance.COMMITMENTS))
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"in_default": True}, -6),
        ({"net_total_income": -1}, -3),
        ({"in_default": True, "war_defeat": True}, -8),
        ({"in_default": None, "net_total_income": None, "war_defeat": True}, -2),
        ({"in_default": True, "is_treaty_active_exists": True}, 0),
        ({"in_default": True, "is_renegotiation_exists": True}, 0),
        ({"in_default": True, "existing_treaties": None}, 0),
    ],
)
def test_military_obligations_separate_role_financing_recovery_and_expiry(
    treaty_texts, definition, changes, expected
):
    _, texts = treaty_texts
    values = commitments.values(definition, **changes)
    assert acceptance.compile_program(definition).evaluate(values, is_ai=True) == expected
    assert commitments.actual(texts[definition], definition, values) == expected


@pytest.mark.parametrize("definition", tuple(acceptance.COMMITMENTS))
def test_actual_military_party_identity_and_full_native_tail(treaty_texts, definition):
    native, texts = treaty_texts
    program = acceptance.compile_program(definition)
    if definition in {"alliance", "defensive_pact"}:
        commitments.test_both_mutual_roles_and_swapped_identity(acceptance, texts, definition)
    else:
        commitments.test_directed_target_never_pays_source_commitment(acceptance, texts, definition)
    commitments.test_exact_target_newness_and_frozen_existing_obligations(
        acceptance, texts, definition
    )
    stripped = re.sub(
        r"\s*# SITAI BEGIN treaty_acceptance:.*?# SITAI END treaty_acceptance:[^\n]+\n\s*",
        "\n",
        texts[definition],
        flags=re.DOTALL,
    )
    assert acceptance._shape(parse_text(stripped).root) == acceptance._shape(
        parse_text(native[program.source]).root
    )
    assert program.evaluate(commitments.values(definition, in_default=True), is_ai=False) == 0
    assert acceptance.patch(native, consumer_program=program, enabled_domains=frozenset()) == {}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"in_default": True}, -10),
        ({"net_total_income": -1}, -6),
        ({"in_default": True, "military_expenses": None}, 0),
        ({"in_default": True, "military_expenses": 0}, 0),
        ({"root": "B", "in_default": True}, 0),
        ({"in_default": True, "is_treaty_active_exists": True}, 0),
        ({"in_default": True, "is_renegotiation_exists": True}, 0),
    ],
)
def test_aid_source_real_expense_and_newness_keep_native_payment(treaty_texts, changes, expected):
    _, texts = treaty_texts
    values = assistance._values(**changes)
    assert (
        acceptance.compile_program("military_assistance").evaluate(values, is_ai=True) == expected
    )
    assert assistance._actual(texts["military_assistance"], values) == expected


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"in_default": True}, -12),
        ({"net_total_income": -1}, -8),
        ({"in_default": False, "net_total_income": 0}, 0),
    ],
)
def test_trade_source_financing_uses_actual_party_and_goods(treaty_texts, changes, expected):
    _, texts = treaty_texts
    values = tariffs._values(**changes)
    assert acceptance.compile_program("no_tariffs").evaluate(values, is_ai=True) == expected
    assert tariffs._actual(texts["no_tariffs"], tariffs._context(values)) == expected


@pytest.mark.parametrize(
    "case",
    [
        "oil_only",
        "both",
        "unknown_rubber_but_oil_known",
        "oil_without_pumpjacks",
        "combined_native_multipliers",
        "small_country_overseas",
        "player",
        "missing_region",
    ],
)
def test_candidate_region_keeps_independent_potential_native_multipliers_and_final_zero(case):
    native = regional.regional_resource_opportunities.frozen_inputs()
    patched = regional.regional_resource_opportunities.patch(native)[
        regional.regional_resource_opportunities.SOURCE
    ]
    row = next(row for row in regional.CASES if row[0] == case)
    regional.test_literal_worlds_run_complete_original_and_patched_numeric_ast(
        regional.regional_resource_opportunities, native, patched, *row
    )


@pytest.fixture(scope="module")
def subject():
    wrapped = getattr(dependence.generated, "__wrapped__", None)
    assert callable(wrapped)
    return wrapped()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.08),
        ({"index": 1}, 1),
        ({"index": None}, 1),
        ({"subject": False}, 1),
        ({"ai": False}, 1),
        ({"liberty": 25, "relations": 50}, 1.26),
    ],
)
def test_actual_overlord_uses_current_identity_without_forced_cooperation(
    subject, changes, expected
):
    actual, reference, _, _ = dependence._witness(subject, **changes)
    assert actual == pytest.approx(expected)
    assert reference == pytest.approx(expected)


def test_changed_overlord_and_full_original_source_leave_old_continuity(subject):
    dependence.test_actual_not_candidate_wrong_country_reverse_or_top_overlord(subject)
    dependence.test_normal_low_financing_player_disable_and_full_native_ast_preservation(subject)


@pytest.fixture(scope="module")
def military():
    original = decision_rules.load()
    rules = tuple(
        r for r in original.rules if r.field in {("wanted_army_size",), ("wanted_navy_size",)}
    )
    keys = {k for r in rules for k in r.input_keys()}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(r for r in original.readers if r.key in keys),
        enabled_domains=frozenset(r.domain for r in rules),
        semantic_ir=(),
        consumer_programs=(),
        port_bindings=(),
        rule_relation_bindings=(),
    )
    policy = programs.enable(policy, source="mod/decisions/information.toml")
    native = pressure.frozen_inputs()[pressure.SOURCE]
    inputs = decision_adapters.read_inputs(decision_adapters.load())
    words = decision_interfaces.proven_reader_words() | frozenset(
        re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))
    )
    text = decision_rules.patch(
        native, policy, baseline=native, reader_words=words, country_policy=country_state.load()
    )
    return policy, native, text


@pytest.mark.parametrize(
    ("field", "changes", "expected"),
    [
        ("wanted_army_size", {"war": True, "default": True}, 0.93),
        ("wanted_navy_size", {"war": True, "default": True}, 0.86),
        (
            "wanted_army_size",
            {"war": True, "default": False, "net_surplus": 1, "bureaucracy": 1},
            1.20,
        ),
        (
            "wanted_navy_size",
            {"war": True, "default": False, "net_surplus": 1, "bureaucracy": 1},
            1.12,
        ),
        ("wanted_army_size", {"war": True, "bureaucracy": 1}, 1.11),
        ("wanted_navy_size", {"war": True, "bureaucracy": 1}, 1.09),
        ("wanted_army_size", {"war": None, "default": True}, 0.85),
        ("wanted_navy_size", {"war": None, "default": True}, 0.80),
    ],
)
def test_actual_military_partial_readiness_keeps_independent_known_cost(
    military, field, changes, expected
):
    policy, _, text = military
    values = dict.fromkeys(r.key for r in policy.readers)
    values.update(changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field, ("", 1))[1]
    actual = _native_number(1, _overlay(text, field), _facts(policy, values))
    assert reference == pytest.approx(expected)
    assert actual == pytest.approx(expected)
    assert _native_number(0, _overlay(text, field), _facts(policy, values)) == 0


def test_complete_military_native_ast_player_and_disabled_preserved(military):
    policy, native, text = military
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(stripped)] == [
        (t.kind, t.value) for t in tokenize(native)
    ]
    assert decision_rules.evaluate(policy, {}, is_ai=False) == {}
    assert (
        decision_rules.patch(native, policy, baseline=native, enabled_domains=frozenset()) == native
    )
