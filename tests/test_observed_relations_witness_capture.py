"""Six explicit executed R8 roles for the A2 evidence capture path."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdx import decisions
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval
from pdx.situated.native_treatments import _digest, _resolve

pytest_plugins = ("tools.ci.architecture_witness_capture",)
pytestmark = pytest.mark.unit
FIELD = "economic_vs_government_spending_balance"
GENERATED = "mod/common/ai_strategies/00_default_strategy.txt"
ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = [
    "mod/decisions/relations.toml",
    "mod/decisions/actions.toml",
    "mod/decisions/action_layers.toml",
    "mod/decisions/adapters.toml",
    "mod/decisions/facts.toml",
    "mod/decisions/fiscal.toml",
    "mod/decisions/capacities.toml",
    "mod/decisions/country_state.toml",
    "src/pdx/situated/compiler.py",
]
CONSUMERS = [{"path": GENERATED, "definition": "ai_strategy_default", "field": FIELD}]


def test_witness_sources_bind_existing_current_production():
    """A retired source must fail ordinary regression before formal capture."""
    for name in PRODUCTION:
        assert (ROOT / name).is_file(), f"witness production source unavailable: {name}"
    assert "mod/decisions/country_state.toml" in PRODUCTION


@pytest.fixture(scope="module")
def candidate():
    model = compiler.load_model()
    raw = (ROOT / GENERATED).read_text(encoding="utf-8")
    actual = pdx_eval.marked_block(raw, "joint_economic_balance", path=GENERATED)
    overlay = compiler.strategy_overlay(model)[FIELD]
    # The executed PDX is extracted from the actual installed output artifact.
    assert _digest(parse_text(actual).root) == _digest(parse_text(overlay).root)
    return model, actual, raw


def _observations(school):
    values = {
        "no_default": True,
        "default": False,
        "literacy_low": True,
        "literacy_ready": False,
        "legitimacy": 80,
        "bureaucracy": 1,
        "debt_ratio": 0.1,
        "net_surplus": 1,
        "coord_evidence_need_industry": False,
        "coord_need_education": True,
        "current_public_schools": school,
        "schools_present": True,
    }
    engine = {
        "ROOT": {
            "is_ai": True,
            "in_default": False,
            "literacy_rate": 0.3,
            "legitimacy": 80,
            "bureaucracy": 1,
            "scaled_debt": 0.1,
            "net_total_income": 1,
            "sitai_context_evidence_need_industry": False,
            "sitai_context_need_education": True,
            "has_law_or_variant": {(("argument", "law_type:law_public_schools"),): school},
            "has_institution": {(("argument", "institution_schools"),): True},
        }
    }
    return values, engine


@pytest.mark.parametrize(
    ("role", "school", "expected_delta"),
    [("positive", True, 0.0), ("negative", False, 0.025), ("unknown", None, 0.025)],
)
def test_actual_observed_school_feedback_role(
    candidate, architecture_witness, role, school, expected_delta
):
    model, actual, _raw = candidate
    values, engine = _observations(school)
    reference = compiler.evaluate_actions(model, values, is_ai=True)[FIELD][1]
    generated = pdx_eval.select(actual, engine).delta
    assert reference == pytest.approx(expected_delta)
    assert generated == pytest.approx(expected_delta)
    # This field's authored increments are integral thousandths. Check both raw
    # floats before recording that explicit unit, so IEEE addition noise cannot
    # turn JSON's exact identity check into a false semantic difference.
    reference_units = round(reference * 1000)
    generated_units = round(generated * 1000)
    assert reference * 1000 == pytest.approx(reference_units, rel=0, abs=1e-10)
    assert generated * 1000 == pytest.approx(generated_units, rel=0, abs=1e-10)
    architecture_witness(
        case_id=f"r8.{role}",
        role=role,
        input={**values, "output_unit": "balance_delta_thousandths"},
        expected={"delta_thousandths": round(expected_delta * 1000)},
        reference={"delta_thousandths": reference_units},
        generated={"delta_thousandths": generated_units},
        production=PRODUCTION,
        consumers=CONSUMERS,
    )


def test_actual_observed_feedback_disabled_role(candidate, architecture_witness):
    model, _actual, _raw = candidate
    values, _engine = _observations(True)
    reference = compiler.evaluate_actions(model, values, is_ai=True, enabled_consumer_fields=set())
    overlay = compiler.strategy_overlay(model, enabled_consumer_fields=set())
    assert reference == {}
    assert overlay == {}
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    profile = decisions.load_extensions(profile="release")
    patched = decisions.patch_default(baseline, decisions.load(), profile, action_overlay=overlay)
    without = decisions.patch_default(baseline, decisions.load(), profile)
    generated = _digest(parse_text(patched).root) == _digest(parse_text(without).root)
    assert generated
    architecture_witness(
        case_id="r8.disabled",
        role="disabled",
        input={**values, "enabled_consumer_fields": []},
        expected={"contributions": {}, "native_profile_retained": True},
        reference={"contributions": reference, "native_profile_retained": not overlay},
        generated={"contributions": overlay, "native_profile_retained": generated},
        production=PRODUCTION,
        consumers=CONSUMERS,
    )


def test_actual_observed_feedback_player_role(candidate, architecture_witness):
    model, actual, _raw = candidate
    values, engine = _observations(True)
    engine["ROOT"]["is_ai"] = False
    reference = compiler.evaluate_actions(model, values, is_ai=False)
    generated = pdx_eval.select(actual, engine)
    assert reference == {}
    assert generated.delta == 0
    assert generated.fallback == "vanilla"
    architecture_witness(
        case_id="r8.player",
        role="player",
        input={**values, "is_ai": False},
        expected={"delta": 0.0, "explicit": False},
        reference={"delta": reference.get(FIELD, ("", 0.0))[1], "explicit": bool(reference)},
        generated={"delta": generated.delta, "explicit": generated.operation is not None},
        production=PRODUCTION,
        consumers=CONSUMERS,
    )


def test_actual_observed_feedback_native_tail_role(candidate, architecture_witness):
    model, _actual, raw = candidate
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    profile = decisions.load_extensions(profile="release")
    plain = baseline
    overlay = compiler.strategy_overlay(model)
    patched = decisions.patch_default(
        baseline,
        decisions.load(),
        profile,
        action_overlay=overlay,
        suppress_fields=frozenset(overlay),
    )
    original, state = _resolve(parse_text(plain).root, "ai_strategy_default", FIELD)
    actual, generated_state = _resolve(parse_text(raw).root, "ai_strategy_default", FIELD)
    reference, reference_state = _resolve(parse_text(patched).root, "ai_strategy_default", FIELD)
    assert state == generated_state == reference_state == "found"
    assert original is not None
    assert isinstance(original.value, Block)
    assert actual is not None
    assert isinstance(actual.value, Block)
    assert reference is not None
    assert isinstance(reference.value, Block)
    expected = {"native_tail_ast": _digest(original.value)}
    reference_result = {"native_tail_ast": _digest(Block(reference.value.items[:-1]))}
    generated_result = {"native_tail_ast": _digest(Block(actual.value.items[:-1]))}
    assert expected == reference_result == generated_result
    architecture_witness(
        case_id="r8.native_tail",
        role="native_tail",
        input={"profile": "release", "field": FIELD, "action_contribution_removed": True},
        expected=expected,
        reference=reference_result,
        generated=generated_result,
        production=[*PRODUCTION, "src/pdx/decisions.py"],
        consumers=CONSUMERS,
    )
