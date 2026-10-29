# 工具目录

这里保存可复现的工程检查、基准、静态分析、快照和一次性输出约定。游戏长期行为、压力长跑和 GUI 自动化不属于
当前工程交付链；日志分析、快照核对和最小复现辅助仍可用于处理用户反馈。发布包不包含 Python 工具、日志或
历史实验。

## 当前入口

| 路径/命令 | 用途 |
|---|---|
| `tools/ci/run_check.py` | 统一调用 encoding、hygiene、lint、format、types、test、test-offline、baseline、deadcode |
| `tools/ci/repo_hygiene.py` | 检查根目录可再生缓存、字节码和运行态目录 |
| `tools/ci/deadcode_audit.py` | AST 级零引用候选审计；动态入口需人工复核 |
| `tools/ci/test_suite.py` | 可选的完整 Python 回归、覆盖率、JUnit 和资源报告 |
| `tools/benchmarks/` | Python 解析、生成和资源基准；固定输入、串行运行，不代表游戏内性能 |
| `src/pdx/` | CLI、全量静态分析、快照、Mod 生成、字段门禁和 ZIP 交付实现 |
| `tools/save_archive.py` | 后台按游戏日期归档稳定的 Victoria 3 自动存档；只读，不控制游戏 |

`src/pdx/observe.py`、`src/pdx/savegame.py` 及 CLI 观察入口用于只读分析用户提供的日志和存档；
它们属于工程辅助能力，不进入标准 Mod 包，也不把日志或存档摘要升级为 AI 行为质量结论。

### 按游戏日期归档存档

需要离开电脑时，可以让 `tools/save_archive.py` 监视游戏用户目录。它从存档头读取
`game_date`，在目标日期附近选择最近的月份；只有文件连续稳定后才复制，并对副本做大小和
SHA-256 校验。它不会启动、暂停、加速或向游戏窗口发送输入，也不能补回游戏尚未产生的存档。

```text
.venv\Scripts\python.exe -X utf8 -B tools/save_archive.py --userdir "游戏用户目录" --output tools/out/save-archive/session --target 1856.1.1 --target 1876.1.1 --target 1896.1.1 --target 1916.1.1 --target 1936.1.1
```

使用尚不存在的新输出目录；工具拒绝覆盖已有输出，也拒绝把归档写入游戏用户目录或云存档目录。
默认从最新稳定本地 `autosave` 识别 `playthrough_id`，随后只接受同一局的文本存档。
仅监视云目录时需显式传 `--playthrough-id`。`--window-months` 设置允许的月份距离，默认 12；
精确日期立即完成，临近候选在窗口结束或游戏退出后的最后一次稳定读取后确定，并如实记录实际日期。
可加 `--pid <游戏进程编号>`，使程序在该游戏进程退出后收尾；不传时持续运行到目标完成或手动停止。

对格式为 Steam 云存档压缩包、但日期已由用户确认的开局档，可用
`--target 1836.1.1 --baseline "1836.1.1=路径"` 原样复制；该日期以用户指定为依据，
不会伪装成已解析压缩存档。状态和事件写入输出目录的 `status.json` 与
`events.jsonl`。需要同时读取 Steam 云存档时，显式添加一个或多个
`--cloud-dir ".../529340/remote/save games"`；工具不会修改云存档目录。macOS/Linux
将解释器替换为 `.venv/bin/python`，并使用对应平台的用户目录。
文件稳定和副本哈希只证明归档复制过程，不能替代游戏内读档验证；本工具不主动请求游戏保存。

## 常用命令

Windows：

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py encoding
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py hygiene
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline
.venv\Scripts\python.exe -X utf8 -m pdx.cli modgen --check
.venv\Scripts\python.exe -X utf8 -m pdx.cli modguard --offline
.venv\Scripts\python.exe -X utf8 -m pdx.cli package
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
- `v3 package`、`pdx.distribution.validate_package`：按生产源版本生成标准 ZIP 和 manifest。本轮由
  `Situated AI 1.4.0` 升级至 `1.5.0`，标准包、标签和 Pre-release 已交付；阶段与交付状态见
  [分层联动实施计划](../docs/design/exec/mod重设计-实施计划.md)、[当前工作清单](../docs/design/当前工作清单.md)和
  [分层联动执行结果](../docs/design/exec/分层联动-执行结果.md)，不可由命令成功推断已发布。
- `v3 verify`、`tables --offline`：无游戏环境的快照与文档检查。`v3 citations <路径...>` 需要本机游戏文件。

`modguard --offline` 通过 `mod/generation-lock.json` 核对冻结源码/产物原始字节，再审计脚本语法与快照接口；
`modgen --write/--check` 和 `package` 始终需要锁定原版。无游戏 CI 不执行原版重生成，也不会回退打包旧产物。

## 已知边界

工具能够回答的问题包括：锁定游戏文件中的静态字段、脚本值读取器、路径、AI 消费者、语言目录和文件级结构；
还可以核对项目生成源是否只使用快照或当前本机原版中存在的接口。

静态分析不能回答引擎内部未暴露状态、脚本运行期语义、国家长期行为、平衡、游戏内性能或玩家体验。这些由用户
在标准生产包上验收。当前 CLI 已交付 `observe` 命令；观察报告仍只能作为带证据分类的辅助材料。
历史阶段收据、冻结快照和必要的原始证据按各自契约保留；它们不改变当前规则、计划或生产包。
