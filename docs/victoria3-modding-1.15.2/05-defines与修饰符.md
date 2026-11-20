# 05 · defines 与修饰符

> 本页采用 Victoria 3 1.15.2 静态安装证据。登记断言使用 `claim` 标记。官方文档路径和指纹见 `research/official-docs-1.15.2.manifest.json`。正文保留早期研究、机器快照和订阅时点的原有标记。

> **历史采集版本**：Victoria 3 **1.14.5 (Ice Tea)**（本文的模块结构统计已重测到 1.14.5；个别标注为 1.14.2 的结论为历史采集值）
> 历史采集的版本依据：`launcher\launcher-settings.json` → `"version": "1.14.5 (Ice Tea)"`、`"rawVersion": "1.14.5"`；`caligula_branch.txt` → `release/1.14.5`；`clausewitz_branch.txt` → `caligula/release/1.14.x`
> **内容根（下文简称 `GAME`）**：`C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game`
> **安装根**：`C:\Program Files (x86)\Steam\steamapps\common\Victoria 3`

本文覆盖四套彼此不同、但经常一起使用的「数值调节」机制：

| 机制 | 目录 | 作用 | 本文位置 |
|---|---|---|---|
| **defines** | `common\defines\` | 引擎级全局静态常量（AI 权重、阈值、摄像机、音频路径…） | §1–§3 |
| **game_rules** | `common\game_rules\` | 开局可选的规则开关，输出「flag」给脚本判断 | §4 |
| **modifier types** | `common\modifier_type_definitions\` | 定义「一个修饰符键」的显示方式与流动作用域 | §5 |
| **static modifiers** | `common\static_modifiers\` | 具名、可被脚本 `add_modifier` 施加的修正包 | §6 |
| **scripted modifiers** | `common\scripted_modifiers\` | 1.14.2 中**只有一份说明文档，无任何实际内容** | §7 |

---

## 0. 提取方法与证据约定

### 0.1 证据标记

全文每条断言都标注来源。标记含义：

| 标记 | 含义 |
|---|---|
| 【提取】 | 由脚本从实际游戏文件机械提取，附文件路径（+ 行号） |
| 【注释】 | 摘录原版文件内的开发者注释 |
| 【文档】 | 原版随游戏附带的 `.md` 说明文件 |
| 【Wiki】 | Victoria 3 官方 Wiki（版本页标注 verified for 1.13，早于采集时点的 1.14.2） |
| 【推断】 | 基于上述证据的推论，未直接验证 |
| **【未确认】** | 本地文件无法确证，需实机或引擎日志验证 |

### 0.2 提取脚本

下列命令在工作区可随时复跑核对（工具链为 Python 实现，见 `tools/README.md`）：

| 命令 | 作用 |
|---|---|
| `v3 defines --ns NAI` | 展开某个 defines 命名空间的全部参数 |
| `v3 defines --json <路径>` | 把提取结果落盘为 JSON |
| `v3 defines --overlay <文件>` | 预览一段 mod defines 会覆盖哪些原版参数 |
| `v3 analyze` | 全量分析，落盘 `tools/out/` 下的全部产物 |

> 早期这些工作由 5 个 PowerShell 脚本完成（`extract_defines.ps1` /
> `dump_precise.ps1` / `dump_misc.ps1` / `make_frags.ps1` / `make_gamerules.ps1`），
> 它们**已全部退休**：PowerShell 的编码陷阱与无法写测试两点让它不可维护。

> ⚠️ **§2.1 / §2.2 / §2.5 / §2.6 与 §1.6 的表格已按 1.14.3 重算。**
> 这几张表原先由那批 PowerShell 脚本产出，数值停留在 1.14.2：
> 1.14.3 给 `NMilitary` 增加了 1 个参数、给 `NDiplomacy` 增加了 39 个，
> 于是 `00_defines.txt` 之后所有块的**起始行号整体后移 40 行**、
> 参数总数从 3434 涨到 **3597**<!--claim:def.param_total-->。现在这些数字由仓库内的解析器
> （`pdx.parser`，口径见 §0.3）重新生成，并由 `v3 verify` 的
> `def.param_total` / `def.param_names` 两条断言钉住。

### 0.3 计数口径（重要）

本文所有计数统一按下列口径，避免误读：

| 术语 | 定义 |
|---|---|
| **顶层命名空间块** | 文件中花括号深度 0→1、形如 `Nxxx = { ... }` 的块 |
| **标量参数** | 块内深度 1 的 `KEY = value`，值是标量（含 `KEY =` 空值） |
| **内联列表参数** | 块内深度 1 的 `KEY = { a b c }`，**块内只有裸值、没有任何 `KEY = value`** |
| **嵌套块** | 块内深度 1 的 `KEY = { ... }`，**块内含有 `KEY = value` 赋值** |

「参数」在无特别说明时 = 标量 + 内联列表 + 嵌套块三者之和。

> **口径补记（1.14.3 重算时修正）**：内联列表与嵌套块的界线是**块里有没有赋值**，
> 而**不是**「是否写在同一行」。早先按行数区分，于是把跨行书写的
> `KEY = { a b c }`（值仍是纯列表）记成了嵌套块 —— 那是排版差异，不是语义差异；
> `jomini/00_tooltips.txt` 的 `NTooltip` 正是这种写法。
> 现在这条界线由 `pdx.defines._classify` 单点决定，且下面 5 张表全部由
> **`v3 tables --write`** 生成，不再手抄（它们此前因为无人重跑，
> 整整落后了一个游戏版本）。

> **关于表格语言与生成**：普通表头使用中文，表头定义由 `pdx.defines`、`pdx.modifiers` 维护，数据行通过 `v3 tables --write` 生成。命名空间名、参数名和文件名保留实际接口值；快照使用稳定的文档名与表名定位，表头翻译不改变提取口径或数据行。

> **关于行号**：全文所有行号均为**物理行号**（1-based），可直接用于在编辑器中跳转。

### 0.4 全局规模（实测）

| 指标 | 数值 | 来源 |
|---|---|---|
| `common\defines\` 下 `.txt` 文件数 | **9**（根目录 6 + `jomini\` 子目录 3） | 【提取】递归枚举 `common\defines\` |
| 顶层命名空间块总数 | **77** | 【提取】§2.2 |
| 去重后命名空间数 | **52** | 【提取】§1.6 |
| 参数条目总数 | **3597**（标量 3409 + 内联列表 188 + 嵌套块 0） | 【提取】§2.1 汇总 |
| 去重后参数名数 | **3590**（有 7 次跨块重复出现） | 【提取】 |

> **解析器口径提示**：`00_shaders.txt` 第 1-2 行是 PDX 的另一种写法——`NShadersCommon =` 与 `{` 分行。全库 9 个 defines 文件中**只有这一处**采用该写法（脚本已逐文件校验：其余文件均无"行尾为 `=`"的情况）。本文的解析器已处理该情形，行号一律为**物理行号**。

---

## 1. defines 系统

### 1.1 用途

defines 是**引擎侧（C++）读取的全局静态常量**，用于调节那些不开放给脚本的游戏行为：IG 支持度阈值、摄像机 FOV、AI 评分权重、Pop 增长曲线、音频事件路径等。【Wiki】

三条关键性质：

1. **静态且全局**——作用于整局游戏，不能在脚本运行时动态修改。【Wiki】
2. **键名与类型由 C++ 侧硬编码**——mod 只能改**值**，不能新增一个引擎会去读取的 define 键；键名拼错既不生效也不报错。【推断】
3. **与 `game_rules` / `static_modifiers` 是不同机制**：`game_rules` 是开局选项开关（§4），`static_modifiers` 是可施加的数值修正包（§6）。

### 1.2 目录结构与内容根

在安装根下递归搜索名为 `defines` 的目录，`defines` 本体只出现一次（`GAME\common\defines`），但 defines **内容**由多个「内容根（content root）」分层提供：【提取】

| 内容根 | 路径 | defines 文件数 |
|---|---|---|
| **game** | `...\Victoria 3\game\common\defines\` | 6（根）+ 3（`jomini\` 子目录） |
| **jomini** | `...\Victoria 3\jomini\common\defines\` | 18（含 `jomini\`、`graphic\` 两处子目录） |
| clausewitz | `...\Victoria 3\clausewitz\` | 0（该目录下无 `common\defines`）【提取】 |

`jomini\common\defines\` 的完整文件清单（18 个）：`00_adaptive_music.txt`、`00_audio_persistent_objects.txt`、`music_player_defines.txt`、`graphic\00_coa.txt`、`jomini\00_tooltips.txt`、`jomini\adjacencies.txt`、`jomini\camera.txt`、`jomini\fog_of_war.txt`、`jomini\icons.txt`、`jomini\mapeditor.txt`、`jomini\modifiers.txt`、`jomini\multiplayer.txt`、`jomini\portraits.txt`、`jomini\rivers.txt`、`jomini\settings.txt`、`jomini\social.txt`、`jomini\text_coloring.txt`、`jomini\text_formatting.txt`。【提取】

**子目录会被递归加载**——这是覆盖机制的关键，见 §1.7。

### 1.3 文件命名规范

| 规范 | 说明 |
|---|---|
| 形式 | `NN_描述.txt`，`NN` 为数字前缀 |
| 作用 | **控制加载顺序**（`00_` 先于 `01_`）；前缀本身不进入命名空间或键名 |
| 为什么重要 | 多个文件/mod 修改同一个 define 时，「最后加载的文件名」决定最终值【Wiki】 |
| 子目录 | 允许，相对路径会被保留（原版自己就在 `common\defines\` 下建了 `jomini\` 子目录） |

原版实际使用的 9 个文件名见 §2.1。

### 1.4 语法要素

全部示例摘自实际文件。

**1）命名空间块**（顶层，必须以 `N` 开头）

原始示例与取证上下文见本篇对应的历史知识库章节。
来源：`GAME\common\defines\00_audio.txt` 第 1 行起。【提取】

**2）标量参数**

原始示例与取证上下文见本篇对应的历史知识库章节。
来源：`GAME\common\defines\00_ai.txt` 第 55、15、17 行。【提取】

**3）内联列表参数**（同一行闭合）

原始示例与取证上下文见本篇对应的历史知识库章节。
来源：`GAME\common\defines\00_graphics.txt`（`NMapMode` 块）。这类内联列表参数全库共 **188**<!--claim:def.inline_list_total--> 条（1.14.2 时是 168；口径见 §0.3）。【提取】

**4）嵌套块**（跨多行）

原始示例与取证上下文见本篇对应的历史知识库章节。
来源：`GAME\common\defines\jomini\00_tooltips.txt`。全库仅 3 条。【提取】

**5）注释**：`#` 到行尾。原版 defines 的注释密度极高，是理解每个参数语义的第一手资料。

**6）块内局部脚本变量 `@name`**

原始示例与取证上下文见本篇对应的历史知识库章节。
来源：`GAME\common\defines\00_graphics.txt` 第 5、46、47 行。【提取】

**7）顶层脚本变量 + 表达式 `@[ ... ]`**

原始示例与取证上下文见本篇对应的历史知识库章节。
来源：`GAME\common\defines\00_defines.txt`。【提取】

`@[...]` 内支持 `+ - * /` 与括号；`00_defines.txt` 第 1660-1661 行还有块内定义的例子：

原始示例与取证上下文见本篇对应的历史知识库章节。

**8）其它字面量写法**

| 写法 | 例子 | 来源 |
|---|---|---|
| 浮点后缀 `f` | `OPEN_DELAYED_TIME = 0.3f;`、`DISTANCE_FADE_START = 100.0f` | `jomini\00_tooltips.txt`、`00_graphics.txt` |
| 布尔 | `INTERACTIVE_MAP_MODE = yes` / `no` | 各处 |
| 带引号字符串 | `DEFAULT_STRATEGY_STRING = "ai_strategy_default"` | `00_ai.txt` |
| 行尾分号（可选） | `TENDENCY_BUFFER = 3;` | `jomini\00_tooltips.txt`（Jomini 风格） |
| 负数 | `country_bureaucracy_mult = -0.1` | `static_modifiers` |

### 1.5 命名规范（机械校验结果）

| 规则 | 校验结果 | 依据 |
|---|---|---|
| 顶层块名必须以 `N` 开头 | **75 / 75 符合，0 例外** | 【提取】脚本校验 `$ns.StartsWith('N')` |
| 参数名应为全大写 `SNAKE_CASE` | **3481 个去重参数名中仅 4 个例外**，且全部在同一个文件 | 【提取】 |
| 命名空间命名风格 | `N` + 大驼峰英文（`NAI`、`NCountry`、`NEconomy`、`NPowerBlocs`…） | §1.6 |

4 个例外（`GAME\common\defines\00_audio.txt`，用于拼接音频事件路径 `MAP_LENS_<map_mode_key>`）：

原始示例与取证上下文见本篇对应的历史知识库章节。
——即**前缀大写 + 后缀小写**的拼接式命名，说明引擎允许参数名含小写，只是原版几乎不用。

其余规则：键名形如 `[A-Z][A-Z0-9_]*`，无前导/尾随下划线，无连字符。【提取】

### 1.6 全部命名空间清单

下表由脚本按命名空间聚合，“参数数”为该命名空间在**全部文件**中的参数条目总和（含重复块累加）。完整逐块明细（第 2 节）见 §2.2。

| 命名空间 | 块数 | 参数数 | 文件 |
|---|---|---|---|
| `NAI` | 1 | 1025 | 00_ai.txt |
| `NAudio` | 1 | 24 | 00_audio.txt |
| `NBattle` | 1 | 66 | 00_defines.txt |
| `NCamera` | 1 | 18 | 00_graphics.txt |
| `NCharacterPanelViewer` | 1 | 15 | 00_graphics.txt |
| `NCharacters` | 1 | 103 | 00_defines.txt |
| `NCities` | 1 | 28 | 00_graphics.txt |
| `NCoasts` | 1 | 6 | 00_graphics.txt |
| `NCountry` | 1 | 45 | 00_defines.txt |
| `NDebug` | 1 | 3 | 00_defines.txt |
| `NDiplomacy` | 1 | 401 | 00_defines.txt |
| `NEconomy` | 1 | 306 | 00_defines.txt |
| `NEdgeOfWorld` | 1 | 19 | 00_shaders.txt |
| `NEvents` | 1 | 3 | 00_defines.txt |
| `NFogOfWar` | 1 | 23 | jomini/fog_of_war.txt |
| `NFortifications` | 1 | 5 | 00_graphics.txt |
| `NFrontend` | 1 | 3 | 00_graphics.txt |
| `NGUI` | 24 | 199 | 00_interfaces.txt |
| `NGame` | 1 | 5 | 00_defines.txt |
| `NGraphics` | 1 | 174 | 00_graphics.txt |
| `NGuiFlag` | 1 | 3 | 00_shaders.txt |
| `NHarvestConditions` | 1 | 2 | 00_defines.txt |
| `NJominiEars` | 1 | 2 | 00_graphics.txt |
| `NJominiGraphics` | 1 | 3 | 00_graphics.txt |
| `NJominiMap` | 1 | 4 | 00_defines.txt |
| `NJominiMapGraphics` | 1 | 11 | 00_graphics.txt |
| `NLenses` | 1 | 9 | 00_interfaces.txt |
| `NMapCoa` | 1 | 11 | 00_shaders.txt |
| `NMapMode` | 1 | 103 | 00_graphics.txt |
| `NMapName` | 1 | 8 | 00_graphics.txt |
| `NMapmodeStripes` | 1 | 6 | 00_shaders.txt |
| `NMilitary` | 1 | 143 | 00_defines.txt |
| `NNavy` | 1 | 109 | 00_graphics.txt |
| `NPolitics` | 1 | 206 | 00_defines.txt |
| `NPops` | 2 | 226 | 00_defines.txt |
| `NPortrait` | 1 | 5 | 00_graphics.txt |
| `NPowerBlocCoa` | 1 | 21 | 00_graphics.txt |
| `NPowerBlocStatueCamera` | 1 | 7 | 00_graphics.txt |
| `NPowerBlocs` | 1 | 23 | 00_defines.txt |
| `NProvinceHighlight` | 1 | 4 | 00_graphics.txt |
| `NRivers` | 1 | 6 | jomini/rivers.txt |
| `NRoutes` | 1 | 9 | 00_graphics.txt |
| `NSaves` | 1 | 1 | 00_interfaces.txt |
| `NSeasons` | 1 | 19 | 00_defines.txt |
| `NShadersCommon` | 1 | 1 | 00_shaders.txt |
| `NShipViewer` | 1 | 22 | 00_graphics.txt |
| `NTechnology` | 1 | 4 | 00_defines.txt |
| `NText` | 1 | 6 | 00_defines.txt |
| `NTooltip` | 1 | 7 | jomini/00_tooltips.txt |
| `NTravelNetwork` | 2 | 54 | 00_defines.txt, 00_graphics.txt |
| `NTrend` | 1 | 2 | 00_interfaces.txt |
| `NWar` | 1 | 89 | 00_defines.txt |

---

### 1.7 defines 的覆盖机制 ★

这是 defines 系统里最容易搞错的一点，也是 full-file 复制派与 minimal 覆盖派争论的焦点。下面给出四条**可复现的证据**，然后给出结论与推荐写法。

#### 结论先行

| 场景 | 引擎行为 | 证据 |
|---|---|---|
| mod 新建 `common/defines/01_mymod.txt`，里面只写 `NCountry = { KEY = v }` | **按命名空间块名合并、按参数名覆盖**，**不需要**复制整个原文件 | 证据 1、2、4 |
| 同一加载层内，多个文件 / 多个重复块声明同一个 `Nxxx` | 合并；同名参数由后出现者覆盖 | 证据 2 |
| 两个内容根下**相对路径完全相同**的文件 | 后加载的内容根**整体接管**该文件 | 证据 3 |
| 多个 mod 修改同一个 define | 「最后加载的文件名」决定最终值 | 证据 4（Wiki 原文） |

#### 证据 1：不同文件名、不同内容根声明同一命名空间 → 合并（最硬）

`NCamera` 被两个**文件名不同、内容根不同**的文件声明：

| 来源文件 | 声明内容 |
|---|---|
| `...\Victoria 3\jomini\common\defines\jomini\camera.txt` | `NCamera = { DEBUG_WIDTH = 400, DEBUG_HEIGHT = 800, DEBUG_TOP = 100, DEBUG_SHIFT_FROM_LEFT = 300 }` |
| `GAME\common\defines\00_graphics.txt` 第 419 行 | `NCamera = { FOV, ZNEAR, ZFAR, EDGE_SCROLLING_PIXELS, SCROLL_SPEED, ZOOM_RATE, MAX_PAN_TO_ZOOM_STEP_EXTRA_CLOSE, MAX_PAN_TO_ZOOM_STEP_CLOSE, MAX_PAN_TO_ZOOM_STEP_FAR, MAX_PAN_TO_ZOOM_STEP_EXTRA_FAR, DEBUG_GAMEPAD_LOWSPEED, DEBUG_GAMEPAD_NORMALSPEED, DEBUG_GAMEPAD_HIGHSPEED, DEBUG_GAMEPAD_SENSITIVITY }`（14 项） |

【提取】脚本已确认：`game\common\defines\00_graphics.txt` 的 `NCamera` 块**完全没有**重新声明 jomini 的 4 个 `DEBUG_*` 键；而在整个 `common\defines\` 树中，`DEBUG_WIDTH` / `DEBUG_HEIGHT` / `DEBUG_TOP` / `DEBUG_SHIFT_FROM_LEFT` 这 4 个键**各自只出现一次**，都在 `jomini\camera.txt`。

如果引擎采用「同名块整块替换」，jomini 层这 4 个调试摄像机参数将永远无法生效，原版也没有任何地方重新声明它们。因此引擎必须**按命名空间块名跨文件合并**。【提取 + 推断】

#### 证据 2：同一文件内同名块重复出现

> 📌 **本表与下面几张「单文件」表的行号列**（「各块起始行」「起始行」）是**时点快照**，
> 由作者维护：行号由排版决定，改一行就全废，所以**不纳入 `v3 tables` 的生成范围**。
> 其余数字列（出现次数、标量 / 内联列表 / 嵌套 / 合计）每次 `v3 tables` 都会重算。

| 文件 | 重复的命名空间 | 出现次数 | 各块参数数 |
|---|---|---|---|
| `GAME\common\defines\00_defines.txt` | `NPops` | **2** | 第 1404 行 209 条；第 1773 行 16 条 |
| `GAME\common\defines\00_interfaces.txt` | `NGUI` | **24** | 合计 189 条（第 13、17、95、100、110、130、142、153、163、172、176、182、189、194、199、203、216、226、230、235、246、250、254、303 行） |

【提取】

若「同名块整块替换」成立，`00_defines.txt` 第 1773 行的 `NPops`（16 条）会把第 1404 行的 `NPops`（209 条）整体抹掉——`NUM_WEALTH_LEVELS`、`POP_WEIGHT_MODIFIER_MAX_SCALE` 等全部失效，游戏不可能正常运行。同理 `00_interfaces.txt` 里 24 个 `NGUI` 块只会剩最后一个。

→ **同一加载层内，`Nxxx` 是"聚合命名空间"，块可以重复，参数按键合并。**

#### 证据 3：原版注释明示「同相对路径 → 整体接管」

`GAME\common\defines\jomini\00_tooltips.txt` **第 1 行**原文：

原始示例与取证上下文见本篇对应的历史知识库章节。

三方共享同一相对路径 `common/defines/jomini/00_tooltips.txt`：

| 层 | 路径 | `NTooltip` 键数 | `MOUSE_MOVE_DISTANCE_TO_UPDATE_TOOLTIP_POSITION` |
|---|---|---|---|
| cw/jomini 模块数据（编译进二进制，本机不可直接读取） | `cw/jomini/modules/tooltip_manager/data/common/defines/jomini/00_tooltips.txt` | 未知【未确认】 | 未知【未确认】 |
| jomini 内容根（磁盘可读） | `...\jomini\common\defines\jomini\00_tooltips.txt` | 7 | `20.0f` |
| game 内容根（磁盘可读） | `GAME\common\defines\jomini\00_tooltips.txt` | 7 | `10.0f` |

两个可读文件的**键名集合完全相同（双向差集均为空）**，唯一实质差异就是上面那个值从 `20.0f` 变成 `10.0f`。【提取】

同样的模式出现在另外两个被 game 层接管的 jomini defines：

| 文件（相对 `common/defines/`） | jomini 层 | game 层 | 差异 |
|---|---|---|---|
| `jomini\fog_of_war.txt` | 12 键 | **24 键** | game 版包含 jomini 版全部 12 键，另有 12 个 game 专属键（`NORMAL_TEXTURE`、`BASE_ALPHA`、`FADE_SPEED`、`REALM_ALPHA`、`NO_CLOUD_ALPHA`、`FIXED_ALPHA_IN_IMPASSABLE`、`IMPASSABLE_ALPHA`、`FADE_OUT_TIMER_START`、`FADE_OUT_TIMER_STOP`、`PROVINCE_VISIBILITY_BIAS`、`CLOUDS_MIN_ZOOMSTEP`、`AUDIO_PARAMETER`）；无 jomini 专属键被丢弃 |
| `jomini\rivers.txt` | 7 键 | 7 键 | 键名相同，4 个值不同：`FADE_OUT_DISTANCE` 5.0→2.0、`WIDTH_MIN` 1.25→1.0、`WIDTH_MAX` 2.75→4.0、`UV_SCALE` 1→0.5 |

【提取】

**关键推论**：game 层必须把 jomini 层的键**逐个重抄一遍**才能保留它们，这只有在"同名相对路径文件被整体接管"的语义下才说得通。若引擎在内容根之间也做按键合并，原版作者只需写那一个差异值即可。

同时注意：`jomini\camera.txt`、`jomini\settings.txt`、`jomini\modifiers.txt` **没有**被 game 层同名文件覆盖（`GAME\common\defines\` 下不存在对应文件），它们的键因此通过证据 1 的跨文件合并机制生效。【提取】

#### 证据 4：官方 Wiki 的 mod 侧说明

[Victoria 3 Wiki · Defines](https://vic3.paradoxwikis.com/Defines) 的 "Define modding" 一节原文（页面标注 verified for 1.13）：

> Defines can be modified individually or in batches **without overwriting an entire defines file**. This better preserves compatibility and makes it easier to keep up with changes in future patches.
>
> To modify a define, create a new file in `<mod>/common/defines/` that **loads after the base game files** such as `01_mod_defines.txt`. In that file, add a block for each set of defines to be modified and include the modified defines in those blocks, for example
>
> ```
> NCountry = {
>     INCORPORATION_TIME_NO_MATCH = 100	# Base game 20 years; ...
> }
>
> NDiplomacy = {
>     COUNTRY_TIER_HEGEMONY_PRESTIGE = 150	# Base game 50
> }
> ```
>
> In the case of multiple mods modifying the same define, **the mod with the last loaded filename determines the final value** of the define.

（`INCORPORATION_TIME_NO_MATCH` 在本机 1.14.2 的 `00_defines.txt` → `NCountry` 中确实存在，默认值 25；Wiki 表格里写的 base game 值 25 与其示例注释 "Base game 20 years" 不一致，属 Wiki 陈旧，以实际文件为准。）

#### 推荐写法

原始示例与取证上下文见本篇对应的历史知识库章节。

`01_mymod_ai_defines.txt` 内容（**只写要改的键**）：

原始示例与取证上下文见本篇对应的历史知识库章节。

#### 注意事项与坑

| # | 注意点 | 说明 |
|---|---|---|
| 1 | **文件名前缀必须大于原版** | `00_ai.txt`、`00_defines.txt`、`00_graphics.txt`、`00_interfaces.txt`、`00_audio.txt`、`00_shaders.txt` 全部是 `00_`；mod 用 `01_` 起，最稳是 `99_`。【提取 + Wiki】 |
| 2 | **不要复制整份原版文件** | `00_defines.txt` 有 215 KB；整份复制会与其它 mod 冲突，且每次游戏更新都要重新同步。【Wiki】 |
| 3 | **键名拼错静默失败** | 引擎不会因为未知键报错；改完没效果先怀疑拼写。 |
| 4 | **不要试图"新增"引擎 define** | 键名+类型在 C++ 侧硬编码，新增的键不会被读取。【推断】 |
| 5 | **子目录与根目录的先后顺序【未确认】** | 原版把同相对路径覆盖文件放在 `common\defines\jomini\` 子目录下，但脚本无法确证"子目录文件"与"根目录文件"在排序时的相对位置。若要覆盖 `NMapCoa` 之类，建议用**根目录**下的大前缀文件，而不要复制 `jomini\` 子目录结构。 |
| 6 | **`@` 局部变量不跨文件** | `@opacity`、`@birthrate_transition_slope` 等只在定义它们的文件内（或至少在解析顺序内）可用；在 mod 文件里覆盖某个引用了 `@` 变量的键时，要直接写数值，不能引用原版的 `@` 变量。【推断】 |
| 7 | **`@[表达式]` 可在 mod 文件中使用** | 语法与其它 PDX 脚本一致，可用于让多个 define 保持比例关系。 |
| 8 | **改动需重开游戏** | defines 是启动时读取的静态值。【Wiki】 |

---

## 2. `common\defines\` 各文件结构与顶层命名空间块清单

### 2.1 文件总览

口径见 §0.3。「条目」= 标量 + 内联列表 + 嵌套块。

| 文件（相对 `common\defines\`） | 顶层块数 | 标量参数 | 内联列表 | 嵌套块 | 条目合计 |
|---|---|---|---|---|---|
| `00_ai.txt` | 1 | 1025 | 0 | 0 | **1025** |
| `00_audio.txt` | 1 | 24 | 0 | 0 | **24** |
| `00_defines.txt` | 20 | 1689 | 5 | 0 | **1694** |
| `00_graphics.txt` | 20 | 428 | 139 | 0 | **567** |
| `00_interfaces.txt` | 27 | 174 | 37 | 0 | **211** |
| `00_shaders.txt` | 5 | 35 | 5 | 0 | **40** |
| `jomini/00_tooltips.txt` | 1 | 6 | 1 | 0 | **7** |
| `jomini/fog_of_war.txt` | 1 | 22 | 1 | 0 | **23** |
| `jomini/rivers.txt` | 1 | 6 | 0 | 0 | **6** |
| **合计** | **77** | **3409** | **188** | **0** | **3597** |

【提取】

### 2.2 全部 77<!--claim:def.blocks--> 个顶层命名空间块

“起始行”为该块在所属文件中的**物理起始行号**。

| 全部 defines 文件 | 命名空间块 | 起始行 | 标量 | 内联列表 | 嵌套 | 合计 |
|---|---|---|---|---|---|---|
| `00_ai.txt` | `NAI` | 1 | 1025 | 0 | 0 | 1025 |
| `00_audio.txt` | `NAudio` | 1 | 24 | 0 | 0 | 24 |
| `00_defines.txt` | `NGame` | 1 | 5 | 0 | 0 | 5 |
| `00_defines.txt` | `NJominiMap` | 9 | 4 | 0 | 0 | 4 |
| `00_defines.txt` | `NCountry` | 16 | 45 | 0 | 0 | 45 |
| `00_defines.txt` | `NPolitics` | 64 | 206 | 0 | 0 | 206 |
| `00_defines.txt` | `NEconomy` | 356 | 305 | 1 | 0 | 306 |
| `00_defines.txt` | `NMilitary` | 739 | 143 | 0 | 0 | 143 |
| `00_defines.txt` | `NDiplomacy` | 926 | 401 | 0 | 0 | 401 |
| `00_defines.txt` | `NPowerBlocs` | 1396 | 23 | 0 | 0 | 23 |
| `00_defines.txt` | `NPops` | 1422 | 206 | 4 | 0 | 210 |
| `00_defines.txt` | `NPops` | 1796 | 16 | 0 | 0 | 16 |
| `00_defines.txt` | `NEvents` | 1823 | 3 | 0 | 0 | 3 |
| `00_defines.txt` | `NTechnology` | 1829 | 4 | 0 | 0 | 4 |
| `00_defines.txt` | `NCharacters` | 1837 | 103 | 0 | 0 | 103 |
| `00_defines.txt` | `NBattle` | 1992 | 66 | 0 | 0 | 66 |
| `00_defines.txt` | `NWar` | 2079 | 89 | 0 | 0 | 89 |
| `00_defines.txt` | `NTravelNetwork` | 2173 | 40 | 0 | 0 | 40 |
| `00_defines.txt` | `NHarvestConditions` | 2226 | 2 | 0 | 0 | 2 |
| `00_defines.txt` | `NSeasons` | 2231 | 19 | 0 | 0 | 19 |
| `00_defines.txt` | `NText` | 2267 | 6 | 0 | 0 | 6 |
| `00_defines.txt` | `NDebug` | 2277 | 3 | 0 | 0 | 3 |
| `00_graphics.txt` | `NMapMode` | 1 | 40 | 63 | 0 | 103 |
| `00_graphics.txt` | `NMapName` | 168 | 7 | 1 | 0 | 8 |
| `00_graphics.txt` | `NJominiMapGraphics` | 198 | 11 | 0 | 0 | 11 |
| `00_graphics.txt` | `NJominiGraphics` | 213 | 3 | 0 | 0 | 3 |
| `00_graphics.txt` | `NJominiEars` | 219 | 2 | 0 | 0 | 2 |
| `00_graphics.txt` | `NGraphics` | 224 | 142 | 32 | 0 | 174 |
| `00_graphics.txt` | `NFrontend` | 472 | 3 | 0 | 0 | 3 |
| `00_graphics.txt` | `NCamera` | 478 | 14 | 4 | 0 | 18 |
| `00_graphics.txt` | `NCities` | 505 | 25 | 3 | 0 | 28 |
| `00_graphics.txt` | `NFortifications` | 551 | 5 | 0 | 0 | 5 |
| `00_graphics.txt` | `NCoasts` | 559 | 6 | 0 | 0 | 6 |
| `00_graphics.txt` | `NRoutes` | 568 | 6 | 3 | 0 | 9 |
| `00_graphics.txt` | `NPortrait` | 586 | 5 | 0 | 0 | 5 |
| `00_graphics.txt` | `NProvinceHighlight` | 594 | 4 | 0 | 0 | 4 |
| `00_graphics.txt` | `NTravelNetwork` | 603 | 11 | 3 | 0 | 14 |
| `00_graphics.txt` | `NPowerBlocCoa` | 623 | 7 | 14 | 0 | 21 |
| `00_graphics.txt` | `NPowerBlocStatueCamera` | 653 | 7 | 0 | 0 | 7 |
| `00_graphics.txt` | `NNavy` | 663 | 104 | 5 | 0 | 109 |
| `00_graphics.txt` | `NShipViewer` | 791 | 16 | 6 | 0 | 22 |
| `00_graphics.txt` | `NCharacterPanelViewer` | 817 | 10 | 5 | 0 | 15 |
| `00_interfaces.txt` | `NLenses` | 1 | 9 | 0 | 0 | 9 |
| `00_interfaces.txt` | `NGUI` | 13 | 8 | 0 | 0 | 8 |
| `00_interfaces.txt` | `NGUI` | 24 | 50 | 14 | 0 | 64 |
| `00_interfaces.txt` | `NGUI` | 104 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 109 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NTrend` | 114 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NGUI` | 119 | 15 | 0 | 0 | 15 |
| `00_interfaces.txt` | `NGUI` | 142 | 5 | 4 | 0 | 9 |
| `00_interfaces.txt` | `NGUI` | 154 | 8 | 0 | 0 | 8 |
| `00_interfaces.txt` | `NGUI` | 165 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NSaves` | 171 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 175 | 6 | 0 | 0 | 6 |
| `00_interfaces.txt` | `NGUI` | 184 | 0 | 1 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 188 | 3 | 0 | 0 | 3 |
| `00_interfaces.txt` | `NGUI` | 194 | 9 | 0 | 0 | 9 |
| `00_interfaces.txt` | `NGUI` | 206 | 0 | 0 | 0 | 0 |
| `00_interfaces.txt` | `NGUI` | 209 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NGUI` | 214 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 218 | 6 | 0 | 0 | 6 |
| `00_interfaces.txt` | `NGUI` | 231 | 7 | 0 | 0 | 7 |
| `00_interfaces.txt` | `NGUI` | 241 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 245 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NGUI` | 250 | 0 | 6 | 0 | 6 |
| `00_interfaces.txt` | `NGUI` | 259 | 0 | 0 | 0 | 0 |
| `00_interfaces.txt` | `NGUI` | 262 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 266 | 18 | 12 | 0 | 30 |
| `00_interfaces.txt` | `NGUI` | 316 | 16 | 0 | 0 | 16 |
| `00_shaders.txt` | `NShadersCommon` | 1 | 1 | 0 | 0 | 1 |
| `00_shaders.txt` | `NMapCoa` | 6 | 11 | 0 | 0 | 11 |
| `00_shaders.txt` | `NMapmodeStripes` | 20 | 6 | 0 | 0 | 6 |
| `00_shaders.txt` | `NEdgeOfWorld` | 29 | 14 | 5 | 0 | 19 |
| `00_shaders.txt` | `NGuiFlag` | 56 | 3 | 0 | 0 | 3 |
| `jomini/00_tooltips.txt` | `NTooltip` | 2 | 6 | 1 | 0 | 7 |
| `jomini/fog_of_war.txt` | `NFogOfWar` | 1 | 22 | 1 | 0 | 23 |
| `jomini/rivers.txt` | `NRivers` | 2 | 6 | 0 | 0 | 6 |

---

### 2.3 `00_ai.txt` —— AI 专用 defines（详见 §3）

整个文件只有 1<!--claim:def.file_ai--> 个顶层命名空间块 `NAI`，起始于第 1 行，包含 **1025**<!--claim:def.nai_count--> 个参数，全部为标量，无内联列表、无嵌套块。文件共 1324<!--claim:def.ai_file_lines--> 行，全文中 `= {` 只出现 1 次（即第 1 行的 `NAI = {`）。【提取】

结构明细见 §3.1，全部 1017 个参数名见 §3.3。

### 2.4 `00_audio.txt`

该文件有 1<!--claim:def.file_audio--> 个顶层命名空间块 `NAudio`。

| 命名空间块 | 起始行 | 条目数 |
|---|---|---|
| `NAudio` | 1 | 23 |

23 条全部是音频事件路径字符串（FMOD/Wwise 风格 `event:/...`），例如 `DEFAULT_SELECT = "event:/SFX/UI/Global/select"`、`MAP_CLICKSOUND = "event:/SFX/UI/Global/map_click"`、`DEFAULT_NOTIFICATION_SOUND = "event:/SFX/UI/Alerts/Toasts/_transient"`。【提取】

其中 4 条是按地图模式键拼接的：`MAP_LENS_political_lens`、`MAP_LENS_production_lens`、`MAP_LENS_diplomatic_lens`、`MAP_LENS_military_lens`（即 `MAP_LENS_<地图模式 key>`）。这也是全库唯一 4 个含小写的参数名（见 §1.5）。【提取】

> 做音频 mod 时注意：这里定义的是「UI 音效绑定点」，不是音频资源本身；资源在 `sound\` 下。

### 2.5 `00_defines.txt` —— 主 defines 文件

1.15.2 文件有 42<!--claim:def.file_defines--> 个顶层赋值（包含 `@` 变量），其中不同命名空间为 19<!--claim:defines.00_defines_namespaces--> 个。`NPops` 命名空间块在第 1424 行和第 1798 行各出现一次；顶层赋值数、块数和去重命名空间数不可混用。

| # | 命名空间 | 块起始行 | 该命名空间的块数 | 参数合计 |
|---|---|---|---|---|
| 1 | `NGame` | 1 | 1 | 5 |
| 2 | `NJominiMap` | 9 | 1 | 4 |
| 3 | `NCountry` | 16 | 1 | 45 |
| 4 | `NPolitics` | 64 | 1 | 206 |
| 5 | `NEconomy` | 356 | 1 | 306 |
| 6 | `NMilitary` | 739 | 1 | 143 |
| 7 | `NDiplomacy` | 926 | 1 | 401 |
| 8 | `NPowerBlocs` | 1396 | 1 | 23 |
| 9 | `NPops` | 1422, 1796 | **2** | 210 + 16 = 226 |
| 10 | `NEvents` | 1823 | 1 | 3 |
| 11 | `NTechnology` | 1829 | 1 | 4 |
| 12 | `NCharacters` | 1837 | 1 | 103 |
| 13 | `NBattle` | 1992 | 1 | 66 |
| 14 | `NWar` | 2079 | 1 | 89 |
| 15 | `NTravelNetwork` | 2173 | 1 | 40 |
| 16 | `NHarvestConditions` | 2226 | 1 | 2 |
| 17 | `NSeasons` | 2231 | 1 | 19 |
| 18 | `NText` | 2267 | 1 | 6 |
| 19 | `NDebug` | 2277 | 1 | 3 |
| | **合计** | | **20 块** | **1694** |

【提取】——这 18 个命名空间与官方 Wiki [Defines](https://vic3.paradoxwikis.com/Defines) 的 §2 小节列表**完全一致**，可作为交叉验证。

规模最大的四块：`NDiplomacy`（406）、`NEconomy`（294）、`NPops`（211）、`NPolitics`（208）。

### 2.6 `00_graphics.txt`

1.15.2 中有 20<!--claim:def.file_graphics--> 个顶层块，567 个条目（其中 139 条是 `KEY = { r g b a }` 形式的纯值列表；**0 条嵌套块** —— defines 层是完全扁平的，这也是它与其他 `common\` 数据目录最大的结构差别）。

| 命名空间块 | 起始行 | 标量 | 内联列表 | 嵌套 | 合计 |
|---|---|---|---|---|---|
| `NMapMode` | 1 | 40 | 63 | 0 | 103 |
| `NMapName` | 168 | 7 | 1 | 0 | 8 |
| `NJominiMapGraphics` | 198 | 11 | 0 | 0 | 11 |
| `NJominiGraphics` | 213 | 3 | 0 | 0 | 3 |
| `NJominiEars` | 219 | 2 | 0 | 0 | 2 |
| `NGraphics` | 224 | 142 | 32 | 0 | 174 |
| `NFrontend` | 472 | 3 | 0 | 0 | 3 |
| `NCamera` | 478 | 14 | 4 | 0 | 18 |
| `NCities` | 505 | 25 | 3 | 0 | 28 |
| `NFortifications` | 551 | 5 | 0 | 0 | 5 |
| `NCoasts` | 559 | 6 | 0 | 0 | 6 |
| `NRoutes` | 568 | 6 | 3 | 0 | 9 |
| `NPortrait` | 586 | 5 | 0 | 0 | 5 |
| `NProvinceHighlight` | 594 | 4 | 0 | 0 | 4 |
| `NTravelNetwork` | 603 | 11 | 3 | 0 | 14 |
| `NPowerBlocCoa` | 623 | 7 | 14 | 0 | 21 |
| `NPowerBlocStatueCamera` | 653 | 7 | 0 | 0 | 7 |
| `NNavy` | 663 | 104 | 5 | 0 | 109 |
| `NShipViewer` | 791 | 16 | 6 | 0 | 22 |
| `NCharacterPanelViewer` | 817 | 10 | 5 | 0 | 15 |
| | | **428** | **139** | **0** | **567** |

【提取】注意 `NCamera` 与 Jomini 层的 `NCamera` 合并（§1.7 证据 1）；`NNavy` 是本文件第二大块。

### 2.7 `00_interfaces.txt`

27<!--claim:def.file_interfaces--> 个块，但只有 **4<!--claim:defines.interfaces_ns_doc05--> 个不同命名空间**——`NGUI` 在同一个文件里出现了 **24 次**（这是 §1.7 证据 2 的第二个来源）。

| 命名空间块 | 出现次数 | 各块起始行 | 合计条目 |
|---|---|---|---|
| `NGUI` | **24** | 13, 17, 95, 100, 110, 130, 142, 153, 163, 172, 176, 182, 189, 194, 199, 203, 216, 226, 230, 235, 246, 250, 254, 303 | 199 |
| `NLenses` | 1 | 1 | 9 |
| `NTrend` | 1 | 105 | 2 |
| `NSaves` | 1 | 159 | 1 |
|  |  |  | **211** |

【提取】

同一文件里 24 次声明同一个 `NGUI` 块，是"同名块合并"最直观的原版用法——原版作者用这种方式给 `NGUI` 分区加注释组织内容。

### 2.8 `00_shaders.txt`

> 📌 本节的「起始行」同 §1.7 的说明：行号列是快照，其余列由 `v3 tables` 重算。

5<!--claim:def.file_shaders--> 个块，40 个条目。

| 命名空间块 | 起始行 | 标量 | 内联列表 | 合计 |
|---|---|---|---|---|
| `NShadersCommon` | **1**（`=` 与 `{` 分行） | 1 | 0 | 1 |
| `NMapCoa` | 6 | 11 | 0 | 11 |
| `NMapmodeStripes` | 20 | 6 | 0 | 6 |
| `NEdgeOfWorld` | 29 | 14 | 5 | 19 |
| `NGuiFlag` | 56 | 3 | 0 | 3 |
| | | **35** | **5** | **40** |

【提取】

`NShadersCommon` 只有一条参数：`PARALLAX_HEIGHT = 8  # Height of parallax effects`。它的块写法值得注意（这是全库唯一一处该风格）：

原始示例与取证上下文见本篇对应的历史知识库章节。

本节也顺带说明：官方 Wiki 的 `00_shaders` 一节（列出 ShadersCommon / MapCoa / MapmodeStripes / EdgeOfWorld / GuiFlag）与本机 1.14.2 实测**一致**。

### 2.9 `jomini\` 子目录（3 个文件，36 个条目）

| 文件 | 命名空间块 | 起始行 | 标量 | 内联列表 | 嵌套 | 合计 |
|---|---|---|---|---|---|---|
| `jomini/00_tooltips.txt` | `NTooltip` | 2 | 6 | 1 | 0 | 7 |
| `jomini/fog_of_war.txt` | `NFogOfWar` | 1 | 22 | 1 | 0 | 23 |
| `jomini/rivers.txt` | `NRivers` | 2 | 6 | 0 | 0 | 6 |

【提取】

这 3 个文件是 game 内容根对 Jomini 层同名文件的**整体接管**文件（见 §1.7 证据 3）。它们的相对路径 `common/defines/jomini/*.txt` 必须与 Jomini 层完全一致才能生效。

Jomini 内容根另有 15<!--claim:def.jomini_untaken--> 个未被 game 层接管的 defines 文件（`00_adaptive_music.txt`、`00_audio_persistent_objects.txt`、`music_player_defines.txt`、`graphic/00_coa.txt`、`jomini/adjacencies.txt`、`jomini/camera.txt`、`jomini/icons.txt`、`jomini/mapeditor.txt`、`jomini/modifiers.txt`、`jomini/multiplayer.txt`、`jomini/portraits.txt`、`jomini/settings.txt`、`jomini/social.txt`、`jomini/text_coloring.txt`、`jomini/text_formatting.txt`），它们通过跨文件合并机制生效。【提取】

---

## 3. `00_ai.txt` 完整参数清单（AI mod 重点）

### 3.0 概览与结论

**最重要的结论：`00_ai.txt` 里没有 `NCountry`、`NAI_Military` 之类的"多个 AI 命名空间块"，它从头到尾只有一个块：`NAI`。**【提取】

| 项目 | 值 |
|---|---|
| 文件 | `GAME\common\defines\00_ai.txt` |
| 文件大小 / 行数 | 147,603 字节 / **1311 行** |
| 顶层命名空间块 | **1 个：`NAI`**（第 1 行） |
| 参数总数 | **1017**（全部标量；内联列表 0；嵌套块 0） |
| 去重参数名数 | **1017**（无重复键） |
| 文件内 `= {` 出现次数 | **1 次**（仅第 1 行） |
| 判空校验 | 解析器按「块内深度 1 的 `KEY = value`」计数得到 1017，与顶层块口径一致 |

【提取】

也就是说：`NAI` 是一个**完全扁平的、1017 条键值对的大块**，所有 AI 相关 define 都平铺在其中，靠命名前缀和注释分组，而不是靠嵌套命名空间。

### 3.1 `NAI` 块清单

| 命名空间块 | 起始行 | 标量参数 | 内联列表参数 | 嵌套块 | 参数合计 |
|---|---|---|---|---|---|
| `NAI` | 1 | 1017 | 0 | 0 | **1017** |

---

### 3.2 参数前缀分组（104 组）

由于 `NAI` 是完全扁平的 1017 条键，实际阅读时需要靠**命名前缀**分组。下表按「第一个下划线之前的部分」机械分组，按参数数降序排列。

> 说明：这是**机械切分**，不是官方分组。同一前缀可能跨越不同语义（如 `MIN_` 是通用修饰前缀）。原版文件本身没有 `# ===== 分区 =====` 式的分区标题，只有零散的行内/行上注释。

| 参数前缀 | 参数数 |
|---|---|
| `DIPLO_*` | 209 |
| `PRODUCTION_*` | 88 |
| `AI_*` | 43 |
| `MONEY_*` | 43 |
| `GOAL_*` | 35 |
| `AUTONOMOUS_*` | 30 |
| `UNIFICATION_*` | 30 |
| `MOBILIZATION_*` | 29 |
| `FLEET_*` | 25 |
| `CHANGE_*` | 24 |
| `GOVERNMENT_*` | 23 |
| `NAVAL_*` | 17 |
| `DIPLOMATIC_*` | 16 |
| `POWER_*` | 16 |
| `OWNER_*` | 15 |
| `SHIP_*` | 14 |
| `COMPANY_*` | 12 |
| `FRONT_*` | 12 |
| `CONSTRUCTION_*` | 11 |
| `MILITARY_*` | 11 |
| `TREATIES_*` | 11 |
| `DEFEND_*` | 10 |
| `NUM_*` | 10 |
| `PROTECT_*` | 10 |
| `RAID_*` | 10 |
| `TRADE_*` | 10 |
| `PIRACY_*` | 9 |
| `SUPPLY_*` | 9 |
| `BLOCKADE_*` | 8 |
| `HQ_*` | 8 |
| `INVADE_*` | 8 |
| `LAND_*` | 8 |
| `MIN_*` | 8 |
| `NATIONALIZATION_*` | 8 |
| `WAGE_*` | 8 |
| `CONSUMPTION_*` | 7 |
| `REFORM_*` | 7 |
| `SELL_*` | 7 |
| `WAR_*` | 7 |
| `COLONY_*` | 6 |
| `CONSCRIPTION_*` | 6 |
| `DISBAND_*` | 6 |
| `HUNT_*` | 6 |
| `RECRUITABLE_*` | 6 |
| `SUBSIDIZE_*` | 6 |
| `TREATY_*` | 6 |
| `IDEOLOGICAL_*` | 5 |
| `IMPOSE_*` | 5 |
| `RAISE_*` | 5 |
| `START_*` | 5 |
| `VIOLATE_*` | 5 |
| `ESCORT_*` | 4 |
| `INSTITUTION_*` | 4 |
| `MAX_*` | 4 |
| `PORT_*` | 4 |
| `REGIME_*` | 4 |
| `COLONIZATION_*` | 3 |
| `INFLUENCE_*` | 3 |
| `INTERCEPT_*` | 3 |
| `LOWER_*` | 3 |
| `REJECTED_*` | 3 |
| `STRAIT_*` | 3 |
| `STRATEGIC_*` | 3 |
| `ATTITUDE_*` | 2 |
| `BASELINE_*` | 2 |
| `COUNTRY_*` | 2 |
| `DECLARE_*` | 2 |
| `HIGH_*` | 2 |
| `INCORPORATE_*` | 2 |
| `LOW_*` | 2 |
| `PRIVATEER_*` | 2 |
| `TECH_*` | 2 |
| `TRANSPORT_*` | 2 |
| `UNUSED_*` | 2 |
| `AUTHORITY_*` | 1 |
| `BASE_*` | 1 |
| `BUILDING_*` | 1 |
| `COLD_*` | 1 |
| `CONTAINMENT_*` | 1 |
| `COSSACK_*` | 1 |
| `DEFAULT_*` | 1 |
| `DESIRED_*` | 1 |
| `DID_*` | 1 |
| `ENEMY_*` | 1 |
| `EXILE_*` | 1 |
| `EXPEL_*` | 1 |
| `FRIENDLY_*` | 1 |
| `LEAVE_*` | 1 |
| `MARINE_*` | 1 |
| `NODE_*` | 1 |
| `OBLIGATION_*` | 1 |
| `OBSOLETE_*` | 1 |
| `PROJECT_*` | 1 |
| `PROMOTION_*` | 1 |
| `REGIONAL_*` | 1 |
| `SECRET_*` | 1 |
| `SENT_*` | 1 |
| `STRATEGY_*` | 1 |
| `SUPPRESSION_*` | 1 |
| `TAX_*` | 1 |
| `TICKS_*` | 1 |
| `TRANSIT_*` | 1 |
| `UNITS_*` | 1 |

---

### 3.3 全部 1017 个参数名

下表由脚本从 `GAME\common\defines\00_ai.txt` 按**文件中的原始出现顺序**机械导出（第 2 行至第 1310 行），两列排版。全部 1017 个，无遗漏、无编造；`NAI` 块内**无重复键**（脚本校验：1017 条 → 1017 个去重名）。

查找建议：用编辑器的「在文件中查找」直接搜关键词（如 `DIPLO_PLAY`、`INVESTMENT`、`CONSCRIPTION`）。参数语义请回到原文件看同一行的 `#` 注释——原版注释相当完整。

原始示例与取证上下文见本篇对应的历史知识库章节。

---

### 3.4 `00_ai.txt` 之外的 AI 相关 define

**重要提醒**：AI 相关 define **并非**全部集中在 `00_ai.txt`。但也不能靠"名字里有没有 AI"来判断——下表是脚本对整个 `common\defines\` 树做的机械匹配（键名含独立单词 `AI`），**排除 `NAI` 本身**：

命中仅 4 条：

- `NPolitics`（`00_defines.txt`）：`MAX_GOVERNMENT_ALTERNATIVES_TO_CONSIDER_AI`
- `NMilitary`（`00_defines.txt`）：`AI_FIND_FLEET_EXPECTED_DISTANCE`
- `NGUI`（`00_interfaces.txt`）：`AI_STRATEGIC_REGION_STANCE_TYPE_ICON_FONT`、`AI_STRATEGIC_REGION_STANCE_TYPE_ICON_OFFSET`（都是 UI 图标设置，与 AI 行为无关）

下表为完整命中清单：

| 文件 | 命名空间块 | 参数键 |
|---|---|---|
| `00_defines.txt` | `NPolitics` | `MAX_GOVERNMENT_ALTERNATIVES_TO_CONSIDER_AI` |
| `00_defines.txt` | `NMilitary` | `AI_FIND_FLEET_EXPECTED_DISTANCE` |
| `00_interfaces.txt` | `NGUI` | `AI_STRATEGIC_REGION_STANCE_TYPE_ICON_FONT` |
| `00_interfaces.txt` | `NGUI` | `AI_STRATEGIC_REGION_STANCE_TYPE_ICON_OFFSET` |
**结论**：想在 `00_ai.txt` 之外找 AI 调参点，"键名含 AI"这条线索几乎无效（只有 4 条，且 2 条是 UI 图标）。真正与 AI 决策相关的参数大量分布在 `NDiplomacy`（406 条）、`NEconomy`（294 条）、`NPolitics`（208 条）等块中，但**命名不含 `AI` 字样**（例如 `NDiplomacy` 的 `COUNTRY_TIER_HEGEMONY_PRESTIGE = 50`）。做 AI mod 时应以 `00_ai.txt` 的 `NAI` 块为主战场，其余按语义人工排查。【提取 + 推断】

---

## 4. `common\game_rules\`

### 4.1 目录与用途

目录只有两个文件：【提取】

| 文件 | 大小 | 作用 |
|---|---|---|
| `00_game_rules.txt` | 5,008 字节 | **实际规则定义** |
| `game_rules.md` | 1,972 字节 | 原版语法说明文档 |

`game_rules` 是**开局规则开关**（类似 HoI4 的 game rules）：玩家在开新档时选择「AI 侵略性」「成就是否允许」「Pop 合并强度」等，引擎据此激活一组具名 flag，脚本再用 trigger 读取。

### 4.2 语法（原版 `game_rules.md` 原文）

原始示例与取证上下文见本篇对应的历史知识库章节。

`game_rules.md` 同时给出本地化键命名约定（原文）：

原始示例与取证上下文见本篇对应的历史知识库章节。

已在本地化文件中验证（`GAME\localization\english\*.yml` 与 `simp_chinese\*.yml`）：`rule_ai_aggression`、`setting_standard_ai_aggression`、`setting_standard_ai_aggression_desc` 都存在。【提取】→ 做 game rule mod **必须同时提供这三种本地化键**，否则界面显示原始键名。

### 4.3 实测规模

| 指标 | 数值 |
|---|---|
| **game_rule 键（顶层块）** | **15** |
| setting 块 | **38** |
| `flag = ` 条目 | **67** |
| 去重 flag 键 | **47** |
| `apply_modifier` 条目 | **0**（文档记载但原版 1.14.2 未使用） |
| `default = ` 条目 | 15（每条规则一条） |

【提取】

### 4.4 15 条 game_rule 完整键名

| # | game_rule 键 | 默认 setting | 非默认 setting | flag 条目数 |
|---|---|---|---|---|
| 1 | `achievements` | `achievements_allowed` | `achievements_blocked` | 1 |
| 2 | `ai_behavior` | `standard_ai_behavior` | `lenient_ai_behavior`, `harsh_ai_behavior` | 2 |
| 3 | `ai_aggression` | `standard_ai_aggression` | `low_ai_aggression`, `high_ai_aggression` | 2 |
| 4 | `free_construction` | `free_construction_scaled_player_exemption` | `free_construction_scaled_all`, `free_construction_unscaled` | 2 |
| 5 | `formable_nations` | `all_formable_nations` | `plausible_formable_nations` | 0 |
| 6 | `releasable_nations` | `all_releasable_nations` | `plausible_releasable_nations` | 0 |
| 7 | `loyalties_grace_period` | `loyalties_grace_period_none` | `loyalties_grace_period_short`, `_long`, `_extra_long` | 4 |
| 8 | `pop_consolidation` | `moderate_consolidation` | `no_consolidation`, `minor_consolidation`, `aggressive_consolidation` | 4 |
| 9 | `monument_effects` | `allow_monument_effects` | `prestige_only_monument_effects`, `no_monument_effects` | **43** |
| 10 | `subject_flags` | `allow_subject_flags` | `no_subject_flags` | 1 |
| 11 | `subject_map_color` | `allow_subject_map_color` | `no_subject_map_color` | 1 |
| 12 | `fantastical_content` | `allow_fantastical_content` | `no_fantastical_content` | 2 |
| 13 | `custom_rng_seed` | `no_custom_rng_seed` | `use_custom_rng_seed` | 1 |
| 14 | `dynamic_naming` | `allow_dynamic_naming` | `no_dynamic_naming` | 1 |
| 15 | `ruler_selector` | `no_ruler_selector` | `allow_ruler_selector` | 3 |

【提取】——完整明细（含每条 flag 的具体键名）见 §4.5–§4.7 的表。

### 4.5 完整明细：每条规则的 default / settings / flags

| # | game_rule 键 | 默认 setting | 非默认 setting | flag 条目 |
|---|---|---|---|---|
| 1 | `achievements` | `achievements_allowed` | `achievements_blocked` | `achievements_blocked:blocks_achievements` |
| 2 | `ai_behavior` | `standard_ai_behavior` | `lenient_ai_behavior`, `harsh_ai_behavior` | `lenient_ai_behavior:lenient_ai`<br>`harsh_ai_behavior:harsh_ai` |
| 3 | `ai_aggression` | `standard_ai_aggression` | `low_ai_aggression`, `high_ai_aggression` | `low_ai_aggression:low_ai_aggression`<br>`high_ai_aggression:high_ai_aggression` |
| 4 | `free_construction` | `free_construction_scaled_player_exemption` | `free_construction_scaled_all`, `free_construction_unscaled` | `free_construction_scaled_player_exemption:free_construction_scaled_player_exemption`<br>`free_construction_unscaled:free_construction_unscaled` |
| 5 | `formable_nations` | `all_formable_nations` | `plausible_formable_nations` | (none) |
| 6 | `releasable_nations` | `all_releasable_nations` | `plausible_releasable_nations` | (none) |
| 7 | `loyalties_grace_period` | `loyalties_grace_period_none` | `loyalties_grace_period_short`, `loyalties_grace_period_long`, `loyalties_grace_period_extra_long` | `loyalties_grace_period_none:loyalties_grace_period_none`<br>`loyalties_grace_period_short:loyalties_grace_period_short`<br>`loyalties_grace_period_long:loyalties_grace_period_long`<br>`loyalties_grace_period_extra_long:loyalties_grace_period_extra_long` |
| 8 | `pop_consolidation` | `moderate_consolidation` | `no_consolidation`, `minor_consolidation`, `aggressive_consolidation` | `no_consolidation:no_pop_consolidation`<br>`minor_consolidation:minor_pop_consolidation`<br>`moderate_consolidation:moderate_pop_consolidation`<br>`aggressive_consolidation:aggressive_pop_consolidation` |
| 9 | `monument_effects` | `allow_monument_effects` | `prestige_only_monument_effects`, `no_monument_effects` | **43** 条（见 §4.7） |
| 10 | `subject_flags` | `allow_subject_flags` | `no_subject_flags` | `no_subject_flags:no_subject_flags` |
| 11 | `subject_map_color` | `allow_subject_map_color` | `no_subject_map_color` | `no_subject_map_color:no_subject_map_color` |
| 12 | `fantastical_content` | `allow_fantastical_content` | `no_fantastical_content` | `allow_fantastical_content:give_fantastical_content`<br>`no_fantastical_content:no_fantastical_content` |
| 13 | `custom_rng_seed` | `no_custom_rng_seed` | `use_custom_rng_seed` | `use_custom_rng_seed:use_custom_rng_seed` |
| 14 | `dynamic_naming` | `allow_dynamic_naming` | `no_dynamic_naming` | `no_dynamic_naming:no_dynamic_naming` |
| 15 | `ruler_selector` | `no_ruler_selector` | `allow_ruler_selector` | `allow_ruler_selector:give_ruler_selector`<br>`allow_ruler_selector:blocks_achievements`<br>`no_ruler_selector:no_ruler_selector` |

---

### 4.6 全部 setting 键（38 个）

`game_rule` 下的 `setting_*` 块即为可选设置。下表列出全部 38 个，并标明所属规则与是否为默认值。

| # | setting 键 | 所属 game_rule | 是否默认 |
|---|---|---|---|
| 1 | `achievements_allowed` | `achievements` | yes |
| 2 | `achievements_blocked` | `achievements` |  |
| 3 | `lenient_ai_behavior` | `ai_behavior` |  |
| 4 | `standard_ai_behavior` | `ai_behavior` | yes |
| 5 | `harsh_ai_behavior` | `ai_behavior` |  |
| 6 | `low_ai_aggression` | `ai_aggression` |  |
| 7 | `standard_ai_aggression` | `ai_aggression` | yes |
| 8 | `high_ai_aggression` | `ai_aggression` |  |
| 9 | `free_construction_scaled_all` | `free_construction` |  |
| 10 | `free_construction_scaled_player_exemption` | `free_construction` | yes |
| 11 | `free_construction_unscaled` | `free_construction` |  |
| 12 | `all_formable_nations` | `formable_nations` | yes |
| 13 | `plausible_formable_nations` | `formable_nations` |  |
| 14 | `all_releasable_nations` | `releasable_nations` | yes |
| 15 | `plausible_releasable_nations` | `releasable_nations` |  |
| 16 | `loyalties_grace_period_none` | `loyalties_grace_period` | yes |
| 17 | `loyalties_grace_period_short` | `loyalties_grace_period` |  |
| 18 | `loyalties_grace_period_long` | `loyalties_grace_period` |  |
| 19 | `loyalties_grace_period_extra_long` | `loyalties_grace_period` |  |
| 20 | `no_consolidation` | `pop_consolidation` |  |
| 21 | `minor_consolidation` | `pop_consolidation` |  |
| 22 | `moderate_consolidation` | `pop_consolidation` | yes |
| 23 | `aggressive_consolidation` | `pop_consolidation` |  |
| 24 | `allow_monument_effects` | `monument_effects` | yes |
| 25 | `prestige_only_monument_effects` | `monument_effects` |  |
| 26 | `no_monument_effects` | `monument_effects` |  |
| 27 | `no_subject_flags` | `subject_flags` |  |
| 28 | `allow_subject_flags` | `subject_flags` | yes |
| 29 | `no_subject_map_color` | `subject_map_color` |  |
| 30 | `allow_subject_map_color` | `subject_map_color` | yes |
| 31 | `allow_fantastical_content` | `fantastical_content` | yes |
| 32 | `no_fantastical_content` | `fantastical_content` |  |
| 33 | `no_custom_rng_seed` | `custom_rng_seed` | yes |
| 34 | `use_custom_rng_seed` | `custom_rng_seed` |  |
| 35 | `allow_dynamic_naming` | `dynamic_naming` | yes |
| 36 | `no_dynamic_naming` | `dynamic_naming` |  |
| 37 | `allow_ruler_selector` | `ruler_selector` |  |
| 38 | `no_ruler_selector` | `ruler_selector` | yes |

---

### 4.7 全部 flag 条目（67 条）

每条 `flag` 都归在某个 `game_rule` 的某个 `setting` 之下。原版对 flag 的**消费方式**是脚本 trigger `has_game_rule`（见 §4.9），而不是在游戏规则文件里自带效果——**flag 本身只是一个开关名**。

| game_rule | setting | flag / 指令 |
|---|---|---|
| `achievements` | `achievements_blocked` | `blocks_achievements` |
| `ai_behavior` | `lenient_ai_behavior` | `lenient_ai` |
| `ai_behavior` | `harsh_ai_behavior` | `harsh_ai` |
| `ai_aggression` | `low_ai_aggression` | `low_ai_aggression` |
| `ai_aggression` | `high_ai_aggression` | `high_ai_aggression` |
| `free_construction` | `free_construction_scaled_player_exemption` | `free_construction_scaled_player_exemption` |
| `free_construction` | `free_construction_unscaled` | `free_construction_unscaled` |
| `loyalties_grace_period` | `loyalties_grace_period_none` | `loyalties_grace_period_none` |
| `loyalties_grace_period` | `loyalties_grace_period_short` | `loyalties_grace_period_short` |
| `loyalties_grace_period` | `loyalties_grace_period_long` | `loyalties_grace_period_long` |
| `loyalties_grace_period` | `loyalties_grace_period_extra_long` | `loyalties_grace_period_extra_long` |
| `pop_consolidation` | `no_consolidation` | `no_pop_consolidation` |
| `pop_consolidation` | `minor_consolidation` | `minor_pop_consolidation` |
| `pop_consolidation` | `moderate_consolidation` | `moderate_pop_consolidation` |
| `pop_consolidation` | `aggressive_consolidation` | `aggressive_pop_consolidation` |
| `monument_effects` | `allow_monument_effects` | `disable_pm_monument_prestige_only` |
| `monument_effects` | `allow_monument_effects` | `disable_pm_monument_no_effects` |
| `monument_effects` | `allow_monument_effects` | `disable_pm_power_bloc_prestige_only` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_eiffel_tower` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_angkor_wat` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_big_ben` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_forbidden_city` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_hagia_sophia` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_mosque_of_djenne` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_saint_basils_cathedral` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_statue_of_liberty` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_taj_mahal` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_vatican_city` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_default_building_white_house` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_monument_no_effects` |
| `monument_effects` | `prestige_only_monument_effects` | `force_pm_monument_prestige_only` |
| `monument_effects` | `prestige_only_monument_effects` | `force_pm_monument_prestige_only_vatican_city` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_power_bloc_statue_religious` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_power_bloc_statue_trade_league` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_power_bloc_statue_military_treaty` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_power_bloc_statue_ideological_union` |
| `monument_effects` | `prestige_only_monument_effects` | `disable_pm_power_bloc_statue_sovereign_empire` |
| `monument_effects` | `prestige_only_monument_effects` | `force_pm_power_bloc_prestige_only` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_eiffel_tower` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_angkor_wat` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_big_ben` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_forbidden_city` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_hagia_sophia` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_mosque_of_djenne` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_saint_basils_cathedral` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_statue_of_liberty` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_taj_mahal` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_vatican_city` |
| `monument_effects` | `no_monument_effects` | `disable_pm_default_building_white_house` |
| `monument_effects` | `no_monument_effects` | `disable_pm_monument_prestige_only` |
| `monument_effects` | `no_monument_effects` | `disable_pm_monument_prestige_only_vatican_city` |
| `monument_effects` | `no_monument_effects` | `disable_pm_power_bloc_prestige_only` |
| `monument_effects` | `no_monument_effects` | `disable_pm_power_bloc_statue_religious` |
| `monument_effects` | `no_monument_effects` | `disable_pm_power_bloc_statue_trade_league` |
| `monument_effects` | `no_monument_effects` | `disable_pm_power_bloc_statue_military_treaty` |
| `monument_effects` | `no_monument_effects` | `disable_pm_power_bloc_statue_ideological_union` |
| `monument_effects` | `no_monument_effects` | `disable_pm_power_bloc_statue_sovereign_empire` |
| `monument_effects` | `no_monument_effects` | `force_pm_monument_no_effects` |
| `subject_flags` | `no_subject_flags` | `no_subject_flags` |
| `subject_map_color` | `no_subject_map_color` | `no_subject_map_color` |
| `fantastical_content` | `allow_fantastical_content` | `give_fantastical_content` |
| `fantastical_content` | `no_fantastical_content` | `no_fantastical_content` |
| `custom_rng_seed` | `use_custom_rng_seed` | `use_custom_rng_seed` |
| `dynamic_naming` | `no_dynamic_naming` | `no_dynamic_naming` |
| `ruler_selector` | `allow_ruler_selector` | `give_ruler_selector` |
| `ruler_selector` | `allow_ruler_selector` | `blocks_achievements` |
| `ruler_selector` | `no_ruler_selector` | `no_ruler_selector` |

---

### 4.8 flag 语义（原版 `game_rules.md` 的 "Flags" 表）

`game_rules.md` 只对部分 flag 给出说明，其余标为 `???`（原版文档本身未完成）。原文（下表逐行转录）：

| Flag | 说明（原文 / 中文） |
|---|---|
| `blocks_achievements` | Achievements cannot be earned while this flag is active ／ 该 flag 激活时无法获得成就 |
| `lenient_ai` | `???`（原版未说明；从命名与 `ai_behavior` 上下文可推断为"宽松 AI"） |
| `harsh_ai` | `???`（同上，"严苛 AI"） |
| `low_ai_aggression` | `???`（"低侵略性"） |
| `high_ai_aggression` | `???`（"高侵略性"） |
| `no_subject_flags` | Subject nations' flags do not include their Overlord's flag as a canton ／ 附庸国国旗不再把宗主国国旗作为左上角旗角 |
| `no_subject_map_color` | Subject nations do not share their Overlord's map color ／ 附庸国不再共享宗主国地图颜色 |
| `disable_<production_method_key>` | The specified production method cannot be activated under any circumstances ／ 指定生产方式**无法**启用 |
| `force_<production_method_key>` | The specified production method is forcibly activated and cannot be switched away from ／ 指定生产方式**强制启用**且无法切换掉 |

【文档】来源：`GAME\common\game_rules\game_rules.md`

注意：`disable_pm_*` / `force_pm_*` 是**通配模式**，不是固定 flag 名。原版 `00_game_rules.txt` 里的 `monument_effects` 规则一次性使用了 **43 条**这样的 flag，覆盖所有奇观/权力集团雕像的生产方式。

### 4.9 脚本中如何使用

原版脚本一律使用**标量形式**（不是块形式）：【提取】

原始示例与取证上下文见本篇对应的历史知识库章节。
来源：`GAME\common\ai_strategies\00_default_strategy.txt` 第 4367、4370、6847 行。

| 项目 | 实测 |
|---|---|
| 使用 `has_game_rule` 的文件数 | **18**（`common\*\*.txt` + `events\*.txt`） |
| 观察到的语法 | `has_game_rule = <setting_key>`（单参数） |
| `has_game_rule = { ... }` 块形式 | 全游戏仅 1 处命中，位于 `common\trigger_localization\00_trigger_localization.txt` 第 4489 行——那是 **trigger 的提示文本定义**，不是使用语法。【提取】 |

> **【已答，2026-09-20 探针实测】块形式不存在，只有标量形式** —— 而且**参数是「设置名」不是「规则名」**：
>
> * 标量（原版在用）：`has_game_rule = free_construction_unscaled` → 加载期**零报错**；
>   注意 `free_construction_unscaled` 是**规则 `free_construction` 下的设置名**（`00_game_rules.txt:52`），
>   不是规则名 —— 用规则名当参数会被引擎拒：
>   `Error: has_game_rule trigger [ Invalid database object 'zzprobe_rule' ]`；
> * 块形式（`has_game_rule = { name = … value = yes }`）→ **非法**，两条引擎原文：
>
>   ```text
>   [pdx_persistent_reader.cpp:268]: Error: "Unknown trigger type: value, near line: 5"
>     in file: "common/scripted_triggers/zz_probe_p1_t1.txt" near line: 5
>   [jomini_trigger.cpp:224]: PostValidate of trigger 'has_game_rule' returned false
>     at common/scripted_triggers/zz_probe_p1_t1.txt:5
>   Error: has_game_rule trigger [ Invalid database object '{' ]
>   ```
>
>   —— 引擎把整个块当成参数，先拿 `{` 去查数据库对象、再把块内的 `value` 当触发器键解析。
>   所以**只能写标量**；块形式是本条【未确认】的答案，不是「没人试过」。
> * MOD 自己新增的设置也可以被查到：探针里新增规则 `zzprobe_rule`（设置 `zzprobe_on`，
>   带 `flag = zzprobe_on`）后 `has_game_rule = zzprobe_on` **加载期零报错**。
> * 历史取证（已退役）：旧实验工具的高风险探针启动动作对应的 `[P1]`（探针 `zz_probe_p1_t1/t2/t3.txt`），当前工作树不再提供该子命令。

### 4.10 做 game rule mod 的注意点

| # | 注意点 |
|---|---|
| 1 | **三份本地化键缺一不可**：`rule_<key>`、`setting_<key>`、`setting_<key>_desc`（§4.2 已在本地化文件验证） |
| 2 | flag 只是开关名；**效果要自己在脚本里用 `has_game_rule` 实现**，写 flag 不会自动产生效果 |
| 3 | 原版只在 `common\game_rules\00_game_rules.txt` 定义规则；mod 想**新增**规则需要新文件（如 `01_mymod_rules.txt`），想**改默认值**则只需重写该规则块——game_rules 采用与本数据库一致的"同名键后加载覆盖"语义【推断】 |
| 4 | `apply_modifier = player:very_easy` 形式文档有载，但原版 1.14.2 **零使用**；**1.14.3 探针实测**：`rule = { default = <设置名>  <设置名> = { flag = <名字>  apply_modifier = player:very_easy } }` 这个形状**语法被接受**（加载期无 Unexpected token/PostValidate 报错），但引擎随后报 `[gamedatabase.h:781]: Failed to cache an item for Static Modifiers! Key: very_easy` —— **`very_easy` 不是一个静态修正键**（官方 md 的示例键在 1.14.3 里查不到）。结论：`apply_modifier = <类别>:<静态修正键>`，`类别` 取值 player / ai / all，`键`必须是 `common/static_modifiers/` 里真实存在的键。复算：探针 `zz_probe_a/common/game_rules/zz_probe_rules_v3.txt` |
| 5 | `flag` 名不要与生产方式 key 冲突的写法混用；`disable_pm_*` / `force_pm_*` 必须精确对应 `common\production_methods\` 里的 key |

---

## 5. `common\modifier_type_definitions\`

### 5.1 作用：决定「修饰符键」的流动与显示

`modifier_type_definitions` 定义的是**修饰符键（modifier type）的元数据**。每个键都必须在某个 `*_modifier_types.txt` 里注册过，否则在 `static_modifiers` / 事件 / 法律中使用时会被引擎忽略或报错。

`modifier_types.md` 原文（第 1-3 行）点明了最关键的一点——**键的命名前缀决定它在"修饰符图"里的流动路径**：

> the key determines which category the modifier falls into and thereby its flow through the modifier graph
> for example, a modifier definition key that starts with `country_` with an entry in a static modifier applied to a Power Bloc will flow to countries belonging to that Bloc, but no further
> while a modifier definition key that starts with `state_` with an entry in the same static modifier will flow through countries to all states in that country

【文档】来源：`GAME\common\modifier_type_definitions\modifier_types.md`

**实测前缀分布**（2477<!--claim:def.modtypes--> 个键，按第一个下划线前切分）——与上述规则完全吻合：

| 前缀 | 键数 | 流动含义（据上文推断） |
|---|---|---|
| `country_` | **1138** | 作用于国家；在权力集团上施加时只流到成员国，不再向下 |
| `state_` | **582** | 会穿过国家流到该国所有州 |
| `building_` | **302** | 作用于建筑 |
| `goods_` | **128** | 作用于商品 |
| `ship_` | **71** | 作用于船只 |
| `unit_` | **60** | 作用于陆军单位 |
| `character_` | **41** | 作用于角色 |
| `power_` | **39** | 权力集团（`power_bloc_*`） |
| `interest_` | **80** | 利益集团（`interest_group_*`） |
| `battle_` | **12** | 战斗 |
| `military_` | **11** | 军事 |
| `tax_` / `political_` | 各 **6** | 税收 / 政治 |
| `dummy_` | **1** | 占位 |

【提取】

**后缀分布**同样有强规律：`_add` **1665**<!--claim:defines.suffix_add-->、`_mult` **699**<!--claim:defines.suffix_mult-->、`_bool` **99**<!--claim:defines.suffix_bool-->、`_factor` 5<!--claim:def.suffix_factor-->，另有 9<!--claim:def.suffix_other--> 个键各以其它词结尾（`_support`、`_strata`、`_time`、`_cost`、`_guns`、`_literacy`、`_impact`、`_likelihood`、`_type`，各 1 个）。合计 2364。【提取】——即「加法修正 / 乘法修正 / 布尔开关」三分天下。

### 5.2 字段参考

`modifier_types.md` 给出了全部字段。下表「原版使用量」列为脚本对 15 个实际文件的统计（全库 2364 个键）。

| 字段 | 取值 | 含义（据 `modifier_types.md`） | 原版使用量 |
|---|---|---|---|
| `decimals` | 0 / 1 / 2 | 显示时保留的小数位数 | `1`×1349、`0`×966、`2`×18、**未写**×31 |
| `color` | `good` / `bad` / `neutral` | 显示为正面/负面/中性（`boolean` 类型时决定图标） | `good`×1776、`neutral`×306、`bad`×282 |
| `percent` | `yes` / `no` | 是否按百分比显示（×100 并加 `%`，底层数值不变） | `yes`×824、`no`×61、**未写**×1479 |
| `prefix` | 本地化键名 | 数值前缀 | 6 处，全部是 `"MONEY_PREFIX"` |
| `suffix` | 本地化键名 | 数值后缀 | **1 处**：`"per_wealth"`（`00_modifier_types.txt` 第 1765 行） |
| `boolean` | `yes`（仅 yes 有效） | 视为布尔开关（"某种行为是否存在"） | `yes`×91、`no`×1 |
| `script_only` | `yes` | **不在** `modifier_types.md` 中记载，但原版实际使用；标记为仅脚本可用的修饰符类型 | **66** 个键 |
| `game_data.ai_value` | 数值 | 拥有该修饰符对 AI 的价值，乘以数值得到 AI 追求该类静态修饰符的概率；**仅部分类型实现** | 非零 91 处（与 `boolean=yes` 的 91 个高度重合） |
| `game_data.translate` | 另一个 modifier type 键 | 在特定代码区域应被当作的替代类型 | **24 处，全部在 `04_label_modifier_types.txt`**，取值只有 `unit_offense_add` / `unit_offense_mult` / `unit_defense_add` / `unit_defense_mult` 四个 |
| `game_data.type_set` | `{ ... }` | 该类型所属的"类型集"，用于代码内的特定操作（如法律带来 cultural_acceptance 修饰符时更新文化社群接受度 delta） | **0 处**（`modifier_types.md` 有记载，但原版 1.14.2 无任何文件使用） |

【提取 + 文档】

字段是否必填【未确认】——原版有 35<!--claim:def.modtypes_missing_decimals--> 个键完全没写 `decimals`、1512<!--claim:def.modtypes_missing_percent--> 个键没写 `percent`，说明二者至少有默认值。建议 mod 显式写出 `decimals` / `color` / `percent` 以避免显示异常。

### 5.3 规模与文件分布

| 文件 | 修饰符类型键数 |
|---|---|
| `00_modifier_types.txt` | 451 |
| `01_building_modifier_types.txt` | 351 |
| `02_modifier_types_rules.txt` | 43 |
| `03_modifier_types_script_only.txt` | 32 |
| `04_label_modifier_types.txt` | 24 |
| `05_power_bloc_modifier_types.txt` | 41 |
| `06_country_modifier_types.txt` | 123 |
| `07_description_modifier_types.txt` | 4 |
| `08_movement_modifier_types.txt` | 67 |
| `09_social_class_modifier_types.txt` | 101 |
| `10_country_cultural_acceptance_culture_modifier_types.txt` | 317 |
| `11_country_fervor_taget_culture_modifier_types.txt` | 317 |
| `12_ip4_script_modifiers.txt` | 12 |
| `13_ep2_script_modifiers.txt` | 3 |
| `99_todo_sort_into_other_files.txt` | 478 |

---

### 5.4 完整修饰符类型列表（2364 个）

下表由脚本从 `GAME\common\modifier_type_definitions\` 的 15 个 `.txt` 文件机械提取，按**文件内出现顺序**排列，每个文件一节，两列排版。

> 目录下的第 16 个文件 `modifier_types.md` 是说明文档，不含任何修饰符类型。

#### `00_modifier_types.txt` —— 451 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `01_building_modifier_types.txt` —— 351 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `02_modifier_types_rules.txt` —— 43 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `03_modifier_types_script_only.txt` —— 32 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `04_label_modifier_types.txt` —— 24 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `05_power_bloc_modifier_types.txt` —— 42<!--claim:def.file_defines--> 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `06_country_modifier_types.txt` —— 123 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `07_description_modifier_types.txt` —— 4 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `08_movement_modifier_types.txt` —— 67 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `09_social_class_modifier_types.txt` —— 101 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `10_country_cultural_acceptance_culture_modifier_types.txt` —— 317 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `11_country_fervor_taget_culture_modifier_types.txt` —— 317 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `12_ip4_script_modifiers.txt` —— 12 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `13_ep2_script_modifiers.txt` —— 3 个键

原始示例与取证上下文见本篇对应的历史知识库章节。

#### `99_todo_sort_into_other_files.txt` —— 478 个键

原始示例与取证上下文见本篇对应的历史知识库章节。


---

## 6. `common\static_modifiers\`

### 6.1 它是什么

**static modifier（静态修饰符 / 具名修正）** 是「一组修饰符键 + 数值」的**具名包裹**。定义一次，之后可在事件、决议、法律、日志条目、AI 策略等处用脚本反复施加与移除。

与 §5 的关系：**`static_modifiers` 里用的每个键，都必须先在 `common\modifier_type_definitions\` 注册过**。

| 概念 | 所在目录 | 例子 |
|---|---|---|
| 修饰符**类型**（键的元数据） | `common\modifier_type_definitions\` | `country_prestige_add`、`building_throughput_add` |
| 修饰符**包裹**（键 + 值） | `common\static_modifiers\` | `modifier_olympic_games = { icon = ...; country_prestige_add = 100 }` |

### 6.2 组织形式

| 维度 | 实测 |
|---|---|
| 文件数 | **68** |
| 条目（静态修饰符）总数 | **6128**（口径见下） |
| 每个文件的顶层条目 | 1 ~ 634 不等 |
| 目录内 `.md` 说明文件 | **0**（`static_modifiers` 不像 `modifier_type_definitions` / `game_rules` 那样带说明文档） |
| 文件结构一致性 | **68 / 68 个文件都以 `key = {` 开头**（脚本逐文件校验首行） |

> **计数口径说明（历史 1.14.5 三次复核记录，另列当前值）**
>
> 本节先后写过 **6125** 与 **6121**，**两个都是错的**。正确值是 **6490**<!--claim:def.static-->。
>
> 错因是判据选错了：两次都拿**缩进**当"是否顶层"的依据，而缩进在 PDX
> 脚本里**没有语义** —— 官方文件混用 tab / 2 空格 / 4 空格 / 完全不缩进。
> 顶层与否只能看**花括号深度**。
>
> 用「行首无缩进」数会**静默漏掉 7<!--claim:def.static_indented--> 个确实顶层的键**：
>
> | 文件:行 | 键 | 行首 |
> |---|---|---|
> | `02_event_modifiers.txt:427` | `modifier_great_salt_lake_mapped` | 1 空格 |
> | `02_event_modifiers.txt:432` | `modifier_surveying_suez` | 1 空格 |
> | `02_event_modifiers.txt:437` | `modifier_surveying_panama` | 2 空格 |
> | `02_event_modifiers.txt:442` | `modifier_failed_expedition` | 1 空格 |
> | `content_1_modifiers.txt:1210` | `modifier_objectors_conscription_law` | 1 空格 |
> | `content_1_modifiers.txt:1215` | `modifier_objectors_conscription_bad_law` | 1 空格 |
> | `00_ip3_04_modifiers.txt:62` | `negotiation_pushing_for_law` | 1 空格 |
>
> 历史 1.14.5 的算式是 6121 + 7 = 6128；当前总量为 6490<!--claim:def.static-->，不沿用该历史算式。历史对照中反向为空 —— 顶格但非顶层的键一个也没有，
> 说明「缩进口径」是「深度口径」的真子集，只会少不会多。
>
> 以下是历史 1.14.5 的四种口径对照：
>
> | 口径 | 数量 | 判定 |
> |---|---:|---|
> | **花括号深度为 0** | 6128 | 当时的正确值（当前值见上文） |
> | 行首无缩进 | 6121 | ❌ 漏掉上表 7 个 |
> | 不限缩进、不数深度 | 6129 | ❌ 混入 1 个嵌套键 |
> | 用 `^[A-Za-z_]` 开头 | 6118 | ❌ 另漏 3 个数字开头的键 |
>
> **三个具体陷阱**：
>
> 1. **有 3<!--claim:def.static_digit_leading--> 个静态修饰符以数字开头** —— `1848_popular_radical`、`1848_reactionary_enactment`、
>    `1848_institution_speed`（均在 `content_1_modifiers.txt`）。用 `^[A-Za-z_]` 类正则会漏掉它们。
> 2. **`icon` 是赋值而非块**（`icon = gfx/...dds`），容易被误计或漏计。
> 3. **有 7 个顶层键带缩进** —— 见上表。这一类最隐蔽：总数只差 7，
>    不逐个核对根本看不出来。

【提取】

**文件按"来源"编号分组**，前缀即用途：

| 前缀 | 用途 | 代表文件 |
|---|---|---|
| `00_code_static_modifiers.txt` | **代码内部使用**的全局修正（原版注释：`# All global modifiers are here. They are applied from certain game-features.` / `#these names can NOT be removed or changed, as the code uses them....`） | 150 条，含最大的 `base_values`（49 项） |
| `01_`–`12_` | 按机制分类的通用修正 | `01_loans.txt`、`02_event_modifiers.txt`（383 条）、`03_event_ig_opinion_modifiers.txt`、`04_decision_modifiers.txt`、`05_rule_modifiers.txt`、`06_conscription_modifiers.txt`、`12_diplomatic_modifiers.txt` |
| `07_`–`11_` | 文化 / 生活水平 / 文化接受度 / 文化热情，**机械生成的大批量条目** | `07_culture_standard_of_living.txt`（634）、`08_religion_standard_of_living.txt`、`10_culture_cultural_acceptance_modifiers.txt`（634）、`11_culture_fervor_target_modifiers.txt`（634） |
| `99_` | 测试用 | `99_global_je_test.txt` |
| `101_`/`104_`/`105_`/`106_` | 内容包批次 | `104_modifiers.txt`（173 条） |
| `00_ep2_*` / `00_ip2_*` / `00_ip3_*` / `00_ip4_*` | 对应 DLC / 沉浸包 | `00_ip4_04_modifiers.txt` 等 14 个文件 |
| `agitators_N_modifiers.txt` | Agitators（鼓动家）内容 | `agitators_5_modifiers.txt`（216 条） |
| `content_N_modifiers.txt` | 免费内容批次 | `content_1_modifiers.txt`（275 条） |
| 国家/地区名 | 特定国家内容 | `brazil_1_modifiers.txt`、`bulgarian_modifiers.txt`、`cuban_modifiers.txt`、`libya_modifiers.txt`、`montenegrin_modifiers.txt`、`morocco_modifiers.txt`、`spanish_africa_modifiers.txt` 等 |
| 主题名 | 单一主题 | `state_atheism.txt`、`unification.txt`、`00_companies.txt`、`01_loans.txt` |

文件名**不必**以 `_modifiers.txt` 结尾——实测 7 个文件不是：`00_companies.txt`、`01_loans.txt`、`07_culture_standard_of_living.txt`、`08_religion_standard_of_living.txt`、`99_global_je_test.txt`、`state_atheism.txt`、`unification.txt`。所以 `_modifiers.txt` 只是**命名约定**，不是引擎要求。【提取 + 推断】

### 6.3 典型写法

**最小形态**（只有 icon、无效果，`01_loans.txt` 全文只有这一条）：

原始示例与取证上下文见本篇对应的历史知识库章节。

**最典型形态**（`04_decision_modifiers.txt`）：

原始示例与取证上下文见本篇对应的历史知识库章节。

**带负值与混合作用域**（`99_global_je_test.txt`）：

原始示例与取证上下文见本篇对应的历史知识库章节。

**代码内部使用的大块**（`00_code_static_modifiers.txt` 的 `base_values`，49 项，文件开头带有"不可删除/改名"的原版警告）：

原始示例与取证上下文见本篇对应的历史知识库章节。
（上面只摘了 49 项中的前 9 项，逐字对照 `00_code_static_modifiers.txt` 第 6-25 行。）

**写法要点**

| 要点 | 说明 |
|---|---|
| 顶层块名即「修饰符名」 | 全局唯一，脚本用这个名字引用 |
| `icon` 可选但强烈建议写 | 6087 / 6128 个条目都写了；不写则 UI 上可能无图标 |
| **不含时长** | 定义里**没有** `days` / `months`；持续时间在**施加时**由脚本给出（见 §6.4） |
| 值可以是负数 | `building_throughput_add = -0.1` |
| 同一修饰符可含多个不同作用域的键 | 例如同时含 `country_*` 与 `state_*`（§5.1 的流动规则决定它们如何向下传播） |
| 键名必须是已注册的 modifier type | 否则无效 |

### 6.4 脚本中如何引用

原版使用 `add_modifier` / `remove_modifier` / `has_modifier` 三个脚本命令：

原始示例与取证上下文见本篇对应的历史知识库章节。
来源：`GAME\events\crime_events.txt` 第 445-453 行。【提取】

| 命令 | 用法 | 出现范围 |
|---|---|---|
| `add_modifier = { name = <静态修饰符名> days = <时长> }` | 施加 | `events\*.txt` 中 `add_modifier = {` 共 **4141** 处命中（grep 统计值，非文件数） |
| `remove_modifier = <名>` | 移除 | 15 个事件文件 |
| `has_modifier = <名>` | 判定 | 42 个事件文件 |

【提取】

`days = short_modifier_time` 中的 `short_modifier_time` 是 `common\script_values\` 里的脚本值，说明**时长不属于 static modifier 定义**。

### 6.5 文件与条目统计（68 个文件）

「最大条目数」指该文件内单个静态修饰符所含的**全部键**数量，**含 `icon`**（即块内键数最多的那个块的键数）。
> ⚠️ 这句原先写的是「不含 `icon`」，与列里的数据**矛盾** —— 按「含」算 68/68 行相符，按「不含」只相符 1/68。已按数据如实改写；该表现在由 `v3 tables` 生成，说明与数字不会再各自漂移。

| 文件 | 条目数 | 单个修饰符最大条目数 |
|---|---|---|
| `00_code_static_modifiers.txt` | 151 | 49 |
| `00_companies.txt` | 1 | 2 |
| `00_diplomacy_modifiers.txt` | 3 | 3 |
| `00_ep2_01_modifiers.txt` | 13 | 4 |
| `00_ep2_02_modifiers.txt` | 46 | 6 |
| `00_ep2_03_modifiers.txt` | 20 | 3 |
| `00_ep2_04_modifiers.txt` | 71 | 5 |
| `00_ep2_05_modifiers.txt` | 8 | 3 |
| `00_ep2_06_modifiers.txt` | 41 | 5 |
| `00_intelligentsia_modifiers.txt` | 2 | 2 |
| `00_ip2_02_modifiers.txt` | 55 | 6 |
| `00_ip2_03_modifiers.txt` | 60 | 9 |
| `00_ip2_05_modifiers.txt` | 24 | 5 |
| `00_ip3_02_modifiers.txt` | 80 | 5 |
| `00_ip3_03_modifiers.txt` | 46 | 5 |
| `00_ip3_04_modifiers.txt` | 102 | 6 |
| `00_ip4_02_modifiers.txt` | 63 | 5 |
| `00_ip4_03_modifiers.txt` | 39 | 6 |
| `00_ip4_04_modifiers.txt` | 93 | 7 |
| `00_ip5_02_modifiers.txt` | 26 | 6 |
| `00_ip5_03_modifiers.txt` | 45 | 4 |
| `00_ip5_04_modifiers.txt` | 26 | 4 |
| `00_ip5_05_modifiers.txt` | 3 | 4 |
| `00_ip5_06_modifiers.txt` | 20 | 6 |
| `00_ip5_07_modifiers.txt` | 27 | 5 |
| `00_negotiation_modifiers.txt` | 14 | 3 |
| `00_rlit_static_modifiers.txt` | 164 | 7 |
| `00_test_modifiers.txt` | 13 | 2 |
| `01_loans.txt` | 1 | 1 |
| `02_event_modifiers.txt` | 384 | 6 |
| `03_event_ig_opinion_modifiers.txt` | 80 | 3 |
| `04_decision_modifiers.txt` | 7 | 3 |
| `05_rule_modifiers.txt` | 3 | 2 |
| `06_conscription_modifiers.txt` | 12 | 6 |
| `07_culture_standard_of_living.txt` | 644 | 2 |
| `07_lobbies_03_modifiers.txt` | 14 | 2 |
| `07_sphere_of_influence_2_modifiers.txt` | 29 | 5 |
| `07_sphere_of_influence_4_modifiers.txt` | 76 | 4 |
| `08_religion_standard_of_living.txt` | 34 | 2 |
| `09_movement_modifiers.txt` | 1 | 2 |
| `10_culture_cultural_acceptance_modifiers.txt` | 644 | 2 |
| `11_culture_fervor_target_modifiers.txt` | 644 | 2 |
| `12_diplomatic_modifiers.txt` | 1 | 2 |
| `99_global_je_test.txt` | 3 | 3 |
| `101_modifiers.txt` | 52 | 3 |
| `104_modifiers.txt` | 173 | 4 |
| `105_modifiers.txt` | 162 | 4 |
| `106_modifiers.txt` | 47 | 11 |
| `agitators_1_modifiers.txt` | 83 | 4 |
| `agitators_2_modifiers.txt` | 191 | 6 |
| `agitators_3_modifiers.txt` | 29 | 6 |
| `agitators_4_modifiers.txt` | 211 | 4 |
| `agitators_4_revolution_modifiers.txt` | 110 | 6 |
| `agitators_5_modifiers.txt` | 217 | 12 |
| `agitators_6_modifiers.txt` | 80 | 3 |
| `brazil_1_modifiers.txt` | 29 | 4 |
| `brazil_2_modifiers.txt` | 74 | 7 |
| `brazil_3_modifiers.txt` | 2 | 4 |
| `bulgarian_modifiers.txt` | 9 | 7 |
| `content_1_modifiers.txt` | 282 | 11 |
| `content_2_modifiers.txt` | 151 | 5 |
| `content_3_modifiers.txt` | 117 | 7 |
| `content_4_modifiers.txt` | 144 | 7 |
| `content_204_modifiers.txt` | 119 | 6 |
| `content_304_modifiers.txt` | 129 | 9 |
| `cuban_modifiers.txt` | 17 | 10 |
| `japan_single_fire_events_modifiers.txt` | 27 | 5 |
| `libya_modifiers.txt` | 1 | 6 |
| `montenegrin_modifiers.txt` | 84 | 7 |
| `morocco_modifiers.txt` | 24 | 6 |
| `nemo_modifiers.txt` | 6 | 2 |
| `portugal_single_fire_events_1_modifiers.txt` | 25 | 3 |
| `portuguese_colonialism_modifiers.txt` | 25 | 4 |
| `portuguese_monarchy_modifiers.txt` | 8 | 2 |
| `spanish_africa_modifiers.txt` | 16 | 4 |
| `state_atheism.txt` | 10 | 2 |
| `unification.txt` | 3 | 2 |

---

### 6.6 未声明 `icon` 的静态修饰符（32 个）

`icon` 是静态修饰符**唯一**的非修饰符类型键，但并非强制。下图由脚本机械筛出全部 32 个缺 `icon` 的条目——其中 **26 个在 `00_code_static_modifiers.txt`**（代码内部使用、不在 UI 上作为"临时修正"展示），另有 5 个在 `104_modifiers.txt`、1 个在 `00_test_modifiers.txt`。

| 文件 | 未声明 `icon` 的静态修饰符 |
|---|---|
| `00_code_static_modifiers.txt` | `base_army_attrition` |
| `00_code_static_modifiers.txt` | `base_navy_attrition` |
| `00_code_static_modifiers.txt` | `base_values` |
| `00_code_static_modifiers.txt` | `battle_occupation` |
| `00_code_static_modifiers.txt` | `character_base_values` |
| `00_code_static_modifiers.txt` | `character_historical` |
| `00_code_static_modifiers.txt` | `character_noble` |
| `00_code_static_modifiers.txt` | `country_authority_per_subject` |
| `00_code_static_modifiers.txt` | `country_gdp_construction` |
| `00_code_static_modifiers.txt` | `country_supply_ship_construction_ratio_medium` |
| `00_code_static_modifiers.txt` | `formation_attrition_at_home_hq` |
| `00_code_static_modifiers.txt` | `government_wages_medium` |
| `00_code_static_modifiers.txt` | `holding_revenue_magnate_scale` |
| `00_code_static_modifiers.txt` | `incorporated_state` |
| `00_code_static_modifiers.txt` | `infamy_infamous` |
| `00_code_static_modifiers.txt` | `infamy_notorious` |
| `00_code_static_modifiers.txt` | `infamy_pariah` |
| `00_code_static_modifiers.txt` | `infamy_reputable` |
| `00_code_static_modifiers.txt` | `military_wages_medium` |
| `00_code_static_modifiers.txt` | `opposition_agitator_popularity` |
| `00_code_static_modifiers.txt` | `prestige_goods_supply_army` |
| `00_code_static_modifiers.txt` | `prestige_goods_supply_navy` |
| `00_code_static_modifiers.txt` | `prestige_ranking` |
| `00_code_static_modifiers.txt` | `tax_modifier_medium` |
| `00_code_static_modifiers.txt` | `top_prestige_ranking` |
| `00_code_static_modifiers.txt` | `war_support_battle_effects` |
| `00_test_modifiers.txt` | `more_companies` |
| `104_modifiers.txt` | `anti_industrial_party_modifier` |
| `104_modifiers.txt` | `gods_will_modifier` |
| `104_modifiers.txt` | `stopped_radicals_modifier` |
| `104_modifiers.txt` | `supported_war_leaders_modifier` |
| `104_modifiers.txt` | `supported_war_politics_modifier` |

---

## 7. `common\scripted_modifiers\`

### 7.1 目录内容

目录下**只有一个文件**：【提取】

| 文件 | 大小 | 内容 |
|---|---|---|
| `scripted_modifiers.md` | 192 字节 | 一段示例语法 |

`scripted_modifiers.md` **全文**（14 行）：

原始示例与取证上下文见本篇对应的历史知识库章节。

### 7.2 在 1.14.2 中未被使用

| 检查 | 结果 |
|---|---|
| `common\scripted_modifiers\` 下的实际定义文件 | **0 个**（只有 `.md`） |
| 整个 `GAME\` 树中出现 `scripted_modifier` 字样的位置 | **0 处**（`grep -r` 全库检索，含 `.txt` / 脚本 / GUI） |

【提取】

**结论**：在 Victoria 3 **1.14.2** 中，`scripted_modifiers` 机制看起来是**遗留/文档化的空壳**——目录保留了说明文档，但原版既没有定义任何 scripted modifier，也没有任何地方引用它。【提取 + 推断】

给 mod 作者的建议：

- 想写「带条件分支的动态修正」时，**不要**指望这个目录；改用 `common\script_values\`（可写 `if/limit` 的脚本值）+ `static_modifiers`，或直接在事件/效果里用 `add_modifier` / `if` 组合。
- 若确实要试 `scripted_modifiers`，语法可参考上面的 `.md`（`if = { limit = {...} factor = ... }`），但是否被引擎解析 **【未确认】**——原版 0 使用，无法从本地文件验证。

---

## 8. 未确认项汇总

下面每一条都**查过了**：表格的「本地证据」列写明查到什么（含 `文件:行号` 与复算命令），
「状态」列说明它是否还开着（`【未确认】` + 缺口 / 取证配方，配方定义见
[`04-脚本系统.md`](04-脚本系统.md) §13.1）。**已答的条目不再带标记**，但仍留在表里 ——
清单的价值是「问题有没有答案」，不是「还剩几行字」。
本机 mod 侧的数字一律是**本机快照**（`v3 prefixes` / `pdx.mods.analyse_all()` 复算），不是版本属性。

| # | 未确认项 | 本地证据（可复算） | 状态 |
| --- | --- | --- | --- |
| 1 | **mod 的 defines 文件能否放在 `common/defines/` 的子目录**（如 `common/defines/jomini/`）来覆盖子目录下的原版文件 | 原版自己在 `GAME\common\defines\jomini\` 放了 **3 个**文件（§0.4：根目录 6 + 子目录 3），但那是**内容根之间**的机制（§1.7 证据 3）；mod 层：本机 23 个 mod 里 **12 个**带 `common/defines/`，**12 个文件全部落在根目录、0 个用子目录**（复算：递归枚举 `<mod>\common\defines` 后看相对路径是否含分隔符） | 【未确认】本地无证据（无 mod 层实例）→ 配方 C。**建议**不变：先在根目录用大前缀文件试 |
| 2 | **子目录文件与根目录文件之间的加载先后顺序** | §1.7 证据 3 证明的排序只发生在**内容根之间**（`cw/jomini` → `jomini` → `game` 共享同一相对路径 `common/defines/jomini/00_tooltips.txt`，`NTooltip` 7 键、`MOUSE_MOVE_DISTANCE_TO_UPDATE_TOOLTIP_POSITION` 20.0f → 10.0f）；mod 层 **0 个子目录实例**（同第 1 条）→ 无对照 | 【未确认】本地无证据 → 配方 C |
| 3 | **mod defines 文件与原版文件同名时**是「整文件替换」还是「按键合并」 | 本机 12 个 mod defines 文件**没有一个**与原版 9 个文件同名（复算同第 1 条，按文件名取交集 = ∅）；Wiki 说的是**按键合并**（§1.7 证据 4），而 §1.7 证据 3 的「整体接管」只覆盖内容根之间 | 【未确认】本地无证据 → 配方 C。**建议**不变：mod 永远用不同文件名 + 大前缀 |
| 4 | **`@` 变量的作用域是否跨文件** | `common/defines/` + `jomini/common/defines/` 共 **27 个 `.txt`**：`@` **定义 28 个**（`00_defines.txt` 24 + `00_graphics.txt` 4）、**引用 43 处**（18 + 25），**跨文件引用 = 0 处**（复算：逐行去掉 `#` 注释后正则 `@([A-Za-z_]\w*)`，按其后是否紧跟 `=` 分定义/引用）。例：`@opacity` 定义在 `00_graphics.txt:5`、`@birthrate_transition_slope` 定义在 `00_defines.txt:1787` | 【未确认】本地无证据（「原版不跨文件用」≠「不支持」）→ 配方 C |
| 5 | **引擎 define 的默认值/最大最小值** | defines 本身不声明类型或范围（§0.3 的口径只按**形状**分类：标量 / 内联列表 / 嵌套块）；同族另一例的取值分布已量化：`v3 evidence decimals percent color --dir common/modifier_type_definitions --values` → `decimals` **2333 处 / 3 种取值**、`percent` **885 处 / 2 种**、`color` **2364 处 / 3 种** | 【未确认】本地无证据 → 配方 A/B |
| 6 | **`has_game_rule` 的块形式**（`has_game_rule = { name = ... value = ... }`）是否存在 | **已答（2026-09-20 探针实测）**：**不存在**。引擎逐字：`Unknown trigger type: value, near line: 5`（`common/scripted_triggers/zz_probe_p1_t1.txt`）+ `PostValidate of trigger 'has_game_rule' returned false` + `Error: has_game_rule trigger [ Invalid database object '{' ]` —— 块被整个当成参数；标量形式（原版在用）零报错。**另修正一条**：参数是**设置名**（settings 里的键）而非规则名，用规则名会报 `Invalid database object '<规则名>'`。详见 §4.9 | **已答**：只写标量 + 设置名 |
| 7 | **`apply_modifier` 在 game_rules 中是否仍有效** | **1.14.3 复测**：`v3 evidence apply_modifier` → 原版键 **0 处**；官方 md **1 处赋值**，`common/game_rules/game_rules.md:5` 逐字：`apply_modifier = category:modifier_key	# Apply a modifier to characters matching a specific category. Valid are player, ai, and all. E.G., player:very_easy`；exe 有字面量。**2026-09-20 探针实测**：按 md 形状写进 `common/game_rules/`，**语法被接受**（无 token/PostValidate 报错），但引擎报 `Failed to cache an item for Static Modifiers! Key: very_easy` → **`very_easy` 不是真实静态修正键**，md 的示例值在本版本无效 | **已答**：语法 ✅、值必须是 `common/static_modifiers/` 里存在的键（md 示例值 ❌） |
| 8 | **`game_data.type_set` 的合法取值** | **1.14.3 复测**：`v3 evidence type_set --values` → 原版键 **0 处**；官方 md **1 处赋值**，`common/modifier_type_definitions/modifier_types.md:25` 逐字 `type_set = { cultural_acceptance }`（上方 `:24` 的注释：`# the modifier typesets this type belongs to, used in code to perform bespoke operations (such as updating cultural community acceptance deltas when a country enacts a law with a modifier entry of this type)`）；exe 有字面量 | 【未确认】本地无证据（原版 0 实例，取值全集无从枚举）→ 配方 A |
| 9 | **`decimals` / `percent` / `color` 缺省值** | 数量侧已由断言钉住（1.14.3）：`modifier_type_definitions` 共 **2364** 个键，`decimals` **2333** 处 → **31** 个没写（`def.modtypes_missing_decimals`）、`percent` **885** 处 → **1479** 个没写（`def.modtypes_missing_percent`）、`color` **2364** 处 → 0 个没写。取值分布：`decimals` {1×1349, 0×966, 2×18}、`percent` {yes×824, no×61}、`color` {good×1776, neutral×306, bad×282}（`v3 evidence … --values`） | 【未确认】本地无证据（**缺省值**本身无声明；只能证明「有默认值」）→ 配方 A |
| 10 | **`scripted_modifiers` 是否仍被引擎解析** | **1.14.3 复测**：`v3 evidence scripted_modifier` → 原版键 **0 处**、官方 md **0 处**、exe **无该字面量**（`v3 evidence --exe-grep scripted_modifier` → 0 个）；同族里存在的是 Jomini 模板数据库 —— `v3 evidence --exe-grep scripted` → `CJominiScriptedModifierTemplateDatabase`。**2026-09-20 探针实测**：`common/scripted_modifiers/` 里的**定义会被解析**（照 md 的模板体写 → 无报错），**调用形态**见 [`04-脚本系统.md`](04-脚本系统.md) §7.3：把模板名当键会被引擎识别（引擎会去解析该模板），`scripted_modifier = 名字` / `modifier = { 名字 = yes }` / `modifier = { scripted_modifier = 名字 }` 三种写法全被拒 | **部分已答**：定义 ✅、调用点 = 模板名当键（模板体形状仍【未确认】） |
| 11 | **wiki 的 verified 版本是 1.13，采集时点本机是 1.14.2** | 本机指纹已更新：`env.caligula_branch` = `release/1.14.5`、`env.caligula_rev` = `9f8281a…`（本次 `v3 verify` 已核验），另有头部「版本依据」三条；§1.7 证据 4 已把该 Wiki 页标注为 verified for 1.13，并给出实测反例：`INCORPORATION_TIME_NO_MATCH` 实测 **25**（`00_defines.txt`），Wiki 示例注释写 "Base game 20 years" | 已答（版本差异已量化，见 §0.1 的【Wiki】行与 §1.7 证据 4） |
| 12 | **mod 中新增 define 键是否完全无效** | define **键名确实编译进二进制**：`v3 evidence --exe-grep INCORPORATION_TIME_NO_MATCH` → exe 里存在该标识符（1 个）；§0.4 的 **3488** 个参数全部来自原版 9 个文件。**没有**「新增键被读取」的本地实例 | 【未确认】本地无证据 → 配方 C |

---

## 9. 复现方法

本文全部机械清单可在工作区复跑：

原始示例与取证上下文见本篇对应的历史知识库章节。

> 早期由 5 个 PowerShell 脚本完成同样的事，它们**已全部退休** ——
> 退休原因见 `tools/README.md` 末尾「为什么全 Python 化」。

注意事项（踩过的坑，写给后来者）：

| 坑 | 说明 |
|---|---|
| `NAME =` 与 `{` 分行 | `00_shaders.txt` 第 1-2 行是这种写法；朴素的行内 `= {` 正则匹配会漏掉整个 `NShadersCommon` 块。 |
| 行号 | 若为处理上一条而合并行，必须保留**物理行号**，否则所有行号整体偏移。 |
| 读文件编码 | 早期用 PowerShell `Get-Content` 不带 `-Encoding UTF8`，会按 ANSI（GBK）解码含中文的脚本，导致解析错误。Python 侧固定用 `utf-8-sig`，自动剥离 BOM，这一类问题不再存在。 |
| BOM | 原版 `common/` 下 3,026 个 `.txt` 有 3,002 个带 BOM。编码名用 `utf-8-sig` 即可自动处理，否则首键会被污染成 `\ufefffoo`。 |

---

## 附：速查小结（TL;DR）

| 问题 | 答案 |
|---|---|
| Victoria 3 defines 在哪？ | `GAME\common\defines\`（9 个 `.txt`）；另有 Jomini 层 `...\Victoria 3\jomini\common\defines\`（18 个文件） |
| 命名空间长什么样？ | 顶层块一律 `N` + 大驼峰，如 `NAI`、`NCountry`、`NEconomy`；共 **50** 个去重命名空间、**75** 个顶层块 |
| AI define 在哪个块？ | **`NAI`，且只有一个块，共 1017 个参数，全部扁平**（`00_ai.txt`，1311 行，148 KB） |
| 00_defines.txt 有哪些块？ | 19 个块 / 18 个命名空间；最大的是 `NDiplomacy`(406)、`NEconomy`(294)、`NPops`(211，分 2 块) |
| 怎么覆盖原版 define？ | 在 `<mod>\common\defines\` 新建 `01_xxx.txt`，**只写** `NXXX = { KEY = 新值 }`；**不要**复制整个原版文件 |
| 为什么不用复制整个文件？ | 引擎按「命名空间块名合并、参数名覆盖」解析（证据：`NCamera` 跨文件合并、`NPops`×2、`NGUI`×24） |
| 什么时候才必须整体重写？ | 只有「跨内容根且相对路径完全相同」时（如原版 `game\common\defines\jomini\fog_of_war.txt` 接管 `jomini\common\defines\jomini\fog_of_war.txt`） |
| game_rules 有多少条？ | **15** 条规则、**38** 个 setting、**67** 条 flag 条目（**47** 个去重 flag 键） |
| 修饰符类型有多少？ | **2364** 个，分布在 15 个文件；前缀 `country_`(1095) / `state_`(571) / `building_`(300) 决定作用域流动 |
| 静态修饰符有多少？ | **6128** 个，分布在 **68** 个文件；唯一特殊键是 `icon` |
| scripted_modifiers 呢？ | 1.14.2 中**只有一份 `.md` 文档，零定义、零引用** |
