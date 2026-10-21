# 文档导航

文档按“当前规则 → 当前设计 → 当前计划 → 结果与历史 → 知识库”组织。导航页只提供入口和短摘要，
不复制规则正文或实验结论。

## 当前入口

| 目的 | 文档 |
|---|---|
| 代理接手和修改边界 | [根目录 AGENTS.md](../AGENTS.md) |
| 贡献、检查、Git 和发布 | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| 工程原则 | [工程原则](principles/工程原则.md) |
| Mod 原则 | [Mod 开发原则](principles/Mod开发原则.md) |
| 工具、快照和证据边界 | [工程交付基线](design/exec/工程基线-1.0.md) |
| 产品架构 | [处境决策设计](design/03-处境决策设计.md) |
| 当前计划 | [Situated AI 1.0.0 交付计划](design/exec/mod重设计-实施计划.md) |
| 当前状态 | [当前工作清单](design/当前工作清单.md) |
| 工具使用 | [工具手册](../tools/README.md) |
| Victoria 3 知识库 | [victoria3-modding](victoria3-modding/README.md) |

## 目录职责

- `docs/principles/`：持续工程和产品约束。
- `docs/design/`：当前产品设计、计划、backlog 和执行结果。
- `docs/audits/`、`docs/reports/`：日期化审计、实测、失败和独立复核；只保留当时事实。
- `docs/victoria3-modding/`：由锁定游戏文件整理的研究知识库，版本和来源以各页说明为准。
- `docs/superpowers/`：历史计划模板和已完成任务记录，不是当前计划入口。

## 文档维护

规则进入规则页，流程进入 `CONTRIBUTING.md`，产品架构进入设计页，当前顺序进入主计划，事实进入结果或
日期化审计，历史实验保持原始上下文。机械统计、指纹和表格通过 Python 生成器维护；不要手改生成物。
删除或移动前核对链接、测试、生成入口和证据引用。历史文档不会被改写成当前状态，也不会进入标准 Mod ZIP。
