# docs/ 导航

本目录按“当前规则 → 当前设计 → 当前结果 → 历史依据 → 知识库”组织。导航页只提供入口和状态摘要；原则、设计和计划只在各自权威文档维护。

## 先看当前入口

| 目的 | 权威入口 |
|---|---|
| 工程原则 | [工程原则](principles/工程原则.md) |
| Mod 开发原则 | [Mod 开发原则](principles/Mod开发原则.md) |
| 贡献、验证、性能、实机和 Git | [CONTRIBUTING.md](<../CONTRIBUTING.md>) |
| 代理工作边界和修改入口 | [AGENTS.md](<../AGENTS.md>) |
| 测试、分析、快照和证据契约 | [工程基线 1.0](design/exec/工程基线-1.0.md) |
| 当前产品架构和行为边界 | [处境决策设计](design/03-处境决策设计.md) |
| M0–M5 执行顺序、出口和重开条件 | [最终执行纲领](design/exec/mod重设计-实施计划.md) |
| 当前阶段结果和阻塞 | [当前工作清单](design/当前工作清单.md)、[结果索引](design/exec/README.md)与 [backlog](design/backlog.md) |
| 报告与独立复核 | [报告索引](reports/README.md)、[审计索引](audits/README.md) |
| Victoria 3 文件和脚本知识库 | [知识库](victoria3-modding/README.md) |
| Python 工具、CLI、快照和探针 | [工具手册](../tools/README.md) |

## 目录职责

| 路径 | 职责 | 文档效力 |
|---|---|---|
| `principles/` | 工程与 Mod 的持续约束，共同遵守正确性优先并分别验证开发和运行效率 | 当前原则权威 |
| [design/](design/README.md) | 当前设计、计划、结果、backlog 和历史依据 | 设计与执行权威 |
| [design/exec/](design/exec/README.md) | M1–M5 结果、工程基线、性能计划和历史执行记录 | 当前入口在 README，旧文件按历史使用 |
| [audits/](audits/README.md) | 仓库、工程和证据审计 | 日期化审计；不能覆盖当前原则 |
| [reports/](reports/README.md) | 独立报告、复核和失败记录 | 历史证据；按报告自身日期和范围解释 |
| [victoria3-modding/](victoria3-modding/README.md) | 基于本机游戏文件整理的 21 篇知识库 | 研究资料；版本和来源以各页说明为准 |
| `superpowers/plans/` | 已执行的工程专项计划 | 具体历史任务的依据，不替代当前 Mod 纲领 |

## 当前设计与历史证据

当前行为设计以 [03 · 处境决策设计](design/03-处境决策设计.md)为准，当前工程契约以 [工程基线](design/exec/工程基线-1.0.md)为准，当前执行顺序以 [最终执行纲领](design/exec/mod重设计-实施计划.md)为准。[当前工作清单](design/当前工作清单.md)提供状态摘要，M1–M5 结果页记录实测和边界；backlog 保留当前触发条件以及已结案条目的历史编号。

01、01a、旧阶段文档、交接记录、审计和 reports 保留当时的输入、失败和推断。它们可以支持复核，不能把旧阶段完成词句追认为当前能力。02 · 可执行面是当前生成的接口资料，生成入口见 [设计导航](design/README.md#生成文档)；生成文档和机械统计由对应工具维护，不手改。

## 文档维护

新增或修改文档时先判定它属于规则、设计、计划、结果、审计、历史报告、生成物、官方原文或证据。持续原则进入原则页；工程流程进入 CONTRIBUTING，工具契约进入工程基线；产品架构进入 03；阶段顺序和出口进入最终执行纲领。流程、架构和阶段出口落实原则，不能成为另一套相互矛盾的持续规则。专项实现可以有从属计划，但不得改变主纲领门禁。实测追加到结果页或日期化审计，历史报告保留原语境。导航文件只增加链接和短摘要，不复制完整规则。机械数字、表格和指纹通过生成器更新。

Mod 总计划由人工维护目标、依赖、预算和出口；[当前工作清单](design/当前工作清单.md#当前任务编排)管理执行队列，M1–M5 结果页记录预登记与证据。纯生成文档使用对应 CLI，混合文档的机械表由 `pdx.docgen` / `pdx.doc_tables` 登记，正文数字复用 `claim` 标记及 `pdx.verify`；不能将上述人工判断交给生成器自行判定通过。实验运行复用现有账本和恢复机制，不另建重复维护阶段状态或验收规则的配置。

维护时同时更新受影响的链接、命令和状态摘要。结果页负责完整证据，当前工作清单只摘录结论和下一出口；冲突时先核对新结果并修正摘要。删除或移动前检查历史引用、测试、生成入口和可恢复原件。旧文档若混有当前操作与历史取证，在索引中说明范围，不能一律当作失效文件删除。

## 常用命令

    .venv\Scripts\python.exe -X utf8 tools/ci/run_check.py encoding
    .venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline
    .venv\Scripts\python.exe -X utf8 -m pdx.cli modgen --check
    .venv\Scripts\python.exe -X utf8 -m pdx.cli citations --offline

macOS/Linux 将解释器替换为 `.venv/bin/python`。完整命令和验证矩阵见 [CONTRIBUTING.md](../CONTRIBUTING.md#验证矩阵)；游戏侧 BOM 只在安装/打包边界添加，仓库文档保持 UTF-8 无 BOM、LF。
