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
| EP-20 | 强执行 | `.github/workflows/ci.yml` 的三平台解释器矩阵（离线用例） |
| EP-27 | 强执行 | `run_check.py encoding`（CI、pre-commit）、`tests/test_repo_hygiene.py` |
| EP-28 | 强执行 | `src/pdx/distribution.py` 的交付文件 BOM/LF 校验 |
| EP-24 | 强执行 | `tests/test_engineering_enforcement.py` 逐行核对 `.github/workflows/*.yml` 的 `uses:`（本地 action 除外）以 40 位提交 SHA 固定 |
| EP-03 | 仅评审 | 当前主线尚未核实到覆盖本条完整边界的自动检查入口；专项证据另行登记 |
| EP-04 | 部分执行 | `src/pdx/distribution.py`、`src/pdx/decision_rules.py` 的漂移拒绝；`tests/test_decisions.py`、`tests/test_profile_live_boundary.py` |
| EP-06、EP-07、EP-09 | 仅评审 | 当前主线尚未核实到覆盖本条完整边界的自动检查入口；专项证据另行登记 |
| EP-10 | 仅评审 | 当前主线尚未核实到覆盖本条完整边界的自动检查入口；专项证据另行登记 |
| EP-14 | 仅评审 | 当前主线尚未核实到覆盖本条完整边界的自动检查入口；专项证据另行登记 |
| EP-16 | 部分执行 | CI 各任务从 `pyproject.toml` 读取解释器要求；`tests/test_engineering_enforcement.py` 拒绝仓库根的独立工具配置文件并核对 pytest、coverage、ruff、mypy 配置段；其余工具的配置集中靠评审 |
| EP-19 | 部分执行 | `tests/test_portability.py` 拒绝受控 `src`、`tools`、`tests` Python 文件中的机器专属绝对路径；`tests/test_engineering_enforcement.py` 只覆盖 `tests/` 下属性调用形式的 `read_text`/`write_text` 省略 encoding，以及带 `text=`/`universal_newlines=` 的 `subprocess` 属性调用省略 encoding；内建 `open()`、`Path.open()` 的文本模式、`from subprocess import run` 形式，以及 `src`、`tools` 的默认编码与 shell 默认行为都靠评审 |
| EP-21 | 部分执行 | `run_check.py types` 在 `pyproject.toml` 的 mypy 文件范围检查类型兼容；公共注解完整性与错误合同仍需测试及评审 |
| EP-22 | 部分执行 | CI 的 `v3 lock` 与 `pip check`；`tests/test_lockfile.py` 覆盖解释器合同、条件依赖、extras、环及缺失闭包拒绝；变更原因靠评审 |
| EP-23 | 部分执行 | `tests/test_engineering_enforcement.py` 核对 dev 依赖中的 Ruff、mypy 以 `==` 固定且与 `requirements.lock` 版本相等；CI 的 `v3 lock`；升级复核靠评审 |
| EP-25 | 部分执行 | `v3 modgen --check` 只在本地 `run_check.py baseline`；CI 运行 `v3 modguard --offline` |
| EP-26 | 部分执行 | 机械表格由 `tests/test_doc_overview.py` 与 CI 的 `v3 tables --offline` 看守；指纹与 manifest 未核实到专门的自动检查入口 |
| EP-29 | 部分执行 | `tests/test_repo_hygiene.py` 的原版证据路径与哈希合同 |
| EP-30 | 部分执行 | `src/pdx/distribution.py` 的包内容校验；默认生产路径靠评审 |
| EP-31 | 部分执行 | `.gitignore`、`run_check.py hygiene`（CI）；凭据靠评审 |
| EP-34 | 部分执行 | CI 的 `tools/ci/test_summary.py` 拒绝未分类跳过；`tests/test_engineering_enforcement.py` 拒绝无法归类的跳过原因与未登记 xfail；覆盖率总门及核心模块门由本地 `full-acceptance` 核验，其余靠评审 |
| EP-50 | 仅评审 | 当前主线尚未核实到覆盖本条完整边界的自动检查入口；专项证据另行登记 |
| EP-55 | 部分执行 | `v3 verify --from-snapshot`（CI、pre-commit）与 `tests/test_docs_consistency.py` 只看守已登记的数字断言 |
| EP-05 | 仅评审 | 失效的相对链接另由 `tests/test_docs_consistency.py` 发现 |
| EP-36 | 仅评审 | `.github/pull_request_template.md` 提示标明类别 |
| EP-56、EP-57 | 仅评审 | `tests/test_engineering_contract.py` 只锁定原文，不检查行为 |
| EP-01、EP-02、EP-08、EP-11、EP-12、EP-13、EP-15、EP-17、EP-18 | 仅评审 | 未核实到自动检查入口 |
| EP-32、EP-33、EP-35、EP-37、EP-38、EP-39、EP-40、EP-41、EP-42、EP-43、EP-44、EP-45 | 仅评审 | 未核实到自动检查入口 |
| EP-46、EP-47、EP-48、EP-49、EP-51、EP-52、EP-53、EP-54、EP-58 | 仅评审 | 未核实到自动检查入口 |
| EP-59、EP-60、EP-61 | 部分执行 | `pyproject.toml` 固定补丁版本，三平台 CI 共用该基线；`tools/ci/run_check.py`、`tests/test_run_check.py` 核验正式 CPython 和虚拟环境记录；旧兼容代码清退和实现选型靠评审 |
| EP-62、EP-63 | 仅评审 | 信息读取范围与成熟库选型需要专项审查，本轮工具检查不代签产品读取能力 |
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
