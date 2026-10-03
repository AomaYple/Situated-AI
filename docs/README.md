# docs/ 导航

本目录是「Situated AI」项目的文档面。**第一次来 / 隔久了再回来，先看下面第一行。**

## 先看这个

| 想做什么 | 看这里 |
|---|---|
| 当前编码、三平台工具链、测试与性能审计 | [`design/exec/工程基线-1.0.md`](design/exec/工程基线-1.0.md)（当前工程入口与证据边界）；[`audits/2026-10-01-repository-upgrade.md`](audits/2026-10-01-repository-upgrade.md) 是审计依据 |
| **接手工作 / 恢复一个暂停的会话** | [`design/exec/工程基线-1.0.md`](design/exec/工程基线-1.0.md)；[`design/exec/接续-下一步.md`](design/exec/接续-下一步.md) 作为历史交接记录保留 |
| 了解项目大方向与阶段划分 | [`design/01-大方向.md`](design/01-大方向.md)（**冻结文档**：原则 P1–P14、冻结清单 F1–F12、阶段 §3） |
| 看依据与参考 | [`design/01a-依据与参考.md`](design/01a-依据与参考.md) |
| 看可执行面 / 欠账 | [`design/02-可执行面.md`](design/02-可执行面.md)、[`design/backlog.md`](design/backlog.md) |
| 最近一次收尾快照 | [`design/exec/阶段性收尾-20261001-仓库审计.md`](design/exec/阶段性收尾-20261001-仓库审计.md)（2026-10-01 历史快照）；当前工程状态以基线和 backlog 为准 |

## 本目录结构

| 路径 | 内容 |
|---|---|
| `design/` | 大方向、依据与参考、可执行面、欠账清单（**冻结文档**在 `01-大方向.md`） |
| `design/exec/` | 阶段执行文档、实机读数与历史交接；引用路径保留，索引见 [`design/exec/README.md`](design/exec/README.md) |
| `audits/` | 当前工程审计与历史快照；已完成报告集中在 [`audits/archive/`](audits/archive/) |
| `victoria3-modding/` | **21 篇 mod 开发知识库**（基于本机游戏安装目录与用户数据目录逐文件读取整理；多数结论采集于 1.14.2，尚未逐条重测） |
| `mod-face/` | （**规划中**）从 `mod/sitai_*.md` 迁入的 mod 对外说明（见接手文档 §4·q_mod_docs） |

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
| `mod/` | **生成物**：由 `v3 modgen` 从 `mod/data/*.toml`（9 份处境档案）生成，**不要手改** |
| `CLAUDE.md` / 会话纪律 | 见 [`design/exec/接续-下一步.md`](design/exec/接续-下一步.md) §6 铁律与 §7 已知的坑 |

## 三条最常见的命令

```text
python -m pdx.cli modgen --check          # 生成物与数据源逐字节一致？（使用仓库 venv Python）
python -m pdx.cli verify                 # 234 条断言；没有游戏时加 --from-snapshot
python -m pdx.cli citations --offline    # 引用是否落在快照支撑域内
```

完整门禁清单见 [`design/exec/收口清单.md`](design/exec/收口清单.md)。
