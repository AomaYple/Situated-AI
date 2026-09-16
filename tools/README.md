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
| `verify.py` | 断言注册表，把文档里的数字变成可执行检查 |
| `console.py` | stdout/stderr 的 UTF-8 兜底（**必须在构造 rich Console 之前调用**） |
| `cli.py` | 唯一的命令行入口，`v3` 的全部子命令 |

## 命令行 `v3`

7 个各自为政的旧入口脚本（`run_analyze.py` / `run_defines.py` / `run_index.py` /
`run_snapshot.py` / `run_verify.py` / `check_outputs.py` / `show_outputs.py`）
已删除，功能全部并入：

| 子命令 | 取代 | 作用 |
|---|---|---|
| `v3 analyze` | `run_analyze.py` | 全量分析并落盘：`--no-mods` `--no-cross` `--no-write` `--quiet` `--profile` |
| `v3 defines` | `run_defines.py` | defines 提取：`--ns NAME` `--json PATH` `--overlay FILE` |
| `v3 index` | `run_index.py` | 重生成 `docs/victoria3-modding/13-common全量键名索引.md`：`--dry-run` |
| `v3 snapshot create/list/diff/verify` | `run_snapshot.py` | 版本快照：`--label` / `--detail` / `--json PATH` |
| `v3 verify` | `run_verify.py` | 核对文档里的数量断言：`--fast` `--json PATH` `--only ID` |
| `v3 check-outputs` | `check_outputs.py` | 核验**已落盘产物**是否与断言注册表一致 |
| `v3 show` | `show_outputs.py` | 转储产物的结构与规模 |

```powershell
$py = ".venv\Scripts\python.exe"
$v3 = ".venv\Scripts\v3.exe"      # 或：& $py -m pdx.cli

& $v3 analyze                     # 全量分析，落盘报告
& $v3 analyze --no-mods --quiet   # 只分析游戏本体，不打印进度
& $v3 analyze --profile           # 附 pyinstrument 调用树
& $v3 verify --fast               # 只跑不需要全库扫描的断言
& $v3 check-outputs               # 核验产物（需先 analyze）
& $v3 defines --ns NAI            # 展开某个 defines 命名空间
& $v3 index --dry-run             # 只统计，不写文档
& $v3 snapshot diff A B --detail  # 比对两份快照
& $v3 show                        # 产物里到底有什么
& $v3 <子命令> --help             # 每个子命令都有中文帮助
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

```powershell
& $py -m pytest                    # 配置在 pyproject.toml 的 [tool.pytest.ini_options]
& $py -m pytest -m "not slow"      # 跳过慢用例
& $py -m pytest --cov=pdx          # 覆盖率（门槛 86%，见 pyproject）
```

285 个用例（`pytest --collect-only` 实测），全部对应**实际踩过的坑**，
不是凭空构造：

| 测试文件 | 覆盖的坑 |
|---|---|
| `test_lexer.py` | 注释内花括号、字符串中的 `#`、`?=` 不被拆开、行号追踪 |
| `test_parser.py` | BOM 污染首键、含连字符的键、`c:SWE` 不被误认为前缀、缩进的顶层键、`=` 与 `{` 分行 |
| `test_scan.py` | 递归计数、后缀过滤、真实游戏树的结构断言 |
| `test_extract.py` | 字段只收第一层、前缀归类、跨文件合并、已知条目数 |
| `test_analyze.py` / `test_golden.py` | 产物结构与指纹回归（产物被改坏要立刻失败） |
| `test_snapshot.py` / `test_verify.py` | 快照确定性与断言注册表口径 |
| `test_properties.py` / `test_metamorphic.py` / `test_lexer_differential.py` | hypothesis 属性测试、变形测试、与独立 oracle 实现的差分对比 |
| `test_benchmarks.py` | 性能基准（`pytest-benchmark`，回归即失败） |

CLI 自身目前没有 pytest 覆盖（`tools/tests/TEST_SUITE_REVIEW.md` 第 4 项计划补
`test_cli.py`，届时用 `subprocess` 跑 `python -m pdx.cli`）。

## 输出产物

**分开存放** —— 游戏本体与 mod 互不混杂：

```
tools/out/game/游戏本体.json      游戏本体全量数据（约 7.9 MB）
tools/out/mods/mod.json          mod 全量数据（约 650 KB）
tools/out/cross/交叉.json         两者的覆盖关系
tools/out/snapshots/*.json       版本快照
tools/reports/游戏本体分析.md      人可读报告
tools/reports/mod分析.md          人可读报告
```

`tools/out/` 已 gitignore（随时可由 `v3 analyze` 重建）；
`tools/reports/` **入库** —— 两份报告是研究成果的一部分，改动它们应当出现在 diff 里。

## 解析器的五条铁律

这些是踩坑换来的，改代码时不要违反：

```
1. 用花括号深度判断顶层        —— 官方文件混用 tab / 空格 / 无缩进
2. 剥离 BOM                    —— common 下 3,026 个 .txt 有 3,000 个带 BOM
3. 注释剥离要引号感知          —— 字符串里可能含 #
4. 键名字符集用「非空白非等号」  —— 存在含连字符的键（全库 32 个）
5. 识别 6 个功能前缀           —— INJECT: / REPLACE: 等，且**只 mod 用**
```

另有两条口径纪律，都曾导致过真实错误：

* **`@变量` 不是数据条目** —— `00_defines.txt` 顶部 22 个，误计会让命名空间块数从 75 变成 97
* **空目录也要收录** —— `scripted_modifiers` 只有 `.md` 没有 `.txt`，靠「有没有 `.txt`」数目录会得到 135 而非 136

## 性能剖析 `prof/`

`pdx` 包本身不埋点，剖析用独立脚本跑：

```powershell
& $py tools/prof/prof_e2e.py full          # 整条流水线（冷缓存）+ 调用树
& $py tools/prof/prof_e2e.py stages        # 逐阶段冷缓存剖析
& $py tools/prof/prof_e2e.py walkaudit     # 文件系统被重复遍历的程度
& $py tools/prof/prof_e2e.py prefixaudit   # 功能前缀扫描的范围与耗时
```

阶段序列与 `v3 analyze` 保持一致，因此剖析结果可以直接用来解释 `analyze` 的耗时。

## 沙箱环境注意事项

在 DSH 沙箱里开发本工具链时遇到并已规避的问题：

| 问题 | 规避方式 |
|---|---|
| 控制台是 GBK 代码页，`print` emoji 会抛 `UnicodeEncodeError`（**重定向到管道时同样会抛**） | 入口处统一调 `pdx.console.enable_utf8_stdio()`；rich 替代不了它，实测 `Console().print("✅")` 一样抛 |
| `tempfile` 创建的目录权限受限，沙箱拒绝写入 | 测试改用工作区内的自管临时目录 |
| pip 在沙箱里曾不可用 | 现已可用，依赖写进 `pyproject.toml`，不再需要 `requirements.txt` |

## 为什么全 Python 化

| 原因 | 具体表现 |
|---|---|
| PowerShell 5.1 的编码陷阱 | 不加 `-Encoding utf8` 按 GBK 解码；`Set-Content -Encoding UTF8` 写 BOM |
| PowerShell 的反引号转义 | 字符串里写 Markdown 代码块会报语法错误（开发中触发多次） |
| 缺少数据结构 | 解析结果只能用 PSCustomObject 拼，不如 dataclass 清晰 |
| 无法写正经测试 | PowerShell 没有 `pytest` 那样的测试框架 |
| Node 需要额外运行时 | 而 Python 的 `utf-8-sig` 编码名天然解决 BOM 问题 |

Python 版把上述问题都变成了**可测试的代码**：285 个用例 + 39 条断言核验
（`v3 verify`，其中 `--fast` 跑不需要全库扫描的 35 条）。
