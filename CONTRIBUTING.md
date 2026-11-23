# 贡献与维护规范

本指南统一维护流程、验证命令和交付步骤。当前架构与计划状态入口为
[架构主计划](docs/design/架构主计划.md)与[架构子计划](docs/design/架构子计划.md)。任务路由见 [AGENTS.md](AGENTS.md)，持续工程与产品约束见
[工程原则](docs/principles/工程原则.md)和[Mod 开发原则](docs/principles/Mod开发原则.md)，生成与证据合同见
[工程交付基线](docs/design/exec/工程基线-1.0.md)。本指南只写流程、步骤和命令；持续约束以 `EP-nn`、`MP-nn` 编号指向原则页，
规则文件的分工见[原则索引](docs/principles/README.md)。

## 工作前与问题反馈

修改前检查 `git status --short --branch` 和 `git diff --check`，保留已有改动；按变更风险运行充分的检查。
证据类别与标识符见 [EP-36](docs/principles/工程原则.md)，各类的证明范围见工程交付基线。

普通问题通过仓库 Issues 提交，并尽量提供游戏版本与构建、Mod 版本与包 SHA-256、包的获取渠道、单人或多人联机、实际启用的玩法 DLC 和 Mod 集、存档或新局条件、复现步骤和脱敏日志。涉及联机 DLC 时注明主机的共享情况。安全问题使用 [SECURITY.md](SECURITY.md) 中的私密报告方式，不在公开 Issue 附利用细节或敏感数据。

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
`dev` 和 `mutation`。Windows 上使用 WSL 内的 CPython 和虚拟环境。变异测试在
`mutants/` 中运行 lexer 单元与差分用例、文档归属标记用例。

```text
.venv/bin/python -X utf8 -m pip install -e ".[dev,mutation]"
.venv/bin/python -X utf8 -m mutmut run
.venv/bin/python -X utf8 -m mutmut results
```

## 安装根只读盘点

将 `V3_ROOT` 设为包含 `game/` 的安装根，运行 `python -m pdx.cli input-inventory`。
命令逐项记录所有文件类别、相对路径、大小、原字节 SHA-256 和读取状态，标准输出为 JSON。
盘点包含脚本目录以外的文件，并报告读取失败、受阻目录及无法登记的路径。报告对无法登记的路径保留可逆的字符转义。

盘点前核对 Victoria 3 1.15.2 的安装身份。身份不符时，命令向标准错误输出诊断并返回 2。
盘点在开始和结束时核对同一个安装根，并从盘点记录回查身份文件的大小和摘要。只有身份复核、文件盘点和默认策略源指纹均通过才返回 0，否则保留报告并返回 1。
完整游戏输入验收、原件保全和语法解析各走独立流程。

## 完整安装研究

将 `V3_ROOT` 指向锁定游戏安装，运行以下命令从本机只读盘点和分析全部安装路径。输出包括相对路径、原字节摘要、结构位置和分层覆盖。命令核对当前默认策略摘要。输入身份中的起止时点界定初次盘点，报告另外记录末次完整盘点通过的时点。现场安装有文件未能读取，或安装身份、文件字节或目录分母发生漂移时，命令拒绝生成正式完成的研究目录。

```text
python -m pdx.cli analyze --installation --output-dir <本机研究目录>
```

已有当前版本的已提交原件时，可指定原件目录和 epoch 的 SHA-256。

```text
python -m pdx.cli analyze --raw-root <原件目录> --epoch <epoch摘要> --output-dir <本机研究目录>
```

两个入口均要求目标目录尚不存在、父目录已存在，且目标与安装目录和原件目录分离。生成研究产物时使用系统临时目录。若系统临时目录与输出目标位于不同卷，发布时会另在目标父目录暂存研究产物。请为系统临时目录和输出所在卷预留足够空间。仓库内的研究输出使用 Git 忽略路径，并与原件一起留在本机。

`COMPLETE.json` 绑定安装分母和两个产物的 SHA-256。`information-catalog.json` 记录逐文件处置、各格式的解码与解析范围，以及各层覆盖的分母和缺口。`occurrences.sqlite` 保存来源、结构键、路径和出现位置，并把脚本定义和引用候选关联到同一套来源位置。普通 `analyze` 生成现场概览和 Mod 交叉报告。

### 查询研究目录

将已生成的目录作为 `research-query` 的第一个参数。命令以只读方式验证目录身份、文件摘要和索引合同，将结果写为 JSON。下面的命令查看两个来源的格式元数据及结构位置，并包含逐项覆盖报告。

```text
python -m pdx.cli research-query "tools/out/installation-research" --source game/common/ai_strategies/00_default_strategy.txt --source game/map_data/nodes.dat --source-details --coverage-report --limit 25
```

- `--source` 使用安装根相对路径和正斜杠，可重复指定。`--source-details` 需要至少一个来源。`--key` 按精确结构键查询，结构位置以末条记录的 ID 通过 `--after` 续页。
- `--symbol` 按选定名称独立查询整个索引，可重复指定。引用续页时保留同一符号的查询，将上一页末条引用的 `occurrence_id` 和 `ordinal` 以 `--reference-after <occurrence_id>:<ordinal>` 传入。`--limit` 是每组查询的行数上限。
- 使用 `--source` 和 `--script-references` 可查看指定文件的全部已登记引用候选，包括没有固定名称的 `dynamic` 和状态为 `unknown` 的候选。按来源续页时，保留相同的来源和选项，并用其末条引用的 `occurrence_id:ordinal` 作为 `--reference-after`。
- 已登记的旧实现现场定位索引可加 `--historical-locators` 读取。仍须通过该目录的原始身份与摘要校验，查询范围限于旧产物所保存的定位资料。需要当前格式证据或脚本符号候选时，用当前工具生成新目录。
- 覆盖层 `structure` 按通用逐文件解析结果计数。地图、Shader 和二进制格式的专用结构证据由 `--coverage-report` 在 `format_structure_evidence` 分列，各来源的具体处置可通过 `--source-details` 查看。
- 格式处置和引用候选属于静态证据。按报告中的逐项处置解释完整解析、局部结构、未解析或未知等状态。实际脚本求值、合法运行期读取及 Mod 生产接线需要各自的证据。

例如，可在同一份 1.15.2 研究目录中查看默认 AI 策略文件的引用候选，并用实际符号 `has_friendly_diplomatic_pact` 查看全索引中的定义和引用。

```text
python -m pdx.cli research-query "tools/out/installation-research" --source game/common/ai_strategies/00_default_strategy.txt --script-references --symbol has_friendly_diplomatic_pact --limit 25
```

逐来源状态表示该文件的脚本索引处置。`complete` 表示完整解析，`partial` 表示保留可解析片段，`failed` 表示解析失败，`not_attempted` 表示该来源未做脚本索引，`unknown_source` 表示该来源未登记在查询目录的冻结输入分母中，当前机器上的文件状态需另行核对。引用为空时，结合来源状态判断覆盖范围。

`incomplete_definition_sources` 列出未完整处理的定义来源。同一类别中只要有定义来源缺失或未完整解析，已索引到的定义仍可定位，引用在无法判断目标唯一或缺失时保留 `unknown`。例如，已见一个定义候选时，未完整处理的同类来源仍可能包含另一个定义。

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

在线读取和生产命令仅接受 Victoria 3 `1.15.2`。可用 `--profile 1.15.2` 明确断言当前生产版本。
同一组命令可用 `--configuration <TOML路径>` 选择构建配置（严格 schema、核心、领域和 policy/neutral 模式），
检查与打包必须传入同一配置；具体字段见 `src/pdx/situated/profile_configuration.py`。
候选静态通过及 ZIP 生成不代表完整工程门通过，也不构成发布或部署。

`snapshot`、`tables`、`verify`、`index` 使用 1.15.2 的版本合同、文档、官方文档 manifest 和快照。
例如在 PowerShell 中运行以下离线验证命令。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pdx.cli verify --from-snapshot
.venv/Scripts/python.exe -B -X utf8 -m pdx.cli tables --offline
```

在线读取先核对启动器游戏标识与版本，以及冻结的分支、修订和构建校验文件。
有日期的 Workshop 订阅统计通过文档归属标记核对。`v3 check-outputs` 核对当前本机分析产物中 Mod 概览与逐项明细的数量。

原版权威候选通过专用入口显式捕获，例如：

```text
python -m pdx.native_authority_capture --profile 1.15.2 --installation <安装根目录> --kind parameters --output tools/out/version1152/authority-candidates/inventory-parameters.json
```

`--profile`、`--installation`、`--kind`、`--output` 均必填，不从环境推断本次授权。
`--kind` 还可选 `retentions-native-subset`、`compatibility`、`technology-catalog`；前三类输出 `.json`，科技目录输出 `.toml`。
入口核对实际安装身份，只向无链接的 `tools/out/` 写入候选；已有文件相同则幂等，不同则拒绝，不能自动改写历史或当前受控证据。
retention 候选仅复核原版保留字段，不含学校等独立政策迁移收据，不是完整迁移合同；所有候选均只提供原版静态证据，运行行为仍为 `unknown`。

## 一键发布

在完成工程验收并合并后，从干净的 `main` 工作区运行 `v3 publish`。使用当前生产基线 **Victoria 3 1.15.2**
和 **CPython 3.15.2**，将 `V3_ROOT` 指向锁定的游戏安装。版本默认为当前生产声明，正式标签默认为
`v<version>`。执行时显式传入与 HEAD 相同的 40 位提交 SHA、持久收据目录和至少一个渠道。

先运行不带 `--apply` 的命令。计划以只读方式核对各渠道，输出源、候选包和渠道状态的 JSON。
计划模式下的源提交默认为 HEAD。显式选择渠道且源工作区符合条件时，计划会读取同一发布身份的已有收据和冻结包，
或在系统临时目录构建和校验包。省略 `--channel` 可查看三个渠道的前置条件。重复指定 `--channel` 可选任意组合。
仅选择本地或 Workshop 渠道时，使用显式 `--github-repo` 或 GitHub `origin` 公开回查源提交是否已进入远端 `main`。

公开发布前，取用已冻结的标准 ZIP。若计划仅在临时目录打包，则从同一干净提交、锁定游戏底本和默认发布配置运行
`v3 package --output <持久验证目录中的 ZIP 路径>`，将 ZIP 留在发布收据目录之外。
将待测 ZIP 的原始字节 SHA-256 与发布计划 JSON 的 `package.sha256` 核对一致后再取证。按 MP-41 和 MP-66，在固定游戏构建、完整官方玩法 DLC 组合及所声明的每种模式下完成实测，记录加载、新开局、开局后原版及 DLC 功能和适用的保存与读档证据。单人通过而多人联机尚未通过时，可以仅声明支持单人。公开发布说明及各渠道支持切换按模式登记实际验证和可获取状态。计划与候选包用于准备和验证，公开支持以固定包实际可获取及相应模式的实测为准。证据口径见[工程交付基线](docs/design/exec/工程基线-1.0.md#证据口径)。

| 渠道 | 参数与权限 | 执行和独立回读 |
|---|---|---|
| `github` | `--github-repo OWNER/REPO`。在 `github.com` 使用已认证的 GitHub CLI（`gh`）。凭据须能读取目标公开仓库、创建正式标签、上传附件并发布 Release，远端 `main` 须包含源提交。 | 核对标签提交，上传标准 ZIP 和 `.zip.sha256` 到草稿，下载附件核对原始字节，再公开 Release 并复核状态和附件。 |
| `local` | `--local-root` 指定已存在且可写的用户 `mod` 根目录的绝对路径，目标是其下的 `Situated AI`。传入 `--local-previous-sha256` 确认该目标当前目录树摘要，目标不存在时传 `absent`。 | 将已确认的旧树备份到收据目录下的 `local-previous`，校验后切换安装目录并回读全树。记录可读取的 launcher 启用状态，launcher、playset 与订阅选择由用户管理。 |
| `workshop` | `--workshop-item` 和 `--workshop-owner` 指定既有创意工坊条目及其 SteamID64 所有者。用该账号登录 Steam，以 `--workshop-helper` 指定 Windows Steamworks 辅助程序的绝对路径。 | 从同一标准包更新内容与封面，发布各语言的描述。回读和运行环境见[创意工坊发布材料](docs/publishing/README.md)。 |

第一次核对本地目标时，可在计划中只给 `--channel local --local-root <绝对路径>`。此时计划会要求确认并以非零状态退出。
核对 `preflight.channels.local.target` 后，将该渠道的 `observed_tree_sha256` 作为 `--local-previous-sha256`。
该摘要覆盖目录路径和文件字节。首次执行使用新的或空的专用收据目录，父目录须已存在。收据目录与用户 `mod` 根目录互不包含。

本地切换使用操作系统的非覆盖式目录重命名。目标文件系统须支持此操作，切换过程中出现新的目标目录时发布会停止。
目录回读后，命令先写入 `activated` 阶段，再清理切换暂存目录。此后检测到安装目录变更时，重试会报告冲突。

以下 PowerShell 示例为新装时选择全部三个渠道。将示例值换成实际的发布身份及路径。更新已有本地安装时替换 `absent`。

```powershell
$publishArgs = @(
    '--version', '<正式版本>', '--tag', '<v正式版本>', '--commit', '<40 位源提交 SHA>',
    '--publication-dir', 'tools/out/publication-<正式版本>',
    '--channel', 'github', '--github-repo', 'AomaYple/Situated-AI',
    '--channel', 'local', '--local-root', '<用户 mod 根目录绝对路径>',
    '--local-previous-sha256', 'absent',
    '--channel', 'workshop', '--workshop-item', '<条目 ID>', '--workshop-owner', '<所有者 SteamID64>',
    '--workshop-helper', '<Steamworks 辅助程序绝对路径>'
)
.venv/Scripts/python.exe -B -X utf8 -m pdx.cli publish @publishArgs
# 核对包身份、所声明模式的实测和各渠道状态后执行
.venv/Scripts/python.exe -B -X utf8 -m pdx.cli publish @publishArgs --apply
```

`--apply` 在持久目录冻结并校验同一份标准 ZIP 和 SHA-256 校验文件。所有所选渠道均通过预检后，依次执行所选的
GitHub、Workshop 和本地渠道。
`publication.json` 绑定发布身份和包摘要，记录各渠道的阶段和回读结果。`verified` 表示所有所选渠道均已回读通过。
收到 `blocked` 或 `partial` 时，查看错误及各渠道阶段，确认已经执行的操作。

失败或响应丢失时，保留收据、冻结包、备份和暂存目录，先根据已记录阶段核对远端和本地实际状态。修复环境或权限后，
使用同一组参数和收据目录重试。命令复核目标现状，复用可验证的已完成步骤。遇到异字节附件、标签指向不同提交
或已验证本地安装发生变化时停止。各渠道独立恢复，已完成的 GitHub 或 Workshop 更新仍在线上。
GitHub 上传中断后若诊断显示附件状态为 `starter`，可按返回的 Release ID 和附件 ID 核实并在 GitHub 移除该未完成附件，
再用同一收据续跑。
在各自渠道确认完成后，将实际发布链接、包 SHA-256 和回读证据登记到
[版本交付索引](docs/design/exec/版本交付-结果.md)。历史正式版本仍通过对应不可移动标签、原版 ZIP 与 SHA-256 附件及原始收据追溯。

## 验证

按风险选择检查。阶段开发运行改动域测试；冻结最终候选后运行一次完整回归。静态收口至少运行：

```text
python tools/ci/run_check.py encoding
python tools/ci/run_check.py hygiene
python tools/ci/run_check.py lint .
python tools/ci/run_check.py format --check .
python tools/ci/run_check.py types
python tools/ci/run_check.py baseline-offline
```

`baseline-offline` 与三平台 CI 使用同一入口，依次核对依赖、离线断言、离线生成表格、Mod 门禁、情境决策合同、AI 可执行面和死代码报告。`baseline` 复用这七项，指定 `--profile` 时追加实装检查。

带 `--profile` 的静态基线追加生产生成检查，需要本机锁定安装。完整验收始终核对当前安装身份。

```text
python tools/ci/run_check.py baseline --profile 1.15.2
python tools/ci/run_check.py full-acceptance --profile 1.15.2 --quiet
```

两个入口均使用 1.15.2 的工程合同。`--profile` 可显式断言这一版本。

涉及 Python 包布局、构建配置或正式交付时，额外在临时源码副本构建 wheel，核对全部源码模块的集合与原始字节、ZIP 完整性和重复条目，并拒绝项目打包元数据允许清单之外的条目。构建结束后检查工作树中的 `build/` 和 egg-info 残留。

```text
python tools/ci/python_package.py
```

常规反馈或无游戏环境运行 `python tools/ci/run_check.py test-offline`，它与线上 CI 使用同一当前版本和测试筛选。冻结最终候选运行
`python tools/ci/run_check.py full-acceptance --quiet`。完整验收已经包含离线用例，不要在同一轮再重复运行 `test-offline`。
pytest 默认由仓库配置选择 `-n auto --dist loadscope`；报告需记录实际 worker、测试选择、跳过项、覆盖率、墙钟和进程 RSS。
性能基准清除普通 pytest 参数并串行运行；输入、测试集合、环境和资源口径不一致时，只报告各自成本，不声称整体提速。

统一检查入口禁止当前及嵌套 Python 写入字节码；测试和静态工具仍可能生成其他缓存。结束后清理可再生目录，再运行 `hygiene` 作为最后的卫生检查；
不要与测试并行运行 hygiene，否则会把测试正在创建的缓存误报成残留。
可用 `python -m tools.ci.repo_hygiene --clean` 预览清理白名单；实际清理追加 `--apply`。
该入口仅清理白名单中的缓存、字节码、根目录构建物和 `src/` 直系 egg-info，并保护 Git 已跟踪文件及其父目录。链接、reparse point、环境和证据目录受到保护。卫生检查也会报告被忽略规则命中且已强制入库的路径。`.gitignore` 为 1.15.2 精简快照登记了精确路径。

产品阶段同时要求功能完整接入生产、参考语义与生成 PDX 一致、静态工程验证和标准包合同通过。完整回归覆盖 Python 工程。逐项功能验收及用户实机验收的职责见[工程交付基线](docs/design/exec/工程基线-1.0.md)，Mod 行为目标见[Mod 开发原则](docs/principles/Mod开发原则.md)。共用架构首版的阶段出口见[架构主计划](docs/design/架构主计划.md)，后续领域和方面的阶段出口见[架构子计划](docs/design/架构子计划.md)。
历史收据按原版本、配置、包身份和证据范围追溯。X1 的生产差异、独立参考与 PDX 见证、
回归和实际交付记录见[广度深度拓展结果](docs/design/exec/广度深度拓展-结果.md)。
助手可基于用户提供的运行条件、存档和日志，使用仓库工具辅助定位。结果按工程交付基线标明证据类别及其覆盖范围。

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
