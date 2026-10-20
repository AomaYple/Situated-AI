"""研究分母与真实动作观测的离线契约，不启动游戏。"""

import hashlib
from itertools import product
from pathlib import Path

import pytest

from pdx import research_observation as observation
from pdx.model import Block, Scalar
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
    assert "is_researching_technology = pan-nationalism" in effect
    assert "TECH;pan-nationalism;0;0;0" in effect
    assert ".metadata/metadata.json" not in files  # 只能显式附到本局标准候选。


@pytest.mark.parametrize(("legal", "owned", "active"), list(product((False, True), repeat=3)))
def test_实际生成分支独立输出三种原生状态(legal: bool, owned: bool, active: bool) -> None:
    """错误嵌套或把研究状态当资格时，完整真值表必须抓出错误日志。"""
    files = observation.build(("a",), tags=("RUS",))
    parsed = parse_text(files["common/scripted_effects/zz_sitai_research_observation.txt"])
    assert not parsed.errors
    effect = parsed.root.first("sitai_research_observe_read_RUS")
    assert effect is not None
    effect_value = effect.value
    assert isinstance(effect_value, Block)
    state = {
        "can_research": legal,
        "has_technology_researched": owned,
        "is_researching_technology": active,
    }
    messages: list[str] = []

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
                conditions = list(limit.value.assignments())
                assert len(conditions) == 1
                condition = conditions[0]
                assert condition.key in state
                assert isinstance(condition.value, Scalar)
                assert condition.value.text == "a"
                previous = state[condition.key]
                if previous:
                    execute(item.value)
            elif item.key == "else":
                assert previous is not None
                assert isinstance(item.value, Block)
                if not previous:
                    execute(item.value)
                previous = None
            else:
                assert item.key == "limit", f"观测出现未声明副作用：{item.key}"

    execute(effect_value)
    assert messages == [f"SITAI RESEARCH;RUS;TECH;a;{int(legal)};{int(owned)};{int(active)}"]


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


@pytest.mark.parametrize("second", ["", frame().replace(";RUS;", ";FRA;")])
def test_全部显式观察国都必须取得有效帧(second: str) -> None:
    result = observation.analyze(frame() + "\n" + second, ("a", "b"), tags=("RUS", "FRA"))
    assert result["complete"] is bool(second)
    if not second:
        errors, frames = result["errors"], result["frames"]
        assert isinstance(errors, list)
        assert isinstance(frames, list)
        assert any("FRA" in error for error in errors)
        assert len(frames) == 1


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


def test_显式研究目标使用独立hook名称且默认脚本保持不变() -> None:
    plain = observation.build(("a", "b"), tags=("RUS",))
    instrumented = observation.build(("a", "b"), tags=("RUS",), with_targets=True)
    path = "common/on_actions/zz_sitai_research_observation.txt"
    assert ";TARGET;" not in plain[path]
    assert instrumented[path].count("SCOPE.sTechnology('technology').GetNameNoFormatting") == 3
    assert instrumented[path].count("SITAI RESEARCH;RUS;TARGET;") == 3
    assert "IsResearching" not in instrumented[path]
    assert not parse_text(instrumented[path]).errors


def target_frame(label: str = "甲科技", reason: str = "START") -> str:
    return frame(reason).replace(
        f"[debug] SITAI RESEARCH;RUS;BEGIN;{reason}",
        f"[debug] SITAI RESEARCH;RUS;BEGIN;{reason}\n[debug] SITAI RESEARCH;RUS;TARGET;{label}",
    )


def test_独立目标映射并核对开始时原生主动研究() -> None:
    result = observation.analyze_lines(
        iter(target_frame().splitlines()),
        ("a", "b"),
        tags=("RUS",),
        hook_labels={"a": "甲科技", "b": "乙科技"},
    )
    assert result["complete"]
    frames = result["frames"]
    assert isinstance(frames, list)
    observed = frames[0]
    assert observed["target"] == "a"
    assert observed["target_label"] == "甲科技"
    assert observed["start_line"] == 1
    assert observed["end_line"] == 5
    assert not result["getter_runtime_verified"]
    assert result["behavior_quality"] == "not_evaluated"


@pytest.mark.parametrize(
    "text",
    [
        target_frame("未知名称"),
        target_frame("乙科技"),
        target_frame().replace(
            ";TARGET;甲科技", ";TARGET;甲科技\nSITAI RESEARCH;RUS;TARGET;甲科技"
        ),
        frame(),
        target_frame().replace(";yes", ";unknown"),
        target_frame(reason="MONTHLY"),
    ],
)
def test_目标未知重复缺失或START不匹配时整帧失效(text: str) -> None:
    result = observation.analyze_lines(
        text.splitlines(),
        ("a", "b"),
        tags=("RUS",),
        hook_labels={"a": "甲科技", "b": "乙科技"},
    )
    assert not result["complete"]
    assert result["errors"]
    assert result["frames"] == []


@pytest.mark.parametrize(
    "labels", [{}, {"a": "甲科技"}, {"a": "同名", "b": "同名"}, {"a": "", "b": "乙科技"}]
)
def test_研究标签合同缺项或歧义不能解析(labels) -> None:
    with pytest.raises(ValueError):
        observation.analyze_lines([], ("a", "b"), tags=("RUS",), hook_labels=labels)


def test_名称从该语言全部文件读取并冻结原件与源行号(tmp_path: Path) -> None:
    root = tmp_path / "localization/simp_chinese"
    root.mkdir(parents=True)
    raw = '\ufeffl_simp_chinese:\r\n a:0 "甲科技"\r\n'.encode()
    (root / "inventions.yml").write_bytes(raw)
    (root / "goods.yml").write_text('l_simp_chinese:\n b:0 "乙科技"\n', encoding="utf-8")
    labels, sources, origins = observation.label_snapshot(
        tmp_path, ("a", "b"), language="l_simp_chinese"
    )
    assert labels == {"a": "甲科技", "b": "乙科技"}
    assert origins["b"] == {"source": "localization/simp_chinese/goods.yml", "line": 2}
    assert sources["localization/simp_chinese/inventions.yml"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "content",
    [
        'l_simp_chinese:\n a:0 "甲"\n',
        'l_english:\n a:0 "甲"\n b:0 "乙"\n',
        'l_simp_chinese:\n a:0 "甲"\n b:0 "甲"\n',
        'l_simp_chinese:\n a:0 "甲"\n a:0 "甲"\n b:0 "乙"\n',
        'l_simp_chinese:\n a:0 "$other$"\n b:0 "乙"\n',
    ],
)
def test_名称缺失重复异语言或未求值表达式拒绝(tmp_path: Path, content: str) -> None:
    root = tmp_path / "localization/simp_chinese"
    root.mkdir(parents=True)
    (root / "inventions.yml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        observation.label_snapshot(tmp_path, ("a", "b"), language="l_simp_chinese")


def test_名称允许递归静态别名并登记完整来源(tmp_path: Path) -> None:
    root = tmp_path / "localization/simp_chinese"
    root.mkdir(parents=True)
    (root / "inventions.yml").write_text(
        'l_simp_chinese:\n a:0 "$ship_name$"\n b:0 "乙科技"\n', encoding="utf-8"
    )
    (root / "ships.yml").write_text(
        'l_simp_chinese:\n ship_name:0 "$ship_kind$"\n ship_kind:0 "战舰"\n', encoding="utf-8"
    )
    labels, sources, origins = observation.label_snapshot(
        tmp_path, ("a", "b"), language="l_simp_chinese"
    )
    assert labels == {"a": "战舰", "b": "乙科技"}
    assert len(sources) == 2
    assert origins["a"]["line"] == 2


@pytest.mark.parametrize(
    "tail",
    [
        'ship_name:0 "$ship_name$"',
        'ship_name:0 "$ship_kind$"\n ship_kind:0 "$ship_name$"',
        'ship_name:0 "[Country.GetName]"',
        'ship_name:0 "战舰"\n ship_name:0 "另一个"',
    ],
)
def test_名称别名循环动态getter或歧义拒绝(tmp_path: Path, tail: str) -> None:
    root = tmp_path / "localization/simp_chinese"
    root.mkdir(parents=True)
    (root / "names.yml").write_text(
        f'l_simp_chinese:\n a:0 "$ship_name$"\n b:0 "乙科技"\n {tail}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        observation.label_snapshot(tmp_path, ("a", "b"), language="l_simp_chinese")
