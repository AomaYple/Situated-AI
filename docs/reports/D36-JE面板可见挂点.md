# D36 —— JE 面板的可见挂点（三行到底挂在哪、双行 `战败余波` 的因果）

卡片：t36（implementation）。日期：2026-10-01。范围：`mod/data/ru_defeat.toml` / `mod/common` /
`mod/localization` / `src/pdx/modgen.py` / `tests/test_modgen.py` / 本报告。
实机验证**不在本卡**（队长口径：交给功能工程师 15 分钟预检 + t8 的 L14）。

**改前 → 改后（本卡自己动的两个源文件）**

| 文件 | 改前 | 改后 | 与 HEAD 的 numstat |
| --- | --- | --- | --- |
| `src/pdx/modgen.py` | 121,900 B / `9a19e913…`（t6 判的 revision） | 124,082 B / `4451a454d0758c168c47b20aaded067c2a8a91f55532119501685e3e9c2b1046` | 399 / 26（含前序卡） |
| `tests/test_modgen.py` | 30,422 B / `f08a51f0…`（t27 判的 revision） | 62,406 B / `a00bf3c19f9cb0b3dde967bd73e1c681b0bcd6215e8301e1c04fa2395fe25588` | 358 / 1（含前序卡） |

进程树峰值 RSS / 墙钟逐条见 §5；本卡盘上存底脚本与原始输出在 `tools/out/d36-logs/`
（`pre-effects/`、`07-effects-diff.txt`、`08-verify.txt`、`09-vanilla-reason.txt`、`10-state.txt`）。

## 一页速览

1. **三行有挂点，缺的不是数据**：引擎在 `game/gui/journal_entry.gui:742` 用
   `text = "[JournalEntry.GetReason]"` 渲染 `<JE 键>_reason`；我们的键已经生成在
   `mod/localization/simp_chinese/sitai_ru_defeat_l_simp_chinese.yml:4`（英文同名文件 `:4`），
   数据源 `mod/data/ru_defeat.toml:263-264`。**t33 的「没看到」是面选错**（看的是侧栏列表、
   不是 JE 面板），现读代码：`journal.gui:112` 的 default 页只列**活跃** JE，而我们的 JE 有
   `complete = { legitimacy >= 75 }` ⇒ 合法性过 75 就立刻离开活跃列表。
2. **双行 `战败余波` 不是设计使然，是真被挂两次**：接线把同一个效果追加到**两条**原版钩子
   （`on_capitulation` + `on_wargoal_enforced`），而原版注释（`00_code_on_actions.txt:6280-6284`）
   写明后者也涵盖 capitulation ⇒ 投降那一局两条都触发、`sitai_ru_defeat_shock` 跑两遍，
   改前那条 `add_modifier` 是裸挂 ⇒ 修正页签出现同名同 9 年两行。
3. **修法 = 幂等**（不删任何一条钩子：两条各有覆盖面）：生成器现在把每个
   `add_modifier = { name = X … }` 写成 `remove_modifier = X` + 原节点。生成物 diff
   **9 份 effects / +22 行 / −0 行**；判据面与闸门 ④ 不受影响（facts/readback 都看不见裸 `remove_modifier`）。
4. **新增回归用例**（`test_modgen.py::test_每个add_modifier前面先删同名`）钉住这条性质；
   变异检查（把幂等换成直通）该用例**立刻红**，不是空转。
5. **十条 verify 全部 EXIT 0**（§5），含 `verify` 234/234、`modguard` 五道全过、`modgen --check`
   69 个产物逐字节一致、`pytest 75 passed`、`ruff` 与 `mypy --no-incremental` 全绿。
6. **现场预检单见 §4**：哪一面、哪几步、每行该显示什么文本，以及若不成立最可能的三个原因与排查点。

## §1 挂点：`[JournalEntry.GetReason]` ← `<JE 键>_reason`（原版先例 + 我们的键）

**机制与原文出处（现读游戏文件，不是猜）**

- 渲染点：`game/gui/journal_entry.gui:742` → `text = "[JournalEntry.GetReason]"`
  （面板根 `journal_entry_panel = default_block_window_two_lines`，同文件 `:16-17`）。
- 官方文档把这一格叫 **JE Description**：`research/official-docs/game/common/journal_entries/journal_entries.md:105-119`
  的 GUI 层级里 `JE Status` = `GetStatusDesc`（同文件 `:188-189`）、`JE Description` = `GetReason`。
- 面板怎么打开：`game/gui/journal.gui:339`（行类型 `type journal_entry = button`）`:348`
  `OpenJournalEntryPanel`；顶栏入口 `game/gui/information_panel_bar.gui:655-704`
  = `onclick = "[InformationPanelBar.OpenPanelCycleTabs('journal', 'default|inactive_journal_entries|nation_formation')]"`。
- 我们的键（数据源 `mod/data/ru_defeat.toml:263-264` → 生成物）：
  `mod/localization/simp_chinese/sitai_ru_defeat_l_simp_chinese.yml:4`（`je_sitai_ru_reform_window_reason`）、
  英文 `mod/localization/english/sitai_ru_defeat_l_english.yml:4`（同名键）。
  **G3 的三行就在这一段文本里**（4 段：背景 / 「当前目标：…」 / 「最大压力与阻力：…」 / 「上次改主意的原因：…」）。
- 为什么它**能承载动态文本**（本卡要答的那一问）：这一键就是普通本地化文本，可以写数据函数。
  原版现读（`tools/out/d36-logs/vanilla_reason.py` → `09-vanilla-reason.txt`）：
  `game/localization/english/` 168 个 yml 里 **459 条** `<JE 键>_reason`，其中 **252 条**值里带 `[...]`
  数据函数 —— 例：`localization/english/agitators_2_l_english.yml:758`
  `je_haitian_debt_reason = "…[SCOPE.sCountry('france_scope').GetName]…"`。
  另有 **78 条** `<JE 键>_status`（侧栏/面板的状态格走 `GetStatusDesc`），例
  `localization/english/acw_text_l_english.yml:134 je_acw_reconstruction_status`。
  **我们这份目前写的是静态散文**（数字在生成时烘进文本，`..._l_simp_chinese.yml:4`）——
  机制支持动态，但本卡**没有**改成数据函数（不在验收面内，如实记在 §6）。

**t33「没看到」的原因（现读代码，可证伪）**

- `game/gui/journal.gui:112`（default 页签，`visible = "[InformationPanel.IsTabSelected('default')]"`）
  的分组列表数据源是 `:167 AccessPlayer.GetGroupsForActiveJournalEntries` +
  `:183 JournalEntryGroup.GetActiveJournalEntryTypes(GetPlayer.Self)` ⇒ **只列活跃 JE**。
- 我们 JE 的判据（`mod/common/journal_entries/sitai_ru_defeat_window.txt`）：
  `possible = { has_variable = sitai_ru_defeat_memory; legitimacy <= 75 }`（`:24-27`）、
  `complete = { legitimacy >= 75 }`（`:29-31`）、`is_shown_when_inactive`（`:19-22`，为真）⇒
  合法性 ≥75 的那一刻它立刻 complete、离开活跃页；`possible` 不成立时它去 **潜在页**
  （`journal.gui:240 visible = IsTabSelected('inactive_journal_entries')`、`:246`
  `AccessPlayer.GetGroupsForInActiveJournalEntries`）。
- t33 现读的合法性是 100 → 74 → 73（投降事件前后）⇒ **读数时刻决定它在哪个页**。
  结论：链路本来是通的，缺的是「开对面、点对行、看对格」——这正是 §4 预检单要一次说清的东西。

## §2 双行 `战败余波` 的因果（离线两方：effect 侧 + 生成物侧）

**effect 侧（接线，唯一出处）**：`mod/common/on_actions/sitai_ru_defeat_on_actions.txt:9-41` 把**同一个**
效果追加到两条**原版**钩子上：

| 钩子 | 包装块 | 判据 | 何时触发 |
| --- | --- | --- | --- |
| `on_capitulation` | `:14-23` | `c:RUS ?= this`（root 就是投降国） | 本国被迫投降 |
| `on_wargoal_enforced` | `:25-40` | `scope:target ?= c:RUS` | 战争目标被强制执行 |

决定性原文：`game/common/on_actions/00_code_on_actions.txt:6280-6284` 的注释写明
`on_wargoal_enforced` —— *"Fires when a goal is taken in such a manner that it cannot be
reversed - from diplomatic demands, capitulation, peace deals and so on"*，
`scope:target = the country the wargoal was enforced against`。
⇒ **投降那一局两条都触发**，`sitai_ru_defeat_shock` 跑两遍。

**生成物侧（改前）**：`mod/common/scripted_effects/sitai_ru_defeat_effects.txt:15-18` 是**裸挂**
（`add_modifier = { name = sitai_ru_defeat_pressure; years = 10 }`，前面没有 `remove_modifier`）
⇒ 两次调用 = 引擎侧两个实例 ⇒ 「国家详情 → 修正」页签出现**同名同寿命（9 年）两行**，
正是 t33 实测到的那两行。

**为什么删掉一条钩子不是修法**：两条各有覆盖面 —— `on_wargoal_enforced` 还管外交要求与和约割让，
删任一条都会漏判（战败只认一半）。所以修在**幂等**上：每次挂之前先删同名。

**`_capitulation` 档为什么只应有一行**：叠加档的判据是 `has_variable = recent_capitulation`
（生成物 `:20-22`），而原版是在 capitulation 处理里才写这个变量
（`00_code_on_actions.txt:4221-4224`）—— `on_wargoal_enforced` 先跑（那时变量还没写）、
`on_capitulation` 后跑（变量已写）⇒ 叠加档命中一次。改后即使两条路径都跑，也各只剩一个实例。

**「引擎到底叠不叠同名修正」**：现象层证据（t33 实测的同名两行）证明引擎**允许**同名修正并存为
两个实例；数值是否各算一份，离线面判不了（没有静态可读的修正清单/合计）。本卡**把这个问题移出问题面**：
幂等之后任何时刻最多一个实例，叠加与否都不再影响标定；这条性质现在由生成器的回归用例钉住（§3）。
残留：若将来有人再加一条裸 `add_modifier`，用例会在生成侧当场红，而不是等实机看到两行。

## §3 修：生成器层面的幂等挂载（一处新函数、四处调用点）

`src/pdx/modgen.py` 新增 `_idempotent_add(node)`（`:1321` 起），把
`add_modifier = { name = X … }` 渲染成 `remove_modifier = X` + 原节点；取不到 `name`、或节点名不是
`add_modifier` 时 `raise DataError`（不安静放过）。四个调用点：
`effects_text` 的基线压力、inputs 的 `add_modifier`、`_escalation_branch` 的叠加档、
`_difficulty_branches` 的每个难度档。

docstring 里写的**原版先例**（判「不加 `has_modifier` 守卫」的依据）：
`game/common/scripted_effects/00_strike_effects.txt:63-78` = `strike_state_add_modifier_effect_weak`
里在 `hidden_effect` 中**无守卫**连删三个同名修正（`:65`/`:66`/`:67`），随后 `:69-78` 在 `if` 里重新挂；
另一路（带守卫）见 `game/common/scripted_effects/00_scripted_effects.txt:741-754`。
现读原版：`on_actions` 36 处 / `scripted_effects` 75 处 `remove_modifier`，12 个文件存在「同名删 + 同名加」
（探针 `tools/out/d36-logs/vanilla_stack.py` → `06-vanilla-stack.txt`）⇒ 删一个不存在的修正是**空操作**，
所以不需要守卫，少一个分支就少一个核对面。

**生成物 diff（本卡自己的产出，改前存底 `tools/out/d36-logs/pre-effects/`）**：9 份 effects **+22 / −0**。
8 份各 +2 行（基线压力 + 改革输入各一条 `remove_modifier`）；`sitai_ru_defeat_effects.txt` +6 行：

```
:14  remove_modifier = sitai_ru_defeat_pressure                    （基线压力）
:23  remove_modifier = sitai_ru_defeat_pressure_capitulation       （投降叠加档）
:34  remove_modifier = sitai_ru_defeat_difficulty_history_friendly （史实友好档）
:45  remove_modifier = sitai_ru_defeat_difficulty_harsh            （无情档）
:59  remove_modifier = sitai_ru_reform_inputs                      （改革输入）
:68  remove_modifier = sitai_ru_reform_inputs_capitulation         （改革输入叠加档）
```

**判据面为什么安全**：`modgen._facts_effects`（`:2424-2451`）只反解 `set_variable` / `add_modifier` /
`if[index].limit.*` / `if[index].add_modifier.*`，`readback`（`:2589`）复用同一函数 ⇒ 新增的裸
`remove_modifier` 对 facts 与 readback **双方都不可见**；`modguard` 闸门 ④（`src/pdx/modguard.py:711-760`）
比的就是这两者，所以不会因为这次改动变红（现测：五道全过，§5）。判据侧原有钉死的几条
（`test_modgen.py:1157` 的 `years` 计数、`:1231` 的 `if` 分支数、`:1239`/`:1240` 的 facts 键）
全部只数标量与分支，不受标量兄弟行影响（现测 75 passed）。

**回归用例**：`tests/test_modgen.py::test_每个add_modifier前面先删同名`（文件末尾新增
`_idempotent_sites(block)` 助手）：取 `modgen.load_all()` 的 9 份档案 → `modgen.effects_text()`
→ 用仓库自己的 `pdx.parser.parse_text` 解析 → 对每个效果块递归进 `if`，断言每个
`add_modifier = { name = X … }` 的**前一条兄弟**是 `remove_modifier = X`（名字必须一致），
并断言覆盖面 ≥ `len(archives) * 2`。
**变异检查**（`tools/out/d36-logs/mutate_idempotent.py`：把 `_idempotent_add` 换成直通）
⇒ `1 failed, 74 deselected`（红）⇒ 用例不是空转。

## §4 现场预检单（15 分钟，一键照做；这就是本卡的核心交付）

**前置**：按仓库现成逻辑取机器锁 + 冷启动闸（与 t5 同款），起一局 1.14.5、选**俄罗斯**、
造一次投降（t5 runbook 的场景即可），确认游戏内**合法性 ≤ 75**（这是 `possible` 的条件，
`mod/common/journal_entries/sitai_ru_defeat_window.txt:24-27`）。

**步骤（照顺序点）**

1. 顶栏点**日志/期刊**图标（`game/gui/information_panel_bar.gui:655-704`
   → `OpenPanelCycleTabs('journal', 'default|inactive_journal_entries|nation_formation')`）。
2. 先看 **default** 页签（`journal.gui:112`）的分组列表：找 `je_group_internal_affairs` 分组下
   标题为 **「战败求存：改革窗口」** 的行（本地化键 `je_sitai_ru_reform_window`，
   `..._l_simp_chinese.yml:3`）。
3. 若 default 页没有 ⇒ 切 **潜在** 页签（`journal.gui:240`）：因为 `is_shown_when_inactive` 为真
   （`sitai_ru_defeat_window.txt:19-22`），**合法性 ≥75（JE 立刻 complete）时它只在这里**。
4. **点这一行**（`journal.gui:348 OpenJournalEntryPanel`）打开 JE 面板 ⇒ 面板正文那一格
   （`journal_entry.gui:742` = `[JournalEntry.GetReason]`）应显示
   `..._l_simp_chinese.yml:4` 的整段（共 4 段）。
5. 打开 **国家详情 → 修正** 页签。

**每一格该显示什么（逐字比对）**

- 面板正文（`[JournalEntry.GetReason]` → `je_sitai_ru_reform_window_reason`）4 段：
  1. 「仗打输了，账单到了。把国家带进这场战争的贵族失去了对朝堂的掌控，王权的威信已经破裂，
     国库只能以高昂的利息借债。」
  2. 「窗口已经打开：旧势力虚弱、政府合法性动摇之时，改革是可能的。等国家重新站稳，这扇窗就会关上。」
  3. 「**当前目标**：趁窗口开着，把旧势力一直拦着的那项改革推过去。」
  4. 「**最大压力与阻力**：压力 = 贵族失势 + 王权威信破裂 + 借债成本高昂；阻力 = 等国家重新自己站稳。」
  5. 「**上次改主意的原因**：因为战败被记进了账 —— 是这场败仗挪动了 AI 读到的那些输入。」
  （G3 的「三行」= 上面 3/4/5；它们与背景段同在一格，靠空行分段。）
- 「修正」页签：**`战败余波`（9 年）恰好一行**；若投降叠加档命中，另有
  **`战败余波：被迫投降（合法性 -15，地主政治力量 -15%，借债利息 +15%）`（9 年）恰好一行**。
  ⇒ 两行**不同名**是设计（基线 + 叠加），同名两行才是这次修的 bug。

**若不成立：最可能的三个原因 + 各自的排查点**

1. **面 / 页签选错**（t33 的现状）：default 页只列**活跃** JE
   （`journal.gui:112` + `:167 AccessPlayer.GetGroupsForActiveJournalEntries` +
   `:183 JournalEntryGroup.GetActiveJournalEntryTypes(GetPlayer.Self)`）。
   排查：切「潜在」页（`:240`/`:246`）；直接读 `possible` / `complete` 的条件
   （`sitai_ru_defeat_window.txt:24-31`）与当下合法性数值。
2. **不在窗口内**：合法性 > 75 ⇒ `complete` 立刻成立、JE 退出活跃页；
   或这一局没真战败 ⇒ `has_variable = sitai_ru_defeat_memory` 不成立
   （变量由 `sitai_ru_defeat_effects.txt:9-13` 写，接线 `sitai_ru_defeat_on_actions.txt:14-23`）。
   排查：读游戏内合法性 + 探针读变量 / 看 on_action 是否真的跑过。
3. **「修正」页签仍是同名两行**：说明跑的不是新产物，不是逻辑没修。
   排查：`v3 modgen --check`（现测「盘上 69 个产物与数据源逐字节一致 ✅」）、
   产物 `sitai_ru_defeat_effects.txt:14` 是否有 `remove_modifier = sitai_ru_defeat_pressure`、
   游戏是否重启并读了新产物（Mounted Data 里 mod 版本那行）。
   另：若文本**显示成键名**（`je_sitai_ru_reform_window_reason`），那是本地化没加载 ——
   排查 yml 的 BOM/文件名（`l_simp_chinese` 与 `*_l_simp_chinese.yml`）、语言设置、mod 是否被挂载。

**一条残余未知（不拦预检，先记下）**：我们**没有**出 `<JE 键>_status` 键，而侧栏行与面板状态格走
`GetStatusDesc`（`journal.gui:425-426`、`journal_entry.gui:188-189`，回落键名 = `<JE 键>_status`）。
原版另有 78 条 `*_status` 键（例 `localization/english/acw_text_l_english.yml:134`）。
若预检看到侧栏那一列是空/原样键名，原因就是这条，不是挂点问题。

## §5 门禁：十条 verify 逐条读数（现跑，`tools/out/d36-logs/08-verify.txt`）

| # | 命令 | EXIT | 墙钟 | 进程树峰值 | 语义读数 |
| --- | --- | --- | --- | --- | --- |
| 1 | `v3 modgen --write` | 0 | 0.915 s | 54.8 MB | 已写入 69 个产物 |
| 2 | `v3 modgen --check` | 0 | 0.788 s | 52.1 MB | 盘上 69 个产物与数据源逐字节一致 ✅ |
| 3 | `v3 objectives --check` | 0 | 1.442 s | 89.5 MB | 9 份档案 P1–P5 全绿、总红 0 |
| 4 | `v3 modguard` | 0 | 6.886 s | 238.9 MB | 五道闸门全过 ✅（含 ① 命名空间/平铺、② 引用完整性、④ 往返净度） |
| 5 | `v3 verify` | 0 | 40.254 s | 289.7 MB | 通过 234 / 234，失败 0；归属标记全部对上（219 处）；正文与断言表一致 |
| 6 | `v3 citations --offline` | 0 | 1.690 s | 66.4 MB | 975 条引用全部有入库支撑（与入库快照一致）✅ |
| 7 | `pytest tests/test_modgen.py -q -n0` | 0 | 3.514 s | 74.8 MB | 75 passed in 2.51s |
| 8 | `ruff check .` | 0 | 0.144 s | 7.1 MB | All checks passed! |
| 9 | `ruff format --check .` | 0 | 0.142 s | 7.2 MB | 249 files already formatted |
| 10 | `mypy --no-incremental` | 0 | 11.642 s | 369.4 MB | Success: no issues found in 146 source files |

首轮曾有两处红（现已消，留痕）：⑨ `ruff format --check` 报 `src/pdx/modgen.py:1371` 的一处
多余换行（按 `ruff format --diff` 的写法重排）、⑩ `mypy` 报 `_idempotent_add` 的
`str-unpack` / `union-attr` 3 条（改成 `isinstance(node, str)` 先行 + `isinstance(field, str)` 过滤后全绿）。
表内数字是**修完之后重跑一遍**的读数（顺序、命令、语义与首次一致）。

## §6 边界与残差（如实）

1. **本卡没有做实机**（队长口径）：实机由功能工程师的 15 分钟预检 + t8 的 L14 承担。
   本卡给出的是可被现场核对的**预测**（§4）与离线两方证据（§2/§3）。
2. **`_reason` 目前是静态散文**：机制支持动态文本（原版 459 条 `_reason` 里 252 条带 `[...]`，§1），
   但我们这一键没写数据函数。要做"实时合法性/实时压力"需要把数据函数写进
   `mod/data/ru_defeat.toml:263-264` 的值 —— **本卡没做**（不在验收面内）。
3. **`<JE 键>_status` 未出**：侧栏状态列回落键缺失（§4 末），原版先例 78 条。未改，如实记。
4. **引擎是否对同名修正数值叠加**：离线不可判；已由幂等移出问题面（§2 末），并由回归用例钉住。
5. **未改判据 / 未改阈值**：`modgen._facts_effects` / `readback` / `modguard` 的判据一行未动；
   未碰 `tools/probe/perf_compare.py` 与预注册文件；未碰 `tests/test_inventory.py` /
   `tests/test_docs_consistency.py`。
6. **`mod/common/on_actions/sitai_ru_defeat_on_actions.txt` 是未跟踪文件**（`??`，前序卡
   B35 接线落地时新增）：本卡只读它取证，没有改动它。
7. 归因提醒：9 份 effects 的 **+22 行是本卡的**；`sitai_ru_defeat_effects.txt` 与 HEAD 差的
   27/3 里另有 21/3 来自前序卡（t1 的 A1 修复与 t3 的版本面），`src/pdx/modgen.py` /
   `test_modgen.py` 的 numstat 也含前序卡改动 —— 逐文件读数在 `tools/out/d36-logs/10-state.txt`。

## §7 复现命令

```powershell
# 存底 → 生成 → 算 diff（改前状态必须先从 git 取，盘上存底只能代表当时）
py tools\out\d36-logs\effects_diff.py pre
.venv\Scripts\v3.exe modgen --write
py tools\out\d36-logs\effects_diff.py post          # → 07-effects-diff.txt

# 十条门禁（顺序、EXIT、墙钟、进程树峰值一次记齐）
py tools\out\d36-logs\run_verify.py                 # → 08-verify.txt + verify\*.out.txt

# 回归用例的变异检查（必须红）
py tools\out\d36-logs\mutate_idempotent.py

# 原版 `_reason` 约定与动态文本先例 + 本卡台账
py tools\out\d36-logs\vanilla_reason.py             # → 09-vanilla-reason.txt
py tools\out\d36-logs\state.py                      # → 10-state.txt
```

\n