# 20 · 引擎共享层：jomini 与 clausewitz

> Victoria 3 的内容有**三层**：`clausewitz\`（引擎底层）→ `jomini\`（通用框架）→ `game\`（游戏内容）。
> mod 主要作用于 `game\`，但另两层也含可被覆盖的数据。本文补齐这一盲区。**【实测】**

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
| `game\` | **19 个一级目录**（另有 13 个根级松散文件） | **27,724** | 见 `08-目录全量清单.md` |

## 2. `jomini\common\` —— 18 个 defines 命名空间

**【实测】** `jomini\common\` 下有 5 个子目录 + 1 个说明文件：

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

| 项 | 状态 |
|---|---|
| mod 提供 `jomini\` 目录是否被加载 | **未确认** |
| mod 覆盖 `NJomini*` 命名空间 defines 是否生效 | **未确认** |
| `jomini\jomini\gui\encyclopedia\jomini_encyclopedia.gui`（4,731 B） | 已读：教科书窗口的 GUI 定义（`window = { name = "jomini_encyclopedia" using = editor_window … }`，色板用 Ubuntu 终端配色）。**与 mod 开发基本无关** |
| `clausewitz\tools\pdx_node_editor.settings`（8,670 B） | 已读：节点编辑器的窗口布局设置，**与 mod 开发无关** |
| 三份 coat_of_arms readme 的具体内容 | **未读**（官方纹章说明，路径见 §5） |
| `jomini\common\script_values\_script_values.info` | **未读**（3,745 B，疑似官方说明） |
