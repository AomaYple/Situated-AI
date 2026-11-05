"""Exact source-decimal bounds at the sixteen logged PDX failure consumers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from pdx import decision_adapters, decision_rules
from pdx.situated import programs
from pdx.situated.relations import RuleRelationProjection

pytestmark = pytest.mark.unit
TECH = "common/technology/technologies/"
INFO = "mod/decisions/information.toml"


@pytest.fixture(scope="module")
def production_programs():
    policies = ((INFO, decision_rules.load()), *decision_adapters.load().policies)
    return {
        (source, ".".join(program.field)): program
        for source, policy in policies
        for program in programs.enable(policy, source=source).consumer_programs
    }


@pytest.mark.parametrize(
    ("source", "field", "bound", "expected"),
    [
        (TECH + "10_production.txt", "steel_railway_cars.ai_weight", "max", "1.44"),
        (TECH + "20_military.txt", "field_works.ai_weight", "max", "1.33"),
        (TECH + "20_military.txt", "power_of_the_purse.ai_weight", "max", "1.3"),
        (TECH + "20_military.txt", "concrete_dockyards.ai_weight", "max", "1.42"),
        (TECH + "30_society.txt", "urbanization.ai_weight", "max", "1.18"),
        (TECH + "30_society.txt", "urban_planning.ai_weight", "max", "1.18"),
        (TECH + "30_society.txt", "modern_sewerage.ai_weight", "max", "1.2"),
        (TECH + "30_society.txt", "dialectics.ai_weight", "max", "1.24"),
        (TECH + "30_society.txt", "realism.ai_weight", "max", "1.16"),
        (TECH + "30_society.txt", "steel_frame_buildings.ai_weight", "max", "1.18"),
        (TECH + "30_society.txt", "camera.ai_weight", "max", "1.16"),
        (TECH + "30_society.txt", "elevator.ai_weight", "max", "1.18"),
        (TECH + "30_society.txt", "film.ai_weight", "max", "1.16"),
        (TECH + "30_society.txt", "multilateral_alliances.ai_weight", "max", "1.16"),
        # This consumer acquired another genuine cost since the old package:
        # its current exact floor is .65, not the old package's .7.
        (INFO, "institution_scores.institution_social_security", "min", "0.65"),
        (INFO, "state_value", "min", "0.54"),
    ],
)
def test_logged_consumers_render_hand_calculated_exact_source_bounds(
    production_programs, source, field, bound, expected
):
    program = production_programs[source, field]
    rendered = programs.render(
        program,
        guards={item.action_id: "always = yes" for item in program.variants},
        ai_guard="is_ai = yes",
        descriptions={},
        producer_markers={},
        cost_guards={item.action_id: ("always = yes", "always = no") for item in program.variants},
    )
    assert f"\t\t\t{bound} = {expected}\n" in rendered
    actual = program.lower if bound == "min" else program.upper
    assert programs.numeric_literal(actual) == expected


def _independent(values, *, operation="multiply"):
    rules = tuple(
        decision_rules.Rule(
            f"rule_{index}",
            "test",
            ("field",),
            index,
            value,
            (),
            "source",
            "counterexample",
            operation=operation,
            contribution_group=f"cause_{index}",
        )
        for index, value in enumerate(values)
    )
    policy = decision_rules.RuleSet(
        (), rules, hashlib.sha256(b"fixture").hexdigest(), "0" * 64, frozenset({"test"})
    )
    return programs.enable(policy, source="fixture")


@pytest.mark.parametrize(
    ("values", "lower", "upper"),
    [((1.2, 1.1), "1", "1.3"), ((0.9, 0.8), "0.7", "1"), ((0.82, 0.72), "0.54", "1")],
)
def test_independent_decimal_limits_do_not_embed_binary_addition_noise(values, lower, upper):
    policy = _independent(values)
    scalar = programs.rule_scalar(policy.consumer_programs[0])
    assert programs.numeric_literal(scalar.lower) == lower
    assert programs.numeric_literal(scalar.upper) == upper
    # The persisted policy contract keeps its established JSON number shape.
    json.dumps(programs.contract(policy), allow_nan=False)


def test_bound_preserves_genuine_tiny_independent_source_contribution():
    policy = _independent((1.2345678901234567e-10, 1e-30), operation="add")
    scalar = programs.rule_scalar(policy.consumer_programs[0])
    assert programs.numeric_literal(scalar.upper) == "0.000000000123456789012345680001"


def test_exact_bound_precision_grows_with_source_exponents_without_rounding():
    policy = _independent((1.0, 1e-100), operation="add")
    scalar = programs.rule_scalar(policy.consumer_programs[0])
    assert programs.numeric_literal(scalar.upper) == "1." + "0" * 99 + "1"


def test_relation_bounds_use_exact_source_deltas_and_strongest_same_cause():
    policy = _independent((1.1,))
    relation = RuleRelationProjection(
        "fixture",
        "rule_0",
        "writer",
        ("field",),
        "multiply",
        "port",
        "cause",
        0.1,
        ("source",),
        "test",
        "multiplier_delta",
        "first",
        "second",
    )
    program = replace(
        policy.consumer_programs[0],
        relations=(
            relation,
            replace(relation, amount=0.08),
            replace(relation, cause_id="other", amount=0.02),
        ),
    )
    scalar = programs.rule_scalar(program)
    assert programs.numeric_literal(scalar.upper) == "1.22"
    rendered = programs.render(
        program,
        guards={"rule_0": "always = yes"},
        ai_guard="is_ai = yes",
        descriptions={},
        producer_markers={},
        relation_guards={item.guard_id: "always = yes" for item in program.relations},
    )
    assert "\t\t\tmax = 1.22\n" in rendered


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1e-30, "0.000000000000000000000000000001"),
        (Decimal("1E+40"), "1" + "0" * 40),
        (
            Decimal("1.23456789012345678901234567890123456789"),
            "1.23456789012345678901234567890123456789",
        ),
        (Decimal("-0.000000000000000000000000000123"), "-0.000000000000000000000000000123"),
    ],
)
def test_literal_preserves_real_precision_and_expands_exponents(value, expected):
    assert programs.numeric_literal(value) == expected


@pytest.mark.parametrize(
    "value", [float("inf"), -float("inf"), float("nan"), Decimal("Infinity"), Decimal("NaN")]
)
def test_nonfinite_source_values_stay_rejected(value):
    with pytest.raises(ValueError, match="有限"):
        programs.numeric_literal(value)
