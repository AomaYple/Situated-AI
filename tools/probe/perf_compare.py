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

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
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

#: 原版 debug 覆盖层里那个「错误计数」按钮的**模板**（在 `tools/probe/zz_probe_ab/ui/`）。
#:
#: 为什么不再用颜色找按钮（2026-09-21 的做法，2026-09-23 三次实测都失败）：
#: 往 `error_deer` 里插**新**按钮画不出来（插进内层 flowcontainer ⇒ 0 像素；
#: 换成自己的 widget + 显式 size/position/textcolor ⇒ 仍然 0 像素，
#: 而 error.log 里那两条 `Unlocalized text 'CLEAR'` 证明控件**被解析了**）。
#: ⇒ 改成**覆写那个已有按钮的 `onclick`**（`perf_mod.py`），要点的就是它；
#: 而"它在哪"用**模板匹配**回答（不像坐标那样会漂）—— 自测：拿它匹配当初裁它的那张截图，
#: 分数 **1.000**、落在 (1370,500)。模板裁的是按钮左边那枚图标（60x60）。
ERROR_COUNTER_TEMPLATE = "btn_error_counter"

#: 匹配不上时的**兜底坐标**（客户区，1920x1080；实测值）。
#: 用它就意味着"这次没测到按钮在哪"，所以要在返回值里**如实报出来**（P13）。
ERROR_COUNTER_XY = (1455, 510)

MONTH_DAYS = 30.44
RUN_TIMEOUT = 900.0


def _kill_game() -> list[int]:
    pids = ga._process_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    return pids


def _set_local_mods(paths: list[Path], *, original: dict[str, object] | None = None) -> None:
    """`content_load.json` 只留这些**本地** mod（备份由 main 负责）。

    ⚠️ 三个字段都要显式写：`enabledMods`（本地 mod）+ `disabledDLC` + `enabledUGC`。
    只写 `enabledMods` 会**丢掉**用户原有的 DLC/UGC 设置 —— 那是"改了别人的配置"，
    而 P12 要求可回滚（回滚靠备份，但"跑的时候别把别的字段吃掉"是另一回事）。
    """
    base = original or {}
    payload = {
        "enabledMods": [{"path": str(p)} for p in paths],
        "disabledDLC": base.get("disabledDLC", []),
        "enabledUGC": base.get("enabledUGC", []),
    }
    CONTENT_LOAD.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def _quarantine_logs() -> list[str]:
    """把上一次会话的日志挪去临时目录 —— **两局对照必须这样做**。

    为什么：`debug.log` 按大小轮转，上一局的尾巴会留在 `debug.1.log`… 里。
    `_mounted_evidence()` 读的是"日志里有没有 Mounted Data"，跨会话残留会让
    **第二局的取证里混进第一局的挂载记录** —— 那正是"原版局看起来也挂了 mod"的假象。
    """
    target = Path(tempfile.gettempdir()) / "v3_quarantine_perflogs"
    moved: list[str] = []
    for path in sorted(LOGS.glob("*.log")):
        target.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target / path.name))
        moved.append(path.name)
    return moved


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
    moved = _quarantine_logs()
    print(f"\n===== {label}：起游戏（只挂本地 mod）=====")
    print(f"  已挪走 {len(moved)} 个旧日志（取证只可能来自这一局）")
    hwnd, previous = ga.launch_to_foreground(timeout=float(ga.WINDOW_TIMEOUT))
    settle = ga.wait_for_boot_settle(timeout=float(ga.LOBBY_TIMEOUT))
    print(f"  加载等待（不碰窗口）：{settle.why}")
    session = ga.start_session(hwnd, previous, settle=settle, force=True)
    print(f"  进局：{session.handover.describe()} speed_ok={session.rate_ok} rate={session.rate}")
    hwnd = ga._live_window(hwnd)

    advanced = _wait_months(hwnd, months)
    print(f"  跑完 {months} 个月：{advanced}")

    # 点那个被覆写过 onclick 的错误计数按钮：它**就是** dump 的触发器。
    # 位置用**模板匹配**现场测（坐标会漂），测不到才回落实测坐标 —— 且如实报出来。
    # 点击要真前台（引擎读原始输入状态），所以点完把前台还给启动前那个窗口。
    ga.ensure_foreground(hwnd, force=True)
    try:
        before = ga.screenshot(hwnd)
    except ga.CaptureFailedError as exc:
        raise ga.GameAutoError(f"{label}：点击前抓不到画面（{exc}）") from exc
    ga.save_shot(before, f"perf-{label}-before-click")
    found = ga.match_template(
        np.array(before),
        ga.load_template(ERROR_COUNTER_TEMPLATE),
        name=ERROR_COUNTER_TEMPLATE,
        threshold=0.6,
        scales=ga.DEFAULT_SCALES,
    )
    if found is not None:
        point, how = (found.x, found.y), f"模板匹配（分数 {found.score:.3f}）"
    else:
        point, how = ERROR_COUNTER_XY, "**兜底坐标**（这次没测到按钮在哪）"
    ga.click_client(hwnd, point[0], point[1], previous=previous, force=True)
    print(f"  已点错误计数按钮 @ {point} —— {how}；onclick 已被覆写成 dump，等文件出现……")
    with suppress(ga.CaptureFailedError):
        ga.ensure_foreground(hwnd, force=True)
        ga.save_shot(ga.screenshot(hwnd), f"perf-{label}-after-click")

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline and not DUMP.exists():
        time.sleep(1.0)
    if not DUMP.exists():
        raise ga.GameAutoError(
            f"{label}：点了错误计数按钮 @ {point}（{how}）但 {DUMP.name} 没出现 —— "
            "按钮没点到，或控制台命令没执行（证据帧：tools/out/auto/"
            f"perf-{label}-before-click.png 与 perf-{label}-after-click.png）"
        )
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
        "click": {"point": list(point), "how": how},
        "session": session.as_dict(),
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
    parser = argparse.ArgumentParser(description="G-EXIT-3 两局性能对照")
    parser.add_argument("months", nargs="?", type=float, default=12.0, help="每局跑几个月")
    months = parser.parse_args().months
    backup = DOCS / "content_load.json.sitai-perf-backup"
    if not CONTENT_LOAD.is_file():
        print(f"找不到 {CONTENT_LOAD}")
        return 2
    shutil.copy(CONTENT_LOAD, backup)
    original = json.loads(CONTENT_LOAD.read_text(encoding="utf-8"))
    print(f"content_load.json 已备份到 {backup.name}（收尾会还原）")

    reports: list[dict[str, object]] = []
    try:
        # 装两个本地 mod：探针（两局都要，它是 dump 按钮的宿主）+ 我们的 mod（第二局）
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "perf_mod.py")],
            check=True,
            capture_output=True,
        )
        if OURS_DST.exists():
            shutil.rmtree(OURS_DST)
        shutil.copytree(config.REPO / "mod", OURS_DST)
        print(f"已装本地 mod：{PROBE_DIR.name} + {OURS_DST.name}（复制自 {config.REPO / 'mod'}）")

        _set_local_mods([PROBE_DIR], original=original)
        reports.append(run_once("vanilla", months))

        _set_local_mods([PROBE_DIR, OURS_DST], original=original)
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
