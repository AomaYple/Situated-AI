"""Inspect and validate published analysis products."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import typer
from rich.markup import escape
from rich.table import Table

from pdx import (
    analyze,
    config,
    verify,
    version_contracts,
)

from .common import EXIT_FAILED, console, require_workspace
from .common import READ_ERRORS as _READ_ERRORS
from .common import fail as _fail
from .common import relative as _relative

if TYPE_CHECKING:
    from pathlib import Path


def _load_product(path: Path, label: str) -> tuple[dict[str, Any], str]:
    """读一份已落盘的分析产物。

    两种失败都算前置条件缺失：文件不在（还没跑过 analyze），或文件在但读不
    出来（截断、写坏、根本不是 JSON）。都以退出码 2 终止并说明原因。
    """
    if not path.is_file():
        _fail(f"缺少产物：{_relative(path)}（请先运行 `v3 analyze` 生成{label}）")
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except _READ_ERRORS as exc:
        _fail(f"产物无法读取：{_relative(path)}（{type(exc).__name__}: {exc}）")
    if not isinstance(data, dict):
        _fail(f"产物结构异常：{_relative(path)}（顶层应为对象，实为 {type(data).__name__}）")
    return data, hashlib.sha256(raw).hexdigest()


def _load_game_product(path: Path) -> tuple[dict[str, Any], str]:
    game, digest = _load_product(path, "游戏本体分析")
    overview = game.get("概览")
    version = overview.get("版本") if isinstance(overview, dict) else None
    branch = version.get("caligula_branch") if isinstance(version, dict) else None
    expected = f"release/{version_contracts.CURRENT_VERSION}"
    if branch != expected:
        _fail(f"分析产物的原版版本不符：期望 {expected}，实际 {branch!r}。请重新运行 v3 analyze。")
    return game, digest


def _paired_cross_product(path: Path, game_digest: str, mods_digest: str) -> dict[str, Any] | None:
    """Return cross-analysis only when its publication matches the reports just read."""
    try:
        pairing = json.loads(path.with_name(analyze.CROSS_PAIRING_NAME).read_text(encoding="utf-8"))
        if (
            not isinstance(pairing, dict)
            or pairing.keys() != {"game", "mods", "cross"}
            or pairing["game"] != game_digest
            or pairing["mods"] != mods_digest
        ):
            return None
        raw = path.read_bytes()
        if pairing["cross"] != hashlib.sha256(raw).hexdigest():
            return None
        cross = json.loads(raw.decode("utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return None
    return cross if isinstance(cross, dict) else None


def _describe(value: object) -> tuple[str, str]:
    """把一个 JSON 值描述成「类型 + 规模」。标量直接给值，长值截断。"""
    if isinstance(value, dict):
        return "字典", f"{len(value):,} 个键"
    if isinstance(value, list):
        return "列表", f"{len(value):,} 项"
    text = str(value)
    return type(value).__name__, text if len(text) <= 60 else f"{text[:59]}…"


def _structure_table(title: str, data: Any) -> Table:
    """把一层 JSON 对象的字段结构渲染成表格。"""
    table = Table(title=title or None, show_lines=False)
    table.add_column("字段")
    table.add_column("类型", style="dim")
    table.add_column("规模", justify="right", style="cyan")
    for key, value in data.items():
        kind, scale = _describe(value)
        table.add_row(escape(str(key)), kind, escape(scale))
    return table


def _size_text(path: Path) -> str:
    """文件大小的可读形式。文件不在就返回破折号 —— 表里不能因此缺行。"""
    if not path.is_file():
        return "—"
    n = path.stat().st_size
    return f"{n / 1048576:.2f} MB" if n > 1048576 else f"{n / 1024:.0f} KB"


def check_outputs_cmd() -> None:
    """核验已落盘的分析产物是否与断言注册表一致。

    与 verify 的分工：verify 核验**游戏本体**（游戏里到底有多少条目），
    本命令核验**产物**（落盘的 JSON 有没有把它写对）。两者检查的是不同
    问题，但共用同一份注册表 ``verify.CLAIMS``。

    历史教训：早先这个脚本自己维护了一套写死的期望值，它的
    ``on_actions = 263`` 与注册表里的 264 长期冲突，又因为跑在 pytest
    管辖之外而无人发现。现在这种结构性分歧不可能再出现。

    缺少产物时退出码 2（先跑 `v3 analyze`），不一致时退出码 1。
    """
    require_workspace()
    game, _ = _load_game_product(config.OUT_GAME / "游戏本体.json")
    mods, _ = _load_product(config.OUT_MODS / "mod.json", "mod 分析")

    results = verify.verify_products(game, mods, {})
    checkable = [r for r in results if r.claim.kind in verify.product_kinds()]

    table = Table(title="分析产物核验", show_lines=False)
    table.add_column("", width=2, justify="center")
    table.add_column("断言")
    table.add_column("实得", justify="right", style="cyan")
    table.add_column("期望", justify="right", style="dim")
    for result in checkable:
        table.add_row(
            "✅" if result.ok else "❌",
            escape(result.claim.text),
            escape(str(result.actual)),
            escape(str(result.claim.expected)),
        )
    console.print(table)

    failed = [r for r in checkable if not r.ok]
    skipped = len(results) - len(checkable)
    console.print(
        f"\n产物可核验 {len(checkable)} / {len(results)} 条断言"
        f"（其余 {skipped} 条需单独运行对应提取器，本命令不覆盖）"
    )

    if failed:
        console.print(f"[red]不一致 {len(failed)} 条：[/]")
        for result in failed:
            console.print(f"  ❌ [{escape(result.claim.id)}] {escape(result.line())}")
        raise typer.Exit(EXIT_FAILED)

    console.print("[green]产物与断言注册表完全一致 ✅[/]")


def show_cmd() -> None:
    """转储已落盘产物的结构与规模。

    列出产出文件、各 JSON 的顶层字段、以及「一个 common 目录」和
    「一个 mod」记录了哪些内容 —— 改动提取逻辑后用它快速确认产物里
    到底有什么。产物不存在时退出码 2。
    """
    require_workspace()
    products = [
        ("游戏本体 JSON", config.OUT_GAME / "游戏本体.json"),
        ("mod JSON", config.OUT_MODS / "mod.json"),
    ]
    game, game_digest = _load_game_product(products[0][1])
    mods, mods_digest = _load_product(products[1][1], "mod 分析")
    cross_path = config.OUT_CROSS / "交叉.json"
    cross = _paired_cross_product(cross_path, game_digest, mods_digest)
    if cross is not None:
        products.append(("交叉 JSON", cross_path))

    files = [
        *products,
        ("游戏本体报告", config.REPORTS / "游戏本体分析.md"),
        ("mod 报告", config.REPORTS / "mod分析.md"),
    ]
    table = Table(title="产出文件", show_lines=False)
    table.add_column("名称")
    table.add_column("大小", justify="right", style="cyan")
    table.add_column("路径", style="dim")
    for label, path in files:
        table.add_row(escape(label), _size_text(path), escape(_relative(path)))
    console.print(table)

    console.print(_structure_table("游戏本体 JSON —— 顶层字段", game))

    common = game.get("common") or {}
    if common:
        # 样例取 buildings：它的字段最全。取不到就退回第一个目录 ——
        # 旧的 show_outputs.py 写的是 mods["各mod"][1]，产物结构一变就
        # IndexError，属于把「当前数据长什么样」硬编码进了展示代码。
        sample = "buildings" if "buildings" in common else next(iter(common))
        console.print(f"\n  · common 每个目录记录的内容（样例：{escape(sample)}）")
        console.print(_structure_table("", common[sample]))

        entries = sum(len(body.get("条目", [])) for body in common.values())
        fields = sum(len(body.get("字段", {})) for body in common.values())
        console.print(f"      common 条目名合计 {entries:,}")
        console.print(f"      common 字段名合计 {fields:,}")

    console.print(_structure_table("mod JSON —— 顶层字段", mods))

    mod_rows = mods.get("各mod") or []
    if mod_rows:
        first = mod_rows[0]
        name = first.get("名称") or first.get("目标") or "—"
        console.print(f"\n  · 每个 mod 记录的内容（样例：{escape(str(name))}）")
        console.print(_structure_table("", first))

    if cross is not None:
        console.print(_structure_table("交叉 JSON —— 顶层字段", cross))
    else:
        console.print("[dim]当前没有同批次的交叉分析结果。[/]")
