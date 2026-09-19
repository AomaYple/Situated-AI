"""``common\\static_modifiers\\`` 的逐文件统计。

为什么单独一个模块
------------------
doc 05（`defines与修饰符`）§6.5 有一张 ``| File | Entries | Max entries in one
modifier |`` 表，**曾号称「脚本直接落盘的」而实际无人重跑**：产出它的
PowerShell 脚本早已退休，表还留在文档里（doc 05 §1 至今写着「由脚本机械
生成的表头保持英文（如 … ``File``、``Entries``）」）。

核查结果：``Entries`` 列 68/68 全对，但 ``Max entries`` 列与紧随其上的那句
说明**自相矛盾** —— 数据用的是「块内全部键（**含** ``icon``）」口径
（68/68 命中），而说明写着「**不含** ``icon``」（按那个口径只命中 1/68）。

放这里而不是 :mod:`pdx.defines`：那个模块的自述是「defines 专用提取」，
而静态修饰符是 ``common/static_modifiers/`` 下的另一类数据。混在一起会让
它的 docstring 变成假话 —— 这正是本仓库一直在修的那类问题。
"""

from __future__ import annotations

import re

from . import config
from .cache import parse_cached
from .doc_tables import TableSpec
from .model import Block

#: doc 05 §6.5 的表头
STATIC_TABLE = "| File | Entries | Max entries in one modifier |"

#: 数字片段（用于**自然序**排序）
_NUM = re.compile(r"(\d+)")


def _natural(name: str) -> list[object]:
    """自然序排序键：``10_culture`` 排在 ``101_modifiers`` 之前。

    纯 ``sorted()`` 是 ASCII 序，会把 ``101_modifiers.txt`` 排到
    ``10_culture_...`` **前面** —— 实测生成一次就把整张表的开头挪了位。
    文档原本是人读的顺序（数字按数值大小），所以这里也用数值序。

    只写三行而不是引入 ``natsort``：这是一处排序键，不是一套功能；
    为它加一个运行时依赖不划算（``natsort`` 也没进 dev extra）。
    """
    return [int(x) if x.isdigit() else x for x in _NUM.split(name)]


def static_modifier_stats() -> list[tuple[str, int, int]]:
    """``(文件名, 条目数, 单块最大键数)``，按文件名**自然序**排列。

    两个口径都写明白（它们是这张表最容易被悄悄改掉的地方）：

    * **条目数** = 文件里的顶层块数（``NAME = { ... }``）；
    * **单块最大键数** = 这些块里「键最多那个」的键数，**含 ``icon``**。
      含 ``icon`` 是照数据说话：按「含」算 68/68 与文档一致，按「不含」只
      命中 1/68。文档里那句「不含 ``icon``」是错的，已改。
    """
    base = config.GAME / "common" / "static_modifiers"
    if not base.is_dir():
        return []
    out: list[tuple[str, int, int]] = []
    for path in sorted(
        (p for p in base.rglob("*.txt") if p.is_file()), key=lambda p: _natural(p.name)
    ):
        entries = [
            a
            for a in parse_cached(path).top_assignments
            if not a.is_variable and isinstance(a.value, Block)
        ]
        if not entries:
            continue
        widest = max(len(list(e.value.assignments())) for e in entries)  # type: ignore[union-attr]
        out.append((path.name, len(entries), widest))
    return out


def static_rows() -> list[str]:
    return [f"| `{name}` | {n} | {widest} |" for name, n, widest in static_modifier_stats()]


def doc_table_specs() -> list[TableSpec]:
    """doc 05 §6.5 的表 —— 登记给 ``v3 tables``。"""
    return [TableSpec(name="doc05 静态修饰符逐文件", header=STATIC_TABLE, rows=static_rows)]


__all__ = ["STATIC_TABLE", "doc_table_specs", "static_modifier_stats", "static_rows"]
