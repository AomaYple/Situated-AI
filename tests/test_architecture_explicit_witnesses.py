"""Actual explicit cards and continuous support: independent six-role witnesses.

The handwritten observations and numbers below are independent of production
selectors, renderers and evaluators. Each card changes its complete physical
consumer output. Capture is deliberately limited to its named S2/S3 owner.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, replace
from typing import Any

import pytest
from test_architecture_all_consumer_witnesses import _json_observation, _units
from test_situated_action_reference import _COMPLETE, _typed

from pdx import (
    config,
    decision_adapters,
    decision_rules,
    decisions,
    distribution,
    version_contracts,
)
from pdx.parser import parse_text
from pdx.situated import audit, compiler, pdx_eval
from pdx.situated.native_treatments import _digest, _resolve
from pdx.situated.support_program import SupportObservation

pytest_plugins = ("tools.ci.architecture_witness_capture",)
pytestmark = pytest.mark.integration
SOURCE = "common/ai_strategies/00_default_strategy.txt"
PATH = (decisions.product_path().relative_to(config.REPO) / SOURCE).as_posix()
DEFINITION = "ai_strategy_default"
_MARKED = re.compile(r"(?ms)^\s*# SITAI BEGIN [^\n]+\n.*?^\s*# SITAI END [^\n]+\n")

# Each tuple gives positive / negative / actual missing-input observations and
# the complete field's hand-calculated signed ADD, including coexisting cards.
# The education negative/unknown remains +.15 from independent industry work.
CARDS: tuple[tuple[Any, ...], ...] = (
    (
        "fiscal_recovery",
        "diplomatic_play_neutrality",
        "S2",
        "economy_fiscal_construction",
        ({"in_default": True}, 8),
        ({"in_default": False}, 0),
        ({"in_default": None}, 0),
    ),
    (
        "wartime_defense",
        "diplomatic_play_neutrality",
        "S3",
        "military_security_recovery",
        ({"is_at_war": True}, 6),
        ({"is_at_war": False}, 0),
        ({"is_at_war": None}, 0),
    ),
    (
        "political_reform",
        "change_law_chance",
        "S2",
        "politics_governance_identity",
        ({}, 0.5),
        ({"is_at_war": True}, 0),
        ({"is_at_war": None}, 0),
    ),
    (
        "industrial_foundation",
        "economic_vs_government_spending_balance",
        "S2",
        "economy_fiscal_construction",
        ({}, 0.15),
        ({"in_default": True}, 0),
        ({"in_default": None}, 0),
    ),
    (
        "education_and_research",
        "economic_vs_government_spending_balance",
        "S2",
        "society_education_knowledge",
        ({"literacy_rate": 0.3, "sitai_context_need_education": True}, 0.025),
        ({"literacy_rate": 0.6, "sitai_context_need_education": True}, 0.15),
        ({"literacy_rate": None, "sitai_context_need_education": True}, 0.15),
    ),
    (
        "diplomatic_restraint",
        "recklessness",
        "S3",
        "military_security_recovery",
        ({"is_at_war": True}, -4),
        ({"is_at_war": False}, 2),
        ({"is_at_war": None}, 0),
    ),
    (
        "diplomatic_opening",
        "recklessness",
        "S3",
        "market_trade_company_diplomacy",
        ({}, 2),
        ({"in_default": True}, 0),
        ({"is_at_war": None}, 0),
    ),
    (
        "reform_progressive_window",
        "max_progressiveness",
        "S2",
        "politics_governance_identity",
        ({}, 5),
        ({"is_at_war": True}, 0),
        ({"is_at_war": None}, 0),
    ),
    (
        "reform_conservative_guard",
        "max_regressiveness",
        "S2",
        "politics_governance_identity",
        ({"in_default": True}, 5),
        ({"in_default": False}, 0),
        ({"in_default": None}, 0),
    ),
    (
        "diplomatic_boldness_window",
        "diplomatic_play_boldness",
        "S3",
        "market_trade_company_diplomacy",
        ({}, 8),
        ({"is_at_war": True}, 0),
        ({"is_at_war": None}, 0),
    ),
    (
        "diplomatic_aggression_guard",
        "aggression",
        "S3",
        "market_trade_company_diplomacy",
        ({}, 0.1),
        ({"in_default": True}, 0),
        ({"in_default": None}, 0),
    ),
)
FIELDS = frozenset(row[1] for row in CARDS) | {"diplomatic_play_support"}


def _overlay(text, field):
    matches = re.findall(
        rf"(?ms)^\s*# SITAI BEGIN {re.escape(field)}\n(.*?)^\s*# SITAI END {re.escape(field)}\n",
        text,
    )
    assert len(matches) == 1, (field, len(matches))
    return matches[0]


def _field(text, field):
    parsed = parse_text(text)
    assert not parsed.errors
    node, state = _resolve(parsed.root, DEFINITION, field)
    assert state == "found"
    assert node is not None
    return _digest(node.value)


@pytest.fixture(scope="module")
def candidate():
    # This is the actual release-profile package builder and metadata, not a
    # test model whose program is silently substituted into production output.
    policy, extensions, files = distribution.package_inputs(include_engineering_metadata=True)
    built = files[SOURCE]
    assert isinstance(built, str)
    metadata = json.loads(files[".metadata/metadata.json"])
    model = compiler.load_model()
    continuous = audit._production_continuous_bindings(files)
    assert len(continuous) == 1
    support = continuous[0].writer.program
    assert support is not None
    disabled_extensions = replace(
        extensions,
        reform_enabled=False,
        market_enabled=False,
        security_enabled=False,
        economy_enabled=False,
        diplomacy_enabled=False,
    )
    disabled = decisions.build(replace(policy, enabled=False), extensions=disabled_extensions)
    return {
        "built": built,
        "model": model,
        "metadata": metadata,
        "support": support,
        "disabled": disabled[SOURCE],
        "baseline": decisions.baseline_path().read_text(encoding="utf-8"),
    }


def _disk(candidate, field):
    installed = (config.REPO / PATH).read_text(encoding="utf-8-sig")
    # Compare the entire physical field, not only an isolated marked branch.
    assert _field(installed, field) == _field(candidate["built"], field), field
    return installed


def _record(
    witness, *, card, field, stage, requirement, role, observations, expected, reference, actual
):
    assert expected == reference == actual
    witness(
        evidence_ids=["a2.explicit." + requirement],
        case_id=f"explicit.{card}.{role}",
        role=role,
        input={
            "card": card,
            "contract_version": version_contracts.active_version(),
            "responsibility_stage": stage,
            "responsibility_requirement": requirement,
            **_json_observation(observations),
        },
        expected=expected,
        reference=reference,
        generated=actual,
        production=[
            "mod/decisions/actions.toml",
            "mod/decisions/extensions.toml",
            "src/pdx/situated/compiler.py",
            "src/pdx/situated/support_program.py",
            "src/pdx/decisions.py",
        ],
        consumers=[{"path": PATH, "definition": DEFINITION, "field": field}],
    )


def _boundary_roles(
    candidate,
    architecture_witness,
    *,
    card,
    field,
    stage,
    requirement,
    player_engine,
    player_reference,
):
    installed = _disk(candidate, field)
    actual = pdx_eval.select(_overlay(installed, field), player_engine)
    assert actual.operation is None
    _record(
        architecture_witness,
        card=card,
        field=field,
        stage=stage,
        requirement=requirement,
        role="player",
        observations={"engine": player_engine, "is_ai": False},
        expected={"contribution": False},
        reference={"contribution": player_reference},
        actual={"contribution": actual.operation is not None},
    )
    marker = f"# SITAI BEGIN {field}\n"
    assert marker not in candidate["disabled"]
    disabled_native = _field(candidate["disabled"], field)
    baseline = _field(candidate["baseline"], field)
    assert disabled_native == baseline
    if field == "diplomatic_play_support":
        disabled_reference = bool(
            decisions.diplomatic_play_support_addition(decisions.Extensions())
        )
    else:
        disabled_reference = bool(
            compiler.evaluate_actions(
                candidate["model"],
                _typed(_COMPLETE),
                is_ai=True,
                enabled_consumer_fields=frozenset(),
            )
        )
    _record(
        architecture_witness,
        card=card,
        field=field,
        stage=stage,
        requirement=requirement,
        role="disabled",
        observations={"enabled_modules": [], "actual_builder": "decisions.build"},
        expected={"contribution": False, "native_ast": baseline},
        reference={"contribution": bool(disabled_reference), "native_ast": baseline},
        actual={"contribution": marker in candidate["disabled"], "native_ast": disabled_native},
    )
    expected_native = {"complete_native_numeric_ast": baseline}
    reference_native = {
        "complete_native_numeric_ast": _field(_MARKED.sub("\n", candidate["built"]), field)
    }
    actual_native = {"complete_native_numeric_ast": _field(_MARKED.sub("\n", installed), field)}
    _record(
        architecture_witness,
        card=card,
        field=field,
        stage=stage,
        requirement=requirement,
        role="native_tail",
        observations={
            "remove_only_declared_overlays": True,
            "original_source": decisions.baseline_path().relative_to(config.REPO).as_posix(),
            "original_sha256": hashlib.sha256(candidate["baseline"].encode()).hexdigest(),
        },
        expected=expected_native,
        reference=reference_native,
        actual=actual_native,
    )


@pytest.mark.parametrize("row", CARDS, ids=[row[0] for row in CARDS])
def test_every_explicit_card_executes_actual_six_role_witnesses(
    candidate, architecture_witness, row
):
    card, field, stage, requirement, *cases = row
    installed = _disk(candidate, field)
    overlay = _overlay(installed, field)
    assert card in overlay
    assert cases[0][1] != cases[1][1], "card must change the complete physical output"
    for role, (changes, expected) in zip(("positive", "negative", "unknown"), cases, strict=True):
        engine = {**_COMPLETE, **changes}
        if role == "unknown":
            assert any(value is None for value in changes.values())
        typed = _typed(engine)
        reference = compiler.evaluate_actions(candidate["model"], typed, is_ai=True).get(field)
        actual = pdx_eval.select(overlay, engine)
        reference_value = reference[1] if reference else 0
        assert actual.delta == pytest.approx(expected)
        assert reference_value == pytest.approx(expected)
        _record(
            architecture_witness,
            card=card,
            field=field,
            stage=stage,
            requirement=requirement,
            role=role,
            observations={"engine": engine, "typed": typed, "counterfactual": changes},
            expected=_units("add", expected),
            reference=_units("add", reference_value),
            actual=_units("add", actual.delta),
        )
    player_engine = {**_COMPLETE, **cases[0][0], "is_ai": False}
    player = compiler.evaluate_actions(candidate["model"], _typed(player_engine), is_ai=False)
    _boundary_roles(
        candidate,
        architecture_witness,
        card=card,
        field=field,
        stage=stage,
        requirement=requirement,
        player_engine=player_engine,
        player_reference=bool(player),
    )


def _support_facts(observation):
    partner, opponent = (
        ("scope:enemy_country", "scope:country")
        if observation.initiator
        else ("scope:country", "scope:enemy_country")
    )
    return {
        "ROOT": {
            "is_ai": observation.is_ai,
            "economic_dependence": {
                (("argument", "scope:country"),): observation.country_dependence,
                (("argument", "scope:enemy_country"),): observation.enemy_dependence,
            },
            "sitai_defense_commitment": {(("PARTNER", partner),): observation.commitment},
            "sitai_neighbor_defense": {
                tuple(sorted((("PARTNER", partner), ("OPPONENT", opponent)))): observation.neighbor
            },
        },
        "scope:country": {} if observation.has_sides else None,
        "scope:enemy_country": {} if observation.has_sides else None,
        "scope:is_initiator": observation.initiator,
    }


def test_continuous_support_executes_actual_six_role_witnesses(candidate, architecture_witness):
    field = "diplomatic_play_support"
    installed = _disk(candidate, field)
    overlay = _overlay(installed, field)
    program = candidate["support"]
    # Independent source-level oracle: (0-4)*5 + max(25,15) = 5;
    # reversing the defensive direction yields -20-25=-45. Unknown economics
    # drops only its term, retaining the actual +25 defensive commitment.
    observation = SupportObservation(True, True, False, 0, 4, True, True)
    cases = (
        ("positive", observation, 5),
        ("negative", replace(observation, initiator=True), -45),
        ("unknown", replace(observation, country_dependence=None), 25),
    )
    for role, observed, expected in cases:
        engine = _support_facts(observed)
        reference = program.evaluate(observed).value
        actual = pdx_eval.select(overlay, engine).delta
        _record(
            architecture_witness,
            card=program.writer_id,
            field=field,
            stage="S3",
            requirement="market_trade_company_diplomacy",
            role=role,
            observations={"engine": engine, "observation": asdict(observed)},
            expected=_units("add", expected),
            reference=_units("add", reference),
            actual=_units("add", actual),
        )
    player = replace(observation, is_ai=False)
    _boundary_roles(
        candidate,
        architecture_witness,
        card=program.writer_id,
        field=field,
        stage="S3",
        requirement="market_trade_company_diplomacy",
        player_engine=_support_facts(player),
        player_reference=bool(program.evaluate(player).value),
    )


def test_explicit_and_continuous_denominator_is_exact_and_separate(candidate):
    model = candidate["model"]
    writers = candidate["metadata"]["situated_actions"]["consumer_ir"]["writers"]
    cards = [writer for writer in writers if writer["kind"] == "action_card"]
    assert len(cards) == 11
    assert {writer["definition"] for writer in cards} == {row[0] for row in CARDS}
    assert {card.id for card in model.actions} == {row[0] for row in CARDS}
    assert {writer["field"] for writer in cards} == {row[1] for row in CARDS}
    assert len({row[1] for row in CARDS}) == 8
    continuous = [writer for writer in writers if writer["kind"] == "support_program"]
    assert len(continuous) == 1
    assert continuous[0]["field"] == "diplomatic_play_support"
    assert len(FIELDS) == 9
    legacy: set[str] = set()
    for source, policy in (
        ("mod/decisions/information.toml", decision_rules.load()),
        *decision_adapters.load().policies,
    ):
        if source == "mod/decisions/information.toml":
            legacy.update(".".join(rule.field) for rule in policy.rules)
        elif source == SOURCE:
            legacy.update(
                ".".join(rule.field[1:]) for rule in policy.rules if rule.field[0] == DEFINITION
            )
    assert not FIELDS & legacy, "explicit/continuous owners cannot duplicate a legacy field"


def test_release_build_has_the_expected_nine_actual_physical_fields(candidate):
    """Build-only pre-freeze check, deliberately not a formal witness capture."""
    for field in FIELDS:
        assert _overlay(candidate["built"], field)
        assert _field(_MARKED.sub("\n", candidate["built"]), field) == _field(
            candidate["baseline"], field
        )
