# Situated AI 项目代理指南

本文件是仓库级执行入口。它只保存长期有效的任务路由、边界和交付要求；完整贡献流程见
[CONTRIBUTING.md](CONTRIBUTING.md)，持续工程约束见[工程原则](docs/principles/工程原则.md)，产品约束见
[Mod 开发原则](docs/principles/Mod开发原则.md)。用户、系统和开发者指令优先于本文件；子目录若增加
更窄作用域的 `AGENTS.md`，按路径作用域补充本文件。

## 权威入口

| 问题 | 唯一当前来源 |
|---|---|
| 代理接手顺序、修改边界 | 本文件 |
| 贡献、验证、提交、推送和合并 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 跨项目工程约束 | 全局 `AGENTS.md` |
| 工程原则 | [工程原则](docs/principles/工程原则.md) |
| Mod 原则与运行边界 | [Mod 开发原则](docs/principles/Mod开发原则.md) |
| 游戏工具、快照和证据契约 | [工程交付基线](docs/design/exec/工程基线-1.0.md) |
| 当前产品计划和正式版出口 | [Situated AI 1.1.0 交付计划](docs/design/exec/mod重设计-实施计划.md) |
| 当前状态和下一动作 | [当前工作清单](docs/design/当前工作清单.md) |
| 当前事实与交付收据 | `docs/design/exec/*-结果.md`；更早的原始材料只在 Git 历史中保留 |

原则页只写持续约束，计划页只写顺序和出口，结果页只写事实，导航页只提供链接。发现冲突时先按
这张表核对，不在摘要页复制另一套规则。

## 接手顺序

开始非只读任务前：

1. 在目标工作树运行 `git status --short --branch`，检查已有改动、活动进程、部署指针和锁文件；保留不属于本任务的改动。
2. 读取本文件、`CONTRIBUTING.md`、两份原则、工程交付基线、主计划和当前工作清单。
3. 只有需要历史事实、失败因果或原始字节时，才读取结果页、审计、报告和 `research` 清单。

## 修改路由

| 任务 | 首选入口 | 约束 |
|---|---|---|
| Mod 源和生成 | `mod/decisions/*.toml`、`src/pdx/decisions.py`、`decision_rules.py`、`decision_adapters.py`、`distribution.py` | 不手改生成物；改源后运行 `v3 modgen --write`、`v3 modgen --check`，唯一生产包由 `v3 package` 生成 |
| 静态全量分析和快照 | `src/pdx/`、`v3 analyze`、`v3 information-catalog`、`v3 snapshot` | 只把可发现信息登记为能力；不可见的引擎状态保持 `unknown`/`unsupported` |
| 工程检查 | `tools/ci/run_check.py` | 使用仓库 `.venv`，不依赖 shell 激活；输出写入被忽略的 `tools/out/` |
| 文档和机械表格 | 对应 CLI、`pdx.doc_tables`、`pdx.docgen` | 修改来源后重新生成；不手改指纹、统计表和 manifest |
| 发布交付 | `src/pdx/distribution.py`、`dist/` | 标准包无探针、无 Python、无日志、无缓存和历史实验；ZIP 使用 POSIX 路径，游戏文本在打包边界加 BOM |
| 历史实验 | Git 历史；可再生输出在 `tools/out/` | 不进入工作树、当前计划、发布包或默认 CLI 路径 |

## 当前任务边界

本仓库当前交付目标是维护一个工程上可生成、可安装、可审计的 `Situated AI 1.1.0` 候选包，并持续扩展其 Mod 源；
各版本的冻结标签、标准包和 SHA-256 见[版本交付索引](docs/design/exec/版本交付-结果.md)，历史交付内容不改写。助手负责 Mod 开发、原版接口合法性、生成和静态工程验证。
自动化必须保证：使用锁定 Victoria 3 原版字段、触发器、效果、作用域和路径；生成器拒绝漂移、未知字段、
重复作者、非法路径和编码错误；包结构、manifest、哈希和本地化契约完整；生产包不含诊断探针。

长期实机行为、AI 平衡、长期性能、玩家体验、创意工坊发布和跨平台 GUI 由用户在交付包上验收，不能用
Python 测试、静态快照、脚本加载成功、评分变化或根 hook 记录冒充这些结论。用户提供日志、版本、启用 Mod 集和
最小复现后，助手可以用保留的日志解析器、快照和静态工具辅助定位。Windows/macOS/Linux 的 Python 工具链和
无头检查仍需保持可运行；长期 GUI/压力/行为自动化已退役，不是当前工程出口。

正确性第一、速度第二、内存第三，同时适用于工程和 Mod。性能改动必须有同口径可重复测量，不能牺牲
字段合法性、输出、回退或证据契约。优先使用仓库 `.venv` 和成熟 Python 库，路径、文本、批量盘点、
生成和验证优先使用 Python；受控文本为 UTF-8 无 BOM、LF，只有游戏交付边界按引擎要求添加 BOM。

## 删除、清理与提交

删除或改名之前，用 Python/`git grep` 核对调用方、动态注册、测试、CLI、生成入口、文档链接和历史证据。
缓存、运行态和可再生输出可清理；历史证据和第三方原始字节按其契约保留。清理必须同步内容、链接、
忽略规则和测试，不能只删除文件名。

代码、规则、生产数据和目录结构变更使用短期 `codex/<topic>` 分支和 PR；提交标题、正文和 PR 使用中文。
用户已授权的推送、PR、合并和分支清理可直接执行，禁止强制推送 `main`。最终报告分开说明修改、实际检查、
跳过/失败、实机边界、包路径与哈希、Git 状态以及仍由用户验收的范围。
