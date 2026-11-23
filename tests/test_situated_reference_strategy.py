"""主计划手算案例和能击穿错误策略的反例。"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from pdx.situated import reference_strategy as ref
from pdx.situated.core_contracts import EntityKey, EvidenceRef, Observation, TimeIdentity, Unit

pytestmark = pytest.mark.unit
COUNTRY = EntityKey("country", "A")
PARTNER = EntityKey("country", "B")
THIRD = EntityKey("country", "C")
RESOURCE = ref.Resource(COUNTRY, "shared-budget", "capacity-unit", "capacity")
EPOCH = "hand-calculation"
BASELINE = "native-status-quo"
UNIT = "net-value"
SOURCE = "docs/design/架构主计划.md#共享资源的手算试验"
EVIDENCE = EvidenceRef("docs/design/架构主计划.md", 116)
BUDGET = ref.Budget()


def _choice(
    time: int,
    opportunity: str,
    options: tuple[tuple[str, ref.Node], ...],
    *,
    actor: EntityKey = COUNTRY,
    control: ref.Control = "ai",
    **settings,
) -> ref.Choice:
    return ref.Choice(time, opportunity, options, actor=actor, control=control, **settings)


def _value(
    outcome: str,
    amount: int,
    time: int,
    *,
    end: int | None = None,
    source: str = SOURCE,
) -> ref.Endpoint:
    label = ref.Attribution(
        COUNTRY, COUNTRY, "own", outcome, UNIT, time, end or time + 1, BASELINE, outcome
    )
    return ref.Endpoint(label, amount, source)


def _report(
    value: bool | int | None,
    learned: int,
    *,
    occurred: int = 0,
    valid_until: int = 8,
    observer: EntityKey = COUNTRY,
    entity: EntityKey = COUNTRY,
    direction: str = "own",
    fact: str = "disruption",
    epoch: str = EPOCH,
    occurred_order: int = 0,
    learned_order: int = 0,
) -> ref.Report:
    unit: Unit = "points" if fact == "capacity" else "boolean"
    observation = Observation(
        fact,
        entity,
        unit,
        "unknown" if value is None else "known",
        TimeIdentity(epoch, learned),
        value,
        (EVIDENCE,),
    )
    return ref.Report(
        observer,
        observation,
        direction,
        occurred,
        valid_until,
        SOURCE,
        occurred_order=occurred_order,
        learned_order=learned_order,
    )


def _problem(*models: ref.Model, budget: ref.Budget = BUDGET) -> ref.Problem:
    return ref.Problem(COUNTRY, EPOCH, BASELINE, UNIT, models, budget)


def _use_budget(
    invest: bool, available: bool, industrial: int, military: int, interaction: int
) -> ref.Node:
    end = ref.End(4)
    if available:
        military_effects: tuple[ref.Endpoint, ...] = (_value("military", military, 2),)
        if invest:
            military_effects += (_value("joint-residual", interaction, 2),)
        apply = ref.Transition(
            2,
            "military-executed",
            end,
            ((RESOURCE, -3),),
            military_effects,
            blocked=end,
            blocked_event="military-capacity-refusal",
        )
        follow: ref.Node = _choice(2, "military-opportunity", (("take", apply), ("wait", end)))
    else:
        follow = ref.Transition(2, "military-opportunity-absent", end)
    if not invest:
        return follow
    return ref.Transition(
        0, "industry-paid", follow, ((RESOURCE, -4),), (_value("industrial", industrial, 0),)
    )


def _industry_model(
    total: int,
    disrupted: bool,
    probability: Fraction,
    *,
    report_disruption: bool = True,
) -> ref.Model:
    industrial, military, interaction = (2, 9, -1) if disrupted else (6, 5, 1)
    worlds = []
    for name, arrived, weight in (
        ("offered", True, probability),
        ("absent", False, 1 - probability),
    ):
        if not weight:
            continue
        root = _choice(
            0,
            "industrial-opportunity",
            (
                ("invest", _use_budget(True, arrived, industrial, military, interaction)),
                ("status-quo", _use_budget(False, arrived, industrial, military, interaction)),
            ),
            reads=(ref.Read("disruption", COUNTRY, "boolean", "own"),),
        )
        reports = (_report(disrupted, 0),) if report_disruption else ()
        worlds.append(ref.World(name, weight, root, (ref.Balance(RESOURCE, total, 2),), reports))
    return ref.Model(
        f"capacity-{total}-disrupted-{str(disrupted).lower()}-probability-{probability.numerator}-{probability.denominator}",
        tuple(worlds),
        SOURCE,
    )


@pytest.mark.parametrize(
    ("total", "disrupted", "candidate", "baseline", "net"),
    [
        (7, False, 6, Fraction(15, 4), Fraction(9, 4)),
        (7, True, 2, Fraction(27, 4), Fraction(-19, 4)),
        (10, False, Fraction(21, 2), Fraction(15, 4), Fraction(27, 4)),
        (10, True, 8, Fraction(27, 4), Fraction(5, 4)),
    ],
)
def test_resource_competition_matches_hand_table_and_local_formula(
    total, disrupted, candidate, baseline, net
):
    probability = Fraction(3, 4)
    problem = _problem(_industry_model(total, disrupted, probability))
    result = ref.compare(problem, "invest", "status-quo")
    assert result.candidate.lower == candidate
    assert result.baseline.lower == baseline
    assert result.bounds == ref.Interval(net, net)
    assert result.direction == ("increase" if net > 0 else "decrease")
    assert ref.replay(problem, result.candidate.policy) == result.candidate

    if total == 10:
        strong_local = 2 - probability if disrupted else 6 + probability
    else:
        strong_local = 2 - 9 * probability if disrupted else 6 - 5 * probability
    assert strong_local == net
    if disrupted and total == 7:
        current_value_only = 2
        assert current_value_only > 0 > result.bounds.upper

    assert result.candidate.trajectories[1].events == (
        (0, "industry-paid"),
        (2, "military-opportunity-absent"),
    )
    assert len(result.candidate.trajectories[1].decisions) == 1
    if total == 10:
        assert result.candidate.trajectories[0].events[-1] == (2, "military-executed")
        assert result.candidate.trajectories[0].remaining_resources == ((RESOURCE, 1),)


@pytest.mark.parametrize(
    ("disrupted", "low", "high", "direction"),
    [
        (False, Fraction(9, 4), Fraction(27, 4), "increase"),
        (True, Fraction(-19, 4), Fraction(5, 4), "vanilla"),
    ],
)
def test_hidden_capacity_requires_common_strategy_and_whole_uncertainty(
    disrupted, low, high, direction
):
    problem = _problem(*(_industry_model(total, disrupted, Fraction(3, 4)) for total in (7, 10)))
    result = ref.compare(problem, "invest", "status-quo")
    assert result.bounds == ref.Interval(low, high)
    assert result.direction == direction
    by_world = {(path.model, path.world): path for path in result.candidate.trajectories}
    low_offer = by_world[(problem.models[0].id, "offered")]
    high_offer = by_world[(problem.models[1].id, "offered")]
    assert low_offer.decisions == high_offer.decisions
    assert low_offer.events[-1] == (2, "military-capacity-refusal")
    assert high_offer.events[-1] == (2, "military-executed")
    assert ref.dominates(problem, "invest", "status-quo") is (direction == "increase")


@pytest.mark.parametrize(
    ("probability", "value", "direction"),
    [
        (Fraction(2, 9) - Fraction(1, 90), Fraction(1, 10), "increase"),
        (Fraction(2, 9), 0, "vanilla"),
        (Fraction(2, 9) + Fraction(1, 90), Fraction(-1, 10), "decrease"),
    ],
)
def test_probability_critical_and_equal_margin(probability, value, direction):
    problem = _problem(_industry_model(7, True, probability))
    assert ref.compare(problem, "invest", "status-quo").direction == direction
    result = ref.compare(problem, "invest", "status-quo", margin=abs(value))
    assert result.bounds == ref.Interval(value, value)
    assert result.direction == "vanilla"


def test_probability_interval_and_zero_arrival():
    low_q, high_q = Fraction(1, 9), Fraction(1, 3)
    problem = _problem(_industry_model(7, True, low_q), _industry_model(7, True, high_q))
    result = ref.compare(problem, "invest", "status-quo")
    assert result.bounds == ref.Interval(-1, 1)
    assert result.direction == "vanilla"
    absent = ref.compare(_problem(_industry_model(7, True, Fraction(0))), "invest", "status-quo")
    assert absent.bounds == ref.Interval(2, 2)


def test_unreported_disruption_cannot_split_the_root_decision():
    normal = _industry_model(7, False, Fraction(3, 4), report_disruption=False)
    disrupted = _industry_model(7, True, Fraction(3, 4), report_disruption=False)
    result = ref.compare(_problem(normal, disrupted), "invest", "status-quo")
    assert result.bounds == ref.Interval(Fraction(-19, 4), Fraction(9, 4))
    assert result.direction == "vanilla"
    assert len({path.decisions[0] for path in result.candidate.trajectories}) == 1
    unpaired = _industry_model(7, True, Fraction(3, 4))
    with pytest.raises(ValueError, match="同一合法可观察历史"):
        ref.compare(_problem(normal, unpaired), "invest", "status-quo")


def _reward(name: str, amount: int, time: int, *, final: int = 8) -> ref.Transition:
    return ref.Transition(time, name, ref.End(final), effects=(_value(name, amount, time),))


def _information_problem(
    probe_cost: int,
    *,
    learned: int = 2,
    reads: tuple[ref.Read, ...] | None = None,
    observer: EntityKey = COUNTRY,
    entity: EntityKey = COUNTRY,
    direction: str = "own",
    valid_until: int = 8,
    epoch: str = EPOCH,
) -> ref.Problem:
    if reads is None:
        reads = (ref.Read("disruption", COUNTRY, "boolean", "own"),)
    worlds = []
    for state in (False, True):
        first, second = (0, 8) if state else (8, 0)
        options = (("one", _reward("one", first, 3)), ("two", _reward("two", second, 3)))
        direct = _choice(3, "follow-up", options, reads=reads)
        probe = ref.Transition(
            0,
            "probe",
            direct,
            effects=(_value("probe-cost", -probe_cost, 0),),
            reports=(
                _report(
                    state,
                    learned,
                    observer=observer,
                    entity=entity,
                    direction=direction,
                    valid_until=valid_until,
                    epoch=epoch,
                ),
            ),
        )
        root = _choice(0, "decision", (("direct", direct), ("probe", probe)))
        worlds.append(ref.World(f"hidden-{state!s}".lower(), Fraction(1, 2), root))
    return _problem(ref.Model("mixture", tuple(worlds), SOURCE))


def test_equal_histories_have_value_four_and_use_one_action():
    result = ref.compare(_information_problem(0, learned=4), "probe", "direct")
    assert result.candidate.lower == result.baseline.lower == 4
    assert result.candidate.trajectories[0].decisions == result.candidate.trajectories[1].decisions
    assert result.bounds == ref.Interval(0, 0)


@pytest.mark.parametrize(
    ("probe_cost", "value", "direction"),
    [(0, 8, "increase"), (4, 4, "vanilla"), (5, 3, "decrease")],
)
def test_legal_probe_adds_four_before_cost(probe_cost, value, direction):
    result = ref.compare(_information_problem(probe_cost), "probe", "direct")
    assert result.candidate.lower == value
    assert result.baseline.lower == 4
    assert result.direction == direction
    assert [path.decisions[-1][1] for path in result.candidate.trajectories] == ["one", "two"]


@pytest.mark.parametrize(
    "limits",
    [
        {"reads": ()},
        {"observer": PARTNER},
        {"entity": THIRD},
        {"direction": "reversed"},
        {"valid_until": 2},
        {"epoch": "unrelated-epoch"},
        {"learned": 4},
    ],
)
def test_consumer_cannot_see_unlicensed_wrong_or_late_probe_result(limits):
    result = ref.compare(_information_problem(1, **limits), "probe", "direct")
    assert result.candidate.lower == 3
    assert result.baseline.lower == 4
    assert result.candidate.trajectories[0].decisions == result.candidate.trajectories[1].decisions


def test_one_hidden_model_must_apply_across_observed_future_contexts():
    read = ref.Read("disruption", COUNTRY, "boolean", "own")
    models = []
    for hidden in (False, True):
        worlds = []
        for observed in (False, True):
            outcome = _reward("risky-payoff", 8 if hidden == observed else 0, 3)
            follow = _choice(3, "future-opportunity", (("continue", outcome),), reads=(read,))
            risky = ref.Transition(
                1, "signal-arrives", follow, reports=(_report(observed, 2, occurred=1),)
            )
            root = _choice(
                0,
                "current-opportunity",
                (
                    ("risky", risky),
                    ("safe", _reward("safe-payoff", 2, 0)),
                ),
            )
            worlds.append(ref.World(f"context-{observed!s}".lower(), Fraction(1, 2), root))
        models.append(ref.Model(f"model-{hidden!s}".lower(), tuple(worlds), SOURCE))
    problem = _problem(*models)
    result = ref.compare(problem, "risky", "safe")
    assert result.candidate.model_values == (
        ("model-false", ref.Interval(4, 4)),
        ("model-true", ref.Interval(4, 4)),
    )
    assert result.bounds == ref.Interval(2, 2)
    assert ref.dominates(problem, "risky", "safe")


def test_per_model_optimism_and_all_baselines_claim_are_distinct():
    models = []
    for selector in (0, 1):
        choose_candidate = _choice(
            2,
            "candidate-choice",
            (
                ("a", _reward("a", 8 if selector == 0 else 0, 2)),
                ("b", _reward("b", 0 if selector == 0 else 8, 2)),
            ),
        )
        choose_baseline = _choice(
            2,
            "baseline-choice",
            (
                ("common", _reward("common", 2, 2)),
                ("irregular", _reward("irregular", 9 if selector == 0 else 0, 2)),
            ),
        )
        root = _choice(
            0,
            "root",
            (
                ("candidate", choose_candidate),
                ("baseline", choose_baseline),
                ("fixed", _reward("fixed", 3, 0)),
            ),
        )
        models.append(ref.Model(f"model-{selector}", (ref.World("world", 1, root),), SOURCE))
    problem = _problem(*models)
    result = ref.compare(problem, "candidate", "baseline")
    assert result.candidate.lower == 0
    fixed = ref.compare(problem, "fixed", "baseline")
    assert fixed.bounds == ref.Interval(1, 1)
    assert not ref.dominates(problem, "fixed", "baseline")
    native = next(
        strategy
        for strategy in ref.evaluate(problem)
        if strategy.policy[0][1] == "baseline" and strategy.policy[1][1] == "irregular"
    )
    against_native = ref.compare_policies(problem, fixed.candidate.policy, native.policy)
    assert against_native.bounds == ref.Interval(-6, 3)
    assert against_native.direction == "vanilla"


def test_known_zero_unknown_and_late_reports_form_different_read_sets():
    reader = ref.Read("capacity", COUNTRY, "points", "own")
    follow = _choice(
        4,
        "later",
        (
            ("one", _reward("one", 8, 4)),
            ("two", _reward("two", 0, 4)),
        ),
        reads=(reader,),
    )
    before = _choice(1, "before", (("wait", follow),), reads=(reader,))
    root = _choice(0, "root", (("status-quo", before),))
    worlds = tuple(
        ref.World(name, Fraction(1, 3), root, reports=(report,))
        for name, report in (
            ("zero", _report(0, 0, fact="capacity")),
            ("unknown", _report(None, 0, fact="capacity")),
            ("late", _report(0, 2, fact="capacity")),
        )
    )
    strategy = ref.evaluate(_problem(ref.Model("model", worlds, SOURCE)))[0]
    zero, unknown, late = strategy.trajectories
    assert zero.decisions[1] != unknown.decisions[1] == late.decisions[1]
    assert zero.decisions[2][0].reports
    assert late.decisions[2][0].reports
    assert not unknown.decisions[2][0].reports


def _terminal_problem(candidate: ref.Node, **settings) -> ref.Problem:
    root = _choice(0, "root", (("candidate", candidate), ("status-quo", ref.End(4))))
    return _problem(ref.Model("model", (ref.World("world", 1, root),), SOURCE), **settings)


def test_duplicate_attribution_counts_once_and_adjacent_periods_add():
    first = _value("prosperity", 2, 0)
    duplicated = replace(first, source="independent-evidence")
    adjacent = _value("prosperity", 3, 1)
    later = ref.Transition(1, "later-evidence", ref.End(4), effects=(duplicated, adjacent))
    node = ref.Transition(0, "gain", later, effects=(first,))
    result = ref.compare(_terminal_problem(node), "candidate", "status-quo")
    assert result.bounds == ref.Interval(5, 5)
    assert len(result.candidate.trajectories[0].endpoints) == 2
    assert set(result.candidate.trajectories[0].attribution_sources[0][1]) == {
        SOURCE,
        "independent-evidence",
    }


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (_value("prosperity", 3, 0, end=2), "期间重叠"),
        (_value("prosperity", 3, 0), "价值冲突"),
    ],
)
def test_overlapping_or_inconsistent_utility_is_rejected(extra, message):
    node = ref.Transition(0, "gain", ref.End(4), effects=(_value("prosperity", 2, 0), extra))
    with pytest.raises(ValueError, match=message):
        ref.evaluate(_terminal_problem(node))


def test_evidenced_tail_and_joint_error_widen_the_bounds():
    node = ref.Transition(
        0, "gain", ref.End(4, ref.Interval(-2, 1), SOURCE), effects=(_value("gain", 4, 0),)
    )
    problem = _terminal_problem(node, budget=ref.Budget(error=4))
    problem = replace(problem, error=Fraction(1, 2), error_source=SOURCE)
    result = ref.compare(problem, "candidate", "status-quo")
    assert result.bounds == ref.Interval(Fraction(3, 2), Fraction(11, 2))
    assert result.direction == "increase"
    budget_result = ref.compare(replace(problem, budget=ref.Budget()), "candidate", "status-quo")
    assert budget_result.bounds == result.bounds
    assert not budget_result.within_error_budget
    assert budget_result.direction == "vanilla"
    with pytest.raises(ValueError, match="截断尾部缺少"):
        ref.End(4, ref.Interval(-2, 1))


def test_budget_and_same_opportunity_feedback_fail_explicitly():
    with pytest.raises(ref.BudgetExceededError, match="时间窗"):
        ref.evaluate(_terminal_problem(ref.End(5), budget=ref.Budget(horizon=4)))
    with pytest.raises(ref.BudgetExceededError, match="展开步数"):
        ref.evaluate(_terminal_problem(ref.End(4), budget=ref.Budget(steps=1)))
    with pytest.raises(ref.BudgetExceededError, match="完整策略数"):
        ref.evaluate(_terminal_problem(ref.End(4), budget=ref.Budget(policies=1)))
    problem = _information_problem(1)
    with pytest.raises(ref.BudgetExceededError, match="联合世界数"):
        ref.evaluate(replace(problem, budget=ref.Budget(worlds=1)))
    same_time = _choice(0, "feedback", (("one", ref.End(4)),))
    with pytest.raises(ValueError, match="反馈需在较晚时点"):
        ref.Transition(0, "premature-feedback", same_time, reports=(_report(True, 0),))


@pytest.mark.parametrize(("history", "value", "strategies"), [(False, 4, 2), (True, 8, 4)])
def test_current_reader_cannot_inherit_report_time_from_history(history, value, strategies):
    read = ref.Read("disruption", COUNTRY, "boolean", "own")
    worlds = []
    for learned in (1, 2):
        follow = _choice(
            3,
            "future-opportunity",
            (
                ("early", _reward("early-payoff", 8 if learned == 1 else 0, 3)),
                ("late", _reward("late-payoff", 8 if learned == 2 else 0, 3)),
            ),
            reads=(read,),
            history=history,
        )
        root = _choice(0, "root", (("wait", follow),))
        worlds.append(
            ref.World(f"learned-{learned}", Fraction(1, 2), root, reports=(_report(True, learned),))
        )
    policies = ref.evaluate(_problem(ref.Model("timing", tuple(worlds), SOURCE)))
    assert len(policies) == strategies
    assert max(strategy.lower for strategy in policies) == value


def test_finite_state_survival_loss_and_rare_upside_enter_the_same_value_scale():
    worlds = []
    for name, probability, gain in (
        ("rare-opportunity", Fraction(1, 10), 101),
        ("regime-lost", Fraction(1, 10), -30),
        ("no-external-change", Fraction(4, 5), 0),
    ):
        root = _choice(
            0,
            "reform-opportunity",
            (
                ("status-quo", _reward("preserve-regime", 8, 0)),
                ("reform", _reward(name, gain, 0)),
                ("calibrated-risk", _reward(name, 2 * gain, 0)),
            ),
        )
        worlds.append(ref.World(name, probability, root))
    problem = _problem(ref.Model("reform-risk", tuple(worlds), SOURCE))
    assert ref.compare(problem, "reform", "status-quo").bounds == ref.Interval(
        Fraction(-9, 10), Fraction(-9, 10)
    )
    direction = ref.compare(problem, "calibrated-risk", "status-quo")
    assert direction.direction == "increase"
    assert direction.bounds == ref.Interval(Fraction(31, 5), Fraction(31, 5))


@pytest.mark.parametrize(
    ("actor", "control"), [(PARTNER, "ai"), (COUNTRY, "player"), (COUNTRY, "unknown")]
)
def test_strategy_cannot_adopt_a_partner_or_player_choice(actor, control):
    foreign_choice = _choice(
        2,
        "independent-response",
        (("accept", _reward("accept", 8, 2)), ("decline", _reward("decline", 0, 2))),
        actor=actor,
        control=control,
    )
    with pytest.raises(ValueError, match="其他回应须经原版转移"):
        ref.compare(_terminal_problem(foreign_choice), "candidate", "status-quo")


def test_native_partner_response_player_takeover_and_missing_opportunity():
    accepted = _reward("partner-accepts", 8, 2)
    rejected = ref.Transition(2, "partner-declines", ref.End(4))
    player_chosen = ref.Transition(1, "player-takes-over", rejected)
    absent = ref.Transition(1, "partner-opportunity-absent", ref.End(4))
    worlds = tuple(
        ref.World(
            state,
            Fraction(1, 4),
            _choice(0, "proposal", (("submit", response), ("wait", ref.End(4)))),
        )
        for state, response in (
            ("acceptance", accepted),
            ("rejection", rejected),
            ("player-takeover", player_chosen),
            ("no-opportunity", absent),
        )
    )
    result = ref.compare(_problem(ref.Model("native-response", worlds, SOURCE)), "submit", "wait")
    assert result.bounds == ref.Interval(2, 2)
    assert all(len(path.decisions) == 1 for path in result.candidate.trajectories)
    assert [path.events for path in result.candidate.trajectories] == [
        ((2, "partner-accepts"),),
        ((2, "partner-declines"),),
        ((1, "player-takes-over"), (2, "partner-declines")),
        ((1, "partner-opportunity-absent"),),
    ]


@pytest.mark.parametrize("hidden_contract_change", [False, True])
def test_opportunity_reader_contract_is_scoped_to_visible_role_binding(hidden_contract_change):
    worlds = []
    for target in (PARTNER, THIRD):
        for disclosed in (False, True):
            read = ref.Read("disruption", target, "boolean", "counterpart")
            reads = () if hidden_contract_change and target == PARTNER and disclosed else (read,)
            follow = _choice(
                2,
                "counterpart-opportunity",
                (
                    ("first", _reward("first", 0 if disclosed else 8, 2)),
                    ("second", _reward("second", 8 if disclosed else 0, 2)),
                ),
                bindings=(("target", target),),
                reads=reads,
            )
            root = _choice(0, "root", (("go", follow), ("wait", ref.End(4))))
            report = _report(disclosed, 1, entity=target, direction="counterpart")
            id_suffix = "yes" if disclosed else "no"
            worlds.append(
                ref.World(
                    f"{target.id.lower()}-{id_suffix}", Fraction(1, 4), root, reports=(report,)
                )
            )
    problem = _problem(ref.Model("counterparts", tuple(worlds), SOURCE))
    if hidden_contract_change:
        with pytest.raises(ValueError, match="同一机会的合法读取合同随隐藏路径变化"):
            ref.compare(problem, "go", "wait")
    else:
        result = ref.compare(problem, "go", "wait")
        assert result.bounds == ref.Interval(8, 8)
        assert all(path.decisions[-1][0].reports for path in result.candidate.trajectories)


def test_ordered_same_day_opportunities_can_only_use_already_learned_reports():
    read = ref.Read("disruption", COUNTRY, "boolean", "own")
    later = _choice(0, "recheck", (("wait", ref.End(2)),), reads=(read,), history=True, order=4)
    before_report = _choice(0, "other", (("wait", later),), reads=(read,), history=True, order=2)
    event = ref.Transition(
        0,
        "disruption",
        before_report,
        reports=(_report(True, 0, occurred_order=1, learned_order=3),),
        order=1,
    )
    result = ref.compare(_terminal_problem(event), "candidate", "status-quo")
    path = result.candidate.trajectories[0]
    assert path.event_trace == (((0, 1), "disruption"),)
    assert [moment for moment, _, _ in path.decision_trace] == [(0, 0), (0, 2), (0, 4)]
    assert [report.learning for report in path.report_trace] == [(0, 3)]
    assert not path.decisions[1][0].reports
    assert path.decisions[2][0].reports
    with pytest.raises(ValueError, match="反馈需在较晚时点"):
        replace(event, next=replace(before_report, order=1))
    with pytest.raises(ValueError, match="获知时点"):
        _report(True, 0, occurred_order=3, learned_order=2)


@pytest.mark.parametrize("remember", [False, True])
@pytest.mark.parametrize("visible", ["none", "report", "opportunity"])
def test_same_day_policy_uses_only_the_actual_opportunity_and_legal_report(remember, visible):
    worlds = []
    for hidden in (False, True):
        inspect_order = 3 if hidden else 2
        take_order = 5 if remember else inspect_order
        opportunity = "select-after-disruption" if visible == "opportunity" and hidden else "select"
        reports = (_report(hidden, 0, learned_order=1),) if visible == "report" else ()
        decision = _choice(
            0,
            opportunity,
            tuple(
                (
                    action,
                    ref.Transition(
                        0,
                        action,
                        ref.End(2),
                        effects=(_value(action, amount, 0),),
                        order=take_order,
                    ),
                )
                for action, amount in (
                    ("first", 0 if hidden else 8),
                    ("second", 8 if hidden else 0),
                )
            ),
            reads=(ref.Read("disruption", COUNTRY, "boolean", "own"),),
            remember_choices=remember,
            order=take_order,
        )
        if remember:
            decision = _choice(0, "inspect", (("continue", decision),), order=inspect_order)
        after_hidden: ref.Node = (
            ref.Transition(0, "unreported", decision, order=1) if hidden else decision
        )
        root = _choice(0, "root", (("go", after_hidden), ("wait", ref.End(2))))
        worlds.append(ref.World(f"world-{inspect_order}", Fraction(1, 2), root, reports=reports))
    result = ref.compare(_problem(ref.Model("same-day", tuple(worlds), SOURCE)), "go", "wait")
    expected = 4 if visible == "none" else 8
    assert result.bounds == ref.Interval(expected, expected)
    first, second = result.candidate.trajectories
    assert (first.decisions == second.decisions) is (visible == "none")
    assert first.decision_trace != second.decision_trace


def test_hidden_same_day_order_cannot_change_one_opportunity_reader_contract():
    read = ref.Read("disruption", COUNTRY, "boolean", "own")
    worlds = []
    for order, reads in ((2, (read,)), (3, ())):
        same_opportunity = _choice(
            0, "inspect", (("continue", ref.End(2)),), reads=reads, order=order
        )
        root = _choice(0, "root", (("go", same_opportunity), ("wait", ref.End(2))))
        worlds.append(ref.World(f"world-{order}", Fraction(1, 2), root))
    problem = _problem(ref.Model("same-day", tuple(worlds), SOURCE))
    with pytest.raises(ValueError, match="同一机会的合法读取合同随隐藏路径变化"):
        ref.compare(problem, "go", "wait")


@pytest.mark.parametrize(
    ("visibility", "expected", "report_count"),
    [("single", 4, 1), ("different-order", 8, 2), ("same-batch", 4, 2), ("duplicate", 4, 1)],
)
def test_report_history_tracks_observable_order_without_hidden_offsets(
    visibility, expected, report_count
):
    disruption = ref.Read("disruption", COUNTRY, "boolean", "own")
    capacity = ref.Read("capacity", COUNTRY, "points", "own")
    worlds = []
    for hidden in (False, True):
        choice_order = 5
        first = ref.Transition(
            0,
            "first",
            ref.End(2),
            effects=(_value("first", 0 if hidden else 8, 0),),
            order=choice_order,
        )
        second = ref.Transition(
            0,
            "second",
            ref.End(2),
            effects=(_value("second", 8 if hidden else 0, 0),),
            order=choice_order,
        )
        choice = _choice(
            0,
            "choose",
            (("first", first), ("second", second)),
            reads=(disruption, capacity),
            history=True,
            order=choice_order,
        )
        learned = 2 if hidden else 1
        supply = _report(True, 0, learned_order=learned)
        reports: tuple[ref.Report, ...] = (supply,)
        if visibility == "different-order":
            reports += (_report(7, 0, fact="capacity", learned_order=1 if hidden else 3),)
        elif visibility == "same-batch":
            reports += (_report(7, 0, fact="capacity", learned_order=learned),)
            if hidden:
                reports = tuple(reversed(reports))
        elif visibility == "duplicate" and hidden:
            reports += (supply, _report(False, 0, learned_order=1, observer=PARTNER))
        follow: ref.Node = ref.Transition(0, "unreported", choice, order=1) if hidden else choice
        root = _choice(0, "root", (("go", follow), ("wait", ref.End(2))))
        worlds.append(ref.World(f"world-{learned}", Fraction(1, 2), root, reports=reports))
    problem = _problem(ref.Model("report-timing", tuple(worlds), SOURCE))
    result = ref.compare(problem, "go", "wait")
    assert result.bounds == ref.Interval(expected, expected)
    first_path, second_path = result.candidate.trajectories
    first_info = first_path.decisions[1][0]
    second_info = second_path.decisions[1][0]
    assert len(first_info.reports) == len(second_info.reports) == report_count
    assert (first_info == second_info) is (visibility != "different-order")
    assert first_path.report_trace[0].learning != second_path.report_trace[0].learning


def test_exact_payoff_past_horizon_must_be_replaced_by_evidenced_tail():
    exact = _value("current", 3, 0)
    past_horizon = _value("after-end", 20, 0, end=5)
    invalid = ref.Transition(0, "gain", ref.End(4), effects=(exact, past_horizon))
    with pytest.raises(ValueError, match="精确终点期间越过终止时点"):
        ref.compare(_terminal_problem(invalid), "candidate", "status-quo")
    capped = replace(invalid, next=ref.End(4, ref.Interval(-4, 1), SOURCE), effects=(exact,))
    capped_problem = _terminal_problem(capped, budget=ref.Budget(horizon=4, error=5))
    result = ref.compare(capped_problem, "candidate", "status-quo")
    assert result.bounds == ref.Interval(-1, 4)
    assert result.direction == "vanilla"
    assert result.within_error_budget
    assert result.candidate.trajectories[0].tail == ref.Interval(-4, 1)
