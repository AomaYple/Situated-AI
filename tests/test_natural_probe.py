"""纯自然观察与受控外交实验隔离；不虚构机会分母。"""

import pytest

from pdx import natural_probe
from pdx.model import Block
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def test_自然仪器只写私有计数且不改变AI或创建博弈():
    text = natural_probe.build(["dp_humiliation", "dp_annex_war"])[
        "common/on_actions/zz_sitai_natural.txt"
    ]
    tree = parse_text(text)
    assert not tree.errors
    forbidden = {
        "set_strategy",
        "create_diplomatic_play",
        "add_treasury",
        "activate_law",
        "remove_variable",
    }

    def visit(block):
        for assignment in block.assignments():
            assert assignment.key not in forbidden
            if assignment.key in {"set_variable", "change_variable"}:
                assert isinstance(assignment.value, Block)
                name = assignment.value.first("name")
                assert name is not None
                assert str(name.value) in {
                    natural_probe.START_VAR,
                    natural_probe.MONTH_VAR,
                }
            if isinstance(assignment.value, Block):
                visit(assignment.value)

    visit(tree.root)
    assert "TimeKeeper" not in text
    assert "is_ai = yes" in text


@pytest.mark.parametrize("play_types", [[], ["dp_a", "dp_a"], ["dp_a }"], ["not_a_play"]])
def test_类型生成拒绝空集重复与注入(play_types):
    with pytest.raises(ValueError):
        natural_probe.build(play_types)


@pytest.mark.parametrize("tags", [(), ("RUS", "RUS"), ("RU}",)])
def test_观察国生成拒绝空集重复与注入(tags):
    with pytest.raises(ValueError):
        natural_probe.build(["dp_humiliation"], tags=tags)
    for raw in ("", "RUS", "RUS,RUS", "RU}"):
        with pytest.raises(ValueError):
            natural_probe.parse_tags(raw)
    assert natural_probe.parse_tags(" AUS, FRA ") == ("AUS", "FRA")


def pulses():
    return "SITAI NATURAL;RUS;PULSE;ready;sample-1\nSITAI NATURAL;PRU;PULSE;ready;sample-1\n"


def test_有完整自报的零发起可以报告而无日志必须失败(tmp_path):
    with pytest.raises(ValueError, match="月度自报"):
        natural_probe.analyze(tmp_path)
    (tmp_path / "debug.log").write_text(pulses(), encoding="utf-8")
    result = natural_probe.analyze(tmp_path)
    assert result["countries"]["RUS"]["started"] == 0
    assert result["opportunity_denominator"] is None
    assert not result["quality_improvement_proven"]


def test_同一发起的重复行不膨胀计数且国家序号互不覆盖(tmp_path):
    event = (
        "SITAI NATURAL;RUS;START;France;sample-1\nSITAI NATURAL;RUS;TYPE;dp_humiliation;sample-1\n"
    )
    (tmp_path / "debug.1.log").write_text(pulses() + event, encoding="utf-8")
    (tmp_path / "debug.log").write_text(event + event.replace("RUS", "PRU"), encoding="utf-8")
    result = natural_probe.analyze(tmp_path)
    assert all(country["started"] == 1 for country in result["countries"].values())


@pytest.mark.parametrize(
    "extra",
    [
        "SITAI NATURAL;RUS;START;France;sample-1\n",
        "SITAI NATURAL;RUS;START;ERROR:[scope];sample-1\n",
        "SITAI NATURAL;RUS;START;France;sample-ERROR\n",
        "SITAI NATURAL;RUS;START;France;sample-1\nSITAI NATURAL;RUS;START;Britain;sample-1\n",
        "SITAI NATURAL;USA;PULSE;ready;sample-1\n",
    ],
)
def test_不完整冲突和错误行都拒绝(tmp_path, extra):
    (tmp_path / "debug.log").write_text(pulses() + extra, encoding="utf-8")
    with pytest.raises(ValueError):
        natural_probe.analyze(tmp_path)
