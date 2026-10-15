"""根钩子诊断不推断机会、国家响应或行为质量。"""

from __future__ import annotations

import json
from argparse import Namespace

import pytest

from pdx import behavior_probe
from pdx.model import Block, Scalar
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def _block(parent: Block, key: str) -> Block:
    node = parent.first(key)
    assert node is not None
    assert isinstance(node.value, Block)
    return node.value


def _text(parent: Block, key: str) -> str:
    node = parent.first(key)
    assert node is not None
    assert isinstance(node.value, Scalar)
    return node.value.unquoted


@pytest.mark.parametrize("binding", ["missing", "same", "different"])
@pytest.mark.parametrize("actor", ["missing", "5"])
def test_独立根事件不能充当已绑定机会或行为样本(tmp_path, binding, actor):
    (tmp_path / "debug.log").write_text(
        f"SITAI RESPONSE ROOT;join_side;{binding};{actor};50;1836.3.1\n",
        encoding="utf-8",
    )
    result = behavior_probe.analyze(tmp_path, natural_pair=("AUS", "SAR"))
    diagnostic = result["response_diagnostics"]
    assert diagnostic["count"] == 1
    assert diagnostic["events"] == [
        {
            "hook": "join_side",
            "saved_scope": binding,
            "actor_id": None if actor == "missing" else "5",
            "escalation": 50,
            "date_text": "1836.3.1",
        }
    ]
    assert diagnostic["opportunity_identity_verified"] is False
    assert diagnostic["actor_scope_supported"] is False
    assert diagnostic["absence_proves_no_response"] is False
    assert diagnostic["quality_improvement_proven"] is False
    assert result["natural_capture"]["captured"] is False
    assert result["usable_for_paired_behavior"] is False
    assert result["quality_observations"]["status"] == "unsupported"
    assert result["quality_observations"]["join_latency"] is None
    assert result["countries"]["RUS"]["joined"] == 0
    assert result["countries"]["RUS"]["absence_is_neutrality"] is False


@pytest.mark.parametrize(
    "payload",
    [
        "other;missing;5;50;1836.3.1",
        "join_side;unknown;5;50;1836.3.1",
        "join_side;missing;-1;50;1836.3.1",
        "join_side;missing;;50;1836.3.1",
        "join_side;missing;[SCOPE.sCountry(actor).GetIDString];50;1836.3.1",
        "join_side;missing;5;-1;1836.3.1",
        "join_side;missing;5;101;1836.3.1",
        "join_side;missing;5;nan;1836.3.1",
        "join_side;missing;5;50;",
        "join_side;missing;5;50;[TimeKeeper.GetCurrentDate.GetString]",
        "join_side;missing;5;50;1836.3.1;extra",
        "join_side;missing;5;50",
    ],
)
def test_诊断坏行不能被普通机会记录掩盖(tmp_path, payload):
    (tmp_path / "debug.log").write_text(
        f"SITAI OPPORTUNITY;CONTROL;READY;AUS_SAR;sample-0\nSITAI RESPONSE ROOT;{payload}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="根钩子诊断"):
        behavior_probe.analyze(tmp_path, natural_pair=("AUS", "SAR"))


def test_没有根事件仍明确未观察到且不推断无响应(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI OPPORTUNITY;CONTROL;READY;AUS_SAR;sample-0\n", encoding="utf-8"
    )
    result = behavior_probe.analyze(tmp_path, natural_pair=("AUS", "SAR"), response_hooks=True)
    assert result["response_diagnostics"]["status"] == "no_root_events_observed"
    assert result["response_diagnostics"]["events"] == []
    assert result["response_diagnostics"]["absence_proves_no_response"] is False
    assert result["natural_capture"]["captured"] is False


def test_轮转根事件保留顺序和重复但不按actor或日期合并机会(tmp_path):
    root = "SITAI RESPONSE ROOT;join_side;missing;5;50;1836.3.1\n"
    (tmp_path / "debug.2.log").write_text(root, encoding="utf-8")
    (tmp_path / "debug.log").write_text(
        root + "SITAI RESPONSE ROOT;abandon_side;different;5;51;1836.3.1\n", encoding="utf-8"
    )
    result = behavior_probe.analyze(tmp_path, natural_pair=("AUS", "SAR"))
    diagnostic = result["response_diagnostics"]
    assert diagnostic["count"] == 3
    assert [event["hook"] for event in diagnostic["events"]] == [
        "join_side",
        "join_side",
        "abandon_side",
    ]
    assert result["natural_capture"]["complete_opportunity_denominator"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"purpose": "M3-A"},
        {"purpose": "M3-B"},
        {"purpose": "reconnaissance"},
        {"arm": "candidate"},
        {"fiscal_injection": "stress"},
        {"natural_opportunity": False},
        {"keep_save": True},
    ],
)
def test_诊断错误目的在任何源生成和游戏副作用前拒绝(tmp_path, mutation):
    from tools.probe import decision_behavior

    args = Namespace(
        **{
            "purpose": "instrument",
            "arm": "control",
            "fiscal_injection": "none",
            "natural_opportunity": True,
            "response_hooks": True,
            "keep_save": False,
            **mutation,
        }
    )
    source = tmp_path / "sources"
    with pytest.raises(ValueError, match="外交响应钩子"):
        decision_behavior.execute(args, tmp_path / "out", source)
    assert not source.exists()


@pytest.mark.parametrize("root_event", [False, True])
def test_实际入口冻结诊断版本并将合成日志交给分析器(tmp_path, monkeypatch, root_event):
    from pdx import config, game_run, response_probe
    from tools.probe import decision_behavior

    game = tmp_path / "game"
    for relative, text in (
        ("common/laws/laws.txt", "law_autocracy = {}\n"),
        ("common/ai_strategies/strategies.txt", "ai_strategy_test = { type = political }\n"),
        ("common/diplomatic_plays/plays.txt", "dp_humiliation = {}\n"),
    ):
        path = game / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)
    logdir = tmp_path / "logs"
    logdir.mkdir()
    rows = (
        "SITAI DECISION;RUS;RISK;no;sample-1\n"
        "SITAI DECISION;PRU;RISK;no;sample-1\n"
        "SITAI OPPORTUNITY;CONTROL;READY;AUS_SAR;sample-0\n"
    )
    if root_event:
        rows += "SITAI RESPONSE ROOT;join_side;missing;5;50;1836.3.1\n"
    (logdir / "debug.log").write_text(rows, encoding="utf-8")

    def run(sources, **kwargs):
        observer = sources["zz_probe_decision_opportunity"]
        metadata = json.loads((observer / ".metadata/metadata.json").read_text(encoding="utf-8"))
        assert (
            metadata["game_custom_data"]["response_diagnostics"] == response_probe.configuration()
        )
        observation = kwargs["qualification_context"]["observation"]
        assert observation["response_hooks"] == response_probe.configuration()
        result = kwargs["analyze"](logdir)["opportunity"]
        assert result["response_diagnostics"]["count"] == int(root_event)
        assert result["natural_capture"]["captured"] is False
        assert result["quality_observations"]["status"] == "unsupported"
        assert result["usable_for_paired_behavior"] is False
        return {"ok": True}

    monkeypatch.setattr(game_run, "run", run)
    args = Namespace(
        purpose="instrument",
        arm="control",
        fiscal_injection="none",
        natural_opportunity=True,
        response_hooks=True,
        keep_save=False,
        observers=("RUS", "PRU"),
        initiator="AUS",
        target="SAR",
        months=1,
        save=tmp_path / "input.v3",
    )
    assert decision_behavior.execute(args, tmp_path / "out", tmp_path / "sources") == 0


def test_生成诊断覆盖缺失相同和不同身份且保护actor读取():
    files = behavior_probe.build(natural=True, play_types=("dp_humiliation",), response_hooks=True)
    tree = parse_text(files["common/on_actions/zz_sitai_opportunity.txt"])
    assert not tree.errors
    actions = {a.key: a.value for a in tree.root.assignments()}
    for hook in ("join_side", "abandon_side", "war_start"):
        action = actions[f"zz_sitai_response_{hook}"]
        assert isinstance(action, Block)
        effect = _block(action, "effect")
        outer = _block(effect, "if")
        assert _text(_block(outer, "limit"), "exists") == "scope:sitai_opportunity"
        same = _block(outer, "if")
        assert _text(_block(same, "limit"), "this") == "scope:sitai_opportunity"
        branches = [same, _block(outer, "else"), _block(effect, "else")]
        for state, branch in zip(("same", "different", "missing"), branches, strict=True):
            guarded = _block(branch, "if")
            assert _text(_block(guarded, "limit"), "exists") == "scope:actor"
            positive = _text(guarded, "debug_log")
            negative = _text(_block(branch, "else"), "debug_log")
            assert positive.startswith(
                f"SITAI RESPONSE ROOT;{hook};{state};[SCOPE.sCountry('actor').GetIDString];"
            )
            assert negative.startswith(f"SITAI RESPONSE ROOT;{hook};{state};missing;")
        assert _text(same, "debug_log").startswith(f"SITAI RESPONSE;{hook};")
    metadata = json.loads(files[".metadata/metadata.json"])
    assert metadata["game_custom_data"]["response_diagnostics"] == {
        "version": 1,
        "identity": "chain-local-diagnostic",
        "actor": "guarded-id-unvalidated",
        "unbound_root": True,
    }
