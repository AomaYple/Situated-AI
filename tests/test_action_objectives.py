"""Current-evaluation objectives bind actual observations and lower real guards."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
import test_network_profile as witness

from pdx import version_contracts
from pdx.situated import action_network as net
from pdx.situated import core_contracts as core
from pdx.situated import expressions as expr
from pdx.situated import network_profile as adapter
from pdx.situated import production_profile as native

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module")
def profile():
    return native.load_profile(native.BASELINE_ROOT)


@pytest.fixture(scope="module")
def programs(profile):
    return {
        item.network.actions[0].definition.consumer_id: item
        for item in adapter.compile_profile(profile)
    }


def observations(program, values):
    action = program.network.actions[0]
    return net.ObservationBatch(
        action,
        tuple(
            core.Observation(
                fact.id,
                action.actor if fact.binding == "actor" else action.target,
                fact.unit,
                "unknown" if values[fact.id] is None else "known",
                action.time,
                values[fact.id],
                fact.sources,
            )
            for fact in program.network.facts
            if fact.id in values
        ),
    )


def with_action(program, action):
    network = program.network
    consumer = action.definition.consumer_id
    return net.compile_action_network(
        replace(
            network,
            actions=(action,),
            bridges=tuple(replace(bridge, action=action) for bridge in network.bridges),
            objectives=tuple(
                replace(goal, action=action, starts=action.time, deadline=action.time)
                for goal in network.objectives
            ),
            facts=tuple(replace(fact, consumer_ids=(consumer,)) for fact in network.facts),
            registry=replace(
                network.registry,
                accounts=tuple(
                    replace(account, consumer_id=consumer) for account in network.registry.accounts
                ),
            ),
        )
    )


@pytest.mark.parametrize(
    "change", ["target", "actor", "consumer", "epoch", "evaluation", "bindings"]
)
def test_observation_batch_cannot_cross_candidate_contexts(programs, change):
    original = programs[witness.DIPLOMACY]
    action = original.network.actions[0]
    changed = {
        "target": replace(action, target=core.EntityKey("country", "target-b")),
        "actor": replace(action, actor=core.EntityKey("country", "ACTOR-B")),
        "consumer": replace(
            action, definition=replace(action.definition, consumer_id="another-consumer")
        ),
        "epoch": replace(action, time=core.TimeIdentity("other-epoch", 0)),
        "evaluation": replace(action, time=core.TimeIdentity("native-on-demand", 1)),
        "bindings": replace(
            action, bindings=(("commitment", core.EntityKey("country", "auxiliary-country")),)
        ),
    }[change]
    alternative = with_action(original, changed)
    # Deliberately omit the target-bound optional pact observation: the two
    # actual observations both bind actor and previously hid the counterparty.
    values = {"protective": True, "influence": 500}
    first = observations(original, values)
    second = observations(alternative, values)
    assert net.evaluate_observations(original, first).total == 2
    result = net.evaluate_observations(alternative, second)
    assert result.total == 2
    assert result.objectives[0].target == changed.target
    assert result.objectives[0].actor == changed.actor
    with pytest.raises(ValueError, match="候选上下文"):
        net.evaluate_observations(alternative, first)
    with pytest.raises(ValueError, match="候选上下文"):
        net.evaluate_observations(original, first, action=changed)
    with pytest.raises(ValueError, match="候选上下文"):
        alternative.network.objectives[0].bind(first, alternative.network.facts)


def test_real_objectives_cannot_strip_the_observation_batch_context(programs):
    program = programs[witness.DIPLOMACY]
    batch = observations(program, {"protective": True, "influence": 500})
    with pytest.raises(ValueError, match="ObservationBatch"):
        net.evaluate_observations(program, batch.observations)


def test_multi_candidate_reference_uses_each_batch_full_context(programs):
    original = programs[witness.DIPLOMACY]
    first = original.network.actions[0]
    second = replace(first, target=core.EntityKey("country", "target-b"))
    second_program = with_action(original, second)
    extra = tuple(
        replace(
            bridge,
            id=bridge.id + ".second",
            term=replace(
                bridge.term,
                id=bridge.term.id + ".second",
                group_id=bridge.term.group_id + ".second",
            ),
        )
        for bridge in second_program.network.bridges
    )
    program = net.compile_action_network(
        replace(
            original.network,
            actions=(first, second),
            bridges=(*original.network.bridges, *extra),
            groups=(
                *original.network.groups,
                *(
                    replace(
                        group,
                        id=group.id + ".second",
                        term_ids=tuple(name + ".second" for name in group.term_ids),
                    )
                    for group in original.network.groups
                ),
            ),
            objectives=(*original.network.objectives, *second_program.network.objectives),
        )
    )
    for source, expected in ((original, 2), (second_program, -2)):
        batch = observations(
            source, {"protective": expected > 0, "influence": 500 if expected > 0 else 100}
        )
        result = net.evaluate_observations(program, batch)
        assert result.total == expected
        assert result.action == batch.action
        assert result.objectives[0].target == batch.action.target


@pytest.mark.parametrize(
    ("consumer", "goal", "baseline", "values", "expected"),
    [
        (
            witness.ROAD,
            "local-capacity",
            "infrastructure",
            {"infrastructure": 0.1, "road-present": False},
            4,
        ),
        (
            witness.SCHOOL,
            "education-capacity",
            "literacy",
            {"literacy": 0.2, "bureaucracy": 0, "default": False, "school-agenda": True},
            3,
        ),
        (
            witness.DIPLOMACY,
            "external-security",
            "protective",
            {"protective": True, "influence": 500, "target-interference": True},
            1,
        ),
    ],
)
def test_three_production_objectives_bind_the_actual_current_baseline(
    programs, consumer, goal, baseline, values, expected
):
    program = programs[consumer]
    action = program.network.actions[0]
    observed = observations(program, values)
    result = net.evaluate_observations(program, observed)
    assert result.total == expected
    assert len(result.objectives) == 1
    objective = result.objectives[0]
    assert isinstance(objective, core.ActorObjectiveSpec)
    assert objective.id == goal
    assert (objective.actor, objective.target) == (action.actor, action.target)
    assert objective.starts == objective.deadline == action.time
    assert objective.source_fact_ids == (baseline,)
    assert objective.consumer_ids == (consumer,)
    assert objective.status == "known"
    assert objective.baseline is next(
        item for item in observed.observations if item.spec_id == baseline
    )
    # Retaining native scoring and measuring the current world are distinct bases.
    assert {account.baseline for account in program.network.registry.accounts} == {
        "retained-native"
    }
    assert objective.baseline.value == values[baseline]
    assert all(not isinstance(item, core.Observation) for item in program.network.objectives)


@pytest.mark.parametrize(
    ("consumer", "initial", "steps"),
    [
        (
            witness.ROAD,
            {"infrastructure": 0.6, "road-present": False},
            [
                ({}, {}, 0, ()),
                ({"infrastructure": 0.1, "road-present": True}, {}, 4, (("road-relief", 4),)),
                ({}, {"road-present": "unknown"}, 4, (("road-relief", 4),)),
                ({}, {"road-present": "stale"}, 4, (("road-relief", 4),)),
                ({}, {}, 4, (("road-relief", 4),)),
                ({"infrastructure": 0.8}, {}, -2, (("road-held-authority", -2),)),
                ({}, {"infrastructure": "unknown"}, 0, ()),
                ({}, {"infrastructure": "stale"}, 0, ()),
                ({}, {}, -2, (("road-held-authority", -2),)),
                ({"infrastructure": 0.6, "road-present": False}, {}, 0, ()),
            ],
        ),
        (
            witness.SCHOOL,
            {"literacy": 0.7, "bureaucracy": 0, "default": False, "school-agenda": True},
            [
                ({}, {}, 0, ()),
                (
                    {"literacy": 0.2},
                    {},
                    3,
                    (("school-agenda-residual", 1), ("school-literacy", 2)),
                ),
                ({}, {"school-agenda": "unknown"}, 2, (("school-literacy", 2),)),
                ({}, {"school-agenda": "stale"}, 2, (("school-literacy", 2),)),
                ({}, {}, 3, (("school-agenda-residual", 1), ("school-literacy", 2))),
                ({}, {"bureaucracy": "unknown"}, 0, ()),
                ({}, {"bureaucracy": "stale"}, 0, ()),
                ({}, {}, 3, (("school-agenda-residual", 1), ("school-literacy", 2))),
                ({"literacy": 0.7}, {}, 0, ()),
            ],
        ),
        (
            witness.DIPLOMACY,
            {"protective": False, "influence": 500, "target-interference": False},
            [
                ({}, {}, 0, ()),
                (
                    {"protective": True, "influence": 100, "target-interference": True},
                    {},
                    -1,
                    (
                        ("relations-influence-opportunity", -2),
                        ("relations-interference-residual", -1),
                        ("relations-protective-value", 2),
                    ),
                ),
                (
                    {},
                    {"target-interference": "unknown"},
                    0,
                    (("relations-influence-opportunity", -2), ("relations-protective-value", 2)),
                ),
                (
                    {},
                    {"target-interference": "stale"},
                    0,
                    (("relations-influence-opportunity", -2), ("relations-protective-value", 2)),
                ),
                (
                    {},
                    {},
                    -1,
                    (
                        ("relations-influence-opportunity", -2),
                        ("relations-interference-residual", -1),
                        ("relations-protective-value", 2),
                    ),
                ),
                ({}, {"influence": "unknown"}, 0, ()),
                ({}, {"influence": "stale"}, 0, ()),
                (
                    {"influence": 500, "target-interference": False},
                    {},
                    2,
                    (("relations-protective-value", 2),),
                ),
            ],
        ),
    ],
)
def test_three_real_consumers_refresh_through_shock_unknown_stale_and_recovery(
    profile, programs, consumer, initial, steps
):
    """Static observation sequence, with independent lowered-PDX arithmetic.

    Each step supplies new typed observations to the actual production network.
    Unavailable-reader specialization witnesses the declared unknown contract;
    it does not pretend that a fixed installed script observes Python status or
    that this sequence was sampled from a running engine.
    """
    canonical = programs[consumer]
    generated = adapter.build(profile)
    row = next(item for item in profile.declarations if item.id == consumer)
    installed_overlay = witness._overlay(generated[row.source.removeprefix("game/")], consumer)
    scope = "state" if consumer == witness.ROAD else "actor"
    stable_values = {
        witness.ROAD: {"infrastructure": 0.1, "road-present": False},
        witness.SCHOOL: {
            "literacy": 0.2,
            "bureaucracy": 0,
            "default": False,
            "school-agenda": True,
        },
        witness.DIPLOMACY: {
            "protective": True,
            "influence": 500,
            "target-interference": True,
        },
    }
    stable = {
        key: net.evaluate_observations(programs[key], observations(programs[key], values))
        for key, values in stable_values.items()
        if key != consumer
    }
    current = dict(initial)
    previous_batch = None
    for evaluation, (changes, statuses, expected, effects) in enumerate(steps):
        current.update(changes)
        action = replace(
            canonical.network.actions[0], time=core.TimeIdentity("native-on-demand", evaluation)
        )
        program = with_action(canonical, action)
        batch = observations(program, current)
        batch = replace(
            batch,
            observations=tuple(
                replace(
                    item,
                    status=statuses[item.spec_id],
                    value=None if statuses[item.spec_id] == "unknown" else item.value,
                )
                if item.spec_id in statuses
                else item
                for item in batch.observations
            ),
        )
        result = net.evaluate_observations(program, batch)
        assert result.total == expected, (consumer, evaluation)
        assert result.effects == effects, (consumer, evaluation)
        # Repeating one exact evaluation cannot accumulate a previous delta.
        assert net.evaluate_observations(program, batch) == result
        assert result.action.time == action.time
        assert all(item.starts == item.deadline == action.time for item in result.objectives)
        available = tuple(item.spec_id for item in batch.observations if item.status == "known")
        known = {item.spec_id: item.value for item in batch.observations if item.status == "known"}
        pdx = witness._parsed(adapter.render_program(canonical, available=available))
        assert witness._score(pdx, {**known, "ai": True}, scope) == expected
        assert witness._score(pdx, {**known, "ai": False}, scope) == 0
        if not statuses:
            # Known rounds also exercise the actual production file's overlay,
            # rather than only the standalone specialization renderer.
            assert witness._score(installed_overlay, {**current, "ai": True}, scope) == expected
        if previous_batch is not None:
            with pytest.raises(ValueError, match="候选上下文"):
                net.evaluate_observations(program, previous_batch)
        previous_batch = batch
        for key, stable_result in stable.items():
            assert (
                net.evaluate_observations(
                    programs[key], observations(programs[key], stable_values[key])
                )
                == stable_result
            )


@pytest.mark.parametrize("mode", ["omitted", "unknown", "stale"])
def test_unknown_or_stale_required_goal_baseline_withdraws_complete_groups(programs, mode):
    program = programs[witness.SCHOOL]
    observed = observations(
        program,
        {"literacy": 0.2, "bureaucracy": -1, "default": False, "school-agenda": True},
    )
    if mode == "omitted":
        observed = replace(
            observed,
            observations=tuple(
                item for item in observed.observations if item.spec_id != "literacy"
            ),
        )
    else:
        observed = replace(
            observed,
            observations=tuple(
                replace(item, status="unknown", value=None)
                if item.spec_id == "literacy" and mode == "unknown"
                else replace(item, status="stale")
                if item.spec_id == "literacy"
                else item
                for item in observed.observations
            ),
        )
    result = net.evaluate_observations(program, observed)
    assert result.total == 0
    assert result.effects == ()
    assert result.unknown_groups == ("school-investment.complete", "school-investment.interaction")
    if mode == "omitted":
        assert result.objectives == ()
    else:
        assert result.objectives[0].status == "unknown"
        assert result.objectives[0].baseline is next(
            item for item in observed.observations if item.spec_id == "literacy"
        )


def test_false_goal_baseline_does_not_veto_opposing_cost_or_native_qualification(programs):
    program = programs[witness.DIPLOMACY]
    result = net.evaluate_observations(
        program,
        observations(program, {"protective": False, "influence": 100, "target-interference": True}),
    )
    assert result.objectives[0].baseline.value is False
    assert result.objectives[0].status == "known"
    assert result.total == -2
    assert result.effects == (("relations-influence-opportunity", -2),)


def test_unknown_goal_only_withdraws_its_own_complete_group(programs):
    network = programs[witness.ROAD].network
    benefit = network.bridges[0]
    recovery = network.bridges[-1]
    recovery = replace(
        recovery,
        term=replace(recovery.term, group_id="independent-resource"),
        source_ids=("road-present",),
        condition=expr.Compare("road-present", "eq", True),
        condition_fact_ids=("road-present",),
    )
    resource_goal = replace(
        network.objectives[0],
        id="resource-opportunity",
        source_fact_ids=("road-present",),
        baseline_fact_id="road-present",
    )
    registry = replace(
        network.registry,
        accounts=tuple(
            replace(account, objective_id=resource_goal.id)
            if account.id == recovery.effect_id
            else account
            for account in network.registry.accounts
        ),
    )
    split = replace(
        network,
        bridges=(benefit, recovery),
        groups=(
            net.AssessmentGroup(
                benefit.term.group_id, (benefit.term.id,), review_sources=(adapter.PROOF,)
            ),
            net.AssessmentGroup(
                recovery.term.group_id, (recovery.term.id,), review_sources=(adapter.PROOF,)
            ),
        ),
        predicates=(),
        registry=registry,
        objectives=(*network.objectives, resource_goal),
    )
    program = net.compile_action_network(split)
    for facts, expected, unknown in (
        ({"infrastructure": None, "road-present": True}, -2, benefit.term.group_id),
        ({"infrastructure": 0.1, "road-present": None}, 2, recovery.term.group_id),
    ):
        result = net.evaluate_observations(program, observations(program, facts))
        assert result.total == expected
        assert result.unknown_groups == (unknown,)
        assert sorted(goal.status for goal in result.objectives) == ["known", "unknown"]


@pytest.mark.parametrize(
    "damage",
    [
        "actor",
        "target",
        "epoch",
        "deadline",
        "source",
        "missing_source",
        "horizon",
        "unrelated",
        "orphan",
    ],
)
def test_objective_identity_scope_source_and_lifetime_cannot_grant_free_contributions(
    programs, damage
):
    def compile_damaged():
        network = programs[witness.ROAD].network
        template = network.objectives[0]
        if damage == "actor":
            template = replace(
                template, action=replace(template.action, actor=core.EntityKey("country", "OTHER"))
            )
        elif damage == "target":
            template = replace(
                template,
                action=replace(template.action, target=core.EntityKey("state", "other-state")),
            )
        elif damage == "epoch":
            template = replace(template, starts=core.TimeIdentity("other", 0))
        elif damage == "deadline":
            template = replace(template, deadline=core.TimeIdentity("native-on-demand", 1))
        elif damage == "source":
            template = replace(template, source_fact_ids=())
        elif damage == "missing_source":
            template = replace(
                template, source_fact_ids=("unregistered",), baseline_fact_id="unregistered"
            )
        elif damage == "horizon":
            registry = replace(
                network.registry,
                accounts=tuple(replace(item, horizon="long") for item in network.registry.accounts),
            )
            network = replace(network, registry=registry)
        elif damage == "unrelated":
            template = replace(template, id="another-interest")
        elif damage == "orphan":
            network = replace(
                network, objectives=(template, replace(template, id="orphan-interest"))
            )
        if damage != "orphan":
            network = replace(network, objectives=(template,))
        net.compile_action_network(network)

    with pytest.raises(ValueError):
        compile_damaged()


@pytest.mark.parametrize("damage", ["wrong_entity", "wrong_time", "wrong_source", "no_source"])
def test_objective_baseline_cannot_be_forged_at_typed_observation_boundary(programs, damage):
    program = programs[witness.ROAD]
    observed = observations(program, {"infrastructure": 0.1, "road-present": False})

    def evaluate_damaged():
        baseline = next(item for item in observed.observations if item.spec_id == "infrastructure")
        if damage == "wrong_entity":
            baseline = replace(baseline, entity=core.EntityKey("state", "other-state"))
        elif damage == "wrong_time":
            baseline = replace(baseline, time=core.TimeIdentity("native-on-demand", 2))
        elif damage == "wrong_source":
            baseline = replace(baseline, sources=(core.EvidenceRef("game/common/other.txt", 1),))
        else:
            baseline = replace(baseline, sources=())
        net.evaluate_observations(
            program,
            replace(
                observed,
                observations=tuple(
                    baseline if item.spec_id == baseline.spec_id else item
                    for item in observed.observations
                ),
            ),
        )

    with pytest.raises(ValueError):
        evaluate_damaged()


def test_objective_source_changes_reference_and_generated_availability_not_only_metadata(
    profile, programs, tmp_path: Path
):
    source = tmp_path / "goal-baseline.toml"
    source.write_text(
        adapter.SOURCE.read_text(encoding="utf-8")
        .replace('source_facts = ["infrastructure"]', 'source_facts = ["road-present"]', 1)
        .replace('baseline_fact = "infrastructure"', 'baseline_fact = "road-present"', 1),
        encoding="utf-8",
    )
    altered = adapter.compile_profile(profile, source=source)[0]
    original = programs[witness.ROAD]
    known: dict[str, object | None] = {"infrastructure": 0.1}
    assert net.evaluate_network(original, known).total == 4
    assert net.evaluate_network(altered, known).total == 0
    assert all("road-present" in item.lineage.roots for item in altered.contributions)
    assert net.evaluate_observations(altered, observations(altered, known)).objectives == ()
    for program, expected in ((original, 4), (altered, 0)):
        pdx = adapter.render_program(program, available=("infrastructure",))
        assert witness._score(witness._parsed(pdx), {**known, "ai": True}, "state") == expected
    for present in (False, True):
        facts: dict[str, object | None] = {**known, "road-present": present}
        assert net.evaluate_network(altered, facts).total == 4
        assert (
            witness._score(
                witness._parsed(adapter.render_program(altered)), {**facts, "ai": True}, "state"
            )
            == 4
        )


def test_goal_is_not_allowed_to_attach_unrelated_but_usable_fact(programs):
    network = programs[witness.ROAD].network
    source = replace(network.facts[0], id="other-observation", reader_id="other-observation")
    template = replace(
        network.objectives[0], source_fact_ids=(source.id,), baseline_fact_id=source.id
    )
    with pytest.raises(ValueError, match="无关目标"):
        net.compile_action_network(
            replace(network, facts=(*network.facts, source), objectives=(template,))
        )


def test_reference_compatibility_without_objective_cannot_reach_production_renderer(programs):
    network = programs[witness.ROAD].network
    registry = replace(
        network.registry,
        accounts=tuple(
            replace(account, objective_id="relative-preference")
            for account in network.registry.accounts
        ),
    )
    reference = net.compile_action_network(replace(network, registry=registry, objectives=()))
    assert (
        net.evaluate_network(reference, {"infrastructure": 0.1, "road-present": False}).total == 4
    )
    with pytest.raises(ValueError, match=r"ObjectiveTemplate.*reference-only"):
        adapter.render_program(reference)


def extra_cost_goal(network, *, mechanism: str):
    recovery = next(bridge for bridge in network.bridges if bridge.id == "road-recovery")
    original = network.registry.account(recovery.effect_id)
    goal = replace(network.objectives[0], id="other-local-objective")
    account = replace(original, id="other-local-cost", mechanism_id=mechanism, objective_id=goal.id)
    duplicate = replace(
        recovery,
        id="other-cost-claim",
        effect_id=account.id,
        term=replace(recovery.term, id="other-cost-term", effect_id=account.id),
    )
    reviews = tuple(
        net.OverlapReview(
            account.id,
            existing.id,
            "independent",
            (
                "Different reviewed marginal mechanisms may share the same current observation; an objective rename never creates a mechanism.",
            ),
        )
        for existing in network.registry.accounts
    )
    return replace(
        network,
        bridges=(*network.bridges, duplicate),
        objectives=(*network.objectives, goal),
        groups=tuple(
            replace(group, term_ids=(*group.term_ids, duplicate.term.id))
            if group.id == duplicate.term.group_id
            else group
            for group in network.groups
        ),
        registry=replace(
            network.registry,
            accounts=(*network.registry.accounts, account),
            overlaps=(*network.registry.overlaps, *reviews),
        ),
    )


def test_real_second_goal_and_independent_review_cannot_duplicate_one_canonical_cost(programs):
    network = programs[witness.ROAD].network
    assert (
        net.evaluate_network(
            programs[witness.ROAD], {"infrastructure": 0.8, "road-present": True}
        ).total
        == -2
    )
    # The new goal has real infrastructure provenance, the same valid actor,
    # target, current baseline and deadline. Even explicit independent reviews
    # cannot authorize a second account for the same authority opportunity.
    with pytest.raises(ValueError, match="同一规范机制换名重复注册"):
        extra_cost_goal(network, mechanism="authority-opportunity")


def test_different_reviewed_mechanisms_can_still_share_objective_baselines(programs):
    network = extra_cost_goal(programs[witness.ROAD].network, mechanism="distinct-reviewed-burden")
    program = net.compile_action_network(network)
    values = {"infrastructure": 0.8, "road-present": True}
    result = net.evaluate_observations(program, observations(program, values))
    assert result.total == -4
    assert len(result.objectives) == 2
    assert {objective.baseline.value for objective in result.objectives} == {0.8}
    pdx = adapter.render_program(program)
    assert witness._score(witness._parsed(pdx), {**values, "ai": True}, "state") == -4


@pytest.mark.parametrize("change", ["actor", "epoch", "evaluation"])
def test_renderer_rejects_reference_context_that_cannot_bind_native_root(programs, change):
    network = programs[witness.SCHOOL].network
    original = network.actions[0]
    action = (
        replace(original, actor=core.EntityKey("country", "OTHER"))
        if change == "actor"
        else replace(
            original,
            time=core.TimeIdentity("other-evaluation", 0)
            if change == "epoch"
            else core.TimeIdentity("native-on-demand", 1),
        )
    )
    rebound = replace(
        network,
        actions=(action,),
        bridges=tuple(replace(bridge, action=action) for bridge in network.bridges),
        objectives=tuple(
            replace(goal, action=action, starts=action.time, deadline=action.time)
            for goal in network.objectives
        ),
    )
    # This is valid reference data: observations bind the real actor and time,
    # and every bridge/objective was rebound consistently before compilation.
    program = net.compile_action_network(rebound)
    observed = observations(
        program,
        {"literacy": 0.2, "bureaucracy": 0, "default": False, "school-agenda": True},
    )
    result = net.evaluate_observations(program, observed)
    assert result.total == 3
    assert result.action == action
    assert result.objectives[0].actor == action.actor
    assert result.objectives[0].starts == result.objectives[0].deadline == action.time
    # The production renderer has only a symbolic actor/root and one native
    # evaluation, so it must not silently emit the same PDX for this reference.
    with pytest.raises(ValueError, match="native authority for this candidate context"):
        adapter.render_program(program)


@pytest.mark.parametrize(
    "change", ["actor", "target", "lifetime", "objective", "empty_objective", "missing_source"]
)
def test_production_objective_declaration_is_strict_and_really_consumed(
    profile, tmp_path: Path, change
):
    source = adapter.SOURCE.read_text(encoding="utf-8")
    before, after = {
        "actor": ('actor = "actor"', 'actor = "FRA"'),
        "target": ('target = "root"', 'target = "other-state"'),
        "lifetime": ('lifetime = "evaluation"', 'lifetime = "monthly"'),
        "objective": ('objective = "local-capacity"', 'objective = "country-name-route"'),
        "empty_objective": ("[[action.objective]]", "[[action.not_objective]]"),
        "missing_source": ('source_facts = ["infrastructure"]', 'source_facts = ["undeclared"]'),
    }[change]
    path = tmp_path / "invalid.toml"
    path.write_text(source.replace(before, after, 1), encoding="utf-8")
    with pytest.raises(ValueError):
        adapter.compile_profile(profile, source=path)


def test_audit_preserves_symbolic_goals_without_creating_sampled_baselines(profile):
    audit = adapter.audit(profile)
    assert audit["runtime"] == "unknown"
    programs = audit["programs"]
    assert isinstance(programs, list)
    for program in programs:
        assert len(program["objectives"]) == 1
        goal = program["objectives"][0]
        assert (
            goal["baseline_value"] == "read from the same evaluation; never sampled at generation"
        )
        assert goal["lifetime"] == "evaluation"
        assert goal["score_comparison_baseline"] == "retained-native"


@pytest.fixture(scope="module", autouse=True)
def _historical_1150_contract():
    """Bind the archived three-consumer objective witnesses to their input identity."""
    with version_contracts.select_version("1.15.0"):
        yield
