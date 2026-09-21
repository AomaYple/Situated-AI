"""挑一个**跟指针位置无关**的速度表盘模板。

背景：第一版模板把整个扇形（含指针）裁进去了 —— 指针位置随当前速度变，
换一局（速度不同）就匹配不上，实机已经踩到（`TemplateNotFoundError`）。

做法：抓两张**速度不同**的截图（当前档 vs 点过 V 档之后），对若干候选裁剪区域
分别算两次的匹配分数，**取两边的较小值**当"稳健性" —— 越小越说明该区域随状态变。
选稳健性最高、又够独特的那个当模板。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from pdx import game_auto

AUTO = Path(r"C:\Users\28905\projects\Situated AI\tools\out\auto")

#: 候选裁剪（客户区坐标）：整扇 / 右半（含 IV V）/ 上缘 / 右缘条
CANDIDATES: dict[str, tuple[int, int, int, int]] = {
    "整扇（含指针）": (1700, 18, 1858, 86),
    "右半（IV V 与右缘）": (1778, 18, 1858, 86),
    "右上（V 与上缘）": (1790, 14, 1858, 56),
    "右缘条": (1806, 20, 1858, 84),
    "左下（绿三角）": (1700, 46, 1760, 86),
}


def score(image_arr: np.ndarray, box: tuple[int, int, int, int]) -> float:
    crop = image_arr[box[1] : box[3], box[0] : box[2]]
    match = game_auto.match_template(
        image_arr,
        np.ascontiguousarray(crop),
        name="候选",
        threshold=0.0,
        scales=(1.0,),
        roi=game_auto.TOP_RIGHT_ROI,
    )
    return 0.0 if match is None else round(match.score, 3)


def main() -> int:
    hwnd = game_auto.find_window()
    if not hwnd:
        print("游戏没在跑")
        return 2

    current = np.array(game_auto.screenshot(hwnd))
    game_auto.save_shot(game_auto.screenshot(hwnd), "speed-候选-当前档")

    # 用**已知能点中**的坐标把速度切到 V，再抓一张
    game_auto.ensure_foreground(hwnd)
    game_auto.click_client(hwnd, *game_auto.SPEED_V_XY, give_back=False)
    game_auto._sleep(1.5)
    at_v = np.array(game_auto.screenshot(hwnd))
    game_auto.save_shot(game_auto.screenshot(hwnd), "speed-候选-V档")

    print(f"{'候选区域':22s} {'当前档':>8s} {'V 档':>8s} {'稳健性(取小)':>12s}")
    for name, box in CANDIDATES.items():
        a = score(current, box)
        b = score(at_v, box)
        print(f"{name:22s} {a:8.3f} {b:8.3f} {min(a, b):12.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
