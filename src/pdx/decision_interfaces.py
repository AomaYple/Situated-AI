"""已审计脚本接口的类型边界；静态契约不代替引擎实测。

只接受有原版消费者依据的作用域转换，不能用“各个词都出现过”证明
它们可以任意拼接。增加接口时同时补来源、类型、消费者和反例。
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

from . import observation_queries
from .model import Assignment, Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from .decision_rules import Reader, RuleSet
    from .event_opportunities import EventProgram
    from .situated.decision_ir import EvaluationContext
    from .treaty_acceptance_opportunities import AcceptanceProgram


_LJ10_EVIDENCE = Path(__file__).resolve().parents[2] / (
    "research/situated/victoria3-1.15.0-defensive-pact-reader.json"
)
_LJ10_EVIDENCE_SHA256 = "28233903a12affc8b5478a3484d2f73f3c930e3ea6fb601d9899d0193ea10d8e"
SCRIPTED_PREDICATE_SOURCE = Path(__file__).resolve().parents[2] / (
    "research/situated/victoria3-1.15.0-scripted-predicate.json"
)
SCRIPTED_PREDICATE_SHA256 = "e96d22eb906bc39bced42bc6d17b1690fac5959e916f9de4defe8639d4c52a7d"


def scripted_trigger_snapshot() -> bytes:
    """Identify the exact historical scripted predicate, never a builtin getter."""
    raw = SCRIPTED_PREDICATE_SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SCRIPTED_PREDICATE_SHA256:
        raise ValueError("原版脚本布尔谓词冻结证据漂移")
    data = json.loads(raw)
    if data.get("reader") != {
        "engine": "any_insurrection_ongoing",
        "origin": "scripted_trigger",
        "scope": "root",
        "result": "boolean",
        "unit": "boolean",
        "source": "common/scripted_triggers/00_scripted_triggers.txt",
        "line": 1243,
        "definition": (
            "any_insurrection_ongoing = { any_political_movement = { is_insurrectionary = yes } }"
        ),
    }:
        raise ValueError("原版脚本布尔谓词精确合同漂移")
    return raw


def _insurrection_predicate_definition(item: Assignment) -> bool:
    if item.op != "=" or item.prefix is not None or not isinstance(item.value, Block):
        return False
    if len(item.value.items) != 1:
        return False
    movement = item.value.items[0]
    if (
        not isinstance(movement, Assignment)
        or movement.key != "any_political_movement"
        or movement.op != "="
        or movement.prefix is not None
        or not isinstance(movement.value, Block)
        or len(movement.value.items) != 1
    ):
        return False
    predicate = movement.value.items[0]
    return (
        isinstance(predicate, Assignment)
        and predicate.key == "is_insurrectionary"
        and predicate.op == "="
        and predicate.prefix is None
        and isinstance(predicate.value, Scalar)
        and not predicate.value.quoted
        and predicate.value.text == "yes"
    )


def verify_scripted_trigger_game(game: Path) -> tuple[tuple[str, str], ...]:
    """Require pinned native sources and one exact AST at production boundaries."""
    data = json.loads(scripted_trigger_snapshot())
    sources = data["sources"]
    actual = {
        path.relative_to(game).as_posix(): path
        for path in (game / "common/scripted_triggers").rglob("*.txt")
        if path.is_file()
    }
    if set(actual) != set(sources):
        raise ValueError("原版脚本布尔谓词来源集合漂移")
    definitions: list[tuple[str, Assignment]] = []
    for source, path in sorted(actual.items()):
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sources[source]:
            raise ValueError(f"原版脚本布尔谓词来源SHA漂移：{source}")
        parsed = parse_text(raw.decode("utf-8-sig"))
        if parsed.errors:
            raise ValueError(f"原版脚本布尔谓词来源无法解析：{source}")
        definitions.extend(
            (source, item)
            for item in parsed.top_assignments
            if item.key == "any_insurrection_ongoing"
        )
    if (
        len(definitions) != 1
        or definitions[0][0] != data["reader"]["source"]
        or not _insurrection_predicate_definition(definitions[0][1])
    ):
        raise ValueError("原版脚本布尔谓词缺少唯一精确AST定义")
    return tuple(sorted(sources.items()))


def proven_reader_words() -> frozenset[str]:
    """Pinned 1.15.0 static reader evidence; current game identity is a separate gate.

    The manifest contains verified executable observations and original script
    hashes. It extends token discovery only; reader_scope still enforces exact
    own-Country signatures and does not grant arbitrary foreign-scope access.
    """
    raw = _LJ10_EVIDENCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _LJ10_EVIDENCE_SHA256:
        raise ValueError("LJ10 读取器冻结证据字节漂移")
    manifest = json.loads(raw)
    semantic = {
        key: value
        for key, value in manifest.items()
        if key
        not in {"exe", "observations", "script_hashes", "lineage", "supplemental_guard_evidence"}
    }
    if (
        hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        != "6b4a321d90617a95af89a04285f8cad6895f6ccf78a0e7e2ecc07b9d73cc5972"
    ):
        raise ValueError("LJ10 当前读取器/同ROOT严格比较合同漂移")
    if manifest["exe"]["sha256"] != (
        "473186e8d8deba993651e0ae4cf02a003b02f5accb99b096a6a0a8bd9506cbaa"
    ):
        raise ValueError("LJ10 读取器原版引擎身份漂移")
    return frozenset(
        [manifest["reader"]["engine"]]
        + [item["engine"] for item in manifest["positive_native_guard"]["readers"]]
    )


def verify_lj10_game(game: Path) -> tuple[tuple[str, str], ...]:
    """Recheck current native spans and exact original scripts at production gates."""
    from .situated import engine_scope  # noqa: PLC0415

    proven_reader_words()
    manifest = json.loads(_LJ10_EVIDENCE.read_bytes())
    _, hashes, verified = engine_scope._verified_manifest(
        game,
        {source: (game / source).read_bytes() for source in manifest["script_hashes"]},
        _LJ10_EVIDENCE,
        _LJ10_EVIDENCE.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
        _LJ10_EVIDENCE_SHA256,
        "LJ10 当前读取器与严格比较证据",
    )
    if not verified:
        raise ValueError("LJ10 当前原版脚本或EXE与锁定证据不一致")
    from .situated.native_treatments import _digest  # noqa: PLC0415

    for source, field, expected in (
        (
            "common/script_values/ai_script_values.txt",
            ("wanted_army_size_script_value",),
            "18a212ac494c4fafcde60204027574fc8c85cbf096215a4b74319dbc9129a413",
        ),
        (
            "common/script_values/ai_script_values.txt",
            ("wanted_marines_size_script_value",),
            "d667859e1e8f50b41a0dd3060d0f3940a052164fe7d45cb1d1704718fe9c2988",
        ),
        (
            "common/ai_strategies/00_default_strategy.txt",
            ("ai_strategy_default", "wanted_army_size"),
            "392c3d8c378e6f6b40947ae539dbf219b64753561028eb51a8c80a6e11e6a8a8",
        ),
    ):
        parsed = parse_text((game / source).read_text(encoding="utf-8-sig"))
        if parsed.errors:
            raise ValueError("LJ10 当前原版比较公式无法解析")
        block = parsed.root
        for part in field:
            rows = block.all(part)
            if len(rows) != 1 or not isinstance(rows[0].value, Block):
                raise ValueError("LJ10 当前原版比较公式缺失或重复")
            block = rows[0].value
        if _digest(rows[0]) != expected:
            raise ValueError("LJ10 当前原版比较公式完整AST漂移")
    return hashes


_COUNTRY_BOOLEAN = frozenset(
    {
        "is_ai",
        "in_default",
        "is_at_war",
        "taking_loans",
        "is_subject",
        "is_subject_of",
        "has_insurrectionary_interest_groups",
        "has_variable",
        "has_law_or_variant",
        "has_strategy",
        "has_technology_researched",
        "has_truce_with",
        "has_diplomatic_pact",
        "has_treaty_alliance_with",
        "has_institution",
        "is_diplomatic_play_target",
        "is_diplomatic_play_initiator",
    }
)
_COUNTRY_NUMBER = frozenset(
    {
        "army_size",
        "navy_size",
        "average_sol",
        "bureaucracy",
        "produced_bureaucracy",
        "fixed_income",
        "gdp",
        "gold_reserves",
        "infamy",
        "legitimacy",
        "liberty_desire",
        "literacy_rate",
        "total_population",
        "pop_type_percent_country",
        "radical_fraction",
        "scaled_debt",
        "net_total_income",
        "weeks_until_bankruptcy",
        "modifier:country_tech_spread_mult",
        "relations:root",
        "country_fervor_primary_culture",
        "num_defensive_pacts",
        "wanted_army_size_script_value",
        "wanted_marines_size_script_value",
        "num_companies",
        "max_num_companies",
        "authority",
        "influence",
        "institution_investment_level",
        "prestige",
        "num_alliances",
    }
)
_STATE_NUMBER = frozenset(
    {
        "infrastructure_delta",
        "market_access",
        "state_unemployment_rate",
        "state_population",
        "tax_capacity",
        "tax_capacity_usage",
        "devastation",
    }
)
_INPUTS = {
    **dict.fromkeys(_COUNTRY_BOOLEAN, ("country", "boolean")),
    **dict.fromkeys(_COUNTRY_NUMBER, ("country", "number")),
    **dict.fromkeys(_STATE_NUMBER, ("state", "number")),
    "is_treaty_port": ("state", "boolean"),
    "is_incorporated": ("state", "boolean"),
    "is_mass_migration_target": ("state", "boolean"),
    "is_production_method_active": ("state", "boolean"),
    "is_homeland_of_country_cultures": ("state", "boolean"),
    "owner": ("state", "boolean"),
    "is_isolated_from_market": ("state", "boolean"),
    "primary_cultures_percent_state": ("state", "number"),
    "pop_type_percent_state": ("state", "number"),
    "ig_clout": ("interest_group", "number"),
    "ig_approval": ("interest_group", "number"),
    "is_in_government": ("interest_group", "boolean"),
    "state_goods_pricier": ("state_goods", "number"),
    "market_goods_pricier": ("market_goods", "number"),
    "market_goods_delta": ("market_goods", "number"),
    "market_goods_consumption": ("market_goods", "number"),
}
_UNITS = {
    "army_size": "battalions",
    "navy_size": "ships",
    "average_sol": "standard_of_living",
    "bureaucracy": "capacity_balance",
    "produced_bureaucracy": "capacity_output",
    "authority": "capacity_balance",
    "influence": "capacity_balance",
    "num_companies": "company_count",
    "max_num_companies": "company_count",
    "institution_investment_level": "institution_level",
    "prestige": "prestige_points",
    "num_alliances": "alliance_count",
    "fixed_income": "currency_per_week",
    "net_total_income": "currency_per_week",
    "gdp": "annual_gdp_currency",
    "gold_reserves": "currency",
    "infamy": "infamy_points",
    "legitimacy": "legitimacy_0_100",
    "liberty_desire": "liberty_0_100",
    "literacy_rate": "ratio",
    "total_population": "persons",
    "state_population": "persons",
    "pop_type_percent_country": "ratio",
    "radical_fraction": "ratio",
    "scaled_debt": "debt_to_credit_ratio",
    "weeks_until_bankruptcy": "weeks",
    "modifier:country_tech_spread_mult": "modifier_ratio",
    "relations:root": "relations_minus100_100",
    "country_fervor_primary_culture": "fervor_points",
    "primary_cultures_percent_state": "ratio",
    "pop_type_percent_state": "ratio",
    "ig_clout": "ratio",
    "ig_approval": "approval_points",
    "infrastructure_delta": "infrastructure_points",
    "devastation": "ratio",
    "market_access": "ratio",
    "state_unemployment_rate": "ratio",
    "tax_capacity": "tax_capacity_points",
    "tax_capacity_usage": "tax_capacity_points",
    "num_defensive_pacts": "treaty_article_count",
    "wanted_army_size_script_value": "barracks_levels",
    "wanted_marines_size_script_value": "barracks_levels",
    "state_goods_pricier": "price_above_base_ratio",
    "market_goods_pricier": "price_above_base_ratio",
    "market_goods_delta": "sell_minus_buy_orders",
    "market_goods_consumption": "total_consumption_units",
}


def reader_scope(
    reader: Reader,
    actor_path: tuple[str, ...],
    *,
    native_root: str | None = None,
    source: str | None = None,
    field: tuple[str, ...] | None = None,
    context: EvaluationContext | None = None,
) -> str:
    """解析本生成器明确支持的有限转换，不猜测任意具名词的类型。"""
    root = native_root if native_root is not None else "state" if actor_path else "country"
    if reader.engine.startswith("scope:") or reader.key == "negotiation_amenability":
        from . import negotiation_context  # noqa: PLC0415

        if reader.engine != "scope:target_region":
            negotiation_context.validate_reader(reader, actor_path, root)
            return "country"
    if reader.key.startswith("commitment_") or "military_commitment_query" in dict(
        reader.parameters
    ):
        from . import treaty_acceptance_opportunities as acceptance  # noqa: PLC0415

        definition = field[0] if field else None
        if definition not in acceptance.COMMITMENTS:
            raise ValueError("军事承诺读取器只授权精确四类条约接受字段")
        program = acceptance.compile_program(definition)
        if (
            root != "country"
            or actor_path
            or source != program.source
            or field != program.field_path
            or context != program.evaluation_context()
            or reader not in program.readers()
        ):
            raise ValueError("军事承诺读取器必须保持精确条约、ROOT和互惠/有向角色上下文")
        return "country"
    if (
        reader.key == "regional_resource_opportunity"
        or reader.engine == "scope:target_region"
        or "regional_resource_query" in dict(reader.parameters)
    ):
        from . import regional_resource_opportunities as regional  # noqa: PLC0415

        regional_program = regional.compile_program()
        if (
            root != "country"
            or actor_path
            or reader not in regional_program.readers()
            or source != regional_program.source
            or field != regional_program.field_path
            or context != regional_program.evaluation_context()
        ):
            raise ValueError("区域资源读取器只授权精确殖民立场与已证明target_region上下文")
        return "country"
    if (
        reader.key.startswith("hokkaido_")
        or reader.scope == "hokkaido_state_scope"
        or reader.engine == "hokkaido_observation"
        or "event_hokkaido_query" in dict(reader.parameters)
    ):
        from . import event_opportunities  # noqa: PLC0415

        return event_opportunities.validate_hokkaido_reader(
            reader, source, field, context, actor_path=actor_path, native_root=root
        )
    if reader.key.startswith("sol_response_") or reader.scope == "slums_state":
        from . import event_opportunities  # noqa: PLC0415

        event_program = next(
            p for p in event_opportunities.compile_programs() if p.option == "sol_events.6.a"
        )
        expected = {item.key: item for item in event_program.readers()}
        if root != "country" or actor_path or expected.get(reader.key) != reader:
            raise ValueError("生活水平响应只授权精确保存slums_state与本国ROOT读取器")
        return "country" if reader.scope == "root" else "state"
    if reader.key.startswith("military_") and reader.key in {
        "military_article_exists",
        "military_source_exists",
        "military_target_exists",
        "military_active_exists",
        "military_renegotiation_exists",
        "military_default",
        "military_income",
        "military_expenses",
        "military_existing_source_commitment",
    }:
        from . import treaty_acceptance_opportunities as acceptance  # noqa: PLC0415

        expected = {
            item.key: item for item in acceptance.compile_program("military_assistance").readers()
        }
        if root != "country" or actor_path or expected.get(reader.key) != reader:
            raise ValueError("军事援助只授权本国ROOT精确首次承诺读取器")
        return "country"
    if reader.engine == "produced_bureaucracy" and (
        root != "country"
        or actor_path
        or reader.key != "olympic_bureaucracy_output"
        or reader.scope != "root"
        or reader.path
        or reader.kind != "number"
        or reader.unit != "capacity_output"
        or reader.minimum != 0
        or reader.maximum is not None
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
    ):
        raise ValueError("赛事行政产出必须保持精确本国ROOT数值签名")
    if reader.engine == "modifier:country_tech_spread_mult" and (
        root != "country"
        or actor_path
        or reader.key != "knowledge_donor_spread"
        or reader.scope != "root"
        or reader.kind != "number"
        or reader.unit != "modifier_ratio"
        or reader.path
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
        or reader.minimum is not None
        or reader.maximum is not None
    ):
        raise ValueError("科技共享传播修正必须保持精确本国ROOT无界数值签名")
    if reader.engine == "state_population":
        from . import event_opportunities  # noqa: PLC0415

        if (
            root != "country"
            or actor_path
            or reader.scope not in event_opportunities.DISASTER_SCOPES
            or reader.key != "disaster_" + reader.scope + "_population"
            or reader.kind != "number"
            or reader.unit != "persons"
            or reader.minimum != 0
            or reader.maximum is not None
            or reader.path
            or reader.argument is not None
            or reader.parameters
            or reader.value_field is not None
        ):
            raise ValueError("灾害人口读取器必须是精确保存州的state_population合同")
        return "state"
    if "event_disaster_query" in dict(reader.parameters):
        from . import event_opportunities  # noqa: PLC0415

        mode = dict(reader.parameters)["event_disaster_query"]
        if (
            root != "country"
            or actor_path
            or reader.scope != "crop_fail_state"
            or reader.key != "disaster_crop_fail_state_farm_" + mode
            or reader.kind != "boolean"
            or reader.unit != "boolean"
            or reader.minimum is not None
            or reader.maximum is not None
            or reader.path
            or reader.argument is not None
            or reader.value_field is not None
        ):
            raise ValueError("灾害农业暴露必须是精确保存作物歉收州的固定查询")
        event_opportunities.disaster_query_from_reader(reader.engine, dict(reader.parameters))
        return "state"
    if reader.engine == "is_mass_migration_target" and (
        root != "state"
        or actor_path != ("owner",)
        or reader.scope != "root"
        or reader.path
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
        or reader.minimum is not None
        or reader.maximum is not None
        or reader.kind != "boolean"
        or reader.unit != "boolean"
    ):
        raise ValueError(f"大迁移目标必须保持真实候选州ROOT无参数布尔合同：{reader.key}")
    if reader.engine == "pop_type_percent_state" and (
        root != "state"
        or reader.scope != "root"
        or reader.path
        or reader.argument is not None
        or reader.parameters != (("target", "pop_type:peasants"),)
        or reader.value_field != "value"
        or reader.minimum != 0
        or reader.maximum != 1
    ):
        raise ValueError(f"农民比例必须保持候选州ROOT精确peasants参数合同：{reader.key}")
    if reader.engine in {"tax_capacity", "tax_capacity_usage", "is_incorporated"} and (
        root != "state"
        or reader.scope != "root"
        or reader.path
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
    ):
        raise ValueError(f"地方征税读取器必须保持候选州ROOT无参数合同：{reader.key}")
    if not isinstance(root, str) or (root, actor_path) not in {
        ("country", ()),
        ("state", ("owner",)),
        ("military_formation", ("owner",)),
    }:
        raise ValueError("读取器原生ROOT类型与AI所有者路径不一致")
    if reader.engine == "devastation" and (
        root != "state"
        or actor_path != ("owner",)
        or reader.scope != "root"
        or reader.path
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
        or reader.kind != "number"
        or reader.unit != "ratio"
        or reader.minimum != 0
        or reader.maximum != 1
    ):
        raise ValueError(f"受创比例必须保持精确候选州ROOT、ratio和[0,1]合同：{reader.key}")
    if reader.engine == "any_insurrection_ongoing":
        scripted_trigger_snapshot()
        if (
            reader.scope != "root"
            or actor_path
            or reader.kind != "boolean"
            or reader.unit != "boolean"
            or reader.argument is not None
            or reader.path
            or reader.parameters
            or reader.value_field is not None
            or reader.minimum is not None
            or reader.maximum is not None
        ):
            raise ValueError(f"原版脚本布尔谓词必须保持精确国家ROOT无参数合同：{reader.key}")
        return "country"
    if reader.engine == "market_goods_consumption" and (
        reader.scope != "root"
        or actor_path
        or reader.path != ("market", "mg:automobiles")
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
        or reader.minimum != 0
        or reader.maximum is not None
    ):
        raise ValueError(f"汽车消费代理必须保持精确所属市场总消费签名：{reader.key}")
    if reader.engine in observation_queries.QUERY_ENGINES:
        if (
            reader.scope != "root"
            or actor_path
            or reader.path
            or reader.kind != "boolean"
            or reader.unit != "boolean"
            or reader.argument is not None
            or reader.value_field is not None
            or reader.minimum is not None
            or reader.maximum is not None
        ):
            raise ValueError(f"本国聚合观测必须保持国家ROOT布尔合同：{reader.key}")
        observation_queries.from_reader(reader.engine, dict(reader.parameters))
        return "country"
    if reader.engine in {"has_institution", "institution_investment_level"}:
        institutions = {
            "institution_police",
            "institution_schools",
            "institution_health_system",
            "institution_social_security",
            "institution_workplace_safety",
            "institution_home_affairs",
            "institution_colonial_affairs",
        }
        numeric = reader.engine == "institution_investment_level"
        identifier = dict(reader.parameters).get("institution") if numeric else reader.argument
        if (
            reader.scope != "root"
            or actor_path
            or reader.path
            or identifier not in institutions
            or (
                numeric
                and (
                    reader.argument is not None
                    or reader.value_field != "value"
                    or set(dict(reader.parameters)) != {"institution"}
                    or reader.minimum != 0
                )
            )
            or (
                not numeric
                and (
                    reader.parameters
                    or reader.value_field is not None
                    or reader.minimum is not None
                )
            )
            or reader.maximum is not None
        ):
            raise ValueError(f"制度读取器偏离已证明的国家 ROOT、制度定义与参数合同：{reader.key}")
    if reader.engine in {
        "prestige",
        "num_alliances",
        "is_diplomatic_play_target",
        "is_diplomatic_play_initiator",
    } and (
        reader.scope != "root"
        or actor_path
        or reader.path
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
        or reader.maximum is not None
        or reader.minimum != (0 if reader.engine in {"prestige", "num_alliances"} else None)
    ):
        raise ValueError(f"外交/声望观测必须保持精确本国 ROOT 签名：{reader.key}")
    decree_authority = (
        reader.key == "decree_relief_owner_authority"
        and reader.engine == "authority"
        and native_root == "state"
        and actor_path == ("owner",)
        and reader.scope == "root"
        and reader.path == ("owner",)
        and reader.kind == "number"
        and reader.unit == "capacity_balance"
        and reader.argument is None
        and not reader.parameters
        and reader.value_field is None
        and reader.minimum is None
        and reader.maximum is None
    )
    if (
        reader.engine in {"num_companies", "max_num_companies", "authority"}
        and not decree_authority
        and (
            reader.scope != "root"
            or actor_path
            or reader.path
            or reader.argument is not None
            or reader.parameters
            or reader.value_field is not None
            or reader.maximum is not None
            or reader.minimum != (None if reader.engine == "authority" else 0)
        )
    ):
        raise ValueError(f"公司容量与权威余额仅支持已证明的国家 ROOT 数值合同：{reader.key}")
    # 1.15.0 Windows reader/consumer证据只授权本国根；条款数量不是履约或军力。
    # 固定依据见 research/situated/victoria3-1.15.0-defensive-pact-reader.json。
    if reader.engine == "num_defensive_pacts" and (
        reader.scope != "root"
        or actor_path
        or reader.path
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
        or reader.minimum != 0
        or reader.maximum is not None
    ):
        raise ValueError(f"防御协定条款计数只支持本国根的无参数计数合同：{reader.key}")
    if reader.engine in {"wanted_army_size_script_value", "wanted_marines_size_script_value"} and (
        reader.scope != "root"
        or actor_path
        or reader.path
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
        or reader.minimum is not None
        or reader.maximum is not None
    ):
        raise ValueError(f"原版军备基值只支持本国根的无参数数值合同：{reader.key}")
    # country_state 生成的协调触发器在国家消费者时机读取；它们是
    # 无持久状态的布尔事实，不是原版 getter，也不需要伪造底本词汇证据。
    if reader.engine.startswith("sitai_context_"):
        from . import country_coordination  # noqa: PLC0415 - 不引入状态层循环依赖

        if (
            reader.engine
            not in {country_coordination.PREFIX + name for name in country_coordination.NAMES}
            or reader.kind != "boolean"
            or reader.unit != "boolean"
            or reader.scope != "root"
            or reader.path != actor_path
            or reader.argument is not None
            or reader.parameters
            or reader.value_field is not None
            or reader.minimum is not None
            or reader.maximum is not None
        ):
            raise ValueError(f"协调触发器必须使用已拥有的国家布尔合同：{reader.key}")
        return "country"
    scope = {
        "target_state": "state",
        "interest_group": "interest_group",
    }.get(reader.scope, "country")
    if reader.scope == "root":
        scope = root
    for part in reader.path:
        if scope in {"state", "military_formation"} and part == "owner":
            scope = "country"
        elif scope == "country" and part == "market":
            scope = "market"
        elif (
            scope == "country"
            and part == "overlord"
            and reader.scope == "root"
            and reader.path == ("overlord",)
            and reader.engine == "relations:root"
            and reader.key == "actual_overlord_relations"
        ):
            # This is the actor's real relationship, not scope:overlord supplied
            # by the separate become-subject candidate consumer.
            scope = "country"
        elif scope == "country" and part in {"ig:ig_trade_unions", "ig:ig_landowners"}:
            scope = "interest_group"
        elif scope == "market" and part.startswith("mg:"):
            scope = "market_goods"
        elif scope == "state" and part.startswith("sg:"):
            scope = "state_goods"
        else:
            raise ValueError(f"读取器没有已审计的作用域转换：{reader.key}/{part}")
    if _INPUTS.get(reader.engine) != (scope, reader.kind):
        raise ValueError(f"读取器类型或作用域与静态接口签名不一致：{reader.key}")
    if reader.unit != _UNITS.get(reader.engine, "boolean"):
        raise ValueError(f"读取器单位与静态接口签名不一致：{reader.key}")
    return scope


def validate(rules: RuleSet) -> None:
    """同时核对消费者提供的具名上下文和每步读取类型。"""
    from .mobilization_opportunities import CANDIDATE_IDS  # noqa: PLC0415

    readers = {reader.key: reader for reader in rules.readers}
    for reader in rules.readers:
        reader_scope(reader, rules.actor_path, native_root=rules.native_root)
    for rule in rules.rules:
        field = rule.field[1:] if rule.field[0] == "ai_strategy_default" else rule.field
        if any(readers[key].engine == "scope:amenability" for key in rule.input_keys()):
            negotiation_values = {
                "remaining_organized_negotiation_need": 0.1,
                "lj08_negotiation_local_political_capacity": 0.25,
            }
            conditions = {(p.fact, p.op, p.value) for p in rule.conditions}
            if (
                field != ("negotiation_chance",)
                or rule.id not in negotiation_values
                or rule.operation != "add"
                or rule.value != negotiation_values[rule.id]
                or rule.contribution_group != "organized_negotiation_need"
                or not {
                    ("negotiation_amenability", ">", 0),
                    ("negotiation_amenability", "<=", 1),
                    ("radical_share", ">=", 0.25),
                }
                <= conditions
            ):
                raise ValueError("谈判amenability只授权有界迁移政策及精确接受窗口")
        if any(
            readers[key].engine == "modifier:country_tech_spread_mult" for key in rule.input_keys()
        ) and (
            field != ("da_knowledge_sharing", "ai", "propose_score")
            or rules.native_root != "country"
            or rules.actor_path
            or rule.operation != "multiply"
            or not 0.8 <= rule.value < 1
            or rule.semantic_role != "cost"
        ):
            raise ValueError("传播机会成本只授权精确科技共享捐助方提案")
        if field[0] in {
            "da_increase_autonomy_of_self",
            "decrease_payments",
            "da_knowledge_sharing",
            "suez_survey_decision",
            "panama_survey_decision",
        }:
            expected = (
                (field[0], "ai", "propose_score")
                if field[0]
                in {"da_increase_autonomy_of_self", "decrease_payments", "da_knowledge_sharing"}
                else (field[0], "ai_chance")
            )
            if (
                field != expected
                or rules.native_root != "country"
                or rules.actor_path
                or rule.operation != "multiply"
                or rule.value <= 0
                or any(
                    readers[key].scope != "root" or readers[key].path for key in rule.input_keys()
                )
            ):
                raise ValueError("原生提案/运河调查只支持精确country ROOT正倍率消费者")
        if (
            field[0] == "revive_olympic_games_decision"
            or any(readers[key].engine == "produced_bureaucracy" for key in rule.input_keys())
        ) and (
            field != ("revive_olympic_games_decision", "ai_chance")
            or rules.native_root != "country"
            or rules.actor_path
            or rule.operation != "multiply"
            or not 0.75 <= rule.value < 1
            or rule.semantic_role != "cost"
            or any(readers[key].scope != "root" or readers[key].path for key in rule.input_keys())
        ):
            raise ValueError("赛事行政风险只授权精确country ROOT有界成本消费者")
        if "actual_overlord_relations" in rule.input_keys() and field != (
            "ai_strategy_subject_overlord_compliance",
            "weight",
        ):
            raise ValueError("实际宗主关系仅授权已证明的宗属合作策略消费者")
        if any(
            "war_pressure_query" in dict(readers[key].parameters) for key in rule.input_keys()
        ) and (
            field != ("wargoal_scores", "conquer_state")
            or rule.id != "war_pressure_conquer_state"
            or rules.native_root != "country"
            or rules.actor_path
            or rule.operation != "add"
            or rule.semantic_role != "cost"
            or not -3 <= rule.value < 0
        ):
            raise ValueError("本国多线低支持观测仅授权精确征服目标的有界扩张成本")
        if any(
            "subject_dependence_query" in dict(readers[key].parameters) for key in rule.input_keys()
        ) and (
            field != ("ai_strategy_subject_overlord_compliance", "weight")
            or rules.native_root != "country"
            or rules.actor_path
            or rule.operation != "multiply"
            or rule.value <= 1
        ):
            raise ValueError("实际宗主经济依赖仅授权已证明的国家宗属合作收益消费者")
        if (
            rules.native_root == "military_formation" or field[0].startswith("mobilization_option_")
        ) and (
            rules.native_root != "military_formation"
            or rules.actor_path != ("owner",)
            or len(field) != 2
            or field[0] not in CANDIDATE_IDS
            or field[1] != "ai_weight"
            or rule.operation != "multiply"
        ):
            raise ValueError("动员只支持精确候选、编队ROOT及owner国家边界")
        if field == ("wanted_construction_output",) and (
            rule.operation != "multiply" or not math.isfinite(rule.value) or rule.value <= 0
        ):
            raise ValueError("建设目标消费者只能使用正乘数；其原版人口终止零分位于新增调整之前")
        named = {"root"}
        if field[0] == "raise_payments":
            from . import native_action_opportunities as native_actions  # noqa: PLC0415

            native_actions.validate_batch_policy(
                rules, native_actions.BATCH_CANDIDATES[native_actions.RAISE]
            )
            named.add("target_country")
        if field[0] in {
            "state_value",
            "treaty_port_value",
            "wargoal_scores",
            "subject_value",
            "secret_goal_scores",
        }:
            named.add("target_country")
        if field[0] in {"state_value", "treaty_port_value"}:
            named.add("target_state")
        if field[0] == "become_subject_value":
            named.add("overlord")
        if field[0] == "interest_group_government_weight":
            named.add("interest_group")
        if any(readers[key].scope not in named for key in rule.input_keys()):
            raise ValueError(f"消费者没有提供读取器的具名作用域：{rule.id}")


def regional_resource_consumer(program) -> dict[str, object]:
    from . import regional_resource_opportunities as regional  # noqa: PLC0415

    program.validate()
    return {
        **regional.consumer_catalog(),
        "role": "vanilla_candidate_region_stance_score",
        "reader_context_bindings": [list(row) for row in program.reader_bindings()],
        "scope_evidence_level": "static_complete_native_and_existing_r7; runtime_behavior_unverified",
        "eligibility_costs_and_execution": "retained_vanilla",
        "world_scans": 0,
    }


def event_consumer(program: EventProgram) -> dict[str, object]:
    """Grant only the proven event/option selector, never a generic country event."""
    from . import event_opportunities  # noqa: PLC0415

    program.validate()
    return {
        **event_opportunities.consumer_catalog()[program.option],
        "role": "vanilla_event_option_aiweight",
        "evaluation_context": program.evaluation_context().as_dict(),
        "reader_context_bindings": [list(row) for row in program.reader_bindings()],
        "scope_evidence_level": "static_complete_native_sources; runtime_behavior_unverified",
        "eligibility_costs_and_execution": "retained_vanilla",
        "world_scans": 0,
    }


def acceptance_consumer(program: AcceptanceProgram) -> dict[str, object]:
    """Exact inherent acceptance; current ROOT and the article's proven roles."""
    from . import treaty_acceptance_opportunities as acceptance  # noqa: PLC0415

    program.validate()
    for reader in program.readers():
        if reader.key.startswith("commitment_"):
            reader_scope(
                reader,
                (),
                native_root="country",
                source=program.source,
                field=program.field_path,
                context=program.evaluation_context(),
            )
    return {
        **acceptance.consumer_catalog()[program.definition],
        "role": f"vanilla_{program.kind}_article_inherent_acceptance",
        "evaluation_context": program.evaluation_context().as_dict(),
        "reader_context_bindings": [list(row) for row in program.reader_bindings()],
        "scope_evidence_level": "static_complete_native_sources; runtime_behavior_unverified",
        "eligibility_costs_and_execution": "retained_vanilla",
        "world_scans": 0,
    }


def consumer(
    field: tuple[str, ...],
    actor_path: tuple[str, ...],
    *,
    source: str | None = None,
    native_root: str | None = None,
) -> dict[str, object]:
    """解释实际数值写入的角色、影响级别与不可越过的引擎职责。"""
    leaf = field[-1]
    evidence = "common/ai_strategies/00_default_strategy.txt"
    role = "vanilla_strategy_numeric_evaluation"
    native_unit = None
    if (
        native_root == "military_formation"
        and source != "common/mobilization_options/00_mobilization_option.txt"
    ):
        raise ValueError("编队ROOT消费者必须提供精确医疗动员原件身份")
    if (source is not None and source.startswith("common/diplomatic_actions/")) or field[0] in {
        "da_increase_autonomy_of_self",
        "decrease_payments",
        "join_power_bloc",
        "da_knowledge_sharing",
    }:
        from .native_action_opportunities import consumer_catalog  # noqa: PLC0415

        catalog = consumer_catalog()
        row = catalog.get(field[0])
        if (
            row is None
            or row["source"] != source
            or row["field"] != ".".join(field)
            or actor_path
            or native_root not in {None, "country"}
        ):
            raise ValueError("原生外交行动只授权已登记精确country ROOT提案优先字段")
        evidence, role = row["scope_evidence"], "vanilla_diplomatic_action_proposal_priority"
        native_unit = "score"
    elif (
        source == "common/decisions/00_decisions.txt" or field[0] == "revive_olympic_games_decision"
    ):
        from . import native_decision_opportunities as native_decision  # noqa: PLC0415

        if (
            (source, ".".join(field))
            not in {(row["source"], row["field"]) for row in native_decision.consumer_catalog()}
            or actor_path
            or native_root not in {None, "country"}
        ):
            raise ValueError("赛事只授权精确country ROOT决议相对权重")
        evidence, role = native_decision.HELP, "vanilla_country_decision_relative_weight"
        native_unit = "relative_weight"
    elif source == "common/decisions/canal_decisions.txt" or field[0] in {
        "suez_survey_decision",
        "panama_survey_decision",
    }:
        from .canal_opportunities import HELP  # noqa: PLC0415
        from .canal_opportunities import consumer_catalog as canal_catalog  # noqa: PLC0415

        if (
            (source, ".".join(field))
            not in {(row["source"], row["field"]) for row in canal_catalog()}
            or actor_path
            or native_root not in {None, "country"}
        ):
            raise ValueError("运河只授权两个精确country ROOT调查相对权重")
        evidence, role = HELP, "vanilla_country_decision_relative_weight"
        native_unit = "relative_weight"
    elif (source is not None and source.startswith("common/decrees/")) or field[0].startswith(
        "decree_"
    ):
        from . import decree_opportunities as decree  # noqa: PLC0415

        if (
            source != decree.SOURCE
            or ".".join(field) != decree.FIELD
            or actor_path != ("owner",)
            or native_root != "state"
        ):
            raise ValueError("政令只授权精确救济州ROOT与真实owner数值消费者")
        decree.consumer_catalog()
        evidence, role = decree.SOURCE, "vanilla_state_decree_relative_weight"
        native_unit = "relative_weight"
    elif (source is not None and source.startswith("common/scripted_buttons/")) or field[
        0
    ].startswith("je_indian_famines_button_"):
        from . import famine_opportunities as famine  # noqa: PLC0415
        from . import native_button_opportunities as buttons  # noqa: PLC0415

        exact = (source, ".".join(field))
        famine_pairs = {(row["source"], row["field"]) for row in famine.consumer_catalog()}
        button_pairs = {(row["source"], row["field"]) for row in buttons.consumer_catalog()}
        if (
            exact not in famine_pairs | button_pairs
            or actor_path
            or native_root not in {None, "country"}
        ):
            raise ValueError("按钮只授权精确country ROOT消费者相对权重")
        evidence = famine.HELP
        role = (
            "vanilla_famine_button_relative_weight"
            if exact in famine_pairs
            else "vanilla_native_button_relative_weight"
        )
        native_unit = "relative_weight"
    elif leaf == "ai_enact_weight_modifier":
        evidence, role = "common/laws/readme.md", "vanilla_law_candidate_weight"
    elif leaf == "ai_weight" and source is not None and source.startswith("common/company_types/"):
        evidence, role = (
            "research/situated/victoria3-1.15.0-company-scope.json",
            "vanilla_company_base_candidate_weight",
        )
    elif leaf == "ai_weight" and source == "common/mobilization_options/00_mobilization_option.txt":
        from .mobilization_opportunities import CANDIDATE_IDS  # noqa: PLC0415

        if (
            native_root != "military_formation"
            or actor_path != ("owner",)
            or len(field) != 2
            or field[0] not in CANDIDATE_IDS
        ):
            raise ValueError("医疗动员消费者必须保留精确编队ROOT及所属国家角色")
        evidence, role = (
            "research/situated/mobilization-opportunities.json",
            "vanilla_mobilization_utility_multiplier_before_monetary_cost",
        )
    elif leaf == "ai_weight":
        evidence, role = "common/technology/technologies/", "vanilla_research_candidate_weight"
    elif leaf == "ai_value":
        evidence, role = "common/buildings/buildings.md", "vanilla_state_building_candidate_weight"
    elif (
        leaf == "proposal_weight"
        and source is not None
        and source.startswith("common/treaty_articles/")
    ):
        evidence, role = (
            "research/situated/treaty-opportunities.json",
            "vanilla_treaty_article_proposal_multiplier",
        )
    elif (
        leaf == "evaluation_chance"
        and source is not None
        and source.startswith("common/treaty_articles/")
    ):
        if (
            actor_path
            or native_root not in {None, "country"}
            or len(field) != 3
            or field[1] != "ai"
        ):
            raise ValueError("条约抽样概率只允许被评估国家ROOT，无条款或对方角色")
        evidence, role = (
            "research/situated/treaty-opportunities.json",
            "vanilla_treaty_article_evaluation_probability",
        )
    return {
        **(
            {
                "native_unit": native_unit,
                "writer_unit": "weight_delta"
                if role == "vanilla_state_decree_relative_weight"
                else "multiplier",
            }
            if native_unit
            else {}
        ),
        **(
            {"native_unit": "probability", "writer_unit": "multiplier"}
            if role == "vanilla_treaty_article_evaluation_probability"
            else {}
        ),
        "role": role,
        "impact": "B",
        "root": native_root if native_root is not None else "state" if actor_path else "country",
        "scope_evidence": evidence,
        "scope_evidence_level": "static_vanilla_examples; runtime_behavior_unverified",
        "eligibility_costs_and_execution": "retained_vanilla",
        "refresh": "vanilla_consumer_evaluation",
        "world_scans": 0,
        "description_required": field[-1] == "state_value",
        "placement": placement_contract(field),
    }


def placement_contract(field: tuple[str, ...]) -> str:
    """数值写入先于原版终结资格/截断；路径按锁定消费者逐项审计。"""
    field = field[1:] if field[0] == "ai_strategy_default" else field
    if field == ("decree_emergency_relief", "ai_weight"):
        return "before_native_decree_political_multiply_tail"
    if field == ("subject_value",):
        return "inside_regular_reachable_subject_branch_before_native_tail"
    if field == ("treaty_port_value",):
        return "before_native_market_reachability_and_clamp_tail"
    if field == ("aggression",):
        return "before_native_aggression_terminal_zero_tail"
    if field in {
        ("wargoal_scores", "conquer_state"),
        ("wargoal_scores", "transfer_subject"),
    }:
        return "before_native_terminal_zero_and_clamp_tail"
    if field in {
        ("become_subject_value",),
        ("max_active_stances",),
        ("state_value",),
        ("negotiation_chance",),
        ("wargoal_scores", "make_subject"),
        ("wargoal_scores", "liberate_subject"),
    }:
        return "before_native_first_top_level_clamp_and_special_tail"
    return "after_native_numeric_evaluation"


def _retained_reason(field: str) -> dict[str, str]:
    """保留原版是明确设计选择，既不是新增实现也不是接口不支持。"""
    policies = (
        (("icon",), "presentation", "保留原版策略图标，不把显示资源作为决策输入", "无行为影响"),
        (
            ("cossack_host_scores",),
            "native_cossack_host_scores_pending",
            "逐字保留当前原版哥萨克军团评分映射、资格与尾部；本阶段不扩展写入许可",
            "候选身份、评分与编制执行仍归原版；后续扩展须单独证明消费者与成本边界",
        ),
        (
            ("colonial_interest_ratio",),
            "native_consumer_context_unknown",
            "真实求值对象和合并语义尚未证明；撤销无依据覆盖，精确保留原版AST，接口继续unknown",
            "地区殖民立场、殖民制度、州价值与海军保障各走已证消费者；不是该字段的等价实现",
        ),
        (
            ("desired_tax_level", "max_tax_level", "min_tax_level"),
            "native_tax_policy",
            "字段为原版税率枚举；不把枚举改成未声明支持的动态脚本值",
            "通过财政状态、支出平衡、建筑与法律权重间接响应；未新增逐税种优化器",
        ),
        (
            ("will_form_power_bloc", "will_incorporate_state", "possible"),
            "native_eligibility",
            "保留原版政治集团、整合及策略资格，避免新权重授予免费行动资格",
            "既有合法目标继续由价值、财政、地理及外交权重影响；未扩大资格",
        ),
        (
            (
                "ideological_opinion_effect_mult",
                "max_progressiveness",
                "max_regressiveness",
                "pro_interest_groups",
                "anti_interest_groups",
            ),
            "native_political_identity",
            "保留原版意识形态方向及路线惯性，不将财政危机变成统一政治立场",
            "法律候选、政府IG与协商权重综合政治能力和财政；不重写意识形态本身",
        ),
        (
            ("diplomatic_play_boldness", "obligation_value"),
            "native_commitments",
            "保留原版博弈胆量与人情的资格、零分拒绝和估值，避免同一风险重复计分",
            "侵略、鲁莽、支持、中立及目标估值已响应财政和相对实力；不另开人情优化器",
        ),
        (
            ("wanted_naval_fortification_levels",),
            "native_fixed_defense",
            "保留原版固定防御，不以债务惩罚削弱基础防御资格",
            "海军规模、舰类、编制、军需与护航权重另行响应",
        ),
        (
            ("building_group_weights", "subsidies", "war_subsidies"),
            "native_industry_support",
            "保留产业组及补贴制度，避免与逐建筑投入成本和军需评价双重补偿",
            "建筑ai_value、研发、商品供给立场与支出平衡已接通；未新增逐企业补贴优化器",
        ),
        (
            ("liberate_country_scores", "strategic_region_scores", "strait_scores"),
            "native_geostrategy",
            "保留原版指定地区、海峡和释放国家偏好；不把历史目标统一为通用地理分数",
            "州价值、宗属/战争目标和本土/孤立州成本已接通；不替换原版战略地图",
        ),
        (
            ("goods_stances",),
            "native_goods_stances",
            "商品供给适配关闭时完整保留原版商品立场、触发条件与顺序",
            "适配启用时只按真实商品稀缺追加立场；关闭不新增立场、不改变原版选择",
        ),
        (
            ("weight",),
            "native_strategy_selection",
            "保留默认策略本身的选择权重；新增规则不额外争夺策略槽",
            "在原版消费者内重评估；活跃策略同名字段的覆盖语义须按具体字段证据判断",
        ),
    )
    for fields, policy, reason, alternative in policies:
        if field in fields:
            return {
                "disposition": policy,
                "reason": reason,
                "alternative_and_limit": alternative,
                "verification": "static_native_placement; user_behavior_review_pending",
            }
    raise ValueError(f"保留的原版字段缺少逐项处置：{field}")


def coverage(baseline: str, owners: dict[tuple[str, ...], str]) -> list[dict[str, object]]:
    """逐件登记锁定默认策略的全部字段，包括明确保留给原版的字段。

    保留字段不算本 Mod 新实现，也不标成引擎不支持；字段不出现时不能
    通过一个笼统的“原版负责”隐藏新增目标。对应源行可直接复核完整语义。
    """
    parsed = parse_text(baseline)
    if parsed.errors or len(parsed.top_assignments) != 1:
        raise ValueError("覆盖台账需要唯一锁定默认策略")
    root = parsed.top_assignments[0].value
    if not isinstance(root, Block):
        raise ValueError("覆盖台账默认策略必须是块")
    result = []
    for assignment in root.assignments():
        writers = {
            ".".join(field): owner for field, owner in owners.items() if field[0] == assignment.key
        }
        value = assignment.value
        numeric = isinstance(value, Block) and any(
            value.first(op) is not None for op in ("value", "add", "multiply", "subtract")
        )
        result.append(
            {
                "field": assignment.key,
                "source": "common/ai_strategies/00_default_strategy.txt",
                "line": assignment.line,
                "shape": "numeric_script"
                if numeric
                else "structured_table_or_trigger"
                if isinstance(value, Block)
                else "scalar",
                "status": "generated_intervention"
                if writers
                else "retained_vanilla_not_new_mod_implementation",
                "writers": writers,
                "retained_disposition": None if writers else _retained_reason(assignment.key),
                "native_qualification_costs_and_execution": "unchanged",
                "behavior_verified": False,
            }
        )
    if {field[0] for field in owners} - {row["field"] for row in result}:
        raise ValueError("覆盖台账含不在锁定默认策略中的写入字段")
    return result


STATE_DEVASTATION_SOURCE = "common/ideologies/01_character_ideologies.txt"
STATE_DEVASTATION_SHA256 = "ca28311ba527e4fca8ef590a4bff69e2d541cbaca5de9828913ca22d26b81ad4"


def verify_state_devastation_sources(texts: dict[str, str]) -> tuple[str, ...]:
    """Pin the native state ratio AST and victim-limited five-year memory.

    The ideology supplies a state getter witness, not a railway effect.
    The consumer remains the independently proved state building ai_value.
    """
    from .textio import normalized_text  # noqa: PLC0415

    sources = {
        STATE_DEVASTATION_SOURCE: STATE_DEVASTATION_SHA256,
        "common/on_actions/00_code_on_actions.txt": "ceebee2c1b4846ba1ad11a78093bb85b619b911c92c414c9f3f8e8bfb6e8510e",
    }
    parsed = {}
    for source, expected in sources.items():
        text = texts.get(source)
        if (
            not isinstance(text, str)
            or hashlib.sha256(normalized_text(text).encode()).hexdigest() != expected
        ):
            raise ValueError(f"州恢复读取器原版来源漂移或缺失：{source}")
        result = parse_text(text, path=source)
        if result.errors:
            raise ValueError(f"州恢复读取器原版AST无法解析：{source}")
        parsed[source] = result.root

    def shape(node):
        if isinstance(node, Scalar):
            return node.text, node.quoted
        if isinstance(node, Assignment):
            return node.key, node.op, node.prefix, shape(node.value)
        if isinstance(node, Block):
            return tuple(shape(x) for x in node.items)
        raise ValueError("州恢复原版AST含未知节点")

    ideology = parsed[STATE_DEVASTATION_SOURCE].first("ideology_pacifist")
    expected = shape(
        parse_text(
            "owner ?= { any_scope_state = { is_incorporated = yes devastation > 0.2 } }"
        ).root
    )
    references = []
    if ideology is None or not isinstance(ideology.value, Block):
        raise ValueError("州受创读取器失去精确原版意识形态消费者")
    for field in ("interest_group_leader_weight", "non_interest_group_leader_weight"):
        weight = ideology.value.first(field)
        matches = []
        if weight is not None and isinstance(weight.value, Block):
            for branch in weight.value.all("if"):
                if isinstance(branch.value, Block):
                    limit = branch.value.first("limit")
                    if limit is not None and shape(limit.value) == expected:
                        matches.append(limit.line)
        if len(matches) != 1:
            raise ValueError("州受创读取器缺少唯一owner到同州devastation完整原版AST")
        references.append(f"{STATE_DEVASTATION_SOURCE}:{matches[0]}")
    memory = parsed["common/on_actions/00_code_on_actions.txt"].first("on_lost_war")
    expected_memory = parse_text(
        "effect = { if = { limit = { exists = scope:victim_of_wargoal } set_variable = { name = recently_lost_war days = 1825 value = yes } } }"
    ).root
    if memory is None or shape(memory.value) != shape(expected_memory):
        raise ValueError("州恢复失去原版受害者限定与1825天战败记忆生命周期")
    references.append(f"common/on_actions/00_code_on_actions.txt:{memory.line}")
    return tuple(references)
