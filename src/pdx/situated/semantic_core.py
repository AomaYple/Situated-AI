"""A2 的纯事实→处境→行动参考语义。

本模块只消费 ``core_contracts`` 中不可变的观察、事实、快照和重评合同。
它不读取生成器、PDX 或运行时状态，也不把不同消费者的项压成总分。
所有派生结果均是不可变值；重评可通过依赖索引只替换受影响节点。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, cast, get_args

from . import core_contracts as contracts
from .expressions import All, BooleanLiteral, Compare, Not
from .expressions import Any as AnyExpr

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

FacetKind = Literal["need", "capacity", "opportunity", "risk", "commitment"]
Knowledge = contracts.Knowledge
Scope = Literal["country", "state", "building", "law", "good", "market", "target"]
Horizon = Literal["short", "long", "current"]
Truth = Literal[True, False, None]


class InvalidSemanticInputError(ValueError):
    """事实值通过对象构造后，在绑定到 FactSpec 时仍非法。"""


FacetExpression = All | AnyExpr | BooleanLiteral | Compare | Not


def _ids(values: tuple[str, ...], path: str) -> None:
    if type(values) is not tuple:
        raise ValueError(f"{path}: 必须为不可变 tuple")
    for value in values:
        if type(value) is not str:
            raise ValueError(f"{path}: 必须为字符串 ID")
        contracts.stable_id(value, path)
    contracts.unique(values, path)


def _unit(unit: contracts.Unit) -> None:
    if unit not in get_args(contracts.Unit):
        raise ValueError("语义项单位无效")


def _value_status(status: Knowledge, value: contracts.Scalar | None) -> None:
    if status not in get_args(Knowledge):
        raise ValueError("语义项状态无效")
    if value is not None and type(value) not in (bool, int, float, str):
        raise ValueError("语义项必须为不可变标量")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("语义项数值必须有限")
    if (status == "known") != (value is not None):
        raise ValueError("语义项已知性与值不一致")


def _expression_inputs(expression: FacetExpression) -> frozenset[str]:
    """只接受有限声明 IR，防止可调用对象隐式读取未登记依赖。"""
    if type(expression) is Compare:
        contracts.stable_id(expression.fact_id, "Compare.fact_id")
        if expression.operator not in {"eq", "ne", "gt", "ge", "lt", "le"}:
            raise InvalidSemanticInput("Compare 操作无效")
        if type(expression.expected) not in (bool, int, float):
            raise InvalidSemanticInput("Compare 阈值类型无效")
        if isinstance(expression.expected, float) and not math.isfinite(expression.expected):
            raise InvalidSemanticInput("Compare 阈值必须有限")
        return frozenset((expression.fact_id,))
    if type(expression) is BooleanLiteral:
        if expression.value is not None and type(expression.value) is not bool:
            raise InvalidSemanticInput("BooleanLiteral 必须是三值布尔")
        return frozenset()
    if type(expression) in (All, AnyExpr):
        compound = cast("All | AnyExpr", expression)
        if type(compound.items) is not tuple:
            raise InvalidSemanticInput("复合表达式必须为不可变 tuple")
        return frozenset(
            source
            for item in compound.items
            for source in _expression_inputs(cast("FacetExpression", item))
        )
    if type(expression) is Not:
        return _expression_inputs(cast("FacetExpression", expression.item))
    raise InvalidSemanticInput("表达式必须使用现有有限声明 IR")


def _validate_expression(expression: FacetExpression | None, sources: tuple[str, ...]) -> None:
    if expression is not None and not _expression_inputs(expression) <= set(sources):
        raise InvalidSemanticInput("表达式读取未登记来源事实")


def _validate_expression_types(
    expression: FacetExpression | None, facts: Mapping[str, contracts.FactSpec]
) -> None:
    if expression is None or type(expression) is BooleanLiteral:
        return
    if type(expression) is Compare:
        if expression.fact_id not in facts:
            raise InvalidSemanticInput(f"Compare: 未声明事实 {expression.fact_id}")
        fact = facts[expression.fact_id]
        if fact.kind == "boolean":
            valid = type(expression.expected) is bool and expression.operator in {"eq", "ne"}
        else:
            valid = fact.kind != "enum" and type(expression.expected) in (int, float)
        if not valid:
            raise InvalidSemanticInput(f"Compare.{fact.id}: 阈值与事实类型不一致")
        return
    if type(expression) in (All, AnyExpr):
        for item in cast("All | AnyExpr", expression).items:
            _validate_expression_types(cast("FacetExpression", item), facts)
    elif type(expression) is Not:
        _validate_expression_types(cast("FacetExpression", expression.item), facts)


def _value_unit(value: contracts.Scalar | None, unit: contracts.Unit) -> None:
    if value is None:
        return
    valid = (
        type(value) is bool
        if unit == "boolean"
        else type(value) is str
        if unit == "enum"
        else type(value) in (int, float)
    )
    if not valid:
        raise InvalidSemanticInput("语义项值类型与单位不一致")


def _status_rank(status: Knowledge) -> int:
    # invalid is handled as an exception; this order keeps the most specific
    # capability/freshness explanation when several inputs are unavailable.
    return {"known": 0, "unknown": 1, "stale": 2, "unsupported": 3, "invalid": 4}[status]


def _combine_status(statuses: Iterable[Knowledge]) -> Knowledge:
    values = tuple(statuses)
    return cast("Knowledge", max(values, key=_status_rank, default="known"))


@dataclass(frozen=True, slots=True)
class FacetSpec:
    """一份处境表达式声明；阈值由调用者声明，不由核心隐式添加。"""

    id: str
    category: FacetKind
    unit: contracts.Unit
    scope: str
    source_fact_ids: tuple[str, ...]
    expression: FacetExpression | None = None

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "FacetSpec.id")
        _ids(self.source_fact_ids, f"FacetSpec.{self.id}.source_fact_ids")
        _unit(self.unit)
        if (
            not self.id
            or not self.source_fact_ids
            or any(not item for item in self.source_fact_ids)
        ):
            raise ValueError("FacetSpec 必须有稳定 ID 和来源事实")
        if self.category not in {"need", "capacity", "opportunity", "risk", "commitment"}:
            raise ValueError(f"FacetSpec.{self.id}: 类别无效")
        if type(self.scope) is not str or not self.scope:
            raise ValueError(f"FacetSpec.{self.id}: 作用域缺失")
        if len(set(self.source_fact_ids)) != len(self.source_fact_ids):
            raise ValueError(f"FacetSpec.{self.id}: 重复来源事实")
        _validate_expression(self.expression, self.source_fact_ids)
        if self.expression is not None and self.unit != "boolean":
            raise InvalidSemanticInput("处境表达式的结果单位必须为 boolean")


@dataclass(frozen=True, slots=True)
class SituationFacet:
    id: str
    category: FacetKind
    unit: contracts.Unit
    scope: str
    status: Knowledge
    value: contracts.Scalar | None
    source_fact_ids: tuple[str, ...]
    explanation: str = ""
    source_statuses: tuple[tuple[str, Knowledge], ...] = ()
    snapshot_identity: (
        tuple[contracts.EntityKey, contracts.EntityKey | None, str, contracts.TimeIdentity] | None
    ) = None

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "SituationFacet.id")
        _ids(self.source_fact_ids, f"SituationFacet.{self.id}.source_fact_ids")
        _unit(self.unit)
        _value_status(self.status, self.value)
        _value_unit(self.value, self.unit)
        if (
            self.category not in get_args(FacetKind)
            or type(self.scope) is not str
            or not self.scope
        ):
            raise ValueError("SituationFacet 类别或作用域无效")
        if type(self.source_statuses) is not tuple:
            raise ValueError("SituationFacet.source_statuses: 必须为不可变 tuple")
        if self.source_statuses and (
            tuple(name for name, _ in self.source_statuses) != self.source_fact_ids
            or any(status not in get_args(Knowledge) for _, status in self.source_statuses)
        ):
            raise ValueError("SituationFacet.source_statuses: 来源状态不一致")
        if not self.id or not self.source_fact_ids:
            raise ValueError("SituationFacet 必须有身份和来源")
        if self.status == "known" and self.value is None:
            raise ValueError(f"SituationFacet.{self.id}: known 必须有值")
        if self.status != "known" and self.value is not None:
            raise ValueError(f"SituationFacet.{self.id}: {self.status} 不得携带值")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError(f"SituationFacet.{self.id}: 数值必须有限")

    @property
    def dependencies(self) -> tuple[str, ...]:
        return self.source_fact_ids


@dataclass(frozen=True, slots=True)
class AssessmentTerm:
    """一个仍保留单位、期限和来源的收益或成本项。"""

    id: str
    kind: Literal["benefit", "cost"]
    unit: contracts.Unit
    scope: str
    value: contracts.Scalar | None
    status: Knowledge = "known"
    source_ids: tuple[str, ...] = ()
    horizon: Horizon = "current"
    baseline: str = ""

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "AssessmentTerm.id")
        _ids(self.source_ids, f"AssessmentTerm.{self.id}.source_ids")
        _unit(self.unit)
        _value_status(self.status, self.value)
        _value_unit(self.value, self.unit)
        if self.baseline:
            contracts.stable_id(self.baseline, f"AssessmentTerm.{self.id}.baseline")
        if (
            not self.id
            or self.kind not in {"benefit", "cost"}
            or (type(self.scope) is not str or not self.scope)
        ):
            raise ValueError("AssessmentTerm 身份、方向或作用域无效")
        if self.status == "known" and self.value is None:
            raise ValueError(f"AssessmentTerm.{self.id}: known 必须有值")
        if self.status != "known" and self.value is not None:
            raise ValueError(f"AssessmentTerm.{self.id}: 未知项不得携带值")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError(f"AssessmentTerm.{self.id}: 数值必须有限")
        if self.horizon not in {"short", "long", "current"}:
            raise ValueError(f"AssessmentTerm.{self.id}: 期限无效")

    @property
    def dependencies(self) -> tuple[str, ...]:
        return self.source_ids


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """具体候选行动声明；仅描述评估，不执行或改变原版资格。"""

    id: str
    consumer_id: str
    actor: contracts.EntityKey
    target: contracts.EntityKey | None
    depends_on: tuple[str, ...] = ()
    benefits: tuple[AssessmentTerm, ...] = ()
    costs: tuple[AssessmentTerm, ...] = ()
    eligibility: FacetExpression | None = None
    eligibility_facts: tuple[str, ...] = ()
    objective_ids: tuple[str, ...] = ()
    exit_when: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "ActionSpec.id")
        contracts.stable_id(self.consumer_id, "ActionSpec.consumer_id")
        _ids(self.depends_on, f"ActionSpec.{self.id}.depends_on")
        _ids(self.eligibility_facts, f"ActionSpec.{self.id}.eligibility_facts")
        _ids(self.objective_ids, f"ActionSpec.{self.id}.objective_ids")
        if not isinstance(self.actor, contracts.EntityKey) or (
            self.target is not None and not isinstance(self.target, contracts.EntityKey)
        ):
            raise ValueError("ActionSpec 对象身份类型无效")
        for terms, kind in ((self.benefits, "benefit"), (self.costs, "cost")):
            if type(terms) is not tuple or any(
                not isinstance(term, AssessmentTerm) or term.kind != kind for term in terms
            ):
                raise ValueError(f"ActionSpec.{self.id}: 收益成本项类型或方向无效")
        if type(self.exit_when) is not tuple or any(
            type(item) is not str or not item for item in self.exit_when
        ):
            raise ValueError(f"ActionSpec.{self.id}: 退出依据必须为不可变字符串 tuple")
        if not self.id or not self.consumer_id or self.actor.kind != "country":
            raise ValueError("ActionSpec 身份或 actor 无效")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"ActionSpec.{self.id}: 重复依赖")
        if len(set(self.eligibility_facts)) != len(self.eligibility_facts):
            raise ValueError(f"ActionSpec.{self.id}: 重复资格事实")
        if len(set(self.objective_ids)) != len(self.objective_ids):
            raise ValueError(f"ActionSpec.{self.id}: 重复利益依赖")
        _validate_expression(self.eligibility, self.eligibility_facts)


@dataclass(frozen=True, slots=True)
class ActionAssessment:
    candidate_id: str
    consumer_id: str
    actor: contracts.EntityKey
    target: contracts.EntityKey | None
    benefits: tuple[AssessmentTerm, ...]
    costs: tuple[AssessmentTerm, ...]
    qualification: Knowledge
    eligible: bool | None
    qualification_evidence: tuple[str, ...]
    unknowns: tuple[str, ...]
    dependencies: tuple[str, ...]
    exit_when: tuple[str, ...] = ()
    objective_ids: tuple[str, ...] = ()
    snapshot_identity: (
        tuple[contracts.EntityKey, contracts.EntityKey | None, str, contracts.TimeIdentity] | None
    ) = None


@dataclass(frozen=True, slots=True)
class _EvaluationBasis:
    snapshot: contracts.SituationSnapshot
    facts: tuple[contracts.FactSpec, ...]
    facets: tuple[FacetSpec, ...]
    actions: tuple[ActionSpec, ...]
    schedule: contracts.EvaluationSchedule
    objectives: tuple[contracts.InterestSpec, ...]


@dataclass(frozen=True, slots=True)
class SemanticEvaluation:
    facets: tuple[SituationFacet, ...]
    actions: tuple[ActionAssessment, ...]
    _basis: _EvaluationBasis | None = field(default=None, repr=False, compare=False)


def _observations(
    snapshot: contracts.SituationSnapshot,
    facts: tuple[contracts.FactSpec, ...],
    schedule: contracts.EvaluationSchedule,
) -> dict[str, contracts.Observation]:
    try:
        snapshot.validate(facts, schedule)
    except ValueError as exc:
        raise InvalidSemanticInput(str(exc)) from exc
    return {item.spec_id: item for item in snapshot.observations}


def _raw_values(observations: Mapping[str, contracts.Observation]) -> dict[str, object | None]:
    return {
        key: item.value if item.status == "known" else None for key, item in observations.items()
    }


def _scope_entity(
    scope: str, snapshot: contracts.SituationSnapshot, *, path: str
) -> contracts.EntityKey:
    """Resolve country to the actor, target or a concrete local kind to the target."""
    if scope not in (*get_args(contracts.EntityKind), "target"):
        raise InvalidSemanticInput(f"{path}: 未声明作用域 {scope}")
    entity = snapshot.actor if scope == "country" else snapshot.target
    if entity is None or scope not in {"target", entity.kind}:
        raise InvalidSemanticInput(f"{path}: 作用域对象与快照不匹配")
    return entity


def _validate_fact_binding(
    fact: contracts.FactSpec,
    snapshot: contracts.SituationSnapshot,
    *,
    scope: str,
    path: str,
) -> None:
    """Require a raw declaration to identify the same entity as its fact.

    ``country`` identifies the snapshot actor. Other concrete kinds and
    ``target`` identify its target. Unknown observations do not hide malformed
    object or consumer bindings.
    """

    expected = snapshot.actor if fact.binding == "actor" else snapshot.target
    if expected is None or expected.kind != fact.entity_kind:
        raise InvalidSemanticInput(f"{path}: 事实对象、消费者或作用域与快照不匹配")
    if _scope_entity(scope, snapshot, path=path) != expected:
        raise InvalidSemanticInput(f"{path}: 作用域与事实对象不匹配")
    if snapshot.consumer_id not in fact.consumer_ids:
        raise InvalidSemanticInput(f"{path}: 事实未接线到当前消费者")


def derive_facets(
    snapshot: contracts.SituationSnapshot,
    facts: Sequence[contracts.FactSpec],
    specs: Sequence[FacetSpec],
    schedule: contracts.EvaluationSchedule,
) -> tuple[SituationFacet, ...]:
    """按事实状态和声明表达式纯派生五类处境项。"""

    observations = _observations(snapshot, tuple(facts), schedule)
    declared = {item.id: item for item in facts}
    values = _raw_values(observations)
    result: list[SituationFacet] = []
    for spec in specs:
        missing = [name for name in spec.source_fact_ids if name not in declared]
        if missing:
            raise InvalidSemanticInput(f"{spec.id}: 未声明来源事实 {missing}")
        _validate_expression_types(spec.expression, declared)
        # Expression facets still read the declared facts from the same
        # snapshot.  Do not let a Compare/All/Any expression bypass the
        # actor/target, scope, entity-kind, and consumer binding contract that
        # raw facets already enforce.
        for name in spec.source_fact_ids:
            _validate_fact_binding(
                declared[name], snapshot, scope=spec.scope, path=f"{spec.id}.{name}"
            )
        if spec.expression is None and any(
            declared[name].unit != spec.unit for name in spec.source_fact_ids
        ):
            raise InvalidSemanticInput(f"{spec.id}: 来源事实单位与处境单位不一致")
        source_statuses: list[Knowledge] = []
        for name in spec.source_fact_ids:
            item = observations.get(name)
            status = item.status if item is not None else "unknown"
            if status == "invalid":
                raise InvalidSemanticInput(f"{spec.id}: 来源事实 {name} invalid")
            source_statuses.append(status)
        status = _combine_status(source_statuses)
        value: contracts.Scalar | None = None
        if spec.expression is not None:
            outcome = spec.expression.evaluate(values)
            value = cast("contracts.Scalar | None", outcome)
            status = (
                "known" if value is not None else _combine_status((*source_statuses, "unknown"))
            )
        elif status == "known":
            raw = values.get(spec.source_fact_ids[0])
            if raw is not None and (not isinstance(raw, float) or math.isfinite(raw)):
                value = cast("contracts.Scalar", raw)
        result.append(
            SituationFacet(
                spec.id,
                spec.category,
                spec.unit,
                spec.scope,
                status,
                value,
                spec.source_fact_ids,
                f"{spec.category} derived from {', '.join(spec.source_fact_ids)}",
                tuple(zip(spec.source_fact_ids, source_statuses, strict=True)),
                (snapshot.actor, snapshot.target, snapshot.consumer_id, snapshot.time),
            )
        )
    return tuple(result)


def _source_status(
    name: str,
    facts: Mapping[str, contracts.FactSpec],
    observations: Mapping[str, contracts.Observation],
    facets: Mapping[str, SituationFacet],
) -> Knowledge:
    if name in facets:
        return facets[name].status
    if name not in facts:
        raise InvalidSemanticInput(f"未声明来源 {name}")
    observation = observations.get(name)
    return observation.status if observation is not None else "unknown"


def _objective_status(
    objective: contracts.InterestSpec,
    snapshot: contracts.SituationSnapshot,
    facts: Mapping[str, contracts.FactSpec],
    observations: Mapping[str, contracts.Observation],
) -> Knowledge:
    if (
        objective.actor != snapshot.actor
        or objective.target != snapshot.target
        or snapshot.consumer_id not in objective.consumer_ids
        or objective.starts.epoch != snapshot.time.epoch
    ):
        raise InvalidSemanticInput(f"{objective.id}: 利益对象、消费者或时间串接")
    for name in objective.source_fact_ids:
        if name not in facts or snapshot.consumer_id not in facts[name].consumer_ids:
            raise InvalidSemanticInput(f"{objective.id}: 未声明或未接线利益来源 {name}")
    try:
        facts[objective.baseline.spec_id].validate_observation(
            objective.baseline,
            actor=objective.actor,
            target=objective.target,
            consumer_id=snapshot.consumer_id,
            time=objective.starts,
        )
    except ValueError as exc:
        raise InvalidSemanticInput(f"{objective.id}: 基准无效: {exc}") from exc
    if not set(objective.baseline.sources) <= set(facts[objective.baseline.spec_id].sources):
        raise InvalidSemanticInput(f"{objective.id}: 基准证据与声明来源不一致")
    if (
        snapshot.time == objective.starts
        and observations.get(objective.baseline.spec_id) != objective.baseline
    ):
        raise InvalidSemanticInput(f"{objective.id}: 开始时点快照与现状基准不一致")
    if snapshot.time.evaluation < objective.starts.evaluation:
        return "unknown"
    if snapshot.time.evaluation > objective.deadline.evaluation:
        return "stale"
    return _combine_status(
        (
            "known" if objective.status == "known" else "unknown",
            objective.baseline.status,
            *(_source_status(name, facts, observations, {}) for name in objective.source_fact_ids),
        )
    )


def _resolved_term(
    term: AssessmentTerm,
    facts: Mapping[str, contracts.FactSpec],
    observations: Mapping[str, contracts.Observation],
    facets: Mapping[str, SituationFacet],
    objectives: Mapping[str, Knowledge],
    snapshot: contracts.SituationSnapshot,
) -> AssessmentTerm:
    entity = _scope_entity(term.scope, snapshot, path=term.id)
    for name in term.source_ids:
        source = facets[name] if name in facets else facts.get(name)
        if source is None:
            raise InvalidSemanticInput(f"{term.id}: 未声明来源 {name}")
        if isinstance(source, contracts.FactSpec):
            # Numeric terms carry a concrete value and therefore must retain
            # the fact's entity scope. Boolean facts remain valid as gates.
            if source.unit != "boolean":
                _validate_fact_binding(source, snapshot, scope=term.scope, path=f"{term.id}.{name}")
        elif source.unit != "boolean" and entity != _scope_entity(
            source.scope, snapshot, path=f"{term.id}.{name}"
        ):
            raise InvalidSemanticInput(f"{term.id}: 作用域与来源处境不匹配")
        if source is not None and source.unit not in {"boolean", term.unit}:
            raise InvalidSemanticInput(f"{term.id}: 来源 {name} 单位与评估项不一致")
    statuses = [term.status]
    statuses.extend(_source_status(name, facts, observations, facets) for name in term.source_ids)
    if term.baseline:
        if term.baseline not in objectives:
            raise InvalidSemanticInput(f"{term.id}: 未绑定现状基准 {term.baseline}")
        statuses.append(objectives[term.baseline])
    status = _combine_status(statuses)
    if status == "invalid":
        raise InvalidSemanticInput(f"{term.id}: invalid 来源")
    return replace(term, status=status, value=term.value if status == "known" else None)


def assess_actions(
    actions: Sequence[ActionSpec],
    facets: Sequence[SituationFacet],
    snapshot: contracts.SituationSnapshot,
    facts: Sequence[contracts.FactSpec],
    schedule: contracts.EvaluationSchedule,
    objectives: Sequence[contracts.InterestSpec] = (),
) -> tuple[ActionAssessment, ...]:
    """保留各项与原版资格的已知性；未声明资格不构成合格证据。"""
    observations = _observations(snapshot, tuple(facts), schedule)
    declared = {item.id: item for item in facts}
    values = _raw_values(observations)
    facet_map = {item.id: item for item in facets}
    objective_map = {item.id: item for item in objectives}
    if len(objective_map) != len(objectives) or len(facet_map) != len(facets):
        raise InvalidSemanticInput("处境或利益身份重复")
    if any(
        item.snapshot_identity
        != (snapshot.actor, snapshot.target, snapshot.consumer_id, snapshot.time)
        for item in facets
    ):
        raise InvalidSemanticInput("处境对象、消费者或时点与快照串接")
    for facet in facets:
        _scope_entity(facet.scope, snapshot, path=facet.id)
        for name in facet.source_fact_ids:
            if name not in declared:
                raise InvalidSemanticInput(f"{facet.id}: 未声明来源事实 {name}")
            if facet.unit != "boolean":
                _validate_fact_binding(
                    declared[name], snapshot, scope=facet.scope, path=f"{facet.id}.{name}"
                )
    result: list[ActionAssessment] = []
    for action in actions:
        _validate_expression_types(action.eligibility, declared)
        if (action.actor, action.target, action.consumer_id) != (
            snapshot.actor,
            snapshot.target,
            snapshot.consumer_id,
        ):
            raise InvalidSemanticInput(f"{action.id}: 行动对象或消费者与快照串接")
        missing_facet = [name for name in action.depends_on if name not in facet_map]
        if missing_facet:
            raise InvalidSemanticInput(f"{action.id}: 未找到处境依赖 {missing_facet}")
        bound_objectives = dict.fromkeys(
            (
                *action.objective_ids,
                *(term.baseline for term in (*action.benefits, *action.costs) if term.baseline),
            )
        )
        objective_statuses: dict[str, Knowledge] = {}
        for name in bound_objectives:
            if name not in objective_map:
                raise InvalidSemanticInput(f"{action.id}: 未声明利益 {name}")
            objective_statuses[name] = _objective_status(
                objective_map[name], snapshot, declared, observations
            )
        dependencies = list(action.depends_on)
        dependencies.extend(action.eligibility_facts)
        dependencies.extend(
            source for term in (*action.benefits, *action.costs) for source in term.source_ids
        )
        dependencies.extend(
            source for name in action.depends_on for source in facet_map[name].source_fact_ids
        )
        dependencies.extend(
            source for name in bound_objectives for source in objective_map[name].source_fact_ids
        )
        for name in tuple(dependencies):
            if name in facet_map:
                dependencies.extend(facet_map[name].source_fact_ids)
        dependencies = list(dict.fromkeys(dependencies))
        source_statuses = {
            name: _source_status(name, declared, observations, facet_map) for name in dependencies
        }
        statuses = [source_statuses[name] for name in action.eligibility_facts]
        qualification = _combine_status(statuses)
        eligible: bool | None = None
        if action.eligibility is not None:
            eligible = action.eligibility.evaluate(values)
            if eligible is None:
                qualification = _combine_status((*statuses, "unknown"))
            else:
                qualification = "known"
        elif action.eligibility is None:
            qualification = _combine_status((*statuses, "unknown"))
        benefits = tuple(
            _resolved_term(term, declared, observations, facet_map, objective_statuses, snapshot)
            for term in action.benefits
        )
        costs = tuple(
            _resolved_term(term, declared, observations, facet_map, objective_statuses, snapshot)
            for term in action.costs
        )
        unknowns = tuple(
            dict.fromkeys(
                (
                    *(term.id for term in (*benefits, *costs) if term.status != "known"),
                    *(name for name, status in source_statuses.items() if status != "known"),
                    *(name for name, status in objective_statuses.items() if status != "known"),
                )
            )
        )
        result.append(
            ActionAssessment(
                action.id,
                action.consumer_id,
                action.actor,
                action.target,
                benefits,
                costs,
                qualification,
                eligible,
                action.eligibility_facts,
                unknowns,
                tuple(dependencies),
                action.exit_when,
                tuple(bound_objectives),
                (snapshot.actor, snapshot.target, snapshot.consumer_id, snapshot.time),
            )
        )
    return tuple(result)


def dependency_index(
    facet_specs: Sequence[FacetSpec],
    actions: Sequence[ActionSpec],
    objectives: Sequence[contracts.InterestSpec] = (),
) -> dict[str, tuple[str, ...]]:
    """返回事实→直接或传递依赖节点的稳定索引。"""
    result: dict[str, set[str]] = defaultdict(set)
    facet_map = {item.id: item for item in facet_specs}
    objective_map = {item.id: item for item in objectives}
    for spec in facet_specs:
        for source in spec.source_fact_ids:
            result[source].add(spec.id)
    for action in actions:
        direct = set(action.eligibility_facts)
        direct.update(
            source for term in (*action.benefits, *action.costs) for source in term.source_ids
        )
        for facet_id in (*action.depends_on, *tuple(direct)):
            if facet_id in facet_map:
                direct.update(facet_map[facet_id].source_fact_ids)
            elif facet_id in action.depends_on:
                raise InvalidSemanticInput(f"{action.id}: 未找到处境依赖 {facet_id}")
        objective_ids = (
            *action.objective_ids,
            *(term.baseline for term in (*action.benefits, *action.costs) if term.baseline),
        )
        for name in objective_ids:
            if name not in objective_map:
                raise InvalidSemanticInput(f"{action.id}: 未声明利益 {name}")
            direct.update(objective_map[name].source_fact_ids)
        for source in direct - set(facet_map):
            result[source].add(action.id)
    facet_ids = set(facet_map)
    return {
        key: tuple(sorted(value, key=lambda item: (item not in facet_ids, item)))
        for key, value in sorted(result.items())
    }


def recompute(
    snapshot: contracts.SituationSnapshot,
    facts: Sequence[contracts.FactSpec],
    facet_specs: Sequence[FacetSpec],
    actions: Sequence[ActionSpec],
    schedule: contracts.EvaluationSchedule,
    *,
    previous: SemanticEvaluation | None = None,
    changed_facts: Sequence[str] = (),
    objectives: Sequence[contracts.InterestSpec] = (),
) -> SemanticEvaluation:
    """只计算失效节点；求值时点、声明及绑定改变时丢弃旧求值缓存。"""
    observations = _observations(snapshot, tuple(facts), schedule)
    identities = [
        *(item.id for item in facts),
        *(item.id for item in facet_specs),
        *(item.id for item in actions),
        *(item.id for item in objectives),
    ]
    if len(set(identities)) != len(identities):
        raise InvalidSemanticInput("事实、处境、行动和利益必须有唯一身份")
    if set(changed_facts) - {item.id for item in facts}:
        raise InvalidSemanticInput("changed_facts 包含未声明事实")
    basis = _EvaluationBasis(
        snapshot, tuple(facts), tuple(facet_specs), tuple(actions), schedule, tuple(objectives)
    )
    old_basis = previous._basis if previous is not None else None
    reusable = old_basis is not None and (
        old_basis.facts,
        old_basis.facets,
        old_basis.actions,
        old_basis.schedule,
        old_basis.objectives,
        old_basis.snapshot.actor,
        old_basis.snapshot.target,
        old_basis.snapshot.consumer_id,
        old_basis.snapshot.time,
    ) == (
        basis.facts,
        basis.facets,
        basis.actions,
        basis.schedule,
        basis.objectives,
        snapshot.actor,
        snapshot.target,
        snapshot.consumer_id,
        snapshot.time,
    )
    if not reusable or previous is None or old_basis is None:
        facets = derive_facets(snapshot, facts, facet_specs, schedule)
        assessments = assess_actions(actions, facets, snapshot, facts, schedule, objectives)
        return SemanticEvaluation(facets, assessments, basis)
    old_observations = {item.spec_id: item for item in old_basis.snapshot.observations}
    changed = set(changed_facts) | {
        name
        for name in set(observations) | set(old_observations)
        if observations.get(name) != old_observations.get(name)
    }
    index = dependency_index(facet_specs, actions, objectives)
    affected = {node for fact_id in changed for node in index.get(fact_id, ())}
    old_facets = {item.id: item for item in previous.facets}
    old_actions = {item.candidate_id: item for item in previous.actions}
    replacements = {
        item.id: item
        for item in derive_facets(
            snapshot, facts, tuple(item for item in facet_specs if item.id in affected), schedule
        )
    }
    facets = tuple(
        replacements[item.id] if item.id in replacements else old_facets[item.id]
        for item in facet_specs
    )
    new_assessments = {
        item.candidate_id: item
        for item in assess_actions(
            tuple(item for item in actions if item.id in affected),
            facets,
            snapshot,
            facts,
            schedule,
            objectives,
        )
    }
    assessments = tuple(
        new_assessments[item.id] if item.id in new_assessments else old_actions[item.id]
        for item in actions
    )
    return SemanticEvaluation(facets, assessments, basis)


def wire_objectives(
    objectives: Sequence[contracts.InterestSpec], consumer_id: str
) -> tuple[contracts.InterestSpec, ...]:
    """只保留明确接入该消费者的国家利益，未接线项保持可见而不伪造接入。"""

    return tuple(item for item in objectives if consumer_id in item.consumer_ids)


__all__ = [
    "ActionAssessment",
    "ActionSpec",
    "AssessmentTerm",
    "FacetSpec",
    "InvalidSemanticInput",
    "InvalidSemanticInputError",
    "SemanticEvaluation",
    "SituationFacet",
    "assess_actions",
    "dependency_index",
    "derive_facets",
    "recompute",
    "wire_objectives",
]

InvalidSemanticInput = InvalidSemanticInputError
