# 02 · Mod 结构与加载机制

> 本文区分三类信息：**【实测】**= 从本机文件直接读到；**【官方】**= 游戏自带 `.md`/注释原文；**【推断】**= 由证据推导，尚未直接验证。请以标注为准。

> **版本提示（精确清单）**：本机游戏是 **1.14.3 (Ice Tea)**，`binaries\victoria3.exe` = **97,292,920 B**。本文没有 1.14.2 的遗留值 ——
> - **已是 1.14.3**：六个前缀的原版**零使用**断言 `pfx.vanilla_*` **7 条**（含总和 `pfx.vanilla_zero`）每次 `v3 verify` 都重扫全树，本次 **7/7 通过**；本机 mod 的前缀用量（总计 **2,737** 次、逐前缀 `REPLACE_OR_CREATE` 1116 / `INJECT` 740 / `TRY_INJECT` 440 / `TRY_REPLACE` 221 / `REPLACE` 174 / `INJECT_OR_CREATE` 46）由 `pfx.mods_total` 等 6 条断言钉住，本次全绿。
> - **本轮现场复算**：§5.1.1 的目录分布 = `v3 prefixes -n 60`，输出 **43 行**；它与 §5.1.1 表的唯一差异是 `technology/technologies`(58) 与 `technology/eras`(3) 在该表里被合并成 `technology` 一行，故正文写 **42** 个目录。
> - **唯一已知漂移（已消解）**：`v3 verify` 的 `tree.game` 曾报 **27,725**（比本文的 27,723 多 2），根因是游戏目录里被外部程序丢进两个**非游戏文件**（看图工具的 `.XnViewSort` 索引与一个 `.dmp` 缓存，2026-09-20 09:02 生成）。把它们移出游戏目录后断言恢复到 **27,723**。这类文件现在由 `tools/tests/test_install_hygiene.py` 自动点名。

## 1. 两种 mod 形态

| 形态 | 位置 | 标识文件 | 本机现状 |
|---|---|---|---|
| **本地 mod** | `C:\Users\28905\Documents\Paradox Interactive\Victoria 3\mod\<mod名>\` | `.metadata\metadata.json` | **空** |
| **Workshop mod** | `C:\Program Files (x86)\Steam\steamapps\workshop\content\529340\<steamId>\` | `.metadata\metadata.json` | 23 个 |

两者**结构完全一致**，启动器统一处理。

## 2. 关键结论：不需要 `descriptor.mod`

**【实测】** 对 `binaries\victoria3.exe`（**97,292,920 字节 ≈ 92.79 MiB**）做字符串检索：

| 字符串 | 结果 |
|---|---|
| `descriptor.mod` | **未找到** |
| `.metadata` | 找到 |
| `metadata.json` | 找到 |
| `supported_game_version` | 找到 |
| `multiplayer_synchronized` | 找到 |

**【实测】** 全部 23 个 Workshop mod 中，`.mod` 与 `descriptor.mod` 文件数量为 **0**<!--claim:pfx.vanilla_replace--><!--claim:pfx.vanilla_replace_or_create--><!--claim:pfx.vanilla_try_replace--><!--claim:pfx.vanilla_try_inject--><!--claim:pfx.vanilla_inject_or_create--><!--claim:pfx.vanilla_zero-->。

> **结论**：Victoria 3 使用 Paradox Launcher v2 的 `.metadata/metadata.json` 格式。网上仍流传的旧式 `descriptor.mod` + `<mod名>.mod` 写法已不被游戏本体引用。

## 3. `metadata.json` 完整字段

**【实测】** 对**全部 23 个 mod** 的 `.metadata\metadata.json` 取顶层字段并集
（不是只看两个样本 —— 早先只据两个样本写成「8 个字段」，漏了出现频率较低的两个）：

| 字段 | 出现次数 | 类型 | 说明 |
|---|---:|---|---|
| `name` | 23 / 23 | string | mod 显示名（启动器中可见） |
| `id` | 23 / 23 | string | mod 唯一标识，习惯用反向域名式命名（如 `kai.kuromi`） |
| `version` | 23 / 23 | string | mod 自身版本 |
| `supported_game_version` | 23 / 23 | string | 支持的游戏版本，**支持通配符**（实测样本用 `1.13.*`） |
| `short_description` | 23 / 23 | string | 简介 |
| `tags` | 23 / 23 | array | 标签 |
| `relationships` | 23 / 23 | array | mod 间关系（如依赖） |
| `game_custom_data` | 22 / 23 | object | 游戏自定义数据；唯一被用到的子键是 `multiplayer_synchronized`（bool），**多人同步标记** |
| `picture` | 4 / 23 | string | 启动器里的封面文件名（实测取值 `thumbnail.png` / `thumbnail.jpg`，相对 mod 根） |
| `game_id` | 2 / 23 | string | 目标游戏标识（实测取值均为 `victoria3`） |

也就是说：**7 个字段是必需的**（前 7 行），其余 3 个可选 —— 23 个 mod 里有
1 个连 `game_custom_data` 都没写（该 mod 的 `multiplayer_synchronized` 因此缺省）。

下面是两个真实样本（字段取值的形态参考）。

`Kuromi's AI`（`steamId 3227982912`）：

```json
{
  "name" : "Kuromi's AI",
  "id" : "kai.kuromi",
  "version" : "7.5",
  "supported_game_version" : "1.13.*",
  "short_description" : "A mod that improves AI's behavior.",
  "tags" : [],
  "relationships" : [],
  "game_custom_data" : {
    "multiplayer_synchronized" : true
  }
}
```

`牛奶汉化`（`steamId 2880069248`）字段名完全相同，但**多个字段留空**：`id` / `version` / `supported_game_version` / `short_description` 是空串，`tags` / `relationships` 是空数组，`multiplayer_synchronized` 为 `true`，而 `name` 仍写着「牛奶汉化」。也就是说**只有 `name` 是实质必填的**，其余都允许留空。【实测】

> `supported_game_version` 是给启动器做兼容性提示用的，**不会阻止加载**。

## 4. mod 目录结构

**【实测】** 典型 Workshop mod 顶层（`3007678964`）：

```text
<mod根目录>\
├─ .metadata\
│   └─ metadata.json          ← 必需
├─ common\                    ← 覆盖 game\common\
├─ events\                    ← 覆盖 game\events\
├─ gfx\                       ← 覆盖 game\gfx\
├─ gui\                       ← 覆盖 game\gui\
├─ localization\              ← 覆盖 game\localization\
└─ thumbnail.png              ← 启动器缩略图（实测各 mod 文件名大小写不一）
```

**核心规则**：mod 根目录下的子目录名，与游戏 `game\` 下的子目录名**一一对应**，逐层镜像。

```text
game\common\ai_strategies\00_default_strategy.txt
        ↕ 同名同相对路径即构成覆盖
<mod>\common\ai_strategies\00_default_strategy.txt
```

## 5. 覆盖 vs 新增

### 5.1 头等重要：数据功能前缀（`INJECT:` / `REPLACE:` 等）

**【实测】** Victoria 3 支持在**键名前加功能前缀**，从而**只改原版的单个条目而不必替换整个文件**：

```pdx
REPLACE:annex_country = { ... }        # 整体替换已存在的条目
INJECT:ban_slavery = { ... }           # 向已存在条目注入/合并字段
INJECT_OR_CREATE:building_food_industry = { ... }   # 存在则注入，不存在则新建
REPLACE_OR_CREATE:state_trait_lorraine_ironfield = { ... }  # 存在则整体替换，不存在则新建
TRY_REPLACE:company_bunge_born = { ... }   # 替换，目标不存在时不报错
TRY_INJECT:law_concordat = { ... }         # 注入，目标不存在时不报错
```

**六个前缀的实测出现次数**（扫描本机 23 个 Workshop mod 的全部 `.txt`，规则：行首匹配 `^前缀:键名 = {`）：

| 前缀 | 次数 | 语义（由行为推断） |
|---|---:|---|
| `REPLACE_OR_CREATE:` | **1,116** | 存在则整体替换，不存在则新建 |
| `INJECT:` | **740** | 向已存在条目**注入/合并字段**（不整体替换） |
| `TRY_INJECT:` | **440** | 同 `INJECT`，目标不存在时不报错 |
| `TRY_REPLACE:` | **221** | 同 `REPLACE`，目标不存在时不报错 |
| `REPLACE:` | **174** | 整体替换已存在条目 |
| `INJECT_OR_CREATE:` | **46** | 存在则注入，不存在则新建 |

每条都有逐字实证，例如：

| 出处 | 首行内容 |
|---|---|
| `3018606449` UH Diplomacy · `common\war_goal_types\Ultra_D_annex_country.txt:1` | `REPLACE:annex_country = {` |
| `3018606449` · `Ultra_D_War_Goal_Types.txt:3` | `INJECT:ban_slavery = {` |
| `3227982912` Kuromi's AI · `common\treaty_articles\kai_foreign_investment_rights.txt:1` | `INJECT:foreign_investment_rights = {` |
| `3227982912` · `common\ship_types\kai_ship_types.txt:2` | `INJECT:ship_type_monitor = {` |
| `3007678964` UH Warfare · `common\terrain\Ultra_W_terrain.txt:2` | `INJECT:plains = {` |
| `3278770055` · `common\buildings\zw_cpc_01_industry.txt:1` | `INJECT_OR_CREATE:building_food_industry = {` |
| `2897378189` UH Research · `Ultra_RE_country_ranks.txt:6` | `INJECT:great_power = {` |

> ⚠️ **这套机制在游戏自带的 92 份官方 `.md` 中完全没有记载**
> （全树搜索 `INJECT:` / `REPLACE:` 命中数为 **0**<!--claim:pfx.vanilla_inject-->）。
> 它是从真实 mod 的行为中反推出来的。

**为什么这极其重要**：它解释了 `12-真实mod解剖与改造面地图.md` 中那个反直觉的现象 ——
**多个 mod 可以同时修改同一个原版条目而互不冲突**，因为它们用的是 `INJECT:` 而非整文件替换。

### 5.1.1 适用范围：42 个数据目录（**实测**）

**【实测】** 扫描 23 个 mod，统计前缀出现在哪些 `common\` 子目录下：

| 使用次数 | 目录 | | 使用次数 | 目录 |
|---:|---|---|---:|---|
| 788 | `company_types` | | 22 | `ai_strategies` |
| 367 | `state_traits` | | 19 | `combat_unit_types` |
| 339 | `dynamic_country_map_colors` | | 15 | `goods` |
| 250 | `production_methods` | | 13 | `decisions` |
| 189 | `flag_definitions` | | 12 | `modifier_type_definitions` |
| 127 | `dynamic_country_names` | | 11 | `static_modifiers` |
| 82 | `laws` | | 11 | `discrimination_traits` |
| 76 | `cultures` | | 10 | `power_bloc_principles` |
| 61 | `technology` | | 10 | `country_creation` |
| 53 | `country_definitions` | | 8 | `amendments` |
| 51 | `buildings` | | 6 | `script_values` |
| 41 | `character_traits` | | 6 | `scripted_effects` |
| 37 | `ideologies` | | 5 | `combat_unit_experience_levels` |
| 28 | `war_goal_types` | | 5 | `ship_types` |
| 26 | `country_ranks` | | 3 | `political_movements` |
| 25 | `interest_group_traits` | | 3 | `legitimacy_levels` |
| 23 | `scripted_triggers` | | 2 | `scripted_buttons` / `game_rules` / `battle_conditions` / `treaty_articles` / `decrees` / `country_formation` |
| | | | 1 | `journal_entries` / `building_groups` / `terrain` |

**共 42 个 `common\` 子目录**出现该机制 → 说明它是**通用的数据层能力**，不限于少数类型。

> 注意：`script_values`、`scripted_triggers`、`scripted_effects`、`scripted_buttons`、`decisions`、`journal_entries`
> 这些**脚本类**目录也在列表中，意味着连脚本定义条目都能被 `INJECT:`。

### 5.1.2 原版本体完全不用它 —— 但引擎确实内置了它

**【实测】** 对整个 `game\` 树（27,723 个文件）做同样扫描：

```text
原版 .txt 文件中命中总数 = 0
```

**原版一处都没用过这套前缀**，全部 2,700+ 次使用都来自第三方 mod。

> ⚠️ **重要更正**：本文档早期版本据此推断「该机制缺乏自证，语义只能靠行为反推」。
> 后续对 `binaries\victoria3.exe`（97,292,920 字节）做**二进制字符串检索**，
> 找到了**决定性证据** —— 六个前缀的关键字与对应的**内部枚举名**成组连续存在于可执行文件中：
>
> ```text
> REPLACE_OR_CREATE:  REPLACE:  TRY_REPLACE:  TRY_INJECT:  INJECT_OR_CREATE:  INJECT:
> ReplaceOrCreate     Replace   TryReplace    TryInject    InjectOrCreate     Inject
> ```
>
> 该字符串区域位于 `jomini\modules\core\source\idlerlogicbase.cpp` 相关串附近。
>
> **结论修正**：这**不是社区约定，而是引擎内置的数据库操作语法**。
> 「原版不用」只说明它是**专为 mod 提供的介入手段**，不代表语义不可靠。

### 5.1.3 处理顺序（**【推断】，建议实测验证**）

有资料给出六个关键字的处理顺序（同关键字之间再按文件名 ASCII 顺序）：

```text
INJECT_OR_CREATE  →  REPLACE_OR_CREATE  →  TRY_INJECT
      →  TRY_REPLACE  →  INJECT  →  REPLACE
```

> **该顺序未在本机实测验证**，标为**【推断】**。
> 注意：二进制中六个字符串的**排列顺序**（`REPLACE_OR_CREATE, REPLACE, TRY_REPLACE, TRY_INJECT, INJECT_OR_CREATE, INJECT`）
> 与上面这个**处理顺序并不相同**，两者不可混为一谈。
> 若你的 mod 需要在同一键上叠加多种操作，**建议先做一次实测确认**。

### 5.1.4 已知限制

| 限制 | 说明 | 来源 |
|---|---|---|
| **只能作用于文件顶层块** | 无法只往某个已有子块里加一条（例如不能只给某 PM 的 `building_modifiers` 追加一项） | 【推断】 |
| **并非所有目录都支持** | **42 个** `common\` 子目录出现过该用法（见 §5.1.1）；**未在本机观察到反例** —— 早期版本曾写「实测 `travel_network` 不支持」，但 23 个 mod 里**没有任何一个**有 `common\travel_network\` 目录，该结论既无法复现也无法否证，故降级为「未确认」 | 【推断】 |


### 5.2 传统机制：同键名覆盖 / 整文件替换

> **2026-09-20 实测补两条**（探针 mod + 一次真实游戏会话，3 experiment）：
> 1. **裸同名键（不带前缀）＝ 先到先得**：在新增文件里重定义原版键，引擎逐字报
>    Duplicated key debug_success will not be created from file: …/zz_probe_effects.txt:4
>    —— 后写的那份**不会被创建**，不合并、不报错；国库只涨了原版的 50,000。
> 2. **两个 mod 用同一种前缀抢同一个键时，也是先加载者胜**：A（+1M）在启用列表里排在
>    B（+2M）前面，实测只有 A 生效，且日志对那个键**没有**重复警告 ——
>    说明 REPLACE_OR_CREATE 只对「已存在的条目」做替换，**不会让后写的 mod 覆盖先写的 mod**。
>    这一条修正了本文早期对前缀语义的简化说法（见 §5.1 的语义列）。

**【官方】** `game\common\on_actions\_on_actions.md` 明确说明了合并规则（这是全部数据文件共通的模式）：

> You can declare data for on-actions in multiple files, however, **you cannot have multiple triggers or effect blocks for a given named on-action**. In particular, you cannot append an effect block directly to an on_action which already has an effect block, as this creates a conflict.

因此：

| 操作 | 做法 | 说明 |
|---|---|---|
| **新增** | 用自己的文件名放新键 | 最安全，推荐 |
| **改原版单条目** | **用数据功能前缀**（`INJECT:` / `REPLACE:` …） | ✅ **最推荐**，见 §5.1 |
| **覆盖某键** | 用**同一个键名**重新定义 | 同名键会被替换（与 §5.1 前缀的关系**【未确认】**） |
| **整文件替换** | 放同相对路径同名文件 | 粒度最粗，冲突风险最高 |
| **追加到原版 on_action** | 不覆盖原文件，而是让原版 on_action 调用自己的 on_action（见下） | 官方推荐手法 |

官方给出的**追加 on_action** 配方（逐字引用自 `_on_actions.md`）：

```pdx
some_vanilla_on_action = {
	on_actions = { some_modded_on_action }
}
some_modded_on_action = {
	effect = {
		some_fun_modding_effect = yes
	}
}
```

> 注意：直接给已有 `effect` 块的 on_action 再写一个 `effect` 块会**冲突**，必须用上述转调手法。

### 5.3 未确认项

| # | 未确认内容 | 本地证据（可复算） | 状态 |
| --- | --- | --- | --- |
| U1 | 六个前缀的**权威语义**（原先只有行为推断） | **机制性质已答**：六个关键字与内部枚举名成组存在于 exe（§5.1.2）——`v3 evidence --exe-grep Inject` → `Inject` / `InjectOrCreate` / `TryInject`；`v3 evidence --exe-grep Replace` → `Replace` / `ReplaceOrCreate` / `TryReplace`。⚠️ 该口径只认**标识符形状**的整串（带冒号的 `INJECT:` 形态不入此列，见 §5.1.2 的原始串检索）。**逐条语义**仍只有行为推断：§5.1 的语义列 + 本机 23 mod 2,737 次实践（`pfx.mods_total` 已核验） | 【未确认】逐条语义本地无证据 → 配方 C |
| U2 | 前缀是否对**所有**数据目录都有效 | 本机 23 个 mod 在 **43 个** `common/` 目录下用过前缀（`v3 prefixes -n 60`；§5.1.1 表把 `technology/technologies`(58)+`technology/eras`(3) 合并为 `technology` 一行，故该表写 42）；原版 **0** 次（§5.1.2，`pfx.vanilla_zero` 已核验）；§5.1.4 记「未观察到反例」 | 【未确认】本地无证据（「未观察到反例」≠「所有目录都有效」）→ 配方 C |
| U3 | 不带前缀的同名键 与 `REPLACE:` 的差异 | 原版**跨文件重名 = 0**（doc 04 §12.2）；本机 23 个 mod **全部走功能前缀**（`v3 prefixes`）；exe 里有 `replace_cw_duplicate_compat`（`v3 evidence --exe-grep Replace`）→ 重名策略是**按键名逐项配置**的。同 **doc 04 §13.2 U1** | 【未确认】本地无证据 → 配方 C |
| U4 | 多个 mod 对同一条目分别 `INJECT:` 的合并顺序 | **本机就有实例**：**34 个**条目被 ≥2 个 mod 用前缀碰过，涉及 10 个 mod，`INJECT:great_power` / `unrecognized_power` / `unrecognized_regional_power` 各被 **4** 个 mod 碰过（复算：对 23 个 mod 的 `.txt` 逐行匹配行首 `前缀:键名 =`，再按键去重；总处数 2,736 与 `pfx.mods_total` 的 2,737 差 1 处，属字符类边界）。exe 侧另有 **161** 个 `<键名>_cw_duplicate_compat` 策略名（`v3 evidence --exe-grep _cw_duplicate_compat`，该命令默认只列前 40 条，见 `pdx.exe_strings.match_identifiers(limit=40)`） | 【未确认】待实测 → 配方 D（可直接拿 `INJECT:great_power` 那 4 个 mod 交换加载顺序对照） |


**【实测】文件名层面的覆盖**：`Kuromi's AI` 直接提供了自己的 `common\ai_strategies\00_default_strategy.txt`（183,606 B），替换原版同名文件（1.14.3 为 **199,110 B**）。这说明**整文件替换**也是有效手段。

## 6. 加载顺序与启用状态

### 6.1 启用列表 `content_load.json`

**【实测】** 位于用户数据目录，顶层三个属性：

```json
{
  "enabledMods": [ { "path": "C:\\...\\workshop\\content\\529340\\3656697666" }, ... ],
  "disabledDLC": [ ... ],
  "enabledUGC": [ ... ]
}
```

- `enabledMods` 是**对象数组**，每项含 `path`（绝对路径）
- 本机当前启用 **23** 个 mod

### 6.2 玩集（playset）`playsets_backup\*.json`

**【实测】** 格式：

```json
{
  "game": "victoria3",
  "name": "Ultra Historical",
  "mods": [
    {
      "displayName": "Ultra Historical Companies",
      "enabled": true,
      "position": 0,
      "steamId": "3656697666"
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `game` | 固定 `victoria3` |
| `name` | 玩集名 |
| `mods[].displayName` | 显示名 |
| `mods[].enabled` | 是否启用 |
| `mods[].position` | **加载顺序（0 起）** |
| `mods[].steamId` | Workshop ID（本地 mod 此项应为空或不同，【推断】） |

> **加载顺序由 `position` 决定**。多个 mod 覆盖同一键时，顺序靠后的生效（【推断】，未直接验证）。

本机两个玩集：

| 玩集 | mod 数 |
|---|---|
| `Ultra Historical` | 23 |
| `StateCraft AI` | **0**（空玩集） |

### 6.3 启动器数据库

`launcher-v2.sqlite`（151 KB）与 `launcher-v2_backup.sqlite`（131 KB）保存启动器的 mod 索引与玩集。**不要手工编辑**，改用启动器界面或 `playsets_backup` + `content_load.json`。

## 7. 新建本地 mod 的流程

### 方式 A：用游戏自带 mod 模板生成器（推荐）

**【实测】** `launcher-settings.json` 中声明：

```json
"modStubberPath": "../binaries/victoria3.exe",
"modStubberData": {
    "args": [ "--mod_stubber" ],
    "type": "MOD_NAME_PROMPT"
}
```

即运行 `binaries\victoria3.exe --mod_stubber`，会提示输入 mod 名并生成骨架。

### 方式 B：手工创建

```text
C:\Users\28905\Documents\Paradox Interactive\Victoria 3\mod\<你的mod名>\
├─ .metadata\
│   └─ metadata.json
├─ common\
│   ├─ ai_strategies\
│   ├─ defines\
│   └─ script_values\
└─ thumbnail.png
```

`metadata.json` 建议起始内容（字段依据 §3 实测样本）：

```json
{
  "name" : "StateCraft AI",
  "id" : "statecraft.ai",
  "version" : "0.1.0",
  "supported_game_version" : "1.14.*",
  "short_description" : "AI behaviour overhaul for Victoria 3.",
  "tags" : [],
  "relationships" : [],
  "game_custom_data" : {
    "multiplayer_synchronized" : true
  }
}
```

> 注意：这只是文件格式，**能否被启动器识别为 mod 尚未在本机验证**（`mod\` 目录为空，无样本可对照）。首次创建后请用启动器确认能出现在列表中。

## 8. 开发期必用的启动参数

**【实测】** `launcher-settings.json` 的 `alternativeExecutables` 提供调试模式入口：

```json
"exePath": "../binaries/victoria3.exe",
"exeArgs": [ "-gdpr-compliant","-debug_mode" ]
```

| 参数 | 作用 |
|---|---|
| `-debug_mode` | 调试模式：解锁控制台、显示错误、`ai.log` 等详细日志 |
| `-gdpr-compliant` | 默认参数，与 mod 无关 |

启动器界面中对应「**以调试模式打开游戏**」（含简体中文标签）。

## 9. 冲突排查

| 手段 | 位置 |
|---|---|
| `database_conflicts.log` | `logs\` —— **专用于检测数据覆盖冲突** |
| `error.log` | 语法/引用错误 |
| `warning.log` | 非致命问题 |

> 建议每次修改后优先检查 `database_conflicts.log`（当前 0 字节 = 无冲突）。

## 10. 打包与发布

**【实测】** `modExtension` = `zip`，说明本地 mod 可打包为 zip 分发。

**【实测】** `isLooseFilesModSupported` = `true`，说明**开发阶段用散装文件夹即可**，不必每次打包。

发布到 Steam Workshop 需通过游戏内或启动器的上传功能（未在本机验证具体入口）。

## 11. 速查清单

- [x] mod 根目录 = `Documents\Paradox Interactive\Victoria 3\mod\<名字>\`
- [x] 元数据 = `.metadata\metadata.json`（**不需要** `descriptor.mod`）
- [x] 内容目录名与 `game\` 下一一对应
- [x] 覆盖 = 同键名 或 同相对路径文件
- [x] 追加 on_action 要用官方转调手法，不可重复写 `effect` 块
- [x] 调试启动加 `-debug_mode`
- [x] 出错先看 `error.log` + `database_conflicts.log`
