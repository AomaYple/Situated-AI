# D29：`test_crosscheck_与引擎日志一致` 改成自带夹具的确定性用例（3 = 不可核对 / 1 = 真错配）

本卡 = `t28`（kind：implementation），执行者：评审员。判据口径来自 `t4` 的实机附判：
**EXIT 3 = 不可核对**（16 条 token 行号不可比，来源 Steam Workshop `3007678964` 覆盖两个
`gui/*.gui`；三态里的「判红」为 **0** 条）⇒ 实机行为与用例期望的 3 一致；在别的机器上
「跑测试测得 1」，是**宿主机环境差**（测试环境里「持有覆盖版」这个条件不成立），
不是被测对象的行为。

**一句话**：用例现在自带「原版 / 覆盖版 / 引擎日志」三份夹具，**四个方向**各钉一次
（不可核对 ⇒ 3、真错配 ⇒ 1、全匹配 ⇒ 0、日志比安装旧 ⇒ 3）；改前它是**宿主机状态的函数**
（同一份代码换环境就从「跑」变「不跑」），改后两种环境读数**逐字相同**（各 `1 passed`），
且 49 条 assert 一条不少、`skip`/`skipif`/`xfail`/`noqa` 一条不加、`src/pdx/cli.py` 未动。

## 一页速览

| # | 方向 | 夹具输入（原版行数 / 生效版行数） | 判据（`token_verdicts()`） | 退出码 | 用例落点 |
|---|---|---|---|---|---|
| ① | 行号不可比 | 4 / 6（`KEY_ALPHA` 挤到第 5 行、`KEY_BETA` 整份没有） | `lines_incomparable` + `stale_no_effective` | **3** | `:266-304` |
| ② | 行号可比却对不上 | 4 / 4 | `misplaced` 1 + `matched` 2 | **1** | `:306-331` |
| ③ | 全部命中 | 4 / 4（逐行相同） | `matched` 2 | **0** | `:333-351` |
| ④ | 日志比安装旧 | 2 / 无覆盖版 | `stale_absent` 1 | **3** | `:353-376` |

环境读数（同一条用例，改后）：宿主 `1 passed in 0.76s` / 隔离 `1 passed in 0.78s`（§3）。

## §1 改前：这条用例是宿主机状态的函数

- **旧实现**（被替换掉的 80 行，改前在工作树第 145..224 行）：`@_needs_game` + 真
  `engine_log.parse_logs()`（读 `Documents/.../logs`）+ 真 `build_override_map()`（读
  `steamapps/workshop`）+ 两条 `pytest.skip`（没有引擎日志、探针会话）；断言按
  `report.incomparable_tokens` / `absent_tokens` 的**当时读数**分档。
- **今天两次现跑（改前那 80 行，替换之前）**：

  | 环境 | 命令 | 读数 |
  |---|---|---|
  | 宿主（本机装着 Workshop 覆盖版 `3007678964`） | `pytest "tests/test_cli.py::test_crosscheck_与引擎日志一致" -q -n0 -rs` | `1 passed in 2.74s` |
  | 隔离（`V3_ROOT`/`V3_USERDIR`/`V3_WORKSHOP` = `Z:/nope`） | 同上 | `1 skipped in 0.46s`（`SKIPPED …:146: 游戏目录不可用`） |

  同一份代码、同一条用例，换环境就从「跑」变「不跑」——红/绿由宿主机装了什么决定。
- **宿主真 CLI 今天**：`python -m pdx.cli crosscheck` = **exit 3**，16 条
  `lines_incomparable`、判红 **0** 条，覆盖来源 `Steam …\workshop\content\529340\3007678964`
  的 `gui/military_formation_panel.gui` 与 `gui/panel_military.gui`（与 t4 的实机口径一致）。
  原始输出留档 `tools/out/_d29_probe_host.txt`（现读末尾：`结论 = 不可核对：16 条 token 行号不可比
  （另有 0 条 token 在当前安装里整份文件都找不到）；…本命令退出码 3`）。
- ⚠️ **不声称**：卡面记录的「本机跑测试测得 1」**没有在我今天这台机器上复现**（今天退 3）。
  我没有当时那台机器的状态，故只把「改后的确定性」当本卡交付；那个 1 不引用为本卡证据。

## §2 夹具：原版 / 覆盖版 / 日志三份都在 `tmp_path`

```
<tmp_path>/d1|d2|d3|d4/
├── game/gui/panel.gui                    原版（引擎日志里的行号以它为准）
├── workshop/fixture_workshop_mod/gui/panel.gui   生效版（④ 不建 = 没有覆盖版）
├── userdir/logs/debug.log                合成的引擎日志（default_log_dir() 的真正来源）
└── userdir/mod/                          空的本地 mod 目录（免得撞上宿主机装的本地 mod）
```

- 四个根逐个 `monkeypatch.setattr(config, …)`（`:176-231`），并**自检**
  `engine_log.default_log_dir() == userdir/"logs"`、`root == config.GAME`、
  `workshop == config.WORKSHOP`、`userdir / "mod" == config.LOCAL_MODS` —— 防 monkeypatch
  失效后**静默退回读宿主机**（那正是这条用例改造前的病）。
- 夹具 mod 目录名故意用 `fixture_workshop_mod`（**不是** `3007678964`）：断言里出现它，
  即证明读数来自夹具、不是宿主机（`:301`、`:304`）。
- 合成日志（`_engine_log()`，`:158-174`）：版本行 `Feeding game version into checksum: 1.14.5`
  + 枚举行 `Starting pre-enumerating 'gui'(.gui, , 0)` + 每条 `Unlocalized text '{tok}' at
  {rel}:{line}`。
- 命令链**全真**：真 `parse_logs` → 真 `build_override_map` → 真 `cross_check` →
  真 `token_verdicts`，只把文件系统换成夹具（分工见 §5）。
- ⚠️ 一个易错点：`summary()` 的表格**永远**有一行「覆盖面缺口」（`engine_log.py:419`），
  所以「没有缺口」只能用**带全角冒号**的串（`"覆盖面缺口：" not in flat` —— 对应
  `cli.py:1603-1607` 只在真有缺口时才打印）或 JSON 读数来断；表格行本身不能当证据。
- ④ 为什么不是「覆盖版删掉了它」而是「日志比安装旧」：`_stale()`（`engine_log.py:311-327`）
  要求 `tokens_anywhere` 与 `vanilla_anywhere` **两边都为 None** ⇒ 只有 ④ 那条落进
  `stale_absent`；① 的 `KEY_BETA` 在原版第 3 行有、只是覆盖版整份没有，故走
  `stale_no_effective`（仍是不可核对，但**不**打印「日志比安装旧」——用例 `:295` 就这么钉的）。
- 退出码只由 token 三态推：四个方向都断言 `覆盖面缺口 == 0`；夹具 `game/gui` 只有 1 个
  `.gui` 且 `is_scriptable` 为真 ⇒ `coverage_gaps` 空（否则 `cli.py:1744` 的
  `if gaps or misplaced: Exit(1)` 会把 ① 的 3 抢成 1）。

## §3 两次读数（改后）+ 变异检验

| 读数 | 宿主 | 隔离（`V3_* = Z:/nope`） |
|---|---|---|
| 单条用例（A2 / B2） | `1 passed in 0.76s` exit 0 | `1 passed in 0.78s` exit 0 |
| `-k crosscheck`（A / B，4 条） | `4 passed, 44 deselected in 1.27s` | `4 passed, 44 deselected in 1.03s` |
| 整文件（C / D） | `48 passed in 324.65s` exit 0 | `25 passed, 23 skipped in 6.13s` exit 0 |

- 两次**逐字相同**，且**都没有 skip**；隔离那次整文件剩的 23 条跳过全是 `_needs_game`
  （跳点 `:536`/`:617`/`:682`/`:711`/`:794`），**不含** `:232` 这条。
- **变异检验**（证明断言不是空跑）：`tools/out/_d29_mutate.py` 生成两份 test_cli.py 全文副本，
  各只改一处夹具输入 ——
  - A：① 的生效版改成 4 行 ⇒ 期望 3、实得 1 ⇒ `FAILED … assert 1 == 3`；
  - B：② 的生效版加一行 ⇒ 期望 1、实得 3 ⇒ `FAILED … assert 3 == 1`。

  两次都是 `1 failed, 47 passed`（副本会跑整文件，各约 4-5 分钟）。两份副本已清理
  （`tools/out/_d29_mutant_{a,b}.py` 删除；生成脚本 `tools/out/_d29_mutate.py` 保留，可复现）。

## §4 判据没有放松（逐条）

- 新块里 `pytest.skip` / `skipif` / `xfail` / `noqa` **各 0 次**（现读：新块 `:145-376`（232 行）
  内 0/0/0/0）。全文件剩下的 `skipif` 只有 `:50`（`_needs_game` 标记定义，23 条别的用例在用）、
  `pytest.skip` 只有 `:539`/`:563`（「尚无产物，先跑 v3 analyze」），都不在本卡范围。
  唯一从本用例删掉的跳过是 `@_needs_game` —— 那是**环境**跳过，不是判据。
- 断言：改后新块 **50 条 assert**（替换前那一档是 14 条）；旧版断过的整句**逐字保留**——
  现读 `:297`「gui/panel.gui 日志第 2 行 'KEY_ALPHA' —— 覆盖版里别处有（第 5 行）」、
  `:298`「… 日志第 3 行 'KEY_BETA' —— 覆盖版整份都没有」、`:291`「结论 = 不可核对」、
  `:292`「既不是通过，也不是不一致」、`:300`「覆盖来源（引擎读的是它，我们读的也是它）：」、
  `:347`「与引擎日志完全一致」。
- 三态**都可区分**且**两端都有人看守**：① 断「不可核对」且 `"真错配" not in flat`（`:294`）；
  ② 断判红且 `"结论 = 不可核对" not in flat`（`:331`，真错配不许被软化进不可核对那一档）；
  ③ 断 0 —— 这一端就是「判据不许放宽成永远报不可核对」的看守。
- `src/pdx/cli.py` **本卡未动**：现读 mtime `2026-09-29 00:20:13`（早于本卡开工），工作树里
  那 143/28 行改动是本轮别的卡留下的；`EXIT_FAILED = 1` / `EXIT_UNVERIFIABLE = 3` 与
  `crosscheck_cmd` 的退出码分支一字未改。
- 结构化读数走 `--json`（`:259`）：`日志版本`、`概览` 的「三态·匹配 / 三态·判红（行号可比却
  对不上）/ 三态·不可核对 / 覆盖面缺口」、`token分类` 的三个桶 —— 文本断言 + JSON 读数双保险。

## §5 分工与不声称

| 用例 | 夹的是什么 | 会不会随宿主机变 |
|---|---|---|
| `tests/test_engine_log_offline.py` | `cross_check` 纯函数 | 不变（本来就自带夹具） |
| `tests/test_cli.py:232`（本卡） | **整条命令链**（真解析→真映射→真核对→真判据），只换文件系统 | **不变** |
| `tests/test_cli.py:379`（负对照） | 命令层对**报告对象**的消费（monkeypatch 出报告） | 主体不变 |
| `tests/test_engine_crosscheck.py` | **宿主机真日志**的外部背书（`integration`；无日志/无游戏/探针会话即 skip） | 会——那正是它的职责 |

- 本用例**不再声称**核过宿主机真日志；真日志那一路的看守在上面第四行那个文件里。
- 负对照 `:379` 里仍有一条宿主依赖分支（`:507` `if claims and not engine_log.probe_session():`）：
  宿主机没日志时它**退化成不断言**，只有在宿主真有不可比条目、而 CLI 却退 1（假绿）时才红
  ⇒ 是探测器，不是假红。**不属于本卡范围，只登记**（§7）。

## §6 门禁现跑（4 条，均在仓库根目录）

| 命令 | 读数 | 退出码 |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest tests/test_cli.py -q -n0` | `48 passed` | 0 |
| `.venv/Scripts/python.exe -m ruff check .` | `All checks passed!` | 0 |
| `.venv/Scripts/python.exe -m ruff format --check .` | `249 files already formatted` | 0 |
| `.venv/Scripts/python.exe -m mypy --no-incremental` | `Success: no issues found in 146 source files` | 0 |

- 收尾复跑（用例与报告定稿后再跑一次，内容未变）：`48 passed in 351.96s (0:05:51)` exit 0；
  captain 重派 attempt 2 后按同一哈希再跑一次：`48 passed in 218.96s (0:03:38)` exit 0。
- **ruff 事件（如实记录）**：本卡改动在飞时，t30 档案工程师报整树 `ruff check . --no-cache`
  EXIT 1 / 4 errors，全部落在本文件：`:225`/`:226`/`:227` **SIM300**（`assert config.GAME == root`
  —— ruff 把全大写属性当常量，判成 Yoda 条件）与 `:301` **PT018**（`assert sources and all(...)`）。
  已修：写成 `assert root == config.GAME` / `workshop == config.WORKSHOP` /
  `userdir / "mod" == config.LOCAL_MODS`，PT018 拆成两条 assert；随后复测全绿，并已回消息告知 t30。
  ⚠️ 提醒：本文件的门禁是**整树**跑的，同轮其他人在改别的文件时读数会互相污染（我这次就是
  被别人先发现的）。
- ⚠️ 注意：整文件 pytest 在宿主上要 **5 分 25 秒**（48 条里多数要起真 CLI / 真 verify），
  隔离环境只 6 秒（23 条 `_needs_game` 直接跳过）——别把「快」当成「绿」。

## §7 残留登记（不在本卡 inScope，只登记不改）

1. `tools/probe/perf_compare.py:50` 与 `docs/design/exec/接续说明.md:134` 都写着这条用例
   「会因本机 mod 集不同而红」—— 本卡之后这句**过时**（用例不再读宿主机 mod 集）。
2. `docs/reports/t32-CI-闸门与基准-核对.md:125` 列的 test_cli.py 跳过计数/行号含
   `:170`/`:172` 两条 skip —— 本卡把这两条删了，该处计数与行号**过时**。
3. 负对照用例 `:379` 的宿主依赖分支 `:507`（见 §5）：不假红，但「没日志就不看守」这一半
   可以补成夹具；本卡不动。
4. ⚠️ 被替换掉的旧用例文本**不在 git 里**：`git show HEAD:tests/test_cli.py` 只有 517 行
   （更早版本），工作树那一版（737 行）是本轮多张卡叠出来的、没有提交 ⇒ 旧 80 行**无法回放**。
   §1 的两次读数与 §4 的断言清单是本卡替换前现读的，不能从历史复原。

## §8 现读校验

- `tests/test_cli.py` = **43,409 B / sha256 `9352b35f24c0c75aaa09c87c98bff8c901429a5c971b5ea58bc2c6715c2bfe92`**、
  **889 行**（改前 737 行，+152），UTF-8 **无 BOM**、`\r\n` **0** 个（LF）。
- 关键行号：`_FIXTURE_MOD` `:148`、`_FIXTURE_VERSION` `:152`、`_VANILLA_GUI` `:155`、
  `_engine_log` `:158`、`_crosscheck_fixture` `:176`、用例 `:232`、四个方向
  `:266`/`:306`/`:333`/`:353`、负对照 `:379`、无日志用例 `:518`。
- 本卡只改 `tests/test_cli.py`，新增本报告。

## §9 D34：负对照的宿主依赖分支（原 `:507`）改成夹具 —— 消灭「静默过」

**本卡 = `t34`（kind：implementation），执行者：评审员。** D29 自己登记的漏网（§5 末、§7.3）
在本卡补齐：`test_crosscheck_真错配仍判红_阴性对照` 的 ⑥「真报告上的钳子」原有**三道宿主闸门**
（`claims` 非空 / 不是探针会话 / 真报告里真有不可核对条目）——宿主机没日志时第一道就短路，
**一条断言都不跑**，用例照样绿：这就是"什么都不验就过"（B114、t39/D3 同族）。

改法（`tests/test_cli.py`，D34 前 = 43,409 B / `9352b35f…`）：

- ⑥ 整段**移出**那条负对照（原 `:504-515` 共 12 行 → 4 行指针注释，现读 `:509-512`）；
  负对照留下的 ①-⑤ 全是 monkeypatch 出报告对象的确定性断言（`:439-502`），一条没删。
- 新增 `test_crosscheck_行号不可比不判红_真报告阴性对照`（现读 **`:514-563`**，50 行、**9 条 assert**，
  `pytest.skip`/`skipif`/`xfail`/`noqa` **各 0**）：现场由 `_crosscheck_fixture(tmp_path / "d6", …)`
  现造（输入同 ①：原版 4 行 / 生效版 6 行），走**真** `parse_logs` → 真 `build_override_map`
  → 真 `cross_check` → 真 `token_verdicts`，只把 `config` 的四个根指到 `tmp_path`。
- 三道宿主闸门**升级成断言**（本卡要害）：`assert claims`、token 断言恰 2 条、`version == 1.14.5`、
  `assert not engine_log.probe_session()`、`assert rep.incomparable_tokens`、
  `assert not rep.misplaced_tokens` —— 条件造不出来时**红**，不再静默过；再接命令层：
  `assert r.exit_code == 3`、「结论 = 不可核对」在、「真错配」不在。

读数（新用例，两环境）：

| 环境 | 命令 | 读数 |
|---|---|---|
| 宿主（本机装着 `3007678964`） | `pytest "...::test_crosscheck_行号不可比不判红_真报告阴性对照" -q -n0 -rs` | `1 passed in 0.56s` |
| 隔离（`V3_ROOT`/`V3_USERDIR`/`V3_WORKSHOP` = `Z:/nope`） | 同上 | `1 passed in 0.47s`（**无 skip**） |
| 宿主 / 隔离 | `pytest tests/test_cli.py -q -n0 -k crosscheck -rs` | `5 passed, 44 deselected in 0.81s` / `… 0.80s` |

⚠️ `-k crosscheck` 现在是 **5 条**（原有 4 条 + 本卡新增那条名字里也含 `crosscheck`）。
原有的 4 条没被动过，单独验证：`-k crosscheck --deselect "...::test_crosscheck_行号不可比不判红_真报告阴性对照"`
⇒ `4 passed, 45 deselected in 0.78s`。

- **变异检验**（`tools/out/_d34_mutate.py` 生成副本，各只改**被判对象**、不动断言）：
  - **M1 输入变异**（新用例夹具的生效版 6 行 → 4 行 ⇒ 现场不再是"行号不可比"）：
    `pytest tools/out/_d34_mutant_input.py -q -n0 -k 真报告阴性对照` ⇒ `1 failed, 48 deselected`，
    红在 `assert rep.incomparable_tokens`：`AssertionError: 夹具没造出「行号不可比」这一档，钳子就无从夹起`
    / `assert []`（报告里 `line_counts={'gui/panel.gui': (4, 4)}`）—— 证明"条件造不出来就过"这条路被堵死。
  - **M2 实现变异**（`cli.py:1756` `EXIT_UNVERIFIABLE` → `EXIT_FAILED`，即"把不可核对记到不一致头上"
    的旧病；`_d34_mutant_impl.py` 把 `pdx.cli` 换成这份变异模块）：同上命令 ⇒ `1 failed, 48 deselected`，
    红在 `assert 1 == 3`（`+ where 1 = <Result SystemExit(1)>.exit_code`）—— 证明这条断言真在判实现。
    ⚠️ 该变异只改退出码、不改文案，输出里仍印着"本命令退出码 3"而实际退出 1 —— 用例抓的正是这个脱离处。
- 三份副本跑完已删（`_d34_mutant_input.py` / `_d34_mutant_impl.py` / `_d34_mutant_cli.py`）；
  生成脚本 `tools/out/_d34_mutate.py` 保留，可复现。
- `src/pdx/cli.py` **未动**（mtime `2026/9/29 0:20:13`、162,499 B，早于本卡开工）：变异只在 `tools/out` 的副本里做。

门禁读数（三份副本已删、最终交付态；`tests/test_cli.py` = `eb69d7bf…` / 935 行 / 46,326 B）：

| 命令 | 读数 |
|---|---|
| `pytest tests/test_cli.py -q -n0` | `49 passed in 209.67s`（exit 0） |
| `ruff check .` | `All checks passed!`（exit 0） |
| `ruff format --check .` | `249 files already formatted`（exit 0） |
| `mypy --no-incremental` | `Success: no issues found in 146 source files`（exit 0） |

## 已知过时引用（D34 追加；B112：只追加，不改旧字）

| # | 位置 | 过时说法 | 现在的事实 | 归属 |
|---|---|---|---|---|
| 1 | `tools/probe/perf_compare.py:50` | 这条用例「会因本机 mod 集不同而红」 | D29 起用例自带夹具，不再读宿主机 mod 集 | 别卡 inScope，**只登记** |
| 2 | `docs/design/exec/接续说明.md:134` | 同上（「这条用例会因 mod 集不同而红」） | 同上 —— 该说法**已不成立** | 别卡 inScope，**只登记** |
| 3 | `docs/reports/t32-CI-闸门与基准-核对.md:125` | test_cli.py 的跳过计数/行号含已删的 `:170`/`:172` | D29 删了那两条 skip，计数与行号**过时** | 别卡 inScope，**只登记**（交 t18 收口） |
| 4 | 本文件 §8 的行号表 | 是 D29 交付态（`9352b35f…` / 889 行）的读数 | D34 改动后已位移（现 935 行）：负对照仍 `:379`，无日志用例 `:518` → `:564` | 本文件：旧字保留，新读数见 §9 |
| 5 | 本文件 §5 末那条「不属于本卡范围，只登记」 | 负对照 `:507` 的宿主依赖分支「没日志就不看守」 | **D34 已补齐**（分支移出 + 夹具断言，见 §9） | 本文件：旧字保留 |

\n