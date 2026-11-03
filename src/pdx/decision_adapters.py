"""从本机版本锁定原件生成法律、科技等消费者的最小权重补丁。

原件不随源码入库；标准包携带实际修改后的同路径文件。生成前核对全部
规范化 SHA，关闭时不输出覆盖文件。只改变明确登记的数值块，保留资格、
成本、效果和其它条目，运行期作用域与消费者以锁定原版接口合同为准；长期行为由用户实机验收。
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from . import (
    building_opportunities,
    company_sectors,
    config,
    decision_intents,
    decision_rules,
    equipment_opportunities,
    law_opportunities,
    mobilization_opportunities,
    observation_queries,
    production_inputs,
    technology_opportunities,
    treaty_opportunities,
)
from .lexer import ATOM, LBRACE, OP, RBRACE, tokenize
from .model import Block, Scalar
from .parser import parse_text
from .situated import supply_program
from .situated.supply_program import SupplyAction, SupplyProgram
from .textio import normalized_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .country_state import CountryPolicy
    from .situated.decision_ir import ConsumerIRBundle

SOURCE = config.REPO / "mod/decisions/adapters.toml"
_FLEET_SOURCE = "common/ai_strategies/00_default_strategy.txt"
_FLEET_FIELD = (
    "ai_strategy_default",
    "fleet_compositions",
    "secondary_fleet",
    "mission_type_weights",
    "protect_supply",
)
_FLEET_VALUE = "sitai_adapter_fleet_supply_weight"
_VALUE_SOURCE = "common/script_values/sitai_adapter_values.txt"


@dataclass(frozen=True, slots=True)
class InitialValue:
    """只为已证明的缺省评分恢复锁定原版基值。"""

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

    def actions(self) -> tuple[SupplyProgram, ...]:
        if (
            not isinstance(self.goods, tuple)
            or not self.goods
            or len(set(self.goods)) != len(self.goods)
        ):
            raise ValueError("商品供给计划商品身份缺失或重复")
        return tuple(
            SupplyProgram(SupplyAction(self.source, good, self.price_threshold))
            for good in self.goods
        )


@dataclass(frozen=True, slots=True)
class AdapterSet:
    sources: tuple[tuple[str, str], ...]
    policies: tuple[tuple[str, decision_rules.RuleSet], ...]
    source_sha256: str
    initial_values: tuple[InitialValue, ...] = ()
    supply: SupplyPlan | None = None
    scalar_values: tuple[tuple[str, tuple[str, ...]], ...] = ()
    company_sectors_sha256: str | None = None
    law_opportunities_sha256: str | None = None
    technology_opportunities_sha256: str | None = None


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


def _merge_derivation(data: dict[str, Any], derived: Mapping[str, Any], label: str) -> None:
    """Merge one derivation without accepting a conflicting source or reader."""
    for collection in ("sources", "readers"):
        for key, value in derived[collection].items():
            if key in data[collection] and data[collection][key] != value:
                raise ValueError(f"{label}与消费者源冲突：{collection}/{key}")
            data[collection][key] = value
    data["rules"].extend(derived["rules"])


def load(source: Path = SOURCE, *, strategy: decision_intents.Strategy | None = None) -> AdapterSet:
    raw = source.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    if source == SOURCE and strategy is None:
        strategy = decision_intents.load()
    if set(data) - {"actors", "initial_values", "contexts", "supply", "scalar_values"} != {
        "schema",
        "sources",
        "domains",
        "readers",
        "rules",
    } or (type(data["schema"]) is not int or data["schema"] != 1):
        raise ValueError("消费者适配 schema 无效")
    sector_digest = None
    opportunity_digest = None
    equipment_digest = None
    treaty_digest = None
    treaty_fields = None
    mobilization_digest = None
    mobilization_fields = None
    law_digest = None
    technology_digest = None
    if source == SOURCE:
        if (
            not isinstance(data["sources"], dict)
            or not isinstance(data["readers"], dict)
            or not isinstance(data["rules"], list)
            or not isinstance(data.get("initial_values", []), list)
        ):
            raise ValueError("公司部门消费者源集合类型无效")
        # One source of sector semantics: the frozen, structurally verified
        # derivation. Loading it is not a claim about the current installation.
        sectors = company_sectors.load_baseline()
        derived = {
            "sources": {**sectors["sources"], **company_sectors.query_source_hashes(sectors)},
            "readers": sectors["readers"],
            "rules": sectors["rules"],
        }
        _merge_derivation(data, derived, "公司部门派生")
        data.setdefault("initial_values", []).extend(company_sectors.initialized_fields(sectors))
        sector_digest = hashlib.sha256(company_sectors.BASELINE.read_bytes()).hexdigest()
        opportunity = building_opportunities.derive(data, sectors)
        _merge_derivation(data, opportunity, "建筑基础机会")
        opportunity_digest = hashlib.sha256(
            building_opportunities.PARAMETERS.read_bytes()
            + b"\0generator:"
            + Path(building_opportunities.__file__).read_bytes()
        ).hexdigest()
        equipment = equipment_opportunities.derive(data)
        _merge_derivation(data, equipment, "舰船材料机会")
        equipment_digest = hashlib.sha256(
            equipment_opportunities.BASELINE.read_bytes()
            + b"\0parameters:"
            + equipment_opportunities.PARAMETERS.read_bytes()
            + b"\0generator:"
            + Path(equipment_opportunities.__file__).read_bytes()
        ).hexdigest()
        treaties = treaty_opportunities.derive(data)
        treaty_fields = {(row["source"], row["field"]) for row in treaties["covered"]}
        _merge_derivation(data, treaties, "条约实际承诺机会")
        treaty_digest = hashlib.sha256(
            treaty_opportunities.BASELINE.read_bytes()
            + b"\0parameters:"
            + treaty_opportunities.PARAMETERS.read_bytes()
            + b"\0generator:"
            + Path(treaty_opportunities.__file__).read_bytes()
        ).hexdigest()
        medical = mobilization_opportunities.derive(data)
        mobilization_fields = {(row["source"], row["field"]) for row in medical["covered"]}
        _merge_derivation(data, medical, "医疗动员实际投入机会")
        actor_bindings = data.setdefault("actors", {})
        if not isinstance(actor_bindings, dict):
            raise ValueError("医疗动员AI所有者必须是映射")
        for name, path in medical["actors"].items():
            if name in actor_bindings and actor_bindings[name] != path:
                raise ValueError("医疗动员AI所有者与编队原生ROOT冲突")
            actor_bindings[name] = path
        mobilization_digest = hashlib.sha256(
            mobilization_opportunities.BASELINE.read_bytes()
            + b"\0parameters:"
            + mobilization_opportunities.PARAMETERS.read_bytes()
            + b"\0generator:"
            + Path(mobilization_opportunities.__file__).read_bytes()
        ).hexdigest()
        laws = law_opportunities.derive(data)
        _merge_derivation(data, laws, "具体法律处境机会")
        law_digest = hashlib.sha256(
            law_opportunities.PARAMETERS.read_bytes()
            + b"\0generator:"
            + Path(law_opportunities.__file__).read_bytes()
        ).hexdigest()
        technologies = technology_opportunities.derive(data)
        _merge_derivation(data, technologies, "具体科技机制机会")
        technology_digest = hashlib.sha256(
            technology_opportunities.PARAMETERS.read_bytes()
            + b"\0generator:"
            + Path(technology_opportunities.__file__).read_bytes()
        ).hexdigest()
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
                "common/company_types/",
                "common/ship_modifications/",
                "common/treaty_articles/",
                "common/mobilization_options/",
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
    policies: list[tuple[str, decision_rules.RuleSet]] = []
    used_readers: set[str] = set()
    used_domains: set[str] = set()
    contexts = data.get("contexts", {})
    if not isinstance(contexts, dict):
        raise ValueError("共享约束必须是映射")
    used_contexts: set[str] = set()
    digest = hashlib.sha256(
        raw
        + (b"\0company_sectors:" + sector_digest.encode("ascii") if sector_digest else b"")
        + (
            b"\0building_opportunities:" + opportunity_digest.encode("ascii")
            if opportunity_digest
            else b""
        )
        + (
            b"\0equipment_opportunities:" + equipment_digest.encode("ascii")
            if equipment_digest
            else b""
        )
        + (b"\0treaty_opportunities:" + treaty_digest.encode("ascii") if treaty_digest else b"")
        + (b"\0law_opportunities:" + law_digest.encode("ascii") if law_digest else b"")
        + (
            b"\0technology_opportunities:" + technology_digest.encode("ascii")
            if technology_digest
            else b""
        )
        + (
            b"\0mobilization_opportunities:" + mobilization_digest.encode("ascii")
            if mobilization_digest
            else b""
        )
    ).hexdigest()
    for name, rules in sorted(groups.items()):
        mobilization = name.startswith("common/mobilization_options/")
        if mobilization:
            if mobilization_fields is None:
                mobilization_fields = {
                    (row["source"], row["field"])
                    for row in mobilization_opportunities.derive(data)["covered"]
                }
            if any(
                (name, rule["field"]) not in mobilization_fields or rule["operation"] != "multiply"
                for rule in rules
            ):
                raise ValueError("医疗动员只许可两项已冻结的精确编队权重块")
        if name.startswith("common/treaty_articles/"):
            if treaty_fields is None:
                treaty_fields = {
                    (row["source"], row["field"])
                    for row in treaty_opportunities.derive(data)["covered"]
                }
            if any(
                (name, rule["field"]) not in treaty_fields
                or rule["operation"] != "multiply"
                or len(rule["field"].split(".")) != 3
                or not rule["field"].endswith(".ai.proposal_weight")
                for rule in rules
            ):
                raise ValueError("条约适配只许可已核实的精确提议倍率块")
        if name.startswith("common/company_types/") and any(
            len(rule["field"].split(".")) != 2
            or not rule["field"].endswith(".ai_weight")
            or rule["operation"] != "multiply"
            for rule in rules
        ):
            raise ValueError("公司适配只许可已证明的正倍率基础候选评分字段")
        if name.startswith("common/ship_modifications/") and any(
            len(rule["field"].split(".")) != 2
            or not rule["field"].endswith(".ai_weight")
            or rule["operation"] != "multiply"
            for rule in rules
        ):
            raise ValueError("舰船改装适配只许可已证明的具名候选评分块")
        expected_actor = ["owner"] if name.startswith("common/buildings/") or mobilization else []
        if actors.get(name, []) != expected_actor:
            raise ValueError("消费者 AI 所有者与锁定接口作用域不一致")
        try:
            names = {name for rule in rules for name in rule.get("contexts", [])}
            selected_contexts = {name: contexts[name] for name in names}
            conditions = [condition for rule in rules for condition in rule["conditions"]]
            conditions.extend(
                condition for items in selected_contexts.values() for condition in items
            )
            if strategy is not None:
                for rule in rules:
                    if "intent" in rule:
                        intent = rule["intent"]
                        if not isinstance(intent, str):
                            raise ValueError("规则战略意图名称无效")
                        conditions.extend(strategy.expand(intent))
            readers = {condition["fact"] for condition in conditions}
            readers.update(key for rule in rules for key in rule.get("required_known_facts", []))
            readers.update(
                condition["value"]["fact"]
                for condition in conditions
                if isinstance(condition.get("value"), dict)
            )
            domains = {rule["domain"] for rule in rules}
            rule_set: decision_rules.RuleSet = decision_rules.from_data(
                {
                    "schema": 1,
                    "baseline_sha256": data["sources"][name],
                    "actor_path": actors.get(name, []),
                    "native_root": "military_formation"
                    if mobilization
                    else "state"
                    if expected_actor
                    else "country",
                    "readers": {key: data["readers"][key] for key in readers},
                    "domains": {key: data["domains"][key] for key in domains},
                    "rules": rules,
                    "contexts": selected_contexts,
                },
                source_sha256=digest,
                strategy=strategy,
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("消费者适配缺少类型化输入或开关") from exc
        policies.append((name, rule_set))
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
        company_default = (
            native_source == "common/company_types/99_basic_companies.txt"
            and define_source == "common/defines/00_ai.txt"
            and define == "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT"
        )
        allowed_defines = (
            {"NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT"}
            if company_default
            else {"NAI.PRODUCTION_BUILDING_BASE_VALUE", "NAI.GOVERNMENT_BUILDING_BASE_VALUE"}
        )
        if (
            not all(
                isinstance(value, str) for value in (native_source, field, define_source, define)
            )
            or native_source not in groups
            or not (native_source.startswith("common/buildings/") or company_default)
            or define_source not in data["sources"]
            or not define_source.startswith("common/defines/")
            or define not in allowed_defines
        ):
            raise ValueError("建筑缺省评分必须引用锁定的原版建筑与 defines")
        field_path = tuple(field.split("."))
        if (
            len(field_path) != 2
            or field_path[1] != ("ai_weight" if company_default else "ai_value")
            or (native_source, field_path) in seen_fields
        ):
            raise ValueError("建筑缺省评分路径无效或重复")
        if company_default:
            from .situated import engine_scope  # noqa: PLC0415

            proof = json.loads(engine_scope.company_default_snapshot())
            if field_path[0] not in {row["id"] for row in proof["implicit_companies"]}:
                raise ValueError("公司缺省评分不在精确引擎证据集合中")
        building_policy = dict(policies)[native_source]
        if field_path not in {rule.field for rule in building_policy.rules}:
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
        # 原版注释允许国家脚本值；实机拒绝内联任务权重，须生成具名引用。
        # 此处只放行已审计字段；动态求值与实际行动仍由用户在固定包上验收。
        fleet_scalar = source_name == _FLEET_SOURCE and scalar_path == _FLEET_FIELD
        if (
            not (building_scalar or fleet_scalar)
            or source_name not in groups
            or scalar_path not in {rule.field for rule in dict(policies)[source_name].rules}
            or (source_name, scalar_path) in scalar_values
            or (source_name, scalar_path) in seen_fields
        ):
            raise ValueError("建筑常量评分缺少唯一实际消费者")
        scalar_values.append((source_name, scalar_path))
    # Joint consumers retain both directions. Priority only breaks ties within
    # one cause/strength, so it cannot serve as an input-vs-output veto chain.
    for source_name, loaded_set in policies:
        for loaded_rule in loaded_set.rules:
            is_cost = loaded_rule.id.startswith("actual_cost_")
            is_output = loaded_rule.id.startswith("actual_output_")
            if (is_cost or is_output) and (
                loaded_rule.operation != "multiply"
                or (is_cost and loaded_rule.value >= 1)
                or (is_output and loaded_rule.value <= 1)
            ):
                raise ValueError(f"实际投入/产出贡献方向错误：{source_name}/{loaded_rule.id}")
    adapters = AdapterSet(
        tuple(sorted(data["sources"].items())),
        tuple(policies),
        digest,
        tuple(initial_values),
        supply,
        tuple(sorted(scalar_values)),
        sector_digest,
        law_digest,
        technology_digest,
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


def _externalize_fleet_value(text: str) -> tuple[str, str]:
    """只移动已登记的完整值块，保留条件、优先级、基值及所有外围字节。"""
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    stack: list[str] = []
    previous = before_previous = None
    opening = None
    spans = []
    for token in tokenize(text):
        if token.kind == LBRACE:
            key = (
                before_previous.value
                if previous is not None
                and previous.kind == OP
                and before_previous is not None
                and before_previous.kind == ATOM
                else "<anonymous>"
            )
            stack.append(key)
            if tuple(stack) == _FLEET_FIELD:
                opening = starts[token.line - 1] + token.col - 1
        elif token.kind == RBRACE:
            if tuple(stack) == _FLEET_FIELD and opening is not None:
                spans.append((opening, starts[token.line - 1] + token.col))
            stack.pop()
        before_previous, previous = previous, token
    if len(spans) != 1:
        raise ValueError("舰队具名评分缺少唯一完整值块")
    start, end = spans[0]
    return text[:start] + _FLEET_VALUE + text[end:], f"{_FLEET_VALUE} = {text[start:end]}\n"


def _supply_patch(
    text: str,
    plan: SupplyPlan,
    inputs: Mapping[str, str],
    words: frozenset[str],
    programs: tuple[SupplyProgram, ...],
) -> str:
    """保留已有商品立场与资格，只追加缺省的、按市场稀缺激活的立场。"""
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("供给计划原件无法解析")
    strategy = parsed.root.first("ai_strategy_default")
    if (
        len(parsed.root.all("ai_strategy_default")) != 1
        or strategy is None
        or not isinstance(strategy.value, Block)
    ):
        raise ValueError("供给计划缺少默认策略")
    goods_stances = strategy.value.first("goods_stances")
    if (
        len(strategy.value.all("goods_stances")) != 1
        or goods_stances is None
        or not isinstance(goods_stances.value, Block)
    ):
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
    rows.extend(program.render() for program in programs)
    rows.append("\t\t# SITAI END supply:goods_stances\n\t")
    result = text[:position] + "".join(rows) + text[position:]
    if parse_text(result).errors:
        raise ValueError("商品供给计划产物无法解析")
    return result


def _supply_programs(
    plan: SupplyPlan | None, bundle: ConsumerIRBundle | None, *, enabled: bool
) -> tuple[SupplyProgram, ...]:
    expected = plan.actions() if plan is not None else ()
    if bundle is None:
        return expected if enabled else ()
    bundle.validate_chain_refs()
    rows = [writer for writer in bundle.writers if writer.kind == "supply_program"]
    programs = tuple(writer.validate_supply_program() for writer in rows)
    if any(
        writer.supply_program is not None and writer.kind != "supply_program"
        for writer in bundle.writers
    ):
        raise ValueError("非供给writer不能携带供给程序")
    if len({program.good for program in programs}) != len(programs):
        raise ValueError("供给枚举writer重复")
    if enabled and {program.good: program for program in programs} != {
        program.good: program for program in expected
    }:
        raise ValueError("供给计划与冻结ConsumerIR完整程序不一致")
    if not enabled:
        # A build may narrow an enabled bundle to a disabled domain.  Any
        # retained configured rows must still be exact; no row is emitted.
        if programs and {program.good: program for program in programs} != {
            program.good: program for program in expected
        }:
            raise ValueError("关闭的供给计划与冻结ConsumerIR不一致")
        return ()
    by_good = {program.good: program for program in programs}
    return tuple(by_good[program.good] for program in expected)


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
        if item.source.startswith("common/company_types/"):
            from .situated import engine_scope  # noqa: PLC0415

            proof = json.loads(engine_scope.company_default_snapshot())
            allowed = {row["id"]: row["line"] for row in proof["implicit_companies"]}
            if (
                item.source != "common/company_types/99_basic_companies.txt"
                or item.field[1] != "ai_weight"
                or item.define != ("NAI", "COMPANY_TYPE_DEFAULT_BASE_WEIGHT")
                or item.define_source != "common/defines/00_ai.txt"
                or allowed.get(item.field[0]) != parent.line
                or parent.op != "="
                or parent.prefix is not None
            ):
                raise ValueError("公司缺省评分偏离精确原版字段与初始化证据")
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
        if item.source.startswith("common/company_types/") and value != "1":
            raise ValueError("公司缺省评分必须保留已证明的原版常量1")
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
            f"\t{path[1]} = {{ value = {value} }}\n"
            f"\t# SITAI END initialized:{key}\n"
        )
        text = text[:position] + fragment + text[position:]
    return text


def read_inputs(
    adapters: AdapterSet, *, game: Path | None = None, texts: Mapping[str, str] | None = None
) -> dict[str, str]:
    """读取并核对全部锁定原件，供跨生产生成器共享同一证据合同。"""
    game = config.GAME if game is None else game
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
    return inputs


def reader_evidence(inputs: Mapping[str, str]) -> dict[str, dict[str, object]]:
    """只索引调用方已核对的锁定输入；一次词法扫描同时定位静态依据。"""
    evidence: dict[str, dict[str, object]] = {}
    for name, text in inputs.items():
        for token in tokenize(text):
            if token.kind == ATOM and token.value not in evidence:
                evidence[token.value] = {"source": name, "line": token.line}
    return evidence


def build(
    adapters: AdapterSet,
    *,
    game: Path | None = None,
    texts: Mapping[str, str] | None = None,
    enabled_domains: frozenset[str] | None = None,
    overlays: Mapping[str, str] | None = None,
    country_policy: CountryPolicy | None = None,
    owned_triggers: frozenset[str] | set[str] | None = None,
    consumer_ir: ConsumerIRBundle | None = None,
) -> tuple[dict[str, str], dict[str, object]]:
    """全输入预检后生成；合成测试可显式注入文本，生产默认读取 config.GAME。"""
    known_domains = {rule.domain for _, policy in adapters.policies for rule in policy.rules}
    if enabled_domains is not None and enabled_domains - known_domains:
        raise ValueError("消费者适配含未知领域开关")
    owners = writes(adapters, enabled_domains)
    inputs = read_inputs(adapters, game=game, texts=texts)
    if adapters.company_sectors_sha256 is not None:
        company_sectors.verify_baseline(inputs)
    if adapters.law_opportunities_sha256 is not None:
        law_opportunities.verify_inputs(inputs)
    if adapters.technology_opportunities_sha256 is not None:
        technology_opportunities.verify_inputs(inputs)
    # 一次词法扫描同时建立校验集合与原件定位，避免逐读取器反复扫描大文件。
    evidence = reader_evidence(inputs)
    words = frozenset(evidence)
    files = {}
    contracts = []
    initialized = []
    required_engines: set[str] = set()
    active_methods: set[tuple[str, str]] = set()
    definitions_cache: dict[str, Block] = {}
    query_evidence = {}
    consumption_evidence = False
    named_fleet = False
    for name, policy in adapters.policies:
        selected = (
            policy.enabled_domains
            if enabled_domains is None
            else (enabled_domains & {rule.domain for rule in policy.rules})
        )
        if not selected:
            continue
        for reader in policy.readers:
            if reader.engine == "market_goods_consumption" and not consumption_evidence:
                observation_queries.verify_market_consumption_sources(inputs)
                consumption_evidence = True
            if reader.engine in observation_queries.QUERY_ENGINES:
                query = observation_queries.from_reader(reader.engine, dict(reader.parameters))
                if query not in query_evidence:
                    query_evidence[query] = observation_queries.compile_query(query, inputs)
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
            country_policy=country_policy,
            owned_triggers=owned_triggers,
            consumer_ir=consumer_ir,
            consumer_source=name,
        )
        if name == _FLEET_SOURCE and _FLEET_FIELD in scalar_fields:
            if _FLEET_VALUE in words or _VALUE_SOURCE in (overlays or {}):
                raise ValueError("舰队具名评分与已有定义冲突")
            files[name], files[_VALUE_SOURCE] = _externalize_fleet_value(files[name])
            named_fleet = True
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
                    replace(policy, enabled_domains=selected),
                    owner="consumer_adapters",
                    source=name,
                ),
            }
        )
    supply = adapters.supply
    supply_enabled = supply is not None and (
        any("market" in policy.enabled_domains for _, policy in adapters.policies)
        if enabled_domains is None
        else "market" in enabled_domains
    )
    supply_programs = _supply_programs(supply, consumer_ir, enabled=supply_enabled)
    if supply is not None and supply_enabled:
        text = files.get(supply.source, (overlays or {}).get(supply.source, inputs[supply.source]))
        files[supply.source] = _supply_patch(text, supply, inputs, words, supply_programs)
    return files, {
        "schema": 1,
        "evidence": "source_locked_generated_consumer_patches",
        "behavior_verified": False,
        "source_sha256": adapters.source_sha256,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "supply_program_generator_sha256": hashlib.sha256(
            Path(supply_program.__file__).read_bytes()
        ).hexdigest(),
        "production_inputs_generator_sha256": hashlib.sha256(
            Path(production_inputs.__file__).read_bytes()
        ).hexdigest(),
        "sources": dict(adapters.sources),
        "field_owners": [
            {"source": source, "field": ".".join(field), "owner": owner}
            for source, field, owner in owners
        ],
        "reader_evidence": {
            engine: evidence[engine]
            for engine in sorted(required_engines)
            if not engine.startswith("sitai_context_")
        },
        "generated_reader_evidence": {
            engine: {
                "source": "mod/decisions/country_state.toml",
                "generator": "src/pdx/country_coordination.py",
                "contract": "owned_country_boolean_trigger",
            }
            for engine in sorted(required_engines)
            if engine.startswith("sitai_context_")
        },
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
                **(
                    {
                        "operation": "retain_native_constant_in_named_value",
                        "value_source": _VALUE_SOURCE,
                        "value_name": _FLEET_VALUE,
                        "runtime_evaluation_verified": False,
                    }
                    if named_fleet and source == _FLEET_SOURCE and field == _FLEET_FIELD
                    else {}
                ),
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
            "consumer_programs": [program.as_dict() for program in supply_programs],
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
