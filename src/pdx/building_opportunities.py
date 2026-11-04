"""Basic construction opportunities from the existing verified company recipes.

This module grants no missing consumer. Within each mandatory output group,
only an ordinary good shared by every PM is eligible for market inference.
The result is a recipe opportunity, never proof of the current local output,
profitability, resources, technology or vanilla construction eligibility.
Observed default and local infrastructure deficits add independent preference
costs. These static adjustments neither pay nor reserve construction resources.
When mandatory alternatives have different market outputs, an independently
registered exact active-method reader can identify a low-tier local opportunity;
the potential output union alone never licenses such a rule.
Explicitly registered power/rail consumers additionally use same-state local
goods prices; exact observed PMs and actual inputs only refine readiness/costs.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from . import company_sectors, config

if TYPE_CHECKING:
    from pathlib import Path

PARAMETERS = config.REPO / "mod/decisions/building_opportunities.toml"
_KEYS = frozenset(
    {
        "priority_base",
        "shortage_balance",
        "output_price_threshold",
        "demand_multiplier",
        "pressure_multiplier",
        "default_multiplier",
        "infrastructure_multiplier",
    }
)
_FIELD = re.compile(r"([a-z][a-z0-9_]*)\.ai_value\Z")


def _parameters(values: Mapping[str, object]) -> dict[str, float]:
    if set(values) != _KEYS:
        raise ValueError("建筑基础机会参数键无效")
    result: dict[str, float] = {}
    for key, value in values.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError("建筑基础机会参数必须是有限数字")
        result[key] = float(value)
    if not result["priority_base"].is_integer() or not 80000 <= result["priority_base"] <= 1000000:
        raise ValueError("建筑基础机会优先级必须为独立高段整数")
    if result["shortage_balance"] != 0:
        raise ValueError("建筑基础机会缺口必须保持sell-minus-buy零边界")
    if not 0 < result["output_price_threshold"] <= 0.75:
        raise ValueError("建筑基础机会高价阈值必须在(0,.75]内")
    if not 1 < result["demand_multiplier"] < result["pressure_multiplier"] <= 1.5:
        raise ValueError("建筑基础机会倍率必须为正向有序有界档位")
    if not all(
        0.5 <= result[key] < 1 for key in ("default_multiplier", "infrastructure_multiplier")
    ):
        raise ValueError("建筑基础机会成本必须为正倍率与负贡献")
    if result["default_multiplier"] + result["infrastructure_multiplier"] - 1 < 0.5:
        raise ValueError("建筑基础机会联合成本超出有界下限")
    return dict(sorted(result.items()))


def load_parameters(path: Path = PARAMETERS) -> dict[str, float]:
    """Read the sole adjustable parameter source; never write generated output."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "parameters"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or not isinstance(data["parameters"], dict)
    ):
        raise ValueError("建筑基础机会参数schema无效")
    return _parameters(data["parameters"])


def _reader(good: str, tier: str) -> dict[str, Any]:
    balance = tier == "balance"
    return {
        "engine": "market_goods_delta" if balance else "market_goods_pricier",
        "scope": "root",
        "kind": "number",
        "unit": "sell_minus_buy_orders" if balance else "price_above_base_ratio",
        "path": ["owner", "market", f"mg:{good}"],
    }


def _buildings(baseline: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    # Reuse the baseline's existing structural/identity contract instead of
    # maintaining another parser, inventory, freeze format or validation copy.
    try:
        company_sectors._validate_runtime(dict(baseline))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("建筑基础机会底本结构无效") from exc
    buildings: dict[str, dict[str, Any]] = {}
    for profile in baseline["profiles"].values():
        for sector in profile["base_recipes"]:
            identity = sector["id"]
            if not sector["source"].startswith("common/buildings/") or (
                identity in buildings and buildings[identity] != sector
            ):
                raise ValueError("建筑基础机会底本定义身份冲突")
            buildings[identity] = sector
    return buildings


def _outputs(sector: Mapping[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    common: set[str] = set()
    group_ids: set[str] = set()
    for group in sector["groups"]:
        if group["id"] in group_ids or len({pm["id"] for pm in group["methods"]}) != len(
            group["methods"]
        ):
            raise ValueError("建筑基础机会PMG或PM定义重复")
        group_ids.add(group["id"])
        if group["base"]:
            shared = set(group["methods"][0]["outputs"])
            for method in group["methods"][1:]:
                shared.intersection_update(method["outputs"])
            common.update(shared)
    market = common & set(sector["market_outputs"])
    reasons: list[dict[str, Any]] = []
    special = common - market
    if special:
        reasons.append(
            {"reason": "non_market_output_requires_native_evidence", "goods": sorted(special)}
        )
    optional = set(sector["potential_outputs"]) - common
    if optional:
        reasons.append({"reason": "optional_or_method_specific_output", "goods": sorted(optional)})
    if not common:
        reason = (
            "no_common_output_across_base_methods"
            if any(group["base"] for group in sector["groups"])
            else "no_mandatory_output_recipe_group"
        )
        reasons.append({"reason": reason, "goods": []})
    return sorted(market), reasons


def _conditional_outputs(
    sector: Mapping[str, Any], old_readers: Mapping[str, Any]
) -> list[tuple[str, str, str]]:
    """Observe an existing mandatory method; never guess a new building's PM."""
    result: list[tuple[str, str, str]] = []
    for group in sector["groups"]:
        if not group["base"]:
            continue
        for method in group["methods"]:
            key = f"pm_active_{sector['id']}_{method['id']}"
            if key not in old_readers:
                continue
            expected = {
                "engine": "is_production_method_active",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "parameters": {"building_type": sector["id"], "production_method": method["id"]},
            }
            if old_readers[key] != expected:
                raise ValueError("建筑方法机会的active PM reader身份漂移")
            result.extend(
                (method["id"], key, good)
                for good in sorted(set(method["outputs"]) & set(sector["market_outputs"]))
            )
    return result


def employment_lower_bound(sector: Mapping[str, Any]) -> float:
    """Worst independent PMG combination of laborer slots, never actual hiring.

    Include automation, luxury and ownership groups, even when they are not
    base-output groups. Negative employment deltas are genuine offsets.
    """
    return math.fsum(
        min(
            math.fsum(
                float(m["value"])
                for m in method["modifiers"]
                if m["key"] == "building_employment_laborers_add"
            )
            for method in group["methods"]
        )
        for group in sector["groups"]
    )


def derive(
    adapters: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Return mergeable rules/readers and explicit covered/uncovered facets.

    ``adapters`` is the raw existing consumer declaration. The default baseline
    is loaded through ``company_sectors.load_baseline``; callers supplying an
    explicit baseline must use that same runtime format. Existing production
    source verification remains responsible for comparing frozen recipes with
    the locked native files. No default ``ai_value`` is created here.
    """
    chosen = load_parameters() if parameters is None else _parameters(parameters)
    frozen = company_sectors.load_baseline() if baseline is None else baseline
    buildings = _buildings(frozen)
    sources, old_readers, old_rules = (
        adapters.get("sources"),
        adapters.get("readers"),
        adapters.get("rules"),
    )
    if (
        not isinstance(sources, Mapping)
        or not isinstance(old_readers, Mapping)
        or not isinstance(old_rules, list)
    ):
        raise ValueError("建筑基础机会需已有消费者源、reader和规则集合")
    fields: dict[str, str] = {}
    for row in old_rules:
        if not isinstance(row, Mapping):
            raise ValueError("建筑基础机会消费者规则必须是记录")
        source, field = row.get("source"), row.get("field")
        if not isinstance(source, str) or not source.startswith("common/buildings/"):
            continue
        if not isinstance(field, str) or (match := _FIELD.fullmatch(field)) is None:
            raise ValueError("建筑基础机会只接受已登记ai_value消费者")
        if (
            source not in sources
            or source not in frozen["sources"]
            or sources[source] != frozen["sources"][source]
        ):
            raise ValueError("建筑基础机会消费者原件来源或哈希漂移")
        if field in fields and fields[field] != source:
            raise ValueError("建筑基础机会消费者定义重复或来源漂移")
        fields[field] = source
        sector = buildings.get(match[1])
        if sector is not None and sector["source"] != source:
            raise ValueError("建筑基础机会消费者与底本定义来源不一致")
    readers: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    covered: list[dict[str, Any]] = []
    conditional_covered: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    cost_readers: dict[str, dict[str, Any]] = {
        "state_owner_default": {
            "engine": "in_default",
            "scope": "root",
            "unit": "boolean",
            "kind": "boolean",
            "path": ["owner"],
        },
        "state_infrastructure": {
            "engine": "infrastructure_delta",
            "scope": "root",
            "unit": "infrastructure_points",
            "kind": "number",
        },
    }
    for field, source in sorted(fields.items()):
        building = field.split(".")[0]
        identity = {"building": building, "source": source, "field": field}
        sector = buildings.get(building)
        if (
            building == "building_textile_mill"
            and sector is not None
            and employment_lower_bound(sector) <= 0
        ):
            raise ValueError("纺织完整PMG组合缺少正劳动就业下界")
        if sector is None:
            uncovered.append(
                {**identity, "reason": "missing_verified_building_recipe", "goods": []}
            )
            continue
        goods, reasons = _outputs(sector)
        uncovered.extend({**identity, **reason} for reason in reasons)
        if goods:
            covered.append({**identity, "goods": goods})
        # Ordinary shared outputs already have an ungated basic tier. For a
        # varying mandatory output, bind only to an exact existing PM reader.
        # No source, default field, technology or active recipe is invented.
        conditional = _conditional_outputs(sector, old_readers) if not goods else []
        for method, fact, good in conditional:
            balance_key = f"state_owner_{good}_balance"
            expected = _reader(good, "balance")
            if balance_key in old_readers and old_readers[balance_key] != expected:
                raise ValueError("建筑方法机会state-owner reader身份漂移")
            readers[balance_key] = expected
            readers[fact] = old_readers[fact]
            rules.append(
                {
                    "id": f"building_method_opportunity_{building}_{method}_{good}",
                    "source": source,
                    "field": field,
                    "domain": "market",
                    "operation": "multiply",
                    "value": chosen["demand_multiplier"],
                    "priority": int(chosen["priority_base"]) + len(rules),
                    "contribution_group": "building_output_demand",
                    "conditions": [
                        {"fact": fact, "op": "=", "value": True},
                        {"fact": balance_key, "op": "<", "value": 0.0},
                    ],
                    "why": f"本州已存在建筑实际启用{method}且其真实{good}产出短缺；基础需求不以财政物流与投入全满足为前提",
                    "counterexample": "缺失或未知PM不推定新建配方；候选获分不代表建设或供给完成，独立成本与原版资格、费用、玩家和尾部保留",
                }
            )
            conditional_covered.append({**identity, "method": method, "good": good, "reader": fact})
        for good in goods:
            for tier in ("balance", "price"):
                key = f"state_owner_{good}_{tier}"
                expected = _reader(good, tier)
                if key in old_readers and old_readers[key] != expected:
                    raise ValueError("建筑基础机会state-owner reader身份漂移")
                readers[key] = expected
            balance = {"fact": f"state_owner_{good}_balance", "op": "<", "value": 0.0}
            for tier, conditions in (
                ("demand", [balance]),
                (
                    "pressure",
                    [
                        balance,
                        {
                            "fact": f"state_owner_{good}_price",
                            "op": ">",
                            "value": chosen["output_price_threshold"],
                        },
                    ],
                ),
            ):
                rules.append(
                    {
                        "id": f"building_opportunity_{building}_{good}_{tier}",
                        "source": source,
                        "field": field,
                        "domain": "market",
                        "operation": "multiply",
                        "value": chosen[f"{tier}_multiplier"],
                        "priority": int(chosen["priority_base"]) + len(rules),
                        "contribution_group": "building_output_demand",
                        "conditions": conditions,
                        "why": f"必选基础PMG全部方法共同正产出{good}；所有者市场缺口为基础机会，高价只升档同一需求",
                        "counterexample": "配方机会不是active PM或当前产出；未知局部退出，饱和退出，保留原版资格、实际成本、玩家与尾部",
                    }
                )
        if goods or conditional:
            for name, fact, op, value, group, why in (
                (
                    "default",
                    "state_owner_default",
                    "=",
                    True,
                    "building_financing_pressure",
                    "所有者已实际违约，增加建设筹资压力；正常借款不触发，不是实际付款或资源预留",
                ),
                (
                    "infrastructure",
                    "state_infrastructure",
                    "<",
                    0.0,
                    "building_infrastructure_pressure",
                    "候选州基础设施余额为负，增加建设承载压力；静态偏好代价不改变原版费用或资格",
                ),
            ):
                expected = cost_readers[fact]
                if fact in old_readers and old_readers[fact] != expected:
                    raise ValueError("建筑基础机会成本reader身份漂移")
                readers[fact] = expected
                rules.append(
                    {
                        "id": f"building_opportunity_{building}_{name}_cost",
                        "source": source,
                        "field": field,
                        "domain": "market",
                        "operation": "multiply",
                        "value": chosen[f"{name}_multiplier"],
                        "priority": int(chosen["priority_base"]) + len(rules),
                        "contribution_group": group,
                        "conditions": [{"fact": fact, "op": op, "value": value}],
                        "why": why,
                        "counterexample": "该成本未知只撤回本项，不声称财政或承载健康；需求与其他已知成本继续联合，保留玩家与关闭路径",
                    }
                )
    # Local goods have a separate audited state-goods price contract. They do
    # not enter the ordinary-market output inference above, and this path only
    # extends explicitly registered native consumers.
    for building, good in (
        ("building_power_plant", "electricity"),
        ("building_railway", "transportation"),
    ):
        field = f"{building}.ai_value"
        if field not in fields:
            continue
        sector = buildings[building]
        methods = [m for g in sector["groups"] if g["base"] for m in g["methods"]]
        if not methods or any(good not in m["outputs"] for m in methods):
            raise ValueError("本地供给机会缺少完整基础PMG共同产出证据")
        price_key = f"state_local_{good}_price"
        readers[price_key] = {
            "engine": "state_goods_pricier",
            "scope": "root",
            "kind": "number",
            "unit": "price_above_base_ratio",
            "path": [f"sg:{good}"],
        }

        def local_rule(
            suffix,
            value,
            conditions,
            group="building_local_goods_demand",
            *,
            building=building,
            field=field,
        ):
            rules.append(
                {
                    "id": f"building_local_{building}_{suffix}".replace("-", "_"),
                    "source": fields[field],
                    "field": field,
                    "domain": "market",
                    "operation": "multiply",
                    "value": value,
                    "priority": int(chosen["priority_base"]) + len(rules),
                    "contribution_group": group,
                    "conditions": conditions,
                    "why": "同州本地商品价格压力构成供给机会；精确实际PM与真实投入仅升准备档，独立材料成本联合",
                    "counterexample": "未知仅退出对应分量；不推断未来PM、订单或利润，原版首座引导、资格、成本、玩家和尾部保留",
                }
            )

        demand = {"fact": price_key, "op": ">", "value": 0.25}
        local_rule("demand", 1.1, [demand])
        local_rule("pressure", 1.15, [{"fact": price_key, "op": ">", "value": 0.5}])
        for method in methods:
            pm_key = f"pm_active_{building}_{method['id']}".replace("-", "_")
            readers[pm_key] = {
                "engine": "is_production_method_active",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "parameters": {"building_type": building, "production_method": method["id"]},
            }
            active = {"fact": pm_key, "op": "=", "value": True}
            ready = [demand, active]
            for material in method["inputs"]:
                if material == "electricity":
                    key = "state_electricity_price"
                    expected = {
                        "engine": "state_goods_pricier",
                        "scope": "root",
                        "kind": "number",
                        "unit": "price_above_base_ratio",
                        "path": ["sg:electricity"],
                    }
                    readers[key] = expected
                    ready.append({"fact": key, "op": "<=", "value": 0.25})
                    continue
                for tier in ("balance", "price"):
                    key = f"state_owner_{material}_{tier}"
                    expected = _reader(material, tier)
                    if key in old_readers and old_readers[key] != expected:
                        raise ValueError("本地供给投入reader身份漂移")
                    readers[key] = expected
                    ready.append(
                        {
                            "fact": key,
                            "op": ">=" if tier == "balance" else "<=",
                            "value": 0 if tier == "balance" else 0.25,
                        }
                    )
                # Railway already owns these exact material-cost groups.
                if building == "building_power_plant":
                    local_rule(
                        f"{method['id']}_{material}_cost",
                        0.9,
                        [
                            active,
                            {"fact": f"state_owner_{material}_balance", "op": "<", "value": 0},
                            {"fact": f"state_owner_{material}_price", "op": ">", "value": 0.5},
                        ],
                        f"building_active_input_{material}",
                    )
            # Principle variants retain their existing infrastructure-ready
            # and exact cost rules. Avoid duplicating that auxiliary readiness
            # across this additional local demand; basic/pressure tiers cover
            # every variant and leave room for the recovery refinement.
            if not method["id"].endswith("_principle_transport_3"):
                local_rule(f"{method['id']}_ready", 1.2, ready)
    return {
        "sources": dict(frozen["sources"]),
        "readers": dict(sorted(readers.items())),
        "rules": rules,
        "covered": covered,
        "conditional_covered": conditional_covered,
        "uncovered": uncovered,
    }
