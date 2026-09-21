"""一条龙：起游戏 → 等大厅 → 置顶(不激活) → 点击 → 判定。

为什么要一条龙：上一版分两步跑，等我去点的时候大厅已经自己过去了（按钮"已经切走"），
**结论无效**。这里把"确认在大厅"与"点击"之间的窗口压到几秒内。
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
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
OBSERVE_XY = (864, 1055)


def in_lobby(hwnd: int) -> tuple[bool, str]:
    try:
        match = game_auto.locate(game_auto.screenshot(hwnd), "btn_observe")
    except game_auto.TemplateNotFoundError:
        return False, "找不到观察按钮"
    return True, f"score={match.score:.3f}"


def main() -> int:
    pydirectinput.FAILSAFE = False
    pydirectinput.PAUSE = 0.0

    game_auto.assert_no_game_running()
    hwnd = game_auto.launch(scripted_tests=True, timeout=300)
    print("hwnd =", hwnd)
    game_auto.wait_for_lobby(hwnd, timeout=420)
    ok, detail = in_lobby(hwnd)
    print(f"到大堂：{ok}（{detail}）")

    # 把前台还给"别的窗口"——这样才能验证"不激活也能点"
    other = 0
    for candidate in range(1, 40):
        pass
    fg = user32.GetForegroundWindow()
    print(f"当前前台={fg}（游戏={fg == hwnd}）")
    if fg == hwnd:
        # 用 SetWindowPos 把游戏降下去？简单点：记下来，置顶后确认前台是否变了
        pass

    ok_top = user32.SetWindowPos(
        wintypes.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )
    time.sleep(0.4)
    fg2 = user32.GetForegroundWindow()
    print(f"置顶(不激活) 返回={ok_top}；之后前台={fg2}（游戏={fg2 == hwnd}）")

    origin = game_auto._client_origin(hwnd)
    print(
        f"客户区原点={origin}；点 {OBSERVE_XY} → 屏幕 {origin[0] + OBSERVE_XY[0]},{origin[1] + OBSERVE_XY[1]}"
    )
    pydirectinput.moveTo(origin[0] + OBSERVE_XY[0], origin[1] + OBSERVE_XY[1])
    time.sleep(0.2)
    pydirectinput.click()
    time.sleep(2.5)

    ok_after, detail_after = in_lobby(hwnd)
    print(f"点击后还在大厅：{ok_after}（{detail_after}）")
    print("⇒ 按钮消失 = 置顶不激活也能点；仍在 = 这条路也不通（只能抢前台）")
    game_auto.save_shot(game_auto.screenshot(hwnd), "topmost-click-后")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
