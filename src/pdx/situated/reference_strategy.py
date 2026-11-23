"""有限图的独立精确参考求值。概率模型为全程联合分布。

图输入只声明模型、真实候选、时序和可读信息。原版或他国的裁决由模型给出，
本国策略仅在 Choice 节点选择。每个加权世界的一份外生历史供所有候选复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from itertools import groupby
from typing import TYPE_CHECKING, Literal

from .core_contracts import stable_id, unique

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .core_contracts import EntityKey, Observation, Scalar, Unit

type Number = int | Fraction
type Direction = Literal["increase", "decrease", "vanilla"]
type ResourceKind = Literal["stock", "capacity", "commitment", "time"]
type Control = Literal["ai", "player", "unknown"]
type Moment = tuple[int, int]
type RoleBindings = tuple[tuple[str, EntityKey], ...]


def _validate_moment(moment: Moment) -> None:
    if any(type(value) is not int or value < 0 for value in moment):
        raise ValueError("日期和同日顺序须为非负整数")


def _fraction(value: Number) -> Fraction:
    if type(value) not in (int, Fraction):
        raise ValueError("参考求值使用整数或精确分数")
    return Fraction(value)


@dataclass(frozen=True, slots=True)
class Interval:
    lower: Number
    upper: Number

    def __post_init__(self) -> None:
        if _fraction(self.lower) > _fraction(self.upper):
            raise ValueError("区间下界不可超过上界")

    def __add__(self, other: Interval) -> Interval:
        return Interval(self.lower + other.lower, self.upper + other.upper)

    def __sub__(self, other: Interval) -> Interval:
        return Interval(self.lower - other.upper, self.upper - other.lower)

    def scale(self, probability: Fraction) -> Interval:
        return Interval(self.lower * probability, self.upper * probability)

    def direction(self, margin: Number = 0) -> Direction:
        if _fraction(margin) < 0:
            raise ValueError("有意义差距不可为负数")
        if self.lower > margin:
            return "increase"
        if self.upper < -margin:
            return "decrease"
        return "vanilla"


_ZERO = Interval(0, 0)


@dataclass(frozen=True, slots=True)
class Resource:
    owner: EntityKey
    id: str
    unit: str
    kind: ResourceKind

    def __post_init__(self) -> None:
        stable_id(self.id, "Resource.id")
        stable_id(self.unit, "Resource.unit")
        if self.kind not in {"stock", "capacity", "commitment", "time"}:
            raise ValueError("资源类型无效")


@dataclass(frozen=True, slots=True)
class Balance:
    resource: Resource
    total: Number
    reserved: Number = 0

    def __post_init__(self) -> None:
        if not 0 <= _fraction(self.reserved) <= _fraction(self.total):
            raise ValueError("义务必须在当前资源总量内")


@dataclass(frozen=True, slots=True)
class Read:
    """在当前机会可读的具体事实及方向。"""

    fact: str
    entity: EntityKey
    unit: Unit
    direction: str

    def __post_init__(self) -> None:
        stable_id(self.fact, "Read.fact")
        stable_id(self.direction, "Read.direction")


@dataclass(frozen=True, slots=True)
class Report:
    """time 为实际获知时点，事件时点另存。"""

    observer: EntityKey
    observation: Observation
    direction: str
    occurred_at: int
    valid_until: int
    source: str
    occurred_order: int = field(default=0, kw_only=True)
    learned_order: int = field(default=0, kw_only=True)

    def __post_init__(self) -> None:
        stable_id(self.direction, "Report.direction")
        _validate_moment(self.occurrence)
        _validate_moment(self.learning)
        if (
            self.observer.kind != "country"
            or not self.source
            or self.occurrence > self.learning
            or not self.learning[0] <= self.valid_until
        ):
            raise ValueError("观测必须有来源、发生时点、获知时点和有效窗")

    @property
    def occurrence(self) -> Moment:
        return self.occurred_at, self.occurred_order

    @property
    def learning(self) -> Moment:
        return self.observation.time.evaluation, self.learned_order

    @property
    def read(self) -> Read:
        return Read(
            self.observation.spec_id,
            self.observation.entity,
            self.observation.unit,
            self.direction,
        )


@dataclass(frozen=True, slots=True)
class Attribution:
    perspective: EntityKey
    entity: EntityKey
    direction: str
    outcome: str
    unit: str
    start: int
    end: int
    baseline: str
    instance: str

    def __post_init__(self) -> None:
        for name in ("direction", "outcome", "unit", "baseline", "instance"):
            stable_id(getattr(self, name), f"Attribution.{name}")
        if not 0 <= self.start < self.end:
            raise ValueError("归因期间必须为非空半开区间")

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.perspective,
            self.entity,
            self.direction,
            self.outcome,
            self.unit,
            self.baseline,
            self.instance,
        )


@dataclass(frozen=True, slots=True)
class Endpoint:
    attribution: Attribution
    value: Number
    source: str

    def __post_init__(self) -> None:
        _fraction(self.value)
        if not self.source:
            raise ValueError("终点缺少来源")


@dataclass(frozen=True, slots=True)
class End:
    """精确期间止于 time。后续净价值另用有据的 tail 表示。"""

    time: int
    tail: Interval = _ZERO
    source: str = ""
    order: int = field(default=0, kw_only=True)

    def __post_init__(self) -> None:
        _validate_moment(_moment(self))
        if self.tail != _ZERO and not self.source:
            raise ValueError("截断尾部缺少上下界的证据")


@dataclass(frozen=True, slots=True)
class Transition:
    time: int
    event: str
    next: Node
    resources: tuple[tuple[Resource, Number], ...] = ()
    effects: tuple[Endpoint, ...] = ()
    reports: tuple[Report, ...] = ()
    blocked: Node | None = None
    blocked_event: str = "unavailable"
    order: int = field(default=0, kw_only=True)

    def __post_init__(self) -> None:
        _validate_moment(_moment(self))
        stable_id(self.event, "Transition.event")
        stable_id(self.blocked_event, "Transition.blocked_event")
        unique(tuple(resource for resource, _ in self.resources), "Transition.resources")
        for _, change in self.resources:
            _fraction(change)
        if any(item.occurrence != _moment(self) for item in self.reports):
            raise ValueError("转移报告的发生时点须对应触发事件")
        following = (self.next,) if self.blocked is None else (self.next, self.blocked)
        for successor in following:
            _check_edge(_moment(self), successor, after_transition=True)


@dataclass(frozen=True, slots=True)
class Choice:
    """真实机会提供的动作及其后续。

    bindings 记录当前可见角色，reads 限定当前消费者能用的事实。
    history 为真时允许可读事实的历史，remember_choices 为真时允许自己的先前行动。
    order 给同日节点排序，机会身份由可见的 opportunity 和 bindings 表示。
    """

    time: int
    opportunity: str
    options: tuple[tuple[str, Node], ...]
    bindings: RoleBindings = ()
    reads: tuple[Read, ...] = ()
    history: bool = False
    remember_choices: bool = False
    actor: EntityKey = field(kw_only=True)
    control: Control = field(kw_only=True)
    order: int = field(default=0, kw_only=True)

    def __post_init__(self) -> None:
        _validate_moment(_moment(self))
        stable_id(self.opportunity, "Choice.opportunity")
        if self.actor.kind != "country" or self.control not in {"ai", "player", "unknown"}:
            raise ValueError("选择须明确实际决策国和控制权")
        if not self.options:
            raise ValueError("没有出现的原版机会应沿原版转移")
        for action, _ in self.options:
            stable_id(action, "Choice.options")
        for role, _ in self.bindings:
            stable_id(role, "Choice.bindings")
        unique(tuple(action for action, _ in self.options), "Choice.options")
        unique(tuple(role for role, _ in self.bindings), "Choice.bindings")
        unique(self.reads, "Choice.reads")
        for _, successor in self.options:
            _check_edge(_moment(self), successor, after_transition=False)


type Node = Choice | Transition | End
type ActionMemory = tuple[int, str, RoleBindings, str]


def _moment(node: Node) -> Moment:
    return node.time, node.order


def _check_edge(moment: Moment, successor: Node, *, after_transition: bool) -> None:
    if _moment(successor) < moment or (
        _moment(successor) == moment
        and (
            isinstance(successor, Choice)
            or (after_transition and isinstance(successor, Transition))
        )
    ):
        raise ValueError("反馈需在较晚时点，机会结果可在本机会发生")


@dataclass(frozen=True, slots=True)
class World:
    id: str
    probability: Number
    root: Choice
    balances: tuple[Balance, ...] = ()
    reports: tuple[Report, ...] = ()

    def __post_init__(self) -> None:
        stable_id(self.id, "World.id")
        if not 0 < _fraction(self.probability) <= 1:
            raise ValueError("只显式枚举概率严格为正的世界")
        unique(tuple(balance.resource for balance in self.balances), "World.balances")
        if any(item.occurrence > _moment(self.root) for item in self.reports):
            raise ValueError("初始世界的报告须源于已有事件")


@dataclass(frozen=True, slots=True)
class Model:
    id: str
    worlds: tuple[World, ...]
    source: str

    def __post_init__(self) -> None:
        stable_id(self.id, "Model.id")
        unique(tuple(world.id for world in self.worlds), "Model.worlds")
        if not self.source or sum(world.probability for world in self.worlds) != 1:
            raise ValueError("模型必须有来源且世界的概率和等于 1")


@dataclass(frozen=True, slots=True)
class Budget:
    horizon: int = 64
    steps: int = 50_000
    worlds: int = 128
    policies: int = 2_048
    error: Number = 0

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not int or value < 1
                for value in (self.horizon, self.steps, self.worlds, self.policies)
            )
            or _fraction(self.error) < 0
        ):
            raise ValueError("小图预算必须有正的时域、步数、世界数和策略数及非负误差")


@dataclass(frozen=True, slots=True)
class Problem:
    perspective: EntityKey
    epoch: str
    baseline: str
    unit: str
    models: tuple[Model, ...]
    budget: Budget = Budget()
    error: Number = 0
    error_source: str = ""

    def __post_init__(self) -> None:
        stable_id(self.epoch, "Problem.epoch")
        stable_id(self.baseline, "Problem.baseline")
        stable_id(self.unit, "Problem.unit")
        unique(tuple(model.id for model in self.models), "Problem.models")
        if (
            self.perspective.kind != "country"
            or not self.models
            or _fraction(self.error) < 0
            or (self.error and not self.error_source)
        ):
            raise ValueError("比较须有国家视角、模型和有证据的非负误差")


@dataclass(frozen=True, slots=True)
class InformationSet:
    time: int
    opportunity: str
    actor: EntityKey
    bindings: RoleBindings
    offered: tuple[str, ...]
    # 历史报告使用获知日期和该日可见批次的相对顺序。
    reports: frozenset[tuple[Read, Moment | None, bool, Scalar]]
    choices: tuple[ActionMemory, ...]


type Policy = tuple[tuple[InformationSet, str], ...]


@dataclass(frozen=True, slots=True)
class Trajectory:
    model: str
    world: str
    probability: Number
    event_trace: tuple[tuple[Moment, str], ...]
    decision_trace: tuple[tuple[Moment, InformationSet, str], ...]
    endpoints: tuple[Endpoint, ...]
    attribution_sources: tuple[tuple[Attribution, tuple[str, ...]], ...]
    remaining_resources: tuple[tuple[Resource, Number], ...]
    value: Interval
    tail: Interval
    report_trace: tuple[Report, ...] = ()

    @property
    def events(self) -> tuple[tuple[int, str], ...]:
        """只按日期显示事件。完整先后顺序见 event_trace。"""
        return tuple((time, event) for (time, _), event in self.event_trace)

    @property
    def decisions(self) -> Policy:
        """按合法信息集回读实际采用的动作。"""
        return tuple((key, action) for _, key, action in self.decision_trace)


@dataclass(frozen=True, slots=True)
class Strategy:
    policy: Policy
    model_values: tuple[tuple[str, Interval], ...]
    trajectories: tuple[Trajectory, ...]
    tail_width: Number

    @property
    def lower(self) -> Number:
        return min(value.lower for _, value in self.model_values)


@dataclass(frozen=True, slots=True)
class Comparison:
    candidate: Strategy
    baseline: Strategy
    model_differences: tuple[tuple[str, Interval], ...]
    bounds: Interval
    direction: Direction
    within_error_budget: bool


class BudgetExceededError(ValueError):
    """精确展开超出预算，调用方须改用有据的截断或原版路径。"""


@dataclass(slots=True)
class _Search:
    problem: Problem
    root: InformationSet
    steps: int = 0
    definitions: dict[
        tuple[int, str, EntityKey, RoleBindings], tuple[frozenset[Read], bool, bool]
    ] = field(default_factory=dict)

    def visit(self, time: int) -> None:
        if not self.root.time <= time <= self.root.time + self.problem.budget.horizon:
            raise BudgetExceededError("小图超过时间窗，请声明有据的截断尾部")
        self.steps += 1
        if self.steps > self.problem.budget.steps:
            raise BudgetExceededError("小图超过展开步数预算")


def _information(
    perspective: EntityKey,
    epoch: str,
    choice: Choice,
    reports: Iterable[Report],
    memory: tuple[ActionMemory, ...],
) -> InformationSet:
    if choice.actor != perspective or choice.control != "ai":
        raise ValueError("仅本国 AI 控制下的真实机会可由策略选择，其他回应须经原版转移")
    visible: dict[tuple[Read, Moment], tuple[bool, Scalar]] = {}
    for report in reports:
        observation = report.observation
        learned = report.learning
        if (
            observation.time.epoch == epoch
            and report.observer == perspective
            and report.read in choice.reads
            and learned <= _moment(choice)
            and choice.time <= report.valid_until
            and observation.status == "known"
            and observation.value is not None
        ):
            key = (report.read, learned)
            value = (type(observation.value) is bool, observation.value)
            if visible.setdefault(key, value) != value:
                raise ValueError("同一事实的同次合法报告有冲突")
    reports_key: frozenset[tuple[Read, Moment | None, bool, Scalar]]
    if not choice.history:
        latest: dict[Read, Moment] = {}
        for read, learned in visible:
            latest[read] = max(latest.get(read, learned), learned)
        reports_key = frozenset(
            (read, None, *visible[read, learned]) for read, learned in latest.items()
        )
    else:
        # 先过滤掉未获知和不可读的报告，再按可见批次重排同日位置。
        arrivals = sorted({learned for _, learned in visible})
        positions = {
            learned: (day, rank)
            for day, batch_times in groupby(arrivals, key=lambda moment: moment[0])
            for rank, learned in enumerate(batch_times)
        }
        reports_key = frozenset(
            (read, positions[learned], *value) for (read, learned), value in visible.items()
        )
    return InformationSet(
        choice.time,
        choice.opportunity,
        choice.actor,
        tuple(sorted(choice.bindings)),
        tuple(sorted(action for action, _ in choice.options)),
        reports_key,
        memory if choice.remember_choices else (),
    )


def _start(problem: Problem) -> _Search:
    """根求值限定为一个可观察区域，允许该区域下多个隐藏世界。"""

    worlds = tuple(world for model in problem.models for world in model.worlds)
    if len(worlds) > problem.budget.worlds:
        raise BudgetExceededError("小图超过联合世界数预算")
    roots = {
        _information(problem.perspective, problem.epoch, world.root, world.reports, ())
        for world in worlds
    }
    if len(roots) != 1:
        raise ValueError("参考比较的根必须共享同一合法可观察历史和原版候选")
    return _Search(problem, roots.pop())


def _credit(
    problem: Problem,
    endpoint: Endpoint,
    credited: dict[Attribution, Endpoint],
    attribution_sources: dict[Attribution, set[str]],
    time: int,
) -> None:
    key = endpoint.attribution
    if (key.perspective, key.baseline, key.unit) != (
        problem.perspective,
        problem.baseline,
        problem.unit,
    ):
        raise ValueError("终点的视角、基准或价值单位超出本次比较")
    for prior, credited_endpoint in credited.items():
        if key == prior:
            if credited_endpoint.value != endpoint.value:
                raise ValueError("同一归因的价值冲突")
            attribution_sources[key].add(endpoint.source)
            return
        if key.identity == prior.identity and key.start < prior.end and prior.start < key.end:
            raise ValueError("同一归因的期间重叠")
    if key.start < time:
        raise ValueError("终点期间早于产生它的转移")
    credited[key] = endpoint
    attribution_sources[key] = {endpoint.source}


def _step(
    node: Transition, balances: dict[Resource, Number], events: list[tuple[Moment, str]]
) -> tuple[Node, bool]:
    updated: dict[Resource, Number] = {}
    for resource, change in node.resources:
        if resource not in balances:
            raise ValueError(f"资源 {resource.id} 缺少初始存量")
        updated[resource] = balances[resource] + change
    if any(value < 0 for value in updated.values()):
        if node.blocked is None:
            raise ValueError(f"资源不足时缺少 {node.event} 的原版裁决路径")
        events.append((_moment(node), node.blocked_event))
        return node.blocked, False
    balances.update(updated)
    events.append((_moment(node), node.event))
    return node.next, True


def _play(
    search: _Search, model: Model, world: World, policy: Mapping[InformationSet, str]
) -> Trajectory | InformationSet:
    problem = search.problem
    reports = list(world.reports)
    balances = {entry.resource: entry.total - entry.reserved for entry in world.balances}
    events: list[tuple[Moment, str]] = []
    decisions: list[tuple[Moment, InformationSet, str]] = []
    memory: tuple[ActionMemory, ...] = ()
    credited: dict[Attribution, Endpoint] = {}
    attribution_sources: dict[Attribution, set[str]] = {}
    node: Node = world.root
    while True:
        search.visit(node.time)
        if isinstance(node, End):
            if any(attribution.end > node.time for attribution in credited):
                raise ValueError("精确终点期间越过终止时点，未展开价值须计入有据尾部")
            value = sum(endpoint.value for endpoint in credited.values())
            return Trajectory(
                model.id,
                world.id,
                world.probability,
                tuple(events),
                tuple(decisions),
                tuple(credited.values()),
                tuple(
                    (key, tuple(sorted(sources))) for key, sources in attribution_sources.items()
                ),
                tuple(balances.items()),
                Interval(value, value) + node.tail,
                node.tail,
                tuple(reports),
            )
        if isinstance(node, Choice):
            key = _information(problem.perspective, problem.epoch, node, reports, memory)
            definition = (frozenset(node.reads), node.history, node.remember_choices)
            context = (node.time, node.opportunity, node.actor, key.bindings)
            if search.definitions.setdefault(context, definition) != definition:
                raise ValueError("同一机会的合法读取合同随隐藏路径变化")
            if key not in policy:
                return key
            action = policy[key]
            if action not in key.offered:
                raise ValueError(f"策略选择 {action} 超出原版提供的候选")
            decisions.append((_moment(node), key, action))
            memory += ((node.time, node.opportunity, key.bindings, action),)
            node = dict(node.options)[action]
            continue
        transition = node
        node, executed = _step(transition, balances, events)
        if executed:
            reports.extend(transition.reports)
            for endpoint in transition.effects:
                _credit(problem, endpoint, credited, attribution_sources, transition.time)


def _value(search: _Search, policy: Mapping[InformationSet, str]) -> Strategy | InformationSet:
    trajectories: list[Trajectory] = []
    model_values: list[tuple[str, Interval]] = []
    tail_width: Number = 0
    for model in search.problem.models:
        value = _ZERO
        tail = _ZERO
        for world in model.worlds:
            trajectory = _play(search, model, world, policy)
            if isinstance(trajectory, InformationSet):
                return trajectory
            trajectories.append(trajectory)
            probability = _fraction(world.probability)
            value += trajectory.value.scale(probability)
            tail += trajectory.tail.scale(probability)
        model_values.append((model.id, value))
        tail_width = max(tail_width, tail.upper - tail.lower)
    return Strategy(tuple(policy.items()), tuple(model_values), tuple(trajectories), tail_width)


def _evaluate(search: _Search, root_actions: tuple[str, ...]) -> tuple[Strategy, ...]:
    pending = [{search.root: action} for action in reversed(root_actions)]
    strategies: list[Strategy] = []
    while pending:
        policy = pending.pop()
        result = _value(search, policy)
        if isinstance(result, InformationSet):
            pending.extend({**policy, result: action} for action in reversed(result.offered))
        else:
            strategies.append(result)
            if len(strategies) > search.problem.budget.policies:
                raise BudgetExceededError("小图超过完整策略数预算")
    return tuple(strategies)


def evaluate(problem: Problem) -> tuple[Strategy, ...]:
    """按确定性顺序枚举所有非预知的可行策略。"""

    search = _start(problem)
    return _evaluate(search, search.root.offered)


def replay(problem: Problem, policy: Policy) -> Strategy:
    """用同一模型和世界重放一份完整策略。"""

    unique(tuple(information for information, _ in policy), "Policy")
    result = _value(_start(problem), dict(policy))
    if isinstance(result, InformationSet):
        raise ValueError(f"策略没有覆盖原版机会 {result.opportunity}")
    used = {information for path in result.trajectories for information, _ in path.decisions}
    if used != {information for information, _ in policy}:
        raise ValueError("策略包含未到达的信息集")
    return result


def _difference(
    problem: Problem, candidate: Strategy, baseline: Strategy
) -> tuple[tuple[str, Interval], ...]:
    error = Interval(-problem.error, problem.error)
    return tuple(
        (model, value - other + error)
        for (model, value), (_, other) in zip(
            candidate.model_values, baseline.model_values, strict=True
        )
    )


def _compare(
    problem: Problem, candidate: Strategy, baseline: Strategy, margin: Number
) -> Comparison:
    differences = _difference(problem, candidate, baseline)
    bounds = Interval(
        min(value.lower for _, value in differences),
        max(value.upper for _, value in differences),
    )
    within_budget = (
        candidate.tail_width + baseline.tail_width + problem.error <= problem.budget.error
    )
    return Comparison(
        candidate,
        baseline,
        differences,
        bounds,
        bounds.direction(margin) if within_budget else "vanilla",
        within_budget,
    )


def compare(problem: Problem, candidate: str, baseline: str, *, margin: Number = 0) -> Comparison:
    """对每个根动作固定一份最大化最差模型下界的参考策略，再作同模型配对。"""

    _ZERO.direction(margin)
    search = _start(problem)
    if candidate == baseline or not {candidate, baseline} <= set(search.root.offered):
        raise ValueError("比较应选择两个不同的真实根候选")
    strategies = _evaluate(search, (candidate, baseline))
    candidate_strategy = max(
        (strategy for strategy in strategies if strategy.policy[0][1] == candidate),
        key=lambda strategy: strategy.lower,
    )
    baseline_strategy = max(
        (strategy for strategy in strategies if strategy.policy[0][1] == baseline),
        key=lambda strategy: strategy.lower,
    )
    return _compare(problem, candidate_strategy, baseline_strategy, margin)


def compare_policies(
    problem: Problem, candidate: Policy, baseline: Policy, *, margin: Number = 0
) -> Comparison:
    """配对比较指定的可行策略，包括已经给定的原版续策。"""

    _ZERO.direction(margin)
    return _compare(problem, replay(problem, candidate), replay(problem, baseline), margin)


def dominates(problem: Problem, candidate: str, baseline: str, *, margin: Number = 0) -> bool:
    """核对是否存在一份候选续策能胜过基准的所有可行续策。"""

    _ZERO.direction(margin)
    search = _start(problem)
    if candidate == baseline or not {candidate, baseline} <= set(search.root.offered):
        raise ValueError("比较应选择两个不同的真实根候选")
    strategies = _evaluate(search, (candidate, baseline))
    baselines = tuple(strategy for strategy in strategies if strategy.policy[0][1] == baseline)
    return any(
        all(
            _compare(problem, strategy, other, margin).direction == "increase"
            for other in baselines
        )
        for strategy in strategies
        if strategy.policy[0][1] == candidate
    )
