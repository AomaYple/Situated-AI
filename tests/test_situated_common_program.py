"""Common scalar execution, with handwritten net values and real PDX witnesses."""

import hashlib
from dataclasses import replace

import pytest

from pdx import decision_rules
from pdx.situated import compiler, decision_ir, pdx_eval, programs
from pdx.situated.schema import ConsumerContract, CostPredicate, EvidenceSpec, RankTerm

pytestmark = pytest.mark.unit


def _cards():
    consumer = ConsumerContract("c", "field_c", "test", 5.0, 3, "retain")
    high = decision_ir.ConsumerDecisionIR(
        "high",
        "test",
        "c",
        "field_c",
        "add",
        (),
        (),
        (),
        (),
        5.0,
        5.0,
        "retain",
        "vanilla",
        (),
        base=8.0,
        requires_all=("high",),
        variant_group="choice",
        variant_priority=2,
        commitment=10.0,
        commitment_when=(CostPredicate("pressure", ">", 0.4, "ratio"),),
    )
    low = replace(
        high,
        action_id="low",
        base=0.3,
        requires_all=("low",),
        variant_priority=1,
        commitment=0.0,
        commitment_when=(),
    )
    independent = replace(
        low,
        action_id="independent",
        base=2.0,
        requires_all=("independent",),
        variant_group="",
        variant_priority=0,
    )
    rows = (high, low, independent)
    facts = (
        *(
            EvidenceSpec(
                name,
                "test",
                "fixture",
                "root",
                "boolean",
                "flag",
                "consumer",
                "vanilla",
                f"{name} = yes",
            )
            for name in ("high", "low", "independent")
        ),
        EvidenceSpec(
            "pressure",
            "test",
            "fixture",
            "root",
            "number",
            "ratio",
            "consumer",
            "vanilla",
            "pressure",
            0.0,
            1.0,
        ),
    )
    writers = tuple(
        decision_ir.WriterDecisionIR(
            f"card_{row.action_id}",
            "action_card",
            "mod/decisions/actions.toml",
            row.action_id,
            "c",
            "field_c",
            "root",
            "none",
            "add",
            "retain",
            "situated_kernel",
            action=row,
        )
        for row in rows
    )
    return compiler.SituatedModel(
        facts,
        (consumer,),
        (),
        (),
        {},
        decision_ir=rows,
        consumer_ir=decision_ir.ConsumerIRBundle(1, rows, writers),
    )


def _rules():
    readers = tuple(
        decision_rules.Reader(name, name, "root", "boolean", "boolean")
        for name in ("high", "low", "cost")
    )
    rules = tuple(
        decision_rules.Rule(
            name,
            "test",
            ("field",),
            index,
            amount,
            (decision_rules.Predicate(name, "=", True),),
            "manual",
            "absent",
            operation="add",
        )
        for index, (name, amount) in enumerate((("high", 8.0), ("low", 0.3), ("cost", -6.0)))
    )
    return programs.enable(
        decision_rules.RuleSet(
            readers, rules, hashlib.sha256(b"").hexdigest(), "0" * 64, frozenset({"test"})
        ),
        source="fixture",
    )


@pytest.mark.parametrize(
    ("high", "pressure", "expected"),
    [(True, 1.0, 0.0), (True, None, 0.0), (True, 0.0, 5.0), (None, 1.0, 2.3)],
)
def test_dynamic_variant_costs_and_independent_terms_share_the_single_final_clamp(
    high,
    pressure,
    expected,
):
    # High variant 8 - 10 plus independent 2 = 0. Clamping either the high
    # base or an intermediate total first produces a different answer.
    model = _cards()
    values = {"high": high, "low": True, "independent": True, "pressure": pressure}
    reference = compiler.evaluate_actions(model, values, is_ai=True)
    assert reference.get("field_c", ("", 0.0))[1] == pytest.approx(expected)
    text = compiler.strategy_overlay(model)["field_c"]
    result = pdx_eval.select(text, {**values, "is_ai": True})
    assert result.delta == pytest.approx(expected)
    assert text.count("min =") == text.count("max =") == 1
    assert all(f"# ACTION {name} [test]" in text for name in ("high", "low", "independent"))


def test_both_production_entrypoints_use_the_same_scalar_evaluator_and_lowerer(monkeypatch):
    evaluations = []
    renderings = []
    evaluate = programs.evaluate_scalar
    render = programs.render_scalar

    def observed_evaluate(program, guards):
        evaluations.append(program)
        return evaluate(program, guards)

    def observed_render(program, guards, **kwargs):
        renderings.append(program)
        return render(program, guards, **kwargs)

    monkeypatch.setattr(programs, "evaluate_scalar", observed_evaluate)
    monkeypatch.setattr(programs, "render_scalar", observed_render)
    policy = _rules()
    assert decision_rules.evaluate_ir(
        policy, {"high": True, "low": True, "cost": True}, is_ai=True
    )["field"][1] == pytest.approx(2.0)
    text = programs.render(
        policy.consumer_programs[0],
        guards={name: f"{name} = yes" for name in ("high", "low", "cost")},
        ai_guard="is_ai = yes",
        descriptions={},
        producer_markers={},
    )
    assert pdx_eval.select(
        text, {"high": True, "low": True, "cost": True, "is_ai": True}
    ).delta == pytest.approx(2.0)
    model = _cards()
    compiler.evaluate_actions(model, {"high": None, "low": True, "independent": True}, is_ai=True)
    compiler.strategy_overlay(model)
    assert len(evaluations) == len(renderings) == 2
    assert all(
        isinstance(program, programs.ScalarProgram) for program in (*evaluations, *renderings)
    )


def test_unclamped_compatibility_value_uses_common_effects_without_qualification():
    row = replace(_cards().decision_ir[0], rank_terms=(RankTerm("need", "goal", 1, "flag", 2.0),))
    # The compatibility entry deliberately computes the row value without
    # claiming that its absent qualification is satisfied: 8 + 2 + 3 - 10 = 3.
    assert compiler._row_delta(
        row, {"need": True, "pressure": None}, complement=3.0
    ) == pytest.approx(3.0)
