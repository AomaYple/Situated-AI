# 原则索引

本页说明规则文件的分工、原则条款的编号与修订方式，以及每条原则当前靠什么执行；不复述条款正文。

## 规则文件职责

| 文件 | 负责 | 不负责 |
|---|---|---|
| [AGENTS.md](../../AGENTS.md) | 任务接手顺序与修改路由 | 流程步骤与原则正文 |
| [CONTRIBUTING.md](../../CONTRIBUTING.md) | 环境、生成、验证、Git 与交付的流程、步骤和命令 | 持续约束正文，以编号指向原则页 |
| [SECURITY.md](../../SECURITY.md) | 安全问题的私密报告方式与处理范围 | 工程或产品约束 |
| [工程原则](工程原则.md)（`EP-nn`） | 工程持续约束 | 步骤、命令、阶段状态 |
| [Mod 开发原则](Mod开发原则.md)（`MP-nn`） | 产品目标与持续设计约束 | 实现清单、阶段状态、验收结果 |
| [工程交付基线](../design/exec/工程基线-1.0.md)、[1.15架构设计](../design/1.15架构设计.md) | 对原则的具体合同细化：生成、包结构、证据、恢复，以及架构规范 | 另立持续约束 |

计划页描述顺序和出口，清单页记录当前状态，结果页记录证据；原则或计划中的目标不证明代码已经实现。

## 编号与引用

- 工程原则用 `EP-nn`，Mod 开发原则用 `MP-nn`，各自从 01 起连续编号；这两个前缀不用于验收门、任务号或合同号。
- 编号稳定、不复用：新增条款取该页当前最大编号加一，放入对应主题小节；条款移动小节或改写时编号不变。
- 废止的条款保留编号，在原位写作 `- **EP-nn（已废止）**：原因或替代条款`，不删除行、不重排后续编号。
- 引用写裸编号（如 `EP-34`）或带页面链接的编号（如 `[EP-34](工程原则.md)`）；不链接标题锚点，不引用行号。

## 修订

修改、新增或废止条款时，在同一次改动中同步：

1. 本页“条款执行方式”表。
2. 其他文档中对该编号的引用（`git grep -n "EP-\|MP-"`）。
3. 受影响的测试：`tests/test_principle_ids.py` 核对编号唯一连续、受控文档（收据、归档、原版资料与可再生输出除外）的引用有定义及本页覆盖全部编号；`tests/test_engineering_contract.py` 锁定 EP-56、EP-57、MP-59、MP-60 中的四句原文。

## 条款执行方式

本表描述条款目前已核对到的自动执行覆盖，不扩张条款本身的证明范围。“强执行”指违反会被自动检查拒绝；“部分执行”指只有一部分由自动检查覆盖，其余靠评审；“仅评审”指未核实到自动检查入口，依靠评审和 PR 模板。入口只写文件名或命令名，日常运行口径统一见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

自动检查覆盖不等于行为合规：测试只锁定条文原文时，只能防止规则文字漂移，不能证明实现遵守条文。只有对应入口实际拒绝或产生了表中声明的证据，才能计入该条款的自动覆盖；未覆盖的实现行为仍按 EP-37、MP-63 由评审或专项验收核对。

| 条款 | 执行方式 | 入口与说明 |
|---|---|---|
| EP-01 | 仅评审 | 按真实原版重生成、包回读和完整回归评审性能或内存改动 |
| EP-02 | 部分执行 | `tests/test_cache_release.py`、`tests/test_standard_generation_boundary.py` 核对缓存及写入失败，`pdx.performance` 检查结果指纹 |
| EP-03 | 部分执行 | `tests/test_parser_completeness.py`、`tests/test_production_profile.py`、`tests/test_native_authority_capture.py` 核对解析、生产合同与捕获拒绝 |
| EP-04 | 部分执行 | `distribution.verify_compatibility_installation()`，`tests/test_current_release_contract.py`、`tests/test_profile_live_boundary.py` |
| EP-05 | 部分执行 | `tests/test_docs_consistency.py` 核对相对路径目标，其余调用、动态注册、证据和机械入口靠评审 |
| EP-06 | 部分执行 | `version_contracts.require_current()`、`tests/test_current_release_contract.py` 把生产入口约束到现行身份 |
| EP-07 | 部分执行 | `tests/test_current_release_contract.py`、`tests/test_version_contracts.py` 拒绝旧版和未登记合同 |
| EP-08 | 仅评审 | 当前知识库的环境与版本页保留独立的 Paradox 官方发布公告 |
| EP-09 | 部分执行 | `tests/test_current_release_contract.py`、`tests/test_live_current_installation.py` 核对安装身份、原版漂移与坏包保留 |
| EP-10 | 部分执行 | 生产入口拒绝旧 profile，代码、适配、配置和历史引用清退由差异评审确认 |
| EP-11 | 部分执行 | `tests/test_release_integration.py`、`tests/test_architecture_inventory.py` 经当前生产路线检查共用能力 |
| EP-12 | 仅评审 | 逐项追溯清退测试的去向，核对仍适用的生产回归和门禁 |
| EP-13 | 部分执行 | `tests/test_current_release_contract.py` 验证旧 profile 无法调用当前生产命令 |
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
| MP-50 | 仅评审 | 当前主线尚未核实到覆盖本条完整边界的自动检查入口；专项证据另行登记 |
| MP-55 | 强执行 | `src/pdx/distribution.py`、`tests/test_localization_languages.py` |
| MP-56 | 部分执行 | `src/pdx/distribution.py` 在 `v3 package` 时校验语言头、键集合、占位符和路径；CI 没有打包步骤，未核实到覆盖这些拒绝路径的测试 |
| MP-45 | 部分执行 | 生产生成器的原版接口核对；CI 的 `v3 modguard --offline` 只核对锁定快照 |
| MP-58 | 部分执行 | `src/pdx/config.py` 的命名常量与 `tests/test_mods.py`（Mod ID 与前缀）；展示名靠评审 |
| MP-59、MP-60 | 仅评审 | `tests/test_engineering_contract.py` 只锁定原文，不检查行为 |
| MP-01、MP-02、MP-03、MP-04、MP-05、MP-06、MP-07、MP-08、MP-09、MP-10、MP-11、MP-12 | 仅评审 | 未核实到自动检查入口 |
| MP-13、MP-14、MP-15、MP-16、MP-17、MP-18、MP-19、MP-20、MP-21、MP-22、MP-23、MP-24 | 仅评审 | 未核实到自动检查入口 |
| MP-25、MP-26、MP-27、MP-28、MP-29、MP-30、MP-31、MP-32、MP-33、MP-34、MP-35、MP-36 | 仅评审 | 未核实到自动检查入口 |
| MP-37、MP-38、MP-39、MP-40、MP-41、MP-42、MP-43、MP-44、MP-46、MP-47、MP-48、MP-49 | 仅评审 | 未核实到自动检查入口 |
| MP-51、MP-52、MP-53、MP-54、MP-57、MP-61、MP-62、MP-63、MP-64、MP-65 | 仅评审 | 未核实到自动检查入口 |
