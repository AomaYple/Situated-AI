"""A2 pure semantic core: independent reference and locality witnesses."""

from dataclasses import replace
from typing import Literal, cast

import pytest

from pdx.situated import core_contracts as c
from pdx.situated.expressions import All, BooleanLiteral, Compare
from pdx.situated.expressions import Any as AnyExpr
from pdx.situated.semantic_core import (
    ActionSpec,
    AssessmentTerm,
    FacetExpression,
    FacetKind,
    FacetSpec,
    InvalidSemanticInput,
    assess_actions,
    dependency_index,
    derive_facets,
    recompute,
)

EVIDENCE = c.EvidenceRef("common/ai/a2.txt", 1)
ACTOR = c.EntityKey("country", "FRA")
STATE = c.EntityKey("state", "FRA-paris")
TIME = c.TimeIdentity("session", 1)


def fact(
    spec_id: str,
    unit: c.Unit = "ratio",
    entity_kind: c.EntityKind = "country",
    binding: Literal["actor", "target"] = "actor",
    minimum: float | None = None,
    maximum: float | None = None,
) -> c.FactSpec:
    if spec_id == "fiscal" and unit == "ratio":
        unit = "currency_per_week"
    return c.FactSpec(
        spec_id,
        f"reader.{spec_id.replace('.', '_')}",
        "number",
        unit,
        entity_kind,
        binding,
        ("consumer.main",),
        (EVIDENCE,),
        minimum,
        maximum,
    )


def observation(
    spec_id: str,
    value: object | None,
    *,
    entity: c.EntityKey = ACTOR,
    status: c.Knowledge = "known",
) -> c.Observation:
    unit: c.Unit = (
        "boolean"
        if isinstance(value, bool)
        else "currency_per_week"
        if spec_id == "fiscal"
        else "ratio"
    )
    return c.Observation(
        spec_id,
        entity,
        unit,
        status,
        TIME,
        cast("c.Scalar | None", value),
        (EVIDENCE,) if status in {"known", "unsupported"} else (),
    )


def snapshot(*items: c.Observation) -> c.SituationSnapshot:
    return c.SituationSnapshot(
        ACTOR, None, "consumer.main", TIME, "country", items, "schedule.main"
    )


def schedule() -> c.EvaluationSchedule:
    return c.EvaluationSchedule("schedule.main", "consumer.main", (EVIDENCE,))


def test_facets_keep_categories_units_scope_and_unknown_states_without_global_score():
    facts = (
        fact("literacy"),
        fact("fiscal"),
        fact("state_gap", entity_kind="state", binding="target"),
    )
    snap = replace(snapshot(observation("literacy", 0.2), observation("fiscal", 0.1)), target=STATE)
    specs = (
        FacetSpec(
            "need.education",
            "need",
            "boolean",
            "country",
            ("literacy",),
            Compare("literacy", "lt", 0.5),
        ),
        FacetSpec(
            "capacity.fiscal",
            "capacity",
            "boolean",
            "country",
            ("fiscal",),
            Compare("fiscal", "ge", 0.0),
        ),
        FacetSpec("opportunity.state", "opportunity", "ratio", "state", ("state_gap",), None),
    )
    facets = derive_facets(snap, facts, specs, schedule())
    assert [item.category for item in facets] == ["need", "capacity", "opportunity"]
    assert facets[0].unit == "boolean"
    assert facets[0].scope == "country"
    assert facets[0].value is True
    assert facets[2].status == "unknown"
    assert facets[2].value is None
    assert all(not hasattr(item, "score") for item in facets)


@pytest.mark.parametrize("status", ["unknown", "stale", "unsupported"])
def test_unknown_stale_and_unsupported_are_local_to_dependent_facet(status: str):
    facts = (fact("literacy"), fact("fiscal"))
    snap = snapshot(
        observation("literacy", None, status=cast("c.Knowledge", status)),
        observation("fiscal", 0.4),
    )
    specs = (
        FacetSpec(
            "need.education",
            "need",
            "boolean",
            "country",
            ("literacy",),
            Compare("literacy", "lt", 0.5),
        ),
        FacetSpec(
            "capacity.fiscal",
            "capacity",
            "boolean",
            "country",
            ("fiscal",),
            Compare("fiscal", "ge", 0.0),
        ),
    )
    facets = derive_facets(snap, facts, specs, schedule())
    assert facets[0].status == status
    assert facets[0].value is None
    assert facets[1].status == "known"
    assert facets[1].value is True


def test_invalid_values_fail_at_semantic_boundary_instead_of_becoming_unknown():
    facts = (fact("literacy", minimum=0.0, maximum=1.0),)
    invalid = observation("literacy", 2.0)
    with pytest.raises(InvalidSemanticInput, match="literacy"):
        derive_facets(snapshot(invalid), facts, (), schedule())


def test_action_assessment_keeps_short_long_terms_and_qualification_basis():
    facts = (fact("literacy"), fact("fiscal"))
    snap = snapshot(observation("literacy", 0.2), observation("fiscal", 0.1))
    snap = replace(snap, target=STATE, aggregation="local")
    facets = derive_facets(
        snap,
        facts,
        (
            FacetSpec(
                "need.education",
                "need",
                "boolean",
                "country",
                ("literacy",),
                Compare("literacy", "lt", 0.5),
            ),
        ),
        schedule(),
    )
    action = ActionSpec(
        "school.paris",
        "consumer.main",
        ACTOR,
        STATE,
        ("need.education",),
        (
            AssessmentTerm(
                "literacy_gain",
                "benefit",
                "ratio",
                "state",
                0.2,
                "known",
                ("need.education",),
                "short",
            ),
        ),
        (
            AssessmentTerm(
                "maintenance",
                "cost",
                "currency_per_week",
                "country",
                10.0,
                "known",
                ("fiscal",),
                "long",
            ),
        ),
        eligibility=Compare("fiscal", "ge", 0.0),
        eligibility_facts=("fiscal",),
    )
    result = assess_actions((action,), facets, snap, facts, schedule())
    assert result[0].qualification == "known"
    assert result[0].qualification_evidence == ("fiscal",)
    assert result[0].benefits[0].horizon == "short"
    assert result[0].costs[0].horizon == "long"
    assert result[0].benefits[0].unit != result[0].costs[0].unit


def test_dependency_index_and_recompute_are_local_and_idempotent():
    facts = (fact("literacy"), fact("fiscal"))
    snap = snapshot(observation("literacy", 0.2), observation("fiscal", 0.1))
    specs = (
        FacetSpec(
            "need.education",
            "need",
            "boolean",
            "country",
            ("literacy",),
            Compare("literacy", "lt", 0.5),
        ),
        FacetSpec(
            "capacity.fiscal",
            "capacity",
            "boolean",
            "country",
            ("fiscal",),
            Compare("fiscal", "ge", 0.0),
        ),
    )
    actions = (
        ActionSpec("school", "consumer.main", ACTOR, None, ("need.education",)),
        ActionSpec("bond", "consumer.main", ACTOR, None, ("capacity.fiscal",)),
    )
    idx = dependency_index(specs, actions)
    assert idx["literacy"] == ("need.education", "school")
    assert idx["fiscal"] == ("capacity.fiscal", "bond")
    first = recompute(snap, facts, specs, actions, schedule())
    changed = snapshot(observation("literacy", 0.8), observation("fiscal", 0.1))
    partial = recompute(
        changed, facts, specs, actions, schedule(), previous=first, changed_facts=("literacy",)
    )
    again = recompute(changed, facts, specs, actions, schedule())
    assert partial.facets[0].value is False
    assert partial.actions == first.actions
    assert partial.facets == again.facets
    assert partial.actions == again.actions


def test_country_and_state_observations_cannot_be_cross_wired():
    specs = (FacetSpec("state.need", "need", "ratio", "state", ("state_gap",), None),)
    state_fact = fact("state_gap", entity_kind="state", binding="target")
    with pytest.raises(ValueError, match="串接"):
        derive_facets(snapshot(observation("state_gap", 0.2)), (state_fact,), specs, schedule())


@pytest.mark.parametrize("scope", ["state", "target"])
def test_raw_facet_cannot_relabel_actor_fact_as_target_entity(scope):
    snap = replace(snapshot(observation("literacy", 0.2)), target=STATE, aggregation="local")
    spec = FacetSpec("need.raw", "need", "ratio", scope, ("literacy",))
    with pytest.raises(InvalidSemanticInput, match="作用域"):
        derive_facets(snap, (fact("literacy"),), (spec,), schedule())


def test_raw_country_facet_cannot_relabel_foreign_country_fact_as_actor():
    target = c.EntityKey("country", "GER")
    snap = replace(snapshot(observation("literacy", 0.2, entity=target)), target=target)
    spec = FacetSpec("need.raw", "need", "ratio", "country", ("literacy",))
    with pytest.raises(InvalidSemanticInput, match="作用域"):
        derive_facets(snap, (fact("literacy", binding="target"),), (spec,), schedule())


@pytest.mark.parametrize("damage", ["missing_target", "wrong_target_kind", "consumer"])
def test_missing_observation_does_not_hide_invalid_fact_binding(damage):
    source = fact("state_gap", entity_kind="state", binding="target")
    snap = replace(snapshot(), target=STATE, aggregation="local")
    if damage == "missing_target":
        snap = snapshot()
    elif damage == "wrong_target_kind":
        snap = replace(snap, target=c.EntityKey("building", "FRA-university"))
    else:
        source = replace(source, consumer_ids=("consumer.other",))
    spec = FacetSpec("need.raw", "need", "ratio", "state", ("state_gap",))
    with pytest.raises(InvalidSemanticInput, match=r"对象|消费者|作用域"):
        derive_facets(snap, (source,), (spec,), schedule())


@pytest.mark.parametrize("source_kind", ["fact", "facet"])
def test_numeric_terms_cannot_relabel_actor_sources_as_target(source_kind):
    facts = (fact("literacy"),)
    snap = replace(snapshot(observation("literacy", 0.2)), target=STATE, aggregation="local")
    facets = derive_facets(
        snap, facts, (FacetSpec("need.raw", "need", "ratio", "country", ("literacy",)),), schedule()
    )
    term = AssessmentTerm(
        "gain",
        "benefit",
        "ratio",
        "state",
        0.2,
        source_ids=("literacy" if source_kind == "fact" else "need.raw",),
    )
    action = ActionSpec("school", "consumer.main", ACTOR, STATE, benefits=(term,))
    with pytest.raises(InvalidSemanticInput, match="作用域"):
        assess_actions((action,), facets, snap, facts, schedule())


def test_target_scope_preserves_valid_foreign_country_binding():
    target = c.EntityKey("country", "GER")
    facts = (fact("literacy", binding="target"),)
    snap = replace(snapshot(observation("literacy", 0.2, entity=target)), target=target)
    facets = derive_facets(
        snap, facts, (FacetSpec("need.raw", "need", "ratio", "target", ("literacy",)),), schedule()
    )
    term = AssessmentTerm("gain", "benefit", "ratio", "target", 0.2, source_ids=("need.raw",))
    action = ActionSpec("school", "consumer.main", ACTOR, target, benefits=(term,))
    result = assess_actions((action,), facets, snap, facts, schedule())[0]
    assert (result.benefits[0].status, result.benefits[0].value) == ("known", 0.2)


def test_assessment_revalidates_numeric_facet_source_scope():
    facts = (fact("literacy"),)
    snap = replace(snapshot(observation("literacy", 0.2)), target=STATE, aggregation="local")
    facet = derive_facets(
        snap, facts, (FacetSpec("need.raw", "need", "ratio", "country", ("literacy",)),), schedule()
    )[0]
    # Matching snapshot identity must not license relabelling a raw facet.
    forged = replace(facet, scope="state")
    action = ActionSpec("school", "consumer.main", ACTOR, STATE, ("need.raw",))
    with pytest.raises(InvalidSemanticInput, match="作用域"):
        assess_actions((action,), (forged,), snap, facts, schedule())


def test_runtime_unknown_schedule_and_objective_wiring_are_preserved():
    assert schedule().runtime_status == "unknown"
    base = observation("fiscal", 0.1)
    objective = c.InterestSpec(
        "solvency",
        ACTOR,
        None,
        ("fiscal",),
        TIME,
        c.TimeIdentity("session", 4),
        base,
        (),
        ("consumer.main",),
        "known",
    )
    assert objective.consumer_ids == ("consumer.main",)
    with pytest.raises(ValueError):
        replace(objective, consumer_ids=())


@pytest.mark.parametrize("status", ["unknown", "stale", "unsupported"])
def test_term_sources_propagate_unavailability_without_free_costs(status):
    facts = (fact("literacy"), fact("fiscal"))
    snap = snapshot(observation("literacy", 0.2), observation("fiscal", None, status=status))
    action = ActionSpec(
        "school",
        "consumer.main",
        ACTOR,
        None,
        benefits=(
            AssessmentTerm("gain", "benefit", "ratio", "country", 0.2, source_ids=("literacy",)),
        ),
        costs=(
            AssessmentTerm(
                "burden", "cost", "currency_per_week", "country", 10.0, source_ids=("fiscal",)
            ),
        ),
        eligibility=BooleanLiteral(True),
    )
    assessed = assess_actions((action,), (), snap, facts, schedule())[0]
    assert assessed.eligible is True
    assert assessed.qualification == "known"
    assert (assessed.benefits[0].status, assessed.benefits[0].value) == ("known", 0.2)
    assert (assessed.costs[0].status, assessed.costs[0].value) == (status, None)
    assert assessed.unknowns == ("burden", "fiscal")


def test_absent_qualification_is_explicitly_unknown_and_does_not_mean_false():
    action = ActionSpec("school", "consumer.main", ACTOR, None)
    assessed = assess_actions((action,), (), snapshot(), (), schedule())[0]
    assert assessed.qualification == "unknown"
    assert assessed.eligible is None
    assert assessed.qualification_evidence == ()


@pytest.mark.parametrize(
    "change",
    [
        {"actor": c.EntityKey("country", "GER")},
        {"target": STATE},
        {"consumer_id": "consumer.other"},
    ],
)
def test_actions_reject_cross_actor_target_or_consumer(change):
    action = replace(ActionSpec("school", "consumer.main", ACTOR, None), **change)
    with pytest.raises(InvalidSemanticInput, match="串接"):
        assess_actions((action,), (), snapshot(), (), schedule())


def test_missing_term_source_fails_instead_of_inventing_known_value():
    action = ActionSpec(
        "school",
        "consumer.main",
        ACTOR,
        None,
        costs=(AssessmentTerm("burden", "cost", "ratio", "country", 0.1, source_ids=("missing",)),),
    )
    with pytest.raises(InvalidSemanticInput, match="missing"):
        assess_actions((action,), (), snapshot(), (), schedule())


def test_local_recompute_does_not_evaluate_unaffected_expressions(monkeypatch):
    facts = (fact("literacy"), fact("fiscal"))
    specs = (
        FacetSpec(
            "need.education",
            "need",
            "boolean",
            "country",
            ("literacy",),
            Compare("literacy", "lt", 0.5),
        ),
        FacetSpec(
            "capacity.fiscal",
            "capacity",
            "boolean",
            "country",
            ("fiscal",),
            Compare("fiscal", "ge", 0.0),
        ),
    )
    actions = (
        ActionSpec(
            "school",
            "consumer.main",
            ACTOR,
            None,
            benefits=(
                AssessmentTerm(
                    "gain", "benefit", "ratio", "country", 0.2, source_ids=("need.education",)
                ),
            ),
            eligibility=Compare("literacy", "lt", 0.5),
            eligibility_facts=("literacy",),
        ),
        ActionSpec(
            "bond",
            "consumer.main",
            ACTOR,
            None,
            ("capacity.fiscal",),
            eligibility=Compare("fiscal", "ge", 0.0),
            eligibility_facts=("fiscal",),
        ),
    )
    first = recompute(
        snapshot(observation("literacy", 0.2), observation("fiscal", 0.1)),
        facts,
        specs,
        actions,
        schedule(),
    )
    calls = []
    original = Compare.evaluate

    def tracked(self, values):
        calls.append(self.fact_id)
        return original(self, values)

    monkeypatch.setattr(Compare, "evaluate", tracked)
    second = recompute(
        snapshot(observation("literacy", 0.8), observation("fiscal", 0.1)),
        facts,
        specs,
        actions,
        schedule(),
        previous=first,
        changed_facts=("literacy",),
    )
    assert calls == ["literacy", "literacy"]
    assert second.facets[0].value is False
    assert second.actions[0].eligible is False
    assert second.facets[1] is first.facets[1]
    assert second.actions[1] is first.actions[1]
    assert dependency_index(specs, actions)["literacy"] == ("need.education", "school")
    calls.clear()
    assert second._basis is not None
    third = recompute(second._basis.snapshot, facts, specs, actions, schedule(), previous=second)
    assert third.actions[0] is second.actions[0]
    assert calls == []


def objective():
    return c.InterestSpec(
        "solvency",
        ACTOR,
        None,
        ("fiscal",),
        TIME,
        c.TimeIdentity("session", 3),
        observation("fiscal", 0.1),
        (),
        ("consumer.main",),
        "known",
    )


def objective_action():
    return ActionSpec(
        "school",
        "consumer.main",
        ACTOR,
        None,
        benefits=(
            AssessmentTerm(
                "gain",
                "benefit",
                "ratio",
                "country",
                0.2,
                source_ids=("literacy",),
                horizon="short",
                baseline="solvency",
            ),
        ),
        costs=(
            AssessmentTerm(
                "burden",
                "cost",
                "currency_per_week",
                "country",
                10.0,
                source_ids=("fiscal",),
                horizon="long",
            ),
        ),
        eligibility=Compare("fiscal", "ge", 0.0),
        eligibility_facts=("fiscal",),
        objective_ids=("solvency",),
    )


def test_multiround_expected_qualification_cost_and_baseline_deadline_states():
    facts = (fact("literacy"), fact("fiscal"))
    action = objective_action()
    goal = objective()
    previous = None
    # Hand-specified independent oracle: t1 baseline, t2 unavailable cost,
    # t3 native fiscal rejection, t4 deadline expired. No reference self-comparison.
    expected = (
        ("known", True, "known", 0.2, "known", 10.0),
        ("unknown", None, "unknown", None, "unknown", None),
        ("known", False, "known", 0.2, "known", 10.0),
        ("known", True, "stale", None, "known", 10.0),
    )
    for tick, fiscal, wanted in zip((1, 2, 3, 4), (0.1, None, -0.1, 0.2), expected, strict=True):
        time = c.TimeIdentity("session", tick)
        observations = (
            replace(observation("literacy", 0.2), time=time),
            replace(
                observation("fiscal", fiscal, status="known" if fiscal is not None else "unknown"),
                time=time,
            ),
        )
        snap = replace(snapshot(), time=time, observations=observations)
        current = recompute(
            snap, facts, (), (action,), schedule(), previous=previous, objectives=(goal,)
        )
        result = current.actions[0]
        assert (
            result.qualification,
            result.eligible,
            result.benefits[0].status,
            result.benefits[0].value,
            result.costs[0].status,
            result.costs[0].value,
        ) == wanted
        assert result.objective_ids == ("solvency",)
        assert (result.benefits[0].horizon, result.costs[0].horizon) == ("short", "long")
        previous = current


@pytest.mark.parametrize(
    "damage", ["baseline_value", "baseline_source", "undeclared_source", "consumer", "epoch"]
)
def test_objectives_enforce_actual_baseline_sources_and_time_binding(damage):
    goal = objective()
    snap = snapshot(observation("literacy", 0.2), observation("fiscal", 0.1))
    facts = (fact("literacy"), fact("fiscal"))
    if damage == "baseline_value":
        goal = replace(goal, baseline=replace(goal.baseline, value=0.8))
    elif damage == "baseline_source":
        goal = replace(
            goal, baseline=replace(goal.baseline, sources=(c.EvidenceRef("common/other.txt", 1),))
        )
    elif damage == "undeclared_source":
        goal = replace(goal, source_fact_ids=("fiscal", "missing"))
    elif damage == "consumer":
        goal = replace(goal, consumer_ids=("consumer.other",))
    elif damage == "epoch":
        goal = replace(
            goal,
            starts=c.TimeIdentity("other", 1),
            deadline=c.TimeIdentity("other", 3),
            baseline=replace(goal.baseline, time=c.TimeIdentity("other", 1)),
        )
    with pytest.raises(InvalidSemanticInput):
        assess_actions((objective_action(),), (), snap, facts, schedule(), (goal,))


def test_expression_dependencies_are_complete_and_arbitrary_callables_rejected():
    with pytest.raises(InvalidSemanticInput, match="未登记"):
        FacetSpec(
            "need.education",
            "need",
            "boolean",
            "country",
            ("literacy",),
            Compare("fiscal", "gt", 0.0),
        )
    with pytest.raises(InvalidSemanticInput, match="未登记"):
        ActionSpec("school", "consumer.main", ACTOR, None, eligibility=Compare("fiscal", "gt", 0.0))
    with pytest.raises(InvalidSemanticInput, match="声明 IR"):
        FacetSpec(
            "need.education",
            "need",
            "boolean",
            "country",
            ("literacy",),
            cast("FacetExpression", lambda _facts: True),
        )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (All((Compare("literacy", "gt", 0.5), Compare("fiscal", "gt", 0.0))), False),
        (AnyExpr((Compare("literacy", "lt", 0.5), Compare("fiscal", "gt", 0.0))), True),
    ],
)
@pytest.mark.parametrize("unavailable", ["unknown", "stale", "unsupported"])
def test_definite_three_valued_facet_and_eligibility_keep_partial_source_state(
    expression, expected, unavailable
):
    facts = (fact("literacy"), fact("fiscal"))
    snap = snapshot(observation("literacy", 0.2), observation("fiscal", None, status=unavailable))
    specs = (
        FacetSpec(
            "need.education", "need", "boolean", "country", ("literacy", "fiscal"), expression
        ),
    )
    facets = derive_facets(snap, facts, specs, schedule())
    assert (facets[0].status, facets[0].value) == ("known", expected)
    assert facets[0].source_statuses == (("literacy", "known"), ("fiscal", unavailable))
    action = ActionSpec(
        "school",
        "consumer.main",
        ACTOR,
        None,
        eligibility=expression,
        eligibility_facts=("literacy", "fiscal"),
    )
    result = assess_actions((action,), facets, snap, facts, schedule())[0]
    assert (result.qualification, result.eligible) == ("known", expected)
    assert result.unknowns == ("fiscal",)


@pytest.mark.parametrize(
    "damage",
    ["unit", "category", "scope", "sources", "term_kind", "term_value", "term_status", "cost_kind"],
)
def test_pure_semantic_constructors_reject_wrong_runtime_types(damage):
    facet = FacetSpec("need.education", "need", "ratio", "country", ("literacy",))
    term = AssessmentTerm("gain", "benefit", "ratio", "country", 0.2)

    def construct_invalid():
        if damage == "unit":
            return replace(facet, unit=cast("c.Unit", "bogus"))
        if damage == "category":
            return replace(facet, category=cast("FacetKind", "bogus"))
        if damage == "scope":
            return replace(facet, scope=cast("str", 123))
        if damage == "sources":
            return replace(facet, source_fact_ids=cast("tuple[str, ...]", ["literacy"]))
        if damage == "term_kind":
            return replace(term, kind=cast("Literal['benefit', 'cost']", "bogus"))
        if damage == "term_value":
            return replace(term, value=cast("c.Scalar", [0.2]))
        if damage == "term_status":
            return replace(term, status=cast("c.Knowledge", "bogus"), value=None)
        return ActionSpec("school", "consumer.main", ACTOR, None, costs=(term,))

    with pytest.raises(ValueError):
        construct_invalid()


def test_facets_cannot_be_reused_across_snapshot_contexts():
    facts = (fact("literacy"),)
    snap = snapshot(observation("literacy", 0.2))
    facets = derive_facets(
        snap,
        facts,
        (FacetSpec("need.education", "need", "ratio", "country", ("literacy",)),),
        schedule(),
    )
    foreign = c.EntityKey("country", "GER")
    changed = replace(
        snap, actor=foreign, observations=(replace(snap.observations[0], entity=foreign),)
    )
    action = ActionSpec("school", "consumer.main", foreign, None, ("need.education",))
    with pytest.raises(InvalidSemanticInput, match=r"处境.*串接"):
        assess_actions((action,), facets, changed, facts, schedule())


@pytest.mark.parametrize("unit", ["percent", "currency_per_week", "boolean"])
def test_raw_facets_reject_implicit_unit_conversion(unit):
    spec = FacetSpec("need.raw", "need", unit, "country", ("literacy",))
    with pytest.raises(InvalidSemanticInput, match="单位"):
        derive_facets(
            snapshot(observation("literacy", 0.2)), (fact("literacy"),), (spec,), schedule()
        )


def test_expression_facets_declare_boolean_result_unit():
    with pytest.raises(InvalidSemanticInput, match="boolean"):
        FacetSpec(
            "need.raw", "need", "ratio", "country", ("literacy",), Compare("literacy", "gt", 0.1)
        )


def test_expression_facets_reject_source_fact_scope_mismatch():
    target = c.EntityKey("state", "FRA-paris")
    target_fact = fact("state_gap", entity_kind="state", binding="target")
    snap = replace(
        snapshot(
            replace(
                observation("state_gap", 0.2, entity=target),
                unit="ratio",
            )
        ),
        target=target,
        aggregation="local",
    )
    spec = FacetSpec(
        "need.local",
        "need",
        "boolean",
        "country",
        ("state_gap",),
        Compare("state_gap", "gt", 0.1),
    )
    with pytest.raises(InvalidSemanticInput, match="作用域"):
        derive_facets(snap, (target_fact,), (spec,), schedule())


def test_expression_facets_accept_matching_target_binding():
    target = c.EntityKey("state", "FRA-paris")
    target_fact = fact("state_gap", entity_kind="state", binding="target")
    snap = replace(
        snapshot(
            replace(
                observation("state_gap", 0.2, entity=target),
                unit="ratio",
            )
        ),
        target=target,
        aggregation="local",
    )
    spec = FacetSpec(
        "need.local",
        "need",
        "boolean",
        "state",
        ("state_gap",),
        Compare("state_gap", "gt", 0.1),
    )
    result = derive_facets(snap, (target_fact,), (spec,), schedule())
    assert (result[0].status, result[0].value) == ("known", True)


@pytest.mark.parametrize("source_kind", ["fact", "facet"])
def test_terms_reject_numeric_source_unit_mismatch(source_kind):
    facts = (fact("literacy"),)
    snap = snapshot(observation("literacy", 0.2))
    facets = derive_facets(
        snap, facts, (FacetSpec("need.raw", "need", "ratio", "country", ("literacy",)),), schedule()
    )
    term = AssessmentTerm(
        "burden",
        "cost",
        "currency_per_week",
        "country",
        10.0,
        source_ids=("literacy" if source_kind == "fact" else "need.raw",),
    )
    action = ActionSpec("school", "consumer.main", ACTOR, None, costs=(term,))
    with pytest.raises(InvalidSemanticInput, match="单位"):
        assess_actions((action,), facets, snap, facts, schedule())


@pytest.mark.parametrize("site", ["facet", "eligibility"])
@pytest.mark.parametrize("operator", ["eq", "gt"])
def test_numeric_fact_cannot_compare_to_boolean_threshold(site, operator):
    expression = Compare("literacy", operator, True)
    facts = (fact("literacy"),)
    snap = snapshot(observation("literacy", 1.0))
    if site == "facet":
        with pytest.raises(InvalidSemanticInput, match="类型"):
            derive_facets(
                snap,
                facts,
                (FacetSpec("need.raw", "need", "boolean", "country", ("literacy",), expression),),
                schedule(),
            )
    else:
        action = ActionSpec(
            "school",
            "consumer.main",
            ACTOR,
            None,
            eligibility=expression,
            eligibility_facts=("literacy",),
        )
        with pytest.raises(InvalidSemanticInput, match="类型"):
            assess_actions((action,), (), snap, facts, schedule())


def test_known_observation_cannot_claim_undeclared_evidence():
    forged = replace(observation("literacy", 0.2), sources=(c.EvidenceRef("common/other.txt", 2),))
    with pytest.raises(InvalidSemanticInput, match="证据"):
        derive_facets(snapshot(forged), (fact("literacy"),), (), schedule())


@pytest.mark.parametrize("value", [True, "0.2"])
def test_numeric_term_unit_rejects_boolean_or_string_values(value):
    with pytest.raises(InvalidSemanticInput, match="类型与单位"):
        AssessmentTerm("gain", "benefit", "ratio", "country", value)
