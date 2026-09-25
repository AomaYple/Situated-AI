# t64 三条 finding 的收口复验（t85）

**卡的身份**：`kind=repair`、`sourceTaskId=t64` —— `t64` 因 `needs_revision` 被 harness 记成 failed，本卡是挂在它名下的那张 repair（Delivery 上「failed 卡没有挂在它名下的 repair」这条硬账的收口）。
**本卡不重复实现任何修复**：F1/F2 的实现是 **t73**（评审员）、F3 库侧是 **t83**（功能工程师）；我只做**独立复验**，且**每个判决性数字都是我自己现算或自己数出来的**（可以复用产物，不许转抄自述）。

## §0 三条判决（先说结论）

| finding | 判决 | 判决依据（一句话） |
|---|---|---|
| **F1**（`on_actions_text()` 钩子语法，blocker） | ✅ **已收口** | 生成物里 `on_monthly_pulse_country` 块体**只有** `on_actions`（无 `effect` 键、无脚本效果调用），被转调名在同文件 `:14` 有 `effect = {` 定义并调用脚本效果；实机 `error.log` 点名我们文件的行 **9 → 0**，两臂自报 WAR×5 |
| **F2**（革命潮段少 `limit = {`，blocker） | ✅ **已收口（生成物级）** | `scripted_effects` 里 `if = {` **53** 处、**缺 `limit = {` = 0**；8 国比较被包进**同一个 `OR = { }`**（我数到 8 个 `c:<TAG>`）；`v3 preflight` 压力剧本体检 ✅ ⚠️ **实机级**（RADICAL 8 行）由 **t86** 在 t22 那一局判 —— 见 §3 的教训 |
| **F3**（单臂「0 行⇒出声」+ `HEALTH_ERROR_MARKERS` 未接压力臂，medium） | **库侧 ✅ 已收口 / runner 侧 ✗ 仍未做** | 库侧：`probe_lint` 三条规则都在、`preflight` 覆盖压力剧本产物且我实跑那一行 ✅（exit 0）；runner 侧：`perf_compare.py` 里 **没有** `HEALTH_ERROR_MARKERS`、**没有**任何「0 行⇒出声」逻辑 ⇒ 照实写「仍未做」并给补卡建议（§4） |

## §1 三独立与所验身份（我核的是哪些字节）

* **独立性**：`t73` 是 **评审员**、`t83` 是 **功能工程师**；我**没有写过** `stress_probe.py` / `test_stress_probe.py` / `probe_lint.py` / `preflight.py` 的任何一版 ⇒ 本卡由「没写过那份生成器」的一方执行 ✓。
* **我现读的身份**（`sha256[:16]`，全部我自己算）：

| 文件 | bytes | LF | sha16 |
|---|---|---|---|
| `tools/pdx/stress_probe.py`（t73 的实现） | 34,083 | 617 | `870ddf62baab5d14` |
| `tools/tests/test_stress_probe.py`（t73 的用例） | 34,362 | 679 | `cab64dc665aefc82` |
| `tools/pdx/probe_lint.py`（t83 的规则） | 27,665 | 588 | `d8c82e3b9125c6ed` |
| `tools/pdx/preflight.py`（t83 的接线） | 23,914 | 524 | `419244ca0eec284e` |
| `tools/probe/perf_compare.py`（runner 侧，**t71 独占，本卡未动**） | 35,490 | 733 | `6bfd69633ecd497a` |

`git status --porcelain`：**94 行**，整份文本留档 `%TEMP%\t85-git-status.txt`（sha256[:16] `42d0dc33db8efbec`）。

## §2 F1/F2：**生成物级**证据（`stress_probe.files()` 现生成，不看自述）

现数脚本：`%TEMP%\t85_recompute.py`（自写；`files = stress_probe.files()` 后按**花括号配对**取块、逐行去注释）。产物清单 = `.metadata/metadata.json` + `common/on_actions/zz_stress_on_actions.txt`（**793 B / 18 行**）+ `common/scripted_effects/zz_stress_effects.txt`（**7,941 B / 314 行**）。

**F1 一侧**（`zz_stress_on_actions.txt`）：

```
on_monthly_pulse_country 块体（去注释）逐行 = ['on_actions = { zz_stress_monthly_tick }']
块内顶层键 = ['on_actions']                         ⇒ 只有 on_actions = True
块内有 `effect` 键 = False；块内有脚本效果调用 = False
被转调的名字 = zz_stress_monthly_tick
同一份文件里有它的顶层定义 = True（:14）
整份文件 `effect = {` 计数 = 1
该定义块内调用脚本效果 = True
```

⇒ 与卡文要求的四条逐条对上：**块内只有 `on_actions`** ✓、**无脚本效果调用** ✓、**无 `effect` 键** ✓、**被转调名在同文件有 `effect = { … }` 定义并调用脚本效果** ✓。

**F2 一侧**（`zz_stress_effects.txt`）：`if = {` 计数 = **53**；**缺 `limit = {` 的处数 = 0** ✓（同一支脚本还核了：`OR = {` 计数 = 2、`limit = { OR = {` = 1、该 `OR` 内 **8 个** `c:<TAG>`：AUS/CHI/FRA/GBR/PRU/RUS/TUR/USA）⇒ 与卡文 F2 的验收（缺 `limit` = 0）一致 ✓，且 8 国比较是**同一个 `OR`**（不是平铺成 AND —— 那正是 t73 实机里 RADICAL 0 的成因）✓。

## §3 F1 的判决性证据：实机（**取法 (b)：复用 t73 那一局的产物 + 我亲手重验**）

> **本卡的实机读数来自 t73 那一局的产物，不是本卡自己起的局。**

我逐个重算（bytes / sha256[:16] / 行数 / 点名我们文件的行数，**全部我自己数**）：

| 档 | error.log bytes | sha16 | 总行 | **点名我们文件的行** |
|---|---|---|---|---|
| **改前**（`v3probe-logs-archive\t64-剧本首跑-031917\error.log`） | 19,451 | `287e84a3c6165267` | 136 | **9** |
| 改后 t73 `vanilla-arm-logs\error.log` | 18,687 | `781aa9810a809c6b` | 124 | **0** |
| 改后 t73 `ours-arm-logs\error.log` | 18,290 | `c849afae58ff7495` | 126 | **0** |

⇒ **`error.log` 里提到我们文件的错误行数：9 → 0** ✓（卡文的硬要求：必须是 0 ✓），且改前那 9 行 = 8 条 `Unknown effect`（F2）+ 1 条 `Unexpected token`（F1）—— 两类症状都消失了 ✓。
首波自报（我自己在 `debug.log` 里数）：vanilla 臂 **WAR = 5**、ours 臂 **WAR = 5** ✓（两臂逐字一致）。
`debug.log` 身份：vanilla 283,317 B / `bab5bc272a7f96a2`；ours 284,676 B / `2e2fd4ba8c422b0c` ✓。

⚠️ **一条必须连带说的教训（t73 自己记的，我复算证实）**：那一局两臂的 **RADICAL 行都是 0** ⇒ 那一局是在 F2 的 `OR` 修复**之前**跑的 ⇒ **它的「error.log 0 行」不能当 F2 的证据**（0 行却恒假 —— 静默失效）。所以：F1 的实机证据成立 ✓；**F2 的实机确认属 t86**（t22 那一局），本卡只给生成物级证据 ✓。

## §4 F3：两半分开判

**① 库侧（开局前）—— ✅ 已收口**（t83 的产出 + 我实跑）：
* `probe_lint.py` 三条规则都在（`on_action_allowed_keys` / `limit_scope_flattenings` / `if_blocks_without_limit` = True/True/True，我现读源码）；
* `preflight.py` 里出现过 `stress_probe` 与 `压力剧本体检`（我现读源码）⇒ 压力剧本产物**进体检清单** ✓；
* **我实跑**：`.venv\Scripts\v3.exe preflight` ⇒ **exit 0**，其中那一行 = **`✅ 压力剧本体检：2 个 on_action 顶层键 + 52 … 全合法`** ✓；（另外两个 ❌ 行 = 用户配置（WRONG 档：23 个 workshop mod 的清单可核对后删）与 日志干净（WRONG 档：上一局探针自报 228 行仍在 debug 日志里，建议加 `--fresh-logs`）—— **都与本卡判据无关**；`产物一致 = 68` 是**别人在制**带出来的计数（文档里是 67），不是 t73/t85 引入）。

**② runner 侧（单臂/侦察遇到「0 行」或命中 `HEALTH_ERROR_MARKERS` 要出声）—— ✗ 仍未做**：
* 我现读 `tools/probe/perf_compare.py`（**未改动它**，35,490 B / `6bfd69633ecd497a`）：**没有** `HEALTH_ERROR_MARKERS` 这个名字，也**没有**任何「0 行 / expected_lines / 没命中⇒出声」逻辑 ⇒ 这一半**仍未做** ✓（与卡文预期一致）。
* **补卡建议**：`tools/probe/perf_compare.py` 归 **t71** 独占 ⇒ 建议**另开一张卡**（或并进 t71 的收口）实现：侦察/单臂路径在「自报 0 行」或命中 `HEALTH_ERROR_MARKERS` 时必须**出声**（非零退出或显著告警），并配一条「喂 0 行输入 ⇒ 判红」的用例。**本卡不动那个文件** ✓。

## §5 环境与证据纪律

* **本卡没有自己起局** ⇒ 不需要 START/END（台账里我不会写跑局行）；**也没有轮转/覆盖任何日志** ✓；
* 顺手核了环境完整性：`content_load.json` = **2,166 B / sha16 `d553ffe23a54c062`** —— 与备份基准（2,166 B / `D553FFE23A54C062`）**逐字节相同** ✓（说明 t73/t34 之后环境是干净的 ✓）；
* 我写盘的只有：本报告 + `%TEMP%` 下的脚本/留档（`t85_recompute.py` / `t85_readings.md` / `t85-git-status.txt`）+ 台账追加 ✓。

## §6 可复核命令原文与退出码（全部我自己跑过）

| 命令 | 结果 |
|---|---|
| `.venv\Scripts\python.exe -m pytest tools/tests/test_stress_probe.py tools/tests/test_probe_lint.py -q -n 0` | **80 passed in 3.77s**，exit **0** |
| `.venv\Scripts\python.exe -m ruff check tools` | `All checks passed!`，exit **0** |
| `.venv\Scripts\python.exe -m ruff format --check tools` | `161 files already formatted`，exit **0** |
| `.venv\Scripts\v3.exe preflight` | exit **0**；`✅ 压力剧本体检：2 个 on_action 顶层键 + 52 个 if + 52 个 limit 全合法` |
| `python %TEMP%\t85_recompute.py`（我自写的生成物与归档现数脚本） | 见 §2/§3；读数落 `%TEMP%\t85_readings.md` |

## §7 三条 finding 的最终判决（照 §0）

1. **F1 = 已收口**：生成物四条逐条对上 + 实机 9→0 + 两臂 WAR×5（取法 (b)，已逐字声明）✓
2. **F2 = 已收口（生成物级）**：缺 `limit` = 0 + 8 国在同一 `OR` + preflight ✅；**实机级待 t86**（t73 那一局 0 行不能当 F2 证据 —— 教训已写进 §3）✓
3. **F3 = 库侧已收口 / runner 侧仍未做**：库侧见 §4①（含我实跑的 preflight），runner 侧见 §4②（补卡建议已给，且明写 `perf_compare.py` 归 t71）✓
