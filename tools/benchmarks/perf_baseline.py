#!/usr/bin/env python
"""I7a：工具链性能与内存基线（**只测量，不改被测代码**）。

为什么是这个形状
================

用户第 7 条要求「所有 Python 代码做性能测试优化性能（速度与内存）」。没有可信的
**基线**，后面的「优化」与「护栏」都是空话。这份脚本就是那把量尺的扩表：

* 内存读数复用 ``tools/probe/mem_baseline.py`` 的 psutil 量尺。
  Windows 读取 peak_wset，Linux 补读 /proc 的 VmHWM，macOS 使用采样峰值；
  具体来源写在原始记录里，不把各平台的读数称为同一种精确值。
* 覆盖面由 CASES 与动态分片表枚举；模块导入和 AST 成本不是函数运行成本。
  实际运行热点另由 ``profile_suite.py`` 对测试执行进行 cProfile 采样。

三条读数口径（同时给，不许只挑好看的那个）
==========================================

* ``peak_hwm_mb`` —— 观察到的各进程高水位之和；macOS 回退为采样读数。
  短命子进程可能未被观察到，不能宣称是整棵进程树的严格上界。
* ``peak_sampled_mb`` —— 采样时刻的 RSS 之和取最大。采样间隔 50 ms（套件 250 ms），
  两次采样之间的尖峰会被漏掉，所以它是**下界**。
* ``max_proc_hwm_mb`` —— 观察到的单进程最大高水位，须结合平台与来源判断。

两种读数都进基线；另记观察到的进程 CPU 时间，辅助解释墙钟变化。
CPU 时间也不能补回未被观察到的短命子进程，因此同时标记并发负载。

机器纪律
========

同一时刻只跑一个重活。每轮开工前 ``ensure_quiet`` 等安静（有界等待），开工前后各记一次
并发重活快照；**被抢的轮次标 ``contended``，汇总时优先用不被抢的轮次**，一个都没有就如实说。

产物
====

* 临时件（每轮的 log / 采样 csv / 原始 json）：``%TEMP%/repo-audit-perf/``
* 本机报告（忽略）：``tools/benchmarks/repo-audit-baseline.json``、
  ``tools/benchmarks/repo-audit-modules.json``；可复核结论写入 docs/audits。

用法
====

    .venv\\Scripts\\python.exe tools/benchmarks/perf_baseline.py list
    .venv\\Scripts\\python.exe tools/benchmarks/perf_baseline.py run --group cli --rounds auto
    .venv\\Scripts\\python.exe tools/benchmarks/perf_baseline.py run --group suite --rounds 3
    .venv\\Scripts\\python.exe tools/benchmarks/perf_baseline.py run --group shards --rounds 1
    .venv\\Scripts\\python.exe tools/benchmarks/perf_baseline.py modules
    .venv\\Scripts\\python.exe tools/benchmarks/perf_baseline.py summarize
    .venv\\Scripts\\python.exe tools/benchmarks/perf_baseline.py check --ci
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pdx.performance import command as measure_command

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
MEM_SCRIPT = REPO / "tools" / "probe" / "mem_baseline.py"
BENCH_DIR = REPO / "tools" / "benchmarks"
BASELINE_JSON = BENCH_DIR / "repo-audit-baseline.json"
MODULES_JSON = BENCH_DIR / "repo-audit-modules.json"

_TMP_ENV = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
RAW_DIR = Path(_TMP_ENV) / "repo-audit-perf"

PY = Path(sys.executable)

#: 多大的外来 python / victoria3 进程算「重活」。
QUIET_MB = 200.0
#: 低于这个可用物理内存就认为机器不安静。
MIN_AVAIL_MB = 2048.0
#: 看门狗上限：不为了「防呆」把真读数杀掉，只挡住失控。
WATCH_MB = 12000.0
WATCH_AVAIL_MB = 1024.0
#: 单个用例的墙钟上限（秒）：超了杀树并标 timed_out。
DEFAULT_TIMEOUT_S = 900.0
#: 短命令用细采样（否则漏掉整条命令），长命令用粗采样（少扰动）。
INTERVAL_CLI_S = 0.05
INTERVAL_SUITE_S = 0.25
#: 等安静的上限（秒）。超时不算失败，记 contended 照跑。
WAIT_QUIET_S = 600.0
#: 被测命令的环境：只加编码这一条（控制台 GBK 会让中文输出乱码 / 抛 UnicodeEncodeError，
#: B109 已修但日志仍要可读；CI 也是 UTF-8）。其余环境原样继承。
ENV_EXTRA = {"PYTHONIOENCODING": "utf-8", "COLUMNS": "200"}


def _load_mem() -> ModuleType:
    """按路径 import 量尺（``tools/probe`` 不是包；与 ``test_mem_baseline.py`` 同法）。"""
    spec = importlib.util.spec_from_file_location("repo_audit_mem_baseline", MEM_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - 文件必然存在
        raise SystemExit(f"找不到量尺：{MEM_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ────────────────────────────── 用例表 ──────────────────────────────
#
# ``tier`` 的含义（报告里逐条写明）：
#   T1 真跑     —— 只读，或只写 %TEMP%；给的是这条命令的真成本。
#   T2 只装配   —— 真跑会写受保护文件（tools/probe/** 探针）或需要实机；测的是
#                  「CLI 装配 + import」这一段，并写明为什么到此为止。
#   T3 需实机   —— 需要游戏日志 / 实机存档；无实机时测的是**拒绝路径**（启动即判红）的成本。


def _v3(*args: str) -> list[str]:
    return [str(PY), "-m", "pdx.cli", *args]


def _pytest(*args: str) -> list[str]:
    return [str(PY), "-m", "pytest", "-q", *args]


#: 全量套件的官方跑法（pyproject 的 addopts 自带 ``-n auto --dist loadscope``）。
SUITE_ARGS = ["-n", "auto"]

CASES: list[dict[str, Any]] = [
    # ── T1：全量工具链命令（覆盖 `v3 --help` 现读的 34 个子命令）──────────────
    {
        "id": "cli.root-help",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("--help"),
        "interp": "导入地板：typer + rich 装配 + 全命令注册",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.analyze",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("analyze", "--no-write", "--quiet"),
        "interp": "全量分析（游戏本体 + mods），--no-write 不落盘",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.defines",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("defines"),
        "interp": "defines 命名空间与参数提取（游戏层 + Jomini 层）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.index-dry",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("index", "--dry-run"),
        "interp": "全量键名索引重算，--dry-run 不写文档",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.refresh-dry",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("refresh", "--dry-run"),
        "interp": "升级后一条命令：重算生成表 + 数字改写预览，不写盘",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.tables-offline",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("tables", "--offline"),
        "interp": "生成表核对（拿入库快照比，不读游戏）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.objectives-check",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("objectives", "--check"),
        "interp": "9 国目标函数表 + P1–P5 五条闸门",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.verify",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("verify"),
        "interp": "数量断言核对 + 文档漂移扫描（**不含**被禁的 --fix-claims）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.verify-fast",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("verify", "--fast"),
        "interp": "同上的 --fast 路径（跳过全库扫描）——用来把成本拆开看",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.crosscheck",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("crosscheck"),
        "interp": "用引擎日志交叉验证解析结果",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.check-outputs",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("check-outputs"),
        "interp": "落盘产物与断言注册表一致性",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.strings",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("strings", "--limit", "5"),
        "interp": "victoria3.exe 字符串开采（--limit 5 只影响打印量）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.experiment-plan",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("experiment"),
        "interp": "实验编排默认动作 plan（只打印，不装探针、不动 content_load）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.lock",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("lock"),
        "interp": "依赖锁核对（不带 --write，只比对不重写 requirements.lock）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.cov-check",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("cov", "--check-only"),
        "interp": "覆盖率门禁：只读上次数据，不重跑测试",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.cache-list",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("cache", "--list"),
        "interp": "解析缓存状态盘点",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.evidence",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("evidence", "orphan", "character_event"),
        "interp": "键名四类证据（原版用法 / 官方 md / mod / exe 字面量）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.prefixes",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("prefixes"),
        "interp": "本机 mod 功能前缀按目录用量",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.assets",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("assets", "--no-examples"),
        "interp": "DDS 头普查（--no-examples 只算不列例）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.csv",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("csv", "map_data/adjacencies.csv"),
        "interp": "非 PDX 表格取值分布（doc 06 §4.4 的可复算版）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.ai-surface-check",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("ai-surface", "--offline", "--check"),
        "interp": "AI 可执行面核对（离线：读入库精简快照）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.h1-health",
        "group": "cli",
        "tier": "T3",
        "argv": _v3("h1", "--health"),
        "interp": "H1 开局自检：实机日志不在盘上 ⇒ 测的是**拒绝路径**（启动即判红）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.h1-probe",
        "group": "cli",
        "tier": "T2",
        "argv": _v3("h1-probe", "--help"),
        "interp": "H1 探针生成器：真跑会写 tools/probe/zz_probe_h1/**（受保护面）⇒ 只测装配",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.modgen-check",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("modgen", "--check"),
        "interp": "mod 产物与数据源一致性（**这条必须保持绿**：69 个产物逐字节）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.package-help",
        "group": "cli",
        "tier": "T2",
        "argv": _v3("package", "--help"),
        "interp": "交付入口装配；真实 ZIP 的确定性与 BOM 边界由打包测试验证",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.citations-offline",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("citations", "--offline"),
        "interp": "数据源 文件:行号 引用可解析性核对（离线）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.release",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("release"),
        "interp": "发布说明 ↔ 档案 ↔ 元数据三边一致",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.preflight",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("preflight"),
        "interp": "开局前置条件自检（只读）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.modguard-offline",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("modguard", "--offline"),
        "interp": "五道闸门（离线：读入库精简快照）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.ab-probe",
        "group": "cli",
        "tier": "T2",
        "argv": _v3("ab-probe", "--help"),
        "interp": "A/B 探针生成器：真跑会重写 tools/probe/** 探针 ⇒ 只测装配",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.ab-health",
        "group": "cli",
        "tier": "T3",
        "argv": _v3("ab", "--health"),
        "interp": "A/B 开局自检：实机日志不在盘上 ⇒ 测的是拒绝路径",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.backlog-list",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("backlog", "--list"),
        "interp": "未确认/待办合成计数",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.unverified",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("unverified", "--no-context"),
        "interp": "文档【未确认】清单的可复算版",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.show",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("show"),
        "interp": "已落盘产物的结构与规模转储",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.snapshot-list",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("snapshot", "list"),
        "interp": "版本快照清单（snapshot 的子命令）",
        "interval_s": INTERVAL_CLI_S,
    },
    {
        "id": "cli.mirror-check",
        "group": "cli",
        "tier": "T1",
        "argv": _v3("mirror", "check"),
        "interp": "官方 md 清单 ↔ 本地镜像核对（mirror 的子命令）",
        "interval_s": INTERVAL_CLI_S,
    },
    # ── 测试套件：全量 + 分片 ────────────────────────────────────────────
    {
        "id": "suite.full",
        "group": "suite",
        "tier": "T1",
        "argv": _pytest(*SUITE_ARGS, "--junitxml=" + str(RAW_DIR / "junit-full.xml")),
        "interp": "全量套件（并行，仓库默认 addopts = -n auto --dist loadscope）+ junit 逐用例耗时",
        "interval_s": INTERVAL_SUITE_S,
        "timeout_s": 3600.0,
    },
]

#: 分片：按**测试文件名**四分（不按 -k 过滤，避免重复收集与重复 session fixture）。
SHARD_COUNT = 4
# 外部并行运行四片时，每片只保留一个 xdist worker，避免四个 auto
# 池叠加造成内存峰值；完整套件仍使用 SUITE_ARGS 的 auto。
SHARD_SUITE_ARGS = ["-n", "1", "--dist", "no"]


def shard_test_files(files: Sequence[str], shard_count: int = SHARD_COUNT) -> list[list[str]]:
    """按稳定文件名轮转分片，并拒绝无意义的分片参数。"""
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    for index, name in enumerate(sorted(files)):
        shards[index % shard_count].append(name)
    return shards


def shard_cases() -> list[dict[str, Any]]:
    """把 tests 的测试文件按名字四分，每片一条用例（读数=片内墙钟与峰值）。"""
    files = [p.name for p in (REPO / "tests").glob("test_*.py")]
    shards = shard_test_files(files)
    return [
        {
            "id": f"shard.{number + 1}-of-{SHARD_COUNT}",
            "group": "shards",
            "tier": "T1",
            "argv": _pytest(*SHARD_SUITE_ARGS, *[f"tests/{name}" for name in shard]),
            "interp": f"全量套件第 {number + 1}/{SHARD_COUNT} 片（{len(shard)} 个测试文件，按文件名轮转切）",
            "interval_s": INTERVAL_SUITE_S,
            "timeout_s": 3600.0,
        }
        for number, shard in enumerate(shards)
    ]


def all_cases() -> list[dict[str, Any]]:
    return [*CASES, *shard_cases()]


def cases_of(group: str) -> list[dict[str, Any]]:
    everything = all_cases()
    if group == "all":
        return everything
    return [case for case in everything if case["group"] == group]


# ────────────────────────────── 跑一条用例 ──────────────────────────────


def _pump(stream: Any, log: Any) -> None:
    """把被测命令的输出边读边落盘（日志丢了就没法解释失败用例）。"""
    try:
        for line in stream:
            log.write(line)
        log.flush()
    finally:
        with contextlib.suppress(Exception):
            stream.close()


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(ENV_EXTRA)
    return env


def run_round(
    mem: ModuleType,
    case: dict[str, Any],
    *,
    round_index: int,
    allow_concurrent: bool,
    wait_quiet_s: float,
) -> dict[str, Any]:
    """跑一轮：等安静 → 起进程 → 采样 → 收尾 → 原始读数落 %TEMP%。"""
    out_dir = RAW_DIR / case["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"r{round_index}.log"

    mem.ensure_quiet(
        quiet_mb=QUIET_MB,
        min_avail_mb=MIN_AVAIL_MB,
        wait_s=wait_quiet_s,
        allow=allow_concurrent,
        strict=False,
    )
    before = mem.foreign_heavy(QUIET_MB, ignore={os.getpid()})
    avail_before = mem.sys_mem()["avail_mb"]
    cache_before = mem.cache_state()

    argv = list(case["argv"])
    t0 = time.perf_counter()
    pipe, log = mem.spawn(argv, _env(), log_path)
    sampler = mem.TreeSampler(
        pipe.pid,
        interval_s=float(case.get("interval_s", INTERVAL_CLI_S)),
        watch_mb=WATCH_MB,
        watch_avail_mb=WATCH_AVAIL_MB,
        killer=lambda: mem.kill_tree(pipe.pid),
    )
    sampler.start()
    pump = threading.Thread(target=_pump, args=(pipe.stdout, log), daemon=True)
    pump.start()

    timed_out = False
    try:
        pipe.wait(timeout=float(case.get("timeout_s", DEFAULT_TIMEOUT_S)))
    except subprocess.TimeoutExpired:
        timed_out = True
        mem.kill_tree(pipe.pid)
        with contextlib.suppress(Exception):
            pipe.wait(timeout=30.0)
    wall_s = round(time.perf_counter() - t0, 3)
    summary = sampler.finish()
    pump.join(timeout=10.0)
    log.close()

    after = mem.foreign_heavy(QUIET_MB, ignore={os.getpid()})
    exit_code = pipe.returncode
    record: dict[str, Any] = {
        "case": case["id"],
        "group": case["group"],
        "tier": case["tier"],
        "round": round_index,
        "argv": argv,
        "command": case.get("command") or " ".join(argv),
        "interval_s": case.get("interval_s", INTERVAL_CLI_S),
        "wall_s": wall_s,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "peak_hwm_mb": summary["sum_hwm_mb"],
        "peak_sampled_mb": summary["peak_total_mb"],
        "peak_private_mb": summary["peak_total_private_mb"],
        "max_proc_hwm_mb": max((p["hwm_mb"] for p in sampler.procs_table()), default=0.0),
        "cpu_total_s": summary["cpu_total_s"],
        "n_procs": len(sampler.procs_table()),
        "samples": summary["samples"],
        "n_workers": summary["n_workers"],
        "sampler_errors": summary["sampler_errors"],
        "killed_by_watchdog": summary["killed_by_watchdog"],
        "kill_reason": summary["kill_reason"],
        "contended": bool(before or after),
        "foreign_before": before[:3],
        "foreign_after": after[:3],
        "avail_mb_before": avail_before,
        "cache_before": cache_before,
        "log": str(log_path),
        "tail": _tail(log_path),
    }
    (out_dir / f"r{round_index}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (out_dir / f"r{round_index}.samples.csv").write_text(
        sampler.timeline_csv(), encoding="utf-8", newline="\n"
    )
    (out_dir / f"r{round_index}.procs.csv").write_text(
        sampler.procs_csv(), encoding="utf-8", newline="\n"
    )
    return record


def _tail(path: Path, limit: int = 4000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def rounds_for(case: dict[str, Any], spec: str) -> int:
    """``auto``：快的多跑几轮（噪声取中位数要够样本），慢的少跑。"""
    if spec != "auto":
        return int(spec)
    fixed = case.get("rounds")
    if fixed:
        return int(fixed)
    return 5 if case["group"] == "cli" else 3


def cmd_run(args: argparse.Namespace) -> int:
    mem = _load_mem()
    mem._reconfigure_stdio()
    cases = cases_of(args.group)
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only)]
    if not cases:
        print(f"[perf] group={args.group} 没有用例", file=sys.stderr)
        return 2
    print(f"[perf] 机器：{json.dumps(mem.machine_info(), ensure_ascii=False)}")
    print(f"[perf] 原始产物：{RAW_DIR}")
    for case in cases:
        count = rounds_for(case, args.rounds)
        for index in range(1, count + 1):
            record = run_round(
                mem,
                case,
                round_index=index,
                allow_concurrent=args.allow_concurrent,
                wait_quiet_s=args.wait_quiet_s,
            )
            flag = "抢" if record["contended"] else "静"
            print(
                f"[{flag}] {case['id']:<24} r{index}/{count}  "
                f"wall={record['wall_s']:>8.3f}s  hwm={record['peak_hwm_mb']:>8.1f}MB  "
                f"rss_max={record['peak_sampled_mb']:>8.1f}MB  cpu={record['cpu_total_s']:>7.1f}s  "
                f"pid#={record['n_procs']}  exit={record['exit_code']}",
                flush=True,
            )
    return 0


# ────────────────────────────── 汇总 ──────────────────────────────


def _stats(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {"n": 0}
    med = statistics.median(clean)
    return {
        "n": len(clean),
        "median": round(med, 3),
        "min": round(min(clean), 3),
        "max": round(max(clean), 3),
        "spread_pct": round((max(clean) - min(clean)) / med * 100.0, 1) if med else None,
    }


def load_rounds() -> dict[str, list[dict[str, Any]]]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    if not RAW_DIR.exists():
        return by_case
    for path in sorted(RAW_DIR.glob("*/r*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("stale"):
            continue
        by_case.setdefault(record["case"], []).append(record)
    for records in by_case.values():
        records.sort(key=lambda item: item["round"])
    return by_case


def case_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """一条用例的汇总：**优先用不被抢的轮次**，一个都没有就如实说明。"""
    clean = [r for r in records if not r["contended"]]
    used = clean or list(records)
    kept = [r for r in used if r["exit_code"] == 0 and not r["timed_out"]]
    base = kept or used
    return {
        "rounds_total": len(records),
        "rounds_used": len(used),
        "rounds_uncontended": len(clean),
        "rounds_ok": len(kept),
        "contended": len(clean) == 0,
        "wall_s": _stats([r["wall_s"] for r in base]),
        "cpu_total_s": _stats([r["cpu_total_s"] for r in base]),
        "peak_hwm_mb": _stats([r["peak_hwm_mb"] for r in base]),
        "peak_sampled_mb": _stats([r["peak_sampled_mb"] for r in base]),
        "max_proc_hwm_mb": _stats([r["max_proc_hwm_mb"] for r in base]),
        "exit_codes": sorted({r["exit_code"] for r in records}),
        "n_procs": sorted({r["n_procs"] for r in records}),
        "commands": sorted({r["command"] for r in records}),
    }


def _git_state() -> dict[str, Any]:
    def _run(*args: str) -> str:
        out = subprocess.run(
            ["git", *args], cwd=str(REPO), capture_output=True, text=True, check=False
        )
        return out.stdout.strip()

    status = _run("status", "--porcelain")
    return {
        "head": _run("rev-parse", "HEAD"),
        "dirty_files": len(status.splitlines()),
        "status_sha256_12": __import__("hashlib").sha256(status.encode("utf-8")).hexdigest()[:12],
    }


def build_baseline() -> dict[str, Any]:
    mem = _load_mem()
    by_case = load_rounds()
    cases: dict[str, Any] = {}
    for case in all_cases():
        records = by_case.get(case["id"], [])
        summary: dict[str, Any] = (
            case_summary(records) if records else {"rounds_total": 0, "missing": True}
        )
        summary.update(
            {
                "group": case["group"],
                "tier": case["tier"],
                "interp": case["interp"],
                "argv": list(case["argv"]),
                "command": case.get("command") or " ".join(case["argv"]),
                "interval_s": case.get("interval_s", INTERVAL_CLI_S),
            }
        )
        cases[case["id"]] = summary
    measured = {k: v for k, v in cases.items() if v.get("rounds_total")}
    return {
        "口径": {
            "生成者": "tools/benchmarks/perf_baseline.py summarize（可重跑）",
            "机器": mem.machine_info(),
            "git": _git_state(),
            "内存读法": {
                "主读数": "psutil RSS；Windows peak_wset / Linux VmHWM / macOS 采样峰值",
                "peak_hwm_mb": "观察到的各进程高水位之和；采样回退和短命子进程限制见原始记录",
                "peak_sampled_mb": "采样 RSS 之和取最大（间隔 50ms/250ms，尖峰会漏）",
                "max_proc_hwm_mb": "观察到的单进程最大高水位；不等于整棵进程树同时峰值",
                "不确定度": "不保证两种读数夹住真值；来源不同的平台不能直接作精确峰值比较",
                "交叉验证": "pdx.performance 独立采样；旧 Win32 四路实验保存在 tools/probe/frozen",
            },
            "墙钟": "多轮取中位数；同行给 min/max/spread_pct。被外来重活抢过的轮次优先剔除",
            "cpu_total_s": "观察到的进程 CPU 时间合计，作为墙钟辅证，可能漏短命子进程",
            "环境": {"PYTHONIOENCODING": "utf-8", "COLUMNS": "200"},
            "临时件": str(RAW_DIR),
        },
        "用例": cases,
        "计数": {"用例数": len(cases), "有用例数": len(measured), "轮次总数": len(by_case)},
    }


def _rank(rows: Iterable[tuple[str, float]], *, top: int) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda item: -item[1])[:top]
    return [
        {"排名": i + 1, "用例": name, "值": round(value, 3)}
        for i, (name, value) in enumerate(ranked)
    ]


def rankings(baseline: dict[str, Any]) -> dict[str, Any]:
    """时间与内存各前 10（同类可比：CLI 子命令与测试套件分开排）。"""
    out: dict[str, Any] = {}
    for group, label in (("cli", "v3 子命令"), ("suite", "测试套件"), ("shards", "测试分片")):
        rows = [
            (name, data["wall_s"]["median"])
            for name, data in baseline["用例"].items()
            if data.get("group") == group and data.get("wall_s", {}).get("n")
        ]
        if not rows:
            continue
        out[label] = {
            "按墙钟前10": _rank(rows, top=10),
            "按峰值内存前10": _rank(
                [
                    (name, data["peak_hwm_mb"]["median"])
                    for name, data in baseline["用例"].items()
                    if data.get("group") == group and data.get("peak_hwm_mb", {}).get("n")
                ],
                top=10,
            ),
        }
    return out


def cmd_summarize(args: argparse.Namespace) -> int:
    baseline = build_baseline()
    baseline["热点排名"] = rankings(baseline)
    if args.out:
        target = Path(args.out)
    else:
        target = BASELINE_JSON
    target.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[perf] 基线写入 {target}（{target.stat().st_size} B）")
    print(
        json.dumps(
            {name: data.get("wall_s", {}).get("median") for name, data in baseline["用例"].items()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# ────────────────────────────── 护栏 ──────────────────────────────

#: 超基线多少判红（用户 q_perfgate 口径）。
GATE_PCT = 10.0
#: 本机噪声大：本机只出信息性读数，判红只在 CI 专用 job。
CI_ENV_FLAG = "REPO_AUDIT_PERF_GATE"


def compare_to_baseline(
    baseline: dict[str, Any], current: dict[str, Any], *, threshold_pct: float = GATE_PCT
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, base in baseline["用例"].items():
        now = current["用例"].get(name)
        if not now or not now.get("wall_s", {}).get("n") or not base.get("wall_s", {}).get("n"):
            continue
        for metric, key in (("墙钟", "wall_s"), ("峰值内存", "peak_hwm_mb")):
            before = base[key]["median"]
            after = now[key]["median"]
            if not before:
                continue
            delta = (after - before) / before * 100.0
            # 判红是**开区间**：天花板 = 基线 ×(1+阈值)，正好 +10% 不红
            # （用一次乘法而不是比较算出来的百分比 —— 后者在边界上会被浮点尾数顶过去）
            ceiling = before * (1.0 + threshold_pct / 100.0)
            rows.append(
                {
                    "case": name,
                    "metric": metric,
                    "baseline": before,
                    "current": after,
                    "delta_pct": round(delta, 1),
                    "verdict": "红" if after > ceiling else "绿",
                }
            )
    return rows


def cmd_check(args: argparse.Namespace) -> int:
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    if args.current:
        current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    else:
        current = build_baseline()
    rows = compare_to_baseline(baseline, current, threshold_pct=args.threshold)
    red = [row for row in rows if row["verdict"] == "红"]
    ci = args.ci or os.environ.get(CI_ENV_FLAG) == "1"
    marker = "[GATE]" if ci else "[INFO]"
    for row in sorted(rows, key=lambda item: -item["delta_pct"]):
        print(
            f"{marker} {row['verdict']} {row['case']:<24} {row['metric']}  "
            f"基线 {row['baseline']} → 现测 {row['current']}  ({row['delta_pct']:+.1f}%)"
        )
    print(
        f"{marker} 共 {len(rows)} 项指标，超 +{args.threshold:.0f}% 的 {len(red)} 项"
        + ("" if ci else "（本机口径：只出信息性读数，判红在 CI 专用 job）")
    )
    if ci and red:
        return 1
    return 0


# ────────────────────────────── 当前模块集合模块台账 ──────────────────────────────

FAMILIES: list[tuple[str, str, str]] = [
    ("src/pdx", "pdx", "入库包：测导入墙钟 + 整棵子进程树采样 RSS，包含依赖成本"),
    (
        "tests",
        "tests",
        "测试模块：测**套件内耗时**（junit xml 逐文件聚合），另给 AST 解析成本",
    ),
    (
        "tools/probe",
        "probe",
        "一次性探针脚本（非包）：导入即执行，**不测导入**；给 AST 解析成本 + 字节数",
    ),
    ("tools/ci", "ci", "CI 辅助脚本（非包）：同上"),
    ("tools/prof", "prof", "剖析脚本（非包）：同上"),
    (
        "tools/benchmarks",
        "benchmarks",
        "基线与 profile 工具：静态检查，真实执行另由测试和测量报告证明",
    ),
]


def _parse_cost(path: Path, rounds: int = 3) -> float:
    """源码解析（compile）墙钟取最小，毫秒。与执行无关、确定性高。"""
    source = path.read_text(encoding="utf-8-sig")
    best = float("inf")
    for _ in range(rounds):
        start = time.perf_counter()
        compile(source, str(path), "exec")
        best = min(best, time.perf_counter() - start)
    return round(best * 1000.0, 3)


def _module_import_cost(dotted: str, out_dir: Path) -> dict[str, Any]:
    """新进程导入时间与采样 RSS，不按内存阈值把小解释器误当成启动壳。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"{dotted.replace('.', '_')}.log"
    argv = [str(PY), "-c", f"import {dotted}"]
    result = measure_command(argv, log_path, timeout=120, interval=0.01)
    return {
        "import_s": result["wall_s"],
        "import_peak_rss_mb": float(str(result["sampled_tree_peak_rss_bytes"])) / 1048576,
        "import_exit": result["exit_code"],
        "import_timed_out": result["timed_out"],
        "import_sample_interval_s": result["sample_interval_s"],
    }


def _junit_by_file() -> dict[str, dict[str, Any]]:
    """从全量套件的 junit xml 里按测试文件聚合耗时（全量套件跑过才有）。"""
    path = REPO / "tools/out/repository-audit/tests-final.xml"
    if not path.exists():
        path = RAW_DIR / "junit-full.xml"
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    by_file: dict[str, dict[str, Any]] = {}
    for case in root.iter("testcase"):
        name = case.get("classname") or ""
        # classname 形如 tools.tests.test_xxx；取最后一段回推文件名。
        stem = next(
            (part for part in name.split(".") if part.startswith("test_")), name.split(".")[-1]
        )
        entry = by_file.setdefault(
            stem, {"n_tests": 0, "tests_s": 0.0, "failures": 0, "errors": 0, "skipped": 0}
        )
        entry["n_tests"] += 1
        entry["tests_s"] = round(entry["tests_s"] + float(case.get("time") or 0.0), 3)
        entry["failures"] += len(case.findall("failure"))
        entry["errors"] += len(case.findall("error"))
        entry["skipped"] += len(case.findall("skipped"))
    return by_file


def instrument_layer() -> dict[str, Any]:
    """仪器层（tools/out/**/*.py）：不在覆盖率/性能分母内，单独报。"""
    root = REPO / "tools" / "out"
    files = [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]
    lines = 0
    size = 0
    for path in files:
        data = path.read_bytes()
        size += len(data)
        lines += data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
    biggest = sorted(files, key=lambda p: -p.stat().st_size)[:20]
    return {
        "计数口径": "tools/out/**/*.py，排除 __pycache__（rglob，不看 .gitignore）",
        "文件数": len(files),
        "行数": lines,
        "字节": size,
        "入库": False,
        "为什么排除": "tools/out 是**产物 + 一次性仪器**层：整棵被 .gitignore 忽略、"
        "不在 coverage 的 source=['pdx'] 分母内、也不在工具链的运行期代码路径上。"
        "它们是「每次调查时的现场脚本」，逐件性能读数没有意义（多数只跑一次就退役）。",
        "抽样读数": [
            {
                "path": str(path.relative_to(REPO)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "parse_ms": _parse_cost(path),
            }
            for path in biggest
        ],
    }


def cmd_modules(args: argparse.Namespace) -> int:  # noqa: ARG001 - 统一签名
    mem = _load_mem()
    mem._reconfigure_stdio()
    junit = _junit_by_file()
    rows: list[dict[str, Any]] = []
    for directory, family, rule in FAMILIES:
        for path in sorted((REPO / directory).glob("*.py")):
            record: dict[str, Any] = {
                "path": f"{directory}/{path.name}",
                "family": family,
                "bytes": path.stat().st_size,
                "lines": len(path.read_text(encoding="utf-8-sig").splitlines()),
                "parse_ms": _parse_cost(path),
                "测法": rule,
            }
            if family == "pdx":
                dotted = "pdx" if path.name == "__init__.py" else f"pdx.{path.stem}"
                record["module"] = dotted
                record.update(_module_import_cost(dotted, RAW_DIR / "imports"))
                record["读数"] = (
                    f"import {record['import_s']}s / sampled RSS {record['import_peak_rss_mb']}MiB"
                )
            elif family == "tests":
                stats = junit.get(path.stem)
                if stats:
                    record.update(stats)
                    record["读数"] = f"套件内 {stats['tests_s']}s / {stats['n_tests']} 条"
                else:
                    record["读数"] = "未在全量套件里跑到（junit xml 缺该文件）"
                    record["豁免理由"] = "本卡的全量套件读数里没有该文件的用例（新增或被跳过）"
            else:
                record["读数"] = (
                    f"AST 解析 {record['parse_ms']}ms / {record['lines']} 行"
                    f"（非包脚本，导入即执行 ⇒ 不测导入成本）"
                )
                record["豁免理由"] = (
                    "一次性探针/CI/剖析脚本：不是包、没有稳定导入入口，导入即执行会真跑副作用；"
                    "AST 成本不能证明运行成本；实际执行证据另见 profile、CLI 与基准测试报告"
                )
            rows.append(record)
    payload = {
        "口径": {
            "分母": dict(Counter(row["family"] for row in rows)),
            "导入成本含义": "import 的是「该模块 + 它的全部依赖」的墙钟与峰值（不是边际成本）；"
            "边际成本用 --profile / -X importtime 另测",
            "测试模块耗时": "全量套件 junit xml 逐文件聚合（并行下含等待，绝对值偏高，用于**排名**）",
            "解析成本": "compile() 三次取最小，与执行无关",
        },
        "模块": rows,
        "统计": {
            "件数": len(rows),
            "有运行时读数": sum(
                1
                for row in rows
                if row["family"] in {"pdx", "tests"} and "import_s" not in row and "tests_s" in row
            ),
            "pdx 导入读数": sum(1 for row in rows if "import_s" in row),
            "tests 套件读数": sum(1 for row in rows if "tests_s" in row),
            "仪器层": instrument_layer(),
        },
    }
    MODULES_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[perf] 模块台账写入 {MODULES_JSON}（{len(rows)} 件）")
    return 0


def _synthetic(pct: float) -> dict[str, Any]:
    """合成一份「基线/现测」同构 json：一条不动、一条墙钟涨、一条峰值内存涨。"""

    def block(value: float) -> dict[str, Any]:
        return {"n": 3, "median": value, "min": value, "max": value, "spread_pct": 0.0}

    moved_wall = 10.0 * (1.0 + pct / 100.0)
    moved_mem = 100.0 * (1.0 + pct / 100.0)
    return {
        "用例": {
            "fake.ok": {"group": "cli", "wall_s": block(10.0), "peak_hwm_mb": block(100.0)},
            "fake.wall-up": {
                "group": "cli",
                "wall_s": block(moved_wall),
                "peak_hwm_mb": block(100.0),
            },
            "fake.mem-up": {"group": "cli", "wall_s": block(10.0), "peak_hwm_mb": block(moved_mem)},
        }
    }


def cmd_selftest(args: argparse.Namespace) -> int:
    """**护栏有牙演示**：合成基线 + 四档增幅，验证「超 +10% 判红」真的红、且只在 --ci 下红。

    这一条是「护栏建议」不是空话的证据：拿合成数据把 ``compare_to_baseline`` +
    ``cmd_check`` 的判红路径与退出码跑一遍（阈值 10.0 是开区间：正好 +10% **不**红）。
    """
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_path = out_dir / "selftest-baseline.json"
    base_path.write_text(
        json.dumps(_synthetic(0.0), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    failures: list[str] = []
    for pct, expect_red in ((5.0, 0), (10.0, 0), (10.1, 2), (30.0, 2)):
        cur_path = out_dir / f"selftest-current-{pct}.json"
        cur_path.write_text(
            json.dumps(_synthetic(pct), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        rows = compare_to_baseline(
            json.loads(base_path.read_text(encoding="utf-8")), _synthetic(pct)
        )
        red = [row for row in rows if row["verdict"] == "红"]
        code_ci = cmd_check(
            argparse.Namespace(
                baseline=str(base_path), current=str(cur_path), threshold=GATE_PCT, ci=True
            )
        )
        code_local = cmd_check(
            argparse.Namespace(
                baseline=str(base_path), current=str(cur_path), threshold=GATE_PCT, ci=False
            )
        )
        ok = len(red) == expect_red and code_ci == (1 if expect_red else 0) and code_local == 0
        print(
            f"[selftest] +{pct:>5.1f}%  红项={len(red)}（期望 {expect_red}）  "
            f"CI 退出码={code_ci}（期望 {1 if expect_red else 0}）  本机退出码={code_local}（期望 0）"
            f"  ⇒ {'PASS' if ok else 'FAIL'}"
        )
        if not ok:
            failures.append(f"+{pct}%")
    if failures:
        print(f"[selftest] FAIL：{', '.join(failures)}")
        return 1
    print("[selftest] PASS：判红路径有牙，且本机口径永不判红")
    return 0


def cmd_list(args: argparse.Namespace) -> int:  # noqa: ARG001 - 统一签名
    for case in all_cases():
        print(f"{case['group']:<7} {case['tier']:<3} {case['id']:<24} {' '.join(case['argv'])}")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    """把 %TEMP% 下的原始产物清掉（重跑前用；入库件不动）。"""
    if args.raw_dir:
        target = Path(args.raw_dir)
    else:
        target = RAW_DIR
    if target.exists():
        shutil.rmtree(target)
        print(f"[perf] 已清 {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="perf_baseline", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出用例表")

    run = sub.add_parser("run", help="跑用例（原始读数落 %%TEMP%%）")
    run.add_argument("--group", default="cli", choices=["cli", "suite", "shards", "all"])
    run.add_argument("--rounds", default="auto", help="轮数或 auto")
    run.add_argument("--only", nargs="*", default=None, help="只跑这些用例 id")
    run.add_argument("--allow-concurrent", action="store_true", help="不等安静，照跑并留痕")
    run.add_argument("--wait-quiet-s", type=float, default=WAIT_QUIET_S)

    summarize = sub.add_parser("summarize", help="汇总成基线 json")
    summarize.add_argument("--out", default=None)

    check = sub.add_parser("check", help="护栏对照（超基线 +10%% 判红）")
    check.add_argument("--baseline", default=str(BASELINE_JSON))
    check.add_argument(
        "--current", default=None, help="现测 json（不给 = 用 %%TEMP%% 原始读数现算）"
    )
    check.add_argument("--threshold", type=float, default=GATE_PCT)
    check.add_argument("--ci", action="store_true", help="CI 口径：超阈值退出码 1")

    sub.add_parser("modules", help="按当前目录生成模块台账")

    selftest = sub.add_parser("selftest", help="护栏有牙演示（合成数据，判红路径 + 退出码）")
    selftest.add_argument("--out", default=str(RAW_DIR))

    clean = sub.add_parser("clean", help="清 %%TEMP%% 原始产物")
    clean.add_argument("--raw-dir", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    handlers = {
        "list": cmd_list,
        "run": cmd_run,
        "summarize": cmd_summarize,
        "check": cmd_check,
        "modules": cmd_modules,
        "selftest": cmd_selftest,
        "clean": cmd_clean,
    }
    handler = handlers[args.cmd]
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
