from __future__ import annotations

import json
from typing import Any

import pytest

from pdx import decision_adapters, decision_intents, decision_report, decision_rules


@pytest.fixture(scope="module")
def engineering_metadata() -> dict[str, Any]:
    return decision_report.source_metadata()


def test_decision_report_covers_all_declared_domains(engineering_metadata: dict[str, Any]) -> None:
    report = decision_report.build(engineering_metadata)

    assert report["goal"].startswith("基于国家处境")
    assert report["behavior_verified"] is False
    assert set(report["domains"]) == set(decision_report.DOMAINS)
    assert all(row["status"] == "consumer_mapped" for row in report["domains"].values())
    assert report["reader_count"] == (
        report["information_reader_count"] + report["consumer_reader_count"]
    )
    assert report["information_reader_count"] >= 1
    assert report["consumer_reader_count"] >= 1
    assert report["consumer_rule_count"] >= 1
    assert report["field_count"] == len(report["consumer_fields"])
    assert len(report["facts"]) == report["reader_count"]
    assert sum(report["profile"]["dimensions"].values()) == report["reader_count"]
    assert all(fact["used_by"] for fact in report["facts"])
    assert all(field["candidates"] for field in report["consumer_fields"])
    assert sum(len(field["candidates"]) for field in report["consumer_fields"]) == (
        report["information_rule_count"] + report["consumer_rule_count"]
    )
    assert report["profile"]["runtime_state"] == "bounded_persistent_routes"
    assert report["shocks"]["current_facts"]["active_war"]["rule_count"] > 0
    assert report["shocks"]["current_facts"]["war_defeat"]["rule_count"] > 0
    assert set(report["shocks"]["historical_events"].values()) == {
        "unsupported_no_locked_runtime_reader"
    }
    assert report["behavior_verified"] is False


def test_phase_four_to_six_static_coverage_is_explicit(
    engineering_metadata: dict[str, Any],
) -> None:
    """把 F4-F6 的工程出口钉在共享合同上，避免只更新计划文字。"""
    report = decision_report.build(engineering_metadata)
    fields = {row["field"] for row in report["consumer_fields"]}
    facts = {row["key"] for row in report["facts"]}

    # F4: 制度可行性使用原版法律/政府消费者与利益集团事实。
    assert {
        "ai_strategy_default.interest_group_government_weight",
        "ai_strategy_default.min_law_chance_to_pass",
        "ai_strategy_default.negotiation_chance",
        "revolution_aversion",
    } <= fields
    assert {"candidate_ig_clout", "candidate_ig_approval", "candidate_ig_government"} <= facts

    # F5: 外交、宗属、军事、殖民和地理都必须落到原版候选字段。
    assert {
        "ai_strategy_default.subject_value",
        "ai_strategy_default.become_subject_value",
        "ai_strategy_default.wargoal_scores.conquer_state",
        "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply",
        "colonial_interest_ratio",
        "state_value",
    } <= fields
    assert {
        "target_relations",
        "target_truce",
        "target_alliance",
        "target_army",
        "target_navy",
    } <= facts

    # F6: 只有有原版生命周期来源的战败记忆进入运行期；其它历史冲击显式未知。
    assert "war_defeat" in facts
    assert report["shocks"]["current_facts"]["war_defeat"]["rule_count"] > 0
    assert all(
        status == "unsupported_no_locked_runtime_reader"
        for status in report["shocks"]["historical_events"].values()
    )


def test_offline_metadata_reuses_the_shared_rule_contract(
    engineering_metadata: dict[str, Any],
) -> None:
    strategy = decision_intents.load()
    information = decision_rules.load(strategy=strategy)
    adapters = decision_adapters.load(strategy=strategy)

    assert engineering_metadata["decision_rules"] == decision_rules.contract(information)
    assert engineering_metadata["consumer_adapters"]["consumers"] == [
        {"source": source, **decision_rules.contract(rules, owner="consumer_adapters")}
        for source, rules in adapters.policies
    ]


def test_decision_report_rejects_missing_rationale(engineering_metadata: dict[str, Any]) -> None:
    broken = json.loads(json.dumps(engineering_metadata))
    broken["decision_rules"]["rules"][0]["why"] = ""

    with pytest.raises(ValueError, match="why"):
        decision_report.build(broken)


def test_decision_report_rejects_missing_vanilla_consumer(
    engineering_metadata: dict[str, Any],
) -> None:
    broken = json.loads(json.dumps(engineering_metadata))
    broken["decision_rules"]["rules"][0].pop("consumer")

    with pytest.raises(ValueError, match="consumer"):
        decision_report.build(broken)


@pytest.mark.parametrize(
    ("section", "mutation", "issue"),
    [
        ("readers", lambda rows: rows[0].update(engine="unknown_engine"), "画像维度"),
        ("rules", lambda rows: rows[0].update(inputs=["missing_fact"]), "读取器"),
        ("rules", lambda rows: rows[0].update(value=3.0), "越界"),
        ("rules", lambda rows: rows[0].update(domain="unregistered"), "领域"),
    ],
)
def test_decision_report_rejects_broken_links(
    engineering_metadata: dict[str, Any], section: str, mutation: Any, issue: str
) -> None:
    broken = json.loads(json.dumps(engineering_metadata))
    mutation(broken["decision_rules"][section])

    with pytest.raises(ValueError, match=issue):
        decision_report.build(broken)


def test_decision_report_rejects_wrong_relative_unit(
    engineering_metadata: dict[str, Any],
) -> None:
    broken = json.loads(json.dumps(engineering_metadata))
    contract = broken["consumer_adapters"]["consumers"]
    relative = next(
        (row, rule, condition)
        for row in contract
        for rule in row["rules"]
        for condition in rule["conditions"]
        if isinstance(condition["value"], dict)
    )
    row, _, condition = relative
    other_key = condition["value"]["fact"]
    next(reader for reader in row["readers"] if reader["key"] == other_key)["unit"] = "wrong"

    with pytest.raises(ValueError, match="单位不一致"):
        decision_report.build(broken)


def test_decision_report_rejects_duplicate_field_author(
    engineering_metadata: dict[str, Any],
) -> None:
    broken = json.loads(json.dumps(engineering_metadata))
    duplicate = json.loads(json.dumps(broken["consumer_adapters"]["consumers"][0]))
    for rule in duplicate["rules"]:
        rule["id"] = "duplicate_" + rule["id"]
    broken["consumer_adapters"]["consumers"].append(duplicate)

    with pytest.raises(ValueError, match="重复作者"):
        decision_report.build(broken)


@pytest.mark.parametrize(
    ("mutation", "issue"),
    [
        (
            lambda contract: contract["readers"].append(contract["readers"][0].copy()),
            "读取器 ID 重复",
        ),
        (
            lambda contract: next(iter(contract["cost_by_field"].values())).update(predicates=-1),
            "成本台账不一致",
        ),
        (
            lambda contract: contract.update(runtime_state="persistent"),
            "无状态",
        ),
    ],
)
def test_decision_report_rejects_contract_drift(
    engineering_metadata: dict[str, Any], mutation: Any, issue: str
) -> None:
    broken = json.loads(json.dumps(engineering_metadata))
    mutation(broken["decision_rules"])

    with pytest.raises(ValueError, match=issue):
        decision_report.build(broken)
