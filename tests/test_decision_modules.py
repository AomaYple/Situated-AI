"""F0 新增三模块的参考模型、生成契约和完整候选交付测试。"""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace

import pytest

from pdx import decision_diplomacy, decision_economy, decision_subjects, distribution
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def test_经济模块未知输入保守且边界有限():
    policy = replace(decision_economy.load(), enabled=True)
    assert decision_economy.strategy_delta(taking_loans=None, bureaucracy=10, policy=policy) == 0
    assert (
        decision_economy.strategy_delta(taking_loans=True, bureaucracy=10, policy=policy) == -0.25
    )
    assert decision_economy.strategy_delta(taking_loans=False, bureaucracy=10, policy=policy) == 0.1
    with pytest.raises(ValueError):
        decision_economy.strategy_delta(taking_loans=True, bureaucracy=float("nan"), policy=policy)


def test_外交模块战争负担降低冒险且未知不猜测():
    policy = replace(decision_diplomacy.load(), enabled=True)
    assert (
        decision_diplomacy.recklessness_delta(in_war=True, taking_loans=False, policy=policy)
        == -0.5
    )
    assert (
        decision_diplomacy.recklessness_delta(in_war=False, taking_loans=False, policy=policy)
        == 0.15
    )
    assert (
        decision_diplomacy.recklessness_delta(in_war=None, taking_loans=False, policy=policy) == 0
    )


def test_宗属模块只在关系事实已知时计算():
    policy = replace(decision_subjects.load(), enabled=True)
    assert (
        decision_subjects.subject_value_delta(already_subject=True, protected=True, policy=policy)
        == 15
    )
    assert (
        decision_subjects.subject_value_delta(already_subject=False, protected=False, policy=policy)
        == 0
    )
    assert (
        decision_subjects.subject_value_delta(already_subject=True, protected=None, policy=policy)
        == 0
    )


def test_七模块完整候选生成所有脚本和全语言无回退():
    policy, extensions, files = distribution.package_inputs("full")
    metadata = json.loads(files[".metadata/metadata.json"])
    assert policy.package.status == "candidate"
    assert metadata["enabled_modules"] == [
        "fiscal",
        "reform",
        "market",
        "security",
        "economy",
        "diplomacy",
        "subjects",
    ]
    assert metadata["localization"]["fallback_languages"] == []
    assert extensions.economy_enabled
    assert extensions.diplomacy_enabled
    assert extensions.subjects_enabled
    for name, text in files.items():
        assert "\r" not in text
        assert not text.startswith("\ufeff")
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
    strategy = files["common/ai_strategies/00_default_strategy.txt"]
    for field in (
        "economic_vs_government_spending_balance",
        "recklessness",
        "subject_value",
        "become_subject_value",
    ):
        assert f"# SITAI BEGIN {field}" in strategy


def test_完整候选_zip在游戏边界添加BOM且确定性(tmp_path, monkeypatch):
    # 完整候选包含原生国家面板解释附件；用最小合法底本隔离测试对本机游戏安装的依赖。
    from pdx import config, explanation_probe

    panel = (
        "types country_panel_types {\n"
        " type country_panel = default_block_window_two_lines {\n"
        '  datacontext = "[CountryPanel.GetCountry]"\n'
        " }\n"
        "}\n"
    )
    panel_path = tmp_path / "game" / explanation_probe.PANEL
    panel_path.parent.mkdir(parents=True)
    panel_path.write_text(panel, encoding="utf-8", newline="\n")
    monkeypatch.setattr(config, "GAME", panel_path.parent.parent)
    monkeypatch.setattr(config, "game_version", lambda: {"caligula_branch": "release/1.14.5"})
    target = tmp_path / "full.zip"
    distribution.package(target, variant="full")
    first = target.read_bytes()
    distribution.package(target, variant="full")
    assert target.read_bytes() == first
    with zipfile.ZipFile(target) as archive:
        metadata = json.loads(archive.read(".metadata/metadata.json"))
        assert metadata["enabled_modules"][-3:] == ["economy", "diplomacy", "subjects"]
        assert archive.read("localization/english/sitai_decisions_l_english.yml").startswith(
            b"\xef\xbb\xbf"
        )
        assert archive.read(".metadata/metadata.json").startswith(b"{")
