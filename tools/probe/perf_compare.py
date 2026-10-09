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

## 受控性：两臂的压力自报必须逐行相等（2026-09-25 起）

`--stress` 时两臂都装同一份压力剧本（`pdx.stress_probe`），它在每一波落地时由**一个写死的国家**
写一行 `ZZPROBE STRESS;<KIND>;<wave>;<target>`（格式在 `stress_probe` 的模块 docstring 里）。
本脚本在两臂跑完后把两串序列**逐行比对**（`:func:`stress_control_verdict``）：

* 不等 ⇒ **出声失败**（退出码 1，并指出第一处不同的波次与两臂各自那一行，P13）；
* **一条都没有** ⇒ 也是失败 —— "两边都空所以相等"是**空的**受控（窗口里根本没压力落地）；
* 形状不对的自报行（分类不认识等）⇒ 同样失败（格式漂了，"相等"两个字就没有意义）。

⇒ `阶段4-结果.md` §六·补 那张表里的"**非受控**"因此可以升级成"**受控**"，
判据 = 这次的退出码 + `compare.json` 里的 `stress` 块（每局的序列都在里面）。

## 第三臂 `--tempo-arm`（B27，默认关闭）

`--tempo-arm` 多跑一条臂 `tempo` = **原版 + 剧本 + 只挂那一份 tempo defines 的壳 mod**
（`mod/common/defines/*_tempo.txt`，逐字节复制 `v3 modgen` 的产物 —— 探针不重写生成物）。
口径见 `docs/design/exec/阶段4-压力剧本-口径.md` §6：`Δ_tempo = M_tempo − M_vanilla`，盯 `UpdateAI`，
把"节奏杠杆的开销"从 ours 臂的混杂项里**分离**出来。

⚠️ **默认关闭 ⇒ 两臂的行为、产物名与报告格式与从前一字不差**：第三臂的 CSV 是
`tempo-<序号>.csv`（不与 `vanilla-<序号>.csv` / `ours-<序号>.csv` 冲突），壳 mod 落在
`<用户 mod 目录>/zz_probe_tempo_only`（跑完删除，`finally` 里）。
**本卡只提供能力、不跑实机** —— 实跑由 `t22` 按窗口预算决定；不跑就按口径页把它标成混杂项。

## 收尾（P12/可回滚）

统一收尾路径由 `finally`、`atexit`、Ctrl+C、SIGTERM 和 Windows SIGBREAK 共同触发：
只终止本次会话启动的游戏进程 → 原子还原 `content_load.json` → 删除本次产物并恢复运行前同名目录。
每项收尾独立执行，结果写入 `tools/out/perf/cleanup.json`；**用户原来的 Workshop 配置和本地同名 mod 都会恢复。**

⚠️ 操作系统级强杀（例如 `SIGKILL` 或 Windows `TerminateProcess`）不会执行用户态清理；
这种情况会留下临时隔离区，下一次运行前应先检查并恢复。

⚠️ **跑完之后请再跑一局常规游戏**（`python -m pdx.game_auto run`，用用户自己的 mod 配置）：
本脚本的两局都是"只挂本地 mod"，引擎日志因此是在**另一套 mod 集**下产生的，而
`tests/test_cli.py::test_crosscheck_与引擎日志一致` 拿日志行号与原版安装比对 ——
mod 集不同会让它红（实测踩过）。跑一局常规游戏即可让日志与安装一致。

用法：`python tools/probe/perf_compare.py [月数] [--repeat N] [--load-save <观察者检查点.v3>]`

提供 `--load-save` 时，每条臂都从同一份经过版本、观察者身份、停用 Mod 状态和空规则引用检查的
固定检查点启动；源文件先复制到临时 holding 目录，再隔离用户存档目录，收尾删除临时副本并恢复用户原件。
这只是满足固定输入的前置条件，仍需正式三组配对、相同起止日期、真实后期输入和无引擎错误窗口才能形成 M4 结论。

正式 M4 性能表要求 `--repeat 3`；少于三组只产生探索性读数，不会形成正式成对结论。
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import math
import os
import shutil
import signal
import sys
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass, field
from functools import partial
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


from pdx import ab_probe, config, gametimer, stress_probe
from pdx import game_auto as ga
from pdx.console import enable_utf8_stdio
from pdx.game_run import RunLock, save_header, validate_load_save_header
from pdx.textio import deploy_tree, text_bytes

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

DOCS = config.USERDIR
MODS_DIR = DOCS / "mod"
CONTENT_LOAD = DOCS / "content_load.json"
LOGS = DOCS / "logs"
SAVE_DIR = DOCS / "save games"
RULE_PRESETS = DOCS / "player" / "game_rules" / "presets.txt"

#: 标准压力剧本（阶段 4 ④）在用户 mod 目录里的落点。`--stress` 时**两臂都装它** ——
#: 单装一臂就等于把"世界被推到高压"这件事算进了那一臂的差里，对照立刻作废。
STRESS_DST = stress_probe.dest()

#: 真 mod 的安装目录名 —— **从数据源读**（`mod/data/*.toml`），不在探针里写死。
#:
#: 为什么不写死：阶段 5 的 G-EXIT-1 是"加一行数据 = 加一个处境、不改逻辑"。
#: 目录名一旦在探针里写死，就多出若干处"改了数据还得顺手改的 Python"；
#: 而 `ab_probe.load_target()` 已经是那条链的单一来源（`ab_probe.deploy()` 同样读它）。
_TARGET = ab_probe.load_target()
if _TARGET is None:
    raise RuntimeError("未发现可用于性能对照的 mod 目标")
OURS_DST = MODS_DIR / _TARGET.dir_name
OUT_DIR = config.OUT / "perf"

#: 三条臂的标签（= `run_once` 的 `label` = CSV 文件名前缀 = 报告里的 label）。
#: **前两条是默认臂**；第三条（B27 的 `tempo-only`）要显式开，见 :func:`arm_labels`。
VANILLA_LABEL = "vanilla"
OURS_LABEL = "ours"
TEMPO_LABEL = "tempo"
KNOWN_ARM_LABELS = frozenset({VANILLA_LABEL, OURS_LABEL, TEMPO_LABEL})

# M4 预注册的每个检查点成对样本数。探索性短跑可以少于此数，但必须明确不能作为
# 正式性能验收；报告函数据此不再把单组读数伪装成 M4 结论。
REQUIRED_M4_PAIRS = 3


RUN_LOCK = config.USERDIR / ".sitai-game.lock"


def arm_labels(tempo_arm: bool = False) -> tuple[str, ...]:
    """这一轮要跑的臂（**顺序就是交替顺序**；默认两臂与从前一字不差）。"""
    if tempo_arm:
        return (VANILLA_LABEL, OURS_LABEL, TEMPO_LABEL)
    return (VANILLA_LABEL, OURS_LABEL)


def arm_csv_path(label: str, index: int) -> Path:
    """某一臂某一局的 CSV 落点（**产物路径的唯一来源**）。

    为什么单开一个函数：三条臂的路径必须互不冲突，而路径原来是就地拼的字符串 ——
    多一条臂时"撞名"**不会有任何报错**（后一局把前一局的 CSV 覆盖掉，报告里两条臂读出同一份）。
    有了单一来源，"三臂路径互不相同"才能被一条**不跑游戏**的用例钉住。
    """
    return OUT_DIR / f"{label}-{index}.csv"


def arm_mods(label: str, stress_mods: Sequence[Path]) -> list[Path]:
    """这一臂挂哪些**本地** mod：基线 = 剧本；处理 = 剧本 + 我们；第三臂 = 剧本 + 壳 mod。"""
    if label == OURS_LABEL:
        return [*stress_mods, OURS_DST]
    if label == TEMPO_LABEL:
        return [*stress_mods, TEMPO_DST]
    return [*stress_mods]


#: 第三臂（B27）的**壳 mod** 名字：只挂那一份 tempo defines，不带任何档案产物。
#:
#: 前缀取 `mods.PROBE_PREFIX`（`zz_probe_`）**且** id 取 `sitai.` 前缀 —— **两条判据都占上**：
#: `pdx.mods.discover_mods()` 按**目录名前缀**排除探针、按 **id 前缀**排除我们自己部署的 mod
#: （`mods.py:185`、`:203`、`:229-246`；B83 记的就是后者踩过的坑）。
#: 少占一条，"多跑了一条臂"就会把本机 mod 统计与黄金回归指纹一起顶掉。
TEMPO_MOD_NAME = "zz_probe_tempo_only"
TEMPO_DST = MODS_DIR / TEMPO_MOD_NAME
TEMPO_DEFINES_GLOB = "*_tempo.txt"


@dataclass
class PerfCleanup:
    """一次性能对照会话的可重复、可中断收尾状态。

    运行前已存在的探针目录先移到临时隔离区，再允许运行器重建同名目录。
    异常、Ctrl+C、SIGTERM 和正常返回都走同一条恢复路径，且不会误删用户
    原有的本地 mod。所有步骤独立执行，第一步失败不能阻断配置和目录恢复。
    """

    content_path: Path
    backup_path: Path
    generated_paths: tuple[Path, ...]
    killer: Callable[[], list[int]]
    restore_dir: Path | None = None
    path_backups: dict[Path, Path] = field(default_factory=dict)
    claimed_paths: set[Path] = field(default_factory=set)
    removed_paths: set[Path] = field(default_factory=set)
    restored_paths: set[Path] = field(default_factory=set)
    content_restored: bool = False
    cleaned: bool = False
    running: bool = False
    deferred_signals: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error_history: list[str] = field(default_factory=list)
    archived_logs: list[str] = field(default_factory=list)
    reason: str = ""

    def claim_existing_paths(self) -> None:
        """把运行前同名路径安全移入临时隔离区。"""
        if self.restore_dir is None:
            self.restore_dir = Path(tempfile.mkdtemp(prefix="sitai-perf-restore-"))
        for index, path in enumerate(self.generated_paths):
            if not (path.exists() or path.is_symlink()):
                self.claimed_paths.add(path)
                continue
            backup = self.restore_dir / f"{index}-{path.name}"
            shutil.move(str(path), str(backup))
            self.path_backups[path] = backup
            self.claimed_paths.add(path)

    def _step(self, label: str, action: Callable[[], object]) -> object | None:
        try:
            return action()
        except Exception as exc:  # pragma: no cover - 实机权限/占用故障
            self.errors.append(f"{label}: {type(exc).__name__}: {exc}")
            return None

    def _restore_content(self) -> None:
        """原子替换 content_load，避免恢复过程中留下半个 JSON。"""
        if self.content_restored:
            return
        if not self.backup_path.is_file():
            raise FileNotFoundError(f"备份不存在：{self.backup_path}")
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.content_path.name}.restore-",
            dir=str(self.content_path.parent),
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            shutil.copyfile(self.backup_path, temp_path)
            temp_path.replace(self.content_path)
            self.content_restored = True
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    @staticmethod
    def _restore_path(backup: Path, path: Path) -> None:
        """恢复文件或目录前创建父目录，覆盖游戏未重建状态目录的情况。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(backup), str(path))

    def _clean_generated_path(self, path: Path) -> None:
        """清理一个产物路径并最多恢复一次原件，支持失败后安全重试。"""
        if path not in self.claimed_paths:
            return
        if path in self.restored_paths or path in self.removed_paths:
            return
        backup = self.path_backups.get(path)
        if backup is None:
            self._remove_path(path)
            self.removed_paths.add(path)
            return
        # 备份缺失时绝不能先删目标：它可能已在上次 cleanup 调用中成功恢复。
        if not (backup.exists() or backup.is_symlink()):
            raise FileNotFoundError(f"原件备份不存在且恢复状态未知：{backup}")
        self._remove_path(path)
        self._restore_path(backup, path)
        self.restored_paths.add(path)

    def run(self, *, reason: str) -> tuple[str, ...]:
        """执行一次幂等收尾，并返回所有收尾错误。"""
        if self.cleaned or self.running:
            return tuple(self.errors)
        self.running = True
        self.reason = reason
        if self.errors:
            self.error_history.extend(self.errors)
            self.errors.clear()
        try:
            killed = self._step("终止本次游戏", self.killer)
            if killed is None:
                self.errors.append("无法确认游戏已退出；保留原配置、目录备份和实验资源")
                return tuple(self.errors)
            try:
                remaining = ga._process_pids()
            except Exception as exc:
                self.errors.append(f"无法独立核实游戏退出；保留原件与实验资源：{exc}")
                return tuple(self.errors)
            alive = getattr(ga, "LAST_KILL_ALIVE", ())
            if alive or remaining:
                self.errors.append(f"游戏进程仍存活：{list(alive or remaining)}")
                self.errors.append("原配置与目录备份已保留；不在游戏仍运行时恢复或删除实验资源")
                return tuple(self.errors)
            self._step("恢复 content_load.json", self._restore_content)
            for path in self.generated_paths:
                self._step(
                    f"清理并恢复路径 {path.name}",
                    partial(self._clean_generated_path, path),
                )
            restore_dir = self.restore_dir
            if restore_dir is not None and restore_dir.exists() and not self.errors:
                self._step("删除临时隔离区", lambda: shutil.rmtree(restore_dir))
            moved = self._step("归档本次日志", _quarantine_logs)
            if isinstance(moved, list):
                self.archived_logs.extend(str(item) for item in moved)
            if not self.errors:
                self._step(
                    "删除 content_load 备份", lambda: self.backup_path.unlink(missing_ok=True)
                )
        finally:
            self.running = False
            # cleaned 表示关键收尾全部完成；任何错误都必须进入报告并让 CLI 失败。
            self.cleaned = not self.errors
            self._write_report()
            self.cleaned = not self.errors
        return tuple(self.errors)

    def _write_report(self) -> None:
        """尽力留下可复核的收尾结果；报告写失败不能掩盖原始异常。"""
        try:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            (OUT_DIR / "cleanup.json").write_text(
                json.dumps(
                    {
                        "reason": self.reason,
                        "cleaned": self.cleaned,
                        "deferred_signals": list(self.deferred_signals),
                        "errors": list(self.errors),
                        "error_history": list(self.error_history),
                        "archived_logs": list(self.archived_logs),
                        "restored_paths": [str(path) for path in sorted(self.restored_paths)],
                        "removed_paths": [str(path) for path in sorted(self.removed_paths)],
                        "pending_paths": [
                            str(path)
                            for path in sorted(
                                self.claimed_paths - self.restored_paths - self.removed_paths
                            )
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
                newline="\n",
            )
        except Exception as exc:  # pragma: no cover - 输出目录不可写
            self.errors.append(f"写入收尾报告: {type(exc).__name__}: {exc}")


def _make_backup(path: Path) -> Path:
    """创建不会覆盖旧备份的字节级副本。"""
    fd, name = tempfile.mkstemp(
        prefix=f"{path.name}.sitai-perf-", suffix=".backup", dir=str(path.parent)
    )
    os.close(fd)
    backup = Path(name)
    try:
        shutil.copyfile(path, backup)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _install_cleanup_handlers(cleanup: PerfCleanup) -> Callable[[], None]:
    """注册退出、Ctrl+C、SIGTERM 和 Windows SIGBREAK 的统一收尾。"""
    previous: dict[int, object] = {}

    def handle(signum: int, _frame: object) -> None:
        name = signal.Signals(signum).name
        if cleanup.running:
            cleanup.deferred_signals.append(name)
            return
        cleanup.run(reason=name)
        if signum == getattr(signal, "SIGINT", -1):
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    signals = [signal.SIGINT, signal.SIGTERM]
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signals.append(sigbreak)
    for signum in signals:
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, handle)
        except (OSError, RuntimeError, ValueError):
            continue

    def at_exit() -> None:
        cleanup.run(reason="atexit")

    atexit.register(at_exit)

    def restore() -> None:
        for signum, old in previous.items():
            with suppress(OSError, RuntimeError, ValueError):
                signal.signal(signum, cast("Callable[[int, object], object]", old))

    return restore


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


def _announce(fault: str) -> None:
    """挪不动 / 被改名时的**唯一出声处**（默认出口；`t36`，B114）。

    为什么单开一个函数：静默就是证据蒸发。有了这个出口，"文件没挪走却没人知道"
    这条路径才被堵住 —— 出声看得见（stderr 一行），也被用例收集得到（注入 `announce`）。
    """
    print(f"  [隔离日志] {fault}", file=sys.stderr)


def _quarantine_logs(
    *,
    stamp: str | None = None,
    announce: Callable[[str], None] | None = None,
) -> list[str]:
    """把上一次会话的日志挪去**本跑者自己的**隔离目录 —— **两局对照必须这样做**。

    为什么：`debug.log` 按大小轮转，上一局的尾巴会留在 `debug.1.log`… 里。
    `_mounted_evidence()` 读的是"日志里有没有 Mounted Data"，跨会话残留会让
    **第二局的取证里混进第一局的挂载记录** —— 那正是"原版局看起来也挂了 mod"的假象。

    ⚠️ **同名冲突要改名落地，既不覆盖也不静默**（`t36`，B114 的证据蒸发路径）：
    原写法是同名 `shutil.move(path, target / path.name)`。**实测的静默路径有三条**
    （`t12` 逐条复现，读数见 `docs/reports/t12-静默路径文案与回归.md`）：
    ① 隔离目录里已有同名**文件** ⇒ `os.rename` 抛 `FileExistsError`，`shutil.move`
    退回 `copy2` + `unlink` ⇒ **静默覆盖上一代**（实测 8 局里 7 局没归档就是这一条）；
    ② 已有同名**目录**、且那目录里**已有同名文件** ⇒ 走"目标是目录"支：先算出
    `target\\<名字>\\<名字>`、发现它存在 ⇒ 抛 **`shutil.Error`**（`Destination path …
    already exists`）—— 它是 `OSError` 子类，被下面那句
    `except (PermissionError, OSError): continue` **吞掉** ⇒ 文件**留在原地**、**零行输出**；
    ③ 已有同名**目录**、且那目录**为空** ⇒ 按"目标目录"语义把文件挪进
    `target\\<名字>\\<名字>` ⇒ **证据被埋深一层、零行输出、看不见**。
    现在复用 `src/pdx/game_auto.py:1717` 的 `unused_path()`（配 `:1708` 的
    `archive_stamp()`，**不另写一套**）：空着就用原名，被占则把 UTC 时间戳插进扩展名
    （`debug.log` → `debug.20260929-021712.log`，再冲突 `…-2.log`），**两代都留住**
    ⇒ 三条一起堵住（②那句 `shutil.Error` 再无机会出现：挑出来的名字一定是空的）。

    ⚠️ **挪不动的要出声**（2026-09-23 实测 `PermissionError`）：上一次跑批留下过一个进程，
    它握着 `ai.log` 的句柄 ⇒ `shutil.move` 抛 `PermissionError`，整局还没开始就崩。
    **跳过仍然是安全的**（被判据用到的是 `debug.log` / `system.log`，那两个不常被长期占用），
    但"跳过"现在**带一行出声**（路径 + 原因）—— 不再有"没挪走又没人知道"的路径。
    行里报的是**源路径 + 原因 + 隔离目录**：落点名由 `unused_path()` 挑，写成固定的
    `target\\<原名>` 会指到**占位**那一处（三条占位路径全都叫这个名字）。

    ⚠️ **三个近名目录不是一回事**（名字很像，找错了会把"在另一边"误判成"丢了"）：
    * `%TEMP%\\v3_quarantine_perflogs` —— **本文件**（perf_compare 跑者）自己的，就是这里；
    * `%TEMP%\\v3_quarantine_logs` —— `src/pdx/game_auto.py:1743` 的
      `quarantine_logs()` 的目标，`tools/probe/stage3_rerun.py` / `stage6_ui_rerun.py` 在用；
    * `%TEMP%\\v3_quarantine_stagetests` —— `tools/probe/stage3_rerun.py:154` 的
      `quarantine_test_artifacts()`（阶段 3 的**成绩单/产物**，不是引擎日志）。

    ``stamp`` / ``announce`` 是给用例的注入点：时间戳可固定、出声可收集（默认打 stderr）。
    """
    target = Path(tempfile.gettempdir()) / "v3_quarantine_perflogs"
    target.mkdir(parents=True, exist_ok=True)
    the_stamp = stamp or ga.archive_stamp()
    say = _announce if announce is None else announce
    moved: list[str] = []
    critical_failures: list[str] = []
    critical_names = {"debug.log", "system.log", "error.log"}
    for path in sorted(LOGS.glob("*.log")):
        try:
            landing = ga.unused_path(target / path.name, stamp=the_stamp)
            shutil.move(str(path), str(landing))
        except (PermissionError, OSError) as fault:
            message = (
                f"⚠️ 挪不动，文件仍在原地：{path}（{type(fault).__name__}: {fault}）"
                f"；隔离目录 {target}（落点名由 unused_path() 挑，不一定是原名）"
            )
            say(message)
            if path.name in critical_names:
                critical_failures.append(message)
            continue
        moved.append(landing.name)
        if landing.name != path.name:
            say(f"同名已在隔离目录：{path.name} → {landing.name}（两代都留住，没覆盖）")
    if critical_failures:
        raise RuntimeError("关键日志归档失败：" + "；".join(critical_failures))
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


# ── 压力自报：读取与比对（"受控 / 非受控"就是这一节）────────────────────────


def scan_stress_lines(directory: Path | None = None) -> stress_probe.ReportScan:
    """这一局日志里的**压力自报行**（按轮转顺序：`debug.N.log` 旧 → `debug.log` 新）。

    ⚠️ 顺序**不许**拿 `sorted()` 凑：字典序把 `debug.10.log` 排在 `debug.2.log` 前面，
    拼出来的时间顺序是错的（B85 实测踩过两次）⇒ 一律走 `ga.rotated_logs()`。

    为什么**不去重**：重复本身是"这一波释放了两次"的证据；两侧都会看到它，
    比对时能判出来 —— 去重就是把这件事实吃掉（P13）。
    """
    base = LOGS if directory is None else directory
    lines: list[str] = []
    malformed: list[str] = []
    for path in ga.rotated_logs(base, "debug"):
        scanned = stress_probe.scan_report_lines(path.read_text(encoding="utf-8", errors="replace"))
        lines.extend(scanned.lines)
        malformed.extend(scanned.malformed)
    return stress_probe.ReportScan(tuple(lines), tuple(malformed))


def _report_lines(report: dict[str, object]) -> list[str]:
    """一局报告里的自报序列（没有就是空列表 —— 由判据去判，不在这里补）。"""
    raw = report.get("stress_lines")
    return [str(item) for item in raw] if isinstance(raw, list) else []


# 一局的**自带**扫描结果：一个键里同时带 `lines` 与 `malformed`（t89 ②）。
STRESS_SCAN_KEY = "stress_scan"


def _as_str_list(raw: object) -> list[str]:
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _report_scan(report: dict[str, object]) -> stress_probe.ReportScan:
    """一局的压力自报扫描：**自带**在报告里，不再靠调用方另传一个键（t89 ②）。

    两条路都走，缺一条都不算"自带"：

    1. **自带块** ``stress_scan``：跑者现在把 ``lines`` 与 ``malformed`` 一起塞进这一个键
       （少了它，形状漂移就只能靠调用方记得补传 —— 换个调用点就静默失效）；
    2. **逐行自核**：手上每一行都按 :func:`pdx.stress_probe.scan_report_lines` 的格式
       再核一遍 —— 形状漂了的行进 ``malformed``。于是就算上游只把行塞进 ``stress_lines``
       （老的键、甚至把漂移行混在里面），判定照样看得见，不会因为"少传一个键"放行（P13）。

    兼容：老的 ``stress_lines`` / ``stress_malformed`` 仍然读；不含前缀的杂项照旧留在
    序列里（由比对去判），**不当**形状漂移。
    """
    block = report.get(STRESS_SCAN_KEY)
    if isinstance(block, dict):
        raw_lines = _as_str_list(block.get("lines"))
        raw_bad = _as_str_list(block.get("malformed"))
    else:
        raw_lines = _report_lines(report)
        raw_bad = _as_str_list(report.get("stress_malformed"))
    lines: list[str] = []
    malformed: list[str] = []
    for item in [*raw_lines, *raw_bad]:
        parsed = stress_probe.scan_report_lines(item)
        if parsed.malformed:
            malformed.append(item)
        elif parsed.lines:
            lines.append(parsed.lines[0])
        else:
            lines.append(item)
    return stress_probe.ReportScan(tuple(lines), tuple(malformed))


@dataclass(frozen=True, slots=True)
class StressControl:
    """两臂受的压到底一不一样 —— "受控 / 非受控"**只有这一条判据**。"""

    ok: bool
    pairs: int
    problems: tuple[str, ...] = ()

    def describe(self) -> str:
        if self.ok:
            return f"✅ 受控：{self.pairs} 对臂的压力自报**逐行相等**"
        return "❌ 受控性不成立：" + "；".join(self.problems)


def stress_control_verdict(reports: Sequence[dict[str, object]]) -> StressControl:
    """把各局折成"同序号的臂对"、逐对比对自报序列 —— **这就是那条断言**。

    判据三条，缺一条都不算受控（P13 不许静默降级）：

    1. 每个序号都有 `vanilla` 那一局（没有基线就无从配对）；
    2. `vanilla` 的序列**非空** —— 两边都空时"相等"是**空的**受控：窗口里根本没有压力落地
       （剧本没挂上、窗口太短、效果没跑起来都会长成这个样子）；
    3. 其余每一臂与 `vanilla` 的序列**逐行相等**（第一处不同由
       :func:`pdx.stress_probe.compare_report_sequences` 给出：第几处 + 哪一波 + 两臂各自那一行）。

    ⚠️ **次数也算判据**（`t63`）：剧本里"行数 = 施加次数"（自报与施加在同一个守卫里，
    见 `pdx.stress_probe.report_emitter`），所以逐行比**本身**就把次数比进去了；
    这里再把 `describe_count_differences` 的逐行计数差印进失败信息 —— 只报"第一处不同"时，
    读的人看不出根因是"同一波同一国多抽了一次"。

    另外：只要日志里有**形状不对**的自报行（分类不认识、字段少一个），也判不成立 ——
    格式漂了的时候，"相等"两个字没有意义。这份扫描结果由**每局报告自带**
    （:func:`_report_scan`：``stress_scan`` 块 + 逐行自核），**不**依赖调用方另传键（t89 ②）。

    只有**一臂**空时（t89 ①）：话术点名是**哪一臂**没跑出来 —— "两臂都没有"只留给
    两臂都空那一种；空的那一臂是原因，不是"剧本没挂上"。
    """
    by_index: dict[int, dict[str, list[str]]] = {}
    malformed: list[str] = []
    for report in reports:
        label = str(report.get("label"))
        index = report.get("index")
        key = index if isinstance(index, int) else 0
        scanned = _report_scan(report)
        by_index.setdefault(key, {})[label] = list(scanned.lines)
        malformed.extend(f"{label}#{key}: {item}" for item in scanned.malformed)
    problems: list[str] = []
    for key in sorted(by_index):
        arms = by_index[key]
        baseline = arms.get(VANILLA_LABEL)
        if baseline is None:
            problems.append(f"#{key}：没有 {VANILLA_LABEL} 那一局 ⇒ 无从配对")
            continue
        if not baseline:
            landed = {
                label: lines
                for label, lines in sorted(arms.items())
                if label != VANILLA_LABEL and lines
            }
            if landed:
                # t89 ①：**只有一臂空**时不许把原因说成"剧本没挂上" —— 空的那一臂才是原因
                detail = "、".join(f"{label} 有 {len(lines)} 行" for label, lines in landed.items())
                problems.append(
                    f"#{key}：{VANILLA_LABEL} 那一局**一条压力自报都没有**（{detail}）"
                    "⇒ 这一臂没跑出来（日志没拿到、窗口没跑满、这一局没起），**不能**称受控；"
                    "另一臂有压力落地 ⇒ 不是剧本没挂上"
                )
            else:
                problems.append(
                    f"#{key}：两臂一条压力自报都没有 ⇒ 窗口内**没有压力落地**，"
                    "「相等」是空的，**不能**称受控（先查剧本挂没挂上、窗口够不够长）"
                )
            continue
        for label in sorted(set(arms) - {VANILLA_LABEL}):
            if not arms[label]:
                problems.append(
                    f"#{key}：{label} 那一局**一条压力自报都没有**"
                    f"（{VANILLA_LABEL} 有 {len(baseline)} 行）⇒ 这一臂没跑出来，"
                    "**不能**称受控（不是「序列不等」，是这一局没有可比的序列）"
                )
                continue
            diff = stress_probe.compare_report_sequences(baseline, arms[label])
            if diff is not None:
                problems.append(
                    f"#{key}：" + diff.describe(left_label=VANILLA_LABEL, right_label=label)
                )
                counts = stress_probe.describe_count_differences(
                    baseline, arms[label], left_label=VANILLA_LABEL, right_label=label
                )
                if counts:
                    problems.append(f"#{key} 施加次数不同：" + "；".join(counts[:4]))
    if malformed:
        problems.append("形状不对的自报行（格式漂了，不能称受控）：" + "；".join(malformed[:5]))
    return StressControl(ok=not problems, pairs=len(by_index), problems=tuple(problems))


@dataclass(frozen=True, slots=True)
class ErrorScan:
    """本次性能臂的 error.log 扫描结果。"""

    readable: bool | None
    files: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    benign: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "readable": self.readable,
            "files": list(self.files),
            "unreadable": list(self.unreadable),
            "errors": list(self.errors),
            "benign": list(self.benign),
        }


def scan_game_errors(directory: Path | None = None) -> ErrorScan:
    """读取本次会话的 error.log 及轮转副本，复用 game_auto 的分类口径。

    readable=None 表示日志尚未生成；有文件但任一文件无法读取时为 False。
    带我们命名空间的真实错误进入 errors，已知无害的 *_goal redundant 行进入 benign，
    两者不混淆。
    """
    base = LOGS if directory is None else directory
    paths = ga.error_logs() if directory is None else ga.rotated_logs(base, "error")
    if not paths:
        return ErrorScan(readable=None)
    files: list[str] = []
    unreadable: list[str] = []
    errors: list[str] = []
    benign: list[str] = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError) as exc:
            unreadable.append(f"{path}: {type(exc).__name__}: {exc}")
            continue
        files.append(str(path))
        errors.extend(ga.our_error_lines(content))
        benign.extend(ga.benign_error_lines(content))
    return ErrorScan(
        readable=not unreadable,
        files=tuple(files),
        unreadable=tuple(unreadable),
        errors=tuple(errors),
        benign=tuple(benign),
    )


@dataclass(frozen=True, slots=True)
class WindowControl:
    """两臂是否实际跑过同一个游戏日历日期窗口。"""

    ok: bool
    pairs: int
    comparisons: tuple[dict[str, object], ...] = ()
    problems: tuple[str, ...] = ()

    def describe(self) -> str:
        if self.ok:
            return f"✅ 窗口可比：{self.pairs} 对臂的起止日历日期相等（忽略日内 tick）"
        return "❌ 窗口不可比：" + "；".join(self.problems)


def _window_date(advanced: object, key: str) -> str | None:
    if not isinstance(advanced, dict):
        return None
    value = advanced.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value.startswith("<"):
        return None
    return value


def _calendar_date(value: str | None) -> str | None:
    """把 ``1836.4.25`` 或 ``1836.4.25.12`` 规范化为日历日期。

    性能臂的采样时刻可能落在同一个游戏日的不同 sub-day tick；窗口门禁
    只承诺同一日历起止日，因此保留原始 tick 供审计，同时用前三段作比较。
    """
    if value is None:
        return None
    parts = value.split(".")
    if len(parts) < 3:
        return None
    try:
        year, month, day = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
    if year < 1 or not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    return f"{year}.{month}.{day}"


def _calendar_key(value: str | None) -> tuple[int, int, int] | None:
    normalized = _calendar_date(value)
    if normalized is None:
        return None
    year, month, day = (int(part) for part in normalized.split("."))
    return year, month, day


def _shift_to_month_start(value: str, months: int) -> str:
    """将游戏日期平移若干月并对齐到月初，供多臂实验预注册共同窗口。"""
    parts = value.split(".")
    if len(parts) < 3:
        raise ValueError(f"无效游戏日期：{value!r}")
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"无效游戏日期：{value!r}") from exc
    if year < 1 or not 1 <= month <= 12:
        raise ValueError(f"无效游戏日期：{value!r}")
    absolute_month = year * 12 + month - 1 + months
    shifted_year, shifted_month0 = divmod(absolute_month, 12)
    return f"{shifted_year}.{shifted_month0 + 1}.1"


def _wait_for_calendar_date(hwnd: int, target: str, *, timeout: float = 180.0) -> str:
    """等到共同窗口的日历边界；错过目标日就失败，避免暗中改变实验窗口。"""
    target_day = _calendar_date(target)
    if target_day is None:
        raise ValueError(f"窗口日期无效：{target!r}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not ga._live_window(hwnd):
            raise ga.GameAutoError("等待共同性能窗口时游戏窗口消失")
        tick = ga.tick_mark().tick
        current_day = _calendar_date(tick)
        if current_day == target_day:
            return tick
        current_key = _calendar_key(current_day)
        target_key = _calendar_key(target_day)
        if current_key is not None and target_key is not None and current_key > target_key:
            raise ga.GameAutoError(
                f"共同性能窗口边界已错过：目标 {target_day}，当前 {current_day}（{tick}）"
            )
        time.sleep(0.05)
    raise ga.GameAutoError(f"等待共同性能窗口边界超时：{target_day}")


def window_control_verdict(
    reports: Sequence[dict[str, object]], *, required_pairs: int | None = None
) -> WindowControl:
    """按实验序号比较 vanilla 与其它每一臂的 advanced.from/to。

    日期缺失、窗口错误标记和日期不一致分别报出；不会把缺失值当成相等，
    也不会重新采集一份日期数据。
    """
    by_index: dict[int, dict[str, object]] = {}
    seen: set[tuple[int, str]] = set()
    shape_problems: list[str] = []
    for report in reports:
        index = report.get("index")
        label = report.get("label")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            shape_problems.append(f"编号无效：{index!r}（必须是正整数）")
            continue
        if not isinstance(label, str) or label not in KNOWN_ARM_LABELS:
            shape_problems.append(f"#{index}：未知性能臂 {label!r}")
            continue
        entry = (index, label)
        if entry in seen:
            shape_problems.append(f"#{index}：性能臂 {label} 重复出现")
            continue
        seen.add(entry)
        by_index.setdefault(index, {})[label] = report.get("advanced")

    comparisons: list[dict[str, object]] = []
    problems: list[str] = [*shape_problems]
    pairs = 0
    pair_counts: dict[str, int] = {}
    for key in sorted(by_index):
        arms = by_index[key]
        baseline = arms.get(VANILLA_LABEL)
        if baseline is None:
            problems.append(f"#{key}：没有 {VANILLA_LABEL} 那一局 ⇒ 无从配对")
            continue
        labels = sorted(label for label in arms if label != VANILLA_LABEL)
        if not labels:
            problems.append(f"#{key}：没有可与 {VANILLA_LABEL} 比较的其它臂")
            continue
        left_from = _window_date(baseline, "from")
        left_to = _window_date(baseline, "to")
        for label in labels:
            right = arms[label]
            right_from = _window_date(right, "from")
            right_to = _window_date(right, "to")
            missing: list[str] = []
            if left_from is None:
                missing.append(f"{VANILLA_LABEL}.from")
            if left_to is None:
                missing.append(f"{VANILLA_LABEL}.to")
            if right_from is None:
                missing.append(f"{label}.from")
            if right_to is None:
                missing.append(f"{label}.to")
            left_from_day = _calendar_date(left_from)
            right_from_day = _calendar_date(right_from)
            left_to_day = _calendar_date(left_to)
            right_to_day = _calendar_date(right_to)
            invalid_dates: list[str] = []
            for date_label, date_value in (
                (f"{VANILLA_LABEL}.from", left_from_day),
                (f"{label}.from", right_from_day),
                (f"{VANILLA_LABEL}.to", left_to_day),
                (f"{label}.to", right_to_day),
            ):
                if date_value is None and date_label not in missing:
                    invalid_dates.append(date_label)
            if invalid_dates:
                missing.extend(f"{name}（格式无效）" for name in invalid_dates)
            comparison: dict[str, object] = {
                "index": key,
                "from": {VANILLA_LABEL: left_from, label: right_from},
                "to": {VANILLA_LABEL: left_to, label: right_to},
                "calendar_from": {VANILLA_LABEL: left_from_day, label: right_from_day},
                "calendar_to": {VANILLA_LABEL: left_to_day, label: right_to_day},
                "comparable": not missing
                and left_from_day == right_from_day
                and left_to_day == right_to_day,
            }
            comparisons.append(comparison)
            if missing:
                problems.append(
                    f"#{key}：{label} 与 {VANILLA_LABEL} 缺少日期：{', '.join(missing)}"
                )
                continue
            pairs += 1
            pair_counts[label] = pair_counts.get(label, 0) + 1
            if left_from_day != right_from_day or left_to_day != right_to_day:
                problems.append(
                    f"#{key}：{label} 与 {VANILLA_LABEL} 窗口不同："
                    f"{VANILLA_LABEL}={left_from}→{left_to}，{label}={right_from}→{right_to}"
                )
    if required_pairs is not None:
        if required_pairs < 1:
            raise ValueError("required_pairs 必须为正整数")
        expected_indices: set[int] = set(range(1, required_pairs + 1))
        required_labels = {
            label for arms in by_index.values() for label in arms if label != VANILLA_LABEL
        }
        if not required_labels:
            problems.append("没有可用于正式配对的非 vanilla 性能臂")
        for label in sorted(required_labels):
            actual = {
                index for index, arms in by_index.items() if VANILLA_LABEL in arms and label in arms
            }
            if actual != expected_indices:
                missing = sorted(expected_indices - actual)  # type: ignore[arg-type]
                extra = sorted(actual - expected_indices)
                detail: list[str] = []
                if missing:
                    detail.append(f"缺少 {missing}")
                if extra:
                    detail.append(f"多出 {extra}")
                problems.append(
                    f"{label} 有效配对编号不符合预注册的 1..{required_pairs}：" + "、".join(detail)
                )
            elif pair_counts.get(label, 0) != required_pairs:
                problems.append(
                    f"{label} 有效配对数为 {pair_counts.get(label, 0)}，"
                    f"预注册要求 {required_pairs} 组"
                )
    return WindowControl(
        ok=not problems and pairs > 0,
        pairs=pairs,
        comparisons=tuple(comparisons),
        problems=tuple(problems),
    )


def _advanced_payload(
    from_tick: str,
    to_tick: str,
    days: object,
    scan: ErrorScan,
    **extra: object,
) -> dict[str, object]:
    result: dict[str, object] = {
        "from": from_tick,
        "to": to_tick,
        "days": days,
        "error_log_readable": scan.readable,
        "error_files": list(scan.files),
        "error_log_unreadable": list(scan.unreadable),
        "error_lines": list(scan.errors),
        "benign_error_lines": list(scan.benign),
    }
    result.update(extra)
    return result


def _resource_sample(started: float) -> dict[str, object]:
    """采集本次性能臂拥有的游戏进程 RSS/CPU 快照。

    只读 ``game_auto`` 已确认归本会话的 PID；进程退出或权限受限时跳过该
    PID，保留快照结构，避免把不可读的资源值伪装成零。
    """
    rss = 0.0
    cpu = 0.0
    readable = 0
    for pid in tuple(ga._OWNED_GAME_PIDS):
        try:
            process = psutil.Process(pid)
            identity = ga._OWNED_GAME_META.get(pid)
            if identity is not None and not ga._owned_identity_matches(process, identity):
                continue
            with process.oneshot():
                rss += process.memory_info().rss / 1024**2
                times = process.cpu_times()
                cpu += times.user + times.system
            readable += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except psutil.Error:
            continue
    return {
        "seconds": round(time.monotonic() - started, 4),
        "rss_mib": round(rss, 4) if readable else None,
        "cpu_seconds": round(cpu, 4) if readable else None,
        "tick": ga.tick_mark().tick,
    }


def _wait_months(
    hwnd: int,
    months: float,
    *,
    timeout: float = 900.0,
    samples: list[dict[str, object]] | None = None,
    started: float | None = None,
    end_date: str | None = None,
) -> dict[str, object]:
    """跑到游戏时间前进 months 个月，并在发现本 mod 报错时提前停止。"""
    start = ga.tick_mark()
    start_day = ga.tick_day(start.tick)
    target = months * MONTH_DAYS
    last = start_day
    latest = scan_game_errors()
    deadline = time.monotonic() + timeout
    last_sample = started if started is not None else time.monotonic()
    last_health_check = time.monotonic()
    if samples is not None and started is not None:
        samples.append(_resource_sample(started))
    while time.monotonic() < deadline:
        now = time.monotonic()
        if samples is not None and started is not None and now - last_sample >= 5.0:
            samples.append(_resource_sample(started))
            last_sample = now
        if now - last_health_check >= 5.0:
            latest = scan_game_errors()
            last_health_check = now
        if latest.errors:
            if samples is not None and started is not None:
                samples.append(_resource_sample(started))
            return _advanced_payload(
                start.tick,
                ga.tick_mark().tick,
                last,
                latest,
                stopped_early=True,
                stop_reason="our_error_log",
            )
        if not ga._live_window(hwnd):
            return _advanced_payload(
                start.tick,
                "<窗口没了或换了>",
                last,
                latest,
                window_gone=True,
            )
        mark = ga.tick_mark()
        day = ga.tick_day(mark.tick)
        reached_target = (
            _calendar_date(mark.tick) == end_date
            if end_date is not None
            else day is not None and start_day is not None and day - start_day >= target
        )
        missed_target = end_date is not None and _calendar_date(mark.tick) not in (None, end_date)
        if end_date is not None and _calendar_date(mark.tick) is not None:
            current_date = _calendar_date(mark.tick)
            current_key = _calendar_key(current_date)
            end_key = _calendar_key(end_date)
            missed_target = (
                current_key is not None and end_key is not None and current_key > end_key
            )
        if reached_target or missed_target:
            elapsed_days = (
                round(day - start_day, 1) if day is not None and start_day is not None else None
            )
            latest = scan_game_errors()
            if samples is not None and started is not None:
                samples.append(_resource_sample(started))
            if latest.errors:
                return _advanced_payload(
                    start.tick,
                    mark.tick,
                    elapsed_days,
                    latest,
                    stopped_early=True,
                    stop_reason="our_error_log",
                )
            return _advanced_payload(
                start.tick,
                mark.tick,
                elapsed_days,
                latest,
                **({"window_boundary_missed": True} if missed_target else {}),
            )
        last = day
        time.sleep(0.1 if end_date is not None else 5.0)
    end = ga.tick_mark()
    if samples is not None and started is not None:
        samples.append(_resource_sample(started))
    latest = scan_game_errors()
    if latest.errors:
        return _advanced_payload(
            start.tick,
            end.tick,
            last,
            latest,
            stopped_early=True,
            stop_reason="our_error_log",
            timeout=True,
        )
    return _advanced_payload(start.tick, end.tick, last, latest, timeout=True)


def dump_ticktask_csv(
    hwnd: int,
    csv_path: Path,
    *,
    max_attempts: int = 3,
    attempt_timeout: float = 8.0,
) -> int:
    """提交 dump 并等待文件落盘；命令可安全重试，避免偶发丢失整组实机样本。"""
    if max_attempts < 1:
        raise ValueError("max_attempts 必须为正整数")
    for attempt in range(1, max_attempts + 1):
        ga.submit_console_command(hwnd, DUMP_COMMAND, force=True)
        deadline = time.monotonic() + attempt_timeout
        while time.monotonic() < deadline:
            if csv_path.is_file() and csv_path.stat().st_size > 0:
                return attempt
            time.sleep(0.25)
    return max_attempts


def run_once(
    label: str,
    months: float,
    *,
    index: int = 1,
    stress: bool = False,
    save_name: str | None = None,
    checkpoint: dict[str, object] | None = None,
) -> dict[str, object]:
    """跑一局并取一份 dump。调用方负责 content_load 与 mod 目录已就位。

    ``stress=True`` 时额外读这一局的**压力自报**（`ZZPROBE STRESS;…`，见上「受控性」一节）
    并写进报告；``False`` 时连日志都不读一趟 —— 默认两臂的输出与从前一字不差。
    """
    ga.assert_no_game_running()
    csv_path = gametimer.ticktask_default_path()
    csv_path.unlink(missing_ok=True)  # 清掉旧的，靠"文件重新出现"判断命令生效
    moved = _quarantine_logs()
    print(f"\n===== {label} #{index}：起游戏（前台，不碰窗口直到进局）=====")
    print(f"  已挪走 {len(moved)} 个旧日志（取证只可能来自这一局）")
    extra_args = (f"-loadsave={save_name}",) if save_name else ()
    hwnd, previous = ga.launch_to_foreground(
        timeout=float(ga.WINDOW_TIMEOUT), extra_args=extra_args
    )
    settle = ga.wait_for_boot_settle(timeout=float(ga.LOBBY_TIMEOUT))
    print(f"  加载等待（不碰窗口）：{settle.why}")
    if save_name and ga.DEBUG_LOG.is_file():
        with ga.DEBUG_LOG.open(encoding="utf-8-sig", errors="replace") as stream:
            if any("Could not load save game" in line for line in stream):
                raise ga.GameAutoError(f"引擎拒绝载入检查点：{save_name}；保留日志并停止启动输入")
    session = ga.start_session(
        hwnd,
        previous,
        settle=settle,
        force=True,
        loaded_observer=save_name is not None,
    )
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
    # 恢复运行不能只靠“再按一次空格”：如果第一次暂停没有被游戏接受，第二次反而
    # 会把已经运行的世界停住。统一复用 game_auto 的 tick 真值判定，先确认是否已经
    # 推进，只有确实暂停时才按键，并且在按键后再次确认 tick。
    resume_note = resume_after_clear(hwnd, speed_xy=session.speed_xy)
    print(f"  清零后恢复运行：{resume_note}")
    # 清零需要前台输入；计时本身必须在后台，且用真实tick核对最小化后仍推进。
    before_background = ga.tick_mark()
    handover = ga.switch_to_background(hwnd, previous)
    if not handover.minimized:
        raise ga.GameAutoError("性能窗口未成功退到后台")
    ga.wait_until_running(before_background, timeout=30)

    window_start = checkpoint.get("window_start") if checkpoint is not None else None
    window_end = checkpoint.get("window_end") if checkpoint is not None else None
    if isinstance(window_start, str) and isinstance(window_end, str):
        aligned_tick = _wait_for_calendar_date(hwnd, window_start)
        print(f"  已对齐共同窗口：{window_start}（原始 tick={aligned_tick}）")

    samples: list[dict[str, object]] = []
    performance_started = time.monotonic()
    advanced = _wait_months(
        hwnd,
        months,
        samples=samples,
        started=performance_started,
        end_date=window_end if isinstance(window_end, str) else None,
    )
    measurement_wall_seconds = time.monotonic() - performance_started
    print(f"  跑完 {months} 个月：{advanced}")

    ga.ensure_foreground(hwnd, force=True)
    dump_attempts = dump_ticktask_csv(hwnd, csv_path)
    dumped = csv_path.is_file() and csv_path.stat().st_size > 0
    print(
        f"  {DUMP_COMMAND}：{'文件已写入' if dumped else '⚠️ 文件未生成'}（提交 {dump_attempts} 次）"
    )
    with suppress(ga.CaptureFailedError):
        ga.save_shot(ga.screenshot(hwnd), f"perf-{label}-after-dump")
    error_scan = scan_game_errors()
    invalid_reasons: list[str] = []
    if bool(advanced.get("stopped_early")):
        invalid_reasons.append(str(advanced.get("stop_reason") or "提前停止"))
    if bool(advanced.get("window_boundary_missed")):
        invalid_reasons.append("错过预注册的共同窗口结束日")
    if error_scan.errors:
        invalid_reasons.append("error.log 命中属于本 mod 的真实错误")
    if error_scan.readable is not True:
        invalid_reasons.append("error.log 不可读或尚未生成")
    if error_scan.errors:
        print(f"  ⚠️ 提前停止：error.log 命中 {len(error_scan.errors)} 行本 mod 错误")
    elif error_scan.readable is not True:
        print("  ⚠️ 性能臂不可判定：error.log 不可读或尚未生成")
    elif error_scan.benign:
        print(f"  已分类无害 error.log 行：{len(error_scan.benign)} 行")
    if not csv_path.is_file():
        raise ga.GameAutoError(
            f"{label}：dump 之后 {csv_path} 没出现 —— 控制台那条命令没生效"
            "（检查 backlog B66 的三条：反引号开、敲得进去、**两次回车**才提交）"
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = arm_csv_path(label, index)
    shutil.copy(csv_path, target)
    parsed = gametimer.parse_ticktask_file(target)
    summary = gametimer.summarize_ticktask(target, parsed=parsed)
    watch_mean = next(
        (stat.mean_ms for stat in gametimer.ticktask_task_stats(parsed) if stat.task == WATCH_TASK),
        None,
    )
    print(f"  {target}（{target.stat().st_size} 字节）")
    for line in gametimer.ticktask_summary_lines(target, summary=summary):
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
        "console": {"clear": cleared, "dump": dumped, "dump_attempts": dump_attempts},
        "session": session.as_dict(),
        "summary": summary,
        "watch_task": {"name": WATCH_TASK, "mean_ms": watch_mean},
        "mounted": mounted,
        "ours_mounted": ours_mounted,
        "error_scan": error_scan.as_dict(),
        "performance_usable": not invalid_reasons,
        "performance_invalid_reasons": invalid_reasons,
        "samples": samples,
        "resource_cpu_basis": "process_lifetime",
        "measurement_wall_seconds": round(measurement_wall_seconds, 4),
        "wall_seconds": round(time.monotonic() - performance_started, 4),
    }
    if checkpoint is not None:
        report["loaded_save"] = checkpoint
    # 压力自报：只在 `--stress` 时读（默认两臂连这一趟 I/O 都不做 ⇒ 输出与从前一字不差）。
    if stress:
        scanned = scan_stress_lines()
        note = f"  压力自报：{len(scanned.lines)} 行"
        if scanned.malformed:
            note += f"｜⚠️ 形状不对 {len(scanned.malformed)} 行（第一条：{scanned.malformed[0]}）"
        print(note)
        report["stress_lines"] = list(scanned.lines)
        report["stress_malformed"] = list(scanned.malformed)
        # 自带块（t89 ②）：判定要的东西跟序列**在同一个键**里，别指望调用方记得补传。
        report[STRESS_SCAN_KEY] = {
            "lines": list(scanned.lines),
            "malformed": list(scanned.malformed),
        }
    # 只终止本次会话启动的进程，不碰用户另开的 Victoria 3。
    ga.kill_owned_game()
    time.sleep(3)
    return report


def resume_after_clear(hwnd: int, *, speed_xy: tuple[int, int] | None) -> str:
    """把清零计时后的游戏恢复到运行态，并返回带判据的说明。

    控制台输入框会吞掉空格；先点击已经由 ``start_session`` 验证过的速度表盘，
    然后交给 ``game_auto._step_unpause`` 读取真实 tick。该函数不会盲目发送第二个
    空格，因此即使清零前的暂停键未被游戏接受，也不会把已经运行的局再次暂停。
    """
    point = speed_xy or ga.speed_widget_xy(hwnd) or ga.SPEED_V_XY
    ga.click_client(hwnd, point[0], point[1], force=True)
    time.sleep(0.8)
    note, _pressed, _advance = ga._step_unpause(
        hwnd,
        key_timeout=30.0,
        run_timeout=30.0,
        force=True,
    )
    return note


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


def _report_task_mean(report: dict[str, object]) -> float | None:
    """新报告复用本次解析；旧报告仍可按既有路径读取。"""
    cached = report.get("watch_task")
    if isinstance(cached, dict) and cached.get("name") == WATCH_TASK:
        value = cached.get("mean_ms")
        if value is None:
            return None
        if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
            return float(value)
    csv = report.get("csv")
    path = Path(str(csv)) if csv else None
    return _task_mean(path, WATCH_TASK) if path is not None and path.is_file() else None


#: 对照表盯的两个量：整帧合计均值，以及"我们直接改的那个任务"的均值。
WATCH_TASK = "RecalculateModifierNodes"


def _delta(
    base: dict[str, float | int | None],
    other: dict[str, float | int | None],
    *,
    from_label: str,
    to_label: str,
) -> dict[str, float | str | None]:
    """两个 label 的均值差（相对差按**基线**算）。

    两臂的 `delta`（ours − vanilla）与第三臂的 `delta_tempo`（tempo − vanilla）同一套算法：
    同一份代码、同一组键，免得两条差用两种口径读。
    """
    delta: dict[str, float | str | None] = {}
    for key in (
        "per_frame_mean",
        "task_mean",
        "rss_peak_mib",
        "rss_start_mib",
        "rss_end_mib",
        "rss_change_mib",
        "cpu_seconds",
        "wall_seconds",
        "game_days",
        "wall_seconds_per_game_day",
    ):
        first, second = base.get(key), other.get(key)
        value: float | None = None if first is None or second is None else round(second - first, 4)
        delta[key] = value
        delta[f"{key}_pct"] = None if not first or value is None else round(100 * value / first, 2)
    delta["from"] = from_label
    delta["to"] = to_label
    return delta


def _sample_metrics(report: dict[str, object]) -> dict[str, float | int | None]:
    """从 ``game_run`` 报告聚合资源、墙钟和游戏日；缺样本保持 ``None``。

    资源监视器读数属于证据而不是计数器：布尔值、无穷值、负值和无法解析的
    数据都不能参与均值或峰值，更不能悄悄当成零。进程累计 CPU 采用窗口首尾差，
    排除载入开销；旧运行器已经从窗口零点累计的读数保留其原口径。
    墙钟优先使用模拟窗口计时，控制台导出和报告解析耗时单独保留。
    """
    samples = report.get("samples")
    rows = samples if isinstance(samples, list) else []
    valid = [row for row in rows if isinstance(row, dict)]

    def finite(value: object, *, nonnegative: bool = True) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number) or (nonnegative and number < 0):
            return None
        return number

    rss = [value for row in valid if (value := finite(row.get("rss_mib"))) is not None]
    cpu = [value for row in valid if (value := finite(row.get("cpu_seconds"))) is not None]
    process_cpu = report.get("resource_cpu_basis") == "process_lifetime"
    cpu_value = max(cpu) if cpu else None
    if process_cpu:
        endpoints = (
            [finite(row.get("cpu_seconds")) for row in (valid[0], valid[-1])] if valid else []
        )
        cpu_value = (
            cpu[-1] - cpu[0]
            if len(cpu) >= 2
            and len(valid) >= 2
            and all(value is not None for value in endpoints)
            and all(first <= second for first, second in pairwise(cpu))
            else None
        )
    wall = report.get("measurement_wall_seconds", report.get("wall_seconds"))
    wall_value = finite(wall)
    advanced = report.get("advanced")
    days = finite(advanced.get("days")) if isinstance(advanced, dict) else None
    per_day = None if wall_value is None or days is None or days <= 0 else wall_value / days
    return {
        "rss_peak_mib": round(max(rss), 4) if rss else None,
        "rss_start_mib": round(rss[0], 4) if rss else None,
        "rss_end_mib": round(rss[-1], 4) if rss else None,
        "rss_change_mib": round(rss[-1] - rss[0], 4) if rss else None,
        "cpu_seconds": round(cpu_value, 4) if cpu_value is not None else None,
        "wall_seconds": round(wall_value, 4) if wall_value is not None else None,
        "game_days": round(days, 4) if days is not None else None,
        "wall_seconds_per_game_day": round(per_day, 4) if per_day is not None else None,
        "resource_samples": sum(
            1
            for row in valid
            if finite(row.get("rss_mib")) is not None and finite(row.get("cpu_seconds")) is not None
        ),
        "rss_samples": len(rss),
        "cpu_samples": len(cpu),
    }


def _count_value(value: object) -> int:
    """把内部采样计数安全地收敛成整数。"""
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def report_table(
    reports: list[dict[str, object]], *, required_pairs: int | None = None
) -> dict[str, object]:
    """把若干局折成一张对照表，过滤明确不可用于性能结论的臂。"""
    table: dict[str, object] = {"runs": reports, "by_label": {}, "invalid_runs": []}
    by_label: dict[str, list[dict[str, object]]] = {}
    invalid_runs: list[dict[str, object]] = []
    for report in reports:
        label = str(report["label"])
        usable_raw = report.get("performance_usable")
        usable = True if usable_raw is None else bool(usable_raw)
        task_mean = _report_task_mean(report) if usable else None
        row = {
            "_index": report.get("index"),
            "per_frame_mean": _per_frame_mean(report.get("summary")),
            "task_mean": task_mean,
            **_sample_metrics(report),
        }
        if not usable:
            invalid_runs.append(
                {
                    "label": label,
                    "index": report.get("index"),
                    "reasons": (
                        list(cast("list[object]", report["performance_invalid_reasons"]))
                        if isinstance(report.get("performance_invalid_reasons"), list)
                        else ["性能臂被标记为不可用"]
                    ),
                }
            )
            continue
        by_label.setdefault(label, []).append(row)
    aggregate: dict[str, dict[str, float | int | None]] = {}
    for label, rows in by_label.items():
        for key in (
            "per_frame_mean",
            "task_mean",
            "rss_peak_mib",
            "rss_start_mib",
            "rss_end_mib",
            "rss_change_mib",
            "cpu_seconds",
            "wall_seconds",
            "game_days",
            "wall_seconds_per_game_day",
        ):
            values = [
                float(value)
                for row in rows
                if (value := row.get(key)) is not None
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ]
            aggregate.setdefault(label, {})[key] = (
                round(sum(values) / len(values), 4) if values else None
            )
        aggregate[label]["resource_samples"] = sum(
            _count_value(row.get("resource_samples")) for row in rows
        )
        aggregate[label]["rss_samples"] = sum(_count_value(row.get("rss_samples")) for row in rows)
        aggregate[label]["cpu_samples"] = sum(_count_value(row.get("cpu_samples")) for row in rows)
        aggregate[label]["runs"] = len(rows)
    table["by_label"] = aggregate
    table["invalid_runs"] = invalid_runs

    # 这里只检查采集结构和样本数量；M4 的后期、冻结行为候选与预注册预算
    # 另行验收，不能把 m4_gate.ok 误读为完整 M4 或发布通过。
    gate_reasons: list[str] = []
    if required_pairs is not None:
        if required_pairs < 1:
            raise ValueError("required_pairs 必须为正整数")
        usable_reports = [
            report for report in reports if report.get("performance_usable") is not False
        ]
        labels = {str(report.get("label")) for report in usable_reports}
        if VANILLA_LABEL not in labels or OURS_LABEL not in labels:
            gate_reasons.append(f"缺少正式配对所需的 {VANILLA_LABEL}/{OURS_LABEL} 臂")
        baseline_indices = {
            index
            for report in usable_reports
            if str(report.get("label")) == VANILLA_LABEL
            and isinstance((index := report.get("index")), int)
            and not isinstance(index, bool)
        }
        for label in sorted(labels):
            if label not in KNOWN_ARM_LABELS:
                gate_reasons.append(f"出现未知性能臂：{label}")
                continue
            arm = [report for report in usable_reports if str(report.get("label")) == label]
            indices = [report.get("index") for report in arm]
            if any(isinstance(index, bool) or not isinstance(index, int) for index in indices):
                gate_reasons.append(f"{label} 存在非整数实验编号")
            integer_indices = [
                index for index in indices if isinstance(index, int) and not isinstance(index, bool)
            ]
            if len(integer_indices) != len(set(integer_indices)):
                gate_reasons.append(f"{label} 存在重复实验编号")
            actual = set(integer_indices)
            expected_indices = set(range(1, required_pairs + 1))
            if actual != expected_indices:
                gate_reasons.append(
                    f"{label} 实验编号应为 1..{required_pairs}，实际为 {sorted(actual)}"
                )
            if label != VANILLA_LABEL and actual != baseline_indices:
                gate_reasons.append(
                    f"{label} 与 {VANILLA_LABEL} 的实验编号不成对："
                    f"{sorted(actual)} 对 {sorted(baseline_indices)}"
                )
            for report in arm:
                row = next(
                    (
                        item
                        for item in by_label.get(label, [])
                        if item.get("_index") == report.get("index")
                    ),
                    {},
                )
                if not row:
                    continue
                missing = [
                    key
                    for key in (
                        "per_frame_mean",
                        "task_mean",
                        "rss_peak_mib",
                        "rss_start_mib",
                        "rss_end_mib",
                        "rss_change_mib",
                        "cpu_seconds",
                        "wall_seconds",
                        "game_days",
                        "wall_seconds_per_game_day",
                    )
                    if row.get(key) is None
                ]
                if not row.get("rss_samples") or not row.get("cpu_samples"):
                    missing.append("samples.rss_mib/cpu_seconds")
                if missing:
                    gate_reasons.append(
                        f"{label} #{report.get('index')} 缺少指标：{', '.join(missing)}"
                    )
        if invalid_runs:
            gate_reasons.append("存在被标记为不可用的性能臂")
    table["m4_gate"] = {
        "required_pairs": required_pairs,
        "ok": required_pairs is None or not gate_reasons,
        "reasons": gate_reasons,
    }
    gate = cast("dict[str, object]", table["m4_gate"])
    gate_ok = bool(gate["ok"])
    if (
        gate_ok
        and VANILLA_LABEL in aggregate
        and OURS_LABEL in aggregate
        and aggregate[VANILLA_LABEL].get("runs", 0)
        and aggregate[OURS_LABEL].get("runs", 0)
        and (required_pairs is None or aggregate[VANILLA_LABEL]["runs"] == required_pairs)
        and (required_pairs is None or aggregate[OURS_LABEL]["runs"] == required_pairs)
    ):
        table["delta"] = _delta(
            aggregate[VANILLA_LABEL],
            aggregate[OURS_LABEL],
            from_label=VANILLA_LABEL,
            to_label=OURS_LABEL,
        )
    if (
        gate_ok
        and VANILLA_LABEL in aggregate
        and TEMPO_LABEL in aggregate
        and aggregate[VANILLA_LABEL].get("runs", 0)
        and aggregate[TEMPO_LABEL].get("runs", 0)
        and (required_pairs is None or aggregate[TEMPO_LABEL]["runs"] == required_pairs)
    ):
        table["delta_tempo"] = _delta(
            aggregate[VANILLA_LABEL],
            aggregate[TEMPO_LABEL],
            from_label=VANILLA_LABEL,
            to_label=TEMPO_LABEL,
        )
    return table


def tempo_defines_sources(mod_root: Path | None = None) -> list[Path]:
    """仓库产物里那份 **tempo defines**（`mod/common/defines/*_tempo.txt`，来自 `[tempo]` 表）。

    为什么从**产物**取、不现造：`[tempo]` 是 mod 级表，产物名由 `modgen` 按"声明它的那份档案"
    命名（`modgen.py:496-500`）⇒ 探针再拼一次名字，就多出一处"改了档案还得顺手改探针"，
    而 G-EXIT-1 的判据正是"加一行数据 = 不改 Python"（P9）。产物由闸门 ⑤ 与数据源对齐。
    """
    return sorted(
        ((mod_root or (config.REPO / "mod/legacy")) / "common" / "defines").glob(TEMPO_DEFINES_GLOB)
    )


def tempo_metadata_text(mod_root: Path | None = None) -> str:
    """壳 mod 的 `.metadata/metadata.json`（id 用 `sitai.` 前缀，理由见 :data:`TEMPO_MOD_NAME`）。

    ``supported_game_version`` 走 `stress_probe.mod_game_version()` —— **与压力剧本探针同源**
    （`t63` 把那一份从"写死 1.14.3"改成现读，两处就不再各读一遍产物了）。
    """
    return (
        "{\n"
        '  "name": "SITAI 第三臂壳 mod（B27：只挂 tempo defines）",\n'
        f'  "id": "sitai.perf.{TEMPO_MOD_NAME}",\n'
        '  "version": "0.1.0",\n'
        f'  "supported_game_version": "{stress_probe.mod_game_version(mod_root)}",\n'
        '  "short_description": "性能对照第三臂：只有一份 defines 覆盖（节奏杠杆），'
        '不带任何档案产物。由 tools/probe/perf_compare.py --tempo-arm 装，跑完删除。",\n'
        '  "tags": [],\n'
        '  "relationships": [],\n'
        '  "game_custom_data": { "multiplayer_synchronized": false }\n'
        "}\n"
    )


def write_tempo_shell(target: Path | None = None, *, mod_root: Path | None = None) -> list[Path]:
    """把第三臂的**壳 mod** 写到 ``target``（默认 :data:`TEMPO_DST`），返回写出的文件。

    仓库产物保持 UTF-8 无 BOM；写入游戏 mod 目录时只在部署边界为脚本添加恰好一个
    UTF-8 BOM，并统一为 LF。正文仍来自 `v3 modgen` 产物，探针不手写或改写脚本结构。
    产物一份都没有时**报错**（不许装一个空的壳 mod 上去，那会让第三臂变成"原版 + 空气"，
    而读数看起来完全正常）。
    """
    sources = tempo_defines_sources(mod_root)
    if not sources:
        raise RuntimeError(
            f"仓库产物里没有 tempo defines（mod/common/defines/{TEMPO_DEFINES_GLOB}）—— "
            "先跑 `.venv\\Scripts\\v3.exe modgen`；第三臂只挂这一份文件，没有它就没有第三臂"
        )
    base = TEMPO_DST if target is None else target
    written: list[Path] = []
    meta = base / ".metadata" / "metadata.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_bytes(text_bytes(tempo_metadata_text(mod_root)))
    written.append(meta)
    for source in sources:
        copy = base / "common" / "defines" / source.name
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(text_bytes(source.read_bytes().decode("utf-8-sig"), game=True))
        written.append(copy)
    return written


def deploy_stress_probe(destination: Path = STRESS_DST) -> list[Path]:
    """生成压力剧本源码，并在游戏部署边界转换为 BOM/LF 文件。

    `pdx.stress_probe.write` 的仓库产物必须保持无 BOM；直接写到用户 mod 目录会被
    Victoria 3 拒载。因此先写入短生命周期的源码目录，再复用唯一的 `deploy_tree`
    边界部署函数。临时目录在返回前删除，游戏目录只留下可运行的安装副本。
    """
    with tempfile.TemporaryDirectory(prefix="sitai-stress-source-") as temp:
        source = Path(temp)
        stress_probe.write(source)
        return deploy_tree(source, destination)


def _assert_no_symlink(path: Path, *, label: str) -> None:
    """拒绝检查点源/目标路径链上的符号链接，避免隔离边界被绕过。"""
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError(f"{label}不允许符号链接：{item}")


def preserve_checkpoint_source(source: Path) -> tuple[Path, Path]:
    """在隔离用户存档目录前复制检查点源，返回临时副本和原始绝对路径。"""
    original = source.expanduser().resolve()
    _assert_no_symlink(source.expanduser(), label="固定检查点源")
    if not original.is_file():
        raise FileNotFoundError(f"固定检查点不存在：{original}")
    holding = Path(tempfile.mkdtemp(prefix="sitai-checkpoint-source-"))
    copy = holding / original.name
    shutil.copyfile(original, copy)
    return copy, original


def stage_checkpoint(
    source: Path,
    destination: Path,
    *,
    source_label: Path | None = None,
) -> tuple[str, dict[str, object]]:
    """校验并复制固定观察者检查点，返回游戏启动所需的存档名与证据字段。

    源文件可以位于用户 ``save games`` 目录中；调用方必须在隔离该目录前调用本函数
    或先保留源字节。复制后的文件只存在于本次探针的临时用户存档目录，收尾由
    :class:`PerfCleanup` 删除，不修改源存档。
    """
    source = source.expanduser().resolve()
    _assert_no_symlink(source, label="固定检查点源")
    _assert_no_symlink(destination, label="固定检查点目标")
    if not source.is_file():
        raise FileNotFoundError(f"固定检查点不存在：{source}")
    source_before = source.stat()
    header = save_header(source)
    expected_version = config.game_version().get("caligula_branch", "").split("/")[-1]
    validate_load_save_header(
        header,
        expected_version=expected_version,
        allow_save_upgrade=False,
    )
    destination.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".sitai-checkpoint-", dir=str(destination))
    os.close(fd)
    temporary = Path(temp_name)
    try:
        hasher = hashlib.sha256()
        with source.open("rb") as reader, temporary.open("wb") as writer:
            while chunk := reader.read(1024 * 1024):
                hasher.update(chunk)
                writer.write(chunk)
        source_after = source.stat()
        if any(
            getattr(source_before, attr) != getattr(source_after, attr)
            for attr in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        ):
            raise OSError("固定检查点复制期间发生变化，拒绝发布")
        digest = hasher.hexdigest()
        staged = destination / f"sitai_checkpoint_{digest[:16]}.v3"
        _assert_no_symlink(staged, label="固定检查点目标")
        temporary.replace(staged)
    finally:
        temporary.unlink(missing_ok=True)
    with staged.open("rb") as reader:
        copied_digest = hashlib.file_digest(reader, "sha256").hexdigest()
    if copied_digest != digest:
        raise OSError(f"固定检查点复制后校验失败：{staged}")
    return staged.stem, {
        "source": str(source_label or source),
        "name": staged.name,
        "sha256": digest,
        "header": header,
    }


def build_parser() -> argparse.ArgumentParser:
    """命令行 —— 单列出来是为了让用例**不跑游戏**也能钉住 flag 名与默认值。"""
    parser = argparse.ArgumentParser(
        description="G-EXIT-3 性能对照（默认两臂；可选压力剧本 / 第三臂）"
    )
    parser.add_argument("months", nargs="?", type=float, default=12.0, help="每局跑几个月")
    parser.add_argument(
        "--repeat",
        type=int,
        default=REQUIRED_M4_PAIRS,
        help=f"每个配置跑几局（正式 M4 要求 {REQUIRED_M4_PAIRS} 组；少于此数只作探索性读数）",
    )
    parser.add_argument(
        "--stress",
        action="store_true",
        help="开**标准压力剧本**（大战 + 连锁破产 + 革命潮）：两臂都装那一份探针，"
        "于是世界被推到同一个高压状态，差只剩我们的 mod —— 0.5 ms 要靠它才分辨得出来；"
        "并且两臂的压力自报必须**逐行相等**（不等即出声失败），这才是「受控」",
    )
    parser.add_argument(
        "--tempo-arm",
        action="store_true",
        help="多跑一条臂 `tempo` = 原版 + 剧本 + **只挂 tempo defines 的壳 mod**（不带档案产物）—— "
        "B27 的测法：Δ_tempo = M_tempo − M_vanilla，盯 UpdateAI，把「节奏杠杆的开销」从 ours 臂里"
        "分离出来（口径见 docs/design/exec/阶段4-压力剧本-口径.md §6）。默认关闭 ⇒ 两臂的行为与产物"
        "与从前一字不差；打开后 CSV 落 tools/out/perf/tempo-<序号>.csv，壳 mod 落 "
        f"<用户 mod 目录>/{TEMPO_MOD_NAME}（跑完删除）。本卡只提供能力，实跑由 t22 定",
    )
    parser.add_argument(
        "--load-save",
        type=Path,
        help="从固定观察者检查点启动每一臂；源存档只读复制并在收尾删除临时副本",
    )
    return parser


def _main() -> int:
    enable_utf8_stdio()
    # 探针是**显式入口**：按设计打开真实输入授权（`pdx.game_auto` 的闸门说的就是这件事）。
    ga.ALLOW_REAL_INPUT = True
    args = build_parser().parse_args()
    months = args.months
    if not CONTENT_LOAD.is_file():
        print(f"找不到 {CONTENT_LOAD}")
        return 2
    backup = _make_backup(CONTENT_LOAD)
    try:
        original = json.loads(CONTENT_LOAD.read_text(encoding="utf-8"))
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    cleanup = PerfCleanup(
        content_path=CONTENT_LOAD,
        backup_path=backup,
        # 菜单启动时会扫描整个存档目录；旧实验存档里的停用变量会在尚未进入
        # 本局前就写入 error.log。把它和日志、临时 Mod 一起隔离，结束时按原路径
        # 恢复，既不改变用户存档字节，也不把历史错误误归因到性能臂。
        generated_paths=(
            OURS_DST,
            STRESS_DST,
            TEMPO_DST,
            SAVE_DIR,
            RULE_PRESETS,
            gametimer.ticktask_default_path(),
        ),
        killer=ga.kill_owned_game,
    )
    restore_signals = _install_cleanup_handlers(cleanup)
    print(f"content_load.json 已备份到 {backup.name}（收尾会还原）")

    reports: list[dict[str, object]] = []
    cleanup_errors: tuple[str, ...] = ()
    checkpoint_source: Path | None = None
    checkpoint_original: Path | None = None
    checkpoint_holding: Path | None = None
    try:
        if args.load_save is not None:
            checkpoint_source, checkpoint_original = preserve_checkpoint_source(args.load_save)
            checkpoint_holding = checkpoint_source.parent
        cleanup.claim_existing_paths()
        checkpoint_name: str | None = None
        checkpoint: dict[str, object] | None = None
        if args.load_save is not None:
            assert checkpoint_source is not None
            assert checkpoint_original is not None
            checkpoint_name, checkpoint = stage_checkpoint(
                checkpoint_source,
                SAVE_DIR,
                source_label=checkpoint_original,
            )
            header = checkpoint.get("header")
            game_date = header.get("game_date") if isinstance(header, dict) else None
            if not isinstance(game_date, str):
                raise ga.GameAutoError("固定检查点报告缺少有效 game_date，无法预注册共同窗口")
            if not float(months).is_integer():
                raise ga.GameAutoError("固定检查点的共同性能窗口要求 months 为整数")
            window_start = _shift_to_month_start(game_date, 4)
            window_end = _shift_to_month_start(window_start, int(months))
            checkpoint["window_start"] = window_start
            checkpoint["window_end"] = window_end
            print(
                f"已载入固定观察者检查点：{checkpoint['name']}（sha256={str(checkpoint['sha256'])[:16]}…）；"
                f"预注册共同窗口 {window_start}→{window_end}"
            )
        deploy_tree(config.REPO / "mod", OURS_DST)
        print(f"已装本地 mod：{OURS_DST.name}（复制自 {config.REPO / 'mod'}）")

        # 压力剧本：**两臂都装**。单装一臂的话，"世界被推到高压"这件事本身会被算进
        # 那一臂的差里，对照立刻作废 —— 它必须是一个两臂共有的**场景**，不是一种处理。
        stress_mods: list[Path] = []
        if args.stress:
            deploy_stress_probe(STRESS_DST)
            stress_mods = [STRESS_DST]
            print(
                f"已开压力剧本：{STRESS_DST.name}"
                f"（大战 {len(stress_probe.WAR_PAIRS)} 场 @ {stress_probe.WAR_DATE}；"
                f"抽干 {len(stress_probe.BREAK_TAGS)} 国库 @ {stress_probe.BREAK_DATE}；"
                f"激进派 {len(stress_probe.RADICAL_DATES)} 波）"
            )

        # 第三臂（B27）：**只挂那一份 tempo defines**，不带档案产物。
        if args.tempo_arm:
            shell = write_tempo_shell(TEMPO_DST)
            print(
                f"已装第三臂壳 mod：{TEMPO_DST.name}"
                f"（{len(shell)} 个文件：{'、'.join(path.name for path in shell)}）"
            )

        # **交替跑**（vanilla, ours[, tempo], vanilla, …）：同一时段的机器状态（温升、后台负载）
        # 被各个配置平摊，比"先把原版跑完再跑我们"更能压住系统性偏差。
        arms = arm_labels(args.tempo_arm)
        for index in range(1, max(1, args.repeat) + 1):
            for label in arms:
                _set_local_mods(arm_mods(label, stress_mods), original=original)
                reports.append(
                    run_once(
                        label,
                        months,
                        index=index,
                        stress=args.stress,
                        save_name=checkpoint_name,
                        checkpoint=checkpoint,
                    )
                )
    finally:
        cleanup_errors = cleanup.run(reason="normal" if sys.exc_info()[0] is None else "exception")
        if checkpoint_holding is not None:
            shutil.rmtree(checkpoint_holding, ignore_errors=True)
        restore_signals()
        print(
            f"\n[收尾] 本次游戏已终止；content_load.json 已还原；"
            f"本地 mod 已恢复/删除；收尾错误={list(cleanup_errors) or '无'}"
        )

    table = report_table(reports, required_pairs=REQUIRED_M4_PAIRS)
    banner = (
        "===== G-EXIT-3 对照（`--stress`：受控与否由文末的压力自报比对判定）====="
        if args.stress
        else "===== G-EXIT-3 对照（非受控：两局不是同一个世界，只读量级与方向）====="
    )
    print("\n" + banner)
    for report in reports:
        print(f"\n--- {report['label']} #{report.get('index')} ---")
        print(f"  月数 {report['months']}｜{report['advanced']}")
        summary = report["summary"]
        if isinstance(summary, dict):
            task_mean = _report_task_mean(report)
            print(
                f"  帧 {summary.get('frames')}｜每帧合计均值 {_per_frame_mean(summary)} ms"
                f"｜{WATCH_TASK} 均值 {task_mean} ms"
            )
        print(f"  我们的 mod 挂上了吗：{report.get('ours_mounted')}")
        if report.get("performance_usable") is False:
            reasons = report.get("performance_invalid_reasons", [])
            if not isinstance(reasons, list):
                reasons = ["性能臂被标记为不可用"]
            print("  ⚠️ 该性能臂不可用于结论：" + "；".join(str(item) for item in reasons))
    print("\n--- 汇总 ---")
    by_label = cast("dict[str, object]", table["by_label"])
    for label, row in by_label.items():
        print(f"  {label}：{row}")
    if "delta" in table:
        print(f"  差（{table['delta']}）")
    if "delta_tempo" in table:
        print(f"  第三臂差（{table['delta_tempo']}）")

    invalid_runs = table.get("invalid_runs", [])
    if not isinstance(invalid_runs, list):
        invalid_runs = []
    if invalid_runs:
        print(f"\n===== 性能结论门禁：{len(invalid_runs)} 个臂不可用 =====")
        for item in invalid_runs:
            print(f"  {item}")

    m4_gate = table.get("m4_gate", {})
    if isinstance(m4_gate, dict) and not m4_gate.get("ok", False):
        print("\n===== M4 性能证据门禁：失败 =====")
        for reason in m4_gate.get("reasons", []):
            print(f"  {reason}")

    # 窗口日期判据：同一序号的每个非 vanilla 臂都必须与 vanilla 共享同一日历起止日；
    # 原始 sub-day tick 仍完整保留在 comparisons 中供审计。
    window = window_control_verdict(reports, required_pairs=REQUIRED_M4_PAIRS)
    table["window_control"] = {
        "ok": window.ok,
        "pairs": window.pairs,
        "problems": list(window.problems),
        "comparisons": list(window.comparisons),
    }

    # 受控性：**跑完才判**，判据与每局的原始序列一起落盘（可复核，不靠终端里的字）。
    control: StressControl | None = None
    if args.stress:
        control = stress_control_verdict(reports)
        table["stress"] = {
            "ok": control.ok,
            "pairs": control.pairs,
            "problems": list(control.problems),
            "sequences": {
                f"{report['label']}#{report.get('index')}": _report_lines(report)
                for report in reports
            },
        }
    out = OUT_DIR / "compare.json"
    out.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n证据：{out}")
    print("\n===== 窗口可比性 =====")
    print("  " + window.describe())
    if control is not None:
        print("\n===== 受控性（压力自报比对）=====")
        for report in reports:
            label = str(report.get("label"))
            current_index = report.get("index")
            print(f"  {label} #{current_index}：{len(_report_lines(report))} 行自报")
        print("  " + control.describe())
        if not control.ok:
            print("  ⇒ **这一轮不能报「受控」**：先修上面那几条，或按「非受控」写结论（P13）")
            return 1
    if cleanup_errors:
        print("\n===== 收尾门禁：失败 =====")
        for error in cleanup_errors:
            print(f"  {error}")
        return 1
    m4_gate_dict = m4_gate if isinstance(m4_gate, dict) else {}
    if invalid_runs or not window.ok or not bool(m4_gate_dict.get("ok", False)):
        return 1
    return 0


def main() -> int:
    """在整个性能对照生命周期内持有跨进程锁。"""
    with RunLock(RUN_LOCK):
        return _main()


if __name__ == "__main__":
    raise SystemExit(main())
