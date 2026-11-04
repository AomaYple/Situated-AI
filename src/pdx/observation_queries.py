"""Finite country observations, backed by complete native collection consumers.

Queries inspect owned states, buildings, political movements or interest groups. They do
not select a political direction or turn a future production method into a
research prerequisite. Rendering is pure; compilation verifies supplied native
sources and AST evidence without reading the installation or writing state.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from . import company_observations, technology_opportunities
from .model import Assignment, Block, Scalar
from .parser import parse_text
from .textio import normalized_text

QUERY_ENGINES = frozenset(
    {"any_political_movement", "any_scope_state", "any_scope_building", "any_interest_group"}
)
_ECONOMY = "common/laws/01_economic_system.txt"
_TRADE = "common/laws/01_trade_policy.txt"
_POWER = "common/laws/00_distribution_of_power.txt"
_AI = "common/scripted_triggers/00_ai_triggers.txt"
_PORTUGAL = "common/journal_entries/06_portugal_politics.txt"
_ACW = "common/journal_entries/00_acw_entries.txt"
_ART = "common/journal_entries/00_art_jes.txt"
_BUILDING = "common/buildings/06_urban_center.txt"
_GOVERNMENT_BUILDING = "common/buildings/07_government.txt"
_GROUP = "common/production_method_groups/06_urban_center.txt"
_METHOD = "common/production_methods/06_urban_center.txt"
_COMMUNISM = "common/journal_entries/00_communism.txt"
_GOVERNANCE = "common/laws/00_governance_principles.txt"
_ATHEISM = "events/law_events/state_atheism.txt"
_GFX = "common/scripted_triggers/00_gfx_route_graphics_triggers.txt"
_GOODS = "common/goods/00_goods.txt"
MARKET_CONSUMPTION_SOURCES = (_ATHEISM, _GFX, _GOODS)

# Normalized UTF-8, matching the production adapter input contract. These are
# source identities, not a claim that normalized strings retain raw BOM bytes.
SOURCE_HASHES = {
    "common/laws/01_policing.txt": "ce9b5e661196a0ff4dbca693f05a23709958d281ffaa8cadb0995786f575dc4e",
    "common/laws/00_citizenship.txt": "c277d2da3028f34381ba6e52a920db446a52e162d320cadb8fc6b256aaa7460f",
    "common/laws/00_church_and_state.txt": "ab06ce160ed7d49be9ff4694eda2213d777e98d8ca16d921ee94123963e0b174",
    "common/laws/01_land_reform.txt": "8576c5bb769ca0bc9c2e3e2d89fb2e2dffcd9b4d479c08b43ca00c639e98e82f",
    "common/laws/01_taxation.txt": "1f4b3d25b80277a43eacf7f7640dbcb7f0a24b35e107f7bb3baa5364c5ffdbae",
    "common/laws/02_labour_associations.txt": "47ec5d950de0c1fd409203b83aa3a56849a02c6977e69d7e21a4bacc2ca4ce45",
    "common/laws/02_migration.txt": "1ac367f9983e9542ee68a27c188f35669b0101cc2df6014c7499f1a5365b54a5",
    _ECONOMY: "5622b68492a6f57913ead582011980d2ea5c5f5d41c715261bc228b8b7f9f0e9",
    _TRADE: "1746b95df101101845abbcfd5b56306ec9646891302ce09b0895e453f4cac5f3",
    _POWER: "b16b4f8103ade4f61cf2890af6fd2834f8782856bab8b08c6ec5942522a00855",
    _AI: "d8da988122619e26e16ce17e8ac196337cdb8d1592f357c45ded4f8cb85d3698",
    _PORTUGAL: "3419343456182541870fc8de7c7c52c23bb6c9e7ec1deded06a7744d61e04316",
    _ACW: "6132f262affcfc038df2549a0d5cb6ae059bc9e7fb90a8a1fe2c14db5263ff3e",
    _ART: "e0e281573697439d31145c5bdbebb0298ce753acb54be894f9ce6c4f8fc230c5",
    _BUILDING: "c41ed5adb63e8f626e6394ce4f2f619bc8f229cafa3d8994271e2a66d1c2b0c5",
    _GOVERNMENT_BUILDING: "01867816e5cf623ebf50927c94b0c2b92b189c8ed31d78fd55fa79ab67976872",
    _GROUP: "7b63fad3a75067d6157790917fcc5eeb411e5405318f7f3873373be9e6f94871",
    _METHOD: "d9f0e653d3d0c1783fd4e9880fb58a6ada795d0ed3a3fdec011f0d1ce28da71f",
    _COMMUNISM: "fbe2ce3af236a3f49e146f445ba56957952ac910b68022cc0f69e94e8010072f",
    _GOVERNANCE: "481a2c32a6873a0d5d5682e50b056a91ffd1d41017742f171a105737d59be0f8",
    _ATHEISM: "cb39c1a5badc168a6480bd3a19fb67dc82cfa80c8da7bd830b2fad747e80cf8e",
    _GOODS: "496810f9b21012cb3ae764e4c0cd65aafa85b6079f96d3d2a6b3dece92a0afcc",
    _GFX: "1987790bebbf4de42b443a91e81709335bdac1f3ac473428c7b23f59a157939b",
}
LAW_SOURCES = {
    "law_no_police": "common/laws/01_policing.txt",
    "law_local_police": "common/laws/01_policing.txt",
    "law_dedicated_police": "common/laws/01_policing.txt",
    "law_militarized_police": "common/laws/01_policing.txt",
    "law_ethnostate": "common/laws/00_citizenship.txt",
    "law_national_supremacy": "common/laws/00_citizenship.txt",
    "law_racial_segregation": "common/laws/00_citizenship.txt",
    "law_cultural_exclusion": "common/laws/00_citizenship.txt",
    "law_multicultural": "common/laws/00_citizenship.txt",
    "law_state_religion": "common/laws/00_church_and_state.txt",
    "law_millet_system": "common/laws/00_church_and_state.txt",
    "law_people_of_the_book": "common/laws/00_church_and_state.txt",
    "law_freedom_of_conscience": "common/laws/00_church_and_state.txt",
    "law_total_separation": "common/laws/00_church_and_state.txt",
    "law_state_atheism": "common/laws/00_church_and_state.txt",
    "law_anti_strike_laws": "common/laws/02_labour_associations.txt",
    "law_canton_system": "common/laws/01_trade_policy.txt",
    "law_closed_borders": "common/laws/02_migration.txt",
    "law_collectivized_agriculture": "common/laws/01_land_reform.txt",
    "law_combination_acts": "common/laws/02_labour_associations.txt",
    "law_command_economy": "common/laws/01_economic_system.txt",
    "law_commercialized_agriculture": "common/laws/01_land_reform.txt",
    "law_consumption_based_taxation": "common/laws/01_taxation.txt",
    "law_cooperative_ownership": "common/laws/01_economic_system.txt",
    "law_corporatized_unions": "common/laws/02_labour_associations.txt",
    "law_expanded_latifundias": "common/laws/01_land_reform.txt",
    "law_extraction_economy": "common/laws/01_economic_system.txt",
    "law_factory_councils": "common/laws/02_labour_associations.txt",
    "law_graduated_taxation": "common/laws/01_taxation.txt",
    "law_guild_system": "common/laws/02_labour_associations.txt",
    "law_homesteading": "common/laws/01_land_reform.txt",
    "law_industry_banned": "common/laws/01_economic_system.txt",
    "law_interventionism": "common/laws/01_economic_system.txt",
    "law_isolationism": "common/laws/01_trade_policy.txt",
    "law_land_based_taxation": "common/laws/01_taxation.txt",
    "law_latifundias": "common/laws/01_land_reform.txt",
    "law_manorialism": "common/laws/01_land_reform.txt",
    "law_migration_controls": "common/laws/02_migration.txt",
    "law_no_migration_controls": "common/laws/02_migration.txt",
    "law_peasant_proprietorship": "common/laws/01_land_reform.txt",
    "law_per_capita_based_taxation": "common/laws/01_taxation.txt",
    "law_proportional_taxation": "common/laws/01_taxation.txt",
    "law_right_to_associate": "common/laws/02_labour_associations.txt",
    "law_sakoku": "common/laws/01_trade_policy.txt",
    "law_serfdom": "common/laws/01_land_reform.txt",
    "law_tenant_farmers": "common/laws/01_land_reform.txt",
    "law_traditionalism": "common/laws/01_economic_system.txt",
    "law_laissez_faire": _ECONOMY,
    "law_agrarianism": _ECONOMY,
    "law_free_trade": _TRADE,
    "law_mercantilism": _TRADE,
    "law_protectionism": _TRADE,
    "law_anarchy": _POWER,
}
ART_METHODS = frozenset(
    {"pm_traditional_art", "pm_realist_art", "pm_photographic_art", "pm_film_art"}
)
UNKNOWN_POLICY = (
    "missing_collection=unknown; complete_empty_collection=false; any_true=true; "
    "no_true_with_missing_member_observation=unknown; malformed_input=error"
)
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_INTEGER = re.compile(r"[1-9][0-9]*\Z")


@dataclass(frozen=True, slots=True)
class LawMovementSupport:
    law_id: str
    minimum_support: float = 0.10


@dataclass(frozen=True, slots=True)
class LawInterestGroupSupport:
    """Positive actual absolute stance, not preference over the current law."""

    law_id: str


@dataclass(frozen=True, slots=True)
class AnyStateMarketAccessBelow:
    threshold: float = 1.0


@dataclass(frozen=True, slots=True)
class AnyIncorporatedStateTaxCapacityShortfall:
    """A local comparison, without pooling capacity between different states."""


@dataclass(frozen=True, slots=True)
class AnyStateTurmoilAbove:
    threshold: float = 0.1


@dataclass(frozen=True, slots=True)
class OwnBuildingActiveMethod:
    building_id: str
    method_id: str
    minimum_level: int = 1


CountryQuery = (
    LawMovementSupport
    | LawInterestGroupSupport
    | AnyStateMarketAccessBelow
    | AnyIncorporatedStateTaxCapacityShortfall
    | AnyStateTurmoilAbove
    | OwnBuildingActiveMethod
    | company_observations.CompanyQuery
    | technology_opportunities.TechnologyQuery
)


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...]
    actor: Literal["country"] = "country"
    kind: Literal["boolean"] = "boolean"
    unknown_policy: str = UNKNOWN_POLICY
    world_scans: int = 0
    runtime_cost: str = "existential traversal of owned candidates; not constant time"


def _ratio(value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("查询比例必须为有限数值，不能用布尔或字符串")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1 or (positive and number == 0):
        raise ValueError("查询比例超出已登记的0到1范围")
    return number


def _decimal(value: object) -> float:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError("查询参数只接受无符号有限十进制字符串")
    return _ratio(float(value))


def from_reader(engine: str, parameters: Mapping[str, str]) -> CountryQuery:
    """Interpret exact existing Reader parameter identities, never free PDX."""
    if not isinstance(parameters, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in parameters.items()
    ):
        raise ValueError("查询参数必须为完整字符串映射")
    if "company_query" in parameters:
        return company_observations.from_reader(engine, parameters)
    if "technology_query" in parameters:
        return technology_opportunities.query_from_reader(engine, parameters)
    if engine == "any_political_movement" and set(parameters) == {"law", "minimum_support"}:
        query: CountryQuery = LawMovementSupport(
            parameters["law"], _decimal(parameters["minimum_support"])
        )
    elif engine == "any_interest_group" and set(parameters) == {"law"}:
        query = LawInterestGroupSupport(parameters["law"])
    elif engine == "any_scope_state" and set(parameters) == {"threshold"}:
        query = AnyStateMarketAccessBelow(_decimal(parameters["threshold"]))
    elif engine == "any_scope_state" and parameters == {"state_query": "tax_capacity_shortfall"}:
        query = AnyIncorporatedStateTaxCapacityShortfall()
    elif (
        engine == "any_scope_state"
        and set(parameters) == {"state_query", "threshold"}
        and parameters["state_query"] == "turmoil_above"
    ):
        query = AnyStateTurmoilAbove(_decimal(parameters["threshold"]))
    elif engine == "any_scope_building" and set(parameters) == {"building", "method", "min_level"}:
        level = parameters["min_level"]
        if not _INTEGER.fullmatch(level) or len(level) > 4:
            raise ValueError("建筑查询最低等级必须为1到1000的整数字符串")
        query = OwnBuildingActiveMethod(parameters["building"], parameters["method"], int(level))
    else:
        raise ValueError("未登记的国家聚合查询或参数形状")
    render(query)
    return query


def render(query: CountryQuery) -> str:
    """Pure fixed-template lowering, including type, ID and numeric guards."""
    if isinstance(query, company_observations.CompanyQuery):
        return company_observations.render(query)
    if isinstance(query, technology_opportunities.TechnologyQuery):
        return technology_opportunities.render_query(query)
    if type(query) is LawMovementSupport:
        if not isinstance(query.law_id, str) or query.law_id not in LAW_SOURCES:
            raise ValueError("运动查询的法律ID没有已登记的真实定义")
        support = _ratio(query.minimum_support)
        return (
            "any_political_movement = { "
            f"law_enactment_stance = {{ law = law_type:{query.law_id} value > neutral }} "
            f"political_movement_support >= {support!r} }}"
        )
    if type(query) is LawInterestGroupSupport:
        if not isinstance(query.law_id, str) or query.law_id not in LAW_SOURCES:
            raise ValueError("利益集团查询的法律ID没有已登记的真实定义")
        return (
            "any_interest_group = { "
            f"law_stance = {{ law = law_type:{query.law_id} value > neutral }} }}"
        )
    if type(query) is AnyStateMarketAccessBelow:
        threshold = _ratio(query.threshold, positive=True)
        return f"any_scope_state = {{ market_access < {threshold!r} }}"
    if type(query) is AnyIncorporatedStateTaxCapacityShortfall:
        return "any_scope_state = { is_incorporated = yes tax_capacity < tax_capacity_usage }"
    if type(query) is AnyStateTurmoilAbove:
        return f"any_scope_state = {{ turmoil > {_ratio(query.threshold)!r} }}"
    if type(query) is OwnBuildingActiveMethod:
        if query.building_id != "building_art_academy" or query.method_id not in ART_METHODS:
            raise ValueError("建筑/PM组合没有已登记的本国艺术建筑消费者证据")
        if type(query.minimum_level) is not int or not 1 <= query.minimum_level <= 1000:
            raise ValueError("建筑查询最低等级超出1到1000的接口范围，非游戏容量上限")
        return (
            f"any_scope_building = {{ is_building_type = {query.building_id} "
            f"has_active_production_method = {query.method_id} level >= {query.minimum_level} }}"
        )
    raise ValueError("未登记的查询类型，基础设施/汽车消费等模板仍不支持")


def required_sources(query: CountryQuery) -> tuple[str, ...]:
    render(query)
    if isinstance(query, company_observations.CompanyQuery):
        return company_observations.required_sources(query)
    if isinstance(query, technology_opportunities.TechnologyQuery):
        return technology_opportunities.required_query_sources(query)
    if isinstance(query, LawMovementSupport):
        return tuple(sorted({_ECONOMY, _AI, LAW_SOURCES[query.law_id]}))
    if isinstance(query, LawInterestGroupSupport):
        return tuple(sorted({_COMMUNISM, _GOVERNANCE, LAW_SOURCES[query.law_id]}))
    if isinstance(query, AnyStateMarketAccessBelow):
        return (_PORTUGAL,)
    if isinstance(query, AnyIncorporatedStateTaxCapacityShortfall):
        return tuple(sorted({_PORTUGAL, _GOVERNMENT_BUILDING}))
    if isinstance(query, AnyStateTurmoilAbove):
        return tuple(sorted({_PORTUGAL, _ACW}))
    return tuple(sorted({_ART, _BUILDING, _GROUP, _METHOD}))


def _child(block: Block, key: str) -> Block:
    entries = block.all(key)
    if (
        len(entries) != 1
        or entries[0].op != "="
        or entries[0].prefix is not None
        or not isinstance(entries[0].value, Block)
    ):
        raise ValueError(f"原版查询证据缺少唯一块：{key}")
    return entries[0].value


def _shape(block: Block) -> tuple:
    result = []
    for item in block.items:
        if not isinstance(item, Assignment) or item.prefix is not None:
            raise ValueError("原版查询AST含非普通赋值或匿名结构")
        value: object
        if isinstance(item.value, Block):
            value = _shape(item.value)
        elif isinstance(item.value, Scalar):
            value = item.value.unquoted
        else:
            raise ValueError("原版查询AST含未登记的无值结构")
        result.append((item.key, item.op, value))
    return tuple(result)


def _find_shape(block: Block, key: str, expected: tuple) -> int:
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
        raise ValueError(f"原版缺少唯一完整查询AST证据：{key}")
    return matches[0]


def _list(block: Block, key: str) -> tuple[str, ...]:
    child = _child(block, key)
    if any(not isinstance(item, Scalar) for item in child.items):
        raise ValueError(f"原版定义列表含未知结构：{key}")
    return tuple(item.unquoted for item in child.scalars())


def _scalar(block: Block, key: str) -> str:
    entries = block.all(key)
    if (
        len(entries) != 1
        or entries[0].op != "="
        or entries[0].prefix is not None
        or not isinstance(entries[0].value, Scalar)
    ):
        raise ValueError(f"原版观测证据缺少唯一普通标量：{key}")
    return entries[0].value.unquoted


def _verified_sources(
    names: tuple[str, ...], texts: Mapping[str, str]
) -> tuple[dict[str, Block], list[tuple[str, str]]]:
    roots = {}
    hashes = []
    for source in names:
        text = texts.get(source)
        if not isinstance(text, str):
            raise ValueError(f"国家观测缺少必需原版来源：{source}")
        text = normalized_text(text)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != SOURCE_HASHES[source]:
            raise ValueError(f"国家观测原版来源漂移：{source}")
        parsed = parse_text(text, path=source)
        if parsed.errors:
            raise ValueError(f"国家观测原版无法解析：{source}")
        roots[source] = parsed.root
        hashes.append((source, digest))
    return roots, hashes


def verify_market_consumption_sources(texts: Mapping[str, str]) -> tuple[str, ...]:
    """Prove the exact scalar path and car identity; never infer pop consumption.

    This supports only the typed ROOT.market.mg:automobiles total-consumption
    reader. The fixed country event supplies the numeric getter and scope;
    the car graphics template supplies the exact goods scope; the goods
    definition supplies the future pop-infrastructure mechanism. A positive
    value remains total market use, including non-pop and foreign consumers.
    """
    roots, _hashes = _verified_sources(MARKET_CONSUMPTION_SOURCES, texts)
    event = _child(roots[_ATHEISM], "state_atheism.1")
    if (_scalar(event, "type"), _scalar(event, "placement")) != ("country_event", "ROOT"):
        raise ValueError("原版消费数值见证不是精确国家ROOT事件")
    options = []
    for entry in event.all("option"):
        if entry.prefix is not None or entry.op != "=" or not isinstance(entry.value, Block):
            raise ValueError("原版消费事件含非普通option证据")
        if _scalar(entry.value, "name") == "state_atheism.1.c":
            options.append(entry.value)
    if len(options) != 1:
        raise ValueError("原版消费事件缺少唯一精确option")
    market = _child(_child(options[0], "trigger"), "market")
    if _shape(market) != (("mg:opium", "=", (("market_goods_consumption", ">", "100"),)),):
        raise ValueError("原版缺少完整country-market-goods消费数值AST")
    graphics = _child(
        _child(_child(roots[_GFX], "gfx_car_condition_trigger"), "scope:state"), "market"
    )
    if _shape(graphics) != (("mg:automobiles", "=", (("market_goods_sell_orders", ">=", "10"),)),):
        raise ValueError("原版缺少完整汽车market-goods作用域AST")
    automobile = _child(roots[_GOODS], "automobiles")
    if _scalar(automobile, "pop_consumption_can_add_infrastructure") != "yes":
        raise ValueError("原版汽车定义缺少人口消费基础设施机制")
    return (
        f"{_ATHEISM}:{market.all('mg:opium')[0].line}",
        f"{_GFX}:{graphics.all('mg:automobiles')[0].line}",
        f"{_GOODS}:{automobile.all('pop_consumption_can_add_infrastructure')[0].line}",
    )


def compile_query(
    query: CountryQuery, texts: Mapping[str, str]
) -> (
    CompiledQuery
    | company_observations.CompiledQuery
    | technology_opportunities.CompiledTechnologyQuery
):
    """Verify supplied pinned sources and complete consumers, without I/O."""
    if isinstance(query, company_observations.CompanyQuery):
        return company_observations.compile_query(query, texts)
    if isinstance(query, technology_opportunities.TechnologyQuery):
        return technology_opportunities.compile_query(query, texts)
    expression = render(query)
    roots, hashes = _verified_sources(required_sources(query), texts)
    references = []
    if isinstance(query, LawInterestGroupSupport):
        source = LAW_SOURCES[query.law_id]
        _child(roots[source], query.law_id)
        references.append(f"{source}:{roots[source].all(query.law_id)[0].line}")
        _child(roots[_GOVERNANCE], "law_council_republic")
        references.append(f"{_GOVERNANCE}:{roots[_GOVERNANCE].all('law_council_republic')[0].line}")
        country = _child(roots[_COMMUNISM], "je_communism_1")
        limit = _child(_child(_child(_child(country, "on_fail"), "else"), "if"), "limit")
        original = _child(limit, "any_interest_group")
        expected = (
            (
                "law_stance",
                "=",
                (("law", "=", "law_type:law_council_republic"), ("value", ">", "neutral")),
            ),
        )
        if _shape(original) != expected:
            raise ValueError("原版利益集团查询缺少完整法律立场AST证据")
        references.append(f"{_COMMUNISM}:{limit.all('any_interest_group')[0].line}")
        collections = ("owned_interest_groups",)
    elif isinstance(query, LawMovementSupport):
        definition = roots[LAW_SOURCES[query.law_id]].all(query.law_id)
        _child(roots[LAW_SOURCES[query.law_id]], query.law_id)
        references.append(f"{LAW_SOURCES[query.law_id]}:{definition[0].line}")
        enactment = _child(_child(roots[_ECONOMY], "law_laissez_faire"), "ai_enact_weight_modifier")
        line = _find_shape(
            enactment,
            "any_political_movement",
            (
                (
                    "law_enactment_stance",
                    "=",
                    (("law", "=", "law_type:law_laissez_faire"), ("value", ">", "neutral")),
                ),
                ("political_movement_support", ">=", "0.10"),
            ),
        )
        references.append(f"{_ECONOMY}:{line}")
        generic = _child(roots[_AI], "ai_has_reasons_to_not_oppose_law")
        line = _find_shape(
            generic,
            "law_enactment_stance",
            (
                ("law", "=", "scope:law.type"),
                ("value", ">", "neutral"),
            ),
        )
        references.append(f"{_AI}:{line}")
        collections = ("owned_political_movements",)
    elif isinstance(query, AnyIncorporatedStateTaxCapacityShortfall):
        completion = _child(
            _child(roots[_PORTUGAL], "je_portugal_regeneration_public_works"), "complete"
        )
        line = _find_shape(
            completion,
            "any_scope_state",
            (
                ("filter", "=", (("is_incorporated", "=", "yes"),)),
                ("has_building", "=", "building_railway"),
                ("percent", "=", "1"),
            ),
        )
        references.append(f"{_PORTUGAL}:{line}")
        building = _child(roots[_GOVERNMENT_BUILDING], "building_government_administration")
        tax_expected = (
            ("occupancy", ">=", "0.8"),
            (
                "OR",
                "=",
                (
                    ("state.tax_capacity", "<", "state.tax_capacity_usage"),
                    ("owner", "=", (("bureaucracy", "<", "-10"),)),
                ),
            ),
        )
        if _shape(_child(building, "should_auto_expand")) != tax_expected:
            raise ValueError("原版税容量观测缺少完整同州比较AST证据")
        references.append(f"{_GOVERNMENT_BUILDING}:{building.all('should_auto_expand')[0].line}")
        collections = ("owned_states",)
    elif isinstance(query, AnyStateTurmoilAbove):
        completion = _child(
            _child(roots[_PORTUGAL], "je_portugal_regeneration_public_works"), "complete"
        )
        line = _find_shape(
            _child(completion, "NOT"), "any_scope_state", (("market_access", "<", "1"),)
        )
        references.append(f"{_PORTUGAL}:{line}")
        original = _child(_child(_child(roots[_ACW], "je_acw_wild_wild_west"), "complete"), "NOT")
        line = _find_shape(
            original,
            "any_scope_state",
            (
                (
                    "state_region",
                    "=",
                    (
                        (
                            "OR",
                            "=",
                            (("is_homeland", "=", "cu:dixie"), ("is_homeland", "=", "cu:yankee")),
                        ),
                    ),
                ),
                ("devastation", ">", "0.1"),
                ("turmoil", ">", "0.1"),
            ),
        )
        references.append(f"{_ACW}:{line}")
        collections = ("owned_states",)
    elif isinstance(query, AnyStateMarketAccessBelow):
        completion = _child(
            _child(roots[_PORTUGAL], "je_portugal_regeneration_public_works"), "complete"
        )
        original = _child(completion, "NOT")
        line = _find_shape(original, "any_scope_state", (("market_access", "<", "1"),))
        references.append(f"{_PORTUGAL}:{line}")
        collections = ("owned_states",)
    elif isinstance(query, OwnBuildingActiveMethod):
        traditional = _child(_child(roots[_ART], "je_romanticism"), "complete")
        line = _find_shape(
            traditional,
            "any_scope_building",
            (
                ("is_building_type", "=", "building_art_academy"),
                ("has_active_production_method", "=", "pm_traditional_art"),
                ("occupancy", ">=", "0.9"),
                ("level", ">=", "2"),
            ),
        )
        references.append(f"{_ART}:{line}")
        photographic = _child(_child(roots[_ART], "je_camera"), "complete")
        line = _find_shape(
            photographic,
            "any_scope_building",
            (
                ("is_building_type", "=", "building_art_academy"),
                ("level", ">=", "5"),
                ("has_active_production_method", "=", "pm_photographic_art"),
            ),
        )
        references.append(f"{_ART}:{line}")
        building = _child(roots[_BUILDING], query.building_id)
        if "pmg_base_building_art_academy" not in _list(building, "production_method_groups"):
            raise ValueError("艺术建筑缺少真实生产方式组隶属")
        group = _child(roots[_GROUP], "pmg_base_building_art_academy")
        if query.method_id not in _list(group, "production_methods"):
            raise ValueError("艺术PM不属于已证明的建筑方式组")
        _child(roots[_METHOD], query.method_id)
        for source, key in (
            (_BUILDING, query.building_id),
            (_GROUP, "pmg_base_building_art_academy"),
            (_METHOD, query.method_id),
        ):
            references.append(f"{source}:{roots[source].all(key)[0].line}")
        collections = ("owned_buildings",)
    else:
        raise ValueError("未登记的查询类型")
    return CompiledQuery(expression, tuple(references), tuple(hashes), collections)
