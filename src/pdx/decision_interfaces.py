"""已审计脚本接口的类型边界；静态契约不代替引擎实测。

只接受有原版消费者依据的作用域转换，不能用“各个词都出现过”证明
它们可以任意拼接。增加接口时同时补来源、类型、消费者和反例。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

from . import observation_queries, version_contracts
from .model import Assignment, Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from .decision_rules import Reader, RuleSet
    from .situated.profile_configuration import ProfileConfiguration


_LJ10_EVIDENCE = Path(__file__).resolve().parents[2] / (
    "research/situated/victoria3-1.14.5-defensive-pact-reader.json"
)
_LJ10_EVIDENCE_SHA256 = "2237b33ebdb232e2c2061a995d471e98ca015ce06725cc00f4e7d252c63c20c6"
SCRIPTED_PREDICATE_SOURCE = Path(__file__).resolve().parents[2] / (
    "research/situated/victoria3-1.14.5-scripted-predicate.json"
)
SCRIPTED_PREDICATE_SHA256 = "128c85f83fdc007a42d19c97dad7bf8d61351be42121095e680ed1028a38918c"
SCRIPTED_PREDICATE_115 = Path(__file__).resolve().parents[2] / (
    "research/situated/1.15.0/scripted-predicate.json"
)
SCRIPTED_PREDICATE_115_SHA256 = "31dd68a463d5de5c7d1bf7e234be29db8850af011544c5bf6fa0702c49ef52fa"


SCRIPTED_PREDICATE_1151_SHA256 = "ae30c39e5c282adb827f5121c4b283f3b96087e5634e894b19def7ca5e670ae3"


def scripted_predicate_path() -> Path:
    if version_contracts.active_version() == "1.15.1":
        return version_contracts.research_path("situated", "scripted-predicate.json")
    return SCRIPTED_PREDICATE_115 if version_contracts.is_115() else SCRIPTED_PREDICATE_SOURCE


def scripted_predicate_sha256() -> str:
    if version_contracts.active_version() == "1.15.1":
        return SCRIPTED_PREDICATE_1151_SHA256
    return (
        SCRIPTED_PREDICATE_115_SHA256 if version_contracts.is_115() else SCRIPTED_PREDICATE_SHA256
    )


def scripted_trigger_snapshot() -> bytes:
    """Identify the exact historical scripted predicate, never a builtin getter."""
    version = version_contracts.active_version()
    source = scripted_predicate_path()
    expected_hash = scripted_predicate_sha256()
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("原版脚本布尔谓词冻结证据漂移")
    data = json.loads(raw)
    if data.get("reader") != {
        "engine": "any_insurrection_ongoing",
        "origin": "scripted_trigger",
        "scope": "root",
        "result": "boolean",
        "unit": "boolean",
        "source": "common/scripted_triggers/00_scripted_triggers.txt",
        "line": {"1.14.5": 1117, "1.15.0": 1243, "1.15.1": 1244}[version],
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


def write_scripted_trigger_authority_115(game: Path) -> Path:
    """Recapture the complete native trigger namespace after exact AST proof."""
    from .situated import r2_reader_authority  # noqa: PLC0415

    if scripted_predicate_path().exists() and (
        hashlib.sha256(scripted_predicate_path().read_bytes()).hexdigest()
        != scripted_predicate_sha256()
    ):
        raise ValueError("1.15 scripted predicate: existing reviewed evidence drift")
    r2_reader_authority.verify_installation(game.parent)
    paths = sorted((game / "common/scripted_triggers").rglob("*.txt"))
    sources = {
        path.relative_to(game).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    matches: list[tuple[Path, Assignment]] = []
    for path in paths:
        parsed = parse_text(path.read_text(encoding="utf-8-sig"))
        if parsed.errors:
            raise ValueError("1.15 scripted predicate: invalid source AST")
        matches.extend((path, item) for item in parsed.root.all("any_insurrection_ongoing"))
    if len(matches) != 1 or not _insurrection_predicate_definition(matches[0][1]):
        raise ValueError("1.15 scripted predicate: missing exact unique definition")
    data = {
        "schema": 1,
        "evidence_category": "static_check",
        "baseline": f"victoria3-{version_contracts.active_version()}",
        "builder": {
            "path": "src/pdx/decision_interfaces.py",
            "function": "write_scripted_trigger_authority_115",
            "source_sha256": hashlib.sha256(
                inspect.getsource(write_scripted_trigger_authority_115).encode()
            ).hexdigest(),
        },
        "sources": sources,
        "reader": {
            "engine": "any_insurrection_ongoing",
            "origin": "scripted_trigger",
            "scope": "root",
            "result": "boolean",
            "unit": "boolean",
            "source": matches[0][0].relative_to(game).as_posix(),
            "line": matches[0][1].line,
            "definition": (
                "any_insurrection_ongoing = { any_political_movement = { is_insurrectionary = yes } }"
            ),
        },
        "limits": [
            "The exact current native scripted trigger is not a builtin getter.",
            "Only exact country ROOT without arguments, paths or parameters is authorized.",
            "The complete current trigger namespace and unique AST require live source verification; runtime remains unknown.",
        ],
    }
    scripted_predicate_path().parent.mkdir(parents=True, exist_ok=True)
    scripted_predicate_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return scripted_predicate_path()


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
    """Version-selected static reader evidence; installed identity is a separate gate.

    The manifest contains verified executable observations and original script
    hashes. It extends token discovery only; reader_scope still enforces exact
    own-Country signatures and does not grant arbitrary foreign-scope access.
    """
    if version_contracts.is_115():
        from .situated import engine_reader_115  # noqa: PLC0415

        return engine_reader_115.proven_words()
    raw = _LJ10_EVIDENCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _LJ10_EVIDENCE_SHA256:
        raise ValueError("LJ10 读取器冻结证据字节漂移")
    manifest = json.loads(raw)
    if manifest["exe"]["sha256"] != (
        "9b6f133a5dc235de9135d7b57e86ceda8282d1ba6c0e185f3ee19c22f8917f54"
    ):
        raise ValueError("LJ10 读取器原版引擎身份漂移")
    return frozenset(
        [manifest["reader"]["engine"]]
        + [item["engine"] for item in manifest["positive_native_guard"]["readers"]]
    )


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
    "pop_type_percent_country": "ratio",
    "radical_fraction": "ratio",
    "scaled_debt": "debt_to_credit_ratio",
    "weeks_until_bankruptcy": "weeks",
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
    "wanted_army_size_script_value": "battalions",
    "wanted_marines_size_script_value": "battalions",
    "state_goods_pricier": "price_above_base_ratio",
    "market_goods_pricier": "price_above_base_ratio",
    "market_goods_delta": "sell_minus_buy_orders",
    "market_goods_consumption": "total_consumption_units",
}


def reader_scope(
    reader: Reader, actor_path: tuple[str, ...], *, native_root: str | None = None
) -> str:
    """解析本生成器明确支持的有限转换，不猜测任意具名词的类型。"""
    root = native_root if native_root is not None else "state" if actor_path else "country"
    if reader.engine == "pop_type_percent_country":
        current = version_contracts.is_115()
        parameter = "target" if current else "pop_type"
        values = {"peasants", "laborers", "machinists"}
        if (
            reader.scope != "root"
            or reader.path != actor_path
            or reader.argument is not None
            or len(reader.parameters) != 1
            or reader.parameters[0][0] != parameter
            or reader.parameters[0][1]
            not in ({f"pop_type:{name}" for name in values} if current else values)
            or reader.value_field != ("value" if current else "percent")
            or reader.kind != "number"
            or reader.unit != "ratio"
            or reader.minimum != 0
            or reader.maximum != 1
        ):
            raise ValueError(f"人口比例必须保持所选版本的精确国家参数合同：{reader.key}")
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
    if reader.engine in {"num_companies", "max_num_companies", "authority"} and (
        reader.scope != "root"
        or actor_path
        or reader.path
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
        or reader.maximum is not None
        or reader.minimum != (None if reader.engine == "authority" else 0)
    ):
        raise ValueError(f"公司容量与权威余额仅支持已证明的国家 ROOT 数值合同：{reader.key}")
    # Each version has its own reader/consumer proof. Counts witness articles,
    # never treaty fulfilment or military strength; only own Country root.
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
    expected_unit = _UNITS.get(reader.engine, "boolean")
    if version_contracts.is_115() and reader.engine in {
        "wanted_army_size_script_value",
        "wanted_marines_size_script_value",
    }:
        expected_unit = "barracks_levels"
    if reader.unit != expected_unit:
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
        if "actual_overlord_relations" in rule.input_keys() and field != (
            "ai_strategy_subject_overlord_compliance",
            "weight",
        ):
            raise ValueError("实际宗主关系仅授权已证明的宗属合作策略消费者")
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
        if field[0] in {"negotiation_chance", "interest_group_government_weight"}:
            named.add("interest_group")
        if any(readers[key].scope not in named for key in rule.input_keys()):
            raise ValueError(f"消费者没有提供读取器的具名作用域：{rule.id}")


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
    if (
        native_root == "military_formation"
        and source != "common/mobilization_options/00_mobilization_option.txt"
    ):
        raise ValueError("编队ROOT消费者必须提供精确医疗动员原件身份")
    if leaf == "ai_enact_weight_modifier":
        evidence, role = "common/laws/readme.md", "vanilla_law_candidate_weight"
    elif leaf == "ai_weight" and source is not None and source.startswith("common/company_types/"):
        from .situated import engine_scope  # noqa: PLC0415

        _, evidence, _ = engine_scope._company_manifest()
        role = "vanilla_company_base_candidate_weight"
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
    if field == "cossack_host_scores" and version_contracts.is_115():
        return {
            "disposition": "native_cossack_host_policy",
            "reason": "完整保留原版哥萨克军团州目标评分、零分拒绝及COSSACK_HOST_STICKYNESS惯性；未新增Mod写入",
            "alternative_and_limit": "原版注释的country/target_state上下文只描述保留字段，不授予新增读取、写入或任意作用域转换",
            "verification": "static_native_placement; user_behavior_review_pending",
        }
    policies = (
        (("icon",), "presentation", "保留原版策略图标，不把显示资源作为决策输入", "无行为影响"),
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


def _configuration_writers(
    configuration: ProfileConfiguration,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    """Derive active and withdrawn writers from canonical declarations.

    A disabled switch explains only actual declared writers in an excluded
    domain. Active declarations remain required even when another writer for
    the same native field is withdrawn. Caller paths confer no authority.
    """
    from . import decision_adapters, decision_rules, decisions, distribution  # noqa: PLC0415
    from .situated.profile_configuration import LEGACY_DOMAINS  # noqa: PLC0415

    known_domains = frozenset().union(*LEGACY_DOMAINS.values())
    active: dict[str, list[dict[str, str]]] = {}
    disabled: dict[str, list[dict[str, str]]] = {}
    identities: set[tuple[str, str]] = set()

    def register(
        source: str, writer_id: str, field: tuple[str, ...], owner: str, domain: str
    ) -> None:
        identity = (source, writer_id)
        if identity in identities:
            raise ValueError("配置关闭台账含重复声明writer")
        identities.add(identity)
        if domain not in known_domains or not field:
            raise ValueError("配置关闭台账含未知声明领域或字段")
        writers = active if domain in configuration.legacy_domains else disabled
        writers.setdefault(field[0], []).append(
            {
                "source": source,
                "writer_id": writer_id,
                "field": ".".join(field),
                "owner": owner,
                "domain": domain,
            }
        )

    information = decision_rules.load()
    adapters = decision_adapters.load()
    for source, rules, owner in (
        ("mod/decisions/information.toml", information, "information_rules"),
        *((source, rules, "consumer_adapters") for source, rules in adapters.policies),
    ):
        for rule in rules.rules:
            if (source, rule.id) in identities:
                raise ValueError("配置关闭台账含重复声明writer")
            if source not in {
                "mod/decisions/information.toml",
                "common/ai_strategies/00_default_strategy.txt",
            }:
                identities.add((source, rule.id))
                continue
            field = rule.field
            if source != "mod/decisions/information.toml":
                if field[:1] != ("ai_strategy_default",):
                    raise ValueError("配置关闭台账默认策略声明路径无效")
                field = field[1:]
            if rule.domain in rules.enabled_domains:
                register(source, rule.id, field, owner, rule.domain)
            else:
                identities.add((source, rule.id))
    if adapters.supply is not None and any(
        "market" in rules.enabled_domains for _, rules in adapters.policies
    ):
        for program in adapters.supply.actions():
            register(
                program.source,
                program.writer_id,
                ("goods_stances", program.good),
                "supply_plan",
                "market",
            )

    if version_contracts.active_version() == "1.15.1":
        from .situated import network_profile, production_profile  # noqa: PLC0415

        profile = production_profile.load_profile(production_profile.baseline_root())
        # The native declaration alone is not a Mod writer. Confirm that the
        # current policy actually compiles the consumer before recording its
        # withdrawal; the six retired school rules never reappear as writers.
        programs = network_profile.compile_profile(profile)
        consumers = {program.network.actions[0].definition.consumer_id for program in programs}
        for row in profile.declarations:
            if (
                row.id in consumers
                and row.source == "game/common/ai_strategies/00_default_strategy.txt"
            ):
                if row.definition != "ai_strategy_default":
                    raise ValueError("配置关闭台账R2默认策略声明路径无效")
                register(
                    network_profile.source_path(profile.game_version)
                    .relative_to(decisions.config.REPO)
                    .as_posix(),
                    row.id,
                    row.field,
                    "R2/action-network-v2",
                    {"economy": "economy", "politics": "political", "diplomacy": "diplomacy"}[
                        row.domain
                    ],
                )

    policy, extensions = distribution.production_configuration()
    builtin_domains = {
        "fiscal": "fiscal",
        "reform": "political",
        "economy": "economy",
        "diplomacy": "diplomacy",
        "market": "market",
        "security": "military",
    }
    for module, fields in decisions.CONFIGURATION_CONSUMER_FIELDS.items():
        enabled = policy.enabled if module == "fiscal" else getattr(extensions, f"{module}_enabled")
        if enabled:
            for field_name in fields:
                register(
                    "mod/decisions/fiscal.toml"
                    if module == "fiscal"
                    else "mod/decisions/extensions.toml",
                    f"{module}:{field_name}",
                    (field_name,),
                    "situated_kernel",
                    builtin_domains[module],
                )

    def sorted_writers(writers: dict[str, list[dict[str, str]]]) -> dict[str, list[dict[str, str]]]:
        return {
            field: sorted(rows, key=lambda row: (row["source"], row["writer_id"]))
            for field, rows in writers.items()
        }

    return sorted_writers(active), sorted_writers(disabled)


def coverage(
    baseline: str,
    owners: dict[tuple[str, ...], str],
    *,
    configuration: ProfileConfiguration | None = None,
) -> list[dict[str, object]]:
    """逐件登记锁定默认策略的全部字段，包括明确保留给原版的字段。

    保留字段不算本 Mod 新实现，也不标成引擎不支持；字段不出现时不能
    通过一个笼统的“原版负责”隐藏新增目标。对应源行可直接复核完整语义。
    """
    from .situated.profile_configuration import ProfileConfiguration  # noqa: PLC0415

    if configuration is not None and type(configuration) is not ProfileConfiguration:
        raise ValueError("覆盖台账需要已解析的配置")
    active, disabled = ({}, {}) if configuration is None else _configuration_writers(configuration)
    parsed = parse_text(baseline)
    if parsed.errors or len(parsed.top_assignments) != 1:
        raise ValueError("覆盖台账需要唯一锁定默认策略")
    root = parsed.top_assignments[0].value
    if not isinstance(root, Block):
        raise ValueError("覆盖台账默认策略必须是块")
    result: list[dict[str, object]] = []
    for assignment in root.assignments():
        writers = {
            ".".join(field): owner for field, owner in owners.items() if field[0] == assignment.key
        }
        if not writers and assignment.key in active:
            raise ValueError(f"覆盖台账缺少启用声明writer：{assignment.key}")
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
                "retained_disposition": None
                if writers
                else {
                    "disposition": "configuration_disabled_writer",
                    "reason": "resolved configuration excludes these exact declared writers; retain native field",
                    "alternative_and_limit": "no new Mod implementation or unsupported-interface claim; native denominator retained",
                    "verification": "static_declared_writer_configuration_selection; runtime_behavior_unverified",
                    "configuration": configuration.identity()
                    if configuration is not None
                    else None,
                    "disabled_writers": disabled[assignment.key],
                }
                if assignment.key in disabled
                else _retained_reason(assignment.key),
                **(
                    {"configuration_disabled_writers": disabled[assignment.key]}
                    if assignment.key in disabled
                    else {}
                ),
                "native_qualification_costs_and_execution": "unchanged",
                "behavior_verified": False,
            }
        )
    if {field[0] for field in owners} - {row["field"] for row in result}:
        raise ValueError("覆盖台账含不在锁定默认策略中的写入字段")
    return result


STATE_DEVASTATION_SOURCE = "common/ideologies/01_character_ideologies.txt"
STATE_DEVASTATION_SHA256 = "476003c6dc6b089c6bb1633c950c73755df848ecc8759a08c41c81f89cdc4a51"


def verify_state_devastation_sources(texts: dict[str, str]) -> tuple[str, ...]:
    """Pin the native state ratio AST and victim-limited five-year memory.

    The ideology supplies a state getter witness, not a railway effect.
    The consumer remains the independently proved state building ai_value.
    """
    from .textio import normalized_text  # noqa: PLC0415

    sources = {
        STATE_DEVASTATION_SOURCE: STATE_DEVASTATION_SHA256,
        "common/on_actions/00_code_on_actions.txt": "76dd09b04059f40ae22e0efd17aee54c6f76556f84c31e91e2bbe79643213f46",
    }
    if version_contracts.is_115():
        sources = {
            STATE_DEVASTATION_SOURCE: "ca28311ba527e4fca8ef590a4bff69e2d541cbaca5de9828913ca22d26b81ad4",
            "common/on_actions/00_code_on_actions.txt": "ceebee2c1b4846ba1ad11a78093bb85b619b911c92c414c9f3f8e8bfb6e8510e",
        }
    if version_contracts.active_version() == "1.15.1":
        from . import decision_adapters  # noqa: PLC0415

        authority_sources = decision_adapters.native_authority_115()["sources"]
        sources = {source: authority_sources[source] for source in sources}
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
    # Current native owner ?= is an optional scope transition. It witnesses
    # the state getter only inside that guarded owner branch; it grants no
    # unguarded root/foreign-owner access. The produced state consumer retains
    # its own proved state scope and does not copy or remove this native gate.
    owner_operator = "?=" if version_contracts.is_115() else "="
    expected = shape(
        parse_text(
            f"owner {owner_operator} {{ any_scope_state = {{ is_incorporated = yes devastation > 0.2 }} }}"
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
