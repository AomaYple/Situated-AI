"""Engineering witnesses for the intentional current negotiation migration.

PDX interpretation here does not establish engine syntax or runtime behavior;
the independently reviewed native evidence remains a separate prerequisite.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from test_remaining_joint_consumers import (
    DEFAULT,
    NEGOTIATION,
    _assignment,
    _block,
    _native_number,
    _overlay,
    _render,
    _values,
)
from test_remaining_joint_consumers import production as production  # noqa: PLC0414
from test_situated_joint_witnesses import _facts

from pdx import decision_interfaces, decision_rules, negotiation_context
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("amenability", "politics", "expected"),
    [
        (0.5, {}, 0.25),
        (0.00001, {}, 0.25),
        (1, {}, 0.25),
        (0, {}, 0),
        (-0.00001, {}, 0),
        (1.00001, {}, 0),
        (4294967295 / 100000, {}, 0),
        (None, {}, 0),
        (0.5, {"legitimacy": None}, 0.1),
        (0.5, {"legitimacy": 49.999}, 0.1),
        (0.5, {"insurrection": True}, 0.1),
        (0.5, {"radical_share": 0.24999}, 0),
        (0.5, {"radical_share": None}, 0),
        (0.5, {"candidate_ig_clout": None, "candidate_ig_approval": None}, 0.25),
    ],
)
def test_actual_scalar_window_root_pressure_and_maximum_tier(
    production, amenability, politics, expected
):
    policies, generated, _, _ = production
    policy = policies[DEFAULT]
    values = _values(
        policy,
        {
            "negotiation_amenability": amenability,
            "radical_share": 0.25,
            "legitimacy": 50,
            "insurrection": False,
            **politics,
        },
    )
    result = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert result.get(NEGOTIATION, ("", 0))[1] == pytest.approx(expected)
    script = _overlay(generated[DEFAULT], NEGOTIATION)
    facts = _facts(policy, values)
    # An object/foreign decoy never replaces the named number in this frame.
    facts["scope:interest_group"] = {"ig_clout": 1, "ig_approval": -100}
    facts["scope:target_country"] = {"scope:amenability": 0.5}
    assert pdx_eval.select(script, facts).delta == pytest.approx(expected)
    root = _block(parse_text(production[2][DEFAULT]).root, "ai_strategy_default")
    cap = _assignment(_block(root, "negotiation_chance"), "max")
    assert _native_number(0, script + "\n" + _render(cap), facts) == pytest.approx(expected)
    assert _native_number(1, script + "\n" + _render(cap), facts) == 1
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=frozenset()) == {}


@pytest.mark.parametrize("fault", ["unit", "scope", "path", "engine", "actor", "field", "binding"])
def test_scalar_reader_never_grants_general_named_value_access(production, fault):
    policies, _, native, _model = production
    policy = policies[DEFAULT]
    reader = next(r for r in policy.readers if r.key == negotiation_context.KEY)
    if fault in {"unit", "scope", "path", "engine", "actor"}:
        changes: dict[str, dict[str, Any]] = {
            "unit": {"unit": "ratio"},
            "scope": {"scope": "interest_group"},
            "path": {"path": ("owner",)},
            "engine": {"engine": "scope:advance_chance"},
        }
        with pytest.raises(ValueError, match="谈判"):
            decision_interfaces.reader_scope(
                replace(reader, **changes.get(fault, {})),
                ("owner",) if fault == "actor" else (),
            )
        return
    context = compiler.evaluation_contexts(native[DEFAULT])["negotiation_chance"]
    if fault == "binding":
        context = replace(
            context,
            auxiliary_scopes=tuple(b for b in context.auxiliary_scopes if b.name != "amenability"),
        )
    with pytest.raises(ValueError):
        compiler.validate_context_readers(
            "interest_group_government_weight" if fault == "field" else "negotiation_chance",
            context,
            {reader.key: reader},
            (),
            input_keys=(reader.key,),
        )


def test_reviewed_frame_and_ir_exclude_named_ig_but_keep_government_binding(production):
    _, _, native, model = production
    contexts = compiler.evaluation_contexts(native[DEFAULT])
    context = contexts["negotiation_chance"]
    assert context.actor_scope is not None
    assert {b.name for b in (context.actor_scope, *context.targets, *context.auxiliary_scopes)} == {
        "root",
        "law",
        "amenability",
        "advance_chance",
        "stall_chance",
    }
    assert "interest_group" in {
        b.name for b in contexts["interest_group_government_weight"].targets
    }
    writer = next(
        w
        for w in model.consumer_ir.writers
        if w.definition == "lj08_negotiation_local_political_capacity"
    )
    assert writer.operation == "add"
    assert (
        negotiation_context.KEY,
        "amenability",
        "scalar",
        "auxiliary",
    ) in writer.reader_context_bindings
    assert negotiation_context.snapshot()


def test_inclusive_native_raw_draw_scale_is_not_a_percent_or_terminal_zero():
    def accepted(raw):
        return [draw for draw in range(100000) if draw * 100 <= raw]

    assert accepted(0) == [0]
    assert len(accepted(10000)) == 101
    assert len(accepted(25000)) == 251
    assert len(accepted(100000)) == 1001
    assert accepted(-1) == []
