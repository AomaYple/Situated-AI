"""全量分析端到端性能剖析。

用法::

    v3prof full                    # 整条流水线跑一次，回答「总共花在哪」
    v3prof stages --top 25         # 逐阶段冷缓存剖析，定位到具体函数
    v3prof walkaudit               # 文件系统被重复遍历了多少次
    v3prof prefixaudit             # 原版功能前缀扫描的范围与耗时

设计原则
--------
**不自己写计时框架**，只用成熟库：

* ``cProfile`` / ``pstats``   精确到函数级的累计耗时与调用次数
* ``pyinstrument``            调用树，直接看出时间花在哪条路径上
* ``typer`` / ``rich``        命令行与表格渲染

与 ``tools/diag/`` 的区别：``diag/`` 是一次性排障脚本的存档，
``prof/`` 是可重复运行、产出可对比报告的正式工具。
"""

from __future__ import annotations

import cProfile
import os
import pstats
import sys
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from pyinstrument import Profiler
from rich.console import Console
from rich.table import Table

from pdx import analyze, cache, config
from pdx.mods import vanilla_prefix_count
from pdx.scan import walk_files

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

app = typer.Typer(add_completion=False, help="Victoria 3 全量分析性能剖析")
console = Console()
OUT = Path(__file__).resolve().parent / "out"


# ── 剖析原语 ────────────────────────────────────────────────
@dataclass
class StageProfile:
    """一个阶段的剖析结果。"""

    label: str
    elapsed: float = 0.0
    profile: cProfile.Profile = field(default_factory=cProfile.Profile)


@contextmanager
def profiled(label: str) -> Iterator[StageProfile]:
    """用 cProfile 包住一段代码。

    结果通过 ``yield`` 出去，调用方自己持有 —— 早先的实现把它塞进模块级
    字典，导致同名 label 静默互相覆盖、异常时仍会写出半截数据、
    还得靠 ``clear()`` 手工重置。
    """
    stage = StageProfile(label=label)
    start = time.perf_counter()
    stage.profile.enable()
    try:
        yield stage
    finally:
        stage.profile.disable()
        stage.elapsed = time.perf_counter() - start


def _stats_table(pr: cProfile.Profile, top: int, title: str) -> Table:
    """把 cProfile 的统计渲染成 rich 表格。

    直接读 ``pstats.Stats.stats`` 这个字典，而不是解析它 ``print_stats``
    出来的文本再 ``split`` —— 后者依赖 pstats 的输出格式，换个 Python
    版本就可能悄悄错位。

    字典结构：``(文件名, 行号, 函数名) -> (原调用数, 总调用数, 自身耗时,
    累计耗时, 调用方)``。
    """
    table = Table(title=title, show_lines=False)
    table.add_column("ncalls", justify="right", style="dim")
    table.add_column("tottime", justify="right")
    table.add_column("cumtime", justify="right", style="cyan")
    table.add_column("函数", style="green", overflow="fold")

    raw = pstats.Stats(pr).stats
    rows = sorted(raw.items(), key=lambda kv: kv[1][3], reverse=True)[:top]
    for (filename, lineno, funcname), (cc, nc, tt, ct, _callers) in rows:
        short = Path(filename).name if filename.startswith(str(config.REPO)) else filename
        table.add_row(
            f"{nc}" if cc == nc else f"{nc}/{cc}",
            f"{tt:.3f}",
            f"{ct:.3f}",
            f"{short}:{lineno}({funcname})",
        )
    return table


def _write_prof(name: str, pr: cProfile.Profile) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.prof"
    pr.dump_stats(str(path))
    return path


def _report(stage: StageProfile, top: int) -> None:
    console.rule(f"[bold]{stage.label}[/]  {stage.elapsed:.2f} 秒")
    console.print(
        _stats_table(stage.profile, top, f"{stage.label} —— 按累计耗时排序")
    )
    path = _write_prof(stage.label, stage.profile)
    console.print(f"[dim]原始剖析数据：{path.relative_to(config.REPO)}\n")


def _pipeline() -> list[tuple[str, Callable[[], Any]]]:
    """端到端流水线的阶段序列（与 ``v3 analyze`` 保持一致）。

    刻意**不在这里预热**：早先的实现为了构造后两个阶段的闭包，会先跑一遍
    ``game_analysis``/``mods_analysis``，导致 ``full`` 把整条流水线跑两遍。
    现在闭包之间通过 ``ctx`` 传递中间结果，每个阶段只在被计时时执行。
    """
    ctx: dict[str, Any] = {}

    def run_game() -> Any:
        ctx["ga"] = result = analyze.game_analysis()
        return result

    def run_mods() -> Any:
        ctx["ma"] = result = analyze.mods_analysis()
        return result

    def run_cross() -> Any:
        ctx["ca"] = result = analyze.cross_analysis(ctx["ma"])
        return result

    def run_write() -> Any:
        return analyze.write_reports(ctx["ga"], ctx["ma"], ctx["ca"])

    return [
        ("game_analysis", run_game),
        ("mods_analysis", run_mods),
        ("cross_analysis", run_cross),
        ("write_reports", run_write),
    ]


def _run_all() -> None:
    """跑一遍完整流水线（供 pyinstrument 与冷热对比复用）。"""
    ga = analyze.game_analysis()
    ma = analyze.mods_analysis()
    ca = analyze.cross_analysis(ma)
    analyze.write_reports(ga, ma, ca)


# ── 子命令 ──────────────────────────────────────────────────
@app.command()
def full(
    top: int = typer.Option(30, help="每个表显示的函数行数"),
    tree: bool = typer.Option(True, help="同时输出 pyinstrument 调用树"),
) -> None:
    """整条流水线跑一次（冷缓存），回答「总共花在哪」。"""
    cache.clear()
    with profiled("端到端") as stage:
        _run_all()

    _report(stage, top)
    console.print(f"解析缓存：{cache.stats()}")

    if not tree:
        return

    # 第二遍用 pyinstrument。**跑的是同一段 _run_all**，
    # 早先这里手写了一遍流水线且漏掉 write_reports，两遍工作量不可比。
    cache.clear()
    prof = Profiler(interval=0.0005)
    prof.start()
    _run_all()
    prof.stop()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e2e.pyisession").write_bytes(prof.output_session().to_json().encode())
    console.rule("[bold]pyinstrument 调用树")
    console.print(prof.output_text(unicode=True, color=False, show_all=False))


@app.command()
def stages(
    top: int = typer.Option(25, help="每个表显示的函数行数"),
    only: str = typer.Option("", help="只剖析名字含该子串的阶段"),
) -> None:
    """逐阶段冷缓存剖析，定位到具体函数。

    ⚠️ **读结果时必须知道的局限**：每个阶段都在冷缓存下单独跑，因此
    ``write_reports`` 会把「重新解析全部文件」也计入 —— 真实流水线里
    它跑在 ``game_analysis`` 之后，缓存是热的。实测差距很大::

        阶段隔离下 write_reports   42.6 秒
        真实流水线里 write_reports  5.4 秒

    也就是说：这个命令适合定位**解析类**阶段的内部热点，
    不适合判断某个阶段在整条流水线里的实际占比。
    要看真实占比用 ``full``。
    """
    results: list[StageProfile] = []
    for name, fn in _pipeline():
        if only and only not in name:
            continue
        # 每个阶段都从冷缓存开始 —— 否则后一个阶段只是在读前一个阶段的缓存，
        # 测出来的是「缓存命中有多快」，不是这个阶段本身有多贵。
        cache.clear()
        with profiled(name) as stage:
            fn()
        results.append(stage)

    for stage in results:
        _report(stage, top)


@app.command()
def walkaudit() -> None:
    """统计全量分析期间文件系统被重复遍历的程度。

    做法是把 ``os.scandir`` 换成带计数与**调用方归属**的包装 ——
    直接量真实调用，而不是读代码估算。

    判据是「目录被扫了几次 / 一共有几个目录」：
    比值 ≈ 1 说明每个目录只扫一遍，已经最优；比值 > 3 说明存在重复遍历。
    只看「哪个目录被扫得最多」还不够，得知道**是哪段代码在扫**，
    所以要记调用栈。
    """
    real_scandir = os.scandir
    visits: Counter = Counter()
    callers: dict[str, Counter] = {}

    def counting_scandir(path=".", *args, **kwargs):  # type: ignore[no-untyped-def]
        key = os.path.normcase(str(Path(path).resolve()))
        visits[key] += 1
        # 取调用方中第一个属于本仓库的帧
        for frame in reversed(traceback.extract_stack()[:-1]):
            if str(config.REPO) in frame.filename and "prof_e2e" not in frame.filename:
                rel = Path(frame.filename).relative_to(config.REPO)
                callers.setdefault(key, Counter())[f"{rel}:{frame.lineno}"] += 1
                break
        return real_scandir(path, *args, **kwargs)

    os.scandir = counting_scandir  # type: ignore[assignment]
    try:
        cache.clear()
        start = time.perf_counter()
        _run_all()
        elapsed = time.perf_counter() - start
    finally:
        os.scandir = real_scandir  # type: ignore[assignment]

    total = sum(visits.values())
    unique = len(visits)
    rescan = sum(v - 1 for v in visits.values() if v > 1)

    table = Table(title="文件系统遍历审计", show_lines=False)
    table.add_column("指标")
    table.add_column("值", justify="right", style="cyan")
    table.add_row("scandir 总调用", f"{total:,}")
    table.add_row("涉及的目录数", f"{unique:,}")
    table.add_row("重复扫描次数", f"{rescan:,}")
    table.add_row("平均每目录扫描次数", f"{total / unique:.2f}" if unique else "-")
    table.add_row("全量分析耗时", f"{elapsed:.2f} 秒")
    console.print(table)

    console.print("\n[bold]被扫得最多的 15 个目录[/]")
    hot = Table(show_lines=False)
    hot.add_column("次数", justify="right", style="red")
    hot.add_column("目录", style="green", overflow="fold")
    hot.add_column("主要调用方", style="dim", overflow="fold")
    for path, n in visits.most_common(15):
        who = ", ".join(f"{k}×{v}" for k, v in callers.get(path, Counter()).most_common(2))
        hot.add_row(str(n), path.replace(str(config.ROOT), "<ROOT>"), who)
    console.print(hot)


@app.command()
def prefixaudit() -> None:
    """审计「原版功能前缀」扫描的范围与耗时。

    这一项曾是个隐形的时间黑洞：``vanilla_prefix_count`` 按扩展名
    ``.txt`` 扫遍了整个 ``game/`` 树，把 ``config.ASSET_DIRS`` 里
    明确定为「只统计、不解析」的资产文件也解析了。实测 3,756 个
    ``.txt`` 中有 374 个属资产目录，其中单个 24.5 MB 的生成文件就要
    8.5 秒 —— 而结果恒为空。修好范围后这里会显示为 0 个越界文件。
    """
    root = config.GAME
    everything = list(walk_files(root, suffix=".txt"))
    outside = [
        f for f in everything
        if not config.is_scriptable(f.path.relative_to(root).parts, f.suffix)
    ]

    # 这些文件**不该**被解析；只统计它们的规模，不打开
    waste_bytes = sum(f.size for f in outside)

    cache.clear()
    start = time.perf_counter()
    result = vanilla_prefix_count()
    elapsed = time.perf_counter() - start

    table = Table(title="原版功能前缀扫描审计", show_lines=False)
    table.add_column("指标")
    table.add_column("值", justify="right", style="cyan")
    table.add_row("扫描范围内的 .txt", f"{len(everything) - len(outside):,}")
    table.add_row("范围外的资产 .txt（已排除）", f"{len(outside):,}")
    table.add_row("排除掉的体积", f"{waste_bytes / 1048576:.1f} MB")
    table.add_row("冷缓存耗时", f"{elapsed:.2f} 秒")
    table.add_row("命中的前缀", f"{dict(result) or '（无，符合预期）'}")
    console.print(table)

    if outside:
        console.print("\n[bold]被排除的资产文件（按体积前 10）[/]")
        big = Table(show_lines=False)
        big.add_column("MB", justify="right", style="red")
        big.add_column("路径", style="green", overflow="fold")
        for f in sorted(outside, key=lambda x: -x.size)[:10]:
            big.add_row(
                f"{f.size / 1048576:.2f}",
                str(f.path.relative_to(root)).replace("\\", "/"),
            )
        console.print(big)


if __name__ == "__main__":  # pragma: no cover - 手工运行入口
    sys.exit(app())
