# Situated AI 项目代理指南

本文件是仓库级执行入口，适用于整个 Situated AI 仓库。它只说明任务路由、修改边界和容易误判的事项；完整贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。用户、系统和开发者指令优先于本文件，子目录若有更窄作用域的 AGENTS.md，按路径作用域补充本文件。

仓库中没有 CONTRIBUTE.md；实际贡献文件是 CONTRIBUTING.md。不要为了匹配别名再创建第二份贡献指南。

## 权威层级

同一问题只保留一个当前来源，其他文件只链接和摘要：

| 问题 | 权威入口 | 维护内容 |
|---|---|---|
| 代理如何定位和修改 | 本文件 | 任务路由、范围、边界和接手顺序 |
| 如何贡献、验证、提交和合并 | [CONTRIBUTING.md](CONTRIBUTING.md) | 工作流、验证矩阵、性能测量、分支与 Git |
| 工程持续约束 | [工程原则](docs/principles/工程原则.md) | 正确性、跨平台、编码、依赖、测试、性能、清理和文档 |
| Mod 持续约束 | [Mod 开发原则](docs/principles/Mod开发原则.md) | 产品目标、机制边界、公平性、运行效率和发布边界 |
| 工具与证据契约 | [工程基线 1.0](docs/design/exec/工程基线-1.0.md) | 测试层级、快照、实机、恢复和证据口径 |
| 产品顺序与阶段出口 | [Mod 全目标实现优先与集中验证计划 5.0](docs/design/exec/mod重设计-实施计划.md) | F0–F2、V0.1–V0.7/V1.0、M1–M4、重开条件和可玩交付 |
| 当前状态与下一动作 | [当前工作清单](docs/design/当前工作清单.md) | 当前事实、队列、阻塞和下一步 |
| 实测、失败和原始边界 | 对应结果页、审计和报告 | 日期、输入、命令、结果、限制和恢复证据 |

原则页只写持续约束；计划页只写产品顺序和出口；结果页写事实；导航页只写链接。发现冲突时，先按上述层级核对，不在摘要页另建规则。

## 接手顺序与任务路由

开始任何非只读任务前，按以下顺序读取：

1. git status --short --branch、相关已有改动和适用的规则文件；
2. [CONTRIBUTING.md](CONTRIBUTING.md) 中与任务类型对应的章节；
3. [工程原则](docs/principles/工程原则.md)和 [Mod 开发原则](docs/principles/Mod开发原则.md)；
4. [工程基线](docs/design/exec/工程基线-1.0.md)、主计划和当前工作清单；
5. 只有需要历史事实时才读取结果页、审计、报告和 backlog。

| 任务 | 首选入口 | 必须保持的边界 |
|---|---|---|
| 可复用 Python | src/pdx/，测试在 tests/ | 使用项目 .venv、显式 UTF-8/LF、跨 Windows/macOS/Linux |
| 生产 Mod | mod/decisions/*.toml、src/pdx/decisions.py | 改源和生成器后运行 v3 modgen --write、v3 modgen --check，不手改生成物 |
| 历史实验 Mod | mod/data/*.toml、src/pdx/modgen.py | 只生成到 mod/legacy/，不进入生产包 |
| 检查、基准和探针 | tools/ci/、tools/benchmarks/、tools/probe/ | 复用现有 CLI 和 pdx.game_run，一次性脚本写入忽略的输出目录 |
| 生成文档和机械表格 | 对应 CLI、pdx.doc_tables | 修改来源后重新生成并检查，不手改数字或指纹 |
| 快照、交付和证据 | tools/out/ | 绝大多数是可再生或本机证据；精简快照和逐件声明的例外按 .gitignore 入库 |
| 官方资料 | research/official-docs.manifest.json | 本地原文镜像不入库，保留来源和指纹 |

删除、改名或改变忽略规则前，使用 Python 盘点调用方、动态注册、CLI、测试、生成入口和证据引用；忽略状态本身不能证明内容可以删除。

## 通用执行规则

- 正确性第一、速度第二、内存第三，同时适用于工程和 Mod。速度或内存优化必须在相同正确性、输出和证据契约下用可重复测量确认。
- 优先使用仓库已有 .venv 和成熟库；文本、路径、批量盘点、生成和验证优先用 Python。不要依赖 shell 默认编码或本机绝对路径。
- 受控文本为 UTF-8 无 BOM、LF；游戏脚本和本地化只在安装/打包边界添加 BOM。原始游戏文件、第三方镜像、日志和冻结证据按各自字节契约保留。
- Mod 本地化语言集合必须来自当前锁定游戏版本的实际本地化目录或对应精简快照；生产生成器为每种本体语言生成全部自有键，并校验语言头、目录、文件名、键集合和占位符一致。实验包可明确记录英语回退，正式发布前必须完成各语言文本审校并清空回退列表；GUI 自动化模板覆盖与 Mod 本地化覆盖分别记录。
- 完整测试默认 -n auto --dist loadscope，worker 数由 CPU 与内存预算决定；性能基准必须清除普通测试参数并串行运行。测试通过、快照一致、脚本加载成功或评分变化都不能单独证明 Mod 行为质量。
- Windows、macOS、Linux 的代码、CI、无头测试和 GUI 实机证据分开申报。当前 GUI 自动化实机支持范围以工程基线为准，未运行的层级必须写成未验证。
- 实机只使用现有 pdx.game_run 的互斥、部署、日志、归档和恢复流程；游戏进程、存档、挂载和恢复指针未核对干净时，不启动下一次实验。
- 实验账本的停止条件、错误分类和原始输入不可通过改名、改探针、增加预算、清账本或拼接不同会话绕过。遇到外部阻塞，完成不依赖它的离线工作并记录证据限制。

## 验证与交付

从仓库根目录使用对应平台的 .venv 入口。下面的命令文本只表达 Python/CLI 调用，不依赖特定 shell：

| 平台 | Python 入口 |
|---|---|
| Windows | .venv\Scripts\python.exe -X utf8 tools/ci/run_check.py <检查> |
| macOS/Linux | .venv/bin/python -X utf8 tools/ci/run_check.py <检查> |

可替换的检查包括 encoding、lint .、format --check .、types、test、test-offline、deadcode 和 baseline。具体选择、跳过分类、性能口径、实机矩阵和 Git 交付按 [CONTRIBUTING.md](CONTRIBUTING.md) 执行。

代码、规则、结构、生成物或兼容范围变更默认使用短期 codex/<topic> 分支和 PR；提交标题和说明使用中文。合并后核对本地/远端 main、工作区、树等价和必要证据，再删除短期分支。推送、合并和删除远端分支在任务已授权时直接完成；不得强制推送 main。

最终报告必须分别说明：实际修改、实际运行的检查、跳过和失败、实机/快照/模拟/推断的边界、提交/推送/合并状态，以及仍未完成的产品出口。不能把工程收口写成 V0.1 或整个 Mod 完成。
