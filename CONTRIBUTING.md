# 贡献与维护规范

本指南统一维护流程、验证命令和交付步骤。产品计划入口为
[分层联动实施计划](docs/design/exec/mod重设计-实施计划.md)。任务路由见 [AGENTS.md](AGENTS.md)，持续工程与产品约束见
[工程原则](docs/principles/工程原则.md)和[Mod 开发原则](docs/principles/Mod开发原则.md)，生成与证据合同见
[工程交付基线](docs/design/exec/工程基线-1.0.md)。

## 工作前与问题反馈

修改前检查 `git status --short --branch` 和 `git diff --check`，保留已有改动；按变更风险运行充分的检查。
具体证据类别及其证明范围见工程交付基线。

普通问题通过仓库 Issues 提交，并尽量提供游戏版本、Mod 版本与包 SHA-256、启用的 Mod 集、存档或新局条件、
复现步骤和脱敏日志。安全问题使用 [SECURITY.md](SECURITY.md) 中的私密报告方式，不在公开 Issue 附利用细节或敏感数据。

依赖配置集中在 `pyproject.toml`；`requirements.lock` 是 Windows Python 3.14 的安装闭包。调整依赖后运行
`pip check` 和 `v3 lock --write`，再复核锁文件差异。更新 GitHub Actions 时沿用工作流中的完整提交 SHA 固定方式，
所有依赖和自动化更新均通过审查与 CI。

## 环境准备

需要 Python 3.11 或更新版本。优先使用仓库虚拟环境中的解释器，不依赖激活脚本、默认编码或本机绝对路径。

```text
python -m venv .venv
```

Windows：

```text
.venv\Scripts\python.exe -X utf8 -m pip install -e ".[dev]"
.venv\Scripts\python.exe -X utf8 -m pip check
```

macOS/Linux：

```text
.venv/bin/python -X utf8 -m pip install -e ".[dev]"
.venv/bin/python -X utf8 -m pip check
```

开发命令应从完整仓库运行，以便读取 `mod/decisions/`、测试、快照和文档。可通过 `V3_ROOT` 指定游戏安装根目录，
通过 `V3_USERDIR` 指定用户数据目录；未安装游戏时仍可运行离线检查。`requirements.lock` 仅适用于 Windows
Python 3.14；其他平台依据 `pyproject.toml` 解析依赖，并由三平台 CI 核验。

## Mod 生成与打包

生产源位于 `mod/decisions/*.toml`。修改源后，先生成并核对仓库产物，再执行静态合同和打包检查：

```text
python -m pdx.cli modgen --write
python -m pdx.cli modgen --check
python -m pdx.cli modguard --offline
python -m pdx.cli decision-audit
python -m pdx.cli decision-audit --offline
python -m pdx.cli package
```

命令使用当前虚拟环境的 Python；Windows 显式调用 `.venv\Scripts\python.exe -X utf8`，macOS/Linux 调用
`.venv/bin/python -X utf8`。`mod/common/`、生成的本地化和 metadata 不手改。版本、包文件清单、编码、manifest、
哈希和路径合同以工程交付基线及生产校验器为准。

生产生成和打包须读取锁定 Victoria 3 原版；缺少游戏目录或底本漂移时应硬失败，不得从冻结产物静默重建。
`mod/generation-lock.json` 用于离线比对源、底本和生成产物，不放入发布包。离线检查核对冻结合同和静态接口，
不能代替读取本机原版重生成；`decision-audit` 的两种输入模式均只提供 `static_check` 证据，不启动游戏。
离线合同复用生产规则模块提供的合同生成器；新增字段先修改唯一来源，再由生产和离线路径共同覆盖。

标准包只包含 Mod 安装所需内容，不含探针、Python、日志、缓存、本体资源或历史实验。ZIP 路径使用 POSIX 形式；
游戏文本的 BOM 只在游戏安装或打包边界添加。完整包内合同和恢复边界见工程交付基线。

## 验证

按风险选择检查。阶段开发运行改动域测试；冻结最终候选后运行一次完整回归。静态收口至少运行：

```text
python tools/ci/run_check.py encoding
python tools/ci/run_check.py hygiene
python tools/ci/run_check.py lint .
python tools/ci/run_check.py format --check .
python tools/ci/run_check.py types
python tools/ci/run_check.py baseline
python tools/ci/run_check.py deadcode
```

常规反馈或无游戏环境运行 `python tools/ci/run_check.py test-offline`；冻结最终候选运行
`python tools/ci/run_check.py full-acceptance --quiet`。完整验收已经包含离线用例，不要在同一轮再重复运行 `test-offline`。
pytest 默认由仓库配置选择 `-n auto --dist loadscope`；报告需记录实际 worker、测试选择、跳过项、覆盖率、墙钟和进程 RSS。
性能基准清除普通 pytest 参数并串行运行；输入、测试集合、环境和资源口径不一致时，只报告各自成本，不声称整体提速。

完整测试会创建 pytest、benchmark 和字节码缓存。测试结束后清理这些可再生目录，再运行 `hygiene` 作为最后的卫生检查；
不要与测试并行运行 hygiene，否则会把测试正在创建的缓存误报成残留。

当前产品计划要求静态工程验证和标准包合同通过；完整回归是 Python 工程回归，不启动游戏。Mod 行为目标和用户实机
验收边界见 Mod 开发原则。长期游戏运行、数值平衡、游戏内性能和玩家体验由用户自行验收，不作为当前阶段出口。
助手可基于用户提供的版本、包哈希、启用 Mod 集、存档和日志，使用仓库工具辅助定位；结果按工程交付基线标明证据类别，
不扩展其证明范围。

## 文档与清理

受控文本使用 UTF-8 无 BOM、LF；原版、第三方及冻结证据按其原始字节契约保留。文档、统计表、指纹和 manifest
由各自唯一来源维护；需要生成的内容通过 Python 工具更新，不手改生成物。

删除或改名之前，用 Python 或 `git grep` 核对调用方、动态注册、测试、CLI、生成入口、链接和证据引用，并同步
维护内容、链接、忽略规则及测试。缓存、运行态和可再生输出可按需清理；历史证据依契约保留。当前结果写入少量
`docs/design/exec/*-结果.md` 收据，可再生的本机输出放在忽略的 `tools/out/`。

## 分支、提交与合并

`main` 是唯一长期主线。普通任务使用短期 `codex/<topic>` 分支，已发布版本的修复使用 `hotfix/<topic>`；不设置
常驻 `develop`。提交围绕一个完整目的，相关源码、测试、规则、文档和生成合同一起交付。提交标题、正文和 PR 使用
中文，命令、路径和代码标识符保留原文。

提交和合并步骤：

1. 检查工作树、暂存差异、`git diff --check`、编码和所需验证结果；排除凭据、`.venv`、缓存、日志、`tools/out/` 和临时产物。
2. 推送主题分支并创建中文 PR，说明问题、方案、实际检查、跳过或失败项及验收边界。
3. CI 通过并完成审查后合并至 `main`，核对本地和远端主线及工作树状态，再清理短期分支。
4. 禁止强制推送 `main`，不移动已发布标签。版本标签指向交付合并提交；标准包从该提交的源和生成器构建并校验。
   GitHub Release 附标准 ZIP 和 SHA-256 校验文件，候选版如实标为 Pre-release；历史包不得通过改写当前版本重建。

最终说明实际修改、检查结果、失败或跳过项、交付包路径与哈希、Git/PR 状态，以及仍由用户验收的事项；明确区分
静态检查、快照、模拟、实测和推断。
