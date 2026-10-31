"""D6 经济域静态合同：覆盖、回退、并行和局部关系边界。"""

import pytest

from pdx.situated.compiler import load_model
from pdx.situated.domain_coverage import CHAINS, contract, load
from pdx.situated.families import FAMILIES

pytestmark = pytest.mark.unit

ECONOMY_DOMAINS = frozenset(
    {"fiscal", "administrative", "industry", "resources", "market", "research", "education"}
)


def _instances():
    return load_model().action_instances


def test_economy_domains_have_static_base_contract_and_all_chain_nodes():
    model = load_model()
    coverage = load()
    assert set(FAMILIES) >= ECONOMY_DOMAINS
    rows = [item for item in model.action_instances if item.family_id in ECONOMY_DOMAINS]
    assert {item.family_id for item in rows} == ECONOMY_DOMAINS
    assert all(coverage[name].production_instances > 0 for name in ECONOMY_DOMAINS)
    assert all(item.value != 0 for item in rows)
    assert all(item.vanilla_tail.startswith("retain_") for item in rows)
    chain_rows = [chain for chain in CHAINS if set(chain.domain_ids) & ECONOMY_DOMAINS]
    assert chain_rows
    assert all(
        any(item.family_id == domain for item in _instances())
        for chain in chain_rows
        for domain in chain.domain_ids
    )


def test_economy_unknown_policy_preserves_vanilla_and_does_not_become_false():
    model = load_model()
    coverage = load()
    assert all(coverage[name].unknown_policy == "vanilla" for name in ECONOMY_DOMAINS)
    assert all(fact.unknown == "vanilla" for fact in model.facts)
    assert model.contract()["unknown_fallback"] == "vanilla"
    assert model.contract()["behavior_quality"] != "verified"


def test_economy_domains_are_parallel_static_writers_with_no_cross_domain_output_dependency():
    rows = [item for item in _instances() if item.family_id in ECONOMY_DOMAINS]
    ids = {item.action_id for item in rows}
    assert len(ids) == len(rows)
    assert all(not set(item.condition_facts) & ids for item in rows)
    assert {item.kind for item in rows} <= {"rule_action", "action_card"}
    summary = contract(load(), _instances())
    assert all(
        summary["domains"][name]["declared_instances"]
        == summary["domains"][name]["actual_instances"]
        for name in ECONOMY_DOMAINS
    )


def test_economy_local_relation_boundary_keeps_target_state_fields_explicit():
    model = load_model()
    target_rows = [
        item
        for item in model.action_instances
        if item.family_id in ECONOMY_DOMAINS and item.target_scope != "none"
    ]
    assert not target_rows
    assert all(
        fact.scope in {"root", "target_country", "target_state", "interest_group", "overlord"}
        for fact in model.facts
    )
