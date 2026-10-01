# A1b —— 扩 `_fake_game` 夹具（1.14.5 原版钩子 + `recent_capitulation`）

卡：`t26 — D25：扩 _fake_game 夹具（加原版 on_actions 钩子 + recent_capitulation），别放宽闸门`（attempt 1）。
一句话：`tests/test_modguard.py::test_真档案的五道闸门结论可复算` 的红，根因是**假游戏树缺 1.14.5 原版面上真有的东西**；补在夹具上（25 行、0 删除），闸门判据一行未动。

| 项 | 改前 | 改后 |
|---|---|---|
| 单条 `test_真档案的五道闸门结论可复算` | **FAILED**（闸门 ② 4 处 ❌） | **1 passed** |
| `pytest test_modguard.py test_modguard_offline.py -q -n0` | **1 failed, 58 passed** | **59 passed** |
| `tests/test_modguard.py` | **28,771 B**（= HEAD blob `2ed5588aada95b75b3b457469ea9f680f627f302`，相对 HEAD 零改动） | 30,422 B（+1,651 B）/ 2026-10-01 00:51:49 / sha256 `F08A51F0E5014FC9AE2D04C1A8BB9DF6CCE27708DEFD518FE6DA5F83FD0B9E07` |
| 改动形状 | —— | `git diff --numstat` = **25 insertions, 0 deletions**（全部落在 `_fake_game` 的 `return game` 之前） |

## 一 改前 / 改后夹具差异

`_fake_game` 的定位（文件内注释现读）是「按原版目录结构造一份最小的『游戏』，每一块都对应闸门 ② 的一个解析来源」。改前它有 8 块：修正池（含字段名）、JE 池、JE 分组、词汇表（scripted_effects + scripted_triggers）、国家 tag、defines 命名空间、ai_strategies、13 个图标文件 —— **没有 `common/on_actions/`**，`common/scripted_effects/00_vanilla_effects.txt` 里也只写了一个 `vanilla_memory`。

改前红（现跑，闸门 ② 共 4 处）：

```
❌ 引用了一个我们从未写下的变量：recent_capitulation（原版 set_variable 也没写过这个名字）
❌ 原版里找不到这个原版触发器名：on_capitulation（数据源 references 里声明的）
❌ 原版里找不到这个原版触发器名：on_wargoal_enforced（数据源 references 里声明的）
❌ 原版里找不到这个原版触发器名：on_actions（数据源 references 里声明的）
```

四处**都是 1.14.5 原版面上真有的东西**（现读出处）：

- `game/common/on_actions/00_code_on_actions.txt:4214`：`on_capitulation = {`；`:6288`：`on_wargoal_enforced = {`；同目录另有 **11 处** `on_actions =` 字段（我们的产物正是用 `on_actions = { … }` 往原版钩子上追加包装，见 `mod/common/on_actions/sitai_ru_defeat_on_actions.txt:9-13`，数据源据此声明三条 trigger 引用 `mod/data/ru_defeat.toml:371-383`）。
- `game/common/on_actions/00_code_on_actions.txt:4222`：`name = recent_capitulation`（在 `on_capitulation` 的 `effect = { … }` 里，`:4216-4224`）；读侧 `game/events/discrimination_events.txt:222`：`has_variable = recent_capitulation`。

改后（现读行号）：`:225-238` 出处注释，`:239-248` 新增一处 `_write`：

```
:239  game / "common" / "on_actions" / "00_code_on_actions.txt",
:242  set_variable = { name = recent_capitulation days = short_modifier_time }
:245  on_actions = { }
:247  on_wargoal_enforced = { on_actions = { } }
```

形状照原版：钩子 → `effect = { set_variable = { name = … days = … } }`，另加 `on_actions` 字段。三个「触发器名」从**词汇表池**进来（`src/pdx/vanilla_index.py:80-85 VOCABULARY_DIRS` 含 `common/on_actions`，且 `vocabulary_dir()` 收**任意深度**的键名）；`recent_capitulation` 从**变量池**进来（`src/pdx/vanilla_index.py:90-97 VARIABLE_POOL_DIRS = ("common","events")` + `variable_names()` 只认 `set_variable` 块内直接子赋值 `name = <identifier>`）。

## 二 为什么这不是「放宽闸门」

判据（`src/pdx/modguard.py` 的闸门 ② 与 `src/pdx/vanilla_index.py` 的池抽取）**本卡一行未改**，可验的三个事实：

1. `git diff --numstat -- tests/test_modguard.py` = `25  0  tests/test_modguard.py` —— **纯插入、零删除**，且 25 行全部落在 `_fake_game` 内部（`return game` 之前）：没有 `skip` / `skipif` / `xfail` / `noqa`，没有任何断言被删或改松（唯一改动的文件就是夹具所在的测试文件；`src/pdx/modguard.py` 不在本卡改动面）。
2. 补的是**原版真值**：三条 trigger 名与一个变量名都有现读出处（见上节），不是为让测试通过而编的名字；夹具的职责本来就是「合成一份够用的原版」，原版面上多了东西时补夹具正是它的维护方式（同族的先例：阶段 4 补 `TUR`、阶段 5 补 `AUS`/`CHI`、批次 3 补 `SPA`/`BAV`/`BRZ`，注释现读 `tests/test_modguard.py:192-196` 记着这三次）。
3. **对抗面没退化**（本卡实测，命令与输出见下节）：同一份扩后的夹具上注入一个「原版不写、我们也不写」的假变量引用 ⇒ 闸门 ② 仍判红，且同一跑里 `recent_capitulation` **不再**被判红。

```
A 扩夹具后基线：总体 ok = True | 闸门② ok = True
B 注入假变量 sitai_probe_t26_never_written（写进 common/scripted_effects/sitai_au_revolution_effects.txt）
 闸门② ok = False | 1 处引用解析不到（缺引用即红）| 总体 ok = False
 明细： ❌ 引用了一个我们从未写下的变量：sitai_probe_t26_never_written（原版 set_variable 也没写过这个名字）
C 同一跑里 recent_capitulation 被判红？ False
```

反向的力度由 A1 的判据保证：池在场 ⇒ 判红；池缺失（旧快照）⇒ 逐条记「未覆盖」而**不**静默通过（`src/pdx/modguard.py:501-516`）。本卡没有把「未覆盖」用成逃生门 —— 基线是**整体 ok = True 且闸门 ② ok = True**，即四个引用都真解析到了。

## 三 复现命令与读数

```powershell
# ① 改前（HEAD 夹具）/ 改后 同一条：
.venv/Scripts/python.exe -m pytest "tests/test_modguard.py::test_真档案的五道闸门结论可复算" -q -n0
#   改前 ⇒ 1 failed（闸门 ② 4 处 ❌：recent_capitulation + on_capitulation/on_wargoal_enforced/on_actions）
#   改后 ⇒ 1 passed in 0.82s

# ② 两个测试文件：
.venv/Scripts/python.exe -m pytest tests/test_modguard.py tests/test_modguard_offline.py -q -n0
#   改前 ⇒ 1 failed, 58 passed in 16.49s   （少掉的那条就是 ① 的那一条，改前唯一红）
#   改后 ⇒ 59 passed in 15.88s

# ③ 对抗演示（脚本写在 %TEMP%\t26-adv.py，不进仓库；跑的是现读代码 + 扩后的夹具）：
.venv/Scripts/python.exe "$env:TEMP\t26-adv.py"   # 输出见上节 A/B/C 三段

# ④ 门禁：
.venv/Scripts/python.exe -m ruff check .            # All checks passed!            EXIT 0
.venv/Scripts/python.exe -m ruff format --check .   # 249 files already formatted    EXIT 0
.venv/Scripts/python.exe -m mypy --no-incremental   # Success: no issues found in 146 source files  EXIT 0
```

现读读数（2026-10-01 00:52）：

| 件 | size | mtime | sha256 |
|---|---|---|---|
| `tests/test_modguard.py` | 30,422 B | 00:51:49 | `F08A51F0E5014FC9AE2D04C1A8BB9DF6CCE27708DEFD518FE6DA5F83FD0B9E07` |
| `docs/reports/A1b-夹具扩展.md` | 本文自身 | —— | 自引用不回填（改文件即失效）；现读 sha256 见 t26 结卡 output |

编码：两个文件均 **UTF-8 无 BOM + LF**（`BOM=False / CR=False / LF=True` 现读）；夹具里新增的原版文件由 `_write()` 以 `utf-8-sig` 写入（与原版 `.txt` 一致，也是本文件既有夹具的写法）。

一条边界说明：本卡的改前读数是本卡开工时（00:50 前）在同一棵工作树上现跑的；「这条红不是 A1 引入」的四组对照由验证员出（t6 卡面：该文件相对 HEAD 零改动、HEAD 数据源里那三个名字出现 0 次、HEAD 代码 + 现读 `mod/` 覆盖后同样红、`%TEMP%\t6-fix` 用约 10 行扩夹具 ⇒ 现读代码 `1 passed`）。本卡在其参考改法的基础上把夹具写得更贴原版（钩子里带 `effect = { set_variable = { name = recent_capitulation days = short_modifier_time } }`，与 `00_code_on_actions.txt:4216-4224` 同形），并补了出处注释与对抗演示。
