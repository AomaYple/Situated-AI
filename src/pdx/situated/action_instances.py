"""把所有生产规则登记为可追溯的最小行动实例。

显式行动卡描述跨域仲裁；既有 information/adapters 规则则以规则身份
实例化为 ``rule_action``。两者共享 source -> owner -> PDX witness 映射，
这样旧规则不会成为行动内核之外的匿名旁路，同时保持现有原版消费者语义。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping  # noqa: TC003
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from .families import classify

if TYPE_CHECKING:
    from .. import decision_adapters, decision_rules  # noqa: TID252
    from .decision_ir import EvaluationContext
    from .schema import ActionCard, ConsumerContract

_SAFE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class ActionInstance:
    """一条实际生产写入的最小行动实例。"""

    action_id: str
    kind: str
    source: str
    rule_id: str
    domain: str
    consumer_field: str
    operation: str
    value: float
    condition_facts: tuple[str, ...]
    owner: str
    vanilla_tail: str
    evidence: tuple[str, ...]
    family_id: str = ""
    actor_scope: str = "root"
    target_scope: str = "none"
    evaluation_context: EvaluationContext | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _id(source: str, rule_id: str) -> str:
    value = _SAFE.sub("_", f"{source}_{rule_id}".lower()).strip("_")
    return f"rule_action_{value}"


def _rule_instance(
    source: str,
    rule: decision_rules.Rule,
    *,
    owner: str,
    actor_scope: str,
) -> ActionInstance:
    facts = tuple(sorted(rule.input_keys()))
    return ActionInstance(
        action_id=_id(source, rule.id),
        kind="rule_action",
        source=source,
        rule_id=rule.id,
        domain=rule.domain,
        consumer_field=".".join(rule.field),
        operation=rule.operation,
        value=rule.value,
        condition_facts=facts,
        owner=owner,
        vanilla_tail="retain_original_qualification_cost_random_execution",
        evidence=facts,
        family_id=classify(domain=rule.domain, field=".".join(rule.field), source=source),
        actor_scope=actor_scope,
        target_scope=("target_state" if rule.field and rule.field[-1] == "state_value" else "none"),
    )


def build(
    information: decision_rules.RuleSet,
    adapters: decision_adapters.AdapterSet,
    explicit: Iterable[ActionCard] = (),
    consumer_fields: Mapping[str, str] | None = None,
    consumer_contracts: Mapping[str, ConsumerContract] | None = None,
) -> tuple[ActionInstance, ...]:
    """从所有实际规则和显式卡构建稳定、无重复的实例目录。"""

    result: list[ActionInstance] = [
        _rule_instance(
            "mod/decisions/information.toml",
            rule,
            owner="information_rules",
            actor_scope="root",
        )
        for rule in information.rules
    ]
    for source, policy in adapters.policies:
        result.extend(
            _rule_instance(
                source,
                rule,
                owner="consumer_adapters",
                actor_scope="owner" if policy.actor_path else "root",
            )
            for rule in policy.rules
        )
    for card in explicit:
        consumer = (consumer_contracts or {}).get(card.consumer)
        if consumer is None:
            raise ValueError(f"显式行动卡缺少 ConsumerContract，拒绝使用隐式 field/tail：{card.id}")
        field = consumer.field
        if consumer_fields is not None and consumer_fields.get(card.consumer) != field:
            raise ValueError(f"显式行动卡消费者字段与 ConsumerContract 不一致：{card.id}")
        if consumer.operation != "add":
            raise ValueError(f"显式行动卡当前只支持 add 消费者：{card.id}")
        result.append(
            ActionInstance(
                action_id=f"card_{card.id}",
                kind="action_card",
                source="mod/decisions/actions.toml",
                rule_id=card.id,
                domain=card.domain,
                consumer_field=field,
                operation=consumer.operation,
                value=card.base,
                condition_facts=tuple(
                    sorted(
                        {
                            *card.requires_all,
                            *card.requires_any,
                            *card.blocked_by,
                            *(term.fact for term in card.rank_terms),
                        }
                    )
                ),
                owner="situated_kernel",
                vanilla_tail=consumer.vanilla_tail,
                evidence=tuple(
                    sorted(
                        {
                            *card.requires_all,
                            *card.requires_any,
                            *(term.fact for term in card.rank_terms),
                        }
                    )
                ),
                family_id=classify(
                    domain=card.domain,
                    field=f"{card.id}.{card.consumer}",
                    source="mod/decisions/actions.toml",
                ),
                actor_scope=consumer.scope,
            )
        )
    result.sort(key=lambda item: item.action_id)
    ids = [item.action_id for item in result]
    if len(ids) != len(set(ids)):
        raise ValueError("生产行动实例 ID 重复")
    return tuple(result)


def contract(instances: tuple[ActionInstance, ...]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_owner: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for item in instances:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        by_owner[item.owner] = by_owner.get(item.owner, 0) + 1
        by_domain[item.domain] = by_domain.get(item.domain, 0) + 1
        by_family[item.family_id] = by_family.get(item.family_id, 0) + 1
    return {
        "schema": 1,
        "count": len(instances),
        "by_kind": dict(sorted(by_kind.items())),
        "by_owner": dict(sorted(by_owner.items())),
        "by_domain": dict(sorted(by_domain.items())),
        "by_family": dict(sorted(by_family.items())),
        "instances": [item.as_dict() for item in instances],
        "source_to_ir_to_pdx": True,
        "vanilla_tail": "preserved_by_existing_rule_lowering",
        "evidence": "static_check",
    }


def witness_ids(texts: dict[str, str]) -> set[str]:
    """从生成脚本注释提取规则身份，作为独立生产见证。"""

    found: set[str] = set()
    for text in texts.values():
        for line in text.splitlines():
            match = re.search(
                r"#\s+(?:ACTION\s+)?([a-z][a-z0-9_]*)\s+\[[a-z][a-z0-9_]*\];",
                line,
            )
            if match:
                found.add(match.group(1))
    return found


def _output_source(source: str, field: str = "") -> str:
    """将生产源映射到生成产物中的实际文件。

    information 规则统一降低到默认策略文件；adapter 规则保留各自的
    生产路径。见证身份因此使用 ``(output_source, definition)``，不能只
    使用 definition，否则不同来源的同名规则可能互相冒充。
    """

    if source == "mod/decisions/information.toml":
        return "common/ai_strategies/00_default_strategy.txt"
    # 舰队供给字段由 adapter 从默认策略外置到独立 script_value 文件；
    # 其逻辑 source 仍是默认策略，见证 source 必须跟随实际生成文件。
    if (
        source == "common/ai_strategies/00_default_strategy.txt"
        and field
        == "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply"
    ):
        return "common/script_values/sitai_adapter_values.txt"
    return source


def witness_keys(texts: dict[str, str]) -> set[tuple[str, str]]:
    """返回生成 marker 的精确 ``(产物来源, definition)`` 身份。"""

    found: set[tuple[str, str]] = set()
    for source, text in texts.items():
        for line in text.splitlines():
            match = re.search(
                r"#\s+(?:ACTION\s+)?([a-z][a-z0-9_]*)\s+\[[a-z][a-z0-9_]*\];",
                line,
            )
            if match:
                found.add((source, match.group(1)))
    return found


def missing_witnesses(
    instances: tuple[ActionInstance, ...], texts: dict[str, str]
) -> tuple[str, ...]:
    witnesses = witness_keys(texts)
    return tuple(
        item.action_id
        for item in instances
        if item.kind == "rule_action"
        and (_output_source(item.source, item.consumer_field), item.rule_id) not in witnesses
    )


def witness_contract(
    instances: tuple[ActionInstance, ...], texts: dict[str, str]
) -> dict[str, object]:
    """逐实例记录生成标记见证；不把结构见证冒充行为质量。"""

    found = witness_keys(texts)
    rows = [
        {
            "action_id": item.action_id,
            "rule_id": item.rule_id,
            "family_id": item.family_id,
            "consumer_id": item.consumer_field,
            "actor_scope": item.actor_scope,
            "target_scope": item.target_scope,
            "witnessed": (
                item.kind != "rule_action"
                or (_output_source(item.source, item.consumer_field), item.rule_id) in found
            ),
            "evidence": "generated_marker_static_check",
        }
        for item in instances
    ]
    return {
        "schema": 1,
        "count": len(rows),
        "witnessed_count": sum(bool(row["witnessed"]) for row in rows),
        "missing": [row["action_id"] for row in rows if not row["witnessed"]],
        "rows": rows,
        "behavior_quality": "not_evaluated",
    }


def behavior_witness_contract(
    instances: tuple[ActionInstance, ...], texts: dict[str, str]
) -> dict[str, object]:
    """核对每条 legacy action 的实际生成操作和值。

    ``witness_contract`` 只检查 marker 是否存在；这里进一步解析生成文本，
    对 source + rule_id 反查 operation/value。它仍是静态 AST 证据，不声称
    游戏运行期已经执行了该分支。
    """

    from .lowering import witnesses  # noqa: PLC0415

    # 生成文本同时包含显式行动卡和 legacy 规则 marker。只把当前实例目录中
    # 真实 legacy writer 的精确 (产物来源, definition) 纳入重复检查；否则
    # 成本分区会让同一张显式卡合法地出现在多个互斥叶中，却被误报为
    # legacy 重复写入。
    expected_keys = {
        (_output_source(item.source, item.consumer_field), item.rule_id)
        for item in instances
        if item.kind == "rule_action"
    }
    generated = tuple(
        item for item in witnesses(texts) if (item.source, item.action_id) in expected_keys
    )
    by_id: dict[tuple[str, str], Any] = {}
    duplicate_ids: set[str] = set()
    for item in generated:
        key = (item.source, item.action_id)
        if key in by_id:
            duplicate_ids.add(item.action_id)
        else:
            by_id[key] = item
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    mismatches: list[str] = []
    for instance in instances:
        if instance.kind != "rule_action":
            continue
        output_source = _output_source(instance.source, instance.consumer_field)
        witness = by_id.get((output_source, instance.rule_id))
        target = instance.action_id
        if witness is None:
            missing.append(target)
            continue
        matched = (
            instance.rule_id not in duplicate_ids
            and witness.operation == instance.operation
            and witness.value == instance.value
        )
        if not matched:
            mismatches.append(target)
        rows.append(
            {
                "action_id": target,
                "source": instance.source,
                "output_source": output_source,
                "witness_source": witness.source,
                "rule_id": instance.rule_id,
                "operation": witness.operation,
                "value": witness.value,
                "matched": matched,
                "evidence": "independent_ast_value_static_check",
            }
        )
    return {
        "schema": 1,
        "count": len(rows),
        "expected": sum(item.kind == "rule_action" for item in instances),
        "missing": sorted(missing),
        "mismatches": sorted(mismatches),
        "duplicate_ids": sorted(duplicate_ids),
        "rows": rows,
        "behavior_quality": "not_evaluated",
    }


__all__ = [
    "ActionInstance",
    "behavior_witness_contract",
    "build",
    "contract",
    "missing_witnesses",
    "witness_contract",
    "witness_ids",
]
