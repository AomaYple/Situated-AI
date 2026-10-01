# 阶段 4 ④ pilot 结果（标准压力剧本对照 · 3 对）

- 卡号：t6（内部旧称 t22）；成员：内存分析师；日期：2026-09-29（本机钟，+08:00）
- 预注册：`docs/reports/阶段4-④-pilot-预注册.md`（写入时刻 **2026-09-28 23:37:06**，早于第一对起跑 00:17:26）
- 判据来源：`docs/design/exec/阶段4-压力剧本-口径.md` §3.2⑥ `U(n) = t_{0.975,n−1}·s_d/√n`、§3.5（`U(n) > 阈值` ⇒ 未判决）
- 阈值：**0.5 ms/帧**（`|Δ̂| + U(n) ≤ 0.5` 才算达标）

## 0. 一句话结论

**未判决。** 3 对有效配对给出 `Δ̂ = −1.6549 ms/帧`、`s_d = 2.0500 ms` ⇒ `U(3) = 5.0924 ms`，是阈值 0.5 的 **10.2 倍**；按现测噪声，判据要求 **68 对（≈136 局 ≈24 小时机器时间）**，所以 **3 对不够判**，t7 的「4–5 小时跑满」也不可能判到 0.5 ms/帧（`U(14) = 1.1836`、`U(20) = 0.9594`）。只能报 `Δ̂ ± U(3) = −1.65 ± 5.09 ms/帧`。

## 1. 原始命令与原始输出

```
# run A（3 对；第一对后来被判作废，见 §4）
.venv\Scripts\python.exe -X utf8 tools\probe\perf_compare.py 36 --stress --repeat 3
# START=2026-09-29T00:17:26  END=2026-09-29T01:22:54  EXIT=（空）

# run B（替换对，落 index 1 槽位）
.venv\Scripts\python.exe -X utf8 tools\probe\perf_compare.py 36 --stress --repeat 1
# START=2026-09-29T01:27:29  EXIT=0  END=2026-09-29T01:48:48
```

- 元数据：`tools/out/mem/t22-run.meta`（run A）、`tools/out/mem/t22-run2.meta`（run B）
- 控制台：`tools/out/mem/t22-run.log`（0 B：Python 非 tty 时缓冲 stdout）、`t22-run.err.log`、`t22-run2.log`、`t22-run2.err.log`（空）
- run A 的 `EXIT=` 为空是包装器缺陷（`Start-Process -PassThru` 的 `ExitCode` 未回填）；run B 改用调用运算符 + `$LASTEXITCODE` 后 `EXIT=0`。run A 的控制判决改用 `compare.json` 的 `stress.ok`（现读 `True`、`problems` 空）。
- 每局实测 ≈10.7–10.9 分钟（run A 六局 65 分钟；run B 两局 21.3 分钟）。
- 逐局 CSV 落盘：`vanilla-1` 00:28:59（**作废对**）→ `ours-1` 00:40:04（**作废对**）→ `vanilla-2` 00:50:51 → `ours-2` 01:01:28 → `vanilla-3` 01:12:16 → `ours-3` 01:22:44 →（替换对）`vanilla-1` 01:38:15 → `ours-1` 01:48:42。
- run B 的 compare.json 现读摘要（原始输出，乱码是 PowerShell 按 ANSI 读 UTF-8 所致，数字为准）：`vanilla #1 36.0 月 frames=1500 每帧均值 27.577 ms RecalculateModifierNodes 6.0861 ms / 挂载 False`、`ours #1 frames=1500 每帧均值 25.006 ms RecalculateModifierNodes 4.6478 ms / 挂载 True`、`差 per_frame_mean −2.571（−9.32%）task_mean −1.4383（−23.63%）`、`✅ 受控：两臂压力自报逐行相等（各 45 行）`。

## 2. 读数（有效对 = #1' 替换 / #2 / #3）

| 对 | M_vanilla (ms/帧) | M_ours (ms/帧) | Δ (ms/帧) |
| --- | --- | --- | --- |
| #1'（替换对，01:27:29–01:48:48） | 27.5767 | 25.0060 | **−2.5707** |
| #2（00:40:09–01:01:28） | 25.6080 | 26.3013 | **+0.6933** |
| #3（01:01:28–01:22:44） | 26.9267 | 23.8393 | **−3.0873** |
| ~~#1（作废）~~ | ~~28.5410~~ | ~~27.7870~~ | ~~−0.754（不作证据）~~ |

- `Δ̂ = −1.6549 ms/帧`（runner 链 `delta_runner = −2.5710 / +0.6930 / −3.0880`；复算链 `delta_recompute = −2.5707 / +0.6933 / −3.0873`，两条链一致到 3 位小数）
- `s_d = 2.0500 ms`（`statistics.stdev`，ddof=1）
- `U(3) = 4.3027 × 2.0500/√3 = 5.0924 ms > 0.5` ⇒ **未判决**（`|Δ̂| + U(3) = 6.7473 ms`）
- **按判据的最小 n = 68 对**（边界证据：`U(68) = 0.4962 ≤ 0.500`，`U(67) = 0.5000 > 0.500`）；≈136 局、按 10.7 分钟/局 ≈ **24.3 小时**
- 余量目标（口径页 §3.5）：`U ≤ 0.4 ⇒ 104 对`、`U ≤ 0.333 ⇒ 149 对`
- 参考点：`U(7)=2.0005`、`U(14)=1.1836`、`U(20)=0.9594`、`U(40)=0.6557`
- t 分位算法：正则化不完全 Beta 连分数 + 二分反演（`tools/out/mem/t22-minn.py`），与标准 t 表 df=1..22 交叉验证**最大偏差 0.0004**（判据 0.002）

## 3. 名单逐任务读数（口径页 §3.3）

| 任务 | 角色 | 逐对 Δ | Δ̂ | s_d | U(3) | 最小 n |
| --- | --- | --- | --- | --- | --- | --- |
| `RecalculateModifierNodes` | 直接归因 | −1.4383 / +0.6184 / −1.4531 | −0.7577 | 1.1918 | 2.9605 | 25 |
| `UpdateAI` | AI 侧 | −0.5137 / +0.1848 / −0.2137 | −0.1809 | 0.3504 | 0.8704 | **5** |
| `Δ_attr`（两任务之和，描述性） | — | −1.9520 / +0.8032 / −1.6669 | −0.9385 | 1.5151 | 3.7638 | 38 |
| `TickDaily` / `OnActions` | 口径页写的「背景」 | **不在实测 CSV** | — | — | — | — |

- 两条（`RecalculateModifierNodes` / `UpdateAI`）与 `Δ_attr` **都未判决**；表内不做判决，只给读数。
- **边界（须回写口径页）**：口径页 §3.3 的背景名单 `TickDaily` / `OnActions` 在今天实测 CSV 里**一个都没有**；按 §3.3 的扩展规则（「只有实测 CSV 里出现过的任务名才允许进名单」）它们不得进名单。实测重任务（pair#1' 两臂合计 total_ms 前六）= `RecalculateModifierNodes` / `UpdatePopGrowth` / `UpdateAI` / `PrepareNavyAIData` / `SyncedAIPostUpdate` / `MonthlyPulseJournalEntries`（CSV 共 264 个任务名）。
- **可复核的正面读数**：敏感观测点确实更敏感 —— `UpdateAI` 的 `s_d = 0.35`（最小 n = 5）比整帧的 `s_d = 2.05`（最小 n = 68）小一个量级，与口径页 §3.3「盯关键任务」的理由一致；但整帧判决仍必须按整帧的 `s_d`。

## 4. 逐对记账（预注册 §10 五条作废线逐条核）

**对 #1（run A index 1）＝ 作废。** 外部重活：评审员的一次 `pytest tests/test_engine_log_offline.py tests/test_cli.py -q -n0`（单进程、无 xdist worker；起 00:20:45、止 00:28:26，自报 `66 passed in 455.77s`，队长批准的上限是 60 s）。采样器逐 tick 证据：其子进程 **pid 13988**（父 18512）在 `00:20:54` 首现 **211 MB** → `00:25:55` 峰值 **496 MB** → `00:28:25` 仍 **393 MB** → `00:29:01` 退出；与 `vanilla-1.csv`（00:28:59 落盘）与 `ours-1.csv`（00:40:04 落盘）**全程重叠** ⇒ 触发预注册 §10 第③条「外部 ≥200 MB python ⇒ 该对作废并重跑」。作废单位＝**对**，不是整轮；原始读数已留档，不作判决依据。

**对 #1'（替换对）＝ 有效。** 窗口 01:27:29–01:48:48：采样 67 行，状态行 `gt200` 全空、`py=3`（`md_cg` 21 MB + 我的 runner 4/54–65 MB + `victoria3` 2.6–7.3 GB）、`v3=1` 43 行（游戏在飞）、无他人旗标。

**对 #2、#3（run A index 2/3）＝ 有效。** 窗口 00:40:09–01:22:54：`00:33:26–00:39:56` 共 14 个采样瞬间，唯一例外 `00:36:56` 抓到功能工程师的一对 `pytest`（pid 10948 **4 MB** + pid 5276 **102 MB**，双双 <200 MB）；全 log 16 行 `gt200` 命中**全部是 pid 13988**（即作废对的窗口）⇒ 无第二处越线。

**判为「窗口噪声、未污染样本」（峰值均 <200 MB，且都落在已作废的 #1 窗口内）**：验证员 2 笔单进程 python（`00:30:5x–00:31:2x`，仓外夹具 `%TEMP%\t8-verify\t25_extra.py` / `t25_fixture.py`，各数秒）；功能工程师 5 笔 `-n0` pytest（`00:34:07.1–00:36:58.4`，1.34 s / 5.88 s / 5.80 s / 11.98 s / 0.51 s）+ 同窗非 pytest python（机制微探针、两次演练、三次 `ruff`）。口径按队长要求写死：**「短到不改变采样点」≠「没跑过」**，统一写成「窗口噪声、未污染样本」。

**收尾核**：跑完后 `victoria3 = 0`、`content_load.json` sha256 = `d553ffe23a54c06265ea2c543d47c1915829ea6fb670a9c4e9d6ba4936cec71a`（＝开工基线，由 runner 的 `finally` 还原，mtime 01:48:47）、用户 mod 目录无残留、`owner-t22.flag` 已删。

## 5. 窗口边界（本轮新发现，影响后续口径表述）

- 命令给的是 `--months 36`，`advanced` 实测 `1836.3.3 → 1839.3.9`（days 1101.8；其余局同量级，1098.8–1109.8）✓
- 但每局 `frames = 1500`（不是口径页 §3.4 预期的 ≈4500）；独立复核（`t22-framecheck.py` 直接数 CSV 的唯一 frame 值）六份 CSV 全部 `uniq_frames = 1500`、`first≈59,902,4xx`、`last≈59,911,5xx`、`span = 8994` 帧、`frame_step_observed = 6` ⇒ **引擎 ticktask 样本上限为 1500（约末 12 个月）**，`|W| = 1500`、分辨率 `1/1500 = 0.00067 ms`（`millisecond_resolution = 1`、`per_frame_measurable = True`）
- 后果：① 加长 `--months` **买不到** 更多样本（只有末段 12 个月进统计）；② 「压力窗口覆盖」必须写成**末 ~12 个月（含 1838.7 那波革命潮及其余波）**，不是 36 个月；③ 两臂同起止、同一末段 ⇒ 对照仍成立
- 最坏帧（只作异常检测）：多为 `frame 59908176 任务=258 合计 370–442 ms 最重=MonthlyPulseJournalEntries(123–141 ms)`；`ours-2` 例外 `frame 59910696 任务=240 合计 476 ms 最重=UpdateCivilWars(151 ms)` ⇒ 与 09-23 的最坏帧同量级

## 6. 与 `阶段4-结果.md` §六·补（2026-09-23）对照

| 项 | 09-23（`perf_compare.py 12 --repeat 3`） | 今天（`… 36 --repeat 3` + 替换对） |
| --- | --- | --- |
| 逐对 Δ | −1.32 / +0.10 / −0.31 ms | −2.57 / +0.69 / −3.09 ms |
| Δ̂ | ≈ −0.51 ms/帧 | −1.6549 ms/帧 |
| s_d | ≈ 0.73 ms | **2.0500 ms** |
| U(3) | 1.815 ms | **5.0924 ms** |
| 最小 n（该 s_d 下） | 11 对 | **68 对** |

- 结论不变且更硬：**两轮都只能读「没有可观测的退化」，都不能读「已证明 ≤0.5 ms/帧」**；今天的噪声比 09-23 大约 2.8×。
- 跨轮不可直接比：`|W|` 两轮都是 1500，但**窗口内容不同**（今天 vanilla 每帧 25.6–28.5 ms vs 09-23 的 20.6–22.8 ms），世界/回合状态不同 ⇒ 只能各自在轮内读。
- 逐对 Δ 从 +0.69 摆到 −3.09、每臂均值随时间下降（vanilla 28.5→25.6→26.9→27.6）⇒ 主要成分是**时间漂移**（机器/游戏状态），不是臂差异。

## 7. 对 t7 的回答（队长要求明确回答「3 对够不够判」）

1. **不够判。** `U(3) = 5.09 ms` 是阈值的 10.2 倍；按现测 `s_d` 需要 **68 对 ≈136 局 ≈24 小时**。
2. **t7 的「4–5 小时跑满」不可能判到 0.5 ms/帧**：`U(14) = 1.1836 ms`、`U(20) = 0.9594 ms`，都在阈值 2 倍以上（`U ≤ 1.0` 也要 19 对 ≈6.8 小时）。
3. 建议（**不改判据**，改判据必须走口径修订）：
   - 先走「记账 + 未判决」口径收口（本报告即该口径的成品），别把 4–5 小时花在注定不可判的跑上；
   - 要真判 0.5 ms/帧，先降 `s_d`：受控剧本 + 固定存档（口径页 §3.2 四手段）、独占机器、同温锁频、同机同时段交替（runner 已交替）；
   - 若要更便宜的替代判决口径，敏感观测点 `UpdateAI`（最小 n = 5）与 `RecalculateModifierNodes`（25 对）是候选，但**必须单独立卡并改口径页**，不能用本卡读数替代整帧判决。
4. **P1 / P2 不在本卡**（预注册已声明不判）；`Δ_attr`（描述性）给了 `Δ̂_attr = −0.9385 ms/帧`、`U(3) = 3.7638 ms`、`Δ̂_attr × |W| = −1407.8 ms/窗口`、`B_AI = 2513.0 ms/窗口`，按现噪声同样**不可判**。

## 8. 复算入口

```powershell
# 1) 合并两轮 compare.json（替换对覆盖 index 1）→ Δ̂ / s_d / U(3) / 表内最小 n
.venv\Scripts\python.exe -X utf8 tools\out\mem\t22-analyze.py tools\out\mem\t22-runA-compare.json tools\out\perf\compare.json
# 2) 判据最小 n（含 t 表交叉验证）
.venv\Scripts\python.exe -X utf8 tools\out\mem\t22-minn.py 2.0500 0.5
# 3) 名单逐任务 / 实测任务清单 / 窗口唯一 frame 数独立复核
.venv\Scripts\python.exe -X utf8 tools\out\mem\t22-taskstats.py
.venv\Scripts\python.exe -X utf8 tools\out\mem\t22-tasks.py
.venv\Scripts\python.exe -X utf8 tools\out\mem\t22-framecheck.py
# 4) 口径页 §8 剧本本体复核
.venv\Scripts\python.exe -m pytest tests/test_stress_probe.py tests/test_gametimer_ticktask.py -q
```

制品（`tools/out/mem/`）：`t22-runA-compare.json`（48,765 B）、`t22-runB-compare.json`（16,600 B）、`t22-analysis.json`、`void-pair1/`（`compare-runA.json` sha256 `AD47CFAC0B0384CE60A324A0F0EC012FD28FF7C19328CBED9DB5D796656EBEC6` + 作废对 `vanilla-1.csv` 3,680,231 B + `ours-1.csv` 3,683,406 B + `MANIFEST.txt`）、`t22-sampler.log`（353 行，`23:39:05–01:54:03`）、`t22-sampler.ps1`、`t22-analyze.py`、`t22-minn.py`、`t22-taskstats.py`、`t22-tasks.py`、`t22-framecheck.py`、`t22-runB.ps1`、`t22-wait-quiet.ps1`、`t22-report-draft.md`、`pre-t22-perf-backup/`（09-23/09-25 旧产物，跑前备份）。

## 9. 使用边界（不许美化）

1. `Δ̂` 为负**不得**读成「我们的 mod 让游戏变快」：两臂从第 1 月就分叉（无固定存档）、`n = 3`、逐对 Δ 摆动 3.8 ms、主要是时间漂移。
2. 「**未判决**」＝分辨率不足，既**不是**达标，也**不是**超预算（口径页 §3.3 判决规则）。
3. F9-3 的「单帧」按口径读作**平均单帧（窗口均值）**，不读作瞬时；最坏帧只作异常检测，且覆盖缺口如实 —— 第 4 成分（玩家大动作）与固定存档**仍缺**，最坏帧那一半**不能**宣布覆盖。
4. 本报告只读预注册冻结的判据；`|W| = 1500`（而非 ≈4500）与「`TickDaily`/`OnActions` 不在 CSV」两条边界须回写口径页，本卡不自行改口径。
