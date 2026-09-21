"""实机验收：起游戏 → 借一次前台做完三件事 → 还前台 → 后台继续跑。

对应用户口径（2026-09-21）：允许切前台，但要在一次里点「观察」、切速度 V、解除暂停，
然后切回来让它在后台跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdx import game_auto


def main() -> int:
    game_auto.assert_no_game_running()
    hwnd = game_auto.launch(scripted_tests=True, timeout=300)
    print("hwnd =", hwnd)
    game_auto.wait_for_lobby(hwnd, timeout=420)
    print("到大堂 ✅")

    result = game_auto.start_background_session(hwnd)
    print("--- 结果 ---")
    for key, value in result.items():
        print(f"  {key:22s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
