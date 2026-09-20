# 档案 · 俄罗斯 · 战败求存

> ⚠️ 本文件由 `v3 modgen` 生成 —— 改这里没用，改数据源 `mod/data/*.toml`。

* **档案 id**：`ru_defeat`　**国家**：`RUS`　**游戏版本**：`1.14.3`
* **本档案修什么毛病**：战败之后 AI 照旧走原来的路 —— 贵族照旧在朝、合法性不塌、财政不受罚，于是「战败 → 改革」这条因果在原版里根本不存在。档案不替 AI 决定改什么，只把战败记成账、把压力落成真实的合法性/贵族/财政变化，剩下的交给原版已经挂着的那 18 张读 has_journal_entry 的牌。
* **递牌**：0 张 —— 本档案**刻意为空**（F5：能用 A 级表达的绝不占槽）。战败 → 压力的链路已经由变量 + 修正 + JE 表达完，而 JE 会被原版那 18 张读 has_journal_entry 的牌读到 —— 意图位移由原版自己的牌池产生，不需要我们再占一个槽。递牌是「整条路线要换」时才用的手段（C 级，政治槽 S≈33：权重 10 就吃掉 23% 的份额，阶段 2 价格表）。要加牌时写 [[cards.items]]（字段见 modgen 的 card_text 与闸门 ③）。

## 产物清单

| 文件 | 作用 |
|---|---|
| `common/scripted_effects/sitai_ru_defeat_effects.txt` | 冲击记账效果（写 `sitai_ru_defeat_memory` + 挂 `sitai_ru_defeat_pressure`） |
| `common/static_modifiers/sitai_ru_defeat_pressure.txt` | 压力修正（真实的合法性 / 贵族 / 财政变化） |
| `common/journal_entries/sitai_ru_defeat_window.txt` | 改革窗口 JE（判据驱动） |
| `common/defines/sitai_ru_defeat_tempo.txt` | 节奏杠杆（覆盖 `NAI` 块） |
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
| `pressure.effects[0].amount` | -20 | 合法性下降是改革窗口的开窗判据（JE 的 possible 读 legitimacy <= 50）。原版同字段的档位是 ±5 / ±10 / ±20 / ±50（00_code_static_modifiers.txt:322-353 一连串），取 -20 = 塌一档：俄罗斯开局合法性多在 60–80，-20 足以把多数局面推过 50 那条线，又不至于让政府立刻失去执政能力。 |
| `pressure.effects[1].amount` | -0.15 | 贵族失势 —— 这是「战败 → 改革阻力下降」的那一环。原版同字段的档位：±0.03（00_ip3_04_modifiers.txt:334）、±0.10、±0.25（00_ip4_04_modifiers.txt:12 的 modifier_regency_landowners）。取 -0.15 落在中档：方向明确（贵族政治力量 -15%），又不把贵族一次打垮 —— 一次打垮会让议会算术失去张力。 |
| `pressure.effects[2].amount` | 0.2 | 财政恶化取原版最小的正档：00_code_static_modifiers.txt:12 就是 +0.2。战败赔款抬高借债成本，而不是直接没收国库 —— 反目标里写着「不让 AI 获得任何数值作弊」，也不想让俄罗斯当场破产（那样测出来的差分来自破产机制，不是来自战败）。 |
| `journal_entry.fields[0].amount` | 100 | JE 列表拥挤时的保留优先级。与原版 je_corn_laws 的 weight = 100 同档（00_corn_laws.txt:79）—— 改革窗口是处境级 JE，不该被小 JE 挤掉。 |
| `journal_entry.conditions[3].amount` | 50 | 开窗的第二个条件：压力够大。50 是原版反复出现的合法性分界（00_liberalism.txt:54、02_peru_bolivia.txt:39 都用 government_legitimacy >= 50 表示「政府站得住」）。与 -20 的合法性修正配对：战败后多数局面会落到线下，窗口由此打开。 |
| `journal_entry.conditions[4].amount` | 75 | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 legitimacy >= 75。 |

## 判据（JE）

| 判据块 | 判据 | 为什么 |
|---|---|---|
| `is_shown_when_inactive` | `c:RUS ?= this` | 档案是**单国**的（阶段 3 执行文档：主角俄罗斯单国）。c:AUS ?= this 是原版写法（05_metternich.txt:8），问号的语义是「作用域存在才比」，比裸 = 稳。 |
| `is_shown_when_inactive` | `has_variable = sitai_ru_defeat_memory` | 没被记过战败的国家连这条 JE 都不该看见 —— 「和平期占槽率 ≈ 0」这条出口判据靠它：不施加冲击的局里，这行判据为假，整条 JE 不出现。 |
| `possible` | `has_variable = sitai_ru_defeat_memory` | 开窗的第一个条件：确实战败过。is_shown 与 possible 都写一遍是有意的 —— 前者管「看不看得见」，后者管「开不开」，原版 je_corn_laws 也是两处各写一套（00_corn_laws.txt:6-31）。 |
| `possible` | `legitimacy <= 50` | 开窗的第二个条件：压力够大。50 是原版反复出现的合法性分界（00_liberalism.txt:54、02_peru_bolivia.txt:39 都用 government_legitimacy >= 50 表示「政府站得住」）。与 -20 的合法性修正配对：战败后多数局面会落到线下，窗口由此打开。 |
| `complete` | `legitimacy >= 75` | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 legitimacy >= 75。 |

## 声明式引用（闸门 ② 逐条核对）

| 类别 | 名字 | 为什么 |
|---|---|---|
| `trigger` | `legitimacy` | JE 的开窗/关窗判据（legitimacy <= 50 / >= 75）。原版用法：00_meiji_restoration.txt:314、00_sikh_empire.txt:20。 |
| `trigger` | `has_variable` | 记忆变量的读法。原版用法：00_corn_laws.txt:7 等 795 处（阶段 1 统计 has_variable 被 13 张牌直接读）。 |
| `effect` | `set_variable` | 写记忆变量。原版用法：00_code_on_actions.txt:7046（on_war_end 给 recently_had_war 记 5 年）。 |
| `effect` | `add_modifier` | 把静态修正挂到国家上。原版用法：00_movement_effects.txt:2（add_modifier = { name = … years = 20 }）。 |
| `country_tag` | `RUS` | JE 的单国门（c:RUS ?= this）。原版用法：country_definitions 里的 RUS。 |

## 复算

```text
v3 modgen --write     # 数据源 → 产物（改完 TOML 必跑）
v3 modguard           # 五道闸门（不通过不许进游戏）
v3 modgen --why       # 只列每个数字与它的依据
```
