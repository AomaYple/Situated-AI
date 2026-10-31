"""处境规则的独立、可序列化中间表示。

IR 只描述已经登记的生产写入，不替换原版规则的资格、成本和执行尾部。
它让 source -> IR -> PDX 的链条可由审计器重新计算，而不是依赖自由文本。
"""

from __future__ import annotations

from collections.abc import Iterable  # noqa: TC003
from dataclasses import asdict, dataclass
from typing import Any

from ..decision_rules import FactReference, Rule  # noqa: TID252


@dataclass(frozen=True, slots=True)
class PredicateIR:
    fact: str
    operator: str
    value: object

    def as_dict(self) -> dict[str, Any]:
        value = self.value.key if isinstance(self.value, FactReference) else self.value
        return {"fact": self.fact, "operator": self.operator, "value": value}


@dataclass(frozen=True, slots=True)
class ActionIR:
    action_id: str
    source: str
    domain: str
    field: str
    operation: str
    value: float
    predicates: tuple[PredicateIR, ...]
    vanilla_tail: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["predicates"] = [item.as_dict() for item in self.predicates]
        return payload


def from_rule(rule: Rule, *, source: str) -> ActionIR:
    return ActionIR(
        action_id=rule.id,
        source=source,
        domain=rule.domain,
        field=".".join(rule.field),
        operation=rule.operation,
        value=rule.value,
        predicates=tuple(PredicateIR(item.fact, item.op, item.value) for item in rule.conditions),
        vanilla_tail="retain_original_qualification_cost_random_execution",
    )


def from_rules(items: Iterable[tuple[str, Rule]]) -> tuple[ActionIR, ...]:
    result = tuple(from_rule(rule, source=source) for source, rule in items)
    ids = [item.action_id for item in result]
    if len(ids) != len(set(ids)):
        raise ValueError("IR action_id 重复")
    return tuple(sorted(result, key=lambda item: (item.source, item.action_id)))


def contract(items: tuple[ActionIR, ...]) -> dict[str, Any]:
    return {
        "schema": 1,
        "count": len(items),
        "ids": [item.action_id for item in items],
        "instances": [item.as_dict() for item in items],
        "vanilla_tail": "preserved",
    }


__all__ = ["ActionIR", "PredicateIR", "contract", "from_rule", "from_rules"]
