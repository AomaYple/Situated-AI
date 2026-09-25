# t67 · 独立复核：`test_cli_docs.py` 的允许集有没有被写松

> **结论：`pass`。** 允许集**按子命令取**（`cmd.params ∪ framework_options()`），
> 跨子命令混用真选项**仍然判红**；`framework_options()` 是**实测**（`runner.invoke` exit 0）而非硬编码；
> 契约读数（最终字节）只有**一条**红，且逐字是 `objectives` 那条前向引用。
>
> 复核对象：`tools/tests/test_cli_docs.py`（t55 的产物，**本卡只读、未改一行**）
> `sha256[:16] = c08eb71c8977215f` · 11,523 B · **LF 计数 = 244** · mtime `2026-09-25 02:14:37`。

## 0. 同版核对与「行数口径」

* `sha256[:16] = c08eb71c8977215f` 与 t55 报的值**逐字节同版** ⇒ 「读数对应 02:14 那一版」这条残留**不存在**。
* ⚠️ **行数口径**：本报告的行数一律 = **LF 计数**（`编码口径审计.md` §2 的口径）⇒ **244**。
  t55 报的 **245** 是「LF + 1」式数法，**属计数口径差异，不是文件不同**（同一份字节）。

## 1. 撞负例（三条，全部实测；判据用其本体 `_option_offenders(...)`）

用的是仓库既有的 `CliRunner` 在**本进程**里跑（秒级、只读），片段喂回**判据本体**，
与 `test_文档里的v3选项都真的存在` 走的是同一段逻辑（`:194` 调 `_option_offenders()`）。

| # | 命令 | CLI exit | 判据判定 | 判据原文 |
|---|---|---|---|---|
| ① | `v3 citations --definitely-not-a-flag` | **2** | **判红（非空，1 条）** | ``合成片段:1 `v3 citations --definitely-not-a-flag` —— citations 没有这个选项（可用：--help --offline paths）`` |
| ② | `v3 citations --logs x`（`--logs` 由 `ab` / `h1` 声明） | **2** | **判红** | ``合成片段:1 `v3 citations --logs` —— citations 没有这个选项（可用：--help --offline paths）`` |
| ② | `v3 citations --archive x`（由 `ab-probe` / `h1-probe` / `preflight` 声明） | **2** | **判红** | ``… `v3 citations --archive` —— citations 没有这个选项（…）`` |
| ② | `v3 citations --only x`（由 `experiment` / `modguard` / `tables` / `verify` 声明） | **2** | **判红** | ``… `v3 citations --only` —— …`` |
| ② | `v3 citations --write x`（由 `ai-surface` / `analyze` / `lock` / `modgen` / `tables` 声明） | **2** | **判红** | ``… `v3 citations --write` —— …`` |
| ② | `v3 citations --months x`（由 `ab-auto` 声明） | **2** | **判红** | ``… `v3 citations --months` —— …`` |
| ③ | `v3 citations --help` | **0** | **不判红（空列表）** | —— |
| 对照 | `v3 citations --offline x` | 2（是 `x` 这个不存在的路径，不是选项） | **不判红（空列表）** | —— |

**② 是这张卡的重点**：`--logs` / `--archive` / `--only` / `--write` / `--months`
**全都是别的子命令真正声明过的选项**，喂给 `citations` 后 CLI **exit 2**、判据**照样判红**
⇒ **允许集没有跨子命令串味**。

## 2. 反事实：把「写松」那种写法直接排除

若允许集被放宽成「**全部子命令选项的并集**」，则：

| 选项 | 在全局并集里？ | 那种（错的）写法 | 现写法 |
|---|---|---|---|
| `--logs` | **是** | 会**放行** | **判红** ✅ |
| `--archive` | **是** | 会**放行** | **判红** ✅ |

⇒ 现实现取的是**当前子命令**的 `opts`，不是并集 —— 这条是「允许集被写松」最可能的漏法，**已实测排除**。

## 3. 允许集不硬编码（代码定位）

| 位置 | 关键行原文 | 说明 |
|---|---|---|
| `tools/tests/test_cli_docs.py:74` | `_FRAMEWORK_OPT_CANDIDATES = ("--help", "--version")` | **只是候选名单**；上一行注释逐字写着「判据不从这张表来 —— 它只是待验证的输入」 |
| `:82-103` | `def framework_options() -> frozenset[str]:` … `return frozenset(flag for flag in _FRAMEWORK_OPT_CANDIDATES if runner.invoke(cli.app, [_FRAMEWORK_OPT_PROBE, flag]).exit_code == 0)` | **实测**：逐候选真跑一次，只把 exit 0 的收进允许集 |
| `:179-182` | `opts = _options(cmd)` / `if opts is None: continue` / `allowed = opts | common` | 允许集 = **当前子命令**声明的选项 **∪** 实测通用选项 |
| `:116-124` | `_options(cmd)`：`for param in cmd.params: out.update(param.opts)` | 子命令自己的选项来自 `cmd.params`；命令组返回 `None`（选项属于下一级） |

**实测结果**：`framework_options()` = **`['--help']`** —— `--version` 被实测**排除**
（`v3 citations --version` 与 `v3 --version` 都是 exit 2），说明它确实是「跑出来的」而不是抄的名单。

## 4. 判据本体的正面证据（转绿不是靠「凡是 `--` 开头的都合法」）

```
_option_offenders([("合成片段", 1, "v3 citations --definitely-not-a-flag")])
  ⇒ ['合成片段:1 `v3 citations --definitely-not-a-flag` —— citations 没有这个选项（可用：--help --offline paths）']   # 非空
_option_offenders([("合成片段", 1, "v3 citations --help")])
  ⇒ []                                                                                                            # 合法，不报
```
另外 `test_框架通用选项被认作合法`（`:198-210`）还钉住一条**机理断言**：
`all("--help" not in (_options(cmd) or set()) for cmd in tree.values())` ——
即「没有任何子命令在 `params` 里声明 `--help`」，那正是当初误报的根因。

## 5. 契约读数（最终字节同版）

```powershell
.venv\Scripts\python.exe -m pytest tools/tests/test_cli_docs.py -q -n 0
```
完整读数（**照抄**）：

```
..F...                                                                   [100%]
================================== FAILURES ===================================
____________________________ test_文档里的v3命令都有对应的子命令 ____________________________
tools\tests\test_cli_docs.py:158: in test_文档里的v3命令都有对应的子命令
    assert not bad, "文档提到了 CLI 里不存在的子命令：\n  " + "\n  ".join(bad[:15])
E   AssertionError: 文档提到了 CLI 里不存在的子命令：
E       收口清单.md:222 未知子命令 'objectives' —— v3 objectives --check
E       档案目标牌-实机读数.md:307 未知子命令 'objectives' —— v3 objectives --check
E       阶段5-目标函数表-口径.md:22 / :101 / :104 / :330 / :385 / :428 / :501 / :538 / :578 未知子命令 'objectives' —— v3 objectives --check
（:428 那条的片段写法是 .venv\Scripts\v3.exe objectives --check）
=========================== short test summary info ============================
FAILED tools/tests/test_cli_docs.py::test_文档里的v3命令都有对应的子命令 - As...
1 failed, 5 passed in 2.79s
```

* **退出码 1**；**唯一那条红**的断言原文逐字是 **「文档提到了 CLI 里不存在的子命令：」**，
  offender 共 **11 条**、**全部**是 `未知子命令 'objectives'`（+ `v3 objectives --check` 片段）✅
  ⇒ 与合约第 3 条的**分支①**一致（「内容必须**逐字**是 objectives」），不是别的红。
* `test_文档里的v3选项都真的存在` **已转绿**（t55 修的那条）；`..F...` 里另外 5 条（含两条新增用例）全过。
* **`objectives` 未落地**（t40 未到）：`objectives in tree: False`；
  `v3 objectives --help` ⇒ **exit 2**（输出首行 `Usage: v3 [OPTIONS] COMMAND [ARGS]...`）
  ⇒ 该红是**前向引用**，按合约属**预期红**，`t40` 落地即消解。

## 6. 机器纪律与只读证据

* **结构化门**（不看台账文本）：跑之前查 `tools/out/mem/owner-*.flag` ⇒ 只有 **`owner-t34.flag`**（02:16:36）。
  按 captain 02:42 的绿色放行口径（协议 v3 的免占位口子：**单进程 + 秒级 + 远低于 200 MB + 只读**）执行本卡命令。
* **旗标**：跑前建 `owner-archive.flag`，跑后**已删**（现在只剩 `owner-t34.flag`）。
* **台账**（`tools/out/mem/WINDOW.md`，LF 安全追加）：
  `02:22:07 状态 档案工程师 t67：只读部分已完成…等旗标` /
  `02:42:45 开始 档案工程师 t67 pytest tools/tests/test_cli_docs.py -q -n 0（单进程、秒级、只读；owner-t34.flag 在场，按协议 v3 免占位口子）` /
  `02:43:04 结束 档案工程师 t67 pytest … 退出码 1（1 failed / 5 passed / 2.79 s；唯一红 = objectives 前向引用，逐字核过）`。
* **只读**：`git status --porcelain` **开工前 72 条 → 结束后 74 条**，新增的两条是**别的成员的产物**
  （`tools/reports/阶段欠账对账复核.md` 等）；本卡产物只有本文件。
  跑 pytest 未动受控文件：`.pytest_cache/` 在 `.gitignore:18` 里（`git check-ignore` 命中）。
* **未改任何实现**：`tools/tests/test_cli_docs.py` 仍是 t55 那一版（sha 与 244 LF 未变），`tools/pdx/**`、`mod/**` 一字未动。

## 7. 残留与边界（如实写清）

1. 本卡的读数取自**运行时刻**的文档树（含别人在飞的文档）—— offender 列表里 11 条中有 1 条在
   `档案目标牌-实机读数.md:307`（那是**引用** offender 文本造成的自指，t40 落地后一并消失）。
2. 运行期间 `owner-t34.flag` 在场（功能工程师的实机盒）⇒ 本卡命令是**单进程 `-n 0`**，
   没有 xdist、没有改工作树；若收口要「完全干净机器」的读数，可在旗标清后**原样重跑**（≈3 s，读数应一致）。
3. 给 `t40` 的接口：它只需让 `v3 objectives` 存在，`test_文档里的v3命令都有对应的子命令` 即**自动转绿**；
   本卡**没有**为此改动任何判据（判据仍是「子命令不存在就报」）。
