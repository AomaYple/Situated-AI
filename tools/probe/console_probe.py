"""游戏内**控制台**通道：把"引擎自带的逐任务计时"打开（G-EXIT-3 的仪表）。

为什么要有这个文件（backlog B31 / B63 / B64 / B66）
---------------------------------------------------
`log_ticktask_performance` / `dump_ticktask_timings` 是引擎自带的逐任务计时开关
（exe 明文，见 `docs/design/exec/阶段4-性能仪表侦察.md`）。前面两条路都判死了：

* **GUI 注入**（自建按钮 / 覆写已有按钮的 `onclick`）—— 九条候选全判死（B64）；
* **命令行开关**（`-run_console_action*`）—— 帮助原文写着 *"…, then exits"*，
  跑完即退，取不到"跑到某日期之后"的读数。

剩下唯一通道就是**游戏内控制台**。它以前被判成"未证实"，因为当时只看"文件有没有变"，
分不清"键没被接受 / 命令没被执行 / 执行了但写不出来"（B31）。本文件把这三件事分开量，
并且**三条都拿到了实测答案**（2026-09-23）：

1. **键**：反引号 `` ` `` 开控制台。判据不是目测，而是输入框那块 ROI 的均值
   （开着 ≈ 31–48、关着 ≈ 190，地图透出来）；
2. **敲字**：合成的扫描码键盘**能**进输入框（截图里逐字读得到命令名）；
3. **提交**：**要按两次回车** —— 第一次被自动补全吃掉（exe 明文里有
   `SETTING_CONSOLE_AUTOCOMPLETE_MODE` 一族设置），第二次才执行。
   判据是输入框 ROI 标准差从 ~44 掉到 ~7（清空）+ 输出区出现回话。

打开成功时控制台自己会回一行：*"Tick task logging enabled, output: profiling.log"*。

⚠️ **两条踩过的坑**

* **只在暂停的局内用像素判据**（backlog B65）：大厅那张选国地图自己会平移，
  在菜单里量到 28.365 的"巨大变化"，截图一看只是镜头偏了几百像素。
* **打开计时后必须让游戏跑起来**：暂停时一个 tick 都没有，`profiling.log`
  不会出现（B66）。所以本探针的顺序是"开控制台 → 敲命令 → 两次回车 → 关控制台
  → 取消暂停跑 N 个月 → 再找文件"。

用法::

    python tools/probe/console_probe.py --run 12      # 开计时 → 跑 12 个月 → 收日志
    python tools/probe/console_probe.py --sweep       # 只重扫一遍"哪个键开控制台"

产物落在 `tools/probe/zz_console_probe/`（截图 + `report.json` + `profiling.log`），**不进 git**。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from contextlib import suppress
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdx import game_auto as ga

OUT = Path(__file__).resolve().parent / "zz_console_probe"

#: 用户目录（引擎把 `console_history.txt` 写这儿）。
DOCS = Path.home() / "Documents" / "Paradox Interactive" / "Victoria 3"
HISTORY = DOCS / "console_history.txt"
DEBUG_LOG = DOCS / "logs" / "debug.log"

#: 引擎的**日志分类表**（在游戏安装目录里，**可写**、且实测游戏不会改写它 ——
#: 两份文件的 mtime 都停在安装那天）。`log_ticktask_performance` 说的是
#: *"output: profiling.log"*，但这张表里**没有 `profiling` 这一类** ⇒
#: 那条日志**没有 sink、写不出来**。所以探针要把这一类补上（**先备份、收尾还原**）。
LOGGER_SETTINGS = (
    Path(ga.experiments.launch_command()[0]).parent.parent
    / "platform_specific_game_data"
    / "log_settings_live.json"
)
LOGGER_BACKUP = LOGGER_SETTINGS.with_suffix(".json.sitai-backup")

#: 要补的日志类别的候选名。命令的回话只说"profiling.log"，没说类别名 ——
#: 三个都补上，谁落盘谁就是对的（补错的类别最多在 error.log 里留一句，无害）。
PROFILING_CATEGORIES: tuple[str, ...] = ("profiling", "ticktask", "gamemetrics")

#: 逐任务计时的产物**可能落在哪**。命令的帮助只说文件名、没说目录，而游戏是以
#: `cwd=<仓库根>` 起的（`game_auto.launch`），相对路径也可能落在仓库根或 exe 旁边。
ARTIFACT_DIRS: tuple[Path, ...] = (
    DOCS,
    DOCS / "logs",
    ga.config.ROOT,
    ga.config.ROOT / "logs",
    Path(ga.experiments.launch_command()[0]).parent,
)

#: 两条仪器各自的产物文件名。
ARTIFACTS: tuple[str, ...] = ("profiling.log", "ticktask_timings.csv")

#: 候选开控制台的键（**pydirectinput 走扫描码**，键名按它的表来；上档写成 `shift+X`）。
#: 实测只有反引号有效，其余留在这里是让 `--sweep` 能复核这条结论。
CANDIDATE_KEYS: tuple[str, ...] = ("`", "shift+`", "/", "f12")

#: 打开逐任务计时的控制台命令（持续写，不需要 dump）。
COMMAND = "log_ticktask_performance"

#: 另一条仪器：把**已经在内存里记着**的逐任务计时直接落盘（表头
#: `frame,task,milliseconds,calls,longest_lock`）。它的价值是**有界窗口** ——
#: `clear_ticktask_timings` → 跑 N 个月 → dump，读数不会被开局加载拉花。
DUMP_COMMAND = "dump_ticktask_timings"

#: 有界窗口的第一步：把之前记录的计时丢掉，让下一次 dump 只覆盖之后这一段。
CLEAR_COMMAND = "clear_ticktask_timings"

#: 控制台**输入框**（`gui/console.gui` 的 `console_edit`）在客户区里的像素矩形。
#: 实测量（2026-09-23，1920x1080）：`x 8..428`、`y 568..606`。
#:   * 控制台**开没开** ⇒ ROI 均值：开着 ≈ 31–48，关着 ≈ 190；
#:   * 输入框**有没有字** ⇒ ROI 标准差：有字 ≈ 43–55，空的 ≈ 7–18。
EDIT_ROI = (8, 568, 428, 606)

#: 控制台**输出区顶部**（回话就写在这儿；输出区在输入框上方，文字从顶部开始）。
OUTPUT_ROI = (8, 0, 340, 120)

#: 画面差超过这个数才算"界面上多了东西"。
DIFF_THRESHOLD = 3.0

#: 输入框标准差掉到这个数以下 = 被清空了（提交成功的判据之一）。
CLEARED_STD = 30.0


def _roi_stats(hwnd: int, roi: tuple[int, int, int, int]) -> tuple[float, float, int]:
    """ROI 的 (均值, 标准差, 亮像素数)。

    ⚠️ 这里的 ROI 是**像素**，而 `game_auto.screenshot` 要的是**分数**矩形（0–1）。
    实测踩过：把像素直接传进去，bbox 乘出天文数字、PIL 抛 `DecompressionBombError`
    （"Image size (33094656000 pixels)…"），那句报错指不到真正的原因 ——
    所以这儿就地换算（`_grab` 那边也加了硬检查）。
    """
    width, height = ga._client_size(hwnd)
    x0, y0, x1, y1 = roi
    fractions = (x0 / width, y0 / height, x1 / width, y1 / height)
    image = ga.screenshot(hwnd, roi=fractions).convert("L")
    box = np.asarray(image, dtype=np.float32)
    return (float(box.mean()), float(box.std()), int((box > 140).sum()))


def console_open(hwnd: int) -> bool:
    """控制台开着吗？判据是输入框那块 ROI 的**均值**（实测开着 ≈31–48、关着 ≈190）。"""
    mean, _std, _ink = _roi_stats(hwnd, EDIT_ROI)
    return mean < 90.0


def editbox_filled(hwnd: int) -> float:
    """输入框里"有没有字"的代理量：ROI 标准差（有字 ≫ 空）。"""
    _mean, std, _ink = _roi_stats(hwnd, EDIT_ROI)
    return std


def output_ink(hwnd: int) -> int:
    """输出区（顶部那一条）的亮像素数 —— 命令回话就会让它跳。"""
    _mean, _std, ink = _roi_stats(hwnd, OUTPUT_ROI)
    return ink


def _shoot(hwnd: int, tag: str) -> Path:
    """截一张、存一张，返回路径。

    ⚠️ `ga.to_bgr` 吃的是**数组**不是 PIL 图（它按 `ndim` 分灰度/四通道）。
    """
    return ga.save_shot(ga.screenshot(hwnd), tag)


def press_chord(chord: str) -> None:
    """按一次 `key` 或 `shift+key`（转发到 `game_auto.press_chord`）。"""
    ga.press_chord(chord, force=True)


def open_console(hwnd: int, *, key: str = "`") -> bool:
    """把控制台打开（已经开着就直接返回 True）。"""
    if console_open(hwnd):
        return True
    press_chord(key)
    time.sleep(1.5)
    return console_open(hwnd)


def close_console(hwnd: int, *, key: str = "`") -> bool:
    """把控制台关掉。**逐条试几个键并如实报告哪个管用**。

    实测（2026-09-23）：**Esc 关不掉**（`console_open` 仍是 True）。所以别在这里
    自作聪明挑一个键 —— 把候选列出来、量出结果，谁管用谁进结论。
    """
    if not console_open(hwnd):
        return True
    for chord in ("escape", key, "shift+escape"):
        press_chord(chord)
        time.sleep(1.0)
        if not console_open(hwnd):
            print(f"  （关控制台：{chord!r} 管用）")
            return True
    print("  ⚠️ escape / 反引号 / shift+escape 都没关掉控制台 —— 留着它继续跑")
    return False


def unpause(hwnd: int, session: object, *, attempts: int = 4) -> bool:
    """让时间真的走起来，返回是否走起来了。

    为什么不能"按一下空格就假定在跑"：实测 —— 控制台开着时**空格被输入框吃掉**
    （那一次脚本"跑了 12 个月"，游戏时间一动不动：`1836.3.1.6 → 1836.3.1.6`）。
    所以这里先点一次速度表盘（把焦点从输入框拿走，同时确保是 5 档），
    再按空格，然后**用日志里的 tick 判据复核**；不成再换下一招。
    """
    speed_xy = getattr(session, "speed_xy", None)
    for attempt in range(1, attempts + 1):
        ga.ensure_foreground(hwnd, force=True)
        if speed_xy is not None:
            ga.click_client(hwnd, speed_xy[0], speed_xy[1], force=True)
            time.sleep(0.8)
        ga.press_key("space", force=True)
        before = ga.tick_mark()
        time.sleep(6.0)
        if ga.is_running(seconds=0.1).advanced:
            print(f"  已恢复推进（第 {attempt} 招）：{before.tick} → {ga.tick_mark().tick}")
            return True
        print(f"  第 {attempt} 招没让它跑起来，换下一招……")
    return False


def run_months(months: float, *, timeout: float = 1800.0) -> dict[str, object]:
    """跑到时间前进 ``months`` 个月（与 `perf_compare._wait_months` 同口径）。"""
    month_days = 30.44
    start = ga.tick_mark()
    start_day = ga.tick_day(start.tick)
    target = months * month_days
    last = start_day
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mark = ga.tick_mark()
        day = ga.tick_day(mark.tick)
        if day is not None and start_day is not None and day - start_day >= target:
            return {"from": start.tick, "to": mark.tick, "days": round(day - start_day, 1)}
        last = day
        time.sleep(5.0)
    return {"from": start.tick, "to": ga.tick_mark().tick, "days": last, "timeout": True}


def submit_command(hwnd: int, command: str, *, attempts: int = 3) -> dict[str, object]:
    """敲一条命令并提交：**类型 + 两次回车**，然后按"输入框清空 + 输出区回话"判成功。

    为什么是两次回车（2026-09-23 实测）：按一次时输入框标准差 44.9 → 44.0（字一个没少、
    输出区一动不动）；连按两次 43.0 → 7.5（清空）且输出区亮像素 322 → 1732。
    第一次被**自动补全**吃掉了 —— exe 明文里有 `SETTING_CONSOLE_AUTOCOMPLETE_MODE`
    一族设置，控制台的补全模式会让首次回车只做补全。
    """
    rows: list[dict[str, object]] = []
    for attempt in range(1, attempts + 1):
        if not open_console(hwnd):
            rows.append({"attempt": attempt, "console": False})
            return {"ok": False, "rows": rows}
        ink_before = output_ink(hwnd)
        ga.type_text(command, force=True)
        time.sleep(0.6)
        filled = editbox_filled(hwnd)
        ga.press_key("enter", force=True)
        time.sleep(0.35)
        ga.press_key("enter", force=True)
        time.sleep(2.0)
        empty = editbox_filled(hwnd)
        ink_after = output_ink(hwnd)
        row = {
            "attempt": attempt,
            "console": True,
            "filled_std": round(filled, 1),
            "after_std": round(empty, 1),
            "cleared": empty < CLEARED_STD,
            "output_ink_before": ink_before,
            "output_ink_after": ink_after,
            "answered": ink_after > ink_before + 20,
        }
        row["shot"] = str(_shoot(hwnd, f"console-{command}-try{attempt}"))
        rows.append(row)
        print(
            f"  第 {attempt} 次：输入框 {filled:.1f} → {empty:.1f}"
            f"（{'已提交' if row['cleared'] else '还在'}）"
            f"｜输出区 {ink_before} → {ink_after}"
            f"（{'有回话' if row['answered'] else '没回话'}）"
        )
        if row["cleared"] and row["answered"]:
            return {"ok": True, "rows": rows}
        if not row["cleared"]:  # 没提交就清干净，免得下一条粘在后面
            for _ in range(len(command) + 8):
                ga.press_key("backspace", force=True)
            time.sleep(0.4)
    return {"ok": False, "rows": rows}


def sweep_keys(hwnd: int, keys: tuple[str, ...]) -> dict[str, object]:
    """逐个候选键：按一下 → 截图 → 再按一下（收回去）→ 截图。复核"哪个键开控制台"。"""
    rows: list[dict[str, object]] = []
    for key in keys:
        tag = key.replace("`", "grave").replace("~", "tilde").replace("/", "slash")
        before = np.asarray(ga.screenshot(hwnd).convert("L"), dtype=np.int16)
        press_chord(key)
        time.sleep(1.5)
        after_image = ga.screenshot(hwnd)
        after = np.asarray(after_image.convert("L"), dtype=np.int16)
        cut = min(before.shape[0], after.shape[0]) // 2
        diff = float(np.abs(before[:cut] - after[:cut]).mean())
        opened = console_open(hwnd)
        path = ga.save_shot(after_image, f"console-key-{tag}-after")
        rows.append(
            {"key": key, "top_diff": round(diff, 3), "console_open": opened, "shot": str(path)}
        )
        print(f"  键 {key!r}：上半屏像素差 {diff:.3f}｜console_open={opened}")
        press_chord(key)
        time.sleep(1.2)
    return {"keys": rows}


def find_artifact(name: str) -> Path | None:
    """在候选目录里找一件产物（`profiling.log` / `ticktask_timings.csv`）。"""
    for directory in ARTIFACT_DIRS:
        path = directory / name
        with suppress(OSError):
            if path.is_file() and path.stat().st_size > 0:
                return path
    return None


def new_files_since(stamp: float, roots: tuple[Path, ...]) -> list[str]:
    """``stamp`` 之后被动过的文件（**兜底诊断**：命令真写了东西的话，一定在这里现形）。

    为什么要它：两条仪器的落点都没有文档，与其继续猜目录，不如把"这一局里新出现的文件"
    全部列出来。`logs/` 与 `Documents\\…` 都不大，扫一遍很便宜。
    """
    found: list[str] = []
    for root in roots:
        with suppress(OSError):
            for path in root.rglob("*"):
                with suppress(OSError):
                    if path.is_file() and path.stat().st_mtime >= stamp:
                        found.append(f"{path}  {path.stat().st_size} B")
    return sorted(found)[:40]


def add_profiling_sink() -> str:
    """给引擎的日志表补上 `profiling` 这一类（**先备份**，收尾由 :func:`restore_logger_settings` 还原）。

    为什么必须补：`log_ticktask_performance` 的回话写着 *"output: profiling.log"*，
    而 `log_settings_live.json` 里 26 个类别**没有** `profiling`（也没有 `ticktask`）
    ⇒ 那条日志没有 sink，等于写进空气里。这解释了阶段 4 侦察里那个悬案：
    "12 份 `gametimer_*.tsv` 是旧构建产出的，更新之后一份都没有" ——
    不是启动方式变了，是**这一类没有 sink**。
    """
    if not LOGGER_SETTINGS.is_file():
        return f"找不到 {LOGGER_SETTINGS}（跳过补 sink）"
    if not LOGGER_BACKUP.exists():
        shutil.copy2(LOGGER_SETTINGS, LOGGER_BACKUP)
    data = json.loads(LOGGER_SETTINGS.read_text(encoding="utf-8"))
    have = {item.get("category") for item in data.get("loggers", [])}
    added: list[str] = []
    for category in PROFILING_CATEGORIES:
        if category in have:
            continue
        data["loggers"].append(
            {
                "category": category,
                "always_flush_level": "debug",
                "sinks": [
                    {
                        "type": "file",
                        "log_level": "debug",
                        "file_name": category,
                        "format_pattern": "[%T][%s:%#]: %v",
                    }
                ],
            }
        )
        added.append(category)
    LOGGER_SETTINGS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return f"日志表已补 {added or '（本来就有）'}（备份 {LOGGER_BACKUP.name}）"


def restore_logger_settings() -> str:
    """把日志表还原成用户原来那一份（**必须**做到，改的是游戏安装目录）。"""
    if not LOGGER_BACKUP.exists():
        return "没有备份可还原"
    shutil.copy2(LOGGER_BACKUP, LOGGER_SETTINGS)
    LOGGER_BACKUP.unlink()
    return "log_settings_live.json 已还原"


def _new_log_lines(size_before: int) -> list[str]:
    """`logs/debug.log` 新增行里跟控制台 / 计时有关的那些。"""
    if not DEBUG_LOG.is_file():
        return []
    text = DEBUG_LOG.read_text(encoding="utf-8", errors="replace")
    wanted = ("console", "ticktask", "Wrote", "Could not write", "profiling")
    fresh = text[size_before:]
    return [line.strip() for line in fresh.splitlines() if any(w in line for w in wanted)][:20]


def main() -> int:
    parser = argparse.ArgumentParser(description="游戏内控制台：打开引擎自带的逐任务计时")
    parser.add_argument("--run", type=float, default=12.0, help="开完计时让它跑几个月")
    parser.add_argument("--sweep", action="store_true", help="先重扫一遍候选键")
    parser.add_argument("--keep-console", action="store_true", help="收尾不关控制台（留画面证据）")
    args = parser.parse_args()

    ga.ALLOW_REAL_INPUT = True
    ga.assert_no_game_running()
    OUT.mkdir(parents=True, exist_ok=True)
    for directory in ARTIFACT_DIRS:
        for name in ARTIFACTS:
            with suppress(OSError):
                (directory / name).unlink()
    log_size = DEBUG_LOG.stat().st_size if DEBUG_LOG.is_file() else 0
    history_before = (
        len(HISTORY.read_text(encoding="utf-8", errors="replace").splitlines())
        if HISTORY.is_file()
        else 0
    )

    previous = ga._foreground_window()
    report: dict[str, object] = {"history_before": history_before, "command": COMMAND}
    started = time.time()
    try:
        # **必须在起游戏之前**：引擎只在启动时读那张日志表。
        note = add_profiling_sink()
        print(f"  {note}")
        report["logger_patch"] = note
        print("===== 起游戏（debug 模式，普通启动）=====")
        hwnd, previous = ga.launch_to_foreground(timeout=float(ga.WINDOW_TIMEOUT))
        settle = ga.wait_for_boot_settle(timeout=float(ga.LOBBY_TIMEOUT))
        print(f"  加载等待（不碰窗口）：{settle.why}")
        session = ga.start_session(hwnd, previous, settle=settle, force=True)
        print(f"  进局：{session.handover.describe()} rate={session.rate}")
        hwnd = ga._live_window(hwnd)

        # `start_session` 的收尾是**切回后台**（还前台 + 缩窗口），所以这里先把窗口
        # 还原提到前台，否则截图是 0x0（实测 `CaptureFailedError`）。
        ga.ensure_foreground(hwnd, force=True)
        ga.press_key("space", force=True)  # 停住：动着的画面不能用像素差当判据
        time.sleep(1.5)
        if args.sweep:
            print("  复核候选键（局内、已暂停）：")
            report["sweep"] = sweep_keys(hwnd, CANDIDATE_KEYS)

        # 两条仪器都在这一局里试：
        #   ① `dump_ticktask_timings` 直接落盘（**有界窗口**：clear → 跑 N 月 → dump）；
        #   ② `log_ticktask_performance` 走日志、持续写。
        # 跑之前先 dump 一次，是为了让控制台把**落点**打在屏幕上（回话里有 `Wrote %d
        # rows to %s`）；跑完再 dump 一次，那一次才是有内容的。
        report["submits"] = {}
        for command in (DUMP_COMMAND, COMMAND):
            print(f"  开控制台并提交 {command!r}：")
            result = submit_command(hwnd, command)
            report["submits"][command] = result  # type: ignore[index]
            if not result["ok"]:
                print(f"  ⚠️ {command!r} 没提交成功，继续下一条")
        _shoot(hwnd, "console-20-before-run")
        report["console_closed"] = close_console(hwnd)

        print(f"  恢复推进（跑 {args.run:.0f} 个月；**暂停时一个 tick 都没有**）……")
        if not unpause(hwnd, session):
            raise ga.GameAutoError("时间没走起来（空格被控制台输入框吃掉了？）")
        window = run_months(args.run)
        print(f"  跑了 {window}")
        report["window"] = window

        # 跑完再 dump 一次：这一次覆盖的是刚才那段窗口。
        ga.ensure_foreground(hwnd, force=True)
        report["dump_after"] = submit_command(hwnd, DUMP_COMMAND)
        _shoot(hwnd, "console-21-after-run")
        close_console(hwnd)
        time.sleep(5.0)
        got: dict[str, str] = {}
        for name in ARTIFACTS:
            found = find_artifact(name)
            if found is None:
                print(f"  ❌ 没找到 {name}")
                continue
            target = OUT / name
            shutil.copy(found, target)
            got[name] = f"{found}（{target.stat().st_size} B）"
            print(f"  ✅ {found}（{target.stat().st_size} 字节）→ 已另存 {target}")
            print(f"     {name} 前 5 行：")
            for line in target.read_text(encoding="utf-8", errors="replace").splitlines()[:5]:
                print("       " + line)
        report["artifacts"] = got
        report["new_files"] = new_files_since(started, (DOCS, ga.config.ROOT))
        print(f"  这一局新出现的文件（前 {min(12, len(report['new_files']))} 条）：")
        for line in report["new_files"][:12]:  # type: ignore[union-attr]
            print("    " + line)
        report["debug_log_new"] = _new_log_lines(log_size)
        for line in report["debug_log_new"]:
            print("  log | " + line)
    finally:
        (OUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        killed = ga.kill_game()
        if previous:
            ga._set_foreground(previous)
        print(f"[收尾] 杀游戏 {killed or '（没有）'}；{restore_logger_settings()}")
        print(f"        报告 {OUT / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
