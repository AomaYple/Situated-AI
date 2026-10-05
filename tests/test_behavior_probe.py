"""机会分母、无记录失败与仪器生成的独立边界。"""

import pytest

from pdx import behavior_probe
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def test_仪器脚本可解析且不强制AI加入():
    for name, text in behavior_probe.build().items():
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
            assert "set_strategy" not in text
            assert "SupportInitiator" not in text or "CanSupportInitiator" in text


def test_详细评分输出确实在七天节流分支内():
    text = behavior_probe.build()["events/zz_sitai_opportunity.txt"]
    from pdx.model import Block

    tree = parse_text(text)
    assert not tree.errors
    event = tree.top_assignments[1].value
    assert isinstance(event, Block)
    # 每个详细输出的直接所属块都有同一节流变量写入；不能只生成一个空节流块。
    blocks = []

    def visit(block, eligible=False):
        limit = block.first("limit")
        if limit is not None and isinstance(limit.value, Block):
            eligible = eligible or any(
                a.key == "is_diplomatic_play_undecided_participant"
                for a in limit.value.assignments()
            )
        for a in block.assignments():
            if a.key == "debug_log" and (
                "SITAI SCORE DETAIL" in str(a.value)
                or ";INIT_SCORE;" in str(a.value)
                or ";TARGET_SCORE;" in str(a.value)
            ):
                assert eligible, "分数与理由函数只能在未决定参与状态读取"
        if any(
            a.key == "debug_log" and "SITAI SCORE DETAIL" in str(a.value)
            for a in block.assignments()
        ):
            blocks.append(block)
        for assignment in block.assignments():
            if isinstance(assignment.value, Block):
                visit(assignment.value, eligible)

    visit(event)
    assert len(blocks) == 2
    for block in blocks:
        assert block.all("set_variable")


def test_读取事件复用已传递的作用域而不在同一事件首次绑定():
    files = behavior_probe.build()
    actions = files["common/on_actions/zz_sitai_opportunity.txt"]
    events = files["events/zz_sitai_opportunity.txt"]
    assert "save_scope_as = sitai_opportunity" in actions
    assert "save_scope_as = sitai_rus" in actions
    assert "save_scope_as" not in events
    assert "scope:sitai_opportunity ?=" in events
    assert "trigger_event = { id = zz_sitai_opportunity.1 days = 1 }" in actions
    assert "trigger_event = { id = zz_sitai_opportunity.1 days = 1 }" in events
    assert "SelectLocalization" not in events  # 二级本地化会丢失SCOPE，不能用于Getter保护。
    assert "TimeKeeper" not in events
    assert ".MakeScope.Var('sitai_probe_opportunity_sample')" in events


@pytest.mark.parametrize("sample", ["sample-ERROR:[bad.function]", "sample--1", "sample-1.5"])
def test_失败的私有时间读数不能形成配对键(tmp_path, sample):
    (tmp_path / "debug.log").write_text(
        f"SITAI OPPORTUNITY;RUS;CAN_TARGET;yes;{sample}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="采样序号"):
        behavior_probe.analyze(tmp_path)


def test_重复日行不膨胀机会和行为计数(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI OPPORTUNITY;RUS;CAN_TARGET;yes;date\n" * 5
        + "SITAI OPPORTUNITY;RUS;BACKER;yes;date\n" * 3,
        encoding="utf-8",
    )
    report = behavior_probe.analyze(tmp_path)
    assert report["countries"]["RUS"]["independent_opportunities"] == 1
    assert report["countries"]["RUS"]["joined"] == 1
    assert report["countries"]["PRU"]["independent_opportunities"] == 0
    assert not report["behavior_causality"]


def test_缺记录或未解析布尔值不能当中立成功(tmp_path):
    with pytest.raises(ValueError, match="缺少"):
        behavior_probe.analyze(tmp_path)
    (tmp_path / "debug.log").write_text(
        "SITAI OPPORTUNITY;RUS;BACKER;[bad.expression];date\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="布尔"):
        behavior_probe.analyze(tmp_path)


def test_两国资格与激活必须在同一天同时存在(tmp_path):
    lines: list[str] = []
    for tag, date in (("RUS", "day1"), ("PRU", "day2")):
        lines.extend(
            f"SITAI OPPORTUNITY;{tag};{kind};yes;{date}\n"
            for kind in ("CAN_INIT", "UNDECIDED", "ACTIVE")
        )
    path = tmp_path / "debug.log"
    path.write_text("".join(lines), encoding="utf-8")
    report = behavior_probe.analyze(tmp_path)
    assert not report["usable_for_paired_behavior"]
    assert report["countries"]["RUS"]["eligible_active_days"] == 1
    path.write_text("".join(lines).replace("day2", "day1"), encoding="utf-8")
    assert behavior_probe.analyze(tmp_path)["common_eligible_active_dates"] == ["day1"]


def test_已经加入但未观察到资格不能充当机会分母(tmp_path):
    (tmp_path / "debug.log").write_text("SITAI OPPORTUNITY;RUS;BACKER;yes;day\n", encoding="utf-8")
    country = behavior_probe.analyze(tmp_path)["countries"]["RUS"]
    assert country["joined"] == 1
    assert country["independent_opportunities"] == 0


def test_第三方标签参数不会在替换中串成同一国家():
    files = behavior_probe.build(initiator="SAR", target="AUS")
    actions = files["common/on_actions/zz_sitai_opportunity.txt"]
    assert "c:SAR ?= this" in actions
    assert "target_country = c:AUS" in actions
    events = files["events/zz_sitai_opportunity.txt"]
    assert "initiator_is = c:SAR target_is = c:AUS" in events


def test_观察国与旧模板标签相同也不会被替换():
    files = behavior_probe.build(
        initiator="GBR", target="TUR", tags=("AUS", "SAR"), market_readings=True
    )
    text = files["events/zz_sitai_opportunity.txt"]
    actions = files["common/on_actions/zz_sitai_opportunity.txt"]
    assert not parse_text(text).errors
    assert "c:AUS ?= { save_scope_as = sitai_aus }" in actions
    assert "c:SAR ?= { save_scope_as = sitai_sar }" in actions
    assert "SITAI OPPORTUNITY;AUS;ACTIVE" in text
    assert "DEPENDENCY_INIT" in text


@pytest.mark.parametrize(
    ("initiator", "target"), [("RUS", "AUS"), ("AUS", "PRU"), ("AUS", "AUS"), ("../", "SAR")]
)
def test_机会标签拒绝观察国重复和不规范名称(initiator, target):
    with pytest.raises(ValueError, match="第三方"):
        behavior_probe.build(initiator=initiator, target=target)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "[bad.function]"])
def test_评分必须实际解析为有限数值(tmp_path, value):
    (tmp_path / "debug.log").write_text(
        f"SITAI OPPORTUNITY;RUS;INIT_SCORE;{value};day\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="分数"):
        behavior_probe.analyze(tmp_path)
