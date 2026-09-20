# exec · 阶段 4 侦察：`gametimer` 到底怎么开

> **任务**：阶段 4 `阶段4-框架化.md` §④ 的第一个未知 —— `gametimer` 的触发方式。
> **纪律**：开跑前 `python -m pdx.game_auto check`；装/卸 mod 与 `content_load.json` 走 `v3 experiment`；
> 跑完还原用户那 23 条启用列表；结束前停游戏。
>
> **本次结论提前说清**：**触发方式没找到**。但找到了比"怎么开"更值钱的东西 ——
> **12 份真实的 `gametimer_*.tsv` 已经在硬盘上**，于是列结构、粒度、
> 以及"单帧 ≤0.5ms 能不能量"这三件事**都不用再猜**了。
> 末尾逐条列出**已测 / 未测**。

---

## 0. 结论速览

| 路线 | 状态 | 依据 |
|---|---|---|
| ① 启动参数（`-gametimer` / `-gametimer=1` 等） | ❌ **不通** | exe 里 `gametimer` 全串只出现 **1 次**，就是文件名格式串本身；没有任何 `-gametimer*` 字面量 |
| ② 控制台 / 调试命令 | ❌ **不通**（按现有证据） | 控制台命令名在 exe 里是**明文**（例：`log_ticktask_performance`、`Camera.Restrictions`）。`gametimer` 只出现 1 次 ⇒ **不存在**叫这个名字的命令 |
| ③ 设置文件开关 | ❌ **不通** | `platform_specific_game_data\log_settings_live.json` 列了 **26 个 logger category**，**没有** `gametimer`（详见 §3） |
| ④ 其它（自动化/测试框架内部） | ⏳ **未测** | 字符串邻域显示它和 testmanager/automation 同处一堆（§4），但**没做实验** |
| ⑤ **旧构建曾经产出过** | ✅ **有实物为证** | **12 份 `gametimer_*.tsv`**（2026-09-13），见 §2 |

**最要紧的一条**：这 12 份文件的日期是 **09-13**，而 `binaries\victoria3.exe` 的
**LastWriteTime = 2026-09-16 22:16:06**（游戏内 `game_timestamp: 2026-09-15`）。
也就是说 **阳性证据全部来自更新之前的那一份构建**；更新之后我们用过的所有启动方式
（`-debug_mode`、`-debug_mode -scripted_tests`）**一份都没有再产出**。
「是构建变了」还是「当初用了别的启动方式」—— **两者都未被排除，属未测**。

---

## 1. 触发方式的三条明路：怎么试的、看到什么

### ① 启动参数

原始命令与输出（全 exe 逐字节扫描，97,292,920 字节）：

```text
候选 -参数: ['-abandoned', '-b31', '-be7', '-beta', '-blendu', '-blendv', '-boost',
 '-bounded', '-c6r', '-cached', '-clamp', '-contained', '-debug_mode', '-deferred-',
 '-dirs', '-exported-', '-extended', '-filewa', '-gwb', '-hfu', '-ikk', '-imfchan',
 '-inpuu', '-mgi', '-noretire', '-nosymbols-', '-qi2', '-qxr', '-r0j', '-texres',
 '-type', '-unknown-', '-y16', '-zm_', '-zoe']
  skip_lobby                出现 0 次
  auto_start                出现 0 次
  gametimer                 出现 1 次
```

与游戏启动有关的只有 `-debug_mode`。**没有** `-gametimer` 或任何等价写法。

> 同一趟扫描的副产品（阶段 3 遗留问题的答案）：`skip_lobby` / `auto_start` **各 0 次**；
> `loadgame` / `load_game` / `-load` 的命中**全是标识符子串**，**没有** `-load*` 开关；
> 另外发现两个**前端 idler 命令字面量** `continuelastsave` 与 `loadsave`
> （位于 `jomini/modules/core/source/frontendidlerlogic.cpp` 的字符串簇里）——
> 阶段 3 那条"存档/继续游戏"待实测路线**值得从这里接着查**。

### ② 控制台 / 调试命令

控制台命令名在 exe 里是**明文**，这一点有独立实证：`console_history.txt` 里用户用过的
`log_ticktask_performance` 在 exe 里能找到**同名串**，而且它就挨着自己的帮助文本：

```text
     -72  Day
     -68  Week
     -60  Month
     -48  %s - Average sum time
     -24  time
     -16  tick-total
      +0  log_ticktask_performance
     +32  Start outputing ticktask performance data to profiling.log
     +96  Tick task logging disabled
    +128  Tick task logging enabled, output: profiling.log
```

读法：**存在**一个性能日志命令，但它写的是 **`profiling.log`**，
**不是** `gametimer_*.tsv` —— 两者是**不同的机制**，别混。
既然命令名是明文而 `gametimer` 只出现 1 次，**不存在**叫 `gametimer` 的控制台命令。

### ③ 设置文件

`platform_specific_game_data\log_settings_live.json` 是引擎真正读的日志配置，
结构是 `{"loggers": [{"category": …, "always_flush_level": …, "sinks": [...]}]}`。
它的 **26 个 category** 逐个列出如下（原始输出，未删改）：

```text
text_warnings, kernel_release, cw, cw_audio, cw_ecs, cw_fs, cw_graphics, cw_gui,
cw_input, cw_message, cw_network, cw_test, ai, automation_stats, code_rev,
db_conflicts, dedicated_server, game, memory, mp, setup, graphics, tests,
Checksum, Game State Validity, ui_animation_stats
```

* **没有 `gametimer`** ⇒ 这条路不通。
* 顺带纠正一个可能的口径错误：`automation_stats` 这个 category 写的是
  **`custom_automated_stats.log`**（就是阶段 3 看到的官方流水线成绩单），
  它与 `gametimer` **不是一个东西**。
* 另有一个 `ui_animation_stats` category（写 `ui_animation_stats.log`，`clear_file: true`），
  本机该文件是 **0 字节** —— 未测，但它名字上更接近"帧"。

---

## 2. 关键发现：12 份真实 TSV 已经在硬盘上

```
C:\Users\28905\Documents\Paradox Interactive\Victoria 3\logs\gametimer_*.tsv
```

12 份，全部 **2026-09-13**。逐份汇总（本仓 `pdx.gametimer` 解析产出）：

| 文件 | 字节 | 行数 | Year | Month | Day | 触顶 |
|---|---|---|---|---|---|---|
| `…_000815.tsv` | 99,271 | 4,131 | 1 | 32 | 4,098 | 否 |
| `…_001613.tsv` | 315,366 | 13,125 | 8 | 98 | 13,019 | **是** |
| `…_004356.tsv` | 176,262 | 7,335 | 4 | 55 | 7,276 | 否 |
| `…_005829.tsv` | 249,822 | 10,397 | 6 | 78 | 10,313 | 否 |
| `…_103358.tsv` | 315,366 | 13,125 | 8 | 99 | 13,018 | **是** |
| `…_110431.tsv` | 234,798 | 9,772 | 5 | 74 | 9,693 | 否 |
| `…_112541.tsv` | 315,366 | 13,125 | 8 | 99 | 13,018 | **是** |
| `…_132356.tsv` | 315,366 | 13,125 | 8 | 99 | 13,018 | **是** |
| `…_175501.tsv` | 315,366 | 13,125 | 8 | 99 | 13,018 | **是** |
| `…_183159.tsv` | 315,366 | 13,125 | 8 | 99 | 13,018 | **是** |
| `…_205006.tsv` | 315,366 | 13,125 | 8 | 99 | 13,018 | **是** |
| `…_213737.tsv` | 315,366 | 13,126 | 8 | 99 | 13,019 | **是** |

**两条硬结论**：

1. **有上限，会被截断**：7 份文件**正好**停在 **315,366 字节 / 13,125 行**。
   所以"跑了 9 个游戏年"**不等于**"9 年的数据都在" —— 长局必须换文件或分段。
   阶段 4 若用它做预算，得先想清楚怎么避开这个天花板。
2. **文件名时间是"创建时刻"**：例 `…_213737.tsv` 的 `LastWriteTime` 是 **22:02:01**，
   比文件名晚 **24 分钟** ⇒ 文件是**会话期间边跑边写**的，不是退出时一次性落盘。
   这对判据很重要：**"文件出现"= 会话开始**，而"行数增长"才代表在采集。

---

## 3. `.tsv` 的真实列结构（**前 5 行原文**）

```text
Game Date <TAB>Time Unit <TAB>Seconds
1838_01_01<TAB>Year<TAB>134.303810
1839_01_01<TAB>Year<TAB>161.642236
1840_01_01<TAB>Year<TAB>147.237229
1841_01_01<TAB>Year<TAB>186.154032
```

* 三列，**TAB** 分隔，**LF** 换行（无 BOM、无 CRLF）。
* 表头单元格**带尾随空格**：`"Game Date "`、`"Time Unit "`、`"Seconds"`（`Seconds` 没有）。
* 第 1 列 = 游戏内日期 `YYYY_MM_DD`；第 2 列 = 时间单元（**实测只有 Year / Month / Day**）；
  第 3 列 = 该单元的**墙钟秒数**，6 位小数。
* **两个真实瑕疵**（解析器必须容忍，不许静默处理）：
  1. 13,126 行里有 **2 行**年份只有 1 位：`6_11_01` / `6_01_31`（而不是 `1836_…`）。
     本仓解析器**照常解析但打 `suspicious_year` 标**，不改写、不丢弃 ——
     改写是编数据，丢弃会让月度序列缺格。
  2. 每天**恰好 4 条** Day 样本（3,257 个日期里 3,254 个正好 4 条）。

引擎侧的字符串邻域也印证了列名（exe 偏移 75,693,968 起）：

```text
 -96  Failed to log timer info to file: {}
 -40  Game Date 
 -29  Time Unit 
 -18  Seconds
  -8  .tsv
  +0  gametimer_%04d%02d%02d_%02d%02d%02d
```

---

## 4. 「单帧 ≤0.5ms」能不能量？ —— **不能**

**直说：量不了。** 三条理由，都是实测：

1. **粒度到不了帧**。最细的 `Time Unit` 是 `Day`，且**每天 4 条样本**；
   文件里**没有帧号、没有帧计数、没有 per-frame 列**。
2. **Day 行的 `Seconds` 是"这一天的墙钟秒"**，不是"某一帧的耗时"。
   拿它除以假设的帧数去凑一个单帧值，是**发明数据**。
   本仓 `pdx.gametimer` 把这件事写成常量
   `FRAME_GRANULARITY_AVAILABLE = False`，并在 `summarize()` 里输出
   `per_frame_measurable: false`，就是**不让下游顺手凑**。
3. exe 里确实有 per-frame 的 API（`GetPerFrameTimeExclusive` /
   `GetPerFrameTimeInclusive`），但**没找到把它们导出成文件的开关**（⏳ 未测）。

**它能给的是什么**（以 315 KB 那份为例，实测数字）：

```text
Year  n=     8 合计=  1080.824s 均值=135.1030s 中位=131.1307s 最坏=155.6985s
Month n=    98 合计=  1102.954s 均值= 11.2546s 中位= 10.9449s 最坏= 14.2698s
Day   n= 13019 合计=  1195.617s 均值=  0.0918s 中位=  0.0476s 最坏=  1.7063s
月数 109；最坏的一个月：1839-08 天=31 样本=124 日均=0.4540s 最坏一天=2.7862s

月度序列前 3 / 后 3：
  1836-01 天=  1 样本=   2 日均=0.0739s 最坏一天=0.0739s
  1836-02 天= 28 样本= 112 日均=0.3552s 最坏一天=1.6659s
  1836-03 天= 31 样本= 124 日均=0.3405s 最坏一天=1.5968s
  1844-11 天= 30 样本= 120 日均=0.4472s 最坏一天=2.1427s
  1844-12 天= 31 样本= 124 日均=0.4246s 最坏一天=2.0516s
  1845-01 天=  1 样本=   1 日均=0.5785s 最坏一天=0.5785s
```

也就是说它适合做 **「每游戏日 / 月 / 年的墙钟开销」** 这条对照线
（含"最坏一天"这种压力场景指标），**不适合**做单帧预算。

---

## 5. 交付物

| 文件 | 内容 |
|---|---|
| `tools/pdx/gametimer.py` | TSV 解析 + 统计（schema 来自上面 12 份实测文件）。纯离线，不依赖游戏 |
| `tools/tests/test_gametimer.py` | 34 个用例，全部合成夹具；含两个真实瑕疵（年份位数不足、触顶截断） |
| 本文件 | 侦察结论 |

`pdx.gametimer` 的入口：`parse_tsv` / `parse_file` / `unit_stats` / `all_unit_stats` /
`daily_totals` / `monthly_stats` / `summarize` / `summary_lines`。
**未接进 `cli.py`**（按分工由父 agent 统一接线）。

---

## 6. 已测 / 未测（逐条，不许含糊）

**已实测（有原始输出或实物为证）**

1. `gametimer` 在 exe 里只出现 1 次，且就是文件名格式串 —— 逐字节扫描。
2. 不存在 `-gametimer` 之类启动参数 —— 同上。
3. `log_settings_live.json` 的 26 个 category 里没有 `gametimer` —— 读了原文件。
4. `log_ticktask_performance` 存在，但写的是 `profiling.log`，是**另一个**机制 —— exe 明文 + 邻域。
5. 12 份真实 TSV 存在（2026-09-13），列结构 / 粒度 / 触顶上限 —— 用 `pdx.gametimer` 全量解析。
6. 文件是**边跑边写**（`LastWriteTime` 比文件名晚 24 分钟）。
7. exe 的 `LastWriteTime = 2026-09-16`，**晚于**全部阳性证据的日期（09-13）。
8. `-debug_mode`（含 `-scripted_tests`）在 09-20/09-21 的多轮会话里**没有**产出任何 TSV ——
   `logs/` 目录清单里 09-20 之后一份都没有。
9. 单帧耗时**量不出来**（粒度是 Day，每天 4 条，无帧号）。

**未测（明确没做，别当已做）**

1. **触发方式本身**：四条明路里 ①②③ 判为不通，④ 完全没做实验。
   ⇒ 本文件**没有**回答"gametimer 怎么开"这个原问题。
2. **构建更新假说**：09-13 与 09-16 两份构建的差异是否就是原因 —— **未测**。
   可行的判据：拿到 09-13 那份构建（或退回它的 beta 分支）跑一次，
   看 TSV 是否复现；复现即证实，不重复即说明是启动方式差异。
3. **`-scripted_tests` 跑到底会不会产出 TSV** —— 未测。
   （09-20 那两轮都在开局阶段就被我自己结束了，**样本不足，不能宣判**。）
4. **`ui_animation_stats.log`** 能不能当 per-frame 真值 —— 未测（本机 0 字节）。
5. `continuelastsave` / `loadsave` 两个 idler 命令字面量的用法 —— 未测
   （属阶段 3 遗留的存档路线，不是本任务）。

---

## 7. 纪律与还原状态

* 本次侦察**全程只读**：没有启动游戏、没有装卸 mod、**没有改 `content_load.json`**、
  没有跑 `v3 experiment`。因此**无需还原**（用户的 23 条启用列表未被触碰）。
* 游戏进程：侦察期间 **0 个 victoria3 进程**（未启动）。
* 仓库写入仅限本文件与 §5 的两个新文件。
