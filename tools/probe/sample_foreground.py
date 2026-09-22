"""伴随采样：在 `python -m pdx.game_auto run` 跑的这几分钟里，每隔几秒记一次
"前台是谁 / 游戏窗口在不在前台 / 是否已最小化"。

用来**独立证明**三件事（判据不靠被观测方自述，靠外部采样）：

* 起游戏时**没有抢前台**（用户口径第 ① 条：后台启动）；
* 借前台期间**只有很短一段时间**在前台（返回值里的 `borrow_seconds` 应当是个小数字）；
* 点完之后**前台还回去了**（第 ③ 条）＋ 窗口**被缩下去**（第 ④ 条）。

## 口径

* 采样全部走**成熟库缝隙**（`pygetwindow` / `pywin32`，见 `pdx.game_auto` 的窗口层），
  不留手写 ctypes（P3 + 用户口径"完全使用 python"）；
* **只读**：不点、不切前台、不动窗口 —— 采样本身不能影响被观测的过程。

## 用法（另开一个终端，和 `v3 game run` 同时跑）

    .venv\\Scripts\\python.exe tools/probe/sample_foreground.py [总秒数] [间隔秒数]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdx import game_auto as ga

DEFAULT_SECONDS = 300.0
DEFAULT_INTERVAL = 5.0


def sample() -> dict[str, object]:
    """一次采样：前台是谁、游戏窗口在不在前台、是否最小化。"""
    front = ga._foreground_window()
    game = ga.find_window()
    return {
        "front": front,
        "front_title": ga._window_title(front) if front else "",
        "game": game,
        "game_is_front": bool(game) and front == game,
        "game_iconic": bool(game) and ga._is_iconic(game),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="伴随采样：前台是谁")
    parser.add_argument("total", nargs="?", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("interval", nargs="?", type=float, default=DEFAULT_INTERVAL)
    args = parser.parse_args()
    total, interval = args.total, args.interval
    started = time.monotonic()
    game_seen = 0
    game_front_seconds = 0.0
    print(f"采样 {total:.0f} 秒，每 {interval:.1f} 秒一次（只读，不动任何窗口）")
    print(f"{'秒':>6}  {'前台':>8}  {'游戏在前台':>10}  {'游戏最小化':>10}  前台标题")
    while time.monotonic() - started < total:
        row = sample()
        elapsed = time.monotonic() - started
        if row["game"]:
            game_seen += 1
        if row["game_is_front"]:
            game_front_seconds += interval
        print(
            f"{elapsed:6.0f}  {row['front']:>8}  "
            f"{'是' if row['game_is_front'] else '否':>10}  "
            f"{'是' if row['game_iconic'] else '否':>10}  {str(row['front_title'])[:40]}"
        )
        time.sleep(interval)
    print(
        f"\n小结：采到游戏窗口 {game_seen} 次；估算游戏在前台的时长 ≈ {game_front_seconds:.0f} 秒"
        "（后台启动 ⇒ 这个数应当只有“借来点击”的那几秒）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
