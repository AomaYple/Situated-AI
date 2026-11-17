# Situated AI 项目代理指南

本文件是仓库级任务接手、权威来源和修改路由入口，不复制贡献流程、原则正文或当前阶段状态。环境、验证、Git 和交付流程见
[CONTRIBUTING.md](CONTRIBUTING.md)；工程持续约束见[工程原则](docs/principles/工程原则.md)，产品目标与设计约束见
[Mod 开发原则](docs/principles/Mod开发原则.md)；生成、包结构、证据和恢复合同见[工程交付基线](docs/design/exec/工程基线-1.0.md)。

系统、开发者和用户指令优先于本文件；更窄目录中的 `AGENTS.md` 可按作用范围补充本指南。

## 权威入口

| 内容 | 唯一当前来源 |
|---|---|
| 任务接手与代码路由 | 本文件 |
| 环境、验证、Git 和交付流程 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 工程持续约束 | [工程原则](docs/principles/工程原则.md) |
| Mod 目标、设计和验收边界 | [Mod 开发原则](docs/principles/Mod开发原则.md) |
| 规则文件分工、原则编号与执行覆盖 | [原则索引](docs/principles/README.md) |
| 生成、包结构、证据和恢复合同 | [工程交付基线](docs/design/exec/工程基线-1.0.md) |
| 当前架构与计划入口 | [架构主计划](docs/design/架构主计划.md)、[架构子计划](docs/design/架构子计划.md) |
| 当前事实与下一动作 | [当前工作清单](docs/design/当前工作清单.md) |
| 阶段事实和交付收据 | `docs/design/exec/*-结果.md` 及其索引 |
| 安全问题报告 | [SECURITY.md](SECURITY.md) |

原则页描述持续约束，计划页描述顺序和出口，清单页记录当前状态，结果页记录证据。原则、计划或合同中的目标不证明代码已经实现；当前能力以生产源、检查结果和相应收据为准。导航页只提供入口，不复制另一份规则。

## 接手顺序

开始非只读任务前：

1. 按 [CONTRIBUTING.md](CONTRIBUTING.md) 完成工作树检查，辨认并保留已有改动；按任务需要检查相关进程、部署指针和锁文件。
2. 阅读本文件及适用的原则；Mod 工作同时阅读当前工作清单和主计划，涉及生成、快照或交付时阅读工程交付基线。
3. 只有需要历史事实、失败因果或原始字节时，才深入读取历史结果、审计、报告和 `research` 材料。

## 修改路由

| 任务 | 首选入口 | 路由边界 |
|---|---|---|
| Mod 源和生成 | `mod/decisions/*.toml`、`src/pdx/decisions.py`、`decision_rules.py`、`decision_adapters.py`、`distribution.py` | 生产源是唯一输入；生成物按贡献流程更新，不手改生成结果。 |
| 全量分析与快照 | `src/pdx/`、CLI 分析/快照入口 | 完整资料研究、国家运行期观测、解析能力和生产接线分别证明；不可见状态保持未知。 |
| 工程检查 | `tools/ci/` | 检查入口只实现工程质量门；流程和运行口径以 [CONTRIBUTING.md](CONTRIBUTING.md) 为准。 |
| 文档和机械表格 | 对应 CLI、`pdx.doc_tables`、`pdx.docgen` | 修改唯一来源后重新生成；不手改指纹、统计和 manifest。 |
| 标准包 | `src/pdx/distribution.py`、package 入口 | 依据工程交付基线生成和核验；探针、日志、缓存和历史实验不进入生产包。 |
| 实验与历史证据 | `tools/out/`、`docs/design/archive/` | 实验不进入默认生产路径；冻结证据按原字节合同保留。 |

纯工程治理以规则、代码、文档、结构与工具的统一和行为保持为范围，不自动恢复产品计划。提交前核对与目标主线的全部差异；独立治理改动不得夹带未完成产品候选。

全局 `.codex/AGENTS.md` 属于会话治理规则，不复制进仓库。
