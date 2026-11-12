"""D9 strict local production chain evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from pdx import decision_adapters, decision_rules, version_contracts

if TYPE_CHECKING:
    from .decision_ir import ConsumerIRBundle

INFO_SOURCE = "mod/decisions/information.toml"


@dataclass(frozen=True, slots=True)
class ChainRuleBinding:
    chain_id: str
    role: str
    source: str
    rule_id: str
    field: str
    operation: str
    condition_fingerprint: str
    condition_facts: tuple[str, ...]
    bridge_facts: tuple[str, ...]
    status: str = "observed"


@dataclass(frozen=True, slots=True)
class ChainReaderSpec:
    key: str
    engine: str
    kind: str
    scope: str
    path: tuple[str, ...]
    argument: str | None
    parameters: tuple[tuple[str, str], ...]
    value_field: str | None
    unit: str
    minimum: float | None
    maximum: float | None


@dataclass(frozen=True, slots=True)
class ChainLinkSpec:
    chain_id: str
    link_id: str
    source: str
    rule_id: str
    field: str
    actor: str
    target: str
    operation: str
    readers: tuple[ChainReaderSpec, ...]
    condition_semantics: tuple[tuple[str, str, object], ...]
    recipe: tuple[str, ...]
    completion_state: str
    refresh: str
    max_hops: int
    unknown: str
    status: str = "pending"
    required_known_facts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChainEvidence:
    spec: ChainLinkSpec
    writer_id: str
    owner: str
    evidence_paths: tuple[tuple[str, ...], ...]
    evidence_state: str = "static"


_BINDINGS = (
    (
        "LJ01",
        "upstream",
        INFO_SOURCE,
        "remaining_industrial_construction_need",
        "wanted_construction_output",
        "industry",
    ),
    (
        "LJ01",
        "downstream",
        "common/buildings/03_mines.txt",
        "building_coal_mine_bottleneck",
        "building_coal_mine.ai_value",
        "market",
    ),
    (
        "LJ05",
        "fiscal",
        INFO_SOURCE,
        "fiscal_construction_guard",
        "wanted_construction_output",
        "construction",
    ),
    (
        "LJ05",
        "fiscal_recovery",
        "common/ai_strategies/00_default_strategy.txt",
        "military_capacity_ship_default_cost",
        "ai_strategy_default.ship_construction_output_multiplier",
        "construction",
    ),
    (
        "LJ11",
        "war_recovery",
        INFO_SOURCE,
        "remaining_reconstruction_need",
        "wanted_construction_output",
        "recovery",
    ),
    (
        "LJ11",
        "social_recovery",
        "common/ai_strategies/00_default_strategy.txt",
        "health_public_low_living_need",
        "ai_strategy_default.institution_scores.institution_health_system",
        "recovery",
    ),
)
_STRICT_TARGETS = (
    (
        "LJ02",
        "LJ02.coal_output_transport_foundation",
        "common/buildings/03_mines.txt",
        "lj02_coal_output_transport_foundation",
        "building_coal_mine.ai_value",
        "owner",
        "none",
        "multiply",
    ),
    (
        "LJ02",
        "LJ02.coal_transport_railway_support",
        "common/buildings/11_private_infrastructure.txt",
        "infrastructure_railway_prepared_pm_early_trains",
        "building_railway.ai_value",
        "owner",
        "none",
        "multiply",
    ),
    (
        "LJ01",
        "LJ01.iron_tooling_input_repair",
        "common/buildings/03_mines.txt",
        "lj01_iron_tooling_input_repair",
        "building_iron_mine.ai_value",
        "owner",
        "none",
        "multiply",
    ),
    (
        "LJ03",
        "LJ03.university_completed_knowledge_foundation",
        "common/buildings/07_government.txt",
        "knowledge_university_researched_foundation",
        "building_university.ai_value",
        "owner",
        "none",
        "multiply",
    ),
    (
        "LJ03",
        "LJ03.mechanical_tools_actual_paper_option",
        "common/technology/technologies/10_production.txt",
        "technology_mechanical_tools_supply_paper",
        "mechanical_tools.ai_weight",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ04",
        "LJ04.welfare_zero_administration_foundation",
        INFO_SOURCE,
        "lj04_welfare_zero_administration_foundation",
        "institution_scores.institution_social_security",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ06",
        "LJ06.employment_food_unemployment_support",
        "common/buildings/01_industry.txt",
        "comparative_employment_active_building_food_industry_pm_bakery_output_groceries",
        "building_food_industry.ai_value",
        "owner",
        "none",
        "multiply",
    ),
    (
        "LJ06",
        "LJ06.employment_textile_unemployment_support",
        "common/buildings/01_industry.txt",
        "lj06_employment_textile_unemployment_support",
        "building_textile_mill.ai_value",
        "owner",
        "none",
        "multiply",
    ),
    (
        "LJ07",
        "LJ07.grain_health_foundation",
        "common/ai_strategies/00_default_strategy.txt",
        "lj07_grain_health_foundation",
        "ai_strategy_default.institution_scores.institution_health_system",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ07",
        "LJ07.grain_health_social_capacity",
        "common/ai_strategies/00_default_strategy.txt",
        "lj07_grain_health_social_capacity",
        "ai_strategy_default.institution_scores.institution_health_system",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ07",
        "LJ07.grain_social_foundation",
        "mod/decisions/information.toml",
        "lj07_grain_social_foundation",
        "institution_scores.institution_social_security",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ07",
        "LJ07.grain_social_capacity",
        "mod/decisions/information.toml",
        "lj07_grain_social_capacity",
        "institution_scores.institution_social_security",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ08",
        "LJ08.government_local_continuity",
        "common/ai_strategies/00_default_strategy.txt",
        "lj08_government_local_continuity",
        "ai_strategy_default.interest_group_government_weight",
        "root",
        "none",
        "add",
    ),
    (
        "LJ08",
        "LJ08.negotiation_local_political_capacity",
        "common/ai_strategies/00_default_strategy.txt",
        "lj08_negotiation_local_political_capacity",
        "ai_strategy_default.negotiation_chance",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ12",
        "LJ12.existing_subject_insolvency_continuity",
        "common/ai_strategies/00_default_strategy.txt",
        "lj12_existing_subject_insolvency_continuity",
        "ai_strategy_default.subject_value",
        "root",
        "none",
        "add",
    ),
    (
        "LJ12",
        "LJ12.existing_overlord_autonomy_cost",
        "common/ai_strategies/00_default_strategy.txt",
        "lj12_existing_overlord_autonomy_cost",
        "ai_strategy_default.become_subject_value",
        "root",
        "none",
        "add",
    ),
    (
        "LJ12",
        "LJ12.actual_subject_autonomy_need",
        "common/ai_strategies/02_subject_diplomatic_strategies.txt",
        "target_strategy_subject_self_need",
        "ai_strategy_subject_strengthen_self.weight",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ12",
        "LJ12.self_strength_administrative_repair",
        "common/ai_strategies/02_subject_diplomatic_strategies.txt",
        "target_strategy_subject_self_repair",
        "ai_strategy_subject_strengthen_self.weight",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ14",
        "LJ14.connected_homeland_foundation",
        "mod/decisions/information.toml",
        "lj14_connected_homeland_foundation",
        "state_value",
        "root",
        "target_state",
        "multiply",
    ),
    (
        "LJ14",
        "LJ14.homeland_isolation_cost",
        "mod/decisions/information.toml",
        "lj14_homeland_isolation_cost",
        "state_value",
        "root",
        "target_state",
        "multiply",
    ),
    (
        "LJ14",
        "LJ14.homeland_administrative_cost",
        "mod/decisions/information.toml",
        "lj14_homeland_administrative_cost",
        "state_value",
        "root",
        "target_state",
        "multiply",
    ),
    (
        "LJ05",
        "LJ05.fiscal_construction_guard",
        "mod/decisions/information.toml",
        "fiscal_construction_guard",
        "wanted_construction_output",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ05",
        "LJ05.liquidity_construction_guard",
        "mod/decisions/information.toml",
        "liquidity_construction_guard",
        "wanted_construction_output",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ05",
        "LJ05.military_capacity_ship_default_cost",
        "common/ai_strategies/00_default_strategy.txt",
        "military_capacity_ship_default_cost",
        "ai_strategy_default.ship_construction_output_multiplier",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ11",
        "LJ11.remaining_reconstruction_need",
        "mod/decisions/information.toml",
        "remaining_reconstruction_need",
        "wanted_construction_output",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ11",
        "LJ11.military_capacity_conscript_need",
        "common/ai_strategies/00_default_strategy.txt",
        "military_capacity_conscript_need",
        "ai_strategy_default.conscript_battalion_ratio",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ09",
        "LJ09.structural_wartime_supply_escort",
        "common/ai_strategies/00_default_strategy.txt",
        "structural_wartime_supply_escort",
        "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ09",
        "LJ09.structural_wartime_supply_price_escort",
        "common/ai_strategies/00_default_strategy.txt",
        "structural_wartime_supply_price_escort",
        "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ09",
        "LJ09.structural_wartime_supply_balance_escort",
        "common/ai_strategies/00_default_strategy.txt",
        "structural_wartime_supply_balance_escort",
        "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ13",
        "LJ13.navy_existing_capacity",
        "mod/decisions/information.toml",
        "navy_existing_capacity",
        "wanted_navy_size",
        "root",
        "none",
        "multiply",
    ),
    (
        "LJ10",
        "LJ10.defensive_pact_flow_pressure",
        INFO_SOURCE,
        "lj10_defensive_pact_flow_pressure",
        "wanted_army_size",
        "root",
        "none",
        "multiply",
    ),
)

_EXPECTED_CONDITIONS = {
    "lj10_defensive_pact_flow_pressure": (
        ("war", "=", False),
        ("default", "=", False),
        ("net_surplus", "<", 0),
        ("defensive_pact_articles", ">=", 1),
        ("native_army_capacity", ">", {"fact_reference": "ROOT.wanted_marines_size_script_value"}),
    ),
    "lj02_coal_output_transport_foundation": (
        ("pm_active_building_coal_mine_pm_picks_and_shovels_building_coal_mine", "=", True),
        ("state_owner_default", "=", False),
        ("state_owner_loans", "=", False),
        ("state_infrastructure", ">=", 0),
        ("state_owner_coal_price", ">", 0.5),
        ("state_owner_coal_balance", "<", 0),
    ),
    "infrastructure_railway_prepared_pm_early_trains": (
        ("state_infrastructure", "<", 0),
        ("pm_active_building_railway_pm_early_trains", "=", True),
        ("state_owner_coal_balance", ">=", 0),
        ("state_owner_coal_price", "<=", 0.25),
        ("state_owner_engines_balance", ">=", 0),
        ("state_owner_engines_price", "<=", 0.25),
    ),
    "lj01_iron_tooling_input_repair": (
        ("pm_active_building_iron_mine_pm_picks_and_shovels_building_iron_mine", "=", True),
        ("pm_active_building_tooling_workshop_pm_pig_iron", "=", True),
        ("state_owner_default", "=", False),
        ("state_owner_loans", "=", False),
        ("state_infrastructure", ">=", 0),
        ("state_owner_iron_price", ">", 0.5),
        ("state_owner_iron_balance", "<", 0),
        ("state_owner_tools_price", ">", 0.5),
        ("state_owner_tools_balance", "<", 0),
        ("state_owner_wood_price", "<=", 0.25),
    ),
    "knowledge_university_researched_foundation": (
        ("state_owner_literacy", "<", 0.5),
        ("state_owner_academia_completed", "=", True),
    ),
    "technology_mechanical_tools_supply_paper": (("country_goods_paper_balance", "<", 0),),
    "lj04_welfare_zero_administration_foundation": (
        ("default", "=", False),
        ("average_sol", "<", 8),
        ("population", ">", 0),
        ("bureaucracy", "=", 0),
    ),
    "comparative_employment_active_building_food_industry_pm_bakery_output_groceries": (
        ("state_owner_default", "=", False),
        ("state_owner_loans", "=", False),
        ("state_infrastructure", ">=", 0),
        ("pm_active_building_food_industry_pm_bakery", "=", True),
        ("state_owner_groceries_price", ">", 0.25),
        ("state_owner_groceries_balance", "<", 0),
        ("state_owner_grain_price", "<=", 0.25),
        ("state_unemployment", ">=", 0.1),
        ("state_owner_reserves", ">", 0),
    ),
    "lj06_employment_textile_unemployment_support": (
        ("pm_active_building_textile_mill_pm_handsewn_clothes", "=", True),
        ("state_owner_clothes_price", ">", 0.25),
        ("state_owner_clothes_balance", "<", 0),
        ("state_unemployment", ">=", 0.1),
        ("state_owner_default", "=", False),
        ("state_owner_fabric_price", "<=", 0.25),
        ("state_owner_fabric_balance", ">=", 0),
        ("state_infrastructure", ">=", 0),
    ),
    "lj07_grain_health_foundation": (
        ("current_charitable_health", "=", True),
        ("grain_price", ">", 0.5),
        ("grain_balance", "<", 0),
    ),
    "lj07_grain_health_social_capacity": (
        ("current_charitable_health", "=", True),
        ("grain_price", ">", 0.5),
        ("grain_balance", "<", 0),
        ("average_sol", "<", 8),
    ),
    "lj07_grain_social_foundation": (
        ("bureaucracy", ">=", 0),
        ("net_surplus", ">=", 0),
        ("grain_price", ">", 0.5),
        ("grain_balance", "<", 0),
        ("default", "=", False),
    ),
    "lj07_grain_social_capacity": (
        ("grain_price", ">", 0.5),
        ("grain_balance", "<", 0),
        ("average_sol", "<", 8),
        ("bureaucracy", ">", 0),
        ("net_surplus", ">", 0),
        ("insurrection", "=", False),
        ("default", "=", False),
    ),
    "lj08_government_local_continuity": (
        ("candidate_ig_clout", ">=", 0.1),
        ("candidate_ig_approval", ">=", 0),
        ("candidate_ig_government", "=", True),
        ("legitimacy", ">=", 35),
        ("insurrection", "=", False),
    ),
    "lj08_negotiation_local_political_capacity": (
        ("candidate_ig_clout", ">=", 0.1),
        ("candidate_ig_approval", "<", 0),
        ("radical_share", ">=", 0.25),
        ("legitimacy", ">=", 50),
        ("insurrection", "=", False),
    ),
    "lj12_existing_subject_insolvency_continuity": (("candidate_existing_subject", "=", True),),
    "lj12_existing_overlord_autonomy_cost": (
        ("current_overlord_relation", "=", True),
        ("liberty", ">=", 75),
    ),
    "target_strategy_subject_self_need": (
        ("actor_is_subject", "=", True),
        ("liberty", ">=", 50),
    ),
    "target_strategy_subject_self_repair": (
        ("actor_is_subject", "=", True),
        ("bureaucracy", "<", 0),
    ),
    "lj14_connected_homeland_foundation": (
        ("target_owned", "=", False),
        ("target_homeland", "=", True),
        ("target_cultural_share", ">=", 0.25),
        ("target_isolated", "=", False),
    ),
    "lj14_homeland_isolation_cost": (
        ("target_owned", "=", False),
        ("target_homeland", "=", True),
        ("target_isolated", "=", True),
    ),
    "lj14_homeland_administrative_cost": (
        ("target_owned", "=", False),
        ("target_homeland", "=", True),
        ("bureaucracy", "<", 0),
    ),
    "fiscal_construction_guard": (("default", "=", True),),
    "liquidity_construction_guard": (
        ("default", "=", False),
        ("loans", "=", True),
        ("debt_ratio", ">=", 0.4),
        ("bankruptcy_horizon", "<", 26),
    ),
    "military_capacity_ship_default_cost": (
        ("navy", ">", 0),
        ("default", "=", True),
    ),
    "remaining_reconstruction_need": (("war_defeat", "=", True),),
    "military_capacity_conscript_need": (
        ("own_army", ">", 0),
        ("war", "=", True),
    ),
    "structural_wartime_supply_escort": (
        ("war", "=", True),
        ("navy", ">", 0),
        ("steamers_price", ">", 0.25),
        ("steamers_balance", "<", 0),
    ),
    "structural_wartime_supply_price_escort": (
        ("war", "=", True),
        ("navy", ">", 0),
        ("steamers_price", ">", 0.25),
    ),
    "structural_wartime_supply_balance_escort": (
        ("war", "=", True),
        ("navy", ">", 0),
        ("steamers_balance", "<", 0),
    ),
    "navy_existing_capacity": (
        ("navy", "<", 10),
        ("gdp", ">", 0),
        ("gold_reserves", ">=", 100),
        ("default", "=", False),
    ),
}

_PRODUCTION_METHODS = {
    "pm_active_building_coal_mine_pm_picks_and_shovels_building_coal_mine": (
        "building_coal_mine",
        "pm_picks_and_shovels_building_coal_mine",
    ),
    "pm_active_building_railway_pm_early_trains": ("building_railway", "pm_early_trains"),
    "pm_active_building_iron_mine_pm_picks_and_shovels_building_iron_mine": (
        "building_iron_mine",
        "pm_picks_and_shovels_building_iron_mine",
    ),
    "pm_active_building_tooling_workshop_pm_pig_iron": ("building_tooling_workshop", "pm_pig_iron"),
    "pm_active_building_food_industry_pm_bakery": ("building_food_industry", "pm_bakery"),
    "pm_active_building_textile_mill_pm_handsewn_clothes": (
        "building_textile_mill",
        "pm_handsewn_clothes",
    ),
}


_COMPLETION_STATES = {
    "lj10_defensive_pact_flow_pressure": "observed_own_treaty_flagged_articles_and_current_negative_flow",
    "lj02_coal_output_transport_foundation": "active_coal_recipe_and_market_pressure",
    "infrastructure_railway_prepared_pm_early_trains": "active_railway_recipe_and_local_infrastructure_pressure",
    "lj01_iron_tooling_input_repair": "active_recipe_and_input_pressure",
    "knowledge_university_researched_foundation": "completed_knowledge_foundation",
    "technology_mechanical_tools_supply_paper": "actual_paper_shortage_and_native_paper_recipe_option",
    "lj04_welfare_zero_administration_foundation": "zero_administration_capacity",
    "comparative_employment_active_building_food_industry_pm_bakery_output_groceries": "active_food_recipe_and_actual_unemployment",
    "lj06_employment_textile_unemployment_support": "active_textile_recipe_and_actual_unemployment",
    "lj07_grain_health_foundation": "current_charitable_health_actual_grain_pressure",
    "lj07_grain_health_social_capacity": "current_charitable_health_actual_grain_pressure_and_low_living_standard",
    "lj07_grain_social_foundation": "actual_grain_pressure_and_nonnegative_capacity",
    "lj07_grain_social_capacity": "actual_grain_pressure_and_available_capacity",
    "lj08_government_local_continuity": "actual_government_member_and_political_capacity",
    "lj08_negotiation_local_political_capacity": "actual_group_discontent_and_political_capacity",
    "lj12_existing_subject_insolvency_continuity": "observed_existing_subject_continuity_independent_of_fiscal_health",
    "lj12_existing_overlord_autonomy_cost": "observed_current_overlord_and_high_liberty_desire",
    "target_strategy_subject_self_need": "actual_subject_and_observed_self_autonomy_need",
    "target_strategy_subject_self_repair": "actual_subject_and_observed_administrative_repair_need",
    "lj14_connected_homeland_foundation": "observed_target_homeland_culture_and_market_connection",
    "lj14_homeland_isolation_cost": "observed_target_homeland_and_isolation",
    "lj14_homeland_administrative_cost": "observed_target_homeland_and_actor_administrative_deficit",
    "fiscal_construction_guard": "actual_default_independent_of_war",
    "liquidity_construction_guard": "observed_credit_pressure_and_short_bankruptcy_horizon",
    "military_capacity_ship_default_cost": "existing_navy_actual_default_financing_cost",
    "remaining_reconstruction_need": "native_recently_lost_war_memory_independent_reconstruction_need",
    "military_capacity_conscript_need": "current_war_and_existing_army_commitment_need",
    "structural_wartime_supply_escort": "existing_navy_and_observed_two_steamers_market_pressures",
    "structural_wartime_supply_price_escort": "existing_navy_and_observed_steamers_price_pressure",
    "structural_wartime_supply_balance_escort": "existing_navy_and_observed_steamers_order_pressure",
    "navy_existing_capacity": "actual_navy_size_gdp_and_gold_reserves",
}


_EXPECTED_REQUIRED_KNOWN = {
    "lj06_employment_textile_unemployment_support": ("state_owner_loans",),
}

_EXPECTED_REFERENCE_FACTS = {
    "lj10_defensive_pact_flow_pressure": ("native_marine_capacity",),
}


def _fingerprint(rule: Any) -> str:
    payload = {
        "id": rule.id,
        "domain": rule.domain,
        "field": ".".join(rule.field),
        "operation": rule.operation,
        "value": rule.value,
        "conditions": [
            {"fact": i.fact, "op": i.op, "value": getattr(i.value, "key", i.value)}
            for i in rule.conditions
        ],
    }
    if getattr(rule, "required_known_facts", ()):
        payload["required_known_facts"] = list(rule.required_known_facts)
    if getattr(rule, "auxiliary_facts", ()):
        payload["auxiliary_facts"] = list(rule.auxiliary_facts)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _condition_semantics(rule: Any) -> tuple[tuple[str, str, object], ...]:
    result = []
    for predicate in rule.conditions:
        value = getattr(predicate, "value", None)
        reference = getattr(value, "expression", None)
        if reference is not None:
            value = {"fact_reference": reference}
        result.append((predicate.fact, getattr(predicate, "op", "="), value))
    return tuple(result)


def _policies() -> dict[str, Any]:
    result = {INFO_SOURCE: decision_rules.load()}
    result.update(dict(decision_adapters.load().policies))
    return result


def build() -> tuple[ChainRuleBinding, ...]:
    policies = _policies()
    result = []
    for chain_id, role, source, rule_id, field, _ in _BINDINGS:
        policy = policies.get(source)
        if policy is None:
            raise ValueError(f"联合链来源不存在：{chain_id}:{source}")
        rule = next((item for item in policy.rules if item.id == rule_id), None)
        if rule is None:
            raise ValueError(f"联合链规则不存在：{chain_id}:{source}:{rule_id}")
        if ".".join(rule.field) != field:
            raise ValueError(f"联合链消费者字段漂移：{chain_id}:{rule_id}")
        result.append(
            ChainRuleBinding(
                chain_id,
                role,
                source,
                rule_id,
                field,
                rule.operation,
                _fingerprint(rule),
                (
                    *tuple(i.fact for i in rule.conditions),
                    *getattr(rule, "required_known_facts", ()),
                ),
                (),
            )
        )
    if len({(i.chain_id, i.role) for i in result}) != len(result):
        raise ValueError("联合链绑定身份重复")
    by_chain: dict[str, list[ChainRuleBinding]] = {}
    for item in result:
        by_chain.setdefault(item.chain_id, []).append(item)
    out = []
    for item in result:
        shared = set(item.condition_facts)
        for peer in by_chain[item.chain_id]:
            if peer is not item:
                shared &= set(peer.condition_facts)
        out.append(
            ChainRuleBinding(
                item.chain_id,
                item.role,
                item.source,
                item.rule_id,
                item.field,
                item.operation,
                item.condition_fingerprint,
                item.condition_facts,
                tuple(sorted(shared)),
                "observed" if shared else "gap",
            )
        )
    return tuple(out)


def _policy_map(policies: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> dict[str, Any]:
    return dict(policies.items()) if isinstance(policies, Mapping) else dict(policies)


def _reader_copy(reader: Any) -> ChainReaderSpec:
    return ChainReaderSpec(
        reader.key,
        reader.engine,
        reader.kind,
        reader.scope,
        tuple(reader.path),
        reader.argument,
        tuple(reader.parameters),
        reader.value_field,
        reader.unit,
        reader.minimum,
        reader.maximum,
    )


def _expected_reader_signature(key: str) -> tuple[Any, ...] | None:
    """Frozen field-level contract for the observed local writer links."""
    native_target_unit = "barracks_levels" if version_contracts.is_115() else "battalions"
    if key == "country_goods_paper_balance":
        return (
            "market_goods_delta",
            "number",
            "root",
            ("market", "mg:paper"),
            None,
            (),
            None,
            "sell_minus_buy_orders",
            None,
            None,
        )
    additional = {
        "current_charitable_health": (
            "has_law_or_variant",
            "boolean",
            "root",
            (),
            "law_type:law_charitable_health_system",
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "defensive_pact_articles": (
            "num_defensive_pacts",
            "number",
            "root",
            (),
            None,
            (),
            None,
            "treaty_article_count",
            0,
            None,
        ),
        "native_army_capacity": (
            "wanted_army_size_script_value",
            "number",
            "root",
            (),
            None,
            (),
            None,
            native_target_unit,
            None,
            None,
        ),
        "native_marine_capacity": (
            "wanted_marines_size_script_value",
            "number",
            "root",
            (),
            None,
            (),
            None,
            native_target_unit,
            None,
            None,
        ),
        "bankruptcy_horizon": (
            "weeks_until_bankruptcy",
            "number",
            "root",
            (),
            None,
            (),
            None,
            "weeks",
            0,
            None,
        ),
        "debt_ratio": (
            "scaled_debt",
            "number",
            "root",
            (),
            None,
            (),
            None,
            "debt_to_credit_ratio",
            0,
            None,
        ),
        "gdp": ("gdp", "number", "root", (), None, (), None, "annual_gdp_currency", 0, None),
        "gold_reserves": (
            "gold_reserves",
            "number",
            "root",
            (),
            None,
            (),
            None,
            "currency",
            0,
            None,
        ),
        "income": (
            "fixed_income",
            "number",
            "root",
            (),
            None,
            (),
            None,
            "currency_per_week",
            None,
            None,
        ),
        "infamy": ("infamy", "number", "root", (), None, (), None, "infamy_points", 0, None),
        "loans": ("taking_loans", "boolean", "root", (), None, (), None, "boolean", None, None),
        "navy": ("navy_size", "number", "root", (), None, (), None, "ships", 0, None),
        "own_army": ("army_size", "number", "root", (), None, (), None, "battalions", 0, None),
        "actor_is_subject": (
            "is_subject",
            "boolean",
            "root",
            (),
            None,
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "small_arms_balance": (
            "market_goods_delta",
            "number",
            "root",
            ("market", "mg:small_arms"),
            None,
            (),
            None,
            "sell_minus_buy_orders",
            None,
            None,
        ),
        "small_arms_price": (
            "market_goods_pricier",
            "number",
            "root",
            ("market", "mg:small_arms"),
            None,
            (),
            None,
            "price_above_base_ratio",
            None,
            None,
        ),
        "steamers_balance": (
            "market_goods_delta",
            "number",
            "root",
            ("market", "mg:steamers"),
            None,
            (),
            None,
            "sell_minus_buy_orders",
            None,
            None,
        ),
        "steamers_price": (
            "market_goods_pricier",
            "number",
            "root",
            ("market", "mg:steamers"),
            None,
            (),
            None,
            "price_above_base_ratio",
            None,
            None,
        ),
        "war_defeat": (
            "has_variable",
            "boolean",
            "root",
            (),
            "recently_lost_war",
            (),
            None,
            "boolean",
            None,
            None,
        ),
    }
    if key in additional:
        return additional[key]
    if key in _PRODUCTION_METHODS:
        building, method = _PRODUCTION_METHODS[key]
        return (
            "is_production_method_active",
            "boolean",
            "root",
            (),
            None,
            (("building_type", building), ("production_method", method)),
            None,
            "boolean",
            None,
            None,
        )
    if key in {"state_owner_default", "default"}:
        return (
            "in_default",
            "boolean",
            "root",
            ("owner",) if key.startswith("state_owner_") else (),
            None,
            (),
            None,
            "boolean",
            None,
            None,
        )
    if key == "state_owner_loans":
        return (
            "taking_loans",
            "boolean",
            "root",
            ("owner",),
            None,
            (),
            None,
            "boolean",
            None,
            None,
        )
    if key == "state_owner_reserves":
        return (
            "gold_reserves",
            "number",
            "root",
            ("owner",),
            None,
            (),
            None,
            "currency",
            None,
            None,
        )
    if key == "state_infrastructure":
        return (
            "infrastructure_delta",
            "number",
            "root",
            (),
            None,
            (),
            None,
            "infrastructure_points",
            None,
            None,
        )
    if key.startswith("state_owner_") and key.endswith("_price"):
        good = key.removeprefix("state_owner_").removesuffix("_price")
        return (
            "market_goods_pricier",
            "number",
            "root",
            ("owner", "market", f"mg:{good}"),
            None,
            (),
            None,
            "price_above_base_ratio",
            None,
            None,
        )
    if key.startswith("state_owner_") and key.endswith("_balance"):
        good = key.removeprefix("state_owner_").removesuffix("_balance")
        return (
            "market_goods_delta",
            "number",
            "root",
            ("owner", "market", f"mg:{good}"),
            None,
            (),
            None,
            "sell_minus_buy_orders",
            None,
            None,
        )
    if key == "state_transport_price":
        return (
            "state_goods_pricier",
            "number",
            "root",
            ("sg:transportation",),
            None,
            (),
            None,
            "price_above_base_ratio",
            None,
            None,
        )
    if key == "state_owner_academia_completed":
        return (
            "has_technology_researched",
            "boolean",
            "root",
            ("owner",),
            "academia",
            (),
            None,
            "boolean",
            None,
            None,
        )
    if key in {"state_owner_literacy", "literacy"}:
        return (
            "literacy_rate",
            "number",
            "root",
            ("owner",) if key.startswith("state_owner_") else (),
            None,
            (),
            None,
            "ratio",
            0,
            1,
        )
    if key == "state_unemployment":
        return ("state_unemployment_rate", "number", "root", (), None, (), None, "ratio", 0, 1)
    if key == "insurrection":
        return (
            "has_insurrectionary_interest_groups",
            "boolean",
            "root",
            (),
            None,
            (),
            None,
            "boolean",
            None,
            None,
        )
    if key in {"tools_price", "tools_balance", "grain_price", "grain_balance"}:
        return (
            "market_goods_pricier" if key.endswith("_price") else "market_goods_delta",
            "number",
            "root",
            ("market", f"mg:{key.rsplit('_', 1)[0]}"),
            None,
            (),
            None,
            "price_above_base_ratio" if key.endswith("_price") else "sell_minus_buy_orders",
            None,
            None,
        )
    scalar = {
        "average_sol": ("average_sol", "standard_of_living", 0),
        "population": ("total_population", "persons", 0),
        "bureaucracy": ("bureaucracy", "capacity_balance", None),
        "net_surplus": ("net_total_income", "currency_per_week", None),
    }.get(key)
    if scalar is not None:
        engine, unit, minimum = scalar
        return (engine, "number", "root", (), None, (), None, unit, minimum, None)
    named = {
        "candidate_existing_subject": (
            "is_subject_of",
            "boolean",
            "target_country",
            (),
            "root",
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "candidate_ig_approval": (
            "ig_approval",
            "number",
            "interest_group",
            (),
            None,
            (),
            None,
            "approval_points",
            None,
            None,
        ),
        "candidate_ig_clout": (
            "ig_clout",
            "number",
            "interest_group",
            (),
            None,
            (),
            None,
            "ratio",
            0,
            1,
        ),
        "candidate_ig_government": (
            "is_in_government",
            "boolean",
            "interest_group",
            (),
            None,
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "candidate_overlord_war": (
            "is_at_war",
            "boolean",
            "overlord",
            (),
            None,
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "current_overlord_relation": (
            "is_subject_of",
            "boolean",
            "root",
            (),
            "scope:overlord",
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "legitimacy": (
            "legitimacy",
            "number",
            "root",
            (),
            None,
            (),
            None,
            "legitimacy_0_100",
            0,
            100,
        ),
        "liberty": (
            "liberty_desire",
            "number",
            "root",
            (),
            None,
            (),
            None,
            "liberty_0_100",
            0,
            100,
        ),
        "radical_share": (
            "radical_fraction",
            "number",
            "root",
            (),
            None,
            (),
            "value",
            "ratio",
            0,
            1,
        ),
        "target_cultural_share": (
            "primary_cultures_percent_state",
            "number",
            "target_state",
            (),
            None,
            (("target_country", "root"),),
            "value",
            "ratio",
            0,
            1,
        ),
        "target_homeland": (
            "is_homeland_of_country_cultures",
            "boolean",
            "target_state",
            (),
            "root",
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "target_isolated": (
            "is_isolated_from_market",
            "boolean",
            "target_state",
            (),
            None,
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "target_owned": (
            "owner",
            "boolean",
            "target_state",
            (),
            "root",
            (),
            None,
            "boolean",
            None,
            None,
        ),
        "war": ("is_at_war", "boolean", "root", (), None, (), None, "boolean", None, None),
    }
    return named.get(key)


def _reader_signature(reader: ChainReaderSpec) -> tuple[Any, ...]:
    return (
        reader.engine,
        reader.kind,
        reader.scope,
        reader.path,
        reader.argument,
        reader.parameters,
        reader.value_field,
        reader.unit,
        reader.minimum,
        reader.maximum,
    )


def build_strict(
    bundle: Any, policies: Mapping[str, Any] | Iterable[tuple[str, Any]]
) -> tuple[ChainEvidence, ...]:
    policy_map = _policy_map(policies)
    writers = tuple(getattr(bundle, "writers", ()))
    result = []
    for (
        chain_id,
        link_id,
        source,
        rule_id,
        expected_field,
        expected_actor,
        expected_target,
        expected_operation,
    ) in _STRICT_TARGETS:
        policy = policy_map.get(source)
        if policy is None:
            raise ValueError(f"联合链来源不存在：{chain_id}:{source}")
        rules = [i for i in policy.rules if i.id == rule_id]
        if len(rules) != 1:
            raise ValueError(f"联合链规则必须唯一：{chain_id}:{source}:{rule_id}")
        rule = rules[0]
        required_known = getattr(rule, "required_known_facts", ())
        if required_known != _EXPECTED_REQUIRED_KNOWN.get(rule_id, ()):
            raise ValueError(f"联合链核心知识声明漂移：{chain_id}:{rule_id}")
        reference_facts = tuple(
            i.value.key for i in rule.conditions if getattr(i.value, "expression", None) is not None
        )
        if reference_facts != _EXPECTED_REFERENCE_FACTS.get(rule_id, ()):
            raise ValueError(f"联合链相对比较事实来源漂移：{chain_id}:{rule_id}")
        facts = (*tuple(i.fact for i in rule.conditions), *reference_facts, *required_known)
        if any(any(token in fact for token in ("selected", "queued")) for fact in facts):
            raise ValueError(f"联合链拒绝候选态冒充完成态：{chain_id}:{rule_id}")
        semantics = _condition_semantics(rule)
        if semantics != _EXPECTED_CONDITIONS[rule_id]:
            raise ValueError(f"联合链谓词、运算符或阈值漂移：{chain_id}:{rule_id}")
        matches = [
            i
            for i in writers
            if i.kind == "rule_action" and i.source == source and i.definition == rule_id
        ]
        if len(matches) != 1:
            raise ValueError(f"联合链缺少唯一生产 writer：{chain_id}:{source}:{rule_id}")
        writer = matches[0]
        field = ".".join(rule.field)
        if (
            field != expected_field
            or rule.operation != expected_operation
            or writer.field != expected_field
            or writer.operation != expected_operation
            or writer.actor != expected_actor
            or writer.target != expected_target
        ):
            raise ValueError(f"联合链 writer 字段或操作漂移：{chain_id}:{rule_id}")
        readers_by_key: dict[str, list[Any]] = {}
        for reader in policy.readers:
            readers_by_key.setdefault(reader.key, []).append(reader)
        if len(set(facts)) != len(facts):
            raise ValueError(f"联合链证据事实重复：{chain_id}:{rule_id}")
        invalid = [
            fact
            for fact in facts
            if len(readers_by_key.get(fact, ())) != 1
            or _expected_reader_signature(fact) is None
            or _reader_signature(_reader_copy(readers_by_key[fact][0]))
            != _expected_reader_signature(fact)
        ]
        if invalid:
            raise ValueError(
                f"联合链读取器字段级来源、作用域或类型漂移：{chain_id}:{rule_id}:{invalid}"
            )
        readers = tuple(_reader_copy(readers_by_key[fact][0]) for fact in facts)
        recipe = tuple(f for f in facts if f.startswith("pm_active_"))
        if chain_id == "LJ01" and not recipe:
            raise ValueError("LJ01 必须保留实际配方读取器")
        if (
            chain_id == "LJ03"
            and rule_id.endswith("university_completed_knowledge_foundation")
            and "state_owner_academia_completed" not in facts
        ):
            raise ValueError("LJ03 大学链必须使用完成态读取器")
        if any(any(token in f for token in ("selected", "queued")) for f in facts):
            raise ValueError(f"联合链拒绝候选态冒充完成态：{chain_id}:{rule_id}")
        completion = _COMPLETION_STATES[rule_id]
        spec = ChainLinkSpec(
            chain_id,
            link_id,
            source,
            rule_id,
            field,
            writer.actor,
            writer.target,
            rule.operation,
            readers,
            semantics,
            recipe,
            completion,
            "consumer",
            1,
            "vanilla",
            "observed_static_only",
            required_known,
        )
        paths = tuple(i.path for i in readers)
        if len({_reader_signature(i) for i in readers}) != len(readers):
            raise ValueError(f"联合链证据路径重复：{chain_id}:{rule_id}")
        result.append(ChainEvidence(spec, writer.writer_id, writer.owner, paths))
    return tuple(result)


build_links = build_strict


def validate_links(evidence: tuple[ChainEvidence, ...], bundle: Any | None = None) -> None:
    if not evidence:
        raise ValueError("联合链严格证据不能为空")
    if len({(i.spec.chain_id, i.spec.link_id) for i in evidence}) != len(evidence):
        raise ValueError("联合链证据身份重复")
    expected_targets = {row[1]: row for row in _STRICT_TARGETS}
    expected_completion = _COMPLETION_STATES
    for item in evidence:
        spec = item.spec
        if spec.max_hops not in {1, 2} or not spec.readers or not spec.field:
            raise ValueError(f"联合链局部规格无效：{spec.link_id}")
        target = expected_targets.get(spec.link_id)
        if target is None or (
            spec.chain_id,
            spec.source,
            spec.rule_id,
            spec.field,
            spec.actor,
            spec.target,
            spec.operation,
        ) != (target[0], target[2], target[3], target[4], target[5], target[6], target[7]):
            raise ValueError(f"联合链 writer 身份、作用域或操作漂移：{spec.link_id}")
        if len(spec.readers) != len({i.key for i in spec.readers}):
            raise ValueError(f"联合链读取器重复：{spec.link_id}")
        expected_semantics = _EXPECTED_CONDITIONS.get(spec.rule_id)
        if expected_semantics is None or spec.condition_semantics != expected_semantics:
            raise ValueError(f"联合链条件事实、运算符或阈值漂移：{spec.link_id}")
        expected_known = _EXPECTED_REQUIRED_KNOWN.get(spec.rule_id, ())
        if spec.required_known_facts != expected_known:
            raise ValueError(f"联合链核心知识声明漂移：{spec.link_id}")
        if tuple(reader.key for reader in spec.readers) != (
            *tuple(fact for fact, _operator, _value in expected_semantics),
            *_EXPECTED_REFERENCE_FACTS.get(spec.rule_id, ()),
            *expected_known,
        ):
            raise ValueError(f"联合链条件顺序与读取器映射漂移：{spec.link_id}")
        for reader in spec.readers:
            expected_signature = _expected_reader_signature(reader.key)
            if expected_signature is None or _reader_signature(reader) != expected_signature:
                raise ValueError(f"联合链读取器来源、作用域或类型漂移：{spec.link_id}:{reader.key}")
        expected_recipe = tuple(
            fact for fact, _operator, _value in expected_semantics if fact.startswith("pm_active_")
        )
        if (
            spec.recipe != expected_recipe
            or spec.completion_state != expected_completion.get(spec.rule_id)
            or spec.refresh != "consumer"
            or spec.max_hops != 1
            or spec.unknown != "vanilla"
        ):
            raise ValueError(f"联合链局部状态或边界漂移：{spec.link_id}")
        if spec.status in {"completed", "selected", "queued"} or any(
            w in spec.completion_state for w in ("selected", "queued")
        ):
            raise ValueError(f"联合链拒绝把候选或完成标签当作生产完成：{spec.link_id}")
        if spec.status != "observed_static_only":
            raise ValueError(f"联合链局部状态或边界漂移：{spec.link_id}")
        if item.evidence_state != "static" or item.evidence_paths != tuple(
            reader.path for reader in spec.readers
        ):
            raise ValueError(f"联合链证据路径或类别漂移：{spec.link_id}")
        if bundle is not None:
            matches = [i for i in bundle.writers if i.writer_id == item.writer_id]
            if len(matches) != 1:
                raise ValueError(f"联合链 writer 不存在或不唯一：{spec.link_id}")
            writer = matches[0]
            if item.owner != writer.owner:
                raise ValueError(f"联合链 writer owner 漂移：{spec.link_id}")
            if (
                writer.source,
                writer.definition,
                writer.field,
                writer.actor,
                writer.target,
                writer.operation,
            ) != (spec.source, spec.rule_id, spec.field, spec.actor, spec.target, spec.operation):
                raise ValueError(f"联合链 writer 与规格不一致：{spec.link_id}")


def _bundle_chain_refs(bundle: ConsumerIRBundle) -> dict[str, tuple[tuple[str, str], ...]]:
    by_identity = {(writer.source, writer.definition): writer for writer in bundle.writers}
    if len(by_identity) != len(bundle.writers):
        raise ValueError("联合链生产 writer 来源身份重复")
    expected: dict[str, list[tuple[str, str]]] = {}
    for chain_id, link_id, source, rule_id, field, actor, target, operation in _STRICT_TARGETS:
        writer = by_identity.get((source, rule_id))
        if writer is None or (
            writer.kind,
            writer.field,
            writer.actor,
            writer.target,
            writer.operation,
        ) != ("rule_action", field, actor, target, operation):
            raise ValueError(f"联合链生产 writer 身份或目标漂移：{chain_id}:{rule_id}")
        expected.setdefault(writer.writer_id, []).append((chain_id, link_id))
    return {writer_id: tuple(sorted(refs)) for writer_id, refs in expected.items()}


def validate_bundle_refs(bundle: ConsumerIRBundle) -> None:
    """Reject missing, forged or cross-target chain provenance before lowering."""
    expected = _bundle_chain_refs(bundle)
    bindings = tuple(
        sorted(
            (writer_id, chain, link) for writer_id, refs in expected.items() for chain, link in refs
        )
    )
    if bundle.chain_bindings != bindings:
        raise ValueError("联合链 ConsumerIR 绑定清单缺失或漂移")
    for writer in bundle.writers:
        if writer.chain_refs != expected.get(writer.writer_id, ()):
            raise ValueError(f"联合链 writer 引用缺失或漂移：{writer.writer_id}")


def bind_bundle(
    bundle: ConsumerIRBundle, policies: tuple[tuple[str, decision_rules.RuleSet], ...]
) -> ConsumerIRBundle:
    """Bind exact current production links once, with no compiler reload or weight changes.

    This proves local source-to-consumer provenance.  Full-chain six-case witnesses
    and every other D9 exit remain independent acceptance requirements.
    """
    if len({source for source, _policy in policies}) != len(policies):
        raise ValueError("联合链生产策略来源重复")
    evidence = build_strict(bundle, policies)
    validate_links(evidence, bundle)
    expected = _bundle_chain_refs(bundle)
    writers = {writer.writer_id: writer for writer in bundle.writers}
    policy_map = dict(policies)
    for link in evidence:
        writer = writers[link.writer_id]
        rule = next(
            rule for rule in policy_map[link.spec.source].rules if rule.id == link.spec.rule_id
        )
        # build_strict checks the source against the frozen semantic contract.
        # Compare full source values here to retain both FactReference key and
        # expression identity, which the portable semantic projection omits.
        predicates = tuple((item.fact, item.op, item.value) for item in rule.conditions)
        if (
            writer.legacy is None
            or writer.predicates != predicates
            or writer.legacy.predicates != predicates
            or writer.legacy.required_known_facts != link.spec.required_known_facts
        ):
            raise ValueError(f"联合链生产 writer 语义漂移：{link.spec.link_id}")
    if (
        bundle.chains_bound
        or bundle.chain_bindings
        or any(writer.chain_refs for writer in bundle.writers)
    ):
        validate_bundle_refs(bundle)
    result = replace(
        bundle,
        writers=tuple(
            replace(writer, chain_refs=expected.get(writer.writer_id, ()))
            for writer in bundle.writers
        ),
        chains_bound=True,
        chain_bindings=tuple(
            sorted(
                (writer_id, chain, link)
                for writer_id, refs in expected.items()
                for chain, link in refs
            )
        ),
    )
    validate_bundle_refs(result)
    return result


def contract(bindings: tuple[ChainRuleBinding, ...] | None = None) -> dict[str, object]:
    if bindings is None:
        bindings = build()
    return {
        "schema": 1,
        "count": len(bindings),
        "status": "observed_static_only",
        "bindings": [
            {
                "chain_id": i.chain_id,
                "role": i.role,
                "source": i.source,
                "rule_id": i.rule_id,
                "field": i.field,
                "operation": i.operation,
                "condition_fingerprint": i.condition_fingerprint,
                "condition_facts": list(i.condition_facts),
                "bridge_facts": list(i.bridge_facts),
                "status": i.status,
            }
            for i in bindings
        ],
    }


def strict_contract(evidence: tuple[ChainEvidence, ...]) -> dict[str, object]:
    validate_links(evidence)
    rows: list[dict[str, Any]] = [
        {
            "chain_id": i.spec.chain_id,
            "link_id": i.spec.link_id,
            "source": i.spec.source,
            "rule_id": i.spec.rule_id,
            "field": i.spec.field,
            "actor": i.spec.actor,
            "target": i.spec.target,
            "readers": [
                {
                    "key": r.key,
                    "engine": r.engine,
                    "kind": r.kind,
                    "path": list(r.path),
                    "argument": r.argument,
                    "parameters": list(r.parameters),
                    "value_field": r.value_field,
                    "unit": r.unit,
                    "minimum": r.minimum,
                    "maximum": r.maximum,
                    "scope": r.scope,
                }
                for r in i.spec.readers
            ],
            **(
                {"required_known_facts": list(i.spec.required_known_facts)}
                if i.spec.required_known_facts
                else {}
            ),
            "condition_semantics": [
                {"fact": fact, "operator": operator, "value": value}
                for fact, operator, value in i.spec.condition_semantics
            ],
            "recipe": list(i.spec.recipe),
            "completion_state": i.spec.completion_state,
            "refresh": i.spec.refresh,
            "max_hops": i.spec.max_hops,
            "unknown": i.spec.unknown,
            "status": i.spec.status,
            "writer_id": i.writer_id,
            "owner": i.owner,
            "evidence_state": i.evidence_state,
        }
        for i in evidence
    ]
    return {
        "schema": 3,
        "count": len(rows),
        "status": "observed_static_only",
        "locally_witnessed_chains": sorted({row["chain_id"] for row in rows}),
        "pending_chain_closure": [f"LJ{i:02d}" for i in range(1, 15)],
        "pending_uncovered_chains": [
            f"LJ{i:02d}"
            for i in range(1, 15)
            if f"LJ{i:02d}" not in {row["chain_id"] for row in rows}
        ],
        "links": rows,
    }


def validate(bindings: tuple[ChainRuleBinding, ...] | None = None) -> None:
    expected = build()
    actual = expected if bindings is None else bindings
    if [(i.chain_id, i.role, i.source, i.rule_id) for i in actual] != [
        (i.chain_id, i.role, i.source, i.rule_id) for i in expected
    ]:
        raise ValueError("联合链绑定与当前生产规则目录不一致")
    for item, current in zip(actual, expected, strict=True):
        if (
            item.condition_fingerprint != current.condition_fingerprint
            or item.condition_facts != current.condition_facts
        ):
            raise ValueError(f"联合链条件指纹或事实漂移：{item.chain_id}:{item.rule_id}")


__all__ = [
    "INFO_SOURCE",
    "ChainEvidence",
    "ChainLinkSpec",
    "ChainReaderSpec",
    "ChainRuleBinding",
    "bind_bundle",
    "build",
    "build_links",
    "build_strict",
    "contract",
    "strict_contract",
    "validate",
    "validate_bundle_refs",
    "validate_links",
]
