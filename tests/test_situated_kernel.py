"""处境行动内核的确定性、预算和回退合同。"""

import json

import pytest

from pdx import country_state, decision_adapters, decision_intents, decision_rules, decisions
from pdx.parser import parse_text
from pdx.situated.arbitration import Candidate, choose
from pdx.situated.commitment import marginal_cost, overcommitted
from pdx.situated.compiler import compile_policy, load_model, strategy_overlay
from pdx.situated.goals import Goal, prioritize
from pdx.situated.pressure import severity

pytestmark = pytest.mark.unit


def test_生产行动卡引用真实消费者且关系有限():
    model = load_model()
    assert len(model.facts) >= 10
    assert len(model.actions) >= 6
    assert all(action.consumer in {item.id for item in model.consumers} for action in model.actions)
    assert len(model.relations) <= len(model.actions) * 3
    assert model.contract()["behavior_quality"] == "user_long_term_review_pending"


def test_行动降低为有限原版消费者条件块():
    model = load_model()
    overlay = strategy_overlay(model)
    assert set(overlay) == {item.field for item in model.consumers}
    assert all(text.count("add =") <= 3 for text in overlay.values())
    assert all("is_ai = yes" in text for text in overlay.values())
    patched = decisions.patch_default(
        decisions.BASELINE.read_text(encoding="utf-8"),
        decisions.load(),
        decisions.load_extensions(profile="release"),
        action_overlay=overlay,
    )
    assert not parse_text(patched).errors
    assert "set_strategy" not in patched


def test_仲裁按固定排序限幅并保留证据():
    result = choose(
        (
            Candidate("slow", capability_gain=2, feasibility=10),
            Candidate("crisis", crisis_protection=9, capability_gain=1),
        ),
        max_delta=5,
    )
    assert result.action_id == "crisis"
    assert result.delta == 5
    assert "crisis_protection" in result.reason_codes


def test_仲裁空候选回退原版():
    result = choose((), max_delta=5)
    assert result.action_id is None
    assert result.delta == 0
    assert result.fallback == "vanilla"


def test_生产元数据登记行动合同():
    payload = json.loads(
        decisions.build(extensions=decisions.load_extensions(profile="release"))[
            ".metadata/metadata.json"
        ]
    )
    contract = payload["situated_actions"]
    assert contract["schema"] == 1
    assert contract["candidate_limit"] == 7
    assert payload["source_fingerprint"]["situated_actions_source_sha256"]


def test_统一编译器覆盖信息与适配器的全部生产消费者():
    model = load_model()
    assert model.production_rule_count == 1401
    assert len(model.production_consumers) == 377
    source = decision_rules.load()
    compiled, report = compile_policy(source, config_model=model)
    assert len(compiled.rules) == len(source.rules)
    assert report["production_rule_count"] == 1401
    assert report["production_consumer_count"] == 377
    assert all(
        item["write_once"] and item["unknown_fallback"] == "vanilla" for item in report["fields"]
    )


def test_未知或玩家输入保持原版():
    model = load_model()
    compiled, _ = compile_policy(decision_rules.load(), config_model=model)
    assert decision_rules.evaluate(compiled, {}, is_ai=False) == {}
    # 缺少任意 reader 时，decision_rules 的安全语义是不生成调整。
    assert decision_rules.evaluate(compiled, {}, is_ai=True) == {}


def test_行动消费者成为四个策略字段的唯一作者():
    strategy = decision_intents.load()
    information = decision_rules.load(strategy=strategy)
    adapters = decision_adapters.load(strategy=strategy)
    country_policy = country_state.load()
    payload = json.loads(
        decisions.build(
            information_rules=information,
            consumer_adapters=adapters,
            country_policy=country_policy,
            extensions=decisions.load_extensions(profile="release"),
        )[".metadata/metadata.json"]
    )
    owners = payload["default_field_owners"]
    for field in (
        "diplomatic_play_neutrality",
        "change_law_chance",
        "economic_vs_government_spending_balance",
        "recklessness",
    ):
        assert owners[field] == "situated_kernel"


def test_状态辅助函数保留未知并提供确定性排序():
    assert marginal_cost({"debt": 0.4}, "debt") == 0.4
    assert marginal_cost({"debt": None}, "debt") is None
    assert overcommitted({"debt": 0.7, "war": 0.5}, limit=1.0)
    assert overcommitted({"debt": None}) is None
    assert severity({"default": 1.5}, "default") == 1.0
    assert severity({"default": None}, "default") is None
    goals = (Goal("capacity", 60, "medium", True), Goal("survival", 100, "crisis", True))
    assert [item.id for item in prioritize(goals)] == ["survival", "capacity"]
