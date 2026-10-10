# 项目代理指南

本文件适用于整个 Situated AI 仓库，补充通用协作原则。详细贡献流程与工程约定见 [CONTRIBUTING.md](CONTRIBUTING.md)；开始修改前读取与本次任务相关的章节。

## 原则分层

- [工程原则](docs/principles/工程原则.md)定义工程底线；[CONTRIBUTING.md](CONTRIBUTING.md)维护具体贡献流程，[工程基线](docs/design/exec/工程基线-1.0.md)维护工具与验证契约。
- [Mod 开发原则](docs/principles/Mod开发原则.md)定义产品底线；[处境决策设计](docs/design/03-处境决策设计.md)维护架构，[最终执行纲领](docs/design/exec/mod重设计-实施计划.md)维护阶段出口。
- 两类原则共同要求正确性第一、速度第二；在保持正确性与证据完整性的前提下，优化开发、验证和游戏运行效率。流程、设计和计划落实这些约束，性能结论由对应测量验收。
- 原则页只维护持续约束，结果页管理实测和阻塞；导航页不重复定义规则。文档分类与更新规则见 [文档维护](docs/README.md#文档维护)。

全仓规范按维护时最新且适用的现代 Python 仓库最佳实践持续更新；目录、元数据、配置与迁移的落实方式见 [现代 Python 仓库维护](CONTRIBUTING.md#现代-python-仓库维护)。

## 先定位任务

本项目用 Python 分析、生成和验证 Victoria 3 Mod；游戏运行使用生成的游戏脚本，不依赖外部 Python 服务。

- Mod 目标与行为边界：[处境决策设计](docs/design/03-处境决策设计.md)。
- 制作顺序与阶段验收：[最终执行纲领](docs/design/exec/mod重设计-实施计划.md)；当前进展查看对应结果页及 [backlog](docs/design/backlog.md)。
- 工具链与证据边界：[工程基线](docs/design/exec/工程基线-1.0.md)；命令细节见 [工具手册](tools/README.md)。
- 性能任务：工具与开发流程使用 [速度优化计划](docs/design/exec/速度优化计划-正确性优先.md)；游戏运行效率按 [Mod 效率要求](docs/principles/Mod开发原则.md#开发与运行效率)和 M4 实机出口验证。

历史交接、台账与旧报告用于核对当时事实，不替代当前设计、验收条件或本次任务授权。

## 找到正确的修改入口

| 内容 | 修改入口与边界 |
|---|---|
| 可复用 Python 实现 | `src/pdx/`；测试放在 `tests/` |
| 生产 Mod | 当前固定数据入口为 `mod/decisions/fiscal.toml`、`mod/decisions/extensions.toml`，生成器为 `src/pdx/decisions.py`；新增定义须接入生成器，根级游戏产物由生成器维护 |
| 历史实验 Mod | `mod/data/*.toml` 与 `src/pdx/modgen.py`；只生成到 `mod/legacy/`，不进入生产包 |
| 检查、性能与实机探针 | `tools/ci/`、`tools/benchmarks/`、`tools/probe/`；优先扩展已有入口 |
| 生成文档 | 可执行面由对应 CLI 生成，知识库机械表格由 `pdx.doc_tables` 维护；不要手改 |
| 快照、输出与原始证据 | `tools/out/`；忽略规则中的精简快照例外须保留 |
| 官方资料 | `research/official-docs.manifest.json` 入库，本地 `research/official-docs/` 原文镜像不入库 |

改动数据源或生成器后运行 `v3 modgen --write`，再运行 `v3 modgen --check`；使用本工作区的虚拟环境入口。不要以手改生成物、更新黄金指纹或降低门槛掩盖不一致。删除、改名或调整忽略规则前核对消费者、生成入口和证据引用。

## 运行与检查

优先使用本工作区已有的 `.venv`，不依赖激活脚本。Python 工具链须兼容 Windows、macOS、Linux；文件盘点、文本处理和批量操作优先用 Python。shell 可以用于启动命令，不能让其默认编码决定文件字节。

| 平台 | 检查入口示例 |
|---|---|
| Windows | `.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py encoding` |
| macOS / Linux | `.venv/bin/python -X utf8 tools/ci/run_check.py encoding` |

将示例末尾的 `encoding` 替换为 `lint .`、`format --check .`、`types`、`test`、`test-offline`、`deadcode` 或 `baseline`。检查选择见 [验证矩阵](CONTRIBUTING.md#验证矩阵)，不要把会写盘的 `format` 当作只读检查。

- 文档改动：检查编码、链接、命令与事实一致性；生成内容执行对应生成检查。
- Python 改动：执行相关测试及适用的静态检查；广泛改动、阶段验收和交付前执行完整回归。
- Mod 数据、生成或交付改动：执行生成一致性、离线基线和相关测试；运行期行为必须另有实机验收。
- 完整 pytest 默认使用 `-n auto --dist loadscope`，worker 数由 CPU 与内存预算控制。测试写入独立临时目录；性能基准串行运行并清除普通 `addopts`。
- 覆盖率与核心模块下限以 `pyproject.toml`、`pdx.covgate` 为准。性能变化测速度与峰值内存，不能把普通并行测试当作有效基准。

## 容易误判的边界

- 仓库受控文本为 UTF-8 无 BOM、LF；游戏脚本与本地化的 BOM 只由安装、打包边界添加。原始证据按字节契约保留，规范化使用可恢复副本。
- 游戏位置通过 `V3_ROOT`、`V3_USERDIR`、`V3_WORKSHOP` 配置；不要新增本机绝对路径或本地路径配置文件。
- 离线快照证明与记录输入一致，读取游戏文件的集成测试也不等于启动游戏。GUI 自动化当前支持 Windows；其他平台不得标记为已实机验证。
- 实机使用现有 `pdx.game_run` 互斥与恢复流程；参数、输入指纹、时间窗口、日志和清理结果进入证据链。不得用另一个独立流程争用游戏、存档或挂载状态。
- Mod 通过真实处境与原版 AI 接口影响选择；不以免费资源、暴力削弱、强制行动或固定国家剧本制造效果。评分通道、脚本强制机会和加载成功不等于 AI 行为质量。
- 提交标题与说明使用中文，按完整目的组织变更；具体要求见 [提交规范](CONTRIBUTING.md#提交前与提交信息)。收尾说明实际修改、验证、跳过项和证据限制。
