# 预注册 · 阶段 4 ④ pilot（卡 t6 = t22 前半）：标准压力剧本对照 3 对

> **本文件写在第一对开跑之前**。写入时刻（现读，本机本地钟）= **2026-09-28 23:37:06**。
> 判据、阈值、样本量、作废规则、分析流程**全部在跑之前写死**；看到数之后**不许**改判据、**不许**改阈值、
> **不许**把污染对当证据、**不许**用估算代替证据（`并行测试内存基线.md` §10/§11 的三条纪律）。
>
> 本卡只做 **pilot = 3 对**（配对重复，共 6 局）。pilot 自己也可能落在「未判决」——那是**合法交付**，
> 但要写清「还差什么、差多少」。

## 0. 依据

| 用途 | 出处 |
|---|---|
| 判据 / 公式 / 窗口 / 样本量 | `docs/design/exec/阶段4-压力剧本-口径.md` v3（§3.2 公式、§3.4 窗口 36 月、§3.5 判决力与最小 n、§4 两臂协议、§5 P3） |
| `s_d ≈ 0.73 ms` 的来源（算术基准） | `docs/design/exec/阶段4-结果.md:171-192`（§六·补 6 局实测：配对差 −1.32 / +0.10 / −0.31 ms） |
| 作废规则 | `docs/design/exec/并行测试内存基线.md:892-904`（§10：「其间出现过他人重命令 ⇒ 该对作废并重跑」；外部 ≥200 MB python / victoria3 ⇒ 作废）+ `团队台账-停机副本-20260925.md:77` |
| 机器锁协议 | `tools/out/mem/owner-*.flag` 互斥；开工前要求 `owner-*.flag` = 0 + `victoria3` = 0 + >300 MB python = 0，**两次相隔 ≥30 s 的样本都干净** |

## 1. 命令（冻结，逐字；不改）

```powershell
.venv\Scripts\python.exe -X utf8 tools\probe\perf_compare.py 36 --stress --repeat 3
```

* cwd = 仓库根（`C:\Users\28905\projects\Situated AI`）；**不加** `--tempo-arm`（B27 第三臂不在本卡范围，`tools/probe/perf_compare.py:604` 默认关闭）。
* 臂：**基线** = 原版 + 剧本（`enabledMods` 留空）；**处理** = 原版 + 剧本 + 我们的 mod（`perf_compare.py:360-362`）。
* 顺序：**交替** vanilla, ours, vanilla, ours, vanilla, ours（`:660-666`）⇒ 机器状态被两配置平摊。
* 窗口：每局 `clear_ticktask_timings` → 36 个月 → `dump_ticktask_timings`（§3.4；覆盖三波压力 1837.1 / 1837.7 / 1838.7）。
* 无需开环境闸门：runner 自己设 `ga.ALLOW_REAL_INPUT = True`（`perf_compare.py:617`）。
* 前置：`content_load.json` 存在（`:621`），否则 exit 2。runner 自己备份（`:620-624`）与还原（`:667-677`）。

## 2. 产物（冻结：落盘位置）

| 物 | 路径 |
|---|---|
| 控制台原始输出 | `tools/out/mem/t22-pilot-console.log` + `tools/out/mem/t22-pilot-console.meta`（START/CMD/EXIT/END 四行） |
| 结构报告（runner 写） | `tools/out/auto/compare.json`（`:717-718`） |
| 每局 ticktask CSV | `tools/out/auto/*.csv`（runner `shutil.copy`，`:396`，路径在 `runs[i]['csv']`） |
| 机器状态采样器 | `tools/out/mem/t22-sampler.log`（30 s 一行，跑前启动、收跑停止） |
| 分析脚本 + 产物 | `tools/out/mem/t22-analyze.py` → `tools/out/mem/t22-analysis.json` |
| 结果报告 | `docs/reports/阶段4-④-pilot-结果.md` |
| 台账 | `tools/out/mem/WINDOW.md`（开跑、收尾各一条，append-only、末尾带 LF） |

## 3. 量（冻结，抄口径页 §3.2；不改）

设窗口 `W` = 两次 `clear`/`dump` 之间的**实测**帧集合，`|W|` = 帧数：

* ① `M(W) = ( Σ_{f∈W} T_f ) / |W|`，`T_f = Σ_task ms(frame=f, task)` ⇒ `gametimer.summarize_ticktask()['per_frame_total_ms']['mean']`
* ② `M_t(W) = ( Σ_{f∈W} ms(f,t) ) / |W|` ⇒ `gametimer.ticktask_task_stats()` 的 `mean_ms`
* ③ **配对增量** `Δ_i = M_ours(W_i) − M_vanilla(W_i)`（**同一 repeat 序号**的两局相减）
* ④ `Δ̂ = mean(Δ_i)`；`s_d` = 配对差的**样本标准差（ddof = 1）**
* ⑤ `U(n) = t_{0.975, n−1} · s_d / √n`
* 副量（只记、不进判决）：`RecalculateModifierNodes`（`perf_compare.py:457` 的 `WATCH_TASK`，直接归因）、`UpdateAI`（P1 的分母）、背景 `TickDaily` / `OnActions`（只用于噪声估计，**不进分子**）。
* **复算**：主量同时走**两条独立链** —— ① runner 的 `summary.per_frame_total_ms.mean`；② 本卡分析脚本用 `gametimer.ticktask_frame_stats()` 从每局 CSV 复算（= 口径页 §3.6 第一条命令的同一条 API 链）。两条不一致 ⇒ 报告里写出差异，以复算链为准。
* 窗口一致性（§2.1④，判据 = `backlog.md` B103 **尚未立**）：只**报**两臂 `advanced` 的 `from/to/days` 读数，**不擅自立判据**。

## 4. 判决（冻结；三路，跑完照此落结论）

阈值 = **0.5 ms/帧**（P3：`|Δ̂| + U(n) ≤ 0.5` 才算达标）。

1. **可判 · 达标**：`U(3) ≤ 0.5` 且 `|Δ̂| + U(3) ≤ 0.5`
2. **可判 · 超预算**：`U(3) ≤ 0.5` 且 `|Δ̂| + U(3) > 0.5`
3. **未判决**：`U(3) > 0.5` ⇒ **只许**报 `Δ̂ ± U(3)`，并给出按判据算出的**最小 n**（**从 n = 3 起逐个试，取第一个 `U(n) ≤ 0.5` 的 n**）与「还差什么、差多少」

* 算术基准（**不是判据**，只用来对账）：`s_d = 0.7308 ⇒ n = 11`（`U(11)=0.491 ✓` / `U(10)=0.523 ✗`）；`U(3) = 4.303·s_d/√3 = 2.484·s_d`。
* 闭式 `n ≈ (t·s_d/0.5)²` **只是粗估，不许当判据**（口径页 v2 已删其判据地位）。
* 若日后要余量，**先定目标再算**：同一 `s_d` 下 `U ≤ 0.4 ⇒ n = 16`、`U ≤ 0.333 ⇒ n = 21`。本卡**不**预设目标余量。
* ⚠️ **不许**把「最坏帧」拿来凑 0.5 ms（原版自己最坏帧 316–472 ms）；本卡不判最坏帧。

## 5. 污染记账（逐对，冻结）

* **采样器**：每 **30 s** 一行 `时间 / owner-flag 名单 / victoria3 数 / python 总数 / >300 MB python 明细 / >200 MB python 明细`；每 2 分钟额外一行 python+victoria3 的**命令行明细**（截断 110 字符）。
* **作废规则（先写死，遇事照此判，不事后放宽）**：某一对的两局之间出现以下任一 ⇒ **该对作废并重跑**，理由写进采样器日志与结果报告：
  1. 出现 `owner-*.flag`（**别人的**；我自己的 `owner-t22.flag` 不算）；
  2. `victoria3` 进程数 > 0（**非**本 runner 自己的那一个）；
  3. 出现**外部** ≥200 MB 的 python（非本 runner 自身进程）；
  4. `<用户目录>\content_load.json` 在 runner 自己的备份/还原窗口**之外**被改写（sha256 变化）；
  5. 采样器出现异常墙钟（单次 tick 间隔 > 90 s，或日志断档 > 5 分钟）。
* 作废对**不进** `Δ̂` / `s_d`；报告里列出「作废了哪几对、因为什么、重跑结果」。
* **采样器自身开销照实记**：30 s 一次 `Get-Process`（+ 每 2 分钟一次 CIM 命令行查询），是本测量期间常驻的小负载 —— 按 §10 的纪律**披露**，不当作「无」。

## 6. 机器锁（本卡执行）

* **开工前**：`owner-*.flag` = 0 且 `victoria3` = 0 且 >300 MB python = 0，**两次相隔 ≥30 s 的样本都干净** ⇒ 然后写 `tools/out/mem/owner-t22.flag`。
* **收尾三件**：杀进程 → `victoria3` 残留 = 0 → 还原 `content_load.json`（**sha256 比**）⇒ 之后才删 `owner-t22.flag`。
* 与 `v3 modgen --write` 互斥；持锁期间别人不开实机。
* 台账：开跑与收尾各往 `tools/out/mem/WINDOW.md` **追加**一条（append-only、末尾必带 LF、时间戳现读）。

## 7. 本卡**不**做（写死，免得跑完被追问）

* 不跑「跑满」（n = 11 或按新 `s_d` 算出的 n）：那是后续卡（`t69`）的活；本卡只交 pilot 的 `Δ̂` / `s_d` / `U(3)` / 最小 n。
* 不跑第三臂 `--tempo-arm`（B27）。
* 不改任何代码 / 口径 / F9；不动 `docs/**` 的判据文本。
* 不判 P1（5%）与 P2（每月每国 2 ms）：本卡只顺带**记录** `UpdateAI` 的均值（P1 的分母输入），不落判决。

## 8. 写入时刻（现读）

`2026-09-28 23:37:06`（`pwsh` 现读；本文件由 write 工具落盘，UTF-8 无 BOM + LF；行数见盘上文件）。
