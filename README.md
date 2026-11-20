# Situated AI

[![CI](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml)
[![CodeQL](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml)

面向 Victoria 3 的 AI Mod 与开发工具链。项目目标是让每个国家基于自身处境和可观测信息，在原版机制内持续做出符合自身约束与利益的相对最优决策。

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

安装时将 ZIP 解压到 `Paradox Interactive/Victoria 3/mod/Situated AI`，在启动器中登记并启用独立 playset；不要覆盖游戏本体。文本编码规则见[工程原则](docs/principles/工程原则.md)。

## 验证边界

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline-offline
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py test-offline
```

完整矩阵、性能口径、清理和 Git 流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。静态检查、快照和模拟只能证明明确覆盖的工程合同。引擎运行期语义、AI 行为质量、长期行为、平衡、后期性能、本地化呈现和 Workshop 体验需要用户在固定包上验收；工程通过不能代替这些结论。日志和存档提供辅助证据，其摘要不能单独证明这些结果。

## 许可证

[Apache-2.0](LICENSE)
