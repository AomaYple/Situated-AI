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


_LJ10_EVIDENCE = Path(__file__).resolve().parents[2] / (
    "research/situated/victoria3-1.14.5-defensive-pact-reader.json"
)
_LJ10_EVIDENCE_SHA256 = "2237b33ebdb232e2c2061a995d471e98ca015ce06725cc00f4e7d252c63c20c6"
SCRIPTED_PREDICATE_SOURCE = Path(__file__).resolve().parents[2] / (
    "research/situated/victoria3-1.14.5-scripted-predicate.json"
)
SCRIPTED_PREDICATE_SHA256 = "128c85f83fdc007a42d19c97dad7bf8d61351be42121095e680ed1028a38918c"


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
        "line": 1117,
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
    """Pinned 1.14.5 static reader evidence; current game identity is a separate gate.

    The manifest contains verified executable observations and original script
    hashes. It extends token discovery only; reader_scope still enforces exact
    own-Country signatures and does not grant arbitrary foreign-scope access.
    """
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
_STATE_NUMBER = frozenset({"infrastructure_delta", "market_access", "state_unemployment_rate"})
_INPUTS = {
    **dict.fromkeys(_COUNTRY_BOOLEAN, ("country", "boolean")),
    **dict.fromkeys(_COUNTRY_NUMBER, ("country", "number")),
    **dict.fromkeys(_STATE_NUMBER, ("state", "number")),
    "is_treaty_port": ("state", "boolean"),
    "is_production_method_active": ("state", "boolean"),
    "is_homeland_of_country_cultures": ("state", "boolean"),
    "owner": ("state", "boolean"),
    "is_isolated_from_market": ("state", "boolean"),
    "primary_cultures_percent_state": ("state", "number"),
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
    "ig_clout": "ratio",
    "ig_approval": "approval_points",
    "infrastructure_delta": "infrastructure_points",
    "market_access": "ratio",
    "state_unemployment_rate": "ratio",
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
    if not isinstance(root, str) or (root, actor_path) not in {
        ("country", ()),
        ("state", ("owner",)),
        ("military_formation", ("owner",)),
    }:
        raise ValueError("读取器原生ROOT类型与AI所有者路径不一致")
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
    # 1.14.5 Windows reader/consumer证据只授权本国根；条款数量不是履约或军力。
    # 固定依据见 research/situated/victoria3-1.14.5-defensive-pact-reader.json。
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
        evidence, role = (
            "research/situated/victoria3-1.14.5-company-scope.json",
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
    return {
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
            ("weight",),
            "native_strategy_selection",
            "保留默认策略本身的选择权重；新增规则不额外争夺策略槽",
            "在原版消费者内重评估，活跃策略的原有覆盖语义留给F1逐字段确认",
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
