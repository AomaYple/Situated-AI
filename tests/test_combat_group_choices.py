"""Coarse formation ratios must not invent a concrete unit's material recipe."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _render

from pdx import config, country_state, decision_adapters, decision_rules
from pdx.parser import parse_text

SOURCE = "common/ai_strategies/00_default_strategy.txt"
FIELDS = (
    "ai_strategy_default.combat_unit_group_weights.combat_unit_group_infantry",
    "ai_strategy_default.combat_unit_group_weights.combat_unit_group_cavalry",
)


@pytest.fixture(scope="module")
def adapters():
    return decision_adapters.load()


@pytest.mark.parametrize("war", [False, True, None])
@pytest.mark.parametrize("default", [False, True, None])
def test_small_arms_market_and_completed_technology_do_not_reweight_unobserved_units(
    adapters, war, default
):
    policy = dict(adapters.policies)[SOURCE]
    values = {
        r.key: False if r.kind == "boolean" else max(0, r.minimum or 0) for r in policy.readers
    }
    values.update(
        war=war,
        default=default,
        small_arms_price=1,
        small_arms_balance=-100,
        coordinated_line_infantry=True,
        coord_evidence_need_reconstruction=True,
    )
    for is_ai in (True, False):
        result = decision_rules.evaluate(policy, values, is_ai=is_ai)
        assert not set(result) & set(FIELDS)
    disabled = decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset())
    assert not set(disabled) & set(FIELDS)


@pytest.mark.integration
def test_complete_generated_source_keeps_native_group_ast_for_every_original_law_and_tech(adapters):
    policy = dict(adapters.policies)[SOURCE]
    subset = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        initial_values=tuple(row for row in adapters.initial_values if row.source == SOURCE),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == SOURCE),
    )
    native = decision_adapters.read_inputs(subset)
    files, _ = decision_adapters.build(subset, texts=native, country_policy=country_state.load())
    for field in FIELDS:
        before, after = parse_text(native[SOURCE]).root, parse_text(files[SOURCE]).root
        for part in field.split("."):
            before, after = _block(before, part), _block(after, part)
        assert _render(after) == _render(before)
        assert all(".".join(rule.field) != field for rule in policy.rules)


@pytest.mark.integration
def test_irregular_and_hussar_recipes_disprove_universal_small_arms_cost():
    source = config.GAME / "common/combat_unit_types/00_land_combat_unit_types.txt"
    units = parse_text(source.read_text(encoding="utf-8-sig")).root
    irregular = _block(units, "combat_unit_type_irregular_infantry")
    hussars = _block(units, "combat_unit_type_hussars")
    dragoons = _block(units, "combat_unit_type_dragoons")
    assert not _block(irregular, "upkeep_modifier").items
    hussar_cost = _block(hussars, "upkeep_modifier")
    assert hussar_cost.keys() == ["goods_input_grain_add"]
    assert _render(hussar_cost.first("goods_input_grain_add")) == "goods_input_grain_add = 1"
    assert (
        _render(_block(dragoons, "upkeep_modifier").first("goods_input_small_arms_add"))
        == "goods_input_small_arms_add = 2"
    )
