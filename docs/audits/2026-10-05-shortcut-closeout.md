# 快捷键自动化、输入漂移与 M2 工程收口

日期：2026-10-05

本轮在快捷键速度改造之后重新建立了工程基线，并补齐输入配置与财政生命周期的工程约束。Mod 的财政参数和生产脚本没有因为这轮工程改造而改变。

## 完整并行基线

命令：

```text
.venv\Scripts\python.exe -X utf8 tools\probe\mem_baseline.py run --groups auto --inproc --tag 20261005-shortcut-closeout-pass --quiet
```

结果：

| 指标 | 结果 |
|---|---:|
| 收集用例 | 2487 |
| 通过 / 跳过 | 2487 / 6 |
| 退出码 | 0 |
| 实际 worker | 3（标准 loadscope 基线）；4（n auto） |
| 墙钟 | 649.00 秒（标准 loadscope）；521.5 秒（n auto） |
| 进程树 RSS 峰值 | 3646.7 MiB（n auto） |
| 单 worker 高水位峰值 | 1369.1 MiB（n auto） |
| worker 高水位和 | 5866.5 MiB（n auto） |
| 看门狗中止 | 否 |

原始机器可读产物：

* 标准并行输出来自完整测试命令；n auto 内存读数见 `tools/out/mem/20261005-shortcut-closeout-complete-auto-auto.summary.json`、同名 `.samples.csv` 和 `.procs.csv`。

曾经只因 README 用例数口径错误而失败的中间结果保留在 `20261005-shortcut-closeout-final-auto.*`，没有作为最终基线。

## 输入配置漂移检查

新增 [`pdx.input_profile`](../../src/pdx/input_profile.py)，解析原版 `game/input_profile/default.profile` 的每个 `input_action`，保留所有 scancode、鼠标绑定、嵌套修饰键、文本键和文件 SHA-256，并检查关键绑定漂移。检查覆盖暂停、加减速、1–5 速、F1–F10 面板、日志、定位、地图列表、建造队列、确认和国家面板。

本机 Victoria 3 1.14.5 检查结果：

```text
SHA-256: c25cfff47e3de8a7428b4205e951897ee35e80abbacd320e2a9ef1fce4e44851
大小: 7983 字节
结果: 通过
```

命令：

```text
.venv\Scripts\python.exe -X utf8 -m pdx.input_profile --json
```

快照新增 `input_profile` 域，版本升级时可以直接 diff 动作绑定和文件指纹。

本次刷新后的精简快照为 10,718,842 字节，包含 60 个输入动作条目；`release-1.14.5.compact.json` 已更新。

## 覆盖率与离线门禁

完整测试恢复后重新执行了覆盖率和离线基线；覆盖率 JSON 写入 `tools/out/coverage/coverage-20261005-shortcut-closeout-complete.json`，离线基线退出码为 0。最终覆盖率数字以覆盖率命令输出和该 JSON 为准。

## 快捷键自动化接口

`game_auto.GAME_SHORTCUTS` 集中登记原版可安全发送的键盘动作，`GAME_SHORTCUT_MODIFIERS` 记录 `shift`、`alt`、`ctrl` 组合，`press_game_shortcut()` 统一执行前台窗口检查、输入闸门和动作后停顿。媒体键和鼠标专属动作通过 `UNSUPPORTED_GAME_SHORTCUTS` 明确拒绝；速度档继续使用专门的 tick 速率判据和鼠标回退；其它动作只完成输入发送，必须由调用方追加界面、日志或 tick 判据，避免把“按键已发送”写成“游戏已执行”。

## M2 财政生命周期

`decision_probe.analyze(..., strict=True)` 现在要求 RUS 与 PRU 都有观测、每国 `sample-N` 连续从 1 递增、同类读数不重复、每个连续样本都有 `RISK` 读数，并只在相邻样本间判定风险退出。M2 生命周期和卸载探针已切换到严格模式；普通模式保留给历史日志兼容读取。

严格模式提高证据质量，但没有改变行为结论：脚本创建外交博弈只能证明条件链路，不能证明 AI 自主发起；财政风险退出仍需区分原版破产、还款和规则恢复等原因。

## 验证边界

本轮完成的是工程和证据收口。Windows 快捷键速度路径已有实机闭环；macOS/Linux 的 Victoria 3 GUI 仍没有真实引擎证据。M3 的独立外交机会分母、AI 自主发起因果、政治立法行为和市场行为质量也没有因为这轮门禁通过而自动完成。
