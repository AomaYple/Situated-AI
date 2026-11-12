"""Exact current strategy permissions from independently reviewed 1.15 PE evidence.

The historical validator stays separate. This module never projects old VAs or
infers arbitrary readers from a country-tagged container.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

_CONTRACTS = {
    "consumers": {
        "weight": {
            "actor_scope": "country",
            "target_scope": "definition_only:ai_strategy",
            "operation": "base_candidate_score",
            "capability": "direct",
            "unit": "candidate_score",
            "consumer_va": "0x141656424",
            "parser_va": "0x141823040",
            "member_offset": "0xb8",
        },
        "possible": {
            "actor_scope": "country",
            "target_scope": "definition_only:ai_strategy",
            "operation": "eligibility",
            "capability": "direct",
            "unit": "predicate",
            "consumer_va": "0x14165621b",
            "parser_va": "0x141823021",
            "member_offset": "0x40",
        },
        "wanted_army_size": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_army_size_target",
            "capability": "direct",
            "unit": "barracks_levels",
            "consumer_va": "0x1418265ed",
            "parser_va": "0x141823bc7",
            "member_offset": "0x1840",
        },
        "recklessness": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_strength_estimate_multiplier",
            "capability": "direct",
            "unit": "multiplier",
            "consumer_va": "0x14182761f",
            "parser_va": "0x141823b34",
            "member_offset": "0x10c0",
        },
        "max_progressiveness": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "override_progressiveness_limit",
            "capability": "direct",
            "unit": "progressiveness",
            "consumer_va": "0x14182920d",
            "parser_va": "0x141823c1b",
            "member_offset": "0xa98",
        },
        "max_regressiveness": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "override_regressiveness_limit",
            "capability": "direct",
            "unit": "regressiveness",
            "consumer_va": "0x14182939d",
            "parser_va": "0x141823c30",
            "member_offset": "0xb58",
        },
        "change_law_chance": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "first_nonzero_active_change_law_chance_else_default",
            "capability": "direct",
            "unit": "percentage_points",
            "consumer_va": "0x141828d3d",
            "parser_va": "0x141823c45",
            "member_offset": "0xc18",
        },
        "wargoal_maneuvers_fraction": {
            "actor_scope": "country",
            "target_scope": "scope:enemy_country=country",
            "operation": "additive_maneuvers_fraction",
            "capability": "direct",
            "unit": "fraction",
            "consumer_va": "0x141829eef",
            "parser_va": "0x141823c5a",
            "member_offset": "0x798",
        },
        "obligation_value": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_obligation_valuation",
            "capability": "direct",
            "unit": "valuation",
            "consumer_va": "0x14182797f",
            "parser_va": "0x141823b49",
            "member_offset": "0x1240",
        },
        "min_law_chance_to_pass": {
            "actor_scope": "country",
            "target_scope": "scope:law=law",
            "operation": "override_pass_chance_threshold",
            "capability": "direct",
            "unit": "pass_chance",
            "consumer_va": "0x141829083",
            "parser_va": "0x141823c06",
            "member_offset": "0x9d8",
        },
        "revolution_aversion": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "override_revolution_aversion",
            "capability": "direct",
            "unit": "daily_stop_tendency",
            "consumer_va": "0x141828ecd",
            "parser_va": "0x141823bf1",
            "member_offset": "0x918",
        },
        "subject_value": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_subject_valuation",
            "capability": "direct",
            "unit": "valuation",
            "consumer_va": "0x141827dff",
            "parser_va": "0x141823b5e",
            "member_offset": "0x1300",
        },
        "become_subject_value": {
            "actor_scope": "country",
            "target_scope": "scope:overlord=country",
            "operation": "additive_subject_valuation",
            "capability": "direct",
            "unit": "valuation",
            "consumer_va": "0x141827faf",
            "parser_va": "0x141823b73",
            "member_offset": "0x13c0",
        },
        "wanted_construction_output": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_construction_output_target",
            "capability": "direct",
            "unit": "construction_output",
            "consumer_va": "0x1418288e0",
            "parser_va": "0x141823bb2",
            "member_offset": "0x16c0",
        },
        "institution_scores": {
            "actor_scope": "country",
            "target_scope": "definition_only:institution_type",
            "operation": "additive_score",
            "capability": "direct",
            "unit": "score",
            "definition_key": "resolved institution definition pointer; not a named script scope",
            "consumer_va": "0x141826d9a",
            "parser_va": "0x141823b20",
            "member_offset": "0x3f0",
        },
        "wargoal_scores": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country;scope:target_state=state",
            "operation": "additive_score",
            "capability": "direct",
            "unit": "score",
            "child_projection": "exact enum child numeric body",
            "consumer_va": "0x141825c4a",
            "parser_va": "0x141823585",
            "member_offset": "0x1d8",
        },
        "secret_goal_scores": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_score",
            "capability": "direct",
            "unit": "score",
            "child_projection": "exact enum child.score only; trigger remains native filter",
            "consumer_va": "0x141825a5d",
            "parser_va": "0x1418237b3",
            "member_offset": "0x2c0",
        },
        "wanted_navy_size": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_navy_size_target",
            "capability": "direct",
            "unit": "naval_administration_levels",
            "consumer_va": "0x1416139a7",
            "parser_va": "0x141823bdc",
            "member_offset": "0x1a80",
        },
        "ship_construction_output_multiplier": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_ship_construction_output_multiplier",
            "capability": "direct",
            "unit": "multiplier",
            "consumer_va": "0x1416140cb",
            "parser_va": "0x141823f28",
            "member_offset": "0x1c00",
        },
        "aggression": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_aggression",
            "capability": "direct",
            "unit": "play_start_tendency",
            "consumer_va": "0x1418277cf",
            "parser_va": "0x14182387c",
            "member_offset": "0x1180",
        },
        "nationalization_desire": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_nationalization_desire",
            "capability": "direct",
            "unit": "desire",
            "consumer_va": "0x14182a22d",
            "parser_va": "0x141823dbc",
            "member_offset": "0xd98",
        },
        "max_active_stances": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_active_stance_limit",
            "capability": "direct",
            "unit": "count",
            "consumer_va": "0x14182a3bc",
            "parser_va": "0x14182408a",
            "member_offset": "0x4b8",
        },
        "wanted_marines": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_marine_size_target",
            "capability": "direct",
            "unit": "barracks_levels",
            "consumer_va": "0x14182677d",
            "parser_va": "0x141823ebf",
            "member_offset": "0x1900",
        },
        "economic_vs_government_spending_balance": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_spending_balance",
            "capability": "direct",
            "unit": "debt_threshold_ratio",
            "consumer_va": "0x141828bad",
            "parser_va": "0x141823eaa",
            "member_offset": "0x1780",
        },
        "target_marine_formation_size": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_marine_formation_size_target",
            "capability": "direct",
            "unit": "units_per_formation",
            "consumer_va": "0x14182690d",
            "parser_va": "0x141823ed4",
            "member_offset": "0x19c0",
        },
        "unacceptable_infamy_level": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "first_positive_infamy_limit_override",
            "capability": "direct",
            "unit": "infamy",
            "consumer_va": "0x14182645d",
            "parser_va": "0x14182378f",
            "member_offset": "0x1000",
        },
        "undesirable_infamy_level": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "first_positive_infamy_limit_override",
            "capability": "direct",
            "unit": "infamy",
            "consumer_va": "0x1418262cd",
            "parser_va": "0x1418237a1",
            "member_offset": "0xf40",
        },
        "diplomatic_play_neutrality": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_positive_active_neutrality",
            "capability": "direct",
            "unit": "score",
            "consumer_va": "0x141829b9c",
            "parser_va": "0x141823b88",
            "member_offset": "0x628",
        },
        "diplomatic_play_boldness": {
            "actor_scope": "country",
            "target_scope": "scope:diplomatic_play=diplomatic_play",
            "operation": "native_randomized_additive_boldness",
            "capability": "direct",
            "unit": "score",
            "consumer_va": "0x141829a0a",
            "parser_va": "0x141823b9d",
            "member_offset": "0x6e0",
        },
        "treaty_category_scores": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_treaty_category_score",
            "capability": "direct",
            "unit": "score",
            "child_projection": "exact enum child numeric body",
            "consumer_va": "0x141825e09",
            "parser_va": "0x14182310f",
            "member_offset": "0x1f0",
        },
        "strategic_region_stance_type_scores": {
            "actor_scope": "country",
            "target_scope": "scope:target_region=strategic_region;scope:region_score=scalar",
            "operation": "additive_region_stance_score",
            "capability": "direct",
            "unit": "score",
            "definition_key": "resolved strategic "
            "region stance "
            "definition pointer; "
            "not a named script "
            "scope",
            "child_projection": "exact stance definition child numeric body",
            "consumer_va": "0x14182a78a",
            "parser_va": "0x141823df0",
            "member_offset": "0x490",
        },
        "wanted_num_supply_ships": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_supply_ship_count_target",
            "capability": "direct",
            "unit": "ships",
            "consumer_va": "0x141613c2f",
            "parser_va": "0x141823ee9",
            "member_offset": "0x1b40",
        },
        "max_ship_design_complexity": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_ship_design_complexity_limit",
            "capability": "direct",
            "unit": "modification_levels",
            "consumer_va": "0x14165f81b",
            "parser_va": "0x141823f13",
            "member_offset": "0x1d80",
        },
    },
    "rtti": {
        "type_descriptor_va": "0x14564f5b0",
        "parser_col_va": "0x144c98d48",
        "parser_vftable_va": "0x144760b18",
        "parser_subobject": "0x20d8",
        "parser_thunk_va": "0x1408418a8",
        "parser_va": "0x141822e00",
        "constructor_va": "0x141822010",
    },
    "scope_key_registrations": {
        "target_country": {
            "literal_va": "0x14467a448",
            "registration_va": "0x140012850",
            "global_va": "0x145c9ebd8",
        },
        "overlord": {
            "literal_va": "0x14467a668",
            "registration_va": "0x140013690",
            "global_va": "0x145c9ee0c",
        },
        "enemy_country": {
            "literal_va": "0x14467a738",
            "registration_va": "0x140013cf0",
            "global_va": "0x145c9e924",
        },
        "law": {
            "literal_va": "0x144671524",
            "registration_va": "0x1400140b0",
            "global_va": "0x145c9e980",
        },
        "diplomatic_play": {
            "literal_va": "0x1446732a8",
            "registration_va": "0x140012430",
            "global_va": "0x145c9eb38",
        },
        "target_state": {
            "literal_va": "0x14467a4e8",
            "registration_va": "0x140012c10",
            "global_va": "0x145c9ec54",
        },
        "target_region": {
            "literal_va": "0x14467a4a8",
            "registration_va": "0x140012730",
            "global_va": "0x145c9e790",
        },
        "region_score": {
            "literal_va": "0x14467ac88",
            "registration_va": "0x140015850",
            "global_va": "0x145c9ea14",
        },
    },
    "strategy_score_keys": {
        "wargoal_scores": [
            "annex_country",
            "ban_slavery",
            "break_enforced_treaties",
            "colonization_rights",
            "conquer_state",
            "contain_threat",
            "demand_no_strait_closure",
            "demand_no_tolls",
            "demand_strait_access",
            "demand_toll_exemption",
            "enforce_treaty_article",
            "force_nationalization",
            "foreign_investment_rights",
            "humiliation",
            "increase_autonomy",
            "independence",
            "join_power_bloc",
            "leave_power_bloc",
            "liberate_country",
            "liberate_subject",
            "make_subject",
            "open_market",
            "reduce_autonomy",
            "regime_change",
            "release_as_subject",
            "return_state",
            "revoke_all_claims",
            "revoke_claim",
            "secession",
            "take_treaty_port",
            "transfer_subject",
            "unification",
            "unification_leadership",
            "custom",
        ],
        "treaty_category_scores": [
            "economy",
            "trade",
            "military",
            "military_defense",
            "ideology",
            "expansion",
            "power_bloc",
            "other",
            "none",
        ],
        "secret_goal_scores": [
            "none",
            "befriend",
            "reconcile",
            "protect",
            "antagonize",
            "conquer",
            "dominate",
            "comply",
            "defy",
        ],
    },
    "native_unprojected_contexts": {
        "wargoal_scores": {
            "diplomatic_play": {
                "status": "unprojected_unknown",
                "scope_tag": "0x1c",
                "key_va": "0x145c9eb38",
                "registration_va": "0x141825c30",
                "condition": "play id != -1",
                "reader_authorization": False,
            }
        }
    },
    "law_instance_type": {
        "scope_tag": "0x31",
        "native_type": "CCountryLaw",
        "type_descriptor_va": "0x145653d98",
        "link_type_descriptor_va": "0x145934748",
        "link_col_va": "0x144e11700",
        "link_vftable_va": "0x1448f3050",
        "link_method_va": "0x1429668c0",
        "resolver_va": "0x1409784e0",
        "law_type_output_tag": "0x32",
    },
    "diplomatic_play_instance_type": {
        "scope_tag": "0x1c",
        "native_type": "CDiplomaticPlay",
        "type_descriptor_va": "0x14564e768",
        "link_type_descriptor_va": "0x14593c8d8",
        "link_col_va": "0x144e06518",
        "link_vftable_va": "0x1448e3760",
        "link_method_va": "0x142966210",
        "resolver_va": "0x140977910",
    },
    "strategic_region_type": {
        "scope_tag": "0x52",
        "native_database": "CStrategicRegionsDatabase",
        "link_type_descriptor_va": "0x145933ad0",
        "link_col_va": "0x144e139c8",
        "link_vftable_va": "0x1448e25a0",
        "link_method_va": "0x142995f80",
        "resolver_va": "0x140997290",
        "id_member": "0x10",
    },
    "institution_definition_sources": {
        "common/institutions/00_institutions.txt": "9d3b8474e2e99a34cd23cc38343253b850d0b2991a0f9418c85577c68c8ece2b"
    },
    "institution_definitions": {
        "institution_colonial_affairs": {
            "source": "common/institutions/00_institutions.txt",
            "line": 1,
        },
        "institution_social_security": {
            "source": "common/institutions/00_institutions.txt",
            "line": 9,
        },
        "institution_workplace_safety": {
            "source": "common/institutions/00_institutions.txt",
            "line": 18,
        },
        "institution_schools": {"source": "common/institutions/00_institutions.txt", "line": 26},
        "institution_police": {"source": "common/institutions/00_institutions.txt", "line": 31},
        "institution_health_system": {
            "source": "common/institutions/00_institutions.txt",
            "line": 39,
        },
        "institution_home_affairs": {
            "source": "common/institutions/00_institutions.txt",
            "line": 44,
        },
    },
    "stance_definition_sources": {
        "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt": "add54c251b0fb2a37a6038b308ed9e67709d44f7ec0a5aac0bc03346afccb91d"
    },
    "stance_definitions": {
        "stance_none": {
            "source": "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt",
            "line": 3,
        },
        "stance_conquer_region": {
            "source": "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt",
            "line": 7,
        },
        "stance_protect_region": {
            "source": "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt",
            "line": 14,
        },
        "stance_colonize_region": {
            "source": "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt",
            "line": 21,
        },
    },
    "strategy_field_merges": {
        "secret_goal_scores": {
            "function": "0x14160d920",
            "default_call": "0x14160d995",
            "active_call": "0x14160d9d5",
            "operation": "additive_score",
            "native_tail": "retained in complete "
            "observed caller; no generic "
            "runtime getter permission",
        },
        "wargoal_scores": {
            "function": "0x141617fb0",
            "default_call": "0x1416180dd",
            "active_call": "0x141618138",
            "operation": "additive_score",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "treaty_category_scores": {
            "function": "0x1415fd200",
            "default_call": "0x1415fd294",
            "active_call": "0x1415fd2ba",
            "operation": "additive_treaty_category_score",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "undesirable_infamy_level": {
            "function": "0x141610140",
            "default_call": "0x1416101c5",
            "active_call": "0x1416101ee",
            "operation": "first_positive_infamy_limit_override",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime "
            "getter permission",
        },
        "unacceptable_infamy_level": {
            "function": "0x141610400",
            "default_call": "0x141610485",
            "active_call": "0x1416104ae",
            "operation": "first_positive_infamy_limit_override",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime "
            "getter permission",
        },
        "wanted_army_size": {
            "function": "0x141612c20",
            "default_call": "0x141612ca4",
            "active_call": "0x141612cde",
            "operation": "additive_army_size_target",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "wanted_marines": {
            "function": "0x141612d70",
            "default_call": "0x141612df4",
            "active_call": "0x141612e2e",
            "operation": "additive_marine_size_target",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "target_marine_formation_size": {
            "function": "0x141613640",
            "default_call": "0x1416136c4",
            "active_call": "0x1416136fe",
            "operation": "additive_marine_formation_size_target",
            "native_tail": "retained in "
            "complete observed "
            "caller; no "
            "generic runtime "
            "getter "
            "permission",
        },
        "institution_scores": {
            "function": "0x141623f60",
            "default_call": "0x141623ff0",
            "active_call": "0x141624021",
            "operation": "additive_score",
            "native_tail": "retained in complete "
            "observed caller; no generic "
            "runtime getter permission",
        },
        "recklessness": {
            "function": "0x141612390",
            "default_call": "0x14161247a",
            "active_call": "0x1416124ad",
            "operation": "additive_strength_estimate_multiplier",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime getter "
            "permission",
        },
        "aggression": {
            "function": "0x141610850",
            "default_call": "0x1416108e1",
            "active_call": "0x141610912",
            "operation": "additive_aggression",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime getter "
            "permission",
        },
        "obligation_value": {
            "function": "0x141610a10",
            "default_call": "0x141610a98",
            "active_call": "0x141610ad1",
            "operation": "additive_obligation_valuation",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "subject_value": {
            "function": "0x141610dc0",
            "default_call": "0x141610e52",
            "active_call": "0x141610e81",
            "operation": "additive_subject_valuation",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "become_subject_value": {
            "function": "0x1416110c0",
            "default_call": "0x14161115b",
            "active_call": "0x141611191",
            "operation": "additive_subject_valuation",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "wanted_construction_output": {
            "function": "0x141612510",
            "default_call": "0x1416125ef",
            "active_call": "0x14161261a",
            "operation": "additive_construction_output_target",
            "native_tail": "retained in "
            "complete observed "
            "caller; no generic "
            "runtime getter "
            "permission",
        },
        "economic_vs_government_spending_balance": {
            "function": "0x141642340",
            "default_call": "0x141642852",
            "active_call": "0x14164287e",
            "operation": "additive_spending_balance",
            "native_tail": "retained "
            "in "
            "complete "
            "observed "
            "caller; "
            "no "
            "generic "
            "runtime "
            "getter "
            "permission",
        },
        "change_law_chance": {
            "function": "0x1415e0d70",
            "default_call": "0x1415e0f4c",
            "active_call": "0x1415e0eed",
            "operation": "first_nonzero_active_change_law_chance_else_default",
            "active_nonzero_exit": "0x1415e0efc",
            "selection": "First nonzero active result exits the loop at 0x1415e1315; only all-zero active results evaluate the default strategy. Zero is not summed and the active result may be negative.",
            "native_tail": "retained in complete "
            "observed caller; no generic "
            "runtime getter permission",
        },
        "revolution_aversion": {
            "function": "0x141621710",
            "default_call": "0x141621775",
            "active_call": "0x1416217be",
            "operation": "override_revolution_aversion",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "min_law_chance_to_pass": {
            "function": "0x141621a70",
            "default_call": "0x141621ad3",
            "active_call": "0x141621b3e",
            "operation": "override_pass_chance_threshold",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "max_progressiveness": {
            "function": "0x1415e0d70",
            "default_call": "0x1415e10a5",
            "active_call": "0x1415e10cd",
            "operation": "override_progressiveness_limit",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "max_regressiveness": {
            "function": "0x1415e0d70",
            "default_call": "0x1415e1171",
            "active_call": "0x1415e119d",
            "operation": "override_regressiveness_limit",
            "native_tail": "retained in complete "
            "observed caller; no generic "
            "runtime getter permission",
        },
        "diplomatic_play_boldness": {
            "function": "0x14161efb0",
            "default_call": "0x14161efe7",
            "active_call": "0x14161f049",
            "operation": "native_randomized_additive_boldness",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime "
            "getter permission",
        },
        "diplomatic_play_neutrality": {
            "function": "0x14161d8d0",
            "default_call": "0x14161d91c",
            "active_call": "0x14161da29",
            "operation": "additive_positive_active_neutrality",
            "native_tail": "retained in "
            "complete observed "
            "caller; no generic "
            "runtime getter "
            "permission",
        },
        "wargoal_maneuvers_fraction": {
            "function": "0x1415cb0c0",
            "default_call": "0x1415cb3e2",
            "active_call": "0x1415cb410",
            "operation": "additive_maneuvers_fraction",
            "native_tail": "retained in "
            "complete observed "
            "caller; no generic "
            "runtime getter "
            "permission",
        },
        "nationalization_desire": {
            "function": "0x1415d7530",
            "default_call": "0x1415d7646",
            "active_call": "0x1415d766b",
            "operation": "additive_nationalization_desire",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "max_active_stances": {
            "function": "0x141632ff0",
            "default_call": "0x14163304b",
            "active_call": "0x141633096",
            "operation": "additive_active_stance_limit",
            "native_tail": "retained in complete "
            "observed caller; no generic "
            "runtime getter permission",
        },
        "strategic_region_stance_type_scores": {
            "function": "0x141632cd0",
            "default_call": "0x141632de2",
            "active_call": "0x141632e7d",
            "operation": "additive_region_stance_score",
            "native_tail": "retained "
            "in "
            "complete "
            "observed "
            "caller; no "
            "generic "
            "runtime "
            "getter "
            "permission",
        },
        "wanted_navy_size": {
            "function": "0x141613900",
            "default_call": "0x1416139a7",
            "active_call": "0x1416139fd",
            "add_va": "0x141613a02",
            "operation": "additive_navy_size_target",
        },
        "wanted_num_supply_ships": {
            "function": "0x141613a90",
            "default_call": "0x141613c2f",
            "active_call": "0x141613de2",
            "operation": "additive_supply_ship_count_target",
        },
        "ship_construction_output_multiplier": {
            "function": "0x141613fc0",
            "default_call": "0x1416140cb",
            "active_call": "0x1416141a3",
            "operation": "additive_ship_construction_output_multiplier",
        },
        "max_ship_design_complexity": {
            "function": "0x14165f020",
            "default_call": "0x14165f81b",
            "active_call": "0x14165f9bf",
            "operation": "additive_ship_design_complexity_limit",
        },
    },
}


def validate(data: Mapping[str, Any]) -> None:
    """Reject permission, exact member, target identity and merge-contract drift."""
    from pdx import version_contracts  # noqa: PLC0415

    contracts = _CONTRACTS
    if version_contracts.active_version() == "1.15.1":
        from .engine_strategy_1151 import CONTRACTS  # noqa: PLC0415

        contracts = CONTRACTS
    for name, expected in contracts.items():
        if data.get(name) != expected:
            raise ValueError(f"1.15 策略独立字段合同不一致：{name}")
    if data.get("evidence_kind") != "binary_static" or data.get("runtime") != "unknown":
        raise ValueError("1.15 策略证据类别不一致")
    for family in ("institution", "stance"):
        sources = data[family + "_definition_sources"]
        raw_sources = data.get(family + "_definition_bytes", {})
        if set(raw_sources) != set(sources) or any(
            hashlib.sha256(bytes.fromhex(raw)).hexdigest() != sources[source]
            for source, raw in raw_sources.items()
        ):
            raise ValueError(f"1.15 策略 {family} 定义原始字节不一致")
    # Exact current observations must cover every field's own parser branch and
    # own consumer, not merely a shared country container or another field.
    intervals = tuple(
        (int(point["va"], 16), int(point["va"], 16) + len(bytes.fromhex(point["bytes"])))
        for point in data["observations"]
    )
    for field, contract in data["consumers"].items():
        for key in ("parser_va", "consumer_va"):
            address = int(contract[key], 16)
            if not any(start <= address < end for start, end in intervals):
                raise ValueError(f"1.15 策略精确字段缺少真实观察：{field}.{key}")
