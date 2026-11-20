# 工具目录

工具目录汇集检查、基准、静态分析、快照和本机诊断入口。环境、验证和发布的完整步骤见[贡献指南](../CONTRIBUTING.md)，文档生成入口见[生成文档维护](../docs/README.md#生成文档维护)。

产品接口的实施顺序见[架构主计划](../docs/design/架构主计划.md)和[架构子计划](../docs/design/架构子计划.md)。

## 当前入口

| 路径/命令 | 用途 |
|---|---|
| `tools/ci/run_check.py` | 统一调用 encoding、hygiene、lint、format、types、test、test-offline、full-acceptance、offline、decision-audit、baseline-offline、baseline、deadcode、python-package |
| `tools/ci/repo_hygiene.py` | 检查物理残留及被仓库忽略规则命中的已跟踪路径。`--clean` 预览，追加 `--apply` 执行白名单清理，保留已跟踪内容 |
| `tools/ci/python_package.py` | 在临时源码副本中构建 wheel，核对源码模块集合、字节、ZIP 重复条目与完整性，并拒绝允许清单之外的条目 |
| `tools/ci/deadcode_audit.py` | AST 级零引用候选审计；动态入口需人工复核 |
| `tools/ci/test_suite.py` | 最终候选的完整 Python 回归、覆盖率、JUnit、测试身份与资源报告；统一入口为 `run_check.py full-acceptance --quiet` |
| `tools/ci/test_summary.py` | 汇总 pytest JUnit XML 并给 skipped 测试分配工程类别；未知或空的跳过原因返回退出码 2 |
| [CI 基准摘要](ci/bench_summary.py) | 把 pytest-benchmark JSON 汇总成 Markdown，默认输出到 stdout。`--github-step-summary` 为 CI 追加摘要。 |
| `tools/ci/mem_baseline.py` | 并行测试内存基线：整套峰值、每 worker 峰值和总耗时，输出写入忽略的 `tools/out/mem/` |
| `tools/ci/architecture_witness_capture.py` | 串行 pytest 插件，按声明采集当前生产 PDX 见证，核对生产生成锁和现行原版输入，写入结果与草稿行 |
| `python -m tools.ci.r2_profile_budget` | 从锁定安装构建当前生产候选并核对 R2 叠加层的编译、读取和遍历预算，超限返回失败 |
| `tools/benchmarks/` | Python 解析、生成和资源基准；固定输入、串行运行，不代表游戏内性能 |
| `tools/benchmarks/profile_suite.py` | pytest cProfile 插件：每个 worker 独立落盘，按模块汇总函数自身耗时；分析有额外开销，不能代替墙钟/RSS 基线 |
| `tools/prof/prof_e2e.py` | 全量分析端到端性能剖析（`full`、`stages`、`walkaudit`、`prefixaudit`），会重跑分析流水线 |
| `src/pdx/` | CLI、全量静态分析、快照、Mod 生成、字段门禁和 ZIP 交付实现 |
| `tools/save_archive.py` | 后台按游戏日期归档稳定的 Victoria 3 自动存档；只读，不控制游戏 |

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

## 输出和边界

`tools/out/`、`dist/`、缓存、日志和基准原件是可再生或机器相关输出，默认忽略。受控快照是
`tools/out/snapshots/release-1.15.2.compact.json`。旧版快照、诊断工具和阶段证据可从提交
[b3c3356e](https://github.com/AomaYple/Situated-AI/commit/b3c3356e61b7c080038f7d6a61b84d69aedc58d3) 按原路径查阅。
需要留档的审计结果应在结果页说明来源、SHA-256、日期和限制。工程测试、静态快照、包校验和脚本加载
不能证明 AI 行为质量、长期性能、平衡、玩家体验或创意工坊结果；这些由用户安装标准包后验收。

## CLI 分层

- 普通 `v3 analyze` 生成现场概览。完整安装和已提交原件的只读研究入口见[贡献指南](../CONTRIBUTING.md#完整安装研究)。查询已生成研究目录的方式见[研究目录查询](../CONTRIBUTING.md#查询研究目录)。`v3 snapshot` 用于生成可核验的版本快照。
- `v3 modgen`、`modguard`：生成并检查仓库生产产物、锁定原版字段和生成一致性。
- `python -m pdx.cli package`、`pdx.distribution.validate_package`：按生产源版本生成并核对标准 ZIP 和 manifest；标签、Release 和包哈希见
  [版本交付索引](../docs/design/exec/版本交付-结果.md)，候选与部署事实见[当前工作清单](../docs/design/当前工作清单.md)。命令成功不能证明已发布或已部署。
- `v3 verify --from-snapshot` 和 `v3 tables --offline` 可在无游戏环境核对快照断言与文档。`v3 citations <路径...>` 读取本机游戏文件。

`modguard --offline` 通过 `mod/generation-lock.json` 核对冻结源码/产物原始字节，再审计脚本语法与快照接口；
`modgen --write/--check` 和 `package` 始终需要锁定原版。无游戏 CI 不执行原版重生成，也不会回退打包旧产物。

## 已知边界

工具能够回答的问题包括：锁定游戏文件中的静态字段、脚本值读取器、路径、AI 消费者、语言目录和文件级结构；
还可以核对项目生成源是否只使用快照或当前本机原版中存在的接口。

静态分析不能回答引擎内部未暴露状态、脚本运行期语义、国家长期行为、平衡、游戏内性能或玩家体验。
历史阶段收据、冻结快照和必要的原始证据按各自契约保留；它们不改变当前规则、计划或生产包。
