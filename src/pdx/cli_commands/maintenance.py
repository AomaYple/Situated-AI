"""Commands for dependency locks, coverage checks, and local caches."""

from __future__ import annotations

import time

import typer
from rich.markup import escape
from rich.table import Table

from pdx import (
    cache,
    covgate,
    lockfile,
)

from .common import EXIT_FAILED, console
from .common import fail as _fail


def lock_cmd(
    write: bool = typer.Option(
        False, "--write", help="从 Windows CPython 环境重写 requirements.lock"
    ),
) -> None:
    """核对已安装的运行期和 `dev` 依赖闭包。

    从 `pyproject.toml` 的声明出发，按环境标记沿已安装包的
    `Requires-Dist` 展开闭包，并核对版本约束。默认与 `requirements.lock` 对账，
    有差异时退出码为 1。Windows 开发环境可用 `--write` 更新锁文件。
    """
    if write:
        try:
            count = lockfile.write()
        except (OSError, RuntimeError, ValueError) as exc:
            _fail(f"依赖锁写入失败：{exc}", EXIT_FAILED)
        console.print(f"[green]已写入 {lockfile.LOCK_FILE}：{count} 条[/]")
        return

    try:
        lockfile.validate_python_version()
    except (ModuleNotFoundError, RuntimeError, ValueError) as exc:
        _fail(f"依赖锁拒绝当前解释器：{exc}", EXIT_FAILED)
    try:
        actual = lockfile.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        _fail(f"依赖锁生成失败：{exc}", EXIT_FAILED)

    locked = lockfile.read()
    if not locked:
        _fail(f"读不到 {lockfile.LOCK_FILE}（或它不是本工具生成的）—— 先跑 `v3 lock --write`")

    drift = lockfile.compare(actual, locked)
    if not drift:
        console.print(f"[green]{lockfile.LOCK_FILE} 与当前环境一致（{len(locked)} 条）[/]")
        return

    table = Table(title=f"锁与环境有 {len(drift)} 处不一致", show_lines=False)
    table.add_column("包")
    table.add_column("类别")
    table.add_column("锁", style="dim")
    table.add_column("当前", style="cyan")
    for d in drift:
        table.add_row(
            escape(d.name), escape(d.kind), escape(d.locked or "—"), escape(d.actual or "—")
        )
    console.print(table)
    console.print("[yellow]确认过是有意升级/降级后，跑 `v3 lock --write` 更新锁[/]")
    raise typer.Exit(EXIT_FAILED)


def cov_cmd(
    check_only: bool = typer.Option(False, "--check-only", help="只读上次的数据，不重跑测试"),
    top: int = typer.Option(0, "--top", help="只列出覆盖率最低的 N 个模块（0 = 全列）"),
) -> None:
    """跑覆盖率门禁：整体 86% 之外，再按**核心模块**逐条核对下限。

    为什么整体门禁不够：删掉 200 行 `cli.py` 的测试、再给某个小模块补 200 行
    测试，总数可以纹丝不动，而最要紧的那几个模块（解析器、断言注册表、
    归属标记、表格生成）已经悄悄退化了。口径与下限见 `pdx.covgate`。

    `--check-only` 读上次 `v3 cov` 写下的 `tools/out/cov.json`（不重跑，秒级）；
    完整覆盖率使用自适应并行预算，实际耗时见回归记录；这条**不进 CI**（CI 上没有游戏，
    覆盖率口径完全不同，理由见 `.github/workflows/ci.yml` 的文件头注释）。
    """
    code = 0
    if not check_only:
        code = covgate.run_pytest()
        if code != 0:
            console.print(f"[yellow]pytest 退出码 {code} —— 先让测试全绿再看覆盖率[/]")

    rows = covgate.load_coverage()
    if not rows:
        _fail(f"读不到覆盖率数据（{covgate.COV_JSON}）—— 先跑一次 `v3 cov`（不带 --check-only）")

    display_rows = sorted(rows, key=lambda r: r.percent)[:top] if top else rows

    table = Table(title="模块覆盖率（分支）", show_lines=False)
    table.add_column("模块")
    table.add_column("覆盖率", justify="right", style="cyan")
    table.add_column("下限", justify="right")
    table.add_column("语句", justify="right", style="dim")
    table.add_column("", width=2, justify="center")
    for row in display_rows:
        floor = row.floor
        table.add_row(
            escape(row.module),
            f"{row.percent:.1f}%",
            "—" if floor is None else f"{floor:.0f}%",
            f"{row.statements:,}",
            "" if floor is None else ("✅" if row.ok else "❌"),
        )
    console.print(table)

    failed = covgate.check(rows)
    gone = covgate.missing_floors(rows)
    overall = covgate.total_percent(rows)
    floor_overall = covgate.overall_floor()
    below_overall = overall + 1e-9 < floor_overall
    console.print(
        f"整体 {overall:.2f}%    低于下限 {len(failed)} 个模块"
        f"    [dim]（整体下限 {floor_overall:.0f}% 读自 pyproject.toml，"
        f"模块下限表 {len(covgate.FLOORS)} 个，见 pdx.covgate）[/]"
    )
    if below_overall:
        console.print(f"  [red]❌ 整体 {overall:.2f}% < {floor_overall:.0f}%[/]")
    for row in failed:
        console.print(f"  [red]❌ {escape(row.module)}：{row.percent:.1f}% < {row.floor:.0f}%[/]")
    if gone:
        console.print(
            f"[yellow]下限表里这些模块这次没有数据（改名或删了？）：{escape(', '.join(gone))}[/]"
        )
    if code != 0 or failed or below_overall or gone:
        raise typer.Exit(EXIT_FAILED)


def cache_cmd(
    clear: bool = typer.Option(False, "--clear", help="清空磁盘缓存"),
    show_entries: bool = typer.Option(False, "--list", help="列出最旧的若干条目"),
) -> None:
    """解析缓存的状态与清理。

    全量分析、`v3 tables`、`v3 verify` 都要解析 6 千个脚本文件；内存缓存只管
    一次进程内的重复，**跨进程（`pytest -n auto` 的 16 个 worker、每次重跑）
    靠的是磁盘层**。缓存放在系统临时目录，按仓库路径分桶，不往仓库里塞文件。

    键 = `sha256(路径 + mtime + 大小 + 引擎指纹)`：源文件变了、解析器代码变了，
    旧条目自动失效，不需要谁记得清缓存。口径见 `pdx.cache` 模块文档。
    """
    mem = cache.stats()
    disk = cache.disk_counts()
    table = Table(title="解析缓存", show_lines=False)
    table.add_column("层")
    table.add_column("指标")
    table.add_column("值", justify="right", style="cyan")
    table.add_row("内存", "条目", f"{mem['条目']:,}")
    table.add_row("内存", "命中 / 未命中", f"{mem['命中']:,} / {mem['未命中']:,}")
    table.add_row("磁盘", "可命中条目", f"{disk['条目']:,}")
    table.add_row("磁盘", "分片 / 占用", f"{disk['分片']} / {disk['字节'] / 1048576:.1f} MB")
    table.add_row("磁盘", "状态", cache.describe_state())
    console.print(table)

    if show_entries:
        for path, mtime, size in sorted(cache.disk_entries(), key=lambda item: item[1])[:20]:
            console.print(
                f"  {time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))}  "
                f"{size / 1024:8.1f} KB  {escape(str(path))}"
            )

    if clear:
        removed = cache.clear_disk()
        console.print(f"[green]已清空磁盘缓存：{removed} 个分片[/]")
