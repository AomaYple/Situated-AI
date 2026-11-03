"""Six separately owned S1 responsibilities on actual complete production fields.

Expected numbers are handwritten from source-level units, observed identities
and arithmetic. The reference and installed generated PDX are both compared to
that oracle; no S2/S3 record is reused to sign a kernel responsibility.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import asdict, replace
from typing import Any, cast

import pytest
import test_architecture_explicit_witnesses as explicit
from test_architecture_all_consumer_witnesses import _json_observation, _units
from test_situated_action_reference import _COMPLETE, _typed

from pdx import config, decisions
from pdx.model import Assignment, Block, ParsedFile, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval
from pdx.situated.native_treatments import _digest, _resolve
from pdx.situated.support_program import SupportObservation

pytest_plugins = ("tools.ci.architecture_witness_capture",)
pytestmark = pytest.mark.integration
BALANCE = "economic_vs_government_spending_balance"
NEUTRALITY = "diplomatic_play_neutrality"
SUPPORT = "diplomatic_play_support"
REQUIREMENTS = (
    "production_chain",
    "joint_benefit_cost",
    "local_unknown",
    "units_direction",
    "single_cap_native_tail",
    "independent_pdx_witness",
)


class _FieldTrees:
    """Reuse only syntax within one fixture, keyed by the complete actual text."""

    def __init__(self):
        self._parsed: dict[str, ParsedFile] = {}
        self._resolved: dict[tuple[str, str, str], tuple[Assignment | None, str]] = {}

    def field(self, text, definition, field):
        if text not in self._parsed:
            self._parsed[text] = parse_text(text)
        parsed = self._parsed[text]
        assert not parsed.errors
        key = (text, definition, field)
        if key not in self._resolved:
            self._resolved[key] = _resolve(parsed.root, definition, field)
        node, state = self._resolved[key]
        assert state == "found"
        assert node is not None
        return node


@pytest.fixture(scope="module")
def candidate():
    # Reuse the frozen real release builder, never a modified test-only model.
    built = cast("Any", explicit.candidate).__wrapped__()
    built["field_trees"] = _FieldTrees()
    return built


def _record(witness, requirement, field, role, observations, expected, reference, actual):
    assert requirement in REQUIREMENTS
    assert expected == reference == actual
    witness(
        evidence_ids=["a2.s1." + requirement],
        case_id=f"kernel.{requirement}.{role}.{observations.get('case', 'boundary')}",
        role=role,
        input={
            "responsibility_stage": "S1",
            "requirement": requirement,
            **_json_observation(observations),
        },
        expected=expected,
        reference=reference,
        generated=actual,
        production=[
            "mod/decisions/actions.toml",
            "mod/decisions/facts.toml",
            "mod/decisions/relations.toml",
            "src/pdx/situated/compiler.py",
            "src/pdx/situated/decision_ir.py",
            "src/pdx/situated/support_program.py",
            "src/pdx/decisions.py",
            "src/pdx/distribution.py",
        ],
        consumers=[{"path": explicit.PATH, "definition": explicit.DEFINITION, "field": field}],
    )


def _inputs(changes=None, *, public_school=False, schools=False):
    engine = {**_COMPLETE, **(changes or {})}
    typed = _typed(engine)
    typed.update(current_public_schools=public_school, schools_present=schools)
    engine.update(
        has_law_or_variant={(("argument", "law_type:law_public_schools"),): public_school},
        has_institution={(("argument", "institution_schools"),): schools},
        has_journal_entry={
            (("argument", "je_grunderzeit"),): False,
            (("argument", "je_spa_economic_regeneration_master"),): False,
            (("argument", "je_sick_man_main"),): False,
        },
        has_variable={(("argument", "grunderzeit_participant_low_var"),): False},
    )
    # Native field statements use current country; overlay explicitly uses ROOT.
    return typed, {**engine, "ROOT": engine}


def _field(candidate, text, field):
    node = candidate["field_trees"].field(text, explicit.DEFINITION, field)
    return _digest(node.value)


def _complete_value(candidate, text, field, engine):
    node = candidate["field_trees"].field(text, explicit.DEFINITION, field)
    value = pdx_eval._numeric_value(node, engine)
    assert value is not None
    return value


def _action_case(
    candidate,
    witness,
    requirement,
    field,
    role,
    label,
    changes,
    expected,
    *,
    public_school=False,
    schools=False,
    native=0,
    journal=None,
):
    typed, engine = _inputs(changes, public_school=public_school, schools=schools)
    if journal is not None:
        engine["has_journal_entry"][(("argument", journal),)] = True
    installed = explicit._disk(candidate, field)
    reference = compiler.evaluate_actions(candidate["model"], typed, is_ai=True).get(field)
    reference_delta = reference[1] if reference else 0
    actual = pdx_eval.select(explicit._overlay(installed, field), engine)
    assert _complete_value(candidate, candidate["baseline"], field, engine) == pytest.approx(native)
    assert _complete_value(candidate, installed, field, engine) == pytest.approx(native + expected)
    expected_output = {
        **_units("add", expected),
        "complete_value_thousandths": round((native + expected) * 1000),
    }
    reference_output = {
        **_units("add", reference_delta),
        "complete_value_thousandths": round(
            (_complete_value(candidate, candidate["baseline"], field, engine) + reference_delta)
            * 1000
        ),
    }
    actual_output = {
        **_units("add", actual.delta),
        "complete_value_thousandths": round(
            _complete_value(candidate, installed, field, engine) * 1000
        ),
    }
    assert actual.operation == "add"
    _record(
        witness,
        requirement,
        field,
        role,
        {"case": label, "engine": engine, "typed": typed, "native_base": native},
        expected_output,
        reference_output,
        actual_output,
    )


def _boundaries(candidate, witness, requirement, field, *, support=False):
    installed = explicit._disk(candidate, field)
    if support:
        observation = SupportObservation(False, True, False, 0, 4, True, True)
        engine = explicit._support_facts(observation)
        player_reference = bool(candidate["support"].evaluate(observation).value)
        disabled_reference = bool(
            decisions.diplomatic_play_support_addition(decisions.Extensions())
        )
    else:
        # Keep an AI-active business scenario so the player check detects a
        # missing is_ai guard rather than passing on inactive qualifications.
        typed, engine = _inputs(
            {"is_ai": False, "in_default": field == NEUTRALITY, "is_at_war": True}
        )
        assert field in compiler.evaluate_actions(candidate["model"], typed, is_ai=True)
        player_reference = bool(compiler.evaluate_actions(candidate["model"], typed, is_ai=False))
        disabled_reference = bool(
            compiler.evaluate_actions(
                candidate["model"], typed, is_ai=True, enabled_consumer_fields=frozenset()
            )
        )
    actual_player = pdx_eval.select(explicit._overlay(installed, field), engine)
    _record(
        witness,
        requirement,
        field,
        "player",
        {"engine": engine},
        {"contribution": False},
        {"contribution": player_reference},
        {"contribution": actual_player.operation is not None},
    )
    baseline = _field(candidate, candidate["baseline"], field)
    marker = f"# SITAI BEGIN {field}\n"
    _record(
        witness,
        requirement,
        field,
        "disabled",
        {"actual_builder": "decisions.build", "enabled_modules": []},
        {"contribution": False, "native_ast": baseline},
        {"contribution": disabled_reference, "native_ast": baseline},
        {
            "contribution": marker in candidate["disabled"],
            "native_ast": _field(candidate, candidate["disabled"], field),
        },
    )
    _record(
        witness,
        requirement,
        field,
        "native_tail",
        {
            "remove_only_declared_overlays": True,
            "original_source": str(decisions.BASELINE.relative_to(config.REPO)),
            "original_sha256": hashlib.sha256(candidate["baseline"].encode()).hexdigest(),
        },
        {"complete_native_numeric_ast": baseline},
        {
            "complete_native_numeric_ast": _field(
                candidate, explicit._MARKED.sub("\n", candidate["built"]), field
            )
        },
        {
            "complete_native_numeric_ast": _field(
                candidate, explicit._MARKED.sub("\n", installed), field
            )
        },
    )


def test_s1_production_chain_has_one_canonical_writer_and_rejects_a_missing_link(
    candidate, architecture_witness
):
    requirement = "production_chain"
    model = candidate["model"]
    raw = tomllib.loads((config.REPO / "mod/decisions/actions.toml").read_text(encoding="utf-8"))
    card = raw["actions"]["industrial_foundation"]
    assert card["base"] == 0.15
    assert card["consumer"] == "economic_balance"
    bundle = model.consumer_ir
    assert bundle is not None
    rows = [row for row in model.decision_ir if row.action_id == "industrial_foundation"]
    writers = [writer for writer in bundle.writers if writer.definition == "industrial_foundation"]
    assert len(rows) == len(writers) == 1
    row, writer = rows[0], writers[0]
    assert writer.action == row
    assert row in bundle.actions
    assert row.base == card["base"]
    assert row.consumer_id == card["consumer"]
    assert (writer.source, writer.field, writer.actor, writer.operation) == (
        "mod/decisions/actions.toml",
        BALANCE,
        "root",
        "add",
    )
    metadata = candidate["metadata"]["situated_actions"]["consumer_ir"]
    assert metadata["field_owners"][BALANCE] == writer.owner
    assert (
        len([item for item in metadata["writers"] if item["definition"] == "industrial_foundation"])
        == 1
    )
    assert "industrial_foundation" in explicit._overlay(explicit._disk(candidate, BALANCE), BALANCE)
    broken = replace(
        model,
        consumer_ir=replace(
            bundle, writers=tuple(item for item in bundle.writers if item != writer)
        ),
    )
    with pytest.raises(ValueError, match=r"IR|writer|行动"):
        compiler.strategy_overlay(broken)
    typed, _ = _inputs()
    with pytest.raises(ValueError, match=r"IR|writer|行动"):
        compiler.evaluate_actions(broken, typed, is_ai=True)
    for role, label, changes, expected in (
        ("positive", "source_to_installed", {}, 0.15),
        ("negative", "observed_default_exits", {"in_default": True}, 0),
        ("unknown", "unknown_core_is_not_false", {"in_default": None}, 0),
    ):
        _action_case(
            candidate, architecture_witness, requirement, BALANCE, role, label, changes, expected
        )
    _boundaries(candidate, architecture_witness, requirement, BALANCE)


def test_s1_joint_benefit_cost_sums_opposing_actions_and_all_observed_costs(
    candidate, architecture_witness
):
    requirement = "joint_benefit_cost"
    low = {"literacy_rate": 0.3, "sitai_context_need_education": True}
    # +.15-.10-.025 = .025; pressure costs -.10+.08 = -.02.
    # Multiple true predicates in one commitment are an OR, not three charges.
    for role, label, changes, expected in (
        ("positive", "joint_two_benefits", low, 0.025),
        ("negative", "joint_signed_cost", {**low, "net_total_income": -1}, 0.005),
        (
            "negative",
            "same_commitment_three_observations",
            {**low, "net_total_income": -1, "scaled_debt": 0.8, "bureaucracy": -1},
            0.005,
        ),
        ("unknown", "cost_unknown_is_conservative", {**low, "scaled_debt": None}, 0.005),
    ):
        _action_case(
            candidate, architecture_witness, requirement, BALANCE, role, label, changes, expected
        )
    # An enacted school relation is an independent -.025, so .005-.025=-.020.
    _action_case(
        candidate,
        architecture_witness,
        requirement,
        BALANCE,
        "positive",
        "enacted_feedback_is_additional",
        {**low, "net_total_income": -1},
        -0.020,
        public_school=True,
        schools=True,
    )
    _boundaries(candidate, architecture_witness, requirement, BALANCE)


def test_s1_local_unknown_removes_only_unproven_terms_not_independent_costs(
    candidate, architecture_witness
):
    requirement = "local_unknown"
    low = {"literacy_rate": 0.3, "sitai_context_need_education": True, "net_total_income": -1}
    for role, label, changes, law, school, expected in (
        ("positive", "known_feedback_and_cost", low, True, True, -0.020),
        ("negative", "known_absent_feedback_keeps_cost", low, False, True, 0.005),
        ("unknown", "unknown_law_keeps_both_actions_and_cost", low, None, True, 0.005),
        (
            "unknown",
            "unknown_literacy_keeps_industry_cost",
            {**low, "literacy_rate": None},
            True,
            True,
            0.05,
        ),
        (
            "unknown",
            "unknown_demand_keeps_base_and_cost",
            {**low, "sitai_context_need_education": None},
            False,
            False,
            0.03,
        ),
    ):
        _action_case(
            candidate,
            architecture_witness,
            requirement,
            BALANCE,
            role,
            label,
            changes,
            expected,
            public_school=law,
            schools=school,
        )
    _boundaries(candidate, architecture_witness, requirement, BALANCE)


def test_s1_native_units_and_signed_direction_survive_thresholds_and_native_addition(
    candidate, architecture_witness
):
    requirement = "units_direction"
    baseline = candidate["baseline"]
    assert "+0.1 = +10% higher acceptable debt threshold" in baseline
    assert "+10% stricter budget requirements for government expenses" in baseline
    # .4 is a ratio (40%), not .4 percent; weekly income and administrative
    # balances are tested separately rather than summed across incompatible units.
    for role, label, changes, expected in (
        ("positive", "forty_percent_inclusive_cheap", {"scaled_debt": 0.4}, 0.15),
        ("negative", "above_forty_percent_cost", {"scaled_debt": 0.400001}, 0.05),
        ("unknown", "unknown_ratio_local_cost", {"scaled_debt": None}, 0.05),
        ("negative", "weekly_currency_negative_cost", {"net_total_income": -0.000001}, 0.05),
    ):
        _action_case(
            candidate, architecture_witness, requirement, BALANCE, role, label, changes, expected
        )
    # .15-.10-.025-.025=0; adding commitments -.10+.08 gives -.020.
    # A negative final value favors government spending, the native inverse direction.
    _action_case(
        candidate,
        architecture_witness,
        requirement,
        BALANCE,
        "negative",
        "government_direction_and_original_point_four",
        {"literacy_rate": 0.3, "sitai_context_need_education": True, "net_total_income": -1},
        -0.020,
        public_school=True,
        schools=True,
        native=0.4,
        journal="je_grunderzeit",
    )
    _boundaries(candidate, architecture_witness, requirement, BALANCE)


def test_s1_single_consumer_cap_follows_joint_sum_and_leaves_original_tail(
    candidate, architecture_witness
):
    requirement = "single_cap_native_tail"
    overlay = explicit._overlay(explicit._disk(candidate, NEUTRALITY), NEUTRALITY)
    parsed = parse_text(overlay)
    branch = parsed.root.first("if")
    assert branch is not None
    assert isinstance(branch.value, Block)
    numeric = branch.value.first("add")
    assert numeric is not None
    assert isinstance(numeric.value, Block)
    operations = list(numeric.value.assignments())
    assert all(isinstance(item.value, Scalar) for item in operations[-2:])
    assert [(item.key, cast("Scalar", item.value).text) for item in operations[-2:]] == [
        ("min", "-10"),
        ("max", "10"),
    ]
    assert sum(item.key in {"min", "max"} for item in operations) == 2
    # Independent +8 and +6 must join before one +/-10 clamp. Removing either
    # reason restores its surviving magnitude; unknown war cannot discard +8.
    for role, label, changes, expected in (
        ("positive", "eight_plus_six_then_cap", {"in_default": True, "is_at_war": True}, 10),
        ("negative", "remove_war", {"in_default": True, "is_at_war": False}, 8),
        ("negative", "remove_default", {"in_default": False, "is_at_war": True}, 6),
        ("unknown", "unknown_war_keeps_default", {"in_default": True, "is_at_war": None}, 8),
    ):
        _action_case(
            candidate,
            architecture_witness,
            requirement,
            NEUTRALITY,
            role,
            label,
            changes,
            expected,
            native=50,
        )
    _action_case(
        candidate,
        architecture_witness,
        requirement,
        NEUTRALITY,
        "positive",
        "native_journal_fifty_survives",
        {"in_default": True, "is_at_war": True},
        10,
        native=100,
        journal="je_sick_man_main",
    )
    _boundaries(candidate, architecture_witness, requirement, NEUTRALITY)


def test_s1_independent_pdx_oracle_preserves_argument_identity_and_defense_direction(
    candidate, architecture_witness
):
    requirement = "independent_pdx_witness"
    installed = explicit._disk(candidate, SUPPORT)
    overlay = explicit._overlay(installed, SUPPORT)
    original = SupportObservation(True, True, False, 0, 4, True, True)
    # Hand arithmetic: (0-4)*5 + strongest(25,15)=5. It is neither a
    # same-cause 25+15 stack nor an unsigned defense bonus when attacking.
    for role, label, observed, expected in (
        ("positive", "strongest_security_once", original, 5),
        ("negative", "initiator_reverses_security", replace(original, initiator=True), -45),
        (
            "unknown",
            "unknown_economics_keeps_security",
            replace(original, country_dependence=None),
            25,
        ),
        (
            "negative",
            "wrong_partner_does_not_leak",
            replace(original, commitment=False, neighbor=False),
            -20,
        ),
    ):
        engine = explicit._support_facts(observed)
        if label == "wrong_partner_does_not_leak":
            engine["ROOT"]["sitai_defense_commitment"][(("PARTNER", "scope:enemy_country"),)] = True
            engine["ROOT"]["sitai_neighbor_defense"][
                (("OPPONENT", "scope:country"), ("PARTNER", "scope:enemy_country"))
            ] = True
        reference = candidate["support"].evaluate(observed).value
        actual = pdx_eval.select(overlay, engine)
        assert actual.operation == "add"
        _record(
            architecture_witness,
            requirement,
            SUPPORT,
            role,
            {"case": label, "engine": engine, "observation": asdict(observed)},
            _units("add", expected),
            _units("add", reference),
            _units("add", actual.delta),
        )
    _boundaries(candidate, architecture_witness, requirement, SUPPORT, support=True)
