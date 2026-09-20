# 12 · 真实 mod 解剖与改造面地图

> 本文对**本机已订阅的全部 23<!--claim:mod.total--> 个 Steam Workshop mod** 做机械解剖，回答一个核心问题：
> **「实际上，mod 都改了什么？」** —— 这比任何理论文档都更贴近实战。
> 全部数据来自对 `workshop\content\529340\` 的实际扫描（**【实测】**）。

> **版本提示（精确清单）**：本机游戏是 **1.14.3 (Ice Tea)**，但**本文的数字不是游戏版本属性，而是本机 mod 快照**（装了哪些 mod 决定一切）——这句限定比「采集于哪个版本」更要紧，故先说。原先那句笼统的「统计采集于 1.14.2」按类拆开：
> - **没有生成表**：`v3 tables` 的登记表里**没有本篇**（本篇 **0 张**生成表），因此不存在「表已重算」这回事；数字靠 `mod.*` / `mods.*` 断言与本节复算命令看守。
> - **已是 1.14.3 —— 断言已核验**：本篇 **3 条**断言（`mod.total`、`mod.files`、`mods.ig_files_doc12`）随 `v3 verify` 现场重扫，本次 **234/234 通过**（含本篇）。
> - **已复测（本机快照，1.14.3 现场）**：23 个 mod、4,777 个内容文件、去重后 4,750 条相对路径、覆盖原版 107 个文件 + 新增 4,670 个；§1 的「使用率」表逐行复算一致（`localization` 20、`common` 19、`thumbnail.png` 19 + `Thumbnail.png` 4 = 23、`gfx` 10、`events` 6、`gui` 2、`map_data` 1、`fonts` 1、`music`+`sound` 1、`dlc`+`dlc_metadata` 1）；§2 的逐 mod「覆盖/新增」表 10 行也逐行对上（50/1817、16/17、11/29、10/137、7/130、4/819、3/58、3/27、2/31、1/2，其余 13 个 mod 均为 0）。
> - **唯一已知漂移**：§7 那张 `supported_game_version` 表写 `1.13*` 8 / 空 10，本次复算为 `1.13*` 9 / 空 9（`1.13.*` 4、`1.*` 1 两项不变）—— 该表没有生成器看守，差 1 已同步进 §9 第 1 条。
> - **未复测（明确列出）**：§5.1 的 `fonts.font` 语法逐条、§3.5 的 44 个 pattern 逐文件替换清单（都是 1.14.2 采集的正文结论）。
> 已经过自动核验的数量断言见 `v3 verify`（其断言表已更新到 1.14.3）；文档与断言表的一致性由 `tools/tests/test_docs_consistency.py` 持续看守。

## 1. 改造面地图：哪些目录真的被改

**【实测】** 统计每个顶层目录被多少个 mod 触及（共 23 个 mod）：

| 目录 | 使用率 | 说明 |
|---|---|---|
| `.metadata` | **23/23** | 元数据，所有 mod 必有 |
| `thumbnail.png` | **23/23** | 启动器缩略图，所有 mod 必有 |
| `localization` | **20/23** | **文本是最普遍的改造对象** |
| `common` | **19/23** | **脚本数据库，核心改造面** |
| `gfx` | **10/23** | 图标、旗帜、贴图 |
| `events` | **6/23** | 事件脚本 |
| `gui` | **2/23** | 界面布局 |
| `map_data` | 1/23 | 地图数据（州区域） |
| `music` + `sound` | 1/23（同一 mod） | 音频 |
| `fonts` | 1/23 | 字体 |
| `dlc` + `dlc_metadata` | 1/23 | DLC 内容（汉化 mod） |

> **结论**：`common/` + `localization/` 覆盖了绝大多数 mod 的需求。
> 想做一个有价值的 mod，先看这两个目录。

## 2. 最关键发现：**新增 ≫ 覆盖**

**【实测】** 跨 23 个 mod 共 **4,777<!--claim:mod.files--> 个内容文件**（各 mod 的 `metadata.json` 不计入），
去重后是 **4,750 个相对路径**：

```text
被 2 个及以上 mod 共同覆盖的路径数 = 0
```

**零重叠。** 这正是 23 个 mod 能同时启用而互不冲突的根本原因。

进一步统计每个 mod「覆盖原版已有文件」vs「新增自有文件」：

| SteamId | 名称 | 覆盖原版 | 新增 | 覆盖占比 |
|---|---|---|---|---|
| `3507724904` | Dynamic Names, Flags & Colours | 50 | 1,817 | 2.7% |
| `3459869359` | Explorable Real-World Resources | 16 | 17 | 48.5% |
| `2897378189` | Ultra Historical Research & Education | 11 | 29 | 27.5% |
| `2918521358` | Ultra Historical Politics | 10 | 137 | 6.8% |
| `3007678964` | Ultra Historical Warfare | 7 | 130 | 5.1% |
| `3032185644` | More Unique Companies | 4 | 819 | 0.5% |
| `3018606449` | Ultra Historical Diplomacy | 3 | 58 | 4.9% |
| `3227982912` | Kuromi's AI | 3 | 27 | 10.0% |
| `3491107067` | Shocks to the System | 2 | 31 | 6.1% |
| `3117838814` | 萝莉体（字体） | 1 | 2 | 33.3% |
| **其余 13 个** | — | **0** | — | **0%** |

> **13 个 mod 完全不覆盖任何原版文件**，纯靠新增文件实现功能。

### 2.1 这条结论对 mod 开发的指导意义

| 做法 | 冲突风险 | 建议 |
|---|---|---|
| **新增自定义文件** | 无 | ✅ **首选**。用 `前缀_` 命名避免撞名 |
| **用数据功能前缀改原版单条目** | 低 | ✅ **强烈推荐**（`INJECT:` / `REPLACE:` 等，见 §2.2） |
| **覆盖原版文件（整文件替换）** | 与其他 mod 冲突 | ⚠️ 仅在必须整体重写时使用 |

> 这也解释了为什么必须有 `database_conflicts.log` —— 它是覆盖冲突的探测器。

### 2.2 重要修正：真正的「按条目覆盖」机制

**【实测】** 本文早期版本把「覆盖」等同于「整文件替换」，**这个结论不完整**。

Victoria 3 支持在键名前加**数据功能前缀**，从而只改原版的**单个条目**：

```pdx
REPLACE:annex_country = { ... }                    # 整体替换该条目
INJECT:ban_slavery = { ... }                       # 只注入/合并部分字段
INJECT_OR_CREATE:building_food_industry = { ... }  # 存在则注入，不存在则新建
TRY_INJECT:law_concordat = { ... }                 # 注入，目标不存在不报错
```

**六个前缀在 23 个 mod 中的出现次数**（独立复核，规则：行首 `^前缀:键名 = {`）：

| 前缀 | 次数 |
|---|---:|
| `REPLACE_OR_CREATE:` | **1,115** |
| `INJECT:` | **737** |
| `TRY_INJECT:` | **439** |
| `TRY_REPLACE:` | **221** |
| `REPLACE:` | **174** |
| `INJECT_OR_CREATE:` | **46** |

**这解释了本文第 2 节开头那个反直觉的观察**：为什么 4,750 个相对路径里零重叠、23 个 mod 能共存 ——
因为**大多数 mod 根本不替换原版文件，而是用 `INJECT:` 往原版条目里注入字段**。

> ⚠️ 这套机制在游戏自带的 **92 份官方 `.md` 中完全没有记载**（全树搜索命中数为 0），
> 是从真实 mod 的行为反推出来的。完整说明见 `02-Mod结构与加载.md` §5.1。


## 3. 那 5 个「真的覆盖原版」的 mod 改了什么

**【实测】** 这是最有价值的部分：**哪些原版文件是真正需要被替换的**。

### 3.1 `3459869359` Explorable Real-World Resources —— 覆盖全部 16 个州区域文件

```text
map_data\state_regions\00_west_europe.txt      map_data\state_regions\08_middle_east.txt
map_data\state_regions\01_south_europe.txt     map_data\state_regions\09_central_asia.txt
map_data\state_regions\02_east_europe.txt      map_data\state_regions\10_india.txt
map_data\state_regions\03_north_africa.txt     map_data\state_regions\11_east_asia.txt
map_data\state_regions\04_subsaharan_africa.txt map_data\state_regions\12_indonesia.txt
map_data\state_regions\05_north_america.txt    map_data\state_regions\13_australasia.txt
map_data\state_regions\06_central_america.txt  map_data\state_regions\14_siberia.txt
map_data\state_regions\07_south_america.txt    map_data\state_regions\15_russia.txt
```

> **规律**：想改资源分布，必须**逐区域整文件替换** —— `state_regions` 按地理分文件，没有「只改某一处」的粒度。

### 3.2 `2897378189` Ultra Historical Research & Education —— 覆盖 11 个 POP 类型

```text
common\pop_types\  →  academics, aristocrats, bureaucrats, capitalists, clergymen,
                      clerks, engineers, farmers, machinists, officers, shopkeepers
```

> **规律**：`common\pop_types\` 是**每个 POP 一个文件**，改人口机制要逐个替换。

### 3.3 `2918521358` Ultra Historical Politics —— 覆盖全部 8<!--claim:mods.ig_files_doc12--> 个利益集团

```text
common\interest_groups\  →  00_armed_forces, 00_devout, 00_industrialists,
                            00_intelligentsia, 00_landowners, 00_petty_bourgeoisie,
                            00_rural_folk, 00_trade_unions
加上 common\decisions\british_raj_decisions.txt
加上 gfx\interface\icons\law_icons\land_based_taxation.dds
```

> **规律**：`common\interest_groups\` 是**每个 IG 一个文件**（共 8 个），政治类 mod 需要成套替换。

### 3.4 `3007678964` Ultra Historical Warfare —— 覆盖军事系统

```text
common\history\military_formations\00_military_formations_europe.txt
common\history\military_formations\01_military_formations_north_america.txt
common\mobilization_options\00_mobilization_option.txt
common\mobilization_option_groups\00_mobilization_option_groups.txt
events\technology_events.txt
gui\military_formation_panel.gui
gui\panel_military.gui
```

> **规律**：这是唯一一个**同时改了 `.gui` 文件**的 mod —— 说明改军事面板必须动界面布局。

### 3.5 `3507724904` Dynamic Names, Flags & Colours —— 覆盖 50 个，其中 48 个是图形资源

```text
common\coat_of_arms\coat_of_arms\02_overlord_border.txt
common\subject_types\00_subject_types.txt
gfx\coat_of_arms\colored_emblems\  →  ce_crescent / ce_eagle / ce_iron_cross / ce_sun (.dds)
gfx\coat_of_arms\patterns\         →  44 个 pattern_*.dds / pattern_*.tga
```

> **规律**：纹章（coat of arms）系统的图形资源是**逐文件替换**的，44 个 pattern 文件构成旗底纹理库。

## 4. mod 形态分类（按改造面）

**【实测】** 23 个 mod 可归纳为五类：

| 形态 | 特征 | 实例 | 文件数 |
|---|---|---|---|
| **纯文本/汉化** | 只动 `localization/` | `3132637630` 牛奶汉化之超历史系列、`3086429193` 牛奶汉化之公司扩展 | 28 / 6 |
| **纯字体** | 只动 `fonts/` | `3117838814` 萝莉体 | **4** |
| **纯数据调整** | 只动 `common/` | `3647628156` Ultra Historical Workforce、`3656697666` Ultra Historical Companies | 16 / 16 |
| **数据 + 文本** | `common/` + `localization/` | Ultra Historical 系列多数 | 16–148 |
| **内容大修** | `common/` + `events/` + `gfx/` + `gui/` | `3007678964` UH Warfare、`3507724904` Dynamic Names | 138 / 1868 |
| **媒体包** | `music/` + `sound/` | `3533972926` HANE Music | 106 |

## 5. 最小可行 mod：字体 mod（4 个文件）

**【实测】** `3117838814` 萝莉体 是本机**最小的完整 mod**，只有 4 个文件：

```text
.metadata\metadata.json      139 B      ← 元数据
thumbnail.png                825,698 B  ← 启动器缩略图
fonts\fonts.font             26,824 B   ← 字体注册表
fonts\luoliti\luoliti.ttf    10,822,676 B ← 实际字体文件
```

> **这是理解 mod 结构的最佳样本**：`metadata.json` + 资源文件，没有 `common/`、没有脚本。

### 5.1 字体注册文件的语法

**【实测】** `fonts\fonts.font` 的结构（`###` 开头是注释）：

```pdx
### Open Sans (override cw font to support more languages)
fontfiles = {
    name = "Game-OpenSans-Regular"
    always_load = yes

    group = {
        languages = { "l_english" "l_braz_por" "l_french" "l_german" "l_polish" "l_russian" "l_spanish" "l_turkish" }
        files = {
            "fonts/Open_Sans/OpenSans-Regular.ttf"
            "fonts/NotoSans/NotoSansJP-Regular.otf"
            "fonts/NotoSans/NotoSansKR-Regular.otf"
            "fonts/NotoSans/NotoSansSC-Regular.otf"
            "fonts/NotoSans/NotoSans-Regular.ttf"
        }
    }

    group = {
        languages = { "l_japanese" }
        files = {
            "fonts/NotoSans/NotoSansJP-Regular.otf"
            "fonts/Open_Sans/OpenSans-Regular.ttf"
            "fonts/NotoSans/NotoSansKR-Regular.otf"
            "fonts/NotoSans/NotoSansSC-Regular.otf"
            "fonts/NotoSans/NotoSans-Regular.ttf"
        }
    }
}
```

| 字段 | 含义 |
|---|---|
| `fontfiles = { }` | 一个字体组定义块 |
| `name` | 字体组名（如 `Game-OpenSans-Regular`） |
| `always_load = yes` | 是否总是加载 |
| `group = { }` | 按语言分组的字体列表 |
| `group.languages` | 适用语言（`l_japanese`、`l_simp_chinese` 等，**与本地化文件头一致**） |
| `group.files` | 该语言下**按优先级排列**的字体文件列表 |

> **关键点**：`files` 是**列表且有序** —— 前面的字体找不到字形时依次回退到后面的。

## 6. 从 23 个 mod 学到的工程实践

| 实践 | 观察 |
|---|---|
| **文件名加前缀** | `kai_*`（Kuromi's AI）、`ultra_*` 等，避免与原版或其他 mod 撞名 |
| **目录层级照抄原版** | 所有 mod 的 `common/<子目录>/` 结构与原版完全对应 |
| **README / changelog** | `3227982912` 带 19.6 KB README + 10 KB changelog；`2901783277` 带 README |
| **多语言元数据** | `3533972926` HANE Music 甚至带了 `.git` 和 `.gitignore` + Python 脚本 |
| **汉化 mod 的附加文件** | `2880069248` 带 `已经汉化列表.txt`、`更新日志.txt`、`项目组成员.txt`、`暂埋\`、`过期mod\` 等管理性文件 |

## 7. 版本兼容性观察

**【实测】** 各 mod 声明的 `supported_game_version`：

| 声明值 | mod 数 | 实例 |
|---|---|---|
| `1.13*` | 8 | Ultra Historical 系列 |
| `1.13.*` | 4 | More Character Traits、Kuromi's AI、War Is Politics、Shocks to the System |
| `1.*` | 1 | HANE Music |
| **空** | 10 | 汉化 mod、Dynamic Names 等 |

> **重要**：本机游戏是 **1.14.3**（本节结论采集于 1.14.2），而所有 mod 都声明支持 1.13 或留空 —— **全部正常加载且启用**。
> 结论：`supported_game_version` 只影响启动器的兼容性提示，**不会阻止加载**。
> 另外注意 `1.13*` 与 `1.13.*` 两种写法的差异（**是否真的等价未确认**）。

## 8. 对「所有 mod 开发」的实践总结

```text
① 确定改造面
   localization/  → 改文本（20/23 的 mod 都做）
   common/        → 改机制（19/23）
   gfx/           → 改视觉（10/23）
   events/        → 加剧情（6/23）
   gui/           → 改界面（2/23，谨慎）
   map_data/      → 改地图（1/23，最重）

② 优先「新增」而非「覆盖」
   实测 13/23 的 mod 零覆盖，23 个 mod 之间零路径重叠

③ 必须覆盖时，找对粒度
   state_regions  → 按地理分 16 个文件，改一处也要整文件替换
   pop_types      → 每个 POP 一个文件
   interest_groups→ 每个 IG 一个文件
   coat_of_arms   → 逐个图案文件替换

④ 命名加前缀，避免撞名

⑤ 用 -debug_mode 启动，查 error.log / database_conflicts.log
```

## 9. 未确认项

> 证据口径与四条实测配方见 `04-脚本系统.md` §13.1（A 脚本化测试 / B 调试日志 / C 最小 MOD / D 双 MOD 冲突）。
> 本节的 ③ 类证据都是**本机快照**（本机装了哪些 mod 决定数字），复算入口是 `pdx.mods.analyse_all()`。

| # | 未确认内容 | 本地证据（可复算） | 状态 |
|---|---|---|---|
| 1 | 【未确认】`1.13*` 与 `1.13.*` 是否为等价写法 | ③ 本机 23 个 mod 的 `supported_game_version` 实测分布：`1.13*` **9** / `1.13.*` **4** / `1.*` **1** / 空 **9**（本机快照；复算 `pdx.mods.analyse_all()`）——两种写法并存、且**全部正常加载**（§7 结论不变，全表见 §7）；④ exe 里有 `supported_game_version` 字面量（**1 个**，复算 `v3 evidence --exe-grep supported_game_version`），但**没有任何** `1.13*` 形态的字面量（`--exe-grep 1.13` → 0 个）；② 官方 md **91 篇全扫 0 处**提到该字段 | 本地无证据 → 配方 C |
| 2 | 【未确认】覆盖同一原版文件时，多个 mod 的最终生效规则 | ③ 23 个 mod 共 **4,777** 个内容文件、去重后 **4,750** 个相对路径；**被 ≥2 个 mod 命中的路径只有 8 条**，且**没有一条在内容目录**（`common/`、`localization/`、`events/`、`gfx/`、`gui/`、`map_data/` 下 0 条）：`thumbnail.png`×19、`Thumbnail.png`×4、`简介.txt`×2、`README.md`×2、`.idea/{.gitignore,misc.xml,modules.xml,workspace.xml}`×2 —— 即 §2 的「零重叠」在**内容路径**上成立（本机快照，复算同第 1 条）→ 「谁最终生效」**无实例可判** | 【未确认】待实测 → 配方 D |
| 3 | `localization/` 下具体改哪些文件（未逐 mod 展开） | **已答（本机快照，逐 mod 文件条目数）**：20/23 个 mod 带 `localization/`，条目合计 **1,456**（含跨 mod 重复）。逐 mod：`2880069248`（牛奶汉化）**1056**、`2918521358` 88、`3507724904` 72、`3007678964` 55、`3626012595` 33、`3018606449` 33、`3132637630` 26，其余 ≤11；`3227982912`（Kuromi's AI）、`3647628156`、`3117838814`（萝莉体）为 **0**（它只给 `gfx`/`common`）。复算：`overrides + additions` 里 `localization/` 前缀计数 | 已答 |
| 4 | 各 mod 的 `common/` 具体改了哪些键（仅统计了文件级） | **已答（口径从文件级升到条目级，本机快照）**：23 个 mod 在 `common/` 下共 **10,379 条新增条目 + 807 条改原版条目**（`ModInfo.added_entries` / `touched_vanilla`）。文件数/条目数最大的几个：`3507724904` **197 文件 / 5,872 条目**（改原版 10）、`3032185644` 79 / 1,317、`3459869359` 6 / 1,045（改原版 **675**，是本机最激进的一个）、`3656697666` 11 / 591、`3626012595` 29 / 463、`2880069248` 0 文件 / 450 条目。带前缀的键另有**样例**（`ModInfo.prefix_samples`，最多 400 条/mod；按目录的用量见 `v3 prefixes`）。⚠️ 逐键全清单体量大，未抄进文档 —— 但口径已可一条命令现算 | 已答 |
