"""并行测试内存基线：一条命令量出「整套峰值 / 每 worker 峰值 / 总耗时」。

为什么需要先钉口径
==================

`pyproject.toml` 的 addopts 默认 `-n auto --dist loadscope`；本机 16 个逻辑核就是
**16 个 worker**，而 xdist 的 worker 之间不共享内存缓存，每个 worker 都要自己把
需要的那部分语料装一遍。所以「并行测试的内存占用」不是某次运行的偶然现象，而是
**乘上并行度的常数** —— 谈优化之前，先把「量什么、怎么量、上限多少」写死。

三个读数的定义（本脚本输出的字段名就是这三个）
----------------------------------------------

* ``peak_total_mb`` —— **整套峰值**：以被测命令进程为根的那棵**进程树**，在任一采样
  时刻的 RSS 之和，取所有采样的最大值。口径含义是「这台机器必须同时拿得出多少
  物理内存」。采样间隔 250 ms（``--interval-ms``），因此它是**下界**（可能漏掉
  两次采样之间的尖峰）；同时报一个漏不掉的**上界** ``sum_hwm_mb``（每个进程的
  OS 高水位之和，worker 不会同时站在各自最高点，所以它是上界而不是实际占用）。
  两个数接近 = 采样可信；差得远 = 峰值是错峰的，整套峰值不能拿「每 worker 峰值 ×
  worker 数」去推。
* ``per_worker_peak_mb`` —— **每 worker 峰值**：每个 worker 进程自己活到那一刻的
  OS 高水位（Windows ``PeakWorkingSetSize`` / Linux ``VmHWM``）。这是**与采样无关
  的精确值**，也是唯一适合跨机器、跨并行度比较的那个数（整套峰值随并行度变，它不变）。
* ``wall_s`` —— **总耗时**：被测命令的墙钟时间。

与上一轮探针的关系（两处口径更正）
==================================

`tools/out/mem/` 下留着上一轮的探针（``measure.ps1`` / ``probe_steps.py`` /
``memplug.py``）。本脚本沿用它的关键结论、更正它的两处口径：

1. 旧采样器数的是**机器上所有 python 进程**（``Get-Process -Name python``），于是
   把无关进程也算进了「整套峰值」—— ``probe-chain.peak.json`` 的 ``5057.6 MB`` /
   ``nproc=4`` 里混着别的 python 进程。本脚本只数**被测命令的子树**：同名数字在
   旧口径下不可复算，所以那条数只能当线索、不能当基线。
2. 旧读数里的 ``commit`` 是**提交量（虚拟）**，不是常驻内存 —— ``probe_imports.jsonl``
   里 ``import:numpy → commit +488.66 MB`` 同一行的 ``ws`` 只有 ``48.98 MB``。
   本脚本把 ``rss``（常驻）当主口径，``private``（私有提交 / 匿名页）另列一栏，
   **不合并、不换算**。

跨平台
======

* Windows：``kernel32!K32GetProcessMemoryInfo`` 读 RSS / 高水位，
  ``CreateToolhelp32Snapshot`` 枚举父子关系；
* Linux：``/proc/<pid>/status``（``VmRSS`` / ``VmHWM``）+ ``/proc/<pid>/stat``（ppid）；
* macOS 与其它 POSIX：``ps -axo pid=,ppid=,rss=``。该平台**只有当前 RSS、没有高水位**，
  于是每 worker 峰值退化成「存活期间的最大采样值」，输出里用 ``peak_source``
  标注是 ``hwm`` 还是 ``sampled``，混用两种来源的数之前先看这个字段。

只用标准库；``--inproc`` 路径需要 dev 依赖 pytest（仓库 `[project.optional-dependencies] dev`）。

工具自身的三条硬伤（都已修，2026-09-25；逐条登记在 `docs/design/backlog.md` 附⑤）
======================================================================

* **B107 单组跑会把冻结索引截断**：`--index` 原来默认就是 `baseline.json`，而 `run` 会把索引
  **整体重写**成这次跑的组 ⇒ 跑一组就只剩一组（t13 实测 42,568 B → 20,508 B），**而且不报错**；
  之后任何「优化前 vs 优化后」的对照都拿被截断的基线当基准。现在：
  **单组默认写 `<产物前缀>.json`**，多组才写 `baseline.json`；并且要覆盖一个
  「里面还有这次不跑的组」的索引时**拒绝**（exit 2，除非 `--force`）。
* **B108 同一 tag 的第二条臂覆盖第一条臂的明细**：四份产物原来只按 tag 命名 ⇒ 两组共用一个
  tag 时，第一条臂的 per-pid 表与 `avail_mb` 序列**被直接覆盖**、事后补不回来（t13 实测）。
  现在前缀 = :func:`artifact_stem`（`<tag>`；tag 与组名不同时 `<tag>-<group>`），
  summary 里带 `group` / `groups_seen` / `artifacts` ⇒ **一个 tag 跑过哪些臂读得出来**。
* **B109 GBK 控制台下崩**：`✅`/`❌`/`⚠️`/`↳` 都不在 cp936 里，`print` 抛 `UnicodeEncodeError`
  ⇒ **同一条命令在 Windows 默认控制台判红、在 UTF-8 环境判绿**（t14 实测的跨平台硬伤）。
  现在按 stdout 编码选标记（装不下就退 `[OK]`/`[NG]`/`[!]`/`->`），并把 stdout/stderr 的
  编码错误策略设成 `replace`（回显别人的输出也不会崩）。

用法
====

    # ① 合约要求的必测三组：-n 4 / 同样但 V3_PARSE_CACHE=0 / -n 1 串行
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py run

    # ② 附加：默认并行度（-n auto）与固定随机种子的可复算组
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py run --groups auto,n4-seed1

    # ③ 逐 worker 归因（在 worker 进程内记每模块峰值；`rank` 汇总排名）
    #    同一个 tag 跑第二条臂：产物前缀自动带上组名（如 `n4-inproc-n4-nocache.summary.json`）
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py run --groups n4 --inproc --tag n4-inproc
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py run --groups n4-nocache --inproc --tag n4-inproc
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py rank --tag n4-inproc

    # ④ 组件单点复算（把「一个 worker 的内存」拆到每一步 → 前三名组件的证据）
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py one shards_touch
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py one ga
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py one parse_all --evict-every 200

    # ⑤ 判预算（退出码 0 = 达标，1 = 不达标，2 = 缺产物）
    .venv\\Scripts\\python.exe tools/probe/mem_baseline.py check --index baseline.json

产物（全在 ``tools/out/mem/``，该目录整棵被 .gitignore 忽略）
============================================================

    <前缀>.json            单组索引（`run --groups X` 默认落这里；前缀 = 该组）
    baseline.json          多组索引（`run` 不给 --groups 时；文件里写明 `covers_groups`）
    <前缀>.summary.json    单组完整读数（每进程峰值表 + `group` + `groups_seen` + `artifacts`）
    <前缀>.samples.csv     时间线：t_s,nproc,total_rss_mb,total_private_mb,avail_mb
    <前缀>.procs.csv       每进程：pid,name,role,level,rss_max_mb,hwm_mb,peak_source
    <前缀>.log             被测命令的完整输出（失败用例名不许丢）
    steps.jsonl            `one` 模式的逐步读数（追加）
    rank.json              `rank` 模式的分模块排名
    inproc-<前缀>-*.json   `--inproc` 时每个 pytest 进程的原始读数
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import gc
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "tools" / "out" / "mem"
TESTS = "tools/tests"

#: 采样间隔。250 ms × 8 分钟 ≈ 1900 条，采样线程本身的代价可忽略；
#: 之所以不更密：遍历一次进程表 + 逐进程读计数器在 Windows 上是毫秒级的
#: 系统调用，采样越密与被测进程抢 CPU 越多，而 250 ms 已经足够盖住
#: 「重夹具建立」那种持续数秒的峰值平台。
INTERVAL_MS = 250

#: 「launcher 中转」的判据（MiB）：本机 ``.venv\Scripts\python.exe`` 只是个转发壳，
#: 自己常年 4 MB；而真正的解释器一 import pytest 就 > 20 MB。用高水位把两者分开，
#: 比按「第几层子进程」可靠 —— xdist 起 worker 时**也**经由这个壳（实测）。
#: 定成 24 而不是 8：留出调试器/杀软注入等额外占用的余量，宁可漏判 launcher
#: （漏判只会让某个 worker 被叫 helper）也不要误判真身。
LAUNCHER_MAX_MB = 24.0

#: worker 的存活下限：**相对真身**存活时长的比例。两者几乎同寿命（≥90%），
#: 而测试自己起的子进程只占几个百分点；取 30% 留足余量。
ALIVE_RATIO = 0.3

#: 预算：每 worker 峰值上限（MiB）。定义与 why 见 docs/design/exec/并行测试内存基线.md §4。
BUDGET_PER_WORKER_MB = 512.0

#: 预算：固定的车头开销（MiB）—— controller 收集全部用例 + 采集输出 + 结果汇总。
#: 整套峰值上限写成 ``BUDGET_HEAD_MB + n × BUDGET_PER_WORKER_MB``：
#: 上限必须随并行度走，否则同一个绝对数会既误判 ``-n auto`` 又管不住单 worker。
BUDGET_HEAD_MB = 1024.0

_IS_WIN = sys.platform == "win32"
_IS_LINUX = sys.platform.startswith("linux")


def _mb(n: float) -> float:
    return round(n / 1048576.0, 1)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ────────────────────────────── 读内存 ──────────────────────────────
#
# 统一口径：``read(pid) -> (rss_bytes, peak_bytes, private_bytes)``。
# ``peak`` 是 OS 维护的高水位（不需要采样就能拿到），拿不到时退化成 None。

if _IS_WIN:  # pragma: no cover - 平台分支
    import ctypes.wintypes as _wt

    # 结构体字段名保持 Win32 原名（PROCESS_MEMORY_COUNTERS 等），类名按本仓
    # 的 CapWords 约定（ruff N801）：字段名要能对着 MSDN 读，类名只是本地壳子。
    class _MemCounters(ctypes.Structure):
        _fields_ = [
            ("cb", _wt.DWORD),
            ("PageFaultCount", _wt.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    class _ProcEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", _wt.DWORD),
            ("cntUsage", _wt.DWORD),
            ("th32ProcessID", _wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", _wt.DWORD),
            ("cntThreads", _wt.DWORD),
            ("th32ParentProcessID", _wt.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", _wt.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    class _MemStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", _wt.DWORD),
            ("dwMemoryLoad", _wt.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _K32.GetCurrentProcess.restype = _wt.HANDLE
    _K32.OpenProcess.restype = _wt.HANDLE
    _K32.OpenProcess.argtypes = [_wt.DWORD, _wt.BOOL, _wt.DWORD]
    _K32.CloseHandle.argtypes = [_wt.HANDLE]
    _K32.CreateToolhelp32Snapshot.restype = _wt.HANDLE
    _K32.CreateToolhelp32Snapshot.argtypes = [_wt.DWORD, _wt.DWORD]
    _K32.Process32First.argtypes = [_wt.HANDLE, ctypes.POINTER(_ProcEntry)]
    _K32.Process32Next.argtypes = [_wt.HANDLE, ctypes.POINTER(_ProcEntry)]
    _GetProcessMemoryInfo = _K32.K32GetProcessMemoryInfo
    _GetProcessMemoryInfo.argtypes = [
        _wt.HANDLE,
        ctypes.POINTER(_MemCounters),
        _wt.DWORD,
    ]
    _GetProcessMemoryInfo.restype = _wt.BOOL

    #: 只读访问权限：够读内存计数器，又不会被拒绝（比 PROCESS_QUERY_INFORMATION 宽松）。
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _TH32CS_SNAPPROCESS = 0x00000002
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
else:
    _PROCESS_QUERY_LIMITED_INFORMATION = 0
    _TH32CS_SNAPPROCESS = 0
    _INVALID_HANDLE_VALUE = None


class MemReader:
    """跨平台「读任意进程 RSS / 高水位 / 私有提交」。

    为什么不用 psutil：它不是本仓的依赖（``pyproject.toml`` 的依赖是钉死的口径），
    而这三件事在三个平台上各只有几行标准库代码。
    """

    def __init__(self) -> None:
        self._handles: dict[int, Any] = {}
        self.peak_source = "hwm" if (_IS_WIN or _IS_LINUX) else "sampled"

    # ── 单个进程 ────────────────────────────────────────────────
    def read(self, pid: int) -> tuple[int, int | None, int | None] | None:
        """返回 ``(rss, peak|None, private|None)``；读不到返回 None（进程已退出等）。"""
        if _IS_WIN:
            return self._read_win(pid)
        if _IS_LINUX:
            return self._read_linux(pid)
        return self._read_ps(pid)

    def close(self) -> None:
        if not _IS_WIN:  # pragma: no cover - 平台分支
            return
        for handle in self._handles.values():
            with contextlib.suppress(OSError):
                _K32.CloseHandle(handle)
        self._handles.clear()

    def read_cpu(self, pid: int) -> float | None:
        """进程**累计 CPU 时间**（用户+内核，秒）；读不到返回 None。

        为什么必须有这一列：墙钟会被**别人的进程**抬高（实测：我这轮 793 s 的测量期间
        机器上还有另一套 `-n 4` 的 pytest、一个外部项目的 12 worker 套件和一局游戏），
        而 CPU 时间对「谁在抢 CPU」免疫 —— 它才是判断「这次改动是不是真慢」的口径。
        """
        if _IS_WIN:
            return self._cpu_win(pid)
        if _IS_LINUX:
            return self._cpu_linux(pid)
        return self._cpu_ps(pid)

    def _cpu_win(self, pid: int) -> float | None:  # pragma: no cover - 平台分支
        handle = _K32.GetCurrentProcess() if pid == os.getpid() else self._handles.get(pid)
        if handle is None:
            handle = _K32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return None
            self._handles[pid] = handle
        created = _wt.FILETIME()
        exited = _wt.FILETIME()
        kernel = _wt.FILETIME()
        user = _wt.FILETIME()
        ok = _K32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        to_s = lambda ft: ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7  # noqa: E731
        return round(to_s(kernel) + to_s(user), 2)

    @staticmethod
    def _cpu_linux(pid: int) -> float | None:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        tail = stat.rpartition(")")[2].split()
        if len(tail) < 15:
            return None
        ticks = int(tail[11]) + int(tail[12])  # utime + stime
        return round(ticks / (os.sysconf("SC_CLK_TCK") or 100), 2)

    @staticmethod
    def _cpu_ps(pid: int) -> float | None:  # pragma: no cover - macOS
        out = _run_quiet(["ps", "-o", "time=", "-p", str(pid)])
        if not out:
            return None
        parts = out.strip().split(":")
        try:
            seconds = 0.0
            for part in parts:
                seconds = seconds * 60 + float(part)
        except ValueError:
            return None
        return round(seconds, 2)

    def _read_win(self, pid: int) -> tuple[int, int, int] | None:
        if pid == os.getpid():
            handle = _K32.GetCurrentProcess()  # 伪句柄，不用关、也不进缓存
        else:
            handle = self._handles.get(pid)
            if handle is None:
                # 只读权限就够：比 PROCESS_QUERY_INFORMATION 宽松，不会被拒
                handle = _K32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not handle:
                    return None
                self._handles[pid] = handle
        counters = _MemCounters()
        counters.cb = ctypes.sizeof(counters)
        try:
            if not _GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                self._drop(pid)
                return None
        except OSError:  # pragma: no cover - 权限/退出竞态
            self._drop(pid)
            return None
        return (
            int(counters.WorkingSetSize),
            int(counters.PeakWorkingSetSize),
            int(counters.PagefileUsage),
        )

    def _drop(self, pid: int) -> None:  # pragma: no cover - 只在竞态下走到
        handle = self._handles.pop(pid, None)
        if handle:
            with contextlib.suppress(OSError):
                _K32.CloseHandle(handle)

    @staticmethod
    def _read_linux(pid: int) -> tuple[int, int | None, int | None] | None:
        try:
            text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        fields: dict[str, int] = {}
        for line in text.splitlines():
            key, _, rest = line.partition(":")
            value = rest.strip().split()
            if not value or not value[0].isdigit():
                continue
            if key in {"VmRSS", "VmHWM", "RssAnon"}:
                fields[key] = int(value[0]) * 1024
        rss = fields.get("VmRSS")
        if rss is None:
            return None
        return (rss, fields.get("VmHWM"), fields.get("RssAnon"))

    @staticmethod
    def _read_ps(pid: int) -> tuple[int, int | None, int | None] | None:  # pragma: no cover
        """macOS / 其它 POSIX：只有当前 RSS，没有高水位。"""
        out = _run_quiet(["ps", "-o", "rss=", "-p", str(pid)])
        if out is None:
            return None
        text = out.strip()
        if not text.isdigit():
            return None
        return (int(text) * 1024, None, None)


def _run_quiet(cmd: Sequence[str]) -> str | None:
    """跑一条只读命令取 stdout；不存在 / 失败返回 None（不抛）。"""
    if shutil.which(cmd[0]) is None:
        return None
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


# ────────────────────────── 进程表 / 系统内存 ──────────────────────────


def _looks_python(name: str) -> bool:
    """按进程名判断「这是不是 python」（跨平台：python / python3.14 / pythonw / py.exe）。"""
    low = name.lower()
    return low.startswith(("python", "py.")) or low in {"py", "pyw", "pythonw"}


def list_procs() -> list[tuple[int, int, str]]:
    """``[(pid, ppid, 进程名), …]``。"""
    if _IS_WIN:
        return _list_procs_win()
    if _IS_LINUX:
        return _list_procs_linux()
    return _list_procs_ps()  # pragma: no cover


def _list_procs_win() -> list[tuple[int, int, str]]:  # pragma: no cover - 平台分支
    snapshot = _K32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or int(snapshot) == int(_INVALID_HANDLE_VALUE or 0):
        return []
    rows: list[tuple[int, int, str]] = []
    try:
        entry = _ProcEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _K32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.decode("mbcs", errors="replace")
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), name))
            ok = _K32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        _K32.CloseHandle(snapshot)
    return rows


def _list_procs_linux() -> list[tuple[int, int, str]]:
    rows: list[tuple[int, int, str]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # comm 里可以有空格与括号，prune 到最后一个 ')' 之后再切
        head, _, tail = stat.rpartition(")")
        parts = tail.split()
        if len(parts) < 2:
            continue
        rows.append((int(entry.name), int(parts[1]), head.partition("(")[2]))
    return rows


def _list_procs_ps() -> list[tuple[int, int, str]]:  # pragma: no cover - macOS
    out = _run_quiet(["ps", "-axo", "pid=,ppid=,comm="])
    if out is None:
        return []
    rows: list[tuple[int, int, str]] = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        rows.append((int(parts[0]), int(parts[1]), Path(parts[2]).name if len(parts) > 2 else ""))
    return rows


def sys_mem() -> dict[str, float | None]:
    """``{total_mb, avail_mb, commit_mb}``；读不到的项为 None（不猜）。"""
    if _IS_WIN:
        status = _MemStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if _K32.GlobalMemoryStatusEx(ctypes.byref(status)):
            pagefile = status.ullTotalPageFile - status.ullAvailPageFile
            return {
                "total_mb": _mb(status.ullTotalPhys),
                "avail_mb": _mb(status.ullAvailPhys),
                "commit_mb": _mb(pagefile),
            }
        return {"total_mb": None, "avail_mb": None, "commit_mb": None}
    if _IS_LINUX:
        fields: dict[str, float] = {}
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, _, rest = line.partition(":")
                value = rest.strip().split()
                if value and value[0].isdigit():
                    fields[key] = float(value[0]) * 1024
        except OSError:  # pragma: no cover
            return {"total_mb": None, "avail_mb": None, "commit_mb": None}
        return {
            "total_mb": _mb(fields.get("MemTotal", 0)),
            "avail_mb": _mb(fields.get("MemAvailable", 0)),
            "commit_mb": _mb(fields.get("Committed_AS", 0)),
        }
    total = _run_quiet(["sysctl", "-n", "hw.memsize"])  # pragma: no cover - macOS
    return {
        "total_mb": _mb(float(total)) if total and total.strip().isdigit() else None,
        "avail_mb": None,
        "commit_mb": None,
    }


def cpu_count() -> int | None:
    try:
        return len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:
        return os.cpu_count()


def cache_state() -> dict[str, Any]:
    """磁盘解析缓存的分片实况（**不 import pdx** —— 那会把分片读进内存）。

    为什么要记：worker 的内存里有很大一块是「读过的分片」，所以「同一台机器、
    同一条命令、两个数」只有在缓存状态也相同时才可比。这里只看文件名与字节数，
    按桶（一个仓库路径一个桶）列出。
    """
    root = Path(tempfile.gettempdir())
    buckets: list[dict[str, Any]] = []
    for folder in sorted(root.glob("v3-parse-cache-*")):
        if not folder.is_dir():
            continue
        files = sorted(folder.glob("shard-*.bin"))
        buckets.append(
            {
                "dir": str(folder),
                "shards": len(files),
                "bytes": sum(f.stat().st_size for f in files if f.is_file()),
                "newest": max((f.stat().st_mtime for f in files if f.is_file()), default=0),
            }
        )
    return {"buckets": buckets, "shards_total": sum(b["shards"] for b in buckets)}


def machine_info() -> dict[str, Any]:
    mem = sys_mem()
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "cpu_logical": cpu_count(),
        "total_ram_mb": mem["total_mb"],
        "avail_ram_mb_at_start": mem["avail_mb"],
        "peak_source": MemReader().peak_source,
        "probe": str(Path(__file__).resolve().relative_to(REPO)),
        # 工具自身的指纹：口径会随脚本修订而变，所以「这份数是谁跑出来的」
        # 必须可核对（详见 docs/design/exec/并行测试内存基线.md §3.3）。
        "probe_sha256": _self_sha256(),
    }


def _self_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    except OSError:  # pragma: no cover - 脚本必然读得到自己
        return "?"


# ────────────────────────── 进程树采样 ──────────────────────────


class TreeSampler(threading.Thread):
    """按固定间隔采样「以 root 为根的那棵树」的常驻内存。

    只数子树是刻意的：上一轮的采样器数全机器 python，把无关进程算进了峰值，
    于是那个数在别的机器上不可复算（见模块文档 §口径更正）。
    """

    def __init__(
        self,
        root_pid: int,
        *,
        interval_s: float = INTERVAL_MS / 1000.0,
        watch_mb: float = 0.0,
        watch_avail_mb: float = 0.0,
        killer: Any = None,
    ) -> None:
        super().__init__(name="mem-tree-sampler", daemon=True)
        self.root_pid = root_pid
        self.interval_s = interval_s
        self.watch_mb = watch_mb
        self.watch_avail_mb = watch_avail_mb
        self.kill_reason = ""
        self._killer = killer
        self._stop = threading.Event()
        self._reader = MemReader()
        self._t0 = time.time()
        #: 时间线：(t_s, nproc, total_rss_bytes, total_private_bytes, avail_mb)
        self.rows: list[tuple[float, int, int, int, float | None]] = []
        #: pid -> 统计
        self.procs: dict[int, dict[str, Any]] = {}
        self.killed_by_watchdog = False
        self.max_procs = 0
        self.peak_total_bytes = 0
        self.peak_private_bytes = 0
        self.peak_at_s = 0.0
        self.controller_pid = root_pid
        self.worker_pids: list[int] = []
        self.classifier_note = ""
        self._errors: list[str] = []

    # ── 采样 ────────────────────────────────────────────────────
    def run(self) -> None:  # pragma: no cover - 线程体
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception as exc:
                self._errors.append(repr(exc))
            if self.killed_by_watchdog:
                return
            self._stop.wait(self.interval_s)

    def sample_once(self) -> None:
        table = list_procs()
        children: dict[int, list[int]] = {}
        names: dict[int, str] = {}
        parents: dict[int, int] = {}
        for pid, ppid, name in table:
            names[pid] = name
            parents[pid] = ppid
            children.setdefault(ppid, []).append(pid)

        tree: list[tuple[int, int]] = []  # (pid, level)
        stack = [(self.root_pid, 0)]
        seen: set[int] = set()
        while stack:
            pid, level = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            tree.append((pid, level))
            stack.extend((child, level + 1) for child in children.get(pid, ()))

        t = round(time.time() - self._t0, 3)
        total_rss = 0
        total_private = 0
        for pid, level in tree:
            row = self._reader.read(pid)
            if row is None:
                continue
            rss, hwm, private = row
            total_rss += rss
            total_private += private or 0
            stats = self.procs.get(pid)
            if stats is None:
                stats = {
                    "pid": pid,
                    "ppid": parents.get(pid, 0),
                    "name": names.get(pid, ""),
                    # 角色留到 finish() 时统一判（launcher 中转要靠完整的父子关系，
                    # 采样途中定角色会把 launcher 当成 root，见 _classify）
                    "role": "helper",
                    "level": level,
                    "first_t": t,
                    "last_t": t,
                    "rss_max": rss,
                    "hwm": hwm if hwm is not None else rss,
                    "peak_source": "hwm" if hwm is not None else "sampled",
                    "cpu_s": 0.0,
                    "samples": 0,
                }
                self.procs[pid] = stats
            stats["level"] = min(stats["level"], level)
            stats["last_t"] = t
            stats["samples"] += 1
            stats["rss_max"] = max(stats["rss_max"], rss)
            cpu = self._reader.read_cpu(pid)
            if cpu is not None:
                stats["cpu_s"] = cpu
            if hwm is not None:
                stats["hwm"] = max(stats["hwm"], hwm)
                stats["peak_source"] = "hwm"
            else:
                stats["hwm"] = max(stats["hwm"], rss)

        mem = sys_mem()
        self.rows.append((t, len(tree), total_rss, total_private, mem["avail_mb"]))
        self.max_procs = max(self.max_procs, len(tree))
        if total_rss > self.peak_total_bytes:
            self.peak_total_bytes = total_rss
            self.peak_at_s = t
        self.peak_private_bytes = max(self.peak_private_bytes, total_private)

        if not self.killed_by_watchdog and self.watch_mb and total_rss / 1048576.0 > self.watch_mb:
            self._trigger(f"树 RSS {total_rss / 1048576.0:.0f}MB 超过上限 {self.watch_mb:.0f}MB")
        avail = mem["avail_mb"]
        if (
            not self.killed_by_watchdog
            and self.watch_avail_mb
            and avail is not None
            and avail < self.watch_avail_mb
        ):
            self._trigger(f"物理可用内存 {avail:.0f}MB 低于下限 {self.watch_avail_mb:.0f}MB")

    def _trigger(self, reason: str) -> None:
        """看门狗开火：记下原因并杀树（原因会进产物，免得只剩一个「被杀了」）。"""
        self.killed_by_watchdog = True
        self.kill_reason = reason
        if self._killer is not None:
            self._killer()

    # ── 归类 ────────────────────────────────────────────────────
    def _classify(self) -> None:
        """给每个进程定角色：``launcher`` / ``root``（真跑 pytest 那个）/ ``worker`` / ``helper``。

        为什么不能按「第几层子进程」一刀切：本机的 ``.venv\\Scripts\\python.exe`` 是
        个 **launcher**（实测：它 exec 出**同名同命令行**的子进程，``os.getpid()`` 落在
        子进程里，自己只占 4 MB），而且 xdist 起 worker 时**也**经由它 —— 于是一棵树是
        ``launcher → 真 pytest → launcher → worker``，光看层数会把 worker 当成真身。

        判据改成正向识别，与 launcher 有几跳无关：

        * **候选**：python 进程里高水位 ≥ :data:`LAUNCHER_MAX_MB` 的那些（launcher
          只有 4 MB，永远进不了候选）；
        * **真身（controller）**：候选里**最浅**的那个（并列时取「候选后代最多」的）；
        * **worker**：真身的后代候选，且其父就是真身，或父是 python 但**不是候选**
          （那正是 launcher 中转）而祖父是真身；
        * 其余是 ``helper``（测试自己起的 `v3` 之类），真身的 python 祖先是 ``launcher``。

        ``--inproc`` 时这份分类会被 worker 自报的 pid 交叉验证（见 :func:`read_inproc`），
        所以「判错了」不会悄悄混进基线。
        """
        pythons = {pid: s for pid, s in self.procs.items() if _looks_python(s["name"])}
        cands = [pid for pid, s in pythons.items() if s["hwm"] / 1048576.0 >= LAUNCHER_MAX_MB]

        def ancestors(pid: int) -> list[int]:
            """只走**本棵测量树内**的祖先（树外的进程不参与分类）。"""
            chain: list[int] = []
            node = self.procs.get(pid, {}).get("ppid", 0)
            while node in self.procs and node not in chain:
                chain.append(node)
                node = self.procs[node]["ppid"]
            return chain

        def is_descendant(pid: int, top: int) -> bool:
            return pid != top and top in ancestors(pid)

        if cands:
            self.controller_pid = min(
                cands,
                key=lambda p: (
                    self.procs[p]["level"],
                    -sum(1 for other in cands if is_descendant(other, p)),
                ),
            )
        else:  # 极短的运行：连 pytest 都还没长到候选阈值
            self.controller_pid = self.root_pid

        span = max((s["last_t"] for s in self.procs.values()), default=0.0) - min(
            (s["first_t"] for s in self.procs.values()), default=0.0
        )
        # 存活下限**相对真身**取：worker 与真身几乎同寿命，而测试自己起的
        # `v3` 子进程只活几秒。绝对阈值在短跑（冒烟）里会误杀 worker ——
        # 实测 2 秒的跑法里 worker 只被采到 0.8 秒，1.0 秒的绝对下限把它筛掉了。
        own_span = self.procs.get(self.controller_pid, {}).get("last_t", 0.0) - self.procs.get(
            self.controller_pid, {}
        ).get("first_t", 0.0)
        alive_floor = max(0.2, ALIVE_RATIO * max(own_span, 0.2))
        launchers = set(ancestors(self.controller_pid))
        workers: list[int] = []
        for pid in cands:
            if pid == self.controller_pid:
                continue
            parent = self.procs[pid]["ppid"]
            direct = parent == self.controller_pid
            via_launcher = (
                parent in pythons
                and parent not in cands
                and self.procs[parent]["ppid"] == self.controller_pid
            )
            if not (direct or via_launcher):
                continue
            if (self.procs[pid]["last_t"] - self.procs[pid]["first_t"]) < alive_floor:
                continue
            workers.append(pid)
        self.worker_pids = sorted(workers)

        for pid, stats in self.procs.items():
            if pid == self.controller_pid:
                stats["role"] = "root"
            elif pid in launchers:
                stats["role"] = "launcher"
            elif pid in workers:
                stats["role"] = "worker"
            else:
                stats["role"] = "helper"
        self.classifier_note = (
            f"root pid={self.root_pid} → 真身 pid={self.controller_pid}"
            f"（launcher 中转 {sorted(launchers)}）；候选阈值 {LAUNCHER_MAX_MB:.0f}MB，"
            f"worker 存活下限 {alive_floor:.1f}s（真身寿命 {own_span:.1f}s 的 "
            f"{ALIVE_RATIO:.0%}），判出 {len(workers)} 个 worker（树跨度 {span:.1f}s）"
        )

    def finish(self) -> dict[str, Any]:
        self._stop.set()
        self.join(timeout=5.0)
        self._reader.close()
        self._classify()
        workers = [s for s in self.procs.values() if s["role"] == "worker"]
        per_worker = max((s["hwm"] for s in workers), default=0)
        n_workers = max(
            (
                sum(1 for s in workers if s["first_t"] <= t <= s["last_t"])
                for t, _, _, _, _ in self.rows
            ),
            default=0,
        )
        return {
            "samples": len(self.rows),
            "max_procs": self.max_procs,
            "peak_total_mb": _mb(self.peak_total_bytes),
            "peak_total_private_mb": _mb(self.peak_private_bytes),
            "peak_at_s": self.peak_at_s,
            "sum_hwm_mb": _mb(sum(s["hwm"] for s in self.procs.values())),
            #: 被测树的 CPU 时间合计（秒）—— 墙钟会被别人抢 CPU 抬高，这个不会。
            "cpu_total_s": round(sum(s.get("cpu_s", 0.0) for s in self.procs.values()), 1),
            "cpu_workers_s": round(sum(s.get("cpu_s", 0.0) for s in workers), 1),
            "per_worker_peak_mb": _mb(per_worker),
            "n_workers": n_workers,
            "worker_pids": self.worker_pids,
            "controller_pid": self.controller_pid,
            "classifier_note": self.classifier_note,
            "killed_by_watchdog": self.killed_by_watchdog,
            "kill_reason": self.kill_reason,
            "sampler_errors": self._errors[:5],
        }

    def procs_table(self) -> list[dict[str, Any]]:
        rows = sorted(self.procs.values(), key=lambda s: (-s["hwm"], s["pid"]))
        return [
            {
                "pid": s["pid"],
                "name": s["name"],
                "role": s["role"],
                "level": s["level"],
                "first_t_s": s["first_t"],
                "last_t_s": s["last_t"],
                "samples": s["samples"],
                "rss_max_mb": _mb(s["rss_max"]),
                "hwm_mb": _mb(s["hwm"]),
                "cpu_s": s.get("cpu_s", 0.0),
                "peak_source": s["peak_source"],
            }
            for s in rows
        ]

    def timeline_csv(self) -> str:
        lines = ["t_s,nproc,total_rss_mb,total_private_mb,avail_mb"]
        for t, nproc, rss, private, avail in self.rows:
            lines.append(f"{t},{nproc},{_mb(rss)},{_mb(private)},{'' if avail is None else avail}")
        return "\n".join(lines) + "\n"

    def procs_csv(self) -> str:
        keys = (
            "pid",
            "name",
            "role",
            "level",
            "first_t_s",
            "last_t_s",
            "samples",
            "rss_max_mb",
            "hwm_mb",
            "cpu_s",
            "peak_source",
        )
        lines = [",".join(keys)]
        lines.extend(",".join(str(row[key]) for key in keys) for row in self.procs_table())
        return "\n".join(lines) + "\n"


# ────────────────────────── 起进程 / 停进程 ──────────────────────────


def kill_tree(pid: int) -> None:
    """把一棵进程树停掉（看门狗与 Ctrl-C 共用）。"""
    if _IS_WIN:  # pragma: no cover - 平台分支
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    # pragma: no cover - POSIX
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        return
    time.sleep(2.0)
    with contextlib.suppress(OSError):
        os.killpg(os.getpgid(pid), signal.SIGKILL)


def spawn(argv: Sequence[str], env: dict[str, str], log_path: Path) -> tuple[Any, Any]:
    """起被测命令，stdout/stderr 合并到一条管道（由调用方边读边落盘）。"""
    creationflags = 0x00000200 if _IS_WIN else 0  # CREATE_NEW_PROCESS_GROUP
    pipe = subprocess.Popen(
        list(argv),
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
        start_new_session=not _IS_WIN,
    )
    return pipe, log_path.open("w", encoding="utf-8", newline="\n")


def foreign_heavy(min_mb: float, ignore: Iterable[int] = ()) -> list[dict[str, Any]]:
    """列出**不属于本次测量**的重活进程（python / victoria3）。

    口径：任何名字像 python 的进程、任何 victoria3（游戏），只要常驻 ≥ ``min_mb``
    就报出来。测量要求「无并发重活」——并行套件、`v3 verify`、游戏都会改变
    可用的物理内存与 CPU，测出来的峰值就不是这套测试自己的。
    """
    ignore_set = set(ignore)
    reader = MemReader()
    found: list[dict[str, Any]] = []
    try:
        for pid, _ppid, name in list_procs():
            if pid in ignore_set:
                continue
            low = name.lower()
            if not (_looks_python(name) or "victoria3" in low):
                continue
            row = reader.read(pid)
            if row is None:
                continue
            rss = row[0]
            if rss / 1048576.0 >= min_mb:
                found.append({"pid": pid, "name": name, "rss_mb": _mb(rss)})
    finally:
        reader.close()
    return sorted(found, key=lambda item: -item["rss_mb"])


def wait_for_quiet(
    min_mb: float, min_avail_mb: float, max_s: float, *, poll_s: float = 20.0
) -> tuple[list[dict[str, Any]], float | None]:
    """等到「机器既没有别的重活、又有足够空闲物理内存」为止。

    返回 ``(最后一次看到的并发重活清单, 当时的可用物理内存)``。超时也返回，
    由调用方决定是报错退出还是记下状态继续 —— 但**绝不静默继续**：
    「测量时无并发重活」是这份基线的合约条件之一。
    """
    deadline = time.time() + max_s
    while True:
        busy = foreign_heavy(min_mb, ignore={os.getpid()})
        avail = sys_mem()["avail_mb"]
        enough = avail is None or avail >= min_avail_mb
        if (not busy and enough) or time.time() >= deadline:
            return busy, avail
        print(
            f"[mem] 等安静：并发重活 {len(busy)} 个"
            + (
                f"（最大 {busy[0]['name']} pid={busy[0]['pid']} {busy[0]['rss_mb']}MB）"
                if busy
                else ""
            )
            + (f"，可用物理内存 {avail:.0f}MB < {min_avail_mb:.0f}MB" if not enough else "")
            + f"；{poll_s:.0f}s 后再看",
            flush=True,
        )
        time.sleep(poll_s)


def ensure_quiet(
    *,
    quiet_mb: float,
    min_avail_mb: float,
    wait_s: float,
    allow: bool,
    strict: bool = True,
) -> None:
    """测量开工前的守卫：等安静，或（显式 ``--allow-concurrent``）记下状态照跑。

    ⚠️ ``allow=True`` 时**不等待**、直接开工并留痕 —— 实测踩过：先等再判，
    于是「显式允许并发」的命令会先干等一个 ``--wait-quiet-s``（十几分钟），
    看起来像卡死。允许就是允许，等是把闸又装回去了。
    """
    before = foreign_heavy(quiet_mb, ignore={os.getpid()})
    if not before:
        return
    if allow:
        print(
            f"[mem] {_mark('⚠️', '[!]')} --allow-concurrent：不等，直接开工；并发快照照记（{before[:3]}）",
            flush=True,
        )
        return
    busy, avail = wait_for_quiet(quiet_mb, min_avail_mb, wait_s)
    if not busy and (avail is None or avail >= min_avail_mb):
        return
    if strict:
        raise SystemExit(
            f"[mem] 机器不安静：并发重活 {busy[:3]}，可用物理 {avail}MB —— "
            f"测量要求无并发重活（并行套件 / v3 verify / 游戏都会改变读数）。"
            f"停掉它们再跑，或显式 --allow-concurrent 把状态如实记下来。"
        )


# ────────────────────────── 组定义 / 命令拼装 ──────────────────────────

#: 合约要求的必测组（①②③）+ 两个附加组。命令原文写在这里，产物里也原样记一份。
GROUPS: dict[str, dict[str, Any]] = {
    "n4": {
        "n": "4",
        "cache": True,
        "required": True,
        "note": "合约①：默认并行度对照（-n 4）",
    },
    "n4-nocache": {
        "n": "4",
        "cache": False,
        "required": True,
        "note": "合约②：同上但 V3_PARSE_CACHE=0 关闭磁盘缓存层",
    },
    "n1": {
        "n": "1",
        "cache": True,
        "required": True,
        "note": "合约③：-n 1 串行，作为下界参考",
    },
    "auto": {
        "n": "auto",
        "cache": True,
        "required": False,
        "note": "附加：pyproject addopts 的默认并行度（本机 -n auto = 逻辑核数）",
    },
    "n4-seed1": {
        "n": "4",
        "cache": True,
        "seed": 1,
        "required": False,
        "note": "附加：固定随机种子，供优化前后做同序 A/B",
    },
}


def group_argv(group: str, *, inproc: bool, target: str) -> list[str]:
    spec = GROUPS[group]
    argv = [sys.executable, "-m", "pytest", target, "-q", "-n", spec["n"]]
    if spec.get("seed"):
        argv.append(f"--randomly-seed={spec['seed']}")
    if inproc:
        argv += ["-p", "mem_baseline"]
    return argv


def group_env(
    group: str, *, stem: str | None = None, inproc: bool
) -> tuple[dict[str, str], dict[str, str]]:
    """返回 ``(env, 覆盖说明)``。每个覆盖都记进产物，免得「复算命令」缺一环。

    ``stem`` 是产物前缀（默认 = 组名）：`--inproc` 的原始读数按**前缀**落盘
    （`inproc-<前缀>-*.json`），这样同一个 tag 的两条臂不会互相覆盖（B108 的同一族）。
    """
    spec = GROUPS[group]
    stem = stem or group
    env = dict(os.environ)
    overrides: dict[str, str] = {}
    if not spec["cache"]:
        env["V3_PARSE_CACHE"] = "0"
        overrides["V3_PARSE_CACHE"] = "0"
    if inproc:
        probe_dir = str(Path(__file__).resolve().parent)
        env["PYTHONPATH"] = probe_dir + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        env["MEMBASELINE_OUT"] = str(OUT_DIR)
        env["MEMBASELINE_TAG"] = stem
        overrides["PYTHONPATH"] = probe_dir
        overrides["MEMBASELINE_OUT"] = str(OUT_DIR)
        overrides["MEMBASELINE_TAG"] = stem
    # 子进程的 stdout 是管道：Windows 上默认按 ANSI 代码页编码，中文输出会乱码
    # 甚至抛 UnicodeEncodeError。这一条只影响 I/O 编码，不改变被测行为。
    env["PYTHONIOENCODING"] = "utf-8"
    overrides["PYTHONIOENCODING"] = "utf-8"
    return env, overrides


def human_command(group: str, *, stem: str | None = None, inproc: bool, target: str) -> str:
    spec = GROUPS[group]
    stem = stem or group
    py = _short_python()
    parts = [py, "-m", "pytest", target, "-q", "-n", spec["n"]]
    if spec.get("seed"):
        parts.append(f"--randomly-seed={spec['seed']}")
    if inproc:
        parts += ["-p", "mem_baseline"]
    env_bits = []
    if not spec["cache"]:
        env_bits.append("V3_PARSE_CACHE=0")
    if inproc:
        env_bits.append(f"PYTHONPATH={_short(Path(__file__).resolve().parent)}")
        env_bits.append("MEMBASELINE_OUT=tools/out/mem")
        env_bits.append(f"MEMBASELINE_TAG={stem}")
    head = (
        (
            "$env:"
            + "; $env:".join(f"{k}={v}" for k, v in (b.split("=", 1) for b in env_bits))
            + "; "
        )
        if env_bits
        else ""
    )
    return head + " ".join(parts)


def _short(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("/", os.sep)
    except ValueError:
        return str(path)


def _short_python() -> str:
    return _short(Path(sys.executable))


# ────────────────────── 产物命名与索引落点（B107/B108/B109 的正面修法）──────────────────────


def _mark(glyph: str, fallback: str) -> str:
    """控制台编码装不下这个字符时退回 ASCII（B109：GBK 控制台下不许抛 `UnicodeEncodeError`）。

    为什么按**运行时的 stdout 编码**决定，而不是一律写 ASCII：UTF-8 控制台（Linux/macOS、
    以及带 `-X utf8` 的 Windows）上那些标记是可读的，一律降级会让读数变难认；而 Windows
    默认控制台是 GBK（cp936），`✅`/`❌`/`⚠️`/`↳` **都不在 cp936 里** —— `print` 会抛
    `UnicodeEncodeError`，整条命令判红（t14 实测：同一条命令在 GBK 控制台判红、在 UTF-8
    环境判绿 ⇒ 判据不稳定，且违反用户原则③）。两种环境**各自可读**才是修法。
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        glyph.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return fallback
    return glyph


def _reconfigure_stdio() -> None:
    """兜底：stdout/stderr 的编码错误策略改成 `replace`（**别因为一个字符整条命令崩掉**）。

    与 :func:`_mark` 分工不同：`_mark` 管**我们自己**打印的标记；这一条管**别人交给我们打印的
    东西** —— `run_group` 会把被测命令的输出原样回显（`sys.stdout.write(line)`），那里面出现
    任何本控制台编码装不下的字符，同一族崩溃会再发生一次。`errors="replace"` 只影响 I/O，
    不改变被测行为。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # pragma: no cover - stdout 被换成 StringIO 时（用例里）
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="replace")


def artifact_stem(tag: str, group: str) -> str:
    """一组的产物前缀：`<tag>`；`--tag` 与组名不同时是 `<tag>-<group>`。

    B108（t13 实测）：产物原来只按 `<tag>` 命名 ⇒ 同一个 tag 跑第二条臂时，第一条臂的
    `per-pid` 与 `avail_mb` 序列**被直接覆盖**，事后补不回来（报告里只能标注"缺"）。
    两组必须各有各的名字；而 `--tag` 与组名相同时**不**产生 `<n4>-<n4>` 这种丑名字
    （那是日常用法，路径不许变）。
    """
    return tag if tag == group else f"{tag}-{group}"


def group_artifact_paths(stem: str) -> dict[str, Path]:
    """一组的四份产物（**唯一命名处**：`run_group` 与用例共用，免得两处各写一遍而漂移）。"""
    return {
        "summary": OUT_DIR / f"{stem}.summary.json",
        "samples": OUT_DIR / f"{stem}.samples.csv",
        "procs": OUT_DIR / f"{stem}.procs.csv",
        "log": OUT_DIR / f"{stem}.log",
    }


def tag_groups_seen(tag: str, group: str) -> list[str]:
    """本 tag 已经跑过哪些 group（**从盘上 summary 现读**，不靠记忆）。

    B108 的第二个要求：光让文件不互相覆盖还不够，还得能从产物里读出「这个 tag 下跑过哪些臂」。

    认亲用的是 **`tag_arg`（用户给的那个 tag）**，不是 `tag`（= 产物前缀）：两条臂的前缀
    带上了组名（:func:`artifact_stem`），拿前缀去比会一条都认不出来 —— 这正是第一版用例
    当场撞出来的问题（`groups_seen` 只剩自己那一组）。老产物没有 `tag_arg` ⇒ 退回比 `tag`
    （那时前缀就等于 tag，语义一致）。顺序按文件名，读的是**盘上现在有什么**（删了就是没跑过）。
    """
    seen: list[str] = []
    for path in sorted(OUT_DIR.glob("*.summary.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        owner = str(payload.get("tag_arg") or payload.get("tag") or "")
        if owner != tag:
            continue
        name = str(payload.get("group") or owner)
        if name and name not in seen:
            seen.append(name)
    if group not in seen:
        seen.append(group)
    return seen


def default_index_path(groups: Sequence[str], stems: Sequence[str]) -> Path:
    """不带 `--index` 时索引写哪儿 —— **单组绝不写冻结的 `baseline.json`**（B107）。

    原行为：`--index` 默认就是 `baseline.json`，而 `run` 会把索引**整体重写**成这次跑的组
    ⇒ 跑一组就把多组基线截断（t13 实测 42,568 B → 20,508 B、只剩 `n4-nocache`），
    而且**不报错**；之后任何"优化前 vs 优化后"的对照都拿被截断的基线当基准。
    现在：单组 ⇒ `<前缀>.json`（与它自己的明细同前缀，天然成组）；多组 ⇒ `baseline.json`
    （"重做整套基线"的意图，路径不变）。
    """
    if len(groups) == 1:
        return OUT_DIR / f"{stems[0]}.json"
    return OUT_DIR / "baseline.json"


def index_overwrite_guard(path: Path, groups: Sequence[str], *, force: bool) -> str | None:
    """覆盖索引前的闸门：**这次不跑的组还留在里面**就拒绝（返回理由；`None` = 放行）。

    与 :func:`default_index_path` 是两道**独立的**门：前者管"别默认写到冻结索引上"，
    这一条管"就算你显式指到它上面，也不许把它的组悄悄弄丢"。放行两种情形：文件不存在
    （没什么可丢的）、这次跑的组覆盖了文件里已有的组（重做基线是正常意图）。`--force` 越过闸门。
    """
    if force or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        old = {str(g.get("group") or g.get("tag")) for g in payload.get("groups", [])}
    except (OSError, ValueError) as exc:
        return f"{path} 已存在但读不出组清单（{exc!r}）"
    missing = sorted(old - set(groups))
    if missing:
        return f"{path} 里还有这次不跑的组，覆盖会把它们丢掉：{missing}"
    return None


# ────────────────────────── 一组测量 ──────────────────────────


def read_inproc(tag: str) -> dict[str, Any]:
    """读 ``--inproc`` 留下的每进程读数（worker 自报的 pid / 峰值）。

    用途是**交叉验证外部采样**：外部的每 worker 峰值是「存活期间最后一次观测到的
    OS 高水位」，而 worker 自报的是「退出前那一刻的高水位」。两者应当一致到
    采样误差以内；对不上就说明分类或采样有问题，先别信任何一个数。
    """
    files = sorted(OUT_DIR.glob(f"inproc-{tag}-*.json"))
    if not files:
        return {}
    procs = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        procs.append(
            {
                "worker": payload["worker"],
                "pid": payload["pid"],
                "peak_ws_mb": payload["peak_ws_mb"],
                "final_ws_mb": payload["final_ws_mb"],
                "duration_s": payload["duration_s"],
                "counts": payload.get("counts"),
                "file": path.name,
            }
        )
    return {"files": len(procs), "procs": sorted(procs, key=lambda row: row["worker"])}


def run_group(
    group: str,
    *,
    tag: str | None = None,
    target: str,
    inproc: bool,
    interval_ms: int,
    timeout_s: float,
    watch_mb: float,
    watch_avail_mb: float,
    quiet_poll_mb: float,
    min_avail_mb: float,
    wait_s: float,
    allow_concurrent: bool,
    echo: bool,
) -> dict[str, Any]:
    """跑一组 pytest 并落盘四份产物（**产物前缀 = `stem`，默认 = 组名**）。

    为什么把「组」与「产物前缀」拆开（B108）：`--tag` 允许同一个 tag 跑**不同的组**
    （t13 的两条臂就是同 tag、不同组）⇒ 前缀必须带上组名，两组才不互相覆盖
    （见 :func:`artifact_stem`）。组决定**跑什么**（`GROUPS[group]`），前缀只决定**写哪儿**。

    前缀在这里**算一次**（`artifact_stem(tag or group, group)`）：调用方只报"我要什么 tag"，
    免得有人手算一个与组对不上的前缀 —— 那正好会退化成 B108 那个覆盖。
    """
    stem = artifact_stem(tag or group, group)
    paths = group_artifact_paths(stem)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    argv = group_argv(group, inproc=inproc, target=target)
    env, overrides = group_env(group, stem=stem, inproc=inproc)
    command = human_command(group, stem=stem, inproc=inproc, target=target)

    before = foreign_heavy(quiet_poll_mb, ignore={os.getpid()})
    if before and not allow_concurrent:
        ensure_quiet(quiet_mb=quiet_poll_mb, min_avail_mb=min_avail_mb, wait_s=wait_s, allow=False)
    state_before = foreign_heavy(0.0, ignore={os.getpid()})
    mem_before = sys_mem()

    log_path = paths["log"]
    pipe, log = spawn(argv, env, log_path)
    killer = lambda: kill_tree(pipe.pid)  # noqa: E731 - 只给看门狗用
    sampler = TreeSampler(
        pipe.pid,
        interval_s=interval_ms / 1000.0,
        watch_mb=watch_mb,
        watch_avail_mb=watch_avail_mb,
        killer=killer,
    )
    sampler.start()

    t0 = time.time()
    timed_out = False
    try:
        assert pipe.stdout is not None
        for line in pipe.stdout:
            log.write(line)
            if echo:
                sys.stdout.write(line)
                sys.stdout.flush()
            if time.time() - t0 > timeout_s:
                timed_out = True
                kill_tree(pipe.pid)
                break
    except KeyboardInterrupt:  # pragma: no cover - 人工中断
        kill_tree(pipe.pid)
        raise
    finally:
        try:
            exit_code = pipe.wait(timeout=60)
        except subprocess.TimeoutExpired:  # pragma: no cover - 强杀没杀干净
            kill_tree(pipe.pid)
            exit_code = pipe.wait(timeout=30)
        wall_s = round(time.time() - t0, 1)
        log.close()

    stats = sampler.finish()
    procs = sampler.procs_table()
    paths["samples"].write_text(sampler.timeline_csv(), encoding="utf-8", newline="\n")
    paths["procs"].write_text(sampler.procs_csv(), encoding="utf-8", newline="\n")

    text = log_path.read_text(encoding="utf-8", errors="replace")
    counts, failed = parse_pytest_tail(text)
    # 本 tag 已经跑过哪些组：**写 summary 之前**先算（含本次这一组）⇒ 产物自己就能回答
    # 「这个 tag 下跑过哪些臂、各自的文件在哪」（B108 的第二个要求）。
    groups_seen = tag_groups_seen(tag or group, group)
    summary = {
        # `tag` = **产物前缀**（check/compare 按它认组）；`tag_arg` = 用户给的那个 tag
        # （`--tag`，不给就是组名）——「本 tag 跑过哪些组」按后者认亲，见 tag_groups_seen。
        "tag": stem,
        "tag_arg": tag or group,
        "group": group,
        "groups_seen": groups_seen,
        "artifacts": {name: _short(path) for name, path in paths.items()},
        "note": GROUPS[group]["note"],
        "required": GROUPS[group]["required"],
        "command": command,
        "argv": argv,
        "cwd": str(REPO),
        "env_overrides": overrides,
        "workers_arg": GROUPS[group]["n"],
        "workers_expected": int(GROUPS[group]["n"]) if str(GROUPS[group]["n"]).isdigit() else None,
        "wall_s": wall_s,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "counts": counts,
        "failed_names": failed[:40],
        "randomly_seed": parse_randomly_seed(text),
        "inproc": inproc,
        "machine": machine_info(),
        "concurrent_before_mb0": state_before,
        "concurrent_after_mb0": foreign_heavy(0.0, ignore={os.getpid()}),
        "mem_before": mem_before,
        "mem_after": sys_mem(),
        "sampler": {
            "interval_ms": interval_ms,
            "watch_mb": watch_mb,
            "log": _short(paths["log"]),
            "samples_csv": _short(paths["samples"]),
            "procs_csv": _short(paths["procs"]),
            "peak_source": MemReader().peak_source,
        },
        **stats,
        "procs": procs,
        "recompute": command,
    }
    # 交叉验证：worker 自报的 pid/峰值 vs 外部采样分类出来的 worker
    inproc_rows = read_inproc(stem) if inproc else {}
    if inproc_rows:
        summary["inproc"] = inproc_rows
        reported = sorted(row["pid"] for row in inproc_rows["procs"] if row["worker"] != "master")
        summary["inproc_worker_pids"] = reported
        summary["classify_match"] = sorted(summary["worker_pids"]) == reported
        external = {row["pid"]: row["hwm_mb"] for row in procs}
        summary["inproc_vs_external"] = [
            {
                "pid": row["pid"],
                "inproc_peak_mb": row["peak_ws_mb"],
                "external_hwm_mb": external.get(row["pid"]),
            }
            for row in inproc_rows["procs"]
        ]
    paths["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(
        f"[mem] tag={stem} group={group} wall={wall_s}s exit={exit_code} "
        f"peak_total={summary['peak_total_mb']}MB（上界 {summary['sum_hwm_mb']}MB）"
        f" per_worker_peak={summary['per_worker_peak_mb']}MB workers={summary['n_workers']}"
        f" seed={summary['randomly_seed']} -> {paths['summary'].name}",
        flush=True,
    )
    expected = summary["workers_expected"]
    if expected is not None and summary["n_workers"] != expected:
        print(
            f"[mem] {_mark('⚠️', '[!]')} 判出的 worker 数 {summary['n_workers']} ≠ 命令要求的 -n {expected}"
            f"（分类可疑，先看 {paths['procs'].name} 再引用数字）：{summary['classifier_note']}",
            flush=True,
        )
    if summary["killed_by_watchdog"]:
        print(
            f"[mem] {_mark('⚠️', '[!]')} 看门狗中止本组：{summary['kill_reason']}",
            flush=True,
        )
    return summary


#: pytest 收尾汇总里的计数段（`5 failed` / `1592 passed` / `1 error`）。
_COUNT_RE = re.compile(r"(\d+) (passed|failed|skipped|error|errors|deselected|xfailed|xpassed)")


def parse_pytest_tail(text: str) -> tuple[dict[str, int], list[str]]:
    """从 pytest 收尾汇总里取计数与失败用例名（拿不到就给空，不猜）。

    为什么要按逗号切再 ``fullmatch``：`-q` 的收尾行是
    ``35 passed, 16 subtests passed in 1.23s`` 这种**没有 ``=``** 的行，
    而 ``16 subtests passed`` 不是用例数 —— 按整段切、逐段 fullmatch
    才能既拿到 ``35`` 又不把 ``16`` 算进去（实测踩过）。
    """
    counts: dict[str, int] = {}
    failed: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("FAILED ", "ERROR ")):
            failed.append(stripped.split(" ", 1)[1][:160])
        head = stripped.split(" in ", 1)[0]
        for chunk in head.split(","):
            hit = _COUNT_RE.fullmatch(chunk.strip())
            if not hit:
                continue
            key = "error" if hit.group(2).startswith("error") else hit.group(2)
            counts[key] = counts.get(key, 0) + int(hit.group(1))
    return counts, failed


def parse_randomly_seed(text: str) -> int | None:
    hit = re.search(r"--randomly-seed=(\d+)", text)
    return int(hit.group(1)) if hit else None


# ────────────────────────── 预算判决 ──────────────────────────


def budget_for(workers: int) -> float:
    return round(BUDGET_HEAD_MB + BUDGET_PER_WORKER_MB * workers, 1)


def judge(summary: dict[str, Any], *, min_passed: int | None = None) -> dict[str, Any]:
    """一条可自动判定的上限：每 worker ≤ X 且 整套 ≤ 1024 + n×X（外加不许靠少跑用例省内存）。"""
    if summary.get("aborted"):
        return {
            "tag": summary.get("tag"),
            "workers": 0,
            "ok": False,
            "checks": [
                {
                    "name": "ran",
                    "actual": "aborted",
                    "limit": "跑完",
                    "ok": False,
                    "why": f"这一组没能开跑：{summary['aborted']}",
                }
            ],
        }
    workers = int(summary.get("n_workers") or 0) or 1
    peak = float(summary.get("peak_total_mb") or 0.0)
    per_worker = float(summary.get("per_worker_peak_mb") or 0.0)
    checks = [
        {
            "name": "per_worker_peak_mb",
            "actual": per_worker,
            "limit": BUDGET_PER_WORKER_MB,
            "ok": per_worker <= BUDGET_PER_WORKER_MB,
            "why": "每 worker 峰值（OS 高水位）≤ X",
        },
        {
            "name": "peak_total_mb",
            "actual": peak,
            "limit": budget_for(workers),
            "ok": peak <= budget_for(workers),
            "why": f"整套峰值 ≤ 1024 + {workers}×{BUDGET_PER_WORKER_MB:.0f}",
        },
        {
            "name": "exit_code",
            "actual": summary.get("exit_code"),
            "limit": 0,
            "ok": summary.get("exit_code") == 0,
            "why": "被测命令必须整体通过",
        },
    ]
    if min_passed is not None:
        actual = int((summary.get("counts") or {}).get("passed") or 0)
        checks.append(
            {
                "name": "passed",
                "actual": actual,
                "limit": min_passed,
                "ok": actual >= min_passed,
                "why": "用例数不得减少（不许靠少跑用例省内存）",
            }
        )
    return {
        "tag": summary.get("tag"),
        "workers": workers,
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
    }


def cmd_check(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    if not index_path.is_file():
        print(f"[mem] 缺索引：{index_path}", file=sys.stderr)
        return 2
    index = json.loads(index_path.read_text(encoding="utf-8"))
    reference: dict[str, Any] = {}
    if args.reference:
        ref_path = Path(args.reference)
        if not ref_path.is_file():
            print(f"[mem] 缺参考索引：{ref_path}", file=sys.stderr)
            return 2
        reference = {
            g["tag"]: g for g in json.loads(ref_path.read_text(encoding="utf-8"))["groups"]
        }

    verdicts = []
    for group in index["groups"]:
        min_passed = None
        if group["tag"] in reference:
            min_passed = int((reference[group["tag"]].get("counts") or {}).get("passed") or 0)
        verdict = judge(group, min_passed=min_passed)
        verdicts.append(verdict)
        flag = _mark("✅", "[OK]") if verdict["ok"] else _mark("❌", "[NG]")
        print(
            f"{flag} {group['tag']}: 每 worker {verdict['checks'][0]['actual']}MB"
            f"/{verdict['checks'][0]['limit']:.0f}MB，整套 {verdict['checks'][1]['actual']}MB"
            f"/{verdict['checks'][1]['limit']:.0f}MB（n={verdict['workers']}）"
            + (f"，用例 {verdict['checks'][-1]['actual']}" if min_passed is not None else "")
        )
        for check in verdict["checks"]:
            if not check["ok"]:
                print(
                    f"   {_mark('↳', '->')} {check['name']}={check['actual']} > {check['limit']} （{check['why']}）"
                )
    ok = all(v["ok"] for v in verdicts) and bool(verdicts)
    print(f"[mem] 预算判决：{'达标' if ok else '不达标'}（索引 {index_path}）")
    return 0 if ok else 1


def cmd_compare(args: argparse.Namespace) -> int:
    """把「修复后」的索引与**冻结基线**逐组比，并按三层判据给判决。

    三层判据（队长 2026-09-25 裁定，本命令是实现）：

    * **第一层（主判据）**：同一命令下整套峰值相对冻结基线里**完整跑完**的那组
      下降 ≥30%，且退出码 0、用例数不减；
    * **第二层（子目标）**：``pdx.cache`` 的分片视图常驻 ≤ 512 MiB
      （读 ``shards_each.json`` 的 ``total_resident_mb``）；
    * **第三层（瞬态，只要求量准）**：单文件解析尖峰由 ``biggest.json`` 钉到具体文件；
    * **第四层（记账）**：任何一层没过，都要把「旧判据未达标」与新地板数字一起留档。
    """
    index_path = Path(args.index)
    ref_path = Path(args.reference)
    if not index_path.is_file() or not ref_path.is_file():
        print(f"[mem] 缺索引：{index_path} / {ref_path}", file=sys.stderr)
        return 2
    current = {g["tag"]: g for g in json.loads(index_path.read_text(encoding="utf-8"))["groups"]}
    reference = {g["tag"]: g for g in json.loads(ref_path.read_text(encoding="utf-8"))["groups"]}

    rows: list[dict[str, Any]] = []
    layer1: list[dict[str, Any]] = []
    for tag, cur in current.items():
        base = reference.get(tag, {})
        cur_peak = float(cur.get("peak_total_mb") or 0.0)
        base_peak = float(base.get("peak_total_mb") or 0.0)
        drop = round((base_peak - cur_peak) / base_peak * 100, 1) if base_peak else None
        # 「完整跑完」= 没被看门狗中止 且 有计数 —— **不是**「退出码为 0」：
        # 合约②那组（`V3_PARSE_CACHE=0`）本来就必然红 7 条磁盘层用例，
        # 拿 0 当「完整」的门槛会把唯一可用的参考组排除在外（本轮实测踩过）。
        complete = bool(base) and not base.get("killed_by_watchdog") and bool(base.get("counts"))
        rows.append(
            {
                "tag": tag,
                "base_peak_mb": base_peak,
                "base_per_worker_mb": base.get("per_worker_peak_mb"),
                "base_complete": complete,
                "new_peak_mb": cur_peak,
                "new_per_worker_mb": cur.get("per_worker_peak_mb"),
                "drop_percent": drop,
                "new_exit": cur.get("exit_code"),
                "new_passed": (cur.get("counts") or {}).get("passed"),
                "base_passed": (base.get("counts") or {}).get("passed"),
                "new_killed": bool(cur.get("killed_by_watchdog")),
                "new_worker_pids": cur.get("worker_pids"),
            }
        )
        if complete:
            # 正确性判据 = **相对参考组不退化**，不是「退出码必须是 0」：
            # 参考组自己就可能是 1（合约②那组带 `V3_PARSE_CACHE=0` 跑，7 条磁盘层
            # 用例必然红）—— 拿 0 当门槛会把「本来就不可能绿」的组判红，
            # 那是判据写错，不是被测对象错。
            layer1.append(
                {
                    "tag": tag,
                    "drop_percent": drop,
                    "ref_exit": base.get("exit_code"),
                    "new_exit": cur.get("exit_code"),
                    "ref_passed": (base.get("counts") or {}).get("passed"),
                    "new_passed": (cur.get("counts") or {}).get("passed"),
                    "ok": bool(drop is not None and drop >= 30.0)
                    and not cur.get("killed_by_watchdog")
                    and (cur.get("exit_code") == 0 or cur.get("exit_code") == base.get("exit_code"))
                    and int((cur.get("counts") or {}).get("passed") or 0)
                    >= int((base.get("counts") or {}).get("passed") or 0),
                }
            )

    print(
        f"{'组':<14}{'基线整套':>10}{'修复后整套':>12}{'降幅':>9}{'基线/修复后每 worker':>24}  退出"
    )
    for row in rows:
        flag = "" if row["base_complete"] else "（参考组未跑完）"
        print(
            f"{row['tag']:<14}{row['base_peak_mb']:>10.1f}{row['new_peak_mb']:>12.1f}"
            f"{(str(row['drop_percent']) + '%'):>9}"
            f"{str(row['base_per_worker_mb']) + ' / ' + str(row['new_per_worker_mb']):>24}"
            f"  {row['new_exit']}{flag}"
        )
    print(f"  修复后 worker pid：{ {r['tag']: r['new_worker_pids'] for r in rows} }")

    shards = OUT_DIR / "shards_each.json"
    layer2_ok = False
    if shards.is_file():
        payload = json.loads(shards.read_text(encoding="utf-8"))
        resident = float(payload.get("total_resident_mb") or 0.0)
        layer2_ok = resident <= BUDGET_PER_WORKER_MB
        print(
            f"第二层：分片视图常驻 {resident} MB ≤ {BUDGET_PER_WORKER_MB:.0f} MiB ？ "
            f"{_mark('✅', '[OK]') if layer2_ok else _mark('❌', '[NG]')}（布局 {payload.get('layout')}）"
        )
    else:
        print("第二层：缺 shards_each.json（跑 `one shards_each` 后再看）")

    biggest = OUT_DIR / "biggest.json"
    layer3_note = "缺 biggest.json（跑 `one biggest` 后再看）"
    if biggest.is_file():
        payload = json.loads(biggest.read_text(encoding="utf-8"))
        top = (payload.get("top") or [{}])[0]
        layer3_note = (
            f"最大单文件高水位 +{top.get('raised_mb')} MB "
            f"（{top.get('size_mb')} MB 的 {Path(str(top.get('file'))).name}）；"
            f"刷新过高水位的文件共 {payload.get('raised_count')} 个"
        )
    print(f"第三层：{layer3_note}")

    ok = bool(layer1) and all(item["ok"] for item in layer1) and layer2_ok
    verdict = {
        "layer1_relative_drop_ge_30": layer1,
        "layer2_shard_view_le_budget": layer2_ok,
        "layer3_transient_note": layer3_note,
        "ok": ok,
    }
    (OUT_DIR / "compare.json").write_text(
        json.dumps(
            {
                "generated_at": _now_iso(),
                "index": str(index_path),
                "reference": str(ref_path),
                "rows": rows,
                "verdict": verdict,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(f"[mem] 三层判据：{'达标' if ok else '不达标'}（明细 -> {OUT_DIR / 'compare.json'}）")
    return 0 if ok else 1


# ────────────────────────── 组件单点复算 ──────────────────────────
#
# 「哪些组件吃得最多」不能靠猜。这里把「一个 worker 的一生」拆成若干步，
# 每步是一个可以单独跑一遍的进程：命令就是证据，数字可以逐条复算。

_STEP_ROWS: list[dict[str, Any]] = []
_STEP_T0 = time.time()
#: 本进程**真正开始跑测量**的时刻（``cmd_one`` 里重新求值）。
#: 与 ``_now_iso()`` 在收尾时求值不同 —— 那个是结束时刻（踩过这个坑）。
_STARTED_AT = _now_iso()


def _self_read() -> tuple[float, float, float]:
    row = MemReader().read(os.getpid())
    if row is None:  # pragma: no cover - 本进程必然读得到
        raise SystemExit("[mem] 读不到自己的内存计数器")
    rss, hwm, private = row
    return _mb(rss), _mb(hwm or rss), _mb(private or 0)


def step(label: str, *, note: str = "", size_of: object = None) -> dict[str, Any]:
    rss, hwm, private = _self_read()
    prev = _STEP_ROWS[-1]["ws_mb"] if _STEP_ROWS else rss
    row: dict[str, Any] = {
        "step": label,
        "t_s": round(time.time() - _STEP_T0, 2),
        "ws_mb": rss,
        "peak_mb": hwm,
        "private_mb": private,
        "d_ws_mb": round(rss - prev, 1),
        "note": note,
    }
    if size_of is not None:
        row["deep_mb"] = deep_size(size_of)
    _STEP_ROWS.append(row)
    print(
        f"STEP {label}: ws={rss}MB (Δ{row['d_ws_mb']:+}) peak={hwm}MB private={private}MB"
        f" t={row['t_s']}s {note}",
        flush=True,
    )
    return row


def released(label: str, note: str) -> dict[str, Any]:
    gc.collect()
    return step(label, note=note)


# ── 可选择性实验：一边跑一边把「保留层」清掉 ─────────────────────
#
# 清记忆化缓存**不改变任何计算结果**（pdx.cache 的模块文档与 test_cache.py
# 的逐字段等价用例都钉着这条），改变的只是「同一份字节从哪一层来」。所以
# 「清掉之后峰值是多少」就是这条路径的**内存下界**，也是 §5 预算可达性的证据：
# 它回答的是「如果把永久保留改成有界/按需，能降到多少」，而不是在改产品代码。

_JANITOR = {"evictions": 0, "stop": threading.Event(), "thread": None}


def start_janitor(interval_s: float) -> None:
    """起一个后台线程：每 ``interval_s`` 秒清一次两种保留层（并计数）。"""
    if interval_s <= 0:
        return
    _add_pdx_path()
    from pdx import cache  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    def loop() -> None:
        while not _JANITOR["stop"].wait(interval_s):
            cache._parse_by_key.cache_clear()
            _clear_retention(cache)
            _JANITOR["evictions"] += 1

    thread = threading.Thread(target=loop, name="mb-janitor", daemon=True)
    _JANITOR["thread"] = thread
    thread.start()


def stop_janitor() -> int:
    _JANITOR["stop"].set()
    thread = _JANITOR["thread"]
    if thread is not None:
        thread.join(timeout=2.0)
    return int(_JANITOR["evictions"])


#: ``sys.getsizeof`` 递归求和的节点上限（防跑飞，只走容器 / __dict__ / dataclass）。
_DEEP_MAX_NODES = 2_000_000


def deep_size(obj: object) -> float:
    seen: set[int] = set()
    keep: list[object] = []  # 防 id 复用
    total = 0
    stack: list[object] = [obj]
    while stack and len(keep) < _DEEP_MAX_NODES:
        item = stack.pop()
        oid = id(item)
        if oid in seen:
            continue
        seen.add(oid)
        keep.append(item)
        try:
            total += sys.getsizeof(item)
        except TypeError:
            continue
        if isinstance(item, (list, tuple, set, frozenset)):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (str, bytes, bytearray, int, float, bool, type(None))):
            continue
        elif hasattr(item, "__dict__"):
            stack.append(item.__dict__)
        elif hasattr(item, "__dataclass_fields__"):
            stack.extend(getattr(item, field, None) for field in item.__dataclass_fields__)
    return _mb(total)


def _add_pdx_path() -> None:
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)


def corpus_files() -> list[Path]:
    # 延迟导入 pdx：本模块同时是 pytest 插件（每个 worker 都会 import 它），
    # 插件路径上不该顺带把 pdx 及其依赖拉起来 —— 那会污染被测量的内存。
    _add_pdx_path()
    from pdx import config as pdx_config  # noqa: PLC0415 - 见上：延迟导入
    from pdx.scan import walk_files  # noqa: PLC0415 - 见上：延迟导入

    out: list[Path] = []
    for root in (pdx_config.GAME, pdx_config.JOMINI, pdx_config.CLAUSEWITZ):
        if not root.is_dir():
            continue
        for found in walk_files(root):
            try:
                rel = found.path.relative_to(root)
            except ValueError:
                continue
            if pdx_config.is_scriptable(rel.parts, found.suffix):
                out.append(found.path)
    return sorted(out)


def corpus_texts(files: list[Path]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in files:
        try:
            out.append((str(path), path.read_text(encoding="utf-8-sig", errors="replace")))
        except OSError:
            continue
    return out


def step_one(
    which: str, *, evict_every: int, evict_what: str = "both", files_limit: int = 0
) -> int:
    step("startup", note="解释器 + 标准库")
    _add_pdx_path()

    if which == "shards_each":
        return _step_shards_each()

    if which == "invariant":
        return _step_invariant(files_limit)

    if which == "index-audit":
        return _step_index_audit(sample=files_limit or 20)

    if which == "biggest":
        files = corpus_files()
        return _step_biggest(files if not files_limit else files[:files_limit], top=8)

    if which == "layers":
        return _step_layers(corpus_files())

    if which in {"retain", "drop"}:
        return _step_parse_each(corpus_files(), keep=(which == "retain"))

    if which in {"corpus_files", "corpus_texts", "parse_all", "shards_touch", "stream"}:
        files = corpus_files()
        step(
            "corpus_files",
            note=f"{len(files)} 个待解析路径（session 夹具 corpus_files）",
            size_of=files,
        )
        if which == "corpus_files":
            return 0
        if which == "corpus_texts":
            texts = corpus_texts(files)
            step(
                "corpus_texts",
                note=f"{len(texts)} 条正文（session 夹具 corpus_texts）",
                size_of=texts,
            )
            return 0
        if which == "shards_touch":
            from pdx import cache  # noqa: PLC0415 - 延迟导入（见 corpus_files）

            picked: dict[int, str] = {}
            for path in files:
                index = cache._shard_of(str(path))
                picked.setdefault(index, str(path))
                if len(picked) >= cache.SHARDS:
                    break
            for path in picked.values():
                cache.parse_cached(path)
            step(
                "shards_touch",
                note=f"只解析 {len(picked)} 个文件（每个分片 1 个）→ 分片视图 {cache.SHARDS} 片",
            )
            return 0
        return _step_parse_all(files, evict_every=evict_every, evict_what=evict_what)

    if which in {"import:pytest", "import:pdx", "import:heavy", "imports"}:
        steps = {
            "import:pytest": ["pytest"],
            "import:pdx": ["pdx", "pdx.analyze", "pdx.verify", "pdx.cache"],
            "import:heavy": ["numpy", "PIL", "cv2"],
        }
        names = steps.get(which) or [
            "pytest",
            "pdx",
            "pdx.analyze",
            "pdx.verify",
            "pdx.cache",
            "numpy",
            "PIL",
            "cv2",
        ]
        for name in names:
            __import__(name)
            step(f"import:{name}", note="import 的常驻代价（RSS，不是 commit）", size_of=None)
        return 0

    if which in {"ga", "ma", "ca", "compact_snapshot", "full_snapshot", "chain"}:
        return _step_analysis(which)

    print(f"[mem] 未知步骤 {which}（用 --list 看清单）", file=sys.stderr)
    return 2


def _step_shards_each() -> int:
    """逐片量「内存里到底留了多少」—— 组件排名第一名的证据 + 修复后的第二层判据。

    两种布局都能跑（这是刻意的：修复前后要拿同一把尺子量）：

    * **v1**（2026-09-25 之前）：``_load_shard()`` 把**整片条目**反序列化并永久留下 ——
      16 片被碰过就是 20,595 条 / **2402.5 MB**；
    * **v2**（修复后）：内存里只有 ``shard-NN.idx`` 的**偏移索引**（每片 0.1 MB 量级），
      条目按偏移单条取、取完不留。

    产物里带 ``layout`` 字段标明量的是哪一种，免得两个数被混着引用。
    """
    from pdx import cache  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    has_v1 = hasattr(cache, "_load_shard") and hasattr(cache._state, "shards")
    has_v2 = hasattr(cache._state, "indexes")
    layout = "v1（整片常驻）" if has_v1 else ("v2（索引 + 按需单条取）" if has_v2 else "未知")

    rows: list[dict[str, Any]] = []
    for index in range(cache.SHARDS):
        rss0 = _self_read()[0]
        if has_v1:
            entries = cache._load_shard(index)  # 探针要看的就是这一层
            count = len(entries)
        else:
            index_entries = cache._load_index(index)
            count = len(index_entries)
            # 顺手真读一条：证明「按需单条取」这条路是通的（读一条也不留片）
            if index_entries:
                sig = next(iter(index_entries))
                cache._read_entry(index, index_entries[sig], sig)
        rss1 = _self_read()[0]
        data = cache._shard_path(index)
        index_file = cache._index_path(index) if has_v2 else None
        disk = (data.stat().st_size if data.is_file() else 0) + (
            index_file.stat().st_size if index_file is not None and index_file.is_file() else 0
        )
        rows.append(
            {
                "shard": index,
                "entries": count,
                "disk_kb": round(disk / 1024, 1),
                "d_rss_mb": round(rss1 - rss0, 1),
                "rss_mb": rss1,
                "mb_per_entry": round((rss1 - rss0) / (count or 1), 4),
            }
        )
        print(
            f"SHARD {index:02d}: entries={count} disk={rows[-1]['disk_kb']}KB "
            f"Δrss={rows[-1]['d_rss_mb']}MB（{rows[-1]['mb_per_entry']} MB/条）",
            flush=True,
        )
    step(
        "shards_each",
        note=f"{layout}：{len(rows)} 片处理完（{sum(r['entries'] for r in rows)} 条）",
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _now_iso(),
        "layout": layout,
        "shards": cache.SHARDS,
        "cache_dir": str(cache.cache_dir()),
        "rows": rows,
        "total_entries": sum(r["entries"] for r in rows),
        "total_disk_mb": round(sum(r["disk_kb"] for r in rows) / 1024, 2),
        "total_resident_mb": round(sum(r["d_rss_mb"] for r in rows), 1),
    }
    (OUT_DIR / "shards_each.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(
        f"[mem] shards_each（{layout}）：{payload['total_entries']} 条 / 磁盘 "
        f"{payload['total_disk_mb']}MB → 常驻 {payload['total_resident_mb']}MB",
        flush=True,
    )
    return 0


def _step_invariant(limit: int) -> int:
    """缓存不变量检查（`tools/reports/内存优化复核.md` §一–§六 的可执行版本）。

    四项判据，任一项不过即红（退出码 1）：

    1. **深度结构等价**：同一批文件，「全新解析」与「走缓存」两棵树的逐节点
       形状 + 内容指纹必须完全一致；
    2. **类身份**：缓存树里每个节点都必须是 ``type(node) is Scalar/Assignment/Block``
       —— 用 ``type(x) is C`` 而**不是** ``isinstance``（身份错位时 ``isinstance``
       正是那个静默返回假的东西，用它写检查，检查会和被测对象一起失效）；
    3. **行号保真**：``Scalar.line`` / ``Block.line`` 一致；
    4. **引号标记保真**：``Scalar.quoted`` 一致。

    「全新解析」必须**绕过两层缓存**（直接调 ``cache._parse_file``，原名 ``parse_file``），
    否则两边读的是同一份缓存、比对恒真。
    """
    import hashlib as _hashlib  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    from pdx import cache  # noqa: PLC0415
    from pdx.model import Assignment as _Assignment  # noqa: PLC0415
    from pdx.model import Block as _Block  # noqa: PLC0415
    from pdx.model import Scalar as _Scalar  # noqa: PLC0415

    _add_pdx_path()
    from pdx import config as pdx_config  # noqa: PLC0415

    common = pdx_config.GAME / "common"
    files = sorted(common.rglob("*.txt"))[:limit] if common.is_dir() else []
    if not files:
        print(f"[mem] 语料不可用：{common}", file=sys.stderr)
        return 2

    mismatches: list[str] = []
    foreign: list[str] = []

    def fingerprint(tree: object) -> tuple[str, int, int]:
        parts: list[str] = []
        nodes = 0
        for top in tree.top_assignments:  # type: ignore[attr-defined]
            parts.append(f"A|{top.key}")
            nodes += 1
            stack = [top.value]
            while stack:
                node = stack.pop()
                if node is None:
                    continue
                nodes += 1
                if type(node) is _Scalar:
                    parts.append(f"S{int(node.quoted)}|{node.line}|{node.text}")
                elif type(node) is _Block:
                    parts.append(f"B|{node.line}")
                    stack.extend(node.items)
                elif type(node) is _Assignment:
                    parts.append(f"A|{node.key}")
                else:  # 外来类：记下来（这就是那个静默失效的形态）
                    foreign.append(f"{type(node).__module__}.{type(node).__qualname__}")
        digest = _hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
        return digest, nodes, int(getattr(tree, "had_bom", 0))

    for path in files:
        direct = cache._parse_file(str(path))
        cached = cache.parse_cached(str(path))
        if fingerprint(direct) != fingerprint(cached):
            mismatches.append(str(path))

    ok = not mismatches and not foreign
    print(
        f"[mem] 不变量检查：corpus {len(files)} files（{common} 的前 {limit} 个）"
        f"mismatches {len(mismatches)}   foreign-class {len(foreign)}"
        f"memo entries={cache.stats()['条目']}",
        flush=True,
    )
    for path in mismatches[:10]:
        print(f"  MISMATCH {path}", flush=True)
    for name in sorted(set(foreign))[:10]:
        print(f"  FOREIGN-CLASS {name}", flush=True)
    step(
        "invariant",
        note=f"语料 {len(files)}；mismatches={len(mismatches)}；foreign-class={len(foreign)}",
    )
    return 0 if ok else 1


def _step_biggest(files: list[Path], *, top: int) -> int:
    """逐文件记录**高水位是否被刷新**，把「单文件解析放大」钉到具体文件。

    t11 发现了一个 ~450× 的瞬态（2.47 MB 的文件解析一次瞬态要 ~1.1 GB），
    但当时只能给到「3001–4000 区间」+「该区间最大文件 2.47 MB」两条旁证。
    本命令把它钉死：用 ``parse_file``（绕开缓存，与两臂同口径）逐文件解析，
    每解析一个读一次本进程的 OS 高水位（单调不减）——

    * **高水位被刷新过** ⇒ 这个文件就是尖峰候选（记下它刷到多少）；
    * 全程没刷新 ⇒ 该文件与尖峰无关。

    判据落在 **D1 = 首次把高水位顶过 512 MiB / 1 GiB 的文件**上，
    并给出「孤例还是一族」（候选文件的个数与它们的规模分布）。
    """
    from pdx.parser import parse_file  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    threshold = 512.0  # MiB：与每 worker 预算同一量级，用来判「谁顶破了预算」
    rows: list[dict[str, Any]] = []
    first_over: dict[str, Any] = {}
    for index, path in enumerate(files):
        before = _self_read()[1]
        tree = parse_file(path)
        after = _self_read()[1]
        del tree
        size_mb = round(path.stat().st_size / 1048576, 3)
        if after > before:
            rows.append(
                {
                    "index": index,
                    "file": str(path),
                    "size_mb": size_mb,
                    "peak_before_mb": before,
                    "peak_after_mb": after,
                    "raised_mb": round(after - before, 1),
                }
            )
            if after >= threshold and "over512" not in first_over:
                first_over["over512"] = rows[-1]
            if after >= 1024 and "over1024" not in first_over:
                first_over["over1024"] = rows[-1]
    peak = _self_read()[1]
    ranked = sorted(rows, key=lambda r: -r["raised_mb"])
    print(
        f"[mem] biggest：解析 {len(files)} 个文件，其中 {len(rows)} 个刷过新高水位，进程峰值 {peak} MB"
    )
    for row in ranked[:top]:
        print(
            f"  idx={row['index']:5d} {row['size_mb']:6.2f}MB → 高水位 {row['peak_before_mb']}→"
            f"{row['peak_after_mb']}MB（+{row['raised_mb']}） {Path(row['file']).name}",
            flush=True,
        )
    for key, row in first_over.items():
        print(f"  首次越过 {key}: idx={row['index']} size={row['size_mb']}MB {row['file']}")
    step(
        "biggest",
        note=(
            f"解析 {len(files)} 个；刷新高水位的 {len(rows)} 个；"
            f"首次越过 512MiB 的文件 idx={first_over.get('over512', {}).get('index')}"
        ),
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _now_iso(),
        "files": len(files),
        "process_peak_mb": peak,
        "raised_count": len(rows),
        "first_over_512mb": first_over.get("over512"),
        "first_over_1024mb": first_over.get("over1024"),
        "top": ranked[: max(top, 20)],
    }
    (OUT_DIR / "biggest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return 0


def _clear_retention(cache: Any) -> None:
    """清掉缓存模块**当前布局**下的进程内保留（探针用；v1 与 v2 都能跑）。

    v1：``_state.shards``（整片常驻）→ 清它。
    v2：``_state.pending``（待落盘）+ ``_state.indexes``（偏移索引，很小）→ 清两者。
    """
    state = getattr(cache, "_state", None)
    for attr in ("shards", "pending", "indexes"):
        holder = getattr(state, attr, None)
        if isinstance(holder, dict):
            holder.clear()


def _retention_note(cache: Any) -> str:
    """一句话说清「当前内存里留了多少」（两种布局各自可读）。"""
    state = getattr(cache, "_state", None)
    shards = getattr(state, "shards", None)
    if isinstance(shards, dict):
        return f"分片常驻={len(shards)} 片（v1 整片布局）"
    pending = getattr(state, "pending", None) or {}
    indexes = getattr(state, "indexes", None) or {}
    return (
        f"待落盘={sum(len(chunk) for chunk in pending.values())} 条，"
        f"索引={len(indexes)} 片（v2 按需布局）"
    )


def _tree_fingerprint(tree: Any, foreign: list[str] | None = None) -> tuple[str, int]:
    """把「深度结构 + 类身份 + 行号 + 引号标记」压成一条指纹（§二 的四项判据）。

    ``foreign`` 非空时，遇到**不是本模块那三个类**的节点会把类名记进去
    —— 判身份用 ``type(x) is C`` 而**不是** ``isinstance``：身份错位时
    ``isinstance`` 正是那个静默返回假的东西，用它写检查，检查会和被测对象一起失效。
    """
    import hashlib as _hashlib  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    from pdx.model import Assignment as _Assignment  # noqa: PLC0415
    from pdx.model import Block as _Block  # noqa: PLC0415
    from pdx.model import Scalar as _Scalar  # noqa: PLC0415

    parts: list[str] = []
    nodes = 0
    for top in tree.top_assignments:
        parts.append(f"A|{top.key}")
        nodes += 1
        stack = [top.value]
        while stack:
            node = stack.pop()
            if node is None:
                continue
            nodes += 1
            if type(node) is _Scalar:
                parts.append(f"S{int(node.quoted)}|{node.line}|{node.text}")
            elif type(node) is _Block:
                parts.append(f"B|{node.line}")
                stack.extend(node.items)
            elif type(node) is _Assignment:
                parts.append(f"A|{node.key}")
            elif foreign is not None:
                foreign.append(f"{type(node).__module__}.{type(node).__qualname__}")
    digest = _hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return digest, nodes


def _step_index_audit(sample: int) -> int:
    """索引审计：**总条目 / 其中多少条对应现役语料 / 抽样按索引取回是否等价**。

    这条命令回的是「重建后的索引有没有丢条目」这类疑问 —— 它是**只变慢不变错**的
    失效形态（套件照样绿），所以必须单独量：

    * ``磁盘条目总数``：16 片索引加起来多少条；
    * ``现役条目``：这 6,252 个待解析路径里，有多少条的**当前指纹**就在索引里；
      差集 = **过期条目**（路径改过名、文件改过内容、引擎/布局指纹变过）——
      它们永远命中不了，只是占地方，``MAX_ENTRIES_PER_SHARD`` 会在下次写这片时瘦身掉；
    * ``抽样等价``：随机抽 ``sample`` 条现役指纹，按索引 ``_read_entry`` 取回来，
      与**直接解析**（绕开两层缓存）逐节点比对指纹。
    """
    import random  # noqa: PLC0415 - 延迟导入

    from pdx import cache  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    files = corpus_files()
    per_shard = {index: cache._load_index(index) for index in range(cache.SHARDS)}
    total = sum(len(chunk) for chunk in per_shard.values())

    live: list[tuple[Path, int, str]] = []
    for path in files:
        sig = cache._signature(str(path))
        if sig is None:
            continue
        shard = cache._shard_of(str(path))
        if sig in per_shard.get(shard, {}):
            live.append((path, shard, sig))

    rng = random.Random(20260925)
    picked = rng.sample(live, min(sample, len(live)))
    foreign: list[str] = []
    mismatch: list[str] = []
    for path, shard, sig in picked:
        got = cache._read_entry(shard, per_shard[shard][sig], sig)
        if got is None:
            mismatch.append(f"{path}（索引有、取不回来）")
            continue
        direct = cache._parse_file(str(path))
        if _tree_fingerprint(got, foreign) != _tree_fingerprint(direct, foreign):
            mismatch.append(str(path))

    print(
        f"[mem] 索引审计：磁盘条目 {total}；现役 {len(live)} / 语料 {len(files)}；"
        f"过期 {total - len(live)}；抽样 {len(picked)} 条 → 不一致 {len(mismatch)}、"
        f"外来类 {len(foreign)}",
        flush=True,
    )
    for row in mismatch[:10]:
        print(f"  MISMATCH {row}", flush=True)
    step(
        "index_audit",
        note=(
            f"条目 {total}（现役 {len(live)} / 过期 {total - len(live)}）；"
            f"抽样 {len(picked)} 条不一致 {len(mismatch)}"
        ),
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index_audit.json").write_text(
        json.dumps(
            {
                "generated_at": _now_iso(),
                "corpus_files": len(files),
                "disk_entries": total,
                "live_entries": len(live),
                "stale_entries": total - len(live),
                "sampled": len(picked),
                "mismatches": mismatch,
                "foreign_class": sorted(set(foreign)),
                "per_shard": {str(k): len(v) for k, v in sorted(per_shard.items())},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return 0 if not mismatch and not foreign else 1


def _step_parse_all(files: list[Path], *, evict_every: int, evict_what: str) -> int:
    from pdx import cache  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    peak_before = _self_read()[1]
    for index, path in enumerate(files, 1):
        cache.parse_cached(path)
        if evict_every and index % evict_every == 0:
            # 按层分别淘汰：这两层在「命中磁盘的那条」上是**同一个对象**
            # （`_disk_load` 返回的就是分片字典里那个 ParsedFile，memo 只是留了引用），
            # 所以「只清 memo」几乎不省内存，而「只清分片视图」会把**没被请求过的**
            # 那部分（20,595 条里的大头）放掉。分开测才能分清是谁。
            if evict_what in {"both", "memo"}:
                cache._parse_by_key.cache_clear()
            if evict_what in {"both", "shards"}:
                _clear_retention(cache)
    note = (
        f"全语料 {len(files)} 个文件，内存缓存条目={cache.stats()['条目']}"
        f"，分片常驻={_retention_note(cache)}"
    )
    if evict_every:
        note += f"（每 {evict_every} 个文件淘汰一次：{evict_what}）"
    step("parse_all", note=note)
    print(f"[mem] parse_all 起始峰值={peak_before}MB", flush=True)
    return 0


#: 两臂实验的计数（`one retain` / `one drop`）—— 必须进产物，否则又是不可复算的对照。
_ARM: dict[str, Any] = {"files": 0, "kept": 0, "dropped": 0, "last_deep_mb": 0.0}


def _step_parse_each(files: list[Path], *, keep: bool) -> int:
    """两臂对照：**同一份语料、同一个脚本、各自独立进程**，只差「留不留结果」。

    为什么必须两臂、且必须**各起一个进程**：`--evict-every 200` 那一步只证明了
    「驱逐对这种 RSS 无效」，证明不了「2.38 GB 是不可删的地板」—— 要把它当地板，
    至少还差两支：① 分配器有没有把 free 归还 OS（freed-but-retained）；
    ② 解析结果的**表示本身**是不是就这么大。这是「用一次实验推翻一个判据」的坑。

    读法（两臂都走 `pdx.parser.parse_file`，**绕过两层缓存**，唯一差别是留不留）：

    * 两臂峰值**都**停在 ~2.4 GB ⇒ 是表示 / 分配器的开销（地板比 2.4 GB 低）；
    * 「用完即丢」那臂落到几百 MB ⇒ 那 2.4 GB 是**真被持有的结果**（地板成立）。

    若两臂跑在**同一个解释器**里，B 臂会继承 A 臂的堆高水位，两支就分不开了 ——
    所以本函数一次只跑一臂，两臂由调用方各起一个进程。
    """
    from pdx.parser import parse_file  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    holder: list[object] = []
    kept = dropped = 0
    last_deep = 0.0
    for index, path in enumerate(files, 1):
        tree = parse_file(path)
        if keep:
            holder.append(tree)
            kept += 1
        else:
            last_deep = deep_size(tree)  # 量一棵：表示本身多大（用完就丢）
            del tree
            dropped += 1
        if index % 1000 == 0:
            step(f"progress:{index}", note=f"已解析 {index}，留 {kept} / 丢 {dropped}")
    gc.collect()
    _ARM.update({"files": len(files), "kept": kept, "dropped": dropped, "last_deep_mb": last_deep})
    step(
        "end",
        note=(
            f"解析 {len(files)} 个：留 {kept} / 丢 {dropped}（单个文件的表示 deep={last_deep} MB）"
        ),
    )
    print(
        f"[mem] 两臂之一：keep={keep} 解析={len(files)} 留={kept} 丢={dropped} "
        f"last_deep={last_deep}MB 峰值={_self_read()[1]}MB",
        flush=True,
    )
    return 0


def _step_layers(files: list[Path]) -> int:
    """把「一次全语料解析」的常驻量**按层拆开**：分片视图 vs memo 层。

    做法与上一轮的分步探针一致（先清分片、再清 memo），但补上了两个关键计数：

    * ``memo 条目`` = ``cache.stats()['条目']``（被**请求过**的文件数）；
    * ``分片常驻`` = 被**装进内存**的片数/条目数（两种布局都能报，见 :func:`_retention_note`）。

    两个数一起看才知道「2.4 GB 是谁的」：分片视图装的是**整片**（约 1,300 条/片），
    其中只有被请求过的那部分同时被 memo 引用。清分片省下的是「没被请求的绝大多数」，
    清 memo 省下的只是「被请求的那一小撮」—— 这正是「查一条、付一片」的代价。
    """
    from pdx import cache  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    for path in files:
        cache.parse_cached(path)
    step(
        "parse_all",
        note=(
            f"memo 条目={cache.stats()['条目']}，{_retention_note(cache)}"
            f"（缓存统计 命中/未命中={cache.stats()['命中']}/{cache.stats()['未命中']}）"
        ),
    )
    _clear_retention(cache)
    released("clear_shards_only", "只清分片视图（memo 仍引用它请求过的那几条）")
    cache._parse_by_key.cache_clear()
    released("clear_memo_only", "只清 memo 层（此时两层都空）")
    return 0


def _step_analysis(which: str) -> int:
    _add_pdx_path()
    from pdx import analyze, cache, snapshot, verify  # noqa: PLC0415 - 延迟导入（见 corpus_files）

    if which == "compact_snapshot":
        snap = verify.latest_compact_snapshot()
        step(
            "compact_snapshot",
            note=f"verify.latest_compact_snapshot() 命中={snap is not None}",
            size_of=snap,
        )
        return 0
    if which == "full_snapshot":
        paths = sorted(
            x
            for x in (REPO / "tools" / "out" / "snapshots").glob("*.json")
            if "compact" not in x.name
        )
        if not paths:
            step("full_snapshot", note="跳过：tools/out/snapshots 下没有全量快照")
            return 0
        data = snapshot.Snapshot.load(paths[0])
        step("full_snapshot", note=paths[0].name, size_of=data)
        return 0

    if which == "chain":
        step("import:pytest", note="pytest 自身（每个 worker 都要付）")
        from pdx import config as pdx_config  # noqa: F401, PLC0415 - 只为量 pdx 的导入代价

        step("import:pdx", note="pdx 包")
        files = corpus_files()
        step("corpus_files", note=f"{len(files)} 个路径（session 夹具）", size_of=files)
        texts = corpus_texts(files)
        step("corpus_texts", note=f"{len(texts)} 条正文（session 夹具）", size_of=texts)
        picked: dict[int, str] = {}
        for path in files:
            index = cache._shard_of(str(path))
            picked.setdefault(index, str(path))
            if len(picked) >= cache.SHARDS:
                break
        for path in picked.values():
            cache.parse_cached(path)
        step("shards_touch", note=f"只解析 {len(picked)} 个文件（每个分片 1 个）")
        _clear_retention(cache)
        cache._parse_by_key.cache_clear()
        released("release_all_ast", "清两层的保留 + gc")
        game = analyze.game_analysis()
        step("game_analysis", note=f"磁盘缓存={cache.describe_state()}", size_of=game)
        _clear_retention(cache)
        cache._parse_by_key.cache_clear()
        released("release_ast_after_ga", "清两层 + gc（只剩分析结果本身）")
        mods = analyze.mods_analysis()
        step("mods_analysis", size_of=mods)
        cross = analyze.cross_analysis(mods)
        step("cross_analysis", size_of=cross)
        del game, mods, cross
        released("release_analysis", "丢掉 ga/ma/ca + gc")
        snap = verify.latest_compact_snapshot()
        step("compact_snapshot", note=f"命中={snap is not None}", size_of=snap)
        paths = sorted(
            x
            for x in (REPO / "tools" / "out" / "snapshots").glob("*.json")
            if "compact" not in x.name
        )
        full = snapshot.Snapshot.load(paths[0]) if paths else None
        step("full_snapshot", note=paths[0].name if paths else "跳过", size_of=full)
        del snap, full, texts
        released("release_snapshots_texts", "丢掉快照与正文 + gc")
        return 0

    if which == "ga":
        holder = analyze.game_analysis()
        step("ga", note="analyze.game_analysis()（session 夹具 ga）", size_of=holder)
        return 0
    if which == "ma":
        holder = analyze.mods_analysis()
        step("ma", note="analyze.mods_analysis()（session 夹具 ma）", size_of=holder)
        return 0
    holder = analyze.mods_analysis()
    step("ma", note="cross_analysis 的输入")
    cross = analyze.cross_analysis(holder)
    step("ca", note="analyze.cross_analysis(ma)（session 夹具 ca）", size_of=cross)
    return 0


def cmd_one(args: argparse.Namespace) -> int:
    global _STEP_T0, _STARTED_AT  # noqa: PLW0603 - 单进程 CLI，重置计时起点
    ensure_quiet(
        quiet_mb=args.quiet_mb,
        min_avail_mb=args.min_avail_mb,
        wait_s=args.wait_quiet_s,
        allow=args.allow_concurrent,
    )
    _STEP_T0 = time.time()
    _STARTED_AT = _now_iso()
    _STEP_ROWS.clear()
    if args.janitor_s > 0:
        start_janitor(args.janitor_s)
        print(
            f"[mem] 可选择性驱逐已开：每 {args.janitor_s}s 清一次两种保留层"
            f"（只丢记忆化，不改变任何计算结果）",
            flush=True,
        )
    try:
        code = step_one(
            args.step,
            evict_every=args.evict_every,
            evict_what=args.evict_what,
            files_limit=args.files,
        )
    finally:
        evictions = stop_janitor()
    if code:
        return code
    if args.janitor_s > 0:
        step("janitor_stop", note=f"整个过程中共驱逐 {evictions} 次（每 {args.janitor_s}s）")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "steps.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "step_mode": args.step,
                    "evict_every": args.evict_every,
                    "janitor_s": args.janitor_s,
                    "evictions": evictions,
                    "evict_what": args.evict_what,
                    "arm_counts": dict(_ARM),
                    # ⚠️ 两个时刻必须分开记：早先只写了一个 ``started_at``，而它是在
                    # **跑完之后**求值的 —— 于是它其实是结束时刻，还让「两臂时间线重叠」
                    # 这种假象出现（实测被队长抓到）。现在起止分开、各自求值。
                    "started_at": _STARTED_AT,
                    "finished_at": _now_iso(),
                    "machine": machine_info(),
                    "concurrent_at_start": foreign_heavy(0.0, ignore={os.getpid()}),
                    "rows": _STEP_ROWS,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    steps_peak = max((row["peak_mb"] for row in _STEP_ROWS), default=0.0)
    print(f"[mem] one {args.step} 峰值={steps_peak}MB → {_short(path)}", flush=True)
    return 0


# ────────────────────────── 逐 worker 归因（--inproc / rank） ──────────────────────────
#
# 这一段同时是 **pytest 插件**（`-p mem_baseline` + MEMBASELINE_OUT）与 **rank 命令**。
# 插件的活是「在每个 pytest 进程里记下它自己走到哪一步、多大」，于是
# 「哪个测试模块把 worker 顶上去」不用靠猜；`rank` 再把它们汇总成一张排名表。

try:  # pragma: no cover - pytest 是 dev 依赖，缺了只是不能 --inproc
    import pytest
except ImportError:  # pragma: no cover
    pytest = None  # type: ignore[assignment]

_INPROC = {
    "tests": [],
    "fixtures": [],
    "phases": [],
    "series": [],
    "counts": {"passed": 0, "failed": 0, "other": 0},
    "errors": [],
}
_INPROC_LOCK = threading.Lock()
_INPROC_STOP = threading.Event()
_INPROC_T0 = time.time()
_INPROC_ACTIVE = bool(os.environ.get("MEMBASELINE_OUT"))


def _inproc_enabled() -> bool:
    return _INPROC_ACTIVE and pytest is not None


def _inproc_snapshot() -> tuple[float, float]:
    rss, hwm, _private = _self_read()
    return rss, hwm


def _inproc_sampler() -> None:  # pragma: no cover - 线程体
    while not _INPROC_STOP.wait(0.5):
        rss, hwm = _inproc_snapshot()
        with _INPROC_LOCK:
            _INPROC["series"].append([round(time.time() - _INPROC_T0, 3), rss, hwm])


def _inproc_phase(name: str, **extra: Any) -> None:
    rss, hwm = _inproc_snapshot()
    with _INPROC_LOCK:
        _INPROC["phases"].append(
            {
                "phase": name,
                "t_s": round(time.time() - _INPROC_T0, 3),
                "ws_mb": rss,
                "peak_mb": hwm,
                **extra,
            }
        )


def _inproc_write(exitstatus: Any) -> Path | None:
    if not _INPROC_ACTIVE:
        return None
    out = Path(os.environ["MEMBASELINE_OUT"])
    out.mkdir(parents=True, exist_ok=True)
    tag = os.environ.get("MEMBASELINE_TAG", "inproc")
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    rss, hwm = _inproc_snapshot()
    payload = {
        "tag": tag,
        "worker": worker,
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "argv": sys.argv[1:],
        "duration_s": round(time.time() - _INPROC_T0, 2),
        "peak_ws_mb": hwm,
        "final_ws_mb": rss,
        "peak_source": MemReader().peak_source,
        "exitstatus": None if exitstatus is None else int(exitstatus),
        "counts": _INPROC["counts"],
        "tests": _INPROC["tests"],
        "fixtures": _INPROC["fixtures"],
        "phases": _INPROC["phases"],
        "series": _INPROC["series"],
        "errors": _INPROC["errors"][:20],
    }
    path = out / f"inproc-{tag}-{worker}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(
        f"INPROC done worker={worker} pid={os.getpid()} peak={hwm}MB final={rss}MB "
        f"dur={payload['duration_s']}s -> {path.name}",
        flush=True,
    )
    return path


# ── pytest 钩子（只有 MEMBASELINE_OUT 存在时才干活）──────────────────


def pytest_configure(config: Any) -> None:  # pragma: no cover - 由 pytest 调用
    del config  # 只为对齐 hookspec 的形参名
    if not _inproc_enabled():
        return
    _inproc_phase("configure")
    threading.Thread(target=_inproc_sampler, name="membaseline-sampler", daemon=True).start()
    rss, hwm = _inproc_snapshot()
    print(
        f"INPROC start tag={os.environ.get('MEMBASELINE_TAG')} "
        f"worker={os.environ.get('PYTEST_XDIST_WORKER', 'master')} pid={os.getpid()} "
        f"ws={rss}MB peak={hwm}MB",
        flush=True,
    )


def pytest_collection_finish(session: Any) -> None:  # pragma: no cover
    if not _inproc_enabled():
        return
    _inproc_phase("collection_finish", collected=len(session.items))


def pytest_runtest_logstart(nodeid: str, location: Any) -> None:  # pragma: no cover
    del location  # 只为对齐 hookspec 的形参名
    if not _inproc_enabled():
        return
    module = nodeid.split("::", 1)[0]
    with _INPROC_LOCK:
        last = _INPROC["phases"][-1] if _INPROC["phases"] else {}
    if last.get("phase") != f"enter:{module}":
        _inproc_phase(f"enter:{module}")


def pytest_runtest_logreport(report: Any) -> None:  # pragma: no cover
    if not _inproc_enabled() or report.when != "call":
        return
    rss, hwm = _inproc_snapshot()
    row = {
        "nodeid": report.nodeid,
        "module": report.nodeid.split("::", 1)[0],
        "outcome": report.outcome,
        "t_s": round(time.time() - _INPROC_T0, 3),
        "ws_mb": rss,
        "peak_mb": hwm,
    }
    with _INPROC_LOCK:
        _INPROC["tests"].append(row)
        if report.outcome == "failed":
            _INPROC["counts"]["failed"] += 1
            _INPROC["errors"].append(f"FAILED {report.nodeid}")
        else:
            _INPROC["counts"]["passed"] += 1


if pytest is not None:  # pragma: no branch

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(fixturedef: Any, request: Any) -> Any:  # pragma: no cover
        """会话级夹具建立后的 RSS —— ``ga`` / ``ma`` / ``ca`` 的代价就是这一步量出来的。

        用新式 ``wrapper=True``（不是旧的 ``hookwrapper``）：新式包装器必须把结果
        原样 ``return`` 回去，漏了会让夹具返回值变成 None。
        """
        del request  # 只为对齐 hookspec 的形参名
        outcome = yield
        if not _inproc_enabled():
            return outcome
        try:
            value = outcome.get_result()
        except Exception as exc:
            _INPROC["errors"].append(f"FIXTURE-ERROR {fixturedef.argname}: {exc!r}")
            return outcome
        rss, hwm = _inproc_snapshot()
        extra: dict[str, Any] = {}
        if isinstance(value, (list, tuple, set, frozenset, dict)):
            extra["len"] = len(value)
        with _INPROC_LOCK:
            _INPROC["fixtures"].append(
                {
                    "name": fixturedef.argname,
                    "scope": fixturedef.scope,
                    "t_s": round(time.time() - _INPROC_T0, 3),
                    "ws_mb": rss,
                    "peak_mb": hwm,
                    **extra,
                }
            )
        return outcome


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:  # pragma: no cover
    if not _inproc_enabled():
        return
    _INPROC_STOP.set()
    _inproc_phase("sessionfinish", collected=getattr(session, "testscollected", None))
    _inproc_write(exitstatus)


def cmd_rank(args: argparse.Namespace) -> int:
    """把 ``--inproc`` 的原始读数汇总成「按测试模块排名」。"""
    tag = args.tag
    files = sorted(OUT_DIR.glob(f"inproc-{tag}-*.json"))
    if not files:
        print(
            f"[mem] 没有 inproc-{tag}-*.json（先用 run --inproc --tag {tag} 跑一组）",
            file=sys.stderr,
        )
        return 2
    per_module: dict[str, dict[str, Any]] = {}
    per_worker: list[dict[str, Any]] = []
    fixtures: dict[str, dict[str, Any]] = {}
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        per_worker.append(
            {
                "worker": payload["worker"],
                "pid": payload["pid"],
                "peak_ws_mb": payload["peak_ws_mb"],
                "final_ws_mb": payload["final_ws_mb"],
                "duration_s": payload["duration_s"],
                "counts": payload.get("counts"),
            }
        )
        # controller（master）也会收到 worker 转发过来的报告，它那份 per-test
        # 峰值量的是**控制器自己的内存**，混进模块排名会张冠李戴 —— 只取 gw*。
        if payload["worker"] == "master":
            continue
        for row in payload.get("tests", []):
            entry = per_module.setdefault(
                row["module"], {"module": row["module"], "peak_mb": 0.0, "workers": set(), "n": 0}
            )
            entry["peak_mb"] = max(entry["peak_mb"], row["peak_mb"])
            entry["workers"].add(payload["worker"])
            entry["n"] += 1
        for row in payload.get("fixtures", []):
            if row.get("scope") != "session":
                continue
            entry = fixtures.setdefault(
                row["name"], {"fixture": row["name"], "peak_mb": 0.0, "workers": set()}
            )
            entry["peak_mb"] = max(entry["peak_mb"], row["peak_mb"])
            entry["workers"].add(payload["worker"])

    for entry in per_module.values():
        entry["workers"] = sorted(entry["workers"])
    for entry in fixtures.values():
        entry["workers"] = sorted(entry["workers"])
    ranking = sorted(per_module.values(), key=lambda e: -e["peak_mb"])
    payload = {
        "tag": tag,
        "generated_at": _now_iso(),
        "workers": sorted(per_worker, key=lambda w: -w["peak_ws_mb"]),
        "modules": ranking,
        "session_fixtures": sorted(fixtures.values(), key=lambda e: -e["peak_mb"]),
    }
    path = OUT_DIR / f"rank-{tag}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(f"{'模块':<48}{'峰值MB':>10}{'用例':>7}  worker")
    for entry in ranking[: args.top]:
        print(
            f"{entry['module']:<48}{entry['peak_mb']:>10}{entry['n']:>7}  {','.join(entry['workers'])}"
        )
    print("[mem] 会话级夹具（按峰值）：")
    for entry in payload["session_fixtures"][: args.top]:
        print(f"  {entry['fixture']:<24}{entry['peak_mb']:>10}MB  {','.join(entry['workers'])}")
    print(f"[mem] → {path.name}")
    return 0


# ────────────────────────── main ──────────────────────────


def cmd_run(args: argparse.Namespace) -> int:
    groups = [t.strip() for t in (args.groups or ",".join(GROUPS)).split(",") if t.strip()]
    unknown = [t for t in groups if t not in GROUPS]
    if unknown:
        print(f"[mem] 未知组 {unknown}；可用：{list(GROUPS)}", file=sys.stderr)
        return 2
    # `--tag` 只换**产物前缀**，底下的组仍然是原来那个（B108）：同一个 tag 跑两条臂时，
    # 前缀里带上组名（`<tag>-<group>`），两组的明细才同时存在。
    #
    # ⚠️ 这里**不再**往 `GROUPS` 里塞一个别名条目（旧行为）：那是就地改写全局表，一旦
    # `--tag` 与某个**真组名**撞车，真组的定义就被换掉了（同进程里后面每一次
    # `GROUPS[那个名字]` 都是错的）——「跑什么」与「写哪儿」现在靠 `group` / `tag`
    # 两个参数分开传，别名根本不需要住进表里。
    if args.tag and len(groups) != 1:
        print("[mem] --tag 只对单组有意义（--groups 只给一个）", file=sys.stderr)
        return 2
    stems = [artifact_stem(args.tag or group, group) for group in groups]

    # 索引落点与覆盖闸门（B107）——**在跑之前**判：跑完一小时才发现要拒绝，等于白跑。
    index_path = Path(args.index) if args.index else default_index_path(groups, stems)
    reason = index_overwrite_guard(index_path, groups, force=args.force)
    if reason:
        print(f"[mem] 拒绝覆盖索引：{reason}", file=sys.stderr)
        print(
            "[mem] ⇒ 两种走法：① 换一个不覆盖的路径（单组默认就写 "
            f"{default_index_path(groups, stems)}，这次是因为显式 --index 才指到它上面）；"
            "② 确认要覆盖就加 --force",
            file=sys.stderr,
        )
        return 2

    total_mb = sys_mem()["total_mb"]
    watch_mb = args.max_total_mb
    if watch_mb <= 0 and total_mb:
        watch_mb = round(float(total_mb) * args.watch_ratio, 1)
    cache_before = cache_state()

    summaries = []
    for group, stem in zip(groups, stems, strict=True):
        print(f"[mem] === {stem}（组 {group}）：{GROUPS[group]['note']} ===", flush=True)
        try:
            summary = run_group(
                group,
                tag=args.tag,
                target=args.target,
                inproc=args.inproc,
                interval_ms=args.interval_ms,
                timeout_s=args.timeout_s,
                watch_mb=watch_mb,
                watch_avail_mb=args.watch_avail_mb,
                quiet_poll_mb=args.quiet_mb,
                min_avail_mb=args.min_avail_mb,
                wait_s=args.wait_quiet_s,
                allow_concurrent=args.allow_concurrent,
                echo=not args.quiet,
            )
        except SystemExit as exc:
            # 等不到「机器安静」就直接退出，但**不丢已经跑完的组**：
            # 索引照写，缺的那组记成 aborted（实测踩过：整轮的产物因为这个一起没了）。
            print(f"[mem] {_mark('⚠️', '[!]')} {stem} 未开跑：{exc}", flush=True)
            summaries.append(
                {
                    "tag": stem,
                    "group": group,
                    "note": GROUPS[group]["note"],
                    "required": GROUPS[group]["required"],
                    "aborted": str(exc),
                    "command": human_command(
                        group, stem=stem, inproc=args.inproc, target=args.target
                    ),
                }
            )
            continue
        summaries.append(summary)
        if args.fail_fast and summary["exit_code"] != 0:
            break

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index = {
        "generated_at": _now_iso(),
        "note": "并行测试内存基线（口径见模块 docstring 与 docs/design/exec/并行测试内存基线.md）",
        # 这份索引**覆盖了哪些组**要写在里面：它是「这份索引能不能当完整基线用」的判据，
        # 也让 t13 那种「只剩一组」的截断在文件里看得见（不必靠比对大小去猜）。
        "covers_groups": [str(s.get("group") or s.get("tag")) for s in summaries],
        "machine": machine_info(),
        "budget": {
            "per_worker_mb": BUDGET_PER_WORKER_MB,
            "head_mb": BUDGET_HEAD_MB,
            "formula": "peak_total_mb ≤ head_mb + workers × per_worker_mb",
        },
        "watch_mb": watch_mb,
        "watch_avail_mb": args.watch_avail_mb,
        # 磁盘缓存的状态会改变 worker 的内存（读分片就装进内存）—— 记下来，
        # 否则「同一台机器、同一个命令、两个数」没法解释。
        "cache_before": cache_before,
        "cache_after": cache_state(),
        "groups": summaries,
        "verdict": [judge(s) for s in summaries],
    }
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(f"[mem] 索引 → {_short(index_path)}（覆盖组：{index['covers_groups']}）")
    return 0


def cmd_list(args: argparse.Namespace) -> int:  # noqa: ARG001
    print("组：")
    for tag, spec in GROUPS.items():
        print(
            f"  {tag:<12} -n {spec['n']:<5} cache={spec['cache']} {'（合约必测）' if spec['required'] else '（附加）'} {spec['note']}"
        )
    print("单点步骤（one <step>）：")
    for name in STEPS:
        print(f"  {name}")
    return 0


#: ``one`` 的步骤清单（与 :func:`step_one` 的分支一一对应）。
STEPS = (
    "startup",
    "import:pytest",
    "import:pdx",
    "import:heavy",
    "imports",
    "corpus_files",
    "corpus_texts",
    "shards_touch",
    "shards_each",
    "invariant",
    "index-audit",
    "biggest",
    "layers",
    "retain",
    "drop",
    "parse_all",
    "ga",
    "ma",
    "ca",
    "compact_snapshot",
    "full_snapshot",
    "chain",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mem_baseline",
        description="并行测试内存基线：整套峰值 / 每 worker 峰值 / 总耗时（跨平台，只用标准库）",
    )
    sub = parser.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="按组测量（默认三组合约必测 + 两个附加可选）")
    run.add_argument("--groups", help="逗号分隔，见 --list；默认全部")
    run.add_argument("--tag", help="单组的产物前缀（--groups 只给一个时）")
    run.add_argument("--target", default=TESTS, help=f"pytest 目标，默认 {TESTS}")
    run.add_argument(
        "--inproc", action="store_true", help="同时开 worker 内读数（-p mem_baseline）"
    )
    run.add_argument(
        "--index",
        default=None,
        help="索引产物路径（不给 = 单组写 <前缀>.json、多组写 baseline.json）",
    )
    run.add_argument(
        "--force",
        action="store_true",
        help="显式允许覆盖一个「里面还有这次不跑的组」的索引（不给就拒绝并 exit 2）",
    )
    run.add_argument("--interval-ms", type=int, default=INTERVAL_MS)
    run.add_argument("--timeout-s", type=float, default=3600.0)
    run.add_argument(
        "--max-total-mb", type=float, default=0.0, help="树 RSS 超过就杀（0=按 --watch-ratio 推导）"
    )
    run.add_argument(
        "--watch-ratio", type=float, default=0.85, help="看门狗阈值 = 该比例 × 物理内存"
    )
    run.add_argument(
        "--watch-avail-mb",
        type=float,
        default=700.0,
        help="物理可用内存低于该值就杀（0=不看；防换页拖死机器）",
    )
    run.add_argument("--quiet-mb", type=float, default=200.0, help="并发重活的判定阈值（MB 常驻）")
    run.add_argument(
        "--min-avail-mb",
        type=float,
        default=4096.0,
        help="开工前要求的空闲物理内存（MB）；低于它继续等（等不到就报错）",
    )
    run.add_argument(
        "--wait-quiet-s", type=float, default=900.0, help="等机器安静的最长秒数（0=不等）"
    )
    run.add_argument("--allow-concurrent", action="store_true", help="允许并发重活，只如实记录状态")
    run.add_argument("--fail-fast", action="store_true")
    run.add_argument("--quiet", action="store_true", help="不把子进程输出回显到终端（仍落盘）")
    run.set_defaults(func=cmd_run)

    one = sub.add_parser("one", help="单点复算某个组件（组件排名的证据命令）")
    one.add_argument("step", help="见 --list")
    one.add_argument(
        "--evict-every", type=int, default=0, help="parse_all 每 N 个文件清一次保留（0=不清）"
    )
    one.add_argument(
        "--evict-what",
        choices=("both", "memo", "shards"),
        default="both",
        help="淘汰哪一层（默认两层都清；只清一层才能分清是谁占的）",
    )
    one.add_argument(
        "--janitor-s",
        type=float,
        default=0.0,
        help="可选择性实验：每 N 秒清一次两种保留层（0=不清）；用来量「不永久保留」时的内存下界",
    )
    one.add_argument(
        "--files",
        type=int,
        default=0,
        help="限制语料文件数（0=全部）：invariant 默认 250（复核报告的口径），biggest 默认全部",
    )
    one.add_argument("--quiet-mb", type=float, default=200.0, help="并发重活的判定阈值（MB 常驻）")
    one.add_argument(
        "--min-avail-mb", type=float, default=1024.0, help="开工前要求的空闲物理内存（MB）"
    )
    one.add_argument("--wait-quiet-s", type=float, default=900.0, help="等机器安静的最长秒数")
    one.add_argument("--allow-concurrent", action="store_true", help="允许并发重活（如实记录状态）")
    one.set_defaults(func=cmd_one)

    check = sub.add_parser("check", help="判预算（退出码 0 达标 / 1 不达标 / 2 缺产物）")
    check.add_argument("--index", default=str(OUT_DIR / "baseline.json"))
    check.add_argument("--reference", help="参考索引：同 tag 的用例数不得少于它")
    check.set_defaults(func=cmd_check)

    rank = sub.add_parser("rank", help="汇总 --inproc 读数，出「按模块」排名")
    rank.add_argument("--tag", default="n4-inproc")
    rank.add_argument("--top", type=int, default=10)
    rank.set_defaults(func=cmd_rank)

    compare = sub.add_parser("compare", help="比「修复后」与冻结基线，按三层判据给判决")
    compare.add_argument("--index", default=str(OUT_DIR / "baseline-优化后.json"))
    compare.add_argument("--reference", default=str(OUT_DIR / "baseline-优化前.json"))
    compare.set_defaults(func=cmd_compare)

    listing = sub.add_parser("list", help="列出组与单点步骤")
    listing.set_defaults(func=cmd_list)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # 跨平台硬伤 B109 的第一道修法：**先**把 I/O 的编码错误策略改成 replace，
    # 之后任何人（包括我们回显的被测命令输出）打印本控制台装不下的字符都不会崩。
    _reconfigure_stdio()
    raw = list(argv) if argv is not None else sys.argv[1:]
    # 顶层 `--compare` 是 `compare` 子命令的别名（合约里的 verify 命令就长这样：
    # `python tools/probe/mem_baseline.py --compare`）。
    if "--compare" in raw:
        raw = [item for item in raw if item != "--compare"]
        return cmd_compare(build_compare_args(raw))
    parser = build_parser()
    args = parser.parse_args(raw)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return int(args.func(args))


def build_compare_args(raw: Sequence[str]) -> argparse.Namespace:
    """给顶层 ``--compare`` 用的极简解析（只认 index / reference）。"""
    parser = argparse.ArgumentParser(prog="mem_baseline --compare")
    parser.add_argument("--index", default=str(OUT_DIR / "baseline-优化后.json"))
    parser.add_argument("--reference", default=str(OUT_DIR / "baseline-优化前.json"))
    return parser.parse_args(list(raw))


if __name__ == "__main__":
    sys.exit(main())
