# 冻结实验仪器

本目录只保存历史实验所用的仪器与测试修订，供事后核对方法和读数。`.py.frozen` 文件不是运行入口；当前工具使用 `tools/probe/`、`tools/benchmarks/` 和 `src/pdx/` 中的活跃实现。

## 文件与指纹

以下指纹于 2026-10-10 从当前仓库文件读取，描述当前保存的副本。文件名中的尺寸与摘要属于原实验锚点，不能据此推断活跃脚本仍与冻结件等价。

| 文件 | 当前字节数 | 当前 SHA-256 | 来源 |
|---|---|---|---|
| `mem_baseline-before-psutil.py.frozen` | 133,630 | `6005e6ca36626d3523b00dc15949fb1b4d2e23364a810f62385655775b25fc97` | 内存工具迁移到 psutil 前的 ctypes 与平台命令实现 |
| `mem_method_crosscheck-windows.py.frozen` | 11,717 | `a66997f89c6ac7dcde567e3a0ebbcbb4b42f5f6ddf0010496e35de7ed90f2cde` | 旧 Windows 四路内存交叉实验仪器 |
| `perf_compare-42149B-35f2f4fd.py.frozen` | 42,149 | `35f2f4fda6dace32395064972b3da37215191dd82ea6f4285cc407833240e9f6` | 阶段 4④ inv1+inv2 预注册锚定的性能仪器 |
| `test_stress_probe-47651B-96e7d90e.py.frozen` | 47,651 | `96e7d90ee50c52af7b1e764d6f499fe56c05f6c010a500a058279ce433dd7986` | 同批压力探针测试的历史修订 |

## 恢复与解释

仓库编码归一时保留的精确原始字节可从本地忽略目录 `tools/out/repository-audit/encoding-originals.zip`、`encoding-followup-originals.zip` 与 `encoding-final-originals.zip` 恢复；恢复时按归档清单核对路径和 SHA-256。原始字节、仓库规范化副本和当前活跃实现属于不同对象，不能混用指纹或把旧测量冒充当前测量。

阶段 4 仪器复原与当时的差异记录见 [t12 历史报告](../../../docs/reports/t12-静默路径文案与回归.md)。报告中的等价性只针对其固定修订，当前活跃脚本已有后续功能变化，不要求与冻结件 AST 相同。剥掉字符串的 AST 比较也不能独立证明行为相同。

冻结件不参与常规 Python 源码格式化或运行测试；README 按普通仓库文档维护。Ruff 的 Python 格式检查不负责格式化 Markdown 中的代码块。清理前须核查报告、预注册锚点与恢复副本，不能把这些仪器当缓存删除。
