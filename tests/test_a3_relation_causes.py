"""Causal relation copies affect the real common scalar program only once."""

from dataclasses import replace

import pytest

from pdx.situated import compiler, decision_ir, pdx_eval, ports, relations
from pdx.situated.schema import ConsumerContract, EvidenceSpec, Relation

pytestmark = pytest.mark.unit


def _model(
    *,
    second_cause="knowledge",
    second_origins=("reader:schools",),
    variant=False,
    scope="root",
    unknown="vanilla",
):
    rows = []
    for name in ("a", "b"):
        link = Relation(
            name,
            "target",
            "complements",
            0.3 if name == "a" else 0.2,
            scope,
            ("completed",),
            unknown,
            "knowledge" if name == "a" else second_cause,
            ("reader:schools",) if name == "a" else second_origins,
        )
        rows.append(
            decision_ir.ConsumerDecisionIR(
                name,
                "test",
                "c",
                "field_c",
                "add",
                (),
                (),
                (),
                (),
                5,
                5,
                "retain",
                "vanilla",
                (),
                requires_all=(f"need_{name}",),
                base=1.0,
                relations=(link,),
                variant_group="variant" if variant else "",
                variant_priority=(1 if name == "a" else 2) if variant else 0,
            )
        )
    target = replace(
        rows[0],
        action_id="target",
        consumer_id="d",
        field="field_d",
        relations=(),
        base=0.0,
        requires_all=("target",),
        variant_group="",
        variant_priority=0,
    )
    rows.append(target)
    consumers = (
        ConsumerContract("c", "field_c", "test", 5, 3, "retain"),
        ConsumerContract("d", "field_d", "test", 5, 3, "retain"),
    )
    facts = tuple(
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
        for name in ("need_a", "need_b", "target", "completed")
    )
    writers = tuple(
        decision_ir.WriterDecisionIR(
            f"card_{row.action_id}",
            "action_card",
            "mod/decisions/actions.toml",
            row.action_id,
            row.consumer_id,
            row.field,
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
        consumers,
        (),
        (),
        {},
        decision_ir=tuple(rows),
        consumer_ir=decision_ir.ConsumerIRBundle(1, tuple(rows), writers),
    )


def _check(model, completed, expected, *, need_a=True, need_b=True, enabled=None):
    values = {"need_a": need_a, "need_b": need_b, "target": False, "completed": completed}
    result = compiler.evaluate_actions(model, values, is_ai=True, enabled_consumer_fields=enabled)
    assert result["field_c"][1] == pytest.approx(expected)
    text = compiler.strategy_overlay(model, enabled_consumer_fields=enabled)["field_c"]
    assert pdx_eval.select(text, {**values, "is_ai": True}).delta == pytest.approx(expected)


@pytest.mark.parametrize(("completed", "expected"), [(True, 2.3), (False, 2.0), (None, 2.0)])
def test_same_cause_different_paths_take_only_strongest_proven_contribution(completed, expected):
    _check(_model(), completed, expected)


def test_unknown_path_owner_falls_to_known_copy_and_closed_dependency_removes_only_relation():
    model = _model()
    _check(model, True, 1.2, need_a=None)
    _check(model, True, 2.0, enabled={"field_c"})


def test_shared_raw_origin_does_not_merge_independent_explicit_causes():
    _check(_model(second_cause="independent_school_risk"), True, 2.5)


def test_same_cause_cannot_claim_different_origin_closures():
    with pytest.raises(ValueError, match="因果身份"):
        compiler.strategy_overlay(_model(second_origins=("reader:other",)))


@pytest.mark.parametrize(
    ("scope", "unknown"),
    [("target_country", "vanilla"), ("owner", "vanilla"), ("root", "conservative")],
)
def test_unsupported_scope_or_unknown_policy_is_rejected_before_numeric_lowering(scope, unknown):
    with pytest.raises(ValueError, match="尚未实现"):
        compiler.strategy_overlay(_model(scope=scope, unknown=unknown))


@pytest.mark.parametrize(
    ("completed", "need_b", "expected"),
    [(True, True, 1.2), (False, True, 1.0), (None, True, 1.0), (True, None, 1.3)],
)
def test_only_selected_variant_relation_contributes_in_reference_and_pdx(
    completed, need_b, expected
):
    # b has higher priority: its base 1 + .2 relation; unknown b selects a's 1 + .3.
    _check(_model(variant=True), completed, expected, need_b=need_b)


def test_alias_origin_closures_normalize_without_inventing_cause_from_shared_source():
    first = Relation(
        "a",
        "b",
        "complements",
        0.1,
        condition_facts=("world",),
        cause_id="same",
        origins=("alias_one",),
    )
    second = replace(first, source="c", origins=("alias_two",))
    bound = relations.bind_origins(
        (first, second),
        {"alias_one": ("canonical",), "alias_two": ("canonical",), "world": ("canonical",)},
    )
    assert bound[0].origins == bound[1].origins == ("canonical",)
    assert bound[0].cause_id == bound[1].cause_id == "same"
    with pytest.raises(ValueError, match="未知来源"):
        relations.bind_origins((first,), {})
    with pytest.raises(ValueError, match="真实条件闭包"):
        relations.bind_origins((first,), {"world": ("world",), "alias_one": ("other",)})


def test_conditioned_production_metadata_cannot_omit_causal_contract():
    raw = {
        "source": "a",
        "target": "b",
        "kind": "complements",
        "strength": 0.2,
        "condition_facts": ["observed"],
    }
    with pytest.raises(ValueError, match="显式声明"):
        relations.relations((), (raw,))


def test_existing_world_relations_are_bound_to_actual_typed_port_origin_closures():
    model = compiler.load_model()
    graph = model.port_graph
    assert isinstance(graph, ports.PortGraph)
    expected = {
        "school_knowledge_foundation": (
            "current_public_schools",
            "schools_present",
            "literacy_ready",
        ),
        "school_education_channel": ("current_public_schools", "schools_present", "literacy_low"),
    }
    for relation in model.relations:
        names = expected[relation.cause_id]
        origins = {origin.identity for name in names for origin in graph.origins(name)}
        assert set(relation.origins) == origins
        assert relation.scope == "root"
        assert relation.unknown_policy == "vanilla"
