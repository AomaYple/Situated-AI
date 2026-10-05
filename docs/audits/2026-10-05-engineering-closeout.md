# 工程收尾复核（2026-10-05）

本次复核只验收仓库工程链条，不推进新的 Victoria 3 行为实验。所有命令均使用仓库 `.venv/Scripts/python.exe`，工作树在开始和结束时均保持干净。

## 通过的门禁

短门禁通过：

- `ruff check .`；
- `ruff format --check .`（327 个文件）；
- `mypy`（185 个源文件）；
- `tools/ci/run_check.py encoding`（文本 UTF-8 无 BOM、LF）；
- 重点回归测试 123 项（`test_repo_numbers`、扩展观测、比较器、游戏运行器和市场比较）。

完整默认并行测试由 `tools/probe/mem_baseline.py` 记录，证据索引为 [`20261005-engineering-closeout-auto.json`](../../tools/out/mem/20261005-engineering-closeout-auto.json)；原始摘要为 [`20261005-engineering-closeout-auto.summary.json`](../../tools/out/mem/20261005-engineering-closeout-auto.summary.json)。结果如下：

| 项目 | 结果 |
|---|---:|
| 用例 | 2463 passed，10 skipped，1501 subtests passed |
| 退出码 | 0 |
| 墙钟 | 625.2 秒 |
| `-n auto` 实际 worker | 3 |
| 进程树 RSS 采样峰值 | 2785.8 MiB |
| worker 高水位峰值 | 1336.1 MiB |
| worker 高水位和（错峰上界） | 4599.3 MiB |
| 看门狗中止 | 否 |

`auto` 的 3 个 worker 是本机内存护栏依据启动时可用内存动态计算的结果，不是把 `auto` 偷换成固定的 3。测试机为 Windows、Python 3.14.7、16 个逻辑 CPU、约 16 GiB 物理内存；启动时可用内存约 6878 MiB。完整日志为 [`20261005-engineering-closeout-auto.log`](../../tools/out/mem/20261005-engineering-closeout-auto.log)，进程采样为同名前缀的 `.samples.csv` 和 `.procs.csv`。

覆盖率运行同一套 2473 个可收集用例，结果为 `2463 passed, 10 skipped, 1501 subtests passed`，墙钟 588.04 秒。报告为 [`coverage-20261005-engineering-closeout.json`](../../tools/out/coverage/coverage-20261005-engineering-closeout.json)，HTML 在 `tools/out/coverage/`：

- 分支感知总覆盖率：88.8638%（门槛 86%）；
- 语句覆盖率：90.8291%；
- 分支覆盖率：83.0080%。

全局门槛通过，但 `cli.py`、`experiments.py`、`game_auto.py`、`game_run.py`、`objectives.py`、`preflight.py` 和 `ai_surface.py` 的单模块覆盖率仍低于 86%。它们主要包含真实游戏、命令行异常和外部环境分支，后续可作为覆盖率专项，不在本次收尾中用模拟路径冒充实机覆盖。

10 个跳过项全部有明确原因：3 项是 Windows 未授予符号链接权限，7 项是本机没有可用的 Victoria 3 引擎日志目录。它们不计为失败，也不计为对应平台或引擎行为已验证。

## 离线基线

`.venv/Scripts/python.exe tools/ci/run_check.py baseline` 通过，包含：

- `pip check` 无依赖冲突；
- 离线快照核验 43/43；
- 174 张生成表与文档一致；
- 生产 5 个、legacy 69 个产物与数据源逐字节一致；
- modguard 生产和 legacy 五道闸门通过；
- AI surface 与文档一致；
- 976 条 citations 均有入库支撑；
- AST 死代码审计通过（2116 个定义，无未分类候选阻断）；
- release 清单、档案和元数据版本一致。

modguard 离线模式仍明确标记 2 项原版路径检查未被精简快照覆盖：`common/game_rules/` 和 `common/on_actions/` 下对应路径。它们不计为离线通过，仍需真实游戏原版真值；这属于证据边界，不是工程测试失败。

## 收尾结论

当前仓库工程门禁已经完成一轮可复核收口：代码质量、编码、类型、完整默认并行测试、覆盖率、离线分析、生成物、死代码和发布清单均有新的证据。后续仍应单独处理真实游戏行为质量、1900 年后长局、旧存档迁移和 macOS/Linux GUI 实机；这些不属于本次工程收尾的通过项。
