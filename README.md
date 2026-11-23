# Situated AI

[![CI](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml)
[![CodeQL](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml)

面向 Victoria 3 的 AI Mod 与开发工具链。产品目标与设计约束见[Mod 开发原则](docs/principles/Mod开发原则.md)。

Mod ID 为 `situated-ai`。现行游戏与 Python 基线、生产范围和推进状态见[当前工作清单](docs/design/当前工作清单.md)，标准包与公开发布身份见[版本交付索引](docs/design/exec/版本交付-结果.md)。

## 先读什么

- 了解项目设计、当前状态、版本和知识库，请从[文档导航](docs/README.md)进入。
- 产品阶段与目标见[架构主计划](docs/design/架构主计划.md)和[架构子计划](docs/design/架构子计划.md)。旧 31.4 阶段沿革见[历史归档](docs/design/archive/README.md#冻结版本)。
- 修改、生成、验证或打包，请阅读[贡献指南](CONTRIBUTING.md)。
- 代理任务接手与修改边界见[AGENTS.md](AGENTS.md)。

## 目录

```text
mod/                    生产源、策略生成物、脚本和本地化
src/pdx/                Python 解析、全量分析、快照、生成、审计和 ZIP 交付
tests/                  单元、属性、离线合同、生成和跨平台工具测试
tools/ci/               工程质量门；tools/benchmarks/ 为串行 Python 基准
tools/out/              可再生分析、报告和本机证据（通常忽略，少量登记快照与原始证据受控保留）
docs/                   当前规则、设计、计划、结果、审计和知识库
research/               原版资料清单与锁定接口证据
dist/                   可再生发布 ZIP（忽略）
```

文档的 Python 生成入口见[生成文档维护](docs/README.md#生成文档维护)。

## 标准包

标准包的生成、内容与回读校验见[工程交付基线](docs/design/exec/工程基线-1.0.md)。各实际渠道的状态见版本交付索引。

将 ZIP 解压到用户 Mod 目录 `Paradox Interactive/Victoria 3/mod/Situated AI`，在启动器中登记并启用独立 playset，开启新局。运行条件与存档适用范围见 [MP-41 和 MP-66](docs/principles/Mod开发原则.md)，各渠道实际交付以[版本交付索引](docs/design/exec/版本交付-结果.md)为准。

## 验证边界

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline-offline
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py test-offline
```

检查矩阵、工程性能测量、清理和 Git 流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。工程、Mod 静态语义、实际运行和长期体验的验收职责及证据口径见[工程交付基线](docs/design/exec/工程基线-1.0.md#验收职责)。

## 许可证

[Apache-2.0](LICENSE)
