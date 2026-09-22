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


from pdx import ab_probe, config
from pdx import game_auto as ga

DOCS = Path.home() / "Documents" / "Paradox Interactive" / "Victoria 3"
MODS_DIR = DOCS / "mod"
CONTENT_LOAD = DOCS / "content_load.json"
#: `log_ticktask_performance` 的输出（用户目录；exe 明文：*"output: profiling.log"*）。
#:
#: ⚠️ 为什么换掉 `dump_ticktask_timings`（2026-09-23 实测）：那条命令在
#: `console_history.txt` 里**确实被执行过**，但 `ticktask_timings.csv` **始终没出现**、
#: 日志里也既无 `Wrote … rows` 也无 `Could not write`（backlog B63）。
#: `log_ticktask_performance` 走的是另一条路：**持续写**这个日志文件，
#: 文件出现本身就是"命令生效"的判据，不必再猜 dump 的落点。
PROFILING = DOCS / "profiling.log"

#: 命令生效之后再让它攒多久（秒）。这段时间里游戏**在跑**，所以日志会持续长大。
RUN_TAIL_SECONDS = 60.0

#: 半自动模式里等人去按按钮的上限（秒）。**给足**：人要看着提示去操作。
SEMI_WAIT_SECONDS = 600.0

#: 用命令行开关打开逐任务计时（**不再依赖 GUI 点击**）。
#:
#: exe 明文里 `log_ticktask_performance` 的帮助是 *"Start outputing ticktask performance
#: data to profiling.log"*，成功时写 *"Tick task logging enabled, output: profiling.log"*。
CONSOLE_ACTION = "log_ticktask_performance"

#: `run_console_action` 的**变体名** —— exe 明文里有三个，帮助文本分别是：
#: * `--run_console_action` ⇒ *"runs as early as possible."*
#: * `--run_console_action_main` ⇒ *"runs once the game has been initialized."* ← **要这个**
#: * `--run_console_action_clausewitz` ⇒ *"runs once Clausewitz has been initialized."*
#:
#: ⚠️ 用不带 `_main` 的那个会让**进程当场退出**（实测 `WindowNotFoundError`），
#: 因为"尽早跑"发生在游戏初始化之前。`_main` 才是"等游戏起来再跑"。
CONSOLE_ACTION_VARIANT = "run_console_action_main"

LOGS = DOCS / "logs"

PROBE_DIR = MODS_DIR / "zz_sitai_perf"

#: 真 mod 的安装目录名 —— **从数据源读**（`mod/data/*.toml`），不在探针里写死。
#:
#: 为什么不写死：阶段 5 的 G-EXIT-1 是"加一行数据 = 加一个处境、不改逻辑"。
#: 目录名一旦在探针里写死，就多出若干处"改了数据还得顺手改的 Python"；
#: 而 `ab_probe.load_target()` 已经是那条链的单一来源（`ab_probe.deploy()` 同样读它）。
OURS_DST = MODS_DIR / ab_probe.load_target().dir_name
OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "perf"

#: 探针按钮的**候选点**（客户区，1920x1080）—— **已停用，留作记录**。
#:
#: 为什么留：那个按钮**没有可测的颜色**（`using = default_button` +
#: `background = { color = … }` 画出来仍是透明背景，截图里只看得见文字 `TickTimer`），
#: 而六个候选点**一个都没生效**。这条路（GUI 点击触发 dump）已判死，
#: 现在走**命令行** `-run_console_action`（见 :data:`CONSOLE_ACTION`）——
#: 保留这串坐标是为了下次有人想重试时不必再从截图量一遍。
PROBE_CANDIDATES: tuple[tuple[int, int], ...] = (
    (1390, 500),
    (1455, 510),
    (1300, 500),
    (1390, 470),
    (1390, 530),
    (1500, 500),
)

MONTH_DAYS = 30.44
RUN_TIMEOUT = 900.0


def _kill_game() -> list[int]:
    """转发到 :func:`pdx.game_auto.kill_game`（收尾纪律只有一份实现）。"""
    return ga.kill_game()


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

    ⚠️ **被占用的文件要跳过、不报错**（2026-09-23 实测）：上一次跑批留下过一个进程
    （`-run_console_action` 那一族的副作用），它握着 `ai.log` 的句柄 ⇒
    `shutil.move` 抛 `PermissionError: [WinError 32]`，整局还没开始就崩。
    跳过是安全的：被判据用到的是 `debug.log` / `system.log`，那两个不常被长期占用。
    """
    target = Path(tempfile.gettempdir()) / "v3_quarantine_perflogs"
    target.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for path in sorted(LOGS.glob("*.log")):
        try:
            shutil.move(str(path), str(target / path.name))
        except (PermissionError, OSError):
            continue  # 被别的进程占着 —— 跳过，别让收尾动作把整局带崩
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
    if PROFILING.exists():
        PROFILING.unlink()  # 清掉旧的，靠"文件重新出现"判断命令生效
    moved = _quarantine_logs()
    print(f"\n===== {label}：起游戏（只挂本地 mod）=====")
    print(f"  已挪走 {len(moved)} 个旧日志（取证只可能来自这一局）")
    # 用命令行打开逐任务计时。**关键是变体名**（exe 明文里有三个变体）：
    #   `--run_console_action`       runs as early as possible
    #   `--run_console_action_main`  **runs once the game has been initialized** ← 要的是这个
    #   `--run_console_action_clausewitz`  runs once Clausewitz has been initialized
    # ⚠️ 用**不带 `_main`** 的那一个会让进程当场退出（实测 `WindowNotFoundError`）；
    # 带 `_main` 的那个才"等游戏初始化完再跑"，而 `log_ticktask_performance` 一旦打开就
    # **持续写** `profiling.log`（exe 明文：*"Tick task logging enabled, output: profiling.log"*）。
    console_arg = f"-{CONSOLE_ACTION_VARIANT}={CONSOLE_ACTION}"
    print(f"  启动参数：{console_arg}")
    hwnd, previous = ga.launch_to_foreground(
        timeout=float(ga.WINDOW_TIMEOUT), extra_args=(console_arg,)
    )
    settle = ga.wait_for_boot_settle(timeout=float(ga.LOBBY_TIMEOUT))
    print(f"  加载等待（不碰窗口）：{settle.why}")
    session = ga.start_session(hwnd, previous, settle=settle, force=True)
    print(f"  进局：{session.handover.describe()} speed_ok={session.rate_ok} rate={session.rate}")
    hwnd = ga._live_window(hwnd)

    advanced = _wait_months(hwnd, months)
    print(f"  跑完 {months} 个月：{advanced}")

    ga.ensure_foreground(hwnd, force=True)
    with suppress(ga.CaptureFailedError):
        ga.save_shot(ga.screenshot(hwnd), f"perf-{label}-after-run")
    point = (0, 0)
    how = f"命令行 {console_arg}"
    if not PROFILING.exists():
        raise ga.GameAutoError(
            f"{label}：命令行开关 {console_arg} 没能打开逐任务计时（{PROFILING.name} 没出现）"
            " —— 要么这个开关名不对，要么 `log_ticktask_performance` 不能在启动时执行"
        )
    print(f"  {PROFILING.name} 已出现 ✅（{PROFILING.stat().st_size} 字节）")
    # 让它多攒一会儿数据：`log_ticktask_performance` 是**持续写**的日志。
    print(f"  等它长大（再跑 {RUN_TAIL_SECONDS:.0f} 秒）……")
    time.sleep(RUN_TAIL_SECONDS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{label}-profiling.log"
    shutil.copy(PROFILING, target)
    print(f"  profiling.log 已另存：{target}（{target.stat().st_size} 字节）")

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
    """从另存下来的 profiling.log 里挑出关键几行给人看（认不出格式就原样回前几行）。"""
    text = csv.read_text(encoding="utf-8", errors="replace")
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    wanted = [line for line in lines if any(task in line for task in tasks)]
    wanted += [line for line in lines if "Average" in line or "Total:" in line][:6]
    return wanted[:12] or lines[:8]


def _semi_auto(months: float) -> int:
    """**半自动**跑一局：起游戏 → 提示人去按那个按钮 → 等 → 收 `profiling.log`。

    为什么要有这个模式（2026-09-23 的结论，见 backlog B64）：能**自动**触发逐任务计时的
    九条路全部判死（GUI 注入画不出来 / 点不动、命令行开关会让进程当场退出）。
    剩下唯一能拿到读数的办法就是**让人按一下** —— 那个按钮在游戏里**肉眼可见**
    （`error_deer` 调试覆盖层，文字写着 `TickTimer`）。

    代价写在明处：**这一局不是无人值守的**。它换来的是 F9「最坏情况实测」那条预算
    终于有数，而不是继续记"量不出来"。

    用法：``python tools/probe/perf_compare.py --semi 12``
    """
    backup = DOCS / "content_load.json.sitai-perf-backup"
    if not CONTENT_LOAD.is_file():
        print(f"找不到 {CONTENT_LOAD}")
        return 2
    shutil.copy(CONTENT_LOAD, backup)
    original = json.loads(CONTENT_LOAD.read_text(encoding="utf-8"))
    print(f"content_load.json 已备份到 {backup.name}（收尾会还原）")
    previous = ga._foreground_window()
    try:
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "perf_mod.py")],
            check=True,
            capture_output=True,
        )
        _set_local_mods([PROBE_DIR], original=original)
        moved = _quarantine_logs()
        print(f"已挪走 {len(moved)} 个旧日志；只启用探针 mod（**原版一局**，量基线）")
        hwnd, previous = ga.launch_to_foreground(timeout=float(ga.WINDOW_TIMEOUT))
        settle = ga.wait_for_boot_settle(timeout=float(ga.LOBBY_TIMEOUT))
        print(f"加载等待（不碰窗口）：{settle.why}")
        session = ga.start_session(hwnd, previous, settle=settle, force=True)
        print(f"进局：{session.handover.describe()}；速率 {session.rate} 天/秒")
        advanced = _wait_months(hwnd, months)
        print(f"跑完 {months} 个月：{advanced}")

        print("\n" + "=" * 72)
        print("请按一下游戏里那个按钮：它在屏幕**底中偏右**的调试覆盖层里，")
        print("写着 `TickTimer`（就在「我们有 N 个错误？！」左边、FPS 那一列里）。")
        print(f"按完之后 {PROFILING.name} 会出现并持续长大；脚本在等它。")
        print("=" * 72)
        deadline = time.monotonic() + SEMI_WAIT_SECONDS
        while time.monotonic() < deadline and not PROFILING.exists():
            time.sleep(2.0)
        if not PROFILING.exists():
            raise ga.GameAutoError(
                f"等了 {SEMI_WAIT_SECONDS / 60:.0f} 分钟，{PROFILING.name} 仍然没出现 —— "
                "按钮没按到（或那条命令本身有问题，见 backlog B64 的下一步）"
            )
        print(
            f"{PROFILING.name} 出现了（{PROFILING.stat().st_size} 字节），再等 {RUN_TAIL_SECONDS:.0f} 秒……"
        )
        time.sleep(RUN_TAIL_SECONDS)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        target = OUT_DIR / "vanilla-profiling.log"
        shutil.copy(PROFILING, target)
        print(f"已另存：{target}（{target.stat().st_size} 字节）")
        print("\n=== 读数（关键行）===")
        for line in _key_lines(target):
            print("  " + line)
        print(
            f"\n下一步：把 content_load.json 换成 [探针 + {OURS_DST.name}] 再跑一次本命令，"
            "就得到装我们 mod 的那一份；两份对比即是 G-EXIT-3 的对照表。"
        )
    finally:
        killed = _kill_game()
        shutil.copy(backup, CONTENT_LOAD)
        backup.unlink(missing_ok=True)
        for path in (PROBE_DIR, OURS_DST):
            if path.exists():
                shutil.rmtree(path)
        if previous:
            ga._set_foreground(previous)
        print(f"\n[收尾] 杀游戏 {killed or '（没有）'}；content_load.json 已还原；本地 mod 已删除")
    return 0


def main() -> int:
    # 探针是**显式入口**：按设计打开真实输入授权（`pdx.game_auto` 的闸门说的就是这件事）。
    ga.ALLOW_REAL_INPUT = True
    parser = argparse.ArgumentParser(description="G-EXIT-3 两局性能对照")
    parser.add_argument("months", nargs="?", type=float, default=12.0, help="每局跑几个月")
    parser.add_argument(
        "--semi",
        action="store_true",
        help=(
            "**半自动模式**：命令行那九条触发路都判死了（backlog B64），"
            "所以这里改成由人按一下游戏里那个按钮 —— 脚本跑一局、提示、等待、收日志"
        ),
    )
    args = parser.parse_args()
    months = args.months
    if args.semi:
        return _semi_auto(months)
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
