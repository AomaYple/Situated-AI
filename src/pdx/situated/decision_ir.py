"""统一的行动决策 IR。

``ConsumerDecisionIR`` 是生成器与 Python 参考器共同消费的生产输入。
它不是统计登记表：行动的资格、退出、关系、成本、限幅和原版消费者
都在这里保留一份不可变、可追踪的表示。源 ``ActionCard`` 只负责读取
和校验，后续 lowering 与参考求值不得重新从 TOML 或另一套派生逻辑取值。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pdx.decision_rules import RuleSet

    from .action_instances import ActionInstance
    from .bindings import Binding
    from .ir import ActionIR
    from .schema import ActionCard, ConsumerContract, CostPredicate, RankTerm, Relation
    from .support_program import SupportProgram


@dataclass(frozen=True, slots=True)
class ContextBinding:
    """One documented evaluation object; never a historical writer target."""

    name: str
    kind: str
    role: str
    source: str
    line: int

    def __post_init__(self) -> None:
        shapes = {
            "root": ("country", {"actor"}),
            "target_country": ("country", {"target", "auxiliary"}),
            "enemy_country": ("country", {"target"}),
            "overlord": ("country", {"target"}),
            "target_state": ("state", {"target"}),
            "target_region": ("strategic_region", {"target"}),
            "region_score": ("scalar", {"auxiliary"}),
            "ship_modification_type": ("ship_modification", {"candidate"}),
            "interest_group": ("interest_group", {"candidate"}),
            "law": ("law", {"auxiliary"}),
            "diplomatic_play": ("diplomatic_play", {"auxiliary"}),
            "military_formation": ("military_formation", {"auxiliary"}),
            "amenability": ("scalar", {"auxiliary"}),
            "advance_chance": ("scalar", {"auxiliary"}),
            "stall_chance": ("scalar", {"auxiliary"}),
        }
        expected = shapes.get(self.name)
        formation_binding = (self.name, self.kind, self.role) in {
            ("root", "military_formation", "auxiliary"),
            ("owner", "country", "actor"),
        }
        if not formation_binding and (
            expected is None or self.kind != expected[0] or self.role not in expected[1]
        ):
            raise ValueError("求值上下文绑定名称、类型或角色无效")
        if not self.source or type(self.line) is not int or self.line < 1:
            raise ValueError("求值上下文绑定缺少行级来源证据")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "role": self.role,
            "source": self.source,
            "line": self.line,
        }


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Read-only consumer scope evidence, independent of migration identity."""

    actor_scope: ContextBinding | None = None
    targets: tuple[ContextBinding, ...] = ()
    auxiliary_scopes: tuple[ContextBinding, ...] = ()
    evidence: tuple[str, ...] = ()
    status: Literal["observed", "unknown", "ambiguous"] = "observed"

    def __post_init__(self) -> None:
        if self.status not in {"observed", "unknown", "ambiguous"}:
            raise ValueError("求值上下文状态无效")
        if self.status != "observed":
            if self.actor_scope is not None or self.targets or self.auxiliary_scopes:
                raise ValueError("未知或歧义上下文不能携带已证明绑定")
            return
        if self.actor_scope is None or self.actor_scope.role != "actor":
            raise ValueError("求值上下文 actor 角色无效")
        if any(item.role not in {"target", "candidate"} for item in self.targets):
            raise ValueError("求值上下文 target 角色无效")
        if any(item.role != "auxiliary" for item in self.auxiliary_scopes):
            raise ValueError("求值上下文辅助角色无效")
        bindings = (self.actor_scope, *self.targets, *self.auxiliary_scopes)
        if len({item.name for item in bindings}) != len(bindings):
            raise ValueError("求值上下文绑定名称重复")
        if not self.evidence or any(
            f"{item.source}:{item.line}" not in self.evidence for item in bindings
        ):
            raise ValueError("求值上下文缺少逐绑定来源证据")

    def as_dict(self) -> dict[str, object]:
        return {
            "actor_scope": self.actor_scope.as_dict() if self.actor_scope is not None else None,
            "targets": [item.as_dict() for item in self.targets],
            "auxiliary_scopes": [item.as_dict() for item in self.auxiliary_scopes],
            "evidence": list(self.evidence),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class LegacyDecisionIR:
    """一条 legacy 规则的完整、可序列化语义。

    legacy 规则仍由原版 ``Rule`` 保留资格、成本和执行尾部；本类型把
    同一条规则的条件、数值、作用域和消费者身份带入统一 bundle，避免
    ConsumerIR 只有登记身份而把真正 lowering 退回另一套隐式来源。
    """

    action_id: str
    source: str
    definition: str
    domain: str
    consumer_id: str
    field: str
    actor: str
    target: str
    operation: str
    value: float
    predicates: tuple[tuple[str, str, object], ...]
    vanilla_tail: str
    priority: int = 0
    why: str = ""
    counterexample: str = ""
    contexts: tuple[str, ...] = ()
    intent: str | None = None
    auxiliary_facts: tuple[str, ...] = ()
    required_known_facts: tuple[str, ...] = ()
    contribution_group: str = ""

    def to_action_ir(self) -> ActionIR:
        from .ir import ActionIR, PredicateIR  # noqa: PLC0415

        return ActionIR(
            action_id=self.definition,
            source=self.source,
            domain=self.domain,
            field=self.field,
            operation=self.operation,
            value=self.value,
            predicates=tuple(PredicateIR(*p) for p in self.predicates),
            vanilla_tail=self.vanilla_tail,
            priority=self.priority,
            why=self.why,
            counterexample=self.counterexample,
            contexts=self.contexts,
            intent=self.intent,
            auxiliary_facts=self.auxiliary_facts,
            required_known_facts=self.required_known_facts,
            contribution_group=self.contribution_group,
        )


@dataclass(frozen=True, slots=True)
class ConsumerDecisionIR:
    action_id: str
    domain: str
    consumer_id: str
    field: str
    operation: str
    core_evidence: tuple[str, ...]
    auxiliary_evidence: tuple[str, ...]
    hard_negative: tuple[str, ...]
    costs: tuple[str, ...]
    max_delta: float
    consumer_max_delta: float
    vanilla_tail: str
    unknown_policy: str
    relation_ids: tuple[str, ...]
    single_clamp: bool = True
    # 完整行动语义，供 lowering 与参考器共享。保留上面的证据别名，
    # 方便审计和兼容旧收据，但不再把它们当作唯一数据。
    improves: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    requires_all: tuple[str, ...] = ()
    requires_any: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    exit_when: tuple[str, ...] = ()
    base: float = 0.0
    stress: float = 0.0
    opportunity: float = 0.0
    commitment: float = 0.0
    political_cost: float = 0.0
    explanation: str = ""
    relations: tuple[Relation, ...] = ()
    commitment_when: tuple[CostPredicate, ...] = ()
    political_when: tuple[CostPredicate, ...] = ()
    zero_cost_reason: str = ""
    rank_terms: tuple[RankTerm, ...] = ()
    variant_group: str = ""
    variant_priority: int = 0
    cause_group: str = ""
    commitment_cost_id: str = ""
    political_cost_id: str = ""


@dataclass(frozen=True, slots=True)
class WriterDecisionIR:
    """每一条实际生产写入的统一身份行。

    legacy 行的业务谓词由不可变 LegacyDecisionIR 提供；这里保存精确的来源、
    消费者、作用域、操作和尾部合同，使其不能只靠旧规则计数冒充已接入。
    显式行动卡通过 ``action`` 关联完整的动态行动行。
    """

    writer_id: str
    kind: str
    source: str
    definition: str
    consumer_id: str
    field: str
    actor: str
    target: str
    operation: str
    vanilla_tail: str
    owner: str
    action: ConsumerDecisionIR | None = None
    legacy: LegacyDecisionIR | None = None
    predicates: tuple[tuple[str, str, object], ...] = ()
    chain_refs: tuple[tuple[str, str], ...] = ()
    evaluation_context: EvaluationContext | None = None
    reader_context_bindings: tuple[tuple[str, str, str, str], ...] = ()
    program: SupportProgram | None = None


@dataclass(frozen=True, slots=True)
class ConsumerIRBundle:
    schema: int
    actions: tuple[ConsumerDecisionIR, ...]
    writers: tuple[WriterDecisionIR, ...]
    source_hashes: tuple[tuple[str, str], ...] = ()
    chain_bindings: tuple[tuple[str, str, str], ...] = ()
    chains_bound: bool = False

    def writer_ids(self) -> tuple[str, ...]:
        return tuple(item.writer_id for item in self.writers)

    def as_dict(self) -> dict[str, Any]:
        self.validate_chain_refs()

        def predicate_dict(predicate: tuple[str, str, object]) -> list[object]:
            return [predicate[0], predicate[1], _json_value(predicate[2])]

        field_owners: dict[str, set[str]] = {}
        source_field_owners: dict[tuple[str, str], set[str]] = {}
        for item in self.writers:
            if item.kind == "support_program":
                program = item.program
                if (
                    program is None
                    or not program.enabled
                    or (
                        item.writer_id,
                        item.definition,
                        item.source,
                        item.consumer_id,
                        item.field,
                        item.operation,
                        item.actor,
                        item.target,
                        item.owner,
                        item.vanilla_tail,
                    )
                    != (
                        program.writer_id,
                        program.writer_id,
                        "mod/decisions/extensions.toml",
                        "diplomatic_play_support",
                        "diplomatic_play_support",
                        "add",
                        "root",
                        "target_country",
                        "situated_kernel",
                        "preserve",
                    )
                ):
                    raise ValueError("支持程序writer与完整语义不一致")
            elif item.program is not None:
                raise ValueError("非支持writer不能携带支持程序")
            field_owners.setdefault(item.field, set()).add(item.owner)
            source_field_owners.setdefault((item.source, item.field), set()).add(item.owner)
        conflicting = {
            field: sorted(owners) for field, owners in field_owners.items() if len(owners) > 1
        }
        if conflicting:
            raise ValueError(f"同一消费者字段存在多个生产 owner：{sorted(conflicting)}")
        source_conflicting = {
            key: sorted(owners) for key, owners in source_field_owners.items() if len(owners) > 1
        }
        if source_conflicting:
            raise ValueError(f"同一来源消费者字段存在多个生产 owner：{sorted(source_conflicting)}")
        return {
            "schema": self.schema,
            "action_count": len(self.actions),
            "writer_count": len(self.writers),
            "legacy_writer_count": sum(item.kind == "rule_action" for item in self.writers),
            "legacy_semantic_count": sum(
                item.kind == "rule_action" and item.legacy is not None for item in self.writers
            ),
            "action_card_writer_count": sum(
                item.kind == "action_card" and item.action is not None for item in self.writers
            ),
            "support_program_writer_count": sum(
                item.kind == "support_program" and item.program is not None for item in self.writers
            ),
            "writers": [
                {
                    "writer_id": item.writer_id,
                    "kind": item.kind,
                    "source": item.source,
                    "definition": item.definition,
                    "consumer_id": item.consumer_id,
                    "field": item.field,
                    "actor": item.actor,
                    "target": item.target,
                    "operation": item.operation,
                    "vanilla_tail": item.vanilla_tail,
                    "owner": item.owner,
                    "evaluation_context": (
                        item.evaluation_context.as_dict()
                        if item.evaluation_context is not None
                        else None
                    ),
                    "reader_context_bindings": [
                        list(binding) for binding in item.reader_context_bindings
                    ],
                    "chain_refs": [list(reference) for reference in item.chain_refs],
                    "predicates": [predicate_dict(predicate) for predicate in item.predicates],
                    "action_id": item.action.action_id if item.action is not None else None,
                    **({"program": item.program.as_dict()} if item.program is not None else {}),
                    "legacy_action": (
                        {
                            "action_id": item.legacy.action_id,
                            "source": item.legacy.source,
                            "definition": item.legacy.definition,
                            "domain": item.legacy.domain,
                            "consumer_id": item.legacy.consumer_id,
                            "field": item.legacy.field,
                            "actor": item.legacy.actor,
                            "target": item.legacy.target,
                            "operation": item.legacy.operation,
                            "value": item.legacy.value,
                            "priority": item.legacy.priority,
                            "why": item.legacy.why,
                            "counterexample": item.legacy.counterexample,
                            "contexts": list(item.legacy.contexts),
                            "intent": item.legacy.intent,
                            "auxiliary_facts": list(item.legacy.auxiliary_facts),
                            "required_known_facts": list(item.legacy.required_known_facts),
                            "predicates": [
                                [fact, operator, _json_value(value)]
                                for fact, operator, value in item.legacy.predicates
                            ],
                            "vanilla_tail": item.legacy.vanilla_tail,
                        }
                        if item.legacy is not None
                        else None
                    ),
                }
                for item in self.writers
            ],
            "source_hashes": dict(self.source_hashes),
            "chain_bindings": [list(binding) for binding in self.chain_bindings],
            "chains_bound": self.chains_bound,
            "field_owners": {
                field: next(iter(owners)) for field, owners in sorted(field_owners.items())
            },
            "source_field_owners": {
                f"{source}:{field}": next(iter(owners))
                for (source, field), owners in sorted(source_field_owners.items())
            },
        }

    def validate_chain_refs(self) -> None:
        """Check production chain traceability without reloading the compiler."""
        if (
            self.chains_bound
            or self.chain_bindings
            or any(writer.chain_refs for writer in self.writers)
        ):
            from .joint_chain_contract import validate_bundle_refs  # noqa: PLC0415

            validate_bundle_refs(self)


def _json_value(value: object) -> object:
    """将规则谓词中的 FactReference 转成稳定 JSON 值。"""

    if hasattr(value, "key") and hasattr(value, "expression"):
        return {"key": value.key, "expression": value.expression}
    return value


def compile_decisions(
    actions: tuple[ActionCard, ...],
    consumers: tuple[ConsumerContract, ...],
    relations: tuple[Relation, ...],
) -> tuple[ConsumerDecisionIR, ...]:
    by_consumer = {item.id: item for item in consumers}
    if len(by_consumer) != len(consumers):
        raise ValueError("消费者 ID 重复")
    by_action = {item.id: item for item in actions}
    if len(by_action) != len(actions):
        raise ValueError("行动 ID 重复")
    relation_ids: dict[str, list[str]] = {item.id: [] for item in actions}
    for relation in relations:
        if relation.source not in by_action or relation.target not in by_action:
            raise ValueError(f"关系引用未知行动：{relation.source}->{relation.target}")
        relation_ids[relation.source].append(f"{relation.kind}:{relation.target}")
    result: list[ConsumerDecisionIR] = []
    for action in actions:
        consumer = by_consumer.get(action.consumer)
        if consumer is None:
            raise ValueError(f"行动引用未知消费者：{action.id}")
        if action.max_delta > consumer.max_delta:
            raise ValueError(f"行动 {action.id} 超出消费者限幅")
        result.append(
            ConsumerDecisionIR(
                action_id=action.id,
                domain=action.domain,
                consumer_id=action.consumer,
                field=consumer.field,
                operation=consumer.operation,
                core_evidence=tuple(action.requires_all),
                auxiliary_evidence=tuple(action.requires_any),
                hard_negative=tuple(action.blocked_by),
                costs=(*action.consumes, *(("political_cost",) if action.political_cost else ())),
                max_delta=min(action.max_delta, consumer.max_delta),
                consumer_max_delta=consumer.max_delta,
                vanilla_tail=consumer.vanilla_tail,
                unknown_policy=action.unknown_policy,
                relation_ids=tuple(sorted(relation_ids[action.id])),
                improves=tuple(action.improves),
                consumes=tuple(action.consumes),
                requires_all=tuple(action.requires_all),
                requires_any=tuple(action.requires_any),
                blocked_by=tuple(action.blocked_by),
                exit_when=tuple(action.exit_when),
                base=action.base,
                stress=action.stress,
                opportunity=action.opportunity,
                commitment=action.commitment,
                political_cost=action.political_cost,
                explanation=action.explanation,
                commitment_when=action.commitment_when,
                political_when=action.political_when,
                zero_cost_reason=action.zero_cost_reason,
                rank_terms=action.rank_terms,
                variant_group=action.variant_group,
                variant_priority=action.variant_priority,
                cause_group=action.cause_group,
                commitment_cost_id=action.commitment_cost_id,
                political_cost_id=action.political_cost_id,
                relations=tuple(
                    sorted(
                        (relation for relation in relations if relation.source == action.id),
                        key=lambda relation: (
                            relation.kind,
                            relation.target,
                            relation.scope,
                        ),
                    )
                ),
            )
        )
    return tuple(sorted(result, key=lambda item: item.action_id))


def compile_consumer_ir(
    actions: tuple[ActionCard, ...],
    consumers: tuple[ConsumerContract, ...],
    relations: tuple[Relation, ...],
    legacy: tuple[ActionIR, ...],
    bindings: tuple[Binding, ...],
    instances: tuple[ActionInstance, ...],
    source_hashes: dict[str, str] | None = None,
) -> ConsumerIRBundle:
    """把显式卡和 legacy writer 汇入一份可审计生产 bundle。

    该入口不复制 legacy 谓词；它只读取已解析的 ``ActionIR`` 和精确绑定，
    因而任何来源、字段、actor/target 或 operation 漂移都会在生成期失败。
    """
    action_rows = compile_decisions(actions, consumers, relations)
    from .bindings import validate_disposition  # noqa: PLC0415

    for binding_row in bindings:
        validate_disposition(binding_row)
    binding_by_key = {(item.source, item.definition): item for item in bindings}
    instance_by_key = {(item.source, item.rule_id): item for item in instances}
    writers: list[WriterDecisionIR] = []
    for item in legacy:
        binding = binding_by_key.get((item.source, item.action_id))
        instance = instance_by_key.get((item.source, item.action_id))
        if binding is None or instance is None:
            raise ValueError(f"legacy writer 缺少精确绑定或实例：{item.source}:{item.action_id}")
        instance_target = (
            "target_state"
            if instance.target_scope == "target_or_none" and binding.target == "target_state"
            else instance.target_scope
        )
        if (
            binding.field != item.field
            or binding.operation != item.operation
            or binding.actor != instance.actor_scope
            or binding.target != instance_target
        ):
            raise ValueError(
                f"legacy writer 与绑定作用域/操作不一致：{item.source}:{item.action_id}"
            )
        writers.append(
            WriterDecisionIR(
                writer_id=instance.action_id,
                kind=instance.kind,
                source=item.source,
                definition=item.action_id,
                consumer_id=binding.consumer,
                field=item.field,
                actor=binding.actor,
                target=binding.target,
                operation=item.operation,
                vanilla_tail=item.vanilla_tail,
                owner=instance.owner,
                evaluation_context=instance.evaluation_context,
                legacy=LegacyDecisionIR(
                    action_id=instance.action_id,
                    source=item.source,
                    definition=item.action_id,
                    domain=item.domain,
                    consumer_id=binding.consumer,
                    field=item.field,
                    actor=binding.actor,
                    target=binding.target,
                    operation=item.operation,
                    value=item.value,
                    priority=item.priority,
                    why=item.why,
                    counterexample=item.counterexample,
                    contexts=item.contexts,
                    intent=item.intent,
                    auxiliary_facts=item.auxiliary_facts,
                    required_known_facts=item.required_known_facts,
                    contribution_group=item.contribution_group,
                    predicates=tuple(
                        (predicate.fact, predicate.operator, predicate.value)
                        for predicate in item.predicates
                    ),
                    vanilla_tail=item.vanilla_tail,
                ),
                predicates=tuple(
                    (predicate.fact, predicate.operator, predicate.value)
                    for predicate in item.predicates
                ),
            )
        )
    writers.extend(
        WriterDecisionIR(
            writer_id=f"card_{action.action_id}",
            kind="action_card",
            source="mod/decisions/actions.toml",
            definition=action.action_id,
            consumer_id=action.consumer_id,
            field=action.field,
            actor="root",
            target="none",
            operation=action.operation,
            vanilla_tail=action.vanilla_tail,
            owner="situated_kernel",
            action=action,
            evaluation_context=instance_by_key[
                ("mod/decisions/actions.toml", action.action_id)
            ].evaluation_context,
        )
        for action in action_rows
    )
    writers.sort(key=lambda item: item.writer_id)
    ids = [item.writer_id for item in writers]
    if len(ids) != len(set(ids)):
        raise ValueError("统一生产 writer ID 重复")
    if len(writers) != len(legacy) + len(action_rows):
        raise ValueError("统一生产 writer 数量不一致")
    return ConsumerIRBundle(
        schema=1,
        actions=action_rows,
        writers=tuple(writers),
        source_hashes=tuple(sorted((source_hashes or {}).items())),
    )


__all__ = [
    "ConsumerDecisionIR",
    "ConsumerIRBundle",
    "ContextBinding",
    "EvaluationContext",
    "LegacyDecisionIR",
    "WriterDecisionIR",
    "compile_consumer_ir",
    "compile_decisions",
]


def lower_legacy(
    policy: RuleSet, bundle: ConsumerIRBundle | None, *, source: str | None = None
) -> RuleSet:
    """Resolve exact immutable semantics before either reference evaluation or PDX lowering."""
    from .ir import from_rule  # noqa: PLC0415

    if bundle is None:
        raise ValueError("生产规则缺少 ConsumerIR writer")
    bundle.validate_chain_refs()
    writers = [item for item in bundle.writers if item.kind == "rule_action"]
    keys = [(item.source, item.definition) for item in writers]
    if len(keys) != len(set(keys)):
        raise ValueError("ConsumerIR legacy writer 重复")
    native = {item.action_id: item for item in policy.semantic_ir}
    result = []
    for rule in policy.rules:
        matches = [
            w for w in writers if w.definition == rule.id and (source is None or w.source == source)
        ]
        if len(matches) != 1 or matches[0].legacy is None:
            raise ValueError(f"生产规则缺少唯一 IR writer：{rule.id}")
        writer = matches[0]
        legacy = writer.legacy
        assert legacy is not None
        item = legacy.to_action_ir()
        candidate = native.get(rule.id, from_rule(rule, source=writer.source))
        base = (
            replace(candidate, priority=candidate.origin_priority, origin_priority=None)
            if candidate.origin_priority is not None
            else candidate
        )
        if base != item or candidate.to_rule() != rule:
            raise ValueError(f"ConsumerIR legacy 语义与生产规则不一致：{rule.id}")
        if (
            writer.writer_id != legacy.action_id
            or writer.source != legacy.source
            or writer.definition != legacy.definition
            or writer.field != legacy.field
            or writer.operation != legacy.operation
            or writer.actor != legacy.actor
            or writer.target != legacy.target
            or writer.consumer_id != legacy.consumer_id
            or writer.vanilla_tail != legacy.vanilla_tail
            or writer.predicates != legacy.predicates
            or not writer.owner
        ):
            raise ValueError(f"ConsumerIR writer 与规则不一致：{rule.id}")
        result.append(
            replace(item, priority=candidate.priority, origin_priority=candidate.origin_priority)
        )
    return replace(policy, semantic_ir=tuple(result))
