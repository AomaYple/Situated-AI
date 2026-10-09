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


def test_自然响应绑定精确原生对象且不创建机会():
    files = behavior_probe.build(
        initiator="CHL",
        target="BOL",
        tags=("ARG", "BRA"),
        natural=True,
        play_types=("dp_humiliation", "dp_conquer_state"),
    )
    actions = files["common/on_actions/zz_sitai_opportunity.txt"]
    events = files["events/zz_sitai_opportunity.txt"]
    assert "on_diplomatic_play_started" in actions
    assert "save_scope_as = sitai_opportunity" in actions
    assert "save_scope_as = sitai_arg" in actions
    assert "exists = c:ARG exists = c:BRA" in actions
    assert "exists = scope:sitai_opportunity" in events
    assert "TYPE;dp_conquer_state" in events
    assert "sitai_probe_natural_bound" in actions
    assert "sitai_probe_natural_response_sample" in events
    for name, text in files.items():
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
            for forbidden in (
                "create_diplomatic_play",
                "every_diplomatic_play",
                "add_treasury",
                "start_enactment",
                "set_strategy",
                "TimeKeeper",
            ):
                assert forbidden not in text


@pytest.mark.parametrize("types", [(), ("dp_a", "dp_a"), ("dp_a }",)])
def test_自然响应拒绝错误类型全集(types):
    with pytest.raises(ValueError, match="全量类型"):
        behavior_probe.build(natural=True, play_types=types)


@pytest.mark.parametrize("tags", [("AUS", "BRA"), ("ARG", "SAR"), ("AUS", "SAR")])
def test_自然响应存在性守卫保留真实观察国标签(tags):
    files = behavior_probe.build(
        initiator="CHL", target="BOL", tags=tags, natural=True, play_types=("dp_conquer_state",)
    )
    actions = files["common/on_actions/zz_sitai_opportunity.txt"]
    assert " ".join(f"exists = c:{tag}" for tag in tags) in actions
    assert "exists = c:CHL" not in actions
    assert "exists = c:BOL" not in actions


def natural_rows():
    lines = ["SITAI OPPORTUNITY;CONTROL;BIND;CHL_BOL;sample-0\n"]
    for sample in (1, 2):
        lines.extend(
            f"SITAI OPPORTUNITY;CONTROL;{kind};{value};sample-{sample}\n"
            for kind, value in (("TYPE", "dp_conquer_state"), ("ESCALATION", "20"))
        )
        for tag in ("ARG", "BRA"):
            lines.extend(
                f"SITAI OPPORTUNITY;{tag};{kind};{'no' if kind in {'BACKER', 'INIT_BACKER', 'TARGET_BACKER'} else 'yes'};sample-{sample}\n"
                for kind in sorted(behavior_probe.BOOLEAN_KINDS)
            )
            lines.extend(
                f"SITAI OPPORTUNITY;{tag};{kind};1;sample-{sample}\n"
                for kind in ("INIT_SCORE", "TARGET_SCORE")
            )
    return "".join(lines)


def test_自然响应完整矩阵也不冒充同机会配对或安全验收(tmp_path):
    (tmp_path / "debug.log").write_text(natural_rows(), encoding="utf-8")
    result = behavior_probe.analyze(tmp_path, tags=("ARG", "BRA"), natural_pair=("CHL", "BOL"))
    capture = result["natural_capture"]
    assert capture["captured"] is True
    assert capture["binding_matrix_complete"] is True
    assert capture["samples"] == 2
    assert capture["engine_safety_requires_clean_report"] is True
    assert not result["usable_for_paired_behavior"]
    assert not result["behavior_causality"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_bind",
        "duplicate_bind",
        "late_bind",
        "missing_field",
        "duplicate_field",
        "missing_country",
        "wrong_country",
        "bad_type",
        "missing_type",
        "gap",
        "absent_country",
        "malformed",
    ],
)
def test_自然响应拒绝漏项重复身份错误和混合场景(tmp_path, mutation):
    text = natural_rows()
    bind = text.splitlines(keepends=True)[0]
    field = "SITAI OPPORTUNITY;ARG;PRESENT;yes;sample-1\n"
    if mutation == "missing_bind":
        text = text.replace(bind, "")
    elif mutation == "duplicate_bind":
        text = bind + text
    elif mutation == "late_bind":
        text = text.replace(bind, "") + bind
    elif mutation == "missing_field":
        text = text.replace(field, "")
    elif mutation == "duplicate_field":
        text += field
    elif mutation == "missing_country":
        text = "\n".join(line for line in text.splitlines() if ";BRA;" not in line)
    elif mutation == "wrong_country":
        text = text.replace(";BRA;", ";USA;")
    elif mutation == "bad_type":
        text = text.replace("dp_conquer_state", "ERROR:no_object")
    elif mutation == "missing_type":
        text = "\n".join(line for line in text.splitlines() if ";TYPE;" not in line)
    elif mutation == "gap":
        text = text.replace("sample-2", "sample-3")
    elif mutation == "absent_country":
        text = text.replace(field, field.replace(";yes;", ";no;"))
    elif mutation == "malformed":
        text += "SITAI OPPORTUNITY;broken\n"
    (tmp_path / "debug.log").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        behavior_probe.analyze(tmp_path, tags=("ARG", "BRA"), natural_pair=("CHL", "BOL"))


def test_没有自然机会只报告未捕获而不是零收益(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI OPPORTUNITY;CONTROL;READY;CHL_BOL;sample-0\n", encoding="utf-8"
    )
    result = behavior_probe.analyze(tmp_path, tags=("ARG", "BRA"), natural_pair=("CHL", "BOL"))
    assert result["natural_capture"]["captured"] is False
    assert result["natural_capture"]["binding_matrix_complete"] is False
    assert result["natural_capture"]["complete_opportunity_denominator"] is None


@pytest.mark.parametrize(
    "mutation", ["before_bind", "after_end", "duplicate", "wrong_index", "reverse"]
)
def test_自然响应拒绝结束事件和日样本的错误时序(tmp_path, mutation):
    text = natural_rows()
    end = "SITAI OPPORTUNITY;CONTROL;END;CHL_BOL;sample-3\n"
    if mutation == "before_bind":
        text = end.replace("sample-3", "sample-0") + text
    elif mutation == "after_end":
        text = text.replace(
            "SITAI OPPORTUNITY;CONTROL;TYPE;dp_conquer_state;sample-2\n",
            end.replace("sample-3", "sample-2")
            + "SITAI OPPORTUNITY;CONTROL;TYPE;dp_conquer_state;sample-2\n",
        )
    elif mutation == "duplicate":
        text += end * 2
    elif mutation == "wrong_index":
        text += end.replace("sample-3", "sample-9")
    elif mutation == "reverse":
        lines = text.splitlines(keepends=True)
        text = lines[0] + "".join(line for line in lines[1:] if "sample-2" in line)
        text += "".join(line for line in lines[1:] if "sample-1" in line)
    (tmp_path / "debug.log").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        behavior_probe.analyze(tmp_path, tags=("ARG", "BRA"), natural_pair=("CHL", "BOL"))


@pytest.mark.parametrize("samples", [0, 2])
def test_自然响应结束保留与右截断的区别(tmp_path, samples):
    text = natural_rows() if samples else natural_rows().splitlines(keepends=True)[0]
    text += f"SITAI OPPORTUNITY;CONTROL;END;CHL_BOL;sample-{samples + 1}\n"
    (tmp_path / "debug.log").write_text(text, encoding="utf-8")
    result = behavior_probe.analyze(tmp_path, tags=("ARG", "BRA"), natural_pair=("CHL", "BOL"))
    capture = result["natural_capture"]
    assert capture["ended"] is True
    assert capture["end_sample"] == samples + 1
    assert capture["samples"] == samples
    assert capture["binding_matrix_complete"] is bool(samples)
    assert not result["usable_for_paired_behavior"]


@pytest.mark.parametrize("kind", ["BACKER", "INIT_BACKER", "TARGET_BACKER"])
def test_自然响应拒绝相互矛盾的实际选边(tmp_path, kind):
    text = natural_rows().replace(f";ARG;{kind};no;sample-1", f";ARG;{kind};yes;sample-1")
    (tmp_path / "debug.log").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="矛盾"):
        behavior_probe.analyze(tmp_path, tags=("ARG", "BRA"), natural_pair=("CHL", "BOL"))


@pytest.mark.parametrize(
    ("arm", "injection"), [("candidate", "none"), ("control", "stress"), ("control", "no-stress")]
)
def test_自然响应入口在部署前拒绝候选和注入(monkeypatch, tmp_path, arm, injection):
    import sys

    from tools.probe import decision_behavior

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "decision_behavior.py",
            "--save",
            str(tmp_path / "missing.v3"),
            "--arm",
            arm,
            "--fiscal-injection",
            injection,
            "--natural-opportunity",
        ],
    )
    monkeypatch.setattr(
        decision_behavior, "execute", lambda *_args: pytest.fail("不得进入源准备或部署")
    )
    with pytest.raises(SystemExit) as result:
        decision_behavior.main()
    assert result.value.code == 2
