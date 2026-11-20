"""Complete school/social consumers retain demand while independent costs join.

These are score preferences, not free institution investment or population gains.
Every competing source rule is compiled and patched into the locked native body.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from test_network_profile import _consumer, _parsed, _score
from test_situated_joint_witnesses import _facts

from pdx import (
    config,
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
    native = compiler.baseline_text()
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
    profile = production_profile.load_profile(config.ROOT)
    program = next(
        row
        for row in network_profile.compile_profile(profile)
        if row.network.actions[0].definition.consumer_id == "a0-pol-schools"
    )
    strategy = version_contracts.DEFAULT_STRATEGY_SOURCE
    files = {strategy: production[2]}
    network_profile.compose(files, profile)
    generated = files[strategy]
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
