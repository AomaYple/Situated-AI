# 工具目录

这里保存可复现的工程检查、基准和一次性输出约定。游戏长期行为、压力和 UI 自动化探针已经从当前交付链移除；
已停止的探针脚本、冻结实验和测试从当前源码移除；发布包不包含工具。

## 当前入口

| 路径/命令 | 用途 |
|---|---|
| `tools/ci/run_check.py` | 统一调用 encoding、hygiene、lint、format、types、test、test-offline、baseline、deadcode |
| `tools/ci/repo_hygiene.py` | 检查根目录可再生缓存、字节码和运行态目录 |
| `tools/ci/deadcode_audit.py` | AST 级零引用候选审计；动态入口需人工复核 |
| `tools/ci/test_suite.py` | 可选的完整 Python 回归、覆盖率、JUnit 和资源报告 |
| `tools/benchmarks/` | Python 解析、生成和资源基准；固定输入、串行运行，不代表游戏内性能 |
| `src/pdx/` | CLI、全量静态分析、快照、Mod 生成、字段门禁和 ZIP 交付实现 |

## 常用命令

Windows：

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py encoding
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py hygiene
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline
.venv\Scripts\python.exe -X utf8 -m pdx.cli modgen --check
.venv\Scripts\python.exe -X utf8 -m pdx.cli modguard --offline
.venv\Scripts\python.exe -X utf8 -m pdx.cli package --output dist/situated-ai-1.0.1.zip
```

macOS/Linux 将解释器替换为 `.venv/bin/python`。如果 `.venv` 尚未安装，按
[CONTRIBUTING.md](../CONTRIBUTING.md) 的依赖步骤安装；不要把虚拟环境或 `tools/out/` 加入 Git。

## 输出和边界

`tools/out/`、`dist/`、缓存、日志和基准原件是可再生或机器相关输出，默认忽略。需要留档的静态快照或审计结果
应复制为精简、可复核的文件，并在结果页说明来源、SHA-256、日期和限制。工程测试、静态快照、包校验和脚本加载
不能证明 AI 行为质量、长期性能、平衡、玩家体验或创意工坊结果；这些由用户安装标准包后验收。

## CLI 分层

- `v3 analyze`、`information-catalog`、`snapshot`：读取锁定游戏或快照，生成 mod 开发知识和版本差异。
- `v3 modgen`、`modguard`：生成并检查仓库生产产物、锁定原版字段和生成一致性。
- `v3 package`、`pdx.distribution.validate_package`：生成标准 `Situated AI 1.0.1` ZIP 和 manifest。
- `v3 verify`、`tables --offline`：无游戏环境的快照与文档检查。`v3 citations <路径...>` 需要本机游戏文件。

`modguard --offline` 通过 `mod/generation-lock.json` 核对冻结源码/产物原始字节，再审计脚本语法与快照接口；
`modgen --write/--check` 和 `package` 始终需要锁定原版。无游戏 CI 不执行原版重生成，也不会回退打包旧产物。

## 已知边界

工具能够回答的问题包括：锁定游戏文件中的静态字段、脚本值读取器、路径、AI 消费者、语言目录和文件级结构；
还可以核对项目生成源是否只使用快照或当前本机原版中存在的接口。

静态分析不能回答引擎内部未暴露状态、脚本运行期语义、国家长期行为、平衡、游戏内性能或玩家体验。这些由用户
在标准生产包上验收。历史证据和旧实验说明只在 Git 历史中保留，不改变当前规则。
