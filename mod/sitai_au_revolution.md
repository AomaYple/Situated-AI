# 档案 · 奥地利 · 革命潮

> ⚠️ 本文件由 `v3 modgen` 生成 —— 改这里没用，改数据源 `mod/data/*.toml`。

* **档案 id**：`au_revolution`　**国家**：`AUS`　**游戏版本**：`1.14.4`
* **本档案修什么毛病**：「帝国是从内部裂开的」这件事在原版里**没有账**：合法性照旧、激进派照旧被压着、守旧侧照旧在朝，于是「革命危机 → 改革」这条因果在原版里根本不存在。档案不替 AI 决定改什么，只把危机记成账、把压力落成真实的**合法性 / 激进派 / 保守 IG 势力**变化。为什么主角是奥地利：`01a` §K 的「奥地利」那一行写的就是**多民族、保守、财政脆弱、内陆市场**，而「敌人的位置」上写的是**民族主义从内部撕扯** —— 这是一份以内部合法性崩塌为机制的档案，不是「战败」的换名。tag = `AUS` 是本机实测确认的（`v3 evidence AUS` 命中原版 `common/country_definitions/00_countries.txt:93` 的 `AUS = {`，该文件的顶层键就是国家 tag），**不是猜的**。⚠️ 依据已于 2026-09-22 更正：原版 AI 策略里 212 处 has_journal_entry 全部硬编码**具名** JE，没有「读任意 JE」的通用谓词 ⇒ 我们自己的 JE 一张原版牌也喂不到（backlog B52）；真正把压力变成意图位移的通道是递牌（set_strategy，B58）与法律承诺（law commitment，B56/B57）。　【沿用·口径】本表的数值与依据**原样沿用** `ru_defeat.toml` 的实测档位（阶段 3 的 A/B 读数），**未针对本条处境独立校准**。
* **递牌**：0 张 —— 本档案**不使用自建策略牌**（F5：能改世界就不占槽）。革命潮 → 压力的链路由变量 + 修正 + JE 表达；⚠️ JE **不会**被原版牌读到（原版 212 处 has_journal_entry 全硬编码具名 JE，没有通用谓词，backlog B52），所以意图位移**不能**指望「开一个 JE 就被牌池读到」。要真的换路线，用（a）递**原版**的牌 `set_strategy`（B58）或（b）法律承诺 law commitment（B56/B57）—— 两者都是「整条路线要换」时的手段。**本档案为什么不递**：有判据可写的递牌法是「窗口开时递进步牌、窗口关时递回该国 1836 的初始牌」（`ru_defeat` 的 `[journal_entry.signals]` 就是这么写的），但**奥地利在原版里没有写下自己的初始落点** —— `common/history/ai/00_strategy.txt` 里只有具名国家块（`c:RUS` 在 :87-91、其中 :90 是 `set_strategy = ai_strategy_reactionary_agenda`；紧接着 :92 是 `c:TUR`），**没有 `c:AUS` 块**（本机实测：该文件里搜不到 AUS，AUS 只出现在 `00_behavior_variables.txt:6` 与 `00_secret_goals.txt` 的 secret goals 里）。照抄俄国那三行会把奥地利递到一个它从没站过的路线上 —— 那就不是「让 AI 自己推导」，是我们替它选。写这张表的判据需要先实测奥地利 1836 的初始牌与重抽落点（阶段 5 的 A/B 会话），在那之前**一张都不递**比递一张编的牌诚实。递牌的政治槽价格：S≈33 时权重 10 吃掉 23% 的份额（阶段 2 价格表）。

## 产物清单

| 文件 | 作用 |
|---|---|
| `common/scripted_effects/sitai_au_revolution_effects.txt` | 冲击记账效果（写 `sitai_au_revolution_memory` + 挂 `sitai_au_revolution_pressure`） |
| `common/static_modifiers/sitai_au_revolution_pressure.txt` | 压力修正（真实的合法性 / 贵族 / 财政变化） |
| `common/journal_entries/sitai_au_revolution_window.txt` | 改革窗口 JE（判据驱动） |
| —— | 本档案不声明 `[tempo]`（全仓一份的 mod 级表，由另一份数据源声明） |
| `common/static_modifiers/sitai_au_revolution_reform_inputs.txt` | 改革侧输入修正（第二处理段 B2 才挂；`sitai_au_reform_input` 施加） |
| `localization/english/sitai_au_revolution_l_english.yml` | english 文案 |
| `localization/simp_chinese/sitai_au_revolution_l_simp_chinese.yml` | simp_chinese 文案 |
| `.metadata/metadata.json` | mod 元数据（启动器读；不带 BOM） |

## 每个数字与它的依据（P10）

| 位置 | 数值 | 依据 |
|---|---:|---|
| `memory.params[0].amount` | 1 | 变量在判据里只被 has_variable 读，值不参与任何运算；写 1 而不是 yes，是为了将来要用 change_variable 记「第几次革命危机」时不用换类型（原版 set_variable = { name = recently_had_war value = yes } 用的是 yes，见 00_code_on_actions.txt:7046）。 |
| `memory.params[1].amount` | 3650 | 10 年，与压力修正的 years = 10 同一时间尺度（两处必须一起改，否则会出现「记忆还在、压力已经没了」的半截状态）。对照原版给 recently_had_war 的是 days = 1825（5 年，00_code_on_actions.txt:7048），而原版 1848 革命事件给同类修正的写法是 days = short_modifier_time（events/1848.txt:430-433）—— 一次革命危机比「打过仗」更该留得久，故取 1825 的两倍。　【沿用·口径】3650 **沿用 `ru_defeat.toml` 的实测档位**（该值在其 why 里写作「战败比打过仗更该留得久，故取两倍」），**未针对本条处境独立校准**。 |
| `pressure.params[0].amount` | 10 | 与 sitai_au_revolution_memory 的 days = 3650 对齐。原版 add_modifier 用 years 的写法见 00_movement_effects.txt:2-4（add_modifier = { name = … years = 20 }）；原版 1848 革命内容给同类修正的写法见 events/1848.txt:430-433。　【沿用·口径】沿用 `ru_defeat` 的取值，未针对本条处境独立校准。 |
| `pressure.effects[0].amount` | -35 | 合法性是开窗判据的一半（JE 的 possible 读 `legitimacy <= 75` —— 为什么是 75 见 conditions 那条的依据）。**为什么取 -35**：它是 `ru_defeat` 在阶段 3 里**实测调过档**的值（先取 -20 跑一整局 B 组、窗口一次都没开 → 提到 -35；复算 `v3 ab --logs ab-run7`，B 段 55 块合法性分档 b70 24 / b75 18 / b80 13），也就是「把水位稳定压出一档、又不让政府一次失能」的那一档；本档案**原样沿用**，没有针对奥地利重跑 A/B。**这个数在原版里也真的存在**：`modifier_india_crown_rule` 就给 `country_legitimacy_base_add = -35`（content_304_modifiers.txt:249 是修正名、:254 是这个字段），同字段的原版阶梯为 +10 / +5 / -10 / -20 / -50（00_code_static_modifiers.txt:322、:331、:343、:353、:986）—— 所以 -35 落在 -20 与 -50 之间，方向与档位都不是我们发明的。**为什么不取原版那条 50 线**（00_liberalism.txt:54 的 `government_legitimacy >= 50`）：`ru_defeat` 实测过一次「判据取 50」，那一局（`ab-run3-done`，-35，61 个月）窗口从未开、法律全程没动 —— 同样的门槛在本档案里会重犯同一个错。　【沿用·口径】**数值沿用 `ru_defeat` 的实测档位（-35），未针对本条处境独立校准**；原版同字段另有 -35（content_304_modifiers.txt:254）与 -50（00_code_static_modifiers.txt:986）两档可引。 |
| `pressure.effects[1].amount` | 0.25 | **这一条就是革命潮的机制**（也是本档案与 ru/tr 最本质的差别）：该字段的语义是「**由低合法性产生的那部分激进派** × 倍率」，于是它与上面那条 `country_legitimacy_base_add = -35` 合起来构成一条**真实的因果链**：合法性塌 → 激进派涨。原版自己在同一个修正里就是这么配的 —— `modifier_legacy_of_the_liberal_wars`（自由战争的遗产）同时写 `interest_group_ig_landowners_pol_str_mult = -0.75`、`interest_group_ig_intelligentsia_pol_str_mult = 0.25`、`country_radicals_from_legitimacy_mult = 0.25`（00_ip4_04_modifiers.txt:172-178）：那正是「一场内乱之后：旧势力失势 + 激进主义抬头」这一族用法，与本处同型。**为什么取 0.25**：它是**原版档位本身**（00_ip4_04_modifiers.txt:177），不是插值；原版该字段的全部档位为 0.05（00_ip4_02_modifiers.txt:20，modifier_reduced_economic_objectives）、0.1（:64，modifier_economic_regeneration_postponed）、0.2（:71，modifier_failed_economic_regeneration；:104，modifier_divisive_press_campaign）、0.25（00_ip4_04_modifiers.txt:177）、1（agitators_3_modifiers.txt:81，fra_republican_unrest —— 法国共和派骚动，原版里离「革命潮」最近的一族）。取 0.25 而不是 1：0.25 是原版给「内乱之后」的档，1 是原版给**已经烧起来的那一场**的档 —— 本档案的窗口是「危机中」，不是「已经开战」。　【原版行号依据】不是实测读数，是原版同族用法（上面那一串行号，逐行打开确认过）。 |
| `pressure.effects[2].amount` | -0.3 | 第三条：某个保守 IG 的势力。**选地主而不是虔诚派**：奥地利 1836 的守旧侧是**土地贵族**（多民族帝国的议会算术由贵族与民族运动共同决定，见 `01a` §K「奥地利」那一行：多民族、保守、财政脆弱），而且这个字段在**革命那一族**修正里就是原版的用法 —— `modifier_minor_royal_assassinated`（弑君的余波）就是 `interest_group_ig_landowners_pol_str_mult = -0.20`（agitators_4_revolution_modifiers.txt:319 与 :321）。**为什么取 -0.30**：它是 `ru_defeat` 实测调过档的值（-0.15 在一整局里没能让行为层动起来 → -0.30），本档案**原样沿用**；原版该字段的阶梯为 ±0.03（00_ip3_04_modifiers.txt:334）、-0.20（agitators_4_revolution_modifiers.txt:321）、-0.50（agitators_5_modifiers.txt:615）、-0.75（content_1_modifiers.txt:1465 的 shogun_ig_forced_to_open_market），-0.30 落在 -0.20 与 -0.50 之间。**为什么不是虔诚派（devout）**：它同样是奥地利的一条保守侧字段、原版档位也齐全（-0.25 见 00_ip4_04_modifiers.txt:141 的 modifier_devorismo，注释写着 `# Selling church lands`；-0.50 见 agitators_5_modifiers.txt:616；+0.15 见 106_modifiers.txt:224），但那一族的原版语义是「教产/教会权力被动」，而本档案要表达的是**革命把旧贵族的权威打掉**；两条字段只能选一条时选语义更贴的那条，`interest_group_ig_devout_pol_str_mult` 留给「政教冲突」那一类处境。　【沿用·口径】**数值沿用 `ru_defeat` 的实测档位（-0.30），未针对本条处境独立校准**。 |
| `reform_inputs.params[0].amount` | 10 | 与 [pressure.params] 的 years = 10、记忆变量的 days = 3650 三处对齐：三者在实验里是同一段时间窗，任何一处短了都会出现「输入还在、压力已经没了」的半截状态。原版 add_modifier 用 years 的写法见 00_movement_effects.txt:2-4。　【沿用·口径】沿用 `ru_defeat` 的取值，未针对本条处境独立校准。 |
| `reform_inputs.effects[0].amount` | 0.5 | 取原版同族强档 +0.5：`shogun_ig_forced_to_open_market`（content_1_modifiers.txt:1463-1471）在同一个修正里把地主 -0.75（:1465）、知识界 +0.5（:1466）、工业家 +0.5（:1467）一起写 —— 那正是「被外力逼着开门 → 改革侧势力抬头」这一族用法。原版全部档位为 0.1（00_ip4_03_modifiers.txt:7）、0.25（00_ip4_04_modifiers.txt:33）、0.5（content_1_modifiers.txt:1467），另有特例 2（content_304_modifiers.txt:251）。取 0.5 而不是 0.1：`progressive_agenda` 的权重只在 `ig:ig_industrialists ?= { is_powerful = yes }` 时 +10，而 is_powerful 是**相对份额**判定 —— 只抬一档常常翻不过那条线，实验要的是「输入明确到位」，不是「差一点」。　【沿用·口径】**数值沿用 `ru_defeat` 的实测档位（0.5），未针对本条处境独立校准**；档位本身也是原版幕府那条的档（content_1_modifiers.txt:1467）。 |
| `reform_inputs.effects[1].amount` | 0.5 | 与工业家同档同源：`shogun_ig_forced_to_open_market`（content_1_modifiers.txt:1466）里这两条就是成对写的，而原版那条「自由战争的遗产」（伊比利亚自由战争之后）也把知识界 +0.25 与地主 -0.75 写成一对（00_ip4_04_modifiers.txt:174 与 :176）。原版该字段档位为 0.15（106_modifiers.txt:205）、0.25（00_ip4_04_modifiers.txt:176）、0.5（content_1_modifiers.txt:1466）。两条一起给才是原版的用法；只给一条会让「哪一条起了作用」在实验里不可分。　【沿用·口径】**数值沿用 `ru_defeat` 的实测档位（0.5），未针对本条处境独立校准**；档位依据见上一条。 |
| `journal_entry.fields[0].amount` | 100 | JE 列表拥挤时的保留优先级。与原版 je_corn_laws 的 weight = 100 同档（00_corn_laws.txt:79）—— 处境级窗口不该被小 JE 挤掉。⚠️ 已知的档位差异：原版革命危机那两条 JE 用的是 10000（je_springtime_of_the_peoples，00_peoples_springtime_je.txt:315）与 9000（je_red_summer，00_peoples_springtime_je.txt:472）。本档案**刻意不取 1000/9000/10000**：那几档是原版核心历史内容 JE，本档案是与它们并行的处境窗口，压过它们会把原版自己的 1848 内容挤下去。　【沿用·口径】沿用 `ru_defeat` 的取值，未针对本条处境独立校准。 |
| `journal_entry.conditions[3].amount` | 75 | 开窗的第二个条件：压力够大。**为什么门槛是 75**：① 原版就用 75 做「政府站得住 / 站不住」的国家级分界（00_meiji_restoration.txt:314 的 `legitimacy >= 75`、01_french_monarchism.txt:329 的 `government_legitimacy >= 75`）；② 它同时是 `ru_defeat` 在阶段 3 里**实测校准**过的门槛（A 组无冲击时每一个观测月都 >80、不会误开；B 组 -35 时 55 块里有 42 块 ≤75）。本档案没有独立重跑 A/B：这个 75 **原样沿用 `ru_defeat` 的实测分界**。**为什么没有第二条「激进派」判据**（革命潮最想要的那一条）—— 查过原版 1.14.3，结论是**本 schema + 原版词汇表达不出来**，如实记在这里：`radicals_percentage` 在原版是 0 处（`v3 evidence radicals_percentage`：原版键 0 处、exe 也无字面量）；`radical_fraction` 是**块形式**的作用域取值（00_strike_triggers.txt:53-60、00_ip3_victoria_scripted_triggers.txt:193-196）；`political_movement_radicalism` 是**运动作用域**的（05_austria_journal_entries.txt:42-45 就是在 `any_political_movement = { … }` 里用它，00_meiji_restoration.txt:330 同）；唯一平铺可用的国家作用域写法是脚本化触发器 `any_insurrection_ongoing`（00_scripted_triggers.txt:1117），但它要求「已经出现叛乱运动」，比本窗口要表达的「危机中」更晚、也更严 —— 本档案**没有实测**它会不会让窗口一直不开，所以不拿它当门（`ru_defeat` 的教训：判据取 50 的那一局窗口一次都没开）。而生成器的判据渲染只支持平铺一行 `key op 操作数`（tools/pdx/modgen.py:180-182 的 `Clause.render`），块形式的写法在本 schema 里根本表达不出来。**于是激进派这条状态由 [pressure] 的字段承担**（它由引擎自己的激进派公式读，见 `country_radicals_from_legitimacy_mult` 那条 why），门只开在合法性上。相应地 `complete` 写 75，开与关正好接上。　【沿用·口径】**数值沿用 `ru_defeat` 的实测档位，未针对本条处境独立校准**；另两条原版 75 是先例。 |
| `journal_entry.conditions[4].amount` | 75 | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 `legitimacy >= 75`、01_french_monarchism.txt:329 的 `government_legitimacy >= 75`。　【沿用·口径】沿用 `ru_defeat` 的取值，未针对本条处境独立校准。 |

## 判据（JE）

| 判据块 | 判据 | 为什么 |
|---|---|---|
| `is_shown_when_inactive` | `c:AUS ?= this` | 档案是**单国**的，主角是奥地利。tag = `AUS` 是本机实测确认的（`v3 evidence AUS` 命中原版 `common/country_definitions/00_countries.txt:93` 的 `AUS = {`；该文件的顶层键就是国家 tag），不是猜的。`c:AUS ?= this` 这个写法在**奥地利自己的 JE** 里就是原版用法（05_austria_journal_entries.txt:10 的 `c:AUS ?= this`，在 `is_shown_in_lobby` 块里），问号的语义是「作用域存在才比」，比裸 = 稳。 |
| `is_shown_when_inactive` | `has_variable = sitai_au_revolution_memory` | 没被记过「革命危机」的国家连这条 JE 都不该看见 —— 「和平期占槽率 ≈ 0」这条出口判据（G-EXIT-5.2）靠它：不施加冲击的局里，这行判据为假，整条 JE 不出现。原版读变量的写法见 00_corn_laws.txt:7（`NOT = { has_variable = corn_laws_abolished }`）。　【沿用·口径】沿用 ru/tr 的判据形状，未针对本条处境独立校准。 |
| `possible` | `has_variable = sitai_au_revolution_memory` | 开窗的第一个条件：确实经历过革命危机。is_shown 与 possible 都写一遍是有意的 —— 前者管「看不看得见」，后者管「开不开」，原版 je_corn_laws 也是两处各写一套（00_corn_laws.txt:6-31）。　【沿用·口径】沿用 ru/tr 的判据形状，未针对本条处境独立校准。 |
| `possible` | `legitimacy <= 75` | 开窗的第二个条件：压力够大。**为什么门槛是 75**：① 原版就用 75 做「政府站得住 / 站不住」的国家级分界（00_meiji_restoration.txt:314 的 `legitimacy >= 75`、01_french_monarchism.txt:329 的 `government_legitimacy >= 75`）；② 它同时是 `ru_defeat` 在阶段 3 里**实测校准**过的门槛（A 组无冲击时每一个观测月都 >80、不会误开；B 组 -35 时 55 块里有 42 块 ≤75）。本档案没有独立重跑 A/B：这个 75 **原样沿用 `ru_defeat` 的实测分界**。**为什么没有第二条「激进派」判据**（革命潮最想要的那一条）—— 查过原版 1.14.3，结论是**本 schema + 原版词汇表达不出来**，如实记在这里：`radicals_percentage` 在原版是 0 处（`v3 evidence radicals_percentage`：原版键 0 处、exe 也无字面量）；`radical_fraction` 是**块形式**的作用域取值（00_strike_triggers.txt:53-60、00_ip3_victoria_scripted_triggers.txt:193-196）；`political_movement_radicalism` 是**运动作用域**的（05_austria_journal_entries.txt:42-45 就是在 `any_political_movement = { … }` 里用它，00_meiji_restoration.txt:330 同）；唯一平铺可用的国家作用域写法是脚本化触发器 `any_insurrection_ongoing`（00_scripted_triggers.txt:1117），但它要求「已经出现叛乱运动」，比本窗口要表达的「危机中」更晚、也更严 —— 本档案**没有实测**它会不会让窗口一直不开，所以不拿它当门（`ru_defeat` 的教训：判据取 50 的那一局窗口一次都没开）。而生成器的判据渲染只支持平铺一行 `key op 操作数`（tools/pdx/modgen.py:180-182 的 `Clause.render`），块形式的写法在本 schema 里根本表达不出来。**于是激进派这条状态由 [pressure] 的字段承担**（它由引擎自己的激进派公式读，见 `country_radicals_from_legitimacy_mult` 那条 why），门只开在合法性上。相应地 `complete` 写 75，开与关正好接上。　【沿用·口径】**数值沿用 `ru_defeat` 的实测档位，未针对本条处境独立校准**；另两条原版 75 是先例。 |
| `complete` | `legitimacy >= 75` | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 `legitimacy >= 75`、01_french_monarchism.txt:329 的 `government_legitimacy >= 75`。　【沿用·口径】沿用 `ru_defeat` 的取值，未针对本条处境独立校准。 |

## 面板三行（P11 / G3）

| 行 | 本地化键 | 为什么是这一行 |
|---|---|---|
| goal | `je_sitai_au_revolution_window_goal` | 第一行 = **当前目标**。革命潮与战败共用同一句'目标'是对的：这一行说的是**机会窗口**（谁在拦、趁什么推开），不是'为什么会裂开' —— 后者是第三行的事。 |
| pressure | `je_sitai_au_revolution_window_pressure` | 第二行 = **最大压力与阻力**。压力项与 [pressure.effects] 的三条字段对应（合法性 / 激进派系数 / 保守 IG），其中'激进派在涨'来自 country_radicals_from_legitimacy_mult —— 那是革命潮的机制本身（合法性塌 → 激进派涨），所以必须在玩家看得见的那一行里出现。 |
| last_change | `je_sitai_au_revolution_window_last_change` | 第三行 = **上次改主意的原因**。与战败档的区别正在这里：战败是'外部打进来'，革命潮是'内部裂开'，而玩家能从这一行读出因果链的起点。 |

> 为什么拆成三个键而不是揉进 `_reason`：G3 判的是**试玩者能复述**「当前目标 + 主因」，揉在一起就分不清是哪一行没写清楚。缺行当场可见。

## 声明式引用（闸门 ② 逐条核对）

| 类别 | 名字 | 为什么 |
|---|---|---|
| `trigger` | `legitimacy` | JE 的开窗/关窗判据（`legitimacy <= 75` / `>= 75`）。原版用法：00_meiji_restoration.txt:314 的 `legitimacy >= 75`。 |
| `trigger` | `has_variable` | 记忆变量的读法。原版用法：00_corn_laws.txt:7（`NOT = { has_variable = corn_laws_abolished }`），阶段 1 统计 has_variable 被 13 张原版牌直接读。 |
| `effect` | `set_variable` | 写记忆变量。原版用法：00_code_on_actions.txt:7046（on_war_end 给 recently_had_war 记 5 年，:7048 是 days）。 |
| `effect` | `add_modifier` | 把静态修正挂到国家上。原版用法：00_movement_effects.txt:2-4（add_modifier = { name = … years = 20 }）；原版 1848 革命内容里也有 add_modifier = { name = suppressing_radicals days = short_modifier_time }（events/1848.txt:430-433）。 |
| `country_tag` | `AUS` | JE 的单国门（`c:AUS ?= this`）。原版用法：common/country_definitions/00_countries.txt:93 的 `AUS = {`（本机 `v3 evidence AUS` 复核）；该 tag 在奥地利自己的 JE 里也被这么用（05_austria_journal_entries.txt:10）。 |
| `modifier_field` | `country_legitimacy_base_add` | 合法性修正字段。原版档位 +10 / +5 / -10 / -20 / -50（00_code_static_modifiers.txt:322、:331、:343、:353、:986），另有 -35（content_304_modifiers.txt:254 的 modifier_india_crown_rule）—— 本档案取的 -35 正是这一档。 |
| `modifier_field` | `country_radicals_from_legitimacy_mult` | 本档案新引入的字段（革命潮的机制）：合法性低所产生的那部分激进派的倍率。原版档位 0.05（00_ip4_02_modifiers.txt:20）、0.1（00_ip4_02_modifiers.txt:64）、0.2（00_ip4_02_modifiers.txt:71 与 :104）、0.25（00_ip4_04_modifiers.txt:177 的 modifier_legacy_of_the_liberal_wars）、1（agitators_3_modifiers.txt:81 的 fra_republican_unrest）。 |
| `modifier_field` | `interest_group_ig_landowners_pol_str_mult` | 地主（奥地利守旧侧）政治力量。原版档位 ±0.03（00_ip3_04_modifiers.txt:334）、-0.20（agitators_4_revolution_modifiers.txt:321 的 modifier_minor_royal_assassinated，革命那一族的用法）、-0.50（agitators_5_modifiers.txt:615）、-0.75（content_1_modifiers.txt:1465 的 shogun_ig_forced_to_open_market）。 |
| `modifier_field` | `interest_group_ig_industrialists_pol_str_mult` | 工业家政治力量（改革侧输入之一）。原版档位 0.1（00_ip4_03_modifiers.txt:7）、0.25（00_ip4_04_modifiers.txt:33）、0.5（content_1_modifiers.txt:1467 的 shogun_ig_forced_to_open_market）。 |
| `modifier_field` | `interest_group_ig_intelligentsia_pol_str_mult` | 知识界政治力量（改革侧输入之一）。原版档位 0.15（106_modifiers.txt:205）、0.25（00_ip4_04_modifiers.txt:176 的 modifier_legacy_of_the_liberal_wars）、0.5（content_1_modifiers.txt:1466 的 shogun_ig_forced_to_open_market）。 |

## 复算

```text
v3 modgen --write     # 数据源 → 产物（改完 TOML 必跑）
v3 modguard           # 五道闸门（不通过不许进游戏）
v3 modgen --why       # 只列每个数字与它的依据
```
