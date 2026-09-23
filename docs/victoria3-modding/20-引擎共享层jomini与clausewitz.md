# 20 · 引擎共享层：jomini 与 clausewitz

> Victoria 3 的内容有**三层**：`clausewitz\`（引擎底层）→ `jomini\`（通用框架）→ `game\`（游戏内容）。
> mod 主要作用于 `game\`，但另两层也含可被覆盖的数据。本文补齐这一盲区。**【实测】**

> **版本提示（精确清单）**：本机游戏是 **1.14.4 (Ice Tea)**（版本指纹 `env.caligula_rev` = `d369a59ea65e68d4cca455ddd558c497958927f9`、`env.caligula_branch` = `release/1.14.4`，两条断言本次 `v3 verify` 已核验）。原先那句笼统的「统计采集于 1.14.2」按类拆开：
> - **已是 1.14.4 —— 表格已重算**：本篇 **1 张**表（`doc20 clausewitz 子目录`）由 `v3 tables` 生成；本次 `v3 tables` 核对**全部 171 张生成表都与文档一致**。
> - **已是 1.14.4 —— 断言已核验**：本篇 **1 条** `eng.*` 断言随 `v3 verify` 现场重扫，本次 **234/234 通过**（含本篇）、**210 处**归属标记全部对上。
> - **已复测的数字**（1.14.3 现场实测，原为 1.14.2 采集）：`clausewitz` 七个一级子目录 = `fonts` 46 / `gfx` 547 / `gui` 68 / `imgui_fonts` 2 / `input_profile` 19 / `localization` 68 / `tools` 1（七项合计 753）；`jomini` 六个一级子目录 = `common` 25 / `gfx` 134 / `gui` 99 / `jomini` 1 / `localization` 231 / `notifications` 2（六项合计 493）；`jomini\common\` = 5 个子目录 + 1 个 `.md`；`jomini\common\defines\` = 18 个文件 —— 四项与 §1 / §2 / §3 表逐一相符。
> - **未复测（明确列出）**：§5 三份 readme 的**字节数**（内容本轮已读全，见 §7）、§4 的 `jomini\localization\` 键覆盖实例（`MODIFIER_DESCRIPTION_ENTRY`）、§1 表里 `game\` 的 27,723（该数字由 `08-目录全量清单.md` 的生成表看守）。
> 已经过自动核验的数量断言见 `v3 verify`（其断言表已更新到 1.14.4）；文档与断言表的一致性由 `tools/tests/test_docs_consistency.py` 持续看守。

## 1. 三层架构

```text
C:\...\common\Victoria 3\
├─ clausewitz\    引擎底层：字体、通用 gfx/gui、输入配置、编辑器 UI
├─ jomini\        通用框架：纹章、提示、相机、迷雾、多人、文本格式化
└─ game\          游戏内容：脚本数据库、事件、本地化、地图 ← mod 的覆盖目标
```

| 层 | 子目录 | 文件数 | 说明 |
|---|---|---|---|
| `clausewitz\` | fonts / gfx / gui / imgui_fonts / input_profile / localization / tools | 46 / **547** / 68 / 2 / 19 / 68 / 1 | 另含 `compound_settings.txt`(1,110 B)、`cw_flow_graphs.anchor` |
| `jomini\` | common / gfx / gui / jomini / localization / notifications | 25 / 134 / 99 / 1 / **231** / 2 | 另含 `settings_layout.txt`(1,229 B) |
| `game\` | **19 个一级目录**（另有 13 个根级松散文件） | **27,723** | 见 `08-目录全量清单.md` |

## 2. `jomini\common\` —— 18 个 defines 命名空间

**【实测】** `jomini\common\` 下有 5<!--claim:eng.jomini_subdirs_doc20--> 个子目录 + 1 个说明文件：

```text
jomini\common\
├─ coat_of_arms\        （内层再分 coat_of_arms\、options\、template_lists\，各带一份 readme —— 其中一份名为 read_me.txt）
├─ defines\
├─ named_colors\
├─ script_values\       （含 _script_values.info，3,745 B）
├─ trigger_localization\
└─ audio_persistent_objects.md  (805 B)
```

### 2.1 defines 命名空间完整清单

**【实测】** `jomini\common\defines\` 下 **18 个文件**，提取到的命名空间块：

| 文件 | 命名空间块 |
|---|---|
| `00_adaptive_music.txt` | `NAdaptiveMusic` |
| `00_audio_persistent_objects.txt` | `music_manager` |
| `music_player_defines.txt` | `NJominiMusicPlayer`（+ 若干颜色常量） |
| `graphic\00_coa.txt` | `NCoatOfArms`（+ `FALLBACK_COLOR`） |
| `jomini\00_tooltips.txt` | `NTooltip`（+ `TOOLTIP_TINT_RGBA`） |
| `jomini\adjacencies.txt` | `NAdjacencies` |
| `jomini\camera.txt` | `NCamera` |
| `jomini\fog_of_war.txt` | `NFogOfWar`（+ `PATTERN_SPEED`） |
| `jomini\icons.txt` | `NJominiIcons`（+ `MODIFIER_TEXT_ICON_SIZE`、`MODIFIER_TEXT_ICON_OFFSET`） |
| `jomini\mapeditor.txt` | `NMapEditor`（+ `MAP_CONTENT_GROUPING_COLOR` 等） |
| `jomini\modifiers.txt` | `NJominiModifiers` |
| `jomini\multiplayer.txt` | `NJominiMultiplayer` |
| `jomini\portraits.txt` | `NJominiPortraits` |
| `jomini\rivers.txt` | `NRivers` |
| `jomini\settings.txt` | `NJominiSettings` |
| `jomini\social.txt` | `NJominiSocial`（+ 聊天颜色常量） |
| `jomini\text_coloring.txt` | `NTextColoring` |
| `jomini\text_formatting.txt` | `NTextFormatting` |

> **命名规律**：Jomini 层的命名空间多以 `NJomini*` 或 `N<系统>` 命名，
> 与 `game\common\defines\` 下的 `NAI`、`NCountry` 等并列存在于**同一套 defines 系统**中。

### 2.2 对 mod 的意义

defines 系统按「命名空间 + 参数名」索引，**与文件路径无关**。因此：

- 理论上，mod 在自己的 `common\defines\` 里写 `NJominiSettings = { ... }` 即可覆盖 Jomini 层参数
  （依据：`game\common\defines\` 与 `jomini\common\defines\` 内容合并进同一数据库）
- 但 **23 个已订阅 mod 中无一这样做** —— 该做法**未经实测验证**，标为 **【未确认】**

## 3. `clausewitz\` —— 引擎底层

**【实测】** 7 个子目录：

| 子目录 | 文件数 | 内容 |
|---|---|---|
| `gfx\` | **547** | 引擎级图形资源（编辑器 UI、调试素材等） |
| `gui\` | 68 | 引擎级界面（含 `tools\dockable_layout_manager.gui`） |
| `localization\` | 68 | 引擎级本地化 |
| `fonts\` | 46 | 引擎字体（见 §3.1） |
| `input_profile\` | 19 | 输入配置 |
| `imgui_fonts\` | 2 | 开发者界面字体 |
| `tools\` | 1 | 工具 |

另含 `compound_settings.txt`(1,110 B) 与 `cw_flow_graphs.anchor`(16 B)。

### 3.1 `clausewitz\fonts\` —— 引擎字体与 mod 字体系统的关系

**【实测】** 结构：

```text
clausewitz\fonts\
├─ cw_fonts.font          15,167 B   ← 引擎字体注册表
├─ NotoSans\              (NotoSans-Regular/Bold/Italic/BoldItalic.ttf + OFL.txt)
│   ├─ NotoSansJP-{Thin,Light,Regular,Medium,Bold,Black}.otf
│   ├─ NotoSansKR-{...}.otf
│   └─ NotoSansSC-{...}.otf    ← 简体中文（最大者 8.9 MB）
├─ Open_Sans\             (OpenSans-*.ttf + LICENSE.txt)
└─ Roboto_Mono\
```

> **这解释了一个常见疑问**：游戏**本来就自带 Unicode CJK 字体**（NotoSansJP/KR/SC 全套 6 种字重）。
> 因此做中文 mod **通常不需要自己带字体文件**，只要本地化语言是 `l_simp_chinese` 即可正常显示。
> 自带字体 mod（如本机的「萝莉体」）属于**替换外观**而非**补齐字形**。

`fonts\fonts.font`（game 层）与 `clausewitz\fonts\cw_fonts.font` 是两个不同的注册表 ——
前者定义游戏字体组，后者定义引擎字体。完整 `fonts.font` 语法见 `12-真实mod解剖与改造面地图.md` §5.1。

## 4. `jomini\localization\` —— 231 个文件的本地化覆盖

**【实测】** 与 `game\localization\` 并存。`06-本地化与界面资源.md` 已证实一条关键机制：

> **本地化是按键覆盖而非按文件替换**

证据：`MODIFIER_DESCRIPTION_ENTRY` 在
`jomini\localization\modifiers\modifiers_l_english.yml:2` 与
`game\localization\modifiers\modifiers_l_english.yml:2` 各定义一次，**取值不同**。

> **对 mod 的意义**：修改某个本地化键时，只需在自己的 `localization\` 里定义**同名的键**，
> 无论原版把它放在哪一层、哪个文件，都会被覆盖。

## 5. `jomini\common\coat_of_arms\` —— 纹章系统的三份 readme

**【实测】** 该目录带三份 readme（路径注意 `coat_of_arms` 是**两层同名目录**）：

| 文件 | 字节 |
|---|---|
| `coat_of_arms\coat_of_arms\read_me.txt` | 71 |
| `coat_of_arms\options\readme.txt` | 242 |
| `coat_of_arms\template_lists\readme.txt` | 1,153 |

> 这三份是纹章系统的官方说明。结合 `game\common\coat_of_arms\`（23 文件）
> 与 `12-真实mod解剖与改造面地图.md` §3.5（真实 mod 逐文件替换 44 个 pattern），
> 构成完整的纹章改造知识。

## 6. mod 能否覆盖 jomini / clausewitz？

| 问题 | 结论 |
|---|---|
| mod 能否提供 `jomini\` 或 `clausewitz\` 目录？ | **未确认** —— 23 个 mod 的**内容目录**只有 `common/events/gfx/gui/localization/map_data/music/sound/fonts/dlc/dlc_metadata`（另有 `.metadata/` 以及 `.idea/`、`.git/` 等编辑器目录），**无一使用 `jomini/` 或 `clausewitz/`** |
| defines 参数能否跨层覆盖？ | **【推断】可以**（defines 按命名空间索引，与文件路径无关），但**未实测** |
| 本地化能否覆盖 jomini 层的键？ | **【实测】可以**（见 §4） |

## 7. 未确认项

> 证据口径与四条实测配方见 `04-脚本系统.md` §13.1（A 脚本化测试 / B 调试日志 / C 最小 MOD / D 双 MOD 冲突）。

| # | 未确认内容 | 本地证据（可复算） | 状态 |
|---|---|---|---|
| 1 | 【未确认】mod 提供 `jomini\` 目录是否被加载 | ③ 本机 23 个 mod 的**顶层条目**里 `jomini/`、`clausewitz/` 各 **0 个**（本机快照，复算：`pdx.mods.analyse_all()` 的 `top_entries`，即 §6 那张内容目录清单的来源）；② 官方 md **91 篇全扫 0 处**提到 `jomini`/`clausewitz`；④ exe 里有 **40 个**含 `jomini` 的标识符（`CJominiCustomTextDatabase`、`CJominiLineDatabase`、`CJominiNamedValueDatabase`…，复算：`v3 evidence --exe-grep jomini`）→ 引擎认识 jomini 层，但「mod 目录会不会被加载」本地无实例 | 待实测 → 配方 C |
| 2 | 【未确认】mod 覆盖 `NJomini*` 命名空间 defines 是否生效 | ① `jomini\common\defines\jomini\settings.txt:1` 逐字 `NJominiSettings = {`（该文件是 §2.1 那 18 个 defines 文件之一，命名空间定义在 **Jomini 层**、不在 `game\`）；④ exe 有 `NJominiSettings`、`NJominiPortraits` 两个字面量，邻居是 `JOMINI_SETTINGS_RECOMMENDED`、`CPortraitDecalDatabase` 一族（复算：`v3 evidence NJominiSettings NJominiPortraits`）；③ 本机 23 个 mod 在 `common/defines/` 下 **0 个** `NJomini*` 键（本机快照） | 待实测 → 配方 C |
| 3 | `jomini\jomini\gui\encyclopedia\jomini_encyclopedia.gui`（4,731 B） | **已答**：教科书窗口的 GUI 定义（`window = { name = "jomini_encyclopedia" using = editor_window … }`，色板用 Ubuntu 终端配色）——**与 mod 开发基本无关**，原表结论不变 | 已答 |
| 4 | `clausewitz\tools\pdx_node_editor.settings`（8,670 B） | **已答**：节点编辑器的窗口布局设置——**与 mod 开发无关**，原表结论不变 | 已答 |
| 5 | 三份 coat_of_arms readme 的具体内容 | **已答（本轮读全）**：`coat_of_arms\coat_of_arms\read_me.txt` **1 行**，逐字 `# Here you will put prescripted coat of arms and coat of arms templates`；`coat_of_arms\options\readme.txt` **9 行**，规定 atlas 只允许两种尺寸（`tile_size = { 512 512 }` + `nr_of_tiles = 4`；`tile_size = { 256 256 }` + `nr_of_tiles = 16`）；`coat_of_arms\template_lists\readme.txt` **68 行、全部是注释**，给出 5 类 list 的语法示例（`coat_of_arms_template_lists`、`textured_emblem_texture_lists`、`colored_emblem_texture_lists`、`pattern_texture_lists`、`color_lists`）——⚠️ 示例**全部被注释**，不构成实际用法（口径同 `04-脚本系统.md` §13.1） | 已答 |
| 6 | `jomini\common\script_values\_script_values.info` | **已答（本轮读全）**：**113 行**官方说明，两节 `== Static values ==`（`:5`）与 `== Formulas ==`（`:12`），另分 `=== Execution order ===`（`:61`）、`=== Inlining ===`（`:72`）、`=== Chaining ===`（`:84`）、`== Ranges ==`（`:94`）、`== Lists ==`（`:100`）、`== Scoping ==`（`:105`）；公式算子逐字列出：`add` / `subtract` / `multiply` / `divide` / `modulo` / `value` / `max` / `min` / `round` / `ceiling` / `floor` / `if` / `else_if` / `else` / `fixed_range` / `integer_range` | 已答 |
