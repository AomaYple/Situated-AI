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

from .. import decision_adapters, decision_rules  # noqa: TID252
from .families import classify

if TYPE_CHECKING:
    from .schema import ActionCard

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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _id(source: str, rule_id: str) -> str:
    value = _SAFE.sub("_", f"{source}_{rule_id}".lower()).strip("_")
    return f"rule_action_{value}"


def _rule_instance(source: str, rule: decision_rules.Rule, *, owner: str) -> ActionInstance:
    facts = tuple(
        sorted(
            {predicate.fact for predicate in rule.conditions}
            | {
                predicate.value.key
                for predicate in rule.conditions
                if isinstance(predicate.value, decision_rules.FactReference)
            }
        )
    )
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
        actor_scope="owner" if source != "mod/decisions/information.toml" else "root",
        target_scope="target_or_none"
        if rule.field and rule.field[-1] in {"state_value", "colonial_interest_ratio"}
        else "none",
    )


def build(
    information: decision_rules.RuleSet,
    adapters: decision_adapters.AdapterSet,
    explicit: Iterable[ActionCard] = (),
    consumer_fields: Mapping[str, str] | None = None,
) -> tuple[ActionInstance, ...]:
    """从所有实际规则和显式卡构建稳定、无重复的实例目录。"""

    result: list[ActionInstance] = [
        _rule_instance("mod/decisions/information.toml", rule, owner="information_rules")
        for rule in information.rules
    ]
    for source, policy in adapters.policies:
        result.extend(
            _rule_instance(source, rule, owner="consumer_adapters") for rule in policy.rules
        )
    result.extend(
        ActionInstance(
            action_id=f"card_{card.id}",
            kind="action_card",
            source="mod/decisions/actions.toml",
            rule_id=card.id,
            domain=card.domain,
            consumer_field=(consumer_fields or {}).get(card.consumer, card.consumer),
            operation="add",
            value=card.base,
            condition_facts=tuple(
                sorted({*card.requires_all, *card.requires_any, *card.blocked_by})
            ),
            owner="situated_kernel",
            vanilla_tail="retain_qualification_cost_random_execution",
            evidence=tuple(sorted({*card.requires_all, *card.requires_any})),
            family_id=classify(
                domain=card.domain,
                field=f"{card.id}.{card.consumer}",
                source="mod/decisions/actions.toml",
            ),
        )
        for card in explicit
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


def missing_witnesses(
    instances: tuple[ActionInstance, ...], texts: dict[str, str]
) -> tuple[str, ...]:
    witnesses = witness_ids(texts)
    return tuple(
        item.action_id
        for item in instances
        if item.kind == "rule_action" and item.rule_id not in witnesses
    )


def witness_contract(
    instances: tuple[ActionInstance, ...], texts: dict[str, str]
) -> dict[str, object]:
    """逐实例记录生成标记见证；不把结构见证冒充行为质量。"""

    found = witness_ids(texts)
    rows = [
        {
            "action_id": item.action_id,
            "rule_id": item.rule_id,
            "family_id": item.family_id,
            "consumer_id": item.consumer_field,
            "actor_scope": item.actor_scope,
            "target_scope": item.target_scope,
            "witnessed": item.rule_id in found,
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


__all__ = [
    "ActionInstance",
    "build",
    "contract",
    "missing_witnesses",
    "witness_contract",
    "witness_ids",
]
