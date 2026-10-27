"""生成并核对 Situated AI 的情境决策解释报告。

报告只连接生成 metadata 中已经存在的读取器、规则和原版消费者合同。
它可以证明规则合同完整、信息域有明确状态和未知值边界，但不能证明游戏内
AI 已经按预期行动；行为质量仍需用户在标准包上长期观察。
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from . import country_state, decision_adapters, decision_intents, decision_rules, decisions

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
DEFAULT_SOURCE = "common/ai_strategies/00_default_strategy.txt"

# 画像是事实的有界分类，不是游戏内持久状态或跨单位求和。
PROFILE_ROLES = {
    engine: role
    for role, engines in {
        "current_guard": (
            "has_truce_with",
            "in_default",
            "is_in_government",
            "is_subject",
            "is_subject_of",
            "owner",
        ),
        "capacity": (
            "army_size",
            "bureaucracy",
            "fixed_income",
            "gdp",
            "gold_reserves",
            "infrastructure_delta",
            "legitimacy",
            "literacy_rate",
            "market_access",
            "navy_size",
            "total_population",
        ),
        "pressure": (
            "average_sol",
            "country_fervor_primary_culture",
            "ig_approval",
            "infamy",
            "liberty_desire",
            "market_goods_delta",
            "market_goods_pricier",
            "net_total_income",
            "radical_fraction",
            "scaled_debt",
            "state_goods_pricier",
            "state_unemployment_rate",
            "taking_loans",
            "weeks_until_bankruptcy",
        ),
        "structure": (
            "has_law_or_variant",
            "has_strategy",
            "has_technology_researched",
            "ig_clout",
            "is_production_method_active",
            "pop_type_percent_country",
            "primary_cultures_percent_state",
        ),
        "external_opportunity": (
            "has_diplomatic_pact",
            "has_treaty_alliance_with",
            "is_homeland_of_country_cultures",
            "is_isolated_from_market",
            "is_treaty_port",
            "relations:root",
        ),
        "current_shock": ("has_insurrectionary_interest_groups", "is_at_war", "has_variable"),
    }.items()
    for engine in engines
}
CURRENT_SHOCKS = {
    "active_war": ("is_at_war",),
    "fiscal_distress": ("in_default", "taking_loans", "weeks_until_bankruptcy"),
    "political_crisis": ("has_insurrectionary_interest_groups", "radical_fraction"),
    "market_pressure": ("market_goods_delta", "market_goods_pricier"),
    "war_defeat": ("has_variable",),
}
HISTORICAL_SHOCKS_WITHOUT_LOCKED_READER = (
    "diplomatic_humiliation",
    "revolution_outcome",
    "reform_outcome",
    "resource_interruption_history",
)


def source_metadata() -> dict[str, Any]:
    """从入库源和锁定底本构造不依赖本机游戏目录的合同。

    该路径只用于静态合同审计和无游戏 CI。生产生成仍必须经过
    :func:`pdx.distribution.package_inputs`，以便核对当前原版文件的指纹、
    作用域和消费者原件；这里绝不把源合同冒充当前游戏内容或行为验证。
    """

    policy = decisions.load()
    country_policy = country_state.load()
    extensions = decisions.load_extensions(profile="release")
    strategy = decision_intents.load()
    information = decision_rules.load(strategy=strategy)
    adapters = decision_adapters.load(strategy=strategy)

    information_contract = decision_rules.contract(information)

    consumers: list[dict[str, object]] = []
    for source, rules in adapters.policies:
        contract = decision_rules.contract(rules, owner="consumer_adapters")
        contract["source"] = source
        consumers.append(contract)

    metadata = decisions.metadata_payload(
        policy,
        extensions,
        baseline=decisions.BASELINE.read_text(encoding="utf-8"),
        complete_localization=True,
        country_policy=country_policy,
    )
    enabled_modules = metadata["enabled_modules"]
    if not isinstance(enabled_modules, list):
        raise TypeError("元数据的 enabled_modules 必须是列表")
    enabled_modules.extend(("information_rules", "consumer_adapters"))
    metadata["decision_rules"] = information_contract
    metadata["consumer_adapters"] = {
        "schema": 1,
        "evidence": "static_source_contract",
        "behavior_verified": False,
        "source_sha256": adapters.source_sha256,
        "sources": dict(adapters.sources),
        "consumers": consumers,
    }
    metadata["country_state"] = country_state.contract(country_policy)
    metadata["country_coordination"] = {
        "runtime_state": "bounded_persistent_routes" if country_policy.enabled else "disabled",
        "state_contract": metadata["country_state"],
        "behavior_verified": False,
        "evidence": "static_check",
    }
    return metadata


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


def _contracts(metadata: Mapping[str, Any]) -> list[tuple[str, str, Mapping[str, Any]]]:
    information = _mapping(metadata.get("decision_rules"), "decision_rules")
    adapters = _mapping(metadata.get("consumer_adapters"), "consumer_adapters")
    consumers = _rows(adapters.get("consumers"), "consumer_adapters.consumers")
    return [
        (DEFAULT_SOURCE, "information_rules", information),
        *[
            (_text(row.get("source"), "consumer.source"), "consumer_adapters", row)
            for row in consumers
        ],
    ]


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

    state = metadata.get("country_state")
    coordination = metadata.get("country_coordination")
    if not isinstance(state, Mapping) or not isinstance(coordination, Mapping):
        issues.append("缺少 country_state/country_coordination 合同")
    else:
        try:
            country_policy = country_state.load()
            expected = country_state.contract(country_policy)
            if dict(state) != expected:
                issues.append("country_state 合同与生产源不一致")
            fingerprint = metadata.get("source_fingerprint")
            if (
                not isinstance(fingerprint, Mapping)
                or fingerprint.get("country_state_source_sha256") != country_policy.source_sha256
            ):
                issues.append("country_state source_fingerprint 不一致")
            if coordination.get("state_contract") != dict(state):
                issues.append("country_coordination 未引用同源 country_state 合同")
        except (OSError, ValueError) as exc:
            issues.append(f"country_state 合同无法加载：{exc}")

    contract = _mapping(metadata.get("information_contract"), "information_contract")
    declared = contract.get("domains")
    if tuple(declared or ()) != DOMAINS:
        issues.append("information_contract.domains 与权威信息域顺序或集合不一致")

    seen: set[str] = set()
    seen_sources: set[tuple[str, str]] = set()
    field_authors: set[tuple[str, str]] = set()
    for source, owner, rule_contract in _contracts(metadata):
        source_owner = (source, owner)
        if source_owner in seen_sources:
            issues.append(f"消费者来源重复：{source}")
        seen_sources.add(source_owner)
        reader_rows = _rows(rule_contract.get("readers"), f"{source}.readers")
        readers = {_text(row.get("key"), "reader.key"): row for row in reader_rows}
        if len(readers) != len(reader_rows):
            issues.append(f"{source} 读取器 ID 重复")
        if (
            rule_contract.get("unknown_policy") != "preserve_unknown_and_fallback_vanilla"
            or rule_contract.get("runtime_state") != "none"
            or rule_contract.get("world_scans") != 0
        ):
            issues.append(f"{source} 未保持无状态、未知回退或零世界扫描合同")
        rules = _rules(rule_contract, source)
        owned = _mapping(rule_contract.get("field_owners"), f"{source}.field_owners")
        costs = _mapping(rule_contract.get("cost_by_field"), f"{source}.cost_by_field")
        fields: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        used_readers: set[str] = set()
        for rule in rules:
            rule_id = _text(rule.get("id"), "rule.id")
            label = f"{source}:{rule_id}"
            if rule_id in seen:
                issues.append(f"规则 ID 重复：{rule_id}")
            seen.add(rule_id)
            domain = _text(rule.get("domain"), f"{label}.domain")
            if domain not in DOMAINS:
                issues.append(f"{label} 使用未登记领域：{domain}")
            field = _text(rule.get("field"), f"{label}.field")
            fields[field].append(rule)
            for key in ("why", "counterexample"):
                _text(rule.get(key), f"{label}.{key}")
            inputs = rule.get("inputs")
            if (
                not isinstance(inputs, list)
                or not inputs
                or any(not isinstance(item, str) or item not in readers for item in inputs)
            ):
                issues.append(f"{label} 输入缺少可追溯读取器")
                continue
            conditions = _rows(rule.get("conditions"), f"{label}.conditions")
            referenced: set[str] = set()
            for condition in conditions:
                fact = condition.get("fact")
                if not isinstance(fact, str) or fact not in readers:
                    issues.append(f"{label} 条件引用未知事实：{fact}")
                    continue
                referenced.add(fact)
                other = condition.get("value")
                if isinstance(other, Mapping):
                    other_key = other.get("fact")
                    if not isinstance(other_key, str) or other_key not in readers:
                        issues.append(f"{label} 相对比较引用未知事实：{other_key}")
                    else:
                        referenced.add(other_key)
                        if readers[fact].get("unit") != readers[other_key].get("unit"):
                            issues.append(f"{label} 相对比较单位不一致")
            used_readers.update(referenced)
            if len(inputs) != len(set(inputs)) or set(inputs) != referenced:
                issues.append(f"{label} inputs 与实际条件不一致")
            consumer = rule.get("consumer")
            if not isinstance(consumer, Mapping) or (
                consumer.get("eligibility_costs_and_execution") != "retained_vanilla"
                or not consumer.get("scope_evidence")
            ):
                issues.append(f"{label} 缺少有效原版 consumer 合同")
            operation, value = rule.get("operation"), rule.get("value")
            bounds = (
                {"add": (-50, 50), "multiply": (0.5, 1.5)}.get(operation)
                if isinstance(operation, str)
                else None
            )
            valid_value = (
                bounds is not None
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and bounds[0] <= value <= bounds[1]
            )
            if not valid_value:
                issues.append(f"{label} 调整数值越界或操作无效")
        if set(readers) != used_readers:
            issues.append(f"{source} 有未使用或未连接的读取器")
        if set(owned) != set(fields) or set(costs) != set(fields):
            issues.append(f"{source} 字段作者或成本台账与规则不一致")
        for field, candidates in fields.items():
            if owned.get(field) != owner or (source, field) in field_authors:
                issues.append(f"{source}:{field} 重复作者或作者不一致")
            field_authors.add((source, field))
            priorities = [row.get("priority") for row in candidates]
            if any(type(value) is not int for value in priorities) or len(set(priorities)) != len(
                priorities
            ):
                issues.append(f"{source}:{field} 重复或无效优先级")
            cost = costs.get(field)
            input_keys = {
                key
                for row in candidates
                for key in row.get("inputs", [])
                if isinstance(key, str) and key in readers
            }
            expected_predicates = sum(len(row["conditions"]) for row in candidates)
            expected_depth = max(
                (len(readers[key].get("path") or []) for key in input_keys), default=0
            )
            if not isinstance(cost, Mapping) or any(
                cost.get(key) != expected
                for key, expected in (
                    ("candidates", len(candidates)),
                    ("predicates", expected_predicates),
                    ("scope_depth", expected_depth),
                )
            ):
                issues.append(f"{source}:{field} 成本台账不一致")
        for key, reader in readers.items():
            if reader.get("engine") not in PROFILE_ROLES:
                issues.append(f"{source}:{key} 未登记画像维度")
            if not all(reader.get(name) for name in ("scope", "unit", "update", "cost")):
                issues.append(f"{source}:{key} 缺少作用域、单位、刷新或成本")

    return issues


def build(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """从共享生产合同构造可逐项追溯的静态画像和消费者覆盖。"""

    issues = validate(metadata)
    if issues:
        raise ValueError("情境决策合同无效：" + "；".join(issues))
    domains: dict[str, dict[str, Any]] = {
        name: {"information_rules": 0, "consumer_rules": 0, "total_rules": 0} for name in DOMAINS
    }
    facts: list[dict[str, Any]] = []
    consumer_fields: list[dict[str, Any]] = []
    role_counts: dict[str, int] = defaultdict(int)
    shock_readers: dict[str, set[str]] = defaultdict(set)
    shock_rules: dict[str, set[str]] = defaultdict(set)
    information_reader_count = consumer_reader_count = 0
    information_rule_count = consumer_rule_count = 0
    contracts = _contracts(metadata)
    for source, owner, rule_contract in contracts:
        readers = {row["key"]: row for row in _rows(rule_contract["readers"], source)}
        rules_by_field: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        usages: dict[str, list[str]] = defaultdict(list)
        for rule in _rules(rule_contract, source):
            rules_by_field[rule["field"]].append(rule)
            domains[rule["domain"]][
                "information_rules" if owner == "information_rules" else "consumer_rules"
            ] += 1
            for key in rule["inputs"]:
                usages[key].append(rule["id"])
                for shock, engines in CURRENT_SHOCKS.items():
                    if readers[key]["engine"] in engines:
                        shock_rules[shock].add(rule["id"])
        for key, reader in sorted(readers.items()):
            role = PROFILE_ROLES[reader["engine"]]
            role_counts[role] += 1
            for shock, engines in CURRENT_SHOCKS.items():
                if reader["engine"] in engines:
                    shock_readers[shock].add(f"{source}:{key}")
            facts.append(
                {
                    "source": source,
                    "module": owner,
                    **reader,
                    "profile_dimension": role,
                    "status": "consumer_mapped_static; runtime_behavior_unverified",
                    "used_by": sorted(set(usages[key])),
                }
            )
        for field, candidates in sorted(rules_by_field.items()):
            ordered = sorted(candidates, key=lambda item: -item["priority"])
            consumer_fields.append(
                {
                    "source": source,
                    "field": field,
                    "owner": owner,
                    "cost": rule_contract["cost_by_field"][field],
                    "candidates": [
                        {
                            **rule,
                            "input_facts": [
                                {
                                    "key": key,
                                    "unit": readers[key]["unit"],
                                    "profile_dimension": PROFILE_ROLES[readers[key]["engine"]],
                                }
                                for key in rule["inputs"]
                            ],
                            "bounds": [-50, 50] if rule["operation"] == "add" else [0.5, 1.5],
                        }
                        for rule in ordered
                    ],
                }
            )
        if owner == "information_rules":
            information_reader_count += len(readers)
            information_rule_count += sum(map(len, rules_by_field.values()))
        else:
            consumer_reader_count += len(readers)
            consumer_rule_count += sum(map(len, rules_by_field.values()))
    for domain in domains.values():
        domain["total_rules"] = domain["information_rules"] + domain["consumer_rules"]
        domain["status"] = "consumer_mapped" if domain["total_rules"] else "discovered_only"
    return {
        "schema": 3,
        "goal": GOAL,
        "evidence": "static_generated_contract_only",
        "behavior_verified": False,
        "supported_game_version": metadata["supported_game_version"],
        "candidate_version": metadata["version"],
        "enabled_modules": list(metadata["enabled_modules"]),
        "domains": domains,
        "profile": {
            "kind": "bounded_static_fact_classification_with_runtime_country_state",
            "dimensions": dict(sorted(role_counts.items())),
            "runtime_state": metadata.get("country_coordination", {}).get(
                "runtime_state", "unknown"
            ),
        },
        "shocks": {
            "scope": "information_rules_and_consumer_adapters_only",
            "current_facts": {
                name: {
                    "status": "consumer_mapped_static" if shock_rules[name] else "no_consumer",
                    "readers": sorted(shock_readers[name]),
                    "rule_count": len(shock_rules[name]),
                }
                for name in CURRENT_SHOCKS
            },
            "historical_events": dict.fromkeys(
                HISTORICAL_SHOCKS_WITHOUT_LOCKED_READER,
                "unsupported_no_locked_runtime_reader",
            ),
            "memory": "bounded_mod_owned_country_routes_with_ttl_and_cooldown; vanilla_recent_war_variable_read; other_shocks_recomputed_at_vanilla_consumer_evaluation",
        },
        "facts": facts,
        "consumer_fields": consumer_fields,
        "field_count": len(consumer_fields),
        "information_reader_count": information_reader_count,
        "consumer_reader_count": consumer_reader_count,
        "reader_count": len(facts),
        "consumer_count": len(contracts) - 1,
        "information_rule_count": information_rule_count,
        "consumer_rule_count": consumer_rule_count,
        "unknown_policy": "preserve_unknown_and_fallback_vanilla",
        "execution_boundary": "vanilla_eligibility_cost_randomness_and_action_execution",
        "unverified": [
            "AI 实际选择是否符合国家处境",
            "长期平衡、后期性能和玩家体验",
            "跨平台 GUI 与创意工坊发布结果",
        ],
    }
