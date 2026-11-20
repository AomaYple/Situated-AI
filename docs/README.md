# 文档导航

文档按“当前规则 → 当前设计与状态 → 历史计划 → 结果与知识库”组织。导航页只提供入口和短摘要，
不复制规则正文、机械统计或实验结论。当前兼容基线、计划版本和用户验收边界以各自权威页为准。

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
| 1.15架构与实施入口 | [架构主计划](design/架构主计划.md) |
| 仅目标的领域及跨域子计划 | [架构子计划](design/架构子计划.md) |
| 新架构规范与底本依据 | [1.15架构设计](design/1.15架构设计.md)、[1.15底本勘察](design/1.15底本勘察.md)；R2 规范与已有候选能力分开登记 |
| 旧候选设计与范围上下文 | [处境决策设计](design/03-处境决策设计.md)、[行动层深化设计](design/05-行动层深化设计.md)、[行动覆盖与验收](design/04-行动覆盖与验收.md) |
| 原版 AI 静态索引（生成） | [可执行面](design/02-可执行面-1.15.2.md)、[政治候选面](design/02-政治候选面.md) |
| 历史实施计划（仅参考） | [处境行动决策内核实施计划](design/exec/mod重设计-实施计划.md) |
| 当前状态 | [当前工作清单](design/当前工作清单.md) |
| 历史 A2 架构检查与逐项证据 | [架构重设计结果](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/design/exec/%E6%9E%B6%E6%9E%84%E9%87%8D%E8%AE%BE%E8%AE%A1-%E7%BB%93%E6%9E%9C.md)、[架构阶段收据](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/design/exec/%E6%9E%B6%E6%9E%84%E9%98%B6%E6%AE%B5%E6%94%B6%E6%8D%AE.json)；局部通过不等于阶段完成 |
| 当前交付与历史版本证据 | [版本交付索引](design/exec/版本交付-结果.md)、[3.3.0 交付结果](design/exec/3.3.0-交付结果.md)；历史内核与分层收据由执行索引导航 |
| 创意工坊文案（Steam BBCode，发布前核对固定包） | [全部 11 种语言](publishing/README.md) |
| 本机安装盘点与原件研究 | [贡献指南](../CONTRIBUTING.md#完整安装研究) |
| 工具与诊断入口 | [工具手册](../tools/README.md) |
| Victoria 3 当前知识库 | [Victoria 3 1.15.2 知识库](victoria3-modding-1.15.2/README.md) |
| Victoria 3 历史知识库原件 | [1.14.5](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/victoria3-modding/README.md)、[1.15.0](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/victoria3-modding-1.15.0/README.md)、[1.15.1](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/victoria3-modding-1.15.1/README.md) |

## 目录职责

- `docs/principles/`：持续工程和产品约束。
- `docs/design/`：当前产品设计、计划和执行结果。
- `docs/publishing/`：面向玩家的发布材料；正文只维护功能、使用、兼容性和语言信息。
- `docs/victoria3-modding-1.15.2/` 收录当前锁定版本的研究知识库。历史知识库、配套生成索引和证据可在上述 Git 提交按原路径查看。

## 文档维护边界

| 文档类型 | 唯一来源 | 更新方式 |
|---|---|---|
| 规则与贡献流程 | `AGENTS.md`、`CONTRIBUTING.md`、`SECURITY.md`、`docs/principles/` | 人工评审；不在导航页复制 |
| 产品设计、计划、状态和结果 | `docs/design/` | 只在对应权威页更新，结果页记录证据类型 |
| 原版机械统计、指纹和索引 | `docs/design/02-*.md`、`docs/victoria3-modding-1.15.2/08-目录全量清单.md`、`13-common全量键名索引.md` 等生成目标 | 使用仓库 Python CLI 生成或核对，禁止手改生成数据 |
| Victoria 3 研究正文 | `docs/victoria3-modding-1.15.2/` | 保留历史采集值，但必须标明底本版本、快照时点和证据边界 |

## 生成文档维护

| 内容 | Python CLI 入口 |
|---|---|
| [已登记的机械表格](../src/pdx/docgen.py) | `v3 tables` 核对，`v3 tables --write` 重生成，`v3 tables --offline` 按入库快照核对 |
| 原版 AI 可执行面、政治候选面 | `v3 ai-surface --check` 和 `v3 political-surface --check` 核对，对应的 `--write` 生成页面 |
| common 全量键名索引 | `v3 index --dry-run` 查看统计，`v3 index` 重新生成 |
| 已登记表格与绑定归属标记的正文数字 | `v3 refresh --dry-run` 查看差异，`v3 refresh` 更新 |

以上入口也可用 `python -m pdx.cli` 调用。数字或版本漂移按 EP-26 和 EP-09 核对输入身份。本地与 CI 的验证流程见[贡献指南](../CONTRIBUTING.md)。
