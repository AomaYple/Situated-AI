"""Independent administrative, fiscal, political and recovery costs must join."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from _frozen_reader_words import frozen_reader_words
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs
from pdx.situated.native_treatments import _digest

SOURCE = "common/ai_strategies/00_default_strategy.txt"
COLONIAL = "ai_strategy_default.institution_scores.institution_colonial_affairs"
CONQUEST = "ai_strategy_default.strategic_region_stance_type_scores.stance_conquer_region"
CRISIS = {"legitimacy": 20, "insurrection": True, "radical_share": 0.3}


@pytest.fixture(scope="module")
def production():
    source = dict(decision_adapters.load().policies)[SOURCE]
    rules = tuple(r for r in source.rules if ".".join(r.field) in {COLONIAL, CONQUEST})
    assert len(rules) == 5
    keys = {key for rule in rules for key in rule.input_keys()}
    policy = programs.enable(
        replace(
            source,
            rules=rules,
            readers=tuple(r for r in source.readers if r.key in keys),
            enabled_domains=frozenset(r.domain for r in rules),
            semantic_ir=(),
            consumer_programs=(),
        ),
        source=SOURCE,
    )
    native = compiler.BASELINE.read_text(encoding="utf-8")
    patched = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        reader_words=frozen_reader_words(native),
        country_policy=country_state.load(),
    )
    return policy, native, patched


def _values(changes):
    return {
        "default": False,
        "war": False,
        "bureaucracy": 0,
        "legitimacy": 60,
        "insurrection": False,
        "radical_share": 0,
        "coord_evidence_need_reconstruction": False,
        **changes,
    }


def _overlay(text, field):
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    return "\n".join(text[begin:end].splitlines()[1:])


@pytest.mark.parametrize(
    ("field", "changes", "expected"),
    [
        (COLONIAL, {}, 1.0),
        (COLONIAL, {"bureaucracy": -1}, 0.8),
        (COLONIAL, {"default": True}, 0.75),
        (COLONIAL, {"default": True, "bureaucracy": -1}, 0.55),
        (COLONIAL, {"default": True, "bureaucracy": None}, 0.75),
        (COLONIAL, {"default": None, "bureaucracy": -1}, 0.8),
        (CONQUEST, {}, 0.0),
        (CONQUEST, CRISIS, -5.0),
        (CONQUEST, {"default": True}, -5.0),
        (CONQUEST, {**CRISIS, "default": True}, -10.0),
        (CONQUEST, {**CRISIS, "default": None}, -5.0),
        (CONQUEST, {"coord_evidence_need_reconstruction": True}, -4.0),
        (CONQUEST, {**CRISIS, "coord_evidence_need_reconstruction": True}, -9.0),
        (
            CONQUEST,
            {**CRISIS, "default": True, "coord_evidence_need_reconstruction": True},
            -14.0,
        ),
        (CONQUEST, {**CRISIS, "war": True, "coord_evidence_need_reconstruction": True}, -4.0),
    ],
)
def test_independent_costs_match_hand_calculation_and_actual_pdx(
    production, field, changes, expected
):
    policy, _native, patched = production
    values = _values(changes)
    neutral = 1.0 if field == COLONIAL else 0.0
    result = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    observed = pdx_eval.select(_overlay(patched, field), _facts(policy, values))
    assert (result[1] if result else neutral) == pytest.approx(expected)
    assert (observed.delta if observed.operation else neutral) == pytest.approx(expected)


def test_independent_costs_keep_player_disabled_and_complete_native_tail(production):
    policy, native, patched = production
    values = _values(
        {**CRISIS, "default": True, "bureaucracy": -1, "coord_evidence_need_reconstruction": True}
    )
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.patch(
            native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
        )
        == native
    )
    for field in (COLONIAL, CONQUEST):
        assert (
            pdx_eval.select(_overlay(patched, field), _facts(policy, values, is_ai=False)).operation
            is None
        )
    # Remove only the bounded suffixes and compare the complete native AST;
    # insertion may reindent a closing brace without changing native semantics.
    restored = re.sub(
        r"\n[ \t]*# SITAI BEGIN information:[^\n]+\n.*?[ \t]*# SITAI END information:[^\n]+\n",
        "\n",
        patched,
        flags=re.DOTALL,
    )
    before, after = parse_text(native), parse_text(restored)
    assert not before.errors
    assert not after.errors
    assert _digest(after.root) == _digest(before.root)
