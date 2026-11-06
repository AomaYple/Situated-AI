"""Active-coup base-law transitions through production adapters and PDX."""

from __future__ import annotations

import ast
import hashlib
import re
import tomllib
from math import isfinite
from pathlib import Path
from typing import TypedDict

import pytest
from test_a3_internal_security import _engine, _values
from test_remaining_joint_consumers import _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import config, country_state, decision_adapters, decision_rules
from pdx import internal_security_opportunities as security
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs
from pdx.textio import normalized_text


class CoupFacts(TypedDict):
    origin_effect: float | None
    candidate_effect: float | None
    investment: int | None
    active_coup: bool | None
    resistance_multiplier_modifier: float | None


def _coup_reference(
    *,
    origin_effect: float | None,
    candidate_effect: float | None,
    investment: int | None,
    active_coup: bool | None,
    resistance_multiplier_modifier: float | None,
) -> int:
    """Return a provisional bounded additive preference for one base-law switch.

    Inputs are same-country observations; effects are per-level native values.
    Unknown or a nonpositive actual multiplier withdraws this contribution.
    Other contributions are evaluated independently by the production arbiter.
    """
    if (
        active_coup is not True
        or type(investment) is not int
        or investment < 1
        or resistance_multiplier_modifier is None
        or not isfinite(resistance_multiplier_modifier)
        or resistance_multiplier_modifier <= -1
        or origin_effect is None
        or candidate_effect is None
        or not isfinite(origin_effect)
        or not isfinite(candidate_effect)
    ):
        return 0
    delta = candidate_effect - origin_effect
    if delta > 0:
        return 4
    if delta < 0:
        return -4
    return 0


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    policy = programs.enable(
        dict(adapters.policies)[security.LAW_SOURCE], source=security.LAW_SOURCE
    )
    programs.validate(policy)
    native = security.frozen_inputs()[security.LAW_SOURCE]
    inputs = decision_adapters.read_inputs(adapters)
    generated = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        country_policy=country_state.load(),
        reader_words=frozenset(decision_adapters.reader_evidence(inputs)),
    )
    return policy, generated, native


def test_native_base_law_effects():
    laws = security.inventory(security.frozen_inputs())["laws"]
    for name, expected in {
        "law_national_guard": 0.5,
        "law_guaranteed_liberties": 0.5,
        "law_secret_police": 0.75,
        "law_extraordinary_commission": 0.75,
    }.items():
        effects = [
            row for row in laws[name]["effects"] if row["field"] == "country_coup_resistance_add"
        ]
        assert len(effects) == 1
        assert effects[0]["value"] == expected
        assert effects[0]["unit"] == "per_invested_level"
        assert laws[name]["parent"] is None


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 4),
        ({"origin_effect": 0.75, "candidate_effect": 0.5}, -4),
        ({"candidate_effect": 0.5}, 0),
        ({"investment": 0}, 0),
        ({"investment": None}, 0),
        ({"active_coup": False}, 0),
        ({"active_coup": None}, 0),
        ({"resistance_multiplier_modifier": -1}, 0),
        ({"resistance_multiplier_modifier": -1.01}, 0),
        ({"resistance_multiplier_modifier": None}, 0),
        ({"resistance_multiplier_modifier": float("nan")}, 0),
        ({"origin_effect": None}, 0),
    ],
)
def test_candidate_boundaries(changes, expected):
    facts: CoupFacts = {
        "origin_effect": 0.5,
        "candidate_effect": 0.75,
        "investment": 1,
        "active_coup": True,
        "resistance_multiplier_modifier": 0.0,
    }
    facts.update(changes)
    assert _coup_reference(**facts) == expected


def test_query_proof_and_source_drift():
    inputs = security.frozen_inputs()
    query = security.query_from_reader("AND", {"security_query": "active_coup_positive_resistance"})
    proof = security.compile_query(query, inputs)
    assert (
        proof.expression
        == "AND = { has_journal_entry = je_ip4_coup modifier:country_coup_resistance_mult > -1 }"
    )
    assert proof.world_scans == 0
    for source in security.required_query_sources(query):
        with pytest.raises(ValueError, match="来源漂移"):
            security.compile_query(query, {**inputs, source: inputs[source] + "\n"})


@pytest.mark.parametrize(
    ("coup", "multiplier", "expected"),
    [
        (True, 0, True),
        (True, -1, False),
        (True, -2, False),
        (False, 0, False),
        (None, 0, None),
        (True, None, None),
    ],
)
def test_query_with_independent_pdx_evaluator(coup, multiplier, expected):
    text = security.render_query(security.SecurityCoupQuery())
    parsed = parse_text(text)
    assert not parsed.errors
    facts = {
        "has_journal_entry": {(("argument", "je_ip4_coup"),): coup},
        "modifier:country_coup_resistance_mult": multiplier,
    }
    assert pdx_eval.condition(parsed.root, facts) is expected


def test_derives_both_directions_and_all_secret_police_variant_exclusions():
    adapters = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))
    rules = security.derive(adapters)["rules"]
    coup = [r for r in rules if r["id"].endswith("_coup_resistance")]
    assert len(coup) == 8
    assert {r["value"] for r in coup} == {4, -4}
    assert {r["semantic_role"] for r in coup} == {"benefit", "cost"}
    assert {r["contribution_group"] for r in coup} == {"law_security_actual_coup_resistance"}
    for rule in coup:
        facts = {(c["fact"], c["op"], c["value"]) for c in rule["conditions"]}
        assert ("home_affairs_investment", ">=", 1) in facts
        assert ("security_active_coup_positive_resistance", "=", True) in facts
        if "_from_law_secret_police_" in rule["id"]:
            for variant in ("law_shinsengumi", "law_third_section", "law_okhrana"):
                assert (f"security_current_{variant}", "=", False) in facts


@pytest.mark.integration
def test_candidate_sources_match_live_normalized_installation():
    inputs = security.frozen_inputs()
    for source in security._COUP_SOURCES:
        assert (
            normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
            == inputs[source]
        )


@pytest.mark.integration
def test_lightweight_real_rule_parser_patch_and_independent_native_pdx():
    adapters = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))
    data = security.derive(adapters)
    data["rules"] = [
        row
        for row in data["rules"]
        if row["id"].endswith("_coup_resistance") or "_new_institution_" in row["id"]
    ]
    used = {c["fact"] for row in data["rules"] for c in row["conditions"]}
    data["readers"] = {key: value for key, value in data["readers"].items() if key in used}
    native = security.frozen_inputs()[security.LAW_SOURCE]
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": hashlib.sha256(native.encode()).hexdigest(),
            "readers": data["readers"],
            "rules": [{k: v for k, v in row.items() if k != "source"} for row in data["rules"]],
            "domains": {"political": True},
        },
        source_sha256="0" * 64,
    )
    evidence = "\n".join(security.frozen_inputs().values()) + (
        config.GAME / "common/scripted_triggers/00_strike_triggers.txt"
    ).read_text(encoding="utf-8-sig")
    evidence += (config.GAME / "common/script_values/ideology_values.txt").read_text(
        encoding="utf-8-sig"
    )
    for source in (
        "common/character_interactions/00_character_interactions.txt",
        "common/scripted_buttons/08_tsarpoints_buttons.txt",
        "common/decisions/japan_decisions.txt",
        "common/ai_strategies/00_default_strategy.txt",
    ):
        evidence += (config.GAME / source).read_text(encoding="utf-8-sig")
    generated = decision_rules.patch(
        native, policy, baseline=native, default_strategy=False, reader_evidence=evidence
    )
    field = "law_secret_police.ai_enact_weight_modifier"
    for coup, expected in ((True, 4), (False, 0), (None, 0)):
        values: dict[str, object] = {
            r.key: False if r.kind == "boolean" else 0 for r in policy.readers
        }
        values.update(
            security_current_law_national_guard=True,
            home_affairs_investment=1,
            security_active_coup_positive_resistance=coup,
        )
        reference = decision_rules.evaluate(policy, values, is_ai=True)
        assert reference.get(field, ("native", 0))[1] == expected
        facts = _facts(policy, values)
        facts["ROOT"].update(
            has_journal_entry={(("argument", "je_ip4_coup"),): coup},
            **{"modifier:country_coup_resistance_mult": 0},
        )
        assert _native_number(0, _overlay(generated, field), facts) == expected
        facts["ROOT"]["is_ai"] = False
        assert _native_number(0, _overlay(generated, field), facts) == 0
        assert decision_rules.evaluate(policy, values, is_ai=False) == {}
        assert (
            decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
        )
    assert (
        decision_rules.patch(
            native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
        )
        == native
    )
    values.update(default=True, bureaucracy=-1, security_active_coup_positive_resistance=True)
    assert decision_rules.evaluate(policy, values, is_ai=True)[field][1] == 4
    values.update(
        security_current_law_national_guard=False, security_current_law_no_home_affairs=True
    )
    assert decision_rules.evaluate(policy, values, is_ai=True)[field][1] == -8
    values.update(
        security_current_law_no_home_affairs=False, security_current_law_secret_police=True
    )
    for variant in ("law_shinsengumi", "law_third_section", "law_okhrana"):
        values[f"security_current_{variant}"] = True
        assert "law_national_guard.ai_enact_weight_modifier" not in decision_rules.evaluate(
            policy, values, is_ai=True
        )
        values[f"security_current_{variant}"] = False
    stripped = re.sub(
        "(?m)^\\s*# SITAI BEGIN information:[^\\n]+\\n.*?^\\s*# SITAI END information:[^\\n]+\\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    assert _render(parse_text(native).root) == _render(parse_text(stripped).root)


def test_exact_je_direction_full_parent_and_actual_lines():
    proof = security.compile_query(security.SecurityCoupQuery(), security.frozen_inputs())
    assert len(proof.source_hashes) == 6
    assert "common/journal_entries/01_coup.txt:1" in proof.references
    assert "common/journal_entries/01_coup.txt:85" in proof.references
    assert "common/journal_entries/01_coup.txt:112" in proof.references
    assert "common/script_values/ip4_je_values.txt:856" in proof.references
    tree = ast.parse(Path(security.__file__).read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    for name in (
        "query_from_reader",
        "render_query",
        "required_query_sources",
        "compile_query",
        "derive",
    ):
        assert names.count(name) == 1


def test_repin_does_not_bypass_independent_je_semantic_ast(monkeypatch):
    inputs = security.frozen_inputs()
    source = "common/journal_entries/01_coup.txt"
    altered = inputs[source].replace(
        '"scripted_bar_progress(je_ip4_coup_progress_bar)" >= 120',
        '"scripted_bar_progress(je_ip4_coup_progress_bar)" <= 120',
    )
    assert altered != inputs[source]
    data = security.load()
    data["sources"][source] = hashlib.sha256(altered.encode()).hexdigest()
    monkeypatch.setattr(security, "load", lambda: data)
    with pytest.raises(ValueError, match="完整父AST漂移"):
        security.compile_query(security.SecurityCoupQuery(), {**inputs, source: altered})


def test_inventory_marks_only_four_observed_base_law_transition_effects():
    laws = security.inventory(security.frozen_inputs())["laws"]
    observed = {
        law
        for law, data in laws.items()
        for row in data["effects"]
        if row["responsibility"] == "observed_active_coup_base_law_transition_only"
    }
    assert observed == {
        "law_national_guard",
        "law_secret_police",
        "law_guaranteed_liberties",
        "law_extraordinary_commission",
    }
    for law, data in laws.items():
        for row in data["effects"]:
            if row["responsibility"] == "observed_active_coup_base_law_transition_only":
                assert row["field"] == "country_coup_resistance_add"
                assert row["unit"] == "per_invested_level"
            if law in {"law_shinsengumi", "law_third_section", "law_okhrana"}:
                assert (
                    row["responsibility"]
                    == "variant_parent_effect_merging_requires_independent_contract"
                )
    assert any(
        row["responsibility"] == "actual_suppression_exposure_not_registered"
        for data in laws.values()
        for row in data["effects"]
    )


CASES = [
    ("law_secret_police", {"security_current_law_national_guard": True}, 4),
    ("law_national_guard", {"security_current_law_secret_police": True}, -4),
    ("law_guaranteed_liberties", {"security_current_law_secret_police": True}, -4),
    ("law_extraordinary_commission", {"security_current_law_secret_police": True}, 0),
    (
        "law_secret_police",
        {
            "security_current_law_national_guard": True,
            "security_active_coup_positive_resistance": False,
        },
        0,
    ),
    (
        "law_secret_police",
        {
            "security_current_law_national_guard": True,
            "security_active_coup_positive_resistance": None,
        },
        0,
    ),
    (
        "law_secret_police",
        {"security_current_law_national_guard": True, "home_affairs_investment": 0},
        0,
    ),
    (
        "law_secret_police",
        {"security_current_law_national_guard": True, "home_affairs_investment": None},
        0,
    ),
    (
        "law_secret_police",
        {
            "security_current_law_national_guard": True,
            "home_affairs_investment": 3,
            "security_movement_radicalism_base": True,
        },
        16,
    ),
    (
        "law_guaranteed_liberties",
        {"security_current_law_secret_police": True, "security_movement_radicalism_base": True},
        -2,
    ),
    (
        "law_secret_police",
        {"security_current_law_no_home_affairs": True, "bureaucracy": -1, "default": True},
        -14,
    ),
    *[
        (
            "law_guaranteed_liberties",
            {"security_current_law_secret_police": True, f"security_current_{law}": True},
            0,
        )
        for law in ("law_shinsengumi", "law_third_section", "law_okhrana")
    ],
]


@pytest.mark.parametrize(("law", "changes", "expected"), CASES)
@pytest.mark.integration
def test_normal_adapter_program_pdx_hand_reference(production, law, changes, expected):
    policy, generated, _native = production
    values = _values(
        policy,
        {"home_affairs_investment": 1, "security_active_coup_positive_resistance": True, **changes},
    )
    field = f"{law}.ai_enact_weight_modifier"
    assert decision_rules.evaluate(policy, values, is_ai=True).get(field, ("native", 0))[
        1
    ] == pytest.approx(expected)
    facts = _engine(policy, values)
    facts["ROOT"]["has_journal_entry"] = {
        (("argument", "je_ip4_coup"),): values["security_active_coup_positive_resistance"]
    }
    facts["ROOT"]["modifier:country_coup_resistance_mult"] = 0
    assert _native_number(0, _overlay(generated, field), facts) == pytest.approx(expected)


@pytest.mark.parametrize("multiplier", [-2, -1, None, -0.999])
@pytest.mark.integration
def test_pdx_multiplier_and_country_decoys(production, multiplier):
    policy, generated, _native = production
    values = _values(
        policy,
        {
            "home_affairs_investment": 1,
            "security_current_law_national_guard": True,
            "security_active_coup_positive_resistance": True,
        },
    )
    facts = _engine(policy, values)
    facts["ROOT"]["has_journal_entry"] = {(("argument", "je_ip4_coup"),): True}
    facts["ROOT"]["modifier:country_coup_resistance_mult"] = multiplier
    body = _overlay(generated, "law_secret_police.ai_enact_weight_modifier")
    assert _native_number(0, body, facts) == (
        4 if multiplier is not None and multiplier > -1 else 0
    )
    facts["scope:target_country"] = {
        "has_journal_entry": {(("argument", "je_ip4_coup"),): True},
        "modifier:country_coup_resistance_mult": 0,
    }
    facts["ROOT"]["has_journal_entry"] = {(("argument", "je_ip4_coup"),): False}
    assert _native_number(0, body, facts) == 0


@pytest.mark.integration
def test_player_disabled_native_tail_and_single_clamp(production):
    policy, generated, native = production
    values = _values(
        policy,
        {
            "home_affairs_investment": 1,
            "security_current_law_national_guard": True,
            "security_active_coup_positive_resistance": True,
        },
    )
    facts = _engine(policy, values)
    facts["ROOT"].update(is_ai=False, has_journal_entry={(("argument", "je_ip4_coup"),): True})
    facts["ROOT"]["modifier:country_coup_resistance_mult"] = 0
    assert (
        _native_number(0, _overlay(generated, "law_secret_police.ai_enact_weight_modifier"), facts)
        == 0
    )
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.patch(
            native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
        )
        == native
    )
    stripped = re.sub(
        "(?m)^\\s*# SITAI BEGIN information:[^\\n]+\\n.*?^\\s*# SITAI END information:[^\\n]+\\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    assert _render(parse_text(native).root) == _render(parse_text(stripped).root)
    for program in policy.consumer_programs:
        body = _overlay(generated, ".".join(program.field))
        assert len(re.findall("(?m)^\\t{3}min = ", body)) == 1
        assert len(re.findall("(?m)^\\t{3}max = ", body)) == 1
