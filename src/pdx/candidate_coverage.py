"""连接静态目录与候选清单；关联不提升目录状态或证明运行时行为。"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Any, TypedDict

from . import config
from .information_catalog import InformationCatalog

DEFAULT_SOURCE = "common/ai_strategies/00_default_strategy.txt"


class CoverageReport(TypedDict):
    format_version: int
    catalog_version: dict[str, str]
    candidate_version: str
    candidate_metadata_sha256: str
    metadata_authenticity: str
    supported_game_version: str
    evidence: str
    status_promotion: str
    links: list[dict[str, Any]]
    unresolved: list[dict[str, Any]]
    discovered_not_in_candidate: list[str]
    difference_semantics: str
    retained_vanilla_fields: list[dict[str, Any]]


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} 必须为字符串键对象")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 缺失或不是非空字符串")
    return value


def _rows(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须为列表")
    return [_mapping(row, label) for row in value]


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须为字符串列表")
    result = [_text(item, label) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{label} 重复")
    return result


def _digest(value: object, label: str) -> str:
    result = _text(value, label)
    if re.fullmatch(r"[a-f0-9]{64}", result) is None:
        raise ValueError(f"{label} 不是 SHA-256")
    return result


def _source(value: object) -> str:
    result = _text(value, "source")
    if (
        not result.startswith(("common/", "events/"))
        or "\\" in result
        or ":" in result
        or any(part in {"", ".", ".."} for part in result.split("/"))
    ):
        raise ValueError("source 必须是规范游戏相对路径")
    return result


def _field(value: object) -> str:
    result = _text(value, "field")
    if any(not part or part.strip() != part for part in result.split(".")):
        raise ValueError("field 必须是明确的非空字段路径")
    return result


def _strategy_fingerprints(
    data: dict[str, Any],
    fingerprints: dict[str, Any],
    adapters: dict[str, Any],
    contracts: list[tuple[str, str, dict[str, Any]]],
) -> None:
    """战略字段一旦出现就核对整条指纹链，避免部分新合同降级为旧协议。"""
    strategies = [adapters.get("strategy")]
    for _, _, contract in contracts:
        strategy = contract.get("strategy")
        has_intent = any(
            rule.get("intent") is not None for rule in _rows(contract.get("rules"), "rules")
        )
        if has_intent and strategy is None:
            raise ValueError("战略规则缺少 strategy 合同")
        strategies.append(strategy)
    if (
        "strategic_coordination" not in data
        and not any(key.startswith("strategic_") for key in fingerprints)
        and all(strategy is None for strategy in strategies)
    ):
        return

    expected = {
        key: _digest(fingerprints.get("strategic_" + key), "strategic_" + key)
        for key in ("source_sha256", "generator_sha256")
    }
    top = _mapping(data.get("strategic_coordination"), "strategic_coordination")
    for raw_strategy in [top, *(item for item in strategies if item is not None)]:
        strategy = _mapping(raw_strategy, "strategy")
        for key, digest in expected.items():
            if _digest(strategy.get(key), "strategy." + key) != digest:
                raise ValueError("候选战略生成指纹与战略合同不一致")


def build(catalog: InformationCatalog, metadata: Mapping[str, object]) -> CoverageReport:
    """只按来源和完整字段路径连接，返回可 JSON 序列化的确定性报告。

    ``metadata`` 是 integrated 生成物 ``.metadata/metadata.json`` 的解析对象。
    目录须带 ``caligula_branch=release/<supported_game_version>``。父目录命中只
    表示定位到祖先，``unmatched_suffix`` 明示未独立登记的子项。读取依赖完全
    来自每个合同的 ``rules[].inputs`` 与本合同 ``readers``，不搜索词袋。
    未关联静态资源保留完整 ID 差集，不自动解释为产品缺陷。函数不读写文件。
    """
    if not isinstance(catalog, InformationCatalog):
        raise ValueError("必须传入 InformationCatalog")
    if type(catalog.format_version) is not int or catalog.format_version != 1:
        raise ValueError("不支持的目录格式版本")
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata 必须为对象")
    # 同时拒绝不可序列化值、NaN 和非字符串对象键，不隐式修正输入。
    data = dict(metadata)
    _mapping(data, "metadata")
    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata 不是有限 JSON 数据") from exc
    if data.get("id") != config.MOD_ID:
        raise ValueError("metadata 缺少正确的候选身份")
    product_version = _text(data.get("version"), "version")
    game_version = _text(data.get("supported_game_version"), "supported_game_version")
    if not catalog.version or any(
        not isinstance(key, str) or not isinstance(value, str) or not value
        for key, value in catalog.version.items()
    ):
        raise ValueError("目录版本缺失或无效")
    if catalog.version.get("caligula_branch") != f"release/{game_version}":
        raise ValueError("目录游戏版本与候选不匹配")

    by_path: dict[tuple[str, str], list] = defaultdict(list)
    ids: set[str] = set()
    for item in catalog.items:
        if item.id in ids:
            raise ValueError(f"目录 ID 重复：{item.id}")
        ids.add(item.id)
        _digest(item.source_sha256, "catalog_raw_sha256")
        by_path[item.source, item.name].append(item)

    adapters = _mapping(data.get("consumer_adapters"), "consumer_adapters")
    information = _mapping(data.get("decision_rules"), "decision_rules")
    modules = _strings(data.get("enabled_modules"), "enabled_modules")
    if not {"information_rules", "consumer_adapters"} <= set(modules):
        raise ValueError("需要同时启用声明规则与消费者适配的 integrated 候选")
    fingerprints = _mapping(data.get("source_fingerprint"), "source_fingerprint")
    for section, prefix in ((information, "information_rules"), (adapters, "consumer_adapters")):
        for key in ("source_sha256", "generator_sha256"):
            if _digest(section.get(key), key) != _digest(fingerprints.get(prefix + "_" + key), key):
                raise ValueError("候选生成指纹与规则合同不一致")
    if type(adapters.get("schema")) is not int or adapters["schema"] != 1:
        raise ValueError("消费者适配格式版本无效")
    sources = _mapping(adapters.get("sources"), "consumer_adapters.sources")
    for source, digest in sources.items():
        _source(source)
        _digest(digest, "adapter_normalized_sha256")
    contracts = [("decision_rules", DEFAULT_SOURCE, information)]
    contract_sources: set[str] = set()
    for contract in _rows(adapters.get("consumers"), "consumer_adapters.consumers"):
        source = _source(contract.get("source"))
        if source in contract_sources:
            raise ValueError(f"消费者合同来源重复：{source}")
        contract_sources.add(source)
        if source not in sources:
            raise ValueError(f"消费者来源缺少锁定指纹：{source}")
        contracts.append(("consumer_adapters", source, contract))

    _strategy_fingerprints(data, fingerprints, adapters, contracts)

    links: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    matched_ids: set[str] = set()
    active_writers: set[tuple[str, str]] = set()

    def connect(row: dict[str, Any]) -> None:
        source, field = row["source"], row["consumer_field"]
        parts = field.split(".")
        for depth in range(len(parts), 0, -1):
            matches = by_path.get((f"game/{source}", ".".join(parts[:depth])), [])
            if not matches:
                continue
            if len(matches) != 1:
                unresolved.append({**row, "reason": "ambiguous_catalog_path"})
                return
            item = matches[0]
            links.append(
                {
                    **row,
                    "information_id": item.id,
                    "catalog_source": item.source,
                    "catalog_name": item.name,
                    "catalog_status": item.status.value,
                    "catalog_impact": item.impact.value,
                    "catalog_scope": item.scope,
                    "catalog_unit": item.unit,
                    "catalog_update": item.update,
                    "catalog_visibility": item.visibility,
                    "catalog_source_line": item.source_line,
                    "source_catalog_raw_sha256": item.source_sha256,
                    "matched_depth": depth,
                    "requested_depth": len(parts),
                    "unmatched_suffix": parts[depth:],
                    "match": "exact" if depth == len(parts) else "catalog_ancestor_only",
                    "subtree_coverage": "not_claimed",
                }
            )
            matched_ids.add(item.id)
            return
        unresolved.append({**row, "reason": "catalog_consumer_not_found"})

    for kind, source, contract in contracts:
        if type(contract.get("schema")) is not int or contract["schema"] != 1:
            raise ValueError("规则合同格式版本无效")
        baseline = _digest(contract.get("baseline_sha256"), "baseline_normalized_sha256")
        if kind == "consumer_adapters" and baseline != sources[source]:
            raise ValueError("适配器合同与适配器 sources 指纹不一致")
        domains = set(_strings(contract.get("enabled_domains"), "enabled_domains"))
        readers: dict[str, dict[str, Any]] = {}
        for reader in _rows(contract.get("readers"), "readers"):
            key = _text(reader.get("key"), "reader.key")
            for name in ("engine", "scope", "unit", "kind"):
                _text(reader.get(name), f"reader.{name}")
            if key in readers:
                raise ValueError(f"读取器 ID 重复：{key}")
            readers[key] = reader
        seen_rules: set[str] = set()
        active_count = 0
        for rule in _rows(contract.get("rules"), "rules"):
            rule_id = _text(rule.get("id"), "rule.id")
            if rule_id in seen_rules:
                raise ValueError(f"规则 ID 重复：{rule_id}")
            seen_rules.add(rule_id)
            field = _field(rule.get("field"))
            inputs = _strings(rule.get("inputs"), "rule.inputs")
            if set(inputs) - readers.keys():
                raise ValueError(f"规则引用缺失读取器：{rule_id}")
            consumer = _mapping(rule.get("consumer"), "rule.consumer")
            if not consumer:
                raise ValueError(f"规则缺少消费者合同：{rule_id}")
            if _text(rule.get("domain"), "rule.domain") not in domains:
                continue
            active_count += 1
            if kind == "decision_rules" and not field.startswith("ai_strategy_default."):
                field = "ai_strategy_default." + field
            active_writers.add((source, field))
            connect(
                {
                    "manifest_section": kind,
                    "source": source,
                    "consumer_field": field,
                    "rule_id": rule_id,
                    "rule": copy.deepcopy(rule),
                    "readers": [copy.deepcopy(readers[key]) for key in sorted(inputs)],
                    "source_adapter_normalized_sha256": baseline
                    if kind == "consumer_adapters"
                    else None,
                    "source_information_normalized_sha256": baseline
                    if kind == "decision_rules"
                    else None,
                    "evidence": "manifest_connection_only_not_runtime_or_behavior_verification",
                }
            )
        if (
            type(contract.get("active_rule_count")) is not int
            or contract["active_rule_count"] != active_count
        ):
            raise ValueError("合同 active_rule_count 与实际启用规则不一致")

    # 商品立场有独立的、实际生成的合同，不借用其它数值规则的读取器。
    supply = adapters.get("supply_plan")
    if supply is not None:
        supply = _mapping(supply, "supply_plan")
        source = _source(supply.get("source"))
        field = _field(supply.get("field"))
        goods = _strings(supply.get("goods"), "supply_plan.goods")
        threshold = supply.get("price_threshold")
        if (
            source not in sources
            or field != "ai_strategy_default.goods_stances"
            or supply.get("stance") != "wants_high_supply"
            or not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not math.isfinite(threshold)
            or threshold <= 0
            or supply.get("conditions")
            != [
                "is_ai",
                "existing_market_goods",
                "price_above_threshold",
                "negative_market_goods_delta",
            ]
        ):
            raise ValueError("商品供给合同无效")
        for good in goods:
            if re.fullmatch(r"[a-z][a-z0-9_]*", good) is None:
                raise ValueError("商品供给标识无效")
            consumer_field = field + "." + good
            active_writers.add((source, consumer_field))
            connect(
                {
                    "manifest_section": "consumer_adapters.supply_plan",
                    "source": source,
                    "consumer_field": consumer_field,
                    "rule_id": "supply:" + good,
                    "rule": copy.deepcopy(supply),
                    "readers": [
                        {
                            "engine": "market_goods_pricier",
                            "scope": "root.market.mg:" + good,
                            "unit": "price_above_base_ratio",
                            "kind": "number",
                            "operator": ">",
                            "threshold": threshold,
                        },
                        {
                            "engine": "market_goods_delta",
                            "scope": "root.market.mg:" + good,
                            "unit": "sell_minus_buy_orders",
                            "kind": "number",
                            "operator": "<",
                            "threshold": 0,
                        },
                    ],
                    "source_adapter_normalized_sha256": sources[source],
                    "evidence": "manifest_connection_only_not_runtime_or_behavior_verification",
                }
            )

    # 未提供实际合同的作者不能由其它规则或全局同名 reader 代填。
    seen_writers: set[tuple[str, str]] = set()
    for writer in _rows(adapters.get("field_owners"), "consumer_adapters.field_owners"):
        source, field = _source(writer.get("source")), _field(writer.get("field"))
        if source not in sources:
            raise ValueError("字段作者缺少锁定来源")
        if (source, field) in seen_writers:
            raise ValueError("字段作者重复")
        seen_writers.add((source, field))
        if (source, field) not in active_writers:
            unresolved.append(
                {
                    "manifest_section": "consumer_adapters.field_owners",
                    "source": source,
                    "consumer_field": field,
                    "owner": _text(writer.get("owner"), "field owner"),
                    "reason": "manifest_writer_without_rule_reader_contract",
                }
            )

    retained = []
    seen_coverage: set[tuple[str, str]] = set()
    for row in _rows(data.get("vanilla_field_coverage"), "vanilla_field_coverage"):
        field, source = _field(row.get("field")), _source(row.get("source"))
        if (source, field) in seen_coverage:
            raise ValueError("原版字段覆盖项重复")
        seen_coverage.add((source, field))
        status = row.get("status")
        if status not in {"generated_intervention", "retained_vanilla_not_new_mod_implementation"}:
            raise ValueError("原版字段覆盖状态无效")
        if status == "retained_vanilla_not_new_mod_implementation":
            retained.append(copy.deepcopy(row))

    def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
        return row["source"], row["consumer_field"], row.get("rule_id", "")

    return {
        "format_version": 1,
        "catalog_version": dict(sorted(catalog.version.items())),
        "candidate_version": product_version,
        "candidate_metadata_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest(),
        "metadata_authenticity": "caller_supplied_metadata_with_internal_fingerprint_consistency_not_signed_provenance",
        "supported_game_version": game_version,
        "evidence": "static_catalog_to_generated_manifest_only",
        "status_promotion": "none",
        "links": sorted(links, key=row_key),
        "unresolved": sorted(unresolved, key=row_key),
        "discovered_not_in_candidate": sorted(ids - matched_ids),
        "difference_semantics": "all_unlinked_catalog_ids_including_static_resources_not_automatic_product_defects",
        "retained_vanilla_fields": sorted(retained, key=lambda row: (row["source"], row["field"])),
    }
