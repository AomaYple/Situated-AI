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

from pdx import ab_probe, config, modgen, mods, preflight
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

    ⚠️ **为什么要有 ②**（2026-09-23 实测）：`TARGET` 只在"武装"那一刻写**一次**，
    它落在**哪一份**轮转日志里取决于那一局写了多少 —— 实测 `bv_alignment` 那一局它在
    `debug.1.log` 里、而 `debug.log` 里是 **0 条**。只看 `debug.log` 就会得出
    "这一行没落"的错误结论（当时就是这么误判的，见 `exec/阶段5-实机读数补记.md` §四）。
    而 `ROLE` 行**每月都写**（一局 68 条），第一格就是 tag —— 拿它去对
    `[archive].country`（数据源里的事实）比"某一条只在某一刻写、还可能被轮到别的文件里"
    的日志稳得多（P9：事实只有一处定义）。

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


def _probe_target(ours: list[str]) -> tuple[str, object | None]:
    """``(档案 id, 那份档案)`` —— 认不出来时 ``("", None)``。"""
    archive_id = _subject_archive(ours)
    target = next((a for a in modgen.load_all() if a.id == archive_id), None)
    return archive_id, target


def _law_reading(laws: list[str], ours: list[str]) -> dict[str, object]:
    """按**这一局那个国家所属档案**声明的法报"换没换"（B80）。

    声明了 `[probe].reform_law` ⇒ 报「盯的法」+「它还在不在」；
    没声明（或日志里读不到国家）⇒ **这一栏不判**，并说明为什么。
    """
    archive_id, target = _probe_target(ours)
    if target is None or target.probe is None or not target.probe.reform_law:  # type: ignore[attr-defined]
        why = (
            f"这一局盯的是 {archive_id}，它没声明 `[probe].reform_law`"
            if archive_id
            else "日志里既没有 `TARGET` 行、也没有可反查的 `ROLE;<TAG>` 行"
        )
        return {
            "⚠️ 法律换过没有：不判": f'{why} —— 数据源里补 `[probe] reform_law = "law_…"` 才能判'
        }
    declared = target.probe.reform_law  # type: ignore[attr-defined]
    return {
        f"本档案盯的法（{target.id}.[probe].reform_law）": declared,  # type: ignore[attr-defined]
        f"✅ 那条法已不是现行法律（{declared}）": declared not in laws,
    }


def _card_reading(strategies: list[str], ours: list[str]) -> dict[str, object]:
    """按**这一局那个国家所属档案**声明的政治议程牌报「意图层动没动」（B86/B87）。

    为什么不能把 `ai_strategy_progressive_agenda` 写死在分析器里：判据是"那张牌**出现过**"，
    而有的国家**开局就挂着它**（巴西，`common/history/ai/00_strategy.txt:42-45`）
    ⇒ 写死的那一版对巴西**必然假真**。所以改成每份档案显式声明，空 = 不判。

    ⚠️ **空是正当结论，不是遗漏**：查实了但那张牌对这份档案没有判别力时，
    就该留空并写明 —— 行为层改看 `ENACT` 与 `GOV` 两条通用读数。

    ⚠️ **「一行都没有」与「牌是 none」必须分开报**（2026-09-23 加，B87）：
    探针那条 `STRATEGY` 链是 `if/else_if … else`，链尾一定会落一行 —— 所以
    `strategies == []` **只可能**意味着根本没读到这类行（老归档 / 探针没盯这个国家 / 日志被剪过），
    而它此前会被报成"那张牌没挂上过"（**假否定**）。现在分开说。
    """
    archive_id, target = _probe_target(ours)
    if not strategies:
        return {
            "⚠️ 意图层动没动（牌）：读不到 `STRATEGY` 行": (
                "日志里这类行是 0 条 —— 老归档（2026-09-22 之前的探针没有这一格）、"
                "探针没盯这个国家、或日志被剪过，都会这样。"
                "**这不是「牌没挂上」**：探针的链尾必有 `else`，真跑过就一定有一行。"
            )
        }
    if target is None or target.probe is None or not target.probe.reform_card:  # type: ignore[attr-defined]
        why = (
            f"这一局盯的是 {archive_id}，它没声明 `[probe].reform_card`"
            if archive_id
            else "日志里既没有 `TARGET` 行、也没有可反查的 `ROLE;<TAG>` 行"
        )
        return {"⚠️ 意图层动没动（牌）：不判": f"{why} —— 见该档案 `[probe].why` 里写的理由"}
    declared = target.probe.reform_card  # type: ignore[attr-defined]
    return {
        f"本档案盯的牌（{target.id}.[probe].reform_card）": declared,  # type: ignore[attr-defined]
        f"✅ 那张牌挂上过（{declared}）": declared in strategies,
    }


def debug_logs(base: Path) -> list[Path]:
    """引擎的调试日志，**按时间从旧到新**。

    ⚠️ **不许直接 `sorted()`**（实测踩过，2026-09-23）：轮转副本叫 `debug.1.log` …
    `debug.4.log`，当前那份叫 `debug.log` —— 字典序把**当前那份排在最后、次新的排在最前**，
    于是拼出来的文本时间顺序是错的（最新那份夹在中间）。

    后果不是"少读一点"，而是**读出一段不连续的切片**：下面的 `RUN` 切片按拼接后的位置
    找"最后一次武装"，会切在最旧那份的中间 —— `debug.3` / `debug.2` / `debug.1` 整份被丢掉，
    而最新的 `debug.log` 被接在后面。实测同一个目录：**盘上 1,401 行自报，分析器只报了 402 行**，
    还报出一个**假的**「窗口 `inactive → active`」顺序（那是把最旧那份的尾巴接到最新那份上
    拼出来的）。

    正确顺序：编号大的在前（`debug.4` → `debug.1`），当前那份最后。
    """
    rotated = sorted(
        (p for p in base.glob("debug.[0-9]*.log") if p.stem.rsplit(".", 1)[-1].isdigit()),
        key=lambda p: -int(p.stem.rsplit(".", 1)[-1]),
    )
    return [*rotated, *(p for p in [base / "debug.log"] if p.is_file())]


def analyze(log: Path | None = None, *, only_after_arm: bool = True) -> dict[str, object]:
    """从日志里取读数：分类计数 + 去重后的变化序列。

    ⚠️ 读的是**整个日志目录**（含轮转副本 `debug.1.log`…），顺序按 :func:`debug_logs`；
    逐字节相同的文件只算一次。一局跑得久时 `debug.log` 会被轮转，只看它就会把早期读数
    （比如第一次换牌）当成"没发生过"。

    ``only_after_arm``：只算**最后一次武装之后**的行。它的原意是排除**上一局**留在轮转
    文件里的尾巴；但观察者局里没有 `RUN;A`（决议点不到），第一次武装标记是第 37 个月的
    `RUN;B` —— 于是它会**把这一局自己的前 37 个月剪掉**，"窗口开过没有"这类
    **存在性**判据就变成"第 37 个月之后开过没有"。
    ⇒ 用 `--fresh-logs` 跑（日志全是这一局的）时**必须传 False**，调用点见 `main()`。

    判据口径（先写死，避免事后挑对自己有利的读法）：
    * **成功** = `LAW;<非 law_serfdom>` 出现过（法律真的换了）；
    * **牌闸门成立** = 该档案 `[probe].reform_card` 声明的那张牌出现过（**每份档案各自声明**，
      留空 = 不判 —— 写死 `progressive_agenda` 对巴西必然假真，见 `_card_reading` / B86）；
    * **窗口开过** = `JE;active` 出现过。
    """
    base = (log or DEBUG_LOG).parent
    chunks: list[str] = []
    seen: set[str] = set()
    for path in debug_logs(base):
        text = path.read_text(encoding="utf-8", errors="replace")
        if text in seen:
            continue
        seen.add(text)
        chunks.append(text)
    ours = [line for line in "\n".join(chunks).splitlines() if "ZZPROBE AB;" in line]
    total_lines = len(ours)
    # ⚠️ **日志会跨会话**（`debug.log` 按大小轮转，上一次会话的尾巴会留在 `debug.1.log` 里）。
    # 所以"这一局有没有自报"不能只看"日志里有没有" —— 必须**只算最后一轮之后**的行。
    # 判据是探针的 `RUN` 行（自励与决议各写一次）；没有 `RUN` 行时退回"全部"。
    # 但这把剪刀在观察者局里会剪掉这一局自己的前 37 个月（见 docstring）⇒ `--fresh-logs` 时不剪。
    run_at = (
        max((index for index, line in enumerate(ours) if "ZZPROBE AB;RUN;" in line), default=-1)
        if only_after_arm
        else -1
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
    legitimacy = _preferred_scalars(timeline, "LEGV", "LEGF")
    clout_values = _numbers(timeline, "CLOUTV") or _numbers(timeline, "CLOUTP")
    progress = _scalars(timeline, "PROG")
    numbers: dict[str, object] = {}
    if legitimacy:
        numbers["合法性数值（逐月）"] = _series_summary(legitimacy)
    for ig, values in sorted(clout_values.items()):
        numbers[f"IG 政治力量数值（{ig}）"] = _series_summary(values, unit="%")
    if progress:
        numbers["立法进度数值"] = _series_summary(progress)
    return {
        # 两个数都要报：只报"算进去多少"会让人以为那就是盘上的全部（实测踩过：
        # 盘上 1,401 行、只报了 402 行，而输出里看不出被剪掉了什么）。
        "盘上自报行数": total_lines,
        "算进读数的行数": len(ours),
        "分类计数": dict(kinds),
        "法律读数（去重，按出现顺序）": _dedupe(laws),
        "策略牌读数（去重，按出现顺序）": _dedupe(strategies),
        "窗口读数（去重）": _dedupe(je),
        "冲击读数（去重）": _dedupe(shocks),
        "立法读数（去重）": _dedupe(enact),
        "政府在朝（去重）": _dedupe(gov),
        "各 IG 的 clout 水位（最高档）": clout_top,
        **numbers,
        **_law_reading(laws, ours),
        **_card_reading(strategies, ours),
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


def _to_float(text: str) -> float | None:
    """``"61.4"`` / ``"24.8%"`` → 数值；读不出来给 ``None``（**不编 0**）。

    ⚠️ data function 拼错时引擎会把 `[...]` **原样**留在日志里 —— 那时日志里确实有这一行，
    但它的值是字面量。报 0 是最坏的失败形态（「合法性跌到 0」看起来像个发现）。
    """
    try:
        return float(text.replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _scalars(timeline: list[tuple[str, str, str]], kind: str) -> list[float]:
    """**单值**读数（``LEGV`` / ``PROG``）：第 1 格就是数值（第 2 格是国名）。"""
    out: list[float] = []
    for row_kind, value, _rest in timeline:
        if row_kind != kind:
            continue
        number = _to_float(value)
        if number is not None:
            out.append(number)
    return out


def _numbers(timeline: list[tuple[str, str, str]], kind: str) -> dict[str, list[float]]:
    """**带标签**的数值读数（``CLOUTV;<ig>;<数值>``）→ ``{标签: [逐月数值]}``。

    为什么要有数值读数（2026-09-24，B88）：旧的合法性读数是**五档夹逼**（b55/b60/b70/b75/b80），
    而夹逼读数**量不出档内的变化** —— 「我们的压力把合法性抬起 1 分还是 5 分」
    这个问题在旧读数里长得一模一样。原版自己就能打数字
    （`[GetPlayer.GetGovernmentLegitimacy|v]`、`[InterestGroup.GetClout|%1]`），
    所以探针改成记数值；解析**容忍读不出来**（见 :func:`_to_float`）。
    """
    out: dict[str, list[float]] = {}
    for row_kind, label, value in timeline:
        if row_kind != kind:
            continue
        number = _to_float(value)
        if number is not None:
            out.setdefault(label, []).append(number)
    return out


def _series_summary(values: list[float], *, unit: str = "") -> str:
    """一串数值 → 一句人读的摘要（首 → 末，最低/最高）。

    ⚠️ 首末比"均值"值钱：B88 要问的是**压力施加前后动没动**，那是一个方向问题。
    """
    if not values:
        return "（没有数值读数）"
    first, last = values[0], values[-1]
    tail = f"{unit}" if unit else ""
    return (
        f"{first:g}{tail} → {last:g}{tail}"
        f"（共 {len(values)} 个月；最低 {min(values):g}、最高 {max(values):g}）"
    )


def _preferred_scalars(timeline: list[tuple[str, str, str]], *kinds: str) -> list[float]:
    """从若干**同义读数**里取第一个解析得出数值的那一组（``LEGV`` / ``LEGF``）。

    为什么要两条：`debug_log` 里带不带格式指令（`|v`）是**一个没验过的细节**，
    而验它的代价是一次实机会话。所以探针两条都记，这里取能解析的那一条 ——
    「哪条能用」这件事由数据回答，不由猜。
    """
    for kind in kinds:
        values = _scalars(timeline, kind)
        if values:
            return values
    return []


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
        "--skip-preflight",
        action="store_true",
        help="跳过开局前的自检（默认自检：起游戏一次约 137 秒，白跑一次远比自检贵）",
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
    parser.add_argument(
        "--whole-log",
        action="store_true",
        help="把这些日志**整段**当成同一局（不按 `RUN` 剪切）。跑过 --fresh-logs 的日志本来"
        "就该这样读；与 --analyze-only 合用时用它复核历史日志",
    )
    args = parser.parse_args(argv)

    # `--fresh-logs` 已经把上一局的日志挪走了 ⇒ 盘上剩的全是这一局的，**不该再按 RUN 剪切**
    # （观察者局里那把剪刀会剪掉这一局自己的前 37 个月，见 `analyze`）。
    only_after_arm = not (args.fresh_logs or args.whole_log)

    if args.analyze_only:
        result = analyze(only_after_arm=only_after_arm)
        mode = "只算最后一次武装之后" if only_after_arm else "整段（全是这一局的）"
        print(f"  {'读数区间':34s}: {mode}")
        for key, value in result.items():
            print(f"  {key:34s}: {value}")
        return 0

    # ⚠️ **自检放在任何改动之前**（2026-09-23）：起游戏到选国家界面实测约 137 秒，
    # 还要跑几十个游戏月 —— 而"探针盯错了国家""盘上产物是手改过的""日志里混着上一局"
    # 这些条件**开局前全部可查**。一次白跑的代价远大于这几毫秒。
    if not args.skip_preflight:
        report = preflight.run(archive=args.archive or None)
        for line in report.lines():
            print(f"  {line}")
        if report.exit_code():
            print("  ⇒ 先处理上面这些再开局（确实想跳过：--skip-preflight）")
            return report.exit_code()

    # ⚠️ **上一次被强杀留下的探针态，这里自愈**（2026-09-24 真实事故）：
    # 会话被中途杀掉时 `finally` 不会跑，用户的配置就留在"只剩探针"的状态里
    # —— 而那个状态**只可能是我们造成的**（用户不会把 `zz_probe*` 加进自己的列表），
    # 所以拿备份还原是安全的。自愈之后照常继续，不让人为了修我们留下的状态再跑一趟。
    if preflight.probe_state_backup() is not None and BACKUP.exists():
        print(f"⚠️ 上次会话把配置留在探针态 —— 先用 {BACKUP.name} 还原，再继续")
        print(f"  {restore()}")

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
        report["analysis"] = analyze(only_after_arm=only_after_arm)
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
