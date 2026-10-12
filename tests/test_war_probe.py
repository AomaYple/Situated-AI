"""战争关系仪器的只读生成、完整矩阵与独立时间证据边界。"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from pdx import war_probe
from pdx.parser import parse_text

DATES = ("1836.2.24", "1836.2.25")


def rows(*, day="1836.2.24", sample=1, stamp="02:40:11"):
    prefix = f"[{stamp}][jomini_effect_impl.cpp:454]: "
    values = [f"SITAI WAR;MEX;DATE;-;{day};sample-{sample}"]
    for actor, target in war_probe.PAIRS:
        values.append(f"SITAI WAR;MEX;PRESENCE;{actor}/{target};yes;sample-{sample}")
        value = "yes" if (actor, target) == ("MEX", "TEX") else "no"
        values.append(f"SITAI WAR;MEX;RELATION;{actor}/{target};{value};sample-{sample}")
    return [prefix + value for value in values]


def write_logs(directory, values, ticks=None):
    (directory / "debug.log").write_text("\n".join(values) + "\n", encoding="utf-8", newline="\n")
    if ticks is not None:
        (directory / "dedicated_server.log").write_text(
            "\n".join(f"[{stamp}] Processing Tick: {tick}" for stamp, tick in ticks) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def test_有限脚本同host同effect且只写仪器私有变量():
    files = war_probe.build(dates=DATES)
    script = files[f"common/on_actions/{war_probe.SOURCE}.txt"]
    assert not parse_text(script).errors
    assert "on_monthly_pulse_country" in script
    assert script.count("c:MEX ?= this") == 1
    assert "game_date >= 1836.2.24 game_date < 1836.2.25" in script
    assert "game_date >= 1836.2.25 game_date < 1836.2.26" in script
    for actor, target in war_probe.PAIRS:
        assert f"exists = c:{actor} exists = c:{target}" in script
        assert f"c:{actor} ?= {{ has_war_with = c:{target} }}" in script
    for dangerous in (
        "trigger_event",
        "start_diplomatic",
        "add_treasury",
        "add_modifier",
        "declare_war",
        "GetWar",
        "SCOPE.",
    ):
        assert dangerous not in script
    variables = parse_text(script)
    assert war_probe.SAMPLE_VAR in script
    assert "sitai_probe_fiscal_sample" not in script
    assert variables.top_keys == ["on_monthly_pulse_country", war_probe.SOURCE]
    meta = json.loads(files[".metadata/metadata.json"])
    assert meta["game_custom_data"]["war_calibration"] == war_probe.configuration(DATES)
    assert meta["supported_game_version"]


@pytest.mark.parametrize(
    "values",
    [
        (),
        ("1836.2.30",),
        ("1836.2.24.0",),
        ("1836.02.24",),
        ("1836.2.24", "1836.2.24"),
        ("1836.2.25", "1836.2.24"),
        ("1836.2.24", "1836.2.26"),
        ("[unresolved]",),
        ("9999.12.31",),
    ],
)
def test_日期不合法不连续或重复拒绝(values):
    with pytest.raises(ValueError):
        war_probe.build(dates=values)


def test_日期预算与固定host():
    start = date(1836, 1, 1)
    values = tuple(
        f"{day.year}.{day.month}.{day.day}"
        for day in (start + timedelta(days=index) for index in range(91))
    )
    war_probe.build(dates=values[:90])
    with pytest.raises(ValueError):
        war_probe.build(dates=values)
    with pytest.raises(ValueError, match="host=MEX"):
        war_probe.build(dates=DATES, host="BRZ")
    with pytest.raises(ValueError):
        war_probe.parse_dates("1836.2.24,,1836.2.25")


def test_完整矩阵日期包围证实但关系质量与安全不自证(tmp_path):
    write_logs(tmp_path, rows(), [("02:40:10", "1836.2.24.0"), ("02:40:12", "1836.2.24.6")])
    result = war_probe.analyze(tmp_path, dates=DATES)
    assert result["date_binding"] == "verified"
    assert result["samples"][0]["tick_binding"] == "unknown"
    assert result["samples"][0]["pairs"][0]["has_war_with"]
    assert not result["samples"][0]["pairs"][1]["has_war_with"]
    assert result["unobserved_dates"] == ["1836.2.25"]
    assert result["instrument_safe"] is None
    assert result["structural_negative_control_passed"]
    assert not result["engine_interface_validated"]
    assert not result["relation_truth_validated"]
    assert not result["quality_improvement_proven"]


@pytest.mark.parametrize(
    "ticks",
    [
        None,
        [("02:40:11", "1836.2.24.0")],
        [
            ("02:40:10", "1836.2.23.18"),
            ("02:40:11", "1836.2.24.0"),
            ("02:40:11", "1836.2.25.0"),
            ("02:40:12", "1836.2.25.6"),
        ],
    ],
)
def test_无包围或跨日同秒绝不靠DATEguard自证(tmp_path, ticks):
    write_logs(tmp_path, rows(), ticks)
    result = war_probe.analyze(tmp_path, dates=DATES)
    assert result["date_binding"] == "unknown"
    assert result["samples"][0]["tick_binding"] == "unknown"


@pytest.mark.parametrize(
    "fault",
    [
        "date_missing",
        "presence_missing",
        "relation_missing",
        "duplicate",
        "unknown_pair",
        "unknown_date",
        "missing_country",
        "boolean",
        "literal",
        "host",
        "sample_zero",
        "sample_gap",
        "self_positive",
        "date_object",
        "no_rows",
    ],
)
def test_矩阵错误严格拒绝(tmp_path, fault):
    values = rows()
    if fault == "date_missing":
        values.pop(0)
    elif fault == "presence_missing":
        values.pop(1)
    elif fault == "relation_missing":
        values.pop(2)
    elif fault == "duplicate":
        values.append(values[-1])
    elif fault == "unknown_pair":
        values[1] = values[1].replace("MEX/TEX", "RUS/TEX")
    elif fault == "unknown_date":
        values[0] = values[0].replace("1836.2.24", "1836.2.26")
    elif fault == "missing_country":
        values[1] = values[1].replace(";yes;", ";no;")
    elif fault == "boolean":
        values[2] = values[2].replace(";yes;", ";1;")
    elif fault == "literal":
        values[2] = values[2].replace(";yes;", ";[THIS.GetValue];")
    elif fault == "host":
        values[3] = values[3].replace("WAR;MEX;", "WAR;BRZ;")
    elif fault == "sample_zero":
        values = [value.replace("sample-1", "sample-0") for value in values]
    elif fault == "sample_gap":
        values += rows(day="1836.2.25", sample=3)
    elif fault == "self_positive":
        values[-1] = values[-1].replace(";no;", ";yes;")
    elif fault == "date_object":
        values[0] = values[0].replace("DATE;-;", "DATE;MEX/TEX;")
    elif fault == "no_rows":
        values = []
    write_logs(tmp_path, values)
    with pytest.raises(ValueError):
        war_probe.analyze(tmp_path, dates=DATES)


@pytest.mark.parametrize(
    "ticks",
    [
        [("02:40:10", "1836.2.25.0"), ("02:40:12", "1836.2.25.6")],
        [("02:40:12", "1836.2.24.0"), ("02:40:10", "1836.2.24.6")],
        [("02:40:10", "1836.2.24.6"), ("02:40:12", "1836.2.24.0")],
        [("23:59:59", "1836.2.24.0"), ("00:00:01", "1836.2.24.6")],
        [("02:40:10", "1836.2.24.24")],
        [("02:40:10", "1836.2.30.0")],
    ],
)
def test_独立日期冲突倒退午夜和非法tick拒绝(tmp_path, ticks):
    write_logs(tmp_path, rows(), ticks)
    with pytest.raises(ValueError):
        war_probe.analyze(tmp_path, dates=DATES)


def test_轮转按原始顺序完整读取且不混接国家sample(tmp_path):
    values = rows()
    write_logs(tmp_path, values[3:] + rows(day="1836.2.25", sample=2, stamp="02:40:13"))
    (tmp_path / "debug.1.log").write_text(
        "\n".join(values[:3]) + "\n", encoding="utf-8", newline="\n"
    )
    result = war_probe.analyze(tmp_path, dates=DATES)
    assert [row["sample"] for row in result["samples"]] == [1, 2]
    assert result["unobserved_dates"] == []


def test_多行时间交集单tick不能把联合可能区间跨日冒充已验证(tmp_path):
    values = rows()
    values[-1] = values[-1].replace("02:40:11", "02:40:13")
    write_logs(
        tmp_path,
        values,
        [
            ("02:40:10", "1836.2.23.18"),
            ("02:40:12", "1836.2.24.0"),
            ("02:40:14", "1836.2.25.0"),
        ],
    )
    sample = war_probe.analyze(tmp_path, dates=DATES)["samples"][0]
    assert sample["shared_time_feasible_bounds"] == [[1836, 2, 24, 0], [1836, 2, 24, 0]]
    assert sample["tick_bounds"] == [[1836, 2, 23, 18], [1836, 2, 25, 0]]
    assert sample["date_binding"] == "unknown"
    assert sample["tick_binding"] == "unknown"


def test_多行独立包围区间不相交拒绝(tmp_path):
    values = rows()
    values[-1] = values[-1].replace("02:40:11", "02:40:15")
    write_logs(
        tmp_path,
        values,
        [
            ("02:40:10", "1836.2.24.0"),
            ("02:40:12", "1836.2.24.6"),
            ("02:40:14", "1836.2.24.12"),
            ("02:40:16", "1836.2.24.18"),
        ],
    )
    with pytest.raises(ValueError, match="不相交"):
        war_probe.analyze(tmp_path, dates=DATES)


@pytest.mark.parametrize("day", ["1836.2.24", "1836.2.25"])
def test_部分行缺包围不掩盖已知日期冲突且无冲突仍未知(tmp_path, day):
    values = rows()
    values[-1] = values[-1].replace("02:40:11", "02:40:13")
    write_logs(
        tmp_path,
        values,
        [("02:40:10", f"{day}.0"), ("02:40:12", f"{day}.6")],
    )
    if day == "1836.2.25":
        with pytest.raises(ValueError, match=r"DATE.*冲突"):
            war_probe.analyze(tmp_path, dates=DATES)
    else:
        result = war_probe.analyze(tmp_path, dates=DATES)
        assert result["date_binding"] == "unknown"
        sample = result["samples"][0]
        assert sample["tick_bounds"] == [[1836, 2, 24, 0], [1836, 2, 24, 6]]
        assert sample["date_binding"] == "unknown"
        assert sample["tick_binding"] == "unknown"


@pytest.mark.parametrize(
    "fault", ["date_repeat", "sample_reverse", "wall_reverse", "bad_stamp", "no_stamp"]
)
def test_跨样本日期顺序和壁钟格式严格验证(tmp_path, fault):
    values = rows()
    if fault == "date_repeat":
        values += rows(sample=2)
    elif fault == "sample_reverse":
        values = rows(day="1836.2.25", sample=2) + values
    elif fault == "wall_reverse":
        values += rows(day="1836.2.25", sample=2, stamp="02:40:10")
    elif fault == "bad_stamp":
        values[0] = values[0].replace("02:40:11", "25:40:11")
    else:
        values[0] = values[0].removeprefix("[02:40:11]")
    write_logs(tmp_path, values)
    with pytest.raises(ValueError):
        war_probe.analyze(tmp_path, dates=DATES)
