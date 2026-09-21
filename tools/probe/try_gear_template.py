"""换思路：不拿"整扇"当模板（它会跟着"运行/暂停 + 当前速度"变色），
改用**中央那枚金色齿轮** —— 它是装饰件，状态无关；表盘的位置由它反推。

本脚本：
1. 从当前截图裁出齿轮，存成候选模板；
2. 拿它去匹配**上一局（暂停态）**留下的整张截图，看分数 —— 高就说明它真的与状态无关；
3. 顺带算出 "V 档点在齿轮框里的相对位置"，供 `speed_widget_xy` 用。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from pdx import game_auto

AUTO = Path(r"C:\Users\28905\projects\Situated AI\tools\out\auto")
#: 齿轮（客户区坐标）—— 由 `speed-now.png` 目测：扇形中央那枚金色齿轮。
GEAR_BOX = (1788, 56, 1838, 86)


def main() -> int:
    hwnd = game_auto.find_window()
    if not hwnd:
        print("游戏没在跑")
        return 2

    running = game_auto.screenshot(hwnd)
    gear = running.crop(GEAR_BOX)
    gear.save(AUTO / "gear-template.png")
    print(f"齿轮候选模板：{gear.size}  客户区 {GEAR_BOX}")

    template = np.array(gear)

    # 拿上一局（暂停态）的整张截图当"另一个状态"
    old = AUTO / "speed-full.png"
    if old.is_file():
        with Image.open(old) as im:
            old_arr = np.array(im.convert("RGB"))
        match = game_auto.match_template(
            old_arr, np.ascontiguousarray(template), name="齿轮", threshold=0.0, scales=(1.0,)
        )
        if match is None:
            print("在暂停态截图里：完全没匹配上")
        else:
            print(f"在**暂停态**截图里：score={match.score:.3f} box={match.box}")
    else:
        print("没有旧的截图可比（speed-full.png 不在）")

    # V 档点相对齿轮框的位置
    vx, vy = game_auto.SPEED_V_XY
    print(
        "V 档点相对齿轮框左上角：",
        (vx - GEAR_BOX[0], vy - GEAR_BOX[1]),
        " 相对框中心：",
        (vx - (GEAR_BOX[0] + GEAR_BOX[2]) / 2, vy - (GEAR_BOX[1] + GEAR_BOX[3]) / 2),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
