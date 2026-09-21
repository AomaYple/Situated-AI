"""用**成熟库** `pydirectinput`（scancode SendInput）试游戏控制台 —— B31 那条死路。

为什么值得再试一次：以前失败的 `keybd_event` / `SendInput` 发的是**虚拟键**，
而很多游戏（含 Paradox 的 Clausewitz）只认**扫描码**；`pydirectinput` 的源码里
确实带 `KEYEVENTF_SCANCODE`。

判据（文件级，不看像素 —— 像素差在大厅里已经被证明会骗人）：
  打开控制台 → 敲一条**会写文件**的命令 → 看文件有没有出现/更新。
  候选命令：`dump_ticktask_timings`（写 `Documents\\…\\ticktask_timings.csv`）、
           `log_ticktask_performance`（写 `profiling.log`）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pydirectinput

from pdx import game_auto

DOCS = Path("~").expanduser() / "Documents" / "Paradox Interactive" / "Victoria 3"
TARGETS = [DOCS / "ticktask_timings.csv", DOCS / "logs" / "profiling.log"]

#: 控制台候选键（V3/Clausewitz 常见的是 ` 与 ~，其次是 F12 / Ctrl+Alt+C 之类）。
CONSOLE_KEYS = ["`", "~", "f12", "f11"]


def state() -> dict[str, float]:
    return {str(p): (p.stat().st_mtime if p.is_file() else 0.0) for p in TARGETS}


def main() -> int:
    pydirectinput.FAILSAFE = False  # 自动化里别让"鼠标移到角落"打断
    pydirectinput.PAUSE = 0.05

    hwnd = game_auto.find_window()
    if not hwnd:
        print("游戏没在跑")
        return 2
    print(f"hwnd={hwnd}  前台是不是游戏：{game_auto._foreground_window() == hwnd}")

    before = state()
    print("命令前：", {Path(k).name: v for k, v in before.items()})

    for key in CONSOLE_KEYS:
        print(f"--- 试控制台键 {key!r} ---")
        # 键盘要送到游戏 → 先把前台给游戏（pydirectinput 是系统级注入，不认窗口参数）
        try:
            game_auto.ensure_foreground(hwnd)
        except Exception as exc:
            print("  强激活失败：", exc)
            continue
        pydirectinput.press(key)
        time.sleep(0.6)
        pydirectinput.write("dump_ticktask_timings", interval=0.02)
        pydirectinput.press("enter")
        time.sleep(1.5)
        after = state()
        changed = {Path(k).name: (before[k], after[k]) for k in after if after[k] != before[k]}
        if changed:
            print(f"  ✅ 有文件被写：{changed}")
            print(f"  ⇒ 控制台键 {key!r} **可用**（键盘注入被引擎接受）")
            return 0
        print("  ❌ 没有任何目标文件变化")
        before = after

    print("\n结论：四个候选键都不行 ⇒ 控制台路线（B31）用 scancode 也走不通")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
