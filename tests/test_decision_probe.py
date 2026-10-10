"""真实日志格式、轮转次序与两国生命周期证据判定。"""

from __future__ import annotations

import json

import pytest

from pdx import decision_probe
from pdx.localization import parse_loc_entries
from pdx.model import Block
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def test_原版输入仪器不引用生产变量并明确状态不可观测(tmp_path):
    files = decision_probe.build_observer(policy_state=False)
    actions = files["common/on_actions/zz_sitai_fiscal_observer.txt"]
    assert "sitai_fiscal_risk" not in actions
    assert "SITAI DECISION;RUS;RISK" not in actions
    lines = "".join(
        f"SITAI DECISION;{tag};{kind};no;sample-{sample}\n"
        for tag in ("RUS", "PRU")
        for sample in (4, 5)
        for kind in ("DEFAULT", "LOANS", "WAR")
    )
    path = tmp_path / "debug.log"
    path.write_text(lines, encoding="utf-8")
    result = decision_probe.analyze(tmp_path, strict=True, policy_state=False)
    for country in result["countries"].values():
        assert country["risk_observation_available"] is False
        assert country["entry_observed"] is None
        assert country["exit_after_entry"] is None
        assert country["active_observed"] is None
    path.write_text(lines + "SITAI DECISION;RUS;RISK;no;sample-5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="生产状态"):
        decision_probe.analyze(tmp_path, strict=True, policy_state=False)


def test_原版输入仪器仍拒绝漏采原生财政条件(tmp_path):
    lines = "".join(
        f"SITAI DECISION;{tag};{kind};no;sample-1\n"
        for tag in ("RUS", "PRU")
        for kind in ("DEFAULT", "LOANS")
    )
    (tmp_path / "debug.log").write_text(lines, encoding="utf-8")
    with pytest.raises(ValueError, match="WAR"):
        decision_probe.analyze(tmp_path, strict=True, policy_state=False)


def native_rows():
    return [
        f"SITAI DECISION;{tag};{kind};{value};sample-{sample}"
        for tag in ("RUS", "PRU")
        for sample in (4, 5)
        for kind, value in (
            ("DEFAULT", "no"),
            ("LOANS", "yes"),
            ("WAR", "no"),
            ("NATIVE_CREDIT_POS", "yes"),
            ("NATIVE_ENTRY", "no"),
            ("NATIVE_HOLD", "yes"),
            ("NATIVE_WEEKS", "40.000"),
        )
    ]


def test_原生财政只读条件复用生产阈值但不写生产状态(tmp_path):
    import hashlib

    from pdx import decisions

    previous = decision_probe.build_observer(policy_state=False)[
        "common/on_actions/zz_sitai_fiscal_observer.txt"
    ]
    assert (
        hashlib.sha256(previous.encode()).hexdigest()
        == "17c830a0567ec260ba7e8cf16dcfd6bb615cdd2b414a2dbe7b571a43cee9141c"
    )
    text = decision_probe.build_observer(policy_state=False, native_fiscal_inputs=True)[
        "common/on_actions/zz_sitai_fiscal_observer.txt"
    ]
    assert not parse_text(text).errors
    for weeks in (decisions.load().entry_weeks, decisions.load().exit_weeks):
        assert decisions.fiscal_condition(weeks) in text
    for forbidden in (
        "sitai_fiscal_risk",
        "add_treasury",
        "set_strategy",
        "create_diplomatic_play",
    ):
        assert forbidden not in text
    (tmp_path / "debug.log").write_bytes(("\n".join(native_rows()) + "\n").encode())
    result = decision_probe.analyze(tmp_path, policy_state=False, native_fiscal_inputs=True)
    assert len(result["native_fiscal_inputs"]["rows"]) == 16
    assert not result["native_fiscal_inputs"]["active_inferred"]
    for country in result["countries"].values():
        assert country["risk_observation_available"] is False
        assert country["active_observed"] is None
        assert country["entry_observed"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "cross_sample",
        "country",
        "unknown_field",
        "unknown_legacy_field",
        "production_state",
    ],
)
def test_原生财政输入缺失和声明漂移不能静默接受(tmp_path, fault):
    rows = native_rows()
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows.append(rows[-1])
    elif fault == "cross_sample":
        rows[-1] = rows[-1].replace("sample-5", "sample-6")
    elif fault == "country":
        rows.append(rows[-1].replace("PRU", "FRA"))
    elif fault == "unknown_field":
        rows.append(rows[-1].replace("NATIVE_WEEKS", "NATIVE_UNKNOWN"))
    elif fault == "unknown_legacy_field":
        rows.append(rows[-1].replace("NATIVE_WEEKS", "BOGUS"))
    else:
        rows.append("SITAI DECISION;RUS;RISK;yes;sample-4")
    (tmp_path / "debug.log").write_bytes(("\n".join(rows) + "\n").encode())
    with pytest.raises(ValueError):
        decision_probe.analyze(tmp_path, policy_state=False, native_fiscal_inputs=True)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "[unresolved]", ""])
def test_原生财政周数未解析不能当零(tmp_path, value):
    rows = [line.replace(";40.000;", f";{value};") for line in native_rows()]
    (tmp_path / "debug.log").write_bytes(("\n".join(rows) + "\n").encode())
    with pytest.raises(ValueError, match="周数"):
        decision_probe.analyze(tmp_path, policy_state=False, native_fiscal_inputs=True)


def test_未开启原生输入时拒绝混入观测(tmp_path):
    (tmp_path / "debug.log").write_bytes(("\n".join(native_rows()) + "\n").encode())
    with pytest.raises(ValueError, match="未声明"):
        decision_probe.analyze(tmp_path, policy_state=False)


@pytest.mark.parametrize("policy_state", [False, True])
def test_原生输入支持自定义国家且生产变量仍独立观测(tmp_path, policy_state):
    rows = [line.replace("RUS", "SAX").replace("PRU", "BAV") for line in native_rows()]
    if policy_state:
        rows += [
            f"SITAI DECISION;{tag};RISK;yes;sample-{sample}"
            for tag in ("SAX", "BAV")
            for sample in (4, 5)
        ]
    (tmp_path / "debug.log").write_bytes(("\n".join(rows) + "\n").encode())
    result = decision_probe.analyze(
        tmp_path, tags=("SAX", "BAV"), policy_state=policy_state, native_fiscal_inputs=True
    )
    for country in result["countries"].values():
        assert country["risk_observation_available"] is policy_state
        assert country["active_observed"] is None
    assert not result["native_fiscal_inputs"]["production_risk_state_inferred"]


@pytest.mark.parametrize("value", ["−1,250", "0.000", "92233720368547.758"])
def test_本地化周数及原版超大读数仅保持为观察值(tmp_path, value):
    rows = [line.replace(";40.000;", f";{value};") for line in native_rows()]
    (tmp_path / "debug.log").write_bytes(("\n".join(rows) + "\n").encode())
    result = decision_probe.analyze(tmp_path, policy_state=False, native_fiscal_inputs=True)
    assert {
        row["value"]
        for row in result["native_fiscal_inputs"]["rows"]
        if row["kind"] == "NATIVE_WEEKS"
    } == {value}


@pytest.mark.parametrize("tags", [("RUS",), ("RUS", "RUS"), ("RUS", "BAD }"), ("rus", "PRU")])
def test_原生输入的国家声明必须为两国唯一规范标签(tags):
    with pytest.raises(ValueError, match="国家"):
        decision_probe.build_observer(tags=tags, native_fiscal_inputs=True)


@pytest.mark.parametrize("weeks", [0, -1, True, 26.0])
def test_财政条件生成拒绝非正整数(weeks):
    from pdx import decisions

    with pytest.raises(ValueError):
        decisions.fiscal_condition(weeks)


def test_真实标量颜色分隔符不破坏日期(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI DECISION;RUS;PRINCIPAL;\x15v; 55.00\x15!;1月 28, 1836\n", encoding="utf-8"
    )
    row = decision_probe.analyze(tmp_path)["rows"][0]
    assert row["value"] == "55.00"
    assert row["date"] == "1月 28, 1836"


def test_轮转日志保留重复并按时间读退出(tmp_path):
    (tmp_path / "debug.10.log").write_text("SITAI DECISION;RUS;RISK;no;date\n", encoding="utf-8")
    (tmp_path / "debug.2.log").write_text("SITAI DECISION;RUS;RISK;yes;date\n", encoding="utf-8")
    (tmp_path / "debug.log").write_text(
        "SITAI DECISION;RUS;RISK;no;date\nSITAI DECISION;RUS;RISK;no;date\n", encoding="utf-8"
    )
    result = decision_probe.analyze(tmp_path)
    assert result["countries"]["RUS"]["risk_series"] == ["no", "yes", "no", "no"]
    assert result["countries"]["RUS"]["exit_after_entry"]
    assert not result["countries"]["PRU"]["entry_observed"]
    assert not result["behavior_causality"]


def test_探针注入不会混入生产生成链():
    for name, text in decision_probe.build().items():
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
            assert text.count("add_treasury = -1000000000") == 2


def test_财政探针可声明另一组国家且默认字节不变():
    custom = decision_probe.build(tags=("SAX", "BAV"))
    text = custom["common/on_actions/zz_sitai_decision_probe.txt"]
    assert "c:SAX" in text
    assert "c:BAV" in text
    assert "c:RUS" not in text
    assert "c:PRU" not in text
    assert decision_probe.build() == decision_probe.build(tags=decision_probe.DEFAULT_TAGS)


def test_卸载观察仪器不会刷新生产状态():
    def assert_private_writes(block):
        for assignment in block.assignments():
            if assignment.key in {"set_variable", "change_variable"}:
                assert isinstance(assignment.value, Block)
                name = assignment.value.first("name")
                assert name is not None
                assert str(name.value) == decision_probe.SAMPLE_VAR
            if isinstance(assignment.value, Block):
                assert_private_writes(assignment.value)

    for name, text in decision_probe.build_observer().items():
        if name.endswith(".txt"):
            tree = parse_text(text, name)
            assert not tree.errors
            assert_private_writes(tree.root)
            assert "remove_variable" not in text
            assert "add_treasury" not in text
            assert "sitai_update_fiscal" not in text


@pytest.mark.parametrize(
    "variable", ["sitai_fiscal_risk", "sitai_probe_", "sitai_probe_a }", "sitai_probe_A"]
)
def test_采样序号拒绝生产命名空间和脚本注入(variable):
    with pytest.raises(ValueError, match="仪器命名空间"):
        decision_probe.sample_step(variable)


def test_私有序号可解析且不会调用全局GUI日期(tmp_path):
    assert not parse_text(decision_probe.sample_step(decision_probe.SAMPLE_VAR)).errors
    assert all("TimeKeeper" not in text for text in decision_probe.build_observer().values())
    (tmp_path / "debug.log").write_text("SITAI DECISION;RUS;RISK;yes;sample-1\n", encoding="utf-8")
    analysis = decision_probe.analyze(tmp_path)
    assert analysis["rows"][0]["date"] == "sample-1"
    assert "不是日历日期" in analysis["time_basis"]


@pytest.mark.parametrize("row", ["RISK;INVALID;sample-1", "RISK;yes;sample-error", "truncated"])
def test_财政观测错误与空日志不能被当作没有风险(tmp_path, row):
    with pytest.raises(ValueError):
        decision_probe.analyze(tmp_path)
    (tmp_path / "debug.log").write_text(f"SITAI DECISION;RUS;{row}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        decision_probe.analyze(tmp_path)


def test_财政输入反事实可以关闭注入而不改读数():
    files = decision_probe.build(inject=False)
    text = files["common/on_actions/zz_sitai_decision_probe.txt"]
    assert not parse_text(text).errors
    assert "add_treasury" not in text
    assert "SITAI DECISION;RUS;ACTIVE" in text
    assert "SITAI DECISION;PRU;ACTIVE" in text


def test_严格生命周期拒绝缺国和缺月(tmp_path):
    (tmp_path / "debug.log").write_text(
        "\n".join(
            [
                "SITAI DECISION;RUS;RISK;no;sample-1",
                "SITAI DECISION;RUS;RISK;yes;sample-3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"缺少国家观测|不连续"):
        decision_probe.analyze(tmp_path, strict=True)


def test_严格生命周期允许两国连续样本并按样本序列判退出(tmp_path):
    rows = []
    for tag in ("RUS", "PRU"):
        for sample, value in ((1, "no"), (2, "yes"), (3, "no")):
            rows.append(f"SITAI DECISION;{tag};RISK;{value};sample-{sample}")
    (tmp_path / "debug.log").write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = decision_probe.analyze(tmp_path, strict=True)
    assert result["countries"]["RUS"]["exit_after_entry"]
    assert result["countries"]["PRU"]["entry_observed"]


def test_严格生命周期支持自定义国家对(tmp_path):
    rows = []
    for tag in ("SAX", "BAV"):
        for sample, value in ((1, "no"), (2, "yes"), (3, "no")):
            rows.append(f"SITAI DECISION;{tag};RISK;{value};sample-{sample}")
    (tmp_path / "debug.log").write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = decision_probe.analyze(tmp_path, strict=True, tags=("SAX", "BAV"))
    assert result["countries"]["SAX"]["exit_after_entry"]
    assert result["countries"]["BAV"]["entry_observed"]


def test_严格式样本可从检查点已有计数继续(tmp_path):
    rows = []
    for tag in ("RUS", "PRU"):
        for sample, value in ((4, "no"), (5, "yes"), (6, "no")):
            rows.append(f"SITAI DECISION;{tag};RISK;{value};sample-{sample}")
    (tmp_path / "debug.log").write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = decision_probe.analyze(tmp_path, strict=True)
    assert result["countries"]["RUS"]["exit_after_entry"]
    assert result["countries"]["PRU"]["entry_observed"]


def test_严格生命周期拒绝中间月份缺少风险读数(tmp_path):
    rows = []
    for tag in ("RUS", "PRU"):
        rows.extend(
            [
                f"SITAI DECISION;{tag};RISK;no;sample-1",
                f"SITAI DECISION;{tag};ACTIVE;no;sample-2",
                f"SITAI DECISION;{tag};RISK;yes;sample-3",
            ]
        )
    (tmp_path / "debug.log").write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="RISK 样本不连续"):
        decision_probe.analyze(tmp_path, strict=True)


def write_localization(tmp_path, *, english=True, chinese=False, duplicate=False):
    for lang, enabled in (("english", english), ("simp_chinese", chinese)):
        directory = tmp_path / "localization" / lang
        directory.mkdir(parents=True, exist_ok=True)
        keys = sorted(decision_probe.BASELINE_LOC_KEYS) if enabled else []
        text = f"l_{lang}:\n" + "\n".join(
            f' {key}:0 "value $placeholder$ \\"quoted\\""' for key in keys
        )
        (directory / "base.yml").write_text(text, encoding="utf-8")
        if duplicate and lang == "english":
            (directory / "duplicate.yml").write_text(text, encoding="utf-8")


def test_中文缺键实验只补缺失键并保留英语占位符(tmp_path):
    write_localization(tmp_path)
    files = decision_probe.build_localization_baseline(tmp_path)
    text = files["localization/simp_chinese/zz_sitai_vanilla_baseline_l_simp_chinese.yml"]
    language, entries = parse_loc_entries(text)
    assert language == "l_simp_chinese"
    assert {key for key, _value in entries} == decision_probe.BASELINE_LOC_KEYS
    assert all(value == 'value $placeholder$ \\"quoted\\"' for _key, value in entries)
    assert not any(name.startswith(("common/", "events/")) for name in files)
    assert set(json.loads(files["baseline.json"])["keys"]) == decision_probe.BASELINE_LOC_KEYS


def test_中文已有键不被实验覆盖(tmp_path):
    write_localization(tmp_path, chinese=True)
    files = decision_probe.build_localization_baseline(tmp_path)
    manifest = json.loads(files["baseline.json"])
    assert manifest["keys"] == {}
    assert set(manifest["already_present"]) == decision_probe.BASELINE_LOC_KEYS


@pytest.mark.parametrize("duplicate", [False, True])
def test_缺失或歧义底本拒绝猜测(tmp_path, duplicate):
    write_localization(tmp_path, english=duplicate, duplicate=duplicate)
    with pytest.raises(ValueError, match=r"底本|重复"):
        decision_probe.build_localization_baseline(tmp_path)
