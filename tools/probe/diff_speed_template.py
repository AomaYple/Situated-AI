"""拿**上一次会话收的模板**去匹配**现在这张截图**，看到底差多少、差在哪。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from pdx import game_auto

AUTO = Path(r"C:\Users\28905\projects\Situated AI\tools\out\auto")
BOX = (1700, 18, 1858, 86)


def main() -> int:
    hwnd = game_auto.find_window()
    if not hwnd:
        print("游戏没在跑")
        return 2
    image = np.array(game_auto.screenshot(hwnd))
    template = game_auto.load_template("btn_speed")
    print("模板 shape =", template.shape)

    match = game_auto.match_template(
        image,
        template,
        name="btn_speed",
        threshold=0.0,
        scales=game_auto.DEFAULT_SCALES,
        roi=game_auto.TOP_RIGHT_ROI,
    )
    if match is None:
        print("连低于阈值的匹配都没有")
    else:
        print(f"最佳匹配：score={match.score:.3f} box={match.box} scale={match.scale}")

    # 把"现在这块"也存下来，跟模板并排看
    now = game_auto.screenshot(hwnd).crop(BOX)
    now.save(AUTO / "speed-now.png")
    print("当前这块已存：", AUTO / "speed-now.png", now.size)
    print(
        "模板在：",
        Path(r"C:\Users\28905\projects\Situated AI\tools\probe\zz_probe_ab\ui\btn_speed.png"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
