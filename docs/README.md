# docs/ 导航

本目录是「Situated AI」项目的文档面。**第一次来 / 隔久了再回来，先看下面第一行。**

## 先看这个

| 想做什么 | 看这里 |
|---|---|
| 当前编码、三平台工具链、测试与性能审计 | [`design/exec/工程基线-1.0.md`](design/exec/工程基线-1.0.md)（当前工程入口与证据边界）；[`audits/2026-10-01-repository-upgrade.md`](audits/2026-10-01-repository-upgrade.md) 是审计依据 |
| 参与开发、编码和提交前检查 | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |
| 编码代理的项目规则、源码入口与验证选择 | [`../AGENTS.md`](../AGENTS.md) |
| 性能优化的顺序、预算与正确性验收 | [速度优化计划-正确性优先](design/exec/速度优化计划-正确性优先.md) |
| 本轮仓库总览、清理与验证 | [2026-10-10 仓库整理](audits/2026-10-10-repository-maintenance.md) |
| **接手工作 / 恢复一个暂停的会话** | [`最终执行纲领 1.0`](design/exec/mod重设计-实施计划.md) → 对应 M1–M5 结果页及 [`backlog`](design/backlog.md)；行为模型见 [`03`](design/03-处境决策设计.md)，工程入口见 [`工程基线`](design/exec/工程基线-1.0.md) |
| 了解当前 mod 方向、产品形式与验收 | [`design/03-处境决策设计.md`](design/03-处境决策设计.md)（当前设计；真实财政机制已实现；评分差分与卸载已有实机证据，长期和扩展验收继续执行） |
| 看历史方向及引擎依据 | [`design/01-大方向.md`](design/01-大方向.md)、[`design/01a-依据与参考.md`](design/01a-依据与参考.md)（保留历史正文与引用行号） |
| 看可执行面 / 政治候选 / 欠账 | [`design/02-可执行面.md`](design/02-可执行面.md)、[`design/02-政治候选面.md`](design/02-政治候选面.md)、[`design/backlog.md`](design/backlog.md) |
| 2026-10-01 收尾快照 | [`design/exec/阶段性收尾-20261001-仓库审计.md`](design/exec/阶段性收尾-20261001-仓库审计.md)（历史快照）；当前工程状态以基线和 backlog 为准 |

## 本目录结构

| 路径 | 内容 |
|---|---|
| `design/` | 当前处境决策设计、历史方向与依据、生成的可执行面、研究欠账清单 |
| `design/exec/` | 阶段执行文档、实机读数与历史交接；引用路径保留，索引见 [`design/exec/README.md`](design/exec/README.md) |
| `audits/` | 当前工程审计与历史快照；已完成报告集中在 [`audits/archive/`](audits/archive/) |
| `victoria3-modding/` | **21 篇 mod 开发知识库**（基于本机游戏安装目录与用户数据目录逐文件读取整理；多数结论采集于 1.14.2，尚未逐条重测） |

## 历史归档

已完成的工程记录、重构计划和重构前测试审计集中在 [`audits/archive/`](audits/archive/) 与 [`superpowers/archive/`](superpowers/archive/)。原路径保留兼容指针，避免历史报告和测试说明出现悬空引用。

## 相关但不在本目录

| 位置 | 内容 |
|---|---|
| `README.md`（仓库根） | 项目总览、环境、知识库入口、关键结论 |
| `tools/README.md` | **工具链手册**（`v3` 全子命令、门禁、测试、性能与内存纪律） |
| `docs/reports/` | 各卡的交付报告与独立复核，索引见 [`reports/README.md`](reports/README.md) |
| `tools/out/` | 原始证据、机器测量和可恢复备份；忽略原始输出，只放行精简快照 |
| `research/` | 官方文档 manifest + 本地镜像（**原文不入库**） |
| `mod/` | 生产源 `decisions/fiscal.toml` 与 `decisions/extensions.toml` 生成根级产物；旧9份 `data/*.toml` 只生成至 `legacy/`，**不要手改产物** |
| 历史会话纪律与交接 | [`design/exec/接续-下一步.md`](design/exec/接续-下一步.md)；其中任务、授权和读数属于当时记录，当前工作以本页入口及用户指令为准 |

## 当前设计与历史证据的关系

`design/03-处境决策设计.md` 管理当前行为设计，`design/exec/工程基线-1.0.md` 管理工程契约，
`design/exec/mod重设计-实施计划.md` 是固定执行纲领，定义目标、出口与变化分支；M1–M5 结果页更新实验参数和进度，`design/backlog.md` 管理未完成研究与工程维护项。
旧 `01 / 01a` 和阶段报告继续提供历史事实与实验依据；旧手段阶梯、阶段顺序和验收不能覆盖当前设计。
`design/02-可执行面.md`、知识库机械表格以及 `mod/legacy/sitai_*.md` 仍由对应工具生成，不手改。

## 三条最常见的命令

```text
python -m pdx.cli modgen --check          # 生成物与数据源逐字节一致？（使用仓库 venv Python）
python -m pdx.cli verify                 # 234 条断言；没有游戏时加 --from-snapshot
python -m pdx.cli citations --offline    # 引用是否落在快照支撑域内
```

完整门禁清单见 [`design/exec/收口清单.md`](design/exec/收口清单.md)。
