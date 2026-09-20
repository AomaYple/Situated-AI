"""表格类数据提取（``.csv`` / ``.tsv``）。

为什么单独一个模块
------------------
这类文件**不是** PDX 花括号语法，而是分隔符表格 —— 塞给 :mod:`pdx.parser`
只会静默产出垃圾（和 ``.yml`` 一样：0 个键、0 个错误）。

虽然全库只有**一个**这样的文件（``map_data/adjacencies.csv``），但它不能省：
它定义的是**海峡与陆地连通性**，mod 改地图边界时必须动它。
此前它落在所有范围之外 —— 既不是 PDX 脚本，也没有专用读取器。

分隔符靠**嗅探**而不是写死：Paradox 的表格用分号，但别的文件可能是逗号
或制表符。用标准库 :mod:`csv` 的 ``Sniffer`` 判断，不自己写启发式。
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config
from .doc_tables import TableSpec
from .parser import TOLERATED_ERRORS
from .scan import walk_files

if TYPE_CHECKING:
    from pathlib import Path

#: 会被本模块处理的扩展名
SUFFIXES = (".csv", ".tsv")

#: 嗅探失败时的兜底分隔符（Paradox 的表格普遍用分号）
_FALLBACK_DELIMITERS = (";", ",", "\t", "|")


@dataclass(slots=True)
class Table:
    """一个已解析的表格。"""

    rel: str
    delimiter: str
    columns: list[str]
    rows: list[list[str]]
    size: int

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, object]:
        """转成 ``{"列名": [值, …]}`` 的列式表示。

        列式比行式紧凑得多（列名只写一次），而且查询时通常按列看。
        """
        cols: dict[str, list[str]] = {c: [] for c in self.columns}
        for row in self.rows:
            for i, name in enumerate(self.columns):
                cols[name].append(row[i] if i < len(row) else "")
        return {
            "分隔符": self.delimiter,
            "行数": self.row_count,
            "列": cols,
        }


@dataclass(slots=True)
class TableReport:
    tables: list[Table] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(t.row_count for t in self.tables)

    def summary(self) -> dict[str, object]:
        return {
            "表格数": len(self.tables),
            "总行数": self.total_rows,
            "解析错误": len(self.errors),
        }


def _sniff(text: str) -> str:
    """判断分隔符。优先用标准库的 Sniffer，失败再按固定顺序试。"""
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(_FALLBACK_DELIMITERS)).delimiter
    except csv.Error:
        pass
    # 嗅探失败：选在首行里出现次数最多的那个
    first = text.splitlines()[0] if text.splitlines() else ""
    counts = {d: first.count(d) for d in _FALLBACK_DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ";"


def parse_table_text(text: str) -> tuple[str, list[str], list[list[str]]]:
    """解析一份表格文本，返回 ``(分隔符, 列名, 数据行)``。

    首行当表头 —— 实测 ``adjacencies.csv`` 就是
    ``From;To;Type;Through;…;Comment``。带 BOM 时由调用方先剥。
    """
    delimiter = _sniff(text)
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return delimiter, [], []
    columns = [c.strip() for c in rows[0]]
    return delimiter, columns, [list(r) for r in rows[1:]]


@dataclass(frozen=True, slots=True)
class ColumnStat:
    """一列的取值分布（`v3 csv` 用）。"""

    name: str
    distinct: int
    blanks: int
    top: tuple[tuple[str, int], ...]


def column_stats(table: Table, *, top: int = 5) -> list[ColumnStat]:
    """逐列统计：不同取值数、空值数、出现最多的几个取值。

    为什么要它：doc 06 §4.4 关于 `adjacencies.csv` 的几条结论（``Type`` 只有 14 种取值、
    ``Through`` 全是 ``-1``、``adjacency_rule_name`` 全是空串）此前是**一次性脚本**的
    产物。把「一列有哪些取值」变成命令之后，这类结论就能随时复算。
    """
    out: list[ColumnStat] = []
    for index, name in enumerate(table.columns):
        counter: Counter[str] = Counter()
        blanks = 0
        for row in table.rows:
            value = row[index].strip() if index < len(row) else ""
            if value:
                counter[value] += 1
            else:
                blanks += 1
        out.append(
            ColumnStat(
                name=name,
                distinct=len(counter),
                blanks=blanks,
                top=tuple(counter.most_common(top)),
            )
        )
    return out


#: 生成表在文档里的表头（doc 06 §4.4）。
ADJACENCIES_TABLE_HEADER = "| adjacencies 列 | 不同取值 | 空值 |"


def _adjacencies_rows() -> list[str]:
    path = config.GAME / "map_data" / "adjacencies.csv"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    delimiter, columns, rows = parse_table_text(text)
    sheet = Table(
        rel="map_data/adjacencies.csv", delimiter=delimiter, columns=columns, rows=rows, size=0
    )
    return [f"| `{s.name}` | {s.distinct} | {s.blanks} |" for s in column_stats(sheet, top=1)]


def doc_table_specs() -> list[TableSpec]:
    """doc 06 §4.4 的 `adjacencies.csv` 列分布表 —— 让那几条结论的数字可复算。

    实测（1.14.3）：241 个数据行 × 10 列；`Type` 14 种取值、`Through` 只有 `-1`、
    `adjacency_rule_name` 全为空串、`Comment` 空 34 行。此前这些是 PowerShell
    一次性脚本的产物，现在由 `v3 tables` 每次核对（复算命令：`v3 csv`）。
    """
    return [TableSpec("doc06 adjacencies 列分布", ADJACENCIES_TABLE_HEADER, _adjacencies_rows)]


def extract_tables(root: Path) -> TableReport:
    """提取一个内容根下全部表格文件。"""
    report = TableReport()
    if not root.is_dir():
        return report
    for f in sorted(walk_files(root), key=lambda e: str(e.path)):
        if f.suffix not in SUFFIXES:
            continue
        try:
            text = f.path.read_text(encoding="utf-8-sig", errors="replace")
        except TOLERATED_ERRORS as exc:
            report.errors.append((str(f.path), f"{type(exc).__name__}: {exc}"))
            continue
        try:
            delimiter, columns, rows = parse_table_text(text)
        except csv.Error as exc:
            report.errors.append((str(f.path), f"csv.Error: {exc}"))
            continue
        report.tables.append(
            Table(
                rel=str(f.path.relative_to(root)).replace("\\", "/"),
                delimiter=delimiter,
                columns=columns,
                rows=rows,
                size=f.size,
            )
        )
    return report
