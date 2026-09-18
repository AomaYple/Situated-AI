# 13 · common 全量键名索引

> 对 `game\common\` 下**全部 136 个子目录** + 根下 **1 个散装 `.txt`**
> 做机械提取，共 **27,628 个顶层条目**。
> 本文回答「**什么东西定义在哪个目录**」。

> 数据版本：Victoria 3 `release/1.14.3`
> （`caligula_rev = bf52e8efe8f4…`）。
> 本文**每次运行 `v3 index` 都会整体重新生成**，因此其中的数字始终对应当前安装，
> 不存在「文档数字过期」的问题 —— 这也是它与其他主题文档的区别。

## 提取口径

本索引由 `v3 index` 生成（实现见 `tools/pdx/cli.py`），口径如下：

```text
顶层判定   花括号深度 == 0，**与缩进无关**
编码       utf-8-sig，自动剥离 BOM
注释       引号感知地剥离 # 到行尾（在花括号计数之前）
键名字符集  非空白、非花括号、非等号、非引号（因此支持连字符）
@变量      不计入条目
```

**逐目录统计 + 根下散装文件**：本索引按 `common\` 的 136 个子目录逐个提取，
合计 **3,025 个文件**；`common\` 根下另有 **1 个散装 `.txt`**
（achievement_groups.txt）不在任何子目录里，列在本文末尾。
所以「本索引 3,025 个文件」与「`common` 全树 3,026 个 `.txt`」
差的就是这 1 个 —— 两者都对，只是口径不同，**不要为了对齐而互相改**。

## 勘误记录

### 勘误 1：早期版本漏计含连字符的键

早期版本用**枚举字符类**匹配键名，静默漏掉了含连字符 `-` 的键。
全库共 **32 个**，分布在 4 个目录：

| 目录 | 含连字符键数 | 修正前 | 修正后 |
|---|---:|---:|---:|
| `character_templates` | 27 | 1,983 | **2,011** |
| `production_methods` | 3 | 433 | **436** |
| `technology` | 1 | 183 | **184** |
| `power_bloc_names` | 1 | 199 | **200** |

### 勘误 2：早期版本漏计文件首键（BOM）与缩进的顶层键

`common` 下 3,026 个 `.txt` 中 **3,002 个带 UTF-8 BOM**，且部分文件的顶层键**带前导空格**。
用「行首无缩进」判定顶层的做法会漏掉它们。实测 `static_modifiers` 因此少算 7 个：

| 目录 | 修正前 | 修正后 |
|---|---:|---:|
| `static_modifiers` | 6,121 | **6,128** |

### 勘误 3：`.txt` 文件数曾用非递归统计

5 个含子目录的目录受影响：`history` 0→1152、`coat_of_arms` 0→23、
`technology` 0→4、`defines` 6→9、`terrain_manipulators` 1→2。

> **三条勘误的共同教训**：解析 PDX 数据不要假设字符集、不要假设文件平铺、
> 不要用缩进判断结构。全部改用花括号深度 + `utf-8-sig` + 取反字符组。

## 全部 136 个目录

| 目录 | .txt 文件 | 顶层条目 | 官方文档 | 条目示例（前 6 个） |
|---|---:|---:|---|---|
| `acceptance_statuses` | 1 | 5 | readme.md | cultural_erasure, full_acceptance, open_prejudice, second_rate_citizen, violent_hostility |
| `achievements` | 9 | 141 | — | achievement_a_las_barricadas, achievement_agitate_elsewhere, achievement_all_quiet_on_the_western_front, achievement_amish_paradise, achievement_authoritarian, achievement_azadi |
| `ai_strategic_region_stance_types` | 1 | 4 | ai_strategic_region_stance_types.md | stance_colonize_region, stance_conquer_region, stance_none, stance_protect_region |
| `ai_strategies` | 5 | 35 | — | ai_strategy_agricultural_expansion, ai_strategy_anti_imperialism, ai_strategy_armed_isolationism, ai_strategy_colonial_expansion, ai_strategy_colonial_extraction, ai_strategy_conservative_agenda |
| `alert_groups` | 1 | 24 | — | blockaded_hubs, blockaded_states, bombarded_states, can_decrease_subject_autonomy, can_take_decisions, companies_losing_prosperity |
| `alert_types` | 1 | 68 | — | above_company_limit, active_peace_deal_alert, article_contravened, blockaded_hub_alert, blockaded_state_alert, can_abdicate_alert |
| `amendments` | 6 | 67 | amendments.md | amendment_200_franc_suffrage, amendment_agricultural_communes, amendment_american_fugitive_slaves_act, amendment_american_second_amendment, amendment_chamber_of_gentleman_deputies, amendment_chamber_of_procurators |
| `battle_conditions` | 1 | 21 | battle_condition.md | battle_condition_aggressive_maneuver, battle_condition_blunder, battle_condition_broken_supply_line, battle_condition_camouflaged, battle_condition_careful_maneuver, battle_condition_charted_terrain |
| `building_groups` | 1 | 69 | — | bg_agriculture, bg_army, bg_army_logistics_center, bg_arts, bg_banana_plantations, bg_bureaucracy |
| `buildings` | 14 | 115 | buildings.md | building_angkor_wat, building_argebam, building_arms_industry, building_army_logistics_center, building_art_academy, building_artillery_foundry |
| `buy_packages` | 1 | 99 | — | wealth_1, wealth_10, wealth_11, wealth_12, wealth_13, wealth_14 |
| `character_interactions` | 4 | 21 | — | abdicate_monarch, arrange_accident, exile_character, grant_command_to_agitator, grant_command_to_ruler, grant_leadership_to_agitator |
| `character_roles` | 3 | 10 | character_roles.md | character_role_admiral, character_role_agitator, character_role_emperor_of_japan, character_role_executive, character_role_general, character_role_heir |
| `character_templates` | 210 | 2011 | — | ABU_khalifa_al_nahyan, ABU_saeed_al_nahyan, ABU_said_al_qasim, ACE_alauddin_muhammad_bugis, ACE_alauddin_sulaiman_bugis, AGC_ahmadi_bari |
| `character_traits` | 5 | 121 | character_traits.md | aesthete, alcoholic, ambitious, arrogant, bandit, basic_artillery_commander |
| `coat_of_arms` | 23 | 1701 | — | ABS, ABU, ABU_subject, ABU_subject_FRA, ABU_subject_GBR, ACE |
| `cohesion_levels` | 1 | 5 | — | cohesion_level_high, cohesion_level_low, cohesion_level_moderate, cohesion_level_very_high, cohesion_level_very_low |
| `combat_unit_experience_levels` | 1 | 5 | — | no_veterancy, veterancy1, veterancy2, veterancy3, veterancy4 |
| `combat_unit_groups` | 1 | 4 | — | combat_unit_group_artillery, combat_unit_group_cavalry, combat_unit_group_infantry, combat_unit_group_marines |
| `combat_unit_types` | 1 | 19 | — | combat_unit_type_cannon_artillery, combat_unit_type_cuirassiers, combat_unit_type_dragoons, combat_unit_type_heavy_tank, combat_unit_type_high_tier_marines, combat_unit_type_hussars |
| `commander_orders` | 2 | 12 | orders.md | advance, advance_cautious, advance_cavalry_assualt, advance_heavy_barrage, advance_pillager, advance_reckless |
| `commander_ranks` | 1 | 6 | — | commander_rank_1, commander_rank_2, commander_rank_3, commander_rank_4, commander_rank_5, commander_rank_ruler |
| `company_charter_types` | 1 | 5 | company_charter_types.md | colonization_charter, industry_charter, investment_charter, monopoly_charter, trade_charter |
| `company_types` | 22 | 221 | companies.md | company_a_markwald_and_company, company_aker_mek, company_allatini_mills, company_altos_hornos_de_vizcaya, company_anglo_persian_oil, company_anglo_sicilian_sulphur_company |
| `console_command_macros` | 1 | 3 | — | debug_args, debug_macro, debug_money |
| `country_creation` | 1 | 394 | — | ABU, ACE, AFG, AGJ, AHU, AIN |
| `country_definitions` | 4 | 830 | — | ABK, ABS, ABU, ACE, ACH, ADG |
| `country_formation` | 2 | 74 | — | AFG, ALD, AOT, ARA, AST, ATL |
| `country_ranks` | 1 | 8 | — | decentralized_power, great_power, insignificant_power, major_power, minor_power, unrecognized_major_power |
| `country_types` | 1 | 5 | — | colonial, company, decentralized, recognized, unrecognized |
| `culture_graphics` | 1 | 10 | — | african, arabic, balkan, brazilian, decentralised_americas, east_asian |
| `cultures` | 1 | 317 | — | aborigine, afar, afro_american, afro_antillean, afro_brazilian, afro_caribbean |
| `customizable_localization` | 28 | 480 | — | BR_Dede, BR_DoDa, BR_DosDas, BR_EmEm, BR_NoNa, BR_NosNas |
| `decisions` | 34 | 60 | — | KOR_declare_korean_empire, abolish_tangena_ordeal, antarctica_expedition, aus_integrate_crown_lands_decision, aus_organise_trialism, aus_revisit_federation_proposal |
| `decrees` | 1 | 11 | — | decree_emergency_relief, decree_encourage_agricultural_industry, decree_encourage_manufacturing_industry, decree_encourage_resource_industry, decree_enlistment_efforts, decree_establish_missions |
| `defines` | 9 | 50 | — | NAI, NAudio, NBattle, NCamera, NCharacters, NCities |
| `diplomatic_actions` | 48 | 55 | diplomatic_action.md | add_power_bloc_culture, chartered_company, colonization_rights, colony, crown_land, da_appoint_colonial_governor |
| `diplomatic_catalyst_categories` | 1 | 35 | diplomatic_catalyst_categories.md | cc_ai_strategy_change, cc_alliance_broken, cc_alliance_formed, cc_autonomy_change, cc_bankruptcy, cc_cooldown_long |
| `diplomatic_catalysts` | 3 | 77 | diplomatic_catalysts.md | catalyst_alliance_broken, catalyst_alliance_formed, catalyst_alliance_with_rival, catalyst_allies_in_play, catalyst_autonomy_change_imposed, catalyst_autonomy_increase_denied |
| `diplomatic_plays` | 1 | 53 | diplomatic_plays.md | dp_annex_subject, dp_annex_war, dp_balkan_war, dp_ban_slavery, dp_conquer_state, dp_contain_threat |
| `discrimination_trait_groups` | 3 | 89 | discrimination_trait_groups.md | heritage_group_abrahamic, heritage_group_african, heritage_group_central_asian, heritage_group_east_asian, heritage_group_eastern, heritage_group_european |
| `discrimination_traits` | 4 | 324 | discrimination_traits.md | heritage_abyssinian, heritage_afghan, heritage_african_diaspora, heritage_african_settler, heritage_afro_arab, heritage_ainu |
| `dna_data` | 584 | 583 | dna_data.md | dna_abd_al_rahmani, dna_abdelkader_ibn_muhieddine, dna_abdul_hamid_ii, dna_abdulkerim_nadir_pasha, dna_abraham_lincoln, dna_abu_bakr_ii |
| `dynamic_company_names` | 1 | 10 | — | dynamic_company_name_country_1, dynamic_company_name_country_2, dynamic_company_name_country_3, dynamic_company_name_country_4, dynamic_company_name_country_5, dynamic_company_name_state_1 |
| `dynamic_country_map_colors` | 1 | 75 | — | algeria_ait_abbas, algeria_constantine, algeria_mascara, bengal_free_state, brazil_integralist, brazil_republican |
| `dynamic_country_names` | 1 | 147 | dynamic_country_names.md | ACE, AFG, AFS, AHU, ALD, ALK |
| `dynamic_treaty_names` | 1 | 34 | readme.md | treaty_name_agreement_between_country_and_country, treaty_name_city_agreement, treaty_name_city_convention, treaty_name_city_declaration, treaty_name_city_protocol, treaty_name_concordat_between_the_holy_see_and_country_first |
| `effect_localization` | 18 | 297 | — | abandon_revolution, activate_building, activate_law, activate_law_with_investment_level, activate_production_method, add_acceptance |
| `ethnicities` | 21 | 36 | — | Default_temp, african, african_diaspora, arab, asian, asian_test |
| `flag_definitions` | 2 | 433 | — | ABS, ABU, ACE, AFG, AFS, AIT |
| `game_concepts` | 2 | 612 | — | concept_acceptance, concept_acceptance_status, concept_accepted_culture, concept_accepted_religion, concept_accuracy, concept_activism |
| `game_rules` | 1 | 15 | game_rules.md | achievements, ai_aggression, ai_behavior, custom_rng_seed, dynamic_naming, fantastical_content |
| `genes` | 8 | 5 | genes.md | accessory_genes, age_presets, color_genes, morph_genes, special_genes |
| `geographic_regions` | 9 | 165 | geographic_regions.md | geographic_region_afghanistan, geographic_region_africa, geographic_region_allahabad_bombay_line, geographic_region_alpide_belt, geographic_region_amazon, geographic_region_americas |
| `goods` | 1 | 53 | goods.md | aeroplanes, ammunition, artillery, automobiles, clippers, clothes |
| `government_types` | 10 | 444 | — | gov_absolute_county, gov_absolute_duchy, gov_absolute_empire, gov_absolute_grand_duchy, gov_absolute_grand_principality, gov_absolute_kingdom |
| `harvest_condition_types` | 2 | 22 | harvest_condition_types.md | calm_waters, cyclone, disease_outbreak, drought, earthquake, extreme_winds |
| `history` | 1152 | 22 | — | AI, BUILDINGS, CHARACTERS, CONSCRIPTION, COUNTRIES, CULTURES |
| `ideologies` | 6 | 172 | — | ideology_abolitionist, ideology_absolutist_movement, ideology_agrarian, ideology_agrarian_jeffersonian, ideology_anarchist, ideology_anarchist_movement |
| `institutions` | 1 | 7 | institutions.md | institution_colonial_affairs, institution_health_system, institution_home_affairs, institution_police, institution_schools, institution_social_security |
| `interest_group_traits` | 8 | 99 | — | ig_shipping_magnates, ig_trait_asceticism, ig_trait_avant_garde, ig_trait_bachareis, ig_trait_bad_boyars, ig_trait_bah_humbug |
| `interest_groups` | 8 | 8 | — | ig_armed_forces, ig_devout, ig_industrialists, ig_intelligentsia, ig_landowners, ig_petty_bourgeoisie |
| `interest_tier_types` | 1 | 6 | interest_tier_types.md | interest_tier_engaged, interest_tier_hegemonic, interest_tier_influential, interest_tier_none, interest_tier_observant, interest_tier_pervasive |
| `journal_entries` | 172 | 419 | journal_entries.md | central_america_falls_apart, je_5_year_plan, je_aberdeen_act, je_abolish_monarchy, je_achieve_sovereignty, je_acquire_korean_protectorate |
| `journal_entry_groups` | 1 | 27 | — | je_group_brazil, je_group_brazil_pedro, je_group_british_india, je_group_british_india_global, je_group_crises, je_group_expeditions |
| `labels` | 1 | 7 | — | label_developed, label_elevated, label_flat, label_forested, label_hazardous, label_travel_harsh_environment |
| `law_groups` | 1 | 26 | — | lawgroup_army_model, lawgroup_bureaucracy, lawgroup_caste_hegemony, lawgroup_childrens_rights, lawgroup_church_and_state, lawgroup_citizenship |
| `laws` | 25 | 138 | readme.md | law_affirmative_action, law_agrarianism, law_anarchy, law_anti_strike_laws, law_appointed_bureaucrats, law_autocracy |
| `legitimacy_levels` | 1 | 5 | — | legitimacy_level_contested, legitimacy_level_illegitimate, legitimacy_level_legitimate, legitimacy_level_righteous, legitimacy_level_unacceptable |
| `liberty_desire_levels` | 1 | 3 | — | ld_level_high, ld_level_low, ld_level_moderate |
| `map_interaction_types` | 1 | 32 | — | activate_conscription_center, build_building, build_special_building, create_formation, deploy_military_formation_to_front, deploy_military_formation_to_sea_node |
| `map_notification_types` | 1 | 23 | — | map_notification_average_sol_decreased, map_notification_average_sol_increased, map_notification_building_expanded, map_notification_building_foreign_investment, map_notification_building_foreign_investment_made, map_notification_building_foreign_investment_made_privatization |
| `messages` | 8 | 473 | — | aberdeen_act_notification, acquired_technology_notification, acre_dispute_failure, acre_dispute_success, afghanistan_assistance_request_accepted, afghanistan_assistance_request_rejected |
| `military_formation_flags` | 1 | 30 | formation_flags.md | army_01, army_02, army_03, army_04, army_05, army_06 |
| `mobilization_option_groups` | 1 | 6 | mobilization_option_groups.md | medic_support, reconnaissance, special_weapons, supplements, supplies, transport |
| `mobilization_options` | 1 | 18 | mobilization_options.md | mobilization_option_aerial_recon, mobilization_option_balloon_recon, mobilization_option_basic_supplies, mobilization_option_chemical_weapons, mobilization_option_chocolate, mobilization_option_extra_supplies |
| `modifier_type_definitions` | 15 | 2364 | modifier_types.md | battle_casualties_mult, battle_combat_width_mult, battle_defense_owned_province_mult, battle_naval_condition_calm_waters_chance_mult, battle_naval_condition_cyclone_chance_mult, battle_naval_condition_fog_chance_mult |
| `named_colors` | 4 | 1 | — | colors |
| `naval_battle_conditions` | 1 | 7 | naval_battle_conditions.md | naval_condition_calm_waters, naval_condition_cyclone, naval_condition_fog, naval_condition_ice, naval_condition_rough_waters, naval_condition_strong_winds |
| `naval_mission_types` | 1 | 9 | naval_mission_types.md | naval_mission_type_blockade, naval_mission_type_hunt_pirates, naval_mission_type_intercept, naval_mission_type_piracy, naval_mission_type_port_bombardment, naval_mission_type_privateer |
| `objective_subgoal_categories` | 1 | 5 | categories.md | sgcat_economic_dominance, sgcat_egalitarian_society, sgcat_great_game, sgcat_hegemon, sgcat_tutorial |
| `objective_subgoals` | 5 | 86 | subgoals.md | sg_achieve_sovereignty, sg_acquire_chinese_concessions, sg_acquire_korean_protectorate, sg_african_colonies, sg_capacity_deficit, sg_change_production_method |
| `objectives` | 2 | 5 | objectives.md | objective_economic_dominance, objective_egalitarian_society, objective_great_game, objective_hegemon, objective_tutorial |
| `on_actions` | 6 | 264 | _on_actions.md | austrian_monarchy_yearly_events, bp1_misc_yearly_events, british_dictate_yearly_events, carlist_war_battle_score, colonial_claims_check, coup_aftermath_half_yearly_events |
| `opinion_modifiers` | 1 | 6 | opinion_modifiers.md | interest_marker, opinion_friendly_nation, opinion_no_decay_test, opinion_rivals_initiator, opinion_rivals_recipient, opinion_unfriendly_nation |
| `parties` | 12 | 12 | — | agrarian_party, anarchist_party, communist_party, conservative_party, fascist_party, free_trade_party |
| `political_lobbies` | 1 | 4 | political_lobbies.md | lobby_anti_country, lobby_anti_overlord, lobby_pro_country, lobby_pro_overlord |
| `political_lobby_appeasement` | 1 | 49 | political_lobby_appeasement.md | appeasement_alliance_broken, appeasement_alliance_formed, appeasement_autonomy_decreased, appeasement_autonomy_increased, appeasement_baseline_decay, appeasement_became_subject |
| `political_movement_categories` | 1 | 5 | political_movement_categories.md | movement_category_cultural, movement_category_cultural_majority, movement_category_ideological, movement_category_pan_national, movement_category_religious |
| `political_movement_pop_support` | 1 | 60 | political_movement_pop_support.md | movement_support_academics, movement_support_aristocrats, movement_support_aristocrats_polish, movement_support_backwardsness, movement_support_below_expected_sol, movement_support_bureaucrats |
| `political_movements` | 7 | 39 | political_movements.md | movement_anarchist, movement_anti_slavery, movement_bonapartist, movement_carlist, movement_communist, movement_corporatist |
| `pop_needs` | 1 | 15 | — | popneed_basic_food, popneed_communication, popneed_crude_items, popneed_free_movement, popneed_heating, popneed_household_items |
| `pop_types` | 15 | 15 | pop_types.md | academics, aristocrats, bureaucrats, capitalists, clergymen, clerks |
| `power_bloc_coa_pieces` | 1 | 220 | — | pb_addorsed_scimitars.dds, pb_ahom_winged_lion.dds, pb_alaska_big_dipper.dds, pb_angkor_vat.dds, pb_armillary_sphere.dds, pb_arrow_cross.dds |
| `power_bloc_identities` | 1 | 6 | power_bloc_identities.md | identity_cultural, identity_ideological_union, identity_military_treaty_organization, identity_religious, identity_sovereign_empire, identity_trade_league |
| `power_bloc_map_textures` | 1 | 18 | — | pb_pattern_01, pb_pattern_02, pb_pattern_03, pb_pattern_04, pb_pattern_05, pb_pattern_06 |
| `power_bloc_names` | 1 | 200 | power_bloc_names.md | adelaide_alliance, adriatic_council, algerian_league, alliance_of_colombo, alliance_of_the_hague, alliance_of_triumph |
| `power_bloc_principle_groups` | 1 | 23 | power_bloc_principle_groups.md | principle_group_advanced_research, principle_group_aggressive_coordination, principle_group_colonial_offices, principle_group_companies, principle_group_construction, principle_group_creative_legislature |
| `power_bloc_principles` | 1 | 69 | power_bloc_principles.md | principle_advanced_research_1, principle_advanced_research_2, principle_advanced_research_3, principle_aggressive_coordination_1, principle_aggressive_coordination_2, principle_aggressive_coordination_3 |
| `prestige_goods` | 1 | 72 | prestige_goods.md | prestige_good_acorn_fed_pork, prestige_good_armstrong_ships, prestige_good_assam_tea, prestige_good_bacardi_rum, prestige_good_baku_oil, prestige_good_basma_tobacco |
| `production_method_groups` | 15 | 197 | production_method_groups.md | pmg_additional_ownership_building_manor_house, pmg_aeroplanes, pmg_airship_mooring_post, pmg_amenities, pmg_army_logistics_center, pmg_automation_building_arms_industry |
| `production_methods` | 15 | 436 | production_methods.md | automatic_irrigation_building_banana_plantation, automatic_irrigation_building_cotton_plantation, automatic_irrigation_building_dye_plantation, automatic_irrigation_building_opium_plantation, automatic_irrigation_building_rubber_plantation, automatic_irrigation_building_silk_plantation |
| `proposal_types` | 1 | 10 | — | proposal_break_pact, proposal_break_pact_call_in_obligation, proposal_break_pact_owe_obligation, proposal_diplomatic_action, proposal_diplomatic_action_call_in_obligation, proposal_diplomatic_action_owe_obligation |
| `religions` | 1 | 17 | — | animist, atheist, catholic, confucian, gelugpa, hindu |
| `script_values` | 30 | 479 | script_values.md | absolute_state_daimyo_loyalty, acceptance_status_1, acceptance_status_2, acceptance_status_3, acceptance_status_4, acceptance_status_5 |
| `scripted_buttons` | 50 | 218 | scripted_buttons.md | CHI_deport_missionaries_button, acre_dispute_button, amazon_border_treaty_button_1, amazon_border_treaty_button_2, army_git_good_button, austrian_neo_absolutism_abolish_crown_land_autonomy_button |
| `scripted_effects` | 40 | 721 | — | JAP_character_generate_choshu_daimyo, JAP_character_generate_hikone_daimyo, JAP_character_generate_kaga_daimyo, JAP_character_generate_kishu_daimyo, JAP_character_generate_matsumae_daimyo, JAP_character_generate_mito_daimyo |
| `scripted_guis` | 4 | 23 | scripted_guis.md | annex_subject_liberty_desire_sgui, debug_kill_character_sgui, debug_movement_activism_down_sgui, debug_movement_activism_up_sgui, je_acw_reincoprorate_states_sgui, je_colonize_korea_states_sgui |
| `scripted_lists` | 1 | 5 | — | character_in_jail, interest_group_in_government, interest_group_in_opposition, princely_state, scope_barracks |
| `scripted_modifiers` | 0 | 0 | scripted_modifiers.md | — |
| `scripted_progress_bars` | 14 | 42 | scripted_progress_bars.md | austrian_neo_absolutism_constitutional_pressure_progress_bar, balkan_league_timeout_bar, bavarocracy_progress_bar, bulgaria_military_progress_bar, communism_1_progress_bar, control_eastern_crisis_bar |
| `scripted_rules` | 1 | 18 | — | can_form_power_bloc, can_impose_law_default, can_join_side_in_diplomatic_play, can_lead_power_bloc, can_sign_treaty_with, can_start_diplomatic_plays_against |
| `scripted_triggers` | 25 | 749 | — | academics_clothes_pop_trigger, accepted_cultural_minority_check_character_scope, african_clothes_pop_trigger, african_clothes_trigger, african_diaspora_clothes_trigger, african_diaspora_pop_clothes_trigger |
| `ship_groups` | 1 | 4 | ship_groups.md | ship_group_capital_ships, ship_group_cruisers, ship_group_supply_ships, ship_group_torpedo_craft |
| `ship_modification_slots` | 1 | 7 | ship_modification_slots.md | ship_mod_slot_armor, ship_mod_slot_guns, ship_mod_slot_propulsion, ship_mod_slot_range, ship_mod_slot_utility_1, ship_mod_slot_utility_2 |
| `ship_modifications` | 2 | 259 | ship_modifications.md | ship_mod_aircraft_carrier_armor_high, ship_mod_aircraft_carrier_armor_light, ship_mod_aircraft_carrier_armor_medium, ship_mod_aircraft_carrier_guns_high, ship_mod_aircraft_carrier_guns_light, ship_mod_aircraft_carrier_guns_medium |
| `ship_name_definitions` | 14 | 86 | ship_name_definitions.md | ship_names_historical_austrian_capital_ships, ship_names_historical_austrian_cruisers, ship_names_historical_austrian_destroyers, ship_names_historical_austrian_sail_frigates, ship_names_historical_austrian_submarines, ship_names_historical_blockade_runners |
| `ship_types` | 1 | 21 | ship_types.md | ship_type_aircraft_carrier, ship_type_armored_cruiser, ship_type_coastal_defense_ship, ship_type_destroyer, ship_type_dreadnought, ship_type_early_ironclad |
| `ship_veterancy_levels` | 1 | 5 | ship_veterancy_levels.md | ship_veterancy_1, ship_veterancy_2, ship_veterancy_3, ship_veterancy_4, ship_veterancy_none |
| `social_classes` | 3 | 14 | readme.md | brahmins, dalit, kshatriyas, lower_class, middle_class, shudras |
| `social_hierarchies` | 1 | 3 | readme.md | british_indian_caste_system, default_social_hierarchy, edo_system |
| `state_traits` | 13 | 239 | — | state_trait_alborz_mountains, state_trait_alps_mountains, state_trait_amazon_rainforest, state_trait_amazon_rainforest_level_1, state_trait_amazon_rainforest_level_2, state_trait_amazon_river |
| `static_modifiers` | 68 | 6128 | — | 1848_institution_speed, 1848_popular_radical, 1848_reactionary_enactment, USA_accepted_ross_petition, USA_paying_for_provisions, USA_paying_removal_costs |
| `strait_definitions` | 1 | 12 | strait_definitions.md | canal_kiel, canal_panama, canal_suez, strait_bab_el_mandeb, strait_bosporus, strait_gibraltar |
| `strategic_regions` | 7 | 142 | strategic_regions.md | region_adriatic_sea, region_aegean_sea, region_amazon_delta, region_andes, region_arabia, region_arabian_sea |
| `subject_types` | 1 | 9 | — | subject_type_chartered_company, subject_type_colony, subject_type_crown_land, subject_type_dominion, subject_type_personal_union, subject_type_protectorate |
| `technology` | 4 | 184 | — | academia, admiralty, analytical_philosophy, anarchism, aniline, antibiotics |
| `terrain` | 1 | 25 | — | cleared_land, desert, docks, farmland_maize, farmland_millet, farmland_rice |
| `terrain_manipulators` | 2 | 14 | — | farmland_maize, farmland_millet, farmland_rice, farmland_rye, farmland_wheat, forestry |
| `themes` | 1 | 60 | themes.md | gui_skin_ap1, gui_skin_base, gui_skin_ep2, gui_skin_ip2, gui_skin_ip3, gui_skin_ip4 |
| `travel_network` | 1 | 2 | — | connections, nodes |
| `treaty_articles` | 34 | 34 | treaty_articles.md | abandon_piracy, acquire_monopoly_for_company, alliance, amend_succession, defensive_pact, foreign_investment_rights |
| `trigger_localization` | 4 | 1683 | trigger_localization.md | active_lens, active_lens_option, add_to_temporary_list, age, aggressive_diplomatic_plays_permitted, ai_army_comparison_equal |
| `tutorial_lesson_chains` | 1 | 3 | tutorial_lesson_chains.md | lesson_chain_intro, lesson_chain_journal_guides, lesson_chain_pops |
| `tutorial_lessons` | 32 | 66 | tutorial_lesson.md | colonization_law_passed_complete, economic_dominance, economic_dominance_complete, egalitarian_society, egalitarian_society_complete, expand_goods_production_complete |
| `war_goal_types` | 39 | 39 | war_goal_types.md | annex_country, ban_slavery, break_enforced_treaties, colonization_rights, conquer_state, contain_threat |

## `common\` 根下的散装文件（1 个）

这些 `.txt` 不在任何子目录里，上面的逐目录表覆盖不到，单独列出：

| 文件 | 顶层条目 | 顶层键 |
|---|---:|---|
| `achievement_groups.txt` | 4 | `group`, `group`, `group`, `group` |

> 键名重复是**如实反映**，不是 bug：PDX 允许同级重复键，而 `parse_file(...).top_keys` 如实返回全部出现。
