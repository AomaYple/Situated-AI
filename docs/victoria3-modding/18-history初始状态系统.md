# 18 · history 初始状态系统全解

> `common\history\` 定义**1836 年开局时世界的样子**：谁拥有哪些州、有哪些人物、
> 人口构成、建筑、政府、外交关系、军队编制、已生效的条约……
> 这是**所有 mod 都要碰的核心系统**，也是 `11-历史初始状态与AI策略分配.md` 的完整展开。
> 全部内容 **【实测】**。

## 1. 全貌

**【实测】** `common\history\` 下 **22 个子目录 / 1,153 个文件**，根目录无松散文件。
每个子目录的文件都用**一个大写包装块**包裹 —— 这是识别它属于哪个系统的标志：

| 子目录 | 文件数 | **顶层包装块** | 主要效果 |
|---|---|---|---|
| `countries` | 444 | `COUNTRIES` | `add_amendment`、`set_ruling_interest_groups`、`set_institution_investment_level`、`set_export_tariff_level`、`set_import_tariff_level`、`add_journal_entry`、`add_modifier`、`set_global_variable`、`set_variable`、`create_diplomatic_pact` |
| `population` | 373 | `POPULATION` | `effect_starting_pop_wealth_*`、`effect_starting_pop_literacy_*`（与 `countries` 同一套预置效果）【实测】 |
| `characters` | 262 | `CHARACTERS` | `create_character`、`set_career_length`、`add_career_length`、`add_journal_entry`、`add_modifier`、`set_variable` |
| `pops` | 17 | `POPS` | `create_pop` |
| `buildings` | 16 | `BUILDINGS` | `create_building`、`add_ownership` |
| `military_formations` | 10 | `MILITARY_FORMATIONS` | `create_military_formation`、`create_ship`、`create_character`、`set_variable` |
| `diplomacy` | 6 | `DIPLOMACY` | `create_diplomatic_pact`、`create_bidirectional_truce`、`set_relations`、`set_owes_obligation_to` |
| `diplomatic_plays` | 5 | `DIPLOMATIC_PLAYS` | `create_diplomatic_play`、`add_war_goal` |
| `governments` | 5 | `GOVERNMENT` | —（用 `set_ruling_party` 等，见 §4.6） |
| **`ai`** | 3 | **`AI`** | `set_strategy`、`set_secret_goal`、`set_mutual_secret_goal`、`set_variable`（→ 详见 `11`） |
| `conscription` | 1 | `CONSCRIPTION` | — |
| `cultures` | 1 | `CULTURES` | — |
| `global` | 1 | `GLOBAL` | `add_contextless_journal_entry`、`add_radicals`、`add_radicals_in_state`、`add_treasury`、`add_supply_ships`、`add_involvement`、`add_journal_entry`、`add_modifier`、`create_bidirectional_truce`、`set_variable` |
| `government_setup` | 1 | `GOVERNMENT_SETUP` | — |
| `lobbies` | 1 | `LOBBIES` | `create_political_lobby` |
| `military_deployments` | 1 | `MILITARY_DEPLOYMENTS` | — |
| `political_movements` | 1 | `POLITICAL_MOVEMENTS` | `create_political_movement`、`add_modifier` |
| `power_blocs` | 1 | `POWER_BLOCS` | `create_power_bloc` |
| `production_methods` | 1 | `PRODUCTION_METHODS` | — |
| `states` | 1 | `STATES` | `create_state`、`set_variable` |
| `trade` | 1 | `TRADE` | — |
| `treaties` | 1 | `TREATIES` | `create_treaty` |

> 上表「主要效果」列是对该目录全部 `.txt` 中**缩进 ≥2 的 `xxx = {`** 的机械提取，
> 已过滤为 `create_*` / `set_*` / `add_*` / `effect_*` 前缀者。

## 2. 通用结构模式

**【实测】** 所有 history 文件的骨架：

```pdx
<大写包装块> = {
	c:<TAG> ?= {
		<效果> = { ... }
	}
}
```

三个要素：

| 要素 | 说明 |
|---|---|
| **大写包装块** | 每个系统一个，决定文件被归入哪个初始化阶段（见 §1 表） |
| `c:<TAG> ?= { }` | 目标国家。**`?=` 是国家不存在时静默跳过**（不是错误） |
| 效果块 | 实际写入初始状态 |

### 2.1 作用域前缀速查

**【实测】** 文件里出现的作用域前缀：

| 前缀 | 含义 | 实例 |
|---|---|---|
| `c:` | 国家 | `c:SWE`、`c:GBR` |
| `s:` | 州（state） | `s:STATE_SVEALAND`、`s:STATE_MINSK` |
| `region_state:` | 州内的某国控制区 | `region_state:SWE` |
| `cu:` | 文化 | `cu:russian`、`cu:dixie` |
| `ig:` | 利益集团 | `ig:ig_landowners` |
| `py:` | 政党 | `py:conservative_party` |
| `sr:` | 战略区域 | `sr:region_central_europe` |
| `unit_type:` | 单位类型 | `unit_type:combat_unit_type_dragoons` |

## 3. 各系统详解

### 3.1 `states` —— 州的归属（476 KB，最大的单文件）

**【实测】** `00_states.txt` 有 476,391 字节。文件开头有一段官方注释（**逐字**）：

> Why do some state entries have quote marks around them, when others don't?
> It's because of differing methods of editing throughout the production of the game. Quote marks are unnecessary, but harmless if present.

结构：

```pdx
STATES = {
	s:STATE_MINSK = {
		create_state = {
			country = c:RUS
			owned_provinces = { x0161E0 x0A89D7 x16A8B5 ... }
		}

		add_homeland = cu:russian
		add_homeland = cu:byelorussian
	}
}
```

| 要素 | 说明 |
|---|---|
| `owned_provinces` | 该州包含的**地块 ID 列表**（`x` 开头的十六进制） |
| `add_homeland` | 声明某文化以该州为**故土** |

> **改地图归属 → 改这里**。地块 ID 与 `map_data\` 对应。

### 3.2 `countries` —— 国家初始设定（444 文件，逐国一个）

**【实测】** 文件命名 `小写TAG - 国名.txt`（如 `abs - absaroka.txt`）。
小文件可能只有几行：

```pdx
COUNTRIES = {
	c:ABS ?= {
		effect_starting_technology_tier_6_tech = yes
		effect_starting_politics_traditional = yes
		effect_native_conscription_10 = yes
	}
}
```

> **注意**：这里用的是 `effect_starting_*` 系列**预置效果**（引擎内置的成套初始化），
> 不必逐项写法律/科技。这大幅简化了国家定义 —— **但它并不排斥逐项效果**：
> 444 个国家文件里有 **217 个（49%）**在预置效果之外还逐项写了
> `add_amendment`(26)、`set_institution_investment_level`(60)、
> `set_import_tariff_level`(66)、`set_export_tariff_level`(6)、
> `set_ruling_interest_groups`(2)、`create_diplomatic_pact`(1)。【实测】

可用效果（**【实测】** 提取到的效果名）：

| 效果 | 作用 |
|---|---|
| `add_amendment` | 添加修正案 |
| `set_ruling_interest_groups` | 设定执政利益集团 |
| `set_institution_investment_level` | 设定机构投资等级 |
| `set_export_tariff_level` / `set_import_tariff_level` | 设定进出口关税 |
| `add_journal_entry` | 添加日志条目 |
| `add_modifier` | 添加修正符 |
| `create_diplomatic_pact` | 建立外交条约 |
| `set_global_variable` / `set_variable` | 设置变量 |

### 3.3 `characters` —— 历史人物（262 文件）

**【实测】** 用 `template` 引用 `common\character_templates\` 里定义的人物模板：

```pdx
CHARACTERS = {
	c:ABU ?= {
		create_character = {
			template = ABU_khalifa_al_nahyan
		}
		create_character = {
			template = ABU_saeed_al_nahyan
		}
	}
}
```

> **两级结构**：`character_templates`（定义人物长相/性格/出身）+ `history\characters`（决定谁在哪个国家出场）。
> `set_career_length` / `add_career_length` 控制人物在历史舞台上的存续时长。

### 3.4 `pops` —— 人口构成（17 文件，按地区分）

**【实测】** 结构是 **州 → 控制国 → POP 列表**：

```pdx
POPS = {
	s:STATE_SVEALAND = {
		region_state:SWE = {
			create_pop = {
				culture = swedish
				size = 1081208
			}
			create_pop = {
				culture = finnish
				size = 32000
			}
			create_pop = {
				culture = ashkenazi
				size = 1000
			}
		}
	}
}
```

> 每个 POP 只写 `culture` + `size`，**职业（pop_type）由引擎按建筑就业自动推导**
> —— 这与 `history\buildings` 定义的建筑数量联动。

### 3.5 `buildings` —— 初始建筑（16 文件，按地区分，合计 1,015 KiB；最大单文件 205 KiB）

**【实测】** 结构最复杂的一个：

```pdx
BUILDINGS={
	s:STATE_SVEALAND={
		region_state:SWE={
			create_building={
				building="building_government_administration"
				add_ownership={
					country={
						country="c:SWE"
						levels=4
					}
				}
				reserves=1
				activate_production_methods={ "pm_professional_bureaucrats" "pm_religious_bureaucrats" "pm_horizontal_drawer_cabinets" }
			}
			create_building={
				building="building_construction_sector"
				add_ownership={
					country={
						country="c:SWE"
						levels=1
					}
				}
			}
		}
	}
}
```

| 字段 | 说明 |
|---|---|
| `building` | 建筑类型键（对应 `common\buildings\`） |
| `add_ownership` | 所有权分配（`country` + `levels` 等级数） |
| `reserves` | 储备 |
| `activate_production_methods` | **开局激活的生产方式列表**（对应 `common\production_methods\`） |

> **注意引用字符串里的 `c:SWE` 带引号** —— 与其他位置写法不同，这是原版的既有风格。

### 3.6 `governments` —— 初始执政党

**【实测】** 用政党作用域 `py:`：

```pdx
GOVERNMENT = {
	c:BEL ?= {
		py:conservative_party ?= {
			set_ruling_party = yes
			add_momentum = 0.1
		}
	}
}
```

| 效果 | 说明 |
|---|---|
| `set_ruling_party` | 设为执政党 |
| `add_momentum` | 增加动量（政党支持度趋势） |

### 3.7 `military_formations` —— 初始军队编制（10 文件，`.txt` 合计 171 KiB；最大单文件 95 KiB）

**【实测】** 定义具体的军团及其下属单位：

```pdx
MILITARY_FORMATIONS = {
	c:PRU ?= {
		create_military_formation = {
			type = army
			hq_region = sr:region_central_europe
			name = 1_Armee

			combat_unit = {
				type = unit_type:combat_unit_type_skirmish_infantry
				state_region = s:STATE_POMERANIA
				count = 9
			}
		}
	}
}
```

| 字段 | 说明 |
|---|---|
| `type` | `army`（204 处）/ `fleet`（53 处）—— **两种都实测存在**；海军条目的下级用 `ship = { type = ship_type:… count = … }`（89 处），陆军用 `combat_unit = { … }` |
| `hq_region` | 所属战略区域（`sr:` 前缀） |
| `name` | 部队名（可本地化） |
| `combat_unit` | 下属单位块：`type` + `state_region`（驻扎州）+ `count` |

### 3.8 `diplomacy` —— 初始外交关系

**【实测】** 结构：

```pdx
DIPLOMACY = {
	c:TUR ?= {
		create_diplomatic_pact = {
			country = c:MON
			type = embargo
		}
	}
}
```

可用效果：`create_diplomatic_pact`、`create_bidirectional_truce`、`set_relations`、`set_owes_obligation_to`。
`type` 取值之一是 `embargo`（禁运）。

### 3.9 `treaties` —— 历史条约（26.8 KB）

**【实测】** 用日期定义条约生效时间：

```pdx
TREATIES = {
	### Holy Alliance - Russia, Austria, Prussia
	create_treaty = {
		name = treaty_name_holy_alliance
		first_country = c:RUS
		second_country = c:AUS

		is_draft = no
		entered_into_force_on = 1815.10.26
		binding_period = { years = 35 }

		articles_to_create = {
			{ # Defensive Pact
				article = defensive_pact
			}
		}
	}
}
```

| 字段 | 说明 |
|---|---|
| `name` | 条约名（本地化键） |
| `first_country` / `second_country` | 缔约双方 |
| `is_draft` | 是否为草稿 |
| `entered_into_force_on` | 生效日期 `年.月.日` |
| `binding_period` | 约束期（可为 `{ years = N }`） |
| `articles_to_create` | 条款列表（`article = <条款键>`，对应 `common\treaty_articles\`） |

> 注意：**条约名可以复用**（**三个**条约同名 `treaty_name_holy_alliance`：RUS/AUS、PRU/AUS、PRU/RUS）。

### 3.10 `power_blocs` —— 权力集团

**【实测】**：

```pdx
POWER_BLOCS = {
	c:GBR ?= {
		create_power_bloc = {
			name = BRITISH_EMPIRE
			map_color = hsv{ 0.99  0.7  0.9 }

			founding_date = 1784.5.12
			identity = identity_sovereign_empire
			principle = principle_vassalization_1
		}
		if = {
			limit = { has_dlc_feature = power_bloc_features }
			power_bloc = {
				add_principle = principle_colonial_offices_2
			}
		}
	}
}
```

| 字段/效果 | 说明 |
|---|---|
| `name` | 集团名 |
| `map_color` | 地图颜色，用 **`hsv{ h s v }`** 语法 |
| `founding_date` | 成立日期 |
| `identity` | 集团身份（对应 `common\power_bloc_identities\`） |
| `principle` / `add_principle` | 集团原则 |
| `has_dlc_feature` | **DLC 特性检查**（`power_bloc_features`） |

### 3.11 `political_movements` —— 初始政治运动

**【实测】** 用条件判断批量生成：

```pdx
POLITICAL_MOVEMENTS = {
	every_country = {
		limit = { NOT = { is_country_type = decentralized } }
		if = {
			limit = {
				has_law = law_type:law_monarchy
				country_has_voting_franchise = no
				NOT = { has_law = law_type:law_bakufu }
				NOT = { c:FRA ?= this } # No generic royalist movement for France
				NOR = {
					c:SPA ?= this
					c:SPC ?= this
				}
			}
			create_political_movement = { type = movement_royalist_absolutist }
		}
	}
}
```

> **两条重要语法**：
> - `c:FRA ?= this` —— **判断「当前国家是不是 FRA」**（`this` 指代当前作用域）
> - `NOR = { }` —— 「全都不成立」的逻辑块

### 3.12 `diplomatic_plays` —— 开局的进行中博弈

**【实测】** 效果：`create_diplomatic_play`、`add_war_goal`。

### 3.13 `global` —— 最后执行的全局初始化（24 KB）

**【实测】** 文件开头官方注释（**逐字**）：

> This is executed last among all history

```pdx
GLOBAL = {
	add_contextless_journal_entry = je_uneasy_raj

	every_country = {
		limit = { NOT = { has_law_or_variant = law_type:law_slavery_banned } }
		if = {
			limit = { has_law_or_variant = law_type:law_colonial_slavery }
			ig:ig_landowners ?= { add_ideology = ideology_pro_slavery_colonial }
		}
		else = {
			ig:ig_landowners ?= { add_ideology = ideology_pro_slavery }
		}
	}
}
```

> **这是所有 mod 最该关注的 history 文件**：它在最后执行，可以**覆盖前面所有目录的结果**，
> 且支持 `every_country` + `limit` 的批量逻辑，比逐国硬编码优雅。
> 可用效果最丰富：`add_radicals`、`add_radicals_in_state`、`add_treasury`、`add_supply_ships`、`add_involvement`。

### 3.14 `ai` —— AI 策略分配

见 `11-历史初始状态与AI策略分配.md`（含 27 国完整映射表）。
三个文件：`00_strategy.txt`、`00_secret_goals.txt`、`00_behavior_variables.txt`。

### 3.15 其余单文件目录

| 目录 | 包装块 | 推测作用 |
|---|---|---|
| `conscription` | `CONSCRIPTION` | 初始征兵状态 |
| `cultures` | `CULTURES` | 文化初始设定 |
| `government_setup` | `GOVERNMENT_SETUP` | 政府组建规则 |
| `lobbies` | `LOBBIES` | 初始政治游说团（`create_political_lobby`） |
| `military_deployments` | `MILITARY_DEPLOYMENTS` | 初始军队部署 |
| `production_methods` | `PRODUCTION_METHODS` | 生产方式初始状态 |
| `trade` | `TRADE` | 初始贸易路线 |
| `population` | `POPULATION` | 按国家给**初始人口属性**（`effect_starting_pop_wealth_*` / `_literacy_*`）；与 `pops` 的差别是「改属性 vs 造人口」【实测】 |

## 4. 在 mod 中改开局

### 4.1 三种介入方式

| 方式 | 做法 | 风险 |
|---|---|---|
| **覆盖整文件** | 放同路径同名文件（如 `history\countries\swe - sweden.txt`） | 与其他 mod 冲突 |
| **新增文件** | 用自己的文件名 + 同样的包装块 | ✅ **推荐**，零冲突 |
| **用 `GLOBAL` 兜底** | 在 `history\global\` 加自己的文件，用 `every_country` 批量改 | ✅ 最后执行，结果最确定 |

### 4.2 实战示例：让某国开局多一个建筑

```pdx
BUILDINGS = {
	c:SWE ?= {
		s:STATE_SVEALAND = {
			region_state:SWE = {
				create_building = {
					building = "building_university"
					activate_production_methods = { "pm_scholastic_education" "pm_religious_academia" }
					add_ownership = {
						country = { country = "c:SWE" levels = 1 }
					}
				}
			}
		}
	}
}
```

> ⚠️ **生产方式名必须是真实存在的 PM**：`building_university` 的 PM 组是
> `pmg_base_building_university` / `pmg_university_academia`，合法 PM 为
> `pm_scholastic_education`、`pm_philosophy_department`、
> `pm_analytical_philosophy_department`、`pm_religious_academia`、
> `pm_secular_academia`。上面两个取自原版
> （`common\history\buildings\00_west_europe.txt`）。
> 【实测】**全 `game` 树搜 `university_standard` 零命中** —— 这类"看起来很像"
> 的名字在 PDX 脚本里不会报错，只会静默失效。

### 4.3 实战示例：开局给所有国家加修正符

```pdx
GLOBAL = {
	every_country = {
		limit = { is_country_type = recognized }
		add_modifier = { modifier = my_starting_modifier years = 10 }
	}
}
```

## 5. 未确认项

| 项 | 状态 |
|---|---|
| `population` 与 `pops` 的分工 | **未确认** |
| 各 history 目录的**执行顺序**（仅知 `global` 最后） | **未确认** |
| `conscription`、`cultures`、`government_setup`、`military_deployments`、`production_methods`、`trade` 的具体字段 | **未采样** |
| 多处对同一国家/州写入的合并规则 | **未确认** |
| `effect_starting_*` 预置效果的完整清单 | **未整理**（猜测在 `common\scripted_effects\`，待查） |
