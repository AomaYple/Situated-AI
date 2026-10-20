"""研究分母与真实动作观测的离线契约，不启动游戏。"""

import hashlib
from pathlib import Path

import pytest

from pdx import research_observation as observation
from pdx.parser import parse_text


def test_从所有科技文件收集完整键并保持稳定顺序(tmp_path: Path) -> None:
    root = tmp_path / "common/technology/technologies"
    root.mkdir(parents=True)
    (root / "b.txt").write_text("pan-nationalism = { era = era_3 }", encoding="utf-8")
    (root / "a.txt").write_text("sericulture = { can_research = no }", encoding="utf-8")
    assert observation.technology_keys(tmp_path) == ("pan-nationalism", "sericulture")


@pytest.mark.parametrize("content", ["broken = {", "a = yes", "a = {} a = {}", "bad.key = {}"])
def test_坏定义不能静默丢弃(tmp_path: Path, content: str) -> None:
    root = tmp_path / "common/technology/technologies"
    root.mkdir(parents=True)
    (root / "a.txt").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        observation.technology_keys(tmp_path)


def test_空定义集合拒绝(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="为空"):
        observation.technology_keys(tmp_path)


def test_科技键与来源指纹来自同一份读取字节(tmp_path: Path) -> None:
    relative = "common/technology/technologies/production.txt"
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    raw = b"\xef\xbb\xbfa = {}\r\n"
    source.write_bytes(raw)
    keys, hashes = observation.technology_snapshot(tmp_path)
    assert keys == ("a",)
    assert hashes == {relative: hashlib.sha256(raw).hexdigest()}


def test_生成明确国家作用域且只读无全世界扫描() -> None:
    files = observation.build(("a", "pan-nationalism"), tags=("RUS", "FRA"))
    assert files == observation.build(("pan-nationalism", "a"), tags=("FRA", "RUS"))
    for path, text in files.items():
        assert not parse_text(text, path).errors
        assert not text.startswith("\ufeff")
        assert "\r" not in text
        assert text.endswith("\n")
        assert not any(
            k in text
            for k in [
                "set_variable",
                "add_technology",
                "set_research",
                "every_country",
                "random_",
                "set_strategy",
            ]
        )
    on_actions = files["common/on_actions/zz_sitai_research_observation.txt"]
    assert all(
        name in on_actions
        for name in [
            "on_research_technology_started",
            "on_acquired_technology",
            "on_spreading_technology",
        ]
    )
    effect = files["common/scripted_effects/zz_sitai_research_observation.txt"]
    assert effect.count("can_research =") == 4  # 每国每科技一次，分支不重复枚举。
    assert "GetTechnology(" not in effect
    assert "IsResearching" not in effect
    assert "TECH;pan-nationalism;0;0;unknown" in effect
    assert ".metadata/metadata.json" not in files  # 只能显式附到本局标准候选。


@pytest.mark.parametrize(
    ("keys", "tags"),
    [
        ((), ("RUS",)),
        (("a", "a"), ("RUS",)),
        (("a;injection",), ("RUS",)),
        (("a",), ()),
        (("a",), ("RUS", "RUS")),
        (("a",), ("bad",)),
    ],
)
def test_生成解析共同拒绝无效身份(keys, tags) -> None:
    with pytest.raises(ValueError):
        observation.build(keys, tags=tags)
    with pytest.raises(ValueError):
        observation.analyze("", keys, tags=tags)


def frame(reason: str = "START") -> str:
    return "\n".join(
        [
            f"[debug] SITAI RESEARCH;RUS;BEGIN;{reason}",
            "[debug] SITAI RESEARCH;RUS;TECH;a;1;0;yes",
            "[debug] SITAI RESEARCH;RUS;TECH;b;0;1;no",
            f"[debug] SITAI RESEARCH;RUS;END;{reason}",
        ]
    )


@pytest.mark.parametrize("reason", sorted(observation.REASONS))
def test_完整帧保留原始原因和逐科技状态但不提升资格(reason: str) -> None:
    result = observation.analyze(frame(reason), ("a", "b"), tags=("RUS",))
    assert result["complete"]
    assert not result["errors"]
    assert result["frames"] == [
        {
            "tag": "RUS",
            "reason": reason,
            "start_line": 1,
            "end_line": 4,
            "log_prefix": "[debug] ",
            "technologies": {
                "a": {"can_research": True, "researched": False, "researching": True},
                "b": {"can_research": False, "researched": True, "researching": False},
            },
        }
    ]
    assert not result["getter_runtime_verified"]
    assert not result["ai_candidate_denominator_complete"]
    assert result["behavior_quality"] == "not_evaluated"


@pytest.mark.parametrize(
    "text",
    [
        "",
        frame().rsplit("\n", 1)[0],
        frame().replace(";b;0;1;no", ";a;0;1;no"),
        frame().replace(";b;0;1;no", ";unknown;0;1;no"),
        frame().replace(";yes", ";getter-error"),
        frame().replace(";END;START", ";END;SPREAD"),
        frame().replace(";RUS;TECH", ";FRA;TECH"),
        frame().replace(";BEGIN;START", ";BEGIN;invalid"),
        "SITAI RESEARCH;malformed",
    ],
)
def test_缺失重复越界和不可读不能获得完整结果(text: str) -> None:
    result = observation.analyze(text, ("a", "b"), tags=("RUS",))
    assert not result["complete"]
    assert not result["getter_runtime_verified"]


def test_连续hook和月度采样不把科技取得认作研究完成() -> None:
    result = observation.analyze(
        frame("ACQUIRED") + "\n" + frame("MONTHLY"), ("a", "b"), tags=("RUS",)
    )
    assert result["complete"]
    frames = result["frames"]
    assert isinstance(frames, list)
    assert len(frames) == 2
    assert "研究完成" in str(result["limits"])


def test_流式日志与字符串输入等价并保留原始定位() -> None:
    text = "unrelated\n" + frame() + "\n"
    result = observation.analyze_lines(
        iter(text.splitlines(keepends=True)), ("a", "b"), tags=("RUS",)
    )
    assert result == observation.analyze(text, ("a", "b"), tags=("RUS",))


def test_多个当前研究不作为有效帧验收() -> None:
    result = observation.analyze(
        frame().replace(";b;0;1;no", ";b;0;1;yes"), ("a", "b"), tags=("RUS",)
    )
    assert not result["complete"]
    assert result["errors"]
    assert result["frames"] == []


def test_未知当前研究保持缺失而不冒充未研究() -> None:
    result = observation.analyze(
        frame().replace(";yes", ";unknown").replace(";no", ";unknown"),
        ("a", "b"),
        tags=("RUS",),
    )
    assert result["complete"]
    assert not result["getter_runtime_verified"]
    assert not result["ai_candidate_denominator_complete"]
    frames = result["frames"]
    assert isinstance(frames, list)
    assert all(value["researching"] is None for value in frames[0]["technologies"].values())


def test_重复后补齐的坏帧不泄漏为有效帧() -> None:
    text = frame().replace(
        "[debug] SITAI RESEARCH;RUS;TECH;b;0;1;no",
        "[debug] SITAI RESEARCH;RUS;TECH;a;1;0;yes\n[debug] SITAI RESEARCH;RUS;TECH;b;0;1;no",
    )
    result = observation.analyze(text + "\n" + frame("MONTHLY"), ("a", "b"), tags=("RUS",))
    assert not result["complete"]
    frames = result["frames"]
    assert isinstance(frames, list)
    assert len(frames) == 1
    assert frames[0]["reason"] == "MONTHLY"


@pytest.mark.parametrize(
    "injected",
    ["SITAI RESEARCH;malformed", "SITAI RESEARCH;FRA;TECH;a;1;0;yes"],
)
def test_活动帧中格式或越界国家错误使整帧失效(injected: str) -> None:
    lines = frame().splitlines()
    lines.insert(-1, injected)
    result = observation.analyze(
        "\n".join(lines),
        ("a", "b"),
        tags=("RUS",),
    )
    assert result["errors"]
    assert result["frames"] == []
