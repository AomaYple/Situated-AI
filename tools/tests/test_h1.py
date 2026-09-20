"""``pdx.h1`` 的用例：H1 实验的日志解析与统计。

用合成日志钉住四件事：**配对口径**（按启动段 + 时间戳 + 国名配对）、
**启动分段**（多次启动的行不混池）、**三槽与节奏**（剂量反应 + 换牌率）、
**判定逻辑**（区间不重叠才算通过）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdx import h1

pytestmark = pytest.mark.unit

_HEAD = "[12:00:{sec:02d}][jomini_effect_impl.cpp:454]: "


def _line(sec: int, kind: str, value: str, tag: str) -> str:
    return f"{_HEAD.format(sec=sec)}ZZPROBE H1;{kind};{value};{tag}"


def _block(
    sec: int,
    rows: list[tuple[str, str, str]],
    *,
    admi: str | dict[str, str] = "agricultural_expansion",
    dipl: str | dict[str, str] = "maintain_power_balance",
) -> str:
    """一个月的日志块：``rows`` 是 (tag, DOSE, 政治槽落点)。

    ``admi`` / ``dipl`` 既可以给一个字符串（所有国家一样），也可以给
    ``{剂量组: 落点}``（用来构造"换个槽位也一样吃剂量"的对照）。
    """
    out: list[str] = []
    for tag, dose, card in rows:
        a = admi[dose] if isinstance(admi, dict) else admi
        d = dipl[dose] if isinstance(dipl, dict) else dipl
        out.append(_line(sec, "DOSE", dose, tag))
        out.append(_line(sec, "POLI", card, tag))
        out.append(_line(sec, "ADMI", a, tag))
        out.append(_line(sec, "DIPL", d, tag))
    return "\n".join(out)


def test_三槽解析与配对() -> None:
    text = _block(1, [("RUS", "HIGH", h1.PROBE_CARD), ("FRA", "CTRL", "progressive")])
    parsed = h1.parse_lines(text)
    assert len(parsed.rows) == 2
    assert parsed.unpaired == 0
    row = parsed.rows[(0, "12:00:01", "RUS")]
    assert row["DOSE"] == "HIGH"
    assert row["POLI"] == h1.PROBE_CARD
    assert row["ADMI"] == "agricultural_expansion"
    assert parsed.runs == ("unknown",)


def test_老格式CARD行等价于政治槽() -> None:
    text = "\n".join(
        [
            _line(1, "DOSE", "LOW", "RUS"),
            f"{_HEAD.format(sec=1)}ZZPROBE H1;CARD;progressive;RUS",
        ]
    )
    parsed = h1.parse_lines(text)
    assert parsed.rows[(0, "12:00:01", "RUS")]["POLI"] == "progressive"
    assert parsed.unpaired == 0


def test_RUN行切分多次启动() -> None:
    # 两次启动的日志混在同一个目录里（轮转的常态），时间戳故意重复：
    # 键里带启动段，才不会把两段样本倒进同一个池子。
    text = "\n".join(
        [
            f"{_HEAD.format(sec=1)}ZZPROBE H1;RUN;natural",
            _block(1, [("RUS", "HIGH", "conservative")]),
            f"{_HEAD.format(sec=1)}ZZPROBE H1;RUN;storm",
            _block(1, [("RUS", "HIGH", h1.PROBE_CARD)]),
        ]
    )
    result = h1.analyze_text(text)
    assert result.runs == ("natural", "storm")
    assert result.variant == "storm"
    # 只统计最后一段：第一段的 conservative 不进样本
    assert [s.card for s in result.samples] == [h1.PROBE_CARD]


def test_缺一半的行算未配对且不进统计() -> None:
    result = h1.analyze_text(_line(1, "DOSE", "HIGH", "RUS"))
    assert result.unpaired == 1
    assert not result.samples


def test_按组统计命中率与区间() -> None:
    rows = [(f"H{i:03d}", "HIGH", h1.PROBE_CARD) for i in range(40)]
    rows += [(f"C{i:03d}", "CTRL", "progressive") for i in range(40)]
    result = h1.analyze_text(_block(1, rows))
    assert result.groups["HIGH"].observations == 40
    assert result.groups["HIGH"].probe_hits == 40
    assert result.groups["CTRL"].probe_hits == 0
    lo, hi = result.groups["CTRL"].wilson()
    assert 0.0 <= lo <= hi <= 1.0
    assert result.tags == 80


def test_三个槽位各自算剂量反应() -> None:
    rows = [(f"H{i:03d}", "HIGH", h1.PROBE_CARD) for i in range(30)]
    rows += [(f"C{i:03d}", "CTRL", "conservative") for i in range(30)]
    probe_admin = h1.PROBE_CARDS["administrative"]
    probe_diplo = h1.PROBE_CARDS["diplomatic"]
    text = _block(
        1,
        rows,
        admi={"HIGH": probe_admin, "CTRL": "agricultural_expansion"},
        dipl={"HIGH": probe_diplo, "CTRL": "maintain_power_balance"},
    )
    result = h1.analyze_text(text)
    for slot in h1.SLOTS:
        assert result.by_slot[slot]["HIGH"].hits == 30, slot
        assert result.by_slot[slot]["CTRL"].hits == 0, slot
    # 政治槽只有 30 次命中：ADMI/DIPL 的命中不算进 G1
    assert result.groups["HIGH"].probe_hits == 30


def test_重抽节奏按国家相邻观测计() -> None:
    text = "\n".join(
        [
            _block(1, [("A", "HIGH", "conservative"), ("B", "HIGH", "conservative")]),
            _block(2, [("A", "HIGH", "conservative"), ("B", "HIGH", "conservative")]),
            _block(3, [("A", "HIGH", h1.PROBE_CARD), ("B", "HIGH", "conservative")]),
        ]
    )
    tempo = h1.analyze_text(text).tempo["political"]
    assert tempo.pairs == 4  # 2 国 × 2 个相邻对
    assert tempo.changes == 1
    assert tempo.rate == pytest.approx(0.25)
    assert tempo.top[0] == ("conservative", 5)


def test_等效竞争权重反推() -> None:
    cell = h1.Cell(dose="HIGH", observations=100, hits=80)
    assert cell.implied_rival_weight() == pytest.approx(250 * 0.2 / 0.8)
    assert h1.Cell(dose="HIGH", observations=100, hits=100).implied_rival_weight() is None
    assert h1.Cell(dose="?", observations=10, hits=5).implied_rival_weight() is None


def test_判定_区间不重叠即通过() -> None:
    rows = [(f"H{i:03d}", "HIGH", h1.PROBE_CARD) for i in range(30)]
    rows += [(f"C{i:03d}", "CTRL", "conservative") for i in range(30)]
    report = h1.format_report(h1.analyze_text(_block(1, rows)))
    assert "G1 通过" in report
    assert "剂量单调性" in report


def test_判定_方向对但样本不足() -> None:
    rows = [(f"H{i}", "HIGH", h1.PROBE_CARD) for i in range(2)]
    rows += [("C0", "CTRL", "conservative")]
    report = h1.format_report(h1.analyze_text(_block(1, rows)))
    assert "区间重叠" in report


def test_判定_方向不对即不成立() -> None:
    rows = [(f"H{i:02d}", "HIGH", "conservative") for i in range(20)]
    rows += [(f"C{i:02d}", "CTRL", h1.PROBE_CARD) for i in range(20)]
    report = h1.format_report(h1.analyze_text(_block(1, rows)))
    assert "G1 不成立" in report


def test_第四槽出现会被标成异常() -> None:
    text = "\n".join(
        [
            _block(1, [("RUS", "HIGH", "conservative")]),
            _line(1, "FOURTH", "active", "RUS"),
        ]
    )
    result = h1.analyze_text(text)
    assert result.fourth_hits == 1
    assert "需要复查" in h1.format_report(result)


def test_无loc牌会被单独计数() -> None:
    text = _block(1, [("RUS", "LOW", h1.NOLOC_CARD)])
    result = h1.analyze_text(text)
    assert result.noloc_hits == 1
    assert "被抽中 1 次" in h1.format_report(result)


def test_H3标记进报告() -> None:
    text = "\n".join(
        [
            _block(1, [("RUS", "HIGH", "conservative")]),
            f"{_HEAD.format(sec=1)}ZZPROBE H3;TRY;block;HED",
        ]
    )
    result = h1.analyze_text(text)
    assert result.h3_events == ("TRY;block;HED",)
    report = h1.format_report(result)
    assert "TRY 1 条 / DONE 0 条" in report
    assert "该语法被引擎拒" in report


def test_空日志不炸() -> None:
    result = h1.analyze_text("")
    assert result.samples == ()
    assert result.variant == "unknown"
    assert "无法判定" in h1.format_report(result)


def test_日志目录不存在时返回空() -> None:
    assert h1.log_files(Path("Z:/不存在的目录")) == []


def test_wilson区间边界() -> None:
    assert h1.wilson_interval(0, 0) == (0.0, 0.0)
    assert h1.wilson_interval(0, 10)[0] == 0.0
    assert h1.wilson_interval(10, 10)[1] == 1.0
