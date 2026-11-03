"""Finite company opportunities over owned states and buildings.

Country -> owned state -> state goods is composed from separately proven typed
native consumers. Every conjunct remains on the same state or building. The
templates grant no free PDX, world scan, company target or execution authority.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .model import Assignment, Block, Scalar
from .parser import parse_text
from .textio import normalized_text

_COMPANY = "common/company_types/00_companies_soi.txt"
_PRIVATE_BUILDING = "common/buildings/11_private_infrastructure.txt"
_POWER_BUILDING = "common/buildings/06_urban_center.txt"
_RAIL_GROUP = "common/production_method_groups/11_private_infrastructure.txt"
_PORT_GROUP = "common/production_method_groups/07_government.txt"
_POWER_GROUP = "common/production_method_groups/06_urban_center.txt"
_PRIVATE_METHOD = "common/production_methods/11_private_infrastructure.txt"
_POWER_METHOD = "common/production_methods/06_urban_center.txt"
_GOODS = "common/goods/00_goods.txt"
_ART = "common/journal_entries/00_art_jes.txt"
_OPIUM = "common/journal_entries/00_opium.txt"
_MINES_BUILDING = "common/buildings/03_mines.txt"
_MINES_GROUP = "common/production_method_groups/03_mines.txt"
_MINES_METHOD = "common/production_methods/03_mines.txt"
SOURCE_HASHES = {
    _COMPANY: "59546f6105092bad8935498d917a6012aa508c58bea873e462dd66a5850f2f1d",
    _PRIVATE_BUILDING: "3438f826295bb37ae52823121209734042e759c64c453754bde6876d44f9f35b",
    _POWER_BUILDING: "c41ed5adb63e8f626e6394ce4f2f619bc8f229cafa3d8994271e2a66d1c2b0c5",
    _RAIL_GROUP: "188b1828634d7ec7e8673df9fea33799e67cbfe9abfcfe5fcb4ef93f765f2186",
    _PORT_GROUP: "e1ea7e0286546ca4b2e5ad8bafa35de4e6dec6af59c93b1ff91c99d5815dd6da",
    _POWER_GROUP: "7b63fad3a75067d6157790917fcc5eeb411e5405318f7f3873373be9e6f94871",
    _PRIVATE_METHOD: "b1be6179a07bc71150ec45fd5c7b7fd14b88d6cba8068775c5e29cd364ccbbec",
    _POWER_METHOD: "d9f0e653d3d0c1783fd4e9880fb58a6ada795d0ed3a3fdec011f0d1ce28da71f",
    _GOODS: "496810f9b21012cb3ae764e4c0cd65aafa85b6079f96d3d2a6b3dece92a0afcc",
    _ART: "e0e281573697439d31145c5bdbebb0298ce753acb54be894f9ce6c4f8fc230c5",
    _OPIUM: "c8e51f799ffe192b1789c91ab6d0772d9dd028b5610529907e6a1a7760509dc8",
    _MINES_BUILDING: "6b3e9846022b6e4f998be0b131fc7c465a2a592d70c7c6ff6786e158aec68992",
    _MINES_GROUP: "995d2a9a19c99c5b64c3136c886be439c9a7e578d0a796980a1eebdbeddba0bd",
    _MINES_METHOD: "80eaa71892c2c6da5b5c4e1d954161ec7d4172386a35a6b4fd47603a0565fb39",
}
PORT_METHODS = frozenset({"pm_basic_port", "pm_industrial_port", "pm_modern_port"})
QUERY_ENGINES = frozenset({"any_scope_state", "any_scope_building"})
UNKNOWN_POLICY = (
    "missing_collection=unknown; complete_empty_collection=false; any_true=true; "
    "no_true_with_missing_member_observation=unknown; malformed_input=error"
)
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


@dataclass(frozen=True, slots=True)
class RailInfrastructure:
    minimum_transport_price: float | None = None


@dataclass(frozen=True, slots=True)
class PowerScarcity:
    minimum_price: float = 0.25


@dataclass(frozen=True, slots=True)
class PortMethod:
    method_id: str


@dataclass(frozen=True, slots=True)
class ExistingBusiness:
    """Operating business, not trade-capacity scarcity or JE completion.

    Level one deliberately identifies existing operations. The original opium
    JE requires ten levels for its own objective; that objective is not copied.
    """

    building_id: str
    strong: bool = False


CompanyQuery = RailInfrastructure | PowerScarcity | PortMethod | ExistingBusiness


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...]
    scope_chain: tuple[str, ...]
    actor: Literal["country"] = "country"
    kind: Literal["boolean"] = "boolean"
    unknown_policy: str = UNKNOWN_POLICY
    world_scans: int = 0
    runtime_cost: str = "existential traversal of owned candidates; not constant time"


def _price(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("公司价格阈值必须是有限数值比例")
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 0.75:
        raise ValueError("公司价格阈值必须在原版最大价格偏离比例(0,.75]内")
    return number


def _decimal(value: str) -> float:
    if not _DECIMAL.fullmatch(value):
        raise ValueError("公司查询只接受无符号有限十进制参数")
    return _price(float(value))


def from_reader(engine: str, parameters: Mapping[str, str]) -> CompanyQuery:
    if not isinstance(parameters, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in parameters.items()
    ):
        raise ValueError("公司查询参数必须是完整字符串映射")
    tag = parameters.get("company_query")
    query: CompanyQuery
    if (
        engine == "any_scope_state"
        and tag == "rail_infrastructure"
        and set(parameters)
        in (
            {"company_query"},
            {"company_query", "minimum_price"},
        )
    ):
        query = RailInfrastructure(
            _decimal(parameters["minimum_price"]) if "minimum_price" in parameters else None
        )
    elif (
        engine == "any_scope_state"
        and tag == "power_scarcity"
        and set(parameters) == {"company_query", "minimum_price"}
    ):
        query = PowerScarcity(_decimal(parameters["minimum_price"]))
    elif (
        engine == "any_scope_building"
        and tag == "port_method"
        and set(parameters) == {"company_query", "method"}
    ):
        query = PortMethod(parameters["method"])
    elif (
        engine == "any_scope_building"
        and tag == "existing_business"
        and set(parameters) == {"company_query", "building", "tier"}
        and parameters["tier"] in {"base", "strong"}
    ):
        query = ExistingBusiness(parameters["building"], parameters["tier"] == "strong")
    else:
        raise ValueError("公司查询引擎、标识或参数形状未登记")
    render(query)
    return query


def render(query: CompanyQuery) -> str:
    if type(query) is ExistingBusiness:
        if (
            not isinstance(query.building_id, str)
            or query.building_id not in {"building_gold_mine", "building_trade_center"}
            or type(query.strong) is not bool
        ):
            raise ValueError("经营机会只允许金矿/贸易中心与明确布尔档位")
        cash = " cash_reserves_ratio > 0.5" if query.strong else ""
        occupancy = "0.9" if query.strong else "0.75"
        return (
            f"any_scope_building = {{ is_building_type = {query.building_id} "
            f"weekly_profit > 0{cash} occupancy >= {occupancy} level >= 1 }}"
        )
    if type(query) is RailInfrastructure:
        price = ""
        if query.minimum_transport_price is not None:
            price = (
                " sg:transportation = { state_goods_pricier > "
                f"{_price(query.minimum_transport_price)!r} }}"
            )
        return (
            "any_scope_state = { any_scope_building = { "
            "is_building_type = building_railway level >= 1 } "
            f"infrastructure_delta < 0{price} }}"
        )
    if type(query) is PowerScarcity:
        return (
            "any_scope_state = { any_scope_building = { "
            "is_building_type = building_power_plant level >= 1 } "
            f"sg:electricity = {{ state_goods_pricier > {_price(query.minimum_price)!r} }} }}"
        )
    if type(query) is PortMethod:
        if not isinstance(query.method_id, str) or query.method_id not in PORT_METHODS:
            raise ValueError("公司港口查询仅接受已证实有商船产出的真实active PM")
        return (
            "any_scope_building = { is_building_type = building_port "
            f"has_active_production_method = {query.method_id} level >= 1 }}"
        )
    raise ValueError("未登记的公司查询类型")


def reader_spec(query: CompanyQuery) -> dict[str, Any]:
    render(query)
    parameters: dict[str, str]
    if isinstance(query, RailInfrastructure):
        parameters = {"company_query": "rail_infrastructure"}
        if query.minimum_transport_price is not None:
            parameters["minimum_price"] = repr(_price(query.minimum_transport_price))
    elif isinstance(query, PowerScarcity):
        parameters = {
            "company_query": "power_scarcity",
            "minimum_price": repr(_price(query.minimum_price)),
        }
    elif isinstance(query, ExistingBusiness):
        parameters = {
            "company_query": "existing_business",
            "building": query.building_id,
            "tier": "strong" if query.strong else "base",
        }
    else:
        parameters = {"company_query": "port_method", "method": query.method_id}
    return {
        "engine": "any_scope_building"
        if isinstance(query, (PortMethod, ExistingBusiness))
        else "any_scope_state",
        "parameters": parameters,
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
    }


def required_sources(query: CompanyQuery) -> tuple[str, ...]:
    render(query)
    if isinstance(query, ExistingBusiness):
        if query.building_id == "building_gold_mine":
            return tuple(sorted({_OPIUM, _MINES_BUILDING, _MINES_GROUP, _MINES_METHOD, _GOODS}))
        return tuple(sorted({_OPIUM, _PRIVATE_BUILDING, _RAIL_GROUP, _PRIVATE_METHOD}))
    common = {_PRIVATE_BUILDING, _GOODS}
    if isinstance(query, PortMethod):
        return tuple(sorted(common | {_ART, _PORT_GROUP, _PRIVATE_METHOD}))
    if isinstance(query, PowerScarcity):
        return tuple(sorted(common | {_COMPANY, _POWER_BUILDING, _POWER_GROUP, _POWER_METHOD}))
    return tuple(sorted(common | {_COMPANY, _RAIL_GROUP, _PRIVATE_METHOD}))


def _entry(block: Block, key: str) -> Assignment:
    rows = block.all(key)
    if len(rows) != 1 or rows[0].op != "=" or rows[0].prefix is not None:
        raise ValueError(f"公司查询原版证据缺少唯一普通字段：{key}")
    return rows[0]


def _child(block: Block, key: str) -> Block:
    row = _entry(block, key)
    if not isinstance(row.value, Block):
        raise ValueError(f"公司查询原版证据缺少块：{key}")
    return row.value


def _scalar(block: Block, key: str) -> str:
    row = _entry(block, key)
    if not isinstance(row.value, Scalar):
        raise ValueError(f"公司查询原版证据缺少标量：{key}")
    return row.value.unquoted


def _list(block: Block, key: str) -> tuple[str, ...]:
    values = _child(block, key)
    if any(not isinstance(value, Scalar) for value in values.items):
        raise ValueError("公司查询原版定义列表含未知结构")
    return tuple(value.unquoted for value in values.scalars())


def _shape(block: Block) -> tuple:
    rows = []
    for item in block.items:
        if not isinstance(item, Assignment) or item.prefix is not None:
            raise ValueError("公司查询原版条件含非普通赋值")
        if isinstance(item.value, Block):
            value: object = _shape(item.value)
        elif isinstance(item.value, Scalar):
            value = item.value.unquoted
        else:
            raise ValueError("公司查询原版条件含缺失值")
        rows.append((item.key, item.op, value))
    return tuple(rows)


def _exact(block: Block, key: str, body: str) -> int:
    expected = _shape(parse_text(body).root)
    matches = []

    def visit(parent: Block) -> None:
        for entry in parent.assignments():
            if not isinstance(entry.value, Block) or entry.prefix is not None or entry.op != "=":
                continue
            if entry.key == key and _shape(entry.value) == expected:
                matches.append(entry.line)
            visit(entry.value)

    visit(block)
    if len(matches) != 1:
        raise ValueError(f"公司查询缺少唯一完整原版条件AST：{key}")
    return matches[0]


def _recipe(method: Block, expected: Mapping[str, float]) -> None:
    scaled = _child(_child(method, "building_modifiers"), "workforce_scaled")
    actual = {
        row.key: float(_scalar(scaled, row.key))
        for row in scaled.assignments()
        if row.key.startswith(("goods_input_", "goods_output_"))
    }
    if actual != expected:
        raise ValueError("公司查询消费的实际PM商品配方发生变化")


def compile_query(query: CompanyQuery, texts: Mapping[str, str]) -> CompiledQuery:
    """Verify each typed edge and consumed recipe in supplied frozen sources."""
    expression = render(query)
    roots = {}
    hashes = []
    for source in required_sources(query):
        text = texts.get(source)
        if not isinstance(text, str):
            raise ValueError(f"公司查询缺少必需原版来源：{source}")
        normalized = normalized_text(text)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if digest != SOURCE_HASHES[source]:
            raise ValueError(f"公司查询原版来源漂移：{source}")
        parsed = parse_text(normalized, path=source)
        if parsed.errors:
            raise ValueError(f"公司查询原版来源无法解析：{source}")
        roots[source] = parsed.root
        hashes.append((source, digest))
    references = []
    collections: tuple[str, ...]
    chain: tuple[str, ...]
    methods: tuple[str, ...]

    def reference(source: str, key: str) -> Block:
        block = _child(roots[source], key)
        references.append(f"{source}:{_entry(roots[source], key).line}")
        return block

    if isinstance(query, ExistingBusiness):
        native = _child(reference(_OPIUM, "je_opium"), "complete")
        line = _exact(
            native,
            "any_scope_building",
            "is_building_type = building_opium_plantation cash_reserves_ratio > 0.5 "
            "weekly_profit > 0 occupancy >= 0.75 level >= 10",
        )
        references.append(f"{_OPIUM}:{line}")
        if query.building_id == "building_gold_mine":
            building = reference(_MINES_BUILDING, query.building_id)
            group_id = "pmg_mining_equipment_building_gold_mine"
            if group_id not in _list(building, "production_method_groups"):
                raise ValueError("金矿经营查询失去实际基础开采组")
            group = reference(_MINES_GROUP, group_id)
            methods = (
                "pm_picks_and_shovels_building_gold_mine",
                "pm_atmospheric_engine_pump_building_gold_mine",
                "pm_condensing_engine_pump_building_gold_mine",
                "pm_diesel_pump_building_gold_mine",
            )
            if _list(group, "production_methods") != methods:
                raise ValueError("金矿基础开采组必须完整非空且身份精确")
            for method_id, output, tools, fuel, amount, minting in zip(
                methods,
                (8, 15, 25, 30),
                (5, 10, 15, 15),
                (None, "coal", "coal", "oil"),
                (0, 10, 15, 5),
                (250, 500, 750, 1000),
                strict=True,
            ):
                method = reference(_MINES_METHOD, method_id)
                recipe = {
                    "goods_output_gold_add": float(output),
                    "goods_input_tools_add": float(tools),
                }
                if fuel is not None:
                    recipe[f"goods_input_{fuel}_add"] = float(amount)
                _recipe(method, recipe)
                country = _child(_child(method, "country_modifiers"), "workforce_scaled")
                if _scalar(country, "country_minting_add") != str(minting):
                    raise ValueError("金矿基础PM失去已证明的正就业规模铸币收入")
            good = reference(_GOODS, "gold")
            if _scalar(good, "fixed_price") != "yes" or _scalar(good, "tradeable") != "no":
                raise ValueError("金矿经营查询失去固定价/不可贸易机制")
        else:
            building = reference(_PRIVATE_BUILDING, query.building_id)
            group_id = "pmg_base_building_trade_center"
            if group_id not in _list(building, "production_method_groups"):
                raise ValueError("贸易经营查询失去实际服务PM组")
            group = reference(_RAIL_GROUP, group_id)
            methods = ("pm_trade_center", "pm_trade_center_principle_external_trade_2")
            if _list(group, "production_methods") != methods:
                raise ValueError("贸易基础服务组必须完整非空且身份精确")
            for method_id in methods:
                method = reference(_PRIVATE_METHOD, method_id)
                state = _child(_child(method, "state_modifiers"), "workforce_scaled")
                if (
                    _scalar(state, "state_weekly_trades_add") != "1"
                    or _scalar(state, "state_trade_capacity_add") != "10"
                ):
                    raise ValueError("贸易基础PM失去真实每周贸易/贸易容量服务")
        collections = ("owned_buildings",)
        chain = (
            "country:any_scope_building->owned_building",
            "building:is_building_type+level[building_levels]",
            "building:weekly_profit[currency_per_week]>0",
            "building:occupancy[ratio]>=.75"
            if not query.strong
            else "building:occupancy[ratio]>=.9+cash_reserves_ratio[ratio]>.5",
        )
    elif isinstance(query, PortMethod):
        native = _child(reference(_ART, "je_romanticism"), "complete")
        line = _exact(
            native,
            "any_scope_building",
            "is_building_type = building_art_academy "
            "has_active_production_method = pm_traditional_art occupancy >= 0.9 level >= 2",
        )
        references.append(f"{_ART}:{line}")
        building = reference(_PRIVATE_BUILDING, "building_port")
        group = reference(_PORT_GROUP, "pmg_base_building_port")
        if "pmg_base_building_port" not in _list(building, "production_method_groups"):
            raise ValueError("港口查询失去实际建筑到PM组关系")
        if query.method_id not in _list(group, "production_methods"):
            raise ValueError("港口查询active PM不属于真实建筑PM组")
        expected = {
            "pm_basic_port": {
                "goods_input_clippers_add": 6.0,
                "goods_output_merchant_marine_add": 9.0,
            },
            "pm_industrial_port": {
                "goods_input_steamers_add": 5.0,
                "goods_input_coal_add": 5.0,
                "goods_output_merchant_marine_add": 20.0,
            },
            "pm_modern_port": {
                "goods_input_steamers_add": 5.0,
                "goods_input_oil_add": 10.0,
                "goods_output_merchant_marine_add": 30.0,
            },
        }
        _recipe(reference(_PRIVATE_METHOD, query.method_id), expected[query.method_id])
        good = reference(_GOODS, "merchant_marine")
        if any(good.all(flag) for flag in ("local", "fixed_price", "tradeable")):
            raise ValueError("商船不再是已证明的普通可贸易商品")
        collections = ("owned_buildings",)
        chain = (
            "country:any_scope_building->owned_building",
            "building:is_building_type+active_pm+level",
        )
    else:
        native = _child(reference(_COMPANY, "company_tashkent_railroad"), "possible")
        line = _exact(
            native,
            "any_scope_state",
            "state_region = s:STATE_FERGANA is_incorporated = yes has_building = building_railway "
            "custom_tooltip = { text = has_at_least_5_levels_of_railway_tt "
            "any_scope_building = { is_building_type = building_railway level >= 5 } }",
        )
        references.append(f"{_COMPANY}:{line}")
        railway = reference(_PRIVATE_BUILDING, "building_railway")
        expansion = _child(railway, "should_auto_expand")
        line = _exact(expansion, "state", "sg:transportation = { state_goods_pricier > 0.5 }")
        references.append(f"{_PRIVATE_BUILDING}:{line}")
        line = _exact(expansion, "state", "infrastructure_delta <= -20")
        references.append(f"{_PRIVATE_BUILDING}:{line}")
        if isinstance(query, RailInfrastructure):
            group = reference(_RAIL_GROUP, "pmg_base_building_railway")
            if "pmg_base_building_railway" not in _list(railway, "production_method_groups"):
                raise ValueError("铁路查询失去实际建筑到PM组关系")
            methods = (
                "pm_early_trains",
                "pm_steam_trains",
                "pm_steam_trains_principle_transport_3",
                "pm_electric_trains",
                "pm_electric_trains_principle_transport_3",
                "pm_diesel_trains",
                "pm_diesel_trains_principle_transport_3",
            )
            if _list(group, "production_methods") != methods:
                raise ValueError("铁路基础组必须完整非空且方式身份精确")
            for method_id in methods:
                method = reference(_PRIVATE_METHOD, method_id)
                scaled = _child(_child(method, "building_modifiers"), "workforce_scaled")
                if (
                    float(_scalar(scaled, "goods_output_transportation_add")) <= 0
                    or float(_scalar(scaled, "goods_input_engines_add")) <= 0
                ):
                    raise ValueError("铁路基础组不再共同产运输并消费引擎")
            good_id = "transportation"
        else:
            building = reference(_POWER_BUILDING, "building_power_plant")
            group = reference(_POWER_GROUP, "pmg_base_building_power_plant")
            if "pmg_base_building_power_plant" not in _list(building, "production_method_groups"):
                raise ValueError("电厂查询失去实际建筑到PM组关系")
            if _list(group, "production_methods") != (
                "pm_early_power_plant",
                "pm_coal-fired_plant",
                "pm_oil-fired_plant",
            ):
                raise ValueError("电厂基础组方式发生变化")
            for method_id in _list(group, "production_methods"):
                method = reference(_POWER_METHOD, method_id)
                scaled = _child(_child(method, "building_modifiers"), "workforce_scaled")
                if (
                    float(_scalar(scaled, "goods_output_electricity_add")) <= 0
                    or float(_scalar(scaled, "goods_input_engines_add")) <= 0
                ):
                    raise ValueError("电厂基础组不再共同产电并消费引擎")
            good_id = "electricity"
        good = reference(_GOODS, good_id)
        if _scalar(good, "local") != "yes":
            raise ValueError("公司本地商品查询失去真实local商品定义")
        collections = ("owned_states", "owned_state_buildings")
        chain = (
            "country:any_scope_state->owned_state",
            "state:any_scope_building->same_state_building",
        )
        if isinstance(query, RailInfrastructure):
            chain += ("state:infrastructure_delta[infrastructure_points]",)
        if isinstance(query, PowerScarcity) or query.minimum_transport_price is not None:
            chain += (
                f"state:sg:{good_id}->same_state_goods",
                "state_goods:state_goods_pricier[price_above_base_ratio]",
            )
    return CompiledQuery(expression, tuple(references), tuple(hashes), collections, chain)
