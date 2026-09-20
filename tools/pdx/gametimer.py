"""``gametimer_*.tsv`` 的解析与统计（阶段 4 的性能对照表数据源）。

这个文件解决什么
----------------
阶段 4 的预算里有一条「**单帧 ≤0.5ms**」。要谈"超没超"，先得有个能读的性能真值。
引擎自己会写一份 ``gametimer_<YYYYMMDD_HHMMSS>.tsv``（路径：用户目录 ``logs/``），
本模块把它的**实测列结构**定成 schema，并把"每月均值 / 最坏一天"这类
可直接进对照表的数算出来。

实测列结构（**来自 12 个真实文件，不是猜的**）
--------------------------------------------
文件是 TAB 分隔的三列，表头带尾随空格：

.. code-block:: text

    Game Date <TAB>Time Unit <TAB>Seconds
    1838_01_01<TAB>Year<TAB>134.303810
    1840_07_04<TAB>Day<TAB>0.077892

* 第 1 列 ``Game Date``：``YYYY_MM_DD``（游戏内日期）。
* 第 2 列 ``Time Unit``：**只见过 Year / Month / Day 三种**。
* 第 3 列 ``Seconds``：该时间单元的**墙钟秒数**，6 位小数。

⚠️ **单帧耗时量不出来**（阶段 4 那条预算的正面回答）
----------------------------------------------------
本文件最细的粒度是 **Day**，而且实测**每天恰好 4 条样本**
（2026-09-13 那份 315 KB 的文件：3257 个不同日期，其中 3254 个正好 4 条）。
它**没有帧号、没有帧计数、也没有 per-frame 列** —— 所以
「单帧 ≤0.5ms」**不能**用这份数据判。它能给的是：
每日/每月/每年的**总墙钟**与**最坏一天**。要判单帧，得另找 per-frame 的真值
（exe 里确实有 ``GetPerFrameTimeExclusive`` / ``GetPerFrameTimeInclusive``，
但**目前没找到把它们导出成文件的开关** —— 见
`docs/design/exec/阶段4-gametimer侦察.md`）。
本模块把这个事实写成常量 :data:`FRAME_GRANULARITY_AVAILABLE`，
免得下游有人拿 Day 样本除以帧数去凑一个假的单帧值。

已知的数据瑕疵（解析器必须容忍，不许当异常丢）
-----------------------------------------------
1. **年份字段偶尔只有 1 位**：实测 13126 行里有 2 行写成 ``6_11_01`` / ``6_01_31``
   而不是 ``1836_11_01`` / ``1836_01_31``。行照样解析，但打上
   :attr:`GameTimerRow.suspicious_year`，由调用方决定怎么办 ——
   静默"修正"成 1836 是编数据，直接丢弃又会让月度序列缺一格。
2. **文件有大小上限**：实测多份文件停在 **315366 字节**（约 300 KiB）不再增长，
   即长局会被**截断**。所以"跑了 9 个游戏年"不等于"9 年的数据都在"。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: 表头三列（**注意实测带尾随空格**，比较前统一 strip）。
HEADER: tuple[str, str, str] = ("Game Date", "Time Unit", "Seconds")

#: 实测见过的 Time Unit 取值。
UNITS: tuple[str, ...] = ("Year", "Month", "Day")

#: 单帧耗时能否从本数据源量出来。**实测：不能**（最细粒度是 Day）。
#: 写成常量是为了让下游代码无从"顺手"凑一个假的单帧值。
FRAME_GRANULARITY_AVAILABLE = False

#: 实测的文件大小上限（多份文件停在这里）。超过它说明被截断。
OBSERVED_SIZE_CAP = 315_366

#: ``1836_01_01``；也接受 ``6_11_01`` 这种年份位数不足的写法（见模块文档）。
_DATE_RE = re.compile(r"^(\d{1,4})_(\d{1,2})_(\d{1,2})$")


@dataclass(frozen=True, slots=True)
class GameTimerRow:
    """一行采样。``seconds`` 是该时间单元的**墙钟秒数**。"""

    raw_date: str
    year: int
    month: int
    day: int
    unit: str
    seconds: float
    line_no: int

    @property
    def suspicious_year(self) -> bool:
        """年份字段不是 4 位 —— 实测存在（``6_11_01``），不猜它本意是几几年。"""
        return len(self.raw_date.split("_")[0]) != 4

    @property
    def key(self) -> tuple[int, int]:
        """``(年, 月)``，用于按月聚合。"""
        return (self.year, self.month)


@dataclass(slots=True)
class ParseResult:
    """一次解析的结果：好行 + 坏行 + 说明。"""

    rows: list[GameTimerRow] = field(default_factory=list)
    #: 解析失败的行：``(行号, 原文)``。**不静默丢** —— 数量要能报出来。
    bad_lines: list[tuple[int, str]] = field(default_factory=list)
    header_present: bool = False
    total_lines: int = 0

    @property
    def suspicious(self) -> list[GameTimerRow]:
        return [r for r in self.rows if r.suspicious_year]

    def of_unit(self, unit: str) -> list[GameTimerRow]:
        return [r for r in self.rows if r.unit == unit]


@dataclass(frozen=True, slots=True)
class UnitStats:
    """某一个 Time Unit 的秒数分布。"""

    unit: str
    count: int
    total: float
    mean: float
    median: float
    worst: float
    best: float

    def describe(self) -> str:
        return (
            f"{self.unit:5s} n={self.count:6d} 合计={self.total:10.3f}s "
            f"均值={self.mean:8.4f}s 中位={self.median:8.4f}s "
            f"最坏={self.worst:8.4f}s"
        )


@dataclass(frozen=True, slots=True)
class MonthlyStat:
    """一个游戏月的**日粒度**开销（对照表的直接输入）。"""

    year: int
    month: int
    days: int
    samples: int
    mean_daily: float
    worst_daily: float

    def describe(self) -> str:
        return (
            f"{self.year}-{self.month:02d} 天={self.days:3d} 样本={self.samples:4d} "
            f"日均={self.mean_daily:.4f}s 最坏一天={self.worst_daily:.4f}s"
        )


def parse_line(line: str, line_no: int) -> GameTimerRow | None:
    """解析一行；不合格给 ``None``（调用方负责记进 ``bad_lines``）。"""
    parts = line.split("\t")
    if len(parts) != 3:
        return None
    raw_date, unit, seconds_text = (p.strip() for p in parts)
    match = _DATE_RE.match(raw_date)
    if match is None:
        return None
    try:
        seconds = float(seconds_text)
    except ValueError:
        return None
    year, month, day = (int(g) for g in match.groups())
    return GameTimerRow(
        raw_date=raw_date,
        year=year,
        month=month,
        day=day,
        unit=unit,
        seconds=seconds,
        line_no=line_no,
    )


def is_header(line: str) -> bool:
    """是不是表头（实测带尾随空格，所以按 strip 后比较）。"""
    parts = [p.strip() for p in line.split("\t")]
    return tuple(parts) == HEADER


def parse_tsv(text: str) -> ParseResult:
    """解析整份 TSV。

    * 表头可有可无（缺失时 ``header_present=False``，其余照解析）。
    * 空行跳过，**不计入** ``bad_lines``。
    * 列数不对 / 日期不合法 / 秒数不是数 → 进 ``bad_lines``。
    """
    result = ParseResult()
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        result.total_lines += 1
        if is_header(raw) and not result.header_present:
            result.header_present = True
            continue
        row = parse_line(raw, line_no)
        if row is None:
            result.bad_lines.append((line_no, raw))
            continue
        result.rows.append(row)
    return result


def parse_file(path: Path) -> ParseResult:
    """读并解析一个 ``gametimer_*.tsv``。"""
    return parse_tsv(path.read_text(encoding="utf-8", errors="replace"))


def unit_stats(result: ParseResult, unit: str) -> UnitStats | None:
    """某个 Time Unit 的秒数统计；没有该 unit 的行时给 ``None``。"""
    values = [r.seconds for r in result.of_unit(unit)]
    if not values:
        return None
    return UnitStats(
        unit=unit,
        count=len(values),
        total=sum(values),
        mean=statistics.fmean(values),
        median=statistics.median(values),
        worst=max(values),
        best=min(values),
    )


def all_unit_stats(result: ParseResult, units: tuple[str, ...] = UNITS) -> list[UnitStats]:
    """:data:`UNITS` 里所有出现过的 unit 的统计（按 :data:`UNITS` 顺序）。"""
    return [s for u in units if (s := unit_stats(result, u)) is not None]


def daily_totals(result: ParseResult) -> dict[str, float]:
    """把同一天的多条样本**加起来** —— 即"这一天一共花了多少秒"。

    实测每天 4 条样本，所以日均值不能拿单条样本当"一天的开销"。
    """
    totals: dict[str, float] = {}
    for row in result.of_unit("Day"):
        totals[row.raw_date] = totals.get(row.raw_date, 0.0) + row.seconds
    return totals


def monthly_stats(result: ParseResult) -> list[MonthlyStat]:
    """按游戏月聚合**日粒度**开销（对照表直接可用）。

    ⚠️ 只统计 ``Day`` 行：``Month`` 行是引擎自己给的整月合计，
    两者口径不同，混在一起会得出错误的月均值。本函数**只用 Day 行**，
    想拿引擎的整月合计请显式用 :func:`unit_stats` 的 ``"Month"``。
    """
    day_rows = result.of_unit("Day")
    buckets: dict[tuple[int, int], list[GameTimerRow]] = {}
    for row in day_rows:
        buckets.setdefault(row.key, []).append(row)

    out: list[MonthlyStat] = []
    for (year, month), rows in sorted(buckets.items()):
        per_day: dict[str, float] = {}
        for row in rows:
            per_day[row.raw_date] = per_day.get(row.raw_date, 0.0) + row.seconds
        values = list(per_day.values())
        out.append(
            MonthlyStat(
                year=year,
                month=month,
                days=len(values),
                samples=len(rows),
                mean_daily=statistics.fmean(values),
                worst_daily=max(values),
            )
        )
    return out


def summarize(path: Path) -> dict[str, object]:
    """把一份文件压成可直接进对照表/汇报的字典。"""
    result = parse_file(path)
    stats = all_unit_stats(result)
    months = monthly_stats(result)
    totals = daily_totals(result)
    return {
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "truncated_by_cap": path.stat().st_size >= OBSERVED_SIZE_CAP,
        "rows": len(result.rows),
        "bad_lines": len(result.bad_lines),
        "suspicious_year_rows": len(result.suspicious),
        "header_present": result.header_present,
        "unit_counts": {s.unit: s.count for s in stats},
        "unit_means": {s.unit: round(s.mean, 6) for s in stats},
        "unit_worst": {s.unit: round(s.worst, 6) for s in stats},
        "days_observed": len(totals),
        "worst_day": round(max(totals.values()), 6) if totals else None,
        "months": len(months),
        "per_frame_measurable": FRAME_GRANULARITY_AVAILABLE,
    }


def summary_lines(path: Path) -> list[str]:
    """人能读的几行结论（供 ``v3`` 子命令或文档引用）。"""
    result = parse_file(path)
    lines = [f"文件：{path.name}（{path.stat().st_size:,} 字节）"]
    if path.stat().st_size >= OBSERVED_SIZE_CAP:
        lines.append("⚠️ 已达实测大小上限，数据被截断")
    lines.append(f"样本 {len(result.rows)} 行；坏行 {len(result.bad_lines)} 行")
    if result.suspicious:
        lines.append(f"⚠️ 年份位数不足的行 {len(result.suspicious)} 行（如实保留，未改写）")
    lines.extend("  " + stat.describe() for stat in all_unit_stats(result))
    months = monthly_stats(result)
    if months:
        worst = max(months, key=lambda m: m.worst_daily)
        lines.append(f"  月数 {len(months)}；最坏的一个月：{worst.describe()}")
    lines.append("  单帧耗时：**量不出来**（本数据最细粒度是 Day，实测每天 4 条样本，无帧号）")
    return lines


__all__ = [
    "FRAME_GRANULARITY_AVAILABLE",
    "HEADER",
    "OBSERVED_SIZE_CAP",
    "UNITS",
    "GameTimerRow",
    "MonthlyStat",
    "ParseResult",
    "UnitStats",
    "all_unit_stats",
    "daily_totals",
    "is_header",
    "monthly_stats",
    "parse_file",
    "parse_line",
    "parse_tsv",
    "summarize",
    "summary_lines",
    "unit_stats",
]
