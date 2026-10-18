"""A5 候选的脚本/包契约；有限回放不代替国家上下文、刷新或引擎验收。"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import zipfile
from dataclasses import replace

import pytest

from pdx import decisions, distribution
from pdx import explanation_probe as probe
from pdx.model import Block, Scalar
from pdx.modgen import parse_loc_text
from pdx.parser import parse_text

pytestmark = pytest.mark.unit

PANEL_SOURCE = """# 可离线复核的最小原生契约夹具，不复制游戏原文。
types country_panel_types {
    type country_panel = default_block_window_two_lines {
        name = "country_panel"
        datacontext = "[CountryPanel.GetCountry]"
        widget = { name = "nested } # not a boundary" }
    }
}
"""


@pytest.fixture(autouse=True)
def panel_source(tmp_path, monkeypatch):
    source = tmp_path / probe.PANEL
    source.parent.mkdir(parents=True)
    source.write_text(PANEL_SOURCE, encoding="utf-8", newline="\n")
    monkeypatch.setattr(probe.config, "GAME", tmp_path)
    monkeypatch.setattr(probe.config, "game_version", lambda: {"caligula_branch": "release/1.14.5"})
    return source


def _block(parent, key):
    node = parent.first(key)
    assert node is not None
    assert node.op == "="
    assert isinstance(node.value, Block)
    return node.value


def _messages(script, conditions):
    """仅解释只读效果子集。条件是测试输入，不冒充引擎计算或观测。"""
    tree = parse_text(script)
    assert not tree.errors
    body = _block(_block(tree.root, probe.PREFIX), "effect")
    messages = []

    def execute(block):
        selected = False
        for node in block.assignments():
            assert node.op == "="
            if node.key in {"if", "else"}:
                assert isinstance(node.value, Block)
                if node.key == "if":
                    selected = False
                    limit = list(_block(node.value, "limit").assignments())
                    assert len(limit) == 1
                    item = limit[0]
                    assert item.op == "="
                    assert isinstance(item.value, Scalar)
                    expected = decisions.RISK_VAR if item.key == "has_variable" else "yes"
                    assert item.value.unquoted == expected
                    matches = conditions[item.key]
                else:
                    matches = True
                if not selected and matches:
                    selected = True
                    execute(node.value)
            elif node.key == "custom_tooltip":
                assert isinstance(node.value, Scalar)
                messages.append(node.value.unquoted.removeprefix(probe.PREFIX + "_"))
            else:
                assert node.key == "limit", f"非只读效果：{node.key}"

    execute(body)
    return messages


def test_实际脚本区分全部状态组合且风险不等于ACTIVE(subtests):
    policy = decisions.load()
    script = probe.build(policy, decisions.Extensions())[probe.SGUI]
    for ai, risk, hold, exposure, default in itertools.product((False, True), repeat=5):
        with subtests.test(ai=ai, risk=risk, hold=hold, exposure=exposure, default=default):
            conditions = {
                "is_ai": ai,
                "has_variable": risk,
                "sitai_fiscal_hold": hold,
                "sitai_external_exposure": exposure,
                decisions.ACTIVE_TRIGGER: ai and risk and hold and exposure,
                "in_default": default,
            }
            expected = ["config"]
            if ai:
                expected += [
                    "ai",
                    "risk" if risk else "no_risk",
                    "hold" if hold else "no_hold",
                    "exposure" if exposure else "no_exposure",
                    "active" if risk and hold and exposure else "inactive",
                    "default" if default else "not_default",
                ]
            else:
                expected += ["human"]
            assert _messages(script, conditions) == [*expected, "rules", "boundary"]


def test_关闭分支不访问缺失的财政触发器或国家条件():
    policy = replace(decisions.load(), enabled=False)
    script = probe.build(policy, decisions.Extensions())[probe.SGUI]
    assert _messages(script, {}) == ["config", "off", "rules", "boundary"]
    assert decisions.ACTIVE_TRIGGER not in script
    assert "sitai_fiscal_hold" not in script
    assert "has_variable" not in script


def test_非AI分支不求值风险状态():
    files = probe.build(decisions.load(), decisions.Extensions())
    assert _messages(files[probe.SGUI], {"is_ai": False}) == [
        "config",
        "human",
        "rules",
        "boundary",
    ]


@pytest.mark.parametrize("enabled", [False, True])
def test_只读组件使用闭合允许子集并且无世界扫描或玩法写入(enabled):
    files = probe.build(replace(decisions.load(), enabled=enabled), decisions.Extensions())
    allowed = {
        probe.PREFIX,
        "scope",
        "effect",
        "if",
        "else",
        "limit",
        "custom_tooltip",
        "is_ai",
        "has_variable",
        "sitai_fiscal_hold",
        "sitai_external_exposure",
        decisions.ACTIVE_TRIGGER,
        "in_default",
    }

    def check(block):
        assert len(list(block.assignments())) == len(block.items)
        for node in block.assignments():
            assert node.key in allowed
            assert node.op == "="
            if isinstance(node.value, Block):
                check(node.value)

    tree = parse_text(files[probe.SGUI])
    assert not tree.errors
    check(tree.root)
    assert len(files) == 2 + len(probe.DEFAULT_LANGUAGES)
    assert all(probe.PREFIX in name for name in files)
    assert not any(name.startswith("common/on_actions/") for name in files)


def test_控件仅在原生国家上下文内实例化():
    files = probe.build(decisions.load(), decisions.Extensions())
    assert not any(name.startswith("gui/scripted_widgets/") for name in files)
    # 通用脚本解析器不是 GUI 类型解析器；用明确的词法层级核对外层/内层。
    from pdx.lexer import tokenize

    tokens = list(tokenize(files[probe.GUI]))
    assert [token.value for token in tokens[:8]] == [
        "types",
        f"{probe.PREFIX}_types",
        "{",
        "type",
        probe.PREFIX,
        "=",
        "widget",
        "{",
    ]
    depth = 0
    contexts = []
    for token in tokens:
        if token.value == "{":
            depth += 1
        elif token.value == "}":
            depth -= 1
        elif token.value.startswith('"['):
            contexts.append((depth, token.value))
    assert depth == 0
    assert contexts == [
        (2, '"[Country.IsValid]"'),
        (4, '"[Country.GetNameNoFormatting]"'),
        (
            4,
            f"\"[GetScriptedGui('{probe.PREFIX}').ExecuteTooltip(GuiScope.SetRoot(Country.MakeScope).End)]\"",
        ),
    ]
    assert ".Execute(" not in files[probe.GUI]
    assert "GetPlayer" not in files[probe.GUI]
    patched = probe._extend_country_panel(PANEL_SOURCE)
    addition = f"\n\t\t{probe.PREFIX} = {{}}\n\t"
    assert patched.replace(addition, "", 1) == PANEL_SOURCE
    assert patched.index(addition) > patched.index("nested }")
    assert patched.index(addition) < patched.rindex("}")


@pytest.mark.parametrize(
    "source",
    [
        "",
        PANEL_SOURCE * 2,
        PANEL_SOURCE.replace("[CountryPanel.GetCountry]", "[GetPlayer]"),
        PANEL_SOURCE.replace("datacontext =", "context ="),
        PANEL_SOURCE.replace("default_block_window_two_lines", "new_base"),
        PANEL_SOURCE.replace("\n", "\r\n"),
        "\ufeff" + PANEL_SOURCE,
        PANEL_SOURCE[: PANEL_SOURCE.index("        widget")],
        PANEL_SOURCE.replace('name = "country_panel"', f'name = "{probe.PREFIX}"'),
        PANEL_SOURCE + "}",
        PANEL_SOURCE[:-2],
        '"unterminated',
        PANEL_SOURCE + '"unterminated\\"',
        PANEL_SOURCE + "type country_panel = different_base {}",
        PANEL_SOURCE.replace("types country_panel_types {", "types outer { widget = {") + "}\n",
        PANEL_SOURCE + '\nwidget = { text = "unterminated',
    ],
)
def test_底本漂移歧义和重复注入均拒绝(source):
    with pytest.raises(ValueError, match="国家面板底本"):
        probe._extend_country_panel(source)


def test_底本合法引号转义和注释不改变精确插入边界():
    source = PANEL_SOURCE.replace(
        'name = "country_panel"',
        'name = "country_panel"\n        text = "escaped \\" }\u2028" # ignored {\n',
    )
    patched = probe._extend_country_panel(source)
    addition = f"\n\t\t{probe.PREFIX} = {{}}\n\t"
    assert patched.count(addition) == 1
    assert patched.replace(addition, "", 1) == source
    # Unicode 行分隔符是字符串内容；词法器只以 LF 推进行号。
    closing = source.rindex("    }\n}") + 4
    assert patched[closing:].startswith(addition + "}")


def test_游戏版本不匹配和缺失底本不破坏旧包(tmp_path, monkeypatch, panel_source):
    target = tmp_path / "previous.zip"
    target.write_bytes(b"previous")
    monkeypatch.setattr(probe.config, "game_version", lambda: {"caligula_branch": "release/1.15"})
    with pytest.raises(ValueError, match="版本一致"):
        probe.package(target)
    monkeypatch.setattr(probe.config, "game_version", lambda: {"caligula_branch": "release/1.14.5"})
    panel_source.unlink()
    with pytest.raises(FileNotFoundError):
        probe.package(target)
    assert target.read_bytes() == b"previous"


def test_生成文案使用替代实际参数及一致键与占位符():
    policy = replace(
        decisions.load(),
        entry_weeks=17,
        exit_weeks=43,
        ttl_days=73,
        neutrality=-7.5,
        aggression=0.25,
    )
    files = probe.build(policy, decisions.Extensions(reform_enabled=True, market_enabled=True))
    localization = {
        language: parse_loc_text(files[f"localization/{language}/{probe.PREFIX}_l_{language}.yml"])
        for language in decisions.LANGUAGES
    }
    tables = list(localization.values())
    assert set(localization["simp_chinese"]) == set(localization["english"])
    for table in tables:
        for key, text in table.items():
            assert re.findall(r"\[[^\]]*\]|\$[^$]*\$", text) == []
            assert key.startswith(probe.PREFIX + "_")
        rules = table[probe.PREFIX + "_rules"]
        assert all(str(value) in rules for value in (17, 43, 73))
        active = table[probe.PREFIX + "_active"]
        assert "-7.5" in active
        assert "+0.25" in active
    script = files[probe.SGUI]
    keys = re.findall(r"custom_tooltip = (\w+)", script)
    assert set(keys) <= localization["simp_chinese"].keys()
    assert "改革启用；市场启用" in localization["simp_chinese"][probe.PREFIX + "_config"]
    assert "reform enabled; market enabled" in localization["english"][probe.PREFIX + "_config"]
    assert "未知保持未知" in localization["simp_chinese"][probe.PREFIX + "_boundary"]


@pytest.mark.parametrize("variant", ["current", "control", "disabled"])
def test_实验包与实际生产变体配套且生产交付不含探针(tmp_path, variant):
    production = distribution.package(tmp_path / "production.zip", variant=variant)
    experiment = probe.package(tmp_path / "probe.zip", variant=variant)
    with zipfile.ZipFile(production) as base, zipfile.ZipFile(experiment) as candidate:
        assert not any(probe.PREFIX in name for name in base.namelist())
        for name in base.namelist():
            if name not in {
                "README.md",
                ".metadata/metadata.json",
                "DISTRIBUTION-MANIFEST.json",
            }:
                assert candidate.read(name) == base.read(name)
        metadata = json.loads(candidate.read(".metadata/metadata.json"))
        facts = metadata["game_custom_data"]["explanation_probe"]
        assert metadata["id"] == "sitai.explanation-probe"
        assert metadata["status"] == "experimental"
        assert facts["engine_verified"] is False
        assert facts["quality_improvement_proven"] is False
        assert facts["variant"] == variant
        assert metadata["game_custom_data"]["multiplayer_synchronized"] is False
        assert facts["fiscal"]["enabled"] == (variant != "disabled")
        assert facts["fiscal"]["neutrality"] == (0 if variant == "control" else 25)
        assert facts["extensions"]["market_enabled"] is False
        panel = facts["country_panel"]
        assert panel["source_sha256"] == hashlib.sha256(PANEL_SOURCE.encode()).hexdigest()
        assert panel["generated_sha256"] == hashlib.sha256(candidate.read(probe.PANEL)).hexdigest()
        assert panel["compatibility"] == "overrides_native_country_panel"
        assert probe.PREFIX.encode() in candidate.read(probe.PANEL)
        assert (
            facts["generator_sha256"]
            == hashlib.sha256(probe.Path(probe.__file__).read_bytes()).hexdigest()
        )
        manifest = json.loads(candidate.read("DISTRIBUTION-MANIFEST.json"))
        generation = manifest["generation"]
        assert generation == {
            **distribution.generation_contract(
                variant=variant,
                with_explanation_probe=True,
            ),
            "purpose": "a5-explanation-instrument",
        }
        for name, digest in manifest["files"].items():
            payload = candidate.read(name)
            assert hashlib.sha256(payload).hexdigest() == digest
            assert b"\r" not in payload
            assert payload.startswith(b"\xef\xbb\xbf") == name.endswith((".txt", ".yml"))
        sgui = candidate.read(probe.SGUI).decode("utf-8-sig")
        assert ("sitai_fiscal_external_risk" in sgui) == (variant != "disabled")
        localization = {
            language: parse_loc_text(
                candidate.read(f"localization/{language}/{probe.PREFIX}_l_{language}.yml").decode(
                    "utf-8-sig"
                )
            )
            for language in decisions.LANGUAGES
        }
        assert set(localization) == set(decisions.LANGUAGES)
        english = localization["english"]
        assert ("neutrality +0," if variant == "control" else "neutrality +25,") in english[
            probe.PREFIX + "_active"
        ]
        assert "mount this ZIP alone" in candidate.read("README.md").decode("utf-8")
    previous = experiment.read_bytes()
    probe.package(experiment, variant=variant)
    assert experiment.read_bytes() == previous


def test_默认CLI全关且错误不破坏旧包(tmp_path, capsys, monkeypatch):
    target = tmp_path / "probe.zip"
    assert probe.main(["--output", str(target)]) == 0
    assert str(target) in capsys.readouterr().out
    with zipfile.ZipFile(target) as archive:
        assert (
            json.loads(archive.read("DISTRIBUTION-MANIFEST.json"))["generation"]["variant"]
            == "disabled"
        )
    previous = target.read_bytes()
    with pytest.raises(SystemExit, match="2"):
        probe.main(["--output", str(target), "--variant", "invalid"])
    with pytest.raises(ValueError, match="变体"):
        probe.package(target, variant="invalid")

    def fail(*args, **kwargs):
        raise ValueError("候选生成失败")

    monkeypatch.setattr(probe, "build", fail)
    with pytest.raises(SystemExit, match="1"):
        probe.main(["--output", str(target)])
    assert "候选生成失败" in capsys.readouterr().err
    assert target.read_bytes() == previous


def test_生成组件确定性与仓库字节规范():
    policy, extra = decisions.load(), decisions.load_extensions()
    first = probe.build(policy, extra)
    assert first == probe.build(policy, extra)
    for text in first.values():
        raw = text.encode("utf-8")
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in raw
        assert raw.endswith(b"\n")


def test_三新增模块解释键在全开时明确保持上下文未知():
    policy = decisions.load()
    extra = replace(
        decisions.load_extensions(),
        economy_enabled=True,
        diplomacy_enabled=True,
        subjects_enabled=True,
    )
    files = probe.build(policy, extra)
    script = files[probe.SGUI]
    for key in ("economy_rules", "diplomacy_rules", "subjects_rules"):
        assert f"custom_tooltip = {probe.PREFIX}_{key}" in script
    for language in decisions.LANGUAGES:
        table = parse_loc_text(files[f"localization/{language}/{probe.PREFIX}_l_{language}.yml"])
        for key in ("economy_rules", "diplomacy_rules", "subjects_rules"):
            value = table[f"{probe.PREFIX}_{key}"]
            assert value
            assert value
    assert probe.localization_fallback_languages() == []
    assert set(probe.localization_review_languages()) == set(decisions.LANGUAGES) - {
        "english",
        "simp_chinese",
    }


def test_源与受控产物不一致时拒绝实验包并保全旧文件(tmp_path, monkeypatch):
    target = tmp_path / "previous.zip"
    target.write_bytes(b"previous package")
    product = tmp_path / "product"
    decisions.write(product)
    strategy = product / "common/ai_strategies/00_default_strategy.txt"
    strategy.write_bytes(strategy.read_bytes() + b"\n# inconsistent\n")
    monkeypatch.setattr(decisions, "PRODUCT", product)
    with pytest.raises(ValueError, match="生成物不一致"):
        probe.package(target)
    assert target.read_bytes() == b"previous package"


def test_交付清单校验失败时保全已有ZIP(tmp_path, monkeypatch):
    target = tmp_path / "previous.zip"
    target.write_bytes(b"previous package")

    def fail(*args, **kwargs):
        raise ValueError("清单校验失败")

    monkeypatch.setattr(distribution, "validate_package", fail)
    with pytest.raises(ValueError, match="清单校验失败"):
        distribution.write_zip(
            {"common/example.txt": "example\n"},
            target,
            generation=distribution.generation_contract(
                variant="disabled",
                with_explanation_probe=False,
            ),
        )
    assert target.read_bytes() == b"previous package"
