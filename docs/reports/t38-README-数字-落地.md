# t38：README 计数落地（1868→1885 条用例 / 77→82 个测试文件 / 171→172 张生成表）

任务：t4（= t38）。**结论**：两个 README 的机械数字已按**现跑读数**改准，全仓正则扫的每一处命中都逐处判过「前瞻 / 历史」——前瞻的 36 行落盘、历史的（`docs/design/exec/**` 带日期页、`docs/reports/**`、`.agent-teams/**`、`CHANGELOG.md`、知识库里的「本次」记录）**一处数字未动**（B112）。守卫 `tests/test_repo_numbers.py` 的两条红已消，四道 v3 离线门禁与相关文档门禁全绿。

落盘时间：2026-09-28 23:23:16（第一遍）· 23:34:05（第二遍）· 23:35:30（第三遍）。执行者：档案工程师（t4，attempt `83f9feff-c461-4401-80ac-42716081727b`）。

---

## 1. 现读三条数（命令 + 原始输出）

本卡只认「现跑」，不抄别人的报告。以下输出为 2026-09-28 23:35 前后的当刻读数（`$env:PYTHONIOENCODING='utf-8'`，cwd = 仓库根）。

### ① 用例数

```powershell
.venv\Scripts\python.exe -m pytest --collect-only -q -n0 -p no:randomly --no-header
```

```
1885 tests collected in 1.32s
```

（与此前同一命令的读数对照：22:5x 那次是 `1868 tests collected in 2.42s` —— 变的原因见 §2。）

### ② 测试文件数

```powershell
Get-ChildItem tools\tests\test_*.py -File | Measure-Object | Select-Object -ExpandProperty Count
# 守卫口径等价写法：len(sorted(REPO.joinpath('tools','tests').glob('test_*.py')))
```

```
82
```

三口径并列（**口径不同，数就不同**，报告里必须写清用哪个）：

| 口径 | 现读 | 说明 |
|---|---|---|
| 盘上 `tests/*.py`（全部） | 87 | 含 `conftest.py` 等非用例文件 |
| 盘上 `tests/test_*.py` | **82** | **守卫口径**（`test_repo_numbers.py` 用 glob 扫盘），README:152 写的就是这个 |
| `git ls-files tests/test_*.py` | 81 | 入库口径；差的那 1 个是 `tests/test_probe_stage6.py`（见 §7 未收项 1） |

### ③ 生成表数

```powershell
.venv\Scripts\v3.exe tables --offline
```

```
快照里记录的 172 张生成表都与文档一致
```

同源核对（断言注册表口径，与表数是两回事，此处只作旁证）：`v3 verify --from-snapshot` ⇒ `通过 43 / 43    失败 0    （离线真值覆盖 43/234 条…）` + `文档正文与断言表一致`。

---

## 2. 数字在落地期间变了两次（时序留痕）

读数不是常量，本卡在制期间被同队工作改过两次，**都留痕**，不追改历史：

| 时刻 | 事件 | 用例数 | 测试文件（盘上） |
|---|---|---|---|
| 22:5x | 本卡开工读数（t111 交付的输入也报同一组） | 1868 | 81 |
| 23:19:06→23:25:39 | 内存分析师 t5 全量基线（`docs/reports/全量基线-2026-09-28.md`） | 收集 1868 / 通过 1858 / 失败 5 / 跳过 5 / 496 subtests / 391.48 s | 81 |
| 23:23:16 | 本卡第一遍落盘（1630→1868、77→81、171→172 等 36 行） | 1868 | 81 |
| 23:26:55→23:32:56 | 本卡全量（`tools/out/t38-fullrun.txt`） | 收集 1868 / `2 failed, 1861 passed, 5 skipped, 496 subtests passed in 360.50s` | 81 |
| 23:34:05 | 本卡第二遍落盘（括号里的执行期读数改成指向全量基线） | 1868 | 81 |
| **23:34:52** | **功能工程师 t1 落 `tests/test_probe_stage6.py`（27,362 B，+17 条用例）** | **1885** | **82** |
| 23:35:30 | 本卡第三遍落盘（1868→1885、81→82） | 1885 | 82 |

**两条全量的红各不相同**（t5 5 红 / 我 2 红），且都带并发写树污染 ⇒ **不把「N 通过」写进 README 状态表**（会把污染或环境红固定成状态），改成：README 只写收集数 + 指向 `docs/reports/` 的全量基线；交接页 `接续说明.md:42` 带日期写全（并标明那是基线当时的收集数）。我的那 2 条红：① `test_audit_leftovers.py::test_ruff_format_通过`（跑动期 `tools/probe/stage6_ui_rerun.py` 在制）② `test_cli.py::test_crosscheck_与引擎日志一致`（环境：Workshop mod「Ultra Historical Warfare」覆盖 `gui/military_formation_panel.gui`、`gui/panel_military.gui`，与 1.14.3 日志行号不可比）；5 条 SKIPPED 全在 `test_engine_crosscheck.py:94/:155/:116/:144/:126`，同一理由。

---

## 3. 全仓正则扫（写明模式 + 命中统计）

脚本（只读）：`tools/out/t38-scan.py`（v1）、`tools/out/t38-scan3.py`（v3，补扫）。排除 `.git/.venv/node_modules/__pycache__/.pytest_cache/.mypy_cache/.ruff_cache/out/coverage/official-docs`。

| 版 | 模式 | 扫描文件 | 命中 |
|---|---|---|---|
| v1 | `(1630\|1868\|1622\|\d+\s*个测试文件\|\d+\s*条用例\|\d+\s*张生成表\|171\s*张\|172\s*张\|按条件跳过)` | 417 | 146（含 `.agent-teams/**`）/ 102（去 `.agent-teams`） |
| v3 | `(67\|68) 个产物\|(850\|949) 条引用\|(234\|211\|191\|43) 条断言\|88\.50%\|88\.07%\|54 个模块\|(1630\|1868\|1622\|1810)…条用例\|\d+ 个测试文件\|(169\|171\|172) 张(生成表\|表)\|按条件跳过` | 412 | 87 / 32 文件 |

输出：`tools/out/t38-scan-latest.txt`（全量）、`t38-scan-repo.txt`（去 `.agent-teams`）、`t38-digest.txt`、`t38-scan3.txt`、`t38-scan3-digest.txt`。

命中分布（v3，前几名）：`docs/design/exec/团队台账-停机副本-20260925.md` 15、`tools/README.md` 10、`docs/reports/t38-输入-收集数基线.md` 10、`README.md` 7、`阶段7-长期维护.md` 5、`接续说明.md` 4，其余 1–3。

> 教训（留档）：v2 补扫最初写成 PowerShell 内联 `-c` 字符串，`chr(92)` 被 PowerShell 吞掉 ⇒ `SyntaxError: unterminated string literal`，扫描没跑成。**扫描脚本要写成 `.py` 文件再跑**，不要在 PowerShell 里内联正则。

---

## 4. 逐处判定：前瞻（要改）/ 历史（不许动数字）

判据出处 = B112 原文 `docs/design/backlog.md:353`（t18 立的规矩：① 前瞻性声明重测后改准 ② 历史读数一律不许改数字，最多补「当时」二字）。

### 4.1 前瞻 —— 已改（7 文件 / 36 行 / 38 处替换）

| 文件 | 行 | 改动 |
|---|---|---|
| `README.md` | :8 | `**67 个产物**…850 条引用` → `**68 个产物**…949 条引用` |
| | :104 / :122 / :192 | `171 张` → `172 张`（生成表） |
| | :133 | `**1630 条**用例（1622 通过 / 8 按条件跳过）` → `**1885 条**用例（`pytest --collect-only` 实测；整套读数见 `docs/reports/` 的全量基线）` |
| | :151 | `54 个模块` → `58 个模块`（`src/pdx/*.py` 不含 `__init__.py`，现算 58） |
| | :152 | `77 个测试文件 / 1630 条用例` → `82 个测试文件 / 1885 条用例` |
| `tools/README.md` | :91 / :183 / :221 / :478 / :506 | `171 张` → `172 张` |
| | :184 | `850 条引用` → `949 条引用`（`v3 citations --offline` 现读） |
| | :208 / :491 | `1630 条用例` → `1885 条用例` |
| | :189 / :195 | 补「当时」二字、**数字不动**（`当时 850 条里 827 条报 missing` / `当时 827/850`） |
| `.github/workflows/ci.yml` | :83 | 注释里的 `171 张生成表` → `172 张` |
| `src/pdx/tables_offline.py` | :5 | docstring 的 `169 张生成表` → `172 张` |
| `src/pdx/snapshot.py` | :225 | 注释的 `169 张生成表` → `172 张` |
| `docs/design/exec/接续说明.md` | :31 | `67 个产物` → `68 个产物` |
| | :32 / :33（各 1 处）+ :41（2 处）+ :119 | `850 条引用` → `949 条引用`；:41 另有 `modgen --check 67 产物` → `68` |
| | :42 | `**1625 条**（1617 通过 / 8 按条件跳过）` → `**1885 条**（收集数；2026-09-28 全量基线当时收集 1868，跑出 **1858 通过 / 5 按条件跳过 / 5 红**，红的逐条归属见 `docs/reports/全量基线-2026-09-28.md`）` |
| | :116 | `171 张` → `172 张` |
| `docs/design/exec/阶段7-长期维护.md` | :16 / :65 / :71 / :81 | `171` → `172`（张 / 张表） |
| | :66 | `32 产物` → `68 产物` |
| | :20 / :70 / :82 | `850` → `949`（条引用） |
| | :79 | 补「当时」（`当时 1434 条，全量`），**数字不动** |

判「前瞻」的理由：这些句子陈述的是**当前仓库状态**（README 状态表、目录树说明、`ci.yml` 为什么跑这条门禁、交接页的「现状」格），读者会拿它们当今天的数。逐处核对命令见 §1；`58 个模块` 与 `949 条引用` 是本次扫出来、t111 输入里没有的两处漂移。

### 4.2 历史 —— 一处数字未动

- `docs/design/exec/**`：`团队台账-停机副本-20260925.md`（含 :507）、`团队终局快照-20260925-任务清单.txt`、`夜间进展.md`、`阶段性收尾-20260925.md`、`阶段3/4/5/7-*.md`、`并行测试内存基线.md:295`（`（README 写 1630、实测收集 1640）`）、`收口清单.md:280`、`接续说明.md:78`（带日期的历史段）。
- `docs/reports/**`：`t38-输入-收集数基线.md`、`新增牌复核.md:110`、`t98-模板闸门-独立复核.md`、`全量基线-2026-09-28.md`（内存分析师 t5 的，未动）、`docs/audits/**`（重构前审计）。
- `.agent-teams/**`（团队会话记录，只读）。
- `CHANGELOG.md:58`（发布说明条目）。
- `docs/victoria3-modding/08:16、11:7、14:4、18:9、19:8、20:7`：`本次 v3 tables 核对全部 171 张生成表都与文档一致` —— 过去某次运行的记录（带 1.14.4 时点），历史。
- `docs/design/backlog.md` 的 147/15/4/4/3/8 条：**单卡规模**，不是全仓总数。
- 代码里的局部数字：`src/pdx/modgen.py:1733`（61 条用例）、`src/pdx/install_tree.py:37`（doc 05 的 5 张）、`tests/test_doc17.py:1`（doc 17 的 24 张）。
- `research/official-docs.manifest.json:59` 出现的 `1868` 是字节/哈希巧合，不是用例数。
- `docs/design/exec/阶段5-目标函数表-口径.md`：t96 已按 B112 收口（「历史读数『67（游戏侧 57）』原样留档」+「今天同一批命令给的是 68 / 58」），本卡**未动**。

### 4.3 引用风险面（改之前先查，避免改数破引用）

`v3 citations` 的口径 = 每条引用记**被引文件的文件行数 + 被引那一行的文本指纹** ⇒ 本卡所有编辑都做「**同行内字面量替换、行数不变**」。grep 全仓 `README\.md:\d+` / `接续说明\.md:\d+` / `长期维护\.md:\d+` / `tables_offline\.py:\d+` / `snapshot\.py:\d+` / `ci\.yml:\d+`：引用点只有 `tools/README.md:121 / :157-166 / :116 / :129`、`tools/probe/README.md:102-105 / :132`、`zh/README.md:26`、`接续说明.md:158 / :159 / :177`、`阶段7-长期维护.md:186` —— **与本次改的行全不相交**；改完 `v3 citations --offline` 仍是 `949 条引用全部有入库支撑 ✅`（exit 0），闭环。

---

## 5. 改动清单 + B119 备份 + 自证

**改动规模**：7 个文件、36 行、38 处替换（`README.md:8` 与 `接续说明.md:41` 各含 2 处）。`git diff --stat` 显示 ±成对（同行替换、行数不变）；同批 `tools/probe/stage6_ui_rerun.py` 的 +493 行是功能工程师 t1 的改动，**不属于本卡**。

**B119 备份（逐字节，`tools/out/backup/`）**：

| 文件 | 备份名 | 字节 | sha256 |
|---|---|---|---|
| `README.md` | `t38-20260928-231746-README.md` | 16,290 | `FB860F1779…17C9C` |
| `tools/README.md` | `t38-20260928-231746-tools__README.md` | 59,617 | `06B832B864…4563` |
| `.github/workflows/ci.yml` | `20260928-232238-.github__workflows__ci.yml` | 12,202 | `AE6A23CDB1…1569` |
| `src/pdx/tables_offline.py` | `20260928-232238-tools__pdx__tables_offline.py` | 4,876 | `848F312D44…33E2` |
| `src/pdx/snapshot.py` | `20260928-232238-tools__pdx__snapshot.py` | 15,828 | `3888BE79F1…4A7A` |
| `docs/design/exec/接续说明.md` | `20260928-232238-docs__design__exec__接续说明.md` | 24,130 | `2BA0FF4B74…7B16` |
| `docs/design/exec/阶段7-长期维护.md` | `20260928-232238-docs__design__exec__阶段7-长期维护.md` | 16,634 | `B7381C2E65…8E033` |

第二 / 第三遍写盘前，又各自对**当刻**状态做了一份备份（`*-pass1-*.md` / `*-pass2-*.md`，`逐字节相同=True`）⇒ 三遍都能重放。

**自证（不靠自己声明）**：`tools/out/t38-verify.py` 用**备份 vs 现盘逐行 diff** 独立复算，而不是重放替换脚本：

```
✅  README.md            行数 246→246 · 改动 7 行（期望 7） · 无BOM/无CRLF/末尾LF=True · 越界 0
✅  tools/README.md      行数 511→511 · 改动 10 行（期望 10） · …
✅  .github/…/ci.yml     行数 228→228 · 改动 1 行（期望 1） · …
✅  src/pdx/tables_offline.py  128→128 · 1 行 · …
✅  src/pdx/snapshot.py        388→388 · 1 行 · …
✅  docs/…/接续说明.md    行数 239→239 · 改动 7 行（期望 7） · …
✅  docs/…/阶段7-长期维护.md      207→207 · 改动 9 行（期望 9） · …
合计改动 36 行；出问题的文件数 = 0
```

每一行改动必须满足「只换数字」或「只插『当时』」，否则退出码 1；两处执行期读数的整行改写登记在脚本的 `DECLARED` 白名单里（**显式声明**，不是靠正则放过）。逐行明细：`tools/out/t38-verify-diff.txt`。三遍落盘脚本：`tools/out/t38-apply.py` / `t38-apply2.py` / `t38-apply3.py`（都是两段式：先全查命中数，任一不符**整批不写盘**），日志 `tools/out/t38-apply-log.txt`。

---

## 6. 门禁复跑（全部 exit 0）

| 命令 | 结果 |
|---|---|
| `pytest tests/test_repo_numbers.py tests/test_docs_consistency.py tests/test_quote_audit.py tests/test_inventory.py -q -n 0` | **24 passed in 15.29s**（t111 报的两条红已消：`test_README里的用例数与实际收集一致`、`test_README里的机械数字与仓库现状一致`） |
| `v3 citations --offline` | `949 条引用全部有入库支撑（离线：与入库快照一致）✅` |
| `v3 tables --offline` | `快照里记录的 172 张生成表都与文档一致` |
| `v3 verify --from-snapshot` | `通过 43 / 43    失败 0（…覆盖 43/234 条）` + `文档正文与断言表一致` |
| `v3 modgen --check` | `盘上 68 个产物与数据源逐字节一致 ✅` |
| `ruff check src/pdx/tables_offline.py src/pdx/snapshot.py` | `All checks passed!` |

（`v3 preflight` 一并看过：`产物一致 68 个产物与数据源逐字节一致`；其中 `content_load.json.sitai-backup` 是提示，不拦路。）

---

## 7. 未收项 / 风险（**下一位别当成已完成**）

1. **`tests/test_probe_stage6.py` 未入库**（`git status` 显示 `??`，功能工程师 t1 的在制单测）⇒ 现读的 **82 个测试文件**是「盘上口径」（守卫口径），**干净克隆会算 81**。入库后两边都是 82；在那之前别用 `git ls-files` 口径复算。同理：这个文件一入库、或 t1 再补用例，**用例数会继续变**，守卫 `test_repo_numbers.py::test_README里的用例数与实际收集一致` 会立刻报出期望值 —— 按它的提示改 README 两处（`README.md:133 / :152`）与 `tools/README.md:208 / :491` 即可。
2. **覆盖率三处读数不一致**：`README.md:134` 写 88.50%、`接续说明.md:41` 写 88.53%、`tools/README.md:474` 写 88.07%。本卡**没有重测**（要跑 `v3 cov`，属运行时读数），只登记 —— 建议由覆盖率的归属卡重测后统一，别抄旧数。
3. **历史读数的清单**在 §4.2。若以后有人要把它们改准，请先改「前瞻 / 历史」的判据本身（B112），不要直接改数字。
4. 读数在制期间被写两次（§2）：本报告里**任何一处数字都带时点**；引用时请连带口径一起引。
5. `v3 preflight` 报的 `content_load.json.sitai-backup` 提示、`test_cli.py::test_crosscheck_与引擎日志一致` 的环境红（Workshop mod 覆盖两份 gui）都不是本卡能收的，已登记。

---

## 8. 产物索引

- 报告：本文件（`docs/reports/t38-README-数字-落地.md`）
- 输入：`docs/reports/t38-输入-收集数基线.md`（t111）
- 全量基线：`docs/reports/全量基线-2026-09-28.md`（t5）；本卡那一跑 `tools/out/t38-fullrun.txt`
- 扫描：`tools/out/t38-scan.py` / `t38-scan3.py` + `t38-scan-latest.txt` / `t38-scan-repo.txt` / `t38-digest.txt` / `t38-scan3.txt` / `t38-scan3-digest.txt`
- 落盘：`tools/out/t38-apply.py` / `t38-apply2.py` / `t38-apply3.py` + `t38-apply-log.txt`
- 自证：`tools/out/t38-verify.py` + `tools/out/t38-verify-diff.txt`（36 行明细）
- 备份：`tools/out/backup/t38-*`（见 §5 表）
- 机器锁：`tools/out/mem/owner-t38.flag` + `tools/out/mem/WINDOW.md` 的开工 / 收尾两条
