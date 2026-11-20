"""Static audit commands for the situated decision system."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime.
from typing import Annotated

import typer
from rich.table import Table

from pdx import (
    config,
    situated,
)
from pdx.situated import inventory as situated_inventory

from . import common
from .common import EXIT_FAILED, console
from .common import fail as _fail
from .common import relative as _relative
from .common import write_json as _write_json


def situated_audit_cmd() -> None:
    """检查处境行动内核的源、关系、预算和生产接线合同。"""
    common.require_game(optional=True)
    try:
        problems = situated.audit.check()
        coverage = situated.audit.report()
    except (OSError, ValueError) as exc:
        _fail(f"处境行动内核审计失败：{exc}", EXIT_FAILED)
    if problems:
        _fail("处境行动内核审计失败：\n" + "\n".join(problems), EXIT_FAILED)
    model = situated.load_model()
    label = (
        "处境行动内核审计通过"
        if coverage.status == "complete"
        else "处境行动内核审计完成，覆盖仍未收口"
    )
    color = "green" if coverage.status == "complete" else "yellow"
    console.print(
        f"[{color}]{label}[/]：{len(model.facts)} 个事实、"
        f"{len(model.actions)} 张显式行动卡、{len(model.action_instances)} 个生产行动实例、"
        f"{len(model.production_consumers)} 个生产消费者；覆盖状态 {coverage.status}，"
        f"原版范围状态 {coverage.scope_status}。"
    )
    console.print("证据：静态生成合同；不证明长期游戏行为质量。")


def situated_inventory_cmd(
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", help="盘点 JSON 输出目录；默认写入 tools/out/ci/situated-inventory/"
        ),
    ] = None,
) -> None:
    """生成 K0 原版决策面盘点和旧规则迁移台账。"""
    target = output or (config.OUT / "ci" / "situated-inventory")
    try:
        inventory_path, migration_path = situated_inventory.write(target)
        inventory = situated_inventory.discover()
    except (OSError, ValueError) as exc:
        _fail(f"处境决策面盘点失败：{exc}", EXIT_FAILED)
    console.print(
        f"[green]处境决策面盘点已写入[/]：{_relative(inventory_path)}；{_relative(migration_path)}"
    )
    console.print(
        f"发现 {inventory.discovered_count} 个面，范围哈希 {inventory.scope_hash}；"
        f"状态 {inventory.status_counts}。"
    )
    console.print("证据：K0 静态底本/生产源盘点；pending 不代表功能已实现。")


def situated_report_cmd(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="报告 JSON 输出路径；默认写入 tools/out/ci/"),
    ] = None,
    native: bool = typer.Option(
        False, "--native", help="读取锁定原版并重建生产输出，独立核对全范围映射与原版保护责任"
    ),
) -> None:
    """输出处境行动内核的可追溯合同报告。"""
    common.require_game(optional=not native)
    target = output or (config.OUT / "ci" / "situated-report.json")
    try:
        if native:
            payload = situated.audit.native_report()
        else:
            payload = situated.load_model().contract()
            payload["coverage"] = situated.audit.report().as_dict()
    except (OSError, ValueError) as exc:
        _fail(f"处境行动报告失败：{exc}", EXIT_FAILED)
    _write_json(target, payload)
    console.print(f"[green]处境行动报告已写入[/]：{_relative(target)}")
    console.print("证据：静态生成合同；不证明长期游戏行为质量。")


def situated_explain_cmd() -> None:
    """列出行动卡、消费者和未知回退，供静态审查使用。"""
    try:
        model = situated.load_model()
    except (OSError, ValueError) as exc:
        _fail(f"处境行动解释失败：{exc}", EXIT_FAILED)
    table = Table(title="处境行动卡（生成期合同）", show_lines=False)
    table.add_column("行动")
    table.add_column("领域")
    table.add_column("消费者")
    table.add_column("最大增量", justify="right")
    table.add_column("解释", overflow="fold")
    for action in model.actions:
        consumer = next(item for item in model.consumers if item.id == action.consumer)
        table.add_row(
            action.id,
            action.domain,
            consumer.field,
            f"{action.max_delta:g}",
            action.explanation,
        )
    console.print(table)
    console.print("未知、玩家和不可用路径回退原版；证据类别：simulation/static_check。")
