"""R2 符号行动网络的独立数值、未知与降低反例。"""

from __future__ import annotations

import itertools
import math
from dataclasses import replace
from typing import Any, Literal, cast

import pytest

from pdx.situated import action_network as n
from pdx.situated import core_contracts as c
from pdx.situated import expressions as e

CONSUMER = "a0-econ-road"
SOURCE = c.EvidenceRef("game/common/decrees/00_decree.txt", 1)
TIME = c.TimeIdentity("witness", 1)
PROOF = ("docs/design/1.15架构设计.md#6",)


def fact(
    name: str, *, boolean: bool = True, binding: Literal["actor", "target"] = "target"
) -> c.FactSpec:
    return c.FactSpec(
        name,
        f"reader.{name}",
        "boolean" if boolean else "number",
        "boolean" if boolean else "points",
        "state",
        binding,
        (CONSUMER,),
        (SOURCE,),
    )


def action(*, target: str = "state-a", operation: n.Operation = "add") -> n.ActionInstance:
    definition = n.ActionDefinition(
        "road-maintenance",
        CONSUMER,
        operation,
        "consumer_score" if operation == "add" else "multiplier",
        "state",
        0.0 if operation == "add" else 1.0,
        -4.0 if operation == "add" else 0.1,
        4.0,
    )
    return n.ActionInstance(
        definition, c.EntityKey("country", "AAA"), c.EntityKey("state", target), TIME
    )


def account(name: str, *, operation: n.Operation = "add", **kwargs) -> n.EffectAccount:
    return n.EffectAccount(
        name,
        f"mechanism.{name}",
        "marginal-effect",
        CONSUMER,
        "consumer_score" if operation == "add" else "multiplier",
        "current",
        "native-current",
        PROOF,
        **kwargs,
    )


def bridge(
    name: str,
    effect: str,
    value: float,
    source: str,
    *,
    actor: n.ActionInstance | None = None,
    group: str | None = None,
    condition: e.Expression | None = None,
    kind: n.TermKind = "benefit",
    path: n.PathKind = "direct",
    required: bool = True,
    variant: str | None = None,
    rank: int = 0,
) -> n.ActionBridge:
    group_id = group or f"group.{name}"
    predicate = condition if condition is not None else e.Compare(source, "eq", True)
    facts = tuple(sorted(n._expression_facts(predicate)))
    return n.ActionBridge(
        f"bridge.{name}",
        actor or action(),
        path,
        effect,
        n.AssessmentTerm(
            f"term.{name}",
            effect,
            kind,
            n.Constant(value),
            group_id,
            required,
            variant,
            rank,
            PROOF if variant else (),
        ),
        (source,),
        predicate,
        facts,
    )


def network(
    bridges: tuple[n.ActionBridge, ...],
    facts: tuple[c.FactSpec, ...],
    *,
    accounts: tuple[n.EffectAccount, ...] | None = None,
    registry: n.EffectRegistry | None = None,
    groups: tuple[n.AssessmentGroup, ...] | None = None,
    **kwargs,
) -> n.ActionNetwork:
    actions = {item.action.key: item.action for item in bridges}
    if accounts is None:
        accounts = tuple(
            account(name, operation=bridges[0].action.definition.operation)
            for name in sorted({item.effect_id for item in bridges})
        )
    if groups is None:
        group_ids = sorted({item.term.group_id for item in bridges})
        groups = tuple(
            n.AssessmentGroup(
                name,
                tuple(item.term.id for item in bridges if item.term.group_id == name),
                review_sources=PROOF,
            )
            for name in group_ids
        )
    return n.ActionNetwork(
        tuple(actions.values()),
        bridges,
        groups,
        registry or n.EffectRegistry(accounts),
        facts,
        **kwargs,
    )


def compile_net(*args, **kwargs) -> n.NetworkProgram:
    return n.compile_action_network(network(*args, **kwargs))


def test_direct_and_derived_have_the_same_production_guard_and_value():
    direct = bridge("direct", "need", 3.0, "gap")
    derived = replace(
        direct,
        id="derived",
        path="derived",
        source_ids=("gap-facet",),
        condition=e.Compare("gap-facet", "eq", True),
        condition_fact_ids=("gap-facet",),
    )
    p1 = compile_net((direct,), (fact("gap"),))
    p2 = compile_net(
        (derived,),
        (fact("gap"),),
        predicates=(n.DerivedPredicate("gap-facet", e.Compare("gap", "eq", True), ("gap",)),),
    )
    for value in (True, False, None):
        assert (
            n.evaluate_network(p1, {"gap": value}).total
            == n.evaluate_network(p2, {"gap": value}).total
        )
    low1 = n.specialize_program(p1, ("gap",)).contributions[0]
    low2 = n.specialize_program(p2, ("gap",)).contributions[0]
    assert (low1.guard, low1.value) == (low2.guard, low2.value)
    assert p2.contributions[0].lineage.derivations == ("gap-facet",)
    assert f"{SOURCE.source}:{SOURCE.line}" in p2.contributions[0].lineage.sources


def test_three_paths_mix_without_ignoring_opposing_cost():
    items = (
        bridge("need", "need-effect", 3.0, "gap"),
        bridge("capacity", "capacity-effect", -2.0, "fiscal", kind="cost", path="derived"),
        bridge("supply", "supply-effect", 1.0, "observed-supply", path="interaction"),
    )
    program = compile_net(items, tuple(fact(name) for name in ("gap", "fiscal", "observed-supply")))
    assert (
        n.evaluate_network(program, {"gap": True, "fiscal": True, "observed-supply": True}).total
        == 2
    )
    assert n.evaluate_network(program, {"gap": True, "fiscal": True}).total == 1


def test_renamed_reader_and_effect_alias_do_not_reward_the_same_gap_twice():
    original = bridge("one", "gap-effect", 3.0, "gap")
    alias = bridge("two", "gap-alias", 3.0, "gap-alias-reader")
    registry = n.EffectRegistry(
        (account("gap-effect"),), (n.EffectAlias("gap-alias", "gap-effect", PROOF),)
    )
    program = compile_net(
        (original, alias),
        (fact("gap"),),
        registry=registry,
        fact_aliases=(("gap-alias-reader", "gap"),),
    )
    assert len(program.contributions) == 1
    assert n.evaluate_network(program, {"gap": True}).unbounded == 3
    with pytest.raises(ValueError, match="矛盾"):
        n.evaluate_network(program, {"gap": True, "gap-alias-reader": False})


def test_changing_account_id_cannot_duplicate_one_canonical_mechanism():
    first = account("first")
    with pytest.raises(ValueError, match="换名"):
        n.EffectRegistry((first, replace(first, id="second")))


def test_unreviewed_shared_evidence_cannot_accumulate():
    positive = bridge("security", "military-need", 3.0, "war")
    cost = bridge("fiscal", "war-cost", -2.0, "war", kind="cost")
    with pytest.raises(ValueError, match="重叠证据未审查"):
        compile_net((positive, cost), (fact("war"),))
    registry = n.EffectRegistry(
        (account("military-need"), account("war-cost")),
        overlaps=(n.OverlapReview("military-need", "war-cost", "independent", PROOF),),
    )
    program = compile_net((positive, cost), (fact("war"),), registry=registry)
    assert n.evaluate_network(program, {"war": True}).total == 1


def test_unknown_essential_cost_withdraws_its_group_but_keeps_independent_recovery():
    items = (
        bridge("education", "education-effect", 3.0, "illiteracy", group="education"),
        bridge(
            "school-cost", "school-cost-effect", -1.0, "cost-known", group="education", kind="cost"
        ),
        bridge("recovery", "recovery-effect", 2.0, "recovery"),
    )
    program = compile_net(
        items, tuple(fact(name) for name in ("illiteracy", "cost-known", "recovery"))
    )
    unknown = n.evaluate_network(program, {"illiteracy": True, "recovery": True})
    assert unknown.total == 2
    assert unknown.unknown_groups == ("education",)
    assert (
        n.evaluate_network(
            program, {"illiteracy": True, "cost-known": True, "recovery": True}
        ).unbounded
        == 4
    )


def test_known_false_condition_differs_from_unknown_condition():
    items = (
        bridge("need", "need-effect", 3.0, "need", group="evaluation"),
        bridge("penalty", "penalty-effect", -1.0, "expensive", group="evaluation", kind="cost"),
    )
    program = compile_net(items, (fact("need"), fact("expensive")))
    assert n.evaluate_network(program, {"need": True, "expensive": False}).total == 3
    assert n.evaluate_network(program, {"need": True}).total == 0


def test_stronger_unknown_variant_keeps_the_complete_known_low_tier():
    low = bridge("low", "need", 1.0, "low", variant="severity", rank=1)
    high = bridge("high", "need", 3.0, "high", variant="severity", rank=2)
    program = compile_net((low, high), (fact("low"), fact("high")))
    assert n.evaluate_network(program, {"low": True}).total == 1
    assert n.evaluate_network(program, {"low": True, "high": True}).total == 3
    assert n.evaluate_network(program, {"low": False, "high": True}).total == 3


def test_cost_variant_strength_is_not_numeric_max_or_kind_based_negation():
    low = bridge("low", "cost", -1.0, "low", kind="cost", variant="pressure", rank=1)
    high = bridge("high", "cost", -3.0, "high", kind="cost", variant="pressure", rank=2)
    program = compile_net((low, high), (fact("low"), fact("high")))
    assert n.evaluate_network(program, {"low": True, "high": True}).total == -3


def test_same_effect_opposing_estimates_are_not_cancelled_into_known_zero():
    low = bridge("positive", "effect", 2.0, "a", variant="contradiction", rank=1)
    high = bridge("negative", "effect", -2.0, "b", variant="contradiction", rank=2)
    with pytest.raises(ValueError, match="不能抵消矛盾"):
        compile_net((low, high), (fact("a"), fact("b")))


def test_replacement_activates_only_when_complete_and_restores_known_base():
    base = bridge("base", "base-effect", 3.0, "gap")
    full = bridge("full", "full-effect", 5.0, "market")
    registry = n.EffectRegistry((account("base-effect"), account("full-effect")))
    replacement = n.Replacement(
        "joint", ("base-effect",), "full-effect", e.Compare("market", "eq", True), ("market",)
    )
    program = compile_net(
        (base, full), (fact("gap"), fact("market")), registry=registry, replacements=(replacement,)
    )
    assert n.evaluate_network(program, {"gap": True, "market": True}).unbounded == 5
    restored = n.evaluate_network(program, {"gap": True})
    assert restored.unbounded == 3
    assert not restored.active_replacements
    assert n.evaluate_network(program, {"gap": True, "market": False}).unbounded == 3


def test_replacement_failure_cannot_restore_an_incomplete_basic_reward():
    base = bridge("base", "base-effect", 3.0, "gap", group="base-group")
    cost = bridge("cost", "cost-effect", -1.0, "cost-known", kind="cost", group="base-group")
    full = bridge("full", "full-effect", 5.0, "market")
    replacement = n.Replacement("joint", ("base-effect", "cost-effect"), "full-effect")
    program = compile_net(
        (base, cost, full),
        (fact("gap"), fact("cost-known"), fact("market")),
        replacements=(replacement,),
    )
    result = n.evaluate_network(program, {"gap": True})
    assert result.total == 0
    assert "base-group" in result.unknown_groups


@pytest.mark.parametrize(
    ("operation", "base", "complete", "extra"),
    [("add", 3.0, 5.0, 2.0), ("multiply", 1.3, 1.5, 1.5 / 1.3)],
)
def test_residual_is_in_the_already_mapped_consumer_algebra(operation, base, complete, extra):
    instance = action(operation=operation)
    items = (
        bridge("base", "base-effect", base, "gap", actor=instance),
        bridge("extra", "extra-effect", extra, "market", actor=instance, path="interaction"),
    )
    residual = n.Residual("joint", ("base-effect",), "extra-effect", n.Constant(complete), PROOF)
    program = compile_net(items, (fact("gap"), fact("market")), residuals=(residual,))
    assert math.isclose(
        n.evaluate_network(program, {"gap": True, "market": True}).unbounded, complete
    )
    assert n.evaluate_network(program, {"gap": True}).unbounded == base
    assert math.isclose(n.mapped_residual(base, complete, operation), extra)


def test_raw_nonlinear_residual_or_multiplier_difference_is_rejected():
    items = (
        bridge("base", "base-effect", 9.0, "gap"),
        bridge("extra", "extra-effect", 2.0, "market"),
    )
    with pytest.raises(ValueError, match="已映射"):
        compile_net(
            items,
            (fact("gap"), fact("market")),
            residuals=(
                n.Residual("joint", ("base-effect",), "extra-effect", n.Constant(25), PROOF),
            ),
        )
    with pytest.raises(ValueError, match="正的非零"):
        n.mapped_residual(0.0, 2.0, "multiply")


def test_replacement_cannot_mix_horizon_or_baseline():
    base = bridge("base", "base-effect", 3.0, "gap")
    full = bridge("full", "full-effect", 5.0, "market")
    registry = n.EffectRegistry(
        (account("base-effect"), replace(account("full-effect"), horizon="long"))
    )
    with pytest.raises(ValueError, match="期限"):
        compile_net(
            (base, full),
            (fact("gap"), fact("market")),
            registry=registry,
            replacements=(n.Replacement("joint", ("base-effect",), "full-effect"),),
        )


def test_shared_marginal_cost_across_goals_is_counted_once():
    education = bridge("education", "education-effect", 2.0, "education", group="education")
    science = bridge("science", "science-effect", 2.0, "science", group="science")
    cost1 = bridge("cost-one", "cost-effect", -1.0, "cost", group="education", kind="cost")
    cost2 = bridge("cost-two", "cost-effect", -1.0, "cost", group="science", kind="cost")
    program = compile_net(
        (education, science, cost1, cost2), (fact("education"), fact("science"), fact("cost"))
    )
    assert len(program.contributions) == 3
    assert (
        n.evaluate_network(program, {"education": True, "science": True, "cost": True}).unbounded
        == 3
    )
    assert n.evaluate_network(program, {"education": True, "science": True}).unbounded == 0


def test_other_candidates_do_not_receive_a_free_cost():
    first, second = action(), action(target="state-b")
    items = (
        bridge("cost-a", "cost-effect", -2.0, "cost", actor=first, kind="cost"),
        bridge("cost-b", "cost-effect", -2.0, "cost", actor=second, kind="cost"),
    )
    program = compile_net(items, (fact("cost"),))
    with pytest.raises(ValueError, match="多候选"):
        n.evaluate_network(program, {"cost": True})
    assert n.evaluate_network(program, {"cost": True}, action=first).total == -2
    assert n.evaluate_network(program, {"cost": True}, action=second).total == -2


def test_complete_candidate_binding_signature_is_stable_and_distinguishes_buildings():
    original = action()
    a = replace(
        original,
        bindings=(("building", c.EntityKey("building", "a")), ("law", c.EntityKey("law", "x"))),
    )
    reordered = replace(a, bindings=tuple(reversed(a.bindings)))
    b = replace(
        a, bindings=(("building", c.EntityKey("building", "b")), ("law", c.EntityKey("law", "x")))
    )
    assert a.key == reordered.key
    assert a.key != b.key
    assert a.key != replace(a, definition=replace(a.definition, id="other-action")).key


def test_independent_costs_participate_before_only_one_final_bound():
    items = (
        bridge("benefit", "benefit-effect", 20.0, "need"),
        bridge("cost", "cost-effect", -19.0, "burden", kind="cost"),
    )
    program = compile_net(items, (fact("need"), fact("burden")))
    result = n.evaluate_network(program, {"need": True, "burden": True})
    assert (result.unbounded, result.total) == (1, 1)


def test_source_observations_enforce_scope_time_status_and_finite_types():
    item = bridge("need", "need-effect", 3.0, "gap")
    program = compile_net((item,), (fact("gap"),))
    assert item.action.target is not None
    good = c.Observation("gap", item.action.target, "boolean", "known", TIME, True, (SOURCE,))
    assert n.evaluate_observations(program, (good,)).total == 3
    assert n.evaluate_observations(program, (replace(good, status="stale"),)).total == 0
    with pytest.raises(ValueError, match="对象"):
        n.evaluate_observations(program, (replace(good, entity=c.EntityKey("state", "state-b")),))
    with pytest.raises(ValueError, match="时间"):
        n.evaluate_observations(program, (replace(good, time=c.TimeIdentity("witness", 2)),))
    with pytest.raises(ValueError, match="类型"):
        n.evaluate_network(program, {"gap": 1})


def test_sparse_dag_cycle_and_score_as_fact_are_rejected():
    item = replace(bridge("need", "need-effect", 3.0, "a"), path="derived")
    nodes = (
        n.DerivedPredicate("a", e.Compare("b", "eq", True), ("b",)),
        n.DerivedPredicate("b", e.Compare("a", "eq", True), ("a",)),
    )
    with pytest.raises(ValueError, match="同轮循环"):
        compile_net((item,), (), predicates=nodes)
    with pytest.raises(ValueError, match="候选分数"):
        compile_net(
            (
                replace(
                    item,
                    source_ids=(item.id,),
                    condition=e.Compare(item.id, "eq", True),
                    condition_fact_ids=(item.id,),
                ),
            ),
            (),
        )


def test_sparse_compilation_never_generates_condition_subsets():
    count = 30
    items = tuple(bridge(f"term-{i}", f"effect-{i}", 1.0, f"fact-{i}") for i in range(count))
    facts = tuple(fact(f"fact-{i}") for i in range(count))
    program = compile_net(items, facts)
    specialized = n.specialize_program(program, tuple(item.id for item in facts))
    assert len(program.contributions) == len(specialized.contributions) == count
    with pytest.raises(ValueError, match="预算"):
        compile_net(items, facts, budget=n.NetworkBudget(max_bridges=20))
    with pytest.raises(ValueError, match="guard"):
        compile_net(items, facts, budget=n.NetworkBudget(max_guard_nodes=4))


def test_specialized_guards_match_reference_for_partial_readers():
    condition = e.Any(
        (
            e.Compare("a", "eq", True),
            e.All((e.Compare("b", "eq", True), e.Not(e.Compare("c", "eq", True)))),
        )
    )
    item = bridge("need", "need-effect", 3.0, "a", condition=condition)
    program = compile_net((item,), (fact("a"), fact("b"), fact("c")))
    for values in itertools.product((True, False, None), repeat=3):
        raw: dict[str, object | None] = dict(zip(("a", "b", "c"), values, strict=True))
        known = tuple(name for name, value in raw.items() if value is not None)
        lowered = n.specialize_program(program, known)
        actual = sum(
            (item.value for item in lowered.contributions if item.guard.evaluate(raw) is True), 0.0
        )
        assert actual == n.evaluate_network(program, raw).unbounded


def test_reordering_rules_groups_and_registry_is_semantically_stable():
    items = (bridge("a", "effect-a", 3.0, "a"), bridge("b", "effect-b", -1.0, "b", kind="cost"))
    model = network(items, (fact("a"), fact("b")))
    reversed_model = replace(
        model,
        bridges=tuple(reversed(model.bridges)),
        groups=tuple(reversed(model.groups)),
        registry=replace(model.registry, accounts=tuple(reversed(model.registry.accounts))),
    )
    p1, p2 = n.compile_action_network(model), n.compile_action_network(reversed_model)
    assert p1.contributions == p2.contributions
    assert n.evaluate_network(p1, {"a": True, "b": True}) == n.evaluate_network(
        p2, {"a": True, "b": True}
    )


def test_arbitrary_python_expression_and_nonfinite_or_boolean_numbers_are_rejected():
    class Arbitrary:
        def evaluate(self, facts):
            return True

    with pytest.raises(ValueError, match="任意 Python"):
        replace(
            bridge("need", "need-effect", 1, "gap"), condition=Arbitrary(), condition_fact_ids=()
        )
    with pytest.raises(ValueError, match="有限数"):
        n.Constant(math.inf)
    with pytest.raises(ValueError, match="bool"):
        n.Constant(True)


def test_undeclared_or_unsupported_reader_is_never_granted_by_specialization():
    program = compile_net((bridge("need", "need-effect", 3, "gap"),), (fact("gap"),))
    assert not any(
        item.guard.evaluate({}) is True for item in n.specialize_program(program, ()).contributions
    )
    with pytest.raises(ValueError, match="授予"):
        n.specialize_program(program, ("secret-engine-state",))


def test_required_fact_guard_prevents_empty_cost_condition_from_becoming_free():
    item = bridge("benefit", "benefit-effect", 3, "need")
    group = n.AssessmentGroup(
        item.term.group_id, (item.term.id,), required_fact_ids=("cost",), review_sources=PROOF
    )
    program = compile_net((item,), (fact("need"), fact("cost", boolean=False)), groups=(group,))
    assert n.evaluate_network(program, {"need": True}).total == 0
    assert n.evaluate_network(program, {"need": True, "cost": 3.0}).total == 3


def test_wrong_consumer_or_mapped_unit_is_rejected():
    item = bridge("need", "need-effect", 3, "gap")
    with pytest.raises(ValueError, match="单位"):
        compile_net(
            (item,),
            (fact("gap"),),
            registry=n.EffectRegistry((replace(account("need-effect"), unit="people"),)),
        )
    with pytest.raises(ValueError, match="neutral"):
        replace(item.action.definition, neutral=1)


def test_missing_basis_evidence_never_turns_a_constant_condition_into_a_free_reward():
    item = bridge("need", "need-effect", 3, "basis", condition=e.BooleanLiteral(True))
    program = compile_net((item,), (fact("basis"),))
    assert n.evaluate_network(program, {}).total == 0
    assert n.evaluate_network(program, {"basis": False}).total == 3
    assert n.specialize_program(program, ()).contributions[0].guard.evaluate({}) is False
    false_condition = replace(item, condition=e.BooleanLiteral(False))
    result = n.evaluate_network(compile_net((false_condition,), (fact("basis"),)), {})
    assert result.total == 0
    assert not result.unknown_groups


def test_short_circuit_knownness_does_not_require_every_condition_root():
    item = bridge(
        "need",
        "need-effect",
        3,
        "a",
        condition=e.Any((e.Compare("a", "eq", True), e.Compare("b", "eq", True))),
    )
    program = compile_net((item,), (fact("a"), fact("b")))
    assert n.evaluate_network(program, {"b": True}).total == 3
    assert n.evaluate_network(program, {"a": False}).total == 0
    assert n.evaluate_network(program, {"b": True}).unknown_groups == ()


@pytest.mark.parametrize("value", [False, None])
def test_residual_cannot_activate_without_its_actual_base(value):
    items = (bridge("base", "base-effect", 3, "gap"), bridge("extra", "extra-effect", 2, "market"))
    program = compile_net(
        items,
        (fact("gap"), fact("market")),
        residuals=(n.Residual("joint", ("base-effect",), "extra-effect", n.Constant(5), PROOF),),
    )
    assert n.evaluate_network(program, {"gap": value, "market": True}).total == 0
    lowered = n.specialize_program(program, ("gap", "market") if value is False else ("market",))
    assert not any(
        item.guard.evaluate({"gap": value, "market": True}) is True
        for item in lowered.contributions
    )


def test_replacement_condition_requires_a_declared_compatible_reader():
    base = bridge("base", "base-effect", 3, "gap")
    full = bridge("full", "full-effect", 5, "market")
    replacement = n.Replacement(
        "joint", ("base-effect",), "full-effect", e.Compare("secret", "eq", True), ("secret",)
    )
    with pytest.raises(ValueError, match="未声明事实"):
        compile_net((base, full), (fact("gap"), fact("market")), replacements=(replacement,))
    with pytest.raises(ValueError, match="消费者"):
        compile_net(
            (base, full),
            (
                fact("gap"),
                fact("market"),
                replace(fact("secret"), consumer_ids=("other-consumer",)),
            ),
            replacements=(replacement,),
        )


def test_expression_comparison_types_are_checked_before_lowering():
    numeric = bridge("numeric", "effect", 3, "points")
    with pytest.raises(ValueError, match="类型"):
        compile_net((numeric,), (fact("points", boolean=False),))
    boolean = bridge("boolean", "effect", 3, "flag", condition=e.Compare("flag", "eq", 1))
    with pytest.raises(ValueError, match="类型"):
        compile_net((boolean,), (fact("flag"),))


def test_exponential_derived_expression_is_rejected_before_expansion():
    predicates = [n.DerivedPredicate("p0", e.Compare("root", "eq", True), ("root",))]
    for i in range(1, 20):
        previous = f"p{i - 1}"
        predicates.append(
            n.DerivedPredicate(
                f"p{i}",
                e.All((e.Compare(previous, "eq", True), e.Not(e.Compare(previous, "eq", False)))),
                (previous,),
            )
        )
    item = bridge("need", "need-effect", 3, "p19")
    with pytest.raises(ValueError, match="预展开预算"):
        compile_net(
            (item,),
            (fact("root"),),
            predicates=tuple(predicates),
            budget=n.NetworkBudget(max_depth=64),
        )


def test_registered_action_definition_cannot_be_swapped_by_reusing_its_key():
    item = bridge("need", "need-effect", 3, "gap")
    program = compile_net((item,), (fact("gap"),))
    forged = replace(
        item.action,
        definition=replace(
            item.action.definition, operation="multiply", unit="multiplier", neutral=1, lower=0.1
        ),
    )
    assert item.action.key == forged.key
    with pytest.raises(ValueError, match="定义不一致"):
        n.evaluate_network(program, {"gap": True}, action=forged)
    with pytest.raises(ValueError, match="定义不一致"):
        n.compile_action_network(replace(program.network, bridges=(replace(item, action=forged),)))


def test_replacement_cannot_use_another_candidates_completeness_group():
    first, second = action(), action(target="state-b")
    base = bridge("base", "base-effect", 3, "gap", actor=first)
    full = bridge("full", "full-effect", 5, "market", actor=first)
    unrelated = bridge("unrelated", "other-effect", 1, "other", actor=second)
    replacement = n.Replacement(
        "joint", ("base-effect",), "full-effect", required_group_ids=(unrelated.term.group_id,)
    )
    with pytest.raises(ValueError, match="其它候选"):
        compile_net(
            (base, full, unrelated),
            (fact("gap"), fact("market"), fact("other")),
            replacements=(replacement,),
        )


def test_resource_and_outcome_bindings_keep_cost_accounts_separate():
    first = replace(action(), bindings=(("resource", c.EntityKey("good", "iron")),))
    second = replace(action(), bindings=(("resource", c.EntityKey("good", "wood")),))
    items = (
        bridge("first", "cost", -2, "price", actor=first),
        bridge("second", "cost", -2, "price", actor=second),
    )
    program = compile_net(items, (fact("price"),))
    assert len(program.contributions) == 2
    assert program.contributions[0].effect.key != program.contributions[1].effect.key


def test_mutable_and_boolean_schema_declarations_are_rejected():
    model = network((bridge("need", "need-effect", 3, "gap"),), (fact("gap"),))
    with pytest.raises(ValueError, match="不可变"):
        replace(model, bridges=cast("Any", list(model.bridges)))
    with pytest.raises(ValueError, match="R2"):
        replace(model, schema_version=cast("Any", True))
