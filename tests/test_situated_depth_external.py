"""D8 外部域静态合同：外交、安全、宗属、地理与时间边界。"""

import pytest

from pdx.situated.compiler import load_model
from pdx.situated.domain_coverage import CHAINS, contract, load
from pdx.situated.families import FAMILIES

pytestmark = pytest.mark.unit

EXTERNAL_DOMAINS = frozenset(
    {"diplomacy", "subjects", "army", "war", "navy", "overseas", "geography", "temporal"}
)


def test_external_domains_cover_the_remaining_eight_families_and_all_chain_nodes():
    model = load_model()
    coverage = load()
    assert set(FAMILIES) >= EXTERNAL_DOMAINS
    rows = [item for item in model.action_instances if item.family_id in EXTERNAL_DOMAINS]
    assert {item.family_id for item in rows} == EXTERNAL_DOMAINS
    assert all(coverage[name].production_instances > 0 for name in EXTERNAL_DOMAINS)
    chains = [chain for chain in CHAINS if set(chain.domain_ids) & EXTERNAL_DOMAINS]
    assert {chain.id for chain in chains} == {
        "LJ02",
        "LJ09",
        "LJ10",
        "LJ11",
        "LJ12",
        "LJ13",
        "LJ14",
    }
    assert all(
        any(item.family_id == domain for item in model.action_instances)
        for chain in chains
        for domain in chain.domain_ids
    )


def test_external_unknown_and_static_behavior_boundaries_are_explicit():
    model = load_model()
    assert all(load()[name].unknown_policy == "vanilla" for name in EXTERNAL_DOMAINS)
    assert model.contract()["unknown_fallback"] == "vanilla"
    assert model.contract()["behavior_quality"] != "verified"
    assert all(
        item.vanilla_tail.startswith("retain_")
        for item in model.action_instances
        if item.family_id in EXTERNAL_DOMAINS
    )


def test_external_domains_are_parallel_and_inputs_do_not_reference_produced_outputs():
    model = load_model()
    rows = [item for item in model.action_instances if item.family_id in EXTERNAL_DOMAINS]
    ids = {item.action_id for item in rows}
    assert len(ids) == len(rows)
    assert all(not ids.intersection(item.condition_facts) for item in rows)
    assert len({item.action_id for item in model.action_instances}) == len(model.action_instances)


def test_external_local_relation_boundary_preserves_target_and_owner_scope_labels():
    model = load_model()
    rows = [item for item in model.action_instances if item.family_id in EXTERNAL_DOMAINS]
    assert all(item.actor_scope in {"root", "owner"} for item in rows)
    target_rows = [item for item in rows if item.target_scope != "none"]
    assert target_rows
    assert all(item.target_scope == "target_or_none" for item in target_rows)
    assert all(
        item.consumer_field.split(".")[-1] in {"state_value", "colonial_interest_ratio"}
        for item in target_rows
    )
    summary = contract(load(), model.action_instances)
    assert len(summary["chains"]) == 14
