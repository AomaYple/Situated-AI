# 文档导航

文档按“当前规则 → 当前设计 → 当前计划 → 结果与知识库”组织。导航页只提供入口和短摘要，
不复制规则正文、机械统计或实验结论。当前兼容基线、计划版本和用户验收边界以各自权威页为准。

## 当前入口

| 目的 | 文档 |
|---|---|
| 代理接手和修改边界 | [根目录 AGENTS.md](../AGENTS.md) |
| 贡献、检查、Git 和发布 | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| 工程原则 | [工程原则](principles/工程原则.md) |
| Mod 原则 | [Mod 开发原则](principles/Mod开发原则.md) |
| 工具、快照和证据边界 | [工程交付基线](design/exec/工程基线-1.0.md) |
| 产品架构 | [处境决策设计](design/03-处境决策设计.md) |
| 原版 AI 静态索引（生成） | [可执行面](design/02-可执行面.md)、[政治候选面](design/02-政治候选面.md) |
| 当前计划 | [Situated AI 1.0.1 当前交付与后续计划](design/exec/mod重设计-实施计划.md) |
| 当前状态 | [当前工作清单](design/当前工作清单.md) |
| 工具使用 | [工具手册](../tools/README.md) |
| Victoria 3 知识库 | [victoria3-modding](victoria3-modding/README.md) |

## 目录职责

- `docs/principles/`：持续工程和产品约束。
- `docs/design/`：当前产品设计、计划和执行结果。
- `docs/victoria3-modding/`：由锁定游戏文件整理的研究知识库，版本和来源以各页说明为准。

## 文档维护边界

| 文档类型 | 唯一来源 | 更新方式 |
|---|---|---|
| 规则与贡献流程 | `AGENTS.md`、`CONTRIBUTING.md`、`docs/principles/` | 人工评审；不在导航页复制 |
| 产品设计、计划、状态和结果 | `docs/design/` | 只在对应权威页更新，结果页记录证据类型 |
| 原版机械统计、指纹和索引 | `docs/design/02-*.md`、`docs/victoria3-modding/08-目录全量清单.md`、`13-common全量键名索引.md` 等生成目标 | 使用仓库 Python CLI 生成或核对，禁止手改生成数据 |
| Victoria 3 研究正文 | `docs/victoria3-modding/` | 保留历史采集值，但必须标明底本版本、快照时点和证据边界 |

生成文件的声明优先级高于手工摘要；发现数字或版本漂移时先运行 `v3 refresh`，再修改无法由工具判断的散文。

## 文档维护

规则进入规则页，流程进入 `CONTRIBUTING.md`，产品架构进入设计页，当前顺序进入主计划，事实进入少量结果
收据。机械统计、指纹和表格通过 Python 生成器维护；不要手改生成物。删除或移动前核对链接、测试、生成入口
和证据引用。历史文档保留在 Git 历史，不进入标准 Mod ZIP。
