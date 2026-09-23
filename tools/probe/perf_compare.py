"""G-EXIT-3 对照表驱动：**原版一局 vs 装我们 mod 一局**（同口径 clear → 跑 N 月 → dump）。

## 口径（照 `阶段4-性能仪表侦察.md` 与 backlog B66）

1. **只启用本地 mod**（B39：混着 Workshop 条目时本地 mod 不会被挂载）——
   基线局 `enabledMods` 留空（真正的原版），处理局只放我们的 mod；
2. 两局都：**前台**起游戏 → 等启动忙完（不碰窗口）→ 闭环进观察者局（观察 / 5 档 / 空格）；
3. **用控制台**（引擎自带仪表的唯一入口，B66）：
   `clear_ticktask_timings`（丢掉开局加载那一段，窗口才有界）→ 跑 **N 个月**
   → `dump_ticktask_timings` 落盘 `ticktask_timings.csv` → 另存成
   `tools/out/perf/<label>.csv`；
4. 报关键任务（尤其 `RecalculateModifierNodes` —— 我们的档案加的就是 static modifier）
   的**均值 / 最坏帧**，以及每帧合计。

⚠️ **非受控对照**（要标清楚）：没有固定存档 + 固定指令序列，两局不是同一个世界；
结论只能读"量级与方向"，不能读成"精确差值"。

## 收尾（P12/可回滚）

`finally` 里：杀游戏 → 还原 `content_load.json`（先备份）→ 删掉本脚本装进去的本地 mod。
**用户原来的 23 条 Workshop 配置一个字都不改。**

⚠️ **跑完之后请再跑一局常规游戏**（`python -m pdx.game_auto run`，用用户自己的 mod 配置）：
本脚本的两局都是"只挂本地 mod"，引擎日志因此是在**另一套 mod 集**下产生的，而
`tools/tests/test_cli.py::test_crosscheck_与引擎日志一致` 拿日志行号与原版安装比对 ——
mod 集不同会让它红（实测踩过）。跑一局常规游戏即可让日志与安装一致。

用法：`python tools/probe/perf_compare.py [月数] [--repeat N]`
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from pdx import ab_probe, config, gametimer, stress_probe
from pdx import game_auto as ga

DOCS = config.USERDIR
MODS_DIR = DOCS / "mod"
CONTENT_LOAD = DOCS / "content_load.json"
LOGS = DOCS / "logs"

#: 标准压力剧本（阶段 4 ④）在用户 mod 目录里的落点。`--stress` 时**两臂都装它** ——
#: 单装一臂就等于把"世界被推到高压"这件事算进了那一臂的差里，对照立刻作废。
STRESS_DST = stress_probe.dest()

#: 真 mod 的安装目录名 —— **从数据源读**（`mod/data/*.toml`），不在探针里写死。
#:
#: 为什么不写死：阶段 5 的 G-EXIT-1 是"加一行数据 = 加一个处境、不改逻辑"。
#: 目录名一旦在探针里写死，就多出若干处"改了数据还得顺手改的 Python"；
#: 而 `ab_probe.load_target()` 已经是那条链的单一来源（`ab_probe.deploy()` 同样读它）。
OURS_DST = MODS_DIR / ab_probe.load_target().dir_name
OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "perf"

#: 有界窗口的三条控制台命令（B66 实测：反引号开控制台、敲完要**按两次回车**才提交）。
CLEAR_COMMAND = "clear_ticktask_timings"
DUMP_COMMAND = "dump_ticktask_timings"

MONTH_DAYS = 30.44


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

    ⚠️ **被占用的文件要跳过、不报错**（2026-09-23 实测）：上一次跑批留下过一个进程，
    它握着 `ai.log` 的句柄 ⇒ `shutil.move` 抛 `PermissionError`，整局还没开始就崩。
    跳过是安全的：被判据用到的是 `debug.log` / `system.log`，那两个不常被长期占用。
    """
    target = Path(tempfile.gettempdir()) / "v3_quarantine_perflogs"
    target.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for path in sorted(LOGS.glob("*.log")):
        try:
            shutil.move(str(path), str(target / path.name))
        except (PermissionError, OSError):
            continue
        moved.append(path.name)
    return moved


def _mounted_evidence() -> list[str]:
    """从日志里取证"这一局到底挂了哪些 mod"。

    ⚠️ **必须扫轮转过的日志**（`debug.1.log`…）：`debug.log` 按大小轮转，挂载那几行
    经常落在 `debug.1.log` 里。实测踩过：`ours` 那局的取证返回**空**，看上去像"我们的
    mod 没挂上"——去 `debug.1.log` 里一找，`Mounted Data: …/mod/ru_defeat-tr_defeat`
    和 `Mod SITAI … successfully matched game version` 都在。
    扫全部 `*.log` 是安全的：**本函数只在会话开始时挪走过全部日志之后调用**。
    """
    lines: list[str] = []
    for path in sorted(LOGS.glob("*.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        lines.extend(
            line.strip()
            for line in text.splitlines()
            if "Mounted Data" in line or "successfully matched game version" in line
        )
    return lines[-8:]


def _ours_mounted() -> bool:
    """这一局到底有没有挂上**我们的** mod（判据：日志里出现我们的安装路径或 mod 名）。"""
    marker = OURS_DST.name
    for path in sorted(LOGS.glob("*.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if marker in text or "sitai.ru_defeat" in text:
            return True
    return False


def _wait_months(hwnd: int, months: float, *, timeout: float = 900.0) -> dict[str, object]:
    """跑到游戏时间前进 ``months`` 个月（判据是**游戏内日期**，不是墙钟）。"""
    start = ga.tick_mark()
    start_day = ga.tick_day(start.tick)
    target = months * MONTH_DAYS
    last = start_day
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not ga._live_window(hwnd):
            return {
                "from": start.tick,
                "to": "<窗口没了或换了>",
                "days": last,
                "window_gone": True,
            }
        mark = ga.tick_mark()
        day = ga.tick_day(mark.tick)
        if day is not None and start_day is not None and day - start_day >= target:
            return {"from": start.tick, "to": mark.tick, "days": round(day - start_day, 1)}
        last = day
        time.sleep(5.0)
    return {
        "from": start.tick,
        "to": ga.tick_mark().tick,
        "days": last,
        "timeout": True,
    }


def run_once(label: str, months: float, *, index: int = 1) -> dict[str, object]:
    """跑一局并取一份 dump。调用方负责 content_load 与 mod 目录已就位。"""
    ga.assert_no_game_running()
    csv_path = gametimer.ticktask_default_path()
    csv_path.unlink(missing_ok=True)  # 清掉旧的，靠"文件重新出现"判断命令生效
    moved = _quarantine_logs()
    print(f"\n===== {label} #{index}：起游戏（前台，不碰窗口直到进局）=====")
    print(f"  已挪走 {len(moved)} 个旧日志（取证只可能来自这一局）")
    hwnd, previous = ga.launch_to_foreground(timeout=float(ga.WINDOW_TIMEOUT))
    settle = ga.wait_for_boot_settle(timeout=float(ga.LOBBY_TIMEOUT))
    print(f"  加载等待（不碰窗口）：{settle.why}")
    session = ga.start_session(hwnd, previous, settle=settle, force=True)
    print(f"  进局：{session.handover.describe()} speed_ok={session.rate_ok} rate={session.rate}")
    hwnd = ga._live_window(hwnd)

    # `start_session` 的收尾是**切回后台**（还前台 + 缩窗口）—— 要敲控制台就得先还原。
    ga.ensure_foreground(hwnd, force=True)
    ga.press_key("space", force=True)  # 停住：先清计数，窗口才从"清完"那一点开始算
    time.sleep(1.5)
    cleared = ga.submit_console_command(hwnd, CLEAR_COMMAND, force=True)
    print(f"  {CLEAR_COMMAND}：{'已提交' if cleared else '⚠️ 没提交成功'}")
    # 控制台关不掉（实测 escape / 反引号 / shift+escape 都没用），但**点一下速度表盘**
    # 就能把焦点从输入框拿走 —— 否则空格会被输入框吃掉，游戏一直暂停（实测踩过）。
    if session.speed_xy is not None:
        ga.click_client(hwnd, session.speed_xy[0], session.speed_xy[1], force=True)
        time.sleep(0.8)
    ga.press_key("space", force=True)
    time.sleep(3.0)

    advanced = _wait_months(hwnd, months)
    print(f"  跑完 {months} 个月：{advanced}")

    ga.ensure_foreground(hwnd, force=True)
    dumped = ga.submit_console_command(hwnd, DUMP_COMMAND, force=True)
    print(f"  {DUMP_COMMAND}：{'已提交' if dumped else '⚠️ 没提交成功'}")
    with suppress(ga.CaptureFailedError):
        ga.save_shot(ga.screenshot(hwnd), f"perf-{label}-after-dump")
    time.sleep(3.0)
    if not csv_path.is_file():
        raise ga.GameAutoError(
            f"{label}：dump 之后 {csv_path} 没出现 —— 控制台那条命令没生效"
            "（检查 backlog B66 的三条：反引号开、敲得进去、**两次回车**才提交）"
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{label}-{index}.csv"
    shutil.copy(csv_path, target)
    summary = gametimer.summarize_ticktask(target)
    print(f"  {target}（{target.stat().st_size} 字节）")
    for line in gametimer.ticktask_summary_lines(target):
        print("    " + line)
    mounted = _mounted_evidence()
    ours_mounted = _ours_mounted()
    print(f"  我们的 mod 挂上了吗：{ours_mounted}")

    report: dict[str, object] = {
        "label": label,
        "index": index,
        "csv": str(target),
        "bytes": target.stat().st_size,
        "months": months,
        "advanced": advanced,
        "console": {"clear": cleared, "dump": dumped},
        "session": session.as_dict(),
        "summary": summary,
        "mounted": mounted,
        "ours_mounted": ours_mounted,
    }
    ga.kill_game()
    time.sleep(3)
    return report


def _per_frame_mean(summary: object) -> float | None:
    """ "每帧各任务合计"的均值（ms）—— 从 `summarize_ticktask` 的实测 schema 里取。"""
    if not isinstance(summary, dict):
        return None
    block = summary.get("per_frame_total_ms")
    if isinstance(block, dict):
        value = block.get("mean")
        return float(value) if isinstance(value, int | float) else None
    return None


def _task_mean(csv: Path, task: str) -> float | None:
    """某个任务的**每帧均值**（ms）。

    为什么要单列这个量：我们的档案加的就是 static modifier，而 `RecalculateModifierNodes`
    正是"重算修正节点"那个任务 —— 它比整帧均值**敏感得多**（实测原版 3.77ms vs 整帧 21.3ms）。
    `summarize_ticktask` 只给"最贵任务"那一行，所以这里直接走 `parse_*` + `ticktask_task_stats`。
    """
    for stat in gametimer.ticktask_task_stats(gametimer.parse_ticktask_file(csv)):
        if stat.task == task:
            return stat.mean_ms
    return None


#: 对照表盯的两个量：整帧合计均值，以及"我们直接改的那个任务"的均值。
WATCH_TASK = "RecalculateModifierNodes"


def report_table(reports: list[dict[str, object]]) -> dict[str, object]:
    """把若干局折成一张对照表：每个 label 的**每一局**读数 + 均值。"""
    table: dict[str, object] = {"runs": reports, "by_label": {}}
    by_label: dict[str, list[dict[str, float | None]]] = {}
    for report in reports:
        label = str(report["label"])
        by_label.setdefault(label, []).append(
            {
                "per_frame_mean": _per_frame_mean(report.get("summary")),
                "task_mean": _task_mean(Path(str(report["csv"])), WATCH_TASK),
            }
        )
    aggregate: dict[str, dict[str, float | None]] = {}
    for label, rows in by_label.items():
        for key in ("per_frame_mean", "task_mean"):
            values = [row[key] for row in rows if row[key] is not None]
            aggregate.setdefault(label, {})[key] = (
                round(sum(values) / len(values), 4) if values else None
            )
        aggregate[label]["runs"] = len(rows)
    table["by_label"] = aggregate
    if len(aggregate) == 2:
        labels = list(aggregate)
        delta: dict[str, float | None] = {}
        for key in ("per_frame_mean", "task_mean"):
            a, b = aggregate[labels[0]][key], aggregate[labels[1]][key]
            delta[key] = None if a is None or b is None else round(b - a, 4)
            delta[f"{key}_pct"] = (
                None if not a or delta[key] is None else round(100 * delta[key] / a, 2)
            )
        delta["from"] = labels[0]
        delta["to"] = labels[1]
        table["delta"] = delta
    return table


def main() -> int:
    # 探针是**显式入口**：按设计打开真实输入授权（`pdx.game_auto` 的闸门说的就是这件事）。
    ga.ALLOW_REAL_INPUT = True
    parser = argparse.ArgumentParser(description="G-EXIT-3 两局性能对照")
    parser.add_argument("months", nargs="?", type=float, default=12.0, help="每局跑几个月")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="每个配置跑几局（≥2 才看得出「这两局的差」是不是噪声；单局抖动见结果文档）",
    )
    parser.add_argument(
        "--stress",
        action="store_true",
        help="开**标准压力剧本**（大战 + 连锁破产 + 革命潮）：两臂都装那一份探针，"
        "于是世界被推到同一个高压状态，差只剩我们的 mod —— 0.5 ms 要靠它才分辨得出来",
    )
    args = parser.parse_args()
    months = args.months
    backup = DOCS / "content_load.json.sitai-perf-backup"
    if not CONTENT_LOAD.is_file():
        print(f"找不到 {CONTENT_LOAD}")
        return 2
    shutil.copy(CONTENT_LOAD, backup)
    original = json.loads(CONTENT_LOAD.read_text(encoding="utf-8"))
    print(f"content_load.json 已备份到 {backup.name}（收尾会还原）")

    reports: list[dict[str, object]] = []
    try:
        if OURS_DST.exists():
            shutil.rmtree(OURS_DST)
        shutil.copytree(config.REPO / "mod", OURS_DST)
        print(f"已装本地 mod：{OURS_DST.name}（复制自 {config.REPO / 'mod'}）")

        # 压力剧本：**两臂都装**。单装一臂的话，"世界被推到高压"这件事本身会被算进
        # 那一臂的差里，对照立刻作废 —— 它必须是一个两臂共有的**场景**，不是一种处理。
        stress_mods: list[Path] = []
        if args.stress:
            if STRESS_DST.exists():
                shutil.rmtree(STRESS_DST)
            stress_probe.write(STRESS_DST)
            stress_mods = [STRESS_DST]
            print(
                f"已开压力剧本：{STRESS_DST.name}"
                f"（大战 {len(stress_probe.WAR_PAIRS)} 场 @ {stress_probe.WAR_DATE}；"
                f"抽干 {len(stress_probe.BREAK_TAGS)} 国库 @ {stress_probe.BREAK_DATE}；"
                f"激进派 {len(stress_probe.RADICAL_DATES)} 波）"
            )

        # **交替跑**（vanilla, ours, vanilla, ours…）：同一时段的机器状态（温升、后台负载）
        # 被两个配置平摊，比"先把原版跑完再跑我们"更能压住系统性偏差。
        for index in range(1, max(1, args.repeat) + 1):
            _set_local_mods(stress_mods, original=original)  # 基线：只有压力剧本（没有我们）
            reports.append(run_once("vanilla", months, index=index))
            _set_local_mods([*stress_mods, OURS_DST], original=original)
            reports.append(run_once("ours", months, index=index))
    finally:
        killed = ga.kill_game()
        shutil.copy(backup, CONTENT_LOAD)
        backup.unlink(missing_ok=True)
        for path in (OURS_DST, STRESS_DST):
            if path.exists():
                shutil.rmtree(path)
        print(f"\n[收尾] 杀游戏 {killed or '（没有）'}；content_load.json 已还原；本地 mod 已删除")

    table = report_table(reports)
    print("\n===== G-EXIT-3 对照（非受控：两局不是同一个世界，只读量级与方向）=====")
    for report in reports:
        print(f"\n--- {report['label']} #{report.get('index')} ---")
        print(f"  月数 {report['months']}｜{report['advanced']}")
        summary = report["summary"]
        if isinstance(summary, dict):
            print(
                f"  帧 {summary.get('frames')}｜每帧合计均值 {_per_frame_mean(summary)} ms"
                f"｜{WATCH_TASK} 均值 {_task_mean(Path(str(report['csv'])), WATCH_TASK)} ms"
            )
        print(f"  我们的 mod 挂上了吗：{report.get('ours_mounted')}")
    print("\n--- 汇总 ---")
    for label, row in table["by_label"].items():  # type: ignore[union-attr]
        print(f"  {label}：{row}")
    if "delta" in table:
        print(f"  差（{table['delta']}）")  # type: ignore[index]
    out = OUT_DIR / "compare.json"
    out.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n证据：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
