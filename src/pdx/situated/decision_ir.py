"""统一的行动决策 IR。

``ConsumerDecisionIR`` 是生成器与 Python 参考器共同消费的生产输入。
它不是统计登记表：行动的资格、退出、关系、成本、限幅和原版消费者
都在这里保留一份不可变、可追踪的表示。源 ``ActionCard`` 只负责读取
和校验，后续 lowering 与参考求值不得重新从 TOML 或另一套派生逻辑取值。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .action_instances import ActionInstance
    from .bindings import Binding
    from .ir import ActionIR
    from .schema import ActionCard, ConsumerContract, Relation


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


@dataclass(frozen=True, slots=True)
class WriterDecisionIR:
    """每一条实际生产写入的统一身份行。

    legacy 行的业务谓词仍由原版 RuleSet 提供；这里保存精确的来源、
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


@dataclass(frozen=True, slots=True)
class ConsumerIRBundle:
    schema: int
    actions: tuple[ConsumerDecisionIR, ...]
    writers: tuple[WriterDecisionIR, ...]
    source_hashes: tuple[tuple[str, str], ...] = ()

    def writer_ids(self) -> tuple[str, ...]:
        return tuple(item.writer_id for item in self.writers)

    def as_dict(self) -> dict[str, Any]:
        def predicate_dict(predicate: tuple[str, str, object]) -> list[object]:
            return [predicate[0], predicate[1], _json_value(predicate[2])]

        field_owners: dict[str, set[str]] = {}
        source_field_owners: dict[tuple[str, str], set[str]] = {}
        for item in self.writers:
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
                    "predicates": [predicate_dict(predicate) for predicate in item.predicates],
                    "action_id": item.action.action_id if item.action is not None else None,
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
            "field_owners": {
                field: next(iter(owners)) for field, owners in sorted(field_owners.items())
            },
            "source_field_owners": {
                f"{source}:{field}": next(iter(owners))
                for (source, field), owners in sorted(source_field_owners.items())
            },
        }


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
    "LegacyDecisionIR",
    "WriterDecisionIR",
    "compile_consumer_ir",
    "compile_decisions",
]
