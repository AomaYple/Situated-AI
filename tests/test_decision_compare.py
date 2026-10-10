"""固定检查点配对、资格门与重复观测的评分归因边界。"""

import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest

from pdx import decision_probe, decisions, game_run
from tools.probe import decision_compare
from tools.probe.decision_compare import compare

pytestmark = pytest.mark.unit


def report(score="-10", *, neutrality=0, aggression=0):
    rows = []
    for tag in ("RUS", "PRU"):
        for kind, value in (
            ("ACTIVE", "yes"),
            ("UNDECIDED", "yes"),
            ("CAN_INIT", "yes"),
            ("INIT_SCORE", score),
        ):
            rows.append({"tag": tag, "kind": kind, "value": value, "date": "day1"})
    return {
        "ok": True,
        "mount_allowlist": ["c:/game", "c:/mods/probe"],
        "log_findings": {
            "errors": dict.fromkeys(game_run.ERROR_MARKERS, 0),
            "mod_errors": [],
            "missing_mounts": [],
        },
        "loaded_save": {"sha256": "f" * 64},
        "game_version": {"branch": "1.14.5"},
        "source_hashes": {
            "sitai_decision_candidate": {
                "common/ai_strategies/00_default_strategy.txt": hashlib.sha256(
                    decisions.build(
                        replace(decisions.load(), neutrality=neutrality, aggression=aggression)
                    )["common/ai_strategies/00_default_strategy.txt"].encode("utf-8")
                ).hexdigest(),
                "trigger": "same",
            },
            "instrument": {"probe": "same"},
        },
        "analysis": {
            "opportunity": {"rows": rows, "countries": {"RUS": {"joined": 0}, "PRU": {"joined": 0}}}
        },
        "evidence": "fixture",
    }


def test_有效评分差分不会升级为行为质量通过():
    left, right = report(), report("-35", neutrality=25)
    result = compare(left, right)
    assert result["two_country_score_effect_observed"]
    assert result["countries"]["RUS"]["active_score_deltas"] == {"-25.0": 1}
    assert not result["quality_improvement_proven"]
    assert not result["phase_alignment_verified"]


def test_有评分也不能接受错位的外交阶段():
    left, right = report(), report("-35", neutrality=25)
    for arm, phase in ((left, "36"), (right, "37")):
        arm["analysis"]["opportunity"]["rows"].append(
            {"tag": "CONTROL", "kind": "ESCALATION", "value": phase, "date": "day1"}
        )
    with pytest.raises(ValueError, match="阶段"):
        compare(left, right)


def test_实际角色差异独立报告不把缺记录当未加入():
    left, right = report(), report("-35", neutrality=25)
    for arm, backed in ((left, "yes"), (right, "no")):
        for tag in ("RUS", "PRU"):
            arm["analysis"]["opportunity"]["rows"].extend(
                {"tag": tag, "kind": kind, "value": value, "date": "day1"}
                for kind, value in (
                    ("BACKER", backed),
                    ("INIT_BACKER", backed),
                    ("TARGET_BACKER", "no"),
                )
            )
    result = compare(left, right)
    country = result["countries"]["RUS"]
    assert country["role_observation_complete"]
    assert country["role_differences"][0]["control"]["INIT_BACKER"] == "yes"
    assert country["role_differences"][0]["treatment"]["INIT_BACKER"] == "no"
    assert not result["quality_improvement_proven"]
    right["analysis"]["opportunity"]["rows"] = [
        row for row in right["analysis"]["opportunity"]["rows"] if row["kind"] != "BACKER"
    ]
    country = compare(left, right)["countries"]["RUS"]
    assert not country["role_observation_complete"]
    assert not country["role_differences"]


def test_任意两个观察国按证据集合比较且不混入其他国家():
    left, right = report(), report("-35", neutrality=25)
    for arm in (left, right):
        analysis = arm["analysis"]["opportunity"]
        mapping = {"RUS": "BEL", "PRU": "NET"}
        analysis["countries"] = {
            mapping[tag]: value for tag, value in analysis["countries"].items()
        }
        for row in analysis["rows"]:
            row["tag"] = mapping[row["tag"]]
    result = compare(left, right)
    assert set(result["countries"]) == {"BEL", "NET"}
    assert result["two_country_score_effect_observed"]
    del right["analysis"]["opportunity"]["countries"]["NET"]
    with pytest.raises(ValueError, match="相同"):
        compare(left, right)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("ok", False),
        ("loaded_save", {"sha256": "different"}),
        ("game_version", {"branch": "other"}),
    ],
)
def test_失败局不同检查点不同游戏版本不得配对(path, value):
    right = deepcopy(report(neutrality=25))
    right[path] = value
    with pytest.raises(ValueError):
        compare(report(), right)


def test_改变仪器会使配对失效():
    right = report(neutrality=25)
    right["source_hashes"]["instrument"]["probe"] = "different"
    with pytest.raises(ValueError, match="非策略"):
        compare(report(), right)


def test_两臂挂载允许清单不一致不得配对():
    right = report(neutrality=25)
    right["mount_allowlist"].append("c:/mods/unexpected")
    with pytest.raises(ValueError, match="允许清单"):
        compare(report(), right)


@pytest.mark.parametrize("other", [None, "l_simp_chinese"])
def test_临时语言不同或另一臂缺证不接受配对(other):
    left, right = report(), report(neutrality=25)
    left["language"] = "l_english"
    right["language"] = other
    with pytest.raises(ValueError, match="语言"):
        compare(left, right)


def test_旧门禁和引擎错误拒绝评分配对():
    right = report(neutrality=25)
    del right["log_findings"]["errors"]["Script system error!"]
    with pytest.raises(ValueError, match="门禁"):
        compare(report(), right)
    right = report(neutrality=25)
    right["log_findings"]["mod_errors"] = ["unexpected sitai error"]
    with pytest.raises(ValueError, match="门禁"):
        compare(report(), right)


def test_只有评分变化但无资格不能算有效行为窗口():
    right = report("-35", neutrality=25)
    for row in right["analysis"]["opportunity"]["rows"]:
        if row["kind"] == "CAN_INIT":
            row["value"] = "no"
    result = compare(report(), right)
    assert not result["two_country_score_effect_observed"]


@pytest.mark.parametrize("delta", [float("nan"), float("inf"), -25, 0, 101])
def test_拒绝非有限或越界偏置(delta):
    with pytest.raises(ValueError, match="有限"):
        compare(report(), report(neutrality=25), neutrality_delta=delta)


def test_拒绝任意默认策略改动和多个字段同时变化():
    right = report(neutrality=25)
    right["source_hashes"]["sitai_decision_candidate"][
        "common/ai_strategies/00_default_strategy.txt"
    ] = "0" * 64
    with pytest.raises(ValueError, match="额外改动"):
        compare(report(), right)
    # aggression=-0.25 已从生产实验臂撤下；比较器应先拒绝未声明的默认策略，
    # 而不是把它误报成可接受的单字段差分。
    with pytest.raises(ValueError, match="默认策略"):
        compare(report(), report(neutrality=25, aggression=-0.25))


def test_同样的短检查点指纹也不接受():
    left, right = report(), report(neutrality=25)
    left["loaded_save"]["sha256"] = right["loaded_save"]["sha256"] = "short"
    with pytest.raises(ValueError, match="完整"):
        compare(left, right)


def test_部分分数符合但存在相反差分不宣布单字段效果通过():
    left, right = report(), report("-35", neutrality=25)
    for arm, score in ((left, "0"), (right, "2")):
        for kind, value in (
            ("ACTIVE", "yes"),
            ("UNDECIDED", "yes"),
            ("CAN_INIT", "yes"),
            ("INIT_SCORE", score),
        ):
            arm["analysis"]["opportunity"]["rows"].append(
                {"tag": "RUS", "kind": kind, "value": value, "date": "day2"}
            )
    assert not compare(left, right)["two_country_score_effect_observed"]


def test_缺少候选产物不能靠数值巧合证明字段差分():
    left, right = report(), report("-35", neutrality=25)
    for arm in (left, right):
        del arm["source_hashes"]["sitai_decision_candidate"]
    with pytest.raises(ValueError, match="候选"):
        compare(left, right)


def test_同采样键冲突必须拒绝而完全相同重复不膨胀():
    left, right = report(), report("-35", neutrality=25)
    rows = right["analysis"]["opportunity"]["rows"]
    rows.append(dict(rows[-1]))
    assert compare(left, right)["countries"]["PRU"]["active_score_deltas"] == {"-25.0": 1}
    rows.append({**rows[-1], "value": "5"})
    with pytest.raises(ValueError, match="冲突"):
        compare(left, right)


def test_只有发起方资格不能把目标方评分算有效():
    left, right = report(), report("-35", neutrality=25)
    for arm, score in ((left, "20"), (right, "-5")):
        for tag in ("RUS", "PRU"):
            arm["analysis"]["opportunity"]["rows"].append(
                {"tag": tag, "date": "day1", "kind": "TARGET_SCORE", "value": score}
            )
    result = compare(left, right)
    assert result["countries"]["RUS"]["active_score_deltas"] == {"-25.0": 1}


def test_退出后仍有偏置不能验收停止干预():
    left, right = report(), report("-35", neutrality=25)
    for arm, score in ((left, "0"), (right, "-25")):
        for tag in ("RUS", "PRU"):
            for kind, value in (("ACTIVE", "no"), ("INIT_SCORE", score)):
                arm["analysis"]["opportunity"]["rows"].append(
                    {"tag": tag, "date": "day2", "kind": kind, "value": value}
                )
    result = compare(left, right)
    assert result["two_country_score_effect_observed"]
    assert not result["two_country_exit_effect_observed"]
    assert result["countries"]["RUS"]["inactive_effect_status"] == "residual_difference"


def input_report(*, stress):
    result = report(neutrality=25, aggression=-0.25)
    result["source_hashes"]["zz_probe_decision_lifecycle"] = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in decision_probe.build(inject=stress).items()
    }
    result["analysis"]["fiscal"] = {
        "rows": [
            {"tag": tag, "kind": "RISK", "date": "sample-1", "value": "yes" if stress else "no"}
            for tag in ("RUS", "PRU")
        ],
        "countries": {
            tag: {"entry_observed": stress, "active_observed": stress, "exit_after_entry": stress}
            for tag in ("RUS", "PRU")
        },
    }
    return result


def test_财政输入对照只验输入与状态不冒充行为质量():
    result = decision_compare.compare_inputs(input_report(stress=False), input_report(stress=True))
    assert result["two_country_fiscal_input_effect_observed"]
    assert result["policy_unchanged"]
    assert not result["quality_improvement_proven"]


def test_财政输入对照拒绝其他仪器变动与反向实验臂():
    left, right = input_report(stress=False), input_report(stress=True)
    right["source_hashes"]["instrument"]["probe"] = "different"
    with pytest.raises(ValueError):
        decision_compare.compare_inputs(left, right)
    with pytest.raises(ValueError):
        decision_compare.compare_inputs(input_report(stress=True), input_report(stress=False))


def test_进入前的零差分不能当作退出后的零残留():
    left, right = report(), report("-35", neutrality=25)
    for arm in (left, right):
        rows = arm["analysis"]["opportunity"]["rows"]
        rows[:0] = [
            {"tag": tag, "date": "day0", "kind": kind, "value": value}
            for tag in ("RUS", "PRU")
            for kind, value in (("ACTIVE", "no"), ("INIT_SCORE", "0"))
        ]
    result = compare(left, right)
    assert not result["two_country_exit_effect_observed"]


def test_输入对照没有风险观测不能把缺失当无风险():
    left, right = input_report(stress=False), input_report(stress=True)
    left["analysis"]["fiscal"]["rows"] = []
    with pytest.raises(ValueError, match="观测"):
        decision_compare.compare_inputs(left, right)
