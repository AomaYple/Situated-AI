"""F0 新增三模块的参考模型、生成契约和完整候选交付测试。"""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace

import pytest

from pdx import (
    decision_diplomacy,
    decision_economy,
    decision_subjects,
    decisions,
    distribution,
)
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


def test_共享支持字段仲裁只写一次且安全取最高理由():
    result = decisions.merge_diplomatic_play_support(
        market=-2.5,
        security={"commitment": 25, "neighbor": 15},
    )
    assert result.value == 22.5
    assert result.reasons == ("market", "commitment")
    assert decisions.merge_diplomatic_play_support(
        market=3, security={"commitment": 25, "neighbor": 15}, has_sides=False
    ) == decisions.SupportArbitration(0, ())
    assert decisions.merge_diplomatic_play_support(
        market=3, security={"commitment": 25, "neighbor": 15}, is_ai=False
    ) == decisions.SupportArbitration(0, ())


def test_未知安全输入不干预且玩家边界静态检查():
    assert decisions.merge_diplomatic_play_support(
        market=3, security={"commitment": None}
    ) == decisions.SupportArbitration(0, ())
    assert (
        decisions.player_boundary_issues(
            "\t\t# SITAI BEGIN x\n\t\tif = { limit = { is_ai = yes } }\n\t\t# SITAI END x\n"
        )
        == []
    )
    assert decisions.player_boundary_issues(
        "\t\t# SITAI BEGIN x\n\t\tif = { limit = { foo = yes } }\n\t\t# SITAI END x\n"
    ) == ["x 新增字段块缺少 is_ai = yes 玩家边界"]


def test_七模块机器可读生命周期契约():
    policy, _extensions, files = distribution.package_inputs("full")
    metadata = json.loads(files[".metadata/metadata.json"])
    contract = metadata["module_contract"]
    assert set(contract) == {
        "fiscal",
        "reform",
        "market",
        "security",
        "economy",
        "diplomacy",
        "subjects",
    }
    assert contract["fiscal"]["stateful"] is True
    assert contract["fiscal"]["direct_read"] is False
    assert contract["fiscal"]["ttl_or_none"] == policy.ttl_days
    assert contract["fiscal"]["hooks"] == [
        "on_monthly_pulse_country",
        "on_country_default",
        "on_country_no_longer_default",
    ]
    for name, item in contract.items():
        assert item["clear_on_disable"] is True
        assert item["save_compatibility"] == policy.package.save_compatibility
        if name != "fiscal":
            assert item["stateful"] is False
            assert item["direct_read"] is True
            assert item["ttl_or_none"] is None
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
    localization = metadata["localization"]
    assert localization["production_fallback_languages"] == []
    assert localization["explanation_fallback_languages"] == []
    assert localization["fallback_languages"] == []
    assert set(localization["explanation_review_languages"]) == set(decisions.LANGUAGES) - {
        "english",
        "simp_chinese",
    }
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


@pytest.mark.parametrize("variant", ["control", "disabled"])
def test_控制和全关显式关闭新增模块开关(variant):
    _, extensions, files = distribution.package_inputs(variant)
    assert not extensions.economy_enabled
    assert not extensions.diplomacy_enabled
    assert not extensions.subjects_enabled
    metadata = json.loads(files[".metadata/metadata.json"])
    assert all(
        module not in metadata["enabled_modules"] for module in ("economy", "diplomacy", "subjects")
    )


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
