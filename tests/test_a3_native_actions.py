"""Exact peaceful-action roles and independent arithmetic at native proposal fields."""

from __future__ import annotations

import copy
import hashlib
import re
import tomllib
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import decision_adapters, decision_interfaces, decision_rules
from pdx import native_action_opportunities as actions
from pdx.parser import parse_text
from pdx.situated import programs

pytestmark = pytest.mark.integration
AUTONOMY = "da_increase_autonomy_of_self"
PAYMENTS = "decrease_payments"
BLOC = "join_power_bloc"
BASES = {AUTONOMY: 100, PAYMENTS: 10, BLOC: 20}


@pytest.fixture(scope="module")
def derived():
    adapters = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))
    return actions.derive(adapters)


@pytest.fixture(scope="module")
def compiled(derived):
    # Use current source-locked getter evidence; new action source identities
    # and complete proposal AST are separately verified against their freeze.
    inputs = decision_adapters.read_inputs(decision_adapters.load())
    inputs.update(actions.load_baseline()["texts"])
    words = frozenset(decision_adapters.reader_evidence(inputs))
    results = {}
    for identity, source in actions.CANDIDATES.items():
        rules = [
            {key: value for key, value in row.items() if key != "source"}
            for row in derived["rules"]
            if row["source"] == source
        ]
        used = {condition["fact"] for row in rules for condition in row["conditions"]}
        policy = decision_rules.from_data(
            {
                "schema": 1,
                "baseline_sha256": derived["sources"][source],
                "readers": {key: row for key, row in derived["readers"].items() if key in used},
                "rules": rules,
                "domains": {"diplomacy": True},
            },
            source_sha256="0" * 64,
        )
        decision_interfaces.validate(policy)
        policy = programs.enable(policy, source=source)
        generated = decision_rules.patch(
            inputs[source],
            policy,
            baseline=inputs[source],
            default_strategy=False,
            reader_words=words,
        )
        results[identity] = (policy, generated, inputs[source], words)
    return results


CASES = [
    ({}, 1, 1),
    ({"liberty": 89.99}, 1, 1),
    ({"liberty": 90}, 1.18, 1),
    ({"liberty": 100}, 1.18, 1),
    ({"war_defeat": True}, 0.95, 1),
    ({"liberty": 90, "war_defeat": True}, 1.13, 1),
    ({"liberty": None, "war_defeat": True}, 0.95, 1),
    ({"liberty": 90, "war_defeat": None}, 1.18, 1),
    ({"default": True}, 1, 0.85),
    ({"net_surplus": -0.01}, 1, 0.92),
    ({"default": True, "net_surplus": -100}, 1, 0.85),
    ({"default": None, "net_surplus": -1}, 1, 0.92),
    ({"default": None, "net_surplus": 0}, 1, 1),
    ({"default": True, "net_surplus": None}, 1, 0.85),
    ({"default": None, "net_surplus": None}, 1, 1),
    ({"liberty": 90, "war_defeat": True, "default": True, "net_surplus": -100}, 1.13, 0.85),
]


@pytest.mark.parametrize(("changes", "autonomy", "payments"), CASES)
def test_independent_hand_calculations_match_reference_and_pdx(
    compiled, changes, autonomy, payments
):
    for identity, expected in ((AUTONOMY, autonomy), (PAYMENTS, payments)):
        policy, generated, _, _ = compiled[identity]
        values: dict[str, object] = {
            "liberty": 75,
            "war_defeat": False,
            "default": False,
            "net_surplus": 0,
        }
        values.update(changes)
        field = f"{identity}.ai.propose_score"
        reference = decision_rules.evaluate(policy, values, is_ai=True)
        assert reference.get(field, ("native", 1))[1] == pytest.approx(expected)
        base = BASES[identity]
        assert _native_number(base, _overlay(generated, field), _facts(policy, values)) == (
            pytest.approx(base * expected)
        )


def test_foreign_country_and_owner_decoys_cannot_supply_actor_observations(compiled):
    for identity in actions.CANDIDATES:
        policy, generated, _, _ = compiled[identity]
        assert all(reader.scope == "root" and not reader.path for reader in policy.readers)
        values = dict.fromkeys(reader.key for reader in policy.readers)
        facts = _facts(policy, values)
        decoy = {
            "liberty_desire": 100,
            "in_default": True,
            "net_total_income": -100,
            "has_variable": {(("argument", "recently_lost_war"),): True},
        }
        facts["scope:target_country"] = decoy
        facts["scope:target"] = decoy
        facts["ROOT"]["owner"] = decoy
        base = BASES[identity]
        assert (
            _native_number(base, _overlay(generated, f"{identity}.ai.propose_score"), facts) == base
        )


def test_complete_original_ordered_ast_and_all_other_action_fields_retained(compiled):
    for identity in actions.CANDIDATES:
        _, generated, native, _ = compiled[identity]
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            generated,
            flags=re.DOTALL,
        )
        assert not parse_text(generated).errors
        assert _render(parse_text(stripped).root) == _render(parse_text(native).root)
        assert generated.count("# SITAI BEGIN information:") == 1
        # Full source includes the separate impose-autonomy action; its body,
        # all eligibility/cooldown/accept/decline blocks and special JE x3 survive.
        assert "accept_score" not in _overlay(generated, f"{identity}.ai.propose_score")
    policy, generated, _, _ = compiled[AUTONOMY]
    overlay = _overlay(generated, f"{AUTONOMY}.ai.propose_score")
    facts = _facts(policy, {"liberty": 90, "war_defeat": False})
    assert _native_number(300, overlay, facts) == pytest.approx(354)
    assert _native_number(0, overlay, facts) == 0


def test_player_disable_and_unknown_local_facts_keep_original_scores(compiled):
    for identity in actions.CANDIDATES:
        policy, generated, native, words = compiled[identity]
        values: dict[str, object] = {
            "liberty": 90,
            "war_defeat": True,
            "default": True,
            "net_surplus": -100,
        }
        assert decision_rules.evaluate(policy, values, is_ai=False) == {}
        assert (
            decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
        )
        base = BASES[identity]
        overlay = _overlay(generated, f"{identity}.ai.propose_score")
        assert _native_number(base, overlay, _facts(policy, values, is_ai=False)) == base
        assert _native_number(base, overlay, {"ROOT": {"is_ai": True}}) == base
        assert (
            decision_rules.patch(
                native,
                replace(policy, enabled_domains=frozenset()),
                baseline=native,
                default_strategy=False,
                reader_words=words,
            )
            == native
        )


def test_catalog_and_complete_source_contract_do_not_authorize_other_diplomatic_roles(derived):
    frozen = actions.load_baseline()
    actions.verify_inputs(frozen["texts"])
    catalog = actions.consumer_catalog()
    assert set(catalog) == {AUTONOMY, PAYMENTS, BLOC}
    assert len(derived["rules"]) == 7
    assert set(derived["readers"]) == {"liberty", "war_defeat", "default", "net_surplus"}
    assert all(row["scope_evidence_line"] == 118 for row in catalog.values())
    assert all(row["score_evidence_line"] == 140 for row in catalog.values())
    assert all(
        row["actor"] == "root" and row["native_root"] == "country" for row in catalog.values()
    )
    assert all(
        row["native_unit"] == "score" and row["operation"] == "multiply" for row in catalog.values()
    )
    assert all(row["target_binding"] == "unsupported_not_consumed" for row in catalog.values())
    assert len({row["field"] for row in derived["rules"]}) == 3
    # No loans boolean means neither ordinary low-debt borrowing nor an
    # unmeasured principal transfer is invented as an additional penalty.
    assert "loans" not in derived["readers"]


@pytest.mark.parametrize("source", list(actions.SOURCE_HASHES))
def test_complete_input_hash_drift_rejected(source):
    inputs = actions.load_baseline()["texts"]
    with pytest.raises(ValueError, match="漂移"):
        actions.verify_inputs({**inputs, source: inputs[source] + "\n# drift"})


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (actions.CANDIDATES[AUTONOMY], "\t\tsubject\n", "\t\toverlord\n"),
        (actions.CANDIDATES[AUTONOMY], "is_subject = yes", "is_subject = no"),
        (actions.CANDIDATES[AUTONOMY], "liberty_desire >= 75", "liberty_desire >= 50"),
        (actions.CANDIDATES[AUTONOMY], "value = -30", "value = 0"),
        (actions.CANDIDATES[PAYMENTS], "groups= { overlord }", "groups= { subject }"),
        (actions.CANDIDATES[PAYMENTS], "income_transfer = -0.1", "income_transfer = 0.1"),
        (actions.CANDIDATES[BLOC], "groups = { general }", "groups = { subject }"),
        (actions.CANDIDATES[BLOC], "requires_approval = yes", "requires_approval = no"),
        (
            actions.CANDIDATES[BLOC],
            "join_power_bloc = scope:target_country",
            "join_power_bloc = root",
        ),
        (actions.CANDIDATES[BLOC], "type = invite_to_power_bloc", "type = alliance"),
        (actions.CANDIDATES[BLOC], "value = 20", "value = 10"),
        (
            actions.CANDIDATES[PAYMENTS],
            "second_country_gets_income_transfer = no",
            "second_country_gets_income_transfer = yes",
        ),
        (actions.README, actions.DOCUMENTATION["actor"], "# AI country scope is unknown"),
    ],
)
def test_resigned_hash_cannot_hide_wrong_role_scope_or_effect(monkeypatch, source, old, new):
    inputs = copy.deepcopy(actions.load_baseline()["texts"])
    assert old in inputs[source]
    inputs[source] = inputs[source].replace(old, new)
    config = copy.deepcopy(actions.load())
    config["sources"][source] = hashlib.sha256(inputs[source].encode()).hexdigest()
    monkeypatch.setattr(actions, "load", lambda: config)
    with pytest.raises(ValueError, match="漂移"):
        actions.verify_inputs(inputs)
