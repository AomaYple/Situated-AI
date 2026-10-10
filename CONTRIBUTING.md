# 贡献与维护规范

这份文档是仓库级的开发入口。工程状态、已验证指标和证据边界以 [`docs/design/exec/工程基线-1.0.md`](docs/design/exec/工程基线-1.0.md) 为准；这里约定日常改动怎样保持可复现。

Mod 行为原则以 [`docs/design/03-处境决策设计.md`](docs/design/03-处境决策设计.md) 为准，实施顺序和验收由 [`最终执行纲领`](docs/design/exec/mod重设计-实施计划.md) 管理；性能优化遵守 [`速度优化计划`](docs/design/exec/速度优化计划-正确性优先.md) 的测量、预算与回退规则。旧方向和交接文档保留历史证据，不覆盖当前设计与纲领。

## 环境与命令

统一使用仓库根目录的 `.venv`，不要调用系统 Python 或临时创建第二个虚拟环境。

```text
# Windows（cmd.exe）
.venv\Scripts\python.exe -X utf8 -m pytest -q
.venv\Scripts\python.exe -X utf8 -m ruff check .

# macOS / Linux
.venv/bin/python -X utf8 -m pytest -q
.venv/bin/python -X utf8 -m ruff check .
```

仓库脚本通过 `pathlib`、`sys.executable` 和 `platform` 选择路径与解释器。新代码不要写死盘符、用户目录、反斜杠或只在某个 shell 中存在的命令；命令示例同时给出三平台可执行的写法。Windows 端优先使用 `cmd.exe` 或仓库 Python，避免把 PowerShell 的编码和转义行为带进自动化流程。

## 编码和换行

受控文本文件必须是 UTF-8、无 BOM、LF 换行。Python 源码末尾保留一个换行；其他文件遵循 `.editorconfig` 与生成器字节契约，不自动改写生成物末尾。仓库门禁会检查 Git 跟踪文件、未跟踪文件和可见的忽略文件；不要用编辑器的默认本地代码页保存文件。

游戏原始文件属于证据，按原始字节保存。Victoria 3 本地化 `.yml` 在交付到游戏目录时可以由安装/打包命令按游戏要求补 BOM；仓库源文件仍保持 UTF-8 无 BOM。不要把安装时的兼容转换写回 `mod/` 源码。

## 目录、命名和生成物

- `src/pdx/` 是可复用的 Python 包；`tests/` 放测试；`mod/decisions/*.toml` 是当前生产数据源，旧 `mod/data/*.toml` 是历史实验数据源。
- 根级游戏产物由 `pdx.decisions` 从生产源生成；旧数据源只生成至 `mod/legacy/`，不进入生产包。使用 `v3 modgen` 统一检查／生成，不要手改生成物。
- `tools/ci/` 放门禁与检查驱动，`tools/benchmarks/` 放基准，`tools/probe/` 放实机探针与冻结夹具，`tools/out/` 保存可复核证据。
- `tools/out/`、`tools/probe/frozen/`、精简快照和实机证据都有审计引用。清理前先查 `git ls-files`、报告引用和 `.gitignore`，不要用 `git clean -fdX` 代替盘点。
- 新的 Python 模块使用小写下划线命名；文档文件名沿用现有中文章节编号，不为形式重命名已有路径。只有临时文件、无引用文件或能提供兼容指针时才改名。
- 新增目录或产物必须同时更新 `docs/README.md`、相关索引和 `.gitignore`，说明它是源码、生成物、缓存、第三方镜像还是证据。

## 测试与性能

提交前至少运行以下门禁；需要游戏安装的检查在没有游戏的机器上按项目规则跳过，不要把离线快照结果写成实机结论。

```text
.venv\Scripts\python.exe -X utf8 tools\ci\run_check.py encoding
.venv\Scripts\python.exe -X utf8 tools\ci\run_check.py test
.venv\Scripts\python.exe -X utf8 -m ruff check .
.venv\Scripts\python.exe -X utf8 -m ruff format --check .
.venv\Scripts\python.exe -X utf8 -m mypy
.venv\Scripts\python.exe -X utf8 tools\ci\run_check.py baseline
.venv\Scripts\python.exe -X utf8 -m pdx.cli modgen --check
git diff --check
```

默认完整回归保留 `n-auto`，并行度由 CPU 和可用内存预算自适应控制；不要在单个测试里自行启动固定数量的全局 worker。基准显式串行运行并清除普通测试 `addopts`，与游戏、完整回归及内存剖析错峰。性能改动要同时测墙钟时间和峰值内存，事先固定输入、环境、重复规则、噪声与资源预算；收益满足判据才启用，失败和回退证据保留。正确性回归优先于速度提升。成熟库已有稳定实现时优先复用，并为边界行为补测试。

## 快照、实机和文档证据

`v3 analyze`、`v3 snapshot`、`v3 snapshot diff` 产生的是文件和快照层证据；它们不能证明引擎运行期的加载顺序、覆盖优先级、字段合法性或平衡性。游戏自动化测试和 GUI 探针产生的日志、截图、进程报告必须保留运行参数和时间窗口，才能进入 `tools/out/` 证据链。

文档中的数字要写清口径和来源。能由仓库现算的数字应接入测试或生成表；历史报告中的旧数字可以保留，但要标注历史时点，不能让它看起来像当前基线。官方文档镜像不入库，使用 `research/official-docs.manifest.json` 和 `v3 mirror` 命令复核。

## 提交前与提交信息

**Git 提交遵循最佳实践，提交标题和说明使用中文。** 文件路径、命令、标识符和必要的技术名称保留原文，不使用 `feat:` / `fix:` / `chore:` 等英文前缀。

- 每次提交围绕一个明确目的，保持改动完整、可审查、可独立回退。无关功能、清理和格式化分别提交；相互依赖的源码、测试、文档和生成物放在同一提交，避免人为拆出不一致状态。
- 标题使用简短、具体的中文，以“修复”“增加”“统一”等动词描述实际结果，不使用“更新”“修改一些东西”等含糊标题。标题不声称未完成或未验证的效果。
- 简单改动可以只有标题；复杂改动在标题后空一行，用中文正文说明原因、关键实现、实际验证及必要的兼容或迁移影响。只记录真正执行的检查，失败或未验证项如实说明。
- 提交前按改动范围完成所需门禁，检查 `git status --short`、工作区 diff 和 `git diff --check`；按文件或相关补丁选择暂存，再检查 `git diff --cached` 和 `git diff --cached --check`，确认本次提交内容。
- 临时盘点脚本、缓存、虚拟环境、本机日志和凭据不进入提交。提交后核对提交内容与工作区状态；已经共享的历史通过新的修复或回退提交维护，不擅自改写。

例如：

```text
统一仓库文档口径并规范工程入口
```
