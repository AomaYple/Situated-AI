"""已审计脚本接口的类型边界；静态契约不代替引擎实测。

只接受有原版消费者依据的作用域转换，不能用“各个词都出现过”证明
它们可以任意拼接。增加接口时同时补来源、类型、消费者和反例。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .model import Block
from .parser import parse_text

if TYPE_CHECKING:
    from .decision_rules import Reader, RuleSet


_COUNTRY_BOOLEAN = frozenset(
    {
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
}
_UNITS = {
    "army_size": "battalions",
    "navy_size": "ships",
    "average_sol": "standard_of_living",
    "bureaucracy": "capacity_balance",
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
    "state_goods_pricier": "price_above_base_ratio",
    "market_goods_pricier": "price_above_base_ratio",
    "market_goods_delta": "sell_minus_buy_orders",
}


def reader_scope(reader: Reader, actor_path: tuple[str, ...]) -> str:
    """解析本生成器明确支持的有限转换，不猜测任意具名词的类型。"""
    scope = {
        "target_state": "state",
        "interest_group": "interest_group",
    }.get(reader.scope, "country")
    if reader.scope == "root" and actor_path:
        scope = "state"
    for part in reader.path:
        if scope == "state" and part == "owner":
            scope = "country"
        elif scope == "country" and part == "market":
            scope = "market"
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
    readers = {reader.key: reader for reader in rules.readers}
    for reader in rules.readers:
        reader_scope(reader, rules.actor_path)
    for rule in rules.rules:
        field = rule.field[1:] if rule.field[0] == "ai_strategy_default" else rule.field
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


def consumer(field: tuple[str, ...], actor_path: tuple[str, ...]) -> dict[str, object]:
    """解释实际数值写入的角色、影响级别与不可越过的引擎职责。"""
    leaf = field[-1]
    source = "common/ai_strategies/00_default_strategy.txt"
    role = "vanilla_strategy_numeric_evaluation"
    if leaf == "ai_enact_weight_modifier":
        source, role = "common/laws/readme.md", "vanilla_law_candidate_weight"
    elif leaf == "ai_weight":
        source, role = "common/technology/technologies/", "vanilla_research_candidate_weight"
    elif leaf == "ai_value":
        source, role = "common/buildings/buildings.md", "vanilla_state_building_candidate_weight"
    return {
        "role": role,
        "impact": "B",
        "root": "state" if actor_path else "country",
        "scope_evidence": source,
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
