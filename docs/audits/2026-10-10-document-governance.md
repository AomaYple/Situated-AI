# 2026-10-10 文档权威层级与治理记录

## 目标

本轮在拆分工程原则与 Mod 开发原则的同时，重新整理全仓文档入口。重点是让新贡献者能从一条路径找到当前规则、设计、计划、结果和历史证据，并避免历史收尾记录被误读为当前状态。

## 盘点范围

- 修改前 Git 跟踪文档为 216 个：214 篇 Markdown（其中 docs/ 195 篇）和 docs/ 下 2 份历史任务清单文本；本轮新增 6 篇 Markdown，整理后受控 Markdown 合计 220 篇（其中 docs/ 201 篇）；
- 受控文档统计排除 .git/、.venv/、tools/out/ 和本地 research/official-docs/ 原文镜像；
- 路径盘点使用 Git 的 NUL 分隔输出，避免中文路径转义影响计数；链接扫描覆盖全部受控 Markdown，不混入缓存和忽略文件；
- 受控文档逐字节检查 UTF-8、BOM、CRLF 和末尾换行；
- 对删除、移动和重命名候选执行 Git 跟踪、引用和生成入口核对。

## 当前权威层级

| 层级 | 文档 | 责任 |
|---|---|---|
| 工程原则 | docs/principles/工程原则.md、CONTRIBUTING.md、docs/design/exec/工程基线-1.0.md | 工程底线、流程、验证和证据 |
| Mod 原则 | docs/principles/Mod开发原则.md、docs/design/03-处境决策设计.md | 产品目标、架构、机制边界和验收层级 |
| 当前计划 | docs/design/exec/mod重设计-实施计划.md | M0–M5 顺序、出口、重开条件和发布边界 |
| 当前状态 | docs/design/当前工作清单.md、M1–M5 结果页、docs/design/backlog.md | 实测、阻塞、触发条件和历史编号 |
| 导航 | 根 README、docs/README.md、各目录 README、tools/README.md | 链接和摘要，不重复定义完整规则 |
| 历史证据 | docs/audits/、docs/reports/、旧阶段/交接记录 | 保留原输入、失败和判断，不能覆盖当前规则 |

## 本轮修改

- 新增 docs/principles/工程原则.md 和 docs/principles/Mod开发原则.md；
- 更新 AGENTS.md、CONTRIBUTING.md、根 README、docs/README.md、执行索引、报告索引和工具手册的职责说明；
- 新增当前工作清单和审计索引；
- 同步 `aggression=0` 的当前配置及生成行为，移除执行纲领中“尚未执行”的过时描述；
- 将执行索引拆成当前入口、状态读取顺序和历史文件清单；
- 将报告索引拆成当前入口、主题索引、使用规则和完整历史清单；
- 复核 7 个重点 Git 跟踪文档的字节状态；当前基线均已是 UTF-8 无 BOM、LF，内容和历史引用保持不变。这 7 份历史报告或探针说明没有末尾换行，`.editorconfig` 不强制为 Markdown 添加末尾换行，因此保留与 HEAD 相同的原始字节。治理输出保留盘点哈希；没有把并不存在的 CRLF 转换写成新改动；
- 未删除历史报告、第三方内容、官方原文镜像、原始证据或精简快照；它们均有消费者或字节契约。

## 验证

本轮已运行以下检查：

| 检查 | 结果 |
|---|---|
| `.venv/Scripts/python.exe -X utf8 tools/ci/run_check.py encoding` | 通过：仓库文本 UTF-8 无 BOM + LF |
| `.venv/Scripts/python.exe -X utf8 tools/ci/run_check.py format --check .` | 通过：`364 files already formatted` |
| CLI 文档、文档一致性、仓库卫生和工程契约定向测试 | 通过：`87 passed`；范围为 `tests/test_cli_docs.py`、`tests/test_docs_consistency.py`、`tests/test_repo_hygiene.py`、`tests/test_engineering_contract.py` |
| `.venv/Scripts/python.exe -X utf8 tools/ci/run_check.py baseline` | 通过：依赖检查、离线验证 `43 / 43`、174 张生成表、生产 5 个与 legacy 69 个产物、离线 modguard、AI surface、976 条引用、死代码审计及 release/档案/元数据一致性 |
| Python + `markdown_it` 扫描受控 Markdown 相对链接与图片目标（解码 URL 后解析） | 通过：220 篇 Markdown、477 个相对链接或图片目标、0 个缺失目标；仅核对目标路径存在性，标题锚点和命令语义另由人工复核与相关测试覆盖 |
| 受控文档字节盘点 | 通过：全部 220 篇 Markdown 为 UTF-8 无 BOM、LF；两份历史任务清单与仓库编码检查保持一致 |
| 工作区和暂存区 `git diff --check` | 通过；两份新原则页的末尾多余空行已清理 |

本轮只修改文档，采用上述定向测试和离线基线；未重新运行完整 pytest、覆盖率测量、性能基准或游戏实机。macOS/Linux GUI 仍无真实实机证据，Mod 行为质量也不因工程检查通过而自动宣告完成。
