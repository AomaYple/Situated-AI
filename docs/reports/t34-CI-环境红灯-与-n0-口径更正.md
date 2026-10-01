# t34 —— CI 环境三条红灯的处置与 `-n0` 口径更正

一句话结论：三条红**不是判据变松，也不是环境噪声** —— 它们判的是「两套来源对不对得上」（快照池 vs 游戏池、薄包装的现算路径）与「问题集恰好只有 P1」，**缺游戏树时这三件事做不了**。本卡把三条改成显式跳过（reason 点名缺的路径），并给出两种环境的并列读数：无游戏 **0 failed**、有游戏树时三条**照旧真跑**。同时更正三处过时注释：`-n0` **能用**，真正会让基准静默降级的是**缺 `--benchmark-only`**。

- 任务：`t34`（attempt `c0e919d5-59e0-48c1-a8e7-2fb52de7a218`）
- 上游证据：`docs/reports/t32-CI-闸门与基准-核对.md`（三条红在 CI 自身环境里必然红）
- 日期：2026-09-29（所有读数均为本机实测，含秒级起止与退出码）

---

## 一、三条红的逐条二值处置

| # | 用例（改动前行号） | 处置 | 为什么只能是这一档 | 改动后行号 |
|---|---|---|---|---|
| 1 | `tests/test_modguard_offline.py:59` `test_快照源与游戏源的键池一致` | 挂 `@_needs_game_tree` | 判据是**快照池与游戏池逐域相等**，两个来源必须同时在场。缺游戏树时 `vanilla_index.game_index(config.GAME)` 返回 `None`（`:64` 的 `assert game is not None` 就是抓这个）。**不能真离线化**：只读快照的替代判据恰好会放过「离线池窄于在线池」——那正是这条用例存在的理由。 | `:73` |
| 2 | `tests/test_modguard_offline.py:151` `test_薄包装在游戏源下仍然现算` | 挂同一守卫 | 名字里就写着「现算」：断言 `modguard.vanilla_keys(config.GAME / "common" / "defines")` 非空（`:154`）、`modguard._vanilla_vocabulary(config.GAME)` 走得通（`:155`）。无游戏树时得到的 `set()` 不是「键池为空」，是「没得可读」。 | `:169` |
| 3 | `tests/test_objectives.py:206` `test_备份后缀判红P1` | 挂**已有**的 `@_needs_game` | 判据是「问题集**恰好**只有 P1」；无游戏树时 P3（引用要在原版文件里解得开）与 P4（`derive()` 要读原版开局牌与牌面 type）会额外成立 ⇒ 实得 `{'P1','P3','P4'}`（t32 读数）。这不是判红，是**问不出**。 | `:210` |

守卫本身的定义（`tests/test_modguard_offline.py:32-36`）：

- `_GAME_TREE = config.GAME / "common"`
- `_GAME_TREE_MISSING = f"无游戏树：{_GAME_TREE} 不存在（这条判据要比对『游戏源』的键池，缺了它无从核对）"`
- `_needs_game_tree = pytest.mark.skipif(not _GAME_TREE.is_dir(), reason=_GAME_TREE_MISSING)`

`tests/test_objectives.py:30-36` 把既有 `_needs_game` 的 reason 从「游戏目录不可用（要查原版开局牌与牌面 type）」改成**点名路径**的「无游戏树：…（要查原版开局牌与牌面 type）」，并给 `test_备份后缀判红P1` 挂上；docstring 写清「不是判红，是问不出」。

**没变松的证明**：`git diff` 里 `assert` 的增删行 = **0**（扫描命令见 §六）；两个测试文件的改动只有注释、docstring、装饰器、常量与 reason 文本，断言一字未动。

同族但**故意不动**的两条：`test_子目录里的toml判红P1`（`tests/test_objectives.py:185`）与 `test_换扩展名也是同一种静默写法`（`:217`）断言只比 substring 与退出码，无游戏树也能过。

---

## 二、两种环境的读数并列（acceptance ②）

### A. 无游戏全量 = CI 第 4 步原文

- 环境：`V3_ROOT=<TEMP>\t34-nogame\steamapps\common\Victoria 3`、`V3_USERDIR=<TEMP>\t34-nogame-userdir\Paradox Interactive\Victoria 3`、`V3_WORKSHOP` **不设**、`PYTEST_XDIST_AUTO_NUM_WORKERS=2`
- 命令：`.venv\Scripts\python.exe -m pytest -m "not integration" -q -rs --no-header`
- 读数：02:16:27 → 02:17:22（54.5 s）**1644 passed, 125 skipped, 24 subtests passed, 0 failed**，EXIT=0，峰值 RSS 545.7 MB
- 基线（t32 同命令同环境，02:10:18 → 02:11:08）：**3 failed**, 1639 passed, 122 skipped，EXIT=1

⇒ **failed 3 → 0**；skipped 122 → 125，多出来的正是这三条（两条 modguard + 一条 objectives），且都带点名路径的理由。**总数不逐项可比**：期间队友在改仓库（passed 1639 → 1644，多 5 条用例），所以本卡的判据只用「failed 归零 + 三条以显式 skip 出现在 `-rs` 里」，不用总数相等。

### B. 无游戏定向（为了读理由）

- 命令：`.venv\Scripts\python.exe -m pytest tests/test_modguard_offline.py tests/test_objectives.py -q -n0 -rs --no-header`
- 读数：02:19:41 → 02:19:53（11.6 s）**27 passed, 9 skipped in 10.48s**，EXIT=0
- 三条目标出现在 SKIPPED 行上，理由文本完整可读（控制台码页会把中文弄花 ⇒ 输出重定向到文件 + `PYTHONIOENCODING=utf-8`，**读文件**）：

```
SKIPPED [1] tools\tests\test_modguard_offline.py:73: 无游戏树：C:\Users\28905\AppData\Local\Temp\t34-nogame\steamapps\common\Victoria 3\game\common 不存在（这条判据要比对『游戏源』的键池，缺了它无从核对）
SKIPPED [1] tools\tests\test_modguard_offline.py:169: 无游戏树：…（同上）
SKIPPED [1] tools\tests\test_objectives.py:210: 无游戏树：…不存在（要查原版开局牌与牌面 type）
```

### C. 有游戏树（本机，`V3_*` 全不设）

| 命令 | 起止 / 耗时 | 读数 | EXIT | 峰值 RSS |
|---|---|---|---|---|
| `pytest tests/test_modguard_offline.py tests/test_objectives.py -q -n0 -rs --no-header` | 02:17:48 起 / 15.4 s | **36 passed** in 13.81 s，**零 skip** | 0 | — |
| `pytest … -v -k "快照源与游戏源的键池一致 or 薄包装在游戏源下仍然现算 or 备份后缀判红P1"` | 4.1 s | 3 selected，**三条全 PASSED** | 0 | — |
| `pytest tests/test_benchmarks.py -q -n0 --benchmark-only` | 02:18:19 起 / 26.7 s | **18 passed**, 1 warning in 25.69 s，基准表打满 | 0 | 237.8 MB |

⇒ 三条在**有游戏树时照旧真跑**，没有被守卫误跳；基准专项那张表本身就是「`-n0` 能用」的现场证据。

---

## 三、三处注释更正：`-n0` 与 `--benchmark-only`

**机制**（实测 + 读源码）：`xdist/plugin.py` 在 `config.option.numprocesses == 0` 时把 `config.option.dist` 归一成 `"no"`；`pytest_benchmark/session.py` 的 `xdist_active = config.getoption('dist','no') != 'no'` 据此为假 ⇒ 插件不禁用自己 ⇒ `-n0 --benchmark-only` 正常出表。相反，**不带 `--benchmark-only`** 时基准被**静默降级**：用例照跑、退出码照 0、一条计时读数都没有（实测 18 passed / EXIT=0 / 无基准表 / 5.50 s）——外观与「真测过」完全相同。

| 文件:行 | 改前要点 | 改后要点 |
|---|---|---|
| `pyproject.toml:146-162` | 「跑基准必须把 addopts 清掉…`-n0` **不管用**（实测报 "Can't have both --benchmark-only and --benchmark-disable"）」 | 「跑基准必须显式带 `--benchmark-only`…2026-09-29 更正（t34，实测）：旧注释『`-n0` 不管用』**不成立** —— `-n0` 时 xdist 把 `dist` 归一成 `no`，pytest-benchmark 据此不判并发 ⇒ 能跑出基准表；**纪律不变、理由改口**」 |
| `tests/test_benchmarks.py:8-14` | 「必须清掉 addopts…`-n0` 不管用，实测报错」 | 「**必须带 --benchmark-only**：默认 addopts 带 `-n auto`，xdist 真的并发时 pytest-benchmark 会自动禁用自己」 |
| `docs/design/exec/收口清单.md:186-190` | 「跑基准要把 addopts 整个清掉 —— `-n0` 不管用」 | 「2026-09-29 更正（t34 实测）：`-n0` **能用**（归一成 `dist=no`，实测 18 passed / 有基准表 / EXIT=0）；真正静默降级（18 passed / EXIT=0 / 无基准表）的是缺 `--benchmark-only`」 |

**配置项的值一个字没动**（`addopts` 仍是 `-n auto --dist loadscope` 那一段）；纪律结论不变（跑基准显式带 `--benchmark-only`，照旧建议 `-o addopts=""`）。`tools/README.md:272`、`docs/design/exec/自动化范式.md:434` 只是**用法**提到 `-n0`，不改。

---

## 四、没动 ci.yml（acceptance ③）

- `git diff --stat -- .github/workflows/ci.yml` = `1 file changed, 1 insertion(+), 1 deletion(-)` —— 这一行**不是本卡的**：`docs/reports/t32-CI-闸门与基准-核对.md`（02:0x 读数）与本次看到的都是 `:83` 注释「171 张生成表」→「172 张生成表」，逐字相同。
- 藏红扫描：`Select-String -Path .github/workflows/ci.yml -Pattern 'deselect|xfail|continue-on-error|-k not'` = **0 命中**。
- 本卡的测试改动里没有 xfail / `--deselect` / `-k not`：三条走的是显式 `skipif`，理由是**环境不满足就不做判据**，并点名缺的路径。

---

## 五、残余缺口（把代价说清）

1. **CI 上「快照池 == 在线池」这条不再被守**：`test_快照源与游戏源的键池一致` 在无游戏环境跳过。要恢复只能等 CI 有游戏树；在离线侧另造「快照自身的域覆盖」判据**不能替代**它（快照池窄于游戏池正是它要抓的假绿）。建议由 `t13` 的逐条对账记账。
   - 快照这一侧在 CI 仍有牙：`tests/test_modguard_offline.py` 另外 12 条在无游戏环境下照跑并全过（含「离线未覆盖 ≠ 空集」「快照缺域 ⇒ 退出 2」），`tests/test_modguard_branches.py` 读的也是真快照。
2. **Actions 历史取不到**：`web_fetch https://github.com/AomaYple/Situated-AI/actions` 被沙箱拒（`URL hostname "github.com" resolves to a non-public IP address`）⇒「CI 是否曾绿」无法用页面核对。本文结论只依赖本机复现，而 ci.yml 里 `grep V3_` **零命中** ⇒ 本机模拟与 CI 同性质（都不设 `V3_ROOT/USERDIR/WORKSHOP`）。
3. **峰值 RSS 口径**：「非基线 python 进程 WorkingSet 合计」按 700 ms 采样取峰值，含 xdist worker。无游戏全量那次 **545.7 MB** 超过 200 MB 指引，但当时持旗标（`tools/out/mem/owner-t34-offline.flag`），台账 `tools/out/mem/WINDOW.md` 记有开工/收工两行。

---

## 六、证据附录

| 命令 | 读数 | EXIT |
|---|---|---|
| `ruff check tests/test_modguard_offline.py tests/test_objectives.py tests/test_benchmarks.py` | `All checks passed!`（02:19:41 批次） | 0 |
| `ruff format --check`（同三文件） | `3 files already formatted` | 0 |
| `mypy --no-incremental` | `Success: no issues found in 146 source files`，11 s（02:18:48） | 0 |
| 无游戏定向（见 §二B） | 27 passed, 9 skipped | 0 |
| 无游戏全量（见 §二A） | 1644 passed / 125 skipped / **0 failed** | 0 |
| 有游戏三连（见 §二C） | 36 passed / 3 selected 全 PASSED / 18 passed 有基准表 | 0 |

- diffstat（本卡，`git diff --stat`）：5 files changed, 54 insertions(+), 15 deletions(-)
  —— `docs/design/exec/收口清单.md` 5 行级、`pyproject.toml` 19 行级、`tests/test_benchmarks.py` 5 行级、`tests/test_modguard_offline.py` 26 行级、`tests/test_objectives.py` 14 行级。
- 「断言没被改」扫描：`git --no-pager diff -- tests/test_modguard_offline.py tests/test_objectives.py | Select-String -Pattern '^[-+]\s*(assert|.*assert )'` ⇒ **输出为空**。

---

## 七、本卡纪律

- 开工 02:15:41 建旗标 `tools/out/mem/owner-t34-offline.flag`（与实机队列的 `owner-t34.flag` **区分**，仓里另有一张同号实机卡）；收工行与删旗标记在 `tools/out/mem/WINDOW.md`。
- 只改 inScope 声明的路径：`tests/test_modguard_offline.py`、`tests/test_objectives.py`、`tests/test_benchmarks.py`、`pyproject.toml`、`docs/design/exec/收口清单.md`，加本报告。`mod/`、`src/pdx/**`、`.github/workflows/ci.yml` 一字未动。
