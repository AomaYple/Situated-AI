# 2026-10-02 工程收口记录

本轮针对 Situated AI mod 的工程收口围绕四个边界展开：实机失败可回收、分析结果可解释、快照可验证、测试与 CI 可复现。

## 已落地

- 游戏自动化在 launch() 记录本次 Popen 的根 PID；run_session() 失败时只终止本次进程及其子进程，保留显式清理全部同名进程的旧接口。
- flow_with_cleanup.py 先校验速度坐标，再启动游戏；收尾步骤逐项隔离，任一清理失败都会进入失败摘要，且正常路径使用本次会话的进程所有权。
- 阶段六探针的收尾、早退和部署前异常都有恢复兜底：恢复 SHOT_DIR、前台、内容加载配置，并保留原始异常。
- 全量分析在缺少 game/common 时输出可诊断的解析错误；交叉分析区分原版文件计数与涉及 mod 数，解析失败不再静默丢失，新增键不再伪装成“改动的原版条目”。
- 快照加载严格校验版本和值类型；完整与精简快照禁止直接比较；普通域保留重复项的计数差异。
- 性能基准分片改为读取根 tests/，新增回归用例确保每个分片都有真实测试文件。
- 生成器只删除带生成器头标记的过期 sitai_ 文件，避免误删用户自有的同前缀文件。
- CI 增加手工触发入口和性能分片编排器回归，打包注释与实际 src/ 布局一致。

## 验证记录

- python tools/ci/run_check.py encoding：UTF-8 无 BOM + LF 通过。
- python -m ruff check .：通过。
- python -m ruff format --check：160 个文件通过。
- python -m mypy：157 个源文件通过。
- 关键回归：自动化 15 项、阶段六 99 项、快照 11 项、性能分片 1 项、生成器 80 项、全量分析 42 项均通过。
- 全量 pytest -q 已启动，结果以本次提交前的最终日志为准；实机 GUI 仍以 Windows 证据为准，macOS/Linux 只验证日志与无 GUI 能力。

## 仍需区分的证据等级

CI 的三平台矩阵负责跨平台静态、单元和离线快照验证；当前环境没有 macOS/Linux 实机 GUI，因此不能把它们描述为真实窗口自动化通过。Windows 实机的长时间运行、官方成绩单等待和阶段六取证必须保留原始截图、日志与摘要，超时或人工中断都只能记为未完成，不能改写成通过。

## 2026-10-02 追加收口：性能对照探针

- `tools/probe/perf_compare.py` 已加入 `PerfCleanup`：运行前同名本地 mod 先移入临时隔离区，收尾时逐项恢复；配置文件使用临时文件 + `os.replace` 原子还原。
- 收尾只调用 `game_auto.kill_owned_game()`，不会误杀用户另开的 Victoria 3。
- 正常返回、异常、`atexit`、Ctrl+C、SIGTERM 和 Windows SIGBREAK 共用同一条幂等收尾路径；收尾状态写入 `tools/out/perf/cleanup.json`。
- 新增 `tests/test_perf_compare.py`，覆盖同名目录恢复、单项收尾失败隔离、信号处理器行为。
- 明确限制：`SIGKILL`、Windows `TerminateProcess` 等操作系统级强杀无法执行 Python 清理。

本追加的回归测试：`tests/test_perf_compare.py` 3 passed。
