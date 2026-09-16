"""全量分析 CLI。

用法：
    .venv\\Scripts\\python.exe tools/run_analyze.py              # 全量，落盘报告
    .venv\\Scripts\\python.exe tools/run_analyze.py --no-mods     # 只分析游戏本体
    .venv\\Scripts\\python.exe tools/run_analyze.py --quiet       # 不打印进度
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdx import analyze  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Victoria 3 游戏本体与 mod 全量分析")
    ap.add_argument("--no-mods", action="store_true", help="跳过 mod 分析")
    ap.add_argument("--no-cross", action="store_true", help="跳过交叉分析")
    ap.add_argument("--quiet", action="store_true", help="不打印逐项进度")
    ap.add_argument("--no-write", action="store_true", help="不落盘报告")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    verbose = not args.quiet
    t0 = time.perf_counter()

    if verbose:
        print("▶ 分析游戏本体 …")
    ga = analyze.game_analysis(verbose=verbose)
    if verbose:
        print(f"  完成：{ga.summary()}")

    ma = analyze.ModsAnalysis()
    ca = analyze.CrossAnalysis()

    if not args.no_mods:
        if verbose:
            print("\n▶ 分析 mod …")
        ma = analyze.mods_analysis(verbose=verbose)
        if verbose:
            print(f"  完成：{len(ma.mods)} 个 mod，"
                  f"{sum(ma.prefixes.values())} 次前缀使用")

    if not args.no_mods and not args.no_cross:
        if verbose:
            print("\n▶ 交叉分析 …")
        ca = analyze.cross_analysis(ga, ma, verbose=False)
        if verbose:
            print(f"  完成：{ca.summary()}")

    elapsed = time.perf_counter() - t0

    if not args.no_write:
        paths = analyze.write_reports(ga, ma, ca)
        print()
        for name, p in paths.items():
            size = p.stat().st_size if p.exists() else 0
            print(f"  已写入 [{name}] {p}  ({size:,} 字节)")

    print(f"\n总耗时 {elapsed:.1f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
