# Victoria 3 Mod 开发知识库 · 05 defines 与修饰符

> ⚠️ **版本提示**：本文的数量统计与「零使用 / 未使用」类结论**采集于 1.14.2**，而本机游戏已升级到 **1.14.3**，这些结论尚未逐条重测。
> 已经过自动核验的数量断言见 `v3 verify`（其断言表已更新到 1.14.3）；文档与断言表的一致性由 `tools/tests/test_docs_consistency.py` 持续看守。

> **适用版本**：Victoria 3 **1.14.3 (Ice Tea)**（本文的模块结构统计已重测到 1.14.3；个别标注为 1.14.2 的结论为历史采集值）
> 版本依据：`launcher\launcher-settings.json` → `"version": "1.14.3 (Ice Tea)"`、`"rawVersion": "1.14.3"`；`caligula_branch.txt` → `release/1.14.3`；`clausewitz_branch.txt` → `caligula/release/1.14.x`
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
> 参数总数从 3434 涨到 **3488**。现在这些数字由仓库内的解析器
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

> **关于表格表头语言**：本文正文为中文，但**由脚本机械生成的表头保持英文**（如 `Namespace block`、`Leading prefix`、`File`、`Entries`）——因为这些表是脚本直接落盘的，改成中文会引入手写环节、破坏"机械提取"的可追溯性。表内数据（命名空间名、参数名、文件名、计数）与语言无关，不影响使用。

> **关于行号**：全文所有行号均为**物理行号**（1-based），可直接用于在编辑器中跳转。

### 0.4 全局规模（实测）

| 指标 | 数值 | 来源 |
|---|---|---|
| `common\defines\` 下 `.txt` 文件数 | **9**（根目录 6 + `jomini\` 子目录 3） | 【提取】递归枚举 `common\defines\` |
| 顶层命名空间块总数 | **75** | 【提取】§2.2 |
| 去重后命名空间数 | **50** | 【提取】§1.6 |
| 参数条目总数 | **3488**（标量 3313 + 内联列表 175 + 嵌套块 0） | 【提取】§2.1 汇总 |
| 去重后参数名数 | **3481**（有 7 次跨块重复出现） | 【提取】 |

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

```pdx
NAudio = {
	DEFAULT_SELECT = "event:/SFX/UI/Global/select"
	MAP_CLICKSOUND = "event:/SFX/UI/Global/map_click"
}
```
来源：`GAME\common\defines\00_audio.txt` 第 1 行起。【提取】

**2）标量参数**

```pdx
BASE_AGGRESSION = 0.25              # Base chance that AI will consider starting a diplo play each time the goal is checked (1 = 1%)
MIN_SUBJECT_TYPE_VALUE = 1          # ai_value for a subject type is never below this
GOVERNMENT_MONEY_SPENDING_ENABLED = yes   # If this is set to no, the AI for government money spending will be disabled
```
来源：`GAME\common\defines\00_ai.txt` 第 55、15、17 行。【提取】

**3）内联列表参数**（同一行闭合）

```pdx
HIGHLIGHT_COLOR = { 1 1 1 0.5 }
HEAT_MAP_COLOR_FROM = { 0.9  0.9  0.1  0.3 }
```
来源：`GAME\common\defines\00_graphics.txt`（`NMapMode` 块）。全库共 168 条。【提取】

**4）嵌套块**（跨多行）

```pdx
TOOLTIP_TINT_RGBA = {
	1.0 1.0 1.0 1.0
	0.8 0.8 0.8 1.0
	0.6 0.6 0.6 1.0
	0.1 0.1 0.1 0.2
}
```
来源：`GAME\common\defines\jomini\00_tooltips.txt`。全库仅 3 条。【提取】

**5）注释**：`#` 到行尾。原版 defines 的注释密度极高，是理解每个参数语义的第一手资料。

**6）块内局部脚本变量 `@name`**

```pdx
NMapMode = {
	@opacity = 1
	...
	COLOR_WAR_SELF  = { 0.11 0.46 0.05 @opacity }
	COLOR_WAR_ENEMY = { 0.5 0.04 0.02 @opacity }
}
```
来源：`GAME\common\defines\00_graphics.txt` 第 5、46、47 行。【提取】

**7）顶层脚本变量 + 表达式 `@[ ... ]`**

```pdx
# 定义在第 1709-1752 行，位于块外（顶层）
@min_birthrate = 0.00060
@max_birthrate = 0.00450
@birthrate_at_transition = @[max_birthrate*transition_birthrate_mult]
@rate_at_equilibrium = @[pop_growth_equilibrium_sol*((birthrate_at_transition-max_birthrate)/pop_growth_transition_sol)+max_birthrate]

# 在后面的 NPops 块内引用（第 1775 行起）
NPops = {
	POP_GROWTH_BIRTHRATE_PRETRANSITION_SLOPE = @birthrate_pretransition_slope
	POP_GROWTH_MIN_BIRTHRATE = @min_birthrate
}
```
来源：`GAME\common\defines\00_defines.txt`。【提取】

`@[...]` 内支持 `+ - * /` 与括号；`00_defines.txt` 第 1660-1661 行还有块内定义的例子：

```pdx
	@starvation_threshold = 0.4
	@starvation_scaling_factor = @[1/starvation_threshold]
```

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

```
MAP_LENS_political_lens
MAP_LENS_production_lens
MAP_LENS_diplomatic_lens
MAP_LENS_military_lens
```
——即**前缀大写 + 后缀小写**的拼接式命名，说明引擎允许参数名含小写，只是原版几乎不用。

其余规则：键名形如 `[A-Z][A-Z0-9_]*`，无前导/尾随下划线，无连字符。【提取】

### 1.6 全部命名空间清单

下表由脚本按命名空间聚合，`Params` 为该命名空间在**全部文件**中的参数条目总和（含重复块累加）。完整逐块明细（第 2 节）见 §2.2。

| Namespace | Blocks | Params | File(s) |
|---|---|---|---|
| `NAI` | 1 | 1017 | 00_ai.txt |
| `NAudio` | 1 | 23 | 00_audio.txt |
| `NBattle` | 1 | 66 | 00_defines.txt |
| `NCamera` | 1 | 18 | 00_graphics.txt |
| `NCharacters` | 1 | 103 | 00_defines.txt |
| `NCities` | 1 | 28 | 00_graphics.txt |
| `NCoasts` | 1 | 6 | 00_graphics.txt |
| `NCountry` | 1 | 44 | 00_defines.txt |
| `NDebug` | 1 | 3 | 00_defines.txt |
| `NDiplomacy` | 1 | 406 | 00_defines.txt |
| `NEconomy` | 1 | 294 | 00_defines.txt |
| `NEdgeOfWorld` | 1 | 19 | 00_shaders.txt |
| `NEvents` | 1 | 3 | 00_defines.txt |
| `NFogOfWar` | 1 | 23 | jomini/fog_of_war.txt |
| `NFortifications` | 1 | 5 | 00_graphics.txt |
| `NFrontend` | 1 | 3 | 00_graphics.txt |
| `NGUI` | 24 | 189 | 00_interfaces.txt |
| `NGame` | 1 | 6 | 00_defines.txt |
| `NGraphics` | 1 | 136 | 00_graphics.txt |
| `NGuiFlag` | 1 | 3 | 00_shaders.txt |
| `NHarvestConditions` | 1 | 2 | 00_defines.txt |
| `NJominiEars` | 1 | 2 | 00_graphics.txt |
| `NJominiGraphics` | 1 | 3 | 00_graphics.txt |
| `NJominiMap` | 1 | 4 | 00_defines.txt |
| `NJominiMapGraphics` | 1 | 11 | 00_graphics.txt |
| `NLenses` | 1 | 9 | 00_interfaces.txt |
| `NMapCoa` | 1 | 11 | 00_shaders.txt |
| `NMapMode` | 1 | 97 | 00_graphics.txt |
| `NMapName` | 1 | 8 | 00_graphics.txt |
| `NMapmodeStripes` | 1 | 6 | 00_shaders.txt |
| `NMilitary` | 1 | 169 | 00_defines.txt |
| `NNavy` | 1 | 98 | 00_graphics.txt |
| `NPolitics` | 1 | 208 | 00_defines.txt |
| `NPops` | 2 | 227 | 00_defines.txt |
| `NPortrait` | 1 | 5 | 00_graphics.txt |
| `NPowerBlocCoa` | 1 | 21 | 00_graphics.txt |
| `NPowerBlocStatueCamera` | 1 | 7 | 00_graphics.txt |
| `NPowerBlocs` | 1 | 24 | 00_defines.txt |
| `NProvinceHighlight` | 1 | 4 | 00_graphics.txt |
| `NRivers` | 1 | 6 | jomini/rivers.txt |
| `NRoutes` | 1 | 9 | 00_graphics.txt |
| `NSaves` | 1 | 1 | 00_interfaces.txt |
| `NShadersCommon` | 1 | 1 | 00_shaders.txt |
| `NShipViewer` | 1 | 22 | 00_graphics.txt |
| `NTechnology` | 1 | 4 | 00_defines.txt |
| `NText` | 1 | 6 | 00_defines.txt |
| `NTooltip` | 1 | 7 | jomini/00_tooltips.txt |
| `NTravelNetwork` | 2 | 43 | 00_defines.txt, 00_graphics.txt |
| `NTrend` | 1 | 2 | 00_interfaces.txt |
| `NWar` | 1 | 76 | 00_defines.txt |

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

```
# This file overrides `cw/jomini/modules/tooltip_manager/data/common/defines/jomini/00_tooltips.txt`
```

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

```
你的mod/
├── descriptor.mod
└── common/
    └── defines/
        └── 01_mymod_ai_defines.txt      ← 文件名前缀必须大于 00
```

`01_mymod_ai_defines.txt` 内容（**只写要改的键**）：

```pdx
# 只放改动项；块的其余参数由原版文件提供
NAI = {
	BASE_AGGRESSION = 5
	MIN_SUBJECT_TYPE_VALUE = 0
	GOVERNMENT_MONEY_SPENDING_ENABLED = no
}

NCountry = {
	INCORPORATION_TIME_NO_MATCH = 100
}
```

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
| `00_ai.txt` | 1 | 1017 | 0 | 0 | **1017** |
| `00_audio.txt` | 1 | 23 | 0 | 0 | **23** |
| `00_defines.txt` | 19 | 1674 | 5 | 0 | **1679** |
| `00_graphics.txt` | 19 | 369 | 123 | 0 | **492** |
| `00_interfaces.txt` | 27 | 161 | 40 | 0 | **201** |
| `00_shaders.txt` | 5 | 35 | 5 | 0 | **40** |
| `jomini/00_tooltips.txt` | 1 | 6 | 1 | 0 | **7** |
| `jomini/fog_of_war.txt` | 1 | 22 | 1 | 0 | **23** |
| `jomini/rivers.txt` | 1 | 6 | 0 | 0 | **6** |
| **合计** | **75** | **3313** | **175** | **0** | **3488** |

【提取】

### 2.2 全部 75 个顶层命名空间块

「Line」为该块在所属文件中的**物理起始行号**。

| File | Namespace block | Line | Scalar | Inline list | Nested | Total |
|---|---|---|---|---|---|---|
| `00_ai.txt` | `NAI` | 1 | 1017 | 0 | 0 | 1017 |
| `00_audio.txt` | `NAudio` | 1 | 23 | 0 | 0 | 23 |
| `00_defines.txt` | `NGame` | 1 | 6 | 0 | 0 | 6 |
| `00_defines.txt` | `NJominiMap` | 10 | 4 | 0 | 0 | 4 |
| `00_defines.txt` | `NCountry` | 17 | 44 | 0 | 0 | 44 |
| `00_defines.txt` | `NPolitics` | 64 | 208 | 0 | 0 | 208 |
| `00_defines.txt` | `NEconomy` | 358 | 293 | 1 | 0 | 294 |
| `00_defines.txt` | `NMilitary` | 728 | 169 | 0 | 0 | 169 |
| `00_defines.txt` | `NDiplomacy` | 942 | 406 | 0 | 0 | 406 |
| `00_defines.txt` | `NPowerBlocs` | 1417 | 24 | 0 | 0 | 24 |
| `00_defines.txt` | `NPops` | 1444 | 207 | 4 | 0 | 211 |
| `00_defines.txt` | `NPops` | 1813 | 16 | 0 | 0 | 16 |
| `00_defines.txt` | `NEvents` | 1840 | 3 | 0 | 0 | 3 |
| `00_defines.txt` | `NTechnology` | 1846 | 4 | 0 | 0 | 4 |
| `00_defines.txt` | `NCharacters` | 1854 | 103 | 0 | 0 | 103 |
| `00_defines.txt` | `NBattle` | 2014 | 66 | 0 | 0 | 66 |
| `00_defines.txt` | `NWar` | 2102 | 76 | 0 | 0 | 76 |
| `00_defines.txt` | `NTravelNetwork` | 2183 | 34 | 0 | 0 | 34 |
| `00_defines.txt` | `NHarvestConditions` | 2228 | 2 | 0 | 0 | 2 |
| `00_defines.txt` | `NText` | 2233 | 6 | 0 | 0 | 6 |
| `00_defines.txt` | `NDebug` | 2243 | 3 | 0 | 0 | 3 |
| `00_graphics.txt` | `NMapMode` | 1 | 38 | 59 | 0 | 97 |
| `00_graphics.txt` | `NMapName` | 157 | 7 | 1 | 0 | 8 |
| `00_graphics.txt` | `NJominiMapGraphics` | 187 | 11 | 0 | 0 | 11 |
| `00_graphics.txt` | `NJominiGraphics` | 202 | 3 | 0 | 0 | 3 |
| `00_graphics.txt` | `NJominiEars` | 208 | 2 | 0 | 0 | 2 |
| `00_graphics.txt` | `NGraphics` | 213 | 105 | 31 | 0 | 136 |
| `00_graphics.txt` | `NFrontend` | 417 | 3 | 0 | 0 | 3 |
| `00_graphics.txt` | `NCamera` | 423 | 14 | 4 | 0 | 18 |
| `00_graphics.txt` | `NCities` | 450 | 25 | 3 | 0 | 28 |
| `00_graphics.txt` | `NFortifications` | 496 | 5 | 0 | 0 | 5 |
| `00_graphics.txt` | `NCoasts` | 504 | 6 | 0 | 0 | 6 |
| `00_graphics.txt` | `NRoutes` | 513 | 6 | 3 | 0 | 9 |
| `00_graphics.txt` | `NPortrait` | 531 | 5 | 0 | 0 | 5 |
| `00_graphics.txt` | `NProvinceHighlight` | 539 | 4 | 0 | 0 | 4 |
| `00_graphics.txt` | `NTravelNetwork` | 548 | 9 | 0 | 0 | 9 |
| `00_graphics.txt` | `NPowerBlocCoa` | 561 | 7 | 14 | 0 | 21 |
| `00_graphics.txt` | `NPowerBlocStatueCamera` | 591 | 7 | 0 | 0 | 7 |
| `00_graphics.txt` | `NNavy` | 601 | 96 | 2 | 0 | 98 |
| `00_graphics.txt` | `NShipViewer` | 716 | 16 | 6 | 0 | 22 |
| `00_interfaces.txt` | `NLenses` | 1 | 9 | 0 | 0 | 9 |
| `00_interfaces.txt` | `NGUI` | 13 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 17 | 48 | 15 | 0 | 63 |
| `00_interfaces.txt` | `NGUI` | 95 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 100 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NTrend` | 105 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NGUI` | 110 | 13 | 0 | 0 | 13 |
| `00_interfaces.txt` | `NGUI` | 130 | 5 | 4 | 0 | 9 |
| `00_interfaces.txt` | `NGUI` | 142 | 8 | 0 | 0 | 8 |
| `00_interfaces.txt` | `NGUI` | 153 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NSaves` | 159 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 163 | 6 | 0 | 0 | 6 |
| `00_interfaces.txt` | `NGUI` | 172 | 0 | 1 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 176 | 3 | 0 | 0 | 3 |
| `00_interfaces.txt` | `NGUI` | 182 | 4 | 0 | 0 | 4 |
| `00_interfaces.txt` | `NGUI` | 189 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NGUI` | 194 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NGUI` | 199 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 203 | 6 | 0 | 0 | 6 |
| `00_interfaces.txt` | `NGUI` | 216 | 7 | 0 | 0 | 7 |
| `00_interfaces.txt` | `NGUI` | 226 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 230 | 2 | 0 | 0 | 2 |
| `00_interfaces.txt` | `NGUI` | 235 | 0 | 8 | 0 | 8 |
| `00_interfaces.txt` | `NGUI` | 246 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 250 | 1 | 0 | 0 | 1 |
| `00_interfaces.txt` | `NGUI` | 254 | 18 | 12 | 0 | 30 |
| `00_interfaces.txt` | `NGUI` | 303 | 16 | 0 | 0 | 16 |
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

整个文件**只有一个**顶层命名空间块 `NAI`，起始于第 1 行，包含 **1017** 个参数，全部为标量，无内联列表、无嵌套块。文件共 1311 行，全文中 `= {` 只出现 1 次（即第 1 行的 `NAI = {`）。【提取】

结构明细见 §3.1，全部 1017 个参数名见 §3.3。

### 2.4 `00_audio.txt`

| 命名空间块 | 起始行 | 条目数 |
|---|---|---|
| `NAudio` | 1 | 23 |

23 条全部是音频事件路径字符串（FMOD/Wwise 风格 `event:/...`），例如 `DEFAULT_SELECT = "event:/SFX/UI/Global/select"`、`MAP_CLICKSOUND = "event:/SFX/UI/Global/map_click"`、`DEFAULT_NOTIFICATION_SOUND = "event:/SFX/UI/Alerts/Toasts/_transient"`。【提取】

其中 4 条是按地图模式键拼接的：`MAP_LENS_political_lens`、`MAP_LENS_production_lens`、`MAP_LENS_diplomatic_lens`、`MAP_LENS_military_lens`（即 `MAP_LENS_<地图模式 key>`）。这也是全库唯一 4 个含小写的参数名（见 §1.5）。【提取】

> 做音频 mod 时注意：这里定义的是「UI 音效绑定点」，不是音频资源本身；资源在 `sound\` 下。

### 2.5 `00_defines.txt` —— 主 defines 文件

19 个顶层块，但只有 **18 个不同命名空间**——`NPops` 在同一文件内出现了 **2 次**（第 1404 行、第 1773 行），这是 §1.7 证据 2 的来源之一。

| # | 命名空间 | 块起始行 | 该命名空间的块数 | 参数合计 |
|---|---|---|---|---|
| 1 | `NGame` | 1 | 1 | 6 |
| 2 | `NJominiMap` | 10 | 1 | 4 |
| 3 | `NCountry` | 17 | 1 | 44 |
| 4 | `NPolitics` | 64 | 1 | 208 |
| 5 | `NEconomy` | 358 | 1 | 294 |
| 6 | `NMilitary` | 728 | 1 | 169 |
| 7 | `NDiplomacy` | 942 | 1 | 406 |
| 8 | `NPowerBlocs` | 1417 | 1 | 24 |
| 9 | `NPops` | 1444, 1813 | **2** | 211 + 16 = 227 |
| 10 | `NEvents` | 1840 | 1 | 3 |
| 11 | `NTechnology` | 1846 | 1 | 4 |
| 12 | `NCharacters` | 1854 | 1 | 103 |
| 13 | `NBattle` | 2014 | 1 | 66 |
| 14 | `NWar` | 2102 | 1 | 76 |
| 15 | `NTravelNetwork` | 2183 | 1 | 34 |
| 16 | `NHarvestConditions` | 2228 | 1 | 2 |
| 17 | `NText` | 2233 | 1 | 6 |
| 18 | `NDebug` | 2243 | 1 | 3 |
| | **合计** | | **19 块** | **1679** |

【提取】——这 18 个命名空间与官方 Wiki [Defines](https://vic3.paradoxwikis.com/Defines) 的 §2 小节列表**完全一致**，可作为交叉验证。

规模最大的四块：`NDiplomacy`（406）、`NEconomy`（294）、`NPops`（211）、`NPolitics`（208）。

### 2.6 `00_graphics.txt`

19 个块，492 个条目（其中 123 条是 `KEY = { r g b a }` 形式的纯值列表；**0 条嵌套块** —— defines 层是完全扁平的，这也是它与其他 `common\` 数据目录最大的结构差别）。

| 命名空间块 | 起始行 | 标量 | 内联列表 | 嵌套 | 合计 |
|---|---|---|---|---|---|
| `NMapMode` | 1 | 38 | 59 | 0 | 97 |
| `NMapName` | 157 | 7 | 1 | 0 | 8 |
| `NJominiMapGraphics` | 187 | 11 | 0 | 0 | 11 |
| `NJominiGraphics` | 202 | 3 | 0 | 0 | 3 |
| `NJominiEars` | 208 | 2 | 0 | 0 | 2 |
| `NGraphics` | 213 | 105 | 31 | 0 | 136 |
| `NFrontend` | 417 | 3 | 0 | 0 | 3 |
| `NCamera` | 423 | 14 | 4 | 0 | 18 |
| `NCities` | 450 | 25 | 3 | 0 | 28 |
| `NFortifications` | 496 | 5 | 0 | 0 | 5 |
| `NCoasts` | 504 | 6 | 0 | 0 | 6 |
| `NRoutes` | 513 | 6 | 3 | 0 | 9 |
| `NPortrait` | 531 | 5 | 0 | 0 | 5 |
| `NProvinceHighlight` | 539 | 4 | 0 | 0 | 4 |
| `NTravelNetwork` | 548 | 9 | 0 | 0 | 9 |
| `NPowerBlocCoa` | 561 | 7 | 14 | 0 | 21 |
| `NPowerBlocStatueCamera` | 591 | 7 | 0 | 0 | 7 |
| `NNavy` | 601 | 96 | 2 | 0 | 98 |
| `NShipViewer` | 716 | 16 | 6 | 0 | 22 |
| | | **369** | **123** | **0** | **492** |

【提取】注意 `NCamera` 与 Jomini 层的 `NCamera` 合并（§1.7 证据 1）；`NNavy` 是本文件第二大块。

### 2.7 `00_interfaces.txt`

27 个块，但只有 **4 个不同命名空间**——`NGUI` 在同一个文件里出现了 **24 次**（这是 §1.7 证据 2 的第二个来源）。

| 命名空间块 | 出现次数 | 各块起始行 | 合计条目 |
|---|---|---|---|
| `NGUI` | **24** | 13, 17, 95, 100, 110, 130, 142, 153, 163, 172, 176, 182, 189, 194, 199, 203, 216, 226, 230, 235, 246, 250, 254, 303 | 189 |
| `NLenses` | 1 | 1 | 9 |
| `NTrend` | 1 | 105 | 2 |
| `NSaves` | 1 | 159 | 1 |
| | | | **201** |

【提取】

同一文件里 24 次声明同一个 `NGUI` 块，是"同名块合并"最直观的原版用法——原版作者用这种方式给 `NGUI` 分区加注释组织内容。

### 2.8 `00_shaders.txt`

> 📌 本节的「起始行」同 §1.7 的说明：行号列是快照，其余列由 `v3 tables` 重算。

5 个块，40 个条目。

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

```pdx
NShadersCommon =
{
	PARALLAX_HEIGHT = 8			# Height of parallax effects
}
```

本节也顺带说明：官方 Wiki 的 `00_shaders` 一节（列出 ShadersCommon / MapCoa / MapmodeStripes / EdgeOfWorld / GuiFlag）与本机 1.14.2 实测**一致**。

### 2.9 `jomini\` 子目录（3 个文件，36 个条目）

| 文件 | 命名空间块 | 起始行 | 标量 | 内联列表 | 嵌套 | 合计 |
|---|---|---|---|---|---|---|
| `jomini/00_tooltips.txt` | `NTooltip` | 2 | 6 | 1 | 0 | 7 |
| `jomini/fog_of_war.txt` | `NFogOfWar` | 1 | 22 | 1 | 0 | 23 |
| `jomini/rivers.txt` | `NRivers` | 2 | 6 | 0 | 0 | 6 |

【提取】

这 3 个文件是 game 内容根对 Jomini 层同名文件的**整体接管**文件（见 §1.7 证据 3）。它们的相对路径 `common/defines/jomini/*.txt` 必须与 Jomini 层完全一致才能生效。

Jomini 内容根另有 15 个未被 game 层接管的 defines 文件（`00_adaptive_music.txt`、`00_audio_persistent_objects.txt`、`music_player_defines.txt`、`graphic/00_coa.txt`、`jomini/adjacencies.txt`、`jomini/camera.txt`、`jomini/icons.txt`、`jomini/mapeditor.txt`、`jomini/modifiers.txt`、`jomini/multiplayer.txt`、`jomini/portraits.txt`、`jomini/settings.txt`、`jomini/social.txt`、`jomini/text_coloring.txt`、`jomini/text_formatting.txt`），它们通过跨文件合并机制生效。【提取】

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

| Namespace block | Start line | Scalar params | Inline-list params | Nested blocks | Total params |
|---|---|---|---|---|---|
| `NAI` | 1 | 1017 | 0 | 0 | **1017** |

---

### 3.2 参数前缀分组（104 组）

由于 `NAI` 是完全扁平的 1017 条键，实际阅读时需要靠**命名前缀**分组。下表按「第一个下划线之前的部分」机械分组，按参数数降序排列。

> 说明：这是**机械切分**，不是官方分组。同一前缀可能跨越不同语义（如 `MIN_` 是通用修饰前缀）。原版文件本身没有 `# ===== 分区 =====` 式的分区标题，只有零散的行内/行上注释。

| Leading prefix | Param count |
|---|---|
| `DIPLO_*` | 210 |
| `PRODUCTION_*` | 89 |
| `MONEY_*` | 45 |
| `AI_*` | 34 |
| `GOAL_*` | 33 |
| `AUTONOMOUS_*` | 30 |
| `FLEET_*` | 30 |
| `UNIFICATION_*` | 30 |
| `CHANGE_*` | 24 |
| `MOBILIZATION_*` | 24 |
| `GOVERNMENT_*` | 23 |
| `POWER_*` | 17 |
| `NAVAL_*` | 16 |
| `OWNER_*` | 15 |
| `COMPANY_*` | 13 |
| `DIPLOMATIC_*` | 13 |
| `FRONT_*` | 12 |
| `CONSTRUCTION_*` | 11 |
| `MIN_*` | 11 |
| `RAID_*` | 11 |
| `SHIP_*` | 11 |
| `BLOCKADE_*` | 10 |
| `DEFEND_*` | 10 |
| `PROTECT_*` | 10 |
| `TRADE_*` | 10 |
| `TREATIES_*` | 10 |
| `HQ_*` | 9 |
| `INVADE_*` | 9 |
| `PIRACY_*` | 9 |
| `LAND_*` | 8 |
| `MILITARY_*` | 8 |
| `NATIONALIZATION_*` | 8 |
| `NUM_*` | 8 |
| `SUPPLY_*` | 8 |
| `WAGE_*` | 8 |
| `CONSUMPTION_*` | 7 |
| `RECRUITABLE_*` | 7 |
| `REFORM_*` | 7 |
| `WAR_*` | 7 |
| `COLONY_*` | 6 |
| `CONSCRIPTION_*` | 6 |
| `DISBAND_*` | 6 |
| `HUNT_*` | 6 |
| `SELL_*` | 6 |
| `TREATY_*` | 6 |
| `IDEOLOGICAL_*` | 5 |
| `IMPOSE_*` | 5 |
| `PORT_*` | 5 |
| `RAISE_*` | 5 |
| `SUBSIDIZE_*` | 5 |
| `VIOLATE_*` | 5 |
| `ESCORT_*` | 4 |
| `INSTITUTION_*` | 4 |
| `INTERCEPT_*` | 4 |
| `MAX_*` | 4 |
| `REGIME_*` | 4 |
| `START_*` | 4 |
| `COLONIZATION_*` | 3 |
| `INFLUENCE_*` | 3 |
| `LOWER_*` | 3 |
| `REJECTED_*` | 3 |
| `STRAIT_*` | 3 |
| `STRATEGIC_*` | 3 |
| `ATTITUDE_*` | 2 |
| `BASELINE_*` | 2 |
| `COMMANDER_*` | 2 |
| `COUNTRY_*` | 2 |
| `DECLARE_*` | 2 |
| `HIGH_*` | 2 |
| `INCORPORATE_*` | 2 |
| `LOW_*` | 2 |
| `PRIVATEER_*` | 2 |
| `SEA_*` | 2 |
| `TECH_*` | 2 |
| `TRANSPORT_*` | 2 |
| `UNUSED_*` | 2 |
| `AUTHORITY_*` | 1 |
| `BASE_*` | 1 |
| `BUILDING_*` | 1 |
| `COMFORTABLE_*` | 1 |
| `CONTAINMENT_*` | 1 |
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
| `RETIRE_*` | 1 |
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

```text
DEFAULT_STRATEGY_STRING
STRATEGY_RANDOM_FACTOR
TICKS_FOR_FULL_SPENDING_VARIABLES_UPDATE
NUM_FAILED_MONEY_SPENDING_ATTEMPTS_FOR_UPDATE
NUM_FAILED_AUTHORITY_SPENDING_ATTEMPTS_FOR_UPDATE
MIN_TICKS_TO_UPDATE_BUILDING_SPENDING_STATE
MAX_TICKS_TO_UPDATE_BUILDING_SPENDING_STATE
MIN_SUBJECT_TYPE_VALUE
GOVERNMENT_MONEY_SPENDING_ENABLED
GOVERNMENT_AUTHORITY_SPENDING_ENABLED
TAX_LEVEL_CHANGES_ENABLED
GOVERNMENT_WAGE_LEVEL_CHANGES_ENABLED
MILITARY_WAGE_LEVEL_CHANGES_ENABLED
CHANGE_GOVERNMENT_WAGE_LEVEL_START_OF_GAME_DAYS_TO_WAIT
CHANGE_MILITARY_WAGE_LEVEL_START_OF_GAME_DAYS_TO_WAIT
BASELINE_GOVERNMENT_WAGE_LEVEL
BASELINE_MILITARY_WAGE_LEVEL
WAGE_CUT_INCOME_RATIO_THRESHOLD
WAGE_RESTORE_INCOME_RATIO_THRESHOLD
WAGE_RAISE_MIN_INCOME_RATIO
MILITARY_WAGE_CUT_CREDIT_RATIO
WAGE_RAISE_MIN_GOLD_RESERVE_FRACTION
WAGE_CUT_MAX_RADICALS_FRACTION
WAGE_CUT_SIGNIFICANT_DEBT_RATIO
WAGE_CUT_MIN_WEEKS_OF_GOLD_RESERVES
WAGE_RAISE_MIN_BALANCE_TO_IGNORE_RATIO
PRODUCTION_BUILDING_CONSTRUCTION_ENABLED
AUTONOMOUS_INVESTMENT_CONSTRUCTION_ENABLED
CHANGE_STRATEGY_THRESHOLD
CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE
CHANGE_STRATEGY_POLITICAL_NEW_RULER
CHANGE_STRATEGY_POLITICAL_REGIME_CHANGE
CHANGE_STRATEGY_POLITICAL_LAW_ENACTED
CHANGE_STRATEGY_DIPLOMATIC_STATE_GAINED_OR_LOST
CHANGE_STRATEGY_DIPLOMATIC_UNIFICATION_CANDIDATE
CHANGE_STRATEGY_DIPLOMATIC_LIBERTY_DESIRE_CHANGE
COUNTRY_GOAL_STRATEGIC_UPDATE_COUNT
COUNTRY_GOAL_ADJUSTMENT_UPDATE_COUNT
DECLARE_BANKRUPTCY_MIN_DAYS_IN_DEFAULT
DECLARE_BANKRUPTCY_COOLDOWN_DAYS
BASE_AGGRESSION
UNIFICATION_AGGRESSION_MULT_HIGHER_TIER
UNIFICATION_AGGRESSION_MULT_SAME_TIER
DIPLO_PROPOSAL_DAYS_LEFT_MAX
DIPLO_PROPOSAL_DAYS_LEFT_MIN
DIPLO_PROPOSAL_ANSWER_CHANCE
DIPLO_PROPOSAL_TO_PLAYER_COOLDOWN_MONTHS
DIPLO_PROPOSAL_LIKELY_NON_ACCEPTED_COOLDOWN_MONTHS
DIPLO_PROPOSAL_LIKELY_NON_ACCEPTED_TREATY_COOLDOWN_MONTHS
DIPLO_PROPOSAL_NO_OBLIGATION_COOLDOWN_MONTHS
DIPLO_PROPOSAL_ACCEPT_THRESHOLD
DIPLO_PROPOSAL_HALFWAY_RANDOM_ACCEPTANCE_THRESHOLD
DIPLO_PROPOSAL_GUARANTEED_RANDOM_ACCEPTANCE_THRESHOLD
DIPLO_PROPOSAL_BREAK_THRESHOLD
DIPLO_PROPOSAL_TRANSFER_PACT_RELUCTANCE
OBLIGATION_RECENTLY_REPUDIATED_DESIRE_MULT
DIPLO_ACCEPTANCE_CALL_IN_OBLIGATION
DIPLO_ACCEPTANCE_CALL_IN_OBLIGATION_RECENTLY_REPUDIATED
DIPLO_BREAK_PACT_WEIGHT
DIPLOMATIC_DEMAND_ALWAYS_ACCEPT_THRESHOLD
DIPLOMATIC_DEMAND_DAYS_LEFT_MAX
DIPLOMATIC_DEMAND_DAYS_LEFT_MIN
DIPLOMATIC_DEMAND_ANSWER_CHANCE
DIPLOMATIC_DEMAND_ACCEPTANCE_BASE
DIPLOMATIC_DEMAND_ACCEPTANCE_WARGOAL_IMPACT
DIPLOMATIC_DEMAND_ACCEPTANCE_MILITARY_POWER_SCALE
DIPLOMATIC_DEMAND_ACCEPTANCE_MILITARY_POWER_FACTOR
DIPLOMATIC_DEMAND_ACCEPTANCE_INCORPORATED_STATE_FACTOR
DIPLOMATIC_DEMAND_ACCEPTANCE_SUBJUGATION_FACTOR
DIPLOMATIC_DEMAND_ACCEPTANCE_ANNEXATION_FACTOR
DIPLOMATIC_DEMAND_ACCEPTANCE_LOYAL_SUBJECT_FACTOR
DIPLOMATIC_DEMAND_ACCEPTANCE_ANNEXATION_AS_LOYAL_SUBJECT_FACTOR
INFLUENCE_DEFICIT_RECOVER_INFLUENCE_BASE_VALUE
INFLUENCE_DEFICIT_RECOVER_INFLUENCE_RANDOM_FACTOR
INFLUENCE_DEFICIT_RECOVER_INFLUENCE_OVER_SPENDING_LIMIT_MULT
MIN_AVAILABLE_LABOR_FOR_NEW_BUILDING
MIN_COMBAT_UNITS_FOR_COMMANDER_ABSOLUTE
MIN_COMBAT_UNITS_FOR_COMMANDER_ABSOLUTE_MARINES
MIN_COMBAT_UNITS_FOR_COMMANDER_RELATIVE
MIN_COMBAT_UNITS_FOR_MULTIPLE_COMMANDERS_ABSOLUTE
MIN_COMBAT_UNITS_FOR_MULTIPLE_COMMANDERS_RELATIVE
RETIRE_COMMANDER_INTERACTION_KEY
COMMANDER_DESIRED_RANK_DISPARITY_IN_ARMY
COMMANDER_DESIRED_RANK_DISPARITY_IN_FLEET
RECRUITABLE_COMMANDER_BASE_SCORE
RECRUITABLE_COMMANDER_RANDOM_FACTOR
RECRUITABLE_COMMANDER_SKILL_TRAIT_SCORE
RECRUITABLE_COMMANDER_PERSONALITY_TRAIT_SCORE
RECRUITABLE_COMMANDER_CONDITION_TRAIT_SCORE
RECRUITABLE_COMMANDER_FAVORED_IG_FACTOR
RECRUITABLE_COMMANDER_DISFAVORED_IG_FACTOR
MOBILIZATION_OPTION_RANDOM_FACTOR
MOBILIZATION_OPTION_MONEY_COST_FACTOR
MOBILIZATION_OPTION_NUM_ACTIVE_OPTIONS_DIVISOR
MOBILIZATION_OPTION_GOODS_SHORTAGE_MULT
MOBILIZATION_BASE_DESIRED_RATIO_TO_ENEMY
MOBILIZATION_MAIN_ATTACKER_ADDED_RATIO
MOBILIZATION_MAIN_DEFENDER_ADDED_RATIO
MOBILIZATION_LOYAL_SUBJECT_OF_MAIN_PARTICIPANT_ADDED_RATIO
MOBILIZATION_PEACE_NEGOTIATOR_ADDED_RATIO
MOBILIZATION_LOCAL_FRONTS_ADDED_RATIO
MOBILIZATION_UNINCORPORATED_OCCUPATION_ADDED_RATIO
MOBILIZATION_INCORPORATED_OCCUPATION_ADDED_RATIO
MOBILIZATION_EXISTENTIAL_WAR_FACTOR
MOBILIZATION_MINOR_ALLY_MAX_RELATIVE_POWER
MOBILIZATION_MINOR_ALLY_ADVANTAGE_TO_NOT_MOBILIZE
MOBILIZATION_MIN_ESCALATION_START
MOBILIZATION_MIN_ESCALATION_BOLDNESS_FACTOR
MOBILIZATION_MIN_MOBILIZATION_PEACE_NEGOTIATOR
MOBILIZATION_MIN_MOBILIZATION_LOYAL_SUBJECT_OF_MAIN_PARTICIPANT
MOBILIZATION_MIN_MOBILIZATION_TERRITORIAL_RISK
MOBILIZATION_MIN_MOBILIZATION_UNINCORPORATED_OCCUPATION
MOBILIZATION_MIN_MOBILIZATION_INCORPORATED_OCCUPATION
MOBILIZATION_MIN_MOBILIZATION_LOCAL_FRONTS
MOBILIZATION_MIN_MOBILIZATION_CONTAINMENT_WAR
CONSCRIPTION_INSUFFICIENT_FORCES_FACTOR
CONSCRIPTION_RELATIVE_CONSCRIPTED_COMBAT_POWER_DIVISOR
CONSCRIPTION_SMALL_STANDING_ARMY_THRESHOLD
CONSCRIPTION_SMALL_STANDING_ARMY_MIN_CONSCRIPTS_FACTOR
MIN_GOVERNMENT_LEGITIMACY
DESIRED_GOVERNMENT_LEGITIMACY
REFORM_GOVERNMENT_MONTHS_BETWEEN_CHANGES
REFORM_GOVERNMENT_NUM_OPTIONS_TO_CHECK
REFORM_GOVERNMENT_STICKINESS
REFORM_GOVERNMENT_PRO_IG_CLOUT_FACTOR
REFORM_GOVERNMENT_ANTI_IG_CLOUT_FACTOR
REFORM_GOVERNMENT_ABOVE_DESIRED_LEGITIMACY_FACTOR
REFORM_GOVERNMENT_BELOW_MIN_LEGITIMACY_FACTOR
MAX_CANDIDATES_TO_COMBINE_FOR_GOVERNMENT_ALTERNATIVES
REGIME_CHANGE_NUM_GOVERNMENT_OPTIONS_TO_CHECK
REGIME_CHANGE_MIN_GOVERNMENT_LEGITIMACY
REGIME_CHANGE_REFORM_GOVERNMENT_STICKINESS
REGIME_CHANGE_REFORM_GOVERNMENT_CLOUT_FACTOR_MULTIPLIER
IDEOLOGICAL_OPINION_ACCEPTABLE_PROGRESSIVENESS_DIFFERENCE
IDEOLOGICAL_OPINION_CURRENT_PROGRESSIVENESS_SAME_FACTOR
IDEOLOGICAL_OPINION_CURRENT_PROGRESSIVENESS_DIFF_FACTOR
IDEOLOGICAL_OPINION_IDEAL_PROGRESSIVENESS_SAME_FACTOR
IDEOLOGICAL_OPINION_IDEAL_PROGRESSIVENESS_DIFF_FACTOR
UNIFICATION_MIN_SUPPORT_SCORE
UNIFICATION_BASE_VALUE
UNIFICATION_SUPPORT_INVALID_TARGET_FACTOR
UNIFICATION_SUPPORTER_DEFAULT_RANK_VALUE
UNIFICATION_SUPPORTER_RANK_FACTOR
UNIFICATION_CANDIDATE_DEFAULT_RANK_VALUE
UNIFICATION_CANDIDATE_RANK_FACTOR
UNIFICATION_RELATIONS_HOSTILE_FACTOR
UNIFICATION_RELATIONS_COLD_FACTOR
UNIFICATION_RELATIONS_POOR_FACTOR
UNIFICATION_RELATIONS_CORDIAL_FACTOR
UNIFICATION_RELATIONS_AMICABLE_FACTOR
UNIFICATION_RELATIONS_FRIENDLY_FACTOR
UNIFICATION_ATTITUDE_DISINTERESTED_FACTOR
UNIFICATION_ATTITUDE_CAUTIOUS_FACTOR
UNIFICATION_ATTITUDE_CONCILIATORY_FACTOR
UNIFICATION_ATTITUDE_COOPERATIVE_FACTOR
UNIFICATION_ATTITUDE_GENIAL_FACTOR
UNIFICATION_ATTITUDE_WARY_FACTOR
UNIFICATION_ATTITUDE_BELLIGERENT_FACTOR
UNIFICATION_ATTITUDE_ANTAGONISTIC_FACTOR
UNIFICATION_ATTITUDE_LOYAL_FACTOR
UNIFICATION_ATTITUDE_ALOOF_FACTOR
UNIFICATION_ATTITUDE_DEFIANT_FACTOR
UNIFICATION_ATTITUDE_REBELLIOUS_FACTOR
UNIFICATION_ATTITUDE_PROTECTIVE_FACTOR
UNIFICATION_ATTITUDE_DOMINEERING_FACTOR
UNIFICATION_POWER_BLOC_FACTOR
STRATEGIC_REGION_STANCES_RANDOM_FACTOR
STRATEGIC_REGION_STANCES_STICKINESS
CHANGE_TAX_START_OF_GAME_DAYS_TO_WAIT
CHANGE_TAX_SIGNIFICANT_DEBT_THRESHOLD
RAISE_TAX_TO_DESIRED_INCOME_THRESHOLD
RAISE_TAX_ABOVE_DESIRED_INCOME_MAX_GOLD_RESERVES_THRESHOLD
RAISE_TAX_ABOVE_DESIRED_INCOME_NO_DEBT_THRESHOLD
RAISE_TAX_ABOVE_DESIRED_INCOME_WITH_DEBT_THRESHOLD
LOWER_TAX_TO_DESIRED_INCOME_NO_DEBT_THRESHOLD
LOWER_TAX_TO_DESIRED_INCOME_WITH_DEBT_THRESHOLD
LOWER_TAX_BELOW_DESIRED_INCOME_THRESHOLD
RAISE_TAX_HIGH_DEBT_OVERRIDE_RATIO
CONSTRUCTION_MAX_NUM_PRODUCTION_BUILDING_CONSTRUCTIONS_BASE
CONSTRUCTION_MAX_NUM_PRODUCTION_BUILDING_CONSTRUCTIONS_SCALED
CONSTRUCTION_MAX_NUM_PRODUCTION_BUILDING_CONSTRUCTIONS_SCALED_MAX
CONSTRUCTION_MAX_NUM_GOVERNMENT_BUILDING_CONSTRUCTIONS_BASE
CONSTRUCTION_MAX_NUM_GOVERNMENT_BUILDING_CONSTRUCTIONS_SCALED
CONSTRUCTION_MAX_NUM_GOVERNMENT_BUILDING_CONSTRUCTIONS_SCALED_MAX
CONSTRUCTION_RESERVES_NEW_CONSTRUCTIONS
CONSTRUCTION_DEBT_RESUME
CONSTRUCTION_DEBT_PAUSE
CONSTRUCTION_DEBT_RESUME_CRITICAL_CONSTRUCTION
CONSTRUCTION_DEBT_PAUSE_CRITICAL_CONSTRUCTION
CONTAINMENT_PLAY_PARTICIPATION_RANK
START_DIPLO_PLAY_RANDOM_FACTOR
START_DIPLO_PLAY_DAYS_TO_WAIT
START_DIPLO_PLAY_ALLY_STRENGTH_WEIGHT
START_DIPLO_PLAY_LIKELY_ALLY_STRENGTH_WEIGHT
DIPLO_PLAY_BACK_DOWN_CHANCE_THRESHOLD
DIPLO_PLAY_BACK_DOWN_CHANCE_ESCALATION
DIPLO_PLAY_BACK_DOWN_INCREASE_CHANCE_THRESHOLD
DIPLO_PLAY_BACK_DOWN_INCREASE_CHANCE_MULTIPLIER
DIPLO_PLAY_BACK_DOWN_GUARANTEED_THRESHOLD
DIPLO_PLAY_BACK_DOWN_GUARANTEED_ESCALATION
DIPLO_PLAY_BACK_DOWN_CHANCE_LOW_ESCALATION
DIPLO_PLAY_BACK_DOWN_CHANCE_HIGH_ESCALATION
DIPLO_PLAY_BACK_DOWN_CHANCE_WAR_LOSSES_MULT
DIPLO_PLAY_BACK_DOWN_CHANCE_WAR_LOSSES_MAX
DIPLO_PLAY_FREELY_ADD_WARGOALS_ESCALATION_THRESHOLD
DIPLO_PLAY_ADD_WARGOALS_THRESHOLD
DIPLO_PLAY_FORCE_DIPLOMATIC_PLAY_THRESHOLD
DIPLO_PLAY_SWAY_THRESHOLD
DIPLO_PLAY_REVERSE_SWAY_THRESHOLD
DIPLO_PLAY_SWAY_LEANING_SIDE_MILITARY_STRENGTH_MULT
DIPLO_PLAY_DECIDE_ON_SUPPORT_ESCALATION
DIPLO_PLAY_TAKE_SIDES_MIN_BOLDNESS
DIPLO_PLAY_TAKE_SIDES_CHANCE
DIPLO_PLAY_DECLARE_NEUTRALITY_ESCALATION_MIN_BASE
DIPLO_PLAY_DECLARE_NEUTRALITY_IMPACT_OF_NEUTRALITY_SCORE
DIPLO_PLAY_DECLARE_NEUTRALITY_IMPACT_OF_NEUTRALITY_SCORE_MAX
DIPLO_PLAY_DECLARE_NEUTRALITY_ESCALATION_MAX
DIPLO_PLAY_ABANDON_SUPPORT_CHANCE
DIPLO_PLAY_SWAY_COUNTRIES_ESCALATION
DIPLO_PLAY_REVERSE_SWAY_COUNTRIES_CHANCE_SCALED
DIPLO_PLAY_REVERSE_SWAY_COUNTRIES_CHANCE_MAX
DIPLO_PLAY_REVERSE_SWAY_LEANING_MULT
DIPLO_PLAY_SWAY_COUNTRIES_CHANCE_SCALED
DIPLO_PLAY_SWAY_COUNTRIES_CHANCE_MAX
DIPLO_PLAY_TIMED_WEIGHT_DURATION
DIPLO_PLAY_PREFERENCE_THRESHOLD
DIPLO_PLAY_WEAK_ABANDON_SUPPORT_THRESHOLD
DIPLO_PLAY_STRONG_ABANDON_SUPPORT_THRESHOLD
DIPLO_PLAY_ABANDON_ALLY_OR_SUBJECT_MIN_ENEMY_STRENGTH
DIPLO_PLAY_ABANDON_ALLY_RELUCTANCE
DIPLO_PLAY_ABANDON_SUBJECT_RELUCTANCE
DIPLO_PLAY_SWAY_DAYS_LEFT_MAX
DIPLO_PLAY_SWAY_DAYS_LEFT_MIN
DIPLO_PLAY_SWAY_ANSWER_CHANCE
DIPLO_PLAY_WEAK_ARMY_THRESHOLD
DIPLO_PLAY_STRONG_ARMY_THRESHOLD
DIPLO_PLAY_STRONG_ARMY_MAX
DIPLO_PLAY_FORCE_BALANCE_SCALE
DIPLO_PLAY_FORCE_BALANCE_NAVY_FACTOR
DIPLO_PLAY_FORCE_BALANCE_MOBILIZATION_FACTOR
DIPLO_PLAY_STATE_STABILITY_UNINCORPORATED_WEIGHT_MULT
DIPLO_PLAY_CONTAINMENT_PLAY_FACTOR
DIPLO_PLAY_SWAY_LOW_IMPACT_FACTOR
DIPLO_PLAY_SWAY_LOW_IMPACT_THRESHOLD
DIPLO_PLAY_SWAY_NON_PRIMARY_DEMAND_IMPACT_MULT
DIPLO_PLAY_SWAY_SUBJECT_IMPACT_VALUE_DIVISOR
DIPLO_PLAY_SWAY_INCOME_TRANSFER_PACTS_OF_SAME_TYPE_FACTOR
DIPLO_PLAY_SWAY_TOO_LOW_SUPPORT_DESIRE_THRESHOLD
DIPLO_PLAY_UNWANTED_SWAY_OFFER_MEMORY_DURATION_DAYS
DIPLO_PLAY_CALL_ALLY_PREFERENCE_SCORE
DIPLO_PLAY_WAR_GOAL_IMPACT_MANEUEVERS_MULT
DIPLO_PLAY_WAR_GOAL_IMPACT_INFAMY_MULT
DIPLO_PLAY_WAR_GOAL_IMPACT_CONQUEST_MULT
DIPLO_PLAY_BOLDNESS_FROM_RANK
DIPLO_PLAY_BOLDNESS_WEAK_ARMY_FACTOR
DIPLO_PLAY_BOLDNESS_CONTAINMENT_PLAY
DIPLO_PLAY_BOLDNESS_PRIMARY_DEMANDS
DIPLO_PLAY_CONFIDENCE_FORCE_BALANCE_FACTOR
DIPLO_PLAY_CONFIDENCE_STRONG_ARMY_FACTOR
DIPLO_PLAY_CONFIDENCE_CIVIL_WAR_OR_UPRISING
DIPLO_PLAY_CONFIDENCE_EXISTENTIAL_PLAY
DIPLO_PLAY_CONFIDENCE_FROM_TURMOIL
DIPLO_PLAY_CONFIDENCE_FROM_LOYALISTS
DIPLO_PLAY_CONFIDENCE_FROM_DEVASTATION
DIPLO_PLAY_CONFIDENCE_FROM_DEBT_LEVEL
DIPLO_PLAY_CONFIDENCE_FROM_BANKRUPTCY
DIPLO_PLAY_CONFIDENCE_FROM_GOLD_RESERVES
DIPLO_PLAY_CONFIDENCE_FROM_OWN_CONFLICTS
DIPLO_PLAY_CONFIDENCE_FROM_ENEMY_TURMOIL
DIPLO_PLAY_CONFIDENCE_FROM_ENEMY_DEVASTATION
DIPLO_PLAY_CONFIDENCE_FROM_ENEMY_DEBT_LEVEL
DIPLO_PLAY_CONFIDENCE_FROM_ENEMY_BANKRUPTCY
DIPLO_PLAY_CONFIDENCE_FROM_ENEMY_CONFLICTS
DIPLO_PLAY_CONFIDENCE_VERY_LOW_THRESHOLD
DIPLO_PLAY_CONFIDENCE_LOW_THRESHOLD
DIPLO_PLAY_CONFIDENCE_HIGH_THRESHOLD
DIPLO_PLAY_CONFIDENCE_VERY_HIGH_THRESHOLD
DIPLO_PLAY_NEUTRALITY_MIN
DIPLO_PLAY_NEUTRALITY_PREFERENCE_DELTA_THRESHOLD
DIPLO_PLAY_NEUTRALITY_FROM_DEBT_LEVEL
DIPLO_PLAY_NEUTRALITY_FROM_BANKRUPTCY
DIPLO_PLAY_NEUTRALITY_FROM_DEVASTATION_LEVEL
DIPLO_PLAY_NEUTRALITY_FROM_TURMOIL
DIPLO_PLAY_NEUTRALITY_IN_SUBJECT_CONFLICT
DIPLO_PLAY_NEUTRALITY_IN_NATIVE_UPRISING
DIPLO_PLAY_NEUTRALITY_FROM_ONGOING_CONFLICTS
DIPLO_PLAY_NEUTRALITY_FROM_LOWER_RANK
DIPLO_PLAY_NEUTRALITY_FROM_NO_ARMY
DIPLO_PLAY_NEUTRALITY_WEAK_ARMY_FACTOR
DIPLO_PLAY_NEUTRALITY_TRUCE_FACTOR
DIPLO_PLAY_SYMPATHY_RANGE_MIN
DIPLO_PLAY_SYMPATHY_RANGE_MAX
DIPLO_PLAY_SYMPATHY_BASE_INITIATOR
DIPLO_PLAY_SYMPATHY_BASE_TARGET
DIPLO_PLAY_SYMPATHY_ENEMY_OF_SUBJECT_INITIATOR
DIPLO_PLAY_SYMPATHY_ENEMY_OF_SUBJECT_TARGET
DIPLO_PLAY_SYMPATHY_ENEMY_OF_ALLY_INITIATOR
DIPLO_PLAY_SYMPATHY_ENEMY_OF_ALLY_TARGET
DIPLO_PLAY_SYMPATHY_ENEMY_OF_INFAMOUS_COUNTRY
DIPLO_PLAY_SYMPATHY_ENEMY_OF_NOTORIOUS_COUNTRY
DIPLO_PLAY_SYMPATHY_ENEMY_OF_PARIAH_COUNTRY
DIPLO_PLAY_SYMPATHY_LENIENT_AI_GAME_RULE
DIPLO_PLAY_SYMPATHY_HARSH_AI_GAME_RULE
DIPLO_PLAY_SYMPATHY_FROM_INITIAL_WARGOAL
DIPLO_PLAY_SYMPATHY_INCREASE_NEW_WARGOAL
DIPLO_PLAY_SYMPATHY_INCREASE_SWAYED_WITH_WARGOAL
DIPLO_PLAY_SYMPATHY_INCREASE_ADDED_PRIMARY_WARGOAL
DIPLO_PLAY_SWITCH_SIDES_FACTOR
DIPLO_PLAY_IDEOLOGICAL_OPINION_POSITIVE_FACTOR
DIPLO_PLAY_IDEOLOGICAL_OPINION_NEGATIVE_FACTOR
DIPLO_PLAY_IDEOLOGICAL_OPINION_REVOLUTION_MULT
DIPLO_PLAY_SECESSION_OWN_SECESSION_RISK_FACTOR
DIPLO_PLAY_NON_ALLY_UNRECOGNIZED_BASE_FACTOR
DIPLO_PLAY_NON_ALLY_UNRECOGNIZED_INCONSEQUENTAL_ENEMY_DEMANDS_FACTOR
DIPLO_PLAY_NON_ALLY_UNRECOGNIZED_CONSEQUENTAL_DEMANDS_FACTOR
DIPLO_PLAY_ALLY_INITIATOR_FACTOR
DIPLO_PLAY_ALLY_TARGET_FACTOR
DIPLO_PLAY_GUARANTEE_TARGET_FACTOR
DIPLO_PLAY_OVERLORD_INITIATOR_FACTOR
DIPLO_PLAY_OVERLORD_TARGET_FACTOR
DIPLO_PLAY_SAME_POWER_BLOC_INITIATOR_FACTOR
DIPLO_PLAY_SAME_POWER_BLOC_TARGET_FACTOR
DIPLO_PLAY_RELATIONS_HOSTILE_FACTOR
DIPLO_PLAY_RELATIONS_COLD_FACTOR
DIPLO_PLAY_RELATIONS_POOR_FACTOR
DIPLO_PLAY_RELATIONS_CORDIAL_FACTOR
DIPLO_PLAY_RELATIONS_AMICABLE_FACTOR
DIPLO_PLAY_RELATIONS_FRIENDLY_FACTOR
DIPLO_PLAY_ATTITUDE_DISINTERESTED_FACTOR
DIPLO_PLAY_ATTITUDE_DISINTERESTED_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_CAUTIOUS_FACTOR
DIPLO_PLAY_ATTITUDE_CAUTIOUS_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_CONCILIATORY_FACTOR
DIPLO_PLAY_ATTITUDE_CONCILIATORY_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_COOPERATIVE_FACTOR
DIPLO_PLAY_ATTITUDE_COOPERATIVE_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_GENIAL_FACTOR
DIPLO_PLAY_ATTITUDE_GENIAL_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_WARY_FACTOR
DIPLO_PLAY_ATTITUDE_WARY_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_BELLIGERENT_FACTOR
DIPLO_PLAY_ATTITUDE_BELLIGERENT_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_ANTAGONISTIC_FACTOR
DIPLO_PLAY_ATTITUDE_ANTAGONISTIC_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_LOYAL_FACTOR
DIPLO_PLAY_ATTITUDE_LOYAL_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_ALOOF_FACTOR
DIPLO_PLAY_ATTITUDE_ALOOF_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_DEFIANT_FACTOR
DIPLO_PLAY_ATTITUDE_DEFIANT_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_REBELLIOUS_FACTOR
DIPLO_PLAY_ATTITUDE_REBELLIOUS_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_PROTECTIVE_FACTOR
DIPLO_PLAY_ATTITUDE_PROTECTIVE_BACKER_FACTOR
DIPLO_PLAY_ATTITUDE_DOMINEERING_FACTOR
DIPLO_PLAY_ATTITUDE_DOMINEERING_BACKER_FACTOR
DIPLO_PLAY_SWAY_RANDOM_FACTOR
DIPLO_PLAY_SWAY_UNWANTED_OFFER
DIPLO_PLAY_SWAY_CALL_IN_OBLIGATION
DIPLO_PLAY_SWAY_MINIMUM_OBLIGATION_VALUE
DIPLO_PLAY_SWAY_CALL_ALLY_FACTOR
DIPLO_PLAY_SWAY_MINIMUM_PREFERENCE_FOR_SUBJUGATION
DIPLO_PLAY_SWAY_WARGOAL_WEAK_SWAYER_CONFIDENT_IN_OWN_ARMY_FACTOR
DIPLO_PLAY_SWAY_WARGOAL_FACTOR
DIPLO_PLAY_SWAY_WARGOAL_THRESHOLD
DIPLO_PLAY_SWAY_WARGOAL_MINIMUM_SWAYER_MULTIPLIER_INITIATOR
DIPLO_PLAY_SWAY_WARGOAL_MINIMUM_SWAYER_MULTIPLIER_TARGET
DIPLO_PLAY_SWAY_LEANING_PLAYER_FACTOR
DIPLO_PLAY_SWAY_BECOME_SUBJECT_VALUE_FACTOR
DIPLO_PLAY_SWAY_TRANSFER_SUBJECT_VALUE_FACTOR
DIPLO_PLAY_SWAY_STATE_DESIRE_FACTOR
DIPLO_PLAY_SWAY_DIPLOMATIC_PACT_DESIRE_FACTOR
DIPLO_PLAY_REVERSE_SWAY_ADDED_MILITARY_POWER_FACTOR
DIPLO_PLAY_REVERSE_SWAY_MIN_ADDED_MILITARY_POWER
DIPLO_PLAY_REVERSE_SWAY_ADDED_MILITARY_POWER_OUTMATCHED_MULT
DIPLO_PLAY_REVERSE_SWAY_OUTMATCHING_FACTOR
DIPLO_PLAY_REVERSE_SWAY_BASE_FACTORS_MULT
DIPLO_PLAY_REVERSE_SWAY_WARGOAL_VALUE_FACTOR
DIPLO_PLAY_REVERSE_SWAY_WARGOAL_IMPACT_FACTOR
DIPLO_PLAY_REVERSE_SWAY_WARGOAL_INFAMY_FACTOR
DIPLO_PLAY_REVERSE_SWAY_OFFER_OBLIGATION_MIN_VALUE
DIPLO_PLAY_REVERSE_SWAY_OFFER_OBLIGATION_FACTOR
DIPLO_PLAY_REVERSE_SWAY_CALL_IN_OBLIGATION_FACTOR
DIPLO_PLAY_REVERSE_SWAY_STATE_VALUE_FACTOR
DIPLO_PLAY_REVERSE_SWAY_BECOME_SUBJECT_VALUE_FACTOR
DIPLO_PLAY_REVERSE_SWAY_TRANSFER_SUBJECT_VALUE_FACTOR
DIPLO_PLAY_REVERSE_SWAY_CALL_ALLY_DESIRE
DIPLO_PLAY_ADD_WARGOAL_MIN_SCORE
LOW_AGGRESSION_BASE_EFFECT_MULT
HIGH_AGGRESSION_BASE_EFFECT_MULT
LOW_AGGRESSION_INFAMY_ACCEPTANCE_MULT
HIGH_AGGRESSION_INFAMY_ACCEPTANCE_MULT
AI_AGGRESSION_MAX_ACCEPTABLE_INFAMY
WAR_GOAL_RANDOM_FACTOR
WAR_GOAL_UNDESIRABLE_INFAMY_FACTOR
WAR_GOAL_UNACCEPTABLE_INFAMY_FACTOR
WAR_GOAL_NOT_PRIMARY_DEMAND_FACTOR
STRAIT_ACCESS_STATUS_STICKYNESS
STRAIT_ACCESS_PERMISSIONS_STICKYNESS
STRAIT_TOLL_RATES_STICKYNESS
WAR_GOAL_MAKE_PRIMARY_DEMAND_SCORE_MULT
WAR_GOAL_MAKE_PRIMARY_DEMAND_RETURN_STATE_SCORE_MULT
WAR_GOAL_MIN_SCORE_TO_MAKE_PRIMARY_DEMAND
TECH_RANDOM_FACTOR
TECH_COST_PENALTY_FACTOR
INCORPORATE_STATE_MAX_YEARS
INCORPORATE_STATE_MIN_POPULATION
DEFEND_STATE_BARRACKS_WEIGHT
DEFEND_STATE_BARRACKS_MAX_WEIGHT
DEFEND_STATE_NAVAL_ADMINISTRATION_WEIGHT
DEFEND_STATE_NAVAL_ADMINISTRATION_MAX_WEIGHT
DEFEND_STATE_CAPITAL_WEIGHT
DEFEND_STATE_CAPITAL_WAR_NEGOTIATOR_WEIGHT
DEFEND_STATE_OWN_CAPITAL_WEIGHT_MULT
DEFEND_STATE_WARGOAL_WEIGHT
DEFEND_STATE_INCORPORATED_WEIGHT_MULT
INVADE_STATE_BARRACKS_WEIGHT
INVADE_STATE_BARRACKS_MAX_WEIGHT
INVADE_STATE_NAVAL_ADMINISTRATION_WEIGHT
INVADE_STATE_NAVAL_ADMINISTRATION_MAX_WEIGHT
INVADE_STATE_CAPITAL_WEIGHT
INVADE_STATE_CAPITAL_WAR_NEGOTIATOR_WEIGHT
INVADE_STATE_OWN_CAPITAL_WEIGHT_MULT
INVADE_STATE_WARGOAL_WEIGHT
INVADE_STATE_INCORPORATED_WEIGHT_MULT
LAND_INVASION_RANDOM_FACTOR
LAND_INVASION_MIN_RELATIVE_LOCAL_ARMY_STRENGTH
LAND_INVASION_MIN_SCORE
LAND_INVASION_MAX_LOCAL_FRONT_SCORE
LAND_INVASION_MAX_TRAVEL_TIME_DAYS
LAND_INVASION_TRAVEL_TIME_PENALTY
LAND_INVASION_MAX_AVAILABLE_ARMY_FRACTION
LAND_INVASION_CANCEL_SCORE_THRESHOLD
NAVAL_INVASION_RANDOM_FACTOR
NAVAL_INVASION_MIN_RELATIVE_LOCAL_ARMY_STRENGTH
NAVAL_INVASION_MIN_RELATIVE_LOCAL_NAVY_STRENGTH
NAVAL_INVASION_MIN_RELATIVE_GLOBAL_NAVY_STRENGTH_ATTACKER
NAVAL_INVASION_MIN_RELATIVE_GLOBAL_NAVY_STRENGTH_DEFENDER
NAVAL_INVASION_COOLDOWN_DAYS
NAVAL_INVASION_MIN_SCORE
NAVAL_INVASION_INVADE_STATE_WARGOAL_WEIGHT
NAVAL_INVASION_MAX_TARGET_CANDIDATES
NAVAL_INVASION_HIGH_VALUE_STATE_THRESHOLD
NAVAL_INVASION_MAX_LOCAL_FRONT_SCORE
NAVAL_INVASION_ARMY_EXPECTED_DISTANCE
NAVAL_INVASION_CANCEL_SCORE_THRESHOLD
NAVAL_INVASION_MAX_AVAILABLE_ARMY_FRACTION
NAVAL_INVASION_MAX_AVAILABLE_FLEET_FRACTION
SUPPLY_SHIP_STRAIN_START_RATIO
SUPPLY_SHIP_STRAIN_MAX_RATIO
SUPPLY_SHIP_STRAIN_MULT_AT_START
SUPPLY_SHIP_STRAIN_MULT_AT_FULL
SUPPLY_SHIP_STRAIN_MULT_AT_MAX
MARINE_FORMATION_TAG_MIN_FRACTION
SHIP_TEMPLATE_CREATION_MIN_SCORE_FACTOR
SHIP_RETROFIT_MIN_SCORE_FACTOR
FLEET_RECALL_HULL_RATIO_WAR
FLEET_RECALL_HULL_RATIO_PEACE
FLEET_RECALL_CREW_RATIO_WAR
FLEET_RECALL_CREW_RATIO_PEACE
FLEET_RECALL_MIN_MISSION_SCORE
SHIP_DESIGN_MODIFICATION_RANDOM_FACTOR
SHIP_DESIGN_UTILITY_MOD_MIN_SCORE
SHIP_DESIGN_UTILITY_MOD_MIN_SCORE_DIVISOR_PER_FREE_SLOT
SHIP_CONSTRUCTION_WANTED_SHIPS_TO_BUILD_COST_FACTOR
SHIP_CONSTRUCTION_WANTED_BUILT_SHIPS_COST_FACTOR
SHIP_CONSTRUCTION_DEBT_RESUME
SHIP_CONSTRUCTION_DEBT_PAUSE
MIN_SHIPS_TO_TRANSFER
SHIP_TRANSFER_BASE_VALUE_PER_CONSTRUCTION_POINT
SELL_OBSOLETE_SHIP_ASK_FACTOR
SELL_OBSOLETE_SHIPS_BATCH_RATIO
SELL_OBSOLETE_SHIPS_BATCH_MAX
SELL_OBSOLETE_SHIPS_DECLINED_MEMORY_DAYS
OBSOLETE_SHIP_DISBAND_GRACE_DAYS
DISBAND_OBSOLETE_SHIP_CREW_RATIO
DISBAND_OBSOLETE_SHIPS_MAX_COUNT
DISBAND_OBSOLETE_SHIPS_MAX_RATIO
DISBAND_VERY_OBSOLETE_SHIP_MIN_RATIO
SHIP_CONSTRUCTION_BLOCK_CREW_RATIO
SUPPLY_SHIP_ALLOCATION_HIGH_RATIO
SUPPLY_SHIP_ALLOCATION_LOW_RATIO
SUPPLY_SHIP_ALLOCATION_VERY_LOW_RATIO
DISBAND_EXCESS_SUPPLY_SHIPS_MIN_RATIO
DISBAND_EXCESS_SUPPLY_SHIPS_MAX_COUNT
HQ_DEFENSE_MIN_THEATER_SCORE
NUM_DAYS_TO_REMEMBER_FAILED_FRONT_OR_HQ_ASSIGNMENT
NUM_DAYS_TO_REMEMBER_FAILED_SUPPLY_ROUTE
NUM_DAYS_TO_REMEMBER_FAILED_NAVAL_INVASION
FRONT_OR_HQ_IMPORTANCE_MIN_SCORE
FRONT_IMPORTANCE_OWN_FRONT_WEIGHT_MULT
HQ_STATIONING_IMPORTANCE_NOT_OWN_HQ_WEIGHT_MULT
HQ_OR_FRONT_UNDEFENDED_ASSIGNMENT_WEIGHT
HQ_OR_FRONT_SPLIT_FORCE_BASE_FRACTION
HQ_OR_FRONT_SPLIT_FORCE_MIN_FRACTION
HQ_OR_FRONT_SPLIT_FORCE_DEFENDED_LOCATION_MIN_FRACTION_TO_SEND
TRANSPORT_SPLIT_MIN_FLEET_CAPACITY_FRACTION
TRANSPORT_MARINE_FLEET_SCORE_MULT
UNITS_PERCENTAGE_TO_BE_CONSIDERED_IN_DISADVANTAGE
FRONT_OR_HQ_UNIT_DISPARITY_FOR_MOVE_TRAVEL_TIME_FACTOR
FRONT_OR_HQ_ACTIVE_WAR_MOVE_FACTOR
FRONT_CAPITAL_HQ_IMPORTANCE_MULT
FRONT_NON_WAR_ZONE_IMPORTANCE_MULT
FRONT_WAR_ZONE_IMPORTANCE_MULT
HQ_LANDLOCKED_IMPORTANCE_MULT
HQ_COASTAL_NON_WAR_ZONE_IMPORTANCE_MULT
HQ_COASTAL_WAR_ZONE_IMPORTANCE_MULT
FRONT_MIN_OVERALL_STRENGTH_FACTOR_TO_ATTACK
FRONT_MIN_INDIVIDUAL_ARMY_STRENGTH_FACTOR_TO_ATTACK
FRONT_MIN_MORALE_TO_ATTACK
FRONT_MIN_ORGANIZATION_TO_ATTACK
FRONT_NO_WARGOAL_MIN_STRENGTH_FACTOR_TO_ATTACK
BLOCKADE_STATE_TRADE_VOLUME_MILITARY_GOODS_WEIGHT
BLOCKADE_STATE_TRADE_VOLUME_OTHER_GOODS_WEIGHT
BLOCKADE_STATE_WEIGHT
BLOCKADE_ORDER_LEVEL_DELTA_WEIGHT
BLOCKADE_ORDER_NAVY_STRENGTH_RATIO_MULT
FLEET_MISSION_SCORE_CAP
NODE_STACKING_PENALTY_MULT
FLEET_TASK_ASSIGNMENT_RANDOM_SPICE
FLEET_SEA_PROVINCE_ASSIGNMENT_STICKINESS
FLEET_HQ_REASSIGNMENT_THRESHOLD
FLEET_HQ_REASSIGNMENT_THRESHOLD_AT_WAR
FLEET_SEA_PROVINCE_SETTLING_DAYS
FLEET_SEA_PROVINCE_SETTLING_STICKINESS_MULT
FLEET_SEA_PROVINCE_HOME_HQ_SCORE
FLEET_SEA_PROVINCE_DISTANCE_SCORE
FLEET_SEA_PROVINCE_DISTANCE_SCORE_MAX_DISTANCE
FLEET_MISSION_AREA_SHIPS_PER_NODE
FLEET_RAID_CONVOYS_TASK_SCORE_FROM_STRENGTH
FLEET_ESCORT_CONVOYS_TASK_SCORE_FROM_DEFENSE
FLEET_PROJECT_INTEREST_TASK_SCORE_FROM_INTEREST_PROJECTION
FLEET_DEFEND_FROM_CONVOY_RAID_TASK_SCORE_FROM_PROTECTION
FLEET_DEFEND_FROM_NAVAL_INVASION_TASK_SCORE_FROM_PROJECTION
FLEET_DEFEND_FROM_NAVAL_INVASION_TASK_SCORE_FROM_SHIPS
FLEET_DEFEND_FROM_BLOCKADE_TASK_SCORE_FROM_STRENGTH
FLEET_BLOCKADE_TASK_SCORE_FROM_STRENGTH
FLEET_BLOCKADE_TASK_SCORE_NO_HOSTILES
FLEET_BLOCKADE_TASK_SCORE_STRENGTH_RATIO_FACTOR
FLEET_PORT_BOMBARDMENT_TASK_SCORE_NO_HOSTILES
FLEET_PORT_BOMBARDMENT_TASK_SCORE_STRENGTH_RATIO_FACTOR
FLEET_INTERCEPT_TASK_SCORE_STRENGTH_RATIO_FACTOR
FLEET_MISSION_MAX_SEA_REGIONS
RAID_CONVOYS_ORDER_SCORE
INTERCEPT_ORDER_SCORE
SEA_NODE_OFFENSIVE_FLEET_SHIPPING_LANES_WEIGHT
SEA_NODE_OFFENSIVE_FLEET_STATE_BLOCKADE_WEIGHT
RAID_CONVOYS_LANE_SIZE_FACTOR
ESCORT_CONVOYS_ABSOLUTE_LANE_SIZE_FACTOR
ESCORT_CONVOYS_LANE_SIZE_FACTOR_MAX
ESCORT_CONVOYS_PORT_CONNECTION_WAR_MULT
ESCORT_CONVOYS_PORT_CONNECTION_PEACE_MULT
NUM_GROWING_COLONIES_BASE
NUM_GROWING_COLONIES_SCALED
NUM_GROWING_COLONIES_MAX
COLONY_BASE_WEIGHT
COLONY_POPULATION_WEIGHT
COLONY_ARABLE_LAND_WEIGHT
COLONY_ADJACENT_WEIGHT_MULT
COLONY_UNCONTESTED_WEIGHT_MULT
COLONY_RANDOM_FACTOR
CONSCRIPTION_CENTER_MILITARY_SPENDING_TARGET_BASE
CONSCRIPTION_CENTER_MILITARY_SPENDING_TARGET_MAX
INSTITUTION_INVESTMENT_RANDOM_FACTOR
INSTITUTION_CURRENT_INVESTMENT_DIVISOR
MAX_INSTITUTION_SPENDING_BASE
MAX_INSTITUTION_SPENDING_PER_INSTITUTION
INSTITUTION_SPENDING_INCREASE_SPENDING_RATIO
INSTITUTION_SPENDING_DECREASE_SPENDING_RATIO
MONEY_SPENDING_RANDOM_FACTOR
MONEY_SPENDING_MAX_RATIO_TO_REMOVE_SHOULD_HAVE
MONEY_SPENDING_MAX_RATIO_TO_REMOVE_WANTS_TO_HAVE
MONEY_SPENDING_MAX_RATIO_TO_REMOVE_NICE_TO_HAVE
MONEY_SPENDING_MIN_RATIO_TO_ADD_SHOULD_HAVE
MONEY_SPENDING_MIN_RATIO_TO_ADD_WANTS_TO_HAVE
MONEY_SPENDING_MIN_RATIO_TO_ADD_NICE_TO_HAVE
MONEY_SPENDING_MIN_SURPLUS_TO_ADD_SHOULD_HAVE
MONEY_SPENDING_MIN_SURPLUS_TO_ADD_WANTS_TO_HAVE
MONEY_SPENDING_MIN_SURPLUS_TO_ADD_NICE_TO_HAVE
MONEY_SPENDING_MIN_SURPLUS_RELATIVE_INCOME_CONVERSION
MONEY_SPENDING_MIN_SURPLUS_TO_IGNORE_RATIO_FOR_SHOULD_HAVE
MONEY_SPENDING_MIN_SURPLUS_TO_IGNORE_RATIO_FOR_WANTS_TO_HAVE
MONEY_SPENDING_MIN_SURPLUS_TO_IGNORE_RATIO_FOR_NICE_TO_HAVE
MONEY_SPENDING_ACCEPTABLE_WAR_DEBT
MONEY_SPENDING_MIN_RATIO_TO_CONSIDER_GOLD_RESERVES
MONEY_SPENDING_MIN_WEEKS_OF_GOLD_RESERVES_TO_NOT_REMOVE_SHOULD_HAVE
MONEY_SPENDING_MIN_WEEKS_OF_GOLD_RESERVES_TO_NOT_REMOVE_WANTS_TO_HAVE
MONEY_SPENDING_MIN_GOLD_RESERVE_FRACTION_TO_ADD_SHOULD_HAVE
MONEY_SPENDING_MIN_GOLD_RESERVE_FRACTION_TO_ADD_WANTS_TO_HAVE
MONEY_SPENDING_MIN_GOLD_RESERVE_FRACTION_TO_ADD_NICE_TO_HAVE
MONEY_SPENDING_LAND_THREAT_THRESHOLD
MONEY_SPENDING_NAVY_THREAT_THRESHOLD
MONEY_SPENDING_PRESTIGE_RIVAL_THRESHOLD
MONEY_SPENDING_BELOW_CRITICAL_THRESHOLD_MULTIPLIER
MONEY_SPENDING_MILITARY_CRITICAL_THRESHOLD
MONEY_SPENDING_MILITARY_EXCESSIVE_THRESHOLD
MONEY_SPENDING_MILITARY_WRONG_UNIT_TYPE_MULTIPLIER
MONEY_SPENDING_FORTIFICATIONS_CRITICAL_THRESHOLD
MONEY_SPENDING_CONSTRUCTION_TOO_LARGE_INVESTMENT_POOL_FACTOR
MONEY_SPENDING_CONSTRUCTION_CRITICAL_THRESHOLD
MONEY_SPENDING_CONSTRUCTION_EXCESSIVE_THRESHOLD
MONEY_SPENDING_CONSTRUCTION_MAX_INVESTMENT_POOL_WEEKS
MONEY_SPENDING_SHIP_CONSTRUCTION_CRITICAL_THRESHOLD
MONEY_SPENDING_SHIP_CONSTRUCTION_EXCESSIVE_THRESHOLD
MONEY_SPENDING_INNOVATION_DESIRED_THRESHOLD
MONEY_SPENDING_INNOVATION_EXCESSIVE_THRESHOLD
MONEY_SPENDING_SUPPLY_NETWORK_CRITICAL_THRESHOLD
MONEY_SPENDING_SUPPLY_NETWORK_DESIRED_THRESHOLD
MONEY_SPENDING_BUREAUCRACY_CRITICAL_THRESHOLD
MONEY_SPENDING_BUREAUCRACY_DESIRED_THRESHOLD
MONEY_SPENDING_BUREAUCRACY_EXCESSIVE_THRESHOLD
MONEY_SPENDING_INFRASTRUCTURE_CRITICAL_THRESHOLD
MONEY_SPENDING_INFRASTRUCTURE_DESIRED_THRESHOLD
MONEY_SPENDING_CANAL_MIN_CONSTRUCTION_FOR_SHOULD_HAVE
GOVERNMENT_BUILDING_BASE_VALUE
GOVERNMENT_BUILDING_FAVORED_GOODS_FACTOR
GOVERNMENT_BUILDING_DISFAVORED_GOODS_FACTOR
GOVERNMENT_BUILDING_NO_AVAILABLE_WORKFORCE_FACTOR
GOVERNMENT_BUILDING_STATE_CAPITAL_FACTOR
GOVERNMENT_BUILDING_STATE_MARKET_CAPITAL_FACTOR
GOVERNMENT_BUILDING_STATE_ARMY_NON_ACCEPTED_POP_FACTOR
GOVERNMENT_BUILDING_STATE_ARMY_ACCEPTED_POP_FACTOR
GOVERNMENT_BUILDING_STATE_NAVY_NON_ACCEPTED_POP_FACTOR
GOVERNMENT_BUILDING_STATE_NAVY_ACCEPTED_POP_FACTOR
GOVERNMENT_BUILDING_STATE_UNINCORPORATED_MULT
GOVERNMENT_BUILDING_STATE_MISSING_QUALIFICATIONS_MULT
GOVERNMENT_BUILDING_STATE_MISSING_INFRASTRUCTURE_DIV
GOVERNMENT_BUILDING_STATE_POP_CONSTRUCTION_SECTOR_IMPORTANCE_THRESHOLD
GOVERNMENT_BUILDING_STATE_POP_CONSTRUCTION_SECTOR_IMPORTANCE_MULT
SUBSIDIZE_BASE_VALUE
SUBSIDIZE_SHARE_OF_INFRA_FACTOR
SUBSIDIZE_SHARE_OF_SUPPLY_FACTOR
SUBSIDIZE_FAVORED_GOODS_MULT
SUBSIDIZE_DISFAVORED_GOODS_MULT
AUTHORITY_SPENDING_RANDOM_FACTOR
COMPANY_CHARTER_AUTHORITY_SPENDING_PERCENTAGE
PROMOTION_BASE_VALUE
SUPPRESSION_BASE_VALUE
CONSUMPTION_TAX_INCOME_VALUE
CONSUMPTION_TAX_STAPLE_MULT
CONSUMPTION_TAX_LUXURY_MULT
CONSUMPTION_TAX_LOW_INCOME_THRESHOLD
CONSUMPTION_TAX_HIGH_INCOME_THRESHOLD
CONSUMPTION_TAX_MAX_NUM_TAXED_GOODS_BASE
CONSUMPTION_TAX_MAX_NUM_TAXED_GOODS_PER_MISSING_TAX_TYPE
TRADE_CENTER_MINIMUM_GDP_MARKET_CAPITAL
TRADE_CENTER_MINIMUM_GDP_NON_MARKET_CAPITAL
TRADE_CENTER_MINIMUM_GDP_NON_COASTAL_MULT
TRADE_CENTER_MINIMUM_GDP_UNRECOGNIZED_MULT
TRADE_CENTER_MINIMUM_GDP_PASSED_YEARS_MULT
PRODUCTION_BUILDING_RANDOM_FACTOR
PRODUCTION_BUILDING_STATE_RANDOM_FACTOR
PRODUCTION_BUILDING_STATE_NO_AVAILABLE_WORKFORCE_FACTOR
PRODUCTION_BUILDING_BASE_VALUE
PRODUCTION_BUILDING_NO_AVAILABLE_WORKFORCE_FACTOR
PRODUCTION_BUILDING_GOODS_PROFIT_FACTOR
PRODUCTION_BUILDING_GOODS_DEFICIT_FACTOR
PRODUCTION_BUILDING_GOODS_DEFICIT_SUBSIDIZE_FACTOR
PRODUCTION_BUILDING_PRODUCED_VALUE_FACTOR
PRODUCTION_BUILDING_PRODUCED_TRADE_CAPACITY_FACTOR
PRODUCTION_BUILDING_PRODUCED_TRADE_CAPACITY_GDP_ADDED_FOR_DIVISOR
PRODUCTION_BUILDING_PRODUCED_TRADE_CAPACITY_EXPECTED_REVENUE_PER_UNIT
PRODUCTION_BUILDING_INCORPORATED_INFRASTRUCTURE_USAGE_FACTOR
PRODUCTION_BUILDING_UNINCORPORATED_INFRASTRUCTURE_USAGE_FACTOR
PRODUCTION_BUILDING_INPUT_NO_LOCAL_PRODUCTION_FACTOR
PRODUCTION_BUILDING_OUTPUT_NO_LOCAL_CONSUMPTION_FACTOR
PRODUCTION_BUILDING_OUTPUT_HIGH_PRICE_THRESHOLD
PRODUCTION_BUILDING_OUTPUT_HIGH_PRICE_FACTOR
PRODUCTION_BUILDING_OUTPUT_HIGH_PRICE_WANTS_HIGH_SUPPLY_FACTOR
PRODUCTION_BUILDING_OUTPUT_HIGH_PRICE_LOCAL_CONSUMPTION_MULTIPLIER
PRODUCTION_BUILDING_OUTPUT_LOW_PRICE_THRESHOLD
PRODUCTION_BUILDING_OUTPUT_LOW_PRICE_FACTOR
PRODUCTION_BUILDING_SUBSIDIZE_PRICE_FACTOR_MULT
PRODUCTION_BUILDING_OUTPUT_NEW_GOODS_FACTOR
PRODUCTION_BUILDING_OUTPUT_NEW_GOODS_STATE_INCORPORATED_POPULATION_THRESHOLD
PRODUCTION_BUILDING_OUTPUT_NEW_GOODS_STATE_UNINCORPORATED_POPULATION_THRESHOLD
PRODUCTION_BUILDING_OUTPUT_WANTED_INDUSTRIAL_GOODS_FACTOR
PRODUCTION_BUILDING_OUTPUT_WANTED_MILITARY_GOODS_FACTOR
PRODUCTION_BUILDING_OUTPUT_NEEDED_INDUSTRIAL_GOODS_FACTOR
PRODUCTION_BUILDING_OUTPUT_NEEDED_MILITARY_GOODS_FACTOR
PRODUCTION_BUILDING_FAVORED_GOODS_FACTOR
PRODUCTION_BUILDING_DISFAVORED_GOODS_FACTOR
PRODUCTION_BUILDING_MISSING_QUALIFICATIONS_MULT
PRODUCTION_BUILDING_DESIRED_INFRASTRUCTURE_SURPLUS
PRODUCTION_BUILDING_FREE_INFRASTRUCTURE_TARGET_WHEN_LACKING_WORKFORCE
PRODUCTION_BUILDING_EXCESSIVE_INFRASTRUCTURE_SURPLUS
PRODUCTION_BUILDING_REDUCE_SHORTAGE_MULT
PRODUCTION_BUILDING_INCREASE_SHORTAGE_MULT
PRODUCTION_BUILDING_OTHER_BUILDING_TYPES_UNDER_CONSTRUCTION_DIV
PRODUCTION_BUILDING_LONG_CONSTRUCTION_TIME_THRESHOLD
PRODUCTION_BUILDING_LONG_CONSTRUCTION_TIME_MULT
PRODUCTION_BUILDING_VERY_LONG_CONSTRUCTION_TIME_THRESHOLD
PRODUCTION_BUILDING_VERY_LONG_CONSTRUCTION_TIME_MULT
PRODUCTION_BUILDING_FOREIGN_INVESTMENT_HAS_RECENT_NATIONALIZATION_MULT
PRODUCTION_BUILDING_FOREIGN_INVESTMENT_COMPANY_MULT
GOVERNMENT_CONSTRUCTION_DOMESTIC_INVESTMENT_BIAS
GOVERNMENT_CONSTRUCTION_SUBJECT_INVESTMENT_BIAS
GOVERNMENT_COMPANY_TARGET_BUILDING_TYPE_CONSTRUCTION_FACTOR
GOVERNMENT_COMPANY_TARGET_STATE_NO_BUILDING_CONSTRUCTION_FACTOR
GOVERNMENT_COMPANY_TARGET_STATE_WITH_BUILDING_CONSTRUCTION_FACTOR
AUTONOMOUS_INVESTMENT_COMPANY_TARGET_BUILDING_TYPE_CONSTRUCTION_FACTOR
AUTONOMOUS_INVESTMENT_COMPANY_TARGET_STATE_NO_BUILDING_CONSTRUCTION_FACTOR
AUTONOMOUS_INVESTMENT_COMPANY_TARGET_STATE_WITH_BUILDING_CONSTRUCTION_FACTOR
AUTONOMOUS_INVESTMENT_SELF_INVESTMENT_CHANCE_FROM_COLLECTIVIZATION
PRODUCTION_BUILDING_TREATY_PORT_TRADE_CENTER_FACTOR
PRODUCTION_BUILDING_TREATY_PORT_NON_TRADE_CENTER_FACTOR
PRODUCTION_BUILDING_GOVERNMENT_CONSTRUCTION_MONOPOLY_MULT
PRODUCTION_BUILDING_LOW_EMPLOYMENT_THRESHOLD
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_COMPANY_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_COMPANY_MONOPOLY_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_COMPANY_CHARTERED_COUNTRY_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_WANTED_COST_COVERAGE
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_CONSTRUCTION_COST_DIVISOR_SCALING
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_RANDOM_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_STATE_RANDOM_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_PROFIT_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_PROFIT_PRIVATIZE_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_PRODUCED_VALUE_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_PRODUCED_VALUE_PRIVATIZE_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_PRODUCED_TRADE_CAPACITY_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_PRODUCED_MODIFIER_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_PRICE_COMPENSATION_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_BELOW_DESIRED_INFRASTRUCTURE_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_LOW_INVESTMENT_RESET_TIME
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_MILITARY_GOODS_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_INDUSTRIAL_GOODS_FACTOR_MULT
PRODUCTION_BUILDING_AUTONOMOUS_INVESTMENT_PROFIT_PRIVATIZE_SELF_OWNED_BUILDING_MULT
AUTONOMOUS_INVESTMENT_NUM_FAILED_INVESTMENTS_FOR_REFRESH_BASE
AUTONOMOUS_INVESTMENT_NUM_FAILED_INVESTMENTS_FOR_REFRESH_DYNAMIC
AUTONOMOUS_INVESTMENT_NUM_FAILED_INVESTMENTS_FOR_REFRESH_PLAYER
AUTONOMOUS_INVESTMENT_UPDATE_COUNT_DIVISOR
AUTONOMOUS_INVESTMENT_DOMESTIC_INVESTMENT_BIAS
AUTONOMOUS_INVESTMENT_DOMESTIC_INVESTMENT_BIAS_MAX
AUTONOMOUS_INVESTMENT_DOMESTIC_INVESTMENT_BIAS_RESET_TIME_IN_MONTHS
AUTONOMOUS_INVESTMENT_MIN_PROPORTIONAL_INVESTMENT_WEIGHT
AUTONOMOUS_INVESTMENT_MAX_PROPORTIONAL_INVESTMENT_WEIGHT
AUTONOMOUS_INVESTMENT_MIN_OWNERSHIP_BUILDING_INVESTMENT_SHARE
AUTONOMOUS_INVESTMENT_PREVIOUS_INVESTMENT_LOG_SIZE
AUTONOMOUS_INVESTMENT_PREVIOUS_INVESTMENT_DURATION_DAYS
BUILDING_PRIVATIZATION_CHANCE
OWNER_BUILDING_LOCATION_BASE_SCORE
OWNER_BUILDING_LOCATION_POPULATION_SCORE
OWNER_BUILDING_LOCATION_GDP_SCORE
OWNER_BUILDING_LOCATION_GDP_DIVISOR
OWNER_BUILDING_LOCATION_HAS_OWNER_BUILDING_MULT
OWNER_BUILDING_LOCATION_CAPITAL_MULT
OWNER_BUILDING_LOCATION_SAME_STATE_MULT
OWNER_BUILDING_LOCATION_NOT_HOMELANDS_MULT
OWNER_BUILDING_LOCATION_LOWER_GDP_MULT
OWNER_BUILDING_LOCATION_NO_AVAILABLE_WORKFORCE_MULT
OWNER_BUILDING_LOCATION_NO_AVAILABLE_INFRASTRUCTURE_MULT
OWNER_BUILDING_LOCATION_UNINCORPORATED_MULT
OWNER_COMPANY_EXPANSION_CHANCE_MULTIPLIER
OWNER_COMPANY_PRIVATIZATION_CHANCE_MULTIPLIER
OWNER_COMPANY_OWN_STATE_MULT
CHANGE_LAW_RANDOM_FACTOR
CHANGE_LAW_PRO_IG_IDEOLOGIES_FACTOR
CHANGE_LAW_ANTI_IG_IDEOLOGIES_FACTOR
CHANGE_LAW_POLITICAL_MOVEMENT_FACTOR
CHANGE_LAW_POTENTIAL_CIVIL_WAR_THRESHOLD
CHANGE_LAW_POTENTIAL_CIVIL_WAR_ENACT_CHANCE
CHANGE_LAW_POTENTIAL_CIVIL_WAR_MEMORY_DURATION
CHANGE_LAW_CIVIL_WAR_BOLDNESS_RANGE
CHANGE_LAW_CIVIL_WAR_BOLDNESS_TIMED_WEIGHT_DURATION
CHANGE_LAW_CIVIL_WAR_AVERSION_MOVEMENT_SUPPORT_FACTOR
CHANGE_LAW_CIVIL_WAR_AVERSION_SUBJECT_MULTIPLIER
CHANGE_LAW_CIVIL_WAR_AVERSION_LAW_DIRECTION_FLEXIBILITY
DID_NOT_NEGOTIATE_WITH_IG_COOLDOWN_MONTHS
PRODUCTION_METHOD_BASE_VALUE
PRODUCTION_METHOD_PROFIT_FACTOR
PRODUCTION_METHOD_DEFICIT_FACTOR
PRODUCTION_METHOD_PRODUCED_VALUE_FACTOR
PRODUCTION_METHOD_EMPLOYMENT_CHANGE_FACTOR
PRODUCTION_METHOD_REDUCE_OUTPUT_PENALTY_FACTOR
PRODUCTION_METHOD_REDUCE_OUTPUT_PENALTY_NO_WORLD_MARKET_ACCESS_FACTOR
PRODUCTION_METHOD_INCREASE_OUTPUT_PENALTY_FACTOR
PRODUCTION_METHOD_INCREASE_OUTPUT_PENALTY_NO_WORLD_MARKET_ACCESS_FACTOR
PRODUCTION_METHOD_FAVORED_GOODS_FACTOR
PRODUCTION_METHOD_FAVORED_MILITARY_GOODS_FACTOR
PRODUCTION_METHOD_DISFAVORED_GOODS_FACTOR
PRODUCTION_METHOD_UNDESIRABLE_GOODS_PRICE_THRESHOLD
PRODUCTION_METHOD_UNDESIRABLE_GOODS_PRICE_FACTOR_TRADEABLE
PRODUCTION_METHOD_UNDESIRABLE_GOODS_PRICE_FACTOR_UNTRADEABLE
PRODUCTION_METHOD_STICKINESS_UPGRADE
PRODUCTION_METHOD_STICKINESS_DOWNGRADE
PRODUCTION_METHOD_CHANCE_TO_CHANGE
PRODUCTION_METHOD_LOW_POP_THRESHOLD
PRODUCTION_METHOD_LOW_POP_FACTOR
NATIONALIZATION_DESIRE_NATIONALIZE_THRESHOLD
NATIONALIZATION_DESIRE_PRIVATIZE_THRESHOLD
NATIONALIZATION_RADICALS_THRESHOLD_TO_AVOID_NATIONALIZATION
NATIONALIZATION_RADICALS_THRESHOLD_TO_ALWAYS_COMPENSATE
NATIONALIZATION_DESIRE_FROM_RECENTLY_LIBERATED
NATIONALIZATION_DESIRE_FROM_RECENTLY_CONQUERED
NATIONALIZATION_GOLD_RESERVES_THRESHOLD
NATIONALIZATION_MAX_LEVELS_PER_UPDATE
AI_PEACE_AGREEMENT_BASE_VALUE
AI_PEACE_AGREEMENT_WHITE_PEACE_BASE
AI_PEACE_AGREEMENT_WAR_SUPPORT_MAX
AI_PEACE_AGREEMENT_UNACCEPTABLE_WARGOAL_VALUE
AI_PEACE_AGREEMENT_WARGOAL_VALUE_BASE
AI_PEACE_AGREEMENT_WARGOAL_VALUE_MIN
AI_PEACE_AGREEMENT_WARGOAL_VALUE_MAX
AI_PEACE_AGREEMENT_WARGOAL_VALUE_SCALED
AI_PEACE_AGREEMENT_ALLY_WARGOAL_MULT
AI_PEACE_AGREEMENT_SELF_WARGOAL_MULT
AI_PEACE_AGREEMENT_ENEMY_WARGOAL_SELF_MULT
AI_PEACE_AGREEMENT_ENEMY_WARGOAL_ALLY_MULT
AI_PEACE_AGREEMENT_NON_CONTESTED_ENEMY_WARGOAL_MULT
AI_PEACE_AGREEMENT_ACHIEVABLE_ALLY_WARGOAL
AI_PEACE_AGREEMENT_ACHIEVABLE_ENEMY_WARGOAL
AI_PEACE_AGREEMENT_WAR_SUPPORT_TO_HOLD_ON_TO_ACHIEVABLE_WARGOALS
AI_PEACE_AGREEMENT_PEACE_DESIRE_FACTOR
AI_CAPITULATE_COMPLETELY_DEFEATED
AI_CAPITULATE_BASE_VALUE
AI_CAPITULATE_WAR_LEADER_FACTOR
AI_CAPITULATE_WAR_SUPPORT_MAX
AI_CAPITULATE_SELF_WARGOAL_FACTOR
AI_CAPITULATE_ENEMY_WARGOAL_MULT
AI_CAPITULATE_ENEMY_FOLDS_FIRST
AI_CAPITULATE_ENEMY_FOLDS_FIRST_MIN_DESIRE
AI_CAPITULATE_PEACE_DESIRE_FACTOR
AI_PEACE_DESIRE_FROM_FORCE_BALANCE
AI_PEACE_DESIRE_FROM_SIDE_WAR_SUPPORT
AI_SIDE_WAR_SUPPORT_WAR_LEADER_MULT
AI_SIDE_WAR_SUPPORT_NEGOTIATOR_MULT
AI_PEACE_DESIRE_FACTOR_FROM_ANNEXATION
SECRET_GOAL_STICKINESS
ATTITUDE_STRONG_GOAL_SCORE_THRESHOLD
ATTITUDE_WEAK_GOAL_SCORE_THRESHOLD
GOAL_THREAT_INFAMOUS_FACTOR
GOAL_THREAT_NOTORIOUS_FACTOR
GOAL_THREAT_PARIAH_FACTOR
GOAL_THREAT_NEIGHBOR_FACTOR
GOAL_THREAT_SP_MAX_MULT
GOAL_THREAT_CUSTOMS_UNION_MULT
GOAL_ANTAGONIZE_POOR_RELATIONS_FACTOR
GOAL_ANTAGONIZE_COLD_RELATIONS_FACTOR
GOAL_ANTAGONIZE_HOSTILE_RELATIONS_FACTOR
GOAL_ANTAGONIZE_LIBERTY_DESIRE_FACTOR
GOAL_ANTAGONIZE_CONQUER_SCORE_MULT
GOAL_ANTAGONIZE_CONQUER_SCORE_MAX
GOAL_ANTAGONIZE_TREATY_PORT_SCORE_MULT
GOAL_ANTAGONIZE_TREATY_PORT_SCORE_MAX
GOAL_ANTAGONIZE_DOMINATE_SCORE_MULT
GOAL_ANTAGONIZE_DOMINATE_SCORE_MAX
GOAL_ANTAGONIZE_RIVAL_FACTOR
GOAL_ANTAGONIZE_WAR_FACTOR
GOAL_ANTAGONIZE_NATURAL_ENEMY_FACTOR
GOAL_BEFRIEND_CORDIAL_RELATIONS_FACTOR
GOAL_BEFRIEND_AMICABLE_RELATIONS_FACTOR
GOAL_BEFRIEND_FRIENDLY_RELATIONS_FACTOR
GOAL_BEFRIEND_PROTECTOR_THRESHOLD
GOAL_BEFRIEND_PROTECTOR_FACTOR
GOAL_BEFRIEND_PROTECTOR_RIVAL_MULT
GOAL_BEFRIEND_PROTECTOR_MAX_FACTOR
GOAL_BEFRIEND_PROTECTOR_SP_MAX_MULT
GOAL_BEFRIEND_SUBJECT_FACTOR
GOAL_BEFRIEND_ALLIANCE_FACTOR
GOAL_BEFRIEND_NATURAL_ALLY_FACTOR
GOAL_BEFRIEND_RECONCILE_FACTOR
GOAL_BEFRIEND_WAR_ALLY_FACTOR
GOAL_BEFRIEND_WANTS_TO_PROTECT_FACTOR
FRIENDLY_AI_JOIN_DIPLO_PLAY_FACTOR
VIOLATE_SOVEREIGNTY_ACTION_NAME
VIOLATE_SOVEREIGNTY_MIN_RELATIVE_STRENGTH
VIOLATE_SOVEREIGNTY_RANDOM_FACTOR
VIOLATE_SOVEREIGNTY_MIN_THEATER_IMPORTANCE
VIOLATE_SOVEREIGNTY_COOLDOWN_DAYS
EXPEL_DIPLOMATS_ACTION_NAME
AUTONOMOUS_TRADE_RANDOM_FACTOR
AUTONOMOUS_TRADE_STICKYNESS
AUTONOMOUS_TRADE_WEEKS_BEFORE_TRADE_REDUCTION
AUTONOMOUS_TRADE_MIN_DESIRABILITY_PER_QUANTITY_TO_MAINTAIN_TRADE
AUTONOMOUS_TRADE_MIN_DESIRABILITY_PER_QUANTITY_TO_INCREASE_TRADE
AUTONOMOUS_TRADE_MIN_DESIRABILITY_INITIALIZATION_MULTIPLIER
AUTONOMOUS_TRADE_POTENTIAL_REVENUE_BASE_COST_FACTOR
AUTONOMOUS_TRADE_DESIRE_SUBVENTIONS_FACTOR
AUTONOMOUS_TRADE_DESIRE_SUBVENTIONS_FACTOR_NEW_GOODS_MULT
AUTONOMOUS_TRADE_DESIRE_TARIFFS_FACTOR
AUTONOMOUS_TRADE_DESIRE_OPPOSITE_MARKET_SHARE_FACTOR
AUTONOMOUS_TRADE_DESIRE_SHORTAGE_FACTOR
AUTONOMOUS_TRADE_WEEKLY_TRADES_FRACTION_USED_FOR_FAILED_TRADE
TRADE_VALUE_DELTA_FACTOR
TRADE_VALUE_BASE_MULTIPLIER
TRADE_VALUE_RELATIVE_MULTIPLIER
TRADE_VALUE_FAVORED_GOODS_DIRECTION_MULT
TRADE_VALUE_DISFAVORED_GOODS_DIRECTION_MULT
UNUSED_CAPPED_RESOURCE_RATIO_TO_START_DISCOURAGING_EXPORT
UNUSED_CAPPED_RESOURCE_RATIO_TO_STOP_DISCOURAGING_EXPORT
COMPANY_TYPE_DEFAULT_BASE_WEIGHT
COMPANY_TYPE_RANDOM_FACTOR
COMPANY_TYPE_STICKYNESS
COMPANY_TYPE_STICKYNESS_DURATION_MONTHS
COMPANY_TYPE_FORMABLE_FACTOR
COMPANY_TYPE_FORMABLE_MULTIPLE_FREE_SLOTS_FACTOR
COMPANY_TYPE_PRODUCTIVITY_FACTOR
COMPANY_TYPE_PRODUCTIVITY_MAX
COMPANY_TYPE_BUILDING_LEVELS_FACTOR
COMPANY_TYPE_BUILDING_LEVELS_MAX
COMPANY_TYPE_COMPETITION_FACTOR
COMPANY_TYPE_BUILDING_GROUP_WEIGHT_IMPACT
MILITARY_UNITS_PER_FORMATION_ARMY
MILITARY_UNITS_PER_FORMATION_FLEET
MILITARY_UNITS_MIN_FOR_GARRISON_FORMATION
MILITARY_UNITS_MIN_FOR_GARRISON_FORMATION_IN_CAPITAL_HQ
MILITARY_UNITS_GARRISON_BATTALION_MULT
MILITARY_UNITS_MIN_DELTA_TO_TRANSFER_UNITS
MIN_RANK_TO_FORM_POWER_BLOC
POWER_BLOC_IDENTITY_RANDOM_FACTOR
POWER_BLOC_PRINCIPLE_RANDOM_FACTOR
POWER_BLOC_STATUE_RANDOM_FACTOR
LEAVE_POWER_BLOC_SCORE_THRESHOLD
POWER_BLOC_KICK_MEMBER_LOW_COHESION_THRESHOLD
POWER_BLOC_KICK_MEMBER_LOW_COHESION_SCORE
POWER_BLOC_KICK_MEMBER_COHESION_CHANGE_SCORE
POWER_BLOC_KICK_MEMBER_LEVERAGE_ADVANTAGE_SCORE
POWER_BLOC_KICK_MEMBER_POOR_RELATIONS_SCORE
POWER_BLOC_KICK_MEMBER_HOSTILE_ATTITUDE_SCORE
POWER_BLOC_KICK_MEMBER_MARKET_SHARE_SCORE
POWER_BLOC_KICK_MEMBER_HIGH_ARMY_MILITARY_STRENGTH_SCORE
POWER_BLOC_KICK_MEMBER_HIGH_NAVY_MILITARY_STRENGTH_SCORE
POWER_BLOC_KICK_MEMBER_SCORE_THRESHOLD
POWER_BLOC_KICK_MEMBER_RANDOM_FACTOR
IMPOSE_LAW_NO_POTENTIAL_LAW_COOLDOWN_MONTHS
IMPOSE_LAW_RANDOM_FACTOR
IMPOSE_LAW_MAX_IDEOLOGICAL_OPINION
IMPOSE_LAW_MAX_LIBERTY_DESIRE
IMPOSE_LAW_MIN_ENACTMENT_CHANCE
EXILE_INTERACTION_FAILED_COOLDOWN_MONTHS
AI_INTERACTION_PROMINENCE_CHANCE_FACTOR
AI_INTERACTION_MIN_PROMINENCE_CHANCE
SENT_PEACE_DEAL_MEMORY_DURATION_DAYS
TREATY_FAIRNESS_BASE_SCORE
REJECTED_TREATY_MEMORY_DURATION_DAYS
REJECTED_TREATY_MIN_ACCEPTANCE_IMPROVEMENT_FOR_NEW_PROPOSAL
REJECTED_TREATY_UNDER_MIN_ACCEPTANCE_IMPROVEMENT_PENALTY
TREATIES_RANDOM_FACTOR
TREATIES_CHECK_CATEGORIES_WHEN_COMPOSING_TREATY
TREATIES_NUMBER_CHECKED_CATEGORIES_TREATY_COMPOSER
TREATIES_MINIMUM_ACCEPTANCE_TO_PROPOSE
TREATIES_MINIMUM_OWN_ACCEPTANCE_TO_PROPOSE
TREATIES_MAX_NUMBER_ARTICLES
TREATIES_ACCEPTANCE_BASE
TREATIES_ACCEPTANCE_WITHDRAW_THRESHOLD
TREATIES_ACCEPTANCE_WITHDRAW_BINDING_PERIOD_THRESHOLD
TREATIES_DEFAULT_LENGTH_YEARS
COLONIZATION_VALUE_BASE
COLONIZATION_VALUE_HAS_COLONY_MULTIPLIER
COLONIZATION_VALUE_NO_PRESENCE_MULTIPLIER
TRANSIT_RIGHTS_BASE_DESIRE
TREATY_OBLIGATION_WE_OWE_THEM_ACCEPTANCE
TREATY_OBLIGATION_THEY_OWE_US_ACCEPTANCE
TREATY_OBLIGATION_THEY_OWE_US_RECENTLY_REPUDIATED_ACCEPTANCE
TREATY_OBLIGATION_THEY_CALL_US_IN_ACCEPTANCE
TREATY_OBLIGATION_THEY_CALL_US_IN_RECENTLY_REPUDIATED_ACCEPTANCE
PIRACY_HEAT_RAMP_UP_RATE
PIRACY_HEAT_RAMP_DOWN_RATE
PIRACY_HEAT_BASE_TRADE_VALUE_FOR_SCALING
PIRACY_HEAT_SCALING
PIRACY_HEAT_MAX
RAID_HEAT_GAIN_PER_LOST_SUPPLY_SHIP
RAID_HEAT_DECAY
PROTECT_SUPPLY_OWN_PATH_SCORE_MULT
RAID_SUPPLY_SCORING_FLEET_AVG_SPEED_MULT
RAID_SUPPLY_SCORING_FLEET_DETECTION_VISIBILITY_RATIO_MULT
RAID_SUPPLY_SCORING_FLEET_SIZE_MULT
RAID_SUPPLY_SCORING_FLEET_STRENGTH_RATIO_MULT
RAID_SUPPLY_SCORE_MULT
PROTECT_SUPPLY_SCORE_MULT
PROJECT_POWER_SCORE_MULT
PROTECT_SUPPLY_SCORING_FLEET_SCREENING_RATIO_MULT
PROTECT_SUPPLY_SCORING_FLEET_SIZE_MULT
PROTECT_SUPPLY_SCORING_FLEET_RAID_HEAT_MULT
PROTECT_SUPPLY_SCORING_FLEET_STRENGTH_RATIO_MULT
HUNT_PIRATES_SCORING_FLEET_DETECTION_RATIO_MULT
HUNT_PIRATES_SCORING_FLEET_SCREENING_RATIO_MULT
HUNT_PIRATES_MIN_HOSTILITY_MULT
HUNT_PIRATES_AT_WAR_MULT
HUNT_PIRATES_SCORE_MULT
PIRACY_SCORING_FLEET_SPEED_VISIBILITY_RATIO_ADJUSTER
PIRACY_SCORING_FLEET_SPEED_VISIBILITY_RATIO_MULT
PIRACY_NO_HOSTILITIES_MULT
PIRACY_HOSTILITIES_MULT
PRIVATEER_SCORING_FLEET_SPEED_VISIBILITY_RATIO_ADJUSTER
PRIVATEER_SCORING_FLEET_SPEED_VISIBILITY_RATIO_MULT
PORT_BOMBARDMENT_NAVAL_HOSTILITIES_MULT
PORT_BOMBARDMENT_FULL_HOSTILITIES_MULT
BLOCKADE_WORLD_MARKET_HUB_MULT
BLOCKADE_NOT_WORLD_MARKET_HUB_MULT
INTERCEPT_ENEMY_NAVAL_POWER_MULT
POWER_PROJECTION_ENEMY_NAVAL_POWER_MULT
ENEMY_NAVAL_POWER_RATIO_MAX
POWER_PROJECTION_HOSTILE_NAVAL_RATIO_MAX
INTERCEPT_HOSTILE_NAVAL_RATIO_FOR_FULL_SCORE
INTERCEPT_ACCEPTABLE_DISTANCE
POWER_PROJECTION_ACCEPTABLE_DISTANCE
BLOCKADE_ACCEPTABLE_DISTANCE
RAID_SUPPLY_ACCEPTABLE_DISTANCE
PROTECT_SUPPLY_ACCEPTABLE_DISTANCE
PORT_BOMBARDMENT_ACCEPTABLE_DISTANCE
HUNT_PIRATES_ACCEPTABLE_DISTANCE
DEFEND_COAST_SCORE_MULT
RAID_SUPPLY_ENEMY_NAVAL_POWER_MULT
PROTECT_SUPPLY_ENEMY_NAVAL_POWER_MULT
BLOCKADE_ENEMY_NAVAL_POWER_MULT
PORT_BOMBARDMENT_ENEMY_NAVAL_POWER_MULT
PROTECT_SUPPLY_DOMINANCE_PENALTY
PROTECT_SUPPLY_MIN_DOMINANCE_MULT
BLOCKADE_DOMINANCE_BOOST
PORT_BOMBARDMENT_DOMINANCE_BOOST
COMFORTABLE_HQ_NAVY_SIZE
NAVAL_HQ_IMPORTANCE_MIN_SCORE
```

---

### 3.4 `00_ai.txt` 之外的 AI 相关 define

**重要提醒**：AI 相关 define **并非**全部集中在 `00_ai.txt`。但也不能靠"名字里有没有 AI"来判断——下表是脚本对整个 `common\defines\` 树做的机械匹配（键名含独立单词 `AI`），**排除 `NAI` 本身**：

命中仅 4 条：

- `NPolitics`（`00_defines.txt`）：`MAX_GOVERNMENT_ALTERNATIVES_TO_CONSIDER_AI`
- `NMilitary`（`00_defines.txt`）：`AI_FIND_FLEET_EXPECTED_DISTANCE`
- `NGUI`（`00_interfaces.txt`）：`AI_STRATEGIC_REGION_STANCE_TYPE_ICON_FONT`、`AI_STRATEGIC_REGION_STANCE_TYPE_ICON_OFFSET`（都是 UI 图标设置，与 AI 行为无关）

下表为完整命中清单：

| File | Namespace block | Define |
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

```
game_rule = {
    default = setting_name                        # Which setting to default to

    setting_name = {
        apply_modifier = category:modifier_key    # Apply a modifier to characters matching a specific category.
                                                  # Valid are player, ai, and all. E.G., player:very_easy
        flag = flag_key                           # Has some specific effect. See "flags" section for list
    }
}
```

`game_rules.md` 同时给出本地化键命名约定（原文）：

```
rule_<key> will be used as the key for game rule names
setting_<key> will be used as the key for game rule setting names
setting_<key>_desc will be used as the key for game rule setting descs
```

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

| # | game_rule key | default | 非默认 setting | flag 条目数 |
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

| # | game_rule key | default | settings (non-default) | flag entries |
|---|---|---|---|---|
| 1 | `achievements` | `achievements_allowed` | `achievements_blocked` | `achievements_blocked:blocks_achievements` |
| 2 | `ai_behavior` | `standard_ai_behavior` | `lenient_ai_behavior`, `harsh_ai_behavior` | `lenient_ai_behavior:lenient_ai`<br>`harsh_ai_behavior:harsh_ai` |
| 3 | `ai_aggression` | `standard_ai_aggression` | `low_ai_aggression`, `high_ai_aggression` | `low_ai_aggression:low_ai_aggression`<br>`high_ai_aggression:high_ai_aggression` |
| 4 | `free_construction` | `free_construction_scaled_player_exemption` | `free_construction_scaled_all`, `free_construction_unscaled` | `free_construction_scaled_player_exemption:free_construction_scaled_player_exemption`<br>`free_construction_unscaled:free_construction_unscaled` |
| 5 | `formable_nations` | `all_formable_nations` | `plausible_formable_nations` | (none) |
| 6 | `releasable_nations` | `all_releasable_nations` | `plausible_releasable_nations` | (none) |
| 7 | `loyalties_grace_period` | `loyalties_grace_period_none` | `loyalties_grace_period_short`, `loyalties_grace_period_long`, `loyalties_grace_period_extra_long` | `loyalties_grace_period_none:loyalties_grace_period_none`<br>`loyalties_grace_period_short:loyalties_grace_period_short`<br>`loyalties_grace_period_long:loyalties_grace_period_long`<br>`loyalties_grace_period_extra_long:loyalties_grace_period_extra_long` |
| 8 | `pop_consolidation` | `moderate_consolidation` | `no_consolidation`, `minor_consolidation`, `aggressive_consolidation` | `no_consolidation:no_pop_consolidation`<br>`minor_consolidation:minor_pop_consolidation`<br>`moderate_consolidation:moderate_pop_consolidation`<br>`aggressive_consolidation:aggressive_pop_consolidation` |
| 9 | `monument_effects` | `allow_monument_effects` | `prestige_only_monument_effects`, `no_monument_effects` | **43** entries (see section 4.7) |
| 10 | `subject_flags` | `allow_subject_flags` | `no_subject_flags` | `no_subject_flags:no_subject_flags` |
| 11 | `subject_map_color` | `allow_subject_map_color` | `no_subject_map_color` | `no_subject_map_color:no_subject_map_color` |
| 12 | `fantastical_content` | `allow_fantastical_content` | `no_fantastical_content` | `allow_fantastical_content:give_fantastical_content`<br>`no_fantastical_content:no_fantastical_content` |
| 13 | `custom_rng_seed` | `no_custom_rng_seed` | `use_custom_rng_seed` | `use_custom_rng_seed:use_custom_rng_seed` |
| 14 | `dynamic_naming` | `allow_dynamic_naming` | `no_dynamic_naming` | `no_dynamic_naming:no_dynamic_naming` |
| 15 | `ruler_selector` | `no_ruler_selector` | `allow_ruler_selector` | `allow_ruler_selector:give_ruler_selector`<br>`allow_ruler_selector:blocks_achievements`<br>`no_ruler_selector:no_ruler_selector` |

---

### 4.6 全部 setting 键（38 个）

`game_rule` 下的 `setting_*` 块即为可选设置。下表列出全部 38 个，并标明所属规则与是否为默认值。

| # | setting key | game_rule | is default |
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

| game_rule | setting | flag / directive |
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

```pdx
has_game_rule = free_construction_unscaled
has_game_rule = free_construction_scaled_player_exemption
has_game_rule = high_ai_aggression
```
来源：`GAME\common\ai_strategies\00_default_strategy.txt` 第 4367、4370、6847 行。

| 项目 | 实测 |
|---|---|
| 使用 `has_game_rule` 的文件数 | **18**（`common\*\*.txt` + `events\*.txt`） |
| 观察到的语法 | `has_game_rule = <setting_key>`（单参数） |
| `has_game_rule = { ... }` 块形式 | 全游戏仅 1 处命中，位于 `common\trigger_localization\00_trigger_localization.txt` 第 4489 行——那是 **trigger 的提示文本定义**，不是使用语法。【提取】 |

> 块形式（`has_game_rule = { name = ... value = ... }`）是否存在【未确认】——原版未使用；建议只写标量形式。

### 4.10 做 game rule mod 的注意点

| # | 注意点 |
|---|---|
| 1 | **三份本地化键缺一不可**：`rule_<key>`、`setting_<key>`、`setting_<key>_desc`（§4.2 已在本地化文件验证） |
| 2 | flag 只是开关名；**效果要自己在脚本里用 `has_game_rule` 实现**，写 flag 不会自动产生效果 |
| 3 | 原版只在 `common\game_rules\00_game_rules.txt` 定义规则；mod 想**新增**规则需要新文件（如 `01_mymod_rules.txt`），想**改默认值**则只需重写该规则块——game_rules 采用与本数据库一致的"同名键后加载覆盖"语义【推断】 |
| 4 | `apply_modifier = player:very_easy` 形式文档有载，但原版 1.14.2 **零使用**；可用性【未确认】 |
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

**实测前缀分布**（2364 个键，按第一个下划线前切分）——与上述规则完全吻合：

| 前缀 | 键数 | 流动含义（据上文推断） |
|---|---|---|
| `country_` | **1095** | 作用于国家；在权力集团上施加时只流到成员国，不再向下 |
| `state_` | **571** | 会穿过国家流到该国所有州 |
| `building_` | **300** | 作用于建筑 |
| `goods_` | **125** | 作用于商品 |
| `ship_` | **68** | 作用于船只 |
| `unit_` | **56** | 作用于陆军单位 |
| `character_` | **41** | 作用于角色 |
| `power_` | **39** | 权力集团（`power_bloc_*`） |
| `interest_` | **33** | 利益集团（`interest_group_*`） |
| `battle_` | **12** | 战斗 |
| `military_` | **11** | 军事 |
| `tax_` / `political_` | 各 **6** | 税收 / 政治 |
| `dummy_` | **1** | 占位 |

【提取】

**后缀分布**同样有强规律：`_add` **1635**、`_mult` **626**、`_bool` **89**、`_factor` 5，另有 9 个键各以其它词结尾（`_support`、`_strata`、`_time`、`_cost`、`_guns`、`_literacy`、`_impact`、`_likelihood`、`_type`，各 1 个）。合计 2364。【提取】——即「加法修正 / 乘法修正 / 布尔开关」三分天下。

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

字段是否必填【未确认】——原版有 31 个键完全没写 `decimals`、1479 个键没写 `percent`，说明二者至少有默认值。建议 mod 显式写出 `decimals` / `color` / `percent` 以避免显示异常。

### 5.3 规模与文件分布

| File | Modifier type keys |
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

#### `00_modifier_types.txt` -- 451 keys

```text
interest_group_ig_armed_forces_pol_str_mult
interest_group_ig_devout_pol_str_mult
interest_group_ig_industrialists_pol_str_mult
interest_group_ig_intelligentsia_pol_str_mult
interest_group_ig_landowners_pol_str_mult
interest_group_ig_petty_bourgeoisie_pol_str_mult
interest_group_ig_rural_folk_pol_str_mult
interest_group_ig_trade_unions_pol_str_mult
interest_group_pol_str_mult
interest_group_in_opposition_agitator_popularity_add
country_bureaucracy_add
country_bureaucracy_cost_add
country_bureaucracy_mult
country_bureaucracy_investment_cost_factor_mult
country_amenability_add
country_authority_add
country_authority_cost_add
country_authority_mult
country_free_charters_add
country_influence_add
country_influence_cost_add
country_influence_mult
country_max_companies_add
country_max_unassigned_generals_add
country_max_unassigned_admirals_add
country_company_throughput_bonus_add
country_company_construction_efficiency_bonus_add
country_overlord_income_transfer_mult
country_diplomatic_reputation_add
country_liberty_desire_add
country_liberty_desire_of_subjects_add
country_liberty_desire_increase_mult
country_liberty_desire_decrease_mult
country_authority_per_subject_add
country_subject_income_transfer_mult
country_subject_income_transfer_heathen_mult
country_construction_add
country_max_weekly_construction_progress_add
country_private_construction_allocation_mult
country_construction_goods_cost_mult
country_prestige_add
country_prestige_mult
country_diplomatic_play_maneuvers_add
country_diplomatic_play_maneuvers_mult
country_initiator_war_goal_maneuver_cost_mult
country_prestige_from_army_power_projection_mult
country_prestige_from_navy_power_projection_mult
country_infamy_generation_mult
country_infamy_generation_against_unrecognized_mult
country_infamy_decay_mult
country_tension_decay_mult
country_improve_relations_speed_mult
country_damage_relations_speed_mult
country_minting_add
country_minting_mult
country_expenses_add
country_state_religion_wages_mult
country_non_state_religion_wages_mult
country_government_wages_mult
country_military_wages_mult
country_military_goods_cost_mult
country_tax_income_add
country_support_separatism_strength_mult
country_support_separatism_resistance_mult
state_tariff_import_add
state_tariff_export_add
state_subvention_import_add
state_subvention_export_add
tax_income_add
tax_consumption_add
tax_dividends_add
tax_per_capita_add
tax_land_add
tax_heathen_add
country_consumption_tax_cost_mult
country_loan_interest_rate_add
country_loan_interest_rate_mult
country_gold_reserve_limit_mult
country_government_dividends_reinvestment_add
country_government_dividends_efficiency_add
country_government_dividends_waste_add
building_company_worker_dividends_add
building_company_government_dividends_add
country_education_fervor_add
country_primary_culture_fervor_from_laws_add
interest_group_pol_str_factor
interest_group_ig_armed_forces_approval_add
interest_group_ig_devout_approval_add
interest_group_ig_industrialists_approval_add
interest_group_ig_intelligentsia_approval_add
interest_group_ig_landowners_approval_add
interest_group_ig_petty_bourgeoisie_approval_add
interest_group_ig_rural_folk_approval_add
interest_group_ig_trade_unions_approval_add
interest_group_ig_armed_forces_pop_attraction_mult
interest_group_ig_devout_pop_attraction_mult
interest_group_ig_industrialists_pop_attraction_mult
interest_group_ig_intelligentsia_pop_attraction_mult
interest_group_ig_landowners_pop_attraction_mult
interest_group_ig_petty_bourgeoisie_pop_attraction_mult
interest_group_ig_rural_folk_pop_attraction_mult
interest_group_ig_trade_unions_pop_attraction_mult
interest_group_amenability_add
interest_group_approval_add
interest_group_pop_attraction_mult
interest_group_in_government_approval_add
interest_group_in_opposition_approval_add
country_opposition_ig_approval_add
country_voting_power_base_add
country_voting_power_from_literacy_add
country_voting_power_wealth_threshold_add
country_voting_power_mult
country_legitimacy_base_add
country_legitimacy_govt_total_clout_add
country_legitimacy_govt_total_votes_add
country_legitimacy_headofstate_add
country_legitimacy_govt_leader_clout_add
country_legitimacy_govt_size_add
country_legitimacy_ideological_incoherence_mult
country_party_whip_impact_add
country_radicals_from_legitimacy_mult
country_loyalists_from_legitimacy_mult
country_suppression_attraction_factor
country_bolster_attraction_factor
country_suppression_cost_mult
country_bolster_cost_mult
country_institution_size_change_speed_mult
country_law_enactment_speed_mult
country_law_enactment_max_setbacks_add
country_law_enactment_imposition_success_add
country_law_enactment_success_add
country_law_enactment_stall_mult
country_law_enactment_stall_add
state_devastation_decay_mult
state_decree_cost_mult
political_movement_pop_attraction_mult
political_movement_character_attraction_mult
political_movement_radicalism_add
political_movement_activism_growth_mult
political_movement_radicalism_from_enactment_disapproval_mult
political_movement_radicalism_from_enactment_approval_mult
country_agitator_slots_add
country_revolution_clock_time_add
country_revolution_progress_add
country_revolution_progress_mult
country_secession_clock_time_add
country_secession_progress_add
country_secession_progress_mult
country_radicals_from_conquest_mult
state_trade_capacity_add
state_trade_capacity_mult
state_trade_quantity_mult
state_market_access_price_impact
state_weekly_trades_add
state_trade_advantage_mult
power_bloc_trade_advantage_add
state_trade_advantage_same_religion_add
state_trade_advantage_from_capacity_add
state_max_trade_advantage_from_capacity_add
state_import_advantage_mult
state_export_advantage_mult
country_weekly_innovation_add
country_weekly_innovation_mult
country_weekly_innovation_max_add
country_tech_spread_add
country_tech_spread_mult
country_tech_research_speed_mult
country_tech_group_research_speed_mult
country_ahead_of_time_research_penalty_mult
country_war_support_battles_increase_mult
country_war_support_battles_decrease_mult
country_war_support_casualties_mult
country_resource_discovery_chance_mult
country_resource_depletion_chance_mult
state_construction_mult
state_pop_pol_str_add
state_pop_pol_str_mult
state_welfare_payments_add
state_welfare_payments_mult
state_standard_of_living_add
state_lower_strata_standard_of_living_add
state_middle_strata_standard_of_living_add
state_upper_strata_standard_of_living_add
state_expected_sol_mult
state_fortification_naval_invasion_add
state_fortification_naval_battle_mult
state_fortification_bombardment_resistance_add
state_expected_sol_from_literacy
state_lower_strata_expected_sol_add
state_middle_strata_expected_sol_add
state_upper_strata_expected_sol_add
state_tax_capacity_add
state_tax_capacity_mult
state_tax_waste_add
state_tax_collection_mult
state_education_access_add
state_literacy_growth_add
state_food_security_add
state_pollution_generation_add
state_pollution_reduction_health_mult
state_peasants_consumption_multiplier_add
state_peasants_education_access_add
state_education_access_wealth_add
state_pop_qualifications_mult
state_working_adult_ratio_add
state_dependent_wage_add
state_dependent_wage_mult
building_economy_of_scale_level_cap_add
state_slave_import_mult
building_level_bureaucracy_cost_add
state_assimilation_mult
state_conversion_mult
state_bureaucracy_population_base_cost_factor_mult
state_dependent_political_participation_add
state_political_strength_from_wealth_mult
state_political_strength_from_welfare_mult
state_harvest_condition_drought_impact_mult
state_harvest_condition_drought_duration_mult
state_harvest_condition_flood_impact_mult
state_harvest_condition_flood_duration_mult
state_harvest_condition_wildfire_impact_mult
state_harvest_condition_wildfire_duration_mult
state_harvest_condition_extreme_winds_impact_mult
state_harvest_condition_extreme_winds_duration_mult
state_harvest_condition_heatwave_impact_mult
state_harvest_condition_heatwave_duration_mult
state_harvest_condition_disease_outbreak_impact_mult
state_harvest_condition_disease_outbreak_duration_mult
state_harvest_condition_earthquake_impact_mult
state_harvest_condition_earthquake_duration_mult
state_harvest_condition_tsunami_impact_mult
state_harvest_condition_tsunami_duration_mult
state_incorporation_speed_mult
state_contiguous_incorporation_speed_mult
state_non_contiguous_incorporation_speed_mult
state_infrastructure_add
state_infrastructure_from_population_add
state_infrastructure_from_population_mult
state_infrastructure_from_population_max_add
state_infrastructure_from_population_max_mult
state_infrastructure_from_automobiles_consumption_add
state_infrastructure_mult
state_institution_impact_add
state_urbanization_per_level_add
state_urbanization_per_level_mult
state_building_barrack_max_level_add
state_building_conscription_center_max_level_add
state_building_naval_fortification_max_level_add
state_building_construction_sector_max_level_add
state_colony_growth_creation_factor
state_colony_growth_speed_mult
state_non_homeland_colony_growth_speed_mult
state_migration_pull_add
state_migration_pull_mult
state_unincorporated_starting_wages_mult
state_migration_pull_unincorporated_mult
state_migration_quota_mult
country_mass_migration_attraction_mult
state_conscription_rate_add
state_conscription_rate_mult
state_minimum_incorporated_subsistence_arable_land_add
building_minimum_incorporated_subsistence_employment_add
state_birth_rate_mult
state_blockade_resistance_add
state_mortality_mult
state_non_homeland_mortality_mult
state_mortality_wealth_mult
state_turmoil_effects_mult
state_mortality_turmoil_mult
state_radicals_and_loyalists_from_sol_change_mult
state_radicals_from_political_movements_mult
state_loyalists_from_political_movements_mult
character_command_limit_add
character_command_limit_mult
character_max_offensive_battles_add
character_naval_mission_area_add
character_popularity_add
character_prominence_add
character_piracy_goods_capacity_mult
country_piracy_income_add
character_loyalty_add
character_commander_loyalty_add
character_loyalty_mult
character_health_add
character_advancement_speed_add
character_advancement_speed_mult
character_convoy_protection_mult
character_blockade_mult
character_interception_add
character_raid_supply_add
character_convoy_raiding_mult
battle_offense_owned_province_mult
battle_defense_owned_province_mult
battle_casualties_mult
battle_combat_width_mult
country_sailors_max_add
country_ship_construction_add
country_supply_ship_construction_ratio_add
country_ship_construction_progress_max_add
country_ship_construction_goods_cost_mult
country_supply_ship_construction_progress_max_add
country_supply_ship_construction_progress_max_mult
country_ship_group_capital_ships_construction_progress_max_add
country_ship_group_capital_ships_construction_progress_max_mult
country_ship_group_cruisers_construction_progress_max_add
country_ship_group_cruisers_construction_progress_max_mult
country_ship_group_torpedo_craft_construction_progress_max_add
country_ship_group_torpedo_craft_construction_progress_max_mult
country_ship_construction_efficiency_add
country_ship_group_capital_ships_construction_efficiency_add
country_ship_group_cruisers_construction_efficiency_add
country_ship_group_torpedo_craft_construction_efficiency_add
country_ship_group_supply_ships_construction_efficiency_add
country_ship_type_troop_ship_construction_efficiency_add
country_ship_type_protected_cruiser_construction_efficiency_add
country_ship_type_armored_cruiser_construction_efficiency_add
country_ship_type_light_cruiser_construction_efficiency_add
country_ship_crew_starting_veterancy_experience_add
country_ship_crew_starting_veterancy_experience_mult
ship_interest_gain_add
ship_interest_gain_mult
ship_accuracy_add
ship_accuracy_mult
ship_armor_add
ship_armor_mult
ship_blockade_strength_add
ship_blockade_strength_mult
ship_carrying_capacity_add
ship_carrying_capacity_mult
ship_construction_progress_max_add
ship_construction_progress_max_mult
ship_crew_damage_add
ship_crew_damage_mult
ship_crew_max_add
ship_crew_max_mult
ship_critical_hit_chance_add
ship_critical_hit_chance_mult
ship_critical_hit_multiplier_add
ship_critical_hit_multiplier_mult
ship_detection_add
ship_detection_mult
ship_hit_points_max_add
ship_hit_points_max_mult
ship_hull_damage_add
ship_hull_damage_mult
ship_marine_capacity_add
ship_marine_capacity_mult
ship_readiness_gain_add
ship_readiness_gain_mult
ship_screening_add
ship_screening_mult
ship_movement_speed_add
ship_movement_speed_mult
ship_supply_capacity_add
ship_supply_capacity_mult
ship_supply_efficiency_add
ship_supply_efficiency_mult
ship_visibility_add
ship_visibility_mult
ship_vulnerability_add
ship_vulnerability_mult
ship_max_distance_to_port_add
ship_max_distance_to_port_mult
ship_battle_condition_accuracy_penalty_mult
ship_naval_invasion_efficiency_mult
ship_suffered_accuracy_mult
ship_suffered_crew_damage_mult
ship_suffered_crit_chance_mult
ship_suffered_crit_damage_mult
ship_suffered_hull_damage_mult
ship_ship_type_submarine_hull_damage_mult
ship_ship_type_aircraft_carrier_hull_damage_mult
ship_ship_type_supply_ship_supply_capacity_mult
ship_battle_against_ship_type_torpedo_boat_accuracy_add
ship_battle_against_ship_type_torpedo_boat_accuracy_mult
ship_battle_against_ship_type_torpedo_boat_destroyer_accuracy_add
ship_battle_against_ship_type_torpedo_boat_destroyer_accuracy_mult
ship_battle_against_ship_type_submarine_accuracy_add
ship_battle_against_ship_type_submarine_accuracy_mult
ship_battle_against_ship_type_destroyer_accuracy_add
ship_battle_against_ship_type_destroyer_accuracy_mult
ship_battle_against_ship_type_modern_ironclad_hull_damage_mult
ship_battle_against_ship_type_pre_dreadnought_hull_damage_mult
ship_battle_against_ship_type_dreadnought_hull_damage_mult
ship_battle_against_ship_type_super_dreadnought_hull_damage_mult
unit_offense_add
unit_offense_mult
unit_defense_add
unit_defense_mult
unit_army_offense_add
unit_army_offense_mult
unit_army_defense_add
unit_army_defense_mult
unit_morale_loss_add
unit_morale_loss_mult
unit_morale_damage_mult
unit_morale_recovery_mult
unit_kill_rate_add
unit_recovery_rate_add
unit_provinces_captured_mult
unit_provinces_lost_mult
unit_devastation_mult
unit_supply_consumption_mult
unit_occupation_mult
unit_naval_invasion_efficiency_mult
unit_combat_unit_type_siege_artillery_offense_mult
unit_combat_unit_type_shrapnel_artillery_offense_mult
unit_combat_unit_type_heavy_tank_offense_mult
unit_combat_unit_type_cannon_artillery_offense_mult
unit_combat_unit_type_mobile_artillery_offense_mult
unit_combat_unit_type_trench_infantry_offense_add
unit_combat_unit_type_squad_infantry_offense_add
unit_combat_unit_type_mechanized_infantry_offense_add
military_formation_army_movement_speed_add
military_formation_army_movement_speed_mult
military_formation_fleet_movement_speed_add
military_formation_fleet_movement_speed_mult
military_formation_interest_gain_mult
military_formation_mobilization_speed_add
military_formation_mobilization_speed_mult
military_formation_organization_gain_add
military_formation_organization_gain_mult
military_formation_attrition_risk_add
military_formation_attrition_risk_mult
unit_army_experience_gain_add
unit_experience_gain_add
unit_army_experience_gain_mult
unit_experience_gain_mult
ship_crew_experience_gain_add
ship_crew_experience_gain_mult
country_production_tech_research_speed_mult
country_production_tech_spread_mult
dummy_modifier_type
state_radicalism_increases_violent_hostility_mult
state_radicalism_increases_cultural_erasure_mult
state_radicalism_increases_open_prejudice_mult
state_radicalism_increases_second_rate_citizen_mult
state_radicalism_increases_full_acceptance_mult
state_loyalism_increases_violent_hostility_mult
state_loyalism_increases_cultural_erasure_mult
state_loyalism_increases_open_prejudice_mult
state_loyalism_increases_second_rate_citizen_mult
state_loyalism_increases_full_acceptance_mult
state_sell_orders_ammunition_add
state_sell_orders_small_arms_add
state_sell_orders_artillery_add
state_sell_orders_grain_add
state_buy_orders_ammunition_add
state_buy_orders_small_arms_add
state_buy_orders_artillery_add
country_flagship_interest_gain_mult
```

#### `01_building_modifier_types.txt` -- 351 keys

```text
building_group_bg_construction_laborers_mortality_mult
building_group_bg_agriculture_laborers_mortality_mult
building_group_bg_agriculture_farmers_mortality_mult
building_group_bg_ranching_laborers_mortality_mult
building_group_bg_ranching_farmers_mortality_mult
building_group_bg_plantations_laborers_mortality_mult
building_group_bg_plantations_slaves_mortality_mult
building_group_bg_rubber_laborers_mortality_mult
building_group_bg_rubber_slaves_mortality_mult
building_group_bg_plantations_farmers_mortality_mult
building_group_bg_mining_laborers_mortality_mult
building_group_bg_manufacturing_laborers_mortality_mult
building_group_bg_mining_laborers_standard_of_living_add
building_group_bg_manufacturing_laborers_standard_of_living_add
building_group_bg_mining_machinists_mortality_mult
building_group_bg_manufacturing_machinists_mortality_mult
building_group_bg_mining_machinists_standard_of_living_add
building_group_bg_manufacturing_machinists_standard_of_living_add
building_group_bg_mining_slaves_mortality_mult
building_group_bg_logging_laborers_mortality_mult
building_group_bg_logging_machinists_mortality_mult
building_group_bg_logging_engineers_mortality_mult
building_group_bg_logging_slaves_mortality_mult
building_group_bg_mining_engineers_mortality_mult
building_group_bg_manufacturing_engineers_mortality_mult
building_group_bg_mining_engineers_standard_of_living_add
building_group_bg_manufacturing_engineers_standard_of_living_add
building_group_bg_manor_houses_aristocrats_standard_of_living_add
building_group_bg_subsistence_agriculture_peasants_standard_of_living_add
building_group_bg_subsistence_ranching_peasants_standard_of_living_add
building_group_bg_service_tax_mult
building_group_bg_agriculture_tax_mult
building_group_bg_ranching_tax_mult
building_group_bg_plantations_tax_mult
building_group_bg_mining_tax_mult
building_group_bg_rubber_tax_mult
building_group_bg_logging_tax_mult
building_group_bg_fishing_tax_mult
building_group_bg_whaling_tax_mult
building_group_bg_oil_extraction_tax_mult
building_group_bg_manufacturing_tax_mult
building_group_bg_government_tax_mult
building_group_bg_infrastructure_tax_mult
building_group_bg_service_mortality_mult
building_group_bg_agriculture_mortality_mult
building_group_bg_ranching_mortality_mult
building_group_bg_plantations_mortality_mult
building_group_bg_mining_mortality_mult
building_group_bg_rubber_mortality_mult
building_group_bg_logging_mortality_mult
building_group_bg_fishing_mortality_mult
building_group_bg_whaling_mortality_mult
building_group_bg_oil_extraction_mortality_mult
building_group_bg_manufacturing_mortality_mult
building_group_bg_government_mortality_mult
building_group_bg_infrastructure_mortality_mult
building_group_bg_service_standard_of_living_add
building_group_bg_agriculture_standard_of_living_add
building_group_bg_plantations_standard_of_living_add
building_group_bg_mining_standard_of_living_add
building_group_bg_rubber_standard_of_living_add
building_group_bg_logging_standard_of_living_add
building_group_bg_fishing_standard_of_living_add
building_group_bg_whaling_standard_of_living_add
building_group_bg_oil_extraction_standard_of_living_add
building_group_bg_manufacturing_standard_of_living_add
building_group_bg_government_standard_of_living_add
building_group_bg_infrastructure_standard_of_living_add
building_group_bg_ranching_standard_of_living_add
building_group_bg_service_employee_mult
building_group_bg_agriculture_employee_mult
building_group_bg_plantations_employee_mult
building_group_bg_mining_employee_mult
building_group_bg_rubber_employee_mult
building_group_bg_logging_employee_mult
building_group_bg_fishing_employee_mult
building_group_bg_whaling_employee_mult
building_group_bg_oil_extraction_employee_mult
building_group_bg_manufacturing_employee_mult
building_group_bg_government_employee_mult
building_group_bg_infrastructure_employee_mult
building_goods_input_mult
building_throughput_add
building_cash_reserves_mult
building_group_bg_agriculture_throughput_add
building_group_bg_ranching_throughput_add
building_group_bg_extraction_throughput_add
building_group_bg_mining_throughput_add
building_group_bg_plantations_throughput_add
building_group_bg_manufacturing_throughput_add
building_group_bg_construction_infrastructure_usage_mult
building_group_bg_agriculture_infrastructure_usage_mult
building_group_bg_plantations_infrastructure_usage_mult
building_group_bg_ranching_infrastructure_usage_mult
building_group_bg_manufacturing_allowed_collectivization_add
building_group_bg_agriculture_allowed_collectivization_add
building_group_bg_ranching_allowed_collectivization_add
building_group_bg_subsistence_agriculture_allowed_collectivization_add
building_group_bg_subsistence_ranching_allowed_collectivization_add
building_group_bg_plantations_allowed_collectivization_add
building_group_bg_mining_allowed_collectivization_add
building_group_bg_heavy_industry_allowed_collectivization_add
building_group_bg_military_industry_allowed_collectivization_add
building_group_bg_light_industry_allowed_collectivization_add
building_group_bg_extraction_allowed_collectivization_add
building_group_bg_power_allowed_collectivization_add
building_group_bg_private_infrastructure_allowed_collectivization_add
building_group_bg_arts_allowed_collectivization_add
building_group_bg_arts_throughput_add
building_group_bg_heavy_industry_construction_efficiency_add
building_group_bg_military_industry_construction_efficiency_add
building_group_bg_light_industry_construction_efficiency_add
building_group_bg_ranching_construction_efficiency_add
building_group_bg_agriculture_construction_efficiency_add
building_group_bg_plantations_construction_efficiency_add
building_group_bg_extraction_construction_efficiency_add
building_group_bg_infrastructure_construction_efficiency_add
building_group_bg_government_construction_efficiency_add
building_group_bg_military_construction_efficiency_add
building_subsistence_output_add
building_subsistence_output_mult
building_mobilization_cost_mult
building_unincorporated_subsistence_output_mult
building_training_rate_add
building_training_rate_mult
building_naval_administration_training_rate_add
building_naval_administration_training_rate_mult
building_naval_administration_hiring_rate_mult
building_working_conditions_mult
building_minimum_wage_mult
building_unincorporated_throughput_add
goods_output_services_add
goods_output_fine_art_add
goods_output_furniture_add
goods_output_clothes_add
goods_output_tools_add
goods_output_glass_add
goods_output_steel_add
goods_output_liquor_add
goods_output_groceries_add
goods_output_luxury_clothes_add
goods_output_luxury_furniture_add
goods_output_porcelain_add
goods_output_fertilizer_add
goods_output_explosives_add
goods_output_ammunition_add
goods_output_artillery_add
goods_output_engines_add
goods_output_clippers_add
goods_output_steamers_add
goods_output_manowars_add
goods_output_ironclads_add
goods_output_automobiles_add
goods_output_aeroplanes_add
goods_output_tanks_add
goods_output_radios_add
goods_output_telephones_add
goods_output_grain_add
goods_output_fish_add
goods_output_meat_add
goods_output_fruit_add
goods_output_wine_add
goods_output_fabric_add
goods_output_wood_add
goods_output_sugar_add
goods_output_coal_add
goods_output_iron_add
goods_output_lead_add
goods_output_oil_add
goods_output_gold_add
goods_output_sulfur_add
goods_output_hardwood_add
goods_output_rubber_add
goods_output_merchant_marine_add
goods_output_coffee_add
goods_output_dye_add
goods_output_opium_add
goods_output_tea_add
goods_output_silk_add
goods_output_tobacco_add
goods_output_small_arms_add
goods_output_paper_add
goods_output_electricity_add
goods_output_transportation_add
goods_input_fabric_add
goods_input_wood_add
goods_input_iron_add
goods_input_coal_add
goods_input_lead_add
goods_input_liquor_add
goods_input_grain_add
goods_input_fish_add
goods_input_meat_add
goods_input_fruit_add
goods_input_sugar_add
goods_input_glass_add
goods_input_dye_add
goods_input_silk_add
goods_input_tobacco_add
goods_input_wine_add
goods_input_hardwood_add
goods_input_sulfur_add
goods_input_oil_add
goods_input_steel_add
goods_input_fertilizer_add
goods_input_tools_add
goods_input_rubber_add
goods_input_merchant_marine_add
goods_input_opium_add
goods_input_ammunition_add
goods_input_artillery_add
goods_input_small_arms_add
goods_input_clothes_add
goods_input_groceries_add
goods_input_engines_add
goods_input_automobiles_add
goods_input_clippers_add
goods_input_steamers_add
goods_input_manowars_add
goods_input_ironclads_add
goods_input_paper_add
goods_input_explosives_add
goods_input_electricity_add
goods_input_transportation_add
goods_input_aeroplanes_add
goods_input_tanks_add
goods_input_radios_add
goods_input_telephones_add
goods_output_hardwood_mult
goods_output_oil_mult
building_group_bg_service_throughput_add
building_group_bg_oil_extraction_throughput_add
building_construction_sector_throughput_add
building_coal_mine_throughput_add
building_coffee_plantation_throughput_add
building_tobacco_plantation_throughput_add
building_sugar_plantation_throughput_add
building_silk_plantation_throughput_add
building_dye_plantation_throughput_add
building_cotton_plantation_throughput_add
building_iron_mine_throughput_add
building_gold_mine_throughput_add
building_shipyard_throughput_add
building_port_throughput_add
building_group_bg_logging_throughput_add
building_group_bg_fishing_throughput_add
building_rye_farm_throughput_add
building_group_bg_whaling_throughput_add
building_wheat_farm_throughput_add
building_rice_farm_throughput_add
building_maize_farm_throughput_add
building_millet_farm_throughput_add
building_livestock_ranch_throughput_add
building_opium_plantation_throughput_add
building_art_academy_throughput_add
building_university_throughput_add
building_whaling_station_throughput_add
goods_output_tools_mult
goods_output_small_arms_mult
goods_output_engines_mult
goods_output_artillery_mult
goods_output_ammunition_mult
goods_output_automobiles_mult
goods_output_aeroplanes_mult
goods_output_tanks_mult
goods_output_clippers_mult
goods_output_steamers_mult
goods_output_manowars_mult
goods_output_ironclads_mult
building_food_industry_throughput_add
building_munition_plant_throughput_add
building_synthetics_plant_throughput_add
building_textile_mill_throughput_add
building_furniture_manufactory_throughput_add
building_glassworks_throughput_add
building_tooling_workshop_throughput_add
building_paper_mill_throughput_add
building_chemical_plant_throughput_add
building_motor_industry_throughput_add
building_automotive_industry_throughput_add
building_electrics_industry_throughput_add
building_arms_industry_throughput_add
building_artillery_foundry_throughput_add
building_power_plant_throughput_add
building_lead_mine_throughput_add
building_sulfur_mine_throughput_add
building_gold_field_throughput_add
building_railway_throughput_add
building_rubber_plantation_throughput_add
building_tea_plantation_throughput_add
building_vineyard_throughput_add
building_explosives_factory_throughput_add
goods_output_liquor_mult
goods_output_wine_mult
goods_output_fabric_mult
goods_output_fruit_mult
goods_output_sugar_mult
goods_output_radios_mult
goods_output_silk_mult
building_steel_mill_throughput_add
building_urban_center_throughput_add
goods_output_electricity_mult
building_government_administration_throughput_add
building_nationalization_cost_mult
building_nationalization_radicals_mult
building_nationalization_investment_return_add
goods_input_small_arms_mult
goods_input_artillery_mult
goods_input_ammunition_mult
goods_input_oil_mult
goods_input_radios_mult
goods_input_tanks_mult
country_bg_manufacturing_require_subsidies_bool
building_self_investment_chance_add
building_group_bg_manufacturing_self_investment_chance_add
building_group_bg_agriculture_self_investment_chance_add
building_group_bg_ranching_self_investment_chance_add
building_group_bg_plantations_self_investment_chance_add
building_group_bg_extraction_self_investment_chance_add
building_group_bg_infrastructure_self_investment_chance_add
building_group_bg_power_self_investment_chance_add
building_job_attractiveness_mult
building_laborers_job_attractiveness_mult
building_academics_job_attractiveness_mult
building_aristocrats_job_attractiveness_mult
building_bureaucrats_job_attractiveness_mult
building_capitalists_job_attractiveness_mult
building_clergymen_job_attractiveness_mult
building_clerks_job_attractiveness_mult
building_engineers_job_attractiveness_mult
building_farmers_job_attractiveness_mult
building_machinists_job_attractiveness_mult
building_officers_job_attractiveness_mult
building_peasants_job_attractiveness_mult
building_shopkeepers_job_attractiveness_mult
building_soldiers_job_attractiveness_mult
building_laborers_standard_of_living_add
building_academics_standard_of_living_add
building_aristocrats_standard_of_living_add
building_bureaucrats_standard_of_living_add
building_capitalists_standard_of_living_add
building_clergymen_standard_of_living_add
building_clerks_standard_of_living_add
building_farmers_standard_of_living_add
building_engineers_standard_of_living_add
building_machinists_standard_of_living_add
building_officers_standard_of_living_add
building_peasants_standard_of_living_add
building_shopkeepers_standard_of_living_add
building_soldiers_standard_of_living_add
building_slaves_standard_of_living_add
```

#### `02_modifier_types_rules.txt` -- 43 keys

```text
country_can_impose_same_lawgroup_governance_principles_in_power_bloc_bool
country_can_impose_same_lawgroup_distribution_of_power_in_power_bloc_bool
country_can_impose_same_lawgroup_church_and_state_in_power_bloc_bool
country_can_impose_same_lawgroup_education_system_in_power_bloc_bool
country_can_impose_same_lawgroup_policing_in_power_bloc_bool
country_can_impose_same_lawgroup_colonization_in_power_bloc_bool
country_can_impose_same_lawgroup_army_model_in_power_bloc_bool
country_can_impose_same_lawgroup_citizenship_in_power_bloc_bool
country_disallow_law_no_schools_bool
country_disallow_law_no_police_bool
country_disallow_law_no_colonial_affairs_bool
country_disallow_agitator_invites_bool
country_allow_multiple_alliances_bool
state_disallow_incorporation_bool
state_allow_assimilation_in_homeland_bool
state_allow_assimilation_without_presence_bool
state_allow_conversion_without_presence_bool
state_control_strait_bool
country_disallow_trade_outside_canton_bool
country_disallow_trade_outside_kyushu_bool
country_disallow_trade_bool
country_government_buildings_protected_bool
country_all_buildings_protected_bool
country_disable_investment_pool_bool
country_cannot_start_law_enactment_bool
country_cannot_cancel_law_enactment_bool
country_cannot_be_target_for_law_imposition_bool
country_cannot_enact_laws_bool
country_can_only_conscript_peasants_bool
country_must_have_movement_to_enact_laws_bool
country_disallow_aggressive_plays_bool
country_disable_nationalization_bool
country_disable_nationalization_without_compensation_bool
country_force_privatization_bool
country_block_government_reform_bool
country_forbid_monopoly_bool
country_disable_non_company_privatization_bool
country_can_form_construction_company_bool
country_foreign_collectivization_bool
country_allow_enacting_decrees_in_subject_bool
state_peasants_mass_migration_disallowed_bool
state_peasants_internal_migration_disallowed_bool
country_no_advantage_loss_from_lack_of_interest_bool
```

#### `03_modifier_types_script_only.txt` -- 32 keys

```text
character_battle_condition_dug_in_mult
character_battle_condition_charted_terrain_mult
character_battle_condition_rapid_advance_mult
character_battle_condition_camouflaged_mult
character_battle_condition_logistics_secured_mult
character_battle_condition_mud_mult
character_battle_condition_broken_supply_line_mult
character_battle_condition_exhausted_mult
character_battle_condition_lost_mult
character_battle_condition_surprise_maneuver_mult
character_battle_condition_aggressive_maneuver_mult
character_battle_condition_careful_maneuver_mult
character_battle_condition_blunder_mult
character_battle_condition_poor_visibility_mult
character_battle_condition_good_visibility_mult
character_battle_condition_rough_waters_mult
character_battle_condition_strong_winds_mult
character_battle_condition_death_from_below_mult
character_battle_condition_ramming_maneuver_mult
character_battle_condition_guerilla_ambush_mult
character_expedition_events_explorer_mult
country_expedition_events_explorer_mult
interest_group_in_government_attraction_mult
battle_total_combat_width_mult
state_trade_center_max_limit_add
battle_naval_condition_strong_winds_chance_mult
battle_naval_condition_calm_waters_chance_mult
battle_naval_condition_fog_chance_mult
battle_naval_condition_cyclone_chance_mult
battle_naval_condition_ice_chance_mult
battle_naval_condition_rough_waters_chance_mult
battle_naval_condition_tropical_storm_chance_mult
```

#### `04_label_modifier_types.txt` -- 24 keys

```text
unit_offense_flat_add
unit_offense_flat_mult
unit_defense_flat_add
unit_defense_flat_mult
unit_offense_elevated_add
unit_offense_elevated_mult
unit_defense_elevated_add
unit_defense_elevated_mult
unit_offense_forested_add
unit_offense_forested_mult
unit_defense_forested_add
unit_defense_forested_mult
unit_offense_hazardous_add
unit_offense_hazardous_mult
unit_defense_hazardous_add
unit_defense_hazardous_mult
unit_offense_developed_add
unit_offense_developed_mult
unit_defense_developed_add
unit_defense_developed_mult
unit_offense_water_add
unit_offense_water_mult
unit_defense_water_add
unit_defense_water_mult
```

#### `05_power_bloc_modifier_types.txt` -- 41 keys

```text
power_bloc_leader_can_make_subjects_bool
power_bloc_leader_can_force_state_religion_bool
power_bloc_leader_can_spread_culture_to_pb_bool
power_bloc_leader_can_regime_change_bool
power_bloc_leader_can_add_wargoal_bool
power_bloc_cohesion_add
power_bloc_cohesion_mult
power_bloc_cohesion_per_member_add
power_bloc_mandate_progress_per_great_power_member_add
power_bloc_mandate_progress_per_great_power_member_mult
power_bloc_mandate_progress_per_major_power_member_add
power_bloc_mandate_progress_per_major_power_member_mult
power_bloc_mandate_progress_per_minor_power_member_add
power_bloc_mandate_progress_per_minor_power_member_mult
power_bloc_mandate_progress_per_insignificant_power_member_add
power_bloc_mandate_progress_per_insignificant_power_member_mult
power_bloc_mandate_progress_per_unrecognized_major_power_member_add
power_bloc_mandate_progress_per_unrecognized_major_power_member_mult
power_bloc_mandate_progress_per_unrecognized_regional_power_member_add
power_bloc_mandate_progress_per_unrecognized_regional_power_member_mult
power_bloc_mandate_progress_per_unrecognized_power_member_add
power_bloc_mandate_progress_per_unrecognized_power_member_mult
power_bloc_invite_acceptance_add
power_bloc_invite_acceptance_great_power_add
power_bloc_invite_acceptance_major_power_add
power_bloc_invite_acceptance_minor_power_add
power_bloc_invite_acceptance_unrecognized_major_power_add
power_bloc_invite_acceptance_unrecognized_regional_power_add
power_bloc_disallow_embargo_bool
power_bloc_disallow_war_bool
power_bloc_customs_union_bool
power_bloc_leverage_generation_mult
power_bloc_mandate_progress_mult
power_bloc_target_sway_cost_mult
power_bloc_allow_wider_migration_area_bool
power_bloc_allow_port_access_bool
power_bloc_income_transfer_to_leader_factor
country_nationalization_cost_non_members_mult
country_leader_has_law_enactment_success_mult
country_join_power_bloc_member_in_defensive_plays_bool
country_join_power_bloc_member_in_plays_bool
```

#### `06_country_modifier_types.txt` -- 123 keys

```text
country_general_rank_impact_mult
country_admiral_rank_impact_mult
country_enactment_success_chance_law_technocracy_add
country_enactment_success_chance_law_public_schools_add
country_enactment_speed_law_technocracy_mult
country_enactment_speed_law_public_schools_mult
country_leverage_resistance_add
country_leverage_resistance_mult
country_leverage_generation_mult
country_leverage_generation_add
country_economic_dependence_on_overlord_add
country_electoral_confidence_impact_mult
country_lobby_leverage_generation_mult
country_treaty_leverage_generation_add
country_treaty_leverage_generation_mult
country_pact_leverage_generation_add
country_pact_leverage_generation_mult
country_institution_size_change_speed_institution_colonial_affairs_mult
country_institution_size_change_speed_institution_police_mult
country_institution_size_change_speed_institution_schools_mult
country_institution_cost_institution_colonial_affairs_mult
country_institution_cost_institution_police_mult
country_institution_cost_institution_schools_mult
country_institution_cost_institution_social_security_mult
country_institution_cost_institution_health_system_mult
country_institution_impact_institution_health_system_mult
country_institution_cost_institution_home_affairs_mult
country_support_independence_weekly_liberty_desire_add
country_port_connection_cost_mult
country_legitimacy_min_add
country_acceptance_primary_culture_add
country_acceptance_shared_heritage_trait_add
country_acceptance_shared_heritage_trait_group_add
country_acceptance_no_shared_heritage_trait_add
country_acceptance_shared_language_trait_add
country_acceptance_shared_language_trait_group_add
country_acceptance_no_shared_language_trait_add
country_acceptance_shared_tradition_trait_add
country_acceptance_no_shared_tradition_trait_add
country_acceptance_state_religion_add
country_acceptance_shared_religious_trait_add
country_acceptance_shared_religious_trait_group_add
country_acceptance_no_shared_religious_trait_add
country_acceptance_homeland_add
country_acceptance_not_homeland_add
country_migration_restrictiveness_add
country_allow_assimilation_violent_hostility_bool
country_allow_assimilation_cultural_erasure_bool
country_allow_assimilation_open_prejudice_bool
country_allow_assimilation_second_rate_citizen_bool
country_allow_assimilation_full_acceptance_bool
country_assimilation_violent_hostility_mult
country_assimilation_cultural_erasure_mult
country_assimilation_open_prejudice_mult
country_assimilation_second_rate_citizen_mult
country_assimilation_full_acceptance_mult
country_radicalism_increases_violent_hostility_mult
country_radicalism_increases_cultural_erasure_mult
country_radicalism_increases_open_prejudice_mult
country_radicalism_increases_second_rate_citizen_mult
country_radicalism_increases_full_acceptance_mult
country_loyalism_increases_violent_hostility_mult
country_loyalism_increases_cultural_erasure_mult
country_loyalism_increases_open_prejudice_mult
country_loyalism_increases_second_rate_citizen_mult
country_loyalism_increases_full_acceptance_mult
country_political_strength_violent_hostility_mult
country_political_strength_cultural_erasure_mult
country_political_strength_open_prejudice_mult
country_political_strength_second_rate_citizen_mult
country_political_strength_full_acceptance_mult
country_voting_power_violent_hostility_mult
country_voting_power_cultural_erasure_mult
country_voting_power_open_prejudice_mult
country_voting_power_second_rate_citizen_mult
country_voting_power_full_acceptance_mult
country_allow_voting_violent_hostility_bool
country_allow_voting_cultural_erasure_bool
country_allow_voting_open_prejudice_bool
country_allow_voting_second_rate_citizen_bool
country_allow_voting_full_acceptance_bool
country_qualification_growth_violent_hostility_mult
country_qualification_growth_cultural_erasure_mult
country_qualification_growth_open_prejudice_mult
country_qualification_growth_second_rate_citizen_mult
country_qualification_growth_full_acceptance_mult
country_wage_violent_hostility_mult
country_wage_cultural_erasure_mult
country_wage_open_prejudice_mult
country_wage_second_rate_citizen_mult
country_wage_full_acceptance_mult
country_standard_of_living_violent_hostility_add
country_standard_of_living_cultural_erasure_add
country_standard_of_living_open_prejudice_add
country_standard_of_living_second_rate_citizen_add
country_standard_of_living_full_acceptance_add
country_disallow_government_work_violent_hostility_bool
country_disallow_government_work_cultural_erasure_bool
country_disallow_government_work_open_prejudice_bool
country_disallow_government_work_second_rate_citizen_bool
country_disallow_government_work_full_acceptance_bool
country_disallow_military_work_violent_hostility_bool
country_disallow_military_work_cultural_erasure_bool
country_disallow_military_work_open_prejudice_bool
country_disallow_military_work_second_rate_citizen_bool
country_disallow_military_work_full_acceptance_bool
country_conversion_delta_threshold_add
country_assimilation_delta_threshold_add
country_allow_conversion_violent_hostility_bool
country_allow_conversion_cultural_erasure_bool
country_allow_conversion_open_prejudice_bool
country_allow_conversion_second_rate_citizen_bool
country_allow_conversion_full_acceptance_bool
country_enactment_success_chance_law_autocracy_add
country_enactment_speed_law_autocracy_mult
country_enactment_success_chance_law_oligarchy_add
country_enactment_speed_law_oligarchy_mult
country_enactment_success_chance_law_single_party_state_add
country_enactment_speed_law_single_party_state_mult
country_enactment_success_chance_law_anarchy_add
country_enactment_speed_law_anarchy_mult
country_financial_districts_buy_farms_likelihood
country_navy_goods_cost_mult
```

#### `07_description_modifier_types.txt` -- 4 keys

```text
country_higher_diplomatic_acceptance_same_religion_bool
country_reduced_liberty_desire_same_religion_bool
country_higher_leverage_from_economic_dependence_bool
power_bloc_allow_foreign_investment_lower_rank_bool
```

#### `08_movement_modifier_types.txt` -- 67 keys

```text
state_pop_support_movement_pro_slavery_add
state_pop_support_movement_pro_slavery_mult
state_pop_support_movement_anti_slavery_add
state_pop_support_movement_anti_slavery_mult
state_pop_support_movement_royalist_absolutist_add
state_pop_support_movement_royalist_absolutist_mult
state_pop_support_movement_royalist_constitutional_add
state_pop_support_movement_royalist_constitutional_mult
state_pop_support_movement_labor_add
state_pop_support_movement_labor_mult
state_pop_support_movement_socialist_add
state_pop_support_movement_socialist_mult
state_pop_support_movement_anarchist_add
state_pop_support_movement_anarchist_mult
state_pop_support_movement_communist_add
state_pop_support_movement_communist_mult
state_pop_support_movement_fascist_add
state_pop_support_movement_fascist_mult
state_pop_support_movement_corporatist_add
state_pop_support_movement_corporatist_mult
state_pop_support_movement_liberal_add
state_pop_support_movement_liberal_mult
state_pop_support_movement_radical_add
state_pop_support_movement_radical_mult
state_pop_support_movement_nihilist_add
state_pop_support_movement_nihilist_mult
state_pop_support_movement_positivist_add
state_pop_support_movement_positivist_mult
state_pop_support_movement_land_reform_add
state_pop_support_movement_land_reform_mult
state_pop_support_movement_feminist_add
state_pop_support_movement_feminist_mult
state_pop_support_movement_reactionary_add
state_pop_support_movement_reactionary_mult
state_pop_support_movement_modernizer_add
state_pop_support_movement_modernizer_mult
state_pop_support_movement_cultural_majority_add
state_pop_support_movement_cultural_majority_mult
state_pop_support_movement_cultural_minority_add
state_pop_support_movement_cultural_minority_mult
state_pop_support_movement_religious_majority_add
state_pop_support_movement_religious_majority_mult
state_pop_support_movement_religious_minority_add
state_pop_support_movement_religious_minority_mult
state_pop_support_movement_india_pan_national_add
state_pop_support_movement_india_pan_national_mult
state_pop_support_movement_utilitarian_add
state_pop_support_movement_utilitarian_mult
state_pop_support_movement_orleanist_add
state_pop_support_movement_orleanist_mult
state_pop_support_movement_bonapartist_add
state_pop_support_movement_bonapartist_mult
state_pop_support_movement_legitimist_add
state_pop_support_movement_legitimist_mult
state_pop_support_movement_german_national_add
state_pop_support_movement_german_national_mult
state_pop_support_movement_italian_national_add
state_pop_support_movement_italian_national_mult
state_pop_support_movement_yugoslav_national_add
state_pop_support_movement_yugoslav_national_mult
state_pop_support_movement_carlist_add
state_pop_support_movement_carlist_mult
state_pop_support_movement_miguelist_add
state_pop_support_movement_miguelist_mult
state_pop_support_movement_slave_revolt_add
state_pop_support_movement_slave_revolt_mult
state_free_state_pop_support_movement_anti_slavery_mult
```

#### `09_social_class_modifier_types.txt` -- 101 keys

```text
country_brahmins_acceptance_min_add
country_kshatriyas_acceptance_min_add
country_vaishyas_acceptance_min_add
country_strata_samurai_high_acceptance_min_add
country_strata_samurai_low_acceptance_min_add
country_strata_religious_acceptance_min_add
country_strata_commoners_peasants_acceptance_min_add
country_strata_commoners_townspeople_acceptance_min_add
country_strata_outcastes_acceptance_min_add
country_kshatriyas_acceptance_max_add
country_vaishyas_acceptance_max_add
country_shudras_acceptance_max_add
country_dalit_acceptance_max_add
country_strata_samurai_high_acceptance_max_add
country_strata_samurai_low_acceptance_max_add
country_strata_religious_acceptance_max_add
country_strata_commoners_peasants_acceptance_max_add
country_strata_commoners_townspeople_acceptance_max_add
country_strata_outcastes_acceptance_max_add
country_kshatriyas_cultural_acceptance_add
country_vaishyas_cultural_acceptance_add
country_shudras_cultural_acceptance_add
country_dalit_cultural_acceptance_add
country_strata_samurai_high_cultural_acceptance_add
country_strata_samurai_low_cultural_acceptance_add
country_strata_religious_cultural_acceptance_add
country_strata_commoners_peasants_cultural_acceptance_add
country_strata_commoners_townspeople_cultural_acceptance_add
country_strata_outcastes_cultural_acceptance_add
country_kshatriyas_cultural_acceptance_mult
country_vaishyas_cultural_acceptance_mult
country_shudras_cultural_acceptance_mult
country_dalit_cultural_acceptance_mult
country_strata_samurai_high_cultural_acceptance_mult
country_strata_samurai_low_cultural_acceptance_mult
country_strata_religious_cultural_acceptance_mult
country_strata_commoners_peasants_cultural_acceptance_mult
country_strata_commoners_townspeople_cultural_acceptance_mult
country_strata_outcastes_cultural_acceptance_mult
country_kshatriyas_education_access_add
country_vaishyas_education_access_add
country_shudras_education_access_add
country_dalit_education_access_add
country_strata_samurai_high_education_access_add
country_strata_samurai_low_education_access_add
country_strata_religious_education_access_add
country_strata_commoners_peasants_education_access_add
country_strata_commoners_townspeople_education_access_add
country_strata_outcastes_education_access_add
country_kshatriyas_education_access_mult
country_vaishyas_education_access_mult
country_shudras_education_access_mult
country_dalit_education_access_mult
country_strata_samurai_high_education_access_mult
country_strata_samurai_low_education_access_mult
country_strata_religious_education_access_mult
country_strata_commoners_peasants_education_access_mult
country_strata_commoners_townspeople_education_access_mult
country_strata_outcastes_education_access_mult
country_kshatriyas_qualification_growth_add
country_vaishyas_qualification_growth_add
country_shudras_qualification_growth_add
country_dalit_qualification_growth_add
country_strata_samurai_high_qualification_growth_add
country_strata_samurai_low_qualification_growth_add
country_strata_religious_qualification_growth_add
country_strata_commoners_peasants_qualification_growth_add
country_strata_commoners_townspeople_qualification_growth_add
country_strata_outcastes_qualification_growth_add
country_kshatriyas_qualification_growth_mult
country_vaishyas_qualification_growth_mult
country_shudras_qualification_growth_mult
country_dalit_qualification_growth_mult
country_strata_samurai_high_qualification_growth_mult
country_strata_samurai_low_qualification_growth_mult
country_strata_religious_qualification_growth_mult
country_strata_commoners_peasants_qualification_growth_mult
country_strata_commoners_townspeople_qualification_growth_mult
country_strata_outcastes_qualification_growth_mult
country_brahmins_qualification_growth_same_class_mult
country_kshatriyas_qualification_growth_same_class_mult
country_vaishyas_qualification_growth_same_class_mult
country_shudras_qualification_growth_same_class_mult
country_dalit_qualification_growth_same_class_mult
country_strata_samurai_high_qualification_growth_same_class_mult
country_strata_samurai_low_qualification_growth_same_class_mult
country_strata_religious_qualification_growth_same_class_mult
country_strata_commoners_peasants_qualification_growth_same_class_mult
country_strata_commoners_townspeople_qualification_growth_same_class_mult
country_strata_outcastes_qualification_growth_same_class_mult
country_brahmins_qualification_growth_other_class_mult
country_kshatriyas_qualification_growth_other_class_mult
country_vaishyas_qualification_growth_other_class_mult
country_shudras_qualification_growth_other_class_mult
country_dalit_qualification_growth_other_class_mult
country_strata_samurai_high_qualification_growth_other_class_mult
country_strata_samurai_low_qualification_growth_other_class_mult
country_strata_religious_qualification_growth_other_class_mult
country_strata_commoners_peasants_qualification_growth_other_class_mult
country_strata_commoners_townspeople_qualification_growth_other_class_mult
country_strata_outcastes_qualification_growth_other_class_mult
```

#### `10_country_cultural_acceptance_culture_modifier_types.txt` -- 317 keys

```text
country_scottish_cultural_acceptance_add
country_galician_cultural_acceptance_add
country_malay_cultural_acceptance_add
country_bornean_cultural_acceptance_add
country_sumatran_cultural_acceptance_add
country_balinese_cultural_acceptance_add
country_cajun_cultural_acceptance_add
country_assyrian_cultural_acceptance_add
country_circassian_cultural_acceptance_add
country_francoprovencal_cultural_acceptance_add
country_chechen_cultural_acceptance_add
country_karelian_cultural_acceptance_add
country_bashkir_cultural_acceptance_add
country_buryat_cultural_acceptance_add
country_mordvin_cultural_acceptance_add
country_chuvash_cultural_acceptance_add
country_mari_cultural_acceptance_add
country_udmurt_cultural_acceptance_add
country_mazanderani_cultural_acceptance_add
country_luri_cultural_acceptance_add
country_kho_cultural_acceptance_add
country_south_german_cultural_acceptance_add
country_ashkenazi_cultural_acceptance_add
country_dutch_cultural_acceptance_add
country_flemish_cultural_acceptance_add
country_wallonian_cultural_acceptance_add
country_boer_cultural_acceptance_add
country_alemannic_cultural_acceptance_add
country_swedish_cultural_acceptance_add
country_danish_cultural_acceptance_add
country_norwegian_cultural_acceptance_add
country_icelandic_cultural_acceptance_add
country_finnish_cultural_acceptance_add
country_sami_cultural_acceptance_add
country_british_cultural_acceptance_add
country_irish_cultural_acceptance_add
country_australian_cultural_acceptance_add
country_north_italian_cultural_acceptance_add
country_south_italian_cultural_acceptance_add
country_maltese_cultural_acceptance_add
country_basque_cultural_acceptance_add
country_spanish_cultural_acceptance_add
country_catalan_cultural_acceptance_add
country_portuguese_cultural_acceptance_add
country_french_cultural_acceptance_add
country_occitan_cultural_acceptance_add
country_breton_cultural_acceptance_add
country_croat_cultural_acceptance_add
country_serb_cultural_acceptance_add
country_bulgarian_cultural_acceptance_add
country_albanian_cultural_acceptance_add
country_slovene_cultural_acceptance_add
country_bosniak_cultural_acceptance_add
country_romanian_cultural_acceptance_add
country_hungarian_cultural_acceptance_add
country_polish_cultural_acceptance_add
country_lithuanian_cultural_acceptance_add
country_czech_cultural_acceptance_add
country_slovak_cultural_acceptance_add
country_russian_cultural_acceptance_add
country_byelorussian_cultural_acceptance_add
country_ukrainian_cultural_acceptance_add
country_ugrian_cultural_acceptance_add
country_latvian_cultural_acceptance_add
country_estonian_cultural_acceptance_add
country_greek_cultural_acceptance_add
country_georgian_cultural_acceptance_add
country_armenian_cultural_acceptance_add
country_sephardic_cultural_acceptance_add
country_turkish_cultural_acceptance_add
country_azerbaijani_cultural_acceptance_add
country_north_caucasian_cultural_acceptance_add
country_maghrebi_cultural_acceptance_add
country_misri_cultural_acceptance_add
country_mashriqi_cultural_acceptance_add
country_bedouin_cultural_acceptance_add
country_berber_cultural_acceptance_add
country_persian_cultural_acceptance_add
country_uzbek_cultural_acceptance_add
country_kazak_cultural_acceptance_add
country_kirgiz_cultural_acceptance_add
country_tajik_cultural_acceptance_add
country_uighur_cultural_acceptance_add
country_pashtun_cultural_acceptance_add
country_pathan_cultural_acceptance_add
country_baluchi_cultural_acceptance_add
country_hazara_cultural_acceptance_add
country_turkmen_cultural_acceptance_add
country_kurdish_cultural_acceptance_add
country_tatar_cultural_acceptance_add
country_mongol_cultural_acceptance_add
country_kalmyk_cultural_acceptance_add
country_siberian_cultural_acceptance_add
country_yakut_cultural_acceptance_add
country_tibetan_cultural_acceptance_add
country_assamese_cultural_acceptance_add
country_bengali_cultural_acceptance_add
country_bihari_cultural_acceptance_add
country_manipuri_cultural_acceptance_add
country_nepali_cultural_acceptance_add
country_oriya_cultural_acceptance_add
country_sinhala_cultural_acceptance_add
country_avadhi_cultural_acceptance_add
country_panjabi_cultural_acceptance_add
country_kashmiri_cultural_acceptance_add
country_gujarati_cultural_acceptance_add
country_marathi_cultural_acceptance_add
country_sindi_cultural_acceptance_add
country_rajput_cultural_acceptance_add
country_kannada_cultural_acceptance_add
country_malayalam_cultural_acceptance_add
country_tamil_cultural_acceptance_add
country_telegu_cultural_acceptance_add
country_vietnamese_cultural_acceptance_add
country_khmer_cultural_acceptance_add
country_batak_cultural_acceptance_add
country_dayak_cultural_acceptance_add
country_malagasy_cultural_acceptance_add
country_filipino_cultural_acceptance_add
country_moro_cultural_acceptance_add
country_javan_cultural_acceptance_add
country_moluccan_cultural_acceptance_add
country_champa_cultural_acceptance_add
country_thai_cultural_acceptance_add
country_mon_cultural_acceptance_add
country_khmu_cultural_acceptance_add
country_lao_cultural_acceptance_add
country_shan_cultural_acceptance_add
country_burmese_cultural_acceptance_add
country_kachin_cultural_acceptance_add
country_karen_cultural_acceptance_add
country_japanese_cultural_acceptance_add
country_manchu_cultural_acceptance_add
country_han_cultural_acceptance_add
country_korean_cultural_acceptance_add
country_ainu_cultural_acceptance_add
country_hakka_cultural_acceptance_add
country_miao_cultural_acceptance_add
country_min_cultural_acceptance_add
country_zhuang_cultural_acceptance_add
country_yi_cultural_acceptance_add
country_yue_cultural_acceptance_add
country_polynesian_cultural_acceptance_add
country_hawaiian_cultural_acceptance_add
country_melanesian_cultural_acceptance_add
country_micronesian_cultural_acceptance_add
country_maori_cultural_acceptance_add
country_yuanzhumin_cultural_acceptance_add
country_aborigine_cultural_acceptance_add
country_zapotec_cultural_acceptance_add
country_mayan_cultural_acceptance_add
country_nahua_cultural_acceptance_add
country_tarascan_cultural_acceptance_add
country_quechua_cultural_acceptance_add
country_guarani_cultural_acceptance_add
country_aimara_cultural_acceptance_add
country_amazonian_cultural_acceptance_add
country_patagonian_cultural_acceptance_add
country_guajiro_cultural_acceptance_add
country_tupinamba_cultural_acceptance_add
country_metis_cultural_acceptance_add
country_dakota_cultural_acceptance_add
country_cherokee_cultural_acceptance_add
country_muskogean_cultural_acceptance_add
country_pueblo_cultural_acceptance_add
country_inuit_cultural_acceptance_add
country_cree_cultural_acceptance_add
country_navajo_cultural_acceptance_add
country_athabaskan_cultural_acceptance_add
country_salish_cultural_acceptance_add
country_nez_perce_cultural_acceptance_add
country_siouan_cultural_acceptance_add
country_comanche_cultural_acceptance_add
country_algonquian_cultural_acceptance_add
country_iroquoian_cultural_acceptance_add
country_caddoan_cultural_acceptance_add
country_paiute_cultural_acceptance_add
country_hokan_cultural_acceptance_add
country_apache_cultural_acceptance_add
country_oodham_cultural_acceptance_add
country_mixtec_cultural_acceptance_add
country_muisca_cultural_acceptance_add
country_miskito_cultural_acceptance_add
country_cariban_cultural_acceptance_add
country_yankee_cultural_acceptance_add
country_dixie_cultural_acceptance_add
country_mexican_cultural_acceptance_add
country_central_american_cultural_acceptance_add
country_caribeno_cultural_acceptance_add
country_north_andean_cultural_acceptance_add
country_south_andean_cultural_acceptance_add
country_peruvian_cultural_acceptance_add
country_bolivian_cultural_acceptance_add
country_ecuadorian_cultural_acceptance_add
country_chilean_cultural_acceptance_add
country_venezuelan_cultural_acceptance_add
country_argentine_cultural_acceptance_add
country_uruguayan_cultural_acceptance_add
country_paraguayan_cultural_acceptance_add
country_colombian_cultural_acceptance_add
country_platinean_cultural_acceptance_add
country_brazilian_cultural_acceptance_add
country_sulista_cultural_acceptance_add
country_nordestino_cultural_acceptance_add
country_amazonic_cultural_acceptance_add
country_paulista_cultural_acceptance_add
country_afro_american_cultural_acceptance_add
country_afro_caribbean_cultural_acceptance_add
country_afro_caribeno_cultural_acceptance_add
country_afro_brazilian_cultural_acceptance_add
country_afro_antillean_cultural_acceptance_add
country_akan_cultural_acceptance_add
country_bambara_cultural_acceptance_add
country_bassa_cultural_acceptance_add
country_dyula_cultural_acceptance_add
country_edo_cultural_acceptance_add
country_ewe_cultural_acceptance_add
country_fon_cultural_acceptance_add
country_fulbe_cultural_acceptance_add
country_haratin_cultural_acceptance_add
country_hausa_cultural_acceptance_add
country_ibibio_cultural_acceptance_add
country_ibo_cultural_acceptance_add
country_kissi_cultural_acceptance_add
country_kru_cultural_acceptance_add
country_mande_cultural_acceptance_add
country_bidan_cultural_acceptance_add
country_mossi_cultural_acceptance_add
country_senufo_cultural_acceptance_add
country_songhai_cultural_acceptance_add
country_tiv_cultural_acceptance_add
country_tuareg_cultural_acceptance_add
country_wolof_cultural_acceptance_add
country_yoruba_cultural_acceptance_add
country_bakongo_cultural_acceptance_add
country_baguirmi_cultural_acceptance_add
country_fang_cultural_acceptance_add
country_kanuri_cultural_acceptance_add
country_luba_cultural_acceptance_add
country_lunda_cultural_acceptance_add
country_mongo_cultural_acceptance_add
country_sara_cultural_acceptance_add
country_teda_cultural_acceptance_add
country_equatorial_bantu_cultural_acceptance_add
country_fluvian_bantu_cultural_acceptance_add
country_nilotic_cultural_acceptance_add
country_amhara_cultural_acceptance_add
country_afar_cultural_acceptance_add
country_azande_cultural_acceptance_add
country_baganda_cultural_acceptance_add
country_beja_cultural_acceptance_add
country_dinka_cultural_acceptance_add
country_fur_cultural_acceptance_add
country_kikuyu_cultural_acceptance_add
country_luo_cultural_acceptance_add
country_maasai_cultural_acceptance_add
country_nuer_cultural_acceptance_add
country_nuba_cultural_acceptance_add
country_oromo_cultural_acceptance_add
country_ruanda_cultural_acceptance_add
country_rundi_cultural_acceptance_add
country_sidama_cultural_acceptance_add
country_somali_cultural_acceptance_add
country_sudanese_cultural_acceptance_add
country_sukuma_cultural_acceptance_add
country_deccani_cultural_acceptance_add
country_hindustani_cultural_acceptance_add
country_lushai_cultural_acceptance_add
country_bundeli_cultural_acceptance_add
country_pahari_cultural_acceptance_add
country_gondi_cultural_acceptance_add
country_bageli_cultural_acceptance_add
country_chhattisgarhi_cultural_acceptance_add
country_naga_cultural_acceptance_add
country_swahili_cultural_acceptance_add
country_tigray_cultural_acceptance_add
country_nyamwezi_cultural_acceptance_add
country_lacustrine_bantu_cultural_acceptance_add
country_chewa_cultural_acceptance_add
country_herero_cultural_acceptance_add
country_khoisan_cultural_acceptance_add
country_lomwe_cultural_acceptance_add
country_makua_cultural_acceptance_add
country_nguni_cultural_acceptance_add
country_ovimbundu_cultural_acceptance_add
country_sena_cultural_acceptance_add
country_shona_cultural_acceptance_add
country_sotho_cultural_acceptance_add
country_tonga_cultural_acceptance_add
country_tswana_cultural_acceptance_add
country_xhosa_cultural_acceptance_add
country_yao_cultural_acceptance_add
country_zulu_cultural_acceptance_add
country_kavango_bantu_cultural_acceptance_add
country_anglo_canadian_cultural_acceptance_add
country_franco_canadian_cultural_acceptance_add
country_sorb_cultural_acceptance_add
country_tuvan_cultural_acceptance_add
country_corsican_cultural_acceptance_add
country_yemenite_cultural_acceptance_add
country_welsh_cultural_acceptance_add
country_north_german_cultural_acceptance_add
country_szekely_cultural_acceptance_add
country_east_german_cultural_acceptance_add
country_griqua_cultural_acceptance_add
country_promethean_cultural_acceptance_add
country_asturleonese_cultural_acceptance_add
country_aragonese_cultural_acceptance_add
country_scottish_gaelic_cultural_acceptance_add
country_filipino_mestizo_cultural_acceptance_add
country_filipino_hispanophone_cultural_acceptance_add
country_iberian_cultural_acceptance_add
country_tagalog_cultural_acceptance_add
country_ilocano_cultural_acceptance_add
country_visayan_cultural_acceptance_add
country_lumad_cultural_acceptance_add
country_ryukyuan_cultural_acceptance_add
```

#### `11_country_fervor_taget_culture_modifier_types.txt` -- 317 keys

```text
country_fervor_target_scottish_add
country_fervor_target_galician_add
country_fervor_target_malay_add
country_fervor_target_bornean_add
country_fervor_target_sumatran_add
country_fervor_target_balinese_add
country_fervor_target_cajun_add
country_fervor_target_assyrian_add
country_fervor_target_circassian_add
country_fervor_target_francoprovencal_add
country_fervor_target_chechen_add
country_fervor_target_karelian_add
country_fervor_target_bashkir_add
country_fervor_target_buryat_add
country_fervor_target_mordvin_add
country_fervor_target_chuvash_add
country_fervor_target_mari_add
country_fervor_target_udmurt_add
country_fervor_target_mazanderani_add
country_fervor_target_luri_add
country_fervor_target_kho_add
country_fervor_target_south_german_add
country_fervor_target_ashkenazi_add
country_fervor_target_dutch_add
country_fervor_target_flemish_add
country_fervor_target_wallonian_add
country_fervor_target_boer_add
country_fervor_target_alemannic_add
country_fervor_target_swedish_add
country_fervor_target_danish_add
country_fervor_target_norwegian_add
country_fervor_target_icelandic_add
country_fervor_target_finnish_add
country_fervor_target_sami_add
country_fervor_target_british_add
country_fervor_target_irish_add
country_fervor_target_australian_add
country_fervor_target_north_italian_add
country_fervor_target_south_italian_add
country_fervor_target_maltese_add
country_fervor_target_basque_add
country_fervor_target_spanish_add
country_fervor_target_catalan_add
country_fervor_target_portuguese_add
country_fervor_target_french_add
country_fervor_target_occitan_add
country_fervor_target_breton_add
country_fervor_target_croat_add
country_fervor_target_serb_add
country_fervor_target_bulgarian_add
country_fervor_target_albanian_add
country_fervor_target_slovene_add
country_fervor_target_bosniak_add
country_fervor_target_romanian_add
country_fervor_target_hungarian_add
country_fervor_target_polish_add
country_fervor_target_lithuanian_add
country_fervor_target_czech_add
country_fervor_target_slovak_add
country_fervor_target_russian_add
country_fervor_target_byelorussian_add
country_fervor_target_ukrainian_add
country_fervor_target_ugrian_add
country_fervor_target_latvian_add
country_fervor_target_estonian_add
country_fervor_target_greek_add
country_fervor_target_georgian_add
country_fervor_target_armenian_add
country_fervor_target_sephardic_add
country_fervor_target_turkish_add
country_fervor_target_azerbaijani_add
country_fervor_target_north_caucasian_add
country_fervor_target_maghrebi_add
country_fervor_target_misri_add
country_fervor_target_mashriqi_add
country_fervor_target_bedouin_add
country_fervor_target_berber_add
country_fervor_target_persian_add
country_fervor_target_uzbek_add
country_fervor_target_kazak_add
country_fervor_target_kirgiz_add
country_fervor_target_tajik_add
country_fervor_target_uighur_add
country_fervor_target_pashtun_add
country_fervor_target_pathan_add
country_fervor_target_baluchi_add
country_fervor_target_hazara_add
country_fervor_target_turkmen_add
country_fervor_target_kurdish_add
country_fervor_target_tatar_add
country_fervor_target_mongol_add
country_fervor_target_kalmyk_add
country_fervor_target_siberian_add
country_fervor_target_yakut_add
country_fervor_target_tibetan_add
country_fervor_target_assamese_add
country_fervor_target_bengali_add
country_fervor_target_bihari_add
country_fervor_target_manipuri_add
country_fervor_target_nepali_add
country_fervor_target_oriya_add
country_fervor_target_sinhala_add
country_fervor_target_avadhi_add
country_fervor_target_panjabi_add
country_fervor_target_kashmiri_add
country_fervor_target_gujarati_add
country_fervor_target_marathi_add
country_fervor_target_sindi_add
country_fervor_target_rajput_add
country_fervor_target_kannada_add
country_fervor_target_malayalam_add
country_fervor_target_tamil_add
country_fervor_target_telegu_add
country_fervor_target_vietnamese_add
country_fervor_target_khmer_add
country_fervor_target_batak_add
country_fervor_target_dayak_add
country_fervor_target_malagasy_add
country_fervor_target_filipino_add
country_fervor_target_moro_add
country_fervor_target_javan_add
country_fervor_target_moluccan_add
country_fervor_target_champa_add
country_fervor_target_thai_add
country_fervor_target_mon_add
country_fervor_target_khmu_add
country_fervor_target_lao_add
country_fervor_target_shan_add
country_fervor_target_burmese_add
country_fervor_target_kachin_add
country_fervor_target_karen_add
country_fervor_target_japanese_add
country_fervor_target_manchu_add
country_fervor_target_han_add
country_fervor_target_korean_add
country_fervor_target_ainu_add
country_fervor_target_hakka_add
country_fervor_target_miao_add
country_fervor_target_min_add
country_fervor_target_zhuang_add
country_fervor_target_yi_add
country_fervor_target_yue_add
country_fervor_target_polynesian_add
country_fervor_target_hawaiian_add
country_fervor_target_melanesian_add
country_fervor_target_micronesian_add
country_fervor_target_maori_add
country_fervor_target_yuanzhumin_add
country_fervor_target_aborigine_add
country_fervor_target_zapotec_add
country_fervor_target_mayan_add
country_fervor_target_nahua_add
country_fervor_target_tarascan_add
country_fervor_target_quechua_add
country_fervor_target_guarani_add
country_fervor_target_aimara_add
country_fervor_target_amazonian_add
country_fervor_target_patagonian_add
country_fervor_target_guajiro_add
country_fervor_target_tupinamba_add
country_fervor_target_metis_add
country_fervor_target_dakota_add
country_fervor_target_cherokee_add
country_fervor_target_muskogean_add
country_fervor_target_pueblo_add
country_fervor_target_inuit_add
country_fervor_target_cree_add
country_fervor_target_navajo_add
country_fervor_target_athabaskan_add
country_fervor_target_salish_add
country_fervor_target_nez_perce_add
country_fervor_target_siouan_add
country_fervor_target_comanche_add
country_fervor_target_algonquian_add
country_fervor_target_iroquoian_add
country_fervor_target_caddoan_add
country_fervor_target_paiute_add
country_fervor_target_hokan_add
country_fervor_target_apache_add
country_fervor_target_oodham_add
country_fervor_target_mixtec_add
country_fervor_target_muisca_add
country_fervor_target_miskito_add
country_fervor_target_cariban_add
country_fervor_target_yankee_add
country_fervor_target_dixie_add
country_fervor_target_mexican_add
country_fervor_target_central_american_add
country_fervor_target_caribeno_add
country_fervor_target_north_andean_add
country_fervor_target_south_andean_add
country_fervor_target_peruvian_add
country_fervor_target_bolivian_add
country_fervor_target_ecuadorian_add
country_fervor_target_chilean_add
country_fervor_target_venezuelan_add
country_fervor_target_argentine_add
country_fervor_target_uruguayan_add
country_fervor_target_paraguayan_add
country_fervor_target_colombian_add
country_fervor_target_platinean_add
country_fervor_target_brazilian_add
country_fervor_target_sulista_add
country_fervor_target_nordestino_add
country_fervor_target_amazonic_add
country_fervor_target_paulista_add
country_fervor_target_afro_american_add
country_fervor_target_afro_caribbean_add
country_fervor_target_afro_caribeno_add
country_fervor_target_afro_brazilian_add
country_fervor_target_afro_antillean_add
country_fervor_target_akan_add
country_fervor_target_bambara_add
country_fervor_target_bassa_add
country_fervor_target_dyula_add
country_fervor_target_edo_add
country_fervor_target_ewe_add
country_fervor_target_fon_add
country_fervor_target_fulbe_add
country_fervor_target_haratin_add
country_fervor_target_hausa_add
country_fervor_target_ibibio_add
country_fervor_target_ibo_add
country_fervor_target_kissi_add
country_fervor_target_kru_add
country_fervor_target_mande_add
country_fervor_target_bidan_add
country_fervor_target_mossi_add
country_fervor_target_senufo_add
country_fervor_target_songhai_add
country_fervor_target_tiv_add
country_fervor_target_tuareg_add
country_fervor_target_wolof_add
country_fervor_target_yoruba_add
country_fervor_target_bakongo_add
country_fervor_target_baguirmi_add
country_fervor_target_fang_add
country_fervor_target_kanuri_add
country_fervor_target_luba_add
country_fervor_target_lunda_add
country_fervor_target_mongo_add
country_fervor_target_sara_add
country_fervor_target_teda_add
country_fervor_target_equatorial_bantu_add
country_fervor_target_fluvian_bantu_add
country_fervor_target_nilotic_add
country_fervor_target_amhara_add
country_fervor_target_afar_add
country_fervor_target_azande_add
country_fervor_target_baganda_add
country_fervor_target_beja_add
country_fervor_target_dinka_add
country_fervor_target_fur_add
country_fervor_target_kikuyu_add
country_fervor_target_luo_add
country_fervor_target_maasai_add
country_fervor_target_nuer_add
country_fervor_target_nuba_add
country_fervor_target_oromo_add
country_fervor_target_ruanda_add
country_fervor_target_rundi_add
country_fervor_target_sidama_add
country_fervor_target_somali_add
country_fervor_target_sudanese_add
country_fervor_target_sukuma_add
country_fervor_target_deccani_add
country_fervor_target_hindustani_add
country_fervor_target_lushai_add
country_fervor_target_bundeli_add
country_fervor_target_pahari_add
country_fervor_target_gondi_add
country_fervor_target_bageli_add
country_fervor_target_chhattisgarhi_add
country_fervor_target_naga_add
country_fervor_target_swahili_add
country_fervor_target_tigray_add
country_fervor_target_nyamwezi_add
country_fervor_target_lacustrine_bantu_add
country_fervor_target_chewa_add
country_fervor_target_herero_add
country_fervor_target_khoisan_add
country_fervor_target_lomwe_add
country_fervor_target_makua_add
country_fervor_target_nguni_add
country_fervor_target_ovimbundu_add
country_fervor_target_sena_add
country_fervor_target_shona_add
country_fervor_target_sotho_add
country_fervor_target_tonga_add
country_fervor_target_tswana_add
country_fervor_target_xhosa_add
country_fervor_target_yao_add
country_fervor_target_zulu_add
country_fervor_target_kavango_bantu_add
country_fervor_target_anglo_canadian_add
country_fervor_target_franco_canadian_add
country_fervor_target_sorb_add
country_fervor_target_tuvan_add
country_fervor_target_corsican_add
country_fervor_target_yemenite_add
country_fervor_target_welsh_add
country_fervor_target_north_german_add
country_fervor_target_szekely_add
country_fervor_target_east_german_add
country_fervor_target_griqua_add
country_fervor_target_promethean_add
country_fervor_target_asturleonese_add
country_fervor_target_aragonese_add
country_fervor_target_scottish_gaelic_add
country_fervor_target_filipino_mestizo_add
country_fervor_target_filipino_hispanophone_add
country_fervor_target_iberian_add
country_fervor_target_tagalog_add
country_fervor_target_ilocano_add
country_fervor_target_visayan_add
country_fervor_target_lumad_add
country_fervor_target_ryukyuan_add
```

#### `12_ip4_script_modifiers.txt` -- 12 keys

```text
country_yankee_and_dixie_cultures_obsessed_with_guns
country_forbid_electoral_fraud_bool
country_lobby_support
country_cannot_be_subjugated_bool
country_cannot_join_power_bloc_bool
character_coup_strength_mult
character_coup_strength_add
country_coup_resistance_mult
country_coup_resistance_add
country_frankenstein_company_bool
country_two_spains_liberal_drift_add
country_two_spains_conservative_drift_add
```

#### `13_ep2_script_modifiers.txt` -- 3 keys

```text
country_limit_officers_qualifications_to_upper_strata
country_je_korea_action_cost
country_electoral_confidence_over_time
```

#### `99_todo_sort_into_other_files.txt` -- 478 keys

```text
state_catholic_standard_of_living_add
state_protestant_standard_of_living_add
state_orthodox_standard_of_living_add
state_oriental_orthodox_standard_of_living_add
state_sunni_standard_of_living_add
state_shiite_standard_of_living_add
state_ibadi_standard_of_living_add
state_jewish_standard_of_living_add
state_mahayana_standard_of_living_add
state_gelugpa_standard_of_living_add
state_theravada_standard_of_living_add
state_confucian_standard_of_living_add
state_hindu_standard_of_living_add
state_shinto_standard_of_living_add
state_sikh_standard_of_living_add
state_animist_standard_of_living_add
state_atheist_standard_of_living_add
state_scottish_standard_of_living_add
state_galician_standard_of_living_add
state_malay_standard_of_living_add
state_bornean_standard_of_living_add
state_sumatran_standard_of_living_add
state_balinese_standard_of_living_add
state_cajun_standard_of_living_add
state_assyrian_standard_of_living_add
state_circassian_standard_of_living_add
state_francoprovencal_standard_of_living_add
state_chechen_standard_of_living_add
state_karelian_standard_of_living_add
state_bashkir_standard_of_living_add
state_buryat_standard_of_living_add
state_mordvin_standard_of_living_add
state_chuvash_standard_of_living_add
state_mari_standard_of_living_add
state_udmurt_standard_of_living_add
state_mazanderani_standard_of_living_add
state_luri_standard_of_living_add
state_kho_standard_of_living_add
state_south_german_standard_of_living_add
state_ashkenazi_standard_of_living_add
state_dutch_standard_of_living_add
state_flemish_standard_of_living_add
state_wallonian_standard_of_living_add
state_boer_standard_of_living_add
state_alemannic_standard_of_living_add
state_swedish_standard_of_living_add
state_danish_standard_of_living_add
state_norwegian_standard_of_living_add
state_icelandic_standard_of_living_add
state_finnish_standard_of_living_add
state_sami_standard_of_living_add
state_british_standard_of_living_add
state_irish_standard_of_living_add
state_australian_standard_of_living_add
state_north_italian_standard_of_living_add
state_south_italian_standard_of_living_add
state_maltese_standard_of_living_add
state_basque_standard_of_living_add
state_spanish_standard_of_living_add
state_catalan_standard_of_living_add
state_portuguese_standard_of_living_add
state_french_standard_of_living_add
state_occitan_standard_of_living_add
state_breton_standard_of_living_add
state_croat_standard_of_living_add
state_serb_standard_of_living_add
state_bulgarian_standard_of_living_add
state_albanian_standard_of_living_add
state_slovene_standard_of_living_add
state_bosniak_standard_of_living_add
state_romanian_standard_of_living_add
state_hungarian_standard_of_living_add
state_polish_standard_of_living_add
state_lithuanian_standard_of_living_add
state_czech_standard_of_living_add
state_slovak_standard_of_living_add
state_russian_standard_of_living_add
state_byelorussian_standard_of_living_add
state_ukrainian_standard_of_living_add
state_ugrian_standard_of_living_add
state_latvian_standard_of_living_add
state_estonian_standard_of_living_add
state_greek_standard_of_living_add
state_georgian_standard_of_living_add
state_armenian_standard_of_living_add
state_sephardic_standard_of_living_add
state_turkish_standard_of_living_add
state_azerbaijani_standard_of_living_add
state_north_caucasian_standard_of_living_add
state_maghrebi_standard_of_living_add
state_misri_standard_of_living_add
state_mashriqi_standard_of_living_add
state_bedouin_standard_of_living_add
state_berber_standard_of_living_add
state_persian_standard_of_living_add
state_uzbek_standard_of_living_add
state_kazak_standard_of_living_add
state_kirgiz_standard_of_living_add
state_tajik_standard_of_living_add
state_uighur_standard_of_living_add
state_pashtun_standard_of_living_add
state_pathan_standard_of_living_add
state_baluchi_standard_of_living_add
state_hazara_standard_of_living_add
state_turkmen_standard_of_living_add
state_kurdish_standard_of_living_add
state_tatar_standard_of_living_add
state_mongol_standard_of_living_add
state_kalmyk_standard_of_living_add
state_siberian_standard_of_living_add
state_yakut_standard_of_living_add
state_tibetan_standard_of_living_add
state_assamese_standard_of_living_add
state_bengali_standard_of_living_add
state_bihari_standard_of_living_add
state_manipuri_standard_of_living_add
state_nepali_standard_of_living_add
state_oriya_standard_of_living_add
state_sinhala_standard_of_living_add
state_avadhi_standard_of_living_add
state_panjabi_standard_of_living_add
state_kashmiri_standard_of_living_add
state_gujarati_standard_of_living_add
state_marathi_standard_of_living_add
state_sindi_standard_of_living_add
state_rajput_standard_of_living_add
state_kannada_standard_of_living_add
state_malayalam_standard_of_living_add
state_tamil_standard_of_living_add
state_telegu_standard_of_living_add
state_vietnamese_standard_of_living_add
state_khmer_standard_of_living_add
state_batak_standard_of_living_add
state_dayak_standard_of_living_add
state_malagasy_standard_of_living_add
state_filipino_standard_of_living_add
state_moro_standard_of_living_add
state_javan_standard_of_living_add
state_moluccan_standard_of_living_add
state_champa_standard_of_living_add
state_thai_standard_of_living_add
state_mon_standard_of_living_add
state_khmu_standard_of_living_add
state_lao_standard_of_living_add
state_shan_standard_of_living_add
state_burmese_standard_of_living_add
state_kachin_standard_of_living_add
state_karen_standard_of_living_add
state_japanese_standard_of_living_add
state_manchu_standard_of_living_add
state_han_standard_of_living_add
state_korean_standard_of_living_add
state_ainu_standard_of_living_add
state_hakka_standard_of_living_add
state_miao_standard_of_living_add
state_min_standard_of_living_add
state_zhuang_standard_of_living_add
state_yi_standard_of_living_add
state_yue_standard_of_living_add
state_polynesian_standard_of_living_add
state_hawaiian_standard_of_living_add
state_melanesian_standard_of_living_add
state_micronesian_standard_of_living_add
state_maori_standard_of_living_add
state_yuanzhumin_standard_of_living_add
state_aborigine_standard_of_living_add
state_zapotec_standard_of_living_add
state_mayan_standard_of_living_add
state_nahua_standard_of_living_add
state_tarascan_standard_of_living_add
state_quechua_standard_of_living_add
state_guarani_standard_of_living_add
state_aimara_standard_of_living_add
state_amazonian_standard_of_living_add
state_patagonian_standard_of_living_add
state_guajiro_standard_of_living_add
state_tupinamba_standard_of_living_add
state_metis_standard_of_living_add
state_dakota_standard_of_living_add
state_cherokee_standard_of_living_add
state_muskogean_standard_of_living_add
state_pueblo_standard_of_living_add
state_inuit_standard_of_living_add
state_cree_standard_of_living_add
state_navajo_standard_of_living_add
state_athabaskan_standard_of_living_add
state_salish_standard_of_living_add
state_nez_perce_standard_of_living_add
state_siouan_standard_of_living_add
state_comanche_standard_of_living_add
state_algonquian_standard_of_living_add
state_iroquoian_standard_of_living_add
state_caddoan_standard_of_living_add
state_paiute_standard_of_living_add
state_hokan_standard_of_living_add
state_apache_standard_of_living_add
state_oodham_standard_of_living_add
state_mixtec_standard_of_living_add
state_muisca_standard_of_living_add
state_miskito_standard_of_living_add
state_cariban_standard_of_living_add
state_yankee_standard_of_living_add
state_dixie_standard_of_living_add
state_mexican_standard_of_living_add
state_central_american_standard_of_living_add
state_caribeno_standard_of_living_add
state_north_andean_standard_of_living_add
state_south_andean_standard_of_living_add
state_peruvian_standard_of_living_add
state_bolivian_standard_of_living_add
state_ecuadorian_standard_of_living_add
state_chilean_standard_of_living_add
state_venezuelan_standard_of_living_add
state_argentine_standard_of_living_add
state_uruguayan_standard_of_living_add
state_paraguayan_standard_of_living_add
state_colombian_standard_of_living_add
state_platinean_standard_of_living_add
state_brazilian_standard_of_living_add
state_sulista_standard_of_living_add
state_nordestino_standard_of_living_add
state_amazonic_standard_of_living_add
state_paulista_standard_of_living_add
state_afro_american_standard_of_living_add
state_afro_caribbean_standard_of_living_add
state_afro_caribeno_standard_of_living_add
state_afro_brazilian_standard_of_living_add
state_afro_antillean_standard_of_living_add
state_akan_standard_of_living_add
state_bambara_standard_of_living_add
state_bassa_standard_of_living_add
state_dyula_standard_of_living_add
state_edo_standard_of_living_add
state_ewe_standard_of_living_add
state_fon_standard_of_living_add
state_fulbe_standard_of_living_add
state_haratin_standard_of_living_add
state_hausa_standard_of_living_add
state_ibibio_standard_of_living_add
state_ibo_standard_of_living_add
state_kissi_standard_of_living_add
state_kru_standard_of_living_add
state_mande_standard_of_living_add
state_bidan_standard_of_living_add
state_mossi_standard_of_living_add
state_senufo_standard_of_living_add
state_songhai_standard_of_living_add
state_tiv_standard_of_living_add
state_tuareg_standard_of_living_add
state_wolof_standard_of_living_add
state_yoruba_standard_of_living_add
state_bakongo_standard_of_living_add
state_baguirmi_standard_of_living_add
state_fang_standard_of_living_add
state_kanuri_standard_of_living_add
state_luba_standard_of_living_add
state_lunda_standard_of_living_add
state_mongo_standard_of_living_add
state_sara_standard_of_living_add
state_teda_standard_of_living_add
state_equatorial_bantu_standard_of_living_add
state_fluvian_bantu_standard_of_living_add
state_nilotic_standard_of_living_add
state_amhara_standard_of_living_add
state_afar_standard_of_living_add
state_azande_standard_of_living_add
state_baganda_standard_of_living_add
state_beja_standard_of_living_add
state_dinka_standard_of_living_add
state_fur_standard_of_living_add
state_kikuyu_standard_of_living_add
state_luo_standard_of_living_add
state_maasai_standard_of_living_add
state_nuer_standard_of_living_add
state_nuba_standard_of_living_add
state_oromo_standard_of_living_add
state_ruanda_standard_of_living_add
state_rundi_standard_of_living_add
state_sidama_standard_of_living_add
state_somali_standard_of_living_add
state_sudanese_standard_of_living_add
state_sukuma_standard_of_living_add
state_deccani_standard_of_living_add
state_hindustani_standard_of_living_add
state_lushai_standard_of_living_add
state_bundeli_standard_of_living_add
state_pahari_standard_of_living_add
state_gondi_standard_of_living_add
state_bageli_standard_of_living_add
state_chhattisgarhi_standard_of_living_add
state_naga_standard_of_living_add
state_swahili_standard_of_living_add
state_tigray_standard_of_living_add
state_nyamwezi_standard_of_living_add
state_lacustrine_bantu_standard_of_living_add
state_chewa_standard_of_living_add
state_herero_standard_of_living_add
state_khoisan_standard_of_living_add
state_lomwe_standard_of_living_add
state_makua_standard_of_living_add
state_nguni_standard_of_living_add
state_ovimbundu_standard_of_living_add
state_sena_standard_of_living_add
state_shona_standard_of_living_add
state_sotho_standard_of_living_add
state_tonga_standard_of_living_add
state_tswana_standard_of_living_add
state_xhosa_standard_of_living_add
state_yao_standard_of_living_add
state_zulu_standard_of_living_add
state_kavango_bantu_standard_of_living_add
state_anglo_canadian_standard_of_living_add
state_franco_canadian_standard_of_living_add
state_sorb_standard_of_living_add
state_tuvan_standard_of_living_add
state_corsican_standard_of_living_add
state_yemenite_standard_of_living_add
state_welsh_standard_of_living_add
state_north_german_standard_of_living_add
country_institution_colonial_affairs_max_investment_add
country_institution_social_security_max_investment_add
country_institution_workplace_safety_max_investment_add
country_institution_schools_max_investment_add
country_institution_police_max_investment_add
country_institution_health_system_max_investment_add
country_institution_home_affairs_max_investment_add
country_academics_pol_str_mult
country_soldiers_pol_str_mult
country_clerks_pol_str_mult
state_szekely_standard_of_living_add
state_east_german_standard_of_living_add
state_griqua_standard_of_living_add
state_promethean_standard_of_living_add
state_asturleonese_standard_of_living_add
state_aragonese_standard_of_living_add
state_scottish_gaelic_standard_of_living_add
state_filipino_mestizo_standard_of_living_add
state_filipino_hispanophone_standard_of_living_add
state_iberian_standard_of_living_add
state_tagalog_standard_of_living_add
state_ilocano_standard_of_living_add
state_visayan_standard_of_living_add
state_lumad_standard_of_living_add
state_ryukyuan_standard_of_living_add
state_academics_mortality_mult
building_employment_academics_add
building_academics_mortality_mult
country_aristocrats_pol_str_mult
country_aristocrats_voting_power_add
state_aristocrats_mortality_mult
building_employment_aristocrats_add
state_aristocrats_investment_pool_contribution_add
state_aristocrats_investment_pool_efficiency_mult
building_aristocrats_shares_add
country_bureaucrats_pol_str_mult
building_employment_bureaucrats_add
building_bureaucrats_shares_add
state_bureaucrats_investment_pool_contribution_add
state_bureaucrats_investment_pool_efficiency_mult
country_capitalists_pol_str_mult
country_capitalists_voting_power_add
building_employment_capitalists_add
state_capitalists_investment_pool_contribution_add
state_capitalists_investment_pool_efficiency_mult
building_capitalists_shares_add
country_clergymen_pol_str_mult
country_clergymen_voting_power_add
building_employment_clergymen_add
building_clergymen_shares_add
building_employment_clerks_add
country_engineers_pol_str_mult
building_employment_engineers_add
state_engineers_investment_pool_contribution_add
state_engineers_investment_pool_efficiency_mult
building_engineers_shares_add
building_engineers_mortality_mult
country_farmers_pol_str_mult
country_farmers_voting_power_add
state_farmers_mortality_mult
building_employment_farmers_add
state_farmers_investment_pool_contribution_add
state_farmers_investment_pool_efficiency_mult
state_clergymen_investment_pool_contribution_add
state_clergymen_investment_pool_efficiency_mult
country_laborers_pol_str_mult
state_laborers_mortality_mult
building_employment_laborers_add
building_employment_slaves_add
state_laborers_investment_pool_contribution_add
state_laborers_investment_pool_efficiency_mult
building_laborers_shares_add
building_laborers_mortality_mult
building_slaves_mortality_mult
country_machinists_pol_str_mult
state_machinists_mortality_mult
building_employment_machinists_add
state_machinists_investment_pool_contribution_add
state_machinists_investment_pool_efficiency_mult
building_machinists_shares_add
building_machinists_mortality_mult
country_officers_pol_str_mult
country_officers_voting_power_add
building_employment_officers_add
state_officers_investment_pool_contribution_add
state_officers_investment_pool_efficiency_mult
building_officers_shares_add
state_soldiers_investment_pool_contribution_add
state_soldiers_investment_pool_efficiency_mult
building_soldiers_shares_add
country_peasants_pol_str_mult
state_peasants_mortality_mult
building_employment_peasants_add
country_shopkeepers_pol_str_mult
building_employment_shopkeepers_add
state_shopkeepers_investment_pool_contribution_add
state_shopkeepers_investment_pool_efficiency_mult
building_shopkeepers_shares_add
building_clerks_shares_add
building_academics_shares_add
state_clerks_investment_pool_contribution_add
state_clerks_investment_pool_efficiency_mult
state_academics_investment_pool_contribution_add
state_academics_investment_pool_efficiency_mult
state_slaves_mortality_mult
state_soldiers_mortality_mult
building_employment_soldiers_add
building_group_bg_manufacturing_unincorporated_throughput_add
building_group_bg_light_industry_throughput_add
building_group_bg_light_industry_laborers_mortality_mult
building_group_bg_light_industry_machinists_mortality_mult
building_group_bg_heavy_industry_throughput_add
building_group_bg_heavy_industry_mortality_mult
building_group_bg_heavy_industry_engineers_mortality_mult
building_group_bg_heavy_industry_laborers_mortality_mult
building_group_bg_heavy_industry_machinists_mortality_mult
building_group_bg_military_industry_throughput_add
building_group_bg_military_industry_mortality_mult
building_group_bg_military_industry_engineers_mortality_mult
building_group_bg_military_industry_laborers_mortality_mult
building_group_bg_military_industry_machinists_mortality_mult
building_group_bg_plantations_unincorporated_throughput_add
building_group_bg_mining_unincorporated_throughput_add
building_group_bg_logging_unincorporated_throughput_add
building_group_bg_rubber_throughput_add
building_group_bg_rubber_unincorporated_throughput_add
building_group_bg_whaling_laborers_mortality_mult
building_group_bg_whaling_machinists_mortality_mult
building_group_bg_fishing_engineers_mortality_mult
building_group_bg_fishing_laborers_mortality_mult
building_group_bg_fishing_machinists_mortality_mult
building_group_bg_oil_extraction_engineers_mortality_mult
building_group_bg_oil_extraction_laborers_mortality_mult
building_group_bg_oil_extraction_machinists_mortality_mult
building_group_bg_government_throughput_add
building_group_bg_infrastructure_throughput_add
building_group_bg_infrastructure_engineers_mortality_mult
building_group_bg_infrastructure_laborers_mortality_mult
building_group_bg_infrastructure_machinists_mortality_mult
building_group_bg_military_throughput_add
country_military_tech_spread_mult
country_military_tech_research_speed_mult
country_society_tech_spread_mult
country_society_tech_research_speed_mult
building_barrack_throughput_add
building_naval_administration_throughput_add
building_fishing_wharf_throughput_add
building_trade_center_throughput_add
building_subsistence_farm_throughput_add
country_academics_voting_power_add
country_bureaucrats_voting_power_add
country_clerks_voting_power_add
country_engineers_voting_power_add
country_laborers_voting_power_add
country_machinists_voting_power_add
country_peasants_voting_power_add
country_shopkeepers_voting_power_add
country_slaves_voting_power_add
country_soldiers_voting_power_add
```


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

> **计数口径说明（三次复核记录）**
>
> 本节先后写过 **6125** 与 **6121**，**两个都是错的**。正确值是 **6128**。
>
> 错因是判据选错了：两次都拿**缩进**当"是否顶层"的依据，而缩进在 PDX
> 脚本里**没有语义** —— 官方文件混用 tab / 2 空格 / 4 空格 / 完全不缩进。
> 顶层与否只能看**花括号深度**。
>
> 用「行首无缩进」数会**静默漏掉 7 个确实顶层的键**：
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
> 6121 + 7 = **6128**。反向为空 —— 顶格但非顶层的键一个也没有，
> 说明「缩进口径」是「深度口径」的真子集，只会少不会多。
>
> 四种口径对照：
>
> | 口径 | 数量 | 判定 |
> |---|---:|---|
> | **花括号深度为 0** | **6128** | ✅ 正确 |
> | 行首无缩进 | 6121 | ❌ 漏掉上表 7 个 |
> | 不限缩进、不数深度 | 6129 | ❌ 混入 1 个嵌套键 |
> | 用 `^[A-Za-z_]` 开头 | 6118 | ❌ 另漏 3 个数字开头的键 |
>
> **三个具体陷阱**：
>
> 1. **有 3 个静态修饰符以数字开头** —— `1848_popular_radical`、`1848_reactionary_enactment`、
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

```pdx
country_default = {
	icon = gfx/interface/icons/timed_modifier_icons/modifier_coins_negative.dds
}
```

**最典型形态**（`04_decision_modifiers.txt`）：

```pdx
modifier_olympic_games = {
	icon = gfx/interface/icons/timed_modifier_icons/modifier_statue_positive.dds
	country_prestige_add = 100
}

modifier_film_industry = {
	icon = gfx/interface/icons/timed_modifier_icons/modifier_statue_positive.dds
	country_prestige_add = 20
	state_migration_pull_mult = 0.1
}
```

**带负值与混合作用域**（`99_global_je_test.txt`）：

```pdx
lippe_crisis = {
	icon = gfx/interface/icons/timed_modifier_icons/modifier_coins_negative.dds
	building_throughput_add = -0.1
	country_loan_interest_rate_mult = 1.0
}
```

**代码内部使用的大块**（`00_code_static_modifiers.txt` 的 `base_values`，49 项，文件开头带有"不可删除/改名"的原版警告）：

```pdx
base_values = {
	country_weekly_innovation_add = 50
	country_weekly_innovation_max_add = 50
	country_tech_spread_add = 25
	country_loan_interest_rate_add = 0.2
	country_bureaucracy_add = 100
	country_authority_add = 100
	country_influence_add = 100
	state_tax_capacity_add = 100
	state_infrastructure_add = 3
	...
}
```
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

```pdx
add_modifier = { # authority cost
	name = serial_killer_active_investigation
	days = short_modifier_time
}
add_modifier = { # academics polstr
	name = consulting_academics_serial_killer
	days = short_modifier_time
}
```
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

| File | Entries | Max entries in one modifier |
|---|---|---|
| `00_code_static_modifiers.txt` | 150 | 49 |
| `00_companies.txt` | 1 | 2 |
| `00_diplomacy_modifiers.txt` | 3 | 3 |
| `00_ep2_01_modifiers.txt` | 13 | 4 |
| `00_ep2_02_modifiers.txt` | 46 | 6 |
| `00_ep2_03_modifiers.txt` | 20 | 3 |
| `00_ep2_04_modifiers.txt` | 71 | 5 |
| `00_ep2_05_modifiers.txt` | 8 | 3 |
| `00_ep2_06_modifiers.txt` | 41 | 5 |
| `00_ip2_02_modifiers.txt` | 55 | 6 |
| `00_ip2_03_modifiers.txt` | 60 | 9 |
| `00_ip2_05_modifiers.txt` | 24 | 5 |
| `00_ip3_02_modifiers.txt` | 80 | 5 |
| `00_ip3_03_modifiers.txt` | 46 | 5 |
| `00_ip3_04_modifiers.txt` | 102 | 6 |
| `00_ip4_02_modifiers.txt` | 63 | 5 |
| `00_ip4_03_modifiers.txt` | 39 | 6 |
| `00_ip4_04_modifiers.txt` | 93 | 7 |
| `00_negotiation_modifiers.txt` | 14 | 3 |
| `00_test_modifiers.txt` | 13 | 2 |
| `01_loans.txt` | 1 | 1 |
| `02_event_modifiers.txt` | 383 | 6 |
| `03_event_ig_opinion_modifiers.txt` | 80 | 3 |
| `04_decision_modifiers.txt` | 7 | 3 |
| `05_rule_modifiers.txt` | 3 | 2 |
| `06_conscription_modifiers.txt` | 12 | 5 |
| `07_culture_standard_of_living.txt` | 634 | 2 |
| `07_lobbies_03_modifiers.txt` | 14 | 2 |
| `07_sphere_of_influence_2_modifiers.txt` | 29 | 5 |
| `07_sphere_of_influence_4_modifiers.txt` | 76 | 4 |
| `08_religion_standard_of_living.txt` | 34 | 2 |
| `09_movement_modifiers.txt` | 1 | 2 |
| `10_culture_cultural_acceptance_modifiers.txt` | 634 | 2 |
| `11_culture_fervor_target_modifiers.txt` | 634 | 2 |
| `12_diplomatic_modifiers.txt` | 1 | 2 |
| `99_global_je_test.txt` | 3 | 3 |
| `101_modifiers.txt` | 52 | 3 |
| `104_modifiers.txt` | 173 | 4 |
| `105_modifiers.txt` | 162 | 4 |
| `106_modifiers.txt` | 47 | 9 |
| `agitators_1_modifiers.txt` | 83 | 4 |
| `agitators_2_modifiers.txt` | 191 | 6 |
| `agitators_3_modifiers.txt` | 29 | 6 |
| `agitators_4_modifiers.txt` | 211 | 4 |
| `agitators_4_revolution_modifiers.txt` | 110 | 6 |
| `agitators_5_modifiers.txt` | 216 | 12 |
| `agitators_6_modifiers.txt` | 80 | 3 |
| `brazil_1_modifiers.txt` | 29 | 4 |
| `brazil_2_modifiers.txt` | 74 | 7 |
| `brazil_3_modifiers.txt` | 2 | 4 |
| `bulgarian_modifiers.txt` | 9 | 7 |
| `content_1_modifiers.txt` | 278 | 10 |
| `content_2_modifiers.txt` | 145 | 5 |
| `content_3_modifiers.txt` | 117 | 7 |
| `content_4_modifiers.txt` | 144 | 7 |
| `content_204_modifiers.txt` | 119 | 6 |
| `content_304_modifiers.txt` | 129 | 9 |
| `cuban_modifiers.txt` | 17 | 10 |
| `japan_single_fire_events_modifiers.txt` | 27 | 5 |
| `libya_modifiers.txt` | 1 | 6 |
| `montenegrin_modifiers.txt` | 84 | 7 |
| `morocco_modifiers.txt` | 24 | 6 |
| `portugal_single_fire_events_1_modifiers.txt` | 25 | 3 |
| `portuguese_colonialism_modifiers.txt` | 25 | 4 |
| `portuguese_monarchy_modifiers.txt` | 8 | 2 |
| `spanish_africa_modifiers.txt` | 16 | 4 |
| `state_atheism.txt` | 10 | 2 |
| `unification.txt` | 3 | 2 |

---

### 6.6 未声明 `icon` 的静态修饰符（32 个）

`icon` 是静态修饰符**唯一**的非修饰符类型键，但并非强制。下图由脚本机械筛出全部 32 个缺 `icon` 的条目——其中 **26 个在 `00_code_static_modifiers.txt`**（代码内部使用、不在 UI 上作为"临时修正"展示），另有 5 个在 `104_modifiers.txt`、1 个在 `00_test_modifiers.txt`。

| File | Static modifier without `icon` |
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

```
	is_accepted_culture_and_religion = {
		if = {
			limit = {
				is_accepted_culture = no
			}
			factor = 0.20
		}
		if = {
			limit = {
				is_state_religion = no
			}
			factor = 0.20
		}
	}
```

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

以下事项**无法**从本机文件确证，需实机测试或引擎日志验证。列出以免误用：

| # | 未确认项 | 目前掌握的信息 |
|---|---|---|
| 1 | **mod 的 defines 文件能否放在 `common/defines/` 的子目录**（如 `common/defines/jomini/`）来覆盖子目录下的原版文件 | 原版自己在 `GAME\common\defines\jomini\` 放了 3 个文件覆盖 Jomini 层；但那是内容根之间的机制，mod 层是否同理未验证。**建议**：要覆盖 `NTooltip` / `NFogOfWar` / `NRivers` 这类，先在根目录用大前缀文件试，不行再复制子目录结构。 |
| 2 | **子目录文件与根目录文件之间的加载先后顺序** | 只知道「按文件名排序」（Wiki），但 `jomini/00_tooltips.txt` 与 `00_ai.txt` 谁先加载无法确证。 |
| 3 | **mod defines 文件与原版文件同名时**是「整文件替换」还是「按键合并」 | Wiki 明确说 mod 侧**不需要**覆盖整个文件（按键合并）；但证据 3 显示**内容根之间**同名相对路径是整体接管。同名 mod 文件的行为未实测。**建议**：mod 永远用不同文件名 + 大前缀。 |
| 4 | **`@` 变量的作用域是否跨文件** | 已知原版在同一文件内（含块外顶层定义、块内定义、块内引用）使用正常。跨文件是否可用未验证。**建议**：mod 里直接写数值。 |
| 5 | **引擎 define 的默认值/最大最小值** | defines 没有声明类型或范围；越界值的行为未知（可能夹取、可能崩溃）。 |
| 6 | **`has_game_rule` 的块形式**（`has_game_rule = { name = ... value = ... }`）是否存在 | 原版 0 使用；仅触发器本地化文件里有同名条目。**建议**：只用标量形式。 |
| 7 | **`apply_modifier` 在 game_rules 中是否仍有效** | 原版 1.14.2 零使用；`game_rules.md` 有记载。 |
| 8 | **`game_data.type_set` 的合法取值** | `modifier_types.md` 举例 `cultural_acceptance`，但原版 0 使用；完整取值表未知。 |
| 9 | **`decimals` / `percent` / `color` 缺省值** | 原版有 31 个键不写 `decimals`、1479 个不写 `percent`，证明有默认值，但具体值未确证。 |
| 10 | **`scripted_modifiers` 是否仍被引擎解析** | 全库 0 引用（§7.2）。 |
| 11 | **wiki 的 verified 版本是 1.13，采集时点本机是 1.14.2** | 本文所有 Wiki 引用均标注，并与本机实测交叉核对；发现一处**过时/不符**：Wiki 的 `00_defines` 示例注释称 `INCORPORATION_TIME_NO_MATCH` 的 base game 值为 20，实测为 **25**（`00_defines.txt` 第 57 行）。 |
| 12 | **mod 中新增 define 键是否完全无效** | 推断为无效（键由 C++ 硬编码），但未见官方明文说明。 |

---

## 9. 复现方法

本文全部机械清单可在工作区复跑：

```text
v3 defines                  # 摘要：命名空间块数、参数总数
v3 defines --ns NAI         # 展开 NAI 的全部 1,017 个参数
v3 defines --json out.json  # 落盘完整结构
v3 analyze                  # 全量分析（含 game_rules / 修饰符 / 静态修饰符）
```

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

