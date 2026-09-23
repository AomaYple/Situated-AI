# 09 · AI mod 实战技法

> 本文从真实 AI mod（`Kuromi's AI`，steamId `3227982912`，本机已安装）的作者自述中提炼**可复用的技法**，并与本知识库中的结构分析相互印证。
> 技法本身是通用的；具体数值是该作者的选择，不应照搬。
> ⚠️ **版本跨度（精确清单）**：本文数字分两类，来源与时效各不相同 ——
> **(1) 已由 `v3 verify` 在 1.14.3 核验**（本文那 3 条断言）：`ai.nai_params_doc09` 1017、`ai.script_values_doc09` 33、`ai.strategy_refs_doc09` 19。
> **(2) 其余数字全部是「本机 `Kuromi's AI` 快照」，与游戏版本无关**（换台机器、mod 作者更新一版就变），本轮已按 1.14.3 的安装逐项复算：`changelog.md` 10,027 B / 169 行；`kai_ai.txt` 6,698 B / 67 行（顶层块只有 `NAI` 一个、其下参数 31 个）；三个 `kai_*_strategies.txt` 依次 9,218 B / 315 行、852 B / 55 行、10,359 B / 646 行。
> 本文**没有**仍挂在 1.14.2 的「零使用 / 未使用」类结论 —— 全文不依赖「原版零使用某键」这种判断。

## 1. 先建立正确的心智模型

### 1.1 AI 的取值是「基线 + 策略叠加」

**【官方】** `00_default_strategy.txt` 开头：

> This is a special strategy that sets the default values for different AI scores.
> All AIs always load data from this strategy, which can then be either **added to** or **overridden by** data from its other strategies.

所以改 AI 有两条完全不同效果的路径：

| 路径 | 效果 |
|---|---|
| 改 `ai_strategy_default` 里的值 | 改变**所有**国家在所有情况下的基线 |
| 改具体策略（如 `ai_strategy_industrial_expansion`）里的值 | 只影响**选中该策略**的国家 |

> 若只想调整某类国家的行为，改具体策略；若想整体抬高/压低某个行为，改 default。

### 1.2 策略会在换统治者时重掷

**【实战】** Kuromi 在文档中提到：

> AI strategies are rerolled upon ruler change

这解释了为什么**国家专属策略**（如明治维新）需要针对特定统治者做限制，也意味着：
**依赖「开局即触发」的策略可能在换统治者后丢失。**

### 1.3 小心反馈回路

**【实战】** 作者多次提到反馈回路问题，例如：

> Made the income factor in wanted army / navy size calculation account for current tax rate. This is to prevent a feedback loop between tax changes and military sizes.

> Navy is a large contributing factor to a country's prestige. Tying navy size to country rank could create a feedback loop.

**教训**：AI 字段之间会互相影响（军费↔税收↔威望↔军力），调整前先想清楚闭环。

## 2. 九大可改造领域

按作者实际动手的范围整理，每个都对应到具体字段：

### 2.1 建造意愿 — `wanted_construction_output`

**【实战】** 作者所做的调整类型：

- 修正「投资池转账收入被重复计算」的 bug
- 放宽「收入用于建造」的比例上限
- 移除传统主义、非工业化策略带来的建造乘数惩罚
- 移除建造意愿随人口缩放、随列强等级缩放的做法
- 按科技进度分阶段调整（未研发出某科技前降低建造意愿）

**字段**：`wanted_construction_output`（在 `ai_strategy_default` 及各经济策略中）

### 2.2 生产方式（PM）选择 — 通过 AI 评分参数

**【实战】** 作者大量调整 PM 评分逻辑：

| 调整方向 | 说明 |
|---|---|
| 降低基础分 | 让乘数类因素（如省人力）对低级建筑影响变小 |
| 降低「产出商品价值」权重 | 让 PM 选择少受经济策略牵制 |
| 提高「造成短缺」的评分 | **让 AI 主动创造还不存在的商品需求** |
| 移除升级 PM 的粘性 | 修正兵营 PM 不会升级的问题 |
| 调整降级粘性 | 让飞机/坦克这类「账面降级」能被采用 |
| 对使用昂贵商品的 PM 加分惩罚 | 区分「可贸易」与「不可贸易」商品 |

**教训**：PM 系统是 AI 经济表现的关键，且**多半靠 defines 调，而非策略字段**。

### 2.3 经济策略 — `building_group_weights` / `subsidies` / `goods_stances`

**【实战】**：

- 移除经济策略里的**负向**建筑权重（原版会给工业建筑乘 25–50%），这曾导致 AI 造不出政府用纸
- 调低正向建筑权重的极端程度
- 补贴等级从「必须有」降到「最好有」
- 商品立场（`goods_stances`）不再考虑人口
- **让策略权重主要基于识字率，而非地理硬编码** —— 作者明确批评原版对非欧美国家的「铁路化」引导

> **这是最值得学习的一条**：原版用硬编码的地理/区域倾向限制 AI 发展路径，改用识字率等内生指标可以显著改善非欧洲国家的表现。

### 2.4 政治策略与法律

**【实战】** 涉及字段：

| 字段 | 调整方向 |
|---|---|
| `max_progressiveness` / `max_regressiveness` | 放宽政治策略能推进/倒退的幅度 |
| `change_law_chance` | 提高改法概率（作者把「内乱加成」并入基础概率） |
| `revolution_aversion` | 提高以避免频繁改法引发内战 |
| `min_law_chance_to_pass` | 降低 AI 考虑改法的最低成功概率门槛（原文降到 10%） |
| `pro_interest_groups` / `anti_interest_groups` | 移除某些派系（如农村民众）以避免合法性崩塌 |
| `interest_group_government_weight` | 提高入阁倾向的乘数 |

**策略权重重写思路**（作者原话大意）：
> 完全重写了政治策略权重，主要基于**利益集团影响力**而非统治者意识形态；统治者所属 IG 额外获得「国家元首入阁带来的合法性」加权；所有政治策略起始权重 -10 以抑制选择缺乏支持度的策略。

**法律权重**：给法律设置大额 AI 权重（作者用了 ±1000 量级）来强制行为转向，例如：
- 农民比例降到 75% 以下时，废除消费税/土地税 +1000
- 人均 GDP 超过 1.5 镑时，转向比例税 +1000（反向 -1000）
- 官僚开支超过标准化收入 30% 时，会引入新机构的法律 -1000

### 2.5 外交 — `max_active_stances` / `strategic_region_scores` / 各类 `*_scores`

**【实战】**：

- `max_active_stances`：**不再统计已有合并州的战略区域**（让俄国能兼顾欧亚）、改为随海军投射力缩放、取消 10 的上限
- `strategic_region_scores`：给相邻战略区域 +50，让扩张更自然
- `undesirable_infamy_level`：移除恶名容忍度随民族主义科技缩放，抑制 AI 突破 50 恶名
- `treaty_category_scores`：不再向属国索要投资权
- `wargoal_scores`：移除对竞争对手属国的政权更迭战争目标分

**通用教训**：`max_active_stances` 这类**硬上限**是限制 AI 全局布局的关键阀门。

### 2.6 科技选择

**【实战】** 提高特定科技的权重：
- 铁路的前置科技（否则铁路对 AI 永远不可见）
- 蒸汽轮机（让燃煤电厂 PM 可用）
- 电话、无线电（多个军事单位的前置）

**教训**：AI 看不到「前置未满足」的科技，**给前置科技加权**是解锁后续行为的前提。

### 2.7 军事规模 — `wanted_army_size` / `wanted_navy_size` / `wanted_marines`

**【实战】**：

- `wanted_army_size`：修正内陆国不随收入缩放陆军的 bug；让收入因子考虑当前税率
- `wanted_marines`：**直接设为 0** —— 因为原版存在「已登船陆战队阻塞 AI 建造军事建筑」的 bug
- `wanted_navy_size`：列强海军随沿海人口缩放设下限；孤立主义改为看法律变体而非策略；商船海军法律 -34%
- 舰船类型：让 AI 不造浅水重炮舰、岸防舰、运兵船（因为 AI 不区分其用途）
- `wanted_num_supply_ships`：随科技增长（后期单位耗补给更多）

**教训**：**原版 AI 有大量可利用 bug**。与其硬调参数，不如先找到「AI 为什么不这么做」的真实原因。

### 2.8 动员选项

**【实战】** 调整单位属性对 AI 的价值权重：

| 属性 | 变化 |
|---|---|
| 单位攻击/防御（平铺） | 100 → 200 |
| 士气恢复 | 5000 → 3000 |
| 击杀率/恢复率 | 5000 → 10000 |
| 阵型移动速度 | 10000 → 3000 |
| 战斗占领 | 新增权重 |

**教训**：动员选项的选择由「单位属性 → AI 价值」映射决定，改这个映射即可引导 AI 选不同支援组。

### 2.9 机构与行政

**【实战】**：

- 降低机构基础支出权重，鼓励 AI 投资新解锁机构而非全砸在第一个
- 降低机构降级门槛
- 政府行政的选址权重按「税收能力使用率/产出比」缩放
- 修正「缺少资质」的评估惩罚（-90% → -40%），避免 AI 在偏远地区乱建

## 3. 元技法总结

```text
① 先查 bug，再调参数
   原版 AI 的很多"愚蠢"行为源于逻辑缺陷而非数值。
   例：登船陆战队阻塞建造、投资池收入重复计算、内陆国不缩放陆军。

② 分清"硬编码倾向"与"内生指标"
   原版用地理/区域硬编码引导 AI（如非欧美国家被迫农业化）。
   改用识字率、人口、产业结构等内生指标，效果更好且更少"铁路化"。

③ 用大权重做强制转向，用小权重做微调
   法律/科技转向用 ±1000 量级；行为倾向用 ×1.5 / ×0.75 量级。

④ 改动要有反馈回路意识
   军费 ↔ 税收 ↔ 威望 ↔ 军力 互相咬合，单点调整会传导。

⑤ 用 defines 调机制，用 strategies 调倾向
   PM 评分、外交应答阈值等 → defines (00_ai.txt)
   建造意愿、侵略性、法律倾向等 → ai_strategies
```

## 4. 与结构分析的交叉验证

本文所述的每个领域，都对应到 `03-AI系统.md` 中列出的字段：

| 领域 | 对应字段 | 所在位置 |
|---|---|---|
| 建造 | `wanted_construction_output` | strategy |
| 建筑倾向 | `building_group_weights` | strategy |
| 补贴 | `subsidies` / `war_subsidies` | strategy |
| 商品 | `goods_stances` | strategy |
| 政治 | `max_progressiveness` / `change_law_chance` / `revolution_aversion` / `min_law_chance_to_pass` | strategy |
| 派系 | `pro_interest_groups` / `anti_interest_groups` / `interest_group_government_weight` | strategy |
| 外交 | `max_active_stances` / `strategic_region_scores` / `undesirable_infamy_level` / `wargoal_scores` / `treaty_category_scores` | strategy |
| 军事 | `wanted_army_size` / `wanted_navy_size` / `wanted_marines` / `ship_group_weights` / `combat_unit_group_weights` | strategy |
| 机构 | `institution_scores` | strategy |
| PM 评分 / 外交阈值 / 各类机制 | 1,018 个 `NAI` 参数 | `common\defines\00_ai.txt` |
| AI 中间值 | 40 个脚本值（其中 26 个被 `00_default_strategy.txt` 引用） | `common\script_values\ai_script_values.txt` |

## 5. 真实 AI mod 覆盖了哪些 `NAI` 参数

**【实测】** 解剖 `Kuromi's AI` 的 `common\defines\kai_ai.txt`（67 行），其中 `NAI = { ... }` 块**只覆盖了 31 个参数**（全库有 1,018<!--claim:ai.nai_params_doc09--> 个）。

> **这本身就是重要信息**：一个成熟的 AI mod 并没有大改参数，而是**精准打击少数关键项**。

| 领域 | 参数 | 该 mod 的值 |
|---|---|---|
| **政府改革** | `REFORM_GOVERNMENT_STICKINESS` | `1.0` |
| | `REFORM_GOVERNMENT_PRO_IG_CLOUT_FACTOR` | `2.5` |
| **舰船设计** | `SUPPLY_SHIP_STRAIN_MAX_RATIO` | `1.1` |
| | `SHIP_DESIGN_UTILITY_MOD_MIN_SCORE` | `1.125` |
| | `SHIP_DESIGN_UTILITY_MOD_MIN_SCORE_DIVISOR_PER_FREE_SLOT` | `1.05` |
| **机构开支** | `MAX_INSTITUTION_SPENDING_BASE` | `0.001` |
| | `MAX_INSTITUTION_SPENDING_PER_INSTITUTION` | `0.004` |
| | `INSTITUTION_SPENDING_DECREASE_SPENDING_RATIO` | `1.2` |
| **财政支出优先级** | `MONEY_SPENDING_MIN_RATIO_TO_ADD_SHOULD_HAVE` | `1.3` |
| | `MONEY_SPENDING_MIN_RATIO_TO_ADD_WANTS_TO_HAVE` | `1.35` |
| | `MONEY_SPENDING_MIN_RATIO_TO_ADD_NICE_TO_HAVE` | `1.4` |
| | `MONEY_SPENDING_MIN_SURPLUS_TO_IGNORE_RATIO_FOR_SHOULD_HAVE` | `100000` |
| | `MONEY_SPENDING_MIN_SURPLUS_TO_IGNORE_RATIO_FOR_WANTS_TO_HAVE` | `150000` |
| | `MONEY_SPENDING_MIN_SURPLUS_TO_IGNORE_RATIO_FOR_NICE_TO_HAVE` | `200000` |
| **创新** | `MONEY_SPENDING_INNOVATION_DESIRED_THRESHOLD` | `2.0` |
| | `MONEY_SPENDING_INNOVATION_EXCESSIVE_THRESHOLD` | `2.5` |
| **政府建筑选址** | `GOVERNMENT_BUILDING_STATE_MISSING_QUALIFICATIONS_MULT` | `0.6` |
| | `GOVERNMENT_BUILDING_STATE_POP_CONSTRUCTION_SECTOR_IMPORTANCE_MULT` | `1.0` |
| **税收** | `CONSUMPTION_TAX_INCOME_VALUE` | `150` |
| **生产建筑评分** | `PRODUCTION_BUILDING_OUTPUT_HIGH_PRICE_WANTS_HIGH_SUPPLY_FACTOR` | `2.0` |
| | `PRODUCTION_BUILDING_FAVORED_GOODS_FACTOR` | `0.25` |
| **生产方式（PM）评分** | `PRODUCTION_METHOD_BASE_VALUE` | `300` |
| | `PRODUCTION_METHOD_EMPLOYMENT_CHANGE_FACTOR` | `0.75` |
| | `PRODUCTION_METHOD_REDUCE_OUTPUT_PENALTY_FACTOR` | `5` |
| | `PRODUCTION_METHOD_INCREASE_OUTPUT_PENALTY_FACTOR` | `0.95` |
| | `PRODUCTION_METHOD_FAVORED_GOODS_FACTOR` | `0.05` |
| | `PRODUCTION_METHOD_FAVORED_MILITARY_GOODS_FACTOR` | `1.5` |
| | `PRODUCTION_METHOD_UNDESIRABLE_GOODS_PRICE_FACTOR_UNTRADEABLE` | `-0.75` |
| | `PRODUCTION_METHOD_STICKINESS_UPGRADE` | `1.0` |
| | `PRODUCTION_METHOD_STICKINESS_DOWNGRADE` | `0.95` |
| **军事编制** | `MILITARY_UNITS_PER_FORMATION_ARMY` | `125` |

**规律**：**9 个集中在生产方式（PM）评分** —— 印证了 §2.2 的判断，PM 系统是 AI 经济表现的关键杠杆，且只能靠 defines 调。

### 5.1 对本文档的启示

这 31 个参数可以作为**起点清单**：先在这批参数上做实验，比漫无目的地翻 1,017 个参数高效得多。

> 注意：`kai_ai.txt` 只包含 `NAI` 一个块。这说明 **defines 覆盖是按「块 + 参数」粒度生效的**，不是整文件替换 —— 你只需写出要改的参数即可。

## 6. 下一步可做的事

> 本节列出全文的待办项。与早期版本（四条无证据的复选框）的区别：**每一项都写明「本地已有什么证据」与「还缺什么」**，
> 已经做完的条目改为「已答」并去掉标记；编号沿用原文。证据口径与四条实测配方见 `04-脚本系统.md` §13.1。

| # | 未确认内容 | 本地证据（可复算） | 状态 |
|---|---|---|---|
| 1 | 精读 `Kuromi's AI` 的 `changelog.md`（10 KB），对照版本演进看哪些改动被回滚 | **已答**：`changelog.md` 实测 10,027 B / 169 行，含 7 个版本段（`## Version 6.0` / `7.0` / `7.1` / `7.2` / `7.3` / `7.4` / `7.5`，逐字见 `changelog.md:5`、`:23`、`:31`、`:49`、`:73`、`:99`、`:153`）。按 `revert` 逐行检索命中 3 行：`:45`（防止政府行政退回无纸化 PM）、`:129`（日本不再倒回幕府）都不是回滚 mod 自身改动，**只有 `:47` 是明确的数值回滚** —— 逐字 `Lowered AI's desire for white peace from 2 to 1 per week. This reverts it to 1.12 level.`（复算：`Select-String -Path <mod>\changelog.md -Pattern "revert"`） | 已答 |
| 2 | 反编译/阅读其 `kai_ai.txt`（6.7 KB），看它到底覆盖了哪些 `NAI` 参数 | **已答（见 §5）**：文件实测 6,698 B / 67 行，顶层块**只有 `NAI` 一个**，其下参数 31 个（31 个互不重复）—— 与 §5 表格列的 31 行逐条对应（复算：读 `common\defines\kai_ai.txt`，按顶层块名与块内 `大写键 = 值` 计数） | 已答（见 §5） |
| 3 | 对照其 `kai_*_strategies.txt`，看自定义策略的完整写法 | **已答**：三个文件与顶层块计数 —— `kai_admin_strategies.txt` 9,218 B / 315 行 / 6 个块（全部 `REPLACE:`）、`kai_diplomatic_strategies.txt` 852 B / 55 行 / 8 个块（全部 `INJECT:`）、`kai_political_strategies.txt` 10,359 B / 646 行 / 8 个块（`REPLACE:` 1 + `INJECT:` 7）。写法 = **功能前缀 + 原版同名策略键**，逐字实例见 `kai_admin_strategies.txt:1` `REPLACE:ai_strategy_agricultural_expansion = {` 与 `kai_diplomatic_strategies.txt:1` `INJECT:ai_strategy_maintain_power_balance = {`；顶层字段集合也已取全（admin：`icon`/`type`/`weight`/`possible`/`building_group_weights`/`goods_stances`；diplomatic：`unacceptable_infamy_level`/`undesirable_infamy_level`；political 15 种，含 `pro_interest_groups`/`anti_interest_groups`/`change_law_chance`/`max_progressiveness`/`institution_scores` 等）。前缀机制本身见 `04-脚本系统.md` §12.4 | 已答 |
| 4 | 【未确认】建立本项目自己的最小 AI mod 骨架并实测加载 | 本机用户 mod 目录 `C:\Users\28905\Documents\Paradox Interactive\Victoria 3\mod\` 存在但**为 0 项**；仓库内 `*.mod` / `descriptor.mod` **0 个**（复算：`Get-ChildItem -Recurse -Include *.mod,descriptor.mod | Measure-Object`）；`tools\out\mods\` 下只有工具产物 `mod.json`，不是骨架 —— 既没有现成骨架，也没有任何一次实际加载记录 | 本地无证据 → 配方 C |
