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


def _assignments(parent: Block):
    for node in parent.assignments():
        yield node
        if isinstance(node.value, Block):
            yield from _assignments(node.value)


def _diagnostic_logs(block, *, root, actor, saved, reference, seen, countries):
    """仅解释本仪器的分支子集；验证生成物逻辑，不模拟引擎类型或 TTL。"""
    scopes = {
        "scope:actor": actor,
        "scope:sitai_opportunity": saved,
        "global_var:sitai_response_reference": reference,
        **{f"c:{tag}": tag for tag in countries},
    }

    def condition(limit, current):
        for node in limit.assignments():
            if isinstance(node.value, Block):
                name = node.key.removesuffix(" ?")
                if not condition(node.value, scopes.get(name)):
                    return False
            else:
                assert isinstance(node.value, Scalar)
                value = node.value.unquoted
                if node.key == "exists" and scopes.get(value) is None:
                    return False
                if node.key == "this" and current != scopes.get(value):
                    return False
                if node.key == "has_global_variable" and not seen:
                    return False
        return True

    logs = []

    def execute(body):
        selected = False
        for node in body.assignments():
            if node.key in {"if", "else_if", "else"}:
                assert isinstance(node.value, Block)
                if node.key == "if":
                    selected = False
                matches = node.key == "else" or condition(_block(node.value, "limit"), root)
                if not selected and matches:
                    selected = True
                    execute(node.value)
            elif node.key == "debug_log":
                assert isinstance(node.value, Scalar)
                logs.append(node.value.unquoted)

    execute(block)
    return logs


@pytest.mark.parametrize(
    ("root", "saved", "reference", "seen", "actor", "countries", "want"),
    [
        ("play-a", None, None, False, None, {"RUS", "PRU"}, "missing;unbound;missing"),
        ("play-a", "play-a", "play-a", True, "RUS", {"RUS", "PRU"}, "same;same;RUS"),
        # 即使国家对相同，第二个对象也必须落入 different。
        ("play-b", "play-a", "play-a", True, "PRU", {"RUS", "PRU"}, "different;different;PRU"),
        ("play-b", None, "play-a", True, "ARG", {"RUS", "PRU"}, "missing;different;unmatched"),
        ("play-a", None, None, True, "RUS", {"RUS", "PRU"}, "missing;unavailable;RUS"),
        ("play-a", None, "play-a", True, "RUS", {"PRU"}, "missing;same;unmatched"),
    ],
)
def test_生成分支严格区分同对象另一个对象及不可用引用(
    root, saved, reference, seen, actor, countries, want
):
    files = behavior_probe.build(natural=True, play_types=("dp_humiliation",), response_hooks=True)
    tree = parse_text(files["common/on_actions/zz_sitai_opportunity.txt"])
    effect = _block(_block(tree.root, "zz_sitai_response_join_side"), "effect")
    logs = _diagnostic_logs(
        effect,
        root=root,
        actor=actor,
        saved=saved,
        reference=reference,
        seen=seen,
        countries=countries,
    )
    roots = [line for line in logs if line.startswith("SITAI RESPONSE ROOT2;")]
    assert roots == [
        f"SITAI RESPONSE ROOT2;join_side;{want};[THIS.GetEscalation];[TimeKeeper.GetCurrentDate.GetString]"
    ]
    assert sum(line.startswith("SITAI RESPONSE;") for line in logs) == int(saved == root)


@pytest.mark.parametrize("reference", ["unbound", "unavailable", "same", "different"])
@pytest.mark.parametrize("actor", ["missing", "unmatched", "ARG"])
def test_持久引用诊断保留未知且不能放行机会(tmp_path, reference, actor):
    (tmp_path / "debug.log").write_text(
        f"SITAI RESPONSE ROOT2;join_side;missing;{reference};{actor};50;1836.3.1\n",
        encoding="utf-8",
    )
    result = behavior_probe.analyze(tmp_path, natural_pair=("CHL", "BOL"), tags=("ARG", "BRA"))
    diagnostic = result["response_diagnostics"]
    assert diagnostic["events"] == [
        {
            "hook": "join_side",
            "saved_scope": "missing",
            "actor_id": None,
            "escalation": 50,
            "date_text": "1836.3.1",
            "protocol_version": 2,
            "persistent_scope": reference,
            "actor_state": "matched" if actor == "ARG" else actor,
            "actor_tag": "ARG" if actor == "ARG" else None,
        }
    ]
    assert diagnostic["opportunity_identity_verified"] is False
    assert diagnostic["actor_scope_supported"] is False
    assert result["natural_capture"]["captured"] is False
    assert result["natural_capture"]["complete_opportunity_denominator"] is None
    assert result["usable_for_paired_behavior"] is False
    assert result["quality_observations"]["status"] == "unsupported"


@pytest.mark.parametrize(
    "payload",
    [
        "join_side;missing;expired;ARG;50;1836.3.1",
        "join_side;missing;same;3;50;1836.3.1",
        "join_side;missing;same;arg;50;1836.3.1",
        "join_side;missing;same;ARG;101;1836.3.1",
        "join_side;missing;same;ARG;50;[TimeKeeper.GetCurrentDate.GetString]",
        "other;missing;same;ARG;50;1836.3.1",
        "join_side;other;same;ARG;50;1836.3.1",
        "join_side;missing;same;ARG;50;1836.3.1;extra",
    ],
)
def test_持久引用坏行不能静默丢弃(tmp_path, payload):
    (tmp_path / "debug.log").write_text(
        f"SITAI OPPORTUNITY;CONTROL;READY;CHL_BOL;sample-0\nSITAI RESPONSE ROOT2;{payload}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="根钩子诊断"):
        behavior_probe.analyze(tmp_path, natural_pair=("CHL", "BOL"), tags=("ARG", "BRA"))


def test_诊断声称匹配未声明国家时拒绝(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI RESPONSE ROOT2;join_side;missing;same;USA;50;1836.3.1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="未声明"):
        behavior_probe.analyze(tmp_path, natural_pair=("CHL", "BOL"), tags=("ARG", "BRA"))


def test_新旧协议混合保留顺序并不猜补旧身份(tmp_path):
    (tmp_path / "debug.1.log").write_text(
        "SITAI RESPONSE ROOT;join_side;missing;3;50;1836.3.1\n",
        encoding="utf-8",
    )
    (tmp_path / "debug.log").write_text(
        "SITAI RESPONSE ROOT2;abandon_side;missing;unavailable;RUS;51;1836.3.2\n",
        encoding="utf-8",
    )
    result = behavior_probe.analyze(tmp_path, natural_pair=("AUS", "SAR"))
    events = result["response_diagnostics"]["events"]
    assert len(events) == 2
    assert events[0]["actor_id"] == "3"
    assert "actor_tag" not in events[0]
    assert "persistent_scope" not in events[0]
    assert events[1]["actor_tag"] == "RUS"
    assert events[1]["persistent_scope"] == "unavailable"
    assert result["usable_for_paired_behavior"] is False


def test_实际生成唯一绑定写入有界引用且不转换未知actor():
    files = behavior_probe.build(
        natural=True,
        play_types=("dp_humiliation",),
        response_hooks=True,
        initiator="CHL",
        target="BOL",
        tags=("AUS", "PRU"),
    )
    script = files["common/on_actions/zz_sitai_opportunity.txt"]
    tree = parse_text(script)
    assert not tree.errors
    action = _block(tree.root, "zz_sitai_opportunity_bind")
    binding = _block(_block(action, "effect"), "if")
    assert "sitai_probe_natural_bound" in str(_block(binding, "limit"))
    reference = _block(binding, "set_global_variable")
    assert _text(reference, "name") == "sitai_response_reference"
    assert _text(reference, "value") == "scope:sitai_opportunity"
    assert _text(reference, "days") == "190"
    writes = [n for n in _assignments(tree.root) if n.key == "set_global_variable"]
    assert len(writes) == 2
    assert "sCountry('actor')" not in script
    assert "sC('actor')" not in script
    assert "c:SAR" not in script
    # AUS 是本次观察国，不能被旧模板的发起国标签替换成 CHL。
    assert "c:AUS ?= { this = scope:actor }" in script
    metadata = json.loads(files[".metadata/metadata.json"])
    assert metadata["game_custom_data"]["response_diagnostics"] == {
        "version": 2,
        "identity": "persistent-reference-unvalidated",
        "reference_days": 190,
        "actor": "declared-country-equality-unvalidated",
        "actor_tags": ["CHL", "BOL", "AUS", "PRU"],
        "unbound_root": True,
    }
    for hook in ("join_side", "abandon_side", "war_start"):
        effect = _block(_block(tree.root, f"zz_sitai_response_{hook}"), "effect")
        outer = _block(effect, "if")
        same = _block(outer, "if")
        assert _text(same, "debug_log").startswith(f"SITAI RESPONSE;{hook};")
        for branch in (same, _block(outer, "else"), _block(effect, "else")):
            ref_exists = _block(branch, "if")
            assert (
                _text(_block(ref_exists, "limit"), "exists")
                == "global_var:sitai_response_reference"
            )
            ref_same = _block(ref_exists, "if")
            assert _text(_block(ref_same, "limit"), "this") == "global_var:sitai_response_reference"
            unavailable = _block(_block(branch, "else"), "if")
            assert (
                _text(_block(unavailable, "limit"), "has_global_variable")
                == "sitai_response_reference_seen"
            )
            for actor_branch in (
                ref_same,
                _block(ref_exists, "else"),
                unavailable,
                _block(_block(branch, "else"), "else"),
            ):
                actor_exists = _block(actor_branch, "if")
                assert _text(_block(actor_exists, "limit"), "exists") == "scope:actor"
                candidates = [n for n in actor_exists.assignments() if n.key in {"if", "else_if"}]
                assert len(candidates) == 4
                for tag, candidate in zip(("CHL", "BOL", "AUS", "PRU"), candidates, strict=True):
                    assert isinstance(candidate.value, Block)
                    limit = _block(candidate.value, "limit")
                    assert _text(limit, "exists") == f"c:{tag}"
                    assert _text(_block(limit, f"c:{tag}"), "this") == "scope:actor"


def test_默认自然观察包不写入持久响应状态():
    files = behavior_probe.build(natural=True, play_types=("dp_humiliation",))
    script = files["common/on_actions/zz_sitai_opportunity.txt"]
    assert "sitai_response_reference" not in script
    assert "SITAI RESPONSE ROOT2" not in script


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


def test_生成诊断保留脚本链身份且元数据明确未验证():
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
        assert _text(same, "debug_log").startswith(f"SITAI RESPONSE;{hook};")
    metadata = json.loads(files[".metadata/metadata.json"])
    assert metadata["game_custom_data"]["response_diagnostics"] == {
        "version": 2,
        "identity": "persistent-reference-unvalidated",
        "reference_days": 190,
        "actor": "declared-country-equality-unvalidated",
        "actor_tags": ["AUS", "SAR", "RUS", "PRU"],
        "unbound_root": True,
    }
