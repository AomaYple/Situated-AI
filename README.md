# Situated AI

当前实施状态见[工作清单](docs/design/当前工作清单.md)及[1.15迁移规划结果](docs/design/exec/1.15迁移规划-结果.md)；版本、标准包、发布与部署身份统一见[版本交付索引](docs/design/exec/版本交付-结果.md)。

当前战略见[架构主计划](docs/design/架构主计划.md)，领域与联动目标见[架构子计划](docs/design/架构子计划.md)，
A4 深化目标与验收合同见[架构深化计划](docs/design/架构深化计划.md)。A4 1.15 迁移已启动，执行中；本轮先完成仓库前置核对，阶段仍未完成，实际证据见[A4实施结果](docs/design/exec/A4实施-结果.md)与工作清单；生产版本仍为3.2.0。
X1扩展已完成并随3.2.0正式交付；工程与实际安装证据见[交付结果](docs/design/exec/3.2.0-交付结果.md)。旧计划只作历史参考，长期行为和平衡由用户验收。

[![CI](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml)
[![CodeQL](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml)

Victoria 3 AI Mod 与 Python 开发工具链。项目目标是让每个国家基于自身处境和可观测信息，在原版机制内持续做出符合自身约束与利益的相对最优决策。

当前正式包底本为 Victoria 3 `1.14.5`；A4目标底本为 `1.15.0`，Mod ID 为 `situated-ai`。运行包通过原版 AI 消费者调整局部倾向，只包含 PDX、本地化、元数据和封面；生成器、静态审计、快照和证据工具留在仓库。

当前正式包仍以工程基线及3.2.0交付结果为准；A4先迁移到1.15.0再产生新包；[处境行动决策内核实施计划](docs/design/exec/mod重设计-实施计划.md)仅作旧计划参考，旧设计与原始证据由[历史归档](docs/design/archive/README.md)导航，只解释对应历史快照。
长期行为、平衡、后期性能、本地化呈现和 Workshop 体验由用户在固定包上验收。

## 当前决策方式

已接入的生产机制从原版机会出发，读取具体对象的真实观测，形成具体行动的需求、收益和成本；同一因果的同方向档位取最强已知项，独立贡献联合后在消费者末端一次限幅。调整只影响原版 AI 的局部倾向，资格、实际成本、政治支持、随机、拒绝、终结零分与执行继续由原版决定。

各领域在消费者求值时读取当前事实，教育、政治、产业和安全需求可以同时存在。全国排他路线及其预算、时钟和切换冷却已退役；无实际消费者的财政月度更新不再部署，原版可观察的战败记忆保留。核心未知局部回退，辅助未知只退出相关增量，正常融资、低识字或行政短板不会成为全部发展的共同禁令。

跨域反馈依赖已发生的世界事实。例如，当前公校法律、实际学校制度与识字状态可以改变教育和生产配置的相关增量；候选行动评分较高不代表行动已经执行，也不证明后续变化由 Mod 导致。完整领域范围和阶段验收仍以当前工作清单及对应收据为准。

## 先读什么

1. [AGENTS.md](AGENTS.md)：代理接手顺序和修改边界。
2. [CONTRIBUTING.md](CONTRIBUTING.md)：生成、检查、分支、提交、PR 和发布。
3. [工程原则](docs/principles/工程原则.md)与[Mod 开发原则](docs/principles/Mod开发原则.md)。
4. [架构主计划](docs/design/架构主计划.md)、[架构子计划](docs/design/架构子计划.md)、[架构深化计划](docs/design/架构深化计划.md)与[当前工作清单](docs/design/当前工作清单.md)。
5. [3.2.0交付结果](docs/design/exec/3.2.0-交付结果.md)：当前交付的功能、最终回归、发布、部署与验收边界；旧上下文见[历史归档](docs/design/archive/README.md)。

## 目录

```text
mod/                    生产源、策略生成物、脚本和本地化
src/pdx/                Python 解析、全量分析、快照、生成、审计和 ZIP 交付
tests/                  单元、属性、离线合同、生成和跨平台工具测试
tools/ci/               工程质量门；tools/benchmarks/ 为串行 Python 基准
tools/out/              可再生分析、报告和本机证据（忽略）
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

包包含标准 metadata、生成的 `common/`、11 种本体语言、封面、manifest 和安装说明，不包含 Python、探针、日志、缓存、快照、报告、原始底本或历史实验。`package` 按生产源中的版本打包，不代表该版本已经发布。已发布基线与目标版本的标签、包哈希和 GitHub Release 状态只在[版本交付索引](docs/design/exec/版本交付-结果.md)维护。固定包部署、Steam 工坊上传与全部语言正文同步可使用 `v3 publish`；参数和平台范围见[发布指南](docs/publishing/README.md)。

安装时将 ZIP 解压到 `Paradox Interactive/Victoria 3/mod/Situated AI`，在启动器中登记并启用独立 playset；不要覆盖游戏本体。游戏文本只在打包边界使用 UTF-8 BOM，仓库源统一 UTF-8 无 BOM、LF。

## 验证边界

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py test-offline
```

完整矩阵、性能口径、清理和 Git 流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。静态检查、快照和模拟只能证明明确覆盖的工程合同。引擎运行期语义、AI 行为质量、平衡和长期性能需要用户在固定包上验收；工程通过不能代替这些结论。日志、存档和观察器提供辅助证据，其摘要不能单独证明这些结果。

## 许可证

[Apache-2.0](LICENSE)
