"""处境行动内核的确定性、预算和回退合同。"""

import json
import re
from dataclasses import replace

import pytest
from _situated_sources import production_sources

from pdx import country_state, decision_adapters, decision_intents, decision_rules, decisions
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import relations
from pdx.situated.arbitration import Candidate, choose
from pdx.situated.audit import report as audit_report
from pdx.situated.commitment import marginal_cost, overcommitted
from pdx.situated.compiler import (
    _action_conditions,
    _relation_conditions,
    compile_policy,
    load_model,
    strategy_overlay,
)
from pdx.situated.goals import Goal, prioritize
from pdx.situated.pressure import severity
from pdx.situated.schema import EvidenceValue
from pdx.situated.state import derive

pytestmark = pytest.mark.unit


def _max_exclusive_writes(block: Block) -> int:
    """独立沿 AST 的互斥控制流计算最多实际执行的字段写入。"""
    total = 0
    alternatives: list[int] = []
    for item in block.assignments():
        if item.key in {"if", "else_if", "else"} and isinstance(item.value, Block):
            if item.key == "if" and alternatives:
                total += max(alternatives)
                alternatives = []
            alternatives.append(_max_exclusive_writes(item.value))
        elif item.key in {"add", "multiply"}:
            total += 1
    return total + max(alternatives, default=0)


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
    for consumer in model.consumers:
        text = overlay[consumer.field]
        # Each action contributes exactly once to one bounded numeric program;
        # joint lowering must not duplicate candidates into combinatorial leaves.
        rows = [row for row in model.decision_ir if row.consumer_id == consumer.id]
        assert len(rows) <= consumer.budget
        ids = re.findall(r"# ACTION ([a-z][a-z0-9_]*) ", text)
        assert set(ids) == {f"joint_{consumer.id}", *(row.action_id for row in rows)}
        assert len(ids) == len(rows) + 1
        parsed = parse_text(text)
        assert not parsed.errors
        assert _max_exclusive_writes(parsed.root) == 1
    assert all("is_ai = yes" in text for text in overlay.values())
    patched = decisions.patch_default(
        decisions.BASELINE.read_text(encoding="utf-8"),
        decisions.load(),
        decisions.load_extensions(profile="release"),
        action_overlay=overlay,
    )
    assert not parse_text(patched).errors
    assert "set_strategy" not in patched


def test_互补关系是软增量而不是全满足硬门槛():
    overlay = strategy_overlay(load_model())
    economy = overlay["economic_vs_government_spending_balance"]
    # 教育与产业互补只能改变有界增量；不能把对方完整条件复制进
    # 当前行动的 limit，避免重新形成全满足门槛。
    assert set(re.findall(r"# ACTION ([a-z][a-z0-9_]*) ", economy)) == {
        "joint_economic_balance",
        "industrial_foundation",
        "education_and_research",
    }
    assert "industrial_foundation" in economy
    assert "education_and_research" in economy
    # World facts annotate each signed contribution. Neither opportunity
    # copies the other action's full qualification or uses peace as a gate.
    assert "literacy_rate >= 0.5" in economy
    assert "bureaucracy > 0" in economy
    assert "is_at_war = no" not in economy
    assert "value = -0.1" in economy
    assert "value = 0.15" in economy


def test_关系条件支持真假未知三值传播():
    relation = next(
        item
        for item in load_model().relations
        if item.source == "industrial_foundation" and item.target == "education_and_research"
    )
    assert _relation_conditions(relation, {"literacy_ready": True}) is True
    assert _relation_conditions(relation, {"literacy_ready": False}) is False
    assert _relation_conditions(relation, {}) is None


def test_requires_any有一个真值时不被另一个未知值阻塞():
    action = next(item for item in load_model().actions if item.id == "political_reform")
    assert (
        _action_conditions(
            action,
            {"peace": True, "no_insurrection": True, "stable_legitimacy": True, "default": False},
        )
        is True
    )


@pytest.mark.parametrize("unknown", [None, "yes", 0])
def test_未知或非布尔阻断条件不能被当成安全状态(unknown):
    action = next(item for item in load_model().actions if item.id == "political_reform")
    values = {
        "peace": True,
        "no_insurrection": True,
        "stable_legitimacy": True,
        "default": unknown,
    }
    assert _action_conditions(action, values) is None
    values.pop("default")
    assert _action_conditions(action, values) is None
    values["peace"] = False
    assert _action_conditions(action, values) is False


def test_政治成本进入实际候选强度():
    with_cost = choose(
        (Candidate("with", capability_gain=1, feasibility=1, political_cost=1),), max_delta=5
    )
    without_cost = choose((Candidate("without", capability_gain=1, feasibility=1),), max_delta=5)
    assert with_cost.delta < without_cost.delta


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


def test_仲裁同分使用升序稳定行动ID且拒绝非有限输入():
    result = choose(
        (Candidate("zeta", capability_gain=1), Candidate("alpha", capability_gain=1)),
        max_delta=5,
    )
    assert result.action_id == "alpha"
    with pytest.raises(ValueError, match="非有限"):
        choose((Candidate("bad", capability_gain=float("nan")),), max_delta=5)


def test_关系对称配对且仅使能关系禁止有向环():
    model = load_model()
    relation = next(
        item
        for item in model.relations
        if item.source == "industrial_foundation" and item.target == "education_and_research"
    )
    assert relation.condition_facts == ("literacy_ready",)
    assert relation.unknown_policy == "vanilla"
    assert all(
        (item.target, item.source, item.kind)
        in {(row.source, row.target, row.kind) for row in model.relations}
        for item in model.relations
        if item.kind in {"complements", "substitutes", "conflicts"}
    )
    first, second = model.actions[:2]
    cyclic = (
        replace(first, enables=(second.id,)),
        replace(second, enables=(first.id,)),
        *model.actions[2:],
    )
    with pytest.raises(ValueError, match="循环"):
        relations.validate(cyclic)


def test_成本在非同分场景降低强度而不是只影响排序():
    cheap = choose(
        (Candidate("cheap", capability_gain=4, feasibility=8, commitment_cost=0),),
        max_delta=20,
    )
    expensive = choose(
        (Candidate("expensive", capability_gain=4, feasibility=8, commitment_cost=6),),
        max_delta=20,
    )
    assert expensive.action_id == "expensive"
    assert expensive.delta < cheap.delta
    assert "commitment_cost" in expensive.reason_codes


def test_生产元数据登记行动合同():
    payload = json.loads(
        decisions.build(extensions=decisions.load_extensions(profile="release"))[
            ".metadata/metadata.json"
        ]
    )
    contract = payload["situated_actions"]
    assert contract["schema"] == 1
    assert contract["candidate_limit"] == len(decisions.load_situated_model().actions)
    assert payload["source_fingerprint"]["situated_actions_source_sha256"]
    assert (
        payload["situated_actions"]["action_instances"]["count"]
        == len(production_sources().rules) + contract["candidate_limit"]
    )
    assert payload["situated_actions"]["ir"]["count"] == len(production_sources().rules)
    ast = payload["situated_actions"]["ast_lowering_witness"]
    assert ast["mismatches"] == []
    assert ast["parsed_count"] == ast["witness_count"]
    assert ast["write_count"] == ast["witness_count"]


def test_覆盖报告只在逐实例生产见证齐全时完成():
    report = audit_report()
    # 旧生产 writer 已逐项见证，但 D0 的独立原版范围仍包含 pending
    # 面；覆盖报告不能把生产实例完成误报为全计划完成。
    assert report.status == "incomplete"
    assert report.scope_status in {"incomplete", "unverified"}
    assert not report.blocked
    assert not report.pending
    assert all(row.status == "implemented" for row in report.rows)
    owners = {row.owner for row in report.rows if row.status == "implemented"}
    assert {"information_rules", "consumer_adapters", "situated_kernel"} <= owners


def test_统一编译器覆盖信息与适配器的全部生产消费者():
    model = load_model()
    assert model.production_rule_count == len(production_sources().rules)
    assert len(model.production_consumers) == len(production_sources().consumers)
    assert {
        (item.source, ".".join(item.field)) for item in model.production_consumers
    } == production_sources().consumers
    assert {
        (item.source, item.rule_id, item.consumer_field)
        for item in model.action_instances
        if item.kind == "rule_action"
    } == production_sources().rules
    source = decision_rules.load()
    compiled, report = compile_policy(source, config_model=model)
    assert len(compiled.rules) == len(source.rules)
    assert report["production_rule_count"] == len(production_sources().rules)
    assert report["production_consumer_count"] == len(production_sources().consumers)
    assert all(
        item["write_once"] and item["unknown_fallback"] == "vanilla" for item in report["fields"]
    )


def test_未知或玩家输入保持原版():
    model = load_model()
    compiled, _ = compile_policy(decision_rules.load(), config_model=model)
    assert decision_rules.evaluate(compiled, {}, is_ai=False) == {}
    # 缺少任意 reader 时，decision_rules 的安全语义是不生成调整。
    assert decision_rules.evaluate(compiled, {}, is_ai=True) == {}


@pytest.mark.integration
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


def test_状态派生拒绝非有限数并保留未知维度():
    vector = derive(
        {
            "bureaucracy_positive": EvidenceValue("bureaucracy_positive", True, True),
            "default": EvidenceValue("default", float("nan"), True),
            "war": EvidenceValue("war", None, False),
            "subject": EvidenceValue("subject", True, True),
        }
    )
    assert dict(vector.capacities)["bureaucracy_positive"] == 1.0
    assert dict(vector.pressures)["default"] is None
    assert dict(vector.pressures)["war"] is None
    assert dict(vector.opportunities)["subject"] == 1.0


@pytest.mark.parametrize(
    ("raw", "known", "stale", "expected"),
    [
        (True, True, False, 1.0),
        (False, True, False, 0.0),
        (None, False, False, None),
        (True, False, False, None),
        (True, True, True, None),
        (0, True, False, None),
        (1, True, False, None),
        (2, True, False, None),
        (0.0, True, False, None),
        ("yes", True, False, None),
    ],
)
def test_布尔状态保留真假未知且不接受原始数值冒充(raw, known, stale, expected):
    names = (
        "stable_legitimacy",
        "strong_legitimacy",
        "bureaucracy_positive",
        "default",
        "war",
        "insurrection",
        "literacy_low",
        "subject",
    )
    vector = derive({name: EvidenceValue(name, raw, known, stale=stale) for name in names})
    actual = dict((*vector.capacities, *vector.pressures, *vector.opportunities))
    assert all(actual[name] == expected for name in names)
