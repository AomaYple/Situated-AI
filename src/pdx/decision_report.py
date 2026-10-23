"""生成并核对 Situated AI 的情境决策解释报告。

报告只连接生成 metadata 中已经存在的读取器、规则和原版消费者合同。
它可以证明规则合同完整、信息域有明确状态和未知值边界，但不能证明游戏内
AI 已经按预期行动；行为质量仍需用户在标准包上长期观察。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DOMAINS = (
    "political",
    "fiscal",
    "economy",
    "market",
    "diplomacy",
    "subjects",
    "military",
    "geography",
    "identity",
)
GOAL = "基于国家处境和可观测信息，在原版机制内持续做出受约束的相对最优决策"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须是对象")
    return value


def _rows(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是列表")
    return [_mapping(row, label) for row in value]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空文本")
    return value


def _rules(contract: Mapping[str, Any], label: str) -> list[Mapping[str, Any]]:
    return _rows(contract.get("rules"), f"{label}.rules")


def validate(metadata: Mapping[str, Any]) -> list[str]:
    """返回可机械检查的合同问题；不把未实测行为当作错误。"""

    issues: list[str] = []
    if metadata.get("id") != "situated-ai":
        issues.append("metadata 身份不是 situated-ai")
    issues.extend(
        f"metadata 缺少 {key}"
        for key in ("version", "supported_game_version")
        if not isinstance(metadata.get(key), str) or not metadata[key]
    )

    modules = metadata.get("enabled_modules")
    if not isinstance(modules, list) or not {"information_rules", "consumer_adapters"} <= set(
        modules
    ):
        issues.append("必须同时启用 information_rules 和 consumer_adapters")

    information = _mapping(metadata.get("decision_rules"), "decision_rules")
    adapters = _mapping(metadata.get("consumer_adapters"), "consumer_adapters")
    contract = _mapping(metadata.get("information_contract"), "information_contract")
    declared = contract.get("domains")
    if tuple(declared or ()) != DOMAINS:
        issues.append("information_contract.domains 与权威信息域顺序或集合不一致")

    info_rules = _rules(information, "decision_rules")
    adapter_rows = _rows(adapters.get("consumers"), "consumer_adapters.consumers")
    all_rules = [*info_rules]
    for index, consumer in enumerate(adapter_rows):
        all_rules.extend(_rules(consumer, f"consumer_adapters.consumers[{index}]"))

    seen: set[str] = set()
    for index, rule in enumerate(all_rules):
        label = f"规则[{index}]"
        rule_id = _text(rule.get("id"), f"{label}.id")
        if rule_id in seen:
            issues.append(f"规则 ID 重复：{rule_id}")
        seen.add(rule_id)
        _text(rule.get("domain"), f"{label}.domain")
        _text(rule.get("field"), f"{label}.field")
        _text(rule.get("why"), f"{label}.why")
        _text(rule.get("counterexample"), f"{label}.counterexample")
        inputs = rule.get("inputs")
        if (
            not isinstance(inputs, list)
            or not inputs
            or any(not isinstance(item, str) for item in inputs)
        ):
            issues.append(f"{label} 缺少可追溯 inputs")
        if not isinstance(rule.get("consumer"), Mapping):
            issues.append(f"{label} 缺少原版 consumer 合同")

    return issues


def build(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """构造确定性的域、读取器、消费者和规则摘要。"""

    issues = validate(metadata)
    if issues:
        raise ValueError("情境决策合同无效：" + "；".join(issues))
    information = _mapping(metadata["decision_rules"], "decision_rules")
    adapters = _mapping(metadata["consumer_adapters"], "consumer_adapters")
    info_rules = _rules(information, "decision_rules")
    consumer_rows = _rows(adapters["consumers"], "consumer_adapters.consumers")
    adapter_rules = [rule for row in consumer_rows for rule in _rules(row, "consumer")]
    domain_counts: dict[str, dict[str, Any]] = {}
    for domain in DOMAINS:
        domain_counts[domain] = {
            "information_rules": sum(row.get("domain") == domain for row in info_rules),
            "consumer_rules": sum(row.get("domain") == domain for row in adapter_rules),
        }
        total = sum(domain_counts[domain].values())
        domain_counts[domain]["total_rules"] = total
        domain_counts[domain]["status"] = "consumer_mapped" if total else "discovered_only"

    reader_rows = _rows(information.get("readers"), "decision_rules.readers")
    return {
        "schema": 1,
        "goal": GOAL,
        "evidence": "static_generated_contract_only",
        "behavior_verified": False,
        "supported_game_version": metadata["supported_game_version"],
        "candidate_version": metadata["version"],
        "enabled_modules": list(metadata["enabled_modules"]),
        "domains": domain_counts,
        "reader_count": len(reader_rows),
        "consumer_count": len(consumer_rows),
        "information_rule_count": len(info_rules),
        "consumer_rule_count": len(adapter_rules),
        "unknown_policy": "preserve_unknown_and_fallback_vanilla",
        "execution_boundary": "vanilla_eligibility_cost_randomness_and_action_execution",
        "unverified": [
            "AI 实际选择是否符合国家处境",
            "长期平衡、后期性能和玩家体验",
            "跨平台 GUI 与创意工坊发布结果",
        ],
    }
