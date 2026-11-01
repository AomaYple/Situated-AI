"""真实生产规则到局部联合链的严格追踪合同。

此模块只登记已经存在的 source + rule_id，并核对其字段、条件和指纹。
它不创建第二套业务规则、不改变优先级，也不把链登记误报成行为完成。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pdx import decision_adapters, decision_rules

INFO_SOURCE = "mod/decisions/information.toml"


@dataclass(frozen=True, slots=True)
class ChainRuleBinding:
    chain_id: str
    role: str
    source: str
    rule_id: str
    field: str
    operation: str
    condition_fingerprint: str
    condition_facts: tuple[str, ...]
    bridge_facts: tuple[str, ...]
    status: str = "observed"


# 仅登记已有生产规则；source 是决策加载器真实使用的来源身份。
_BINDINGS: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "LJ01",
        "upstream",
        INFO_SOURCE,
        "economic_development",
        "wanted_construction_output",
        "industry",
    ),
    (
        "LJ01",
        "downstream",
        "common/buildings/03_mines.txt",
        "building_coal_mine_bottleneck",
        "building_coal_mine.ai_value",
        "market",
    ),
    (
        "LJ05",
        "fiscal",
        INFO_SOURCE,
        "fiscal_construction_guard",
        "wanted_construction_output",
        "construction",
    ),
    (
        "LJ05",
        "fiscal_recovery",
        "common/ai_strategies/00_default_strategy.txt",
        "coordinated_route_fiscal_recovery_ship_construction",
        "ai_strategy_default.ship_construction_output_multiplier",
        "construction",
    ),
    (
        "LJ11",
        "war_recovery",
        INFO_SOURCE,
        "war_defeat_reconstruction",
        "wanted_construction_output",
        "recovery",
    ),
    (
        "LJ11",
        "social_recovery",
        "common/ai_strategies/00_default_strategy.txt",
        "social_health_low_living_standard",
        "ai_strategy_default.institution_scores.institution_health_system",
        "recovery",
    ),
)


def _fingerprint(rule: Any) -> str:
    payload = {
        "id": rule.id,
        "domain": rule.domain,
        "field": ".".join(rule.field),
        "operation": rule.operation,
        "value": rule.value,
        "conditions": [
            {"fact": item.fact, "op": item.op, "value": getattr(item.value, "key", item.value)}
            for item in rule.conditions
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _policies() -> dict[str, Any]:
    result: dict[str, Any] = {INFO_SOURCE: decision_rules.load()}
    result.update(dict(decision_adapters.load().policies))
    return result


def build() -> tuple[ChainRuleBinding, ...]:
    policies = _policies()
    result: list[ChainRuleBinding] = []
    for chain_id, role, source, rule_id, field, _relation in _BINDINGS:
        policy = policies.get(source)
        if policy is None:
            raise ValueError(f"联合链来源不存在：{chain_id}:{source}")
        rules = {item.id: item for item in policy.rules}
        rule = rules.get(rule_id)
        if rule is None:
            raise ValueError(f"联合链规则不存在：{chain_id}:{source}:{rule_id}")
        actual_field = ".".join(rule.field)
        if actual_field != field:
            raise ValueError(f"联合链消费者字段漂移：{chain_id}:{rule_id}")
        facts = tuple(item.fact for item in rule.conditions)
        result.append(
            ChainRuleBinding(
                chain_id,
                role,
                source,
                rule_id,
                field,
                rule.operation,
                _fingerprint(rule),
                facts,
                (),
            )
        )
    ids = [(item.chain_id, item.role) for item in result]
    if len(ids) != len(set(ids)):
        raise ValueError("联合链绑定身份重复")
    by_chain: dict[str, list[ChainRuleBinding]] = {}
    for item in result:
        by_chain.setdefault(item.chain_id, []).append(item)
    enriched: list[ChainRuleBinding] = []
    for item in result:
        peers = by_chain[item.chain_id]
        shared = set(item.condition_facts)
        for peer in peers:
            if peer is not item:
                shared &= set(peer.condition_facts)
        enriched.append(
            ChainRuleBinding(
                item.chain_id,
                item.role,
                item.source,
                item.rule_id,
                item.field,
                item.operation,
                item.condition_fingerprint,
                item.condition_facts,
                tuple(sorted(shared)),
                "observed" if shared else "gap",
            )
        )
    return tuple(enriched)


def contract(bindings: tuple[ChainRuleBinding, ...] | None = None) -> dict[str, object]:
    bindings = build() if bindings is None else bindings
    return {
        "schema": 1,
        "count": len(bindings),
        "status": "observed_static_only",
        "bindings": [
            {
                "chain_id": item.chain_id,
                "role": item.role,
                "source": item.source,
                "rule_id": item.rule_id,
                "field": item.field,
                "operation": item.operation,
                "condition_fingerprint": item.condition_fingerprint,
                "condition_facts": list(item.condition_facts),
                "bridge_facts": list(item.bridge_facts),
                "status": item.status,
            }
            for item in bindings
        ],
    }


def validate(bindings: tuple[ChainRuleBinding, ...] | None = None) -> None:
    expected = build()
    actual = expected if bindings is None else bindings
    if [(i.chain_id, i.role, i.source, i.rule_id) for i in actual] != [
        (i.chain_id, i.role, i.source, i.rule_id) for i in expected
    ]:
        raise ValueError("联合链绑定与当前生产规则目录不一致")
    for item, current in zip(actual, expected, strict=True):
        if (
            item.condition_fingerprint != current.condition_fingerprint
            or item.condition_facts != current.condition_facts
        ):
            raise ValueError(f"联合链条件指纹或事实漂移：{item.chain_id}:{item.rule_id}")


__all__ = ["INFO_SOURCE", "ChainRuleBinding", "build", "contract", "validate"]
