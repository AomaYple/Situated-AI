"""细分行动族的稳定性和全生产实例覆盖。"""

from typing import Any, cast

import pytest

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
    assert len(instances) == 1414
    assert all(item.family_id in FAMILIES for item in instances)
    assert all(item.actor_scope and item.target_scope for item in instances)
    families = {item.family_id for item in instances}
    assert set(FAMILIES) <= families


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
    assert contract["count"] == 1414
    assert contract["witnessed_count"] == 1414
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
    assert contract["count"] == 1414
    assert contract["expected"] == 1414
    assert contract["missing"] == []
    assert contract["mismatches"] == []
