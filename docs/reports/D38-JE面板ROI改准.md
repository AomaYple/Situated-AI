# D38 · `je_panel` ROI 改准 + 页签口径（面板实测开在**左侧**）

> 一句话结论：旧 ROI `(0.64, 0.04, 1.00, 0.98)` 指的是**右半屏**，而现场帧里面板开在**左侧**；
> 新 ROI = **`(0.0276, 0.0676, 0.3188, 0.9204)`** —— 三条边是**量测**、下沿是**约定**（理由见 §2.2）。
> 规范文字落在 `docs/design/exec/阶段6-实机读数.md` **§5（新增节，纯追加）**；
> 常量本体 `tools/probe/stage6_ui_rerun.py:943` **不在本卡改动面** ⇒ 交接见 §5。

## 1. 交付与改动台账

| # | 件 | 改前 | 改后 | 说明 |
|---|---|---|---|---|
| 1 | `docs/design/exec/阶段6-实机读数.md` | 43,820 B / `d87160fd07f469a6a19f6c3608b8fda9ad2cd7093902e935c4282d70bbaea374` | **51,563 B** / `40ea1681fff2965272289ef7e8dc45b1579972b01eb97500a1a124b1764ac5ad` | 追加 `## 5.` 一节（6 个子节）；LF / 无 BOM / 0 tab / 围栏 6 处成对 / 602 行 |
| 2 | `docs/reports/D38-JE面板ROI改准.md` | 本文件（新建） | 同左 | 台账与边界 |

**B112 自证（字符级 only-insert）**：现读文件的**前 43,820 字节**逐字节等于改前实记的 sha256
（重建 = 现读文本在锚点处截断 + 原末尾换行；size 与 sha 同时对上）⇒ 上文历史读数**一字未改**，
新增的 7,743 B 全在文件末尾。

## 2. 量测台账（可复算）

### 2.1 帧

* 路径：`tools/out/t5-frames/t8-je4-detail.png`
* 字节：**3,441,584 B**；sha256 **`a50cde26c7dec7d6d828fc0b8f3e5fcf12438f20fa93a4633a09cc7458d2ef65`**
* 尺寸：**1920×1080**；mtime **2026-10-01 05:51:16**（`Get-Item` 现读）
* 来源：功能工程师 t8 的 15 分钟可见性预检现场帧（卡面与 t36 补记给的是同一字节数与同一 sha 前缀）

### 2.2 四条边：三条量测 + 一条约定

| 边 | 比例 | 像素 | 判据 | 类型 |
|---|---|---|---|---|
| left | 0.0276 | 53 | 竖亮线 x=53/54（y∈[110,800] 内 **446/480** 行亮） | **量测** |
| top | 0.0676 | 73 | 横亮线 y=73/74/75（x∈[58,606] 内 **543/545/548** 亮；同一行 x∈[900,1400] 只 **13/15/18** 亮 ⇒ 是面板顶边不是全屏顶栏） | **量测** |
| right | 0.3188 | 612 | 竖亮线 x=611/612（**362/427** 行亮） | **量测** |
| bottom | 0.9204 | 994 | 内容末行 **856** + 约 138 px 余量（且 < 底部 UI 条 ≈1000 px） | **约定**（量不到，见下） |

* 换算：`px = round(比例 × 1920)` / `round(比例 × 1080)` —— 53/1920=0.0276、73/1080=0.0676、612/1920=0.3188、994/1080=0.9204，四舍五入后逐一回到上表整数。
* **下沿为什么量不出来**：面板**宽固定、高随内容**（§4），而这一帧里 y≥860 的 x∈[0,600] 是一片**均匀暗带**（mean 37–40 / sd 1.3–2.0），与面板内部（luma 52–65）在像素上不可分 ⇒ 看不到下沿描边。取值依据是**内容末行**：文字最低一行 **y=856**（y≥838 起再无 luma>105 的像素；y=832 那行还有 169 个亮像素）。**这一条必须在文档里标成「约定」**，不许当量测读。
* 旁证（同一帧）：标题下的分隔线 y=182/183 亮段 x∈[54,613]，与 left/right 自洽。

### 2.3 脚本与判据教训（都在 `tools/out/d38-logs/`，未入库）

`measure4.py`（亮线找边框，成功）｜`measure5.py`（行/列精测 + 左栏图标分段）｜`measure6.py`（竖线纵向延伸）｜
`measure7.py` / `measure8.py`（找下沿，**失败** ⇒ 才有 §2.2 的约定）｜`measure9.py` / `measure10.py` / `measure11.py`（左栏入口）｜
`check_files.py`（文件卫生）。

**教训（值得留给下一个人）**：这一帧面板内部 luma 52–65、夜里地图 64–67 ⇒ 按「暗/亮」**切不开**；
面板内部行 sd≈1.3–2.0，也没法与夜里的海面区分。**只有描边亮线可分**。
（先走的 `measure_panel.py` 用「羊皮纸色」判据，只找到 2 列就废掉了 —— 面板不是羊皮纸色。）

人眼复核件（同目录）：`crop-panel-whole.png`（box 30,60,700,880；670×820；796,903 B / `e3c7ab70984c980b…`）、
`crop-panel-header.png`、`crop-panel-left-edge.png`、`crop-panel-right-edge.png`、`crop-left-bar.png`、
`crop-right-list-top.png`、`zoom-leftbar-670-810.png`（×5 放大）。

## 3. 现场事实（这一帧里到底有什么）

1. **面板在左侧**：可见框 x∈[53,612] / y∈[73, ≈856 起的内容区]，标题「战败求存：改革窗口」+ 副标题「国内事务日志条目」；
   右上角有 pin 与 ✕。
2. **右侧是日志列表**：`日志条目 4未钉选` + 一行「高加索战争」—— 即面板**不在**右侧（旧 ROI 恰好套在列表上）。
3. **我们这一条在「活跃」页**：三行 G3（当前目标 / 最大压力与阻力 / 上次改主意的原因）+「完成条件：俄罗斯政府的合法性大于或等于 75」
   就在这一帧的面板里 ⇒ 与官方法档语义自洽（`possible` 为真 ⇒ Activated）。**D36 §4 猜的「要切到潜在页」在该状态下不成立。**
4. **帧是 D37 修 BUG 之前拍的**：面板「如果完成」段还留着 `BUG: set_strategy missing perspective…`（D37 已修）⇒ 这一帧属**历史帧**，
   不要当现状读；但它对**几何**（边框/位置）仍然有效 —— 面板尺寸与位置不由那一段文本决定。
5. **左栏 journal 入口 ≈ (25, 706)**：图标盘 x∈[4,45] / y∈[686,725]；书封面红像素 x∈[10,25] / y∈[696,708]；
   白徽章「5」x∈[21,30] / y≈[689,705]（归一化 `(0.0130, 0.6537)`）。
   卡面给的是 **(30,706)** —— 两者同属这一枚按钮（x 差 5 px，都落在盘内）⇒ **不矛盾**，文档里两个都给。

## 4. 原版依据（逐处出处；全部现读）

| 文件:行 | 读到什么 | 支撑 |
|---|---|---|
| `game/gui/journal_entry.gui:16` | `type journal_entry_panel = default_block_window_two_lines {`（只给名字/数据源/内容，**没有 position/anchor**） | 面板位置由**引擎**决定 ⇒ 判据不得写死左右 |
| `game/gui/block_windows.gui:695` | `type default_block_window_two_lines = default_block_window {` | 同型定义 |
| `game/gui/block_windows.gui:317-319` | `type default_block_window = widget {` + `:318 using = sidepanel_plus_sidebar_size` + `:319 layoutpolicy_vertical = expanding` | **宽固定、高随内容** |
| `game/gui/block_windows.gui:15-17` | `template sidepanel_plus_sidebar_size { size = { 613 0 } }`（`:3 @panel_width = 540`、`:8 @panel_width_plus_20 = 560`） | 声明宽 613 px；实测可见框 560 px = `@panel_width_plus_20` |
| `game/gui/block_windows.gui:12-14` | `template sidebar_margin { margin_left = "[GetDefine('NGUI', 'LENS_TOOLBAR_MARGIN_LEFT')]" }` | 613 里含左栏留白（为什么可见框是 560） |
| `game/gui/information_panel_bar.gui:661` / `:704` | `input_action = "open_journal"` | 入口动作名 |
| `game/gui/information_panel_bar.gui:660` / `:685` | `OpenPanelCycleTabs('journal', 'default\|inactive_journal_entries\|nation_formation')` | **同一按钮循环切三页**（`:18 @journal_position = 480`） |
| `game/gui/journal.gui:40` | `tab_buttons = {` | 页签本体 |
| `game/gui/journal.gui:47-48` / `:69-70` / `:88-89` | `SelectTab('default')`（`JOURNAL_ENTRIES_CONCEPT`=日志条目）/ `SelectTab('inactive_journal_entries')`（`POTENTIAL`=潜在）/ `SelectTab('nation_formation')`（`NATION_FORMATION`=成立国家） | 三页名字与切法 |
| `game/gui/journal.gui:112` / `:240` / `:300` | `InformationPanel.IsTabSelected(...)` | 三页内容由页签选择驱动 |
| `research/official-docs/game/common/journal_entries/journal_entries.md:33-40` | `possible` = "when **both** this **and** `is_shown_when_inactive` is true, the JE is **Activated**"（默认 yes） | 我们的条目落在**活跃页** |
| 同上 `:13-18` | `is_shown_when_inactive` = "can be shown **when not active**"（默认 no；`add_journal_entry` 进来的忽略它） | 管的是「不活跃时能否显示在**潜在页**」 |
| `mod/common/journal_entries/sitai_ru_defeat_window.txt:22-25` / `:27-30` | `is_shown_when_inactive = { c:RUS ?= this; has_variable = sitai_ru_defeat_memory }` / `possible = { has_variable = sitai_ru_defeat_memory; legitimacy <= 75 }` | 变量在且合法性 ≤75 ⇒ 活跃页；之后 >75 ⇒ 潜在页 |

## 5. 下游影响与旧 ROI 的逐处点名

**下游**：阶段 6 的 **L14 三行**与**英文链（t9）**裁模板 / 判 ROI **一律以新 ROI 为准**；
`je_line_goal` / `je_line_pressure` / `je_line_last_change` 三块**首段**模板必须能在
`(0.0276, 0.0676, 0.3188, 0.9204)` 内**同帧**命中。

| 位置 | 现写 | 处置 |
|---|---|---|
| `tools/probe/stage6_ui_rerun.py:943` | `"je_panel": (0.64, 0.04, 1.00, 0.98),` | **交 t39**（该文件 inScope 持有者，deps t8）—— 本卡**没有**改它，见 §6.2；消费点 `:1028`（L14 步）、`:1029`（L15 旁证）、`:2173`（§5 注释）、`:1289` / `:2727`（`je_line_*` 展开） |
| `docs/design/exec/阶段6-国家身份开局-取证口径.md:95` | `\| JE_PANEL_ROI \| (0.64, 0.04, 1.00, 0.98) \| …` | **不在 D38 改动面** ⇒ 交 t18 收口；同文件 `:82`（L14 步骤表）、`:254`（L14 判据）也点名 |
| `docs/reports/t30-档案与新增牌-改动清单.md:182` | `JE_PANEL_ROI=(0.64,0.04,1.00,0.98)`（C8 行） | 历史报告 ⇒ **只登记不改**（B112） |
| `docs/reports/t33-驱动轮询语义显式化.md:118` | 第 12 帧拿 `je_panel` 当负对照 | 历史报告 ⇒ 只登记 |
| `docs/reports/t41-取证执行器.md:157` | L14 判据链（含 `roi_of` 调用点） | 历史报告 ⇒ 只登记 |
| `tools/probe/sitai_ui/README.md:32`、`tools/probe/sitai_ui/zh/README.md:13/121` | 只列 `je_line_*` 模板名，**无 ROI 数字** | 无需改 |

## 6. 边界（没做成的、做不了的，逐条写清）

1. **卡片 inScope 里的 `tools/design` 在仓库与 git 历史中都不存在**：现测 `Test-Path tools\design` = False；
   `Get-ChildItem tools -Directory` = `.benchmarks / benchmarks / ci / out / pdx / probe / prof / reports / tests`；
   `git ls-files 'tools/design*'` 与 `git log --all -- 'tools/design*'` 与删除历史**全空**。
   ⇒ 规范文字落在 inScope 的另一项 `docs/design/exec/阶段6-实机读数.md` §5（本节即为此记）。
   **若队长确实要一个 `tools/design/` 落地件（新建目录），请回信确认 —— 我不在无授权的情况下新造目录结构。**
2. **常量本体没改**（`tools/probe/stage6_ui_rerun.py:943` 仍写旧值）：它不在本卡 inScope（属 t39 的面），
   而且 t8 正在用这个驱动跑承重批 ⇒ 此刻**盘上的驱动仍按右半屏搜 L14**。
   **⇒ L14 / t9 开跑前必须先落这一处改动**（由 t39 或其 inScope 持有者做），否则 L14 仍会「搜不到三行」。
3. **下沿是约定不是量测**（994 px）：这一帧量不到面板下沿（§2.2）。若将来要把它变成量测，需要一帧
   「面板下方是地图而非暗带」的现场帧。
4. **本卡没跑实机、没碰 `mod/`**：只改文档（冻结期纪律）。因此**没有**新的实机读数；
   机器锁协议与冷启动闸不涉及（未起游戏、未改用户环境）。
5. **`v3 tables --offline` 现读 EXIT 1，属先存红、与本卡无关**：唯一不符的是
   `08-目录全量清单.md::版本指纹`（文档 1.14.5 / 快照 1.14.4）—— 那是 D31 的活（重刷快照 + 入库）。
   本卡改的读数页不在这张表里。
6. **帧早于 D37 修复** ⇒ 帧里「如果完成」段的 `BUG: set_strategy …` 文本是历史，不是现状（§3.4）。
7. **本文不含「面板一定在左」的断言**：原版 GUI 里没有位置声明（§4），本帧在左不代表任何一帧都在左 ——
   判据应优先用模板定位，ROI 只是搜索域。

## 7. 门禁读数（现跑，本卡改动=文档）

| # | 命令 | EXIT | 读数 | 秒 |
|---|---|---|---|---|
| 1 | `.venv\Scripts\python.exe -m ruff check .` | **0** | `All checks passed!`（249 文件面） | 0.278 |
| 2 | `.venv\Scripts\python.exe -m ruff format --check .` | **0** | `249 files already formatted` | 0.199 |
| 3 | `.venv\Scripts\python.exe -m mypy --no-incremental` | **0** | `Success: no issues found in 146 source files` | 20.062 |
| 4 | `pytest tests/test_docs_consistency.py tests/test_inventory.py -q -n0` | **0** | `19 passed in 3.81s` | 3.81 |
| 5 | `.venv\Scripts\v3.exe citations --offline` | **0** | **977 条引用全部有入库支撑**（= D37 的读数，加了我的 20+ 处 `文件:行号` 之后**条数不变** ⇒ 文档不是引用扫描源；B125/B126 的假红不在此门） | 2.156 |
| 6 | `.venv\Scripts\v3.exe verify` | **0** | **通过 234 / 234**；归属标记 219 处全对上；`文档正文与断言表一致`；1.14.5 四项指纹 ✅ | 51.788 |
| 7 | `.venv\Scripts\v3.exe tables --offline` | **1** | 先存红：`08-目录全量清单.md::版本指纹`（1.14.5 vs 快照 1.14.4）—— 与本卡无关（§6.5） | — |

原始输出：`tools/out/d38-logs/g1-ruff-check.txt` … `g6-verify.txt`。
`modgen` / `modguard` / `objectives` / `ai-surface` 未跑：本卡未改 `mod/`、未改数据源、未改产物 ⇒ 与它们无关（口径 ④「写明为何无关」）。

## 8. 复现命令

```powershell
# 1) 帧身份
Get-Item tools\out\t5-frames\t8-je4-detail.png | Select-Object Length, LastWriteTime
.venv\Scripts\python.exe -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('tools/out/t5-frames/t8-je4-detail.png').read_bytes()).hexdigest())"
# 2) 量测复跑（边界与左栏入口）
.venv\Scripts\python.exe tools\out\d38-logs\measure4.py
.venv\Scripts\python.exe tools\out\d38-logs\measure6.py
.venv\Scripts\python.exe tools\out\d38-logs\measure11.py
# 3) 文件卫生
.venv\Scripts\python.exe tools\out\d38-logs\check_files.py "docs/design/exec/阶段6-实机读数.md" "docs/reports/D38-JE面板ROI改准.md"
# 4) 门禁（本卡三条 verify + 相邻两条）
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m mypy --no-incremental
.venv\Scripts\v3.exe citations --offline
.venv\Scripts\v3.exe verify
```
