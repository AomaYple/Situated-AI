"""D5：观测关系、局部成本与联合消费者的独立 PDX 手写反例。"""

from dataclasses import replace
from typing import cast

import pytest

from pdx.situated import compiler, decision_ir, pdx_eval
from pdx.situated import schema as situated_schema
from pdx.situated.goals import Goal
from pdx.situated.schema import ConsumerContract, EvidenceSpec, Relation, RelationKind

pytestmark = pytest.mark.unit


def _native_plus_actions(model, values, *, is_ai):
    """Explicit-action reference plus the handwritten native additive value 10.

    This fixture deliberately tests the consumer boundary; it does not construct
    a fake production legacy binding or call compile_policy on synthetic writers.
    """
    actual = compiler.evaluate_actions(model, values, is_ai=is_ai)
    return {"field_a": ("native", 10.0 + actual.get("field_a", ("", 0.0))[1])} if is_ai else {}


def _with_decisions(model, **changes):
    """同步参考行、生产 bundle 和真实 card writer，避免夹具走匿名卡旁路。"""
    updated = replace(model, **changes)
    bundle = updated.consumer_ir
    assert bundle is not None
    consumers = {consumer.id: consumer for consumer in updated.consumers}
    cards = tuple(
        decision_ir.WriterDecisionIR(
            writer_id=f"card_{row.action_id}",
            kind="action_card",
            source="mod/decisions/actions.toml",
            definition=row.action_id,
            consumer_id=row.consumer_id,
            field=row.field,
            actor=consumers[row.consumer_id].scope,
            target="none",
            operation=row.operation,
            vanilla_tail=row.vanilla_tail,
            owner=consumers[row.consumer_id].owner,
            action=row,
        )
        for row in updated.decision_ir
    )
    return replace(
        updated,
        consumer_ir=replace(
            bundle,
            actions=updated.decision_ir,
            writers=(*tuple(w for w in bundle.writers if w.kind != "action_card"), *cards),
        ),
    )


def _relation_model(*, cross_consumer: bool, kind: str = "complements"):
    consumer = ConsumerContract("c", "field_a", "test", 5.0, 2, "retain")
    target_consumer = ConsumerContract("d", "field_b", "test", 5.0, 1, "retain")
    target = decision_ir.ConsumerDecisionIR(
        action_id="target",
        domain="test",
        consumer_id="d" if cross_consumer else "c",
        field="field_b" if cross_consumer else "field_a",
        operation="add",
        core_evidence=("target_need",),
        auxiliary_evidence=(),
        hard_negative=(),
        costs=(),
        max_delta=5.0,
        consumer_max_delta=5.0,
        vanilla_tail="retain",
        unknown_policy="vanilla",
        relation_ids=(),
        requires_all=("target_need",),
        exit_when=("target_exit",),
    )
    source = replace(
        target,
        action_id="source",
        consumer_id="c",
        field="field_a",
        core_evidence=("source_need",),
        requires_all=("source_need",),
        exit_when=(),
        stress=1.0,
        base=1.0,
        relations=(
            Relation(
                "source", "target", cast("RelationKind", kind), 1.0, condition_facts=("completed",)
            ),
        ),
    )
    rows = (source, target)
    facts = tuple(
        EvidenceSpec(
            name, "test", "test", "root", "boolean", "flag", "consumer", "vanilla", f"{name} = yes"
        )
        for name in ("source_need", "target_need", "target_exit", "completed")
    )
    model = compiler.SituatedModel(
        facts=facts,
        consumers=(consumer, target_consumer) if cross_consumer else (consumer,),
        actions=(),
        relations=source.relations,
        source_sha256={},
        decision_ir=rows,
        consumer_ir=decision_ir.ConsumerIRBundle(1, rows, ()),
    )
    return _with_decisions(model), None


@pytest.mark.parametrize("cross_consumer", [False, True], ids=["local", "other_consumer"])
@pytest.mark.parametrize(
    ("target_exit", "expected"),
    [(False, 12.0), (True, 11.0), (None, 11.0)],
    ids=["active", "exited", "unknown_exit"],
)
def test_complement_uses_complete_target_qualification(cross_consumer, target_exit, expected):
    """历史资格用例迁移为实际完成证据；退出不再被误当作世界完成。"""
    model, _policy = _relation_model(cross_consumer=cross_consumer)
    values = {
        "source_need": True,
        "target_need": True,
        "target_exit": target_exit,
        "completed": target_exit is False if target_exit is not None else None,
    }
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert reference == {"field_a": ("native", expected)}
    assert generated.action_id == "joint_c"
    assert generated.delta == expected - 10.0


@pytest.mark.parametrize("target_need", [False, None], ids=["not_qualified", "unknown_core"])
def test_complement_unknown_or_unqualified_target_keeps_known_source(target_need):
    model, _policy = _relation_model(cross_consumer=True)
    values = {
        "source_need": True,
        "target_need": target_need,
        "target_exit": False,
        "completed": None,
    }
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert reference == {"field_a": ("native", 11.0)}
    assert (generated.action_id, generated.delta) == ("joint_c", 1.0)


def test_relation_target_cannot_change_player_value():
    model, _policy = _relation_model(cross_consumer=True)
    values = {"source_need": True, "target_need": True, "target_exit": False, "completed": True}
    assert _native_plus_actions(model, values, is_ai=False) == {}
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": False}
    )
    assert (generated.action_id, generated.delta, generated.fallback) == (None, 0.0, "vanilla")


def test_cross_consumer_enable_uses_known_target_without_requiring_target_selection():
    model, _policy = _relation_model(cross_consumer=True, kind="enables")
    values = {"source_need": True, "target_need": True, "target_exit": False, "completed": True}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert reference == {"field_a": ("native", 11.0)}
    assert (generated.action_id, generated.delta) == ("joint_c", 1.0)


@pytest.mark.parametrize("target_exit", [True, None], ids=["exited", "unknown_exit"])
def test_cross_consumer_enable_rejects_exited_or_unknown_target(target_exit):
    model, _policy = _relation_model(cross_consumer=True, kind="enables")
    values = {
        "source_need": True,
        "target_need": True,
        "target_exit": target_exit,
        "completed": target_exit is False if target_exit is not None else None,
    }
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert reference == {"field_a": ("native", 10.0)}
    assert generated.delta == 0.0
    assert generated.action_id == "joint_c"
    assert generated.fallback == "selected"


@pytest.mark.parametrize("kind", ["complements", "substitutes", "conflicts", "enables"])
def test_disabled_cross_consumer_target_isolated_without_bypassing_enable(kind):
    """关闭目标消费者时只移除可选关系，不能绕过 enables 硬前提。"""
    model, _policy = _relation_model(cross_consumer=True, kind=kind)
    values = {
        "source_need": True,
        "target_need": True,
        "target_exit": False,
        "completed": True,
        "is_ai": True,
    }
    generated = pdx_eval.select(
        compiler.strategy_overlay(model, enabled_consumer_fields={"field_a"})["field_a"],
        values,
    )
    if kind == "enables":
        assert generated.action_id == "joint_c"
        assert generated.delta == 0.0
    else:
        assert (generated.action_id, generated.delta) == ("joint_c", 1.0)


@pytest.mark.parametrize("kind", ["substitutes", "conflicts"])
def test_higher_ranked_source_ignores_unknown_lower_alternative(kind):
    model, _policy = _relation_model(cross_consumer=False, kind=kind)
    values = {"source_need": True, "target_need": None, "target_exit": False}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert reference == {"field_a": ("native", 11.0)}
    assert (generated.action_id, generated.delta) == ("joint_c", 1.0)


def test_known_exit_excludes_unknown_core_before_selecting_lower_action():
    model, _policy = _relation_model(cross_consumer=False)
    source, target = model.decision_ir
    model = _with_decisions(
        model,
        decision_ir=(
            replace(source, exit_when=("target_exit",), relations=()),
            replace(target, exit_when=(), base=2.0),
        ),
    )
    values = {"source_need": None, "target_need": True, "target_exit": True}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert reference == {"field_a": ("native", 12.0)}
    assert (generated.action_id, generated.delta) == ("joint_c", 2.0)


def test_explicit_cost_predicates_are_part_of_the_production_schema():
    assert "CostPredicate" in vars(situated_schema)
    assert "commitment_when" in situated_schema.ActionCard.__dataclass_fields__
    assert "political_when" in decision_ir.ConsumerDecisionIR.__dataclass_fields__


def test_production_cards_do_not_name_unreadable_cost_facts():
    model = compiler.load_model()
    known = {fact.id for fact in model.facts}
    assert {fact for row in model.decision_ir for fact in row.consumes} <= known


def _cost_model():
    model, _policy = _relation_model(cross_consumer=False)
    source, target = model.decision_ir
    cost = situated_schema.CostPredicate("debt", ">", 0.4, "debt_to_credit_ratio")
    model = _with_decisions(
        model,
        facts=(
            *model.facts,
            EvidenceSpec(
                "debt",
                "test",
                "test",
                "root",
                "number",
                "debt_to_credit_ratio",
                "consumer",
                "vanilla",
                "scaled_debt",
            ),
        ),
        decision_ir=(
            replace(
                source,
                base=2.0,
                stress=0.0,
                consumes=("debt",),
                commitment=1.0,
                commitment_when=(cost,),
                relations=(),
            ),
            replace(target, base=1.25),
        ),
    )
    return model, None


@pytest.mark.parametrize(
    ("debt", "expected_action", "expected_delta"),
    [
        (0.39, "joint_c", 3.25),
        (0.4, "joint_c", 3.25),
        (0.41, "joint_c", 2.25),
        (None, "joint_c", 2.25),
    ],
)
def test_cost_changes_non_tied_selection_at_frozen_debt_boundary(
    debt, expected_action, expected_delta
):
    model, _policy = _cost_model()
    values = {"source_need": True, "target_need": True, "target_exit": False, "debt": debt}
    reference = _native_plus_actions(model, values, is_ai=True)
    pdx_values = {**values, "is_ai": True, "scaled_debt": debt}
    generated = pdx_eval.select(compiler.strategy_overlay(model)["field_a"], pdx_values)
    assert reference == {"field_a": ("native", 10.0 + expected_delta)}
    assert (generated.action_id, generated.delta) == (expected_action, expected_delta)


@pytest.mark.parametrize(
    ("debt", "expected_action", "expected_delta"),
    [
        (0.39, "joint_c", 3.25),
        (0.4, "joint_c", 3.25),
        (0.41, "joint_c", 2.25),
        (None, "joint_c", 2.25),
    ],
)
def test_cost_can_switch_between_active_goals_despite_fixed_priority(
    debt, expected_action, expected_delta
):
    """Legacy goal priority cannot exclude independent demand/cost contributions."""
    model, _policy = _cost_model()
    source, target = model.decision_ir
    model = _with_decisions(
        model,
        goals=(("high", 100), ("low", 10)),
        goal_specs=(
            Goal("high", 100, "medium", True, consumer_bindings=("c",)),
            Goal("low", 10, "long", True, consumer_bindings=("c",)),
        ),
        decision_ir=(
            replace(
                source, rank_terms=(situated_schema.RankTerm("source_need", "high", 1, "flag"),)
            ),
            replace(
                target, rank_terms=(situated_schema.RankTerm("target_need", "low", 1, "flag"),)
            ),
        ),
    )
    values = {"source_need": True, "target_need": True, "target_exit": False, "debt": debt}
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"],
        {**values, "is_ai": True, "scaled_debt": debt},
    )
    assert (generated.action_id, generated.delta) == (expected_action, expected_delta)
    assert _native_plus_actions(model, values, is_ai=True) == {
        "field_a": ("native", 10.0 + expected_delta)
    }


@pytest.mark.parametrize(("base", "expected"), [(3.0, 2.0), (-3.0, -2.0)])
def test_political_cost_reduces_magnitude_without_reversing_direction(base, expected):
    model, _policy = _cost_model()
    source = replace(
        model.decision_ir[0],
        base=base,
        stress=2,
        commitment=0,
        commitment_when=(),
        political_cost=1,
        political_when=(situated_schema.CostPredicate("target_need", "=", True, "flag"),),
    )
    model = _with_decisions(model, decision_ir=(source,))
    values = {"source_need": True, "target_need": True, "target_exit": False, "completed": True}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert reference == {"field_a": ("native", 10.0 + expected)}
    assert generated.delta == expected


def test_cost_cannot_flip_infeasible_action_instead_of_retaining_neutral():
    """Historical feasibility identity: new signed utility must preserve a reversal."""
    model, _policy = _cost_model()
    source = replace(model.decision_ir[0], base=1.0, commitment=3.0)
    model = _with_decisions(model, decision_ir=(source,))
    values = {"source_need": True, "debt": 0.5}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "scaled_debt": 0.5, "is_ai": True}
    )
    # A cost larger than benefit reverses the preference instead of disappearing.
    assert reference == {"field_a": ("native", 8.0)}
    assert generated.delta == -2.0


def test_non_tied_crisis_candidate_that_cannot_afford_cost_yields_to_viable_alternative():
    """Historical winner identity: both utility terms survive until the final clamp."""
    model, _policy = _cost_model()
    source, target = model.decision_ir
    source = replace(source, stress=2, base=3, commitment=20)
    target = replace(target, stress=1, base=1)
    model = _with_decisions(model, decision_ir=(source, target))
    values = {"source_need": True, "target_need": True, "target_exit": False, "debt": 0.5}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "scaled_debt": 0.5, "is_ai": True}
    )
    # Both terms survive; the only consumer clamp limits -17 + 1.
    assert reference == {"field_a": ("native", 5.0)}
    assert (generated.action_id, generated.delta) == ("joint_c", -5.0)


@pytest.mark.parametrize("debt", [None, "unknown", float("nan"), float("inf"), -float("inf")])
def test_unknown_or_invalid_cost_conservatively_uses_costly_tier(debt):
    model, _policy = _cost_model()
    values = {"source_need": True, "target_need": True, "target_exit": False, "debt": debt}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"],
        {**values, "scaled_debt": debt, "is_ai": True},
    )
    assert reference == {"field_a": ("native", 12.25)}
    assert (generated.action_id, generated.delta) == ("joint_c", 2.25)


@pytest.mark.parametrize("cross_consumer", [False, True])
@pytest.mark.parametrize("kind", ["complements", "enables", "substitutes", "conflicts"])
def test_cost_infeasible_target_cannot_supply_relation(cross_consumer, kind):
    model, _policy = _relation_model(cross_consumer=cross_consumer, kind=kind)
    source, target = model.decision_ir
    target = replace(
        target,
        base=1,
        commitment=2,
        commitment_when=(situated_schema.CostPredicate("target_need", "=", True, "flag"),),
    )
    model = _with_decisions(model, decision_ir=(source, target))
    values = {"source_need": True, "target_need": True, "target_exit": False, "completed": True}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    # Completion is an observed fact even if the target current net preference is negative.
    source_delta = 2 if kind == "complements" else 1 if kind == "enables" else 0
    expected = source_delta - (0 if cross_consumer else 1)
    assert reference == {"field_a": ("native", 10 + expected)}
    assert generated.delta == expected


@pytest.mark.parametrize("base", [-3.0, -0.5])
def test_negative_complement_only_relieves_negative_magnitude(base):
    """Positive observed complement strengthens the action in its signed direction."""
    model, _policy = _relation_model(cross_consumer=True)
    source, target = model.decision_ir
    model = _with_decisions(
        model, decision_ir=(replace(source, base=base), replace(target, base=1))
    )
    values = {"source_need": True, "target_need": True, "target_exit": False, "completed": True}
    # A positive complement strengthens utility along the negative projection.
    expected = base - 1
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert reference == {"field_a": ("native", 10 + expected)}
    assert generated.delta == expected


def test_net_benefit_precedes_stress_for_non_tied_costs():
    """Historical rank identity: deprecated stress cannot exclude either net term."""
    model, _policy = _cost_model()
    source, target = model.decision_ir
    model = _with_decisions(
        model,
        decision_ir=(
            replace(source, stress=2, base=3, commitment=2.5),
            replace(target, stress=1, base=1),
        ),
    )
    values = {"source_need": True, "target_need": True, "target_exit": False, "debt": 0.5}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"],
        {**values, "scaled_debt": 0.5, "is_ai": True},
    )
    assert reference == {"field_a": ("native", 11.5)}
    assert (generated.action_id, generated.delta) == ("joint_c", 1.5)


@pytest.mark.parametrize(
    ("debt", "need", "expected"),
    [
        (0.3, False, 2),
        (0.5, False, 1),
        (0.3, True, 1),
        (None, True, 1),
        (0.3, None, 1),
    ],
)
def test_multiple_cost_predicates_retain_any_pressure_semantics(debt, need, expected):
    model, _policy = _cost_model()
    source = replace(
        model.decision_ir[0],
        commitment_when=(
            *model.decision_ir[0].commitment_when,
            situated_schema.CostPredicate("target_need", "=", True, "flag"),
        ),
    )
    model = _with_decisions(model, decision_ir=(source,))
    values = {"source_need": True, "target_need": need, "debt": debt}
    reference = _native_plus_actions(model, values, is_ai=True)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"],
        {**values, "scaled_debt": debt, "is_ai": True},
    )
    assert reference == {"field_a": ("native", 10 + expected)}
    assert generated.delta == expected


def test_production_economy_cost_changes_tool_and_complement_has_visible_bounded_effect():
    model = compiler.load_model()
    # Industry +.15 and education -.10 are independent. Education has .02
    # political cost and a -.025 observed administration complement.
    values = {
        "no_default": True,
        "default": False,
        "literacy_low": True,
        "bureaucracy_positive": True,
        "strong_legitimacy": False,
        "legitimacy": 60,
        "bureaucracy": 1,
        "debt_ratio": 0.4,
        "net_surplus": 1,
    }
    facts = {
        "is_ai": True,
        "in_default": False,
        "literacy_rate": 0.3,
        "bureaucracy": 1,
        "legitimacy": 60,
        "scaled_debt": 0.4,
        "net_total_income": 1,
    }
    field = "economic_vs_government_spending_balance"
    for debt, expected in ((0.4, 0.045), (0.41, 0.025)):
        reference = compiler.evaluate_actions(model, {**values, "debt_ratio": debt}, is_ai=True)
        assert reference[field][1] == pytest.approx(expected)
        generated = pdx_eval.select(
            compiler.strategy_overlay(model)[field], {**facts, "scaled_debt": debt}
        )
        assert generated.action_id == "joint_economic_balance"
        assert generated.delta == pytest.approx(expected)
    # Remove just the observed complement: its bounded contribution is visible.
    rows = tuple(
        replace(row, relations=()) if row.action_id == "education_and_research" else row
        for row in model.decision_ir
    )
    without = _with_decisions(model, decision_ir=rows)
    assert pdx_eval.select(compiler.strategy_overlay(without)[field], facts).delta == pytest.approx(
        0.07
    )


def test_disabled_relation_target_does_not_add_an_invalid_cost_fallback():
    model, _policy = _relation_model(cross_consumer=True)
    source, target = model.decision_ir
    model = _with_decisions(
        model,
        facts=(
            *model.facts,
            EvidenceSpec(
                "debt",
                "test",
                "test",
                "root",
                "number",
                "ratio",
                "consumer",
                "vanilla",
                "scaled_debt",
                minimum=0,
            ),
        ),
        decision_ir=(
            source,
            replace(
                target,
                base=1,
                commitment=0.5,
                commitment_when=(situated_schema.CostPredicate("debt", ">", 0.4, "ratio"),),
            ),
        ),
    )
    text = compiler.strategy_overlay(model, enabled_consumer_fields={"field_a"})["field_a"]
    actual = pdx_eval.select(
        text,
        {
            "is_ai": True,
            "source_need": True,
            "target_need": True,
            "target_exit": False,
            "scaled_debt": -1,
        },
    )
    assert (actual.action_id, actual.delta) == ("joint_c", 1)


@pytest.mark.parametrize("legitimacy", [0, 24, None])
@pytest.mark.parametrize("bureaucracy", [-1, 0, None])
def test_industrial_foundation_uses_cost_tier_instead_of_global_political_gate(
    legitimacy, bureaucracy
):
    model = compiler.load_model()
    row = next(row for row in model.decision_ir if row.action_id == "industrial_foundation")
    values = {"peace": True, "no_default": True, "default": False, "war": False}
    assert compiler._action_status(row, values) is True
    result = pdx_eval.select(
        compiler.strategy_overlay(model)["economic_vs_government_spending_balance"],
        {
            "is_ai": True,
            "is_at_war": False,
            "in_default": False,
            "legitimacy": legitimacy,
            "bureaucracy": bureaucracy,
            "literacy_rate": 0.8,
            "any_insurrection_ongoing": True,
        },
    )
    assert result.action_id == "joint_economic_balance"
    assert result.delta == pytest.approx(0.075)


def test_default_without_insurrection_keeps_conservative_window_available():
    model = compiler.load_model()
    values = {"peace": True, "default": True, "insurrection": False, "ongoing_insurrection": False}
    result = compiler.evaluate_actions(model, values, is_ai=True)
    assert result["max_regressiveness"] == ("joint_max_regressiveness", 5.0)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["max_regressiveness"],
        {"is_ai": True, "is_at_war": False, "in_default": True, "any_insurrection_ongoing": False},
    )
    assert (generated.action_id, generated.delta) == ("joint_max_regressiveness", 5.0)


@pytest.mark.parametrize("target_need", [True, False, None])
@pytest.mark.parametrize("target_exit", [True, False, None])
def test_observed_completion_is_independent_of_target_current_intention(target_need, target_exit):
    model, _policy = _relation_model(cross_consumer=True)
    values = {
        "source_need": True,
        "target_need": target_need,
        "target_exit": target_exit,
        "completed": True,
    }
    actual = compiler.evaluate_actions(model, values, is_ai=True)
    assert actual["field_a"] == ("joint_c", 2.0)
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["field_a"], {**values, "is_ai": True}
    )
    assert (generated.action_id, generated.delta) == ("joint_c", 2.0)
