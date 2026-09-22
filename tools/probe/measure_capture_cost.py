"""抓图成本实测：整屏 vs 只抓 ROI（P2「最坏情况实测」，P5「优化要有前后对照」）。

## 为什么要有这个脚本

找按钮 = **抓图 + 模板匹配**，等界面时一秒要跑好几遍，所以这条路径是热路径。
2026-09-21 把它从"整屏抓图 + 6 尺度全试"改成"只抓需要的 ROI + 命中即停"，
匹配侧的前后对照跑在 `tools/tests/test_benchmarks.py::TestAutoCaptureBenchmarks`
（均值 1.147 秒 → 15.3 毫秒）。**抓图侧**测不了那么干净 —— 它依赖真实屏幕 ——
所以单独放这个探针，量的是同一件事的两个口径：

* 整屏（1920×1080 客户区）
* 底部状态栏 ROI（1920×108，`game_auto.BOTTOM_ROI`）

## 口径

* **只读**：只截当前前台窗口的像素，不移动鼠标、不点、不切前台、不改窗口；
* 报**均值与最坏**（P2 要的是最坏情况，不是好看的平均值）；
* 前台窗口不管是什么程序都行（这里量的是 `ImageGrab` 的成本，与具体窗口无关）。

## 用法

    .venv\\Scripts\\python.exe tools/probe/measure_capture_cost.py [轮数]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab

from pdx import game_auto as ga

#: 每次测量之间歇一下，避免把 CPU 打满影响自己（这本身也是"最坏情况"的一部分）。
GAP_SECONDS = 0.05


def _time_grab(bbox: tuple[int, int, int, int], rounds: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(rounds):
        started = time.perf_counter()
        ImageGrab.grab(bbox=bbox, all_screens=True)
        samples.append((time.perf_counter() - started) * 1000.0)
        time.sleep(GAP_SECONDS)
    return {
        "rounds": rounds,
        "mean_ms": round(statistics.fmean(samples), 3),
        "max_ms": round(max(samples), 3),
        "min_ms": round(min(samples), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="抓图成本实测：整屏 vs 只抓 ROI")
    parser.add_argument("rounds", nargs="?", type=int, default=20, help="测量轮数")
    rounds = parser.parse_args().rounds
    hwnd = ga._foreground_window()
    if not hwnd:
        print("❌ 读不到前台窗口")
        return 2
    width, height = ga._client_size(hwnd)
    if width <= 0 or height <= 0:
        print(f"❌ 客户区尺寸非法：{width}x{height}")
        return 3
    origin_x, origin_y = ga._client_origin(hwnd)
    left, top, right, bottom = ga.BOTTOM_ROI
    full = (origin_x, origin_y, origin_x + width, origin_y + height)
    roi = (
        origin_x + int(left * width),
        origin_y + int(top * height),
        origin_x + int(right * width),
        origin_y + int(bottom * height),
    )
    print(f"前台窗口 {ga._window_title(hwnd)!r}（hwnd={hwnd}）客户区 {width}x{height}")
    print(f"整屏 bbox = {full}")
    print(
        f"ROI  bbox = {roi}（{roi[2] - roi[0]}x{roi[3] - roi[1]}，整屏的 "
        f"{(roi[2] - roi[0]) * (roi[3] - roi[1]) / (width * height):.1%} 面积）"
    )
    full_stats = _time_grab(full, rounds)
    roi_stats = _time_grab(roi, rounds)
    print(f"\n整屏：均值 {full_stats['mean_ms']} ms，最坏 {full_stats['max_ms']} ms")
    print(f"ROI ：均值 {roi_stats['mean_ms']} ms，最坏 {roi_stats['max_ms']} ms")
    print(
        f"省下：均值 {(1 - roi_stats['mean_ms'] / full_stats['mean_ms']) * 100:.1f}%"
        f"（{full_stats['mean_ms'] / roi_stats['mean_ms']:.1f}×）"
    )

    # 屏幕级参照：全屏 1920×1080 vs 一条 1920×108 的横条。
    # 为什么要这个参照：**抓图的成本主要不是像素数**，而是每次截屏 + 位图封装的固定开销；
    # 这条参照把"固定开销有多大"量出来，免得把 ROI 的收益说得比实测大。
    screen_w, screen_h = ImageGrab.grab().size
    screen_stats = _time_grab((0, 0, screen_w, screen_h), rounds)
    strip_stats = _time_grab((0, screen_h - 108, screen_w, screen_h), rounds)
    print(
        f"\n[屏幕参照 {screen_w}x{screen_h}] 全屏：均值 {screen_stats['mean_ms']} ms，"
        f"最坏 {screen_stats['max_ms']} ms"
    )
    print(
        f"[屏幕参照] {screen_w}x108 横条：均值 {strip_stats['mean_ms']} ms，"
        f"最坏 {strip_stats['max_ms']} ms"
    )
    print(
        f"[屏幕参照] 只差 {(1 - strip_stats['mean_ms'] / screen_stats['mean_ms']) * 100:.1f}%"
        " —— 抓图成本由**固定开销**主导：ROI 省下的是**匹配**时间，不是抓图时间"
    )
    out = Path(__file__).resolve().parents[1] / "out" / "auto" / "capture_cost.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "client": f"{width}x{height}",
                "full": full_stats,
                "roi": roi_stats,
                "screen": {
                    "size": f"{screen_w}x{screen_h}",
                    "full": screen_stats,
                    "strip": strip_stats,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n证据：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
