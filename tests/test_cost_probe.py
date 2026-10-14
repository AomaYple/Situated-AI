"""预算 getter 校准的完整性、未知值和用途边界。"""

from __future__ import annotations

import json

import pytest

from pdx import behavior_probe, cost_probe
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def matrix(*, samples=2):
    lines: list[str] = []
    for sample in range(1, samples + 1):
        for tag, identity in (("RUS", "42"), ("PRU", "71")):
            values = {"PRESENT": "yes", "COUNTRY_ID": identity, "COMMITTED": "no"}
            values.update(
                {kind: "0" if kind == "RESERVES" else "1234.567" for kind in cost_probe.GETTERS}
            )
            lines.extend(
                f"SITAI COST;{tag};{kind};{value};sample-{sample}\n"
                for kind, value in values.items()
            )
    return lines


def test_校准默认关闭且隔离字段有真实作用域():
    baseline = behavior_probe.build()
    instrument = behavior_probe.build(cost_readings=True)
    assert cost_probe.MARKER not in "".join(baseline.values())
    assert (
        baseline["common/on_actions/zz_sitai_opportunity.txt"]
        == instrument["common/on_actions/zz_sitai_opportunity.txt"]
    )
    for name, text in instrument.items():
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
    events = instrument["events/zz_sitai_opportunity.txt"]
    assert "TimeKeeper" not in events
    assert "[THIS.GetCountry.GetMaxCredit|3]" in events
    assert "[THIS.GetCountry.GetIDString]" in events
    assert "IsCommittedInDiplomaticPlay" not in events
    assert "is_diplomatic_play_committed_participant = yes" in events
    custom = json.loads(instrument[".metadata/metadata.json"])["game_custom_data"]
    assert custom["cost_calibration"] == cost_probe.configuration()
    assert custom["cost_calibration"]["fields"]["WEEKS_UNTIL_BANKRUPTCY"]["sentinel"]


def test_零值有意义且费用不能升级净代价(tmp_path):
    (tmp_path / "debug.log").write_text("".join(matrix()), encoding="utf-8", newline="\n")
    report = cost_probe.analyze(tmp_path)
    assert report["sample_count"] == 2
    assert report["country_ids"] == {"RUS": "42", "PRU": "71"}
    assert report["samples"][0]["countries"]["RUS"]["RESERVES"] == 0
    assert report["samples"][0]["countries"]["RUS"]["MAX_CREDIT"] == 1234.567
    assert (
        report["action_cost"]
        is report["adverse_outcome"]
        is report["independent_numeric_truth"]
        is None
    )
    assert not report["engine_interface_validated"]
    assert not report["quality_improvement_proven"]


@pytest.mark.parametrize(
    "value",
    ["ERROR:[getter]", "nan", "inf", "1e9", "", "[THIS.GetCountry.GetPrincipal]", "9" * 400],
)
def test_未展开与非有限费用拒绝(tmp_path, value):
    text = "".join(matrix()).replace("PRINCIPAL;1234.567", f"PRINCIPAL;{value}", 1)
    (tmp_path / "debug.log").write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        cost_probe.analyze(tmp_path)


@pytest.mark.parametrize("value", ["−123,25", "+123.25", "0"])
def test_保留实际符号与小数而不推断收益(tmp_path, value):
    text = "".join(matrix()).replace("PRINCIPAL;1234.567", f"PRINCIPAL;{value}")
    (tmp_path / "debug.log").write_text(text, encoding="utf-8", newline="\n")
    assert cost_probe.analyze(tmp_path)["samples"][0]["countries"]["RUS"]["PRINCIPAL"] == float(
        value.replace("−", "-").replace(",", ".")
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "unknown-tag",
        "unknown-kind",
        "gap",
        "reverse",
        "same-id",
        "changing-id",
        "missing-country",
        "absent",
        "bad-bool",
    ],
)
def test_拒绝不完整错误序列和空对象(tmp_path, mutation):
    lines = matrix()
    if mutation == "missing":
        del lines[3]
    elif mutation == "duplicate":
        lines.insert(2, lines[1])
    elif mutation == "unknown-tag":
        lines[0] = lines[0].replace(";RUS;", ";FRA;")
    elif mutation == "unknown-kind":
        lines[0] = lines[0].replace(";PRESENT;", ";UNKNOWN;")
    elif mutation == "gap":
        lines = [line.replace("sample-2", "sample-3") for line in lines]
    elif mutation == "reverse":
        lines = lines[14:] + lines[:14]
    elif mutation == "same-id":
        lines = [line.replace("COUNTRY_ID;71", "COUNTRY_ID;42") for line in lines]
    elif mutation == "changing-id":
        lines[-6] = lines[-6].replace("COUNTRY_ID;71", "COUNTRY_ID;72")
    elif mutation == "missing-country":
        lines = [line for line in lines if ";PRU;" not in line]
    elif mutation == "absent":
        lines[0] = lines[0].replace("PRESENT;yes", "PRESENT;no")
    elif mutation == "bad-bool":
        lines[2] = lines[2].replace("COMMITTED;no", "COMMITTED;0")
    (tmp_path / "debug.log").write_text("".join(lines), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        cost_probe.analyze(tmp_path)


@pytest.mark.parametrize(
    ("purpose", "arm", "injection", "natural"),
    [
        ("M3-A", "control", "none", False),
        ("instrument", "candidate", "none", False),
        ("instrument", "control", "stress", False),
        ("instrument", "control", "none", True),
    ],
)
def test_正式自然候选和财政注入不能偷开校准(purpose, arm, injection, natural):
    with pytest.raises(ValueError, match="预算校准"):
        cost_probe.validate_mode(purpose=purpose, arm=arm, injection=injection, natural=natural)


def test_受支持隔离模式与错误生成组合():
    cost_probe.validate_mode(purpose="instrument", arm="control", injection="none", natural=False)
    with pytest.raises(ValueError, match="独立受控校准"):
        behavior_probe.build(cost_readings=True, natural=True, play_types=("dp_humiliation",))
    with pytest.raises(ValueError, match="独立受控校准"):
        behavior_probe.build(cost_readings=True, market_readings=True)


def test_校准用途错误在源生成和游戏副作用之前拒绝(tmp_path):
    from argparse import Namespace

    from tools.probe import decision_behavior

    args = Namespace(purpose="M3-A", arm="control", fiscal_injection="none", cost_calibration=True)
    with pytest.raises(ValueError, match="预算校准"):
        decision_behavior.execute(args, tmp_path / "output", tmp_path / "source")
    assert list(tmp_path.iterdir()) == []


def test_大序号缺口不分配完整序号范围(tmp_path):
    text = "".join(matrix()).replace("sample-2", "sample-999999999999999999")
    (tmp_path / "debug.log").write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="序号缺失"):
        cost_probe.analyze(tmp_path)
