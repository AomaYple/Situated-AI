# Situated AI

当前实施状态见[当前工作清单](docs/design/当前工作清单.md)和[拓展结果](docs/design/exec/广度深度拓展-结果.md)；版本、标准包、发布与部署身份统一见[版本交付索引](docs/design/exec/版本交付-结果.md)。

1.15 架构已深化为 R2 设计与实施基准，见[架构主计划](docs/design/架构主计划.md)和[架构设计](docs/design/1.15架构设计.md)；已有候选实现仍需按新合同补齐与验收。领域目标见[架构子计划](docs/design/架构子计划.md)，当前正式交付仍为 3.2.0 / 游戏 1.14.5。

[![CI](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml)
[![CodeQL](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml)

Victoria 3 AI Mod 与 Python 开发工具链。项目目标是让每个国家基于自身处境和可观测信息，在原版机制内持续做出符合自身约束与利益的相对最优决策。

Mod ID 为 `situated-ai`，锁定的 Victoria 3 底本版本见[工程交付基线](docs/design/exec/工程基线-1.0.md)。运行包通过原版 AI 消费者调整局部倾向，只包含 PDX、本地化、元数据和封面；生成器、静态审计、快照和证据工具留在仓库。

当前范围与验收以工程交付基线及[版本交付索引](docs/design/exec/版本交付-结果.md)登记的交付结果为准；[处境行动决策内核实施计划](docs/design/exec/mod重设计-实施计划.md)仅作旧计划参考，旧设计与原始证据由[历史归档](docs/design/archive/README.md)导航，只解释对应历史快照。

## 当前决策方式

当前3.2.0生产决策链、国家协调及排他路线退役见[拓展结果](docs/design/exec/广度深度拓展-结果.md)，联合决策合同见[工程交付基线](docs/design/exec/工程基线-1.0.md)。调整只影响原版 AI 的局部倾向，资格、实际成本、政治支持、随机、拒绝、终结零分与执行继续由原版决定。

跨域反馈依赖已发生的世界事实。例如，当前公校法律、实际学校制度与识字状态可以改变教育和生产配置的相关增量；候选行动评分较高不代表行动已经执行，也不证明后续变化由 Mod 导致。完整领域范围和阶段验收仍以[当前工作清单](docs/design/当前工作清单.md)及对应收据为准。

## 先读什么

1. [AGENTS.md](AGENTS.md)：代理接手顺序和修改边界。
2. [CONTRIBUTING.md](CONTRIBUTING.md)：生成、检查、分支、提交、PR 和发布。
3. [工程原则](docs/principles/工程原则.md)与[Mod 开发原则](docs/principles/Mod开发原则.md)。
4. [架构主计划](docs/design/架构主计划.md)、[架构子计划](docs/design/架构子计划.md)与[当前工作清单](docs/design/当前工作清单.md)。
5. [版本交付索引](docs/design/exec/版本交付-结果.md)：当前版本的发布、部署身份与逐版本交付结果入口；旧上下文见[历史归档](docs/design/archive/README.md)。

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

## 快速开始

Windows：

```text
.venv\Scripts\python.exe -X utf8 -m pip install -e ".[dev]"
.venv\Scripts\python.exe -X utf8 -m pdx.cli modgen --check
.venv\Scripts\python.exe -X utf8 -m pdx.cli modguard --offline
.venv\Scripts\python.exe -X utf8 -m pdx.cli package
```

macOS/Linux 将解释器替换为 `.venv/bin/python`。没有游戏时仍可运行离线检查；有游戏时可用 `V3_ROOT`、`V3_USERDIR` 指定路径。生成和正式打包要求锁定原版底本，底本缺失或漂移时硬失败。

## 标准包

包包含标准 metadata、生成的 `common/`、锁定版本支持的全部语言、封面、manifest 和安装说明，不包含 Python、探针、日志、缓存、快照、报告、原始底本或历史实验。`package` 按生产源中的版本打包，不代表该版本已经发布。已发布基线与目标版本的标签、包哈希和 GitHub Release 状态只在[版本交付索引](docs/design/exec/版本交付-结果.md)维护；Workshop 页面由发布者在固定包上单独验收和发布。

安装时将 ZIP 解压到 `Paradox Interactive/Victoria 3/mod/Situated AI`，在启动器中登记并启用独立 playset；不要覆盖游戏本体。文本编码规则见[工程原则](docs/principles/工程原则.md)。

## 验证边界

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py test-offline
```

完整矩阵、性能口径、清理和 Git 流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。静态检查、快照和模拟只能证明明确覆盖的工程合同。引擎运行期语义、AI 行为质量、长期行为、平衡、后期性能、本地化呈现和 Workshop 体验需要用户在固定包上验收；工程通过不能代替这些结论。日志、存档和观察器提供辅助证据，其摘要不能单独证明这些结果。

## 许可证

[Apache-2.0](LICENSE)
