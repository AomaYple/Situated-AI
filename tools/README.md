# tools —— Python 工具链

Victoria 3 游戏本体与 mod 的信息处理工具链。核心解析与提取逻辑在 `pdx/` 包里，
**只用标准库**；命令行外壳用 typer + rich（表格与状态输出），
`--profile` 另需 pyinstrument。

> 早期版本用 PowerShell（10 个脚本）与 Node.js（2 个原型）实现，已全部退休。
> 退休原因见文末「为什么全 Python 化」。

## 环境与安装

```
.venv/                          Python 3.14 虚拟环境（已 gitignore）
.venv\Scripts\python.exe        解释器
.venv\Scripts\v3.exe            命令行入口（安装后生成）
```

```powershell
# 开发模式安装：装 pdx 包 + typer/rich + dev 依赖（pytest/ruff/mypy/pyinstrument）
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

> 注意：`powershell` 这个代码块标记只是**语法高亮**用；整条工具链本身
> 已不含任何 PowerShell 脚本，命令在 cmd / pwsh / bash 下都能跑
> （把 `.venv\Scripts\` 换成 `.venv/bin/` 即可）。

装好之后 `pdx` 可被任意目录下的 Python 导入（不再需要 `sys.path` 补丁），
并生成 `v3` 入口。**不装也能跑**：`python -m pdx.cli` 完全等价。

## 包结构 `pdx/`

| 模块 | 职责 |
|---|---|
| `model.py` | 数据模型：`Assignment` / `Block` / `Scalar` / `ParsedFile` |
| `lexer.py` | 词法：引号感知的注释剥离、运算符识别、行号追踪 |
| `parser.py` | 语法：递归下降，**花括号深度判定顶层**；`TOLERATED_ERRORS` 定义可容忍异常 |
| `cache.py` | 解析缓存，保证同一文件只解析一次 |
| `config.py` | 路径与常量，支持 `V3_ROOT` / `V3_USERDIR` / `V3_WORKSHOP` 覆盖 |
| `scan.py` | 文件系统扫描与统计 |
| `extract.py` | 目录级条目与字段提取 |
| `defines.py` | defines 专用提取（命名空间、参数形态、覆盖预览） |
| `mods.py` | Workshop 与本地 mod 分析 |
| `analyze.py` | 全量分析（游戏本体 / mod / 交叉，**分开存储**） |
| `snapshot.py` | 版本快照与两份快照的 diff |
| `verify.py` | 断言注册表，把文档里的数字变成可执行检查；产物核验与文档漂移扫描 |
| `localization.py` | 本地化专用提取（`.yml` 是行式格式，**不是** PDX 花括号语法） |
| `tabular.py` | 表格类数据（`.csv`），分隔符靠 `csv.Sniffer` 嗅探 |
| `engine_log.py` | 从游戏日志抽外部真值：枚举清单、脚本位置、token 位置 |
| `console.py` | stdout/stderr 的 UTF-8 兜底（**必须在构造 rich Console 之前调用**） |
| `cli.py` | 唯一的命令行入口，`v3` 的全部子命令 |

## 命令行 `v3`

7 个各自为政的旧入口脚本（`run_analyze.py` / `run_defines.py` / `run_index.py` /
`run_snapshot.py` / `run_verify.py` / `check_outputs.py` / `show_outputs.py`）
已删除，功能全部并入：

| 子命令 | 取代 | 作用 |
|---|---|---|
| `v3 analyze` | `run_analyze.py` | 全量分析并落盘：`--no-mods` `--no-cross` `--no-write` `--quiet` `--profile` |
| `v3 defines` | `run_defines.py` | defines 提取：`--ns NAME` `--json PATH` `--overlay FILE` `--tables [--write]` |
| `v3 index` | `run_index.py` | 重生成 `docs/victoria3-modding/13-common全量键名索引.md`：`--dry-run` |
| `v3 snapshot create/list/diff/verify` | `run_snapshot.py` | 版本快照：`--label` / `--compact`（精简，可入库） / `--detail` / `--json PATH` |
| `v3 verify` | `run_verify.py` | 核对文档里的数量断言**并扫描文档正文的数字漂移**：`--fast` `--only ID` `--no-drift` `--unregistered` `--json PATH` |
| `v3 crosscheck` | （新增） | 用**游戏自己的日志**交叉验证解析：覆盖面、行号、token 识别 |
| `v3 check-outputs` | `check_outputs.py` | 核验**已落盘产物**是否与断言注册表一致 |
| `v3 show` | `show_outputs.py` | 转储产物的结构与规模 |

```text
.venv\Scripts\v3.exe analyze                     # 全量分析，落盘报告
.venv\Scripts\v3.exe analyze --no-mods --quiet   # 只分析游戏本体，不打印进度
.venv\Scripts\v3.exe analyze --profile           # 附 pyinstrument 调用树
.venv\Scripts\v3.exe verify --fast               # 只跑不需要全库扫描的断言
.venv\Scripts\v3.exe verify --unregistered       # 列出文档里尚未登记的数量断言
.venv\Scripts\v3.exe check-outputs               # 核验产物（需先 analyze）
.venv\Scripts\v3.exe defines --ns NAI            # 展开某个 defines 命名空间
.venv\Scripts\v3.exe index --dry-run             # 只统计，不写文档
.venv\Scripts\v3.exe snapshot diff A B --detail  # 比对两份快照
.venv\Scripts\v3.exe show                        # 产物里到底有什么
.venv\Scripts\v3.exe <子命令> --help             # 每个子命令都有中文帮助
```

### 退出码

| 码 | 含义 |
|---:|---|
| 0 | 成功 |
| 1 | 检查未通过（`verify` / `check-outputs` / `snapshot verify`） |
| 2 | 用法错误，或前置条件缺失（游戏目录、产物、快照文件不存在） |

约定：**不存在「吞掉异常然后返回 0」的路径**。需要容错时只捕
`pdx.parser.TOLERATED_ERRORS` 这类精确异常集合，并且必须把失败原因打出来。

### 几个约定

* `--json` 在所有子命令里都表示**输出文件路径**（`Path`），不再是「写死的落点开关」。
* 相对路径一律相对仓库根显示；在仓库外运行会退回绝对路径，不会抛 `ValueError`。
* `add_completion=False`：工具链不往用户目录写补全脚本。

## 测试

```text
python -m pytest                    # 配置在 pyproject.toml 的 [tool.pytest.ini_options]
python -m pytest -m "not slow"      # 跳过慢用例
python -m pytest --cov=pdx          # 覆盖率（门槛 86%，见 pyproject）
```

446 条用例（`pytest --collect-only` 实测；443 通过 / 3 按条件跳过），
全部对应**实际踩过的坑**，不是凭空构造：

| 测试文件 | 覆盖的坑 |
|---|---|
| `test_lexer.py` | 注释内花括号、字符串中的 `#`、`?=` 不被拆开、行号追踪 |
| `test_parser.py` | BOM 污染首键、含连字符的键、`c:SWE` 不被误认为前缀、缩进的顶层键、`=` 与 `{` 分行 |
| `test_scan.py` | 递归计数、后缀过滤、真实游戏树的结构断言 |
| `test_extract.py` | 字段只收第一层、前缀归类、跨文件合并、已知条目数 |
| `test_analyze.py` / `test_golden.py` | 产物结构与指纹回归（产物被改坏要立刻失败） |
| `test_snapshot.py` / `test_verify.py` | 快照确定性、精简快照的结构等价性、断言注册表口径 |
| `test_defines_tables.py` | doc 05 那 5 张统计表的**生成链**：表头还在、生成是幂等的、文档现值 == 生成结果 |
| `test_properties.py` / `test_metamorphic.py` / `test_lexer_differential.py` | hypothesis 属性测试、变形测试、与独立 oracle 实现的差分对比 |
| `test_benchmarks.py` | 性能基准（`pytest-benchmark`，回归即失败） |
| `test_cli.py` | CLI 端到端：参数解析、退出码、入口点可用性、GBK 控制台不崩 |
| `test_cache.py` | 缓存透明性：`parse_cached` 必须恒等于 `parse_file` |
| `test_coverage.py` | **覆盖面契约**：每个文件必须归入四类之一，落不进就失败 |
| `test_conftest.py` | 「没有游戏就自动跳过集成用例」这条机制本身（子进程真跑一次收集） |
| `test_data_dump.py` | 结构化转储：必须能取到**值**而不只是字段名 |
| `test_defines.py` | defines 提取：参数形态、命名空间合并、覆盖预览 |
| `test_docs_consistency.py` | 文档数字与断言表的一致性（防文档过期） |
| `test_docs_mirror.py` | `research/official-docs/` 的时效性：篇目集合、**逐字节 sha256**、无多余文件 |
| `test_localization.py` | `.yml` 本地化：语言覆盖、键去重、BOM 处理 |
| `test_engine_crosscheck.py` | 用游戏日志当**外部真值**核对解析 |

### 跑基准要加 `-n0`

`pytest-benchmark` 在 xdist 开启时会**自动禁用自己**，而本项目默认并行
（`-n auto`）。因此不带 `-n0` 时基准会被静默跳过 —— 实测踩过：

```text
python -m pytest tools/tests/test_benchmarks.py --benchmark-only -n0
```

## 输出产物

**分开存放** —— 游戏本体与 mod 互不混杂：

```
tools/out/game/游戏本体.json      统计口径：条目、字段、使用频次（约 8.2 MB）
tools/out/game/游戏数据.json      内容口径：字段、值、嵌套结构、行号与注释（约 54 MB）
tools/out/game/本地化.json        14.5 万个本地化键（约 6.1 MB）
tools/out/game/表格数据.json      adjacencies.csv 等表格类数据
tools/out/mods/mod.json          mod 全量数据（约 640 KB）
tools/out/cross/交叉.json         两者的覆盖关系
tools/reports/游戏本体分析.md      人可读报告
tools/reports/mod分析.md          人可读报告
```

上面 8 项由 `v3 analyze` **一次**产出（也就是黄金回归冻结的那 8 份）。

另有**独立**的一条线：

```
tools/out/snapshots/<版本>.compact.json   精简快照，约 4.9 MiB（**入库**，跨机器可 diff）
tools/out/snapshots/<版本>.json           完整快照，约 39 MiB（gitignore，本机深挖用）
```

> 上面的 MB / KB 按 1024 进制。精确值由黄金回归（`tools/tests/test_golden.py`）
> 冻结为逐产物的「字节数 + sha256」，改动一个字节就会失败。
>
> ⚠️ **快照分两种，只有精简版入库**：完整快照 73% 的体积是本地化键清单
> （11 种语言 × 14.5 万键），而「Paradox 增删了哪些字段与条目」只需要结构域。
> 精简版保留 `common_entries` / `fields` / `defines` / `dlc` / `config` 五个域，
> 只把 `localization` 换成「键数 + sha256」，因此 **不到 5 MiB 就能随仓库分发**，
> 让 `v3 snapshot diff` 在别人的克隆里也能跑。
> 想知道**具体**改了哪些本地化键，才需要那份约 39 MiB 的完整快照。
>
> 两者**形状相同**，`compare` 对谁都能用；但**别拿精简版与完整版对 diff** ——
> 那会把整个本地化域报成「全删 + 全增」。文件里有 `精简` 标记，可据此判断。

`tools/out/` 已 gitignore（随时可由 `v3 analyze` 重建）；
`tools/reports/` **入库** —— 两份报告是研究成果的一部分，改动它们应当出现在 diff 里。

## 解析器的五条铁律

这些是踩坑换来的，改代码时不要违反：

```
1. 用花括号深度判断顶层        —— 官方文件混用 tab / 空格 / 无缩进
2. 剥离 BOM                    —— common 下 3,026 个 .txt 有 3,002 个带 BOM
3. 注释剥离要引号感知          —— 字符串里可能含 #
4. 键名字符集用「非空白非等号」  —— 存在含连字符的键（全库 32 个）
5. 识别 6 个功能前缀           —— INJECT: / REPLACE: 等，且**只 mod 用**
```

另有两条口径纪律，都曾导致过真实错误：

* **`@变量` 不是数据条目** —— `00_defines.txt` 顶部 22 个，误计会让命名空间块数从 75 变成 97
* **空目录也要收录** —— `scripted_modifiers` 只有 `.md` 没有 `.txt`，靠「有没有 `.txt`」数目录会得到 135 而非 136

## 性能剖析 `prof/`

`pdx` 包本身不埋点，剖析用独立脚本跑：

```text
.venv\Scripts\python.exe tools/prof/prof_e2e.py full          # 整条流水线（冷缓存）+ 调用树
.venv\Scripts\python.exe tools/prof/prof_e2e.py stages        # 逐阶段冷缓存剖析
.venv\Scripts\python.exe tools/prof/prof_e2e.py walkaudit     # 文件系统被重复遍历的程度
.venv\Scripts\python.exe tools/prof/prof_e2e.py prefixaudit   # 功能前缀扫描的范围与耗时
```

阶段序列与 `v3 analyze` 保持一致，因此剖析结果可以直接用来解释 `analyze` 的耗时。

> ⚠️ **`full` / `stages` / `walkaudit` 会重跑整条分析流水线，覆盖已入库的
> `tools/reports/*.md` 与 `tools/out/**`。** 它们不是只读命令：
> 跑完 `git status` 会脏。产物应当逐字节相同（黄金回归冻结了 sha256），
> 若真变了就说明有非确定性 bug —— 这反而是个有用的信号。
> 只有 `prefixaudit` 是纯读的。

## 控制台编码

中文 Windows 的控制台是 GBK 代码页，`print("✅")` 会抛 `UnicodeEncodeError`
—— **重定向到管道时同样会抛**。入口处统一调 `pdx.console.enable_utf8_stdio()`。

`rich` 替代不了它：实测 `Console().print("✅")` 在 GBK 下一样抛。

## 已知边界

工具链能回答：某个类型有哪些字段、取值什么形态、定义在哪个文件第几行、
本地化键存不存在、某个目录有哪些条目。

**不能**回答（信息不在文件里，不是功能没做）：

| 答不了的问题 | 为什么 |
|---|---|
| 两个 mod 改同一条目谁生效 | 取决于运行期加载顺序，脚本里没有 |
| 某字段的合法取值范围 | 只有引擎知道；二进制里有候选词表但未开采 |
| 同名条目里哪个最终生效 | 引擎的合并规则，未知 |
| 平衡性与 AI 实际表现 | 要跑游戏才知道 |

## 为什么全 Python 化

| 原因 | 具体表现 |
|---|---|
| PowerShell 5.1 的编码陷阱 | 不加 `-Encoding utf8` 按 GBK 解码；`Set-Content -Encoding UTF8` 写 BOM |
| PowerShell 的反引号转义 | 字符串里写 Markdown 代码块会报语法错误（开发中触发多次） |
| 缺少数据结构 | 解析结果只能用 PSCustomObject 拼，不如 dataclass 清晰 |
| 无法写正经测试 | PowerShell 没有 `pytest` 那样的测试框架 |
| Node 需要额外运行时 | 而 Python 的 `utf-8-sig` 编码名天然解决 BOM 问题 |

Python 版把上述问题都变成了**可测试的代码**：446 条用例 + 63 条断言核验
（`v3 verify`，其中 `--fast` 跑不需要全库扫描的 44 条），
外加一层**外部验证** —— `v3 crosscheck` 拿游戏自己的日志核对我们的解析。

> `v3 verify` 同时跑**文档正文的数字漂移扫描**（`verify.unknown_doc_drift`）：
> 断言表测对了不等于文档写对了 —— 正文里可能仍躺着旧值，而断言表照样全绿。
> 有漂移时退出码同样是 1，所以在 CI / pre-commit 上也会被拦住。
> 确认是「口径不同、文档没错」的登记在 `pdx.verify.KNOWN_METRIC_MIXUPS`（附理由）。
