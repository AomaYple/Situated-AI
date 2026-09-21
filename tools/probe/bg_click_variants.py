"""PostMessage 不行之后，再试两种"不进系统输入队列"的变体 —— 判据仍是按钮还在不在。

V1 `SendMessage`（同步投递，绕开消息队列）
V2 `SendMessage` + 先 `WM_ACTIVATE`/`WM_SETFOCUS`（有些框架不收到激活消息就不处理鼠标）
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdx import game_auto

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_ACTIVATE, WM_SETFOCUS = 0x0006, 0x0007
OBSERVE_XY = (864, 1055)


def _lp(x: int, y: int) -> int:
    return (y << 16) | (x & 0xFFFF)


def button_state(hwnd: int) -> str:
    image = game_auto.screenshot(hwnd)
    match = game_auto.locate(image, "btn_observe")
    return f"还在（score={match.score:.3f}）" if match else "已经切走 ✅"


def variant_send(hwnd: int, *, activate_first: bool) -> str:
    lp = _lp(*OBSERVE_XY)
    if activate_first:
        user32.SendMessageW(hwnd, WM_ACTIVATE, 1, 0)  # WA_ACTIVE
        user32.SendMessageW(hwnd, WM_SETFOCUS, 0, 0)
    user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.05)
    user32.SendMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    time.sleep(0.08)
    user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    time.sleep(2.5)
    return button_state(hwnd)


def main() -> int:
    hwnd = game_auto.find_window()
    if not hwnd:
        print("没有游戏窗口")
        return 2
    print(f"hwnd={hwnd}；前台是不是游戏：{user32.GetForegroundWindow() == hwnd}")
    print(f"起点：观察按钮 {button_state(hwnd)}")
    print(f"V1 SendMessage            → {variant_send(hwnd, activate_first=False)}")
    print(f"V2 SendMessage + 激活消息 → {variant_send(hwnd, activate_first=True)}")
    print("（两种都不行 ⇒ 引擎确实读原始输入，后台点击这条路可以判死）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
