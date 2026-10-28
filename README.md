# Situated AI

[![CI](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/ci.yml)
[![CodeQL](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml/badge.svg)](https://github.com/AomaYple/Situated-AI/actions/workflows/codeql.yml)

Victoria 3 AI Mod 与 Python 开发工具链。项目目标是让每个国家基于自身处境和可观测信息，在原版机制内持续做出符合自身约束与利益的相对最优决策。

当前工程交付候选为 `Situated AI 1.3.0`，底本为 Victoria 3 `1.14.5`，Mod ID 为 `situated-ai`。它包含有限国家状态、六条动态路线、影子预算、TTL/冷却和原版消费者适配。终极方案 4.0 的 E0–E15 已达到静态工程出口；长期行为、平衡、后期性能、本地化呈现和 Workshop 体验由用户在固定包上验收。

## 先读什么

1. [AGENTS.md](AGENTS.md)：代理接手顺序和修改边界。
2. [CONTRIBUTING.md](CONTRIBUTING.md)：生成、检查、分支、提交、PR 和发布。
3. [工程原则](docs/principles/工程原则.md)与[Mod 开发原则](docs/principles/Mod开发原则.md)。
4. [终极方案 4.0 实施计划](docs/design/exec/mod重设计-实施计划.md)与[当前工作清单](docs/design/当前工作清单.md)。

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
.venv\Scripts\python.exe -X utf8 -m pdx.cli package --output dist/situated-ai-1.3.0.zip
```

macOS/Linux 将解释器替换为 `.venv/bin/python`。没有游戏时仍可运行离线检查；有游戏时可用 `V3_ROOT`、`V3_USERDIR` 指定路径。生成和正式打包要求锁定原版底本，底本缺失或漂移时硬失败。

## 标准包

`1.3.0` 是当前工程交付候选。包包含标准 metadata、生成的 `common/`、11 种本体语言、封面、manifest 和安装说明；本轮包为 65 个条目，SHA-256 为 `7ece8f08d8aac3ce5dde070556925bbb839f5ccefa760df39840705eb5df1cad`。包不包含 Python、探针、日志、缓存、快照、报告、原始底本或历史实验。版本标签、包哈希和 GitHub Release 状态见[版本交付索引](docs/design/exec/版本交付-结果.md)；Workshop 页面由发布者在固定包上单独验收和发布。

安装时将 ZIP 解压到 `Paradox Interactive/Victoria 3/mod/Situated AI`，在启动器中登记并启用独立 playset；不要覆盖游戏本体。游戏文本只在打包边界使用 UTF-8 BOM，仓库源统一 UTF-8 无 BOM、LF。

## 验证边界

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py test-offline
```

完整矩阵、性能口径、清理和 Git 流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。静态检查、快照和模拟只能证明明确覆盖的工程合同；工程通过不能代替这些结论，日志、存档和观察器是用户长期验证的辅助证据，不自动证明引擎运行期语义、AI 行为质量或长期性能。

## 许可证

[Apache-2.0](LICENSE)
