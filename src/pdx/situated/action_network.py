"""R2 行动网络的符号 IR：参考与生产降低消费同一份声明。

不观察引擎，不自动发现因果，不展开条件子集。有限条件复用 expressions；
数值是已经完成消费者专属映射的常量，动态数值公式须另加受审算子。
specialize_program 只在适配器证明 reader 每次求值均已知后消去三值测试，
输出可直接降低的普通表达式和贡献；它不授予 reader 或写点能力。

效应实例以完整候选（含必要资源／后果对象 bindings）和规范账目区分。
当前不支持同一未分区候选内另有多个后果对象；声明者必须把这些对象纳入
ActionInstance.bindings，不能通过复用账目将未绑定的多个资源静默聚合。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Literal, cast

from . import core_contracts as contracts
from . import expressions as expr

PathKind = Literal["direct", "derived", "interaction"]
TermKind = Literal["benefit", "cost", "risk"]
Operation = Literal["add", "multiply"]
TRUE = expr.BooleanLiteral(True)
FALSE = expr.BooleanLiteral(False)


def _number(value: float, path: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{path}: 需要有限数，不能使用 bool")


def _ids(values: tuple[str, ...], path: str) -> None:
    if (
        type(values) is not tuple
        or any(type(value) is not str for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(f"{path}: 需要唯一不可变身份")
    for value in values:
        contracts.stable_id(value, path)


def _proof(values: tuple[str, ...], path: str) -> None:
    if type(values) is not tuple or not values or any(type(v) is not str or not v for v in values):
        raise ValueError(f"{path}: 需要可追溯的语义审查来源")


def _all(*items: expr.Expression) -> expr.Expression:
    kept = tuple(item for item in items if item != TRUE)
    if FALSE in kept:
        return FALSE
    return TRUE if not kept else kept[0] if len(kept) == 1 else expr.All(kept)


def _any(*items: expr.Expression) -> expr.Expression:
    kept = tuple(item for item in items if item != FALSE)
    if TRUE in kept:
        return TRUE
    return FALSE if not kept else kept[0] if len(kept) == 1 else expr.Any(kept)


def _not(item: expr.Expression) -> expr.Expression:
    if item == TRUE:
        return FALSE
    return TRUE if item == FALSE else expr.Not(item)


def _expression_facts(expression: expr.Expression) -> frozenset[str]:
    """拒绝任意实现 evaluate 的对象，保证有限且可降低的算子集合。"""
    pending = [(expression, 1)]
    facts: set[str] = set()
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 16384 or depth > 128:
            raise ValueError("Expression: 表达式预算或深度超限")
        if type(item) is expr.Compare:
            _comparison(item)
            facts.add(item.fact_id)
        elif type(item) in (expr.All, expr.Any):
            junction = cast("expr.All | expr.Any", item)
            if type(junction.items) is not tuple:
                raise ValueError("Expression.items: 必须为不可变 tuple")
            pending.extend((child, depth + 1) for child in junction.items)
        elif type(item) is expr.Not:
            pending.append((item.item, depth + 1))
        elif type(item) is expr.BooleanLiteral:
            if item.value is not None and type(item.value) is not bool:
                raise ValueError("BooleanLiteral: 无效三值")
        else:
            raise ValueError("Expression: 仅支持登记的有限表达式，不能使用任意 Python")
    return frozenset(facts)


def _comparison(comparison: expr.Compare) -> None:
    contracts.stable_id(comparison.fact_id, "Compare.fact_id")
    if comparison.operator not in {"eq", "ne", "gt", "ge", "lt", "le"}:
        raise ValueError("Compare.operator: 不支持的算子")
    if type(comparison.expected) not in (bool, int, float):
        raise ValueError("Compare.expected: 仅支持布尔或有限数")
    if type(comparison.expected) is not bool:
        _number(cast("float", comparison.expected), "Compare.expected")
    elif comparison.operator not in {"eq", "ne"}:
        raise ValueError("Compare: 布尔仅支持等值比较")


def _expression_cost(
    expression: expr.Expression,
    expanded: dict[str, tuple[int, int]],
    aliases: dict[str, str],
    limit: int,
) -> tuple[int, int]:
    """在分配展开树前估算出现次数；重复 DAG 引用按实际降低大小累计。"""
    if type(expression) is expr.Compare:
        cost, depth = expanded.get(aliases.get(expression.fact_id, expression.fact_id), (1, 1))
        return min(limit + 1, cost + 1), depth + 1
    if type(expression) in (expr.All, expr.Any):
        junction = cast("expr.All | expr.Any", expression)
        children = [_expression_cost(item, expanded, aliases, limit) for item in junction.items]
        return min(limit + 1, 1 + sum(item[0] for item in children)), 1 + max(
            (item[1] for item in children), default=0
        )
    if type(expression) is expr.Not:
        cost, depth = _expression_cost(expression.item, expanded, aliases, limit)
        return min(limit + 1, cost + 1), depth + 1
    return 1, 1


@dataclass(frozen=True, slots=True)
class Constant:
    value: float

    def __post_init__(self) -> None:
        _number(self.value, "Constant.value")


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    id: str
    consumer_id: str
    operation: Operation
    unit: contracts.Unit
    target_kind: contracts.EntityKind | None = None
    neutral: float = 0.0
    lower: float = -10.0
    upper: float = 10.0

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "ActionDefinition.id")
        contracts.stable_id(self.consumer_id, "ActionDefinition.consumer_id")
        if self.operation not in {"add", "multiply"}:
            raise ValueError("ActionDefinition.operation: 未支持的组合代数")
        expected = ("consumer_score", 0.0) if self.operation == "add" else ("multiplier", 1.0)
        if (self.unit, self.neutral) != expected:
            raise ValueError("ActionDefinition: 映射单位、neutral 与组合代数不一致")
        for value in (self.neutral, self.lower, self.upper):
            _number(value, "ActionDefinition.bounds")
        if not self.lower <= self.neutral <= self.upper:
            raise ValueError("ActionDefinition.bounds: 边界必须包含 neutral")
        if self.operation == "multiply" and self.lower <= 0:
            raise ValueError("ActionDefinition: 乘法有效域仅支持正因子")


@dataclass(frozen=True, slots=True)
class ActionInstance:
    definition: ActionDefinition
    actor: contracts.EntityKey
    target: contracts.EntityKey | None
    time: contracts.TimeIdentity
    bindings: tuple[tuple[str, contracts.EntityKey], ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.definition) is not ActionDefinition
            or type(self.actor) is not contracts.EntityKey
            or type(self.time) is not contracts.TimeIdentity
            or (self.target is not None and type(self.target) is not contracts.EntityKey)
        ):
            raise ValueError("ActionInstance: 需要有类型的定义、实体和时间")
        if self.actor.kind != "country":
            raise ValueError("ActionInstance.actor: 必须为国家")
        actual_kind = self.target.kind if self.target is not None else None
        if actual_kind != self.definition.target_kind:
            raise ValueError("ActionInstance.target: 候选种类不匹配")
        if type(self.bindings) is not tuple:
            raise ValueError("ActionInstance.bindings: 必须为不可变 tuple")
        if any(type(item) is not tuple or len(item) != 2 for item in self.bindings):
            raise ValueError("ActionInstance.bindings: 需要名称与实体对")
        names = tuple(name for name, _ in self.bindings)
        _ids(names, "ActionInstance.bindings")
        if any(not isinstance(entity, contracts.EntityKey) for _, entity in self.bindings):
            raise ValueError("ActionInstance.bindings: 需要有类型实体")

    @property
    def key(self) -> tuple[object, ...]:
        return (
            self.definition.id,
            self.definition.consumer_id,
            self.actor,
            self.target,
            tuple(sorted(self.bindings)),
            self.time,
        )


@dataclass(frozen=True, slots=True)
class ObservationBatch:
    """随观测携带完整候选上下文，不把 actor 观测误当作无对手事实。

    调用者负责诚实记录采样上下文；该包装只校验输入绑定，不证明引擎
    曾经求值。禁止把另一个 batch 的事实脱离其 target/time 后自动重标。
    """

    action: ActionInstance
    observations: tuple[contracts.Observation, ...]

    def __post_init__(self) -> None:
        if type(self.action) is not ActionInstance or type(self.observations) is not tuple:
            raise ValueError("ObservationBatch: 需要完整行动及不可变观测 tuple")
        if any(type(item) is not contracts.Observation for item in self.observations):
            raise ValueError("ObservationBatch: 需要类型化真实观测")
        _ids(tuple(item.spec_id for item in self.observations), "ObservationBatch.observations")


@dataclass(frozen=True, slots=True)
class EvidenceLineage:
    roots: tuple[str, ...]
    derivations: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ids(self.roots, "EvidenceLineage.roots")
        _ids(self.derivations, "EvidenceLineage.derivations")
        if not self.roots:
            raise ValueError("EvidenceLineage.roots: 不能缺失证据")
        _proof(self.sources, "EvidenceLineage.sources")


@dataclass(frozen=True, slots=True)
class ObjectiveTemplate:
    """本次消费者求值的利益声明；基准值只能来自实际传入的同轮观测。

    EffectAccount.baseline 描述相对原版评分的比较基线；这里的
    baseline_fact_id 则指向本次现状读数，两者不能互相充当证明。
    当前仅支持 evaluation 生命周期，不预留持久目标或预测结果。
    """

    id: str
    action: ActionInstance
    source_fact_ids: tuple[str, ...]
    baseline_fact_id: str
    starts: contracts.TimeIdentity
    deadline: contracts.TimeIdentity
    review_sources: tuple[str, ...]
    horizon: Literal["current"] = "current"
    lifetime: Literal["evaluation"] = "evaluation"
    relations: tuple[contracts.ObjectiveRelation, ...] = ()

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "ObjectiveTemplate.id")
        _ids(self.source_fact_ids, "ObjectiveTemplate.source_fact_ids")
        _proof(self.review_sources, "ObjectiveTemplate.review_sources")
        if (
            type(self.action) is not ActionInstance
            or type(self.starts) is not contracts.TimeIdentity
            or type(self.deadline) is not contracts.TimeIdentity
            or self.horizon != "current"
            or self.lifetime != "evaluation"
            or self.starts != self.action.time
            or self.deadline != self.action.time
        ):
            raise ValueError("ObjectiveTemplate: 对象或本次求值期限不一致")
        if not self.source_fact_ids or self.baseline_fact_id not in self.source_fact_ids:
            raise ValueError("ObjectiveTemplate: 现状基准必须属于非空真实来源")
        if type(self.relations) is not tuple or any(
            type(item) is not contracts.ObjectiveRelation for item in self.relations
        ):
            raise ValueError("ObjectiveTemplate: 需要类型化利益关系")
        _ids(tuple(item.other_id for item in self.relations), "ObjectiveTemplate.relations")
        if any(item.other_id == self.id for item in self.relations):
            raise ValueError("ObjectiveTemplate: 利益不能引用自身关系")

    @property
    def key(self) -> tuple[object, ...]:
        return self.id, self.action.key

    def bind(
        self,
        batch: ObservationBatch,
        facts: tuple[contracts.FactSpec, ...],
    ) -> contracts.InterestSpec | None:
        """缺基准时返回未实例化；从不制造零值或构建期 known 观察。"""
        if type(batch) is not ObservationBatch or batch.action != self.action:
            raise ValueError("ObjectiveTemplate.bind: 观测批次的完整候选上下文不一致")
        observations = batch.observations
        specs = {item.id: item for item in facts}
        observed = {item.spec_id: item for item in observations}
        if len(observed) != len(observations):
            raise ValueError("ObjectiveTemplate.bind: 重复观测")
        for name in self.source_fact_ids:
            if name not in specs:
                raise ValueError("ObjectiveTemplate.bind: 未声明目标来源")
            _fact_context(specs[name], self.action)
            if name in observed:
                specs[name].validate_observation(
                    observed[name],
                    actor=self.action.actor,
                    target=self.action.target,
                    consumer_id=self.action.definition.consumer_id,
                    time=self.action.time,
                )
        baseline = observed.get(self.baseline_fact_id)
        if baseline is None:
            return None
        known = all(
            name in observed and observed[name].usable_at(self.action.time)
            for name in self.source_fact_ids
        )
        return contracts.InterestSpec(
            self.id,
            self.action.actor,
            self.action.target,
            self.source_fact_ids,
            self.starts,
            self.deadline,
            baseline,
            self.relations,
            (self.action.definition.consumer_id,),
            "known" if known else "unknown",
        )


@dataclass(frozen=True, slots=True)
class EffectAccount:
    id: str
    mechanism_id: str
    category: str
    consumer_id: str
    unit: contracts.Unit
    horizon: Literal["short", "current", "long"]
    baseline: str
    review_sources: tuple[str, ...]
    objective_id: str = "relative-preference"

    def __post_init__(self) -> None:
        for name in ("id", "mechanism_id", "category", "consumer_id", "baseline", "objective_id"):
            contracts.stable_id(getattr(self, name), f"EffectAccount.{name}")
        if self.horizon not in {"short", "current", "long"}:
            raise ValueError("EffectAccount.horizon: 无效期限")
        _proof(self.review_sources, "EffectAccount.review_sources")

    @property
    def dimensions(self) -> tuple[str, ...]:
        return self.consumer_id, self.unit, self.horizon, self.baseline, self.objective_id


@dataclass(frozen=True, slots=True)
class EffectAlias:
    alias_id: str
    canonical_id: str
    review_sources: tuple[str, ...]

    def __post_init__(self) -> None:
        _ids((self.alias_id, self.canonical_id), "EffectAlias")
        _proof(self.review_sources, "EffectAlias.review_sources")


@dataclass(frozen=True, slots=True)
class OverlapReview:
    left: str
    right: str
    relation: Literal["independent", "replacement", "residual"]
    review_sources: tuple[str, ...]

    def __post_init__(self) -> None:
        _ids((self.left, self.right), "OverlapReview")
        if self.relation not in {"independent", "replacement", "residual"}:
            raise ValueError("OverlapReview.relation: 未声明的重叠语义")
        _proof(self.review_sources, "OverlapReview.review_sources")


@dataclass(frozen=True, slots=True)
class EffectRegistry:
    accounts: tuple[EffectAccount, ...]
    aliases: tuple[EffectAlias, ...] = ()
    overlaps: tuple[OverlapReview, ...] = ()

    def __post_init__(self) -> None:
        for values, expected in (
            (self.accounts, EffectAccount),
            (self.aliases, EffectAlias),
            (self.overlaps, OverlapReview),
        ):
            if type(values) is not tuple or any(type(value) is not expected for value in values):
                raise ValueError("EffectRegistry: 需要不可变类型化登记")
        _ids(tuple(account.id for account in self.accounts), "EffectRegistry.accounts")
        _ids(tuple(alias.alias_id for alias in self.aliases), "EffectRegistry.aliases")
        ids = {account.id for account in self.accounts}
        if ids & {alias.alias_id for alias in self.aliases}:
            raise ValueError("EffectRegistry: 别名不得覆盖 canonical 身份")
        for alias in self.aliases:
            if alias.canonical_id not in ids:
                raise ValueError("EffectRegistry: 别名只可直接引用 canonical 账目")
        # 目标身份不能把同一边际后果变成第二份成本/收益。dimensions 中的
        # objective_id 仍用于残差与替代的一致性，但不授予规范机制新身份。
        fingerprints = [
            (a.mechanism_id, a.category, a.consumer_id, a.unit, a.horizon, a.baseline)
            for a in self.accounts
        ]
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("EffectRegistry: 同一规范机制换名重复注册，须使用 alias")
        pairs = []
        for review in self.overlaps:
            pair = tuple(sorted((self.canonical(review.left), self.canonical(review.right))))
            if pair[0] == pair[1]:
                raise ValueError("EffectRegistry: 同一效应不可声明为独立重叠")
            pairs.append(pair)
        if len(set(pairs)) != len(pairs):
            raise ValueError("EffectRegistry: 重叠声明重复或冲突")

    def canonical(self, effect_id: str) -> str:
        aliases = {alias.alias_id: alias.canonical_id for alias in self.aliases}
        canonical = aliases.get(effect_id, effect_id)
        if canonical not in {account.id for account in self.accounts}:
            raise ValueError(f"EffectRegistry: 未注册效应 {effect_id}")
        return canonical

    def account(self, effect_id: str) -> EffectAccount:
        canonical = self.canonical(effect_id)
        return next(account for account in self.accounts if account.id == canonical)


@dataclass(frozen=True, slots=True)
class AssessmentTerm:
    id: str
    effect_id: str
    kind: TermKind
    value: Constant
    group_id: str
    required: bool = True
    variant_group: str | None = None
    variant_rank: int = 0
    variant_review: tuple[str, ...] = ()
    baseline_relation: Literal[
        "new_consideration", "conditional_correction", "intentional_reweight"
    ] = "conditional_correction"

    def __post_init__(self) -> None:
        _ids((self.id,), "AssessmentTerm.id")
        contracts.stable_id(self.effect_id, "AssessmentTerm.effect_id")
        contracts.stable_id(self.group_id, "AssessmentTerm.group_id")
        if self.kind not in {"benefit", "cost", "risk"} or type(self.value) is not Constant:
            raise ValueError("AssessmentTerm: 需要已映射常量与明确语义角色")
        if type(self.required) is not bool or type(self.variant_rank) is not int:
            raise ValueError("AssessmentTerm: required/rank 类型不正确")
        if self.baseline_relation not in {
            "new_consideration",
            "conditional_correction",
            "intentional_reweight",
        }:
            raise ValueError("AssessmentTerm.baseline_relation: 必须说明与原版基线的关系")
        if self.variant_group is not None:
            contracts.stable_id(self.variant_group, "AssessmentTerm.variant_group")
            _proof(self.variant_review, "AssessmentTerm.variant_review")
        elif self.variant_rank or self.variant_review:
            raise ValueError("AssessmentTerm: 普通独立项不能携带变体优先级")


@dataclass(frozen=True, slots=True)
class AssessmentGroup:
    id: str
    term_ids: tuple[str, ...]
    required_term_ids: tuple[str, ...] = ()
    required_fact_ids: tuple[str, ...] = ()
    review_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "AssessmentGroup.id")
        _ids(self.term_ids, "AssessmentGroup.term_ids")
        _ids(self.required_term_ids, "AssessmentGroup.required_term_ids")
        _ids(self.required_fact_ids, "AssessmentGroup.required_fact_ids")
        if not self.term_ids or not set(self.required_term_ids) <= set(self.term_ids):
            raise ValueError("AssessmentGroup: 必需项必须属于非空组")
        _proof(self.review_sources, "AssessmentGroup.review_sources")


@dataclass(frozen=True, slots=True)
class ActionBridge:
    id: str
    action: ActionInstance
    path: PathKind
    effect_id: str
    term: AssessmentTerm
    source_ids: tuple[str, ...]
    condition: expr.Expression = TRUE
    condition_fact_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "ActionBridge.id")
        _ids(self.source_ids, "ActionBridge.source_ids")
        _ids(self.condition_fact_ids, "ActionBridge.condition_fact_ids")
        _ids(self.depends_on, "ActionBridge.depends_on")
        if self.path not in {"direct", "derived", "interaction"} or not self.source_ids:
            raise ValueError("ActionBridge: 需要合法路径与来源")
        if self.term.effect_id != self.effect_id:
            raise ValueError("ActionBridge: term 与 bridge 的效应身份不匹配")
        if _expression_facts(self.condition) != set(self.condition_fact_ids):
            raise ValueError("ActionBridge: condition_fact_ids 与真实表达式依赖不一致")


@dataclass(frozen=True, slots=True)
class DerivedPredicate:
    id: str
    expression: expr.Expression
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "DerivedPredicate.id")
        _ids(self.source_ids, "DerivedPredicate.source_ids")
        if _expression_facts(self.expression) != set(self.source_ids):
            raise ValueError("DerivedPredicate: 派生依赖与表达式不匹配")


@dataclass(frozen=True, slots=True)
class Replacement:
    id: str
    base_effect_ids: tuple[str, ...]
    full_effect_id: str
    condition: expr.Expression = TRUE
    condition_fact_ids: tuple[str, ...] = ()
    required_group_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "Replacement.id")
        _ids(self.base_effect_ids, "Replacement.base_effect_ids")
        _ids(self.condition_fact_ids, "Replacement.condition_fact_ids")
        _ids(self.required_group_ids, "Replacement.required_group_ids")
        if not self.base_effect_ids or _expression_facts(self.condition) != set(
            self.condition_fact_ids
        ):
            raise ValueError("Replacement: 基础项或条件依赖不完整")


@dataclass(frozen=True, slots=True)
class Residual:
    id: str
    base_effect_ids: tuple[str, ...]
    residual_effect_id: str
    complete_value: Constant
    review_sources: tuple[str, ...]

    def __post_init__(self) -> None:
        contracts.stable_id(self.id, "Residual.id")
        _ids(self.base_effect_ids, "Residual.base_effect_ids")
        _proof(self.review_sources, "Residual.review_sources")
        if not self.base_effect_ids or type(self.complete_value) is not Constant:
            raise ValueError("Residual: 需要基础项和已映射完整估值")


@dataclass(frozen=True, slots=True)
class NetworkBudget:
    max_bridges: int = 128
    max_edges: int = 256
    max_fanout: int = 16
    max_depth: int = 32
    max_guard_nodes: int = 4096
    max_overlap_checks: int = 256

    def __post_init__(self) -> None:
        if any(
            type(v) is not int or v < 1
            for v in (
                self.max_bridges,
                self.max_edges,
                self.max_fanout,
                self.max_depth,
                self.max_guard_nodes,
                self.max_overlap_checks,
            )
        ):
            raise ValueError("NetworkBudget: 必须为正整数")


@dataclass(frozen=True, slots=True)
class ActionNetwork:
    actions: tuple[ActionInstance, ...]
    bridges: tuple[ActionBridge, ...]
    groups: tuple[AssessmentGroup, ...]
    registry: EffectRegistry
    facts: tuple[contracts.FactSpec, ...] = ()
    predicates: tuple[DerivedPredicate, ...] = ()
    replacements: tuple[Replacement, ...] = ()
    residuals: tuple[Residual, ...] = ()
    fact_aliases: tuple[tuple[str, str], ...] = ()
    budget: NetworkBudget = field(default_factory=NetworkBudget)
    schema_version: Literal[2] = 2
    objectives: tuple[ObjectiveTemplate, ...] = ()

    def __post_init__(self) -> None:
        for values, expected in (
            (self.actions, ActionInstance),
            (self.bridges, ActionBridge),
            (self.groups, AssessmentGroup),
            (self.facts, contracts.FactSpec),
            (self.predicates, DerivedPredicate),
            (self.replacements, Replacement),
            (self.residuals, Residual),
            (self.objectives, ObjectiveTemplate),
        ):
            if type(values) is not tuple or any(type(value) is not expected for value in values):
                raise ValueError("ActionNetwork: 需要不可变类型化声明 tuple")
        if (
            type(self.registry) is not EffectRegistry
            or type(self.budget) is not NetworkBudget
            or type(self.schema_version) is not int
            or self.schema_version != 2
        ):
            raise ValueError("ActionNetwork: 需要 R2 登记和预算")
        if type(self.fact_aliases) is not tuple:
            raise ValueError("ActionNetwork.fact_aliases: 必须为不可变 tuple")
        for pair in self.fact_aliases:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("ActionNetwork.fact_aliases: 需要别名对")
            for name in pair:
                contracts.stable_id(name, "ActionNetwork.fact_aliases")


@dataclass(frozen=True, slots=True)
class TruthTest:
    """二值 guard：unknown 不等于 false，也不通过 not 变成 true。"""

    expression: expr.Expression
    state: Literal["true", "false", "known"]

    def evaluate(self, facts: dict[str, object | None]) -> bool:
        value = self.expression.evaluate(facts)
        return value is not None if self.state == "known" else value is (self.state == "true")


@dataclass(frozen=True, slots=True)
class FactKnown:
    fact_id: str

    def evaluate(self, facts: dict[str, object | None]) -> bool:
        return self.fact_id in facts and facts[self.fact_id] is not None


@dataclass(frozen=True, slots=True)
class EffectInstance:
    account_id: str
    action: ActionInstance

    @property
    def key(self) -> tuple[object, ...]:
        return self.account_id, self.action.key


@dataclass(frozen=True, slots=True)
class ProgramContribution:
    effect: EffectInstance
    value: Constant
    kind: TermKind
    guard: expr.Expression
    bridge_ids: tuple[str, ...]
    group_ids: tuple[str, ...]
    paths: tuple[PathKind, ...]
    lineage: EvidenceLineage

    @property
    def effect_id(self) -> str:
        return self.effect.account_id


@dataclass(frozen=True, slots=True)
class ReplacementActivation:
    id: str
    action: ActionInstance
    guard: expr.Expression


@dataclass(frozen=True, slots=True)
class NetworkProgram:
    network: ActionNetwork
    contributions: tuple[ProgramContribution, ...]
    group_guards: tuple[tuple[str, expr.Expression], ...]
    replacements: tuple[ReplacementActivation, ...]


@dataclass(frozen=True, slots=True)
class LoweredContribution:
    effect: EffectInstance
    value: float
    guard: expr.Expression
    bridge_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpecializedProgram:
    source: NetworkProgram
    contributions: tuple[LoweredContribution, ...]
    always_known_fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    action: ActionInstance
    total: float
    unbounded: float
    effects: tuple[tuple[str, float], ...]
    unknown_groups: tuple[str, ...]
    active_replacements: tuple[str, ...]
    objectives: tuple[contracts.InterestSpec, ...] = ()


def mapped_residual(base: float, complete: float, operation: Operation) -> float:
    _number(base, "mapped_residual.base")
    _number(complete, "mapped_residual.complete")
    if operation == "add":
        return complete - base
    if operation != "multiply" or base <= 0 or complete <= 0:
        raise ValueError("mapped_residual: 乘法只支持正的非零因子")
    return complete / base


def _normalizer(network: ActionNetwork) -> dict[str, str]:
    mapping = dict(network.fact_aliases)
    if len(mapping) != len(network.fact_aliases) or any(a == b for a, b in mapping.items()):
        raise ValueError("ActionNetwork.fact_aliases: 重复或自别名")
    fact_ids = {item.id for item in network.facts}
    if set(mapping) & fact_ids or not set(mapping.values()) <= fact_ids:
        raise ValueError("ActionNetwork.fact_aliases: 只能指向已声明 canonical reader")
    return mapping


def _expand(
    expression: expr.Expression,
    nodes: dict[str, DerivedPredicate],
    aliases: dict[str, str],
    memo: dict[str, expr.Expression] | None = None,
) -> expr.Expression:
    memo = {} if memo is None else memo
    if isinstance(expression, expr.Compare):
        fact_id = aliases.get(expression.fact_id, expression.fact_id)
        if fact_id in nodes:
            if type(expression.expected) is not bool or expression.operator not in {"eq", "ne"}:
                raise ValueError("DerivedPredicate: 仅支持布尔等值消费")
            if fact_id not in memo:
                memo[fact_id] = _expand(nodes[fact_id].expression, nodes, aliases, memo)
            result = memo[fact_id]
            positive = (expression.operator == "eq") == expression.expected
            return result if positive else _not(result)
        return expr.Compare(fact_id, expression.operator, expression.expected)
    if isinstance(expression, expr.All):
        return _all(*(_expand(item, nodes, aliases, memo) for item in expression.items))
    if isinstance(expression, expr.Any):
        return _any(*(_expand(item, nodes, aliases, memo) for item in expression.items))
    if isinstance(expression, expr.Not):
        return _not(_expand(expression.item, nodes, aliases, memo))
    return expression


def _guard_count(expression: expr.Expression, memo: dict[int, int] | None = None) -> int:
    memo = {} if memo is None else memo
    identity = id(expression)
    if identity in memo:
        return memo[identity]
    if isinstance(expression, (expr.All, expr.Any)):
        result = 1 + sum(_guard_count(item, memo) for item in expression.items)
    elif isinstance(expression, (expr.Not, TruthTest)):
        result = 1 + _guard_count(
            expression.item if isinstance(expression, expr.Not) else expression.expression, memo
        )
    else:
        result = 1
    memo[identity] = result
    return result


def _bridge_objective(network: ActionNetwork, bridge: ActionBridge) -> ObjectiveTemplate | None:
    account = network.registry.account(bridge.effect_id)
    objective = next(
        (
            item
            for item in network.objectives
            if item.key == (account.objective_id, bridge.action.key)
        ),
        None,
    )
    if objective is None:
        # 旧参考核心未声明国家利益时保留明确的相对偏好模式。具名目标及
        # 生产 profile 不得使用这一兼容路径伪装已有利益接线。
        if not network.objectives and account.objective_id == "relative-preference":
            return None
        raise ValueError("ActionBridge: 目标未登记或不属于精确行动对象")
    if account.horizon != objective.horizon:
        raise ValueError("ActionBridge: 目标与效应期限不一致")
    return objective


def _validate(network: ActionNetwork) -> tuple[dict[str, str], dict[str, DerivedPredicate]]:
    if network.schema_version != 2 or not network.actions:
        raise ValueError("ActionNetwork: 需要 R2 模式和非空行动集合")
    for values, path in (
        (network.bridges, "bridges"),
        (network.groups, "groups"),
        (network.facts, "facts"),
        (network.predicates, "predicates"),
        (network.replacements, "replacements"),
        (network.residuals, "residuals"),
    ):
        _ids(tuple(value.id for value in values), f"ActionNetwork.{path}")
    if len(network.bridges) > network.budget.max_bridges:
        raise ValueError("ActionNetwork: bridge 数量超出预算")
    keys = [action.key for action in network.actions]
    if len(set(keys)) != len(keys):
        raise ValueError("ActionNetwork: 行动实例重复")
    definitions: dict[tuple[str, str], ActionDefinition] = {}
    for action in network.actions:
        identity = action.definition.id, action.definition.consumer_id
        if identity in definitions and definitions[identity] != action.definition:
            raise ValueError("ActionNetwork: 同一行动定义身份的内容不一致")
        definitions[identity] = action.definition
    aliases = _normalizer(network)
    nodes = {node.id: node for node in network.predicates}
    fact_ids = {fact.id for fact in network.facts}
    objective_keys = [item.key for item in network.objectives]
    if len(set(objective_keys)) != len(objective_keys):
        raise ValueError("ActionNetwork: 同一候选目标重复")
    for objective in network.objectives:
        registered = next(
            (item for item in network.actions if item.key == objective.action.key), None
        )
        if registered is None or registered != objective.action:
            raise ValueError("ObjectiveTemplate: 未登记精确行动对象")
        if not set(objective.source_fact_ids) <= fact_ids:
            raise ValueError("ObjectiveTemplate: 来源必须为已声明 canonical 原始事实")
        for fact in network.facts:
            if fact.id in objective.source_fact_ids:
                _fact_context(fact, objective.action)
        if any(
            (relation.other_id, objective.action.key) not in objective_keys
            for relation in objective.relations
        ):
            raise ValueError("ObjectiveTemplate: 关系引用未登记的同候选目标")
    if fact_ids & nodes.keys() or set(aliases) & nodes.keys():
        raise ValueError("ActionNetwork: 派生节点与事实身份冲突")
    graph = {node.id: {aliases.get(s, s) for s in node.source_ids} for node in network.predicates}
    used_objectives = set()
    for bridge in network.bridges:
        if bridge.action.key not in keys:
            raise ValueError(f"ActionBridge.{bridge.id}: 未登记行动实例")
        registered = next(action for action in network.actions if action.key == bridge.action.key)
        if bridge.action.definition != registered.definition:
            raise ValueError("ActionBridge: 登记行动定义不一致")
        graph[bridge.id] = {
            aliases.get(s, s)
            for s in (*bridge.source_ids, *bridge.depends_on, *bridge.condition_fact_ids)
        }
        bound_objective = _bridge_objective(network, bridge)
        if bound_objective is not None:
            graph[bridge.id].update(bound_objective.source_fact_ids)
            used_objectives.add(bound_objective.key)
    if used_objectives != set(objective_keys):
        raise ValueError("ObjectiveTemplate: 孤立目标没有真实 bridge 消费")
    for replacement in network.replacements:
        graph[f"replacement:{replacement.id}"] = {
            aliases.get(s, s) for s in replacement.condition_fact_ids
        }
    bridge_ids = {bridge.id for bridge in network.bridges}
    if bridge_ids & (fact_ids | nodes.keys() | aliases.keys()):
        raise ValueError("ActionNetwork: 行动与事实／派生节点身份冲突")
    if any(
        dependency in bridge_ids for dependencies in graph.values() for dependency in dependencies
    ):
        raise ValueError("ActionNetwork: 候选分数不可作为已发生事实依赖")
    if sum(len(dependencies) for dependencies in graph.values()) > network.budget.max_edges:
        raise ValueError("ActionNetwork: 边数量超出预算")
    fanout: dict[str, int] = defaultdict(int)
    for dependencies in graph.values():
        for dependency in dependencies:
            if dependency not in fact_ids | nodes.keys():
                raise ValueError(f"ActionNetwork: 未声明事实或派生节点 {dependency}")
            fanout[dependency] += 1
    if any(value > network.budget.max_fanout for value in fanout.values()):
        raise ValueError("ActionNetwork: 扇出超出预算")
    visited: dict[str, int] = {}
    visiting: list[str] = []

    def depth(node: str) -> int:
        if node in visiting:
            raise ValueError(f"ActionNetwork: 同轮循环 {' -> '.join((*visiting, node))}")
        if node in visited:
            return visited[node]
        if len(visiting) >= network.budget.max_depth:
            raise ValueError("ActionNetwork: 依赖深度超出预算")
        visiting.append(node)
        result = 1 + max((depth(item) for item in graph.get(node, ())), default=0)
        visiting.pop()
        visited[node] = result
        return result

    for node in sorted(graph):
        if depth(node) > network.budget.max_depth:
            raise ValueError("ActionNetwork: 依赖深度超出预算")
    specs = {fact.id: fact for fact in network.facts}
    costs: dict[str, tuple[int, int]] = {}
    expression_items = [
        (name, nodes[name].expression) for name in sorted(nodes, key=lambda name: visited[name])
    ]
    expression_items.extend((bridge.id, bridge.condition) for bridge in network.bridges)
    expression_items.extend(
        (f"replacement:{item.id}", item.condition) for item in network.replacements
    )
    for name, expression in expression_items:
        _expression_facts(expression)
        pending = [expression]
        while pending:
            item = pending.pop()
            if isinstance(item, expr.Compare):
                canonical = aliases.get(item.fact_id, item.fact_id)
                boolean = canonical in nodes or specs[canonical].kind == "boolean"
                if canonical not in nodes and specs[canonical].kind == "enum":
                    raise ValueError("Expression: enum reader 尚无生产降低支持")
                if boolean != (type(item.expected) is bool):
                    raise ValueError("Expression: 比较常量与事实类型不一致")
            elif isinstance(item, (expr.All, expr.Any)):
                pending.extend(item.items)
            elif isinstance(item, expr.Not):
                pending.append(item.item)
        cost = _expression_cost(expression, costs, aliases, network.budget.max_guard_nodes)
        if cost[0] > network.budget.max_guard_nodes or cost[1] > network.budget.max_depth * 2:
            raise ValueError("ActionNetwork: guard 预展开预算或表达式深度超限")
        if name in nodes:
            costs[name] = cost
    return aliases, nodes


def _compatible(account: EffectAccount, action: ActionInstance) -> None:
    if (
        account.consumer_id != action.definition.consumer_id
        or account.unit != action.definition.unit
    ):
        raise ValueError("EffectAccount: 效应单位或消费者与行动不一致")


def _fact_context(spec: contracts.FactSpec, action: ActionInstance) -> None:
    if action.definition.consumer_id not in spec.consumer_ids:
        raise ValueError("ActionNetwork: 事实不允许此消费者读取")
    entity = action.actor if spec.binding == "actor" else action.target
    if entity is None or entity.kind != spec.entity_kind:
        raise ValueError("ActionNetwork: 事实绑定对象种类与候选不一致")


def compile_action_network(network: ActionNetwork) -> NetworkProgram:
    """编译为符号 guard/效应/完整性/替代；不枚举布尔条件子集。"""
    aliases, nodes = _validate(network)
    bridges = sorted(network.bridges, key=lambda item: item.id)
    terms = {bridge.term.id: bridge for bridge in bridges}
    if len(terms) != len(bridges):
        raise ValueError("ActionNetwork: term 身份重复")
    conditions = {bridge.id: _expand(bridge.condition, nodes, aliases) for bridge in bridges}
    basis: dict[str, expr.Expression] = {}
    readiness: dict[str, expr.Expression] = {}
    for bridge in bridges:
        consumed = {aliases.get(name, name) for name in bridge.condition_fact_ids} | set(
            _expression_facts(conditions[bridge.id])
        )
        checks: list[expr.Expression] = []
        for name in sorted(set(bridge.source_ids) | set(bridge.depends_on)):
            canonical = aliases.get(name, name)
            if canonical not in consumed:
                checks.append(
                    TruthTest(_expand(nodes[canonical].expression, nodes, aliases), "known")
                    if canonical in nodes
                    else FactKnown(canonical)
                )
        basis[bridge.id] = _all(*checks)
        readiness[bridge.id] = _any(
            TruthTest(conditions[bridge.id], "false"),
            _all(TruthTest(conditions[bridge.id], "true"), basis[bridge.id]),
        )
    group_guards: dict[str, expr.Expression] = {}
    membership: dict[str, str] = {}
    for group in sorted(network.groups, key=lambda item: item.id):
        if not set(group.term_ids) <= terms.keys():
            raise ValueError(f"AssessmentGroup.{group.id}: 未声明 term")
        members = [terms[name] for name in group.term_ids]
        if len({bridge.action.key for bridge in members}) != 1:
            raise ValueError("AssessmentGroup: 不同候选不能共享完整性组")
        if any(bridge.term.group_id != group.id for bridge in members):
            raise ValueError("AssessmentGroup: term 的组归属不一致")
        for name in group.term_ids:
            if name in membership:
                raise ValueError("AssessmentGroup: term 不能隶属两个组")
            membership[name] = group.id
        required = set(group.required_term_ids) | {
            bridge.term.id for bridge in members if bridge.term.required
        }
        required_facts = tuple(aliases.get(name, name) for name in group.required_fact_ids)
        if not set(required_facts) <= {fact.id for fact in network.facts}:
            raise ValueError("AssessmentGroup: 必需事实必须引用 canonical 原始观测")
        for fact in network.facts:
            if fact.id in required_facts:
                _fact_context(fact, members[0].action)
        objective_facts: set[str] = set()
        group_basis = set(required_facts)
        for member in members:
            group_basis.update(_expression_facts(_expand(member.condition, nodes, aliases)))
            for name in (*member.source_ids, *member.depends_on):
                canonical = aliases.get(name, name)
                group_basis.update(
                    _expression_facts(_expand(nodes[canonical].expression, nodes, aliases))
                    if canonical in nodes
                    else (canonical,)
                )
            objective = _bridge_objective(network, member)
            if objective is not None:
                objective_facts.update(objective.source_fact_ids)
        if not objective_facts <= group_basis:
            raise ValueError("AssessmentGroup: 无关目标来源不能授予贡献")
        group_guards[group.id] = _all(
            *(readiness[terms[name].id] for name in sorted(required)),
            *(FactKnown(name) for name in sorted(set(required_facts) | objective_facts)),
        )
    if set(membership) != terms.keys():
        raise ValueError("ActionNetwork: 每个 term 都必须属于完整性组")
    guarded = {
        bridge.id: _all(
            group_guards[bridge.term.group_id],
            TruthTest(conditions[bridge.id], "true"),
            basis[bridge.id],
        )
        for bridge in bridges
    }
    buckets: dict[tuple[object, ...], list[ActionBridge]] = defaultdict(list)
    lineages: dict[str, tuple[str, ...]] = {}
    derivations: dict[str, set[str]] = {}
    for bridge in bridges:
        account = network.registry.account(bridge.effect_id)
        _compatible(account, bridge.action)
        roots: set[str] = set()
        for name in (*bridge.source_ids, *bridge.depends_on):
            canonical = aliases.get(name, name)
            if canonical in nodes:
                roots.update(
                    _expression_facts(_expand(nodes[canonical].expression, nodes, aliases))
                )
            else:
                roots.add(canonical)
        roots.update(_expression_facts(conditions[bridge.id]))
        objective = _bridge_objective(network, bridge)
        if objective is not None:
            roots.update(objective.source_fact_ids)
        lineages[bridge.id] = tuple(sorted(roots))
        derived: set[str] = set()
        pending = [
            aliases.get(name, name)
            for name in (*bridge.source_ids, *bridge.depends_on, *bridge.condition_fact_ids)
        ]
        while pending:
            name = pending.pop()
            if name in nodes and name not in derived:
                derived.add(name)
                pending.extend(aliases.get(source, source) for source in nodes[name].source_ids)
        derivations[bridge.id] = derived
        for fact in network.facts:
            if fact.id in roots:
                _fact_context(fact, bridge.action)
        if bridge.action.definition.operation == "multiply" and bridge.term.value.value <= 0:
            raise ValueError("ActionBridge: 乘法只支持正因子")
        buckets[(bridge.action.key, account.id)].append(bridge)
    contributions: list[ProgramContribution] = []
    for (_, effect_id), items in buckets.items():
        canonical_id = cast("str", effect_id)
        unique: list[ActionBridge] = []
        alias_guards: dict[str, list[expr.Expression]] = {}
        for bridge in items:
            signature = (
                bridge.term.value,
                bridge.term.kind,
                conditions[bridge.id],
                lineages[bridge.id],
                bridge.term.variant_group,
                bridge.term.variant_rank,
                bridge.term.baseline_relation,
            )
            duplicate = next(
                (
                    other
                    for other in unique
                    if (
                        other.term.value,
                        other.term.kind,
                        conditions[other.id],
                        lineages[other.id],
                        other.term.variant_group,
                        other.term.variant_rank,
                        other.term.baseline_relation,
                    )
                    == signature
                ),
                None,
            )
            if duplicate is None:
                unique.append(bridge)
                alias_guards[bridge.id] = [guarded[bridge.id]]
            else:
                alias_guards[duplicate.id].append(guarded[bridge.id])
        if len(unique) > 1:
            variant_ids = {bridge.term.variant_group for bridge in unique}
            ranks = [bridge.term.variant_rank for bridge in unique]
            directions = {
                math.copysign(1, bridge.term.value.value - bridge.action.definition.neutral)
                for bridge in unique
            }
            if (
                None in variant_ids
                or len(variant_ids) != 1
                or len(set(ranks)) != len(ranks)
                or len(directions) != 1
                or len({b.term.kind for b in unique}) != 1
            ):
                raise ValueError(
                    "EffectInstance: 重复效应必须是等价别名或有证明的同向强弱变体；不能抵消矛盾"
                )
            ordered = sorted(unique, key=lambda b: b.term.variant_rank)
            magnitudes = [abs(b.term.value.value - b.action.definition.neutral) for b in ordered]
            if magnitudes != sorted(magnitudes):
                raise ValueError("EffectInstance: 强度序与已映射值不一致")
        for bridge in unique:
            own_guard = _any(*alias_guards[bridge.id])
            stronger = [
                _any(*alias_guards[other.id])
                for other in unique
                if other.term.variant_rank > bridge.term.variant_rank
            ]
            guard = _all(own_guard, *(_not(other) for other in stronger))
            same = [
                other
                for other in items
                if other.term.value == bridge.term.value
                and other.term.kind == bridge.term.kind
                and conditions[other.id] == conditions[bridge.id]
                and lineages[other.id] == lineages[bridge.id]
                and other.term.variant_group == bridge.term.variant_group
                and other.term.variant_rank == bridge.term.variant_rank
                and other.term.baseline_relation == bridge.term.baseline_relation
            ]
            contributions.append(
                ProgramContribution(
                    EffectInstance(canonical_id, bridge.action),
                    bridge.term.value,
                    bridge.term.kind,
                    guard,
                    tuple(sorted(other.id for other in same)),
                    tuple(sorted({other.term.group_id for other in same})),
                    tuple(sorted({other.path for other in same})),
                    EvidenceLineage(
                        lineages[bridge.id],
                        tuple(sorted({name for other in same for name in derivations[other.id]})),
                        tuple(
                            sorted(
                                set(network.registry.account(canonical_id).review_sources)
                                | {
                                    f"{source.source}:{source.line}"
                                    for fact in network.facts
                                    if fact.id in lineages[bridge.id]
                                    for source in fact.sources
                                }
                            )
                        ),
                    ),
                )
            )
    contributions, activations = _coordinate(network, contributions, group_guards, nodes, aliases)
    _validate_overlaps(network, contributions)
    guards = (
        [item.guard for item in contributions]
        + list(group_guards.values())
        + [item.guard for item in activations]
    )
    if sum(_guard_count(guard) for guard in guards) > network.budget.max_guard_nodes:
        raise ValueError("ActionNetwork: 符号 guard 展开超出预算")
    return NetworkProgram(
        network, tuple(contributions), tuple(sorted(group_guards.items())), tuple(activations)
    )


def _coordinate(
    network: ActionNetwork,
    contributions: list[ProgramContribution],
    group_guards: dict[str, expr.Expression],
    nodes: dict[str, DerivedPredicate],
    aliases: dict[str, str],
) -> tuple[list[ProgramContribution], list[ReplacementActivation]]:
    activations: list[ReplacementActivation] = []
    occupied: set[tuple[object, ...]] = set()
    group_actions = {bridge.term.group_id: bridge.action.key for bridge in network.bridges}
    for replacement in sorted(network.replacements, key=lambda item: item.id):
        bases = {network.registry.canonical(name) for name in replacement.base_effect_ids}
        complete = network.registry.canonical(replacement.full_effect_id)
        if complete in bases or not set(replacement.required_group_ids) <= group_guards.keys():
            raise ValueError("Replacement: 自替代或未知完整性组")
        dimensions = {network.registry.account(name).dimensions for name in (*bases, complete)}
        if len(dimensions) != 1:
            raise ValueError("Replacement: 单位、期限、目标或基准不同，不能替代")
        matched = False
        for action in network.actions:
            base_items = [
                item
                for item in contributions
                if item.effect.action.key == action.key and item.effect_id in bases
            ]
            full_items = [
                item
                for item in contributions
                if item.effect.action.key == action.key and item.effect_id == complete
            ]
            if not base_items and not full_items:
                continue
            if {item.effect_id for item in base_items} != bases or not full_items:
                raise ValueError("Replacement: 每个候选必须同时有基础和完整估值")
            if any(group_actions[name] != action.key for name in replacement.required_group_ids):
                raise ValueError("Replacement: 不得使用其它候选的完整性组")
            replacement_condition = _expand(replacement.condition, nodes, aliases)
            for spec in network.facts:
                if spec.id in _expression_facts(replacement_condition):
                    _fact_context(spec, action)
            matched = True
            keys = {(action.key, name) for name in (*bases, complete)}
            if occupied & keys:
                raise ValueError("Replacement: 重叠或嵌套替代未证明唯一，拒绝")
            occupied.update(keys)
            guard = _all(
                TruthTest(replacement_condition, "true"),
                _any(*(item.guard for item in full_items)),
                *(group_guards[name] for name in replacement.required_group_ids),
            )
            activations.append(ReplacementActivation(replacement.id, action, guard))
            contributions = [
                replace(item, guard=_all(item.guard, _not(guard)))
                if item.effect.action.key == action.key and item.effect_id in bases
                else replace(item, guard=_all(item.guard, guard))
                if item.effect.action.key == action.key and item.effect_id == complete
                else item
                for item in contributions
            ]
        if not matched:
            raise ValueError("Replacement: 未绑定实际行动")
    for residual in sorted(network.residuals, key=lambda item: item.id):
        bases = {network.registry.canonical(name) for name in residual.base_effect_ids}
        extra = network.registry.canonical(residual.residual_effect_id)
        if (
            extra in bases
            or len({network.registry.account(name).dimensions for name in (*bases, extra)}) != 1
        ):
            raise ValueError("Residual: 对象目标／单位期限／基准不一致或自引用")
        matched = False
        for action in network.actions:
            extra_items = [
                item
                for item in contributions
                if item.effect.action.key == action.key and item.effect_id == extra
            ]
            if not extra_items:
                continue
            matched = True
            base_items = [
                item
                for item in contributions
                if item.effect.action.key == action.key and item.effect_id in bases
            ]
            keys = {(action.key, name) for name in (*bases, extra)}
            if (
                {item.effect_id for item in base_items} != bases
                or len(base_items) != len(bases)
                or len(extra_items) != 1
                or keys & occupied
            ):
                raise ValueError("Residual: 只支持无变体、未替代的明确基础分解")
            occupied.update(keys)
            definition = action.definition
            base_value = (
                sum(item.value.value for item in base_items)
                if definition.operation == "add"
                else math.prod(item.value.value for item in base_items)
            )
            expected = mapped_residual(
                base_value, residual.complete_value.value, definition.operation
            )
            if not math.isclose(extra_items[0].value.value, expected, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Residual: 未在已映射消费者代数中重建完整值")
            extra_item = extra_items[0]
            contributions = [
                replace(item, guard=_all(item.guard, *(base.guard for base in base_items)))
                if item is extra_item
                else item
                for item in contributions
            ]
        if not matched:
            raise ValueError("Residual: 未绑定实际行动")
    return contributions, activations


def _validate_overlaps(network: ActionNetwork, contributions: list[ProgramContribution]) -> None:
    reviews = {
        tuple(
            sorted(
                (network.registry.canonical(review.left), network.registry.canonical(review.right))
            )
        ): review.relation
        for review in network.registry.overlaps
    }
    by_root: dict[tuple[object, ...], set[str]] = defaultdict(set)
    checks = 0
    for item in contributions:
        for root in item.lineage.roots:
            key = item.effect.action.key, root
            for other in sorted(by_root[key] - {item.effect_id}):
                checks += 1
                if checks > network.budget.max_overlap_checks:
                    raise ValueError("ActionNetwork: 证据重叠审查超出预算")
                pair = tuple(sorted((other, item.effect_id)))
                relation = reviews.get(pair)
                if relation is None:
                    raise ValueError(f"ActionNetwork: 重叠证据未审查 {pair}")
                if relation == "replacement" and not any(
                    {network.registry.canonical(r.full_effect_id), network.registry.canonical(base)}
                    == set(pair)
                    for r in network.replacements
                    for base in r.base_effect_ids
                ):
                    raise ValueError("ActionNetwork: replacement 重叠缺少实际替代")
                if relation == "residual" and not any(
                    {
                        network.registry.canonical(r.residual_effect_id),
                        network.registry.canonical(base),
                    }
                    == set(pair)
                    for r in network.residuals
                    for base in r.base_effect_ids
                ):
                    raise ValueError("ActionNetwork: residual 重叠缺少实际分解")
            by_root[key].add(item.effect_id)


def _truth_pair(
    expression: expr.Expression, known: frozenset[str]
) -> tuple[expr.Expression, expr.Expression]:
    """把三值表达式变成分别表示已知真／已知假的两个普通 PDX 谓词。"""
    if isinstance(expression, expr.Compare):
        return (expression, _not(expression)) if expression.fact_id in known else (FALSE, FALSE)
    if isinstance(expression, expr.BooleanLiteral):
        return (
            (TRUE, FALSE)
            if expression.value is True
            else (FALSE, TRUE)
            if expression.value is False
            else (FALSE, FALSE)
        )
    if isinstance(expression, expr.Not):
        positive, negative = _truth_pair(expression.item, known)
        return negative, positive
    if isinstance(expression, (expr.All, expr.Any)):
        pairs = [_truth_pair(item, known) for item in expression.items]
        if isinstance(expression, expr.All):
            return _all(*(pair[0] for pair in pairs)), _any(*(pair[1] for pair in pairs))
        return _any(*(pair[0] for pair in pairs)), _all(*(pair[1] for pair in pairs))
    raise ValueError("specialize_program: 未支持的表达式")


def _specialize(guard: expr.Expression, known: frozenset[str]) -> expr.Expression:
    if isinstance(guard, TruthTest):
        positive, negative = _truth_pair(guard.expression, known)
        return (
            positive
            if guard.state == "true"
            else negative
            if guard.state == "false"
            else _any(positive, negative)
        )
    if isinstance(guard, FactKnown):
        return TRUE if guard.fact_id in known else FALSE
    if isinstance(guard, expr.All):
        return _all(*(_specialize(item, known) for item in guard.items))
    if isinstance(guard, expr.Any):
        return _any(*(_specialize(item, known) for item in guard.items))
    if isinstance(guard, expr.Not):
        return _not(_specialize(guard.item, known))
    return guard


def specialize_program(
    program: NetworkProgram, always_known_fact_ids: tuple[str, ...]
) -> SpecializedProgram:
    """适配器证明这些 reader 在当前消费者内总有值；其余读数保留未知。

    这不是观察快照。若 reader 可能在运行时未知但无合法 known 谓词，适配器
    必须不列入本集合并局部撤回；不能把样例快照里的已知性编译成永久事实。
    """
    _ids(always_known_fact_ids, "specialize_program.always_known_fact_ids")
    if not set(always_known_fact_ids) <= {fact.id for fact in program.network.facts}:
        raise ValueError("specialize_program: 不能授予未声明 reader 可用性")
    known = frozenset(always_known_fact_ids)
    contributions = tuple(
        LoweredContribution(
            item.effect, item.value.value, _specialize(item.guard, known), item.bridge_ids
        )
        for item in program.contributions
    )
    if (
        sum(_guard_count(item.guard) for item in contributions)
        > program.network.budget.max_guard_nodes
    ):
        raise ValueError("specialize_program: 降低 guard 超出预算")
    return SpecializedProgram(program, contributions, tuple(sorted(known)))


def _checked_facts(
    program: NetworkProgram, action: ActionInstance, facts: dict[str, object | None]
) -> dict[str, object | None]:
    aliases = _normalizer(program.network)
    canonical: dict[str, object | None] = {}
    declarations = {fact.id: fact for fact in program.network.facts}
    for name, value in facts.items():
        key = aliases.get(name, name)
        if key not in declarations:
            raise ValueError(f"evaluate_network: 未声明事实 {name}")
        if key in canonical and canonical[key] != value:
            raise ValueError("evaluate_network: 同义 reader 的观测互相矛盾")
        spec = declarations[key]
        if action.definition.consumer_id not in spec.consumer_ids:
            raise ValueError("evaluate_network: 事实消费者不匹配")
        if value is not None:
            if spec.unit == "boolean":
                valid = type(value) is bool
            else:
                valid = type(value) in (int, float) and math.isfinite(cast("float", value))
            if not valid:
                raise ValueError("evaluate_network: 观测单位／类型错误或非有限数")
            if type(value) in (int, float) and (
                (spec.minimum is not None and cast("float", value) < spec.minimum)
                or (spec.maximum is not None and cast("float", value) > spec.maximum)
            ):
                raise ValueError("evaluate_network: 观测超出已声明范围")
        canonical[key] = value
    return canonical


def evaluate_network(
    program: NetworkProgram,
    facts: dict[str, object | None],
    *,
    action: ActionInstance | None = None,
) -> EvaluationResult:
    """显式参考入口；不宣称输入字典已经通过实际引擎观测。"""
    if action is None:
        if len(program.network.actions) != 1:
            raise ValueError("evaluate_network: 多候选必须指定精确行动，不能共享扣账")
        action = program.network.actions[0]
    registered = next((item for item in program.network.actions if item.key == action.key), None)
    if registered is None:
        raise ValueError("evaluate_network: 未登记行动")
    if registered.definition != action.definition:
        raise ValueError("evaluate_network: 登记行动定义不一致")
    action = registered
    values = _checked_facts(program, action, facts)
    effects = tuple(
        sorted(
            (item.effect_id, item.value.value)
            for item in program.contributions
            if item.effect.action.key == action.key and item.guard.evaluate(values) is True
        )
    )
    definition = action.definition
    total = (
        sum(value for _, value in effects)
        if definition.operation == "add"
        else math.prod(value for _, value in effects)
    )
    if not math.isfinite(total):
        raise ValueError("evaluate_network: 组合产生非有限数")
    group_ids = {
        bridge.term.group_id
        for bridge in program.network.bridges
        if bridge.action.key == action.key
    }
    unknown = tuple(
        name
        for name, guard in program.group_guards
        if name in group_ids and guard.evaluate(values) is not True
    )
    replacements = tuple(
        item.id
        for item in program.replacements
        if item.action.key == action.key and item.guard.evaluate(values) is True
    )
    return EvaluationResult(
        action,
        max(definition.lower, min(definition.upper, total)),
        total,
        effects,
        unknown,
        replacements,
    )


def evaluate_observations(
    program: NetworkProgram,
    observations: ObservationBatch | tuple[contracts.Observation, ...],
    *,
    action: ActionInstance | None = None,
) -> EvaluationResult:
    """R2 利益评估必须携带完整候选批次；裸 tuple 仅为旧参考兼容。

    FactSpec 的 actor binding 不能单独表达 actor→target 的关系来源，故先
    核对 batch 的完整 ActionInstance，再验证每个真实 Observation 和目标。
    """
    batch: ObservationBatch | None = None
    if type(observations) is ObservationBatch:
        batch = observations
        if action is None:
            action = batch.action
        if action != batch.action:
            raise ValueError("evaluate_observations: 观测批次的完整候选上下文不一致")
        observed = batch.observations
    else:
        if program.network.objectives:
            raise ValueError("evaluate_observations: R2 目标需要 ObservationBatch 完整候选上下文")
        if type(observations) is not tuple or any(
            type(item) is not contracts.Observation for item in observations
        ):
            raise ValueError("evaluate_observations: 旧参考入口需要类型化观测 tuple")
        observed = observations
    if action is None:
        if len(program.network.actions) != 1:
            raise ValueError("evaluate_observations: 多候选必须指定行动")
        action = program.network.actions[0]
    if action not in program.network.actions:
        raise ValueError("evaluate_observations: 观测批次不属于已登记的精确候选上下文")
    specs = {spec.id: spec for spec in program.network.facts}
    if len({item.spec_id for item in observed}) != len(observed):
        raise ValueError("evaluate_observations: 重复观测")
    values: dict[str, object | None] = {}
    for observation in observed:
        if observation.spec_id not in specs:
            raise ValueError("evaluate_observations: 未声明观测")
        spec = specs[observation.spec_id]
        spec.validate_observation(
            observation,
            actor=action.actor,
            target=action.target,
            consumer_id=action.definition.consumer_id,
            time=action.time,
        )
        values[observation.spec_id] = (
            observation.value if observation.usable_at(action.time) else None
        )
    result = evaluate_network(program, values, action=action)
    objectives = tuple(
        bound
        for template in program.network.objectives
        if template.action == result.action
        if batch is not None
        if (bound := template.bind(batch, program.network.facts)) is not None
    )
    return replace(result, objectives=objectives)


__all__ = [
    "ActionBridge",
    "ActionDefinition",
    "ActionInstance",
    "ActionNetwork",
    "AssessmentGroup",
    "AssessmentTerm",
    "Constant",
    "DerivedPredicate",
    "EffectAccount",
    "EffectAlias",
    "EffectInstance",
    "EffectRegistry",
    "EvaluationResult",
    "EvidenceLineage",
    "FactKnown",
    "LoweredContribution",
    "NetworkBudget",
    "NetworkProgram",
    "ObjectiveTemplate",
    "ObservationBatch",
    "OverlapReview",
    "ProgramContribution",
    "Replacement",
    "ReplacementActivation",
    "Residual",
    "SpecializedProgram",
    "TruthTest",
    "compile_action_network",
    "evaluate_network",
    "evaluate_observations",
    "mapped_residual",
    "specialize_program",
]
