"""D7 社会域静态合同：覆盖、未知保留、并行和作用域边界。"""

import pytest

from pdx.situated.compiler import load_model
from pdx.situated.domain_coverage import CHAINS, load
from pdx.situated.families import FAMILIES

pytestmark = pytest.mark.unit

SOCIETY_DOMAINS = frozenset({"political", "population", "social", "identity"})


def test_society_domains_and_chain_nodes_are_completely_declared():
    model = load_model()
    coverage = load()
    assert set(FAMILIES) >= SOCIETY_DOMAINS
    rows = [item for item in model.action_instances if item.family_id in SOCIETY_DOMAINS]
    assert {item.family_id for item in rows} == SOCIETY_DOMAINS
    assert all(
        coverage[name].production_instances
        == sum(
            item.family_id == name and item.kind == "rule_action" for item in model.action_instances
        )
        for name in SOCIETY_DOMAINS
    )
    chains = [chain for chain in CHAINS if set(chain.domain_ids) & SOCIETY_DOMAINS]
    assert chains
    assert all(
        any(item.family_id == domain for item in model.action_instances)
        for chain in chains
        for domain in chain.domain_ids
    )


def test_society_unknown_inputs_keep_vanilla_fallback_contract():
    model = load_model()
    assert all(load()[name].unknown_policy == "vanilla" for name in SOCIETY_DOMAINS)
    assert all(fact.unknown == "vanilla" for fact in model.facts)
    assert all(action.unknown_policy == "vanilla" for action in model.actions)
    assert model.contract()["behavior_quality"] != "verified"


def test_society_rules_can_be_reviewed_in_parallel_without_using_other_rule_ids_as_inputs():
    model = load_model()
    rows = [item for item in model.action_instances if item.family_id in SOCIETY_DOMAINS]
    ids = {item.action_id for item in rows}
    assert len(ids) == len(rows)
    assert all(not ids.intersection(item.condition_facts) for item in rows)
    assert all(item.vanilla_tail.startswith("retain_") for item in rows)


def test_society_local_relations_use_declared_scope_only():
    model = load_model()
    rows = [item for item in model.action_instances if item.family_id in SOCIETY_DOMAINS]
    assert all(item.actor_scope in {"root", "owner"} for item in rows)
    assert all(item.target_scope in {"none", "target_or_none"} for item in rows)
    assert all(relation.scope == "root" for relation in model.relations)
