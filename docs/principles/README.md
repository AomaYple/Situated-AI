# 原则索引

本页登记规则文件的分工、条款编号及其修订方式，以及各条款对应的检查和评审依据。

## 规则文件职责

| 文件 | 负责 | 不负责 |
|---|---|---|
| [AGENTS.md](../../AGENTS.md) | 任务接手顺序与修改路由 | 流程步骤与原则正文 |
| [CONTRIBUTING.md](../../CONTRIBUTING.md) | 环境、生成、验证、Git 与交付的流程、步骤和命令 | 持续约束正文，以编号指向原则页 |
| [SECURITY.md](../../SECURITY.md) | 安全问题的私密报告方式与处理范围 | 工程或产品约束 |
| [工程原则](工程原则.md)（`EP-nn`） | 工程持续约束 | 步骤、命令、阶段状态 |
| [Mod 开发原则](Mod开发原则.md)（`MP-nn`） | 核心目标及其九条衍生原则，另有构建适配 MP-41、官方内容兼容 MP-66 与接口用法 MP-45 三条独立原则 | 实现清单、阶段状态、验收结果 |
| [工程交付基线](../design/exec/工程基线-1.0.md) | 生成、包结构、验收、证据与恢复合同 | 产品设计和阶段计划 |
| [架构主计划](../design/架构主计划.md)与[架构子计划](../design/架构子计划.md) | 架构、阶段依赖与出口，以及领域和跨域任务 | 持续约束正文、当前事实与已验收结果 |

计划页维护顺序与出口，[当前工作清单](../design/当前工作清单.md)记录当前事实和接手动作。结果页记录实际证据。

## 编号与引用

- 工程原则用 `EP-nn`，Mod 开发原则用 `MP-nn`。两套编号各自从 01 起连续分配，验收门、任务和合同使用各自的编号。
- 新增条款取同前缀已分配的最大编号加一。条款移动或改写时沿用原编号。已分配的编号不得复用。
- 工程条款废止时在原位保留编号和原因。退出 Mod 原则正文的旧编号及其去向集中记录在本页末尾。
- 引用写裸编号（如 `EP-34`）或带页面链接的编号（如 `[EP-34](工程原则.md)`）；不链接标题锚点，不引用行号。

## 修订

修改、新增或废止条款时，在同一次改动中同步：

1. 本页对应的条款执行方式表。
2. 其他文档中对该编号的引用（`git grep -n "EP-\|MP-"`）。
3. 同步受影响的测试。`tests/test_principle_ids.py` 核对已分配编号连续、现行引用有效、执行方式覆盖及旧编号的唯一去向。`tests/test_engineering_contract.py` 核对工程原则与交付基线的验收职责。收据、归档、原版资料与可再生输出按各自合同保留。

## 条款执行方式

“强执行”表示违反条款会被自动检查拒绝。“部分执行”表示自动检查覆盖列出的范围，其余要求依评审或专项验收核对。“仅评审”表示按评审或专项验收取证，目前没有核实到自动检查入口。运行命令见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

自动覆盖按检查实际拒绝的行为或产生的证据登记。锁定条文内容的检查只覆盖文字漂移。依 EP-37 在入口说明中标明参考求值、生成脚本和实际运行各自的范围。引擎调用、选择、执行、实际结果及兼容的证据口径见[工程交付基线](../design/exec/工程基线-1.0.md)。

### 工程原则

| 条款 | 执行方式 | 入口与说明 |
|---|---|---|
| EP-01 | 仅评审 | 按真实原版重生成、包回读和完整回归评审性能或内存改动 |
| EP-02 | 部分执行 | `tests/test_cache_release.py`、`tests/test_standard_generation_boundary.py` 核对缓存及写入失败，`pdx.performance` 检查结果指纹 |
| EP-03 | 部分执行 | `tests/test_parser_completeness.py`、`tests/test_production_profile.py`、`tests/test_native_authority_capture.py` 核对解析、生产合同与捕获拒绝 |
| EP-04 | 部分执行 | `distribution.verify_compatibility_installation()`，`tests/test_current_release_contract.py`、`tests/test_profile_live_boundary.py` |
| EP-05 | 部分执行 | `tests/test_docs_consistency.py` 核对相对路径目标，其余调用、动态注册、证据和机械入口靠评审 |
| EP-06 | 部分执行 | `version_contracts.require_current()`、`tests/test_current_release_contract.py` 将生产入口约束到一套开发基线。受支持发布的身份由交付记录核对 |
| EP-07 | 部分执行 | `tests/test_current_release_contract.py`、`tests/test_version_contracts.py` 核对单一开发基线及拒绝旧版和未登记合同 |
| EP-08 | 仅评审 | 核对最新公开稳定构建的发布来源和实际构建身份。本机安装核对只覆盖本机身份 |
| EP-09 | 部分执行 | `tests/test_current_release_contract.py`、`tests/test_live_current_installation.py` 核对安装身份、原版漂移与坏包保留。替换及重验证范围由迁移评审确认 |
| EP-10 | 部分执行 | 生产入口拒绝旧 profile。通过开发基线切换的差异评审核对源码、配置、测试及现行文档的清退 |
| EP-11 | 部分执行 | `tests/test_release_integration.py`、`tests/test_architecture_inventory.py` 经当前生产路线检查共用能力 |
| EP-12 | 仅评审 | 逐项追溯清退测试的去向，核对仍适用的生产回归和门禁 |
| EP-13 | 部分执行 | `tests/test_current_release_contract.py` 验证旧 profile 无法调用当前生产命令。过渡排查的支持与产物按 MP-41 核对 |
| EP-14 | 部分执行 | `tests/test_architecture_receipts.py` 独立读取归档，`tests/test_decisions.py` 核对标准包排除旧资料 |
| EP-15 | 仅评审 | 清退前核对冻结路径、可恢复字节和活动引用 |
| EP-16 | 部分执行 | `pyproject.toml`、`run_check.py`、`tests/test_engineering_enforcement.py` 的解释器和配置范围 |
| EP-17 | 仅评审 | 贡献流程优先仓库 `.venv`，项目依赖选型及环境回退由评审核对 |
| EP-18 | 仅评审 | 评审复用 `pathlib`、现行解析器、事务、生成和验证接口 |
| EP-19 | 部分执行 | `tests/test_portability.py` 核对机器专属绝对路径。`tests/test_engineering_enforcement.py` 只核对部分测试读写和 subprocess 默认编码 |
| EP-20 | 部分执行 | 三平台 CI 离线矩阵、跨平台测量实现和平台环境标记 |
| EP-21 | 部分执行 | `run_check.py types` 与 mypy 配置范围，公开入口错误的专项反例 |
| EP-22 | 部分执行 | `v3 lock`、`pip check`、`tests/test_lockfile.py` 约束当前安装闭包及条件依赖 |
| EP-23 | 部分执行 | `tests/test_engineering_enforcement.py` 检查 Ruff、mypy 精确版本与锁一致 |
| EP-24 | 强执行 | `tests/test_engineering_enforcement.py` 拒绝工作流外部 Action 缺完整提交 SHA |
| EP-25 | 部分执行 | `v3 modgen --check`、`modguard --offline`、`tests/test_standard_generation_boundary.py` |
| EP-26 | 部分执行 | `v3 tables --offline`、`tests/test_doc_overview.py`、`distribution.generation_lock()` 和包清单回读 |
| EP-27 | 强执行 | `run_check.py encoding`、pre-commit、`tests/test_repo_hygiene.py` |
| EP-28 | 强执行 | `distribution.py` 及 `tests/test_repository_upgrade.py` 的标准包编码断言 |
| EP-29 | 部分执行 | `tests/test_architecture_receipts.py`、`tests/test_current_release_contract.py` 分别核对冻结归档与底本字节 |
| EP-30 | 部分执行 | `distribution.py` 包允许集合与 `tests/test_decisions.py` 排除历史资料 |
| EP-31 | 部分执行 | `.gitignore`、`run_check.py hygiene` 核对受控路径及物理残留，凭据和登记证据由评审检查 |
| EP-32 | 仅评审 | 按影响选择单元、属性、离线、集成和真实包验证，完整套件保留既有覆盖 |
| EP-33 | 部分执行 | 生成与离线一致性检查复用 `distribution.generation_lock()`，在线抽取和快照复用 `vanilla_index` 和 `ai_surface` |
| EP-34 | 部分执行 | `tools/ci/test_suite.py`、`pdx.covgate`、`tools/ci/test_summary.py` 和 `tests/test_engineering_enforcement.py` |
| EP-35 | 仅评审 | 标准 Git 保护流程见贡献指南，托管实际状态见对应交付收据 |
| EP-36 | 部分执行 | 工程交付基线定义证据类别，`tests/test_architecture_inventory.py` 核对当前 R2 预算为 `static_check` |
| EP-37 | 部分执行 | `tests/test_full_information.py` 验证静态矩阵保持范围，工作清单记录 R/U `unknown` |
| EP-38 | 部分执行 | `research_catalog.write_installation()` 与 `tests/test_research_catalog_cli.py` 核对安装独立分母 |
| EP-39 | 部分执行 | `tests/test_decisions.py` 校验生产包排除研究资料，原件使用权限与公开材料由评审核对 |
| EP-40 | 部分执行 | `tests/test_research_catalog_cli.py`、`tests/test_situated_native_report.py` 核对独立分母、逐项处置和拒绝条件 |
| EP-41 | 部分执行 | `situated/native_catalog.py` 保持静态语义、作用域及引擎权限未知，`tests/test_information_catalog.py` 验证静态索引边界 |
| EP-42 | 部分执行 | `tests/test_full_information.py`、`tests/test_native_boundary_closure.py` 核对主体、作用域及无依据权限 |
| EP-43 | 部分执行 | 研究目录记录部分结果和诊断，`tests/test_information_catalog.py` 有读取及解析故障反例 |
| EP-44 | 部分执行 | `pdx.performance.regressions()`、`tests/test_repository_upgrade.py` 检查同环境、输入身份和负载输出 |
| EP-45 | 部分执行 | `tools/ci/mem_baseline.py`、`tools/ci/test_suite.py` 记录资源口径，`tests/test_test_suite.py` 拒绝不完整证据 |
| EP-46 | 仅评审 | 授权、版本、渠道与目标身份见工程交付基线 |
| EP-47 | 仅评审 | 标签、Release、安装和 Workshop 分别核对，见版本交付收据 |
| EP-48 | 仅评审 | 工程交付基线规定阻塞事实和渠道证据 |
| EP-49 | 部分执行 | `tests/test_standard_generation_boundary.py`、`tests/test_repository_upgrade.py` 覆盖本地事务与恢复边界 |
| EP-50 | 部分执行 | `tests/test_current_release_contract.py`、`tests/test_standard_generation_boundary.py` 核对既有产物保留 |
| EP-51 | 仅评审 | 工程交付基线按渠道阶段记录部分失败和恢复 |
| EP-52 | 仅评审 | 版本交付索引登记固定标签，冻结引用可复核，主线保护见贡献指南 |
| EP-53 | 部分执行 | `tests/test_engineering_contract.py` 检查活动文档指向当前规范、状态及交付 |
| EP-54 | 部分执行 | `tests/test_docs_consistency.py` 检查导航目标存在，其余权威职责靠评审 |
| EP-55 | 部分执行 | `v3 verify --from-snapshot`、`tests/test_docs_consistency.py` 校验登记断言 |
| EP-56 | 仅评审 | 治理和产品验收分别记录，`tests/test_engineering_contract.py` 锁定条文并核对部分文档边界 |
| EP-57 | 仅评审 | 真实失败、解析缺口、当前运行未知与范围局限按收据登记 |
| EP-58 | 仅评审 | 以目标主线完整差异核对每个提交目的及候选内容 |
| EP-59 | 部分执行 | 精确 `requires-python`、解释器门和三平台 CI，`tests/test_run_check.py` 验证范围 |
| EP-60 | 部分执行 | `pyproject.toml`、CI 与类型工具采用单一 Python 基线 |
| EP-61 | 部分执行 | `pyproject.toml` 中 Ruff `UP` 规则和当前版本目标参与 CI |
| EP-62 | 部分执行 | `research_catalog`、`information_catalog` 和 `tests/test_research_catalog_cli.py` 覆盖目录、结构、脚本、诊断与格式边界 |
| EP-63 | 仅评审 | 现有依赖和标准库的复用由变更评审，专有 PDX 解析以实际语义和既有接口衡量 |

### Mod 开发原则

| 条款 | 执行方式 | 自动检查范围 | 评审或实机证据 |
|---|---|---|---|
| MP-03 | 仅评审 | — | 新建国和控制权变更后的适用主体、国别利益与战略取舍、国别差异及全局结果的来源 |
| MP-10 | 部分执行 | `tests/test_action_objectives.py` 核对参考求值的观察对象、时点和未知状态 | 实际观察权限、推断依据与不确定性、对本国无法获知的原版输入的处理 |
| MP-25 | 部分执行 | `tests/test_action_objectives.py` 核对候选绑定和对跨候选观察的拒绝 | 当轮候选范围、同组尺度与单候选的比较基准 |
| MP-02 | 部分执行 | `tests/test_network_profile.py` 核对指定生成脚本中的学校收益与必要成本、外交影响力负担 | 跨域得失、机会成本、执政延续、亡国风险及试探、等待和行动的具体取舍 |
| MP-35 | 部分执行 | `tests/test_action_objectives.py` 拒绝重复登记同一成本，`tests/test_network_profile.py` 核对学校议程的额外收益 | 具体影响的重叠、原版已计影响的修正和组合的额外后果 |
| MP-47 | 部分执行 | `tests/test_network_profile.py`、`tests/test_supply_1151.py` 以脚本求值核对指定调整的 AI 和玩家分支 | 国家政策和委托选择的接入、玩家操作、独立主体、委托后的原版自动管理、新增选项、扩展优先级与实际覆盖、判断合理性和可比多局成效 |
| MP-46 | 部分执行 | `tests/test_network_profile.py` 核对指定生成脚本的原版后续运算，`tests/test_supply_1151.py` 核对原版枚举分支 | 官方接口对比较的影响、保留随机的依据及引擎实际裁决、行动和结算 |
| MP-31 | 部分执行 | `tests/test_action_objectives.py` 核对参考求值在观察变化、未知、过期与恢复时的结果 | 实际变化、求值时机、重评机会及转向取舍 |
| MP-49 | 部分执行 | `tests/test_action_objectives.py` 核对必要观察缺失时有关组退出及独立组保留，`tests/test_supply_1151.py` 核对未知时的原版枚举路径，`tests/test_network_profile.py` 核对禁用后原文字节恢复 | 实际求值中缺失或失效的观察、接口与规则的生效边界、撤回贡献后的行为 |
| MP-41 | 部分执行 | `tests/test_current_release_contract.py` 核对生产入口的单一开发身份及对底本漂移的拒绝 | 最新正式构建、基线切换与清退、各渠道旧包和配套游戏构建的可获取性及支持变更、新局与存档条件 |
| MP-66 | 仅评审 | — | DLC 组合、联机共享和开局检查、DLC 更新与存档支持。按模式核对加载、新局、开局后功能与支持声明。按同条件对照核对原版已知问题，并评审有意 AI 改动涉及的玩家操作 |
| MP-45 | 部分执行 | `tests/test_production_profile.py` 核对当前生产允许的输入、字段与写入上下文，`tests/test_network_profile.py` 核对指定调整的静态差异 | 接口用法证据、官方说明冲突与可重复实测、逐构建复验和组合效果复验，以及正式游玩是否依赖调试命令 |

## 旧 Mod 条款去向

保留在原则正文中的编号继续指向现行条款。以下旧号用于追溯，现行文档引用对应的现行原则或合同。

- **MP-13、MP-22、MP-30、MP-48** 的国家范围、处境差异及制度取舍见 MP-03、MP-02、MP-47。
- **MP-11、MP-12、MP-15、MP-16、MP-33** 的观察对象、尺度、历史与未知见 MP-10、MP-31、MP-49。
- **MP-05、MP-18、MP-24、MP-27、MP-28、MP-29、MP-34、MP-37、MP-38** 的事实、比较基准、收益与成本见 MP-10、MP-25、MP-02、MP-35、MP-46。
- **MP-07、MP-08、MP-32、MP-39、MP-40** 的因果顺序、重评及回退见 MP-10、MP-31、MP-46、MP-49。
- **MP-04、MP-17、MP-19、MP-52** 的原版选项、接口与策略见 MP-25、MP-47、MP-46、MP-45。适用范围与实测声明见工程交付基线。
- **MP-06、MP-36、MP-50、MP-51** 的叠加、限幅和隔离见 MP-35、MP-47、MP-46、MP-49。
- **MP-23、MP-26** 的资格、随机与局部回退见 MP-25、MP-46、MP-49。
- **MP-42、MP-43** 的版本适用性与行为延续见 MP-41，底本维护见 EP-06 至 EP-15。
- **MP-44** 的新局与兼容范围见 MP-41、MP-66，兼容证据与恢复见工程交付基线。
- **MP-09、MP-14、MP-21** 的原版研究见 EP-38、EP-40、EP-41、EP-43，国家覆盖声明见工程交付基线，机制盘点见[架构主计划](../design/架构主计划.md)。
- **MP-01、MP-20、MP-59、MP-60、MP-61、MP-62、MP-63、MP-64** 的效果声明与验收职责见[工程交付基线](../design/exec/工程基线-1.0.md)。
- **MP-55、MP-56、MP-57、MP-58** 的本地化和交付命名见工程交付基线。
- **MP-65** 的反馈材料见[贡献指南](../../CONTRIBUTING.md)。验收职责和标准包排除探针的要求见工程交付基线。
- **MP-53** 的原版决策入口见 MP-25、MP-45，游戏内性能要求已废止。
- **MP-54** 的优化语义和工程性能测量见 EP-01、EP-02、EP-44、EP-45，游戏内性能要求已废止。
