"""实机跑一次标准流程，**保证收尾**（关游戏 + 还前台 + 桌面采样）。

为什么要这个包装：`pdx.game_auto` 只管"点到跑起来"，不管"失败时把游戏收掉" ——
前三轮实机各失败一次，其中一次就留下了一个 victoria3 进程，下一次直接被
`GameRunningError` 拦住。用户口径是"每条实机操作必须可回滚"，所以把收尾写成代码：

* `finally` 里**无论成败**都杀掉本进程树起的 victoria3（只杀它，不动别人的进程）；
* 把前台还给**启动前那个窗口**（`game_auto.launch_to_foreground` 会把它记下来）；
* 采样 9 个屏幕点，确认桌面真的回到用户手里（不是"我觉得还回去了"）。

判据（打印在最后，直接抄进结果文档）：
`speed_ok` / `speed_days_per_second` / `handover` / `minimized` / `tick`。

用法：``python tools/probe/flow_with_cleanup.py``（默认不带 `-scripted_tests` 之外的参数）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import win32gui

from pdx import game_auto as ga

SAMPLE_POINTS = (
    (100, 100),
    (960, 100),
    (1800, 100),
    (100, 540),
    (960, 540),
    (1800, 540),
    (100, 1000),
    (960, 1000),
    (1800, 1000),
)


def desktop_owners() -> dict[int, int]:
    """9 个采样点上压着的顶层窗口 → 命中点数（用来证明桌面回没回到用户手里）。"""
    tally: dict[int, int] = {}
    for point in SAMPLE_POINTS:
        under = int(win32gui.GetAncestor(win32gui.WindowFromPoint(point), ga.GA_ROOT))
        tally[under] = tally.get(under, 0) + 1
    return tally


def kill_game() -> list[int]:
    """杀掉 victoria3；返回杀掉的 PID（`taskkill` 不读就不假装知道）。"""
    pids = ga._process_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    return pids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flow_with_cleanup", description=__doc__)
    parser.add_argument("--speed-xy", default="", help="显式指定速度档 V 的客户区坐标 X,Y")
    parser.add_argument("--skip-speed", action="store_true", help="不切速度档")
    parser.add_argument("--lobby-timeout", type=float, default=ga.LOBBY_TIMEOUT)
    args = parser.parse_args(argv)

    ga.ALLOW_REAL_INPUT = True  # 显式入口：允许抢前台点那三下
    leftover = ga._process_pids()
    if leftover:
        print(f"⚠️ 起前有残留 victoria3：{leftover} —— 先收掉（这是上一轮没收拾干净）")
        kill_game()
        time.sleep(3)

    previous = ga._foreground_window()
    print(f"启动前前台 = {previous}（收尾会还给它）")
    result: ga.SessionStart | None = None
    failure = ""
    try:
        hwnd, previous = ga.launch_to_foreground(
            scripted_tests=True, timeout=float(args.lobby_timeout)
        )
        print(f"窗口 hwnd = {hwnd}")
        settle = ga.wait_for_boot_settle(timeout=float(args.lobby_timeout))
        print(f"加载等待（不碰窗口）：{settle.why}")
        speed_xy: tuple[int, int] | None = None
        if args.speed_xy:
            left, _, right = str(args.speed_xy).partition(",")
            speed_xy = (int(left), int(right))
        result = ga.start_session(
            hwnd,
            previous,
            settle=settle,
            speed_xy=speed_xy,
            skip_speed=bool(args.skip_speed),
            force=True,
        )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        killed = kill_game()
        time.sleep(2)
        # 收尾时**先还前台再采样**：否则采到的是还在最上面的游戏窗口，看不出真相。
        if previous and previous != ga.find_window():
            ga._set_foreground(previous)
        owners = desktop_owners()
        print("\n=== 收尾 ===")
        print(f"杀掉的 victoria3 PID：{killed or '（没有）'}")
        print(f"前台现在 = {ga._foreground_window()}（应为 {previous}）")
        print("桌面采样：")
        for owner, count in owners.items():
            print(
                f"  {count} 点 → {win32gui.GetClassName(owner)} "
                f"{win32gui.GetWindowText(owner)[:28]!r}"
            )

    if failure:
        print(f"\n[失败] {failure}")
        return 1
    print("\n=== 标准流程结果（照抄进结果文档）===")
    for key, value in (result.as_dict() if result else {}).items():
        print(f"  {key:22s}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
