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
    assert "SITAI NATURAL;ROOT;HOOK" in text
    assert "SITAI NATURAL;ROOT;INITIATOR" in text


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
    assert result["hook_seen"] is False
    assert result["hook_count"] is None
    assert result["opportunity_denominator"] is None
    assert not result["quality_improvement_proven"]


def test_根哨兵能区分hook触发与观察国过滤(tmp_path):
    (tmp_path / "debug.log").write_text(
        pulses() + "SITAI NATURAL;ROOT;HOOK;start;sample-0\n"
        "SITAI NATURAL;ROOT;INITIATOR;Austria;sample-0\n"
        "SITAI NATURAL;ROOT;TARGET;Sardinia;sample-0\n",
        encoding="utf-8",
    )
    result = natural_probe.analyze(tmp_path)
    assert result["hook_seen"] is True
    assert result["hook_count"] is None
    assert result["root_initiators"] == ["Austria"]
    assert result["root_targets"] == ["Sardinia"]
    assert result["countries"]["RUS"]["started"] == 0


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


def test_有限命令合法性只读观测并延迟传递国家作用域():
    files = natural_probe.build(
        ["dp_humiliation"], tags=("RUS", "PRU"), command_targets=("PER", "SAX")
    )
    events = files["events/zz_sitai_natural_commands.txt"]
    assert not parse_text(events).errors
    assert "GetStartCommandCountry" in events
    assert "IsValid(" in events
    assert "Execute(" not in events
    assert "GetPlayer" not in events
    assert "save_scope_as" not in events
    actions = files["common/on_actions/zz_sitai_natural.txt"]
    assert "save_scope_as = sitai_command_actor_rus" in actions
    assert "save_scope_as = sitai_command_target_rus_per" in actions
    assert "save_scope_as = sitai_command_target_rus_sax" in actions
    assert "sCountry('sitai_command_target_rus_per')" in events
    assert "sCountry('sitai_command_target_rus_sax')" in events
    assert "days = 1" in files["common/on_actions/zz_sitai_natural.txt"]


def test_根哨兵只生成一次且多次入口不冒充事件计数(tmp_path):
    actions = natural_probe.build(["dp_humiliation"])["common/on_actions/zz_sitai_natural.txt"]
    assert actions.count("SITAI NATURAL;ROOT;HOOK;start;") == 1
    (tmp_path / "debug.log").write_text(
        pulses() + "SITAI NATURAL;ROOT;HOOK;start;sample-0\n" * 3, encoding="utf-8"
    )
    result = natural_probe.analyze(tmp_path)
    assert result["hook_seen"] is True
    assert result["hook_count"] is None


def test_自然月度缺号和零序号不当作完整观测(tmp_path):
    path = tmp_path / "debug.log"
    path.write_text(pulses() + pulses().replace("sample-1", "sample-3"), encoding="utf-8")
    with pytest.raises(ValueError, match="不连续"):
        natural_probe.analyze(tmp_path)
    path.write_text(pulses().replace("sample-1", "sample-0"), encoding="utf-8")
    with pytest.raises(ValueError, match="正整数"):
        natural_probe.analyze(tmp_path)


def command_rows():
    return "".join(
        f"SITAI COMMAND;{actor};{target};dp_humiliation;VALID;{value};sample-{sample}\n"
        for actor in ("RUS", "PRU")
        for target in ("PER", "SAX")
        for sample, value in ((1, "yes"), (2, "no"), (3, "yes"))
    )


def test_命令合法性计数是有限月度快照而非独立自然机会(tmp_path):
    (tmp_path / "debug.log").write_text(command_rows(), encoding="utf-8")
    result = natural_probe.analyze_commands(tmp_path, tags=("RUS", "PRU"), targets=("PER", "SAX"))
    assert result["valid_snapshots"] == 8
    assert result["candidate_snapshots"] == 12
    assert result["observed_valid_episodes"] == 8
    assert result["valid_entry_transitions"] == 4
    assert result["complete_opportunity_denominator"] is None
    assert not result["engine_interface_validated"]
    assert not result["quality_improvement_proven"]


def test_自我目标只用作非法反例不能计入候选分母(tmp_path):
    path = tmp_path / "debug.log"
    text = (
        "SITAI COMMAND;RUS;RUS;dp_humiliation;VALID;no;sample-1\n"
        "SITAI COMMAND;PRU;RUS;dp_humiliation;VALID;yes;sample-1\n"
    )
    path.write_text(text, encoding="utf-8")
    result = natural_probe.analyze_commands(tmp_path, tags=("RUS", "PRU"), targets=("RUS",))
    assert result["candidate_snapshots"] == 1
    assert result["valid_snapshots"] == 1
    assert result["negative_control_snapshots"] == 1
    path.write_text(text.replace("VALID;no", "VALID;yes"), encoding="utf-8")
    with pytest.raises(ValueError, match="自我"):
        natural_probe.analyze_commands(tmp_path, tags=("RUS", "PRU"), targets=("RUS",))


@pytest.mark.parametrize("mutation", ["missing", "conflict", "invalid", "gap"])
def test_有限命令观测缺失冲突坏值或采样缺口必须拒绝(tmp_path, mutation):
    text = command_rows()
    if mutation == "missing":
        text = "\n".join(
            line for line in text.splitlines() if not line.startswith("SITAI COMMAND;PRU;SAX;")
        )
    elif mutation == "conflict":
        text += "SITAI COMMAND;RUS;PER;dp_humiliation;VALID;no;sample-1\n"
    elif mutation == "invalid":
        text = text.replace(";yes;", ";[bad.expression];", 1)
    else:
        text = text.replace("sample-3", "sample-4")
    (tmp_path / "debug.log").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        natural_probe.analyze_commands(tmp_path, tags=("RUS", "PRU"), targets=("PER", "SAX"))
