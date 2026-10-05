# 档案 · 俄罗斯 · 战败求存

> ⚠️ 本文件由 `v3 modgen` 生成 —— 改这里没用，改数据源 `mod/data/*.toml`。

* **档案 id**：`ru_defeat`　**国家**：`RUS`　**游戏版本**：`1.14.5`
* **本档案修什么毛病**：战败之后 AI 照旧走原来的路 —— 贵族照旧在朝、合法性不塌、财政不受罚，于是「战败 → 改革」这条因果在原版里根本不存在。档案不替 AI 决定改什么，只把战败记成账、把压力落成真实的合法性/贵族/财政变化。⚠️ 依据已于 2026-09-22 更正：原版 AI 策略里 212 处 has_journal_entry 全部硬编码**具名** JE，没有「读任意 JE」的通用谓词 ⇒ 我们自己的 JE 一张原版牌也喂不到（backlog B52）；真正把压力变成意图位移的通道是递牌（set_strategy，B58）与法律承诺（law commitment，B56/B57）。
* **递牌**：1 张 —— 旧设计实验资产：政治槽处境牌仍参与压力修正后的抽取。本档案不是通用财政决策的默认生产机制；不从 possible 推导已持牌会自动退出。

## 目标函数（9 国目标函数表 · I7）

| 项 | 档 | 依据 | 为什么 |
|---|---|---|---|
| 存续 | 1 · `01a:269` | §K 俄国行（`01a:269`）写「纵深无敌」—— 本仓**没有任何字段**直接动「国家存续」—— 依据 = 口径页 §3.1 的字段族清单（**可复算**：数 9 份 `[[*.effects]]` 的 `key =` 全集，存续类 0 处），**不是对引擎能力的断言** ⇒ 到档 1 为止。 |
| 财政 | 3 · `mod/data/ru_defeat.toml:85-87` | 本档案 `[[pressure.effects]]` 真的在动 `country_loan_interest_rate_add`（`:85-87`）⇒ 档 3（判据或字段）；幅度的原版同族阶梯写在那一格自己的 `why` 里。 |
| 合法性 | 3 · `mod/data/ru_defeat.toml:148-150` | JE 的 `possible` 读 `legitimacy <= 75`（`:148-150`）—— 判据读它。另一条同样合规的依据是 `:75-77` 的 `country_legitimacy_base_add`（§2.2 档 3 子规则 (b)：两条都合规，任选一条进 `evidence`、另一条留在这里）。 |
| 军力 | 1 · `01a:269` | §K 写「陆军庞大」（`01a:269`）；本仓唯一能表达军力的字段 `interest_group_ig_armed_forces_pol_str_mult` 今天只有 `sp_empire_remnant` 在用 ⇒ 本档案**不填**（不许编）。 |
| 市场依赖 | 0 · 缺 | **缺**：本仓 9 份里没有任何字段动商路/市场依赖；`01a:269` 只写「财政靠农税」（那是财政项）⇒ 留空。要填先有字段（口径页 §3.3）。 |
| 身份项 · `ideology` | 1 · `01a:269` | §K 俄国行的政治列写 `conservative_agenda`、括号里明写「战败后应转向 `progressive_agenda`」（`01a:269`；同句见 `01a:306-307`）—— 身份项第一来源（§3.2 第 1 条）就落在这句上：守成，且**被现实惩罚过就该转向**。 |
| 约束集 · `friction` | 3 · `mod/data/ru_defeat.toml:80-82` | 本档案 `[[pressure.effects]]` 把地主压到 -0.30（`:80-82`）—— 它既是摩擦的来源，也是改革要推开的那道钳制（§3.3 的「摩擦」行：本国历史文件 + 本档案 pressure 的 IG 字段）。 |
| 约束集 · `endowment` | 2 · `common/history/countries/rus - russia.txt:14` | 原版具名事实：开局法律里有 `activate_law = law_type:law_serfdom`（`common/history/countries/rus - russia.txt:14`）⇒ 禀赋 = 起手就有的制度与土地关系（§3.3 的「禀赋」行）。 |
| 约束集 · `player` | 1 · `01a:18` | 玩家是外部因素里「快」的那一档，且**不落文件**（`01a:18`；§3.3 的「玩家」行）⇒ 档 1 + 别名依据。 |

**裁定**：`pushed` · `ai_strategy_progressive_agenda` —— `[probe].reform_card` 非空（`ai_strategy_progressive_agenda`）且 `[journal_entry.signals.set_strategy]`（`:170`）递的就是同一张 ⇒ `derive()` 第 1 条 ⇒ `pushed`。
**代价**：政治槽 `40/(40 + 33)` = **54.8%**（现算；预算 `[0.3, 0.6]` 见闸门 ③）

## 产物清单

| 文件 | 作用 |
|---|---|
| `common/scripted_effects/sitai_ru_defeat_effects.txt` | 冲击记账效果（写 `sitai_ru_defeat_memory` + 挂 `sitai_ru_defeat_pressure`） |
| `common/static_modifiers/sitai_ru_defeat_pressure.txt` | 压力修正（真实的合法性 / 贵族 / 财政变化） |
| `common/journal_entries/sitai_ru_defeat_window.txt` | 改革窗口 JE（判据驱动） |
| `common/defines/sitai_ru_defeat_tempo.txt` | 节奏杠杆（覆盖 `NAI` 块） |
| `common/static_modifiers/sitai_ru_defeat_reform_inputs.txt` | 改革侧输入修正（第二处理段 B2 才挂；`sitai_ru_reform_input` 施加） |
| `localization/english/sitai_ru_defeat_l_english.yml` | english 文案 |
| `localization/simp_chinese/sitai_ru_defeat_l_simp_chinese.yml` | simp_chinese 文案 |
| `.metadata/metadata.json` | mod 元数据（启动器读；不带 BOM） |

## 每个数字与它的依据（P10）

| 位置 | 数值 | 依据 |
|---|---:|---|
| `tempo.keys[0].amount` | 40 | 原版 100 点：周通道每周 20% 概率 +1 点 → 0.20×52.14/12 ≈ 0.87 点/月 → 攒够 100 点要 ≈115 个月 ≈ 9.6 年（阶段 2 订正过口径）。取 40 是为了把重抽拉到「数年一次」：与下面那 30% 配对后 ≈1.30 点/月 → 40/1.30 ≈ 30.7 个月 ≈ 2.6 年。不取风暴档（门槛 1 / 周概率 100）—— 那是实验设置，每周改主意在观感上是反复无常，而 G4 要的是「世界活了」（阶段 2 发现 4 末尾的警告）。 |
| `tempo.keys[1].amount` | 30 | 原版 20（1 = 1%）。与门槛 40 一起决定重抽周期（见上一条的算式）。两个键要一起动：只降门槛会让等待时间仍由周通道决定，只提概率则门槛不变、效果被门槛吃掉。30 是「温和档」的取值 —— 阶段 3 执行文档 §设计·节奏 给的 ≈40/≈30 一组。 |
| `memory.params[0].amount` | 1 | 变量在判据里只被 has_variable 读，值不参与任何运算；写 1 而不是 yes，是为了将来要用 change_variable 记「第几次战败」时不用换类型（原版 set_variable = { name = recently_had_war value = yes } 用的是 yes，见 00_code_on_actions.txt:7084）。 |
| `memory.params[1].amount` | 3650 | 10 年，与压力修正的 years = 10 同一时间尺度（两处必须一起改，否则会出现「记忆还在、压力已经没了」的半截状态）。对照原版给 recently_had_war 的是 days = 1825（5 年，00_code_on_actions.txt:7086）—— 战败比「打过仗」更该留得久，故取两倍。 |
| `pressure.params[0].amount` | 10 | 与 sitai_ru_defeat_memory 的 days = 3650 对齐。原版 add_modifier 用 years 的写法见 00_movement_effects.txt:1-7（add_modifier = { name = … years = 20 }）。 |
| `pressure.effects[0].amount` | -20 | **基线档 = 原版自家档位 -20**（原版同字段档位 ±5 / ±10 / ±20 / ±50，00_code_static_modifiers.txt:322-353 与 :979-1034 两处；取其中一档，不再自造介于两档之间的数）。合法性是开窗判据的一半（JE 的 possible 读 `legitimacy <= 75` —— 为什么是 75 见下面 conditions 那条的依据）。**旧实验值作废留痕（B112：不改历史读数，只补记）**：阶段 3 A/B 实测用的是**直接一击 -35**（先取 -20 跑一整局 B（15 个月）窗口一次都没开、JE 全程 0% → 提到 -35），-35 的实测水位是 b70 24 / b75 18 / b80 13（复算 `v3 ab --logs ab-run7`），即「从开局全 >80 掉到 70–80 之间来回、还会自己回升」，够不到原版那条 50 线（00_liberalism.txt:54 的「政府站得住」分界）—— 所以本档案不要求压到 50，开窗判据按实测分界取 75。那些读数保持原样，作废的是「直接一击」这个做法：同一字段现由**基线 -20（恒挂）+ 投降叠加 -15（[pressure.escalation]）**合成，合计仍是被实测过的 -35，且不再自造档位外的数。 |
| `pressure.effects[1].amount` | -0.15 | **基线档 = 原版自家档位 -0.15**（同字段 -0.15 的原版出处：cuban_modifiers.txt:40；+0.15 那一侧见 content_4_modifiers.txt:816。原版全部档位实测：±0.03（00_ip3_04_modifiers.txt:334）、±0.05（agitators_5_modifiers.txt:853）、±0.10（00_ip4_03_modifiers.txt:14）、±0.15（cuban_modifiers.txt:40）、±0.25（00_ip4_04_modifiers.txt:12 的 modifier_regency_landowners）、-0.20（agitators_4_revolution_modifiers.txt:321）、-0.50（agitators_5_modifiers.txt:615）、-0.75（content_1_modifiers.txt:1465 的 shogun_ig_forced_to_open_market，与知识界 +0.5、工业家 +0.5 成对写））。贵族失势是「战败 → 改革阻力下降」的那一环。**旧实验值作废留痕（B112：不改历史读数、只补记）**：阶段 3 A/B 用的是**直接一击 -0.30**，当时的理由是「-0.15 在一整局里没能让行为层动起来 → 取 -0.30」，而 -0.30 落在原版 -0.25 与 -0.50 之间（方向明确，又不把贵族一次打垮 —— 一次打垮会让议会算术失去张力）。现在 -0.30 由**基线 -0.15（恒挂）+ 投降叠加 -0.15（[pressure.escalation]）**合成：总量与实验段相同，但**轻档与重档分开了** —— 「只被和约逼让步」拿一档，「被逼投降」拿两档。 |
| `pressure.effects[2].amount` | 0.2 | **基线档 = 原版全局基准 0.2**：00_code_static_modifiers.txt:12 的 base_values 里 `country_loan_interest_rate_add = 0.2` —— 国家静态修正这一侧原版**没有档位阶梯**、只有这个基准，所以基线就取它。战败赔款抬高借债成本，而不是直接没收国库 —— 反目标里写着「不让 AI 获得任何数值作弊」，也不想让俄罗斯当场破产（那样测出来的差分来自破产机制，不是来自战败）。⚠️ **2026-09-23 复核更正（保留）**：原稿写「该字段原版只出现过一次」，实测 `common/` 下共 **12 处** —— 全局基准 00_code_static_modifiers.txt:12 = 0.2、法律侧 00_amendments_enactment_04.txt:644/1138/1174/1222/1266 = 0.02/0.02/0.03/0.01/0.05、科技侧 30_society.txt:209/599/1226/1473/1647 = -0.02、字段定义 00_modifier_types.txt:662。**旧实验值作废留痕（B112：不改历史读数、只补记）**：阶段 3 A/B 用的是**直接一击 0.35**（从 0.2 提到 0.35，让财政压力在几年内真的能被看见、而不是被收入增长吃掉；当时就标明 0.35 ≈ 1.75× 基准、属实验取值）；现在 0.35 由**基线 0.2 + 投降叠加 0.15（[pressure.escalation]）**合成，总量不变、来源换成真实结果。⚠️ **如实记：财政这条只能间接派生** —— 全树找不到脚本可读的「赔款」触发器（`war_reparations` 只作为外交行动 17_war_reparations.txt:1 与概念存在），所以它是从「战败事实」派生，而不是从赔款金额算出来的；相关 defines（00_defines.txt:1092 WAR_GOAL_REPARATIONS_MONTHS = 60、:1386 DEFAULT_WAR_REPARATIONS_MONEY_TRANSFER = 0.1）只能说明赔款在原版是**月度转账**，不构成可读判据。 |
| `pressure.escalation.effects[0].amount` | -15 | 叠加量 = 实测总量 -35 与基线档 -20 的差额（-15）。⚠️ 它不是 `00_code_static_modifiers.txt` 那套档位阶梯里的一档（那一套是 ±5 / ±10 / ±20 / ±50，见 :322-353 与 :979-1034），**是差额**（如实记：-15 这个取值在原版其它文件里也出现，如 00_ip4_02_modifiers.txt:303、105_modifiers.txt:621；本处取它的理由**只是差额**，不是「原版用了几档」）：这样拆的意义在于「轻档」本身落在原版档位上、而「重档」由原版记号判出来。合法性这一档在投降后 913 天内生效，之后回落到基线 -20。 |
| `pressure.escalation.effects[1].amount` | -0.15 | 叠加量 = 实测总量 -0.30 与基线档 -0.15 的差额。它与基线档同值、方向相同 ⇒ 投降后贵族政治力量合计 -0.30（阶段 3 A/B 实测过的那个总量），只被和约逼让步时是 -0.15。原版档位表见 [pressure.effects] 里那条 why。 |
| `pressure.escalation.effects[2].amount` | 0.15 | 叠加量 = 实测总量 0.35 与基线档 0.2（原版全局基准 00_code_static_modifiers.txt:12）的差额。财政这条只能**间接派生**（没有可读的赔款触发器，见基线那条 why 的末段）：重档 = 「被逼投降」这个事实 ⇒ 借债成本再抬 0.15，合计 0.35 与实验段一致。 |
| `reform_inputs.params[0].amount` | 10 | 与 [pressure.params] 的 years = 10、记忆变量的 days = 3650 三处对齐：三者在实验里是同一段时间窗，任何一处短了都会出现「输入还在、压力已经没了」的半截状态。原版 add_modifier 用 years 的写法见 00_movement_effects.txt:1-7。 |
| `reform_inputs.effects[0].amount` | 0.25 | **基线档 = 原版档位 +0.25**（同字段 +0.25 的原版出处：00_ip4_04_modifiers.txt:33；原版同字段常见档位实测为 ±0.03 / ±0.05 / ±0.10 / ±0.15 / ±0.25 / ±0.5 / ±0.75，另有单点取值 0.3：00_ip3_04_modifiers.txt:334、00_ip4_03_modifiers.txt:7、106_modifiers.txt:191、agitators_5_modifiers.txt:853、content_4_modifiers.txt:397、content_1_modifiers.txt:1467、content_204_modifiers.txt:340；取 +0.25 这一档，不再自造档位外的数）。取原版同族强档 +0.5 的那一族用法是 `shogun_ig_forced_to_open_market`（content_1_modifiers.txt:1462-1470 —— 同一处把地主 -0.75、知识界 +0.5、工业家 +0.5 一起写，正是「被外力逼着开门 → 改革侧势力抬头」那一族，与本处情形同型）。**为什么基线取 0.25 而不是 0.5**：0.5 是**重档总量**（被逼投降时由基线 +0.25 + 叠加 +0.25 得到），轻档（只被和约逼让步）拿一档 0.25。**旧实验值作废留痕（B112：不改历史读数、只补记）**：阶段 3 A/B 用的是**直接一击 +0.5**，当时的理由是「`progressive_agenda` 的权重只在 `ig:ig_industrialists ?= { is_powerful = yes }` 时 +10（03_political_strategies.txt:537-544），而 is_powerful 是**相对份额**判定 —— 同一处只抬一档常常翻不过那条线，实验要的是「输入明确到位」，不是「差一点」」；这条**读数与推理都保留**，只是「一击到位」的做法作废：重档现在仍能拿到 +0.5 总量。 |
| `reform_inputs.effects[1].amount` | 0.25 | **基线档 = 原版档位 +0.25**（同字段 +0.25 的原版出处：00_ip4_04_modifiers.txt:47；+0.15 那一档见 content_4_modifiers.txt:809、content_304_modifiers.txt:331），与工业家同档同源（content_1_modifiers.txt:1466-1467 的 shogun_ig_forced_to_open_market 把知识界 +0.5、工业家 +0.5 成对写）。`progressive_agenda` 的权重对知识界与工业家各 +10（03_political_strategies.txt:528-544），两条一起给才是原版的用法；只给一条会让「哪一条起了作用」在实验里不可分。**旧实验值作废留痕（B112：不改历史读数、只补记）**：阶段 3 A/B 用的是**直接一击 +0.5**（两条成对）；现在重档总量仍为 +0.5，由基线 +0.25（恒挂）+ 投降叠加 +0.25（[reform_inputs.escalation]）合成，轻档只拿一档。档位依据见上一条。 |
| `reform_inputs.escalation.effects[0].amount` | 0.25 | 叠加量 = 实测总量 +0.5 与基线档 +0.25 的差额。⚠️ 如实记：它不是原版档位（原版档位表见基线那条 why），**是差额** —— 基线落在原版档位上，重档由原版记号判出来。 |
| `reform_inputs.escalation.effects[1].amount` | 0.25 | 同上，与工业家成对（两个 IG 各 +0.25，重档合计各 +0.5 = 阶段 3 A/B 实测总量）。 |
| `journal_entry.fields[0].amount` | 100 | JE 列表拥挤时的保留优先级。与原版 je_corn_laws 的 weight = 100 同档（00_corn_laws.txt:79）—— 改革窗口是处境级 JE，不该被小 JE 挤掉。 |
| `journal_entry.conditions[3].amount` | 75 | 开窗的第二个条件：压力够大。**实测校准**（阶段 3 的 A/B 分档读数；**查法**：`v3 ab --logs ab-run7`，转述出处 `docs/design/exec/阶段3-结果.md`）：A 组（无冲击，`ab-A-control`）**每一个观测月都落在最高档**（探针早期的档位标签是 `vhigh`，即 >80）；B 组（-35，`ab-run7` 的 55 块分档观测）**没有一个块在 70 以下为主、且多数落在 70–75**（b70 24 / b75 18 / b80 13）—— 门槛 **75** 就落在这条实测分界上：对照组的全 >80 不会误开，而 B 组有 42/55 个月（76%）≤75。**换挂载点（已发生）**：原方案要求压到原版那条 50 线（00_liberalism.txt:54、02_peru_bolivia.txt:39），但判据仍是 50 的那一局（`ab-run3-done`，-35，61 个月）窗口从未开、法律全程 `law_serfdom`，而 -35 的水位只到 65–80 且会回升 —— 于是判据改到 75：门开在「战败后合法性确实下滑一档」这件事上，压力数值继续塑造世界。相应地 `complete` 仍是 `legitimacy >= 75`，开与关正好接上。 |
| `journal_entry.conditions[4].amount` | 75 | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 legitimacy >= 75。 |
| `cards.items[0].weight.amount` | 40 | 政治槽的等效竞争权重 S≈33（阶段 2 实测）⇒ 门开时份额 p = 40/(40+33) = **54.8%**，落在闸门 ③ 的预算区间 [0.3, 0.6] 内（上限换算 W ≤ 49）。取 40 而不取更高：给将来第二张处境牌留余量，且 60% 是闸门 ③ 的硬上限（`src/pdx/modguard.py:60`）。 |
| `difficulty.tiers.history_friendly.player_effects[0].amount` | 10 | 压力侧压的是 -35（本档案 [pressure.effects] 第一条），这里回 +10 ≈ 三成。原版同类档位：00_code_static_modifiers.txt:322 的 +10、:331 的 +5。取 +10 而不是 +20：+20 会把 -35 抵掉一半以上，玩家几乎感觉不到战败。 |
| `difficulty.tiers.history_friendly.player_effects[1].amount` | 0.15 | 压力侧压的是 -0.30，这里回 +0.15（一半）。原版同字段档位：106_modifiers.txt:205 = 0.15、00_ip4_04_modifiers.txt:47 = 0.25、00_ip3_04_modifiers.txt:334 = 0.03。取 0.15 = 把'贵族失势'从 -30% 缓到 -15%，旧势力仍在走下坡，只是没被一次打垮。 |
| `difficulty.tiers.harsh.player_effects[0].amount` | -20 | 原版同字段强档（00_code_static_modifiers.txt:353 = -20）。叠在压力侧的 -35 之上 ⇒ 玩家总共 -55；AI 仍是 -35。取 -20 而不是 -50：-50 是原版给'被外力打穿'那一档世界状态用的（content_1_modifiers.txt:17 的 opium_wars_lost），拿来当难度会盖过处境本身。 |
| `difficulty.tiers.harsh.player_effects[1].amount` | 0.25 | **方向必须是正的**：压力侧已经把贵族压到 -0.30（战败的直接后果），'无情'要的是**旧势力更不肯松手**，所以这里往回加 +0.25 —— 净效果 -0.05，贵族的钳制几乎没松，改革窗口更难推开。档位依据：00_ip4_04_modifiers.txt:47 用 +0.25（modifier_regency_landowners 那一族）。⚠️ 第一版我写成了 -0.25，那等于**继续削弱贵族**、与'无情'的语义相反 —— 数字对、方向错是最难看出来的一类错，所以这条为什么留在文件里：它记录了这个坑。 |

## 判据（JE）

| 判据块 | 判据 | 为什么 |
|---|---|---|
| `is_shown_when_inactive` | `c:RUS ?= this` | 档案是**单国**的（阶段 3 执行文档：主角俄罗斯单国）。c:AUS ?= this 是原版写法（05_metternich.txt:8），问号的语义是「作用域存在才比」，比裸 = 稳。 |
| `is_shown_when_inactive` | `has_variable = sitai_ru_defeat_memory` | 没被记过战败的国家连这条 JE 都不该看见 —— 「和平期占槽率 ≈ 0」这条出口判据靠它：不施加冲击的局里，这行判据为假，整条 JE 不出现。 |
| `possible` | `has_variable = sitai_ru_defeat_memory` | 开窗的第一个条件：确实战败过。is_shown 与 possible 都写一遍是有意的 —— 前者管「看不看得见」，后者管「开不开」，原版 je_corn_laws 也是两处各写一套（00_corn_laws.txt:6-31）。 |
| `possible` | `legitimacy <= 75` | 开窗的第二个条件：压力够大。**实测校准**（阶段 3 的 A/B 分档读数；**查法**：`v3 ab --logs ab-run7`，转述出处 `docs/design/exec/阶段3-结果.md`）：A 组（无冲击，`ab-A-control`）**每一个观测月都落在最高档**（探针早期的档位标签是 `vhigh`，即 >80）；B 组（-35，`ab-run7` 的 55 块分档观测）**没有一个块在 70 以下为主、且多数落在 70–75**（b70 24 / b75 18 / b80 13）—— 门槛 **75** 就落在这条实测分界上：对照组的全 >80 不会误开，而 B 组有 42/55 个月（76%）≤75。**换挂载点（已发生）**：原方案要求压到原版那条 50 线（00_liberalism.txt:54、02_peru_bolivia.txt:39），但判据仍是 50 的那一局（`ab-run3-done`，-35，61 个月）窗口从未开、法律全程 `law_serfdom`，而 -35 的水位只到 65–80 且会回升 —— 于是判据改到 75：门开在「战败后合法性确实下滑一档」这件事上，压力数值继续塑造世界。相应地 `complete` 仍是 `legitimacy >= 75`，开与关正好接上。 |
| `complete` | `legitimacy >= 75` | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 legitimacy >= 75。 |

## 面板三行（P11 / G3）

| 行 | 本地化键 | 为什么是这一行 |
|---|---|---|
| goal | `（不单独发键；并进 je_sitai_ru_reform_window_reason）` | 第一行 = **当前目标**。写「推过去」而不是「废除农奴制」：改哪条法由 AI 与原版牌池决定，本档案不替它选（§0「让 AI 自己推导」）；写「旧势力拦着的那项」是让玩家知道它为什么一直没动。 |
| pressure | `je_sitai_ru_reform_window_pressure` | 第二行 = **最大压力与阻力**。压力项与 `[pressure.effects]` 的三条字段一一对应（贵族 / 合法性 / 利率），阻力项与 `complete = { legitimacy >= 75 }` 是同一条判据的两种说法 —— 数值改了这行也要改（P9：改一处、三处同步）。 |
| last_change | `je_sitai_ru_reform_window_last_change` | 第三行 = **上次改主意的原因**。这一行是 G3 里最容易被跳过、却最关键的一行：没有它，玩家只能看到「它在改革」，看不到「**为什么是现在**」。写「被记进了账」是让因果链读得出来（§0.1 派生义务：目标函数表要显式、可审）。 |

> 为什么拆成三个键而不是揉进 `_reason`：G3 判的是**试玩者能复述**「当前目标 + 主因」，揉在一起就分不清是哪一行没写清楚。缺行当场可见。

## 声明式引用（闸门 ② 逐条核对）

| 类别 | 名字 | 为什么 |
|---|---|---|
| `trigger` | `legitimacy` | JE 的开窗/关窗判据（`legitimacy <= 75` / `>= 75`）。原版用法：00_meiji_restoration.txt:314、04_sikh_empire.txt:20。 |
| `trigger` | `has_variable` | 记忆变量的读法。原版用法：00_corn_laws.txt:7 等 795 处（**范围 = `common/journal_entries/**`**，即该例所在目录；`v3 evidence has_variable` 现读全树 6383 处。阶段 1 统计读它的牌 = 13 张，规则与现读见生成物 `docs/design/02-可执行面.md`）。 |
| `effect` | `set_variable` | 写记忆变量。原版用法：00_code_on_actions.txt:7084（on_war_end 给 recently_had_war 记 5 年）。 |
| `effect` | `add_modifier` | 把静态修正挂到国家上。原版用法：00_movement_effects.txt:2（add_modifier = { name = … years = 20 }）。 |
| `country_tag` | `RUS` | JE 的单国门（c:RUS ?= this）。原版用法：country_definitions 里的 RUS。 |
| `trigger` | `on_capitulation` | 路径①的挂载点：原版 on_action 名（`common/on_actions/00_code_on_actions.txt:4214`，Root = 投降国本身）。⚠️ 名字在池里 ≠ 接线正确：`common/on_actions` **不在反解表**里（src/pdx/modgen.py 的 `_FACT_READERS` 只有七类），这份产物的正确性由 tests/test_modgen.py 的用例看守（缺口如实记在报告里）。 |
| `trigger` | `on_wargoal_enforced` | 路径②的挂载点：原版 on_action 名（`common/on_actions/00_code_on_actions.txt:6288`；`:6259` scope:target = 被强制执行的一方、`:6298` 给 root（赢家）写 recently_won_war）。池子与缺口同上一条。 |
| `trigger` | `on_actions` | 我们给原版钩子**追加的字段名**（不是 effect 块）：官方口径 research/official-docs/game/common/on_actions/_on_actions.md:115 写明不能给已有 effect 块的 on_action 再追加 effect 块，`:117-128` 给的就是这个字段；原版自己也用它（00_code_on_actions.txt:125 等 11 处），所以它在词汇表池里、闸门 ② 能核。 |
| `modifier_field` | `country_legitimacy_base_add` | 合法性修正字段。原版 `common/static_modifiers/**` 下 157 处（`common/**` 全树 173 处），档位 ±5 / ±10 / ±20 / ±50（00_code_static_modifiers.txt:322-353 等）。 |
| `modifier_field` | `interest_group_ig_landowners_pol_str_mult` | 贵族政治力量。原版 `common/static_modifiers/**` 下 26 处（全树 41 处）：+0.03（4 处，00_ip3_04_modifiers.txt:334、:341、:349、:357；该字段没有 -0.03）、-0.75（content_1_modifiers.txt:1465 幕府被迫开国）。 |
| `modifier_field` | `country_loan_interest_rate_add` | 借债利率。原版**国家修正那一侧**（`common/static_modifiers/**`）实测只有一处：00_code_static_modifiers.txt:12 的 `base_values` 全局基准 +0.2（是全局基准的一部分，不是某个事件修正的档位）；**范围之外另算**：`common/**` 全树 **12 处**（含 `modifier_type_definitions` 定义行）/ **11 处**（不含）—— 口径与查法见 `mod/data/cn_intervention.toml:289`。 |
| `modifier_field` | `interest_group_ig_industrialists_pol_str_mult` | 工业家政治力量。原版 `common/static_modifiers/**` 下 16 处（全树 26 处）：0.1（00_ip4_03_modifiers.txt:7）、0.25（00_ip4_04_modifiers.txt:33）、0.5（content_1_modifiers.txt:1467）。 |
| `modifier_field` | `interest_group_ig_intelligentsia_pol_str_mult` | 知识界政治力量。原版 `common/static_modifiers/**` 下 17 处（全树 21 处）：0.15（106_modifiers.txt:205）、0.25（00_ip4_04_modifiers.txt:47）、0.5（content_1_modifiers.txt:1466）。 |

## 复算

```text
v3 modgen --write     # 数据源 → 产物（改完 TOML 必跑）
v3 modguard           # 五道闸门（不通过不许进游戏）
v3 modgen --why       # 只列每个数字与它的依据
```
