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
from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import KeyedTableSpec, TableSpec
from .model import Assignment, Block

if TYPE_CHECKING:
    from pathlib import Path

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


#: doc 05 §3.x：`modifier_type_definitions\` 里**键名前缀**的分布 ——
#: 前缀决定修正符在「修饰符图」里的流动路径（见 `modifier_types.md:1-3`）。
#:
#: doc 17 §21.3 那张两栏并排的表用的是**同一批数字**，所以计数器放在这里共用：
#: 一处改了另一处不会漂（两篇文档写同一个事实，本来就不该各算各的）。
PREFIX_TABLE_HEADER = "| 前缀 | 键数 | 流动含义（据上文推断） |"

#: doc 05 那张表的行键（作者选的 13 行，最后两行是合并行与「其余」）。
_PREFIX_ROWS: tuple[str, ...] = (
    "`country_`",
    "`state_`",
    "`building_`",
    "`goods_`",
    "`ship_`",
    "`unit_`",
    "`character_`",
    "`power_`",
    "`interest_`",
    "`battle_`",
    "`military_`",
    "`tax_` / `political_`",
    "`dummy_`",
)


def modifier_type_prefixes() -> Counter[str]:
    r"""`modifier_type_definitions\` 里键名前缀（第一个下划线之前）→ 键数。"""

    counter: Counter[str] = Counter()
    base = config.GAME / "common" / "modifier_type_definitions"
    for path in sorted(base.rglob("*.txt")):
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if not a.is_variable:
                counter[a.key.split("_", 1)[0] + "_"] += 1
    return counter


def modifier_type_suffixes() -> Counter[str]:
    r"""`modifier_type_definitions\` 里键名**尾段**（最后一个下划线之后）→ 键数。

    与 :func:`modifier_type_prefixes` 成对：doc 05 §3.x 那段「后缀分布」
    （``_add`` 1635 / ``_mult`` 626 / ``_bool`` 89 / ``_factor`` 5，另有 **9** 个键
    以别的词结尾）就是这一张表的两半 —— 只是那 9 个一直没有看守。

    尾段而不是「以 ``_x`` 结尾」：两种切法在本目录实测完全等价
    （每个键都含下划线），但 ``rpartition`` 对没有下划线的键也不会崩 ——
    它会返回键名本身，正好落进「其它尾段」那一类。
    """
    counter: Counter[str] = Counter()
    base = config.GAME / "common" / "modifier_type_definitions"
    for path in sorted(base.rglob("*.txt")):
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if not a.is_variable:
                counter[a.key.rpartition("_")[2]] += 1
    return counter


def _static_top_blocks() -> list[tuple[Path, Assignment]]:
    """`static_modifiers` 里全部**顶层块**赋值 ``(文件, 赋值)``。"""
    base = config.GAME / "common" / "static_modifiers"
    return [
        (path, a)
        for path in sorted(base.rglob("*.txt"))
        for a in parse_cached(path).top_assignments
        if not a.is_variable and isinstance(a.value, Block)
    ]


def digit_leading_entries() -> list[tuple[str, int, str]]:
    """`static_modifiers` 里**以数字开头**的顶层键 ``(键名, 行号, 文件名)``。

    doc 05 §6.x 的「有 3 个静态修饰符以数字开头」（``1848_popular_radical`` …）。
    键名本身就是证据，所以返回明细、个数由调用方 ``len`` —— 顺带让
    「数字开头的键名合法」这件事在代码里留下实例，而不是只留一个 3。

    为什么值得单列：PDX 脚本里键名允许以数字开头，而多数 mod 工具会按
    标识符规则把它判成非法 —— 这 3 个就是反例（全在
    ``content_1_modifiers.txt``）。
    """
    return [
        (str(a.key), int(a.line), path.name)
        for path, a in _static_top_blocks()
        if str(a.key)[:1].isdigit()
    ]


def indented_top_entries() -> list[tuple[str, int, str]]:
    """`static_modifiers` 里**行首带缩进**的顶层键 ``(键名, 行号, 文件名)``。

    doc 05 §6.2 的「有 7 个顶层键带缩进」—— 缩进在 PDX 里**没有语义**，
    所以「顶层」只能由解析器的花括号深度判定，缩进则必须回原文看第 ``line`` 行。

    ⚠️ 两个口径缺一不可：只看缩进会把条目内的 ``icon = …`` 也算进来
    （实测 2 处，在 ``00_ip2_03_modifiers.txt``），只看深度则一个都找不到。
    """
    out: list[tuple[str, int, str]] = []
    cache: dict[Path, list[str]] = {}
    for path, a in _static_top_blocks():
        if path not in cache:
            cache[path] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = cache[path]
        line = int(a.line)
        if 1 <= line <= len(lines) and lines[line - 1][:1] in (" ", "\t"):
            out.append((str(a.key), line, path.name))
    return out


def prefix_rows_keyed() -> list[tuple[str, dict[int, str]]]:
    """doc 05 那张前缀表：键照抄文档单元格（含合并行），值由计数器给。"""
    counts = modifier_type_prefixes()
    out: list[tuple[str, dict[int, str]]] = []
    for key in _PREFIX_ROWS:
        parts = [p.strip("`") for p in key.split(" / ")]
        values = {counts.get(p, 0) for p in parts}
        if len(parts) > 1 and len(values) == 1:  # 合并行：「各 N」
            text = f"各 **{values.pop()}**"
        elif len(parts) > 1:  # 各不相等 → 逐个列出，别让「各 N」变成假话
            text = " / ".join(f"**{counts.get(p, 0)}**" for p in parts)
        else:
            text = f"**{counts.get(parts[0], 0)}**"
        out.append((key, {1: text}))
    return out


def doc_table_specs() -> list[TableSpec | KeyedTableSpec]:
    """doc 05 的两张修饰符表 —— 登记给 ``v3 tables``。"""
    return [
        TableSpec(name="doc05 静态修饰符逐文件", header=STATIC_TABLE, rows=static_rows),
        KeyedTableSpec(
            name="doc05 修饰符键前缀",
            header=PREFIX_TABLE_HEADER,
            cells=prefix_rows_keyed,
            append_new=False,
        ),
    ]


__all__ = [
    "PREFIX_TABLE_HEADER",
    "STATIC_TABLE",
    "doc_table_specs",
    "modifier_type_prefixes",
    "prefix_rows_keyed",
    "static_modifier_stats",
    "static_rows",
]
