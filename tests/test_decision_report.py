from __future__ import annotations

import json
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_intents, decision_report, decision_rules


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
    assert len(report["taxonomy"]) >= 18
    assert {row["id"] for row in report["taxonomy"]} == {
        "politics",
        "population",
        "social",
        "fiscal",
        "administrative",
        "industry",
        "agriculture_resources",
        "market_trade",
        "technology",
        "education",
        "diplomacy",
        "subjects",
        "military",
        "war",
        "navy",
        "colonial",
        "geography",
        "identity",
        "time_shock",
    }
    assert all(row["facts"] for row in report["taxonomy"]), report["taxonomy"]
    assert all(row["consumers"] for row in report["taxonomy"]), report["taxonomy"]
    assert all(row["status"] == "implemented" for row in report["taxonomy"]), report["taxonomy"]
    assert all(
        set(row["domain_switches"]) <= set(decision_report.DOMAINS) for row in report["taxonomy"]
    )
    assert report["strategy_field_merge_boundary"]["status"] == "engine_behavior_unverified"
    assert all(
        {"source", "module", "key", "engine"} <= fact.keys()
        for field in report["consumer_fields"]
        for candidate in field["candidates"]
        for fact in candidate["input_facts"]
    )


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


def _school_taxonomy(
    fact: dict[str, Any], *, other: dict[str, Any] | None = None
) -> dict[str, Any]:
    fields = [
        {
            "source": fact["source"],
            "owner": fact["module"],
            "field": "institution_scores.institution_schools",
            "candidates": [
                {
                    "id": "school_candidate",
                    "inputs": [fact["key"]],
                    "conditions": [{"fact": fact["key"], "op": "<", "value": 0.5}],
                    "priority": 10,
                    "unknown": "preserve_vanilla_and_block_lower_priority_if_not_known_false",
                    "consumer": {"role": "vanilla_school_investment"},
                }
            ],
        }
    ]
    rows = decision_report._taxonomy_rows(
        [fact] if other is None else [fact, other], fields, country_state.load()
    )
    return next(row for row in rows if row["id"] == "education")


@pytest.mark.parametrize("identity_part", ["source", "module"])
def test_taxonomy_never_borrows_same_alias_from_another_contract(identity_part: str) -> None:
    actual = {
        "source": "source-a",
        "module": "consumer_adapters",
        "key": "same",
        "engine": "gdp",
    }
    unrelated = {**actual, identity_part: "different", "engine": "literacy_rate"}
    education = _school_taxonomy(actual, other=unrelated)

    assert education["status"] == "retained_vanilla"
    assert education["edges"] == []
    assert education["consumers"] == []
    assert all(detail[identity_part] == "different" for detail in education["fact_details"])


def test_taxonomy_coordination_uses_owned_engine_and_traces_country_facts() -> None:
    signal = {
        "source": "school-source",
        "module": "consumer_adapters",
        "key": "local_alias",
        "engine": "sitai_context_need_education",
        "scope": "root",
        "path": ["owner"],
    }
    education = _school_taxonomy(signal)

    assert education["status"] == "implemented"
    assert education["coordination"] == ["school-source::consumer_adapters::local_alias"]
    edge = education["edges"][0]
    path = edge["coordination_paths"][0]
    assert path["signal"]["path"] == ["owner"]
    assert {(fact["source"], fact["key"], fact["engine"]) for fact in path["facts"]} == {
        ("mod/decisions/country_state.toml", "literacy", "literacy_rate"),
        ("mod/decisions/country_state.toml", "population", "total_population"),
    }
    assert path["nodes"][0]["name"] == "education"
    assert "mod/decisions/country_state.toml::country_state::literacy" in edge["inputs"]


def test_taxonomy_does_not_invent_signal_from_alias_prefix() -> None:
    education = _school_taxonomy(
        {
            "source": "school-source",
            "module": "consumer_adapters",
            "key": "coord_not_a_signal",
            "engine": "literacy_rate",
        }
    )

    assert education["status"] == "implemented"
    assert education["coordination"] == []
    assert education["edges"][0]["coordination_paths"] == []


def test_unknown_signal_cannot_prove_a_fact_to_consumer_chain() -> None:
    education = _school_taxonomy(
        {
            "source": "school-source",
            "module": "consumer_adapters",
            "key": "coord_need_education",
            "engine": "sitai_context_unknown_education",
        }
    )

    assert education["status"] == "discovered_only"
    assert education["facts"] == []
    assert education["coordination"] == []
    assert education["edges"] == []


def test_real_trade_and_research_consumers_use_their_actual_inputs(
    engineering_metadata: dict[str, Any],
) -> None:
    taxonomy = {row["id"]: row for row in decision_report.build(engineering_metadata)["taxonomy"]}
    research = next(
        edge for edge in taxonomy["technology"]["edges"] if edge["rule"] == "academia_ai_weight"
    )
    assert research["source"] == "common/technology/technologies/30_society.txt"
    assert set(research["inputs"]) == {
        "common/technology/technologies/30_society.txt::consumer_adapters::default",
        "common/technology/technologies/30_society.txt::consumer_adapters::literacy",
    }
    assert research["coordination"] == []
    assert "building_university.ai_value" in taxonomy["education"]["consumers"]
    assert research["consumer"]["eligibility_costs_and_execution"] == "retained_vanilla"

    trade = next(
        edge
        for edge in taxonomy["market_trade"]["edges"]
        if edge["field"] == "treaty_category_scores.trade"
        and any(name.endswith("::coord_layer_foundation") for name in edge["coordination"])
    )
    assert "mod/decisions/country_state.toml::country_state::income" in trade["inputs"]
    assert "mod/decisions/country_state.toml::country_state::debt_ratio" in trade["inputs"]
    assert trade["source"] == decision_report.DEFAULT_SOURCE
    assert trade["higher_priority_rules"]
    assert all(rule["priority"] > trade["priority"] for rule in trade["higher_priority_rules"])
    assert all(rule["conditions"] and rule["unknown"] for rule in trade["higher_priority_rules"])
    assert trade["unknown"] == "preserve_vanilla_and_block_lower_priority_if_not_known_false"


def test_route_provenance_keeps_persistent_lifecycle_separate(
    engineering_metadata: dict[str, Any],
) -> None:
    time = next(
        row
        for row in decision_report.build(engineering_metadata)["taxonomy"]
        if row["id"] == "time_shock"
    )
    path = next(
        path
        for edge in time["edges"]
        for path in edge["coordination_paths"]
        if path["signal"].get("argument") == "sitai_route_industry"
    )

    assert path["lifecycle"]["ttl_days"] > 0
    assert path["lifecycle"]["cooldown_days"] > 0
    assert {"routes", "budgets"} <= {node["section"] for node in path["nodes"]}
    assert "current_signal_may_outlive_facts" in path["boundary"]
    assert "other_route_preemption_not_expanded" in path["boundary"]


def test_optional_evidence_trace_keeps_no_positive_evidence_distinct_from_known_false() -> None:
    fact = {
        "source": "research-source",
        "module": "consumer_adapters",
        "key": "coord_evidence_need_industry",
        "engine": "sitai_context_evidence_need_industry",
    }
    paths = decision_report._coordination_paths([fact], country_state.load())

    assert paths
    path = paths["research-source::consumer_adapters::coord_evidence_need_industry"]
    assert path["evidence_protocol"]["raw_signal"] == "sitai_context_need_industry"
    assert path["evidence_protocol"]["false_means"] == "no_positive_evidence"
    assert path["evidence_protocol"]["raw_false_inferred"] is False
    assert path["nodes"][0]["section"] == "needs"
    assert path["nodes"][0]["name"] == "industry"
    assert {item["key"] for item in path["facts"]} == {
        "industrial_route",
        "resource_route",
        "war_defeat",
    }


def test_diplomacy_reports_real_wargoal_layered_facts_without_relations_keyword(
    engineering_metadata: dict[str, Any],
) -> None:
    diplomacy = next(
        row
        for row in decision_report.build(engineering_metadata)["taxonomy"]
        if row["id"] == "diplomacy"
    )
    edges = {edge["rule"]: edge for edge in diplomacy["edges"]}

    assert "coordinated_layered_conquer_expansion" in edges
    edge = edges["coordinated_layered_conquer_expansion"]
    assert edge["source"] == "common/ai_strategies/00_default_strategy.txt"
    assert edge["field"] == "ai_strategy_default.wargoal_scores.conquer_state"
    assert edge["rule_inputs"] == [
        "common/ai_strategies/00_default_strategy.txt::consumer_adapters::coord_layer_expansion"
    ]
    assert edge["coordination"] == edge["rule_inputs"]
    assert {
        "mod/decisions/country_state.toml::country_state::default",
        "mod/decisions/country_state.toml::country_state::debt_ratio",
        "mod/decisions/country_state.toml::country_state::income",
    } <= set(edge["inputs"])
    path = edge["coordination_paths"][0]
    assert path["signal"]["engine"] == "sitai_context_layer_expansion"
    assert {node["name"] for node in path["nodes"]} == {"expansion_capacity", "recovery"}
    assert any(
        rule["rule"] == "coordinated_layered_conquer_reconstruction"
        and rule["priority"] > edge["priority"]
        for rule in edge["higher_priority_rules"]
    )
