"""从本机版本锁定原件生成法律、科技等消费者的最小权重补丁。

原件不随源码入库；标准包携带实际修改后的同路径文件。生成前核对全部
规范化 SHA，关闭时不输出覆盖文件。只改变明确登记的数值块，保留资格、
成本、效果和其它条目，运行期作用域及消费者仍需 F1 验证。
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from . import config, decision_rules, production_inputs
from .lexer import ATOM, LBRACE, OP, RBRACE, tokenize
from .model import Block, Scalar
from .parser import parse_text
from .textio import normalized_text

if TYPE_CHECKING:
    from collections.abc import Mapping

SOURCE = config.REPO / "mod/decisions/adapters.toml"


@dataclass(frozen=True, slots=True)
class InitialValue:
    """只为缺省的建筑评分显式恢复锁定 defines 中的原版基值。"""

    source: str
    field: tuple[str, ...]
    define_source: str
    define: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SupplyPlan:
    """对原版尚未声明立场的商品追加有条件的生产/贸易供给偏好。"""

    source: str
    goods: tuple[str, ...]
    price_threshold: float


@dataclass(frozen=True, slots=True)
class AdapterSet:
    sources: tuple[tuple[str, str], ...]
    policies: tuple[tuple[str, decision_rules.RuleSet], ...]
    source_sha256: str
    initial_values: tuple[InitialValue, ...] = ()
    supply: SupplyPlan | None = None
    scalar_values: tuple[tuple[str, tuple[str, ...]], ...] = ()


def writes(
    adapters: AdapterSet, enabled_domains: frozenset[str] | None = None
) -> tuple[tuple[str, tuple[str, ...], str], ...]:
    """登记所有实际写入，包括逐商品追加；父子字段不能有独立作者。"""
    values: list[tuple[str, tuple[str, ...], str]] = []
    for source, policy in adapters.policies:
        selected = (
            policy.enabled_domains
            if enabled_domains is None
            else enabled_domains & {rule.domain for rule in policy.rules}
        )
        values.extend((source, field, "consumer_adapters") for field in policy.groups(selected))
    supply = adapters.supply
    market_enabled = (
        any("market" in policy.enabled_domains for _, policy in adapters.policies)
        if enabled_domains is None
        else "market" in enabled_domains
    )
    if supply is not None and market_enabled:
        values.extend(
            (supply.source, ("ai_strategy_default", "goods_stances", good), "supply_plan")
            for good in supply.goods
        )
    values.sort()
    for (source, parent, _), (other_source, child, _) in pairwise(values):
        if source == other_source and child[: len(parent)] == parent:
            raise ValueError(f"消费者适配重复写入或父子字段冲突：{source}:{'.'.join(child)}")
    return tuple(values)


def load(source: Path = SOURCE) -> AdapterSet:
    raw = source.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    if set(data) - {"actors", "initial_values", "contexts", "supply", "scalar_values"} != {
        "schema",
        "sources",
        "domains",
        "readers",
        "rules",
    } or (type(data["schema"]) is not int or data["schema"] != 1):
        raise ValueError("消费者适配 schema 无效")
    if not isinstance(data["sources"], dict) or not data["sources"]:
        raise ValueError("消费者适配必须锁定全部原件")
    for name, digest in data["sources"].items():
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != name
            or not name.startswith(("common/", "events/"))
            or "\\" in name
            or ":" in name
            or path.suffix not in {".txt", ".md"}
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise ValueError("消费者适配原件路径或指纹无效")
    if not isinstance(data["rules"], list) or not data["rules"]:
        raise ValueError("消费者适配不能为空")
    groups: dict[str, list[dict]] = {}
    actors = data.get("actors", {})
    if not isinstance(actors, dict):
        raise ValueError("消费者 AI 所有者配置必须是映射")
    seen: set[str] = set()
    for item in data["rules"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("source"), str)
            or item.get("source") not in data["sources"]
            or not isinstance(item.get("id"), str)
            or item["id"] in seen
        ):
            raise ValueError("消费者适配规则身份或原件无效")
        name = item["source"]
        if not name.endswith(".txt") or not name.startswith(
            (
                "common/ai_strategies/",
                "common/laws/",
                "common/technology/technologies/",
                "common/buildings/",
            )
        ):
            raise ValueError("只允许适配已登记的数值消费者；事件只能作为读取依据")
        seen.add(item["id"])
        groups.setdefault(name, []).append(
            {key: value for key, value in item.items() if key != "source"}
        )
    if not isinstance(data["readers"], dict) or not isinstance(data["domains"], dict):
        raise ValueError("消费者适配读取器或开关无效")
    if actors.keys() - groups.keys():
        raise ValueError("消费者 AI 所有者不能缺少实际输出")
    policies = []
    used_readers: set[str] = set()
    used_domains: set[str] = set()
    contexts = data.get("contexts", {})
    if not isinstance(contexts, dict):
        raise ValueError("共享约束必须是映射")
    used_contexts: set[str] = set()
    digest = hashlib.sha256(raw).hexdigest()
    for name, rules in sorted(groups.items()):
        expected_actor = ["owner"] if name.startswith("common/buildings/") else []
        if actors.get(name, []) != expected_actor:
            raise ValueError("消费者 AI 所有者与锁定接口作用域不一致")
        try:
            names = {name for rule in rules for name in rule.get("contexts", [])}
            selected_contexts = {name: contexts[name] for name in names}
            conditions = [condition for rule in rules for condition in rule["conditions"]]
            conditions.extend(
                condition for items in selected_contexts.values() for condition in items
            )
            readers = {condition["fact"] for condition in conditions}
            readers.update(
                condition["value"]["fact"]
                for condition in conditions
                if isinstance(condition.get("value"), dict)
            )
            domains = {rule["domain"] for rule in rules}
            policy = decision_rules.from_data(
                {
                    "schema": 1,
                    "baseline_sha256": data["sources"][name],
                    "actor_path": actors.get(name, []),
                    "readers": {key: data["readers"][key] for key in readers},
                    "domains": {key: data["domains"][key] for key in domains},
                    "rules": rules,
                    "contexts": selected_contexts,
                },
                source_sha256=digest,
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("消费者适配缺少类型化输入或开关") from exc
        policies.append((name, policy))
        used_readers.update(readers)
        used_domains.update(domains)
        used_contexts.update(names)
    if used_readers != data["readers"].keys() or used_domains != data["domains"].keys():
        raise ValueError("消费者适配不能保留无消费者的输入或领域")
    if used_contexts != contexts.keys():
        raise ValueError("消费者适配不能保留无消费者的共享约束")
    initial_values = []
    seen_fields = set()
    if not isinstance(data.get("initial_values", []), list):
        raise ValueError("建筑缺省评分必须是列表")
    for item in data.get("initial_values", []):
        if not isinstance(item, dict) or set(item) != {
            "source",
            "field",
            "define_source",
            "define",
        }:
            raise ValueError("建筑缺省评分配置无效")
        native_source, field, define_source, define = (
            item[key] for key in ("source", "field", "define_source", "define")
        )
        if (
            not all(
                isinstance(value, str) for value in (native_source, field, define_source, define)
            )
            or native_source not in groups
            or not native_source.startswith("common/buildings/")
            or define_source not in data["sources"]
            or not define_source.startswith("common/defines/")
            or define
            not in {"NAI.PRODUCTION_BUILDING_BASE_VALUE", "NAI.GOVERNMENT_BUILDING_BASE_VALUE"}
        ):
            raise ValueError("建筑缺省评分必须引用锁定的原版建筑与 defines")
        field_path = tuple(field.split("."))
        if (
            len(field_path) != 2
            or field_path[1] != "ai_value"
            or (native_source, field_path) in seen_fields
        ):
            raise ValueError("建筑缺省评分路径无效或重复")
        policy = dict(policies)[native_source]
        if field_path not in {rule.field for rule in policy.rules}:
            raise ValueError("建筑缺省评分缺少实际规则消费者")
        seen_fields.add((native_source, field_path))
        initial_values.append(
            InitialValue(native_source, field_path, define_source, tuple(define.split(".")))
        )
    supply = None
    if "supply" in data:
        item = data["supply"]
        if (
            not isinstance(item, dict)
            or set(item) != {"source", "goods", "price_threshold"}
            or item["source"] != "common/ai_strategies/00_default_strategy.txt"
            or item["source"] not in groups
            or not isinstance(item["goods"], list)
            or not item["goods"]
            or any(
                not isinstance(good, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", good)
                for good in item["goods"]
            )
            or len(set(item["goods"])) != len(item["goods"])
            or not decision_rules._finite(item["price_threshold"])
            or not 0 < item["price_threshold"] <= 0.75
            or "market" not in used_domains
            or "common/goods/00_goods.txt" not in data["sources"]
        ):
            raise ValueError("商品供给计划必须是锁定默认策略上的有界追加")
        supply = SupplyPlan(
            item["source"], tuple(sorted(item["goods"])), float(item["price_threshold"])
        )
    scalar_values = []
    if not isinstance(data.get("scalar_values", []), list):
        raise ValueError("建筑常量评分必须是列表")
    for item in data.get("scalar_values", []):
        if not isinstance(item, dict) or set(item) != {"source", "field"}:
            raise ValueError("建筑常量评分配置无效")
        source_name, field = item["source"], item["field"]
        if not isinstance(source_name, str) or not isinstance(field, str):
            raise ValueError("建筑常量评分必须使用具名路径")
        scalar_path = tuple(field.split("."))
        building_scalar = (
            source_name.startswith("common/buildings/")
            and len(scalar_path) == 2
            and scalar_path[1] == "ai_value"
        )
        # 默认策略9545–9562明确允许任务权重使用国家作用域脚本值。
        # 只放行当前已审计字段；不把税收枚举或其它常量自动改成脚本值。
        fleet_scalar = (
            source_name == "common/ai_strategies/00_default_strategy.txt"
            and scalar_path
            == (
                "ai_strategy_default",
                "fleet_compositions",
                "secondary_fleet",
                "mission_type_weights",
                "protect_supply",
            )
        )
        if (
            not (building_scalar or fleet_scalar)
            or source_name not in groups
            or scalar_path not in {rule.field for rule in dict(policies)[source_name].rules}
            or (source_name, scalar_path) in scalar_values
            or (source_name, scalar_path) in seen_fields
        ):
            raise ValueError("建筑常量评分缺少唯一实际消费者")
        scalar_values.append((source_name, scalar_path))
    adapters = AdapterSet(
        tuple(sorted(data["sources"].items())),
        tuple(policies),
        digest,
        tuple(initial_values),
        supply,
        tuple(sorted(scalar_values)),
    )
    writes(adapters)
    return adapters


def _wrap_scalars(text: str, fields: set[tuple[str, ...]]) -> str:
    """把版本锁定的数值常量包入 value 块；保留原数字、注释和其余字节。"""
    if parse_text(text).errors:
        raise ValueError("建筑常量评分原件无法解析")
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    changes: list[tuple[int, int, str]] = []
    stack: list[str] = []
    previous = before_previous = None
    found: set[tuple[str, ...]] = set()
    for token in tokenize(text):
        key = (
            before_previous.value
            if previous is not None
            and previous.kind == OP
            and before_previous is not None
            and before_previous.kind == ATOM
            else None
        )
        if token.kind == LBRACE:
            if key is not None and (*stack, key) in fields:
                raise ValueError("建筑常量评分不能覆写已有块")
            stack.append(key or "<anonymous>")
        elif token.kind == RBRACE:
            stack.pop()
        elif token.kind == ATOM and key is not None and (*stack, key) in fields:
            field = (*stack, key)
            if (
                field in found
                or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", token.value)
                or not decision_rules._finite(float(token.value))
            ):
                raise ValueError("建筑常量评分必须是唯一非负数值，不能覆写表达式")
            found.add(field)
            start = offsets[token.line - 1] + token.col - 1
            fragment = f"{{ value = {token.value} # SITAI wrapped-scalar:{'.'.join(field)}\n}}"
            changes.append((start, start + len(token.value), fragment))
        before_previous, previous = previous, token
    if found != fields:
        raise ValueError("建筑常量评分不是锁定的数值常量")
    for start, end, fragment in sorted(changes, reverse=True):
        text = text[:start] + fragment + text[end:]
    return text


def _supply_patch(
    text: str, plan: SupplyPlan, inputs: Mapping[str, str], words: frozenset[str]
) -> str:
    """保留已有商品立场与资格，只追加缺省的、按市场稀缺激活的立场。"""
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("供给计划原件无法解析")
    strategy = parsed.root.first("ai_strategy_default")
    if strategy is None or not isinstance(strategy.value, Block):
        raise ValueError("供给计划缺少默认策略")
    goods_stances = strategy.value.first("goods_stances")
    if goods_stances is None or not isinstance(goods_stances.value, Block):
        raise ValueError("供给计划缺少唯一商品立场表")
    definitions = parse_text(inputs["common/goods/00_goods.txt"])
    if (
        definitions.errors
        or not {
            "market_goods_delta",
            "market_goods_pricier",
            "wants_high_supply",
            "market",
            "mg:grain",
        }
        <= words
    ):
        raise ValueError("商品供给计划缺少锁定的原版读取或立场依据")
    for good in plan.goods:
        if goods_stances.value.first(good) is not None or len(definitions.root.all(good)) != 1:
            raise ValueError(f"商品供给计划不能覆写原版立场或引用未知商品：{good}")
    position = decision_rules._offsets(text, {("ai_strategy_default", "goods_stances")})[
        ("ai_strategy_default", "goods_stances")
    ]
    rows = ["\n\t\t# SITAI BEGIN supply:goods_stances\n"]
    rows.extend(
        f"\t\t{good} = {{ stance = wants_high_supply trigger = {{ "
        f"is_ai = yes exists = market market = {{ exists = mg:{good} mg:{good} = {{ "
        f"market_goods_pricier > {plan.price_threshold!r} market_goods_delta < 0 "
        "} } } }\n"
        for good in plan.goods
    )
    rows.append("\t\t# SITAI END supply:goods_stances\n\t")
    result = text[:position] + "".join(rows) + text[position:]
    if parse_text(result).errors:
        raise ValueError("商品供给计划产物无法解析")
    return result


def _initialize(
    text: str,
    items: list[InitialValue],
    inputs: Mapping[str, str],
    definitions_cache: dict[str, Block],
) -> str:
    """增加有默认语义依据的缺省数值块；关闭不调用，已有值一律拒绝覆盖。"""
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("建筑原件无法解析")
    values = {}
    for item in items:
        parent = parsed.root.first(item.field[0])
        if (
            parent is None
            or not isinstance(parent.value, Block)
            or len(parsed.root.all(item.field[0])) != 1
        ):
            raise ValueError("建筑缺省评分父块不唯一")
        if parent.value.first(item.field[1]) is not None:
            raise ValueError("建筑评分已经存在，不能覆写或使用缺省值")
        definitions = definitions_cache.get(item.define_source)
        if definitions is None:
            result = parse_text(inputs[item.define_source])
            if result.errors:
                raise ValueError("建筑缺省评分 defines 无效")
            definitions = result.root
            definitions_cache[item.define_source] = definitions
        namespace = definitions.first(item.define[0])
        if (
            namespace is None
            or not isinstance(namespace.value, Block)
            or len(definitions.all(item.define[0])) != 1
        ):
            raise ValueError("建筑缺省评分 defines 无效")
        definition = namespace.value.first(item.define[1])
        if (
            definition is None
            or not isinstance(definition.value, Scalar)
            or len(namespace.value.all(item.define[1])) != 1
        ):
            raise ValueError("建筑缺省评分 define 不是常量")
        value = definition.value.unquoted
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
            raise ValueError("建筑缺省评分必须是非负数值常量")
        values[item.field] = value
    # 使用与补丁编译器相同的词法定位，不能按字符串或行尾猜括号。
    offsets = decision_rules._offsets(text, {(item.field[0],) for item in items})
    for path, value in sorted(
        values.items(), key=lambda pair: offsets[(pair[0][0],)], reverse=True
    ):
        position = offsets[(path[0],)]
        key = ".".join(path)
        fragment = (
            f"\n\t# SITAI BEGIN initialized:{key}\n"
            f"\tai_value = {{ value = {value} }}\n"
            f"\t# SITAI END initialized:{key}\n"
        )
        text = text[:position] + fragment + text[position:]
    return text


def build(
    adapters: AdapterSet,
    *,
    game: Path | None = None,
    texts: Mapping[str, str] | None = None,
    enabled_domains: frozenset[str] | None = None,
    overlays: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, object]]:
    """全输入预检后生成；合成测试可显式注入文本，生产默认读取 config.GAME。"""
    game = config.GAME if game is None else game
    known_domains = {rule.domain for _, policy in adapters.policies for rule in policy.rules}
    if enabled_domains is not None and enabled_domains - known_domains:
        raise ValueError("消费者适配含未知领域开关")
    owners = writes(adapters, enabled_domains)
    inputs = {}
    for name, expected in adapters.sources:
        try:
            text = (game / name).read_text(encoding="utf-8-sig") if texts is None else texts[name]
        except (OSError, KeyError) as exc:
            raise ValueError(f"消费者适配缺少锁定游戏原件：{name}") from exc
        text = normalized_text(text)
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected:
            raise ValueError(f"消费者适配原件漂移：{name}")
        inputs[name] = text
    # 一次词法扫描同时建立校验集合与原件定位，避免逐读取器反复扫描大文件。
    evidence: dict[str, dict[str, object]] = {}
    for name, text in inputs.items():
        for token in tokenize(text):
            if token.kind == ATOM and token.value not in evidence:
                evidence[token.value] = {"source": name, "line": token.line}
    words = frozenset(evidence)
    files = {}
    contracts = []
    initialized = []
    required_engines: set[str] = set()
    active_methods: set[tuple[str, str]] = set()
    definitions_cache: dict[str, Block] = {}
    for name, policy in adapters.policies:
        selected = (
            policy.enabled_domains
            if enabled_domains is None
            else (enabled_domains & {rule.domain for rule in policy.rules})
        )
        if not selected:
            continue
        text = overlays.get(name, inputs[name]) if overlays is not None else inputs[name]
        initial_values = [
            item
            for item in adapters.initial_values
            if item.source == name
            and any(
                rule.field == item.field
                for rules in policy.groups(selected).values()
                for rule in rules
            )
        ]
        if initial_values:
            text = _initialize(text, initial_values, inputs, definitions_cache)
            initialized.extend(initial_values)
        scalar_fields = {
            field
            for source, field in adapters.scalar_values
            if source == name and field in policy.groups(selected)
        }
        if scalar_fields:
            text = _wrap_scalars(text, scalar_fields)
        files[name] = decision_rules.patch(
            text,
            policy,
            baseline=inputs[name],
            enabled_domains=selected,
            default_strategy=False,
            reader_words=words,
        )
        used_keys = {
            key
            for rules in policy.groups(selected).values()
            for rule in rules
            for key in rule.input_keys()
        }
        required_engines.update(
            reader.engine for reader in policy.readers if reader.key in used_keys
        )
        for reader in policy.readers:
            if reader.key in used_keys and reader.engine == "is_production_method_active":
                parameters = dict(reader.parameters)
                active_methods.add((parameters["building_type"], parameters["production_method"]))
        contracts.append(
            {
                "source": name,
                **decision_rules.contract(
                    replace(policy, enabled_domains=selected), owner="consumer_adapters"
                ),
            }
        )
    supply = adapters.supply
    supply_enabled = supply is not None and (
        any("market" in policy.enabled_domains for _, policy in adapters.policies)
        if enabled_domains is None
        else "market" in enabled_domains
    )
    if supply is not None and supply_enabled:
        text = files.get(supply.source, (overlays or {}).get(supply.source, inputs[supply.source]))
        files[supply.source] = _supply_patch(text, supply, inputs, words)
    return files, {
        "schema": 1,
        "evidence": "source_locked_generated_consumer_patches",
        "behavior_verified": False,
        "source_sha256": adapters.source_sha256,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "production_inputs_generator_sha256": hashlib.sha256(
            Path(production_inputs.__file__).read_bytes()
        ).hexdigest(),
        "sources": dict(adapters.sources),
        "field_owners": [
            {"source": source, "field": ".".join(field), "owner": owner}
            for source, field, owner in owners
        ],
        "reader_evidence": {engine: evidence[engine] for engine in sorted(required_engines)},
        "reader_evidence_limits": "token_locations_only; typed_signatures_are_static_contracts; engine_validity_pending_f1",
        "production_recipes": production_inputs.recipes(inputs, active_methods),
        "initialized_consumers": [
            {
                "source": item.source,
                "field": ".".join(item.field),
                "define_source": item.define_source,
                "define": ".".join(item.define),
            }
            for item in initialized
        ],
        "scalar_consumers": [
            {
                "source": source,
                "field": ".".join(field),
                "operation": "retain_native_constant_in_value_block",
            }
            for source, field in adapters.scalar_values
            if any(
                row_source == source and row_field == field for row_source, row_field, _ in owners
            )
        ],
        "supply_plan": None
        if supply is None or not supply_enabled
        else {
            "source": supply.source,
            "field": "ai_strategy_default.goods_stances",
            "goods": list(supply.goods),
            "price_threshold": supply.price_threshold,
            "stance": "wants_high_supply",
            "conditions": [
                "is_ai",
                "existing_market_goods",
                "price_above_threshold",
                "negative_market_goods_delta",
            ],
            "consumer": "vanilla_production_and_trade_planning",
            "behavior_verified": False,
            "limits": "market_aggregate_not_national_import_dependency; active_strategy_overrides_retained; no_forced_trade_or_production_method",
        },
        "consumers": contracts,
        "runtime_state": "none",
        "refresh": "vanilla_consumer_evaluation",
        "disable": "regenerate_without_adapter_files_and_restart",
        "compatibility": "locked_game_version_same_path_minimal_ai_weight_edits",
    }
