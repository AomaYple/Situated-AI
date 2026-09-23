# 档案 · 大清 · 列强干涉

> ⚠️ 本文件由 `v3 modgen` 生成 —— 改这里没用，改数据源 `mod/data/*.toml`。

* **档案 id**：`cn_intervention`　**国家**：`CHI`　**游戏版本**：`1.14.4`
* **本档案修什么毛病**：**修的是什么毛病**：原版 1.14.3 里「被列强打穿」这件事**已经有原版自己的账**（`opium_wars_lost`：合法性 -50、生活水平 -2、军事 -33%，content_1_modifiers.txt:15-26），但那本账只记在**战败那一刻**，而且原版对大清只有两条反应通道 —— 要么走 `je_warlord_china` 的军阀裂解（00_warlord_china.txt:1），要么走 `je_chinese_missions` 的传教渗透与排教冲突（00_taiping.txt:1 那个块的块名其实是 `je_chinese_missions`，同文件里的 `je_taiping` 块在 :242）。**「被外力逼着开门 → 改革派被托起来」这条因果在原版里不存在**：士绅与旧官僚照旧在朝、科举与八股照旧，于是玩家看到的是一个**挨了打却不会变**的大清。本档案不替 AI 决定改什么，只把干涉记成账、把压力落成真实的合法性 / 保守侧 / 财政变化，让原版自己那张**读改革派 IG 的**权重公式（`ai_strategy_progressive_agenda`，03_political_strategies.txt:528-544）自己转向。⚠️ 依据已于 2026-09-22 更正：原版 AI 策略里 212 处 has_journal_entry 全部硬编码**具名** JE，没有「读任意 JE」的通用谓词 ⇒ 我们自己的 JE 一张原版牌也喂不到（backlog B52）；真正把压力变成意图位移的通道是递牌（set_strategy，B58）与法律承诺（law commitment，B56/B57）。本档案一张牌都不递（见 `[cards]`）。　【沿用·口径】本表的数值与依据**原样沿用** `ru_defeat.toml` 的实测档位（阶段 3 的 A/B 读数），**未针对本条处境独立校准**；它是「加一处境 = 加一份数据源」（G-EXIT-1）在**另一种失败模式**上的证明件，不是一份经过校准的档案设计。
* **递牌**：0 张 —— 本档案**不使用自建策略牌**（F5：能改世界就不占槽）。列强干涉 → 压力的链路由变量 + 修正 + JE 表达；⚠️ 依据已于 2026-09-22 更正：JE **不会**被原版牌读到（原版 212 处 has_journal_entry 全硬编码具名 JE，没有通用谓词，backlog B52），所以意图位移**不能**指望「开一个 JE 就被牌池读到」。要真的换路线，用（a）递**原版**的牌 `set_strategy`（B58）或（b）法律承诺 law commitment（B56/B57）—— 两者都是「整条路线要换」时的手段。递牌的政治槽价格：S≈33 时权重 10 吃掉 23% 的份额（阶段 2 价格表）。**本档案为什么不递**：有判据可写的递牌法是「窗口开时递进步牌、窗口关时递回反动牌」（ru_defeat 的 `[journal_entry.signals]` 就是这么写的），但那一条的落点依据是**俄国 1836 年的初始牌**（common/history/ai/00_strategy.txt:90 的 set_strategy = ai_strategy_reactionary_agenda）—— 大清的初始牌不是那一张，照抄会把大清递到一个它从没站过的路线上，那就不是「让 AI 自己推导」，是我们替它选。写这张表的判据需要先实测大清 1836 的初始牌与重抽落点（阶段 5 的 A/B 会话），在那之前**一张都不递**比递一张编的牌诚实。

## 产物清单

| 文件 | 作用 |
|---|---|
| `common/scripted_effects/sitai_cn_intervention_effects.txt` | 冲击记账效果（写 `sitai_cn_intervention_memory` + 挂 `sitai_cn_intervention_pressure`） |
| `common/static_modifiers/sitai_cn_intervention_pressure.txt` | 压力修正（真实的合法性 / 贵族 / 财政变化） |
| `common/journal_entries/sitai_cn_intervention_window.txt` | 改革窗口 JE（判据驱动） |
| —— | 本档案不声明 `[tempo]`（全仓一份的 mod 级表，由另一份数据源声明） |
| `common/static_modifiers/sitai_cn_intervention_reform_inputs.txt` | 改革侧输入修正（第二处理段 B2 才挂；`sitai_cn_reform_input` 施加） |
| `localization/english/sitai_cn_intervention_l_english.yml` | english 文案 |
| `localization/simp_chinese/sitai_cn_intervention_l_simp_chinese.yml` | simp_chinese 文案 |
| `.metadata/metadata.json` | mod 元数据（启动器读；不带 BOM） |

## 每个数字与它的依据（P10）

| 位置 | 数值 | 依据 |
|---|---:|---|
| `memory.params[0].amount` | 1 | 变量在判据里只被 has_variable 读，值不参与任何运算；写 1 而不是 yes，是为了将来要用 change_variable 记「第几次被干涉」时不用换类型（原版 set_variable = { name = recently_had_war value = yes } 用的是 yes，见 00_code_on_actions.txt:7046）。　【沿用·口径】沿用 ru_defeat 的取值，未针对本条处境独立校准。 |
| `memory.params[1].amount` | 3650 | 10 年，与压力修正的 years = 10 同一时间尺度（两处必须一起改，否则会出现「记忆还在、压力已经没了」的半截状态）。**这个尺度在大清身上有原版先例**：原版 `je_opium_wars`（鸦片战争，就是「外力打穿大清」那条 JE）的 timeout 正是 3650（00_opium_wars.txt:187）—— 原版给「被外力打开之后」的时间窗就是这个数，而 19 世纪的不平等条约本身就是以十年计的长期抽血，不是一次赔款。⚠️ **本条 why 更正过一次**：初稿写的是「`je_taiping` 的 timeout 是 3650」，复核时发现 `je_taiping` 块（00_taiping.txt:242）**根本没有 timeout 字段**，3650 出自 `je_opium_wars`；已改为引真源。对照原版给 recently_had_war 的是 days = 1825（5 年，00_code_on_actions.txt:7048）。　【沿用·口径】天数沿用 ru_defeat 的 3650（该值在其 why 里写作「战败比打过仗更该留得久，故取两倍」）；本处境换了一条**更贴题**的原版先例（鸦片战争 JE 的同一个数）来支撑它，**未独立校准**。 |
| `pressure.params[0].amount` | 10 | 与 sitai_cn_intervention_memory 的 days = 3650 对齐。原版 add_modifier 用 years 的写法见 00_movement_effects.txt:1-7（add_modifier = { name = … years = 20 }）。　【沿用·口径】沿用 ru_defeat 的取值，未针对本条处境独立校准。 |
| `pressure.effects[0].amount` | -35 | 合法性是开窗判据的一半（JE 的 possible 读 `legitimacy <= 75` —— 为什么是 75 见下面 conditions 那条的依据）。**原版对大清「被外力打穿」这一件事的真实记账就在同一个字段上，而且是重档**：`opium_wars_lost` 给 `country_legitimacy_base_add = -50`（content_1_modifiers.txt:17，同族还有 `country_legitimacy_headofstate_add = -50`，见原版「被迫开国」那条 content_1_modifiers.txt:1468）—— 所以「干涉 → 合法性受损」这个**方向**在原版里是被承认的，不是我们发明的。**档位取 -35 而不是原版大清的 -50**：-35 是 ru_defeat 在阶段 3 里**实测调过档**的值（先取 -20 一整局 B 组窗口一次没开 → 提到 -35；`ab-run7` 的 55 块分档读数 b70 24 / b75 18 / b80 13），也就是「把水位稳定压出一档、又不让政府一次失能」的那一档；原版同字段的档位阶梯是 ±5 / ±10 / ±20 / ±50（00_code_static_modifiers.txt:322-353 一连串），-35 正好落在 -20 与 -50 之间。取 -50 会让大清一挨打就掉进原版那条 50 线以下（00_liberalism.txt:54 的 `government_legitimacy >= 50`），测出来的差分就会来自「政府失能」这个机制，而不是来自「干涉」本身。　【沿用·口径】**数值沿用 ru_defeat 的实测档位（-35），未针对本条处境独立校准**；本处境另外引了一条原版同字段（-50）证明方向成立。 |
| `pressure.effects[1].amount` | -0.3 | **这一条是本档案唯一换了字段的地方，也是它与「战败」最本质的差别**。ru/tr 减的是 `interest_group_ig_landowners_pol_str_mult`（贵族），但大清的守旧侧不是地主贵族，是**士绅与旧官僚**——他们靠科举与礼教站住，原版对应的是 **devout**（教会 / 士绅与旧官僚那一侧）。所以字段换成 devout，**档位仍对齐 ru_defeat 的地主档 -0.30**：原版同字段的档位实测为 +0.25（00_ip4_04_modifiers.txt:19、:241、:442）、+0.15（106_modifiers.txt:224、content_4_modifiers.txt:796）、-0.25（00_ip4_04_modifiers.txt:141，注释 `# Selling church lands` —— 变卖庙产即「旧势力失势」，与本处同型）、-0.50（agitators_5_modifiers.txt:616，与地主 -0.50、工业家 -0.50 成对写）、-0.80（brazil_2_modifiers.txt:149）；法律侧同样用它做档位（00_church_and_state.txt:547 的 -0.5、00_governance_principles.txt:717 的 +0.25）。取 -0.30 = 落在原版 -0.25 与 -0.50 之间：方向明确（士绅与旧官僚政治力量 -30%），又不把守旧侧一次打垮 —— 一次打垮会让议会算术失去张力。**为什么改的是这一侧而不是把改革侧直接抬上去**：守旧侧失势才是「外力把改革派托起来」的中间环节，改革侧的输入由 `[reform_inputs]` 单独一张表承担（那张表在阶段 3 的 A/B 里是可以**分开施加**的第二处理段）。　【沿用·口径】**档位沿用 ru_defeat 的实测档位（-0.30），未针对本条处境独立校准**；换字段的依据是原版同族用法（上面那一串行号），不是实测。 |
| `pressure.effects[2].amount` | 0.35 | **为什么大清的压力里有财政这一条**：列强干涉落到实处的形式不是「割一块地就完了」，是**赔款 + 协定关税**——赔款要借债，协定关税把还债能力也一起锁住，于是借债成本长期抬高。原版 `opium_wars_lost` 也是这么记的（content_1_modifiers.txt:15-26：生活水平 -2、政治运动激进 -0.5 忠诚、军事 -33%），只是它没有动利率字段。⚠️ 原版该字段**没有可引的「国家修正档位阶梯」**：它出现在原版 10 处，其中 6 处是条约修正里 ±0.01 / ±0.02 / ±0.03 / ±0.05（00_amendments_enactment_04.txt:644、:1138、:1174、:1222、:1266），5 处是科技里 -0.02（30_society.txt:209、:599、:1226、:1473、:1647），剩下唯一一处是全局基准 +0.2（00_code_static_modifiers.txt:12 的 base_values）—— 这个分布是 ru_defeat 立档时**没查到的**（那份档案写的是「原版该字段只出现过一次」），本档案按实测复核把原貌写全。**0.35 ≈ 1.75× 全局基准**，属于**实验取值**（不是原版档位），正式版要按真实赔款机制重算（backlog B35）。为什么不直接没收国库：反目标里写着「不让 AI 获得任何数值作弊」，也不想让大清当场破产（那样测出来的差分来自破产机制，不是来自干涉）。　【沿用·口径】**数值沿用 ru_defeat 的实测档位（0.2→0.35），未针对本条处境独立校准**。 |
| `reform_inputs.params[0].amount` | 10 | 与 [pressure.params] 的 years = 10、记忆变量的 days = 3650 三处对齐：三者在实验里是同一段时间窗，任何一处短了都会出现「输入还在、压力已经没了」的半截状态。原版 add_modifier 用 years 的写法见 00_movement_effects.txt:1-7。　【沿用·口径】沿用 ru_defeat 的取值，未针对本条处境独立校准。 |
| `reform_inputs.effects[0].amount` | 0.5 | 取原版同族强档 +0.5，而且**这一档在大清这个处境上有直接同型先例**：`shogun_ig_forced_to_open_market`（content_1_modifiers.txt:1463-1471）在同一个修正里把地主 -0.75、知识界 +0.5、工业家 +0.5 一起写 —— 那就是「被外力逼着开门 → 改革侧势力抬头」，与本档案要表达的情形同型（幕府 vs 大清，同一时代的同一种外部压力）。原版同字段的全部档位实测为 0.05 / 0.1 / 0.15 / 0.25 / 0.3 / 0.5（以及 -0.5、-0.50、2 两个反向与特例），见 00_ip4_03_modifiers.txt:7、00_ip4_04_modifiers.txt:33、content_1_modifiers.txt:1467 等。取 0.5 而不是 0.15：`progressive_agenda` 的权重只在 `ig:ig_industrialists ?= { is_powerful = yes }` 时 +10（03_political_strategies.txt:537-544），而 is_powerful 是**相对份额**判定 —— 同一处只抬一档常常翻不过那条线，实验要的是「输入明确到位」，不是「差一点」。　【沿用·口径】**数值沿用 ru_defeat 的实测档位（0.5），未针对本条处境独立校准**；本处境另外指出它与原版幕府被迫开国那一条同档同字段。 |
| `reform_inputs.effects[1].amount` | 0.5 | 与工业家同档同源（content_1_modifiers.txt:1466 的 shogun_ig_forced_to_open_market 里这两条就是成对写的）。`progressive_agenda` 的权重对知识界与工业家各 +10（03_political_strategies.txt:528-544），两条一起给才是原版的用法；只给一条会让「哪一条起了作用」在实验里不可分。原版同字段档位实测为 0.15（106_modifiers.txt:205）、0.2、0.25（00_ip4_04_modifiers.txt:47）等。　【沿用·口径】**数值沿用 ru_defeat 的实测档位（0.5），未针对本条处境独立校准**；档位依据见上一条。 |
| `journal_entry.fields[0].amount` | 100 | JE 列表拥挤时的保留优先级。与原版 je_corn_laws 的 weight = 100 同档（00_corn_laws.txt:79）—— 改革窗口是处境级 JE，不该被小 JE 挤掉。⚠️ 已知的档位差异：原版大清那一族的 JE 用 weight = 10000（je_opium_wars，00_opium_wars.txt:183；je_warlord_china，00_warlord_china.txt:105）、1000（je_boxer_rebellion，00_boxer_rebellion.txt:49）。本档案**刻意不取 1000/10000**：那几档是原版核心历史内容 JE，本档案是与它们并行的处境窗口，压过它们会把原版自己的历史内容挤下去。　【沿用·口径】沿用 ru_defeat 的取值，未针对本条处境独立校准。 |
| `journal_entry.conditions[4].amount` | 75 | 开窗的第二个条件：压力够大。**为什么门槛是 75**：原版就用 75 做「政府站得住 / 站不住」的国家级分界 —— 00_meiji_restoration.txt:314 的 `legitimacy >= 75`、01_french_monarchism.txt:329 与 :466 的 `government_legitimacy >= 75`、events/greece_events.txt:179 的 `government_legitimacy >= 75`；它同时也是 ru_defeat 在阶段 3 里**实测校准**过的门槛（A 组无冲击时每一个观测月都 >80，不会误开；B 组 -35 时 55 块里有 42 块 ≤75）。**本档案没有独立重跑 A/B**：这个 75 **原样沿用 ru_defeat 的实测分界**，同时也正好落在原版自己那条 75 线上 —— 两件事指向同一个数，但只有前者是实测。相应地 `complete` 写 75，开与关正好接上。　【沿用·口径】**数值沿用 ru_defeat 的实测档位，未针对本条处境独立校准**；本处境另外指出它与原版三处 75 同档。 |
| `journal_entry.conditions[5].amount` | 75 | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 legitimacy >= 75、01_french_monarchism.txt:329 的 government_legitimacy >= 75。　【沿用·口径】沿用 ru_defeat 的取值，未针对本条处境独立校准。 |

## 判据（JE）

| 判据块 | 判据 | 为什么 |
|---|---|---|
| `is_shown_when_inactive` | `c:CHI ?= this` | 档案是**单国**的，主角是**大清**。tag 是 `CHI`（不是 CHN / QNG）：本机实测确认 `v3 evidence CHI` 命中原版 6 处/8 文件，其中 `00_countries.txt:1818` 就是 `CHI = {`（原版国家定义里的顶层键，country_type 在 :1821 写作 `unrecognized` —— 也就是「未列强承认的大国」，这正是本档案处境的制度底子）。`c:CHI ?= this` 这个写法在大清自己的 JE 里就是原版用法（00_boxer_rebellion.txt:12 的 `c:CHI ?= THIS`；问号的语义是「作用域存在才比」，比裸 = 稳），而通用写法见 05_metternich.txt:8 的 `c:AUS ?= this`。　【沿用·口径】写法沿用 ru/tr，未针对本条处境独立校准；单国门这一行是按本档案主角换的（有原版行号）。 |
| `is_shown_when_inactive` | `has_variable = sitai_cn_intervention_memory` | 没被记过「列强干涉」的国家连这条 JE 都不该看见 —— 「和平期占槽率 ≈ 0」这条出口判据（G-EXIT-5.2）靠它：不施加冲击的局里，这行判据为假，整条 JE 不出现。原版读变量的写法见 00_corn_laws.txt:7。　【沿用·口径】沿用 ru/tr 的判据形状，未针对本条处境独立校准。 |
| `is_shown_when_inactive` | `country_has_primary_culture = cu:manchu` | **这是本档案比 ru/tr 多出来的一行，也是「大清」这个主角的必要条件**。原因：tag 是 `CHI` 只说明「这是中国那块地」，而 1836 年的大清是**满族统治的王朝**（八旗、满汉之分、科举与士绅是它统治的两根柱子，见 01a §K「大清」那一行：士绅与科举、八旗退化）。这条判据让窗口只在**清的统治形态还在**时出现 —— 如果 `CHI` 已经变成一个换了主体的政权（原版允许这种变化），「列强干涉托起改革派」这条因果就不再是同一回事。写法是原版自己的：00_boxer_rebellion.txt:14 的 `country_has_primary_culture = cu:manchu`（原版用它把义和团 JE 锁在满清身上，与本处同一个用法），另见 00_warlord_china.txt:8-9 的 `cu:han` / `cu:manchu` 两条。　【原版行号依据】不是实测读数，是原版同族用法。 |
| `possible` | `has_variable = sitai_cn_intervention_memory` | 开窗的第一个条件：确实被外力干涉过。is_shown_when_inactive 与 possible 都写一遍是有意的 —— 前者管「看不看得见」，后者管「开不开」，原版 je_corn_laws 也是两处各写一套（00_corn_laws.txt:6-31）。　【沿用·口径】沿用 ru/tr 的判据形状，未针对本条处境独立校准。 |
| `possible` | `legitimacy <= 75` | 开窗的第二个条件：压力够大。**为什么门槛是 75**：原版就用 75 做「政府站得住 / 站不住」的国家级分界 —— 00_meiji_restoration.txt:314 的 `legitimacy >= 75`、01_french_monarchism.txt:329 与 :466 的 `government_legitimacy >= 75`、events/greece_events.txt:179 的 `government_legitimacy >= 75`；它同时也是 ru_defeat 在阶段 3 里**实测校准**过的门槛（A 组无冲击时每一个观测月都 >80，不会误开；B 组 -35 时 55 块里有 42 块 ≤75）。**本档案没有独立重跑 A/B**：这个 75 **原样沿用 ru_defeat 的实测分界**，同时也正好落在原版自己那条 75 线上 —— 两件事指向同一个数，但只有前者是实测。相应地 `complete` 写 75，开与关正好接上。　【沿用·口径】**数值沿用 ru_defeat 的实测档位，未针对本条处境独立校准**；本处境另外指出它与原版三处 75 同档。 |
| `complete` | `legitimacy >= 75` | 关窗的门：国家重新站稳，窗口自己关上（不是「改革完成」—— 改什么由 AI 与原版牌池决定，本档案不替它选法律）。75 也是原版用过的档：00_meiji_restoration.txt:314 的 legitimacy >= 75、01_french_monarchism.txt:329 的 government_legitimacy >= 75。　【沿用·口径】沿用 ru_defeat 的取值，未针对本条处境独立校准。 |

## 面板三行（P11 / G3）

| 行 | 本地化键 | 为什么是这一行 |
|---|---|---|
| goal | `je_sitai_cn_reform_window_goal` | 第一行 = **当前目标**。写「推过去」而不是点名某条法律：改哪条法由 AI 与原版牌池决定，本档案不替它选（§0「让 AI 自己推导」）；写「士绅与旧官僚拦着的那项」是让玩家知道它为什么一直没动 —— 这一行与 `[pressure.effects]` 里减 devout 的那一条是同一个因果的两端。 |
| pressure | `je_sitai_cn_reform_window_pressure` | 第二行 = **最大压力与阻力**。压力项与 `[pressure.effects]` 的三条字段一一对应（保守侧 / 合法性 / 利率），阻力项与 `complete = { legitimacy >= 75 }` 是同一条判据的两种说法 —— 数值改了这行也要改（P9：改一处、三处同步）。 |
| last_change | `je_sitai_cn_reform_window_last_change` | 第三行 = **上次改主意的原因**。这一行是 G3 里最容易被跳过、却最关键的一行：没有它，玩家只能看到「它在改革」，看不到「**为什么是现在**」。写「被记进了账」是让因果链读得出来（§0.1 派生义务：目标函数表要显式、可审）。 |

> 为什么拆成三个键而不是揉进 `_reason`：G3 判的是**试玩者能复述**「当前目标 + 主因」，揉在一起就分不清是哪一行没写清楚。缺行当场可见。

## 声明式引用（闸门 ② 逐条核对）

| 类别 | 名字 | 为什么 |
|---|---|---|
| `trigger` | `legitimacy` | JE 的开窗/关窗判据（`legitimacy <= 75` / `>= 75`）。原版用法：00_meiji_restoration.txt:314（legitimacy >= 75）、01_french_monarchism.txt:329 与 :466（government_legitimacy >= 75）、events/greece_events.txt:179（government_legitimacy >= 75）。 |
| `trigger` | `country_has_primary_culture` | is_shown_when_inactive 里把窗口锁在满清统治形态上（`country_has_primary_culture = cu:manchu`）。原版用法：00_boxer_rebellion.txt:14（义和团 JE 用同一行锁大清）、00_warlord_china.txt:8-9（cu:han / cu:manchu）。 |
| `trigger` | `has_variable` | 记忆变量的读法。原版用法：00_corn_laws.txt:7 等 795 处（阶段 1 统计 has_variable 被 13 张牌直接读）。 |
| `effect` | `set_variable` | 写记忆变量。原版用法：00_code_on_actions.txt:7046（on_war_end 给 recently_had_war 记 5 年）。 |
| `effect` | `add_modifier` | 把静态修正挂到国家上。原版用法：00_movement_effects.txt:2（add_modifier = { name = … years = 20 }）。 |
| `country_tag` | `CHI` | JE 的单国门（c:CHI ?= this）。本机实测：`v3 evidence CHI` 命中原版 6 处/8 文件 —— common/country_definitions/00_countries.txt:1818 的 `CHI = {`、common/flag_definitions/00_flag_definitions.txt:2184 的 `CHI = { # China`、common/dynamic_country_names/00_dynamic_country_names.txt:1233、common/country_formation/00_formable_countries.txt:177。 |
| `modifier_field` | `country_legitimacy_base_add` | 合法性修正字段。原版档位 ±5 / ±10 / ±20（00_code_static_modifiers.txt:322-353 一连串；另有 ±25 / -50，见 :979 与 :986），而**同一件事在大清身上的原版记账是 -50**：opium_wars_lost（content_1_modifiers.txt:17）。 |
| `modifier_field` | `interest_group_ig_devout_pol_str_mult` | 教会 / 士绅与旧官僚那一侧的政治力量（本档案的「保守侧失势」用的就是它）。原版档位：+0.25（00_ip4_04_modifiers.txt:19）、+0.15（106_modifiers.txt:224）、-0.25（00_ip4_04_modifiers.txt:141「Selling church lands」）、-0.50（agitators_5_modifiers.txt:616）、-0.80（brazil_2_modifiers.txt:149）。 |
| `modifier_field` | `country_loan_interest_rate_add` | 借债利率。原版 10 处：全局基准 +0.2（00_code_static_modifiers.txt:12 的 base_values）、条约修正 ±0.01/±0.02/±0.03/±0.05（00_amendments_enactment_04.txt:644、:1138、:1174、:1222、:1266）、科技 -0.02（30_society.txt:209 等 5 处）。⚠️ ru_defeat 的 why 里写「原版只有一处」，本档案按实测复核更正为 10 处，**没有档位阶梯这一点仍然成立**（国家修正侧只有全局基准 +0.2 那一处）。 |
| `modifier_field` | `interest_group_ig_industrialists_pol_str_mult` | 工业家政治力量。原版档位：0.1（00_ip4_03_modifiers.txt:7）、0.25（00_ip4_04_modifiers.txt:33）、0.5（content_1_modifiers.txt:1467 的 shogun_ig_forced_to_open_market —— 幕府被迫开国，与本档案同型）。 |
| `modifier_field` | `interest_group_ig_intelligentsia_pol_str_mult` | 知识界政治力量。原版档位：0.15（106_modifiers.txt:205）、0.25（00_ip4_04_modifiers.txt:47）、0.5（content_1_modifiers.txt:1466 的 shogun_ig_forced_to_open_market）。 |

## 复算

```text
v3 modgen --write     # 数据源 → 产物（改完 TOML 必跑）
v3 modguard           # 五道闸门（不通过不许进游戏）
v3 modgen --why       # 只列每个数字与它的依据
```
