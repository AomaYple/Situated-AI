# Situated AI 项目代理指南

本文件是仓库级任务路由与接手入口，不重复贡献流程或原则正文。修改、验证、提交和交付流程见
[CONTRIBUTING.md](CONTRIBUTING.md)；持续工程约束见[工程原则](docs/principles/工程原则.md)，产品目标与设计约束见
[Mod 开发原则](docs/principles/Mod开发原则.md)。具体生成、包结构和证据合同见
[工程交付基线](docs/design/exec/工程基线-1.0.md)。

系统、开发者和用户指令优先于本文件；更窄目录中的 `AGENTS.md` 可按作用范围补充本指南。

## 权威入口

| 内容 | 唯一当前来源 |
|---|---|
| 任务接手与代码路由 | 本文件 |
| 环境、验证、Git 和交付流程 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 工程持续约束 | [工程原则](docs/principles/工程原则.md) |
| Mod 目标、设计和验收边界 | [Mod 开发原则](docs/principles/Mod开发原则.md) |
| 生成、包结构、证据和恢复合同 | [工程交付基线](docs/design/exec/工程基线-1.0.md) |
| 当前阶段与出口 | [Mod 实施计划](docs/design/exec/mod重设计-实施计划.md) |
| 当前事实与下一动作 | [当前工作清单](docs/design/当前工作清单.md) |
| 阶段事实和交付收据 | `docs/design/exec/*-结果.md` |
| 安全问题报告 | [SECURITY.md](SECURITY.md) |

原则页描述持续约束，计划页描述顺序和出口，清单页记录当前状态，结果页记录证据。原则或计划中的目标不证明
代码已经实现；当前能力以生产源、检查结果和相应收据为准。导航页只提供入口，不复制另一份规则。

## 接手顺序

开始非只读任务前：

1. 按贡献指南完成工作树检查，辨认并保留已有改动；按任务需要检查相关进程、部署指针和锁文件。
2. 阅读本文件及适用的原则；Mod 工作同时阅读当前工作清单和主计划，涉及生成/快照/交付时阅读工程基线。
3. 只有需要历史事实、失败因果或原始字节时，才深入读取旧结果、审计、报告和 `research` 材料。

## 修改路由

| 任务 | 首选入口 | 约束 |
|---|---|---|
| Mod 源和生成 | `mod/decisions/*.toml`、`src/pdx/decisions.py`、`decision_rules.py`、`decision_adapters.py`、`distribution.py` | 生成物不手改；按贡献流程重生成并核对 |
| 全量分析与快照 | `src/pdx/`、`v3 analyze`、`v3 information-catalog`、`v3 snapshot` | 只登记可发现能力；不可见的引擎状态标为 `unknown`/`unsupported` |
| 工程检查 | `tools/ci/run_check.py` | 使用仓库 `.venv`，无需激活；再生输出写入忽略的 `tools/out/` |
| 文档和机械表格 | 对应 CLI、`pdx.doc_tables`、`pdx.docgen` | 修改唯一来源后重新生成；不手改指纹、统计和 manifest |
| 标准包 | `src/pdx/distribution.py`、`v3 package` | 依据工程基线；不得将探针、日志、缓存或历史实验放入生产包 |
| 历史实验 | Git 历史；可再生输出在 `tools/out/` | 不进入当前工作树、计划、默认 CLI 路径或发布包 |

具体命令、检查范围和 Git 操作统一按 [CONTRIBUTING.md](CONTRIBUTING.md) 执行。当前阶段和版本不在本文件维护，避免
入口规则随阶段推进而过期。
