# 13 · common 全量键名索引

> 对 `game\common\` 下**全部 136 个子目录、3,099 个 .txt 文件**做机械提取，
> 得到 **25,790 个顶层定义键**。本文回答「**什么东西定义在哪个目录**」。

**提取口径**

```text
规则：行首无缩进（^）、排除以 # 开头的注释行、匹配 `键名 = {`
键名字符集：不含空白与 = 的任意字符（含连字符 -）
```

## 勘误：早期版本漏计了含连字符的键

本文早期版本用枚举字符类提取键名，**静默漏掉了含连字符 `-` 的键**。
实测全库共 **32 个**含连字符的顶层键，分布在 4 个目录：

| 目录 | 含连字符的键数 | 修正前 | 修正后 |
|---|---:|---:|---:|
| `character_templates` | 27 | 1,983 | **2,011** |
| `production_methods` | 3 | 433 | **436** |
| `technology` | 1 | 183 | **184** |
| `power_bloc_names` | 1 | 199 | **200** |

> **教训：解析 PDX 键名不要假设字符集。** 用取反字符组而非枚举字符类。

## 全部 136 个目录

| 目录 | .txt 文件 | 顶层键 | 官方文档 | 键名示例（前 6 个） |
|---|---:|---:|---|---|| `acceptance_statuses` | 1 | 5 | readme.md | violent_hostility, cultural_erasure, open_prejudice, second_rate_citizen, full_acceptance |
| `achievements` | 9 | 141 | — | peccavi, perkeletankki, luxurious_luxembourg, anarchy_in_the_uk, muhammed_alis_ambition, an_empire_under_the_pun |
| `ai_strategic_region_stance_types` | 1 | 4 | ai_strategic_region_stance_types.md | stance_none, stance_conquer_region, stance_protect_region, stance_colonize_region |
| `ai_strategies` | 5 | 35 | — | ai_strategy_default, ai_strategy_agricultural_expansion, ai_strategy_plantation_economy, ai_strategy_resource_expansion, ai_strategy_industrial_expansion, ai_strategy_placate_population |
| `alert_groups` | 1 | 24 | — | isolated_states, states_in_turmoil, high_tensions, secession_growing, diplomatic_pact_in_danger, treaty_article_in_danger |
| `alert_types` | 1 | 68 | — | country_default, low_war_support_effects_alert, has_no_research_alert, major_formable_possible, formable_possible, can_establish_company |
| `amendments` | 6 | 67 | amendments.md | amendment_geheime_staatskonferenz_metternich, amendment_geheime_staatskonferenz_kolowrat, amendment_reinstated_fueros, amendment_economic_regeneration_1, amendment_economic_regeneration_2, amendment_frugal_ordinance |
| `battle_conditions` | 1 | 21 | battle_condition.md | battle_condition_pursuit, battle_condition_panicked_retreat, battle_condition_controlled_retreat, battle_condition_dug_in, battle_condition_charted_terrain, battle_condition_rapid_advance |
| `building_groups` | 1 | 69 | — | bg_manufacturing, bg_light_industry, bg_heavy_industry, bg_military_industry, bg_agriculture, bg_staple_crops |
| `buildings` | 14 | 115 | buildings.md | building_food_industry, building_textile_mill, building_furniture_manufactory, building_glassworks, building_tooling_workshop, building_paper_mill |
| `buy_packages` | 1 | 99 | — | wealth_1, wealth_2, wealth_3, wealth_4, wealth_5, wealth_6 |
| `character_interactions` | 4 | 21 | — | grant_command_to_ruler, remove_command_from_ruler, grant_leadership_to_agitator, grant_command_to_agitator, marry_ruler_or_heir, abdicate_monarch |
| `character_roles` | 3 | 10 | character_roles.md | character_role_ruler, character_role_heir, character_role_general, character_role_admiral, character_role_executive, character_role_magnate |
| `character_templates` | 210 | 2011 | — | default, character_template_colonial_governor_plantation, character_template_colonial_governor_local, character_template_colonial_governor_extraction, character_template_colonial_governor_business, character_template_colonial_governor_military |
| `character_traits` | 5 | 121 | character_traits.md | alcoholic, opium_addiction, cocaine_addiction, cancer, tuberculosis, grifter |
| `coat_of_arms` | 0 | 1701 | — | NULL, sub_ENG_coa, sub_SCO_coa, sub_IRE_coa, sub_FRA_coa, sub_GBR |
| `cohesion_levels` | 1 | 5 | — | cohesion_level_very_low, cohesion_level_low, cohesion_level_moderate, cohesion_level_high, cohesion_level_very_high |
| `combat_unit_experience_levels` | 1 | 5 | — | no_veterancy, veterancy1, veterancy2, veterancy3, veterancy4 |
| `combat_unit_groups` | 1 | 4 | — | combat_unit_group_infantry, combat_unit_group_artillery, combat_unit_group_cavalry, combat_unit_group_marines |
| `combat_unit_types` | 1 | 19 | — | combat_unit_type_irregular_infantry, combat_unit_type_line_infantry, combat_unit_type_skirmish_infantry, combat_unit_type_trench_infantry, combat_unit_type_squad_infantry, combat_unit_type_mechanized_infantry |
| `commander_orders` | 2 | 12 | orders.md | advance, advance_reckless, advance_pillager, advance_cautious, advance_heavy_barrage, advance_cavalry_assualt |
| `commander_ranks` | 1 | 6 | — | commander_rank_1, commander_rank_2, commander_rank_3, commander_rank_4, commander_rank_5, commander_rank_ruler |
| `company_charter_types` | 1 | 5 | company_charter_types.md | investment_charter, monopoly_charter, industry_charter, trade_charter, colonization_charter |
| `company_types` | 22 | 221 | companies.md | company_misr, company_egyptian_rail, company_suez_company, company_fundidora_monterrey, company_el_aguila, company_csfa |
| `console_command_macros` | 1 | 3 | — | debug_macro, debug_money, debug_args |
| `country_creation` | 1 | 394 | — | UBD, AUS, IRE, MTC, GEO, ARM |
| `country_definitions` | 4 | 830 | — | GER, GBR, SCA, RUS, FRA, PRU |
| `country_formation` | 2 | 74 | — | GBR, ENG, UCA, RUS, IRE, FRA |
| `country_ranks` | 1 | 8 | — | great_power, major_power, minor_power, insignificant_power, unrecognized_major_power, unrecognized_regional_power |
| `country_types` | 1 | 5 | — | recognized, colonial, unrecognized, decentralized, company |
| `culture_graphics` | 1 | 10 | — | african, east_asian, south_asian, european, arabic, decentralised_americas |
| `cultures` | 1 | 317 | — | north_german, south_german, ashkenazi, dutch, flemish, wallonian |
| `customizable_localization` | 28 | 480 | — | stepping_down_reason, personality_traits_loc, ordered_personality_traits_loc, custom_insult_loc, wedding_son_daughter, air_ace_adjective_loc |
| `decisions` | 34 | 60 | — | revive_olympic_games_decision, lowlands_land_reclamation, abolish_tangena_ordeal, establish_pact_with_nafusis, russia_offer_circassia_recognition, antarctica_expedition |
| `decrees` | 1 | 11 | — | decree_road_maintenance, decree_violent_suppression, decree_emergency_relief, decree_promote_social_mobility, decree_promote_national_values, decree_encourage_manufacturing_industry |
| `defines` | 6 | 49 | — | NAI, NAudio, NGame, NJominiMap, NCountry, NPolitics |
| `diplomatic_actions` | 48 | 55 | diplomatic_action.md | increase_relations, damage_relations, expel_diplomats, redeem_obligation, violate_sovereignty, trade_states |
| `diplomatic_catalyst_categories` | 1 | 35 | diplomatic_catalyst_categories.md | cc_cooldown_long, cc_cooldown_regular, cc_cooldown_short, cc_historical_relationship, cc_diplomatic_relevance, cc_market_opened |
| `diplomatic_catalysts` | 3 | 77 | diplomatic_catalysts.md | catalyst_historical_relationship, catalyst_became_relevant, catalyst_became_irrelevant, catalyst_gained_land_border, catalyst_lost_land_border, catalyst_relations_level_increased |
| `diplomatic_plays` | 1 | 52 | diplomatic_plays.md | dp_default_treaty_article, dp_open_market, dp_regime_change, dp_ban_slavery, dp_conquer_state, dp_return_state |
| `discrimination_trait_groups` | 3 | 89 | discrimination_trait_groups.md | heritage_group_african, heritage_group_central_asian, heritage_group_east_asian, heritage_group_european, heritage_group_indigenous_american, heritage_group_indigenous_oceanic |
| `discrimination_traits` | 4 | 324 | discrimination_traits.md | heritage_abyssinian, heritage_afghan, heritage_african_diaspora, heritage_african_settler, heritage_afro_arab, heritage_ainu |
| `dna_data` | 584 | 583 | dna_data.md | dna_abdelkader_ibn_muhieddine, dna_abdulkerim_nadir_pasha, dna_abdul_hamid_ii, dna_abd_al_rahmani, dna_abraham_lincoln, dna_abu_bakr_ii |
| `dynamic_company_names` | 1 | 10 | — | dynamic_company_name_country_1, dynamic_company_name_country_2, dynamic_company_name_country_3, dynamic_company_name_country_4, dynamic_company_name_country_5, dynamic_company_name_state_1 |
| `dynamic_country_map_colors` | 1 | 75 | — | kalmar_union, fennoscandia, yellow_prussia, imperial_korea, korea_monarchy_blue, japanese_shogunate |
| `dynamic_country_names` | 1 | 147 | dynamic_country_names.md | DEFAULT, SWE, ACE, AFS, AZB, BAV |
| `dynamic_treaty_names` | 1 | 34 | readme.md | treaty_name_treaty_of_city, treaty_name_city_protocol, treaty_name_city_convention, treaty_name_convention_of_city, treaty_name_september_convention, treaty_name_city_declaration |
| `effect_localization` | 18 | 297 | — | set_subsidized, kill_character, retire_character, add_commander_rank, set_commander_rank, add_character_role |
| `ethnicities` | 21 | 37 | — | ethnicity_template, african, african_diaspora, arab, caucasian_base, caucasian |
| `flag_definitions` | 2 | 433 | — | DEFAULT, ABS, ABU, ACE, AFG, AFS |
| `game_concepts` | 2 | 612 | — | concept_concept, concept_regime_change, concept_invasion, concept_naval_invasion, concept_presence, concept_mission_efficiency |
| `game_rules` | 1 | 15 | game_rules.md | achievements, ai_behavior, ai_aggression, free_construction, formable_nations, releasable_nations |
| `genes` | 8 | 6 | genes.md | color_genes, age_presets, morph_genes, gene_face_dacals, accessory_genes, special_genes |
| `geographic_regions` | 9 | 165 | geographic_regions.md | geographic_region_europe, geographic_region_hungary, geographic_region_german_confederation, geographic_region_megali_greece, geographic_region_historic_byzantium, geographic_region_iceland |
| `goods` | 1 | 53 | goods.md | ammunition, small_arms, artillery, tanks, aeroplanes, manowars |
| `government_types` | 10 | 444 | — | gov_decentralized_sultanate, gov_chiefdom, gov_colonial_administration_gov_in_chief, gov_colonial_administration, gov_colonial_administration_spa, gov_crown_colony_india |
| `harvest_condition_types` | 2 | 22 | harvest_condition_types.md | drought, flood, frost, wildfire, hailstorm, locust_swarm |
| `history` | 0 | 22 | — | AI, BUILDINGS, CHARACTERS, CONSCRIPTION, COUNTRIES, CULTURES |
| `ideologies` | 6 | 172 | — | ideology_paternalistic, ideology_laissez_faire, ideology_interventionist, ideology_individualist, ideology_hierarchic, ideology_oligarchic |
| `institutions` | 1 | 7 | institutions.md | institution_colonial_affairs, institution_social_security, institution_workplace_safety, institution_schools, institution_police, institution_health_system |
| `interest_group_traits` | 8 | 99 | — | ig_trait_patriotic_fervor, ig_trait_veteran_consultation, ig_trait_materiel_waste, ig_trait_elan_vital, ig_trait_newly_created_army, ig_trait_self_strengthening |
| `interest_groups` | 8 | 8 | — | ig_armed_forces, ig_devout, ig_industrialists, ig_intelligentsia, ig_landowners, ig_petty_bourgeoisie |
| `interest_tier_types` | 1 | 6 | interest_tier_types.md | interest_tier_none, interest_tier_observant, interest_tier_engaged, interest_tier_influential, interest_tier_pervasive, interest_tier_hegemonic |
| `journal_entries` | 172 | 419 | journal_entries.md | je_abolish_monarchy, je_acw_countdown, je_acw_war, je_acw_reconstruction, je_acw_reincorporate, je_acw_equality |
| `journal_entry_groups` | 1 | 27 | — | je_group_global_test, je_group_global_international_situations, je_group_iberia, je_group_british_india_global, je_group_spa_economic_regeneration, je_group_tanzimat |
| `labels` | 1 | 7 | — | label_flat, label_elevated, label_forested, label_hazardous, label_developed, label_water |
| `law_groups` | 1 | 26 | — | lawgroup_governance_principles, lawgroup_distribution_of_power, lawgroup_citizenship, lawgroup_caste_hegemony, lawgroup_edo_social_system, lawgroup_church_and_state |
| `laws` | 25 | 138 | readme.md | law_peasant_levies, law_warrior_caste, law_professional_army, law_national_militia, law_mass_conscription, law_hereditary_bureaucrats |
| `legitimacy_levels` | 1 | 5 | — | legitimacy_level_illegitimate, legitimacy_level_unacceptable, legitimacy_level_contested, legitimacy_level_legitimate, legitimacy_level_righteous |
| `liberty_desire_levels` | 1 | 3 | — | ld_level_low, ld_level_moderate, ld_level_high |
| `map_interaction_types` | 1 | 32 | — | build_building, build_special_building, diplomatic_action, diplomatic_play_country, diplomatic_play_state, issue_decree |
| `map_notification_types` | 1 | 23 | — | map_notification_interaction, map_notification_building_fully_employed, map_notification_harvest_condition_finished, map_notification_harvest_condition_started, map_notification_average_sol_increased, map_notification_average_sol_decreased |
| `messages` | 8 | 472 | — | peace_agreement_signed_war_leader, peace_agreement_signed_war_participant, self_capitulated, ally_capitulated, enemy_capitulated, diplomatic_proposal_declined |
| `military_formation_flags` | 1 | 30 | formation_flags.md | army_01, army_02, army_03, army_04, army_05, army_06 |
| `mobilization_option_groups` | 1 | 6 | mobilization_option_groups.md | supplies, supplements, transport, reconnaissance, special_weapons, medic_support |
| `mobilization_options` | 1 | 18 | mobilization_options.md | mobilization_option_basic_supplies, mobilization_option_extra_supplies, mobilization_option_luxurious_supplies, mobilization_option_chocolate, mobilization_option_tobacco, mobilization_option_liquor |
| `modifier_type_definitions` | 15 | 2364 | modifier_types.md | interest_group_ig_armed_forces_pol_str_mult, interest_group_ig_devout_pol_str_mult, interest_group_ig_industrialists_pol_str_mult, interest_group_ig_intelligentsia_pol_str_mult, interest_group_ig_landowners_pol_str_mult, interest_group_ig_petty_bourgeoisie_pol_str_mult |
| `named_colors` | 4 | 1 | — | colors |
| `naval_battle_conditions` | 1 | 7 | naval_battle_conditions.md | naval_condition_strong_winds, naval_condition_calm_waters, naval_condition_fog, naval_condition_cyclone, naval_condition_ice, naval_condition_rough_waters |
| `naval_mission_types` | 1 | 9 | naval_mission_types.md | naval_mission_type_project_power, naval_mission_type_intercept, naval_mission_type_protect_supply, naval_mission_type_raid_supply, naval_mission_type_blockade, naval_mission_type_port_bombardment |
| `objective_subgoal_categories` | 1 | 5 | categories.md | sgcat_tutorial, sgcat_economic_dominance, sgcat_egalitarian_society, sgcat_hegemon, sgcat_great_game |
| `objective_subgoals` | 5 | 86 | subgoals.md | sg_expand_basic_building, sg_fix_budget_deficit, sg_change_production_method, sg_expand_productive_building, sg_fix_unproductive_building, sg_promote_movement |
| `objectives` | 2 | 5 | objectives.md | objective_tutorial, objective_economic_dominance, objective_hegemon, objective_egalitarian_society, objective_great_game |
| `on_actions` | 6 | 263 | _on_actions.md | on_game_started, on_game_started_after_lobby, on_monthly_pulse, on_yearly_pulse, on_monthly_pulse_country, on_yearly_pulse_country |
| `opinion_modifiers` | 1 | 6 | opinion_modifiers.md | opinion_friendly_nation, opinion_unfriendly_nation, opinion_no_decay_test, interest_marker, opinion_rivals_initiator, opinion_rivals_recipient |
| `parties` | 12 | 12 | — | agrarian_party, anarchist_party, communist_party, conservative_party, fascist_party, free_trade_party |
| `political_lobbies` | 1 | 4 | political_lobbies.md | lobby_pro_country, lobby_anti_country, lobby_pro_overlord, lobby_anti_overlord |
| `political_lobby_appeasement` | 1 | 49 | political_lobby_appeasement.md | appeasement_baseline_decay, appeasement_diplomatic_status_quo, appeasement_trade_agreement_formed, appeasement_trade_agreement_broken, appeasement_alliance_formed, appeasement_alliance_broken |
| `political_movement_categories` | 1 | 5 | political_movement_categories.md | movement_category_ideological, movement_category_religious, movement_category_cultural, movement_category_cultural_majority, movement_category_pan_national |
| `political_movement_pop_support` | 1 | 60 | political_movement_pop_support.md | movement_support_high_urbanization, movement_support_low_urbanization, movement_support_slave_state, movement_support_colonial_settlers, movement_support_cultural_fervor, movement_support_national_awakening |
| `political_movements` | 7 | 39 | political_movements.md | movement_anti_slavery, movement_pro_slavery, movement_royalist_absolutist, movement_royalist_constitutional, movement_labor, movement_socialist |
| `pop_needs` | 1 | 15 | — | popneed_simple_clothing, popneed_crude_items, popneed_basic_food, popneed_heating, popneed_household_items, popneed_standard_clothing |
| `pop_types` | 15 | 15 | pop_types.md | academics, aristocrats, bureaucrats, capitalists, clergymen, clerks |
| `power_bloc_coa_pieces` | 1 | 220 | — | pb_center_00.dds, pb_center_01.dds, pb_center_02.dds, pb_center_03.dds, pb_center_04.dds, pb_center_05.dds |
| `power_bloc_identities` | 1 | 6 | power_bloc_identities.md | identity_trade_league, identity_sovereign_empire, identity_ideological_union, identity_military_treaty_organization, identity_religious, identity_cultural |
| `power_bloc_map_textures` | 1 | 18 | — | pb_pattern_01, pb_pattern_02, pb_pattern_03, pb_pattern_04, pb_pattern_05, pb_pattern_06 |
| `power_bloc_names` | 1 | 200 | power_bloc_names.md | great_alliance, grand_coalition, council_of_nations, universal_league, steadfast_union, glorious_union |
| `power_bloc_principle_groups` | 1 | 23 | power_bloc_principle_groups.md | principle_group_shared_canon, principle_group_construction, principle_group_internal_trade, principle_group_market_unification, principle_group_vassalization, principle_group_advanced_research |
| `power_bloc_principles` | 1 | 69 | power_bloc_principles.md | principle_construction_1, principle_construction_2, principle_construction_3, principle_internal_trade_1, principle_internal_trade_2, principle_internal_trade_3 |
| `prestige_goods` | 1 | 72 | prestige_goods.md | prestige_good_krupp_guns, prestige_good_canton_porcelain, prestige_good_ford_automobiles, prestige_good_assam_tea, prestige_good_champagne, prestige_good_bohemian_crystal |
| `production_method_groups` | 15 | 197 | production_method_groups.md | pmg_dummy, pmg_base_building_food_industry, pmg_canning, pmg_distillery, pmg_automation_building_food_industry, pmg_base_building_textile_mill |
| `production_methods` | 15 | 436 | production_methods.md | pm_dummy, pm_bakery, pm_sweeteners, pm_baking_powder, pm_disabled_canning, pm_cannery |
| `proposal_types` | 1 | 10 | — | proposal_diplomatic_action, proposal_diplomatic_action_owe_obligation, proposal_diplomatic_action_call_in_obligation, proposal_break_pact, proposal_break_pact_owe_obligation, proposal_break_pact_call_in_obligation |
| `religions` | 1 | 17 | — | catholic, protestant, orthodox, oriental_orthodox, sunni, shiite |
| `script_values` | 29 | 264 | script_values.md | army_projection_comparison, overlords_overlord_army_projection_comparison, num_primary_cultures, annex_subject_prestige_ratio, annex_subject_liberty_desire_weekly_change, annex_subject_base_liberty_desire_change |
| `scripted_buttons` | 50 | 218 | scripted_buttons.md | je_the_balkan_league_invite_vassals_button, je_the_balkan_league_research_mil_tech_start_button, je_the_balkan_league_research_mil_tech_stop_button, je_the_balkan_league_overwork_arms_industries_start_button, je_the_balkan_league_overwork_arms_industries_stop_button, je_the_balkan_league_muster_button |
| `scripted_effects` | 40 | 720 | — | debug_success, debug_fail, assert, set_all_colony, partition_ottoman_balkans, cuba_annex_effects |
| `scripted_guis` | 4 | 23 | scripted_guis.md | debug_kill_character_sgui, debug_movement_activism_up_sgui, debug_movement_activism_down_sgui, annex_subject_liberty_desire_sgui, je_krakatoa_tsunami_states_sgui, je_acw_reincoprorate_states_sgui |
| `scripted_lists` | 1 | 5 | — | princely_state, character_in_jail, interest_group_in_government, interest_group_in_opposition, scope_barracks |
| `scripted_modifiers` | 0 | 0 | scripted_modifiers.md |  |
| `scripted_progress_bars` | 14 | 27 | scripted_progress_bars.md | austrian_neo_absolutism_constitutional_pressure_progress_bar, je_ryukyu_rivalry_score_bar, je_ryukyu_rivalry_progress_bar, great_game_core_progress_bar, bavarocracy_progress_bar, grunderzeit_progress_bar |
| `scripted_rules` | 1 | 18 | — | violate_sovereignty_war_check_rule, has_voting_franchise, can_form_power_bloc, can_lead_power_bloc, is_weak_power_bloc, can_start_diplomatic_plays_against |
| `scripted_triggers` | 25 | 737 | — | lenient_ai_behavior_trigger, harsh_ai_behavior_trigger, ai_strongly_desires_target_state, ai_desires_target_state, has_enactment_je_or_law_commitment, ai_has_reasons_to_not_oppose_law |
| `ship_groups` | 1 | 4 | ship_groups.md | ship_group_capital_ships, ship_group_cruisers, ship_group_torpedo_craft, ship_group_supply_ships |
| `ship_modification_slots` | 1 | 7 | ship_modification_slots.md | ship_mod_slot_armor, ship_mod_slot_guns, ship_mod_slot_propulsion, ship_mod_slot_range, ship_mod_slot_utility_1, ship_mod_slot_utility_2 |
| `ship_modifications` | 2 | 259 | ship_modifications.md | ship_mod_frigate_armor_light, ship_mod_frigate_armor_medium, ship_mod_frigate_armor_high, ship_mod_frigate_guns_light, ship_mod_frigate_guns_medium, ship_mod_frigate_guns_high |
| `ship_name_definitions` | 14 | 86 | ship_name_definitions.md | ship_names_historical_brazilian_capital_ships, ship_names_historical_brazilian_cruisers, ship_names_historical_chinese_capital_ships, ship_names_historical_chinese_cruisers, ship_names_historical_chinese_destroyers, ship_names_historical_french_capital_ships |
| `ship_types` | 1 | 21 | ship_types.md | ship_type_ship_of_the_line, ship_type_monitor, ship_type_early_ironclad, ship_type_coastal_defense_ship, ship_type_modern_ironclad, ship_type_pre_dreadnought |
| `ship_veterancy_levels` | 1 | 5 | ship_veterancy_levels.md | ship_veterancy_none, ship_veterancy_1, ship_veterancy_2, ship_veterancy_3, ship_veterancy_4 |
| `social_classes` | 3 | 14 | readme.md | upper_class, middle_class, lower_class, brahmins, kshatriyas, vaishyas |
| `social_hierarchies` | 1 | 3 | readme.md | default_social_hierarchy, british_indian_caste_system, edo_system |
| `state_traits` | 13 | 239 | — | state_trait_malaria, state_trait_severe_malaria, state_trait_natural_harbors, state_trait_good_soils, state_trait_north_sea_fishing, state_trait_arctic_whaling |
| `static_modifiers` | 68 | 6121 | — | base_values, prestige_ranking, top_prestige_ranking, character_base_values, character_noble, character_historical |
| `strait_definitions` | 1 | 12 | strait_definitions.md | canal_panama, canal_suez, canal_kiel, strait_gibraltar, strait_bosporus, strait_bab_el_mandeb |
| `strategic_regions` | 7 | 142 | strategic_regions.md | region_nile_basin, region_north_africa, region_west_africa, region_equatorial_africa, region_southern_africa, region_east_africa |
| `subject_types` | 1 | 9 | — | subject_type_protectorate, subject_type_puppet, subject_type_tributary, subject_type_vassal, subject_type_dominion, subject_type_colony |
| `technology` | 0 | 184 | — | era_1, era_2, era_3, era_4, era_5, sericulture |
| `terrain` | 1 | 25 | — | plains, ocean, lakes, river, forest, hills |
| `terrain_manipulators` | 1 | 14 | — | farmland_rye, pasture, plantation, farmland_rice, farmland_millet, farmland_wheat |
| `themes` | 1 | 60 | themes.md | gui_skin_base, main_menu_image_base, papermap_base, table_base, papermap_object_divider, papermap_object_compass |
| `travel_network` | 1 | 2 | — | nodes, connections |
| `treaty_articles` | 34 | 34 | treaty_articles.md | alliance, defensive_pact, guarantee_independence, support_independence, take_on_debt, money_transfer |
| `trigger_localization` | 3 | 1681 | trigger_localization.md | any_scope_ally, any_scope_ally_all, any_scope_ally_count, any_scope_ally_percent, any_subject_or_below, any_subject_or_below_all |
| `tutorial_lesson_chains` | 1 | 3 | tutorial_lesson_chains.md | lesson_chain_intro, lesson_chain_journal_guides, lesson_chain_pops |
| `tutorial_lessons` | 32 | 66 | tutorial_lesson.md | lesson_interest_group, lesson_pops, lesson_budget_balance_how, lesson_budget_balance_why, lesson_budget_balance_complete, lesson_budget_balance_fail |
| `war_goal_types` | 39 | 39 | war_goal_types.md | annex_country, ban_slavery, colonization_rights, conquer_state, contain_threat, enforce_treaty_article |
