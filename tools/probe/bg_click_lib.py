"""后台点击 · 成熟库版复试（判据 = 逐 tick 真值，不是像素）。

## 为什么还要再测一次

2026-09-21 已经测死过三条**消息注入**路线（`PostMessage`、`SendMessage`、
`SendMessage` + `WM_ACTIVATE`/`WM_SETFOCUS`）：三种变体点完，「观察」按钮的匹配分数
**一动不动**（0.855），结论是引擎读**原始输入状态**。但那三条都是**手写 ctypes** 拼出来的。
换成成熟库之后，能力面重新盘了一遍（`tools/probe/` 里同一批脚本 + 库内省），有两件事变了：

* `win32process.AttachThreadInput` **存在**（pywin32 暴露了）—— 于是"把我们的输入队列
  接到游戏线程上，再 `SetFocus`，然后投**真实输入**（`pydirectinput`）"这条路
  **以前没测过**：它既不是消息注入，也**不调用** `SetForegroundWindow`，
  所以理论上可以不抢前台；
* `CreateDesktop` / `SetThreadDesktop` **不存在** —— 真·隔离桌面（游戏在另一个桌面上
  自带前台）这条路，纯成熟库走不通，必须回到 ctypes，按用户口径**不做**。

## 判据（这次换成硬真值）

不用像素：`ImageGrab` 只能抓**前台**窗口，而被测场景恰恰是"游戏不在前台"，
拿被遮挡的像素判分是**静默错误**（P5 不许）。改用**游戏自己的逐 tick 真值**：

* 选国家大厅是**暂停**的 ⇒ `dedicated_server.log` **不写 tick**（实测）；
* 点中「观察」⇒ 进入观察者局、时间开始走 ⇒ 日志里**出现 tick 行**。

所以"点完之后 N 秒内出现 tick"= 点击**确实生效**（单向判据：出现即成功；
不出现不能反推失败，见文末 ⚠️）。

## 对照组（必须有，否则判据本身没被验过）

① 库路线点击（不抢前台）→ 看有没有 tick；
② 真·前台借用点击（已知可行）→ 看有没有 tick。
② 就是**判据的阳性对照**：如果 ② 也判不出 tick，那说明判据坏了，而不是"点击没用"。

## 用法

    .venv\\Scripts\\python.exe -m pdx.probe_runner tools/probe/bg_click_lib.py
或在仓库根：

    .venv\\Scripts\\python.exe tools/probe/bg_click_lib.py

**前置条件**：游戏已经起好、停在选国家界面（`-scripted_tests` 流水线会自己走到那里）。
脚本自己会借一次前台**只为定位按钮**（截图必须前台），拿到坐标后立刻把前台还回去，
然后才开始后台点击测试。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pydirectinput
import win32api
import win32con
import win32gui
import win32process

from pdx import game_auto as ga

#: 点完之后给游戏多少秒才看日志（观察者局一开始就跑，实测几秒内就有 tick）。
TICK_WINDOW = 10.0
#: 日志里 tick 行的采样间隔。
TICK_POLL = 0.5


def _safe_foreground() -> int:
    return ga._foreground_window()


def _tick_seen(before: ga.TickMark, seconds: float) -> ga.Advance:
    """等 tick 出现/推进 —— **条件等待**，等到就立刻返回（不固定 sleep）。"""
    after = ga.tick_mark()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        after = ga.tick_mark()
        if after.readable and (not before.readable or ga.is_later(before.tick, after.tick)):
            break
        time.sleep(TICK_POLL)
    return ga.Advance(
        advanced=after.readable and (not before.readable or ga.is_later(before.tick, after.tick)),
        before=before.tick,
        after=after.tick,
        seconds=seconds,
        source="dedicated_server.log",
    )


def _raise_without_activate(hwnd: int) -> bool:
    """把游戏窗口提到 Z 序最前但**不激活**它（焦点仍留给用户）。"""
    try:
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOP, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        )
        return True
    except Exception as exc:
        print(f"  ⚠️ 置顶失败：{type(exc).__name__}: {exc}")
        return False


def _attach_and_click(hwnd: int, x: int, y: int) -> dict[str, Any]:
    """库路线：接输入队列 → `SetFocus` → 投真实输入（**不** `SetForegroundWindow`）。"""
    me = win32api.GetCurrentThreadId()
    game_tid, game_pid = win32process.GetWindowThreadProcessId(hwnd)
    front_before = _safe_foreground()
    result: dict[str, Any] = {
        "our_tid": me,
        "game_tid": game_tid,
        "game_pid": game_pid,
        "foreground_before": front_before,
    }
    attached = False
    try:
        attached = bool(win32process.AttachThreadInput(me, game_tid, True))
        result["attached"] = attached
        try:
            win32gui.SetFocus(hwnd)
            result["set_focus"] = "ok"
        except Exception as exc:
            result["set_focus"] = f"{type(exc).__name__}: {exc}"
        origin = ga._client_origin(hwnd)
        pydirectinput.moveTo(origin[0] + x, origin[1] + y)
        pydirectinput.click()
    finally:
        if attached:
            win32process.AttachThreadInput(me, game_tid, False)
        # 焦点还给用户（探针也不许把用户的前台留在游戏上）。
        if front_before and front_before != hwnd:
            win32gui.SetForegroundWindow(front_before)
    result["foreground_after"] = _safe_foreground()
    result["foreground_stayed_with_user"] = result["foreground_after"] == front_before
    return result


def _real_foreground_click(hwnd: int, x: int, y: int) -> dict[str, Any]:
    """对照组：真·借前台点一次（已验证可行的那条路）。"""
    previous = _safe_foreground()
    ga.ensure_foreground(hwnd, force=True)
    try:
        origin = ga._client_origin(hwnd)
        pydirectinput.moveTo(origin[0] + x, origin[1] + y)
        pydirectinput.click()
    finally:
        if previous and previous != hwnd:
            win32gui.SetForegroundWindow(previous)
    return {"borrowed": True, "foreground_restored": _safe_foreground() == previous}


def main() -> int:
    ga.ALLOW_REAL_INPUT = True  # 探针是显式入口：允许借前台（只为定位按钮）
    hwnd = ga.find_window()
    if not hwnd:
        print("❌ 找不到游戏窗口 —— 先起游戏（`v3 game launch`）并等它停在选国家界面")
        return 2

    baseline = ga.tick_mark()
    print(f"窗口 hwnd={hwnd}；日志 tick 基线 = {baseline.tick or '<读不到>'}")

    # ① 借一次前台**只为定位按钮**（截图必须前台，P5：不拿被遮挡的像素判界面）
    previous = _safe_foreground()
    ga.ensure_foreground(hwnd, force=True)
    try:
        shot = ga.screenshot(hwnd, roi=ga.BOTTOM_ROI)
        match = ga.locate(shot, "btn_observe")
        point = (match.x, match.y)
        print(f"✅ 定位到「观察」按钮：客户区坐标 {point}，分数 {match.score:.3f}")
    except Exception as exc:
        print(f"❌ 定位失败：{type(exc).__name__}: {exc}")
        return 3
    finally:
        if previous and previous != hwnd:
            win32gui.SetForegroundWindow(previous)
        time.sleep(0.5)

    report: dict[str, Any] = {"observe_point": point, "baseline_tick": baseline.tick}

    # ② 库路线：不抢前台，靠 AttachThreadInput + SetFocus + 真实输入
    print("\n[1/2] 库路线：AttachThreadInput + SetFocus + pydirectinput（不抢前台）")
    print(f"  置顶但不激活：{_raise_without_activate(hwnd)}")
    time.sleep(0.5)
    report["library_route"] = _attach_and_click(hwnd, *point)
    advance = _tick_seen(baseline, TICK_WINDOW)
    report["library_route"]["tick"] = advance.describe()
    report["library_route"]["clicked"] = advance.advanced
    print(f"  判据：{advance.describe()} → {'✅ 点击生效' if advance.advanced else '❌ 没有 tick'}")

    if advance.advanced:
        print("\n🎉 库路线**成功**：不抢前台也能点到游戏")
        report["verdict"] = "library-route-works"
    else:
        # ③ 对照组：真前台点一次，验证"判据本身是对的"
        print("\n[2/2] 对照组：真·借前台点一次（判据的阳性对照）")
        report["control_route"] = _real_foreground_click(hwnd, *point)
        control = _tick_seen(baseline, TICK_WINDOW)
        report["control_route"]["tick"] = control.describe()
        report["control_route"]["clicked"] = control.advanced
        print(
            f"  判据：{control.describe()} → {'✅ 点击生效' if control.advanced else '❌ 没有 tick'}"
        )
        if control.advanced:
            report["verdict"] = "library-route-fails-control-succeeds"
            print("\n结论：后台点击（库路线）**不生效**，而前台点击生效 —— 判据有效，结论可信")
        else:
            report["verdict"] = "judge-invalid"
            print("\n⚠️ 对照组也没 tick ⇒ **判据本身没被验过**，本次实验作废（不许当结论用）")

    out = Path(__file__).resolve().parents[1] / "out" / "auto" / "bg_click_lib.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n证据：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
