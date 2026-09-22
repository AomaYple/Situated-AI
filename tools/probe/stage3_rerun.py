"""阶段 3 重做的实机实验：把真 mod（+ 探针）装进本地 mod 目录跑一局，读数从引擎日志里取。

为什么要有这个脚本（而不是手敲一串命令）
----------------------------------------
一次实机实验要动**用户目录**（`content_load.json` 与 `mod/`），而用户原来那 23 条
Workshop 配置**一个字都不能改**。所以"备份 → 改 → 跑 → 还原"必须是**代码**，
且还原写在 `finally` 里（P12 可回滚；阶段 4 踩过"失败时留下一个进程挡住下一局"）。

判据（全部来自**引擎自己写的** `debug.log`，不是我们的自报）
----------------------------------------------------------
* `ZZPROBE AB;STRATEGY;<牌名>;RUS` —— 俄罗斯逐月挂着哪张政治牌（B53 之后这是行为层读数）；
* `ZZPROBE AB;JE;active;RUS` —— 改革窗口开没开；
* `ZZPROBE AB;LAW;<法名>;RUS` —— 当前生效的改革相关法律；
* `ZZPROBE AB;SHOCK;yes;RUS` —— 战败记忆变量在不在。

用法
----
    python tools/probe/stage3_rerun.py --months 96          # 跑 96 个游戏月
    python tools/probe/stage3_rerun.py --months 96 --analyze-only

⚠️ 只启用**本地** mod（清空 `enabledMods` 再写我们两条）：阶段 4 实测"本地 mod 混着
23 条 Workshop 条目"时本地 mod 不会被挂载（backlog B39）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdx import ab_probe, config
from pdx import game_auto as ga

DOCS = Path.home() / "Documents" / "Paradox Interactive" / "Victoria 3"
MODS_DIR = DOCS / "mod"
CONTENT_LOAD = DOCS / "content_load.json"
BACKUP = DOCS / "content_load.json.sitai-backup"
DEBUG_LOG = DOCS / "logs" / "debug.log"
OURS = MODS_DIR / "sitai_sitai"
PROBE = MODS_DIR / "zz_probe_ab"

#: 一天的推进量换算（与 `game_auto.tick_day` 同口径：够算月份就行）。
MONTH_DAYS = 30.44


def deploy() -> str:
    """装本地 mod 并改写 `content_load.json`；返回一句人读的说明。

    **先备份**（只备一次：反复跑时不会被"已改过的版本"覆盖掉真正的原始配置）。
    """
    if not BACKUP.exists():
        shutil.copy2(CONTENT_LOAD, BACKUP)
    original = json.loads(CONTENT_LOAD.read_text(encoding="utf-8"))
    for target in (OURS, PROBE):
        if target.exists():
            shutil.rmtree(target)
    shutil.copytree(config.REPO / "mod", OURS)
    # ⚠️ 用 `ab_probe.write` 而**不是** `ab_probe.deploy`：后者会调
    # `experiments.set_enabled_mods()` 自己改写 `content_load.json`，而这里要保住
    # 用户原来那 23 条 Workshop 配置（本脚本自己写那个文件，只启用两个本地 mod）。
    ab_probe.write(root=PROBE)
    payload = {
        "enabledMods": [{"path": str(OURS)}, {"path": str(PROBE)}],
        "disabledDLC": original.get("disabledDLC", []),
        "enabledUGC": [],
    }
    CONTENT_LOAD.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return (
        f"已装本地 mod：{OURS.name} + {PROBE.name}；"
        f"原配置（{len(original.get('enabledMods', []))} 条 Workshop）备份在 {BACKUP.name}"
    )


def restore() -> str:
    """还原 `content_load.json` 并删掉我们装进去的两个本地 mod 目录。"""
    notes: list[str] = []
    if BACKUP.exists():
        shutil.copy2(BACKUP, CONTENT_LOAD)
        notes.append("content_load.json 已还原")
    else:  # pragma: no cover - 没备份就没得还原，如实说
        notes.append("⚠️ 没有备份可还原")
    for target in (OURS, PROBE):
        if target.exists():
            shutil.rmtree(target)
            notes.append(f"已删 {target.name}")
    return "；".join(notes)


def kill_game() -> list[int]:
    pids = ga._process_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    return pids


def _months_of(tick: str) -> float:
    """把 tick 折成"开局以来的月数"（够排时间线就行）。"""
    day = ga.tick_day(tick)
    return 0.0 if day is None else day / MONTH_DAYS


def wait_months(target: float, *, poll: float = 20.0, timeout: float = 3600.0) -> str:
    """等到游戏时间走过 ``target`` 个月（读 tick 真值，**不看墙钟**）。"""
    started = time.monotonic()
    mark = ga.tick_mark()
    while time.monotonic() - started < timeout:
        mark = ga.tick_mark()
        if mark.readable and _months_of(mark.tick) >= target:
            return mark.tick
        time.sleep(poll)
    return mark.tick  # 超时也如实返回走到了哪


def analyze(log: Path | None = None) -> dict[str, object]:
    """从 `debug.log` 里取读数：逐月时间线 + 每次变化。

    判据口径（先写死，避免事后挑对自己有利的读法）：
    * **成功** = `LAW;<非 law_serfdom>` 出现过（法律真的换了）；
    * **牌闸门成立** = `STRATEGY;ai_strategy_progressive_agenda` 出现过；
    * **窗口开过** = `JE;active` 出现过。
    """
    path = log or DEBUG_LOG
    text = path.read_text(encoding="utf-8", errors="replace")
    ours = [line for line in text.splitlines() if "ZZPROBE AB;" in line]
    kinds: Counter[str] = Counter()
    timeline: list[tuple[str, str]] = []
    for line in ours:
        body = line.split("ZZPROBE AB;", 1)[1].split('"', 1)[0]
        parts = body.split(";")
        kinds[parts[0]] += 1
        timeline.append((parts[0], parts[1] if len(parts) > 1 else ""))
    laws = [value for kind, value in timeline if kind == "LAW"]
    strategies = [value for kind, value in timeline if kind == "STRATEGY"]
    je = [value for kind, value in timeline if kind == "JE"]
    shocks = [value for kind, value in timeline if kind == "SHOCK"]

    def first_change(values: list[str]) -> str:
        seen = ""
        for value in values:
            if value != seen:
                seen = value
                return value
        return ""

    law_switched = any(law not in {"law_serfdom", "none"} for law in laws)
    return {
        "总行数": len(ours),
        "分类计数": dict(kinds),
        "法律读数（去重，按出现顺序）": _dedupe(laws),
        "策略牌读数（去重，按出现顺序）": _dedupe(strategies),
        "窗口读数（去重）": _dedupe(je),
        "冲击读数（去重）": _dedupe(shocks),
        "第一次非农奴制": next((law for law in laws if law not in {"law_serfdom", "none"}), ""),
        "第一次进步牌": first_change(
            [s for s in strategies if s == "ai_strategy_progressive_agenda"]
        ),
        "✅ 法律真的换了": law_switched,
        "✅ 进步牌挂上过": "ai_strategy_progressive_agenda" in strategies,
        "✅ 窗口开过": "active" in je,
        "✅ 冲击施加过": "yes" in shocks,
    }


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if not out or out[-1] != value:
            out.append(value)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stage3_rerun", description=__doc__)
    parser.add_argument("--months", type=float, default=96.0, help="跑到第几个游戏月")
    parser.add_argument("--speed-xy", default="", help="显式指定速度档 V 的坐标")
    parser.add_argument("--analyze-only", action="store_true", help="只分析已有日志，不起游戏")
    parser.add_argument("--keep-installed", action="store_true", help="跑完不还原 mod 配置")
    args = parser.parse_args(argv)

    if args.analyze_only:
        for key, value in analyze().items():
            print(f"  {key:34s}: {value}")
        return 0

    ga.ALLOW_REAL_INPUT = True  # 显式入口
    leftover = ga._process_pids()
    if leftover:
        print(f"⚠️ 起前有残留 victoria3：{leftover} —— 先收掉")
        kill_game()
        time.sleep(3)

    print(deploy())
    report: dict[str, object] = {}
    failure = ""
    previous = ga._foreground_window()
    try:
        hwnd, previous = ga.launch_to_foreground(scripted_tests=True, timeout=300.0)
        print(f"窗口 hwnd={hwnd}；等加载……")
        settle = ga.wait_for_boot_settle(timeout=400.0)
        print(f"  {settle.why}")
        speed_xy: tuple[int, int] | None = None
        if args.speed_xy:
            left, _, right = str(args.speed_xy).partition(",")
            speed_xy = (int(left), int(right))
        session = ga.start_session(hwnd, previous, settle=settle, speed_xy=speed_xy, force=True)
        print(f"  进局：{session.handover.describe()}；速率 {session.rate} 天/秒")
        report["session"] = session.as_dict()
        print(f"跑到第 {args.months:.0f} 个游戏月（tick 真值，不看墙钟）……")
        tick = wait_months(args.months)
        print(f"  现在 tick={tick or '<读不到>'}（≈{_months_of(tick):.1f} 个月）")
        report["tick"] = tick
        report["analysis"] = analyze()
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        killed = kill_game()
        time.sleep(2)
        if previous:
            ga._set_foreground(previous)
        if not args.keep_installed:
            print(f"收尾：杀掉 {killed or '（没有）'}；{restore()}")
        else:
            print(f"收尾：杀掉 {killed or '（没有）'}；**按 --keep-installed 保留安装**")

    if failure:
        print(f"\n[失败] {failure}")
        return 1
    print("\n=== 读数（判据口径见脚本 docstring）===")
    for key, value in (report.get("analysis") or {}).items():  # type: ignore[union-attr]
        print(f"  {key:34s}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
