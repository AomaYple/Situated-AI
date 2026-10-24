"""决策模块参考模型、生成合同与正式候选交付测试。"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pdx import (
    decision_diplomacy,
    decision_economy,
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


@pytest.mark.integration
def test_正式包启用模块与生命周期契约一致():
    policy, extensions, files = distribution.package_inputs(include_engineering_metadata=True)
    metadata = json.loads(files[".metadata/metadata.json"])
    contract = metadata["module_contract"]
    enabled_modules = set(metadata["enabled_modules"])
    assert enabled_modules == {
        "fiscal",
        "reform",
        "market",
        "security",
        "economy",
        "diplomacy",
        "information_rules",
        "consumer_adapters",
    }
    assert enabled_modules <= set(contract)
    assert "subjects" in contract
    assert "subjects" not in enabled_modules
    assert contract["fiscal"]["stateful"] is True
    assert contract["fiscal"]["direct_read"] is False
    assert contract["fiscal"]["ttl_or_none"] == policy.ttl_days
    assert contract["fiscal"]["hooks"] == [
        "on_monthly_pulse_country",
        "on_country_default",
        "on_country_no_longer_default",
    ]
    for name, item in contract.items():
        assert item["save_compatibility"] == policy.package.save_compatibility
        if name != "fiscal":
            assert item["stateful"] is False
            assert item["direct_read"] is True
            assert item["ttl_or_none"] is None
    assert contract["information_rules"]["clear_on_disable"] == "no_persistent_state"
    assert contract["consumer_adapters"]["clear_on_disable"] == (
        "regenerate_without_adapter_files_and_restart"
    )
    assert all(
        getattr(extensions, f"{name}_enabled")
        for name in ("reform", "market", "security", "economy", "diplomacy")
    )


@pytest.mark.integration
def test_七模块完整候选生成所有脚本和全语言无回退():
    policy, extensions, files = distribution.package_inputs(include_engineering_metadata=True)
    metadata = json.loads(files[".metadata/metadata.json"])
    assert policy.package.status == "candidate"
    assert metadata["enabled_modules"] == [
        "fiscal",
        "reform",
        "market",
        "security",
        "economy",
        "diplomacy",
        "information_rules",
        "consumer_adapters",
    ]
    localization = metadata["localization"]
    assert localization["production_fallback_languages"] == []
    assert localization["explanation_fallback_languages"] == []
    assert localization["fallback_languages"] == []
    assert extensions.economy_enabled
    assert extensions.diplomacy_enabled
    assert all(
        getattr(extensions, f"{name}_enabled")
        for name in ("reform", "market", "security", "economy", "diplomacy")
    )
    for name, text in files.items():
        assert "\r" not in text
        assert not text.startswith("\ufeff")
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
    strategy = files["common/ai_strategies/00_default_strategy.txt"]
    for field in (
        "economic_vs_government_spending_balance",
        "recklessness",
    ):
        assert f"# SITAI BEGIN {field}" in strategy
