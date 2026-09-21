"""把速度表盘模板裁准，并**当场自检匹配分数**（分数不够高就说明裁歪了）。

模板只留**扇形表盘本体**，不含右边那排圆按钮 —— 那些按钮带不带红点会变，
把它们裁进模板就会让匹配时好时坏。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from pdx import game_auto

AUTO = Path(r"C:\Users\28905\projects\Situated AI\tools\out\auto")
TEMPLATE = Path(r"C:\Users\28905\projects\Situated AI\tools\probe\zz_probe_ab\ui\btn_speed.png")

#: 扇形表盘本体（客户区坐标）：左边界留一点、右边界停在圆按钮之前。
CROP = (1700, 18, 1858, 86)
#: V 档在模板里的**相对位置**（实测 (1851,52) 是能点中的那一点，见范式文档 §4.3）。
V_REL = ((1851 - CROP[0]) / (CROP[2] - CROP[0]), (52 - CROP[1]) / (CROP[3] - CROP[1]))


def main() -> int:
    hwnd = game_auto.find_window()
    if not hwnd:
        print("游戏没在跑")
        return 2

    image = game_auto.screenshot(hwnd)
    crop = image.crop(CROP)
    crop.save(TEMPLATE)
    print(f"模板已收：{TEMPLATE}  尺寸={crop.size}  V 的相对位置={V_REL[0]:.3f},{V_REL[1]:.3f}")

    template = game_auto.load_template("btn_speed")
    print("模板尺寸（load_template 读回来的）：", template.shape)

    for image_scale in (1.0, 0.9, 1.1):
        if image_scale != 1.0:
            size = (int(image.width * image_scale), int(image.height * image_scale))
            scaled = image.resize(size)
        else:
            scaled = image
        match = game_auto.match_template(
            np.array(scaled),
            template,
            name="btn_speed",
            threshold=0.5,
            scales=game_auto.DEFAULT_SCALES,
            roi=game_auto.TOP_RIGHT_ROI,
        )
        if match is None:
            print(f"  画面缩放 {image_scale}: 没匹配上")
            continue
        width = match.box[2] - match.box[0]
        height = match.box[3] - match.box[1]
        click = (round(match.box[0] + V_REL[0] * width), round(match.box[1] + V_REL[1] * height))
        print(
            f"  画面缩放 {image_scale}: score={match.score:.3f} box={match.box} "
            f"→ 由模板算出的 V 点={click}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
