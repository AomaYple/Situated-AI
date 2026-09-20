"""``pdx.gametimer`` 的用例：纯离线，全部用**合成夹具**，不依赖游戏。

夹具按**实测到的真实列结构**写（表头带尾随空格、TAB 分隔、
``YYYY_MM_DD``、时间单元 Year/Month/Day），并且把两个真实瑕疵也做进夹具：
年份位数不足的行、以及被大小上限截断的文件。
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

import pytest

from pdx import gametimer as gt

if TYPE_CHECKING:
    from pathlib import Path

#: 与真实文件一致的夹具：表头带尾随空格 + 三种时间单元。
SAMPLE = (
    "Game Date \tTime Unit \tSeconds\n"
    "1838_01_01\tYear\t134.303810\n"
    "1839_01_01\tYear\t161.642236\n"
    "1836_11_01\tMonth\t9.879664\n"
    "1837_01_01\tMonth\t13.100000\n"
    "1837_02_01\tMonth\t11.100000\n"
    "1840_07_04\tDay\t0.077892\n"
    "1840_07_04\tDay\t0.075253\n"
    "1840_07_04\tDay\t0.055261\n"
    "1840_07_04\tDay\t0.191594\n"
    "1840_07_05\tDay\t0.200277\n"
)


def write(tmp_path: Path, text: str, name: str = "gametimer_20260913_213737.tsv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestParsing:
    def test_表头带尾随空格也能认(self) -> None:
        assert gt.is_header("Game Date \tTime Unit \tSeconds") is True

    def test_表头不带尾随空格也认(self) -> None:
        assert gt.is_header("Game Date\tTime Unit\tSeconds") is True

    def test_别的行不是表头(self) -> None:
        assert gt.is_header("1840_07_04\tDay\t0.1") is False

    def test_解析整份夹具(self) -> None:
        result = gt.parse_tsv(SAMPLE)
        assert result.header_present is True
        assert len(result.rows) == 10  # 2 Year + 3 Month + 5 Day
        assert result.bad_lines == []

    def test_首行数据字段正确(self) -> None:
        first = gt.parse_tsv(SAMPLE).rows[0]
        assert (first.year, first.month, first.day) == (1838, 1, 1)
        assert first.unit == "Year"
        assert first.seconds == pytest.approx(134.303810)
        assert first.line_no == 2  # 表头占了第 1 行

    def test_没有表头也照解析(self) -> None:
        result = gt.parse_tsv("1840_07_04\tDay\t0.5\n")
        assert result.header_present is False
        assert len(result.rows) == 1

    def test_空行跳过且不算坏行(self) -> None:
        result = gt.parse_tsv("1840_07_04\tDay\t0.5\n\n\n1840_07_05\tDay\t0.6\n")
        assert len(result.rows) == 2
        assert result.bad_lines == []

    @pytest.mark.parametrize(
        "bad",
        [
            "1840_07_04\tDay",  # 少一列
            "1840_07_04\tDay\t0.5\textra",  # 多一列
            "not-a-date\tDay\t0.5",  # 日期不合法
            "1840_07_04\tDay\tabc",  # 秒数不是数
            "1840-07-04\tDay\t0.5",  # 分隔符不是下划线
        ],
    )
    def test_坏行进_bad_lines_而不是被静默丢掉(self, bad: str) -> None:
        result = gt.parse_tsv(bad + "\n")
        assert result.rows == []
        assert len(result.bad_lines) == 1
        assert result.bad_lines[0][1] == bad

    def test_坏行记的是原始行号(self) -> None:
        result = gt.parse_tsv("1840_07_04\tDay\t0.5\ngarbage\n")
        assert result.bad_lines[0][0] == 2

    def test_年份位数不足的行被标出来而不是被改写(self) -> None:
        """实测真文件里有 2 行写成 ``6_11_01``。**不猜它是 1836**，只打标。"""
        result = gt.parse_tsv("6_11_01\tMonth\t9.879664\n1836_11_01\tMonth\t9.0\n")
        assert len(result.rows) == 2
        assert result.rows[0].year == 6
        assert result.rows[0].suspicious_year is True
        assert result.rows[1].suspicious_year is False
        assert len(result.suspicious) == 1

    def test_两次出现的表头只认一次(self) -> None:
        result = gt.parse_tsv(f"{SAMPLE}{SAMPLE}")
        assert result.header_present is True
        # 第二个表头会当坏行（列数对但日期不是日期）
        assert len(result.bad_lines) == 1


class TestStats:
    def test_按单元统计(self) -> None:
        result = gt.parse_tsv(SAMPLE)
        stat = gt.unit_stats(result, "Year")
        assert stat is not None
        assert stat.count == 2
        assert stat.best == pytest.approx(134.303810)
        assert stat.worst == pytest.approx(161.642236)
        assert stat.mean == pytest.approx((134.303810 + 161.642236) / 2)

    def test_没有该单元时给_None(self) -> None:
        assert gt.unit_stats(gt.parse_tsv("1840_07_04\tDay\t0.5\n"), "Year") is None

    def test_三个单元都在(self) -> None:
        stats = gt.all_unit_stats(gt.parse_tsv(SAMPLE))
        assert [s.unit for s in stats] == ["Year", "Month", "Day"]

    def test_日合计是把同一天多条样本加起来(self) -> None:
        """实测每天 4 条样本 —— 拿单条当"一天的开销"会低估。"""
        totals = gt.daily_totals(gt.parse_tsv(SAMPLE))
        assert totals["1840_07_04"] == pytest.approx(0.077892 + 0.075253 + 0.055261 + 0.191594)
        assert totals["1840_07_05"] == pytest.approx(0.200277)

    def test_日合计不含_Month_Year_行(self) -> None:
        totals = gt.daily_totals(gt.parse_tsv(SAMPLE))
        assert set(totals) == {"1840_07_04", "1840_07_05"}

    def test_按月聚合只用_Day_行(self) -> None:
        """``Month`` 行是引擎自己的整月合计，口径不同，不能混进来。"""
        months = gt.monthly_stats(gt.parse_tsv(SAMPLE))
        assert len(months) == 1
        stat = months[0]
        assert (stat.year, stat.month) == (1840, 7)
        assert stat.days == 2
        assert stat.samples == 5
        assert stat.worst_daily == pytest.approx(0.400000)  # 07-04 四条之和

    def test_月均值是日均值的均值而不是样本均值(self) -> None:
        months = gt.monthly_stats(gt.parse_tsv(SAMPLE))
        day_totals = [0.400000, 0.200277]  # 07-04 四条之和 / 07-05 一条
        assert months[0].mean_daily == pytest.approx(statistics.fmean(day_totals))

    def test_按月排序(self) -> None:
        text = "1840_02_01\tDay\t0.2\n1839_12_01\tDay\t0.1\n1840_01_01\tDay\t0.3\n"
        got = [(m.year, m.month) for m in gt.monthly_stats(gt.parse_tsv(text))]
        assert got == [(1839, 12), (1840, 1), (1840, 2)]

    def test_年份异常的行仍进月度序列(self) -> None:
        """丢掉它会让月度序列缺一格；静默改成 1836 是编数据。留着并打标。"""
        result = gt.parse_tsv("6_11_01\tDay\t0.5\n")
        months = gt.monthly_stats(result)
        assert [(m.year, m.month) for m in months] == [(6, 11)]


class TestFileLevel:
    def test_解析真文件路径(self, tmp_path: Path) -> None:
        path = write(tmp_path, SAMPLE)
        assert len(gt.parse_file(path).rows) == 10

    def test_汇总字典(self, tmp_path: Path) -> None:
        path = write(tmp_path, SAMPLE)
        info = gt.summarize(path)
        assert info["file"] == path.name
        assert info["rows"] == 10
        assert info["bad_lines"] == 0
        assert info["header_present"] is True
        assert info["unit_counts"] == {"Year": 2, "Month": 3, "Day": 5}
        assert info["days_observed"] == 2
        assert info["months"] == 1
        # 07-04 四条样本合计 0.400000，是最坏的一天；07-05 只有 0.200277
        assert info["worst_day"] == pytest.approx(0.400000)

    def test_汇总里明说单帧量不出来(self, tmp_path: Path) -> None:
        """阶段 4 的「单帧 ≤0.5ms」预算：这一条必须被机器可读地否掉。"""
        info = gt.summarize(write(tmp_path, SAMPLE))
        assert info["per_frame_measurable"] is False
        assert gt.FRAME_GRANULARITY_AVAILABLE is False

    def test_截断标记(self, tmp_path: Path) -> None:
        path = write(tmp_path, SAMPLE)
        assert gt.summarize(path)["truncated_by_cap"] is False
        padded = path.read_text(encoding="utf-8") + ("1841_01_01\tDay\t0.1\n" * 1)
        path.write_text(padded, encoding="utf-8")
        assert gt.summarize(path)["truncated_by_cap"] is False

    def test_可读结论里带警告(self, tmp_path: Path) -> None:
        path = write(tmp_path, "6_11_01\tDay\t0.5\n1840_01_01\tDay\t0.4\n")
        lines = gt.summary_lines(path)
        text = "\n".join(lines)
        assert "年份位数不足" in text
        assert "量不出来" in text
        assert "Day" in text

    def test_空文件不炸(self, tmp_path: Path) -> None:
        path = write(tmp_path, "")
        result = gt.parse_file(path)
        assert result.rows == []
        info = gt.summarize(path)
        assert info["rows"] == 0
        assert info["worst_day"] is None

    def test_只有表头也不炸(self, tmp_path: Path) -> None:
        path = write(tmp_path, "Game Date \tTime Unit \tSeconds\n")
        info = gt.summarize(path)
        assert info["rows"] == 0
        assert info["header_present"] is True


class TestSchemaConstants:
    def test_表头常量与夹具一致(self) -> None:
        assert gt.HEADER == ("Game Date", "Time Unit", "Seconds")

    def test_单元常量与实测一致(self) -> None:
        assert gt.UNITS == ("Year", "Month", "Day")

    def test_大小上限是实测值(self) -> None:
        assert gt.OBSERVED_SIZE_CAP == 315_366
