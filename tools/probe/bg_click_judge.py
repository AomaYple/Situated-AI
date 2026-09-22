"""后台点击的**判定版**：先排除"画面自己在动"，再看按钮还在不在。

上一版只做了像素差，会被界面动画骗；这一版用**目标按钮是否还在**当判据：
大厅里「观察」按钮匹配得到 ⇒ 还在大厅；匹配不到 ⇒ 界面确实切走了。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import win32con
import win32gui

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageChops

from pdx import game_auto

WM_MOUSEMOVE = win32con.WM_MOUSEMOVE
WM_LBUTTONDOWN = win32con.WM_LBUTTONDOWN
WM_LBUTTONUP = win32con.WM_LBUTTONUP
OBSERVE_XY = (864, 1055)


def post_click(hwnd: int, x: int, y: int) -> None:
    lp = (y << 16) | (x & 0xFFFF)
    win32gui.PostMessage(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.05)
    win32gui.PostMessage(hwnd, WM_LBUTTONDOWN, 1, lp)
    time.sleep(0.08)
    win32gui.PostMessage(hwnd, WM_LBUTTONUP, 0, lp)


def grab(hwnd: int) -> Image.Image:
    return game_auto.screenshot(hwnd)


def identical(a: Image.Image, b: Image.Image) -> bool:
    return (
        a.size == b.size
        and ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is None
    )


def observe_button(image: object) -> str:
    """大厅里「观察」按钮还在不在 —— 比"像素差"可靠：不会被界面动画骗。"""
    match = game_auto.locate(image, "btn_observe")  # type: ignore[arg-type]
    return f"匹配到（score={match.score:.3f}）" if match else "匹配不到（界面已切走）"


def main() -> int:
    hwnd = game_auto.find_window()
    if not hwnd:
        print("没有游戏窗口")
        return 2
    print(f"hwnd={hwnd} 前台是不是游戏：{win32gui.GetForegroundWindow() == hwnd}")

    # ① 对照组：不点任何东西，隔 3 秒再抓一张 —— 排除"界面自己在动"
    a = grab(hwnd)
    time.sleep(3.0)
    b = grab(hwnd)
    print(f"[对照] 3 秒内不做任何操作，两张截图相同：{identical(a, b)}")
    print(f"[对照] 按钮：{observe_button(b)}")

    # ② 实验组：PostMessage 点「观察」
    print(f"[实验] 点击前按钮：{observe_button(b)}")
    post_click(hwnd, *OBSERVE_XY)
    time.sleep(2.5)
    c = grab(hwnd)
    print(f"[实验] 点击后按钮：{observe_button(c)}")
    print(f"[实验] 点击前后截图相同：{identical(b, c)}")
    game_auto.save_shot(c, "bg-click-判定后")
    print("判据：对照组相同 + 点击后按钮匹配不到 ⇒ PostMessage 后台点击**可用**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
