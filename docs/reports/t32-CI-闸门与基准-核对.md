# t32 —— CI 的闸门与基准：独立核对（含静默跳过清单）

**核对对象**：`.github/workflows/ci.yml`（全仓唯一 workflow，227 行、LF；工作区 sha256
`45e0ada060390b347f97579cfe8c35a425e755874d809118405d13131736289f`。与 `HEAD`（`2188a3a`）的**唯一**
差异是别人把 `v3 tables --offline` 步骤注释里的「171 张」改成「172 张」，工作区 HEAD 版 sha256
`ae6a23cdb124a58c93516c804c59079a1157ca967d5c493ecaad688c0a881569`）。
**本机对 CI 环境的模拟口径**：CI 不装游戏、也不设 `V3_*`（ci.yml 里 grep `V3_` 零命中，只有一句注释提到
`V3_ROOT`），于是 `pdx/config.py:52-63` 的 `resolve()` 会落到候选清单里第一个**存在**的路径、一条都不存在时用
确定的回落值 —— 三者都指向不存在的路径。本卡用
`V3_ROOT=<TEMP>\t32-nogame2\steamapps\common\Victoria 3`（形状与真实安装一致，好让 `WORKSHOP` 由 ROOT 反推出的
形状仍对）、`V3_USERDIR=<TEMP>\t32-nogame2-userdir\Paradox Interactive\Victoria 3`、`V3_WORKSHOP` **不设**
来复现。探针实测：`GAME=…\Victoria 3\game is_dir=False`、`WORKSHOP=…\steamapps\workshop\content\529340`
（`parts[-2:] == ('content', '529340')`）。

> 这一条口径必须写在最前面：**「CI 里配了」不等于「CI 上绿」**。本卡能核对的是
> ① 每条闸门是不是 ci.yml 里的一条 `run`（文件名 + 行号 + 步骤名 + 命令原文），
> ② 在 CI 的同等环境（无游戏）里**今天**这些命令会给出什么（逐条 EXIT）。
> Actions 的历史结论本机取不到（见文末「残余不确定」）。

## 一、结论

1. **基准那半格成立**：`bench` job 真在跑 `pytest-benchmark`，参数原文是
   `python -m pytest tests/test_benchmarks.py -o addopts="" --benchmark-only --benchmark-json=bench.json -q`
   （`.github/workflows/ci.yml:169-175`），结果写进 job summary（`:177-178`，`tools/ci/bench_summary.py`）并存
   artifact（`:180-183`）。**不断言**（`:138-141` 的口径表 + `tools/README.md:191`）。
2. **13 道门禁里 11 道在 CI**（另 `v3 lock` 在 `lock` job）：ruff check、ruff format --check、mypy、
   pytest、`v3 verify --from-snapshot`、`v3 tables --offline`、`v3 modgen --check`、`v3 modguard --offline`、
   `v3 ai-surface --check --offline`、`v3 citations --offline`、`v3 release`。
   缺的 4 道是 `v3 snapshot verify`、`v3 preflight`、`v3 cov`、`v3 objectives --check` —— 逐条「今天为什么不可加」
   见 §三。
3. **但第 4 道（pytest）在 CI 自己的环境里必然红 3 条**：三条用例依赖游戏本体、却既没有 `integration` 标记、
   也没有 `_needs_game` 守卫。**「闸门与基准进 CI」（`docs/design/01-大方向.md:137`、`docs/design/exec/阶段4-框架化.md:9`）
   今天不能按「已在 CI 上绿」记账**；`docs/design/exec/阶段7-长期维护.md:63` 那行「`pytest -m "not integration"` ✅ CI」
   不成立。详见 §二。

## 二、13 道门禁逐条（C.1 顺序：`docs/design/exec/收口清单.md:138` §C.1，表 `:143-157`）

| # | C.1 里的门禁 | ci.yml 落点（行 + 步骤名） | 命令行原文 | CI 同等环境（无游戏）本机读数 | 判 |
|---|---|---|---|---|---|
| 1 | `ruff check .` | `:57-58` `ruff —— 代码检查` | `ruff check .` | EXIT=0 `All checks passed!`（0.03 s，02:13:09→02:13:09） | ✅ 在 |
| 2 | `ruff format --check .` | `:60-61` `ruff —— 格式检查` | `ruff format --check .` | EXIT=0 `246 files already formatted`（0.03 s，02:13:09） | ✅ 在 |
| 3 | `mypy --no-incremental` | `:63-64` `mypy —— 类型检查` | `mypy`（**没有** `--no-incremental`） | bare：EXIT=0 / 0.4 s（缓存热）；`--no-incremental`：EXIT=0 / 11 s —— 两条都 `Success: no issues found in 146 source files`（02:12:26） | ✅ 在（旗标差异无害，见 §二注） |
| 4 | `pytest -q` | `:66-69` `pytest —— 不依赖游戏的用例` | `python -m pytest -m "not integration"` | **EXIT=1**：`3 failed, 1639 passed, 122 skipped, 24 subtests passed in 49.18s`（02:10:18→02:11:08） | ⚠️ 在但**红** |
| 5 | `v3 verify` | `:71-80` `v3 verify —— 用入库快照核验一部分断言` | `v3 verify --from-snapshot` | EXIT=0 `文档正文与断言表一致`（0.6 s，02:13:04） | ✅ 在 |
| 6 | `v3 tables` | `:82-89` `v3 tables --offline —— 用入库快照核验生成表` | `v3 tables --offline` | EXIT=0 `快照里记录的 172 张生成表都与文档一致`（0.7 s，02:13:04→02:13:05） | ✅ 在 |
| 7 | `v3 ai-surface --check` | `:112-116` `v3 ai-surface --check --offline —— 可执行面（同一份快照）` | `v3 ai-surface --check --offline` | EXIT=0（0.66 s，02:13:07；尾句「证明的是『文档与入库快照一致』，不是『与现在的游戏一致』」） | ✅ 在 |
| 8 | `v3 citations` | `:118-125` `v3 citations --offline —— P10 的引用在 CI 上也守得住` | `v3 citations --offline` | EXIT=0 `949 条引用全部有入库支撑（离线：与入库快照一致）✅`（0.59 s，02:13:07→02:13:08） | ✅ 在（离线口径，B99：不能替代 live） |
| 9 | `v3 modguard` | `:98-110` `v3 modguard --offline —— 五道闸门（原版真值走入库快照）` | `v3 modguard --offline` | EXIT=0 `五道闸门全过 ✅`（0.8 s，02:13:06→02:13:07；另印「离线未覆盖 1 项（**不算通过**）」） | ✅ 在 |
| 10 | `v3 release` | `:127-132` `v3 release —— 发布说明 ↔ 档案 ↔ 元数据三边一致` | `v3 release` | EXIT=0 `发布说明、档案、元数据三边一致 ✅`（9 份档案；0.47 s，02:13:08） | ✅ 在 |
| 11 | `v3 modgen --check` | `:91-96` `v3 modgen --check —— 产物与数据源逐字节一致` | `v3 modgen --check` | EXIT=0 `盘上 68 个产物与数据源逐字节一致 ✅`（0.62 s，02:13:05→02:13:06） | ✅ 在 |
| 12 | `v3 snapshot verify` | **CI 里没有** | — | 无游戏：**EXIT=2** `找不到游戏目录 …`（`src/pdx/cli.py:824` `snap_verify()` 第一行 `:829` `_require_game()`；`_require_game` 在 `:168-175` 明说「缺了就退出码 2，而不是让满屏『0 个文件』被误信」） | ❌ 不可加 |
| 13 | `v3 preflight` | **CI 里没有** | — | 无游戏：**EXIT=2** `2 条前置条件缺失 —— 这台机器现在跑不了这一局`（`docs/design/exec/收口清单.md:157` 记「无游戏时按设计 exit 2」） | ❌ 不可加 |
| 13+1 | `v3 cov` | **CI 里没有**（`src/pdx/cli.py:2053-2055` 原文写着「这条不进 CI … CI 上没有游戏，覆盖率口径完全不同」） | — | 需游戏 + 覆盖率（`pyproject.toml:202` `fail_under = 86`）；「无游戏必误报」的理由写在 `ci.yml:7-12` | ❌ 按设计本地 |
| （第 14 道） | `v3 objectives --check`（`收口清单.md:222` C.2：t40 落地后成第 14 道） | **CI 里没有** | — | 无游戏：**EXIT=1，总红 13**（P1 红 0 · P2 红 0 · **P3 红 10** · **P4 红 3** · P5 红 0）。逐条例：`common/ai_strategies/03_political_strategies.txt 不存在`；`tr_defeat · P4 · verdict.kind · 落盘 opening_card ≠ derive() 算出的（无规则成立）`（02:08:04→02:08:28 那一批读数） | ❌ **没有离线通道** |
| 另 | `v3 lock`（不在 13 道里，但在 CI） | `:219-223` `v3 lock —— 装出来的环境与锁逐条一致` | `v3 lock` | EXIT=0 `requirements.lock 与当前环境一致（57 条）`（0.51 s，02:13:08→02:13:09） | ✅ 在（`lock` job = windows-latest；本机这条只证明命令本身能跑） |

**§二注（mypy 的旗标）**：C.1 `:190-193` 要求「`mypy` 必须 `--no-incremental` 且不带文件参数」，CI 写的是裸 `mypy`。
两者在 CI 上等价（全新检出没有 `.mypy_cache`，第一次就是全量），本机实测也一致（146 文件、两条都 EXIT=0）。
本卡**不改这一行**：它不是「缺失的门禁」，改它属于给 CI 加一个没有判据支撑的旗标（且会让 CI 每次跑都在冷缓存上多花 ~10 s）。

## 三、缺口一（红灯）：三条用例在 CI 的环境里必然红

无游戏环境下 `python -m pytest -m "not integration"` 的三条红（它们是**非** `integration`、**非** `_needs_game` 的用例）：

| 用例 | 位置 | 断言与实测 | CI 上为什么也红 |
|---|---|---|---|
| `test_快照源与游戏源的键池一致` | `tests/test_modguard_offline.py:59`（红在 `:64`） | `assert game is not None, "本机没有游戏本体"` ⇒ `AssertionError: assert None is not None` | 该文件 `pytestmark = pytest.mark.unit`（`:22`），**没有任何** skip 守卫；`git diff --stat origin/main HEAD -- tests/test_modguard_offline.py` 为空 ⇒ 与最后一次 push 的版本逐字节相同；`git show origin/main:…` 里 grep `skip`/`_needs`/`allow_module_level`/`GAME_OK` **零命中** ⇒ 那次 CI 也会红这一条 |
| `test_薄包装在游戏源下仍然现算` | `tests/test_modguard_offline.py:151`（红在 `:154`） | `assert keys, "游戏源下读不到 defines 顶层键"` ⇒ `assert set()` | 同上（同一文件、同一提交） |
| `test_备份后缀判红P1` | `tests/test_objectives.py:206`（红在 `:214`） | `assert {problem.predicate …} == {"P1"}` 实得 `{'P1', 'P3', 'P4'}` | P3/P4 要读 `config.GAME`（`src/pdx/objectives.py:406/:432/:471/:520/:768`）⇒ 无游戏必多出这两类问题。⚠️ 该文件**不在 `origin/main` 里**（`git show origin/main:tests/test_objectives.py` = `fatal: path … exists on disk, but not in 'origin/main'`）⇒ 属未推送的新用例，CI 下次跑就会红 |

**反证（不是「改坏了」）**：同一三条在**有游戏**时全绿 ——
`pytest tests/test_modguard_offline.py tests/test_objectives.py -q -n0 -m "not integration"
-k "备份后缀判红P1 or 快照源与游戏源的键池一致 or 薄包装在游戏源下仍然现算"` = `3 passed, 33 deselected in 1.65s`，EXIT=0（本机 02:1x）。
⇒ 判据是「游戏在不在」，与代码改动无关。

**修法（不在本卡 inScope，建议单开一卡）**：给这两处加与全仓同形的守卫
（`_needs_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")`，
`tests/test_cli.py:50` 就是现成例子），而不是往 ci.yml 里塞 `--deselect`/`xfail`：
后者是把红藏起来（B85 一族：把「核对不了」写成「通过」）。`tests/test_objectives.py:31` 已经有同形守卫，
只是没挂到这两条上 —— 同一文件内自相矛盾，正说明这是漏挂而不是设计。

## 四、缺口二：`v3 objectives --check` 今天没有离线通道（第 14 道的路被堵着）

`收口清单.md:222`（C.2）写着「`v3 objectives --check`：未实现（t40 落地后成第 14 道）」。t40 已落地（命令存在：
`src/pdx/cli.py:1090` `objectives`），但**在 CI 的环境里它不可能是绿的**：无游戏实测 EXIT=1、总红 13，
红的是 P3（引用要在原版文件里解得开）与 P4（`derive()` 要读原版开局牌与牌面 type）。
⇒ 要让它进 CI，得先给它一条离线真值通道（照 `vanilla_index` 的快照域路子）**或**明确登记它是 live-only。
本卡只登记缺口，不动它。

## 五、基准专项（阶段 4 出口判据的「与基准」）

CI 里跑基准的是**独立 job**（`:154-183`），而不是 `check` job 的 pytest —— 理由是绝对墙钟在共享 runner 上会抖动，
只能「只报告不断言」（`:138-141`、`docs/design/exec/阶段7-长期维护.md:132-145`）。

| 跑法 | 命令行原文 | benchmark 条数 | 跳过 | 退出码 | 起止 / 耗时 |
|---|---|---|---|---|---|
| A（CI bench job 参数，本机有游戏） | `python -m pytest tests/test_benchmarks.py -o addopts="" --benchmark-only --benchmark-json=<TEMP>\t32-bench-ci.json -q` | 18 条（基准表打满 18 行） | 0 | **EXIT=0** | 02:06:45→02:07:11 / 25.01 s |
| B（`-n0` + `--benchmark-only`，addopts 仍在） | `python -m pytest tests/test_benchmarks.py -n0 --benchmark-only -q` | 18 条（**基准表照出**） | 0 | **EXIT=0** | 02:07:19→… / 25.05 s |
| C（默认 addopts、不带 `--benchmark-only`） | `python -m pytest tests/test_benchmarks.py -q` | **0 条，没有任何基准表** | 0 | **EXIT=0**（假绿） | …→02:07:51 / 5.50 s（B+C 合计 32.5 s） |
| A′（CI bench job 参数，**无游戏**＝CI 真实环境） | 同 A | **14 条** | **4 条** | **EXIT=0** | 02:08:04→02:08:28 / 20.46 s |

* A′ 的 4 条跳过在 `tests/test_benchmarks.py:109/116/123/133`（`@_needs_game`，见 `:95-96` 与 `:129-130`），
  理由「游戏目录不可用」⇒ **CI 的 bench job 每次真测 14 条**（合成样本 + gametimer + 自动抓图），
  本机 18 条只是因为本机装了游戏。
* **C 才是风险所在**：不带 `--benchmark-only` 时基准被静默降级成「每条调一次」，**条数照 18、退出码照 0、
  输出里没有任何基准表** —— 与「真测过」外观完全相同（这正是 B85 一族：把「没测」装成「测过」）。
  CI 之所以没踩：bench job 显式清了 addopts 并带 `--benchmark-only`（`:170-175` 注释也写明了理由）。
* **仓库那条「`-n0` 不管用」已经过时**（三处：`pyproject.toml:148-155`、`tests/test_benchmarks.py:8-24`、
  `收口清单.md:186-188`）。实测 B 的基准表照出。机制：
  `.venv/Lib/site-packages/xdist/plugin.py:326-328` `if config.option.numprocesses == 0: config.option.dist = "no"; config.option.tx = []`，
  而 pytest-benchmark 判活是 `.venv/Lib/site-packages/pytest_benchmark/session.py:77`
  `xdist_active = config.getoption('dist','no') != 'no' or self.xdist_worker` —— `-n0` 下 `dist == 'no'` ⇒ 不判为并发 ⇒ 基准**不会**被禁用。
  它报「`Can't have both --benchmark-only and --benchmark-disable`」的条件见 `:97-98`，自动禁用的警告见 `:110-118`。
  ⇒ **纪律仍然成立**（本机跑基准要清 addopts），但理由要改口：不是「`-n0` 不管用」，而是「`-n0` 时 xdist 会把自己改成 `dist=no`，
  于是基准能跑；真正需要的是 `--benchmark-only`，否则静默降级」。本卡**不改**这三处注释（它们是别人的 inScope），只登记。

## 六、静默跳过清单（「CI 真跑过 / CI 里跳过了 / CI 里没跑」）

无游戏环境下 `-m "not integration"` 的汇总：**1639 passed / 122 skipped / 24 subtests passed / 3 failed，EXIT=1，49.18 s**。

**122 条跳过按文件**（计数取自跑出来的日志，按 `SKIPPED [n]` 的 n 相加）：

| 文件 | 条数 | 理由（源码原文 + 位置） |
|---|---|---|
| `tests/test_cli.py` | 24 | `:50` `_needs_game`（`游戏目录不可用`）；`:170`「本机没有引擎日志（需要运行过一次游戏）」；`:172`「日志来自探针会话（只加载了探针 mod）」 |
| `tests/test_probe_lint.py` | 23 | `:31` `游戏目录不可用（要查原版名字池）`；`:41` `本机没有 t73 归档的真产物（它只在跑过那一局的机器上有）` |
| `tests/test_cli_more.py` | 13 | `:26` `_needs_game` |
| `tests/test_objectives.py` | 6 | `:31` `游戏目录不可用（要查原版开局牌与牌面 type）` |
| `tests/test_cli_new_commands.py` | 6 | `:26` `_needs_game` |
| `tests/test_coverage.py` | 5 | `:38` `_needs_game` |
| `tests/test_benchmarks.py` | 4 | `:42` `_needs_game`（`@_needs_game` 在 `:95-96`、`:129-130`） |
| `tests/test_ab_probe.py` | 3 | `:168`/`:258` `游戏目录不可用`；`:993`「这台机器没有游戏本体 ⇒ 跳过交叉 preflight」 |
| `tests/test_probe_stage3.py` | 2 | `:261`/`:280`「没有游戏本体」 |
| `tests/test_citations.py` | 2 | `:138`「本机没有游戏本体，引用无法核对」、`:257`「本机没有游戏本体，核对不了现场」 |
| `tests/test_repo_numbers.py` | 2 | `:105`/`:158`「…这一条只有装了游戏的机器上判」 |
| `tests/test_install_hygiene.py` | 2 | `:35` `_needs_game` |
| `tests/test_docs_mirror.py` | 1 | `:114` `_game`（`游戏目录不可用`） |
| `tests/test_mod_hygiene.py` | 1 | `:123` `游戏目录不可用（要扫原版脚本）` |
| `tests/test_conftest.py` | 1 | `:82`「本机没有游戏本体，且只验证无游戏时的路径」 |
| `tests/test_parser.py` | 1 | `游戏目录不可用`（`_needs_game`） |
| `_pytest/unittest.py:523` | 26 | `unittest.SkipTest` 走 pytest 的 skip 通道（`tests/conftest.py:33-51` 给带 `integration` 的 item 统一加的 skip 从这条通道出来） |

* ⚠️ **口径声明**：上表**理由**按源码原文写（`reason=` 的出处逐条可查）；**计数**取自跑出来的日志（按文件统计，
  ASCII 部分可靠）。日志里的**理由文本**在 PowerShell 重定向时被本机码页弄花、**不可逐字回读** ⇒ 本卡不假装读了它
  （B85 同族：读不到就说读不到）。
* 另有**全局**一处：`tests/conftest.py:30` `GAME_OK = (pdx_config.GAME / "common").is_dir()`，`:33-51`
  `pytest_collection_modifyitems(config, items)` 在无游戏时给每个带 `integration` 关键字的 item 挂
  `pytest.mark.skip(reason=f"游戏目录不可用：{pdx_config.GAME}")`（`:48`）。形参必须叫 `config` 的坑写在 `:36-44`，
  `tests/test_conftest.py` 守着（它此前因形参遮蔽 `pdx.config` 导致 INTERNALERROR）。
* `content_load.json` 一族**不是** skip：`tests/test_preflight.py:35-53` 与 `tests/test_probe_stage6.py:190-231`
  用 monkeypatch 把它与备份落点指到临时目录（属于「能跑就跑」，比 skip 好）。

**三分类**（本卡要的那条区分）：

* **CI 里真跑过（本机同等环境也过）**：ruff check / ruff format --check / mypy / `v3 verify --from-snapshot` /
  `v3 tables --offline` / `v3 modgen --check` / `v3 modguard --offline` / `v3 ai-surface --check --offline` /
  `v3 citations --offline` / `v3 release` / `v3 lock`；以及 `bench` job 的 14 条基准。
* **CI 里跑但会红**：`python -m pytest -m "not integration"` 的 3 条（§三）。
* **CI 里跳过了**：122 条（上表）—— 它们**不提供任何保证**；「闸门在 CI 上守一半」的实质就是这个数。
* **CI 里根本没跑**：`v3 snapshot verify`、`v3 preflight`、`v3 cov`、`v3 objectives --check`；
  以及任何 live 版 `v3 verify` / `v3 tables` / `v3 citations`（B99：`--offline` **不能**替代 live，
  `docs/design/backlog.md:183`）、`v3 crosscheck`（要引擎日志）。
* **本机核对不到**：① Linux 运行时（本卡只能模拟「无游戏」，不能模拟 ubuntu；反向的
  `tests/test_mem_baseline.py:488` `skipif(not _IS_WIN)` 是「CI 上跳过、本机跑」，方向相反）；
  ② Actions 的真实历史结论（见文末）。

## 七、本卡对 `ci.yml` 的改动：**零行**

判据是任务书第 ④ 条「只在本地 EXIT=0 的前提下才把缺失的门禁/基准补进 ci.yml」。逐条核过了：

* 缺的 4 道里，`snapshot verify` 与 `preflight` 在无游戏时**按设计 EXIT=2**（读数见 §二 #12/#13）——加进去就是把
  「这台机器跑不了」写成红灯；`cov` 是 `src/pdx/cli.py:2053-2055` 与 `ci.yml:7-12` **明说不进 CI**；
  `objectives --check` 无游戏 EXIT=1（总红 13），没有离线通道。**四条都不满足「本地 EXIT=0」。**
* 基准已经进了（`bench` job），本卡只是把它的读数补齐（§五）。
* 第 4 道 pytest 的红，病在**用例缺守卫**，不在 ci.yml。往 ci.yml 里加 `--deselect`/`-k` 排除是放宽判据（任务书禁令），
  **不做**。
* 顺带核过两件容易漏的：`tools/ci/bench_summary.py`（3570 B）对本机 A 的 `bench.json` 实跑 EXIT=0、
  吐出 18 行中文基准表 ⇒ `:177-178` 那一步是能跑的；`requirements.lock` 在仓库根（1494 B）⇒ `lock` job 的安装步骤有输入。

## 八、残余不确定（如实登记）

1. **Actions 的真实历史结论本机取不到**：`git remote -v` = `https://github.com/AomaYple/Situated-AI.git`；
   本地 `main` 领先 `origin/main`（= `9e74b73`，2026-09-24「基准进 CI：新增 bench job…」）**9 个提交**，工作区还有 34 项未提交改动。
   本卡试过取 Actions 页，沙箱直接拒（`web_fetch` → `URL hostname "github.com" resolves to a non-public IP address`）。
   ⇒ 「CI 曾经绿过」这件事**本卡不能作证**；能作证的是「在 CI 的同等环境（无游戏）里，今天这些命令会怎么做」。
2. **平台差异**：`origin/main` 与工作区的相关代码（`src/pdx/config.py`、`src/pdx/vanilla_index.py`、
   `src/pdx/objectives.py`、`src/pdx/modguard.py`、`tests/test_modguard_offline.py`、`test_objectives.py`、
   `test_portability.py`）在本会话里**都没被改过**（`git status --porcelain` 对这些路径为空），
   所以本机读数对应的是同一份代码；但 ubuntu 运行时（locale、路径分隔符、`chcp`）本卡只做了静态核对，
   没有实机。
3. **本卡自己的一个手工失误，留档当教训**：第一轮无游戏模拟（02:08:40→02:09:31）我把 `V3_WORKSHOP` 也指到了临时目录，
   于是 `tests/test_portability.py:183` 的 `assert config.WORKSHOP.parts[-2:] == ("content", str(config.APP_ID))`
   被我自己弄红（`('Temp','t32-nogame-workshop')`）⇒ 那一轮的 `4 failed` 里**有 1 条是假红**。
   第二轮把 `V3_ROOT` 指成形状正确的 `…/steamapps/common/Victoria 3`、`V3_WORKSHOP` **不设**之后才是 `3 failed`（§三）。
   教训：模拟「无游戏」时**不要**顺手改 Workshop 的形状 —— 那会把「环境缺游戏」变成「环境被改坏」，两者红的原因不同。
4. **`origin/main` 上的 `ci.yml` 版本**本卡没有逐行比对（只比了工作区 ↔ HEAD，差异 1 行注释）。
   §二的表引的是**工作区**行号 + 工作区 sha256，便于别人复核。

## 九、证据附录（每条都记了起止、命令原文、退出码）

| 起止 | 命令（原文） | 读数 |
|---|---|---|
| 02:06:45→02:07:11 | `.venv\Scripts\python.exe -m pytest tests/test_benchmarks.py -o addopts="" --benchmark-only --benchmark-json=%TEMP%\t32-bench-ci.json -q` | 18 passed，EXIT=0，25.01 s |
| 02:07:19→02:07:51 | `.venv\Scripts\python.exe -m pytest tests/test_benchmarks.py -n0 --benchmark-only -q` 与 `… tests/test_benchmarks.py -q` | 18 passed / EXIT=0（25.05 s，有基准表）；18 passed / EXIT=0（5.50 s，**无基准表**） |
| 02:08:04→02:08:28 | 无游戏会话：`v3 preflight`、`v3 snapshot verify`、`v3 objectives --check`、以及 bench 文件的 CI 参数复跑 | EXIT=2 / EXIT=2 / EXIT=1（总红 13）/ `14 passed, 4 skipped` EXIT=0（20.46 s） |
| 02:08:40→02:09:31 | 无游戏模拟第一轮：`python -m pytest -m "not integration" -q -rs --no-header`（`V3_ROOT`/`V3_USERDIR`/`V3_WORKSHOP` 全指临时路径） | 4 failed / 1637 passed / 123 skipped / EXIT=1（含 1 条自造假红，见 §八.3） |
| 02:10:18→02:11:08 | 无游戏模拟第二轮（形状正确、`V3_WORKSHOP` 不设）：同一命令 | **3 failed / 1639 passed / 122 skipped / 24 subtests passed / EXIT=1**；probe：`WORKSHOP.parts[-2:] == ('content','529340')` |
| 02:12:26 | `.venv\Scripts\python.exe -m mypy`；`.venv\Scripts\python.exe -m mypy --no-incremental` | EXIT=0 / 0.4 s；EXIT=0 / 11 s，两条都 `Success: no issues found in 146 source files` |
| 02:13:04→02:13:09 | 无游戏环境逐条复跑 CI 的 10 条命令（见 §二表的「命令行原文」列） | 全部 EXIT=0，逐条耗时 0.03–0.8 s |
| 02:1x（-n0） | `python -m pytest tests/test_modguard_offline.py tests/test_objectives.py -q -n0 -m "not integration" -k "备份后缀判红P1 or 快照源与游戏源的键池一致 or 薄包装在游戏源下仍然现算"` | **3 passed, 33 deselected in 1.65s**，EXIT=0（有游戏时全绿的反证） |
| 02:13 | `git diff --stat HEAD -- .github/workflows/ci.yml`；`git show origin/main:tests/test_modguard_offline.py`；`git diff --stat origin/main HEAD -- …` | 1 行注释改动（171→172 张）；pushed 版含两条无守卫断言；该文件与 pushed 版逐字节相同 |

**峰值 RSS**：本轮所有命令的单条峰值都没超过「解释器 + 参考套件」量级（最长的一条 = pytest 49 s / mypy 11 s），
但**本卡未对每条命令单独采峰值 RSS**（无采样器在场）⇒ 如实登记「未采」，不写近似值。
