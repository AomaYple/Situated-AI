"""把 pytest-benchmark 的 JSON 汇总成一张 Markdown 表（给 CI 的 job summary 用）。

为什么要有它：CI 上**不断言**基准（墙钟在共享 runner 上抖得厉害，当门禁必然误报），
但"没人看"等于没有 —— 这个脚本把每次 push 的同一套口径写成一张表，贴在 job summary 里，
趋势一眼可见。口径固定为"合成样本 + 同一台 runner 型号"，所以逐次可比。

用法：

```text
pytest tools/tests/test_benchmarks.py -o addopts="" --benchmark-only --benchmark-json=bench.json
python tools/ci/bench_summary.py bench.json >> "$GITHUB_STEP_SUMMARY"
```

只用标准库：CI 上不该为了打一张表再装东西（P4）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: 只报这些统计量。``ops`` 是"每秒多少次"，它比裸耗时更直观，也给两个方向的口径。
COLUMNS = ("min", "mean", "median", "max", "ops")


def _unit(seconds: float) -> tuple[float, str]:
    """秒 → （换算后的值, 单位）。基准的量级跨三个数量级，不换单位读不动。"""
    if seconds < 1e-6:
        return seconds * 1e9, "ns"
    if seconds < 1e-3:
        return seconds * 1e6, "us"
    return seconds * 1e3, "ms"


def table(data: dict[str, object]) -> str:
    """``benchmark JSON`` → Markdown 表（行长按名字排序，便于逐次比对）。"""
    benchmarks = data.get("benchmarks") or []
    if not isinstance(benchmarks, list) or not benchmarks:
        return "_没有基准数据（这一轮的机器上没有可跑的基准？）_\n"
    rows: list[tuple[str, dict[str, float]]] = []
    for item in benchmarks:
        if not isinstance(item, dict):
            continue
        stats = item.get("stats")
        if not isinstance(stats, dict):
            continue
        name = str(item.get("name", "?"))
        # 参数化会把参数塞进 name，取最后一段更短也更好认
        rows.append((name, {k: float(stats.get(k, 0.0) or 0.0) for k in COLUMNS}))
    rows.sort(key=lambda row: row[0])

    out = [
        "### 基准（合成样本，无游戏）",
        "",
        "| 基准 | min | mean | median | max | ops/s |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in rows:
        cells: list[str] = []
        for key in ("min", "mean", "median", "max"):
            value, unit = _unit(stats[key])
            cells.append(f"{value:,.2f} {unit}")
        out.append(f"| `{name}` | " + " | ".join(cells) + f" | {stats['ops']:,.0f} |")
    out.append("")
    out.append(
        f"共 {len(rows)} 条。**这些数字不是门禁**：绝对墙钟在共享 runner 上会抖，"
        "断言留在本机（`test_audit_leftovers.py` 的吞吐下限 + `test_cache.py` 的"
        "「并发下每个文件只解析一次」这类**不依赖墙钟**的不变量）。"
    )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else Path("bench.json")
    if not path.is_file():
        print(f"_找不到 {path} —— 基准那一步没产出文件？_\n")
        return 0  # 汇总失败不该让 job 红：它不是门禁
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"_基准 JSON 读不动（{exc}）_\n")
        return 0
    sys.stdout.write(table(data))
    return 0


if __name__ == "__main__":  # pragma: no cover - 入口
    raise SystemExit(main())
