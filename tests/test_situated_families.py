"""细分行动族的稳定性和全生产实例覆盖。"""

import pytest

from pdx import decision_adapters, decision_rules
from pdx.situated.action_instances import build, witness_contract
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


def test_every_production_instance_has_a_family_and_scope() -> None:
    information = decision_rules.load()
    adapters = decision_adapters.load()
    instances = build(information, adapters)
    assert len(instances) == 1401
    assert all(item.family_id in FAMILIES for item in instances)
    assert all(item.actor_scope and item.target_scope for item in instances)
    families = {item.family_id for item in instances}
    assert set(FAMILIES) <= families


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
    assert contract["count"] == 1401
    assert contract["witnessed_count"] == 1401
    assert contract["missing"] == []
