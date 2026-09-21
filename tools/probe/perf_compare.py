"""G-EXIT-3 对照表驱动：**原版一局 vs 装我们 mod 一局**（同口径 clear → 跑 N 月 → dump）。

## 口径（照 `阶段4-性能仪表侦察.md` 第四节）

1. 只启用**本地** mod（B39：混着 Workshop 条目时本地 mod 不会被挂载）；
2. 两局都：后台启动 → 等启动忙完（不碰窗口）→ 闭环进观察者局（观察 / 5 档 / 空格）；
3. 点 `CLEAR`（清掉开局加载那段）→ 跑 **N 个月** → 点 `DUMP`，把 `ticktask_timings.csv`
   另存为 `tools/out/perf/<label>.csv`；
4. 报关键任务（尤其 `RecalculateModifierNodes` —— 我们的档案加的就是 static modifier）
   的**均值 / 最坏帧**，以及每帧合计。

⚠️ **非受控对照**（要标清楚）：没有固定存档 + 固定指令序列，两局不是同一个世界；
结论只能读"量级与方向"，不能读成"精确差值"。

## 收尾（P12/可回滚）

`finally` 里：杀游戏 → 还原 `content_load.json`（先备份）→ 删掉本脚本装进去的两个本地 mod。
**用户原来的 23 条 Workshop 配置一个字都不改。**

用法：`python tools/probe/perf_compare.py [月数]`
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from pdx import config, gametimer
from pdx import game_auto as ga

DOCS = Path.home() / "Documents" / "Paradox Interactive" / "Victoria 3"
MODS_DIR = DOCS / "mod"
CONTENT_LOAD = DOCS / "content_load.json"
DUMP = DOCS / "ticktask_timings.csv"
PROBE_DIR = MODS_DIR / "zz_sitai_perf"
OURS_DST = MODS_DIR / "sitai_sitai"
OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "perf"
LOGS = DOCS / "logs"

#: 与 `tools/probe/perf_mod.py` 里的按钮颜色**必须一致**（改一处要改两处）。
CLEAR_RGB = (255, 0, 255)
DUMP_RGB = (0, 255, 255)

MONTH_DAYS = 30.44
RUN_TIMEOUT = 900.0


def _find_color_center(
    hwnd: int, want: tuple[int, int, int], *, tolerance: int = 40
) -> tuple[int, int] | None:
    """抓一张客户区图，找目标颜色的**质心** —— 探针按钮就是那块色，不猜坐标。

    为什么要这样：按钮插在原版 `error_deer` 的 flowcontainer 里，位置取决于前面控件的
    高度（`size = { 0 0 }` 自动尺寸 + `spacing`），算不出来；而给它涂上唯一颜色之后，
    "哪块像素是按钮"就变成可测的事实。色块太小（< 200 像素）当作没找到，防噪点。
    """
    try:
        image = np.array(ga.screenshot(hwnd))
    except ga.CaptureFailedError:
        return None
    diff = np.abs(image.astype(np.int16) - np.array(want, dtype=np.int16)).sum(axis=2)
    ys, xs = np.where(diff <= tolerance)
    if len(xs) < 200:
        return None
    return (int(xs.mean()), int(ys.mean()))


def _wait_color_center(
    hwnd: int, want: tuple[int, int, int], *, timeout: float = 60.0
) -> tuple[int, int]:
    """等按钮出现（按颜色找），超时抛错 —— 不猜、也不静默继续。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _find_color_center(hwnd, want)
        if found is not None:
            return found
        time.sleep(1.0)
    raise ga.GameAutoError(f"{timeout:.0f} 秒内没找到颜色 {want} 的按钮 —— 探针 mod 挂上了吗？")


def _kill_game() -> list[int]:
    pids = ga._process_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    return pids


def _set_local_mods(paths: list[Path]) -> None:
    """content_load.json 只留这些**本地** mod（先备份由 main 负责）。"""
    payload = {"enabledMods": [{"path": str(p)} for p in paths]}
    CONTENT_LOAD.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def _mounted_evidence() -> list[str]:
    """从日志里取"挂了什么"的证据（B39 的判据就是这一行）。"""
    hits: list[str] = []
    for name in ("debug.log", "system.log"):
        path = LOGS / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits.extend(
            f"{name}: {line.strip()[:160]}"
            for line in text.splitlines()
            if "Mounted Data" in line or "sitai" in line.lower()
        )
    return hits[-8:]


def _wait_months(hwnd: int, months: float) -> dict[str, object]:
    """等时间推进 ``months`` 个月（按逐 tick 真值算天数，条件等待，不猜）。"""
    start = ga.tick_mark()
    start_day = ga.tick_day(start.tick)
    target = months * MONTH_DAYS
    deadline = time.monotonic() + RUN_TIMEOUT
    last = start_day
    while time.monotonic() < deadline:
        if not hwnd or not ga._is_visible(hwnd) or ga.find_window() != hwnd:
            return {
                "from": start.tick,
                "to": "<窗口没了或换了>",
                "days": last,
                "months": months,
                "window_gone": True,
            }
        mark = ga.tick_mark()
        day = ga.tick_day(mark.tick)
        if day is not None and start_day is not None and day - start_day >= target:
            return {
                "from": start.tick,
                "to": mark.tick,
                "days": round(day - start_day, 1),
                "months": months,
            }
        last = day
        time.sleep(5.0)
    return {
        "from": start.tick,
        "to": ga.tick_mark().tick,
        "days": last,
        "months": months,
        "timeout": True,
    }


def run_once(label: str, months: float) -> dict[str, object]:
    """跑一局并取一份 dump。调用方负责 content_load 与 mod 目录已就位。"""
    ga.assert_no_game_running()
    if DUMP.exists():
        DUMP.unlink()  # 清掉旧的，靠"文件重新出现"判断 dump 成功
    print(f"\n===== {label}：起游戏（只挂本地 mod）=====")
    hwnd = ga.launch(scripted_tests=True, timeout=float(ga.WINDOW_TIMEOUT))
    settle = ga.wait_for_boot_settle(timeout=float(ga.LOBBY_TIMEOUT))
    print(f"  加载等待（不碰窗口）：{settle.why}")
    session = ga.start_background_session(hwnd, force=True)
    print(
        f"  进局：borrows={session['borrows']} borrow_seconds={session['borrow_seconds']} "
        f"speed_ok={session['speed_ok']} rate={session['speed_days_per_second']}"
    )
    hwnd = ga._live_window(hwnd)

    clear_at = _wait_color_center(hwnd, CLEAR_RGB)
    ga.click_client_nosteal(hwnd, clear_at[0], clear_at[1], force=True)
    print(f"  已点 CLEAR @ {clear_at}（清掉开局加载那段计数）")
    advanced = _wait_months(hwnd, months)
    print(f"  跑完 {months} 个月：{advanced}")
    dump_at = _wait_color_center(hwnd, DUMP_RGB)
    ga.click_client_nosteal(hwnd, dump_at[0], dump_at[1], force=True)
    print(f"  已点 DUMP @ {dump_at}，等文件出现……")

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline and not DUMP.exists():
        time.sleep(1.0)
    if not DUMP.exists():
        raise ga.GameAutoError(f"{label}：点了 DUMP 但 {DUMP.name} 没出现")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{label}.csv"
    shutil.copy(DUMP, target)
    print(f"  dump 已另存：{target}（{target.stat().st_size} 字节）")

    report: dict[str, object] = {
        "label": label,
        "csv": str(target),
        "bytes": target.stat().st_size,
        "months": months,
        "advanced": advanced,
        "session": {
            "borrows": session["borrows"],
            "borrow_seconds": session["borrow_seconds"],
            "speed_ok": session["speed_ok"],
            "rate": session["speed_days_per_second"],
        },
        "mounted": _mounted_evidence(),
    }
    _kill_game()
    time.sleep(3)
    return report


def _key_lines(csv: Path, tasks: tuple[str, ...] = ("RecalculateModifierNodes",)) -> list[str]:
    lines = gametimer.ticktask_summary_lines(csv)
    wanted = [
        line
        for line in lines
        if any(task in line for task in tasks) or "每帧各任务合计" in line or "帧 " in line
    ]
    return wanted or lines[:6]


def main() -> int:
    # 探针是**显式入口**：按设计打开真实输入授权（`pdx.game_auto` 的闸门说的就是这件事）。
    ga.ALLOW_REAL_INPUT = True
    months = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    backup = DOCS / "content_load.json.sitai-perf-backup"
    if not CONTENT_LOAD.is_file():
        print(f"找不到 {CONTENT_LOAD}")
        return 2
    shutil.copy(CONTENT_LOAD, backup)
    print(f"content_load.json 已备份到 {backup.name}（收尾会还原）")

    reports: list[dict[str, object]] = []
    try:
        # 装两个本地 mod：探针（两局都要）+ 我们的 mod（第二局）
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "perf_mod.py")],
            check=True,
            capture_output=True,
        )
        if OURS_DST.exists():
            shutil.rmtree(OURS_DST)
        shutil.copytree(config.REPO / "mod", OURS_DST)
        print(f"已装本地 mod：{PROBE_DIR.name} + {OURS_DST.name}（复制自 {config.REPO / 'mod'}）")

        _set_local_mods([PROBE_DIR])
        reports.append(run_once("vanilla", months))

        _set_local_mods([PROBE_DIR, OURS_DST])
        reports.append(run_once("ours", months))
    finally:
        killed = _kill_game()
        shutil.copy(backup, CONTENT_LOAD)
        backup.unlink(missing_ok=True)
        for path in (PROBE_DIR, OURS_DST):
            if path.exists():
                shutil.rmtree(path)
        print(
            f"\n[收尾] 杀游戏 {killed or '（没有）'}；content_load.json 已还原；两个本地 mod 已删除"
        )

    print("\n===== G-EXIT-3 对照（非受控：两局不是同一个世界，只读量级与方向）=====")
    for report in reports:
        print(f"\n--- {report['label']} ---")
        for line in _key_lines(Path(str(report["csv"]))):
            print(f"  {line}")
        print(f"  挂了什么（日志取证）：{report['mounted'][-3:]}")
    out = OUT_DIR / "compare.json"
    out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n证据：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
