"""全仓审查：Python 化 / 成熟库 / 测试 / 性能 / 并行 五条口径的**可执行清单**。

用户的五条要求（2026-09-22）：
1. 能用 Python 的就用 Python，**完全 Python 化**；
2. 能用成熟库的**不要自己写**；
3. 尽可能加测试、**尽可能提升覆盖率**；
4. 做**性能测试**并提升性能；
5. 所有测试**默认并行**。
外加：不影响准确率的前提下尽量提速。

本脚本只**读**仓库并打印清单（不改任何文件、不读游戏），把"该改什么"变成可核对的行：

* 非 Python 的可执行/脚本文件（Python 化的候选）；
* `tools/pdx` 模块 → 是否有专门测试文件引用它（覆盖缺口）；
* 手写痕迹：`ctypes` / 自造解析（`csv`/`json`/`toml` 之外的逐字符解析）/ 自造 CLI 参数解析；
* 覆盖率低于门禁或偏低的模块（读 `cov.json`）；
* 性能：基准用例清单（`pytest-benchmark`）+ 是否有对应基准；
* 并行：`pyproject.toml` 的 `addopts` 里是否 `-n auto`。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdx import config

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    ".benchmarks",
    ".mypy_cache",
    "out",
    "node_modules",
}
SCRIPT_EXT = {".ps1", ".bat", ".cmd", ".sh", ".js", ".ts", ".vbs"}


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def section(title: str) -> None:
    print(f"\n===== {title} =====")


def main() -> int:
    # 控制台可能是 GBK：先把标准输出钉成 UTF-8，别让编码问题伪装成审查失败。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    root = config.REPO
    files = list(_iter_files(root))
    print(f"仓库：{root}\n文件数（排除 .venv/.git/out 等）：{len(files)}")

    section("① Python 化：非 Python 的脚本 / 可执行文件")
    scripts = [p for p in files if p.suffix.lower() in SCRIPT_EXT]
    for path in scripts:
        print(f"  {path.relative_to(root)}")
    print(f"  合计 {len(scripts)} 个" + ("（无 ⇒ 已全 Python）" if not scripts else ""))

    section("② 扩展名分布（看有没有手写产物混进来）")
    for ext, count in Counter(p.suffix.lower() or "<无扩展名>" for p in files).most_common(12):
        print(f"  {ext:<14} {count}")

    section("③ 成熟库：手写痕迹")
    patterns = {
        "ctypes（手写 Win32）": re.compile(r"\bctypes\b"),
        "win32 直接调用（允许 pywin32，但要看看是否重复造轮子）": re.compile(
            r"win32api\.|win32gui\."
        ),
        "自造参数解析（argparse/typer 之外）": re.compile(r"sys\.argv\["),
        "自造 CSV/JSON（应走标准库）": re.compile(r"\.split\(\"[\n,]\""),
    }
    # ⚠️ **每一处都要给出 `文件:行` 与那一行的原文**（2026-09-23 修）。
    # 只印文件名时，人得自己回去 grep 才知道命中的是什么 —— 而这份清单的价值就在于
    # 「扫一眼就能判断是真手写还是误报」。实测：`verify.py` 那句
    # `target.split(",")` 拆的是断言注册表里一个**逗号分隔的 target 字段**，
    # 与 CSV 毫无关系，但在旧输出里和"真的手写了解析器"长得一模一样。
    # 已知的**正当**命中（判据要能区分"手写解析器"与"手写判据"）：
    #   * 测试里的**手写 oracle**（`test_gametimer_csv.py` 拿 `split(",")` 当独立参照，
    #     与走标准库的实现**差分对比**）—— 那是刻意留的第二实现，不是重复造轮子；
    #   * 提到这些关键词的注释 / docstring / 正则本身。
    for label, pattern in patterns.items():
        hits: list[tuple[Path, int, str]] = []
        for path in files:
            if path.suffix != ".py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append((path, lineno, line.strip()))
        print(f"  {label}: {len(hits)} 处 / {len({h[0] for h in hits})} 个文件")
        for path, lineno, line in hits[:6]:
            print(f"      {path.relative_to(root)}:{lineno}  {line[:96]}")

    section("④ 测试：模块 → 是否被专门测试文件引用")
    modules = sorted((root / "tools" / "pdx").glob("*.py"))
    tests = sorted((root / "tools" / "tests").glob("test_*.py"))
    test_text = {p: p.read_text(encoding="utf-8", errors="replace") for p in tests}
    untested: list[str] = []
    for module in modules:
        if module.name.startswith("_"):
            continue
        name = module.stem
        referenced = [
            p for p, text in test_text.items() if re.search(rf"\b{re.escape(name)}\b", text)
        ]
        if not referenced:
            untested.append(module.name)
    print(f"  模块 {len(modules)} 个 / 测试文件 {len(tests)} 个")
    print(f"  没有专门测试引用的模块：{len(untested)} 个")
    for name in untested:
        print(f"      {name}")

    section("⑤ 覆盖率（读 cov.json，若存在）")
    cov_path = root / "tools" / "out" / "cov.json"  # `v3 cov` 写在这里（原来找了仓库根 ⇒ 永远空）
    if cov_path.is_file():
        data = json.loads(cov_path.read_text(encoding="utf-8"))
        rows = []
        for path, body in data.get("files", {}).items():
            summary = body.get("summary", {})
            rows.append(
                (summary.get("percent_covered", 0.0), path, summary.get("num_statements", 0))
            )
        rows.sort()
        for percent, path, stmts in rows[:12]:
            print(f"  {percent:5.1f}%  {stmts:>5} 语句  {path}")
    else:
        print("  （没有 cov.json —— 先跑 `v3 cov`）")

    section("⑥ 性能：基准清单")
    bench_files = [
        p for p in tests if "benchmark" in p.read_text(encoding="utf-8", errors="replace")
    ]
    for path in bench_files:
        text = path.read_text(encoding="utf-8")
        names = re.findall(r"def (test_\w+)\(", text)
        print(f"  {path.relative_to(root)}：{len(names)} 条")
        for name in names[:12]:
            print(f"      {name}")

    section("⑦ 并行：pytest addopts")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    # ⚠️ 别用 `split("[")` 截段：`addopts = [` 自己就带 `[`，一截就永远读不到（原实现就栽在这）。
    section_text = pyproject.split("[tool.pytest.ini_options]", 1)[-1]
    addopts = re.search(r"addopts\s*=\s*\[(.*?)\]", section_text, re.DOTALL)
    body = addopts.group(1) if addopts else ""
    parallel = '"auto"' in body or "'auto'" in body
    print(f"  默认并行：{'✅ 是（addopts 里有 -n auto）' if parallel else '❌ 否'}")
    dist = re.search(r'"--dist"\s*,\s*"(\w+)"', body)
    print(f"  分发策略：{dist.group(1) if dist else '（未设）'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
