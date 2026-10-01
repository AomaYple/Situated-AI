# A1：`v3 modguard` 五条 ❌ 修 —— B35 遗留的 4 个本地化键 + 闸门 ② 不认识原版变量池

> 任务卡 `t1`（attempt 1 / `e670d69e-5700-4892-807d-4113e372749c`；**attempt 2 / `308ae69a-10d4-4740-af2c-3411e13c41c8` 复跑结卡**，见 §7 的闭环记录与一条更正）。
> 数据来源全部**现读**：原版安装目录 `C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game`、
> 本仓工作树、`tools/out/snapshots/release-1.14.5.compact.json`（本卡刷新）。

## 一页速览

| 项 | 改前（2026-09-30 23:37） | 改后（2026-10-01 00:12，attempt 2 复跑） |
| --- | --- | --- |
| `v3 modguard` | **EXIT 1**，五条 ❌ | **EXIT 0**，五道闸门全过 ✅ |
| 变量假阳性 | `❌ 引用了一个我们从未写下的变量：recent_capitulation` | 消失（原版写入池 **614** 个，`recent_capitulation` 在其中） |
| 本地化缺键 | english 4 条 ❌（两键 × 各一次）+ simp_chinese 同 ⇒ 4 个键缺失 | 4 条 ❌ 全消；计数 **english 63 → 65、simp_chinese 63 → 65** |
| 对抗演示（自造假变量） | —— | 闸门 ② **仍红**（EXIT 1，点名探针），闸门强度没降 |
| 验收命令 | `modguard` EXIT 1、pytest **4 failed / 81 passed** | **6 条全绿**：`modguard` 0 / pytest **89 passed** / `ruff check .` 0 / `ruff format --check .` 0 / `mypy` 0 / `modgen --write`+`--check` 0 |

**三类改动**：① 闸门 ② 的变量检查改为「我们写的 ∪ 原版写的」——原版池**数据驱动、现读原版安装目录**，不是白名单；② `mod/data/ru_defeat.toml` 补 4 个本地化键（2 个键 × 2 语言），`v3 modgen --write` 落到 `mod/localization/**`；③ `src/pdx/modgen.py` 对叠加档不准确的概括句改准。

**曾一度未达成的两条（已闭环，如实留档）**：attempt 1 当时 `ruff check .` 与 `ruff format --check .` **不是 EXIT 0**，原因 100% 是两簇**未跟踪、非本卡路径、mtime 早于本卡开工**的文件（上一轮遗留 `.t4-scratch/` 4 个脚本 + `pytest-of-28905/`，加队友在飞的 `tools/probe/frozen/README.md` 一个 format 点）。队长裁决「外因成立」后把这两簇**移出仓库**（可逆、未删除），`t24` 修掉那个 format 点；attempt 2 复跑 **6 条全绿**。详见 §7（含一条对「GBK 乱码」说法的**撤回更正**）。

---

## 1. 改前读数（可复现）

```
$ .venv/Scripts/v3.exe modguard          # 2026-09-30 23:37，EXIT=1，1.8 s
│ ❌ │ ② 引用完整性（变量 / JE / 修正 / 图标 / 本地化键 / defines 参数） │ 5 处引用解析不到（缺引用即红） │
  变量：定义 9 个，被判据引用 10 个
  本地化：english 63 键、simp_chinese 63 键
  修正：引用 22 个（原版池 6128 个）
  声明式引用：核对 98 条（原版词汇表 4292 个键、国家 tag 830 个、修正字段 1487 个）
  ❌ 引用了一个我们从未写下的变量：recent_capitulation
  ❌ english 缺本地化键：sitai_ru_defeat_pressure_capitulation
  ❌ english 缺本地化键：sitai_ru_reform_inputs_capitulation
  ❌ simp_chinese 缺本地化键：sitai_ru_defeat_pressure_capitulation
  ❌ simp_chinese 缺本地化键：sitai_ru_reform_inputs_capitulation
```

五条里 **1 条是假阳性**（`recent_capitulation`：原版自己写、自己读的记号，闸门只认自家 `set_variable`），**4 条是真缺陷**（B35 新增的两个投降叠加档修正没有本地化键 ⇒ 游戏里显示裸键名）。

```
$ .venv/Scripts/python.exe -m pytest tests/test_modguard_offline.py tests/test_modgen.py -q -n0
4 failed, 81 passed                                    # 基线
```

四条红：三条由上面五处 ❌ 直接导致；第四条 `test_快照源与游戏源的键池一致` 是**版本漂移**——入库快照是 1.14.4，游戏是 1.14.5，`common/scripted_effects` 多了一个 `ai_assemble_decree_state_maps`。

---

## 2. 闸门 ② 的变量池：数据驱动，不是白名单

### 2.1 原版确实自己写这个名字（现读）

```
game/common/on_actions/00_code_on_actions.txt:4213-4226   on_capitulation 的 effect = {
  4216-4220     set_variable = { name = recently_lost_war   days = 1825              value = yes }
  4221-4224     set_variable = { name = recent_capitulation days = short_modifier_time }   ← :4222 写
game/events/discrimination_events.txt:217-226             trigger = {
  :222      has_variable = recent_capitulation                                          ← :222 读
```

⇒ 原版**写**它、原版**读**它；我们既没写也没读，闸门却按「我们从未写下」判红 —— 判据本身错了。

### 2.2 池怎么建：扫原版安装目录，不抄名单

实测 1.14.5 原版 `set_variable =` 命中 **543 个文件**，分布遍及 `common/` 全树与 `events/`：

```
common/journal_entries 409、common/scripted_effects 386、common/character_templates 242、
events/agitators_events 200、common/scripted_buttons 190、common/on_actions 122、
common/history 111、common/decisions 53、common/laws 11 …（events/ 328 个 txt 中约 200 个有写入）
```

⇒ 池目录取 `("common", "events")` 两棵树**才**不假阳性（只扫 `common/on_actions` 会漏掉 `common/scripted_buttons` 等一大片）。
现读池大小：`common` **356** + `events` **286**，**并集 614** 个变量名（快照表里那个 642 = 两目录条目数之和，不是并集）。

代码出处（`src/pdx/vanilla_index.py`，全部本卡新增/改动）：

| 位置 | 作用 |
| --- | --- |
| `:97` | `VARIABLE_POOL_DIRS: tuple[str, ...] = ("common", "events")` |
| `:117` | `SECTION_VARIABLES = "vanilla_variables"`（新快照域） |
| `:126` | 加进 `SECTIONS`（写入顺序） |
| `:140` | `REFS_GATE_SECTIONS` **刻意不含**新域：旧快照没有它，并进去会让闸门 ② 直接判「前置条件缺失 / 退出 2」，比逐条记「未覆盖」更坏 |
| `:214` | `def variable_names(directory: Path) -> set[str]`：栈式遍历所有块，只认 `set_variable` 块里**直接子赋值** `name = <标识符>`；`set_global_variable`（另一条命名空间）与 `name = root.x` 这类表达式写法不收 |
| `:287` | `snapshot_sections()` 把该域写进快照（`目录 -> 排序名列表`） |
| `:381` | `VanillaIndex.variables() -> set[str] | None`：game 源现算两棵树并集；snapshot 源读域，**缺任一目录 ⇒ `None`（不是空集）** |
| `:393-397` | 读域时逐目录检查，缺一即 `None` |

`src/pdx/modguard.py`（闸门 ② 的判据）：

| 位置 | 内容 |
| --- | --- |
| `:501` | `vanilla_variables = index.variables()` |
| `:506` | 池为 `None` ⇒ 逐条进「离线未覆盖」：`变量 X（原版变量池未覆盖：快照里没有 vanilla_variables 域）` —— **不静默通过、也不误判成红** |
| `:511` | 池在场 ⇒ 判红：`引用了一个我们从未写下的变量：{name}（原版 set_variable 也没写过这个名字）` |
| `:516` | 计数行：`变量：定义 N 个，被判据引用 M 个（原版写入池 {_pool_count} 个）` |

判据仍是「我们没写 **且** 原版也没写」⇒ **不是白名单、也没放宽**：名单会随版本腐烂，池每次现读。

---

## 3. 四个本地化键（真缺陷）

### 3.1 缺的是谁的键

两个投降叠加档修正**已经被生成、已经被效果挂上**，只是没有显示名：

| 修正 | 定义 | 挂载 | 数据源声明 |
| --- | --- | --- | --- |
| `sitai_ru_defeat_pressure_capitulation` | `mod/common/static_modifiers/sitai_ru_defeat_pressure.txt:13-18`（`country_legitimacy_base_add = -15`、`interest_group_ig_landowners_pol_str_mult = -0.15`、`country_loan_interest_rate_add = 0.15`） | `mod/common/scripted_effects/sitai_ru_defeat_effects.txt:20-23`（`if = { limit = { has_variable = recent_capitulation } add_modifier = … }`） | `mod/data/ru_defeat.toml:123-126` |
| `sitai_ru_reform_inputs_capitulation` | `mod/common/static_modifiers/sitai_ru_defeat_reform_inputs.txt:14` 起（工业家 / 知识界各 +0.25） | `mod/common/scripted_effects/sitai_ru_defeat_effects.txt:61-64` | `mod/data/ru_defeat.toml:174-176` |

⇒ 没有键，游戏界面里这两个修正显示**裸键名**，玩家不知道发生了什么。

### 3.2 键补在哪、长什么样

补在数据源（不是直接改生成物）：`mod/data/ru_defeat.toml:287` 与 `:292` 两个 `[[localization]]`，各带 `key` / `english` / `simp_chinese` / `why`；`v3 modgen --write` 落成 `mod/localization/english/sitai_ru_defeat_l_english.yml:7-8` 与 `mod/localization/simp_chinese/sitai_ru_defeat_l_simp_chinese.yml:7-8`：

```yaml
 sitai_ru_defeat_pressure_capitulation:0 "Aftermath of the Defeat: Forced to Capitulate (legitimacy -15, landowners -15% political strength, loan interest +15%)"
 sitai_ru_reform_inputs_capitulation:0 "Reformers Gain Influence: Forced to Capitulate (industrialists +25% and intelligentsia +25% political strength)"
```

```yaml
 sitai_ru_defeat_pressure_capitulation:0 "战败余波：被迫投降（合法性 -15，地主政治力量 -15%，借债利息 +15%）"
 sitai_ru_reform_inputs_capitulation:0 "改革派抬头：被迫投降（工业家与知识界政治力量各 +25%）"
```

**不是空壳复制**：每条点名①修正名（与基线键同族：`战败余波` / `改革派抬头`）②这一档的来由（`被迫投降`）③这一档自己的效果数值。基线键与叠加键的文案**不同**，因为它们描述的是不同修正；`why` 里另写明「不写总量 —— 总量 = 基线 + 叠加」。

### 3.3 计数变化（闸门确实看到了）

`本地化：english 63 键、simp_chinese 63 键` → `english 65 键、simp_chinese 65 键`（各 +2，正是新增的两个键在每个语言各一条）。

---

## 4. `modgen.py` 对叠加档的概括句改准

- **改前**（`src/pdx/modgen.py:1597` 那一行注释模板）：`f"处境压力（A 级）：{archive.title}。每条字段都照原版同族用法取档位，"` —— 「每条字段」把**叠加档**也算进去了，而叠加档是「实测总量 − 原版基线档」的**差额**，本来就不是原版档位阶梯里的一档（B35 的两个 why 都明写这一点）。
- **改后**：同一句（现在在 `:1601`）收窄为 `基线档的每条字段照原版同族用法取档位，`；并在有叠加档时于 `:1594` 追加一行警告：

```
# ⚠️ 叠加档的每条字段是「实测总量 − 原版基线档」的**差额**，**不是**原版同族用法里的一档（档位依据与「为什么是差额」见各条 why）。
```

落点验证（现读产物 `mod/common/static_modifiers/sitai_ru_defeat_pressure.txt:3-6`）：

```
# 处境压力（A 级）：俄罗斯 · 战败求存。基线档的每条字段照原版同族用法取档位，
# 每条的依据见 sitai_ru_defeat.md（由 why_report 生成）。
# 叠加档 sitai_ru_defeat_pressure_capitulation：只在 has_variable = recent_capitulation 时由冲击效果额外挂上（基线档恒挂 ⇒ 处境牌的门在两种形态下都成立）。
# ⚠️ 叠加档的每条字段是「实测总量 − 原版基线档」的**差额**，**不是**原版同族用法里的一档（档位依据与「为什么是差额」见各条 why）。
```

改革侧输入那一段（`modgen.py:1470-1514 inputs_text`）本来**没有**这句，无需改；10 个档案的 pressure 产物共享这句模板，一并改准。

---

## 5. 对抗演示：闸门强度没降（命令 + 输出，留档）

**设计**：把 `mod/data/ru_defeat.toml:124`（`[pressure.escalation]` 的判据）换成**原版不写、我们也不写**的探针名 `sitai_probe_gate_refs_never_written`，**同时保留** `:174`（`[reform_inputs.escalation]`）的 `recent_capitulation` —— 一次运行同时看两侧：原版记号不再假红、假名字仍然红。注入与还原在**同一条命令**里用 `try/finally` 完成，结束后逐字节比对 sha256。

```powershell
$p='mod/data/ru_defeat.toml'; $probe='sitai_probe_gate_refs_never_written'
$sha0=(Get-FileHash $p -Algorithm SHA256).Hash.ToLower(); Copy-Item $p $bak -Force
try {
  # 只替换 :124 那一对（variable + modifier 两行），:174 原样保留
  [System.IO.File]::WriteAllText((Resolve-Path $p), $text.Replace($old, $new), [Text.UTF8Encoding]::new($false))
  & .venv/Scripts/v3.exe modguard            # ← 期望红
} finally {
  Copy-Item $bak $p -Force                   # 逐字节还原
  & .venv/Scripts/v3.exe modguard            # ← 期望回到绿
}
```

**① 改前（干净树）** —— `EXIT=0`：

```
│ ✅ │ ① 键 / 路径与原版不相交（含 F7 命名空间与平铺）                   │ 路径、键、命名空间、平铺四项全过：与原版零交集         │
│ ✅ │ ② 引用完整性（变量 / JE / 修正 / 图标 / 本地化键 / defines 参数） │ 引用全部解析得到：6 类逐个核过，零缺失                 │
│ ✅ │ ③ 稀释预算（按阶段 2 的三槽价格表定价）                           │ 1 张牌，各槽占用 political 54.8%（预算 60%）           │
│ ✅ │ ④ 往返净度（生成 → 解析回来 → 与数据源一致）                      │ 数据源与产物逐条一致：无丢失字段、无多余字段           │
│ ✅ │ ⑤ 生成可复现 + why 非空 + 盘上产物确实由生成器产出                │ 两次生成逐字节一致、why 全非空、盘上产物与生成结果一致 │
五道闸门全过 ✅
```

**② 注入探针后**（`Select-String` 现读：`124: variable = "sitai_probe_gate_refs_never_written"`、`174: variable = "recent_capitulation"`）—— `EXIT=1`：

```
│ ✅ │ ① 键 / 路径与原版不相交（含 F7 命名空间与平铺）                   │ 路径、键、命名空间、平铺四项全过：与原版零交集 │
│ ❌ │ ② 引用完整性（变量 / JE / 修正 / 图标 / 本地化键 / defines 参数） │ 1 处引用解析不到（缺引用即红）                 │
│ ✅ │ ③ 稀释预算（按阶段 2 的三槽价格表定价）                           │ 1 张牌，各槽占用 political 54.8%（预算 60%）   │
│ ✅ │ ④ 往返净度（生成 → 解析回来 → 与数据源一致）                      │ 数据源与产物逐条一致：无丢失字段、无多余字段   │
│ ❌ │ ⑤ 生成可复现 + why 非空 + 盘上产物确实由生成器产出                │ 2 处不满足（可复现 / why / 盘上一致）          │
  变量：定义 9 个，被判据引用 11 个（原版写入池 614 个）
  本地化：english 65 键、simp_chinese 65 键
  ❌ 引用了一个我们从未写下的变量：sitai_probe_gate_refs_never_written（原版 set_variable 也没写过这个名字）
```

读数三条：① 加了探针，`被判据引用` 从 10 变 11，**原版池仍是 614**；② 假名字被判红（点名到名字），而同一份输出里**保留的 `recent_capitulation`（:174）没有红** ⇒ 假阳性修好、真阳性还在；③ 闸门 ⑤ 的这条红是**预期副产物**——这次演示只改数据源、故意不重跑 `v3 modgen --write`，于是盘上产物与数据源不再逐字节一致 ⇒ ⑤ 判红。顺带证明「改源不重生成」也拦得住。

**③ 还原**（`finally` 里，同一命令内）：

```
== [4] 还原：sha256 相等 = True（78dba2edee9f487c5f6be04da3a71cb6c32aca1b6035218f9593e97e651f608f）; 备份已删 = True =====
五道闸门全过 ✅   EXIT=0
```

⇒ 还原后与改前**逐字节相同**（sha256 一致），工作树无残留（临时备份已删）。

---

## 6. 验收命令逐条读数（合同顺序）

| # | 命令 | EXIT | 现读证据 |
| --- | --- | --- | --- |
| 1 | `.venv/Scripts/v3.exe modguard` | **0** | `五道闸门全过 ✅`；② 明细 `引用全部解析得到：6 类逐个核过，零缺失`；③ `1 张牌，各槽占用 political 54.8%（预算 60%）`；④ `无丢失字段、无多余字段`；⑤ `两次生成逐字节一致、why 全非空、盘上产物与生成结果一致` |
| 2 | `python -m pytest tests/test_modguard_offline.py tests/test_modgen.py -q -n0` | **0** | `89 passed in 14.26s`（基线 `4 failed, 81 passed`）；新增对抗/池用例在 `tests/test_modguard_offline.py:303/329/349/368` |
| 3 | `python -m ruff check .` | **0** | attempt 2 复跑：`All checks passed!`。attempt 1 当时读到 `Found 7 errors`（全在未跟踪的 `.t4-scratch/`）；残留已由队长移出仓库 —— 见 §7 闭环 |
| 4 | `python -m ruff format --check .` | **0** | attempt 2 复跑：`249 files already formatted`。attempt 1 当时读到 `4 files would be reformatted`（`.t4-scratch/` 3 个 + `tools/probe/frozen/README.md`）；前者已移出仓库、后者已由 `t24` 修掉 —— 见 §7 闭环 |
| 5 | `python -m mypy --no-incremental` | **0** | `Success: no issues found in 146 source files` |
| 6 | `.venv/Scripts/v3.exe modgen --write  &&  .venv/Scripts/v3.exe modgen --check` | **0** | `盘上 69 个产物与数据源逐字节一致 ✅` |

**旁证（非合同命令；attempt 3 复跑，现读 2026-10-01 00:14）**：`v3 modguard --offline` 同样 **EXIT 0 / 五道闸门全过 ✅**，明细里也有 `变量：定义 9 个，被判据引用 10 个（原版写入池 614 个）`、`本地化：english 65 键、simp_chinese 65 键` —— 这条证明**变量池真的进了离线通道**（池来自刷新后快照的新域 `vanilla_variables`，不是在线的特例），也正是「把池放进 `src/pdx/vanilla_index.py`（原版索引 + 快照域注册表）而不是塞进 `modguard.py`」这一设计选择的直接收益：CI 的 `v3 modguard --offline` 现在同样能判变量引用。同一批复跑里另五条读数：`pytest … -q -n0` **89 passed in 14.48s**、`ruff check .` **All checks passed!**、`ruff format --check .` **249 files already formatted**、`mypy` **146 source files**、`modgen --check` **69 个产物逐字节一致**（与上表逐条一致）。

**测试侧的两点如实说明**：

1. 新增 4 个用例：`test_变量池只收原版自己写下的名字`（合成原版树：`set_variable = { name = … }` 收，`set_global_variable` / `name = root.x` / 只读 `has_variable` 不收）、`test_变量池在场时假变量仍然判红`（**对抗用例**）、`test_变量池整域缺席时逐条列未覆盖而不是假红`（旧快照路径）、`test_原版变量池来自现读安装目录_原版记号不假红而假变量仍判红`（现读游戏树；无游戏树的机器按 `_needs_game_tree` 显式跳过并点名缺的路径）。
2. 写用例时踩到的坑（留档）：探针**不能**直接写成效果体里的 `has_variable = X`——`modgen.readback` 的事实表按产物结构反解，那种写法根本不会被收进事实表，探针会静默失效、闸门照样绿；要包成 `if = { limit = { has_variable = X } }`（或写进 JE 的 `possible` 门）。
3. 另一处**必要**的越界（见 §8）：`tests/test_modgen.py:340` 原来硬断言 `len(archive.localization) == 15`，本卡给它加了 2 条键 ⇒ 同步为 `== 17`，并补了一行注释说明这 2 条是哪来的。

---

## 7. 曾经的两条 ruff 红：外部残留 —— 已闭环（attempt 2）

**闭环结论（先给结果）**：队长裁决「外因成立」并把残留**移出仓库**之后，本卡 attempt 2 复跑 **6 条验收命令全绿**（`ruff check .` EXIT 0、`ruff format --check .` EXIT 0、`mypy --no-incremental` EXIT 0，见 §6）。本节保留 attempt 1 当时的历史读数与归属证据，并撤回一条我自己说错的判断。

**当时的读数（历史，2026-10-01 00:05 前后，如实留档）**：合同验收里的 `ruff check .` 与 `ruff format --check .` 在这棵共享工作树上各 `EXIT=1`，**原因 100% 不在本卡改动**：

- `ruff check .` → `Found 7 errors`，**7 条全在未跟踪的 `.t4-scratch/`**：`data_copy.py:59:42 B905`、`t4-snapdiff.py:94:41 FURB110`、`t4-truth.py:79:13 SIM102`、`t4-truth.py:102/103/104:27-30 E741`、`t4_data_patch.py:22:5 PLC0415`。
- `ruff format --check .` → `4 files would be reformatted`：`.t4-scratch/data_copy.py:45:22`、`.t4-scratch/t4-snapdiff.py:59:10`、`.t4-scratch/t4-truth.py:47:6`、`tools/probe/frozen/README.md:33:1`。
- **归属证据**：这 5 个文件在 `git status --porcelain` 里全是 `??`（未跟踪）；mtime = `.t4-scratch/*` 2026-09-30 00:15:16–00:19:13、`tools/probe/frozen/README.md` 2026-09-30 05:28:34 —— 都**早于本卡开工（23:37）**；`pyproject.toml:227-237` 的 `extend-exclude` 只排除 `.venv`、`tools/out`、`docs/reports`、`research/official-docs`，不含这两处；两者都不在本卡 in-scope 列表里。
- **隔离读数（同一棵树，命令与输出）**：

```
$ .venv/Scripts/python.exe -m ruff check . --extend-exclude .t4-scratch,tools/probe/frozen
All checks passed!                                                            EXIT=0
$ .venv/Scripts/python.exe -m ruff format --check . --extend-exclude .t4-scratch,tools/probe/frozen
255 files already formatted                                                   EXIT=0
$ .venv/Scripts/python.exe -m ruff check src/pdx/modguard.py src/pdx/vanilla_index.py src/pdx/modgen.py tests/test_modguard_offline.py tests/test_modgen.py
All checks passed!                                                            EXIT=0
$ .venv/Scripts/python.exe -m ruff format --check src/pdx/modguard.py src/pdx/vanilla_index.py src/pdx/modgen.py tests/test_modguard_offline.py tests/test_modgen.py
5 files already formatted                                                     EXIT=0
```

⇒ 排除这两簇后两条命令 EXIT 0；本卡 in-scope 的五个代码/测试文件单独跑也 EXIT 0。**本卡自己改出来的唯一格式红**（`tests/test_modguard_offline.py:378:42`，我拼字符串换行的写法）已用 `ruff format tests/test_modguard_offline.py` 修掉（`1 file reformatted`）。

**闭环处置（attempt 2，现读）**：队长做了三件现读处置 —— ① 把 `.t4-scratch/`（23 件）与 `pytest-of-28905/`（82 件）**移出仓库**（可逆，落在 `%TEMP%\situated-residue-t4-scratch` 与 `%TEMP%\situated-residue-pytest-of-28905`，**未删除**）；② `tools/probe/frozen/README.md` 的 `ruff format` 点由卡片 `t24`（D24）修掉；③ 两条门禁复跑即绿。我复跑（现读 2026-10-01 00:12）：`ruff check .` **EXIT 0 / `All checks passed!`**、`ruff format --check .` **EXIT 0 / `249 files already formatted`**、`mypy --no-incremental` **EXIT 0 / `146 source files`**；`Test-Path` 现读两簇残留均为 `False`，且**复跑 pytest 之后没有重新生成**（`pyproject.toml:166` 明写「不设 `--basetemp`」、`tmp_path` 不落在仓库内 —— 这条对收口「清零残留」有用）。

**一条更正（我先前说错了，在此撤回）**：本报告早前版本写着 `tools/probe/frozen/README.md`「**内容本身是乱码（GBK 解码残渣）**」。**这条没有字节级证据、是错的**：我当时依据的只是 **PowerShell 控制台的解码显示**（`Select-String` / 管道输出在 zh-CN 代码页下把 UTF-8 中文渲染成 `鍒よ锛?True` 之类），我据此推断文件编码坏了 —— 属越界推断，不是现读事实。字节现读（当前版本）：`tools/probe/frozen/README.md` = **3,985 B / mtime 2026-10-01 00:06:40 / BOM=False / CR=0 / LF=59 / 严格 UTF-8 解码 VALID / sha256 `4A2785105284A72F…`**，与队长同时段的字节现读一致 ⇒ **不存在编码 bug**，请后人别再追这条。仍然成立的一条小提示（不是缺陷）：`pyproject.toml:229-231` 那句注释「ruff 本来就不检查非 Python 文件」对现装的 ruff 0.16.7 已不准确 —— 它会格式化 Markdown 里的 Python 代码块，所以 `tools/probe/frozen/README.md` 那类文件也会被 CI 的 format 闸门点中。

**当时的处置请求与结论**：我没有自行处理这些路径（不在本卡 in-scope 列表内，且删除/改写队友**在飞**产物有破坏风险），只把归属证据与隔离读数摆出来请队长裁决 ⇒ 队长认定外因成立、亲自清理残留，并追认了两处越界（§8）。

**终态复跑（本报告改定之后，2026-10-01 00:13，六条逐条）**：`modguard` **0**（`五道闸门全过 ✅`）／`pytest … -q -n0` **0**（`89 passed in 14.68s`）／`ruff check .` **0**（`All checks passed!`）／`ruff format --check .` **0**（`249 files already formatted`）／`mypy --no-incremental` **0**（`Success: no issues found in 146 source files`）／`modgen --write` + `--check` **0**（`盘上 69 个产物与数据源逐字节一致 ✅`）；残留复检 `.t4-scratch=False / pytest-of-28905=False` ⇒ **本卡无未达成项**。

---

## 8. 越界披露（两处，都是必要的前置，已如实记）

1. **入库快照刷新**（`v3 snapshot create --compact`，属 `t2`「A3 机械刷新链」名下的步骤）：本卡跑了它，因为验收要求那两份测试文件全绿，而唯一的非本卡红是 1.14.4 快照 vs 1.14.5 游戏（`common/scripted_effects` 多一个 `ai_assemble_decree_state_maps`）—— 正是仓库演练链里「`v3 snapshot create --compact` 刷新入库快照（否则离线通道会红）」那一步。现读：`EXIT=0`、**28.9 s**、新文件 `tools/out/snapshots/release-1.14.5.compact.json`（6,414,833 B / 2026-10-01 00:01:32 / sha256 `4c077a010481ef1d…`）；新域 `vanilla_variables` 在快照里 2 目录 / 642 条目（**并集 614**，642 是两目录条目数之和）；`snapshot_index().variables()` 与游戏现读并集**相等**（现读 `True`）。旧 `release-1.14.4.compact.json` 未动。
2. **`tests/test_modgen.py` 的计数同步**（15 → 17）：数据源加了 2 条键之后的必然同步，不是放宽 —— 该断言旁逐项列着组成（4 基础 + 2 面板 + 2 叠加档显示名 + 难度 7 + 玩家侧 2），我补的那行注释写清这 2 条是 B35 叠加档的显示名。

---

## 9. 现读读数表（size / mtime / sha256 前 16；现读时间 2026-10-01 00:06:09）

| 文件 | size | mtime | sha256（前 16） |
| --- | --- | --- | --- |
| `src/pdx/vanilla_index.py` | 22659 | 2026-09-30 23:56:03 | `6444a174462f2255` |
| `src/pdx/modguard.py` | 41877 | 2026-09-30 23:56:25 | `aced85863dee4d8a` |
| `src/pdx/modgen.py` | 121900 | 2026-09-30 23:57:05 | `9a19e913d5c403cf` |
| `mod/data/ru_defeat.toml` | 60878 | 2026-09-30 23:56:51 | `78dba2edee9f487c` |
| `tests/test_modguard_offline.py` | 18871 | 2026-10-01 00:05:07 | `42b1bb8d3a5240d3` |
| `tests/test_modgen.py` | 59507 | 2026-10-01 00:02:20 | `d657c56358359c86` |
| `tools/out/snapshots/release-1.14.5.compact.json` | 6414833 | 2026-10-01 00:01:32 | `4c077a010481ef1d` |
| `mod/common/static_modifiers/sitai_ru_defeat_pressure.txt` | 1178 | 2026-10-01 00:05:29 | `209eb3f42c1d0e68` |
| `mod/localization/english/sitai_ru_defeat_l_english.yml` | 2725 | 2026-10-01 00:05:29 | `e11419256f22ad63` |
| `mod/localization/simp_chinese/sitai_ru_defeat_l_simp_chinese.yml` | 2310 | 2026-10-01 00:05:29 | `0deaa23fef1cfdd7` |

环境读数：`ruff 0.16.7`；`v3 modguard` 1.8 s 量级；`modgen --write` + `--check` 共 < 10 s；快照刷新 28.9 s。

> **attempt 2 复核（2026-10-01 00:12 现读）**：上表 10 个文件的 **sha256 逐个与 attempt 1 相同**（内容一字未动）；只有产物 mtime 被 attempt 2 那次 `modgen --write` 刷新到 **2026-10-01 00:10:30**（9 个 `mod/common/static_modifiers/sitai_*_pressure.txt` + 2 个 `mod/localization/{english,simp_chinese}/sitai_ru_defeat_l_*.yml`）——**字节内容不变**（`modgen --check` 的「69 个产物与数据源逐字节一致 ✅」正是这个意思）。另一条现读：复跑 pytest 之后仓库内**没有**重新出现 `pytest-of-28905/`（`pyproject.toml:166` 明写不设 `--basetemp`）。

---

## 10. 改动清单与复现命令

**本卡改动/新增的路径**（工作区相对 POSIX）：

```
src/pdx/vanilla_index.py                                        # 变量池：常量 / 抽取 / 快照域 / 访问器
src/pdx/modguard.py                                             # 闸门 ② 的变量判据（三态）
src/pdx/modgen.py                                               # 叠加档概括句改准 + 新增警示行
tests/test_modguard_offline.py                              # 4 个新用例（含对抗）+ 2 个辅助
tests/test_modgen.py                                        # 本地化计数 15 → 17（同步）
mod/data/ru_defeat.toml                                           # 2 个 [[localization]]（2 键 × 2 语言）
mod/common/static_modifiers/sitai_{au_revolution,brz_market_loss,bv_alignment,cn_intervention,
        eg_debt,pe_great_game,ru_defeat,sp_empire_remnant,tr_defeat}_pressure.txt   # 改准的模板句（9 个）
mod/localization/english/sitai_ru_defeat_l_english.yml            # +2 行
mod/localization/simp_chinese/sitai_ru_defeat_l_simp_chinese.yml  # +2 行
tools/out/snapshots/release-1.14.5.compact.json                   # 新（越界刷新，见 §8）
docs/reports/A1-modguard修复.md                                  # 本报告
```

生成物影响面（如实）：`modgen --write` **重写了全部 69 个产物**（mtime 都变成 00:05:29，所以 mtime 不能当内容变化的证据）。按生成器影响面推断 + grep 现读，**内容**只可能变上面那 11 个产物文件：9 个 `*_pressure.txt`（改准的模板句，grep 命中 9），其中 `sitai_ru_defeat_pressure.txt` 另加警示行（它是唯一有 `[pressure.escalation]` 的档案，grep 命中 1），加 2 个本地化 yml。`mod/sitai_ru_defeat.md` **不含**那句模板句（grep 现读），它的 `M` 状态是 B35 遗留、不是本卡。

**复现命令**（顺序即验收顺序）：

```powershell
.venv/Scripts/v3.exe modguard                                                    # 0，五道闸门全过
.venv/Scripts/python.exe -m pytest tests/test_modguard_offline.py tests/test_modgen.py -q -n0   # 0，89 passed
.venv/Scripts/python.exe -m ruff check .                                         # 0，All checks passed!
.venv/Scripts/python.exe -m ruff format --check .                                # 0，249 files already formatted
.venv/Scripts/python.exe -m mypy --no-incremental                                # 0，146 source files
.venv/Scripts/v3.exe modgen --write  ;  .venv/Scripts/v3.exe modgen --check      # 0，69 产物逐字节一致
```

对抗演示的完整命令与三段输出见 §5；沙箱内注入/还原都在同一条命令里完成，`finally` 保证还原，收尾读数是 sha256 相等 + `五道闸门全过 ✅`。
