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
    game_auto.ALLOW_REAL_INPUT = True  # 显式入口
    hwnd, previous = game_auto.launch_to_foreground(timeout=300)
    print("hwnd =", hwnd)
    settle = game_auto.wait_for_boot_settle(timeout=300)
    print(f"加载等待：{settle.why}")

    # 进观察者模式并跑起来（地图画出来之后顶栏的速度表盘才在）。
    # 用标准流程开一局，而不是自己拼点击序列 —— 那正是我们要收模板的那个界面。
    session = game_auto.start_session(hwnd, previous, settle=settle, force=True)
    print(f"进局 ✅：{session.handover.describe()}")
    hwnd = session.hwnd
    game_auto._sleep(4.0)

    AUTO.mkdir(parents=True, exist_ok=True)
    # 收模板要抓图 ⇒ 游戏必须是前台（`_grab` 的判据）；抓完再把前台还回去。
    game_auto.ensure_foreground(hwnd, force=True)
    try:
        image = game_auto.screenshot(hwnd)
    finally:
        if previous:
            game_auto._set_foreground(previous)
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
