"""Snapshot creation, discovery, comparison, and verification commands."""

from __future__ import annotations

import json
from collections import deque
from itertools import zip_longest
from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime.
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.table import Table

from pdx import (
    snapshot,
    version_contracts,
)

from . import common
from .common import EXIT_FAILED, console, require_workspace
from .common import READ_ERRORS as _READ_ERRORS
from .common import fail as _fail
from .common import relative as _relative
from .common import require_file as _require_file
from .common import write_json as _write_json


def _load_snapshot(path: Path) -> snapshot.Snapshot:
    """读快照。文件损坏属前置条件缺失，退出码 2。"""
    try:
        snap = snapshot.Snapshot.load(path)
        snap.require_version()
        return snap
    except _READ_ERRORS as exc:
        _fail(f"快照无法读取：{_relative(path)}（{type(exc).__name__}: {exc}）")


def _snapshot_output_path(target: str, *, compact: bool) -> Path:
    """返回创建命令的明确输出路径，不走读取时的回退规则。"""
    suffix = ".compact.json" if compact else ".json"
    return snapshot.SNAPSHOT_DIR / f"{target}{suffix}"


def snap_create(
    label: Annotated[str | None, typer.Option("--label", help="快照名（默认为游戏版本号）")] = None,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="精简模式：本地化只留计数与指纹，可入库"),
    ] = False,
) -> None:
    """生成当前版本快照，写入 tools/out/snapshots/。

    默认生成完整快照，供本机分析使用。``--compact`` 保留结构域，
    将本地化条目压缩为计数与指纹，便于随仓库分发和比较版本变化。
    实际体积和条目数取决于当前游戏版本，以生成结果为准。
    """
    require_workspace()
    common.require_game()
    snap = snapshot.build(compact=compact, verbose=True)
    target = label or snap.version_label.replace("/", "-")
    # 创建命令必须显式选择输出口径；snapshot_path() 为读取场景提供
    # 完整→精简回退，不能用于写入，否则完整快照会覆盖同名 .compact.json。
    path = _snapshot_output_path(target, compact=compact)
    snap.write(path)

    counts = snap.counts()
    console.print(f"[green]已写入[/] {escape(_relative(path))}")
    console.print(
        f"域 {len(snap.sections)} 个，条目总计 {sum(counts.values()):,}，"
        f"字节 {path.stat().st_size:,}"
    )

    table = Table(show_lines=False)
    table.add_column("域")
    table.add_column("项", justify="right")
    table.add_column("条目", justify="right", style="cyan")
    for section, body in snap.sections.items():
        table.add_row(
            escape(section),
            f"{len(body):,}",
            f"{sum(len(names) for names in body.values()):,}",
        )
    console.print(table)


def snap_list() -> None:
    """列出已有快照及其规模。"""
    require_workspace()
    paths = snapshot.list_snapshots()
    if not paths:
        console.print("[yellow]尚无快照。先运行 `v3 snapshot create`。[/]")
        return

    table = Table(show_lines=False)
    table.add_column("快照")
    table.add_column("版本")
    table.add_column("条目", justify="right", style="cyan")
    table.add_column("字节", justify="right")
    for path in paths:
        # 单份快照读不了不该让整个列表失败（旧脚本也是这样），但必须把
        # 异常类型与消息打出来，而不是显示成一个空行。
        try:
            snap = snapshot.Snapshot.load(path)
        except _READ_ERRORS as exc:
            table.add_row(
                escape(path.name),
                "[red]读取失败[/]",
                "—",
                escape(f"{type(exc).__name__}: {exc}"),
            )
            continue
        if snap.version_label != f"release/{version_contracts.CURRENT_VERSION}":
            continue
        total = sum(len(names) for body in snap.sections.values() for names in body.values())
        table.add_row(
            escape(path.name),
            escape(snap.version_label),
            f"{total:,}",
            f"{path.stat().st_size:,}",
        )
    if not table.rows:
        console.print("[yellow]尚无当前版本快照。先运行 `v3 snapshot create`。[/]")
        return
    table.title = f"共 {len(table.rows)} 份快照"
    console.print(table)


def snap_diff(
    older: Annotated[str, typer.Argument(help="旧快照名（不含 .json）")],
    newer: Annotated[str, typer.Argument(help="新快照名")],
    detail: Annotated[bool, typer.Option("--detail", help="列出增删明细")] = False,
    json_out: Annotated[Path | None, typer.Option("--json", help="把差异写入该 JSON 文件")] = None,
) -> None:
    """比对两份快照，列出字段与条目的增删。

    检测到变更**不算失败**（退出码仍为 0）—— 变更是这个命令要报告的事实，
    不是错误。快照文件不存在时退出码 2。
    """
    require_workspace()
    a_path = snapshot.snapshot_path(older)
    b_path = snapshot.snapshot_path(newer)
    for path in (a_path, b_path):
        _require_file(path, "快照", "可用 `v3 snapshot list` 查看已有快照")

    a = _load_snapshot(a_path)
    b = _load_snapshot(b_path)

    if a.compact != b.compact:
        _fail("两份快照的精简口径不同：请使用两个完整快照，或使用两个 --compact 快照再比较。")

    console.rule(f"对比 {a.version_label}  →  {b.version_label}")
    console.print(
        f"A rev [dim]{escape(a.version.get('caligula_rev', '?'))}[/]    "
        f"B rev [dim]{escape(b.version.get('caligula_rev', '?'))}[/]"
    )

    changes = snapshot.compare(a, b)
    if not changes:
        console.print("[green]两份快照完全一致 —— 没有检测到任何字段增删。[/]")
        return

    # 域集合变化会改变比较口径，单独报告差异中的分母变化。
    only_a = sorted(set(a.sections) - set(b.sections))
    only_b = sorted(set(b.sections) - set(a.sections))
    if only_a or only_b:
        console.print(
            f"[yellow]⚠️ 两份快照的**域集合不同**[/] —— 下面的差异里混着格式变化，"
            f"别直接当成原版变化读。\n"
            f"   只有 A 有：{escape('、'.join(only_a) or '（无）')}\n"
            f"   只有 B 有：{escape('、'.join(only_b) or '（无）')}\n"
            f"   可比的是两侧都有的域：{escape('、'.join(sorted(set(a.sections) & set(b.sections))))}"
        )

    summary = snapshot.diff_summary(changes)
    table = Table(title="变更", show_lines=False)
    table.add_column("域")
    table.add_column("项")
    table.add_column("新增", justify="right", style="green")
    table.add_column("删除", justify="right", style="red")
    for change in changes:
        table.add_row(
            escape(change.section),
            escape(change.name),
            f"+{len(change.added)}" if change.added else "—",
            f"-{len(change.removed)}" if change.removed else "—",
        )
    console.print(table)
    console.print(
        f"变更项 {summary['变更项数']} 处，"
        f"新增条目 {summary['新增条目']}，删除条目 {summary['删除条目']}"
    )

    if detail:
        console.rule("明细")
        for change in changes:
            console.print(f"[bold]{escape(change.section)} / {escape(change.name)}[/]")
            for name in change.added:
                console.print(f"  [green]+ {escape(name)}[/]")
            for name in change.removed:
                console.print(f"  [red]- {escape(name)}[/]")

    if json_out is not None:
        _write_json(
            json_out,
            {
                "from": {"版本": a.version, "文件": a_path.name},
                "to": {"版本": b.version, "文件": b_path.name},
                "概览": summary,
                "变更": [
                    {
                        "域": change.section,
                        "名称": change.name,
                        "新增": change.added,
                        "删除": change.removed,
                    }
                    for change in changes
                ],
            },
        )


def _matches_json_text(first: Any, second: Any) -> bool:
    """Compare the two canonical JSON encodings without materializing either."""
    encoder = json.JSONEncoder(ensure_ascii=False, indent=1, sort_keys=True)
    first_chunks = encoder.iterencode(first)
    matches = True
    try:
        for left, right in zip_longest(first_chunks, encoder.iterencode(second)):
            if left != right:
                matches = False
    except TypeError, ValueError, RecursionError:
        # Complete the first encoding if the second raises. An error on the
        # first still takes precedence, as with encoding the values in order.
        deque(first_chunks, maxlen=0)
        raise
    return matches


def snap_verify() -> None:
    """自我一致性检查：同一环境重复生成的快照必须逐字节相同。

    不稳定就退出码 1 —— 快照一抖，diff 里全是噪声，整个机制失去意义。
    """
    require_workspace()
    common.require_game()
    console.print("构建快照两次并比较 …")
    first = snapshot.build()
    second = snapshot.build()

    if _matches_json_text(first.to_dict(), second.to_dict()):
        total = sum(len(names) for body in first.sections.values() for names in body.values())
        console.print("[green]✅ 两次构建结果完全一致 —— 快照是确定性的[/]")
        console.print(f"   域 {len(first.sections)} 个，条目总计 {total:,}")
        return

    console.print("[red]❌ 两次构建结果不同 —— 快照不稳定，diff 会充满噪声[/]")
    for change in snapshot.compare(first, second)[:20]:
        console.print(escape(change.line()))
    raise typer.Exit(EXIT_FAILED)
