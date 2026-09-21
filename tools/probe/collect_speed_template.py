"""收「速度表盘」模板：起游戏 → 进观察者 → 截图 → 裁出顶栏右侧那块。

为什么不再用硬编码坐标：`(1851, 52)` 只在这一台机器/这一刻的布局下成立（分辨率、
UI 缩放、界面语言、窗口大小一变就落空）。「观察」「播放」两个按钮早就是**模板匹配**，
速度控件也应该走同一条路。

产物：
* `tools/out/auto/speed-full.png` —— 整张客户端截图（留档，抄坐标/裁模板用）；
* `tools/out/auto/speed-crop.png` —— 裁出来的候选区域（人看一眼确认裁对了）；
* `tools/probe/zz_probe_ab/ui/btn_speed.png` —— 收进模板目录的那一份。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from pdx import game_auto

AUTO = Path(r"C:\Users\28905\projects\Situated AI\tools\out\auto")
TEMPLATE = Path(r"C:\Users\28905\projects\Situated AI\tools\probe\zz_probe_ab\ui\btn_speed.png")

#: 顶栏右侧的候选区域（客户区坐标）。范式文档 §4.3 的实测把「播放」放在 (1725,54)、
#: 速度 V 放在 (1851,52)，所以这块一定落在这里面 —— 先裁大一点，人看一眼再收紧。
CROP = (1690, 20, 1920, 90)


def main() -> int:
    game_auto.assert_no_game_running()
    hwnd = game_auto.launch(scripted_tests=True, timeout=300)
    print("hwnd =", hwnd)
    game_auto.wait_for_lobby(hwnd, timeout=420)
    print("到大堂 ✅")

    # 进观察者模式（地图画出来之后顶栏的速度表盘才在）
    game_auto.click_observer(hwnd)
    print("已点观察 ✅，等界面定型…")
    game_auto._sleep(4.0)

    AUTO.mkdir(parents=True, exist_ok=True)
    image = game_auto.screenshot(hwnd)
    full = AUTO / "speed-full.png"
    image.save(full)
    print("整张截图：", full, image.size)

    crop = image.crop(CROP)
    crop_path = AUTO / "speed-crop.png"
    crop.save(crop_path)
    print("候选区域：", crop_path, crop.size, f"（客户区 {CROP}）")

    TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    crop.save(TEMPLATE)
    print("模板已收：", TEMPLATE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
