"""K4 关系降低与局部联动的反例。"""

from dataclasses import replace

import pytest

from pdx import decisions
from pdx.parser import parse_text
from pdx.situated import core_contracts as c
from pdx.situated import pdx_eval, relations
from pdx.situated.compiler import load_model, strategy_overlay
from pdx.situated.schema import Relation

pytestmark = pytest.mark.unit


def test_complement_is_soft_and_conditioned_in_generated_consumer() -> None:
    model = load_model()
    overlay = strategy_overlay(model)
    text = overlay["economic_vs_government_spending_balance"]
    assert "# ACTION industrial_foundation" in text
    assert "# ACTION education_and_research" in text
    # 互补项以行动内部的条件增量出现，不能成为主行动的硬资格门。
    assert "ROOT ?= {  AND = { is_ai = yes" in text
    facts = {
        "is_ai": True,
        "is_at_war": False,
        "in_default": False,
        "any_insurrection_ongoing": False,
        "legitimacy": 60,
        "bureaucracy": 1,
        "literacy_rate": 0.3,
        "scaled_debt": 0.4,
        "net_total_income": 1,
    }
    # 工业基础 +.15；低识字教育方向 -.10、政治成本 +.02，合计 .07。
    # 需求和已实施学校观测未提供，不能假定成立。高识字使教育项退出，
    # 但识字和合法性本身不能制造学校互补。关系不成为工业资格门。
    for changes, expected in (
        ({}, 0.07),
        ({"literacy_rate": 0.6}, 0.15),
        ({"literacy_rate": 0.6, "legitimacy": 80}, 0.15),
        ({"literacy_rate": 0.6, "legitimacy": 80, "any_insurrection_ongoing": True}, 0.15),
        (
            {
                "has_law_or_variant": {(("argument", "law_type:law_public_schools"),): True},
                "has_institution": {(("argument", "institution_schools"),): True},
            },
            0.045,
        ),
        (
            {
                "literacy_rate": 0.6,
                "has_law_or_variant": {(("argument", "law_type:law_public_schools"),): True},
                "has_institution": {(("argument", "institution_schools"),): True},
            },
            0.175,
        ),
    ):
        result = pdx_eval.select(text, {**facts, **changes})
        assert result.action_id == "joint_economic_balance"
        assert result.operation == "add"
        assert result.delta == pytest.approx(expected)
    patched = decisions.patch_default(
        decisions.baseline_path().read_text(encoding="utf-8"),
        decisions.load(),
        decisions.load_extensions(profile="release"),
        action_overlay=overlay,
    )
    assert not parse_text(patched).errors


def test_duplicate_and_asymmetric_relations_fail_closed() -> None:
    model = load_model()
    first = next(item for item in model.actions if item.id == "industrial_foundation")
    duplicate = replace(first, complements=(*first.complements, "education_and_research"))
    with pytest.raises(ValueError, match="重复"):
        relations.validate((duplicate, *(item for item in model.actions if item.id != first.id)))

    asymmetric = replace(first, complements=())
    with pytest.raises(ValueError, match="对称配对"):
        relations.validate(
            (
                asymmetric,
                *(item for item in model.actions if item.id != first.id),
            )
        )


def test_observed_condition_requires_boolean_current_world_fact() -> None:
    evidence = c.EvidenceRef("common/ai/relations.txt", 1)
    actor = c.EntityKey("country", "FRA")
    time = c.TimeIdentity("session", 1)
    fact = c.FactSpec(
        "ready",
        "reader.ready",
        "boolean",
        "boolean",
        "country",
        "actor",
        ("consumer",),
        (evidence,),
    )
    schedule = c.EvaluationSchedule("schedule", "consumer", (evidence,))
    snap = c.SituationSnapshot(
        actor,
        None,
        "consumer",
        time,
        "country",
        (c.Observation("ready", actor, "boolean", "known", time, True, (evidence,)),),
        "schedule",
    )
    relation = Relation("a", "b", "enables", 1.0, "root", ("ready",), "vanilla")
    assert relations.observed_condition(relation, snap, (fact,), schedule) is True
    stale = replace(snap.observations[0], status="stale", value=None, sources=())
    assert (
        relations.observed_condition(
            relation, replace(snap, observations=(stale,)), (fact,), schedule
        )
        is None
    )


def test_observed_condition_does_not_treat_candidate_readiness_as_completion() -> None:
    evidence = c.EvidenceRef("common/ai/relations.txt", 1)
    actor = c.EntityKey("country", "FRA")
    time = c.TimeIdentity("session", 1)
    fact = c.FactSpec(
        "ready",
        "reader.ready",
        "boolean",
        "boolean",
        "country",
        "actor",
        ("consumer",),
        (evidence,),
    )
    schedule = c.EvaluationSchedule("schedule", "consumer", (evidence,))
    snap = c.SituationSnapshot(
        actor,
        None,
        "consumer",
        time,
        "country",
        (c.Observation("ready", actor, "boolean", "known", time, False, (evidence,)),),
        "schedule",
    )
    relation = Relation("a", "b", "enables", 1.0, "root", ("ready",), "vanilla")
    assert relations.observed_condition(relation, snap, (fact,), schedule) is False
