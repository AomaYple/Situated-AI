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
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdx import ab_probe, config, modgen, mods
from pdx import game_auto as ga

DOCS = Path.home() / "Documents" / "Paradox Interactive" / "Victoria 3"
MODS_DIR = DOCS / "mod"
CONTENT_LOAD = DOCS / "content_load.json"
BACKUP = DOCS / "content_load.json.sitai-backup"
DEBUG_LOG = DOCS / "logs" / "debug.log"
PROBE = MODS_DIR / "zz_probe_ab"


def ours() -> Path:
    """真 mod 的安装目录 —— **目录名从数据源读**，不在脚本里写死。

    为什么不写死：阶段 5 的 G-EXIT-1 是"加一行数据 = 加一个处境、不改逻辑"。
    目录名一旦写死，就多出若干处"改了数据还得顺手改的 Python"；
    而 `ab_probe.load_target()` 已经是那条链的单一来源（`ab_probe.deploy()`
    用的也是它 —— 两边不同名会让"探针装的"和"这里装的"变成两份东西）。
    """
    return MODS_DIR / ab_probe.load_target().dir_name


#: 一天的推进量换算（与 `game_auto.tick_day` 同口径：够算月份就行）。
MONTH_DAYS = 30.44


def _clean_ours(*extra: Path) -> list[str]:
    """删掉用户 mod 目录里**所有属于本仓库**的目录，返回删掉的名字。

    为什么是「所有」而不是「当前那一个」—— 这两件事都必须成立，缺一条就漏：

    * **目录名会变**：`ours()` 现算 `ab_probe.load_target().dir_name`，而那个名字是
      **各档案 id 拼出来的**。档案集合一增删，上一版部署的目录就再也匹配不上。
      实测（backlog **B83**）：批次 2 装下的 6 档案目录在批次 3（8 档案）之后
      **既删不掉**（`restore()` 按新名字找不到它），**又被当成用户订阅的 mod**
      （`discover_mods()` 那时只排除 `zz_probe_` 前缀）—— 于是 `mod.total` 被顶到 24、
      `mod.files` 被顶到 4,828，doc 12 一整批分布数跟着算错。
    * **不许静默空转**：一个都没删到时也要说话（P13）—— 调用方据此判断
      "环境已经干净"还是"我没找到东西"。

    认目录的判据是 `.metadata/metadata.json` 的 id 前缀（`mods.own_mod_dirs()`），
    不是目录名。副作用要说清：用户**手动**装进本地 mod 目录的那份 SITAI 也会被删 ——
    对一个"还原用户环境"的收尾动作来说这是对的（它是我们的东西），但值得知道。
    """
    targets = set(mods.own_mod_dirs())
    for path in extra:
        if path.exists():
            targets.add(path)
    removed: list[str] = []
    for target in sorted(targets):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(target.name)
    return removed


def deploy(*, with_probe: bool = True, archive_id: str | None = None) -> str:
    """装本地 mod 并改写 `content_load.json`；返回一句人读的说明。

    **先备份**（只备一次：反复跑时不会被"已改过的版本"覆盖掉真正的原始配置）。

    ``with_probe=False`` = **只装真 mod、不装探针**。这是"和平期占槽率 ≈ 0"
    那条出口判据的测法：探针本身就是个会写变量的 mod，装了它再测"我们的 JE 出没出现"
    就分不清是谁的效果了 —— 而且探针的 `debug_log` 会把"没有 JE"这件事变成**沉默**，
    而沉默不是证据（日志里那一行**不存在**才是）。
    """
    if not BACKUP.exists():
        shutil.copy2(CONTENT_LOAD, BACKUP)
    original = json.loads(CONTENT_LOAD.read_text(encoding="utf-8"))
    ours_dst = ours()
    # 先清残留：上一版档案集合留下的目录按新名字是找不到的（见 `_clean_ours`）。
    _clean_ours(ours_dst, PROBE)
    shutil.copytree(config.REPO / "mod", ours_dst)
    paths = [ours_dst]
    if with_probe:
        # ⚠️ 用 `ab_probe.write` 而**不是** `ab_probe.deploy`：后者会调
        # `experiments.set_enabled_mods()` 自己改写 `content_load.json`，而这里要保住
        # 用户原来那 23 条 Workshop 配置（本脚本自己写那个文件，只启用本地 mod）。
        ab_probe.write(root=PROBE, archive_id=archive_id)
        paths.append(PROBE)
    payload = {
        "enabledMods": [{"path": str(path)} for path in paths],
        "disabledDLC": original.get("disabledDLC", []),
        "enabledUGC": [],
    }
    CONTENT_LOAD.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    names = " + ".join(path.name for path in paths)
    return (
        f"已装本地 mod：{names}；"
        f"原配置（{len(original.get('enabledMods', []))} 条 Workshop）备份在 {BACKUP.name}"
    )


def restore() -> str:
    """还原 `content_load.json` 并删掉**所有**属于本仓库的本地 mod 目录。"""
    notes: list[str] = []
    if BACKUP.exists():
        shutil.copy2(BACKUP, CONTENT_LOAD)
        notes.append("content_load.json 已还原")
    else:  # pragma: no cover - 没备份就没得还原，如实说
        notes.append("⚠️ 没有备份可还原")
    removed = _clean_ours(ours(), PROBE)
    notes.append(
        "已删本地 mod：" + "、".join(removed) if removed else "本地 mod 目录里没有我们的残留"
    )
    return "；".join(notes)


def kill_game() -> list[int]:
    pids = ga._process_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    return pids


def quarantine_test_artifacts() -> list[str]:
    """把这一局在**游戏安装目录**里留下的产物挪去临时目录，并返回挪走的文件名。

    为什么必须有这一步（实测，与 backlog B44/B49 同一类"环境漂移"）：
    `-scripted_tests` 会把成绩单写成 `<游戏根>\\binaries\\<uuid>_GameTests_testoutput.xml`
    —— 官方文档 `game/tools/scripted_tests/scripted_tests.md:24` 逐字写着
    "an XML file will be created in the game's binaries folder"，**改不了位置**。
    后果是 `v3 verify` 里 `binaries 目录文件数 / 字节总数` 两条断言每跑一局就红一次，
    而且**每次都是不同的 uuid**（会越积越多）。

    这与 B44/B49 的处置口径一致：**只移走，不删**（万一要查成绩单），
    下一次门禁红的时候先看这两条判据行，别去查当次改动。
    """
    binaries = config.ROOT / "binaries"
    if not binaries.is_dir():
        return []
    target = Path(tempfile.gettempdir()) / "v3_quarantine_stagetests"
    moved: list[str] = []
    for path in sorted(binaries.glob("*_GameTests_testoutput.xml")):
        target.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target / path.name))
        moved.append(path.name)
    return moved


def engine_verdict() -> dict[str, object]:
    """引擎自己判的那一份（`-scripted_tests` 的成绩单）—— 读不到就**如实说没判定**。

    为什么要有它：探针自己那套读数（`v3 ab` 读 `debug.log`）是**事后**判的；套件是
    **引擎每天判**的（判据同源、实现不共享，P9）。两条路互相独立 —— 一条出问题还有另一条。

    ⚠️ **必须在收尾挪走成绩单之前读**：`quarantine_test_artifacts()` 会把
    `binaries/*_GameTests_testoutput.xml` 移去临时目录（否则 `v3 verify` 会红），
    所以这里读到的必须是那一刻还在原地的文件。

    读不到**不算失败**（这一局可能在套件判完之前就被杀了），但要打出来 ——
    "没判定"与"判了通过"是两件事，不许混。
    """
    files = ga.testoutput_files()
    if not files:
        return {
            "引擎判定": "（没有成绩单：套件还没判完，或者压根没挂上）",
            "套件跑没跑": False,
        }
    verdict = ga.read_verdict(files[-1])
    out: dict[str, object] = dict(verdict.as_dict())
    out["引擎判定"] = "通过" if verdict.ok else "不通过"
    out["套件跑没跑"] = True
    return out


def quarantine_logs() -> list[str]:
    """转发到 :func:`pdx.game_auto.quarantine_logs`（收尾纪律只有一份实现）。

    为什么不再各写一份：`perf_compare` 那份带着"被占用就跳过"的守卫，这份没有 ——
    实测 `ai.log` 被别的进程握着时这里抛 `PermissionError`，整局还没开始就崩。
    """
    return ga.quarantine_logs()


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


def _subject_tag(ours: list[str]) -> str:
    """这一局的**主角 tag**（`ZZPROBE AB;ROLE;<TAG>;<本地化国名>` 的中间那格）。

    为什么可以用它：ROLE 行由 on_action **每月**写（实测一局 56 条），第一格就是 tag
    （实测原文 `…;ROLE;BAV;巴伐利亚`）。而 `TARGET` 行只在"武装"那一刻写一次。
    """
    for line in ours:
        if "ZZPROBE AB;ROLE;" in line:
            body = line.split("ZZPROBE AB;ROLE;", 1)[1].split('"', 1)[0]
            return body.split(";")[0].strip()
    return ""


def _subject_archive(ours: list[str]) -> str:
    """这一局盯的**档案 id** —— 两条路，先精确后兜底。

    ① 探针武装时写的 `ZZPROBE AB;TARGET;<档案 id>`（B80 加的自报行）；
    ② **按主角 tag 从数据源反查**：`ROLE;<TAG>;<本地化国名>` → `[archive].country`。

    ⚠️ **为什么必须有 ②（实测 2026-09-23，`bv_alignment` 那一局）**：`TARGET` 只在
    "武装"那一刻写一次，那一局的日志里**根本没有它** —— 分析器据此报了「不判」，
    白白丢掉一条本可以判的读数（法律换没换）。同一局的 `ROLE` 行有 **56 条**，
    tag 明明白白写在第一格。档案 ↔ 国家是**数据源里的事实**（`[archive].country`），
    比"某一条只在某一刻写的日志"稳得多（P9：事实只有一处定义）。

    一个国家对上**多份**档案时返回空串（不猜）—— 现在的八份各占一个国家，
    但抽象没保证这条，所以按"唯一才认"写。
    """
    for line in ours:
        if "ZZPROBE AB;TARGET;" in line:
            body = line.split("ZZPROBE AB;TARGET;", 1)[1].split('"', 1)[0]
            return body.split(";")[0].strip()
    tag = _subject_tag(ours)
    if not tag:
        return ""
    matched = [archive.id for archive in modgen.load_all() if archive.country == tag]
    return matched[0] if len(matched) == 1 else ""


def _law_reading(laws: list[str], ours: list[str]) -> dict[str, object]:
    """按**这一局那个国家所属档案**声明的法报"换没换"（B80）。

    声明了 `[probe].reform_law` ⇒ 报「盯的法」+「它还在不在」；
    没声明（或日志里读不到国家）⇒ **这一栏不判**，并说明为什么。
    """
    archive_id = _subject_archive(ours)
    target = next((archive for archive in modgen.load_all() if archive.id == archive_id), None)
    if target is None or target.probe is None or not target.probe.reform_law:
        why = (
            f"这一局盯的是 {archive_id}，它没声明 `[probe].reform_law`"
            if archive_id
            else "日志里既没有 `TARGET` 行、也没有可反查的 `ROLE;<TAG>` 行"
        )
        return {
            "⚠️ 法律换过没有：不判": f'{why} —— 数据源里补 `[probe] reform_law = "law_…"` 才能判'
        }
    declared = target.probe.reform_law
    return {
        f"本档案盯的法（{target.id}.[probe].reform_law）": declared,
        f"✅ 那条法已不是现行法律（{declared}）": declared not in laws,
    }


def analyze(log: Path | None = None) -> dict[str, object]:
    """从日志里取读数：分类计数 + 去重后的变化序列。

    ⚠️ 读的是**整个日志目录**（含轮转副本 `debug.1.log`…），且按内容去重 ——
    一局跑得久时 `debug.log` 会被轮转，只看它就会把早期读数（比如第一次换牌）
    当成"没发生过"。去重口径与 `pdx.ab._read` 相同：逐字节相同的文件只算一次。

    判据口径（先写死，避免事后挑对自己有利的读法）：
    * **成功** = `LAW;<非 law_serfdom>` 出现过（法律真的换了）；
    * **牌闸门成立** = `STRATEGY;ai_strategy_progressive_agenda` 出现过；
    * **窗口开过** = `JE;active` 出现过。
    """
    base = (log or DEBUG_LOG).parent
    chunks: list[str] = []
    seen: set[str] = set()
    for path in sorted(base.glob("debug*.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if text in seen:
            continue
        seen.add(text)
        chunks.append(text)
    ours = [line for line in "\n".join(chunks).splitlines() if "ZZPROBE AB;" in line]
    # ⚠️ **日志会跨会话**（`debug.log` 按大小轮转，上一次会话的尾巴会留在 `debug.1.log` 里）。
    # 所以"这一局有没有自报"不能只看"日志里有没有" —— 必须**只算最后一轮之后**的行。
    # 判据是探针的 `RUN` 行（自励与决议各写一次）；没有 `RUN` 行时退回"全部"。
    run_at = max(
        (index for index, line in enumerate(ours) if "ZZPROBE AB;RUN;" in line), default=-1
    )
    ours = ours[run_at + 1 :] if run_at >= 0 else ours
    kinds: Counter[str] = Counter()
    timeline: list[tuple[str, str, str]] = []
    for line in ours:
        body = line.split("ZZPROBE AB;", 1)[1].split('"', 1)[0]
        parts = body.split(";")
        kinds[parts[0]] += 1
        # 三格：`CLOUT;<ig>;<档位>` 用的是前两格，别的行只用第一格。
        timeline.append(
            (
                parts[0],
                parts[1] if len(parts) > 1 else "",
                parts[2] if len(parts) > 2 else "",
            )
        )
    laws = [b for k, b, _c in timeline if k == "LAW"]
    strategies = [b for k, b, _c in timeline if k == "STRATEGY"]
    je = [b for k, b, _c in timeline if k == "JE"]
    shocks = [b for k, b, _c in timeline if k == "SHOCK"]
    enact = [b for k, b, _c in timeline if k == "ENACT"]
    gov = [b for k, b, _c in timeline if k == "GOV"]
    # `CLOUT` 推的是"**≥** 档位"，所以每月每个 IG 会有多行。
    # ⚠️ 水位要取**出现过的最高档位**，不能取"出现次数最多的那一档" ——
    # 实测（2026-09-22）：智力界的 b03/b08 各 56 次、b12 49 次、b18 只有 9 次，
    # 按"最多"取会得到 `b03`（看起来它几乎没有政治力量），而它其实有 9 个月到过 0.18。
    # 这与 `pdx.ab` 里 `leg_top` 那个 bug 是同一类：**单调夹逼读数只能取极值**。
    clout: dict[str, Counter[str]] = {}
    for kind, ig, band in timeline:
        if kind == "CLOUT":
            clout.setdefault(ig, Counter())[band] += 1
    clout_top = {
        ig: max(counter, key=lambda band: int(band[1:])) if counter else "—"
        for ig, counter in clout.items()
    }

    # ⚠️ 这里**故意不再**派生"法律真的换了"这个布尔：它原来拿观测到的法与 `law_serfdom`
    # 比，那是**俄国口径** —— 奥地利开局读到的是 `law_autocracy`，法没换也会报 True
    # （实测踩过，见 backlog B80）。行为层的**权威读数**是下面的"立法读数"
    # （`is_enacting_law` 逐条问出来的 `ENACT`），法律本身则原样列在"法律读数"里。
    return {
        "总行数": len(ours),
        "分类计数": dict(kinds),
        "法律读数（去重，按出现顺序）": _dedupe(laws),
        "策略牌读数（去重，按出现顺序）": _dedupe(strategies),
        "窗口读数（去重）": _dedupe(je),
        "冲击读数（去重）": _dedupe(shocks),
        "立法读数（去重）": _dedupe(enact),
        "政府在朝（去重）": _dedupe(gov),
        "各 IG 的 clout 水位（最高档）": clout_top,
        **_law_reading(laws, ours),
        "✅ 进步牌挂上过": "ai_strategy_progressive_agenda" in strategies,
        "✅ 窗口开过": "active" in je,
        "✅ 冲击施加过": "yes" in shocks,
        "✅ 立法开过（任一候选法）": any(value != "none" for value in enact),
        "✅ 改革派进过政府": any(value != "landowners" for value in gov),
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
    parser.add_argument(
        "--archive",
        default="",
        help="探针盯哪一份档案（默认 = mod/data 里的第一份；阶段 5 每批各跑一次）",
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="**只装真 mod、不装探针** —— 测「和平期占槽率 ≈ 0」时必须这样（见 deploy 的说明）",
    )
    parser.add_argument(
        "--fresh-logs",
        action="store_true",
        help="开局前把旧日志挪去临时目录（判「这一局有没有自报」时必须，见 quarantine_logs）",
    )
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

    # ⚠️ **先挪日志、再改用户配置**：挪日志只动临时目录，失败了什么都不会被改；
    # 反过来（先 deploy 再挪）一旦挪失败，用户那 23 条 Workshop 配置就留在改动状态
    # （实测踩过：崩完 enabledMods 只剩 1 条）。
    if args.fresh_logs:
        moved_logs = quarantine_logs()
        print(f"已把 {len(moved_logs)} 个旧日志挪去临时目录（这一局的读数只可能来自这一局）")
    print(deploy(with_probe=not bool(args.no_probe), archive_id=args.archive or None))
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
        # 引擎侧的判定要在收尾挪走成绩单**之前**读（见 `engine_verdict`）。
        report["verdict"] = engine_verdict()
        report["analysis"] = analyze()
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        killed = kill_game()
        time.sleep(2)
        moved = quarantine_test_artifacts()
        if previous:
            ga._set_foreground(previous)
        if moved:
            print(f"已把 {len(moved)} 个 testoutput.xml 挪去临时目录（否则 v3 verify 会红）")
        if not args.keep_installed:
            print(f"收尾：杀掉 {killed or '（没有）'}；{restore()}")
        else:
            print(f"收尾：杀掉 {killed or '（没有）'}；**按 --keep-installed 保留安装**")

    if failure:
        print(f"\n[失败] {failure}")
        return 1
    print("\n=== 读数（判据口径见脚本 docstring）===")
    for key, value in (report.get("verdict") or {}).items():
        print(f"  {key:34s}: {value}")
    for key, value in (report.get("analysis") or {}).items():  # type: ignore[union-attr]
        print(f"  {key:34s}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
