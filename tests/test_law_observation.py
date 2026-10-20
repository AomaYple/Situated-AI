"""法律原生观测的生成、完整性和缺值合同，不启动游戏。"""

import hashlib
from itertools import product
from pathlib import Path

import pytest

from pdx import law_observation as observation
from pdx.model import Block, Scalar
from pdx.parser import parse_text


def test_完整法律键与指纹来自同次读取(tmp_path: Path) -> None:
    source = tmp_path / "common/laws/a.txt"
    source.parent.mkdir(parents=True)
    raw = b"\xef\xbb\xbflaw_b = { group = lawgroup_a }\r\nlaw_a = {}\r\n"
    source.write_bytes(raw)
    keys, sources = observation.law_snapshot(tmp_path)
    assert keys == ("law_a", "law_b")
    assert sources == {"common/laws/a.txt": hashlib.sha256(raw).hexdigest()}


@pytest.mark.parametrize("content", ["law_a = {", "law_a = yes", "law_a={} law_a={}", "bad.key={}"])
def test_无效法律定义不静默遗漏(tmp_path: Path, content: str) -> None:
    source = tmp_path / "common/laws/a.txt"
    source.parent.mkdir(parents=True)
    source.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        observation.law_snapshot(tmp_path)


@pytest.mark.parametrize("flags", list(product((False, True), repeat=4)))
def test_生成分支独立读取存在可用现行与立法状态(flags) -> None:
    files = observation.build(("law_a",), tags=("RUS",))
    source = files["common/scripted_effects/zz_sitai_law_observation.txt"]
    parsed = parse_text(source)
    assert not parsed.errors
    effect = parsed.root.first("sitai_law_observe_read_RUS")
    assert effect is not None
    assert isinstance(effect.value, Block)
    messages = []

    def execute(block: Block) -> None:
        previous = None
        for item in block.assignments():
            if item.key == "debug_log":
                assert isinstance(item.value, Scalar)
                messages.append(item.value.unquoted)
            elif item.key == "if":
                assert isinstance(item.value, Block)
                limit = item.value.first("limit")
                assert limit is not None
                assert isinstance(limit.value, Block)
                (condition,) = list(limit.value.assignments())
                if condition.key == "any_law":
                    assert isinstance(condition.value, Block)
                    type_condition = condition.value.first("this.type")
                    assert type_condition is not None
                    assert isinstance(type_condition.value, Scalar)
                    assert type_condition.value.text == "law_type:law_a"
                    previous = flags[1 if condition.value.first("law_is_available") else 0]
                else:
                    assert isinstance(condition.value, Scalar)
                    assert condition.value.text == "law_type:law_a"
                    previous = flags[{"has_law": 2, "is_enacting_law": 3}[condition.key]]
                if previous:
                    execute(item.value)
            elif item.key == "else":
                assert previous is not None
                assert isinstance(item.value, Block)
                if not previous:
                    execute(item.value)
                previous = None
            else:
                assert item.key == "limit", f"观测出现副作用：{item.key}"

    execute(effect.value)
    assert messages == ["SITAI LAW;RUS;LAW;law_a;" + ";".join(str(int(x)) for x in flags)]


def frame(reason="MONTHLY", target=None, second="law_b;0;0;0;0") -> str:
    return "\n".join(
        [
            f"[debug] SITAI LAW;RUS;BEGIN;{reason}",
            *([f"[debug] SITAI LAW;RUS;TARGET;{target}"] if target is not None else []),
            "[debug] SITAI LAW;RUS;LAW;law_a;1;0;1;0",
            f"[debug] SITAI LAW;RUS;LAW;{second}",
            f"[debug] SITAI LAW;RUS;END;{reason}",
        ]
    )


@pytest.mark.parametrize("reason", sorted(observation.REASONS))
def test_激活与立法hook的根作用域和目标来源分别保持(reason: str) -> None:
    files = observation.build(("law_a",), tags=("RUS",))
    parsed = parse_text(files["common/on_actions/zz_sitai_law_observation.txt"])
    assert not parsed.errors
    action = parsed.root.first("sitai_law_observe_" + reason.lower())
    assert action is not None
    assert isinstance(action.value, Block)
    effect = action.value.first("effect")
    assert effect is not None
    assert isinstance(effect.value, Block)
    branch = effect.value.first("if")
    assert branch is not None
    assert isinstance(branch.value, Block)
    limit = branch.value.first("limit")
    assert limit is not None
    assert isinstance(limit.value, Block)
    if reason == "ACTIVATED":
        owner = limit.value.first("owner")
        assert owner is not None
        assert isinstance(owner.value, Block)
        assert owner.value.first("c:RUS") is not None
        reading = branch.value.first("owner")
        assert reading is not None
        assert isinstance(reading.value, Block)
        assert reading.value.first("sitai_law_observe_read_RUS") is not None
        target = branch.value.first("if")
        assert target is not None
        assert isinstance(target.value, Block)
        target_limit = target.value.first("limit")
        assert target_limit is not None
        assert isinstance(target_limit.value, Block)
        assert target_limit.value.first("this.type") is not None
        assert branch.value.first("sitai_law_observe_read_RUS") is None
    else:
        assert limit.value.first("c:RUS") is not None
        assert branch.value.first("sitai_law_observe_read_RUS") is not None
        assert branch.value.first("owner") is None
        if reason == "MONTHLY":
            assert branch.value.first("if") is None
        else:
            existence = branch.value.first("if")
            assert existence is not None
            assert isinstance(existence.value, Block)
            target = existence.value.first("if")
            assert target is not None
            assert isinstance(target.value, Block)
            target_limit = target.value.first("limit")
            assert target_limit is not None
            assert isinstance(target_limit.value, Block)
            assert target_limit.value.first("currently_enacting_law.type") is not None


def test_现行法可用性为假及缺对象分别保留而不推导完整资格() -> None:
    result = observation.analyze(frame(), ("law_a", "law_b"), tags=("RUS",))
    assert result["complete"]
    assert not result["errors"]
    assert result["frames"][0]["laws"] == {
        "law_a": {
            "object_present": True,
            "availability_trigger": False,
            "available": False,
            "active": True,
            "enacting": False,
        },
        "law_b": {
            "object_present": False,
            "availability_trigger": False,
            "available": None,
            "active": False,
            "enacting": False,
        },
    }
    assert not result["getter_runtime_verified"]
    assert not result["ai_candidate_denominator_complete"]
    assert result["behavior_quality"] == "not_evaluated"


@pytest.mark.parametrize("second", ["", frame().replace(";RUS;", ";FRA;")])
def test_全部显式观察国都必须取得有效帧(second: str) -> None:
    result = observation.analyze(frame() + "\n" + second, ("law_a", "law_b"), tags=("RUS", "FRA"))
    assert result["complete"] is bool(second)
    if not second:
        assert any("FRA" in error for error in result["errors"])
        assert len(result["frames"]) == 1


@pytest.mark.parametrize("reason", ["START", "PASS", "FAIL", "ENDED", "ACTIVATED"])
def test_不同原因的目标保持独立而不推断自主立法(reason) -> None:
    result = observation.analyze(frame(reason, "law_a"), ("law_a", "law_b"), tags=("RUS",))
    assert result["complete"]
    assert result["frames"][0]["target"] == "law_a"
    assert result["frames"][0]["reason"] == reason
    assert result["behavior_quality"] == "not_evaluated"


@pytest.mark.parametrize(
    "text",
    [
        "",
        frame().rsplit("\n", 1)[0],
        frame().replace(";law_b;", ";law_a;"),
        frame().replace(";law_b;", ";unexpected;"),
        frame("START"),
        frame("START", "unknown"),
        frame("START", "none"),
        frame("MONTHLY", "law_a"),
        frame("bad"),
        frame().replace(";law_b;0;0;0;0", ";law_b;0;1;0;0"),
        frame()
        .replace(";law_a;1;0;1;0", ";law_a;1;0;1;1")
        .replace(";law_b;0;0;0;0", ";law_b;1;1;0;1"),
        frame().replace(";law_a;1;0;1;0", ";law_a;1;0;true;0"),
        frame().replace(";END;MONTHLY", ";END;START"),
        frame().replace(";RUS;LAW", ";FRA;LAW"),
        frame().replace(";LAW;law_b;", ";bad;law_b;"),
    ],
)
def test_不完整冲突或无效帧不能获得完整结果(text) -> None:
    result = observation.analyze(text, ("law_a", "law_b"), tags=("RUS",))
    assert not result["complete"]


def test_坏帧不得污染下一完整帧且流式位置保留() -> None:
    text = frame().replace(";law_b;", ";law_a;") + "\n" + frame("ACTIVATED", "law_b")
    result = observation.analyze_lines(iter(text.splitlines()), ("law_a", "law_b"), tags=("RUS",))
    assert not result["complete"]
    assert len(result["frames"]) == 1
    assert result["frames"][0]["start_line"] == 5
    assert result["frames"][0]["end_line"] == 9
    assert result["frames"][0]["log_prefix"] == "[debug] "


@pytest.mark.parametrize(
    ("keys", "tags"),
    [
        ((), ("RUS",)),
        (("law_a", "law_a"), ("RUS",)),
        (("law_a;evil",), ("RUS",)),
        (("law_a",), ()),
        (("law_a",), ("bad",)),
    ],
)
def test_观测身份在生成与解析前共同拒绝(keys, tags) -> None:
    with pytest.raises(ValueError):
        observation.build(keys, tags=tags)
    with pytest.raises(ValueError):
        observation.analyze("", keys, tags=tags)
