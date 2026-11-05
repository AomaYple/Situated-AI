"""S1 joint consumer programs: independent handwritten semantic expectations."""

from dataclasses import replace

import pytest

from pdx.parser import parse_text
from pdx.situated import compiler, decision_ir, pdx_eval
from pdx.situated.goals import Goal
from pdx.situated.schema import ConsumerContract, CostPredicate, EvidenceSpec, RankTerm, Relation

pytestmark = pytest.mark.unit


def _row(name, base, *, consumer="c", **changes):
    row = decision_ir.ConsumerDecisionIR(
        action_id=name,
        domain="test",
        consumer_id=consumer,
        field=f"field_{consumer}",
        operation="add",
        core_evidence=(f"need_{name}",),
        auxiliary_evidence=(),
        hard_negative=(),
        costs=(),
        max_delta=1.0,
        consumer_max_delta=5.0,
        vanilla_tail="retain",
        unknown_policy="vanilla",
        relation_ids=(),
        requires_all=(f"need_{name}",),
        base=base,
    )
    return replace(row, **changes)


def _model(*rows, bound=5.0):
    consumers = tuple(
        ConsumerContract(key, f"field_{key}", "test", bound, len(rows), "retain")
        for key in sorted({row.consumer_id for row in rows})
    )
    names = {name for row in rows for name in row.requires_all}
    names.update(name for row in rows for rel in row.relations for name in rel.condition_facts)
    names.update(term.fact for row in rows for term in row.rank_terms)
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
            for name in sorted(names)
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
            writer_id=f"card_{row.action_id}",
            kind="action_card",
            source="mod/decisions/actions.toml",
            definition=row.action_id,
            consumer_id=row.consumer_id,
            field=row.field,
            actor="root",
            target="none",
            operation="add",
            vanilla_tail="retain",
            owner="situated_kernel",
            action=row,
        )
        for row in rows
    )
    return compiler.SituatedModel(
        facts=facts,
        consumers=consumers,
        actions=(),
        relations=tuple(rel for row in rows for rel in row.relations),
        source_sha256={},
        decision_ir=rows,
        consumer_ir=decision_ir.ConsumerIRBundle(1, rows, writers),
        goal_specs=tuple(
            Goal(goal, 1, "fixture", True, consumer_bindings=tuple(c.id for c in consumers))
            for goal in sorted({term.goal for row in rows for term in row.rank_terms})
        ),
    )


def _assert_output(model, values, expected, *, enabled=None, is_ai=True):
    actual = compiler.evaluate_actions(model, values, is_ai=is_ai, enabled_consumer_fields=enabled)
    observed = {field: delta for field, (_, delta) in actual.items()}
    assert observed == pytest.approx(expected)
    scripts = compiler.strategy_overlay(model, enabled_consumer_fields=enabled)
    for field, text in scripts.items():
        assert not parse_text(text).errors
        result = pdx_eval.select(text, {**values, "is_ai": is_ai})
        assert result.delta == pytest.approx(expected.get(field, 0.0))


def test_independent_positive_and_negative_terms_join_before_only_clamp():
    # Clamping the two positive actions separately, selecting one, or clamping
    # the running partial sum would all disagree with this final value.
    model = _model(_row("a", 8.0), _row("b", -7.0), _row("c", 2.0))
    values = {"need_a": True, "need_b": True, "need_c": True}
    _assert_output(model, values, {"field_c": 3.0})
    reordered = replace(model, decision_ir=tuple(reversed(model.decision_ir)))
    _assert_output(reordered, values, {"field_c": 3.0})


def test_explicit_program_preserves_more_than_six_significant_digits():
    model = _model(_row("precise", 0.123456789))
    result = compiler.evaluate_actions(model, {"need_precise": True}, is_ai=True)
    actual = pdx_eval.select(
        compiler.strategy_overlay(model)["field_c"],
        {"is_ai": True, "need_precise": True},
    )
    assert result["field_c"][1] == pytest.approx(0.123456789, abs=1e-14, rel=0)
    assert actual.delta == pytest.approx(0.123456789, abs=1e-14, rel=0)


@pytest.mark.parametrize("unknown", [None, False])
def test_unknown_or_ineligible_action_does_not_block_independent_term(unknown):
    model = _model(_row("a", 4.0), _row("b", 2.0))
    _assert_output(model, {"need_a": unknown, "need_b": True}, {"field_c": 2.0})


@pytest.mark.parametrize(
    ("pressure", "expected"),
    [(0.39, 1.0), (0.4, 1.0), (0.41, -1.0), (None, -1.0), (1.1, -1.0)],
)
def test_cost_can_reverse_net_contribution_and_unknown_is_locally_conservative(pressure, expected):
    costly = _row(
        "a",
        1.0,
        commitment=2.0,
        commitment_when=(CostPredicate("pressure", ">", 0.4, "ratio"),),
    )
    _assert_output(_model(costly), {"need_a": True, "pressure": pressure}, {"field_c": expected})


def test_unconditional_legacy_complement_is_not_world_completion():
    source = _row("a", 1.0, relations=(Relation("a", "b", "complements", 3.0),))
    _assert_output(
        _model(source, _row("b", 2.0)), {"need_a": True, "need_b": True}, {"field_c": 3.0}
    )


@pytest.mark.parametrize(("completed", "expected"), [(False, 1.0), (None, 1.0), (True, 3.0)])
def test_complement_uses_observed_world_fact_even_if_target_is_not_currently_intended(
    completed, expected
):
    source = _row(
        "a",
        1.0,
        relations=(Relation("a", "b", "complements", 2.0, condition_facts=("completed",)),),
    )
    model = _model(source, _row("b", 0.0, consumer="d"))
    _assert_output(
        model, {"need_a": True, "need_b": False, "completed": completed}, {"field_c": expected}
    )


@pytest.mark.parametrize("kind", ["conflicts", "substitutes"])
def test_cross_consumer_relation_is_soft_observed_opportunity_cost(kind):
    source = _row(
        "a", 3.0, relations=(Relation("a", "b", kind, 1.0, condition_facts=("committed",)),)
    )
    model = _model(source, _row("b", 2.0, consumer="d"))
    values = {"need_a": True, "need_b": True, "committed": True}
    _assert_output(model, values, {"field_c": 2.0, "field_d": 2.0})
    _assert_output(model, values, {"field_c": 3.0}, enabled={"field_c"})


@pytest.mark.parametrize(
    ("completed", "expected"), [(False, {}), (None, {}), (True, {"field_c": 1.0})]
)
def test_enable_requires_observed_completion_not_target_card_qualification(completed, expected):
    source = _row(
        "a", 1.0, relations=(Relation("a", "b", "enables", 1.0, condition_facts=("completed",)),)
    )
    _assert_output(
        _model(source, _row("b", 0.0)),
        {"need_a": True, "need_b": True, "completed": completed},
        expected,
    )


def test_unproven_enable_does_not_grant_dependency():
    source = _row("a", 1.0, relations=(Relation("a", "b", "enables", 1.0),))
    _assert_output(_model(source, _row("b", 0.0)), {"need_a": True, "need_b": True}, {})


def test_player_and_disabled_consumers_are_neutral():
    model = _model(_row("a", 3.0))
    _assert_output(model, {"need_a": True}, {}, is_ai=False)
    _assert_output(model, {"need_a": True}, {}, enabled=set())


def test_generated_program_grows_linearly_without_truth_table_partitions():
    def generated(size):
        rows = tuple(
            _row(
                f"a{i}",
                1.0,
                commitment=0.5,
                commitment_when=(CostPredicate("pressure", ">", i / (size + 1), "ratio"),),
            )
            for i in range(size)
        )
        return compiler.strategy_overlay(_model(*rows))["field_c"]

    small, large = generated(8), generated(32)
    assert len(large) < len(small) * 4.5
    assert large.count("# ACTION a") == 32
    assert large.count("min =") == 1
    assert large.count("max =") == 1
    assert "else_if" not in large


@pytest.mark.parametrize("pressure", [None, 1.1])
def test_invalid_cost_affects_only_its_own_term(pressure):
    costly = _row(
        "a",
        1.0,
        commitment=2.0,
        commitment_when=(CostPredicate("pressure", ">", 0.4, "ratio"),),
    )
    _assert_output(
        _model(costly, _row("b", 3.0)),
        {"need_a": True, "need_b": True, "pressure": pressure},
        {"field_c": 2.0},
    )


@pytest.mark.parametrize(("pressure", "expected"), [(0.0, -1.0), (1.0, 1.0)])
def test_cost_weakens_negative_projection_and_can_reverse_it(pressure, expected):
    row = _row(
        "a", -1.0, commitment=2.0, commitment_when=(CostPredicate("pressure", ">", 0.5, "ratio"),)
    )
    _assert_output(_model(row), {"need_a": True, "pressure": pressure}, {"field_c": expected})


def test_unsupported_multiply_consumer_is_rejected_instead_of_silent_add():
    model = _model(_row("a", 2.0))
    rows = tuple(replace(row, operation="multiply") for row in model.decision_ir)
    bundle = replace(
        model.consumer_ir,
        actions=rows,
        writers=tuple(
            replace(writer, operation="multiply", action=rows[i])
            for i, writer in enumerate(model.consumer_ir.writers)
        ),
    )
    model = replace(
        model,
        consumers=tuple(replace(c, operation="multiply") for c in model.consumers),
        decision_ir=rows,
        consumer_ir=bundle,
    )
    with pytest.raises(ValueError, match="add"):
        compiler.strategy_overlay(model)
    with pytest.raises(ValueError, match="add"):
        compiler.evaluate_actions(model, {"need_a": True}, is_ai=True)


@pytest.mark.parametrize(("demand", "expected"), [(True, 1.25), (False, 1.0), (None, 1.0)])
def test_actual_demand_changes_utility_without_gating_base_action(demand, expected):
    row = _row("a", 1.0, rank_terms=(RankTerm("demand", "capacity", 1, "flag", 0.25),))
    _assert_output(_model(row), {"need_a": True, "demand": demand}, {"field_c": expected})


@pytest.mark.parametrize(
    ("a", "b", "expected"), [(True, True, 0.6), (None, True, 0.4), (False, None, 0.3)]
)
def test_correlated_demand_evidence_takes_strongest_known_amount(a, b, expected):
    first = _row("a", 0.1, rank_terms=(RankTerm("d1", "capacity", 2, "flag", 0.3, "shortage"),))
    second = _row("b", 0.2, rank_terms=(RankTerm("d2", "capacity", 1, "flag", 0.1, "shortage"),))
    _assert_output(
        _model(first, second),
        {"need_a": True, "need_b": True, "d1": a, "d2": b},
        {"field_c": expected},
    )


def test_different_need_groups_and_opposite_economic_preferences_remain_independent():
    first = _row(
        "industry",
        0.15,
        rank_terms=(RankTerm("industry", "structure", 1, "flag", 0.025, "industry"),),
    )
    second = _row(
        "education",
        -0.1,
        rank_terms=(RankTerm("education", "capacity", 1, "flag", 0.025, "education"),),
    )
    model = _model(first, second)
    _assert_output(
        model,
        {"need_industry": True, "need_education": True, "industry": True, "education": False},
        {"field_c": 0.075},
    )
    _assert_output(
        model,
        {"need_industry": True, "need_education": True, "industry": False, "education": True},
        {"field_c": 0.025},
    )


def test_cause_dedup_does_not_hide_independent_real_costs():
    rows = tuple(
        _row(
            name,
            base,
            cause_group="same_cause",
            commitment=0.2,
            commitment_when=(CostPredicate("pressure", ">", 0.4, "ratio"),),
        )
        for name, base in (("a", 0.8), ("b", 0.6))
    )
    _assert_output(
        _model(*rows), {"need_a": True, "need_b": True, "pressure": 1.0}, {"field_c": 0.4}
    )
    _assert_output(
        _model(*rows), {"need_a": None, "need_b": True, "pressure": 0.0}, {"field_c": 0.6}
    )


@pytest.mark.parametrize(("high", "expected"), [(True, 1.0), (False, 0.3), (None, 0.3)])
def test_explicit_variants_are_mutually_exclusive_and_unknown_falls_to_known_lower(high, expected):
    rows = (
        _row("a", 1.0, variant_group="one_action", variant_priority=2),
        _row("b", 0.3, variant_group="one_action", variant_priority=1),
    )
    _assert_output(_model(*rows), {"need_a": high, "need_b": True}, {"field_c": expected})


@pytest.mark.parametrize(("shared", "expected"), [("one_commitment", 1.3), ("", 1.0)])
def test_shared_cost_requires_explicit_identity_not_merely_equal_pressure(shared, expected):
    rows = tuple(
        _row(
            name,
            0.8,
            commitment=0.3,
            commitment_cost_id=shared,
            commitment_when=(CostPredicate("pressure", ">", 0.4, "ratio"),),
        )
        for name in ("a", "b")
    )
    _assert_output(
        _model(*rows), {"need_a": True, "need_b": True, "pressure": None}, {"field_c": expected}
    )


def test_shared_cost_owner_unknown_does_not_mask_known_owner():
    rows = tuple(
        _row(
            name,
            0.8,
            commitment=0.3,
            commitment_cost_id="one_commitment",
            commitment_when=(CostPredicate("pressure", ">", 0.4, "ratio"),),
        )
        for name in ("a", "b")
    )
    _assert_output(
        _model(*rows), {"need_a": None, "need_b": True, "pressure": None}, {"field_c": 0.5}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"base": -0.8},
        {"commitment": 0.4},
        {"commitment_when": (CostPredicate("pressure", ">=", 0.4, "ratio"),)},
        {"commitment_when": (CostPredicate("pressure", ">", 0.4, "wrong_unit"),)},
    ],
)
def test_inconsistent_shared_cost_identity_is_rejected(changes):
    first = _row(
        "a",
        0.8,
        commitment=0.3,
        commitment_cost_id="one_commitment",
        commitment_when=(CostPredicate("pressure", ">", 0.4, "ratio"),),
    )
    second = replace(first, action_id="b", requires_all=("need_b",), **changes)
    model = _model(first, second)
    with pytest.raises(ValueError, match="shared cost"):
        compiler.strategy_overlay(model)
    with pytest.raises(ValueError, match="shared cost"):
        compiler.evaluate_actions(model, {"need_a": True}, is_ai=True)


@pytest.mark.parametrize(
    ("category", "high", "expected"),
    [
        ("base", True, 0.8),
        ("base", None, 0.5),
        ("rank", True, 1.3),
        ("rank", None, 0.7),
    ],
)
def test_selected_variant_shares_declared_external_cause_in_reference_and_pdx(
    category, high, expected
):
    if category == "base":
        rows = (
            _row("a", 0.8, variant_group="variant", variant_priority=2, cause_group="cause"),
            _row("b", 0.2, variant_group="variant", variant_priority=1, cause_group="cause"),
            _row("external", 0.5, cause_group="cause"),
        )
        # Only the selected variant competes with external .5 for this cause.
    else:
        rows = (
            _row(
                "a",
                0.8,
                variant_group="variant",
                variant_priority=2,
                rank_terms=(RankTerm("demand", "capacity", 1, "flag", 0.3, "need"),),
            ),
            _row(
                "b",
                0.2,
                variant_group="variant",
                variant_priority=1,
                rank_terms=(RankTerm("demand", "capacity", 1, "flag", 0.1, "need"),),
            ),
            _row(
                "external",
                0.1,
                rank_terms=(RankTerm("demand", "capacity", 1, "flag", 0.4, "need"),),
            ),
        )
        # Independent bases join; shared rank contributes max(selected rank, .4).
    _assert_output(
        _model(*rows),
        {"need_a": high, "need_b": True, "need_external": True, "demand": True},
        {"field_c": expected},
    )


def test_variant_shared_cost_without_positive_cost_and_predicates_remains_rejected():
    model = _model(_row("a", 0.8, variant_group="variant", commitment_cost_id="cost"))
    with pytest.raises(ValueError, match="显式 shared cost 必须包含正成本与谓词"):
        compiler.strategy_overlay(model)
    with pytest.raises(ValueError, match="显式 shared cost 必须包含正成本与谓词"):
        compiler.evaluate_actions(model, {"need_a": True}, is_ai=True)


def test_grouping_produces_linear_chains_instead_of_truth_table_expansion():
    def generated(size):
        rows = tuple(
            _row(
                f"a{i}",
                (i + 1) / 100,
                cause_group="cause",
                commitment=0.1,
                commitment_cost_id="one_cost",
                commitment_when=(CostPredicate("pressure", ">", 0.4, "ratio"),),
                rank_terms=(RankTerm(f"d{i}", "capacity", 1, "flag", 0.1, "need"),),
            )
            for i in range(size)
        )
        return compiler.strategy_overlay(_model(*rows))["field_c"]

    small, large = generated(8), generated(32)
    assert len(large) < len(small) * 4.5
    assert large.count("else_if") == 3 * 31
    assert large.count("min =") == large.count("max =") == 1
