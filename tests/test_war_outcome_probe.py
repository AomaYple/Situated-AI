"""战后回调仪器只证明日志分支，不代替引擎覆盖、净损失或行为质量。"""

from __future__ import annotations

import itertools
import json

import pytest

from pdx import behavior_probe, response_probe
from pdx.model import Block, Scalar
from pdx.parser import parse_text

pytestmark = pytest.mark.unit
TAGS = ("ARG", "BRA")
PAIR = ("CHL", "BOL")
ACTION_FILE = "common/on_actions/zz_sitai_opportunity.txt"


def _block(parent, key):
    node = parent.first(key)
    assert node is not None
    assert isinstance(node.value, Block)
    return node.value


def _logs(body, scopes, root, seen):
    """执行生成 AST 的条件子集，未知语句报错；不模拟引擎对象类型。"""

    def matches(limit, current):
        for node in limit.assignments():
            if isinstance(node.value, Block):
                target = scopes.get(node.key)
                if target is None or not matches(node.value, target):
                    return False
            else:
                assert isinstance(node.value, Scalar)
                value = node.value.unquoted
                if node.key == "exists":
                    if scopes.get(value) is None:
                        return False
                elif node.key == "this":
                    if current != scopes.get(value):
                        return False
                elif node.key == "has_global_variable":
                    assert value == "sitai_response_reference_seen"
                    if not seen:
                        return False
                else:
                    pytest.fail(f"未知条件 {node.key}")
        return True

    logs = []

    def execute(block):
        selected = False
        for node in block.assignments():
            if node.key in {"if", "else_if", "else"}:
                assert isinstance(node.value, Block)
                if node.key == "if":
                    selected = False
                if not selected and (
                    node.key == "else" or matches(_block(node.value, "limit"), root)
                ):
                    selected = True
                    execute(node.value)
            elif node.key == "debug_log":
                assert isinstance(node.value, Scalar)
                logs.append(node.value.unquoted)
            elif node.key != "limit":
                pytest.fail(f"未知效果 {node.key}")

    execute(body)
    return logs


@pytest.mark.parametrize("hook", ["won", "lost"])
@pytest.mark.parametrize("play", ["missing", "unbound", "unavailable", "same", "different"])
def test_实际生成逐国回调全部存在性分支并保留两个独立战目标标志(hook, play, subtests):
    files = behavior_probe.build(
        initiator=PAIR[0],
        target=PAIR[1],
        tags=TAGS,
        natural=True,
        play_types=("dp_humiliation",),
        response_hooks=True,
    )
    script = files[ACTION_FILE]
    tree = parse_text(script)
    assert not tree.errors
    # parser 曾漏报多余右括号；同时独立检查括号守恒与每个根包装结构。
    assert script.count("{") == script.count("}")
    wrapper = _block(tree.root, f"on_{hook}_war")
    assert [n.key for n in wrapper.assignments()] == ["on_actions"]
    effect = _block(_block(tree.root, f"zz_sitai_outcome_{hook}"), "effect")
    for tag, war, benefit, victim in itertools.product(
        TAGS, (False, True), (False, True), (False, True)
    ):
        with subtests.test(tag=tag, war=war, benefit=benefit, victim=victim):
            scopes = {
                "c:ARG": "ARG",
                "c:BRA": "BRA",
                "scope:war": "war-a" if war else None,
                "scope:diplomatic_play": None if play == "missing" else "play-a",
                "global_var:sitai_response_reference": (
                    "play-a" if play == "same" else "play-b" if play == "different" else None
                ),
                "scope:benefitted_from_wargoal": "flag" if benefit else None,
                "scope:victim_of_wargoal": "flag" if victim else None,
            }
            logs = _logs(effect, scopes, tag, play not in {"missing", "unbound"})
            assert logs == [
                (
                    f"SITAI WAR OUTCOME;{hook};{tag};{'present' if war else 'missing'};{play};"
                    f"{'yes' if benefit else 'no'};{'yes' if victim else 'no'};"
                    "[TimeKeeper.GetCurrentDate.GetString]"
                )
            ]
            event = response_probe.parse_outcome(
                logs[0].replace("[TimeKeeper.GetCurrentDate.GetString]", "1836.3.1"), observers=TAGS
            )
            assert event is not None
            assert event["benefitted_from_wargoal"] is benefit
            assert event["victim_of_wargoal"] is victim
            assert event["play_reference"] == play


@pytest.mark.parametrize("root", ["USA", None])
def test_非观察国和不存在国家不输出战后日志(root):
    files = behavior_probe.build(natural=True, play_types=("dp_humiliation",), response_hooks=True)
    tree = parse_text(files[ACTION_FILE])
    for hook in ("won", "lost"):
        effect = _block(_block(tree.root, f"zz_sitai_outcome_{hook}"), "effect")
        assert _logs(effect, {"c:RUS": "RUS", "c:PRU": "PRU"}, root, False) == []
        # 即使调用根声称为声明国家，对应对象不存在时也不能产生日志。
        assert _logs(effect, {}, "RUS", False) == []
        assert _logs(effect, {}, root, False) == []


@pytest.mark.parametrize(
    "payload",
    [
        "other;ARG;present;same;yes;no;1836.3.1",
        "won;USA;present;same;yes;no;1836.3.1",
        "won;CHL;present;same;yes;no;1836.3.1",
        "won;arg;present;same;yes;no;1836.3.1",
        "won;ARG;unknown;same;yes;no;1836.3.1",
        "won;ARG;present;expired;yes;no;1836.3.1",
        "won;ARG;present;same;1;no;1836.3.1",
        "won;ARG;present;same;yes;unknown;1836.3.1",
        "won;ARG;present;same;yes;no;",
        "won;ARG;present;same;yes;no;   ",
        "won;ARG;present;same;yes;no;[TimeKeeper.GetCurrentDate.GetString]",
        "won;ARG;present;same;yes;no;1836.3.1;extra",
        "won;ARG;present;same;yes;1836.3.1",
    ],
)
def test_坏结果行不能被正常机会行掩盖(tmp_path, payload):
    (tmp_path / "debug.log").write_text(
        f"SITAI OPPORTUNITY;CONTROL;READY;CHL_BOL;sample-0\nSITAI WAR OUTCOME;{payload}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="战后结果诊断"):
        behavior_probe.analyze(tmp_path, tags=TAGS, natural_pair=PAIR)


def test_轮转重复战后结果不升级质量或配对且不猜博弈身份(tmp_path):
    row = "SITAI WAR OUTCOME;won;ARG;missing;same;yes;yes;1836.3.1\n"
    (tmp_path / "debug.1.log").write_text(row, encoding="utf-8")
    (tmp_path / "debug.log").write_text(
        row + "SITAI WAR OUTCOME;lost;BRA;present;different;no;yes;1836.3.2\n"
        "SITAI RESPONSE ROOT;join_side;missing;5;50;1836.3.1\n",
        encoding="utf-8",
    )
    result = behavior_probe.analyze(tmp_path, tags=TAGS, natural_pair=PAIR)
    diagnostic = result["war_outcome_diagnostics"]
    assert diagnostic["status"] == "country_callbacks_observed"
    assert diagnostic["count"] == 3
    first, repeated, last = diagnostic["events"]
    assert (
        first
        == repeated
        == {
            "hook": "won",
            "tag": "ARG",
            "war_scope": "missing",
            "play_reference": "same",
            "benefitted_from_wargoal": True,
            "victim_of_wargoal": True,
            "date_text": "1836.3.1",
        }
    )
    assert last["hook"] == "lost"
    assert last["play_reference"] == "different"
    for key in (
        "opportunity_identity_verified",
        "country_coverage_verified",
        "absence_proves_no_harm",
        "quality_improvement_proven",
    ):
        assert diagnostic[key] is False
    assert result["response_diagnostics"]["count"] == 1
    assert result["natural_capture"]["captured"] is False
    assert result["natural_capture"]["complete_opportunity_denominator"] is None
    assert result["usable_for_paired_behavior"] is False
    assert result["quality_observations"]["status"] == "unsupported"
    assert result["quality_observations"]["adverse_outcome"] is None
    assert result["quality_observations"]["action_cost"] is None
    assert result["countries"]["ARG"]["joined"] == 0


def test_只有战后回调仍能分析但没有机会或质量样本(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI WAR OUTCOME;lost;ARG;missing;missing;no;no;1836.3.1\n",
        encoding="utf-8",
    )
    report = behavior_probe.analyze(tmp_path, tags=TAGS, natural_pair=PAIR)
    assert report["rows"] == []
    assert report["war_outcome_diagnostics"]["count"] == 1
    assert report["usable_for_paired_behavior"] is False
    assert report["quality_observations"]["adverse_outcome"] is None


def test_没有战后回调不能推断零损害(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI OPPORTUNITY;CONTROL;READY;CHL_BOL;sample-0\n",
        encoding="utf-8",
    )
    result = behavior_probe.analyze(tmp_path, tags=TAGS, natural_pair=PAIR, response_hooks=True)
    assert result["war_outcome_diagnostics"]["status"] == "no_country_callbacks_observed"
    assert result["war_outcome_diagnostics"]["events"] == []
    assert result["war_outcome_diagnostics"]["absence_proves_no_harm"] is False


def test_默认包不挂载结果钩子且诊断元数据限定两个观察国():
    ordinary = behavior_probe.build(
        initiator=PAIR[0], target=PAIR[1], tags=TAGS, natural=True, play_types=("dp_humiliation",)
    )
    assert "SITAI WAR OUTCOME" not in ordinary[ACTION_FILE]
    assert "on_won_war" not in ordinary[ACTION_FILE]
    diagnostic = behavior_probe.build(
        initiator=PAIR[0],
        target=PAIR[1],
        tags=TAGS,
        natural=True,
        play_types=("dp_humiliation",),
        response_hooks=True,
    )
    assert set(ordinary) == set(diagnostic)
    metadata = json.loads(diagnostic[".metadata/metadata.json"])
    assert metadata["game_custom_data"]["response_diagnostics"]["war_outcomes"] == {
        "version": 1,
        "hooks": ["on_won_war", "on_lost_war"],
        "observer_tags": list(TAGS),
        "identity": "persistent-play-reference-unvalidated",
        "country_coverage_verified": False,
        "quantitative_cost_supported": False,
    }
    for hook in ("won", "lost"):
        action = _block(parse_text(diagnostic[ACTION_FILE]).root, f"zz_sitai_outcome_{hook}")
        logs = [line for line in str(action).split('"') if line.startswith("SITAI WAR OUTCOME;")]
        assert logs
        assert all(
            ".Get" not in line.replace("[TimeKeeper.GetCurrentDate.GetString]", "") for line in logs
        )
