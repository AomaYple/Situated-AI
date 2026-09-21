"""第三条路：把游戏置为 **TOPMOST 但不激活**（`SWP_NOACTIVATE`），再点它。

和已经判死的那两条不同：
  * 窗口消息（`PostMessage`/`SendMessage`）：引擎不看消息 —— 判死；
  * 抢前台再点：**能用，但会夺走用户的焦点** —— 用户明确不要；
  * 本条：游戏排到最上层（视觉上盖住别的窗口），但**焦点仍在用户那边**。
    点击是系统级注入，落点就是最上层那个窗口 ⇒ 理论上能点到游戏，而用户不用被抢焦点。

判据仍用"目标按钮还在不在"（像素差在大厅里会骗人）。
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pydirectinput

from pdx import game_auto

user32 = ctypes.WinDLL("user32", use_last_error=True)
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0010, 0x0040
OBSERVE_XY = (864, 1055)


def button(hwnd: int) -> str:
    """大厅里「观察」按钮还在不在。

    `locate` 是"**必须**找到"那一版（找不到会抛），这里"找不到"本身就是结论，所以要接住。
    """
    try:
        match = game_auto.locate(game_auto.screenshot(hwnd), "btn_observe")
    except game_auto.TemplateNotFoundError:
        return "已经切走 ✅"
    return f"还在（score={match.score:.3f}）"


def main() -> int:
    pydirectinput.FAILSAFE = False
    pydirectinput.PAUSE = 0.0
    hwnd = game_auto.find_window()
    if not hwnd:
        print("游戏没在跑")
        return 2

    fg_before = user32.GetForegroundWindow()
    print(f"hwnd={hwnd}")
    print(f"置顶前：前台={fg_before}（游戏={fg_before == hwnd}）；按钮 {button(hwnd)}")

    ok = user32.SetWindowPos(
        wintypes.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )
    time.sleep(0.5)
    fg_after = user32.GetForegroundWindow()
    print(f"置顶后：SetWindowPos 返回 {ok}；前台={fg_after}（游戏={fg_after == hwnd}）")
    print("  ⇒ 焦点有没有被抢：", "抢了 ❌" if fg_after == hwnd else "没抢 ✅（仍是别人的窗口）")

    origin = game_auto._client_origin(hwnd)
    pydirectinput.moveTo(origin[0] + OBSERVE_XY[0], origin[1] + OBSERVE_XY[1])
    time.sleep(0.2)
    pydirectinput.click()
    time.sleep(2.5)
    print("点击后：", button(hwnd))
    fg_final = user32.GetForegroundWindow()
    print(f"点击后前台={fg_final}（游戏={fg_final == hwnd}）")
    print("\n判据：按钮切走 ⇒ 置顶+不激活**可用**；否则这条也不通。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
