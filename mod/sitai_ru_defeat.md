# 档案 · 俄罗斯 · 战败求存

> ⚠️ 本文件由 `v3 modgen` 生成 —— 改这里没用，改数据源 `mod/data/*.toml`。

* **档案 id**：`ru_defeat`　**国家**：`RUS`　**游戏版本**：`1.14.3`
* **本档案修什么毛病**：战败之后 AI 照旧走原来的路 —— 贵族照旧在朝、合法性不塌、财政不受罚，于是「战败 → 改革」这条因果在原版里根本不存在。档案不替 AI 决定改什么，只把战败记成账、把压力落成真实的合法性/贵族/财政变化。⚠️ 依据已于 2026-09-22 更正：原版 AI 策略里 212 处 has_journal_entry 全部硬编码**具名** JE，没有「读任意 JE」的通用谓词 ⇒ 我们自己的 JE 一张原版牌也喂不到（backlog B52）；真正把压力变成意图位移的通道是递牌（set_strategy，B58）与法律承诺（law commitment，B56/B57）。
* **递牌**：0 张 —— 本档案**刻意为空**（F5：能用 A 级表达的绝不占槽）。战败 → 压力的链路已经由变量 + 修正 + JE 表达完，而 JE 会被原版那 18 张读 has_journal_entry 的牌读到 —— 意图位移由原版自己的牌池产生，不需要我们再占一个槽。递牌是「整条路线要换」时才用的手段（C 级，政治槽 S≈33：权重 10 就吃掉 23% 的份额，阶段 2 价格表）。要加牌时写 [[cards.items]]（字段见 modgen 的 card_text 与闸门 ③）。

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
| `memory.params[0].amount` | 1 | 变量在判据里只被 has_variable 读，值不参与任何运算；写 1 而不是 yes，是为了将来要用 change_variable 记「第几次战败」时不用换类型（原版 set_variable = { name = recently_had_war value = yes } 用的是 yes，见 00_code_on_actions.txt:7046）。 |
| `memory.params[1].amount` | 3650 | 10 年，与压力修正的 years = 10 同一时间尺度（两处必须一起改，否则会出现「记忆还在、压力已经没了」的半截状态）。对照原版给 recently_had_war 的是 days = 1825（5 年，00_code_on_actions.txt:7048）—— 战败比「打过仗」更该留得久，故取两倍。 |
| `pressure.params[0].amount` | 10 | 与 sitai_ru_defeat_memory 的 days = 3650 对齐。原版 add_modifier 用 years 的写法见 00_movement_effects.txt:1-7（add_modifier = { name = … years = 20 }）。 |
| `pressure.effects[0].amount` | -35 | 合法性是开窗判据的一半（JE 的 possible 读 `legitimacy <= 75` —— 为什么是 75 见下面 conditions 那条的依据）。**实测调档**：先取 -20 跑了一整局 B（15 个月），窗口一次都没开（JE 全程 0%）→ 提到 -35。**-35 的实测水位**（复算：`v3 ab --logs ab-run7`，B 段 55 块合法性分档）：b70 24 / b75 18 / b80 13 —— 也就是「从开局的全 >80 掉到 70–80 之间来回，还会自己回升」，**够不到原版那条 50 线**（00_liberalism.txt:54 的「政府站得住」分界）。所以本档案**不再要求压到 50**，开窗判据按实测分界取 75；换挂载点的来由与读数写在 conditions 那条 why 里。取 -35 不是因为它能压到 50，而是它把水位稳定压出一档、又不让政府一次失能：原版同字段的档位是 ±5 / ±10 / ±20 / ±50（00_code_static_modifiers.txt:322-353 一连串），-35 落在 -20 与 -50 之间。 |
| `pressure.effects[1].amount` | -0.3 | **实测调档**：-0.15 在一整局里没能让行为层动起来 → 取 -0.30。贵族失势是「战败 → 改革阻力下降」的那一环。原版同字段的档位实测为 ±0.03（00_ip3_04_modifiers.txt:334）、±0.10（00_ip4_03_modifiers.txt:14）、±0.25（00_ip4_04_modifiers.txt:12 的 modifier_regency_landowners）、-0.20（agitators_4_revolution_modifiers.txt:321）、-0.50（agitators_5_modifiers.txt:615）、-0.75（content_1_modifiers.txt:1465 的 shogun_ig_forced_to_open_market，与知识界 +0.5、工业家 +0.5 成对写）。取 -0.30 = 落在原版 -0.25 与 -0.50 之间：方向明确（贵族政治力量 -30%），又不把贵族一次打垮 —— 一次打垮会让议会算术失去张力。 |
| `pressure.effects[2].amount` | 0.35 | **实测调档**：从 0.2 提到 0.35，让财政压力在几年内真的能被看见，而不是被收入增长吃掉。⚠️ 原版该字段**只出现过一次**（00_code_static_modifiers.txt:12 的 `base_values` 全局基准 +0.2），**没有可引的档位阶梯** —— 所以 0.35 ≈ 1.75× 基准属于**实验取值**（不是原版档位），正式版要按真实赔款机制重算（backlog B35）。战败赔款抬高借债成本，而不是直接没收国库 —— 反目标里写着「不让 AI 获得任何数值作弊」，也不想让俄罗斯当场破产（那样测出来的差分来自破产机制，不是来自战败）。 |
| `reform_inputs.params[0].amount` | 10 | 与 [pressure.params] 的 years = 10、记忆变量的 days = 3650 三处对齐：三者在实验里是同一段时间窗，任何一处短了都会出现「输入还在、压力已经没了」的半截状态。原版 add_modifier 用 years 的写法见 00_movement_effects.txt:1-7。 |
| `reform_inputs.effects[0].amount` | 0.5 | 取原版同族强档 +0.5：`shogun_ig_forced_to_open_market`（content_1_modifiers.txt:1462-1470）在同一处把地主 -0.75、知识界 +0.5、工业家 +0.5 一起写 —— 那正是「被外力逼着开门 → 改革侧势力抬头」这一族用法，与本处要表达的情形同型。原版全部档位实测为 ±0.03 / ±0.05 / ±0.10 / ±0.15 / ±0.25 / ±0.5 / ±0.75（00_ip3_04_modifiers.txt:334、00_ip4_03_modifiers.txt:7、106_modifiers.txt:191、00_ip4_04_modifiers.txt:33、content_204_modifiers.txt:340）。取 0.5 而不是 0.15：`progressive_agenda` 的权重只在 `ig:ig_industrialists ?= { is_powerful = yes }` 时 +10（03_political_strategies.txt:537-544），而 is_powerful 是**相对份额**判定 —— 同一处只抬一档常常翻不过那条线，实验要的是「输入明确到位」，不是「差一点」。 |
| `reform_inputs.effects[1].amount` | 0.5 | 与工业家同档同源（content_1_modifiers.txt:1466 的 shogun_ig_forced_to_open_market 里这两条就是成对写的）。`progressive_agenda` 的权重对知识界与工业家各 +10（03_political_strategies.txt:528-544），两条一起给才是原版的用法；只给一条会让「哪一条起了作用」在实验里不可分。档位依据见上一条。 |
| `journal_entry.fields[0].amount` | 100 | JE 列表拥挤时的保留优先级。与原版 je_corn_laws 的 weight = 100 同档（00_corn_laws.txt:79）—— 改革窗口是处境级 JE，不该被小 JE 挤掉。 |
| `journal_entry.conditions[3].amount` | 75 | 开窗的第二个条件：压力够大。**实测校准**（阶段 3 的 A/B 分档读数）：A 组（无冲击，`ab-A-control`）**每一个观测月都落在最高档**（探针早期的档位标签是 `vhigh`，即 >80）；B 组（-35，`ab-run7` 的 55 块分档观测）**没有一个块在 70 以下为主、且多数落在 70–75**（b70 24 / b75 18 / b80 13）—— 门槛 **75** 就落在这条实测分界上：对照组的全 >80 不会误开，而 B 组有 42/55 个月（76%）≤75。**换挂载点（已发生）**：原方案要求压到原版那条 50 线（00_liberalism.txt:54、02_peru_bolivia.txt:39），但判据仍是 50 的那一局（`ab-run3-done`，-35，61 个月）窗口从未开、法律全程 `law_serfdom`，而 -35 的水位只到 65–80 且会回升 —— 于是判据改到 75：门开在「战败后合法性确实下滑一档」这件事上，压力数值继续塑造世界。相应地 `complete` 仍是 `legitimacy >= 75`，开与关正好接上。 |
| `journal_entry.conditions[4].amount` | 75 | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 legitimacy >= 75。 |

## 判据（JE）

| 判据块 | 判据 | 为什么 |
|---|---|---|
| `is_shown_when_inactive` | `c:RUS ?= this` | 档案是**单国**的（阶段 3 执行文档：主角俄罗斯单国）。c:AUS ?= this 是原版写法（05_metternich.txt:8），问号的语义是「作用域存在才比」，比裸 = 稳。 |
| `is_shown_when_inactive` | `has_variable = sitai_ru_defeat_memory` | 没被记过战败的国家连这条 JE 都不该看见 —— 「和平期占槽率 ≈ 0」这条出口判据靠它：不施加冲击的局里，这行判据为假，整条 JE 不出现。 |
| `possible` | `has_variable = sitai_ru_defeat_memory` | 开窗的第一个条件：确实战败过。is_shown 与 possible 都写一遍是有意的 —— 前者管「看不看得见」，后者管「开不开」，原版 je_corn_laws 也是两处各写一套（00_corn_laws.txt:6-31）。 |
| `possible` | `legitimacy <= 75` | 开窗的第二个条件：压力够大。**实测校准**（阶段 3 的 A/B 分档读数）：A 组（无冲击，`ab-A-control`）**每一个观测月都落在最高档**（探针早期的档位标签是 `vhigh`，即 >80）；B 组（-35，`ab-run7` 的 55 块分档观测）**没有一个块在 70 以下为主、且多数落在 70–75**（b70 24 / b75 18 / b80 13）—— 门槛 **75** 就落在这条实测分界上：对照组的全 >80 不会误开，而 B 组有 42/55 个月（76%）≤75。**换挂载点（已发生）**：原方案要求压到原版那条 50 线（00_liberalism.txt:54、02_peru_bolivia.txt:39），但判据仍是 50 的那一局（`ab-run3-done`，-35，61 个月）窗口从未开、法律全程 `law_serfdom`，而 -35 的水位只到 65–80 且会回升 —— 于是判据改到 75：门开在「战败后合法性确实下滑一档」这件事上，压力数值继续塑造世界。相应地 `complete` 仍是 `legitimacy >= 75`，开与关正好接上。 |
| `complete` | `legitimacy >= 75` | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 legitimacy >= 75。 |

## 声明式引用（闸门 ② 逐条核对）

| 类别 | 名字 | 为什么 |
|---|---|---|
| `trigger` | `legitimacy` | JE 的开窗/关窗判据（`legitimacy <= 75` / `>= 75`）。原版用法：00_meiji_restoration.txt:314、00_sikh_empire.txt:20。 |
| `trigger` | `has_variable` | 记忆变量的读法。原版用法：00_corn_laws.txt:7 等 795 处（阶段 1 统计 has_variable 被 13 张牌直接读）。 |
| `effect` | `set_variable` | 写记忆变量。原版用法：00_code_on_actions.txt:7046（on_war_end 给 recently_had_war 记 5 年）。 |
| `effect` | `add_modifier` | 把静态修正挂到国家上。原版用法：00_movement_effects.txt:2（add_modifier = { name = … years = 20 }）。 |
| `country_tag` | `RUS` | JE 的单国门（c:RUS ?= this）。原版用法：country_definitions 里的 RUS。 |
| `modifier_field` | `country_legitimacy_base_add` | 合法性修正字段。原版 157 处，档位 ±5 / ±10 / ±20 / ±50（00_code_static_modifiers.txt:322-353 等）。 |
| `modifier_field` | `interest_group_ig_landowners_pol_str_mult` | 贵族政治力量。原版 26 处：±0.03（00_ip3_04_modifiers.txt:334）、-0.75（content_1_modifiers.txt:1465 幕府被迫开国）。 |
| `modifier_field` | `country_loan_interest_rate_add` | 借债利率。原版只有一处：00_code_static_modifiers.txt:12 的 `base_values` 全局基准 +0.2（是全局基准的一部分，不是某个事件修正的档位）。 |
| `modifier_field` | `interest_group_ig_industrialists_pol_str_mult` | 工业家政治力量。原版 16 处：0.1（00_ip4_03_modifiers.txt:7）、0.25（00_ip4_04_modifiers.txt:33）、0.5（content_1_modifiers.txt:1467）。 |
| `modifier_field` | `interest_group_ig_intelligentsia_pol_str_mult` | 知识界政治力量。原版 17 处：0.15（106_modifiers.txt:205）、0.25（00_ip4_04_modifiers.txt:47）、0.5（content_1_modifiers.txt:1466）。 |

## 复算

```text
v3 modgen --write     # 数据源 → 产物（改完 TOML 必跑）
v3 modguard           # 五道闸门（不通过不许进游戏）
v3 modgen --why       # 只列每个数字与它的依据
```
