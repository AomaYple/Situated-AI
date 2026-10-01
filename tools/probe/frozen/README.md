# tools/probe/frozen —— 跑批期间用过的仪器修订（只读留档）

2026-10-01 仓库整理新增两份历史来源：`mem_baseline-before-psutil.py.frozen`
保留原来的 ctypes 与平台命令实现，`mem_method_crosscheck-windows.py.frozen`
保留旧 Win32 / PowerShell 四路实验。当前入口改用 psutil 和 Python，旧仪器仅供核对历史读数。
全仓编码归一时的精确原始字节在 `tools/out/repository-audit/encoding-*-originals.zip`
及 `encoding-originals.zip` 中可恢复。下文的尺寸、哈希和 AST 比较描述当时的修订，
不能用作当前活跃脚本与历史脚本仍然等价的断言。

这里放的是**预注册锚定**的那一版 `tools/probe/perf_compare.py`（阶段 4④ inv1+inv2 用的仪器），以及同批
被 `t12` 改过文案的测试文件修订。它们**不是**可运行入口：后缀写作 `.py.frozen` 是为了不给门禁添新面
（ruff 按扩展名收文件 —— `.py.frozen` 的扩展名是 `.frozen`，`ruff check` 与 `ruff format` 都不收它；
`pyproject.toml:224-238` 的 `extend-exclude` 也不管它；mypy 的 `files = ["src/pdx", "tests"]`／
`pyproject.toml:371` 同样不扫它）。**但本文件是 `.md`，这层保护不适用** —— `ruff format` 会连 `.md` 里的
python 代码块一起格式化（`ruff check` 与 mypy 都不会），故下面那个块必须保持 ruff 格式化后的样子，
否则 `.github/workflows/ci.yml:61` 的 `ruff format --check .` 会红。留档目的只有一个：
**跑批期间用哪一版仪器，事后必须可复核**。

| 文件 | size | sha256 | 来历 |
|---|---|---|---|
| `perf_compare-42149B-35f2f4fd.py.frozen` | 42,149 B | `35f2f4fda6dace32395064972b3da37215191dd82ea6f4285cc407833240e9f6` | 阶段 4④ inv1+inv2 的仪器（预注册钉死的那一版；仓库里原先没有副本）；`t12` 收尾时用历史 `edit` 实参**逆序复原**得到，并对 recorded size+sha256 **逐字节自证**（见 `docs/reports/t12-静默路径文案与回归.md` §3.1） |
| `test_stress_probe-47651B-96e7d90e.py.frozen` | 47,651 B | `96e7d90ee50c52af7b1e764d6f499fe56c05f6c010a500a058279ce433dd7986` | 同一批：`t12` 改它之前那一刻的文本（LF 923 / CR 0 / 无 BOM） |

现盘（`t12` 改后）是 **42,895 B / `7672c9144e7c07a902ce462e420bf421ac03c03b785e5b4b52d42592055b8235`**。
留档件与现盘的差别**只在两处**（逐项核对读数见本行下方）：

1. `_quarantine_logs()` 的**文档字符串** —— 1,549 → 1,950 字符（AST 里可见；归一化折叠后不可见，见下节复算）；
2. 一条**出声 f-string** —— **文字与取值表达式都变了**：
   `f"⚠️ 挪不动，文件仍在原地：{path} → {target / path.name}"` →
   `f"…：{path}（{type(fault).__name__}: {fault}）；隔离目录 {target}（落点名由 unused_path() 挑，不一定是原名）"`。

逐项核对读数（现跑；脚本 `%TEMP%\t12-docstring-check.py`）：字符串常量多重集（**含** docstring）299 vs 299 次出现，
**只在 frozen 3 条 / 只在 live 3 条**（旧、新 docstring 各 1 条，加 `' → '` / `'）'` 与 `'）；隔离目录 '` /
`'（落点名由 unused_path() 挑，不一定是原名）'`）；24 个 docstring 中**恰 1 个**不同（`_quarantine_logs`）；
**注释 token 39 == 39，零差异**。⇒ 「只改文案」里的「文案」= 该文档字符串 + 那条出声 f-string 的文字与取值表达式，
**没有任何注释被改**，也没有任何语句 / 控制流 / 判据 / 阈值 / 采样被改。

## 复算：归一化 AST（剥掉注释与字符串文字后必须完全相同）

```python
import ast
from pathlib import Path


class Fold(ast.NodeTransformer):
    def visit_Constant(self, node):
        return ast.Constant(value=None)

    def visit_JoinedStr(self, node):
        return ast.Constant(value=None)


def norm(src):
    return ast.dump(Fold().visit(ast.parse(src)))


frozen = norm(
    Path("tools/probe/frozen/perf_compare-42149B-35f2f4fd.py.frozen").read_text(encoding="utf-8")
)
live = norm(Path("tools/probe/perf_compare.py").read_text(encoding="utf-8"))
print(frozen == live)
```

判读：`True` ⇒ 两版结构相同（`t12` 的改动没有碰任何语句、控制流、判据、阈值或采样规则）。注意 `Fold`
必须把**整条** `JoinedStr` 折成占位：若只剥 docstring 而不折 `JoinedStr`，会在
`tools/probe/perf_compare.py:226-227` 那条**出声文案**上看到预期的差异 —— 那正是本卡允许改的报错文案。
