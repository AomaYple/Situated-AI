# 贡献与维护规范

本指南定义如何修改、验证、提交和交付 Situated AI。代理接手路由见 [AGENTS.md](AGENTS.md)，持续约束见
[工程原则](docs/principles/工程原则.md)和[Mod 开发原则](docs/principles/Mod开发原则.md)，当前出口见
[1.1.0 当前交付与后续计划](docs/design/exec/mod重设计-实施计划.md)。仓库没有 `CONTRIBUTE.md`，不要创建别名文件。

当前职责边界是明确的：助手维护 Mod 源、生成器、原版字段合法性、静态分析和可交付包；用户负责启动游戏、长期
观察、平衡、体验和工坊发布。日志、存档和最小复现由用户提供后，助手只据可复核证据辅助修复。长期 GUI、压力和行为
自动化不属于默认工程出口。

普通问题使用仓库 Issues，并附上版本、最小复现和已脱敏的日志；安全问题请按 [SECURITY.md](SECURITY.md) 私密报告。
依赖和 Action 由 Dependabot 每周检查，更新 PR 同样经过审查与 CI，不自动合并。Action 引用固定为完整提交 SHA；
升级时保留可读版本注释。CodeQL 在 PR、`main` 推送和每周计划中扫描 Python 与工作流，结果见仓库 Security 页；
这些安全检查不替代原版字段门禁、离线合同或用户实机验收。
Dependabot 的 Python 更新以 `pyproject.toml` 为入口；`requirements.lock` 是本机依赖闭包，调整依赖后须在 Windows
Python 3.14 环境核对并按需运行 `v3 lock --write` 更新，不能假定机器人会重建该文件。

## 开始工作

从目标工作树运行：

```text
.venv\Scripts\python.exe -X utf8 -c "import sys; print(sys.version)"
git status --short --branch
git diff --check
```

macOS/Linux 将解释器替换为 `.venv/bin/python`。优先使用仓库 `.venv`；依赖和检查配置只在
`pyproject.toml` 维护。不要依赖激活脚本、默认编码或本机绝对路径。

首次使用需要 Python 3.11+，在仓库根目录创建环境：

```text
python -m venv .venv
.venv\Scripts\python.exe -X utf8 -m pip install -e ".[dev]"
.venv\Scripts\python.exe -X utf8 -m pip check
```

macOS/Linux 同样创建 `.venv`，后两条使用 `.venv/bin/python`。开发工具需在完整仓库中运行，以便读取
`mod/decisions/`、测试、入库快照和文档；仅安装 Python 包不等于安装游戏 Mod。可用 `V3_ROOT` 指定游戏安装
根目录、`V3_USERDIR` 指定用户数据目录；未安装游戏时仍可运行离线合同。`requirements.lock` 是 Windows
Python 3.14 的已安装依赖闭包；其他平台按 `pyproject.toml` 解析，由三平台 CI 核验。

## Mod 生成与发布

生产源在 `mod/decisions/*.toml`，生成链由 `src/pdx/decisions.py`、`decision_rules.py`、
`decision_adapters.py` 和 `distribution.py` 承担。修改源后运行：

```text
.venv\Scripts\python.exe -X utf8 -m pdx.cli modgen --write
.venv\Scripts\python.exe -X utf8 -m pdx.cli modgen --check
.venv\Scripts\python.exe -X utf8 -m pdx.cli modguard --offline
.venv\Scripts\python.exe -X utf8 -m pdx.cli decision-audit
.venv\Scripts\python.exe -X utf8 -m pdx.cli decision-audit --offline
.venv\Scripts\python.exe -X utf8 -m pdx.cli package --output dist/situated-ai-1.1.0.zip
```

生成的 `mod/common`、本地化和 metadata 不手改。标准包必须包含 `.metadata/metadata.json`、
`DISTRIBUTION-MANIFEST.json`、README、`common/` 和锁定游戏的全部生产语言；不得包含探针、Python、日志、
缓存、本体资源或历史实验文件。`pdx.distribution.validate_package` 负责路径、重复项、哈希、编码和探针边界。

`modgen --write/--check` 和 `package` 必须读取锁定原版；未安装游戏或底本漂移时硬失败，不从冻结产物静默重建。
生成时同时更新仓库专用 `mod/generation-lock.json`，记录源码、TOML、底本和生成物的逐字节哈希；该文件不进入
发布 ZIP。无游戏 CI 使用 `modguard --offline` 和 `decision-audit --offline` 核对冻结一致性、脚本语法、
规则合同与入库快照接口，不能替代本机原版重生成。
真实依赖原版的测试标记为 `integration`，由有游戏的完整回归执行；离线合同继续覆盖打包原语、拒绝分支和冻结漂移。
`decision-audit` 默认复用一次生产构建的 engineering metadata；`--offline` 从入库规则源和锁定底本构造同一份静态合同。
两种模式都核对信息域、读取器、规则、原版消费者、解释字段和未知值回退，只输出 `static_check` 证据，不启动游戏，
也不宣称 AI 行为通过。
离线合同必须调用生产规则模块公开的合同生成器；新增字段时先修改唯一来源，再由生产和离线两条输入路径共同覆盖，
禁止在报告层手工复制规则字段。

## 验证矩阵

按风险选择最小充分检查；正式收口至少执行：

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py encoding
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py hygiene
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py lint .
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py format --check .
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py types
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py test-offline
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py deadcode
```

需要完整 Python 回归时运行 `test` 或 `full-acceptance --quiet`；默认可使用 `-n auto --dist loadscope`，
但必须记录实际 worker、选择集、跳过项、覆盖率、墙钟和 RSS。基准清除普通 pytest 参数并串行运行。
没有同口径基线时只报告绝对成本，不声称提速。

工程检查、静态快照、脚本加载和单次评分不能证明 AI 行为、平衡、长期性能或玩家体验。当前任务由用户自行
进行长期实机和创意工坊验收；本仓库只保证 Mod 工程上合法、可生成、可部署、可审计。

## 文件、文档和清理

所有受控文本为 UTF-8 无 BOM、LF；游戏文本只在 ZIP/安装边界加 BOM。机械表、manifest、指纹和统计必须由
Python 生成器更新。删除或改名之前用 Python/`git grep` 盘点调用方、动态注册、测试、CLI、文档、生成入口和
历史证据；缓存和运行态可以清理，历史证据与第三方原始字节按契约保留。规则、计划、结果和历史文档不要互相复制。

长期实机/压力/行为探针不属于当前工程交付链；历史结论只在 Git 历史中保留。当前工程事实写入少量
`docs/design/exec/*-结果.md` 收据，可再生分析输出写入被忽略的 `tools/out/`。
可复用的静态分析、生成、快照和离线检查按当前生产调用方保留。

## 分支、提交和合并

`main` 是唯一长期主线。普通任务使用 `codex/<topic>`，发布修复使用 `hotfix/<topic>`；不常设 `develop`。
一次提交围绕一个完整目的，源码、测试、规则、文档和生成物契约一起提交；标题和正文使用中文，命令、路径和标识符保留原文。

提交前后：

1. 检查 `git status --short --branch`、`git diff --check`、暂存差异和验证结果；
2. 不提交凭据、`.venv`、缓存、日志、`tools/out` 或临时文件；
3. 推送主题分支并创建中文 PR，说明目的、关键设计、实际检查、跳过项和用户验收边界；
4. CI 通过后合并到 `main`，核对本地/远端主线、树等价和工作树干净，再删除短期分支；
5. 禁止强制推送 `main`，不移动已发布标签。正式包可在合并提交上打对应版本标签；`v1.0.0` 和 `v1.0.1` 保持原冻结内容，`1.0.2` 保留历史交付收据。当前候选版本为 `1.1.0`，发布标签须在实际创建后记录。

最终报告分别写明实际修改、删除/保留、检查结果、失败/跳过、包路径和 SHA-256、Git/PR 状态，以及用户仍需完成的长期实机事项。
