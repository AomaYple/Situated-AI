"""细分行动族的稳定性和全生产实例覆盖。"""

from typing import Any, cast

import pytest
from _situated_sources import production_sources

from pdx import decision_adapters, decision_rules
from pdx.situated.action_instances import (
    ActionInstance,
    behavior_witness_contract,
    build,
    missing_witnesses,
    witness_contract,
)
from pdx.situated.families import FAMILIES, classify

pytestmark = pytest.mark.unit


def test_family_classifier_is_deterministic_and_uses_no_country_name() -> None:
    assert classify(domain="economy", field="building_iron_mine.ai_value") == "resources"
    assert (
        classify(domain="political", field="law_public_schools.ai_enact_weight_modifier")
        == "education"
    )
    assert classify(domain="military", field="ai_strategy_default.wanted_navy_size") == "navy"
    assert classify(domain="diplomacy", field="colonial_interest_ratio") == "overseas"


@pytest.mark.parametrize(
    ("domain", "field", "source", "expected"),
    [
        (
            "economy",
            "automatic_bottle_blowers.ai_weight",
            "common/technology/technologies/10_production.txt",
            "research",
        ),
        ("military", "battlefleet_tactics.ai_weight", "", "navy"),
        ("military", "battleship_tech.ai_weight", "", "navy"),
        (
            "military",
            "ai_strategy_default.ai_ship_category_weights.ai_ship_category_battle_line",
            "",
            "navy",
        ),
        (
            "political",
            "law_colonial_resettlement.ai_enact_weight_modifier",
            "common/laws/01_colonial_affairs.txt",
            "overseas",
        ),
        ("economy", "settlement_capacity", "", "industry"),
        ("economy", "bottle_output", "", "industry"),
    ],
)
def test_embedded_ttl_letters_do_not_create_temporal_writers(domain, field, source, expected):
    assert classify(domain=domain, field=field, source=source) == expected


@pytest.mark.parametrize(
    ("field", "source"),
    [
        ("route_ttl_days", ""),
        ("route.cooldown_days", ""),
        ("temporal.route", ""),
        ("route.weight", "mod/decisions/temporal.toml"),
    ],
)
def test_explicit_temporal_keys_and_sources_keep_temporal_responsibility(field, source):
    assert classify(domain="economy", field=field, source=source) == "temporal"


@pytest.mark.parametrize(
    "field",
    [
        "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply",
        "ai_strategy_default.target_marine_formation_size",
        "ai_strategy_default.wanted_marines",
        "ai_strategy_default.naval_invasion_weight",
        "submarine.ai_weight",
        "battlefleet_tactics.ai_weight",
    ],
)
def test_naval_consumers_keep_navy_responsibility_without_ship_in_their_names(field):
    assert classify(domain="military", field=field) == "navy"


def test_colonial_law_source_has_one_overseas_responsibility():
    policies = dict(decision_adapters.load().policies)
    source = "common/laws/01_colonial_affairs.txt"
    rules = policies[source].rules
    assert {rule.field[0] for rule in rules} == {
        "law_colonial_exploitation",
        "law_colonial_resettlement",
        "law_frontier_colonization",
        "law_no_colonial_affairs",
    }
    assert {
        classify(domain=rule.domain, field=".".join(rule.field), source=source) for rule in rules
    } == {"overseas"}


def test_marker_identity_uses_output_source_and_definition_together() -> None:
    common: dict[str, Any] = {
        "kind": "rule_action",
        "rule_id": "same_rule",
        "domain": "economy",
        "consumer_field": "wanted_construction_output",
        "operation": "multiply",
        "value": 1.1,
        "condition_facts": (),
        "owner": "test",
        "vanilla_tail": "retain",
        "evidence": (),
        "family_id": "industry",
        "actor_scope": "root",
        "target_scope": "none",
    }
    instances = (
        ActionInstance(action_id="first", source="common/first.txt", **common),
        ActionInstance(action_id="second", source="common/second.txt", **common),
    )
    texts = {"common/first.txt": "# same_rule [economy];\n"}
    assert missing_witnesses(instances, texts) == ("second",)
    contract = witness_contract(instances, texts)
    assert contract["witnessed_count"] == 1
    rows = cast("list[dict[str, object]]", contract["rows"])
    assert [row["action_id"] for row in rows if not row["witnessed"]] == ["second"]


def test_every_production_instance_has_a_family_and_scope() -> None:
    information = decision_rules.load()
    adapters = decision_adapters.load()
    instances = build(information, adapters)
    assert len(instances) == len(production_sources().rules)
    assert {
        (item.source, item.rule_id, item.consumer_field) for item in instances
    } == production_sources().rules
    assert all(item.family_id in FAMILIES for item in instances)
    assert all(item.actor_scope and item.target_scope for item in instances)
    families = {item.family_id for item in instances}
    assert families == set(FAMILIES) - {"temporal"}
    assert not [item for item in instances if item.family_id == "temporal"]


@pytest.mark.integration
def test_instance_witness_contract_is_complete_for_generated_rules() -> None:
    information = decision_rules.load()
    adapters = decision_adapters.load()
    instances = build(information, adapters)
    from pdx import country_state, decisions

    generated = decisions.build(
        information_rules=information,
        consumer_adapters=adapters,
        country_policy=country_state.load(),
        extensions=decisions.load_extensions(profile="release"),
    )
    contract = witness_contract(
        instances, {name: text for name, text in generated.items() if name.endswith(".txt")}
    )
    assert contract["count"] == len(production_sources().rules)
    assert contract["witnessed_count"] == len(production_sources().rules)
    assert contract["missing"] == []


@pytest.mark.integration
def test_behavior_witness_contract_matches_each_generated_legacy_operation_and_value() -> None:
    information = decision_rules.load()
    adapters = decision_adapters.load()
    instances = build(information, adapters)
    from pdx import country_state, decisions

    generated = decisions.build(
        information_rules=information,
        consumer_adapters=adapters,
        country_policy=country_state.load(),
        extensions=decisions.load_extensions(profile="release"),
    )
    contract = behavior_witness_contract(
        instances, {name: text for name, text in generated.items() if name.endswith(".txt")}
    )
    assert contract["count"] == len(production_sources().rules)
    assert contract["expected"] == len(production_sources().rules)
    assert contract["missing"] == []
    assert contract["mismatches"] == []
