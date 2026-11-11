"""Reviewed 1.15.1 strategy contracts from current RTTI, tokens and caller graph.

Each coordinate is frozen independently of the manifest loaded at runtime.
Historical candidate windows assisted discovery; they grant no current scope.
"""

from __future__ import annotations

CONTRACTS = {
    "consumers": {
        "weight": {
            "actor_scope": "country",
            "target_scope": "definition_only:ai_strategy",
            "operation": "base_candidate_score",
            "capability": "direct",
            "unit": "candidate_score",
            "consumer_va": "0x141668d14",
            "parser_va": "0x14183b1b0",
            "member_offset": "0xb8",
        },
        "possible": {
            "actor_scope": "country",
            "target_scope": "definition_only:ai_strategy",
            "operation": "eligibility",
            "capability": "direct",
            "unit": "predicate",
            "consumer_va": "0x141668b0b",
            "parser_va": "0x14183b191",
            "member_offset": "0x40",
        },
        "wanted_army_size": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_army_size_target",
            "capability": "direct",
            "unit": "barracks_levels",
            "consumer_va": "0x14183e75d",
            "parser_va": "0x14183bd37",
            "member_offset": "0x1840",
        },
        "recklessness": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_strength_estimate_multiplier",
            "capability": "direct",
            "unit": "multiplier",
            "consumer_va": "0x14183f78f",
            "parser_va": "0x14183bca4",
            "member_offset": "0x10c0",
        },
        "max_progressiveness": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "override_progressiveness_limit",
            "capability": "direct",
            "unit": "progressiveness",
            "consumer_va": "0x14184137d",
            "parser_va": "0x14183bd8b",
            "member_offset": "0xa98",
        },
        "max_regressiveness": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "override_regressiveness_limit",
            "capability": "direct",
            "unit": "regressiveness",
            "consumer_va": "0x14184150d",
            "parser_va": "0x14183bda0",
            "member_offset": "0xb58",
        },
        "change_law_chance": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "first_nonzero_active_change_law_chance_else_default",
            "capability": "direct",
            "unit": "percentage_points",
            "consumer_va": "0x141840ead",
            "parser_va": "0x14183bdb5",
            "member_offset": "0xc18",
        },
        "wargoal_maneuvers_fraction": {
            "actor_scope": "country",
            "target_scope": "scope:enemy_country=country",
            "operation": "additive_maneuvers_fraction",
            "capability": "direct",
            "unit": "fraction",
            "consumer_va": "0x14184205f",
            "parser_va": "0x14183bdca",
            "member_offset": "0x798",
        },
        "obligation_value": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_obligation_valuation",
            "capability": "direct",
            "unit": "valuation",
            "consumer_va": "0x14183faef",
            "parser_va": "0x14183bcb9",
            "member_offset": "0x1240",
        },
        "min_law_chance_to_pass": {
            "actor_scope": "country",
            "target_scope": "scope:law=law",
            "operation": "override_pass_chance_threshold",
            "capability": "direct",
            "unit": "pass_chance",
            "consumer_va": "0x1418411f3",
            "parser_va": "0x14183bd76",
            "member_offset": "0x9d8",
        },
        "revolution_aversion": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "override_revolution_aversion",
            "capability": "direct",
            "unit": "daily_stop_tendency",
            "consumer_va": "0x14184103d",
            "parser_va": "0x14183bd61",
            "member_offset": "0x918",
        },
        "subject_value": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_subject_valuation",
            "capability": "direct",
            "unit": "valuation",
            "consumer_va": "0x14183ff6f",
            "parser_va": "0x14183bcce",
            "member_offset": "0x1300",
        },
        "become_subject_value": {
            "actor_scope": "country",
            "target_scope": "scope:overlord=country",
            "operation": "additive_subject_valuation",
            "capability": "direct",
            "unit": "valuation",
            "consumer_va": "0x14184011f",
            "parser_va": "0x14183bce3",
            "member_offset": "0x13c0",
        },
        "wanted_construction_output": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_construction_output_target",
            "capability": "direct",
            "unit": "construction_output",
            "consumer_va": "0x141840a50",
            "parser_va": "0x14183bd22",
            "member_offset": "0x16c0",
        },
        "institution_scores": {
            "actor_scope": "country",
            "target_scope": "definition_only:institution_type",
            "operation": "additive_score",
            "capability": "direct",
            "unit": "score",
            "definition_key": "resolved institution definition pointer; not a named script scope",
            "consumer_va": "0x14183ef0a",
            "parser_va": "0x14183bc90",
            "member_offset": "0x3f0",
        },
        "wargoal_scores": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country;scope:target_state=state",
            "operation": "additive_score",
            "capability": "direct",
            "unit": "score",
            "child_projection": "exact enum child numeric body",
            "consumer_va": "0x14183ddba",
            "parser_va": "0x14183b6f5",
            "member_offset": "0x1d8",
        },
        "secret_goal_scores": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_score",
            "capability": "direct",
            "unit": "score",
            "child_projection": "exact enum child.score only; trigger remains native filter",
            "consumer_va": "0x14183dbcd",
            "parser_va": "0x14183b923",
            "member_offset": "0x2c0",
        },
        "wanted_navy_size": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_navy_size_target",
            "capability": "direct",
            "unit": "naval_administration_levels",
            "consumer_va": "0x141625737",
            "parser_va": "0x14183bd4c",
            "member_offset": "0x1a80",
        },
        "ship_construction_output_multiplier": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_ship_construction_output_multiplier",
            "capability": "direct",
            "unit": "multiplier",
            "consumer_va": "0x141625e5b",
            "parser_va": "0x14183c098",
            "member_offset": "0x1c00",
        },
        "aggression": {
            "actor_scope": "country",
            "target_scope": "scope:target_country=country",
            "operation": "additive_aggression",
            "capability": "direct",
            "unit": "play_start_tendency",
            "consumer_va": "0x14183f93f",
            "parser_va": "0x14183b9ec",
            "member_offset": "0x1180",
        },
        "nationalization_desire": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_nationalization_desire",
            "capability": "direct",
            "unit": "desire",
            "consumer_va": "0x14184239d",
            "parser_va": "0x14183bf2c",
            "member_offset": "0xd98",
        },
        "max_active_stances": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_active_stance_limit",
            "capability": "direct",
            "unit": "count",
            "consumer_va": "0x14184252c",
            "parser_va": "0x14183c1fa",
            "member_offset": "0x4b8",
        },
        "wanted_marines": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_marine_size_target",
            "capability": "direct",
            "unit": "barracks_levels",
            "consumer_va": "0x14183e8ed",
            "parser_va": "0x14183c02f",
            "member_offset": "0x1900",
        },
        "economic_vs_government_spending_balance": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_spending_balance",
            "capability": "direct",
            "unit": "debt_threshold_ratio",
            "consumer_va": "0x141840d1d",
            "parser_va": "0x14183c01a",
            "member_offset": "0x1780",
        },
        "target_marine_formation_size": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_marine_formation_size_target",
            "capability": "direct",
            "unit": "units_per_formation",
            "consumer_va": "0x14183ea7d",
            "parser_va": "0x14183c044",
            "member_offset": "0x19c0",
        },
        "unacceptable_infamy_level": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "first_positive_infamy_limit_override",
            "capability": "direct",
            "unit": "infamy",
            "consumer_va": "0x14183e5cd",
            "parser_va": "0x14183b8ff",
            "member_offset": "0x1000",
        },
        "undesirable_infamy_level": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "first_positive_infamy_limit_override",
            "capability": "direct",
            "unit": "infamy",
            "consumer_va": "0x14183e43d",
            "parser_va": "0x14183b911",
            "member_offset": "0xf40",
        },
        "diplomatic_play_neutrality": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_positive_active_neutrality",
            "capability": "direct",
            "unit": "score",
            "consumer_va": "0x141841d0c",
            "parser_va": "0x14183bcf8",
            "member_offset": "0x628",
        },
        "diplomatic_play_boldness": {
            "actor_scope": "country",
            "target_scope": "scope:diplomatic_play=diplomatic_play",
            "operation": "native_randomized_additive_boldness",
            "capability": "direct",
            "unit": "score",
            "consumer_va": "0x141841b7a",
            "parser_va": "0x14183bd0d",
            "member_offset": "0x6e0",
        },
        "treaty_category_scores": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_treaty_category_score",
            "capability": "direct",
            "unit": "score",
            "child_projection": "exact enum child numeric body",
            "consumer_va": "0x14183df79",
            "parser_va": "0x14183b27f",
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
            "definition "
            "pointer; not a "
            "named script scope",
            "child_projection": "exact stance definition child numeric body",
            "consumer_va": "0x1418428fa",
            "parser_va": "0x14183bf60",
            "member_offset": "0x490",
        },
        "wanted_num_supply_ships": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_supply_ship_count_target",
            "capability": "direct",
            "unit": "ships",
            "consumer_va": "0x1416259bf",
            "parser_va": "0x14183c059",
            "member_offset": "0x1b40",
        },
        "max_ship_design_complexity": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_ship_design_complexity_limit",
            "capability": "direct",
            "unit": "modification_levels",
            "consumer_va": "0x14167210b",
            "parser_va": "0x14183c083",
            "member_offset": "0x1d80",
        },
    },
    "rtti": {
        "type_descriptor_va": "0x1456833b0",
        "parser_col_va": "0x144cc9920",
        "parser_vftable_va": "0x14479ecd8",
        "parser_subobject": "0x20d8",
        "parser_thunk_va": "0x140849604",
        "parser_va": "0x14183af70",
        "constructor_va": "0x14183a180",
    },
    "scope_key_registrations": {
        "target_country": {
            "literal_va": "0x1446a3028",
            "registration_va": "0x1400128b0",
            "global_va": "0x145cd5d38",
        },
        "overlord": {
            "literal_va": "0x1446a3240",
            "registration_va": "0x1400136f0",
            "global_va": "0x145cd5f6c",
        },
        "enemy_country": {
            "literal_va": "0x1446a3308",
            "registration_va": "0x140013d50",
            "global_va": "0x145cd5a88",
        },
        "law": {
            "literal_va": "0x1446999ac",
            "registration_va": "0x140014110",
            "global_va": "0x145cd5ae8",
        },
        "diplomatic_play": {
            "literal_va": "0x14469b690",
            "registration_va": "0x140012490",
            "global_va": "0x145cd5c98",
        },
        "target_state": {
            "literal_va": "0x1446a30b0",
            "registration_va": "0x140012c70",
            "global_va": "0x145cd5db4",
        },
        "target_region": {
            "literal_va": "0x1446a3078",
            "registration_va": "0x140012790",
            "global_va": "0x145cd5900",
        },
        "region_score": {
            "literal_va": "0x1446a3890",
            "registration_va": "0x1400158b0",
            "global_va": "0x145cd5b7c",
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
                "key_va": "0x145cd5c98",
                "registration_va": "0x14183dda0",
                "condition": "play id != -1",
                "reader_authorization": False,
            }
        }
    },
    "law_instance_type": {
        "scope_tag": "0x31",
        "native_type": "CCountryLaw",
        "type_descriptor_va": "0x145687be8",
        "link_type_descriptor_va": "0x145972918",
        "link_col_va": "0x144e33af0",
        "link_vftable_va": "0x144905258",
        "link_method_va": "0x14298d7e0",
        "resolver_va": "0x140980610",
        "law_type_output_tag": "0x32",
    },
    "diplomatic_play_instance_type": {
        "scope_tag": "0x1c",
        "native_type": "CDiplomaticPlay",
        "type_descriptor_va": "0x145682568",
        "link_type_descriptor_va": "0x14596bba0",
        "link_col_va": "0x144e40f40",
        "link_vftable_va": "0x144907518",
        "link_method_va": "0x14298d130",
        "resolver_va": "0x14097fa40",
    },
    "strategic_region_type": {
        "scope_tag": "0x52",
        "native_database": "CStrategicRegionsDatabase",
        "link_type_descriptor_va": "0x14596b250",
        "link_col_va": "0x144e37db8",
        "link_vftable_va": "0x1449022f8",
        "link_method_va": "0x1429bcea0",
        "resolver_va": "0x14099f710",
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
            "function": "0x14161ed70",
            "default_call": "0x14161ede5",
            "active_call": "0x14161ee25",
            "operation": "additive_score",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "wargoal_scores": {
            "function": "0x141629d40",
            "default_call": "0x141629e6d",
            "active_call": "0x141629ec8",
            "operation": "additive_score",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "treaty_category_scores": {
            "function": "0x14160e310",
            "default_call": "0x14160e3a4",
            "active_call": "0x14160e3ca",
            "operation": "additive_treaty_category_score",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "undesirable_infamy_level": {
            "function": "0x141621ed0",
            "default_call": "0x141621f55",
            "active_call": "0x141621f7e",
            "operation": "first_positive_infamy_limit_override",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime "
            "getter permission",
        },
        "unacceptable_infamy_level": {
            "function": "0x141622190",
            "default_call": "0x141622215",
            "active_call": "0x14162223e",
            "operation": "first_positive_infamy_limit_override",
            "native_tail": "retained in "
            "complete observed "
            "caller; no generic "
            "runtime getter "
            "permission",
        },
        "wanted_army_size": {
            "function": "0x1416249b0",
            "default_call": "0x141624a34",
            "active_call": "0x141624a6e",
            "operation": "additive_army_size_target",
            "native_tail": "retained in complete "
            "observed caller; no generic "
            "runtime getter permission",
        },
        "wanted_marines": {
            "function": "0x141624b00",
            "default_call": "0x141624b84",
            "active_call": "0x141624bbe",
            "operation": "additive_marine_size_target",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "target_marine_formation_size": {
            "function": "0x1416253d0",
            "default_call": "0x141625454",
            "active_call": "0x14162548e",
            "operation": "additive_marine_formation_size_target",
            "native_tail": "retained in "
            "complete "
            "observed caller; "
            "no generic "
            "runtime getter "
            "permission",
        },
        "institution_scores": {
            "function": "0x141635cf0",
            "default_call": "0x141635d80",
            "active_call": "0x141635db1",
            "operation": "additive_score",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "recklessness": {
            "function": "0x141624120",
            "default_call": "0x14162420a",
            "active_call": "0x14162423d",
            "operation": "additive_strength_estimate_multiplier",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "aggression": {
            "function": "0x1416225e0",
            "default_call": "0x141622671",
            "active_call": "0x1416226a2",
            "operation": "additive_aggression",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime getter "
            "permission",
        },
        "obligation_value": {
            "function": "0x1416227a0",
            "default_call": "0x141622828",
            "active_call": "0x141622861",
            "operation": "additive_obligation_valuation",
            "native_tail": "retained in complete "
            "observed caller; no generic "
            "runtime getter permission",
        },
        "subject_value": {
            "function": "0x141622b50",
            "default_call": "0x141622be2",
            "active_call": "0x141622c11",
            "operation": "additive_subject_valuation",
            "native_tail": "retained in complete observed "
            "caller; no generic runtime "
            "getter permission",
        },
        "become_subject_value": {
            "function": "0x141622e50",
            "default_call": "0x141622eeb",
            "active_call": "0x141622f21",
            "operation": "additive_subject_valuation",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "wanted_construction_output": {
            "function": "0x1416242a0",
            "default_call": "0x14162437f",
            "active_call": "0x1416243aa",
            "operation": "additive_construction_output_target",
            "native_tail": "retained in "
            "complete observed "
            "caller; no generic "
            "runtime getter "
            "permission",
        },
        "economic_vs_government_spending_balance": {
            "function": "0x141654c00",
            "default_call": "0x14165511e",
            "active_call": "0x14165514d",
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
            "function": "0x1415f2040",
            "default_call": "0x1415f222c",
            "active_call": "0x1415f21cd",
            "operation": "first_nonzero_active_change_law_chance_else_default",
            "native_tail": "retained in complete "
            "observed caller; no generic "
            "runtime getter permission",
            "active_nonzero_exit": "0x1415f21dc",
            "selection": "First nonzero active result "
            "exits the loop at "
            "0x1415f25f5; only all-zero "
            "active results evaluate the "
            "default strategy. Zero is not "
            "summed and the active result "
            "may be negative.",
        },
        "revolution_aversion": {
            "function": "0x1416334a0",
            "default_call": "0x141633505",
            "active_call": "0x14163354e",
            "operation": "override_revolution_aversion",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "min_law_chance_to_pass": {
            "function": "0x141633800",
            "default_call": "0x141633863",
            "active_call": "0x1416338ce",
            "operation": "override_pass_chance_threshold",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "max_progressiveness": {
            "function": "0x1415f2040",
            "default_call": "0x1415f2385",
            "active_call": "0x1415f23ad",
            "operation": "override_progressiveness_limit",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "max_regressiveness": {
            "function": "0x1415f2040",
            "default_call": "0x1415f2451",
            "active_call": "0x1415f247d",
            "operation": "override_regressiveness_limit",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "diplomatic_play_boldness": {
            "function": "0x141630d40",
            "default_call": "0x141630d77",
            "active_call": "0x141630dd9",
            "operation": "native_randomized_additive_boldness",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime "
            "getter permission",
        },
        "diplomatic_play_neutrality": {
            "function": "0x14162f660",
            "default_call": "0x14162f6ac",
            "active_call": "0x14162f7b9",
            "operation": "additive_positive_active_neutrality",
            "native_tail": "retained in "
            "complete observed "
            "caller; no generic "
            "runtime getter "
            "permission",
        },
        "wargoal_maneuvers_fraction": {
            "function": "0x1415da820",
            "default_call": "0x1415dab42",
            "active_call": "0x1415dab70",
            "operation": "additive_maneuvers_fraction",
            "native_tail": "retained in "
            "complete observed "
            "caller; no generic "
            "runtime getter "
            "permission",
        },
        "nationalization_desire": {
            "function": "0x1415e8800",
            "default_call": "0x1415e8916",
            "active_call": "0x1415e893b",
            "operation": "additive_nationalization_desire",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "max_active_stances": {
            "function": "0x141644ed0",
            "default_call": "0x141644f2b",
            "active_call": "0x141644f76",
            "operation": "additive_active_stance_limit",
            "native_tail": "retained in complete "
            "observed caller; no "
            "generic runtime getter "
            "permission",
        },
        "strategic_region_stance_type_scores": {
            "function": "0x141644bb0",
            "default_call": "0x141644cc2",
            "active_call": "0x141644d5d",
            "operation": "additive_region_stance_score",
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
        "wanted_navy_size": {
            "function": "0x141625690",
            "default_call": "0x141625737",
            "active_call": "0x14162578d",
            "add_va": "0x141625792",
            "operation": "additive_navy_size_target",
        },
        "wanted_num_supply_ships": {
            "function": "0x141625820",
            "default_call": "0x1416259bf",
            "active_call": "0x141625b72",
            "operation": "additive_supply_ship_count_target",
        },
        "ship_construction_output_multiplier": {
            "function": "0x141625d50",
            "default_call": "0x141625e5b",
            "active_call": "0x141625f33",
            "operation": "additive_ship_construction_output_multiplier",
        },
        "max_ship_design_complexity": {
            "function": "0x141671910",
            "default_call": "0x14167210b",
            "active_call": "0x1416722af",
            "operation": "additive_ship_design_complexity_limit",
        },
    },
}
