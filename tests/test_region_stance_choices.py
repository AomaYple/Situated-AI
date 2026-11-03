"""Country routes cannot revive a native region with no colonial opportunity."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import programs

SOURCE = "common/ai_strategies/00_default_strategy.txt"
FIELD = "ai_strategy_default.strategic_region_stance_type_scores.stance_colonize_region"


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    policy = programs.enable(dict(adapters.policies)[SOURCE], source=SOURCE)
    subset = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        initial_values=tuple(row for row in adapters.initial_values if row.source == SOURCE),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == SOURCE),
    )
    native = decision_adapters.read_inputs(subset)
    files, _ = decision_adapters.build(subset, texts=native, country_policy=country_state.load())
    before, after = parse_text(native[SOURCE]).root, parse_text(files[SOURCE]).root
    for part in FIELD.split("."):
        before, after = _block(before, part), _block(after, part)
    return policy, before, after


@pytest.mark.parametrize("route", [True, False, None])
@pytest.mark.parametrize("overseas", [True, False, None])
@pytest.mark.integration
def test_known_route_and_capacity_do_not_invent_actual_region_opportunity(
    production, route, overseas
):
    policy, before, after = production
    values: dict[str, object] = {reader.key: None for reader in policy.readers}
    values.update(
        route_maritime=route,
        coord_evidence_need_overseas=overseas,
        coord_layer_expansion=True,
        war=False,
        default=False,
        legitimacy=80,
        insurrection=False,
        radical_share=0,
    )
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert result.get(FIELD, (None, 0))[1] <= 0
    # Execute the actual production suffix after a native zero. A route/owner
    # capacity fact contains no target-region technology/law/adjacency proof.
    assert _render(after) == _render(before)
    assert not any(".".join(rule.field) == FIELD for rule in policy.rules)
    assert FIELD not in decision_rules.evaluate(policy, values, is_ai=False)
    assert FIELD not in decision_rules.evaluate(
        policy, values, is_ai=True, enabled_domains=frozenset()
    )


@pytest.mark.parametrize("route", [True, False, None])
@pytest.mark.parametrize("overseas", [True, False, None])
def test_region_policy_has_no_route_only_grant_without_originals(route, overseas):
    adapters = decision_adapters.load()
    policy = programs.enable(dict(adapters.policies)[SOURCE], source=SOURCE)
    values: dict[str, object] = {reader.key: None for reader in policy.readers}
    values.update(
        route_maritime=route,
        coord_evidence_need_overseas=overseas,
        coord_layer_expansion=True,
        war=False,
        default=False,
        legitimacy=80,
        insurrection=False,
        radical_share=0,
    )
    assert not any(".".join(rule.field) == FIELD for rule in policy.rules)
    assert FIELD not in decision_rules.evaluate(policy, values, is_ai=True)
    assert FIELD not in decision_rules.evaluate(policy, values, is_ai=False)
    assert FIELD not in decision_rules.evaluate(
        policy, values, is_ai=True, enabled_domains=frozenset()
    )


@pytest.mark.integration
def test_native_technology_zero_projection_keeps_zero_with_all_route_capacity_facts(production):
    policy, before, after = production
    facts = _facts(policy, {})
    facts["ROOT"].update(
        has_technology_researched={(("argument", "colonization"),): False},
        country_rank=10,
    )
    # The native NOR and neighbouring-region iterator are outside the independent
    # interpreter's supported grammar. Execute the exact necessary technology
    # predicate and native initial grant as an explicit projection; complete
    # native preservation is asserted separately above.
    for block in (before, after):
        opportunity = _block(block, "if")
        technology = _block(opportunity, "limit").first("has_technology_researched")
        grant = opportunity.first("add")
        assert technology is not None
        assert grant is not None
        body = "if = { limit = { " + _render(technology) + " } " + _render(grant) + " }"
        assert _native_number(0, body, facts) == 0
