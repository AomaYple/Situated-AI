# 贡献与维护规范

本指南统一维护流程、验证命令和交付步骤。当前架构与计划状态入口为
[架构主计划](docs/design/架构主计划.md)与[架构子计划](docs/design/架构子计划.md)。任务路由见 [AGENTS.md](AGENTS.md)，持续工程与产品约束见
[工程原则](docs/principles/工程原则.md)和[Mod 开发原则](docs/principles/Mod开发原则.md)，生成与证据合同见
[工程交付基线](docs/design/exec/工程基线-1.0.md)。本指南只写流程、步骤和命令；持续约束以 `EP-nn`、`MP-nn` 编号指向原则页，
规则文件的分工见[原则索引](docs/principles/README.md)。

## 工作前与问题反馈

修改前检查 `git status --short --branch` 和 `git diff --check`，保留已有改动；按变更风险运行充分的检查。
证据类别与标识符见 [EP-36](docs/principles/工程原则.md)，各类的证明范围见工程交付基线。

普通问题通过仓库 Issues 提交，并尽量提供游戏版本、Mod 版本与包 SHA-256、启用的 Mod 集、存档或新局条件、
复现步骤和脱敏日志。安全问题使用 [SECURITY.md](SECURITY.md) 中的私密报告方式，不在公开 Issue 附利用细节或敏感数据。

依赖、锁文件、检查工具版本与 GitHub Actions 固定方式的约束见 [EP-16](docs/principles/工程原则.md)、[EP-22 至 EP-24](docs/principles/工程原则.md)；
`requirements.lock` 的适用范围见“环境准备”。更新闭包时在 Windows 的新虚拟环境按 `.[dev]` 安装，
运行 `pip check`、`v3 lock --write` 和 `v3 lock`，再复核锁文件差异。已有环境可用
`pip install --upgrade --upgrade-strategy eager -e ".[dev]"` 更新符合声明约束的传递依赖。

## 环境准备

用与 `pyproject.toml` 的 `requires-python` 完全一致的 CPython 正式版创建虚拟环境。优先使用仓库虚拟环境中的解释器，不依赖激活脚本、默认编码或本机绝对路径。

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
通过 `V3_USERDIR` 指定用户数据目录；未安装游戏时仍可运行离线检查。`requirements.lock` 固定 Windows
CPython 3.15.2 的运行期和 `dev` 依赖闭包。复现该环境时，先用虚拟环境的解释器执行
`-X utf8 -m pip install -r requirements.lock`，再安装项目。`pyproject.toml` 的构建依赖由构建隔离环境安装，
其他平台的运行期和 `dev` 依赖也从该文件解析，由三平台 CI 核验。

按需运行变异测试时，使用支持 `fork` 的 Linux、macOS 或 WSL 环境，在项目的虚拟环境安装
`dev` 和 `mutation`。Windows 上使用 WSL 内的 CPython 和虚拟环境。

```text
.venv/bin/python -X utf8 -m pip install -e ".[dev,mutation]"
.venv/bin/python -X utf8 -m mutmut run
.venv/bin/python -X utf8 -m mutmut results
```

## 安装根只读盘点

将 `V3_ROOT` 设为包含 `game/` 的安装根，运行 `python -m pdx.cli input-inventory`。
命令逐项记录所有文件类别、相对路径、大小、原字节 SHA-256 和读取状态，标准输出为 JSON。
盘点包含脚本目录以外的文件，并报告读取失败、受阻目录及无法登记的路径。报告对无法登记的路径保留可逆的字符转义。

盘点前沿用在线读取的当前安装身份门。身份不符或选择历史合同，命令向标准错误输出诊断并返回 2。
盘点在开始和结束时核对同一个安装根，并从盘点记录回查身份文件的大小和摘要。只有身份复核、文件盘点和默认策略源指纹均通过才返回 0，否则保留报告并返回 1。
完整游戏输入验收、原件保全和语法解析各走独立流程。

## 完整安装研究

将 `V3_ROOT` 指向锁定游戏安装，运行以下命令从本机只读盘点和分析全部安装路径。输出包括相对路径、原字节摘要、结构位置和分层覆盖。二次盘点核对安装身份、文件字节和目录分母，出现漂移时不发布结果。

```text
python -m pdx.cli analyze --installation --output-dir <本机研究目录>
```

已有当前版本的已提交原件时，使用下面的命令生成本机研究目录。输出目录必须尚不存在，且须与安装和原件目录分离。

```text
python -m pdx.cli analyze --raw-root <原件目录> --epoch <epoch摘要> --output-dir <本机研究目录>
```

`COMPLETE.json` 绑定安装分母及两个输出的摘要。`information-catalog.json` 保留每个文件的处置、按格式汇总的解码和解析状态，以及五层证据覆盖。`occurrences.sqlite` 可按来源、键、路径和出现位置查询 PDX 脚本、地图邻接表、本地化及其他已读取资料。普通 `analyze` 继续生成现场概览和 Mod 交叉报告。研究目录供本机使用，其中含原版资料。

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

在线读取和生产命令仅接受 Victoria 3 `1.15.1`。可用 `--profile 1.15.1` 明确断言当前生产版本。
已有 1.15.0 历史候选仅通过 `modgen --check`、`modguard --offline` 或 `decision-audit --offline` 配合 `--profile 1.15.0` 核对。
这些命令读取隔离目录 `tools/out/production/1.15.0/`，其中 `decision-audit` 可另写审计 JSON。
同一组命令可用 `--configuration <TOML路径>` 选择构建配置（严格 schema、核心、领域和 policy/neutral 模式），
检查与打包必须传入同一配置；具体字段见 `src/pdx/situated/profile_configuration.py`。
候选静态通过及 ZIP 生成不代表完整工程门通过，也不构成发布或部署。

`snapshot`、`tables`、`verify`、`index` 等没有 `--profile` 参数的分析与文档命令，通过
`V3_CONTRACT_PROFILE=1.15.1` 选择同版本合同、文档、官方文档 manifest 和快照。例如在 PowerShell 中：

```powershell
$env:V3_CONTRACT_PROFILE = '1.15.1'
.venv/Scripts/python.exe -B -X utf8 -m pdx.cli verify --from-snapshot
.venv/Scripts/python.exe -B -X utf8 -m pdx.cli tables --offline
```

环境变量用于明确指定离线证据合同。在线读取先核对启动器游戏标识与版本，以及冻结的分支、修订和构建校验文件。
历史 `1.14.5` 和 `1.15.0` 的已落盘快照仍可离线核对。

原版权威候选通过专用入口显式捕获，例如：

```text
python -m pdx.native_authority_capture --profile 1.15.1 --installation <安装根目录> --kind parameters --output tools/out/version1151/authority-candidates/inventory-parameters.json
```

`--profile`、`--installation`、`--kind`、`--output` 均必填，不从环境推断本次授权。
`--kind` 还可选 `retentions-native-subset`、`compatibility`、`technology-catalog`；前三类输出 `.json`，科技目录输出 `.toml`。
入口核对实际安装身份，只向无链接的 `tools/out/` 写入候选；已有文件相同则幂等，不同则拒绝，不能自动改写历史或当前受控证据。
retention 候选仅复核原版保留字段，不含学校等独立政策迁移收据，不是完整迁移合同；所有候选均只提供原版静态证据，运行行为仍为 `unknown`。

## 验证

按风险选择检查。阶段开发运行改动域测试；冻结最终候选后运行一次完整回归。静态收口至少运行：

```text
python tools/ci/run_check.py encoding
python tools/ci/run_check.py hygiene
python tools/ci/run_check.py lint .
python tools/ci/run_check.py format --check .
python tools/ci/run_check.py types
python tools/ci/run_check.py baseline
```

`baseline` 已包含依赖一致性、离线断言、离线表格、`modguard --offline`、`decision-audit --offline`、`ai-surface --check`
和死代码审计，无需另行重复运行。

当前迁移候选必须运行版本门；这些入口向原有离线检查传递同一版本合同，并追加生成与生产合同检查：

```text
python tools/ci/run_check.py baseline --profile 1.15.1
python tools/ci/run_check.py full-acceptance --profile 1.15.1 --quiet
```

它们保留完整的既有检查集合；不带 `--profile` 的命令默认同一当前版本。历史验收必须绑定其原输入与合同。

涉及 Python 包布局、构建配置或正式交付时，额外在临时源码副本构建 wheel，核对全部源码模块的集合与原始字节、ZIP 完整性和重复条目；构建不应在工作树留下 `build/` 或 egg-info：

```text
python tools/ci/python_package.py
```

常规反馈或无游戏环境运行 `python tools/ci/run_check.py test-offline`；冻结最终候选运行
`python tools/ci/run_check.py full-acceptance --quiet`。完整验收已经包含离线用例，不要在同一轮再重复运行 `test-offline`。
pytest 默认由仓库配置选择 `-n auto --dist loadscope`；报告需记录实际 worker、测试选择、跳过项、覆盖率、墙钟和进程 RSS。
性能基准清除普通 pytest 参数并串行运行；输入、测试集合、环境和资源口径不一致时，只报告各自成本，不声称整体提速。

统一检查入口禁止当前及嵌套 Python 写入字节码；测试和静态工具仍可能生成其他缓存。结束后清理可再生目录，再运行 `hygiene` 作为最后的卫生检查；
不要与测试并行运行 hygiene，否则会把测试正在创建的缓存误报成残留。
可用 `python -m tools.ci.repo_hygiene --clean` 预览清理白名单；实际清理追加 `--apply`。
该入口只清理缓存、字节码、根目录构建物和 `src/` 直系 egg-info，链接、reparse point、环境及证据目录不在清理范围。

历史工具 `tools/ci/situated_closeout.py` 只核验归档 A2 身份，不是当前完成门；其历史实现与证据保留在原有源码、测试及归档收据中，不代替当前工程或产品验收。

产品阶段同时要求功能完整接入生产、参考语义与生成PDX一致、静态工程验证和标准包合同通过。完整回归是Python工程回归，不启动游戏；文件存在、字段合法或旧测试通过不能代替逐项功能验收。Mod 行为目标和用户实机
验收边界见 Mod 开发原则。长期游戏运行、数值平衡、游戏内性能和玩家体验由用户自行验收，不作为当前阶段出口。
旧计划和历史收据只作参考，不是新架构完成门；已完成的 X1 每小计划以生产差异、独立参考/PDX见证和定向测试验收并提交，
集中复核、完整回归和实际交付证据见[广度深度拓展结果](docs/design/exec/广度深度拓展-结果.md)。不得用旧 A2 收据关闭新目标。
助手可基于用户提供的版本、包哈希、启用 Mod 集、存档和日志，使用仓库工具辅助定位；结果按工程交付基线标明证据类别，
不扩展其证明范围。

纯工程治理按实际改动验证工具、配置、目录、文档与行为保持，验收边界见 [EP-34 至 EP-37](docs/principles/工程原则.md)、[EP-56 至 EP-58](docs/principles/工程原则.md)。
独立工程改动从主线提取与适配，提交前核对目标主线的全部差异并保留未完成产品候选的原分支及证据。
CI 失败时定位并修正授权范围内的问题，重新验证后继续标准流程（[EP-35](docs/principles/工程原则.md)）。

## 文档与清理

受控文本和原始字节边界见 [EP-27 至 EP-29](docs/principles/工程原则.md)，文档唯一来源见 [EP-26](docs/principles/工程原则.md)、[EP-53 至 EP-55](docs/principles/工程原则.md)。

删除、移动或改名前，用 `git grep` 或 Python 核对 [EP-05](docs/principles/工程原则.md) 所列的调用、注册、测试、CLI、生成入口、链接和证据用途，并同步受影响内容。
缓存、运行态和可再生输出按需清理；当前结果写入少量 `docs/design/exec/*-结果.md` 收据，可再生本机输出放在忽略的 `tools/out/`。
历史证据依原合同保留，清退前解除当前引用、确认可追溯恢复途径，再验证剩余入口。

## 分支、提交与合并

`main` 是唯一长期主线。普通任务使用短期 `<执行者>/<topic>` 分支，执行者前缀取决于实际操作者（如 `codex`、`claude` 或开发者本人的名字），不作统一规定；已发布版本的修复使用 `hotfix/<topic>`；不设置
常驻 `develop`。提交围绕一个完整目的，相关源码、测试、规则、文档和生成合同一起交付。提交标题、正文和 PR 使用
中文，命令、路径和代码标识符保留原文。

提交和合并步骤：

1. 检查工作树、暂存差异、`git diff --check`、编码和所需验证结果；排除凭据、`.venv`、缓存、日志和临时产物，以及 `tools/out/` 中未登记的内容（受控快照与登记证据除外）。
2. 推送主题分支并创建中文 PR，说明问题、方案、实际检查、跳过或失败项及验收边界。
3. CI 通过并完成审查后合并至 `main`，核对本地和远端主线及工作树状态，再清理短期分支。
4. 禁止强制推送 `main`，不移动已发布标签。版本标签指向交付合并提交；标准包从该提交的源和生成器构建并校验。
   公开标签和 GitHub Release 只保留 `vMAJOR.MINOR.PATCH` 正式版本，Release 附标准 ZIP 和 SHA-256 校验文件。
   候选包及撤回 rc/归档引用的恢复备份留在忽略的本机证据目录，不创建对应公开标签或 Release。
   受控历史证据按既有字节合同保留，历史包不得通过改写当前版本重建。

最终说明实际修改、检查结果、失败或跳过项、交付包路径与哈希、Git/PR 状态，以及仍由用户验收的事项；明确区分
静态检查、快照、模拟、实测和推断。
