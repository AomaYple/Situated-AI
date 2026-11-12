"""Complete school/social consumers retain demand while independent costs join.

These are score preferences, not free institution investment or population gains.
Every competing source rule is compiled and patched into the locked native body.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from test_network_profile import _consumer, _parsed, _score
from test_remaining_joint_consumers import _historical_school_blocks
from test_situated_joint_witnesses import _facts

from pdx import (
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    version_contracts,
)
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, network_profile, production_profile
from pdx.situated import pdx_eval as oracle

pytestmark = pytest.mark.integration
INFO = "mod/decisions/information.toml"
SCHOOL = "institution_scores.institution_schools"
SOCIAL = "institution_scores.institution_social_security"
FIELDS = (SCHOOL, SOCIAL)


@pytest.fixture(scope="module")
def production():
    source = decision_rules.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    compiled, _ = compiler.compile_policy(source, INFO, model)
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    native = compiler.baseline_path().read_text(encoding="utf-8")
    words = (
        frozenset(decision_adapters.reader_evidence(inputs))
        | decision_interfaces.proven_reader_words()
    )

    def patch(enabled=None):
        return decision_rules.patch(
            native,
            compiled,
            baseline=native,
            enabled_domains=enabled,
            reader_words=words,
            country_policy=country_state.load(),
            consumer_ir=model.consumer_ir,
            consumer_source=INFO,
        )

    return source, compiled, native, patch(), patch(frozenset()), model


@pytest.fixture(scope="module")
def current_school(production):
    if version_contracts.active_version() != "1.15.1":
        return None
    profile = production_profile.load_profile(production_profile.baseline_root())
    program = next(
        row
        for row in network_profile.compile_profile(profile)
        if row.network.actions[0].definition.consumer_id == "a0-pol-schools"
    )
    generated = network_profile.build(profile)["common/ai_strategies/00_default_strategy.txt"]
    declaration = next(row for row in profile.declarations if row.id == "a0-pol-schools")
    assert production_profile.strip_policy(generated, declaration) == production[2]
    return program, generated, declaration


def _current_school_facts(values, *, is_ai=True):
    return {
        key: value
        for key, value in {
            "ai": is_ai,
            "literacy": values.get("literacy"),
            "population": values.get("population"),
            "bureaucracy": values.get("bureaucracy"),
            "default": values.get("default"),
            "net-surplus": values.get("net_surplus"),
            "school-agenda": False,
        }.items()
        if value is not None
    }


def _current_school_delta(values):
    # Literal independent assessment for the declared migration. Required
    # unknowns exit the complete assessment; auxiliary income only drops .5.
    if any(values.get(key) is None for key in ("literacy", "population", "bureaucracy", "default")):
        return 0
    needed = values["literacy"] < 0.5 and values["population"] > 0
    return (
        (2 if needed else 0)
        + (0.25 if needed and values["bureaucracy"] > 0 else 0)
        + (
            0.5
            if needed and values["default"] is False and (values.get("net_surplus") or 0) > 0
            else 0
        )
        - (2 if values["bureaucracy"] < 0 else 0)
        - (2 if values["default"] is True else 0)
    )


def _current_school_observed(program, facts):
    declared = {fact.id for fact in program.network.facts}
    text = network_profile.render_program(
        program, available=tuple(key for key in facts if key in declared)
    )
    return _score(_parsed(text), facts)


def _values(changes):
    # High debt selects the actual recovery context, so the unchanged funded
    # school tiers cannot obscure its original low-literacy +.10 foundation.
    values = {
        "default": False,
        "war": False,
        "loans": True,
        "debt_ratio": 0.8,
        "net_surplus": -1,
        "income": 100,
        "bureaucracy": -1,
        "legitimacy": 60,
        "insurrection": False,
        "population": 1_000_000,
        "literacy": 0.3,
        "average_sol": 7,
        "grain_price": 0.2,
        "grain_balance": 0,
        "route_education": False,
    }
    values.update(changes)
    policy = country_state.load()
    raw = {key: value for key, value in values.items() if key in policy.readers}
    derived = country_state.derive(policy, raw)["coordination"]
    values.update({f"coord_{key}": value for key, value in derived.items()})
    return values


def _overlay(text, field):
    marker = f"# SITAI BEGIN information:{field}"
    if marker not in text:
        return ""
    start = text.index(marker)
    stop = text.index(f"# SITAI END information:{field}", start)
    return "\n".join(text[start:stop].splitlines()[1:])


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, (1.0, 0.98)),
        ({"loans": False}, (1.0, 0.98)),
        ({"bureaucracy": 1}, (1.18, 1.08)),
        ({"bureaucracy": 0}, (1.1, 1.08)),
        ({"bureaucracy": 1, "loans": False}, (1.18, 1.08)),
        ({"default": True}, (0.85, 0.78)),
        ({"default": True, "bureaucracy": 1}, (1.03, 0.88)),
        ({"default": True, "war": True}, (0.85, 0.83)),
        ({"default": None}, (1.0, 0.98)),
        ({"bureaucracy": None}, (1.1, 1.08)),
        ({"net_surplus": None}, (1.0, 0.98)),
        ({"loans": None}, (1.0, 0.98)),
        ({"average_sol": None}, (1.0, 0.9)),
        ({"population": None}, (0.9, 0.9)),
        ({"average_sol": 8}, (1.0, 0.9)),
        ({"literacy": 0.35}, (1.0, 0.98)),
        ({"literacy": None}, (0.9, 0.98)),
        ({"average_sol": 12, "literacy": 0.8, "bureaucracy": 1}, (1, 1.0)),
        ({"bureaucracy": 1, "population": 2_000_000}, (1.18, 1.1)),
        (
            {"bureaucracy": 1, "net_surplus": 1, "grain_price": 0.6, "grain_balance": -1},
            (1.25, 1.12),
        ),
        (
            {"bureaucracy": 1, "net_surplus": 0, "grain_price": 0.6, "grain_balance": -1},
            (1.18, 1.08),
        ),
        (
            {
                "bureaucracy": 1,
                "net_surplus": 1,
                "debt_ratio": 0.2,
                "loans": False,
                "legitimacy": 80,
            },
            (1.25, 1.08),
        ),
        (
            {
                "bureaucracy": 1,
                "net_surplus": 1,
                "debt_ratio": 0.3,
                "loans": False,
                "legitimacy": 20,
            },
            (1.25, 1.08),
        ),
        ({"route_education": True}, (1.0, 0.98)),
        ({"candidate_selected": True, "institution_expanding": True}, (1.0, 0.98)),
    ],
)
def test_complete_consumers_match_handwritten_joint_preferences(
    production, current_school, changes, expected
):
    _source, policy, _native, generated, _disabled, _model = production
    # Preserve both historical multiplier contracts against their own frozen
    # source/PDX bodies, independently of the installed current game version.
    for version in ("1.14.5", "1.15.0"):
        with version_contracts.select_version(version):
            historical, blocks = _historical_school_blocks(version)
            old_values = _values(changes)
            reference = decision_rules.evaluate(historical, old_values, is_ai=True)
            assert reference.get(SCHOOL, ("native", 1))[1] == pytest.approx(expected[0])
            assert oracle.select(
                blocks[SCHOOL], _facts(historical, old_values)
            ).delta == pytest.approx(expected[0])
    values = _values(changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    facts = _facts(policy, values)
    for field, factor in zip(FIELDS, expected, strict=True):
        if field == SCHOOL and current_school is not None:
            assert field not in reference
            program, _generated_school, _declaration = current_school
            delta = _current_school_observed(program, _current_school_facts(values))
            assert delta == pytest.approx(_current_school_delta(values))
            assert 10 + delta == pytest.approx(10 + _current_school_delta(values))
            continue
        observed = oracle.select(_overlay(generated, field), facts)
        assert reference.get(field, ("native", 1))[1] == pytest.approx(factor)
        assert (observed.delta if observed.operation == "multiply" else 1) == pytest.approx(factor)
        # Both original institution entries are 10. No test claims investment.
        assert 10 * factor == pytest.approx(10 * (observed.delta if observed.operation else 1))


def test_same_demand_tiers_and_independent_costs_have_explicit_causes(production, current_school):
    source, policy, _native, _generated, _disabled, model = production
    assert model.consumer_ir is not None
    for field, count in ((SCHOOL, 6), (SOCIAL, 9)):
        rules = tuple(rule for rule in source.rules if ".".join(rule.field) == field)
        if field == SCHOOL and current_school is not None:
            assert rules == ()
            assert all(".".join(row.field) != SCHOOL for row in policy.consumer_programs)
            program, generated, declaration = current_school
            action = program.network.actions[0]
            assert action.definition.operation == "add"
            assert {row.id for row in program.network.bridges} == {
                "school-need",
                "school-administration",
                "school-default",
                "school-agenda-complement",
                "school-capacity-administrative",
                "school-capacity-fiscal",
            }
            assert production_profile.strip_policy(generated, declaration) == _native
            continue
        assert len(rules) == count < 32
        assert len({rule.contribution_group for rule in rules if rule.value > 1}) == 1
        costs = {rule.contribution_group for rule in rules if rule.value < 1}
        assert costs == {"institution_financing_pressure", "institution_administrative_pressure"}
        assert all(rule.contribution_group for rule in rules)
        program = next(row for row in policy.consumer_programs if ".".join(row.field) == field)
        assert {row.action_id for row in program.variants} == {rule.id for rule in rules}
        assert all(
            writer.evaluation_context.targets == ()
            for writer in model.consumer_ir.writers
            if writer.source == INFO and writer.field == field
        )


def _syntax(node: Any):
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _syntax(node.value)
    assert isinstance(node, Block)
    return tuple(_syntax(item) for item in node.items)


def test_players_disabled_missing_country_and_native_tail_are_preserved(production, current_school):
    _source, policy, native, generated, disabled, _model = production
    values = _values({"default": True})
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert disabled == native
    for field in FIELDS:
        if field == SCHOOL and current_school is not None:
            program, school_text, declaration = current_school
            assert (
                _current_school_observed(program, _current_school_facts(values, is_ai=False)) == 0
            )
            assert _current_school_observed(program, {"ai": True, "foreign_literacy": 0.3}) == 0
            assert production_profile.strip_policy(school_text, declaration) == native
            native_body = _consumer(
                native, "ai_strategy_default", "institution_scores", "institution_schools"
            )
            assert _score(native_body, {}) == 10
            # The new local preference is additive after the original body;
            # the historical multiplicative native-zero statement does not apply.
            assert _current_school_observed(program, _current_school_facts(values)) == -2
            continue
        overlay = _overlay(generated, field)
        assert oracle.select(overlay, _facts(policy, values, is_ai=False)).operation is None
        foreign = _facts(policy, values)["ROOT"]
        observed = oracle.select(overlay, {"ROOT": {"is_ai": True}, "other_country": foreign})
        assert observed.operation is None or observed.delta == 1
        # The score is multiplicative; it cannot bypass a native zero or law
        # qualification. Definitions remain keys, with no invented target scope.
        observed = oracle.select(overlay, _facts(policy, values))
        assert 0 * observed.delta == 0
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL | re.MULTILINE,
    )
    before, after = parse_text(native), parse_text(stripped)
    assert not before.errors
    assert not after.errors
    assert _syntax(before.root) == _syntax(after.root)
