"""Observed enacted institutions drive bounded feedback, never card eligibility."""

import hashlib
from collections.abc import Mapping
from typing import Any

import pytest

from pdx import config, decision_adapters, decisions
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval
from pdx.textio import normalized_text

pytestmark = pytest.mark.unit
BALANCE = "economic_vs_government_spending_balance"


@pytest.fixture(scope="module")
def model():
    return compiler.load_model()


def _inputs(changes: Mapping[str, object] | None = None):
    values: dict[str, object] = {
        "peace": True,
        "war": False,
        "no_default": True,
        "default": False,
        "no_insurrection": True,
        "ongoing_insurrection": False,
        "legitimacy": 80,
        "stable_legitimacy": True,
        "strong_legitimacy": True,
        "bureaucracy": 1,
        "bureaucracy_positive": True,
        "literacy_low": True,
        "literacy_ready": False,
        "debt_ratio": 0.1,
        "net_surplus": 1,
        "coord_evidence_need_industry": False,
        "coord_need_education": True,
        "current_public_schools": False,
        "schools_present": False,
        "current_traditionalism": False,
    }
    values.update(changes or {})
    engine: dict[str, Any] = {
        "is_ai": True,
        "is_at_war": values["war"],
        "in_default": values["default"],
        "any_insurrection_ongoing": values["ongoing_insurrection"],
        "legitimacy": values["legitimacy"],
        "bureaucracy": values["bureaucracy"],
        "literacy_rate": None
        if values["literacy_low"] is None
        else 0.3
        if values["literacy_low"]
        else 0.8,
        "scaled_debt": values["debt_ratio"],
        "net_total_income": values["net_surplus"],
        "sitai_context_evidence_need_industry": values["coord_evidence_need_industry"],
        "sitai_context_need_education": values["coord_need_education"],
        "has_law_or_variant": {
            (("argument", "law_type:law_public_schools"),): values["current_public_schools"],
            (("argument", "law_type:law_traditionalism"),): values["current_traditionalism"],
        },
        "has_institution": {(("argument", "institution_schools"),): values["schools_present"]},
    }
    return values, engine


def _assert_delta(model, field, changes, expected, *, enabled=None):
    values, engine = _inputs(changes)
    result = compiler.evaluate_actions(model, values, is_ai=True, enabled_consumer_fields=enabled)
    assert result.get(field, ("", 0.0))[1] == pytest.approx(expected)
    actual = pdx_eval.select(
        compiler.strategy_overlay(model, enabled_consumer_fields=enabled)[field], {"ROOT": engine}
    )
    assert actual.delta == pytest.approx(expected)
    assert actual.operation == "add"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 0.025),
        ({"current_public_schools": True}, 0.025),
        ({"schools_present": True}, 0.025),
        ({"current_public_schools": True, "schools_present": True}, 0.0),
        ({"current_public_schools": None, "schools_present": True}, 0.025),
        ({"current_public_schools": True, "schools_present": None}, 0.025),
        ({"bureaucracy_positive": False, "bureaucracy": 0}, 0.025),
    ],
)
def test_enacted_public_school_and_institution_are_required_for_education_feedback(
    model, changes, expected
):
    # Industrial +.15; existing low-literacy education -.10 and demand -.025.
    # The observed public-school feedback adds -.025 only to education's direction.
    _assert_delta(model, BALANCE, changes, expected)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 0.15),
        ({"current_public_schools": True, "schools_present": True}, 0.175),
        ({"current_public_schools": None, "schools_present": True}, 0.15),
        ({"current_public_schools": True, "schools_present": None}, 0.15),
    ],
)
def test_observed_literacy_saturation_exits_education_and_informs_industry(
    model, changes, expected
):
    _assert_delta(
        model,
        BALANCE,
        {"literacy_low": False, "literacy_ready": True, "coord_need_education": False, **changes},
        expected,
    )


def test_generic_reform_tempo_never_claims_an_industry_law_has_completed(model):
    _assert_delta(model, "change_law_chance", {}, 0.5)
    _assert_delta(model, "change_law_chance", {"current_traditionalism": True}, 0.5)
    _assert_delta(model, "change_law_chance", {"current_traditionalism": None}, 0.5)
    _assert_delta(
        model, "change_law_chance", {"bureaucracy_positive": False, "bureaucracy": -1}, 0.5
    )


def test_default_cannot_weaken_wartime_diplomatic_restraint(model):
    _assert_delta(
        model,
        "recklessness",
        {"war": True, "peace": False, "default": True, "no_default": False},
        -4.0,
    )


def test_retired_preference_edges_leave_independent_pressure_and_reversibility(model):
    # Distinct default/war neutrality reasons still join and reach the same cap.
    _assert_delta(
        model,
        "diplomatic_play_neutrality",
        {"war": True, "peace": False, "default": True, "no_default": False},
        10.0,
    )
    _assert_delta(model, "max_regressiveness", {"default": True, "no_default": False}, 5.0)


def test_unknown_literacy_drops_education_feedback_without_blocking_industry(model):
    _assert_delta(
        model,
        BALANCE,
        {
            "current_public_schools": True,
            "schools_present": True,
            "literacy_low": None,
            "literacy_ready": None,
            "coord_need_education": None,
        },
        0.15,
    )


def test_unknown_education_feedback_never_blocks_independent_source_or_cost(model):
    # The existing shared commitment is .10-.08=.02 toward industrial allocation.
    _assert_delta(
        model,
        BALANCE,
        {"current_public_schools": None, "schools_present": True, "net_surplus": -1},
        0.005,
    )
    _assert_delta(
        model,
        BALANCE,
        {"current_public_schools": True, "schools_present": True, "net_surplus": -1},
        -0.020,
    )


def test_other_consumer_switch_cannot_hide_independent_observed_school_feedback(model):
    # The target's card does not count as completion; actual school facts do.
    _assert_delta(
        model,
        BALANCE,
        {"current_public_schools": True, "schools_present": True},
        0.0,
        enabled={BALANCE},
    )


def _tree(item):
    if isinstance(item, Scalar):
        return item.unquoted
    if isinstance(item, Assignment):
        return item.key, item.op, _tree(item.value)
    assert isinstance(item, Block)
    return tuple(_tree(child) for child in item.items)


def test_actual_default_patch_preserves_native_tail_player_and_switches(model):
    baseline = decisions.baseline_path().read_text(encoding="utf-8")
    overlay = compiler.strategy_overlay(model)
    profile = decisions.load_extensions(profile="release")
    patched = decisions.patch_default(baseline, decisions.load(), profile, action_overlay=overlay)
    parsed = parse_text(patched)
    assert not parsed.errors
    values, engine = _inputs({"current_public_schools": True, "schools_present": True})
    block = parsed.root.first("ai_strategy_default")
    assert block is not None
    assert isinstance(block.value, Block)
    actual = block.value.first(BALANCE)
    assert actual is not None
    assert isinstance(actual.value, Block)
    # Compare the same extension profile so unrelated release additions are
    # part of the protected tail, rather than accidentally treated as vanilla.
    without_actions = decisions.patch_default(baseline, decisions.load(), profile)
    original = parse_text(without_actions).root.first("ai_strategy_default")
    assert original is not None
    assert isinstance(original.value, Block)
    native = original.value.first(BALANCE)
    assert native is not None
    assert isinstance(native.value, Block)
    # The final inserted if owns the joint contribution; every native node remains.
    assert _tree(Block(actual.value.items[:-1])) == _tree(native.value)
    assert _tree(actual.value.items[-1]) == _tree(parse_text(overlay[BALANCE]).root.items[-1])
    assert pdx_eval.select(overlay[BALANCE], {"ROOT": engine}).delta == pytest.approx(0.0)
    assert compiler.evaluate_actions(model, values, is_ai=False) == {}
    assert (
        pdx_eval.select(overlay[BALANCE], {"ROOT": {**engine, "is_ai": False}}).fallback
        == "vanilla"
    )
    assert compiler.strategy_overlay(model, enabled_consumer_fields=set()) == {}


@pytest.mark.integration
def test_observed_school_readers_match_locked_real_law_and_root_scope(model):
    adapters = decision_adapters.load()
    readers = {
        reader.key: reader
        for _source, policy in adapters.policies
        for reader in policy.readers
        if reader.key in {"current_public_schools", "schools_present", "current_traditionalism"}
    }
    assert readers["current_public_schools"].argument == "law_type:law_public_schools"
    assert readers["schools_present"].argument == "institution_schools"
    assert all(reader.scope == "root" and not reader.path for reader in readers.values())
    source = "common/laws/01_education_system.txt"
    raw = (config.GAME / source).read_text(encoding="utf-8-sig")
    assert (
        hashlib.sha256(normalized_text(raw).encode()).hexdigest() == dict(adapters.sources)[source]
    )
    law = parse_text(raw).root.first("law_public_schools")
    assert law is not None
    assert isinstance(law.value, Block)
    institution = law.value.first("institution")
    assert institution is not None
    assert isinstance(institution.value, Scalar)
    assert institution.value.unquoted == "institution_schools"
    modifiers = law.value.first("institution_modifier")
    assert modifiers is not None
    assert isinstance(modifiers.value, Block)
    education = modifiers.value.first("state_education_access_add")
    assert education is not None
    assert isinstance(education.value, Scalar)
    assert float(education.value.unquoted) == 0.125
