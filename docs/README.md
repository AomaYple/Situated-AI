# 文档导航

## 当前入口

| 目的 | 文档 |
|---|---|
| 代理接手和修改边界 | [根目录 AGENTS.md](../AGENTS.md) |
| 贡献、检查、Git 和发布 | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| 安全问题私密报告 | [SECURITY.md](../SECURITY.md) |
| 规则分工与条款编号 | [原则索引](principles/README.md) |
| 工程原则 | [工程原则](principles/工程原则.md) |
| Mod 原则 | [Mod 开发原则](principles/Mod开发原则.md) |
| 工具、快照和证据边界 | [工程交付基线](design/exec/工程基线-1.0.md) |
| 架构、深入设计、逐域计划和证据总入口 | [设计文档](design/README.md) |
| 当前架构、实施顺序和阶段出口 | [架构主计划](design/架构主计划.md) |
| 各领域方面的接口和状态 | [架构子计划](design/架构子计划.md) |
| 主线、候选和下一动作 | [当前工作清单](design/当前工作清单.md) |
| 安装与官方资料盘点、原版字段反查 | [原版资料盘点](design/architecture/原版资料盘点.md) |
| 历史设计与实施计划 | [R2 设计与旧候选](design/README.md#历史设计与迁移依据) · [历史归档](design/archive/README.md) |
| 工程、架构与逐项证据 | [执行文档索引](design/exec/README.md) |
| 当前交付与历史版本证据 | [版本交付索引](design/exec/版本交付-结果.md) |
| 创意工坊文案 | [全部 11 种语言](publishing/README.md) |
| 工具与诊断入口 | [工具手册](../tools/README.md) |
| Victoria 3 当前知识库 | [Victoria 3 1.15.2 知识库](victoria3-modding-1.15.2/README.md) |
| Victoria 3 历史知识库原件 | [1.14.5](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/victoria3-modding/README.md) · [1.15.0](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/victoria3-modding-1.15.0/README.md) · [1.15.1](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/victoria3-modding-1.15.1/README.md) |

旧版官方文档镜像和 1.15.0 AI 分类日志按原相对路径归档在仓库旁的 `Situated AI local archive/20261121-legacy-research/`，逐份身份见其中的 `archive-manifest.json`。

## 文档维护边界

| 文档类型 | 唯一来源 | 更新方式 |
|---|---|---|
| 规则与贡献流程 | `AGENTS.md`、`CONTRIBUTING.md`、`SECURITY.md`、`docs/principles/` | 在来源页人工评审。 |
| 产品设计、计划、状态和结果 | `docs/design/` | 在对应页面更新，结果页记录证据类型。 |
| 原版机械统计、指纹和索引 | `docs/design/02-*.md`、`docs/victoria3-modding-1.15.2/08-目录全量清单.md`、`13-common全量键名索引.md` 等生成目标 | 使用仓库 Python CLI 生成或核对。 |
| Victoria 3 研究正文 | `docs/victoria3-modding-1.15.2/` | 保留历史采集值，并标明底本版本、快照时点和证据边界。 |

## 生成文档维护

| 内容 | Python CLI 入口 |
|---|---|
| [已登记的机械表格](../src/pdx/docgen.py) | `v3 tables` 核对，`v3 tables --write` 重生成，`v3 tables --offline` 按入库快照核对 |
| 原版 AI 可执行面、政治候选面 | `v3 ai-surface --check` 和 `v3 political-surface --check` 核对，对应的 `--write` 生成页面 |
| common 全量键名索引 | `v3 index --dry-run` 查看统计，`v3 index` 重新生成 |
| 已登记表格与绑定归属标记的正文数字 | `v3 refresh --dry-run` 查看差异，`v3 refresh` 更新 |

以上入口也可用 `python -m pdx.cli` 调用。数字或版本漂移按 EP-26 和 EP-09 核对输入身份。本地与 CI 的验证流程见[贡献指南](../CONTRIBUTING.md)。
