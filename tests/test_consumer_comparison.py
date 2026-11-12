"""A3 relative comparison preserves dimensions, unknowns and native semantics."""

from dataclasses import replace

import pytest
from test_core_contracts import consumer

from pdx.situated import core_contracts as c
from pdx.situated.programs import compare_candidates
from pdx.situated.semantic_core import ActionAssessment, AssessmentTerm

ACTOR = c.EntityKey("country", "FRA")
TIME = c.TimeIdentity("session", 1)


def assessment(name, gain, cost, *, eligible=True, status="known"):
    candidate = c.EntityKey("state", name)
    return candidate, ActionAssessment(
        name,
        consumer().id,
        ACTOR,
        candidate,
        (AssessmentTerm("gain", "benefit", "ratio", "state", gain),),
        (AssessmentTerm("cost", "cost", "currency_per_week", "country", cost, status),),
        "known",
        eligible,
        (),
        (),
        (),
        snapshot_identity=(ACTOR, candidate, consumer().id, TIME),
    )


def test_pareto_comparison_keeps_cost_tradeoff_and_native_ties():
    pairs = [
        assessment("a", 0.2, 10.0),
        assessment("b", 0.1, 10.0),
        assessment("c", 0.2, 20.0),
        assessment("d", 0.3, 30.0),
        assessment("tie", 0.2, 10.0),
    ]
    items = dict(pairs)
    result = compare_candidates(consumer(), tuple(items), items)
    assert {item.id for item in result.dominated} == {"b", "c"}
    assert {item.id for item in result.non_dominated} == {"a", "d", "tie"}
    assert not result.deferred
    assert result.witness.tie_break == consumer().tie_break
    assert result.witness.random == consumer().random
    assert result.witness.all_zero == consumer().all_zero
    reverse = compare_candidates(consumer(), tuple(reversed(items)), items)
    assert set(reverse.non_dominated) == set(result.non_dominated)


def test_unknown_cost_is_deferred_and_never_free():
    candidate, item = assessment("unknown", 0.9, None, status="unknown")
    result = compare_candidates(consumer(), (candidate,), {candidate: item})
    assert result.deferred == (candidate,)
    assert result.non_dominated == ()
    assert result.witness.eligible == (candidate,)


@pytest.mark.parametrize("damage", ["consumer", "actor", "target", "time", "missing_snapshot"])
def test_comparison_rejects_identity_stitching(damage):
    a, first = assessment("a", 0.2, 10.0)
    b, second = assessment("b", 0.1, 10.0)
    if damage == "consumer":
        second = replace(second, consumer_id="other")
    elif damage == "actor":
        second = replace(second, actor=c.EntityKey("country", "GER"))
    elif damage == "target":
        second = replace(second, target=a)
    elif damage == "time":
        second = replace(
            second, snapshot_identity=(ACTOR, b, consumer().id, c.TimeIdentity("session", 2))
        )
    else:
        second = replace(second, snapshot_identity=None)
    with pytest.raises(ValueError):
        compare_candidates(consumer(), (a, b), {a: first, b: second})


def test_different_units_or_horizons_are_not_added_or_ranked():
    a, first = assessment("a", 0.2, 10.0)
    b, second = assessment("b", 0.1, 10.0)
    second = replace(second, benefits=(replace(second.benefits[0], horizon="long"),))
    result = compare_candidates(consumer(), (a, b), {a: first, b: second})
    assert result.non_dominated == (a, b)
    assert not result.dominated


@pytest.mark.parametrize("first_sources", [("literacy",), ()])
def test_different_term_sources_are_not_ranked_as_the_same_benefit(first_sources):
    a, first = assessment("a", 0.2, 10.0)
    b, second = assessment("b", 0.1, 10.0)
    first = replace(first, benefits=(replace(first.benefits[0], source_ids=first_sources),))
    second = replace(second, benefits=(replace(second.benefits[0], source_ids=("production",)),))
    result = compare_candidates(consumer(), (a, b), {a: first, b: second})
    assert result.non_dominated == (a, b)
    assert result.dominated == ()
    assert result.deferred == ()


def test_term_source_order_does_not_change_semantic_dimension_identity():
    a, first = assessment("a", 0.2, 10.0)
    b, second = assessment("b", 0.1, 10.0)
    first = replace(
        first, benefits=(replace(first.benefits[0], source_ids=("literacy", "fiscal")),)
    )
    second = replace(
        second, benefits=(replace(second.benefits[0], source_ids=("fiscal", "literacy")),)
    )
    result = compare_candidates(consumer(), (a, b), {a: first, b: second})
    assert result.non_dominated == (a,)
    assert result.dominated == (b,)


def test_distinct_sources_cannot_hide_duplicate_comparison_terms():
    candidate, item = assessment("a", 0.2, 10.0)
    item = replace(
        item,
        benefits=(
            replace(item.benefits[0], source_ids=("literacy",)),
            replace(item.benefits[0], source_ids=("production",)),
        ),
    )
    with pytest.raises(ValueError, match="重复比较项"):
        compare_candidates(consumer(), (candidate,), {candidate: item})
