"""Derive company sector opportunities from locked vanilla definitions only.

This module reads no game state and grants no engine getters. A base PM group
has positive goods output in every alternative. Groups containing a disabled or
output-free alternative remain possible opportunities, never mandatory recipes.
Recipe possibilities are not observations of active PMs or current employment.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from . import company_observations, config, version_contracts
from .model import Assignment, Block, Scalar
from .parser import parse_text
from .situated import engine_scope
from .textio import normalized_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/company_sectors.toml"
BASELINE = config.REPO / "research/situated/company-sector-baseline.json"
BASELINE_115 = config.REPO / "research/situated/1.15.0/company-sector-baseline.json"
_BASELINE_115_SHA256 = "27b6284aff73c30ac5a4223a090fac6ec66aa85b333a1ca5ddba31941e979219"
_BUILDER_115_SHA256 = "0cfd52f1b7559e96b3f914ad31268b3c02ff2a1cf83730ae7bfc2985b4d4cf07"
_FAMILIES = frozenset(
    {
        "company_types",
        "buildings",
        "production_method_groups",
        "production_methods",
        "goods",
        "defines",
    }
)
_KEYS = frozenset(
    {
        "priority_base",
        "shortage_balance",
        "output_price_threshold",
        "input_price_threshold",
        "laborers_share_threshold",
        "demand_multiplier",
        "pressure_multiplier",
        "input_multiplier",
        "workforce_multiplier",
        "default_multiplier",
        "outer_lower",
        "outer_upper",
    }
)
_GOOD = re.compile(r"goods_(input|output)_([a-z_]+)_add\Z")
_JOB = re.compile(r"building_employment_([a-z_]+)_add\Z")


def baseline_path() -> Path:
    return (
        version_contracts.research_path("situated", BASELINE_115.name)
        if version_contracts.active_version() == "1.15.1"
        else BASELINE_115
        if version_contracts.is_115()
        else BASELINE
    )


def _parameters(values: Mapping[str, object]) -> dict[str, float]:
    if set(values) != _KEYS:
        raise ValueError("公司部门参数键必须完整且唯一")
    result = {}
    for key, value in values.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError(f"公司部门参数必须是有限数字：{key}")
        result[key] = float(value)
    if result["shortage_balance"] != 0:
        raise ValueError("公司部门短缺必须保持 sell-minus-buy 的零边界")
    if not result["priority_base"].is_integer() or not 50000 <= result["priority_base"] <= 1000000:
        raise ValueError("公司部门优先级基址必须为独立高段整数")
    for key in ("output_price_threshold", "input_price_threshold"):
        if not 0 < result[key] <= 0.75:
            raise ValueError("公司部门价格阈值必须在 (0,.75] 内")
    if not 0 < result["laborers_share_threshold"] <= 1:
        raise ValueError("公司部门劳工比例阈值必须在 (0,1] 内")
    if not 1 < result["demand_multiplier"] <= result["pressure_multiplier"] <= 1.5:
        raise ValueError("公司部门需求档必须有序且有界")
    if not 1 < result["workforce_multiplier"] <= 1.5:
        raise ValueError("公司部门就业结构贡献必须为正且有界")
    if not all(0.5 <= result[key] < 1 for key in ("input_multiplier", "default_multiplier")):
        raise ValueError("公司部门投入和违约代价必须保持正倍率与负贡献")
    if not 0.5 <= result["outer_lower"] < 1 < result["outer_upper"] <= 1.5:
        raise ValueError("公司部门外限必须包含中性倍率且有界")
    # These source parameters bound individual contribution tiers, not the
    # aggregate company program. The number of independently required goods is
    # profile-specific; programs.enable owns its single final [.5, 1.5] clamp.
    lower = min(result["input_multiplier"], result["default_multiplier"])
    upper = max(result["pressure_multiplier"], result["workforce_multiplier"])
    if lower < result["outer_lower"] or upper > result["outer_upper"]:
        raise ValueError("公司部门单项贡献档位超出源参数允许范围")
    return dict(sorted(result.items()))


def load_parameters(path: Path = PARAMETERS) -> dict[str, float]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "parameters"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or not isinstance(data["parameters"], dict)
    ):
        raise ValueError("公司部门参数 schema 无效")
    return _parameters(data["parameters"])


DEFAULTS = load_parameters()


def _family(source: str) -> str | None:
    path = PurePosixPath(source)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != source
        or "\\" in source
        or ":" in source
    ):
        raise ValueError("公司部门原件路径无效")
    if path.suffix != ".txt":
        return None
    parts = path.parts
    for index, part in enumerate(parts[:-2]):
        if part == "common" and parts[index + 1] in _FAMILIES and index + 3 == len(parts):
            return parts[index + 1]
    return None


def _one(block: Block, key: str, *, required: bool = False) -> Assignment | None:
    items = block.all(key)
    if len(items) > 1 or (required and not items):
        raise ValueError(f"公司部门引用字段缺失或重复：{key}")
    return items[0] if items else None


def _list(block: Block, key: str, *, required: bool = False) -> tuple[str, ...]:
    item = _one(block, key, required=required)
    if item is None:
        return ()
    if not isinstance(item.value, Block) or any(
        not isinstance(value, Scalar) for value in item.value.items
    ):
        raise ValueError(f"公司部门引用必须是标识符列表：{key}")
    values = tuple(value.unquoted for value in item.value.scalars())
    if len(values) != len(set(values)) or (required and not values):
        raise ValueError(f"公司部门引用为空或重复：{key}")
    return values


def _definitions(inputs: Mapping[str, str]):
    indices: dict[str, dict[str, tuple[str, Assignment]]] = {family: {} for family in _FAMILIES}
    sources = {}
    for source, text in sorted(inputs.items()):
        family = _family(source)
        if family is None:
            continue
        if not isinstance(text, str):
            raise ValueError("公司部门输入必须是文本")
        normalized = normalized_text(text)
        sources[source] = hashlib.sha256(normalized.encode()).hexdigest()
        parsed = parse_text(normalized, path=source)
        if parsed.errors:
            raise ValueError(f"公司部门原件解析失败：{source}")
        for item in parsed.root.items:
            if not isinstance(item, Assignment):
                raise ValueError(f"公司部门顶层必须是普通定义：{source}")
            if item.is_variable:
                continue
            if family == "defines":
                if item.prefix is not None or item.op != "=" or not isinstance(item.value, Block):
                    raise ValueError(f"公司部门defines必须是普通命名空间：{source}:{item.key}")
                # Vanilla legitimately repeats namespace containers across
                # files. Only the exact consumed constant must have one author.
                for constant in item.value.assignments():
                    if item.key == "NAI" and constant.key == "COMPANY_TYPE_DEFAULT_BASE_WEIGHT":
                        identity = f"{item.key}.{constant.key}"
                        if (
                            identity in indices[family]
                            or constant.prefix is not None
                            or constant.op != "="
                        ):
                            raise ValueError("公司部门缺省评分define重复或不是普通赋值")
                        indices[family][identity] = (source, constant)
                continue
            if (
                item.prefix is not None
                or item.op != "="
                or not isinstance(item.value, Block)
                or item.key in indices[family]
            ):
                raise ValueError(f"公司部门定义不唯一或不是普通块：{source}:{item.key}")
            indices[family][item.key] = (source, item)
    if any(not indices[family] for family in _FAMILIES):
        raise ValueError("公司部门输入缺少公司/建筑/PMG/PM/商品/defines 原件")
    return indices, sources


def _reference(indices, family, key):
    try:
        return indices[family][key]
    except KeyError as exc:
        raise ValueError(f"公司部门原件缺少引用：{family}:{key}") from exc


def _modifiers(block: Block, prefix: tuple[str, ...] = ()):
    seen = set()
    if any(not isinstance(item, Assignment) for item in block.items):
        raise ValueError("公司部门配方修饰器必须为普通赋值")
    for item in block.assignments():
        if item.prefix is not None or item.op != "=" or item.key in seen:
            raise ValueError("公司部门配方修饰器重复或不是普通赋值")
        seen.add(item.key)
        if isinstance(item.value, Block):
            if item.key not in {"workforce_scaled", "level_scaled", "unscaled"}:
                raise ValueError("公司部门未知配方缩放块；不能当无条件产出")
            yield from _modifiers(item.value, (*prefix, item.key))
        elif _GOOD.fullmatch(item.key) or _JOB.fullmatch(item.key):
            if not isinstance(item.value, Scalar):
                raise ValueError("公司部门配方必须为数字常量")
            try:
                value = float(item.value.unquoted)
            except ValueError as exc:
                raise ValueError("公司部门配方必须为数字常量") from exc
            if not math.isfinite(value):
                raise ValueError("公司部门配方不能是非有限数字")
            yield {"key": item.key, "value": value, "scaling": list(prefix), "line": item.line}


def _recipe(indices, method):
    source, definition = _reference(indices, "production_methods", method)
    modifiers = _one(definition.value, "building_modifiers")
    if modifiers is not None and not isinstance(modifiers.value, Block):
        raise ValueError("公司部门 PM building_modifiers 必须是块")
    rows = (
        list(_modifiers(modifiers.value))
        if modifiers is not None and isinstance(modifiers.value, Block)
        else []
    )
    inputs: set[str] = set()
    outputs: set[str] = set()
    employment: set[str] = set()
    for row in rows:
        match = _GOOD.fullmatch(row["key"])
        job = _JOB.fullmatch(row["key"])
        if match:
            _reference(indices, "goods", match[2])
            if row["value"] > 0:
                (inputs if match[1] == "input" else outputs).add(match[2])
        elif job and row["value"] > 0:
            employment.add(job[1])
    return {
        "id": method,
        "source": source,
        "line": definition.line,
        "inputs": sorted(inputs),
        "outputs": sorted(outputs),
        "employment": sorted(employment),
        "modifiers": rows,
    }


def _market_reason(indices, good):
    _source, definition = _reference(indices, "goods", good)
    for key, blocked, reason in (
        ("local", "yes", "local_good_requires_state_market_evidence"),
        ("fixed_price", "yes", "fixed_price_good_retains_native_mechanism"),
        ("tradeable", "no", "nontradeable_good_retains_native_mechanism"),
    ):
        flag = _one(definition.value, key)
        if flag is not None:
            if not isinstance(flag.value, Scalar) or flag.value.unquoted not in {"yes", "no"}:
                raise ValueError(f"公司部门商品 {key} 标记无效")
            if flag.value.unquoted == blocked:
                return reason
    return None


def _building(indices, building):
    source, definition = _reference(indices, "buildings", building)
    groups, potential, base_outputs, common, jobs = [], set(), set(), set(), set()
    for group in _list(definition.value, "production_method_groups", required=True):
        group_source, group_definition = _reference(indices, "production_method_groups", group)
        recipes = [
            _recipe(indices, method)
            for method in _list(group_definition.value, "production_methods", required=True)
        ]
        for recipe in recipes:
            potential.update(recipe["outputs"])
        # Positive output for every alternative proves an always-present recipe
        # opportunity in this group. A disabled branch invalidates necessity.
        base = all(recipe["outputs"] for recipe in recipes)
        if base:
            shared = set(recipes[0]["inputs"])
            for recipe in recipes:
                shared.intersection_update(recipe["inputs"])
                base_outputs.update(recipe["outputs"])
                jobs.update(recipe["employment"])
            common.update(shared)
        groups.append(
            {
                "id": group,
                "source": group_source,
                "line": group_definition.line,
                "base": base,
                "methods": recipes,
            }
        )
    reasons = [
        {"building": building, "good": good, "reason": reason}
        for good in sorted(base_outputs)
        if (reason := _market_reason(indices, good)) is not None
    ]
    if not potential:
        reasons.append(
            {"building": building, "good": None, "reason": "no_goods_output_native_service"}
        )
    elif not base_outputs:
        reasons.append(
            {"building": building, "good": None, "reason": "no_mandatory_output_recipe_group"}
        )
    return {
        "id": building,
        "source": source,
        "line": definition.line,
        "groups": groups,
        "potential_outputs": sorted(potential),
        "base_outputs": sorted(base_outputs),
        "market_outputs": sorted(
            good for good in base_outputs if _market_reason(indices, good) is None
        ),
        "common_inputs": sorted(good for good in common if _market_reason(indices, good) is None),
        "employment": sorted(jobs),
        "native_only": reasons,
    }


def _predicate(key, operation, value):
    return {"fact": key, "op": operation, "value": value}


def _default_identities() -> dict[str, tuple[str, int, str, str]]:
    """Read the independently frozen fallback proof, never current game state."""
    evidence = json.loads(engine_scope.company_default_snapshot())
    contract = evidence["contracts"][0]
    sources = [source for source in evidence["script_hashes"] if _family(source) == "company_types"]
    if len(sources) != 1:
        raise ValueError("公司部门缺省评分缺少唯一公司原件来源")
    return {
        row["id"]: (
            sources[0],
            row["line"],
            contract["define_source"],
            contract["define_field"],
        )
        for row in evidence["implicit_companies"]
    }


def _initialized(profile, identities) -> bool:
    default = profile["default_define"]
    return (
        not profile["explicit_weight"]
        and bool(profile["market_outputs"] or _special_sectors(profile))
        and identities.get(profile["id"])
        == (profile["source"], profile["line"], default["source"], default["field"])
        and type(default["value"]) is int
        and default["value"] == 1
    )


def _special_sectors(profile) -> set[str]:
    """Finite typed building consumers, classified by actual primary output."""
    expected = {
        "building_railway": "transportation",
        "building_power_plant": "electricity",
        "building_port": "merchant_marine",
        "building_gold_mine": "gold",
        "building_trade_center": None,
    }
    return {
        sector["id"]
        for sector in profile["base_recipes"]
        if sector["id"] in expected
        and (
            expected[sector["id"]] is None or expected[sector["id"]] in sector["potential_outputs"]
        )
    }


def _profile_rules(profiles, parameters):
    identities = _default_identities()
    rows = []
    for _company, profile in sorted(profiles.items()):
        if (profile["market_outputs"] or _special_sectors(profile)) and (
            profile["explicit_weight"] or _initialized(profile, identities)
        ):
            rows.extend(_rules(profile, parameters))
    _priorities(rows, parameters)
    return rows


def initialized_fields(data: Mapping[str, Any]) -> list[dict[str, str]]:
    """Expose only proved missing fields that actually have a sector program."""
    identities = _default_identities()
    fields = {(row["source"], row["field"]) for row in data["rules"]}
    return [
        {
            "source": profile["source"],
            "field": profile["field"],
            "define_source": profile["default_define"]["source"],
            "define": profile["default_define"]["field"],
        }
        for _company, profile in sorted(data["profiles"].items())
        if _initialized(profile, identities) and (profile["source"], profile["field"]) in fields
    ]


def query_source_hashes(data: Mapping[str, Any]) -> dict[str, str]:
    """Additional normalized native provenance required by emitted queries."""
    sources: set[str] = set()
    for reader in data["readers"].values():
        if "company_query" not in reader.get("parameters", {}):
            continue
        query = company_observations.from_reader(reader["engine"], reader["parameters"])
        sources.update(company_observations.required_sources(query))
    return {source: company_observations.source_hashes()[source] for source in sorted(sources)}


def unsupported_facets(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Retain explicit gold/trade/other gaps even for a mixed supported company."""
    return [
        {"company": company, **reason}
        for company, profile in sorted(data["profiles"].items())
        for reason in profile["native_only"]
        if reason["building"] not in _special_sectors(profile)
    ]


def _rules(profile, parameters):
    company = profile["id"]
    rows: list[dict[str, Any]] = []

    def add(suffix, cause, value, conditions, why):
        rows.append(
            {
                "id": f"company_sector_{company.replace('-', '_')}_{suffix}",
                "source": profile["source"],
                "field": profile["field"],
                "domain": "market",
                "operation": "multiply",
                "value": value,
                "contribution_group": cause,
                "conditions": conditions,
                "why": why,
                "counterexample": "局部未知撤回相应贡献；保留原版资格、成本、随机、非正分拒绝与执行；潜在配方不是active PM",
            }
        )

    # All outputs are alternatives in one demand cause. A diversified company
    # cannot collect N copies of the same sector-opportunity reward.
    for good in profile["market_outputs"]:
        balance, price = f"country_goods_{good}_balance", f"country_goods_{good}_price"
        need = _predicate(balance, "<", parameters["shortage_balance"])
        add(
            f"{good}_need",
            "company_output_demand",
            parameters["demand_multiplier"],
            [need],
            f"主业基础配方可能产出{good}；国家市场已有买单缺口，形成筹建机会，不假定已启用PM",
        )
        add(
            f"{good}_pressure",
            "company_output_demand",
            parameters["pressure_multiplier"],
            [need, _predicate(price, ">", parameters["output_price_threshold"])],
            f"{good}缺口且相对基价高，升档同一主业需求，不能重复奖励",
        )
    sectors = _special_sectors(profile)
    for building, low, high, description in (
        (
            "building_railway",
            "company_rail_need",
            "company_rail_pressure",
            "本国同一州已有铁路且基础设施不足；本州运输高价只升档同一需求",
        ),
        (
            "building_power_plant",
            "company_power_need",
            "company_power_pressure",
            "本国同一州已有电厂且本州电价高，体现本地电力稀缺，不读取全国电力价格",
        ),
        (
            "building_gold_mine",
            "company_gold_need",
            "company_gold_pressure",
            "本国同一金矿已有正周利润与充分就业，形成经营机会；现金与高就业升档。所有基础开采PM共同产黄金并按就业增加铸币，不使用普通黄金价格/缺口",
        ),
        (
            "building_trade_center",
            "company_trade_need",
            "company_trade_pressure",
            "本国同一贸易中心已有正周利润与充分就业，形成贸易经营/组织机会；现金与高就业升档。不是贸易容量短缺，不预记prosperity或税收",
        ),
    ):
        if building not in sectors:
            continue
        for suffix, reader, multiplier in (
            ("need", low, "demand_multiplier"),
            ("pressure", high, "pressure_multiplier"),
        ):
            add(
                f"{building}_{suffix}",
                "company_output_demand",
                parameters[multiplier],
                [_predicate(reader, "=", True)],
                description,
            )
    if company in {"company_panama_company", "company_suez_company"}:
        if not {"building_trade_center", "building_port"} <= sectors:
            raise ValueError("贸易风险作者需要精确贸易中心及港口主业身份")
        for suffix, key, value in (
            ("loss", "company_trade_loss", 0.95),
            ("loss_low_cash", "company_trade_loss_low_cash", 0.9),
        ):
            add(
                f"trade_{suffix}",
                "company_trade_operating_pressure",
                value,
                [_predicate(key, "=", True)],
                "本国同一已有贸易中心周利润为负形成有限筹建机会成本；同栋现金比率低于.25仅升档同因压力。局部经营风险代理不证明全国贸易亏损或候选公司利润，不能抹去港口独立收益",
            )
    if "building_port" in sectors:
        need = _predicate(
            "country_goods_merchant_marine_balance", "<", parameters["shortage_balance"]
        )
        price = _predicate(
            "country_goods_merchant_marine_price", ">", parameters["output_price_threshold"]
        )
        for method, inputs in (
            ("basic", ("clippers",)),
            ("industrial", ("steamers", "coal")),
            ("modern", ("steamers", "oil")),
        ):
            active = _predicate(f"company_port_{method}", "=", True)
            add(
                f"port_{method}_need",
                "company_output_demand",
                parameters["demand_multiplier"],
                [active, need],
                "本国已有真实产商船的active港口方式，国家商船买单缺口形成航运机会；锚地不算产出",
            )
            add(
                f"port_{method}_pressure",
                "company_output_demand",
                parameters["pressure_multiplier"],
                [active, need, price],
                "同一航运机会同时商船高价，升档需求；不同港口方式不重复奖励",
            )
            for good in inputs:
                add(
                    f"port_{method}_{good}_input",
                    f"company_mandatory_input_{good}",
                    parameters["input_multiplier"],
                    [
                        active,
                        _predicate(
                            f"country_goods_{good}_price", ">", parameters["input_price_threshold"]
                        ),
                    ],
                    f"已观察{method}港口active方式实际需要{good}，国家市场高价为该生产方式的独立机会成本",
                )
    # Profiles already deduplicate required goods across all primary recipe
    # groups. Share the same physical-good cause with active port recipes too:
    # repeated steamers/sulfur evidence is one cost, distinct goods join.
    for good in profile["common_inputs"]:
        add(
            f"{good}_input",
            f"company_mandatory_input_{good}",
            parameters["input_multiplier"],
            [_predicate(f"country_goods_{good}_price", ">", parameters["input_price_threshold"])],
            f"主业某必选基础配方组所有方法共同需要{good}；高价为配方机会成本，不是当前实际账单",
        )
    if profile["employs_laborers"]:
        add(
            "workforce",
            "company_labor_structure",
            parameters["workforce_multiplier"],
            [_predicate("industrial_workforce", ">=", parameters["laborers_share_threshold"])],
            "真实基础配方含laborers岗位；国家laborers占比只作劳动结构适配代理，不是失业或岗位空缺",
        )
    add(
        "default",
        "company_solvency",
        parameters["default_multiplier"],
        [_predicate("default", "=", True)],
        "已观察国家违约提高筹建计划机会成本；不是公司成立时实际付款",
    )
    return rows


def _priorities(rules: list[dict[str, Any]], parameters: Mapping[str, float]) -> None:
    for index, rule in enumerate(rules):
        rule["priority"] = int(parameters["priority_base"]) + index


def _readers(
    rules: list[dict[str, Any]], parameters: Mapping[str, float]
) -> dict[str, dict[str, Any]]:
    readers: dict[str, dict[str, Any]] = {}
    required = {predicate["fact"] for rule in rules for predicate in rule["conditions"]}
    query_readers: dict[str, company_observations.CompanyQuery] = {
        "company_rail_need": company_observations.RailInfrastructure(),
        "company_rail_pressure": company_observations.RailInfrastructure(
            parameters["output_price_threshold"]
        ),
        "company_power_need": company_observations.PowerScarcity(
            parameters["output_price_threshold"]
        ),
        "company_power_pressure": company_observations.PowerScarcity(
            min(0.75, 2 * parameters["output_price_threshold"])
        ),
        "company_port_basic": company_observations.PortMethod("pm_basic_port"),
        "company_port_industrial": company_observations.PortMethod("pm_industrial_port"),
        "company_port_modern": company_observations.PortMethod("pm_modern_port"),
        "company_gold_need": company_observations.ExistingBusiness("building_gold_mine"),
        "company_gold_pressure": company_observations.ExistingBusiness("building_gold_mine", True),
        "company_trade_loss": company_observations.TradeBusinessPressure(),
        "company_trade_loss_low_cash": company_observations.TradeBusinessPressure(True),
        "company_trade_need": company_observations.ExistingBusiness("building_trade_center"),
        "company_trade_pressure": company_observations.ExistingBusiness(
            "building_trade_center", True
        ),
    }
    for key in sorted(required):
        if key in query_readers:
            readers[key] = company_observations.reader_spec(query_readers[key])
        elif key.startswith("country_goods_"):
            good, suffix = key.removeprefix("country_goods_").rsplit("_", 1)
            readers[key] = {
                "engine": "market_goods_delta" if suffix == "balance" else "market_goods_pricier",
                "scope": "root",
                "path": ["market", f"mg:{good}"],
                "unit": "sell_minus_buy_orders"
                if suffix == "balance"
                else "price_above_base_ratio",
                "kind": "number",
            }
        elif key == "industrial_workforce":
            readers[key] = {
                "engine": "pop_type_percent_country",
                "scope": "root",
                "kind": "number",
                "unit": "ratio",
                "parameters": {"pop_type": "laborers"},
                "value_field": "percent",
                "minimum": 0,
                "maximum": 1,
            }
        elif key == "default":
            readers[key] = {
                "engine": "in_default",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
            }
        else:
            raise ValueError("公司部门模板含未知读取器")
    return readers


def derive(
    inputs: Mapping[str, str], *, parameters: Mapping[str, object] | None = None
) -> dict[str, Any]:
    """Return deterministic audit profiles and adapter-shaped rule fragments."""
    chosen = _parameters(DEFAULTS if parameters is None else parameters)
    indices, sources = _definitions(inputs)
    namespace = indices["defines"].get("NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT")
    if namespace is None:
        raise ValueError("公司部门缺少NAI缺省评分define证据")
    default = namespace[1]
    if not isinstance(default.value, Scalar) or default.value.unquoted != "1":
        raise ValueError("公司部门缺省评分define漂移；不得静默初始化")
    profiles: dict[str, Any] = {}
    buildings: dict[str, Any] = {}
    for company, (source, definition) in sorted(indices["company_types"].items()):
        primary = _list(definition.value, "building_types", required=True)
        extensions = _list(definition.value, "extension_building_types")
        weight = _one(definition.value, "ai_weight")
        if weight is not None and not isinstance(weight.value, Block):
            raise ValueError("公司部门显式评分必须是原版数字块")
        for building in (*primary, *extensions):
            _reference(indices, "buildings", building)
        for building in primary:
            if building not in buildings:
                buildings[building] = _building(indices, building)
        sectors = [buildings[building] for building in primary]
        profile = {
            "id": company,
            "source": source,
            "line": definition.line,
            "field": f"{company}.ai_weight",
            "explicit_weight": weight is not None,
            "primary": list(primary),
            "extensions": list(extensions),
            "base_recipes": sectors,
            "potential_outputs": sorted(
                {good for sector in sectors for good in sector["potential_outputs"]}
            ),
            "market_outputs": sorted(
                {good for sector in sectors for good in sector["market_outputs"]}
            ),
            "common_inputs": sorted(
                {good for sector in sectors for good in sector["common_inputs"]}
            ),
            "employs_laborers": any("laborers" in sector["employment"] for sector in sectors),
            "native_only": [reason for sector in sectors for reason in sector["native_only"]],
            "default_define": {
                "source": namespace[0],
                "field": "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT",
                "value": 1,
            },
            "evaluation": "static_recipe_opportunity_not_active_pm",
        }
        profiles[company] = profile
    if len({identity.replace("-", "_") for identity in profiles}) != len(profiles):
        raise ValueError("公司部门原生身份映射到规则ID后冲突")
    rules = _profile_rules(profiles, chosen)
    readers = _readers(rules, chosen)
    return {
        "schema": 1,
        "parameters": chosen,
        "profiles": profiles,
        "rules": rules,
        "readers": readers,
        "sources": sources,
        "counts": {
            "companies": len(profiles),
            "explicit_weight": sum(profile["explicit_weight"] for profile in profiles.values()),
            "implicit_weight": sum(not profile["explicit_weight"] for profile in profiles.values()),
            "primary_buildings": len(buildings),
        },
    }


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _frozen_profile(profile, sources):
    if not isinstance(profile, dict) or set(profile) != {
        "id",
        "source",
        "line",
        "field",
        "explicit_weight",
        "primary",
        "extensions",
        "base_recipes",
        "potential_outputs",
        "market_outputs",
        "common_inputs",
        "employs_laborers",
        "native_only",
        "default_define",
        "evaluation",
    }:
        raise ValueError("公司部门冻结画像键无效")
    if (
        not isinstance(profile["id"], str)
        or not re.fullmatch("[a-z][a-z0-9_-]*", profile["id"])
        or profile["source"] not in sources
        or _family(profile["source"]) != "company_types"
        or type(profile["line"]) is not int
        or profile["line"] < 1
        or profile["field"] != f"{profile['id']}.ai_weight"
        or type(profile["explicit_weight"]) is not bool
        or type(profile["employs_laborers"]) is not bool
        or profile["evaluation"] != "static_recipe_opportunity_not_active_pm"
    ):
        raise ValueError("公司部门冻结画像身份无效")
    for key in ("primary", "extensions", "potential_outputs", "market_outputs", "common_inputs"):
        values = profile[key]
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            or len(values) != len(set(values))
        ):
            raise ValueError("公司部门冻结画像列表无效")
    sectors = profile["base_recipes"]
    if (
        not isinstance(sectors, list)
        or not sectors
        or [sector.get("id") for sector in sectors] != profile["primary"]
    ):
        raise ValueError("公司部门冻结主业配方无效")
    for sector in sectors:
        if (
            set(sector)
            != {
                "id",
                "source",
                "line",
                "groups",
                "potential_outputs",
                "base_outputs",
                "market_outputs",
                "common_inputs",
                "employment",
                "native_only",
            }
            or sector["source"] not in sources
        ):
            raise ValueError("公司部门冻结建筑画像键无效")
        if not isinstance(sector["groups"], list) or not sector["groups"]:
            raise ValueError("公司部门冻结建筑缺少PMG")
        for group in sector["groups"]:
            if (
                not isinstance(group, dict)
                or set(group) != {"id", "source", "line", "base", "methods"}
                or group["source"] not in sources
                or type(group["base"]) is not bool
            ):
                raise ValueError("公司部门冻结PMG画像键无效")
            if not isinstance(group["methods"], list) or not group["methods"]:
                raise ValueError("公司部门冻结PMG缺少PM")
            for recipe in group["methods"]:
                if (
                    not isinstance(recipe, dict)
                    or set(recipe)
                    != {"id", "source", "line", "inputs", "outputs", "employment", "modifiers"}
                    or recipe["source"] not in sources
                ):
                    raise ValueError("公司部门冻结PM画像键无效")
                for key in ("inputs", "outputs", "employment"):
                    values = recipe[key]
                    if (
                        not isinstance(values, list)
                        or any(not isinstance(value, str) for value in values)
                        or values != sorted(set(values))
                    ):
                        raise ValueError("公司部门冻结PM输入/输出/岗位列表无效")
                for modifier in recipe["modifiers"]:
                    if not isinstance(modifier, dict) or set(modifier) != {
                        "key",
                        "value",
                        "scaling",
                        "line",
                    }:
                        raise ValueError("公司部门冻结配方修饰器键无效")
            if group["base"] != all(recipe["outputs"] for recipe in group["methods"]):
                raise ValueError("公司部门冻结基础配方组身份漂移")
        for reason in sector["native_only"]:
            if not isinstance(reason, dict) or set(reason) != {"building", "good", "reason"}:
                raise ValueError("公司部门冻结native-only解释键无效")
    for key in ("potential_outputs", "market_outputs", "common_inputs"):
        if profile[key] != sorted({good for sector in sectors for good in sector[key]}):
            raise ValueError("公司部门冻结画像部门聚合漂移")
    if profile["employs_laborers"] != any(
        "laborers" in sector["employment"] for sector in sectors
    ) or profile["native_only"] != [
        reason for sector in sectors for reason in sector["native_only"]
    ]:
        raise ValueError("公司部门冻结劳动或native-only证据漂移")
    default = profile["default_define"]
    if (
        not isinstance(default, dict)
        or set(default) != {"source", "field", "value"}
        or default["source"] not in sources
        or _family(default["source"]) != "defines"
        or default["field"] != "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT"
        or type(default["value"]) is not int
        or default["value"] != 1
    ):
        raise ValueError("公司部门冻结缺省define证据无效")


def read_inputs(game: Path) -> dict[str, str]:
    """Inventory all relevant root/DLC files, including newly added shadows."""
    return {
        path.relative_to(game).as_posix(): path.read_text(encoding="utf-8-sig")
        for path in sorted(game.rglob("*.txt"))
        if _family(path.relative_to(game).as_posix()) is not None
    }


def write_baseline(game: Path) -> Path:
    """Explicit production step; never called by model loading or import."""
    inputs = read_inputs(game)
    data = derive(inputs, parameters=load_parameters())
    destination = baseline_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    frozen = _freeze(data)
    if version_contracts.is_115():
        from .situated import r2_reader_authority  # noqa: PLC0415

        r2_reader_authority.verify_installation(game.parent)
        frozen = {
            "schema": 3,
            "game_version": version_contracts.active_version(),
            "provenance": _baseline_provenance(),
            "payload": frozen,
        }
    destination.write_text(_canonical(frozen), encoding="utf-8", newline="\n")
    return destination


def _freeze(data: dict[str, Any]) -> dict[str, Any]:
    """Store one exact building definition, without mutating runtime profiles."""
    _validate_runtime(data)
    buildings: dict[str, Any] = {}
    profiles = {}
    for company, profile in sorted(data["profiles"].items()):
        references = []
        for sector in profile["base_recipes"]:
            identity = sector["id"]
            if identity in buildings and buildings[identity] != sector:
                raise ValueError("公司部门建筑表含冲突的重复定义")
            buildings[identity] = sector
            references.append(identity)
        profiles[company] = {**profile, "base_recipes": references}
    return {**data, "schema": 2, "profiles": profiles, "building_profiles": buildings}


def _thaw(data: dict[str, Any]) -> dict[str, Any]:
    """Restore shared building objects; no source or semantic claims are added."""
    if (
        not isinstance(data, dict)
        or set(data)
        != {
            "schema",
            "parameters",
            "profiles",
            "rules",
            "readers",
            "sources",
            "counts",
            "building_profiles",
        }
        or type(data["schema"]) is not int
        or data["schema"] != 2
    ):
        raise ValueError("公司部门引用冻结基线格式或键无效")
    buildings = data["building_profiles"]
    if not isinstance(buildings, dict) or not buildings or not isinstance(data["profiles"], dict):
        raise ValueError("公司部门冻结建筑表或画像集合无效")
    for identity, sector in buildings.items():
        if not isinstance(sector, dict) or sector.get("id") != identity:
            raise ValueError("公司部门冻结建筑表身份冲突")
    profiles, used = {}, set()
    for company, profile in data["profiles"].items():
        if not isinstance(profile, dict):
            raise ValueError("公司部门冻结画像必须是记录")
        references = profile.get("base_recipes")
        if (
            not isinstance(references, list)
            or not references
            or any(
                not isinstance(identity, str) or identity not in buildings
                for identity in references
            )
        ):
            raise ValueError("公司部门冻结建筑引用缺失或未知")
        if len(references) != len(set(references)) or references != profile.get("primary"):
            raise ValueError("公司部门冻结建筑引用重复或与主业不一致")
        used.update(references)
        profiles[company] = {
            **profile,
            "base_recipes": [buildings[identity] for identity in references],
        }
    if used != buildings.keys():
        raise ValueError("公司部门冻结建筑表含无消费者定义")
    return {
        key: 1 if key == "schema" else profiles if key == "profiles" else value
        for key, value in data.items()
        if key != "building_profiles"
    }


def _validate_runtime(data: dict[str, Any]) -> dict[str, Any]:
    keys = {"schema", "parameters", "profiles", "rules", "readers", "sources", "counts"}
    if (
        not isinstance(data, dict)
        or set(data) != keys
        or type(data["schema"]) is not int
        or data["schema"] != 1
    ):
        raise ValueError("公司部门冻结基线格式或键无效")
    if data["parameters"] != load_parameters():
        raise ValueError("公司部门冻结参数漂移，必须重新派生")
    if (
        not isinstance(data["profiles"], dict)
        or not data["profiles"]
        or not isinstance(data["rules"], list)
        or not isinstance(data["readers"], dict)
        or not isinstance(data["sources"], dict)
        or not isinstance(data["counts"], dict)
    ):
        raise ValueError("公司部门冻结基线集合类型无效")
    if any(
        _family(source) is None
        or not isinstance(digest, str)
        or not re.fullmatch("[0-9a-f]{64}", digest)
        for source, digest in data["sources"].items()
    ):
        raise ValueError("公司部门冻结原件身份无效")
    if {_family(source) for source in data["sources"]} != _FAMILIES:
        raise ValueError("公司部门冻结原件缺少必需家族")
    for company, profile in sorted(data["profiles"].items()):
        _frozen_profile(profile, data["sources"])
        if company != profile["id"]:
            raise ValueError("公司部门冻结画像索引无效")
    expected_rules = _profile_rules(data["profiles"], data["parameters"])
    if data["rules"] != expected_rules or data["readers"] != _readers(
        expected_rules, data["parameters"]
    ):
        raise ValueError("公司部门冻结模板或读取器与画像/参数不一致")
    profiles = list(data["profiles"].values())
    expected_counts = {
        "companies": len(profiles),
        "explicit_weight": sum(profile["explicit_weight"] for profile in profiles),
        "implicit_weight": sum(not profile["explicit_weight"] for profile in profiles),
        "primary_buildings": len(
            {building for profile in profiles for building in profile["primary"]}
        ),
    }
    if data["counts"] != expected_counts:
        raise ValueError("公司部门冻结计数与实际画像不一致")
    return data


def _baseline_provenance() -> dict[str, str]:
    """Bind regeneration code, tuning and independently proved default rights."""
    return {
        "builder_path": "src/pdx/company_sectors.py",
        "builder_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rule_builder_source_sha256": hashlib.sha256(
            inspect.getsource(_rules).encode()
        ).hexdigest(),
        "parameters_sha256": hashlib.sha256(PARAMETERS.read_bytes()).hexdigest(),
        "default_authority_sha256": hashlib.sha256(
            engine_scope.company_default_snapshot()
        ).hexdigest(),
    }


def _load_baseline() -> dict[str, Any]:
    raw = baseline_path().read_text(encoding="utf-8")
    data = json.loads(raw)
    if raw != _canonical(data):
        raise ValueError("公司部门冻结基线不是规范格式")
    if version_contracts.is_115():
        provenance = _baseline_provenance()
        if version_contracts.active_version() == "1.15.0":
            # Preserve the historical artifact and the builder that created it.
            # Current rule source, parameters and default authority must still
            # match; verify_baseline separately re-derives the complete payload.
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != _BASELINE_115_SHA256:
                raise ValueError("公司部门1.15.0历史基线原始字节漂移")
            provenance["builder_source_sha256"] = _BUILDER_115_SHA256
        if (
            set(data) != {"schema", "game_version", "provenance", "payload"}
            or data["schema"] != 3
            or data["game_version"] != version_contracts.active_version()
            or data["provenance"] != provenance
        ):
            raise ValueError("公司部门1.15派生版本或生成来源漂移")
        data = data["payload"]
    return _validate_runtime(_thaw(data))


def load_baseline() -> dict[str, Any]:
    """Load a frozen static artifact; it makes no current-game verified claim."""
    try:
        return _load_baseline()
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("公司部门冻结基线嵌套结构无效") from exc


def verify_baseline(inputs: Mapping[str, str]) -> dict[str, Any]:
    """Independently derive current locked inputs and compare the full artifact."""
    frozen = load_baseline()
    current = derive(inputs, parameters=load_parameters())
    if current != frozen:
        raise ValueError("公司部门原件或派生基线漂移，必须独立复核并重生成")
    return current


def verify_game(game: Path) -> dict[str, Any]:
    """Re-inventory current source names before comparing the frozen derivation."""
    return verify_baseline(read_inputs(game))
