"""验证假设：**顶栏会自己隐藏** —— 光标不在顶部时，速度表盘根本不在画面上。

如果是这样，`speed_widget_xy` 必须在截图**之前**先把光标挪到顶部（这本来也是点击要做的），
否则模板当然匹配不上（实机就是这么失败的）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pydirectinput

from pdx import game_auto

TEMPLATE_BOX = (1700, 18, 1858, 86)  # 校准用的整扇区域


def best_score(hwnd: int) -> float:
    image = np.array(game_auto.screenshot(hwnd))
    crop = image[TEMPLATE_BOX[1] : TEMPLATE_BOX[3], TEMPLATE_BOX[0] : TEMPLATE_BOX[2]]
    match = game_auto.match_template(
        image,
        np.ascontiguousarray(crop),
        name="表盘",
        threshold=0.0,
        scales=(1.0,),
        roi=(0.0, 0.0, 1.0, 1.0),
    )
    return 0.0 if match is None else round(match.score, 3)


def main() -> int:
    pydirectinput.FAILSAFE = False
    pydirectinput.PAUSE = 0.0
    hwnd = game_auto.find_window()
    if not hwnd:
        print("游戏没在跑")
        return 2
    origin = game_auto._client_origin(hwnd)

    # ① 光标停在底部（远离顶栏）时的分数
    pydirectinput.moveTo(origin[0] + 960, origin[1] + 900)
    time.sleep(1.5)
    far = best_score(hwnd)
    print(f"光标在底部时，整扇区域自匹配分数 = {far}")

    # ② 光标挪到顶栏附近时的分数
    pydirectinput.moveTo(origin[0] + 1850, origin[1] + 50)
    time.sleep(1.5)
    near = best_score(hwnd)
    print(f"光标在顶部时，整扇区域自匹配分数 = {near}")
    game_auto.save_shot(game_auto.screenshot(hwnd), "speed-光标在顶部")

    print("\n判读：两次都 ≈1.000 ⇒ 顶栏一直在（假设不成立）；")
    print("      底部分数低、顶部分数高 ⇒ **顶栏会隐藏**，取模板前必须先把光标挪上去。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
