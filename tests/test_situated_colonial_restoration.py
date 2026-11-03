"""Unproven colonial ratio overrides are withdrawn, never relabelled as implemented."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pdx import decision_rules, decisions, distribution
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import bindings, compiler, engine_scope, migration_baseline
from pdx.situated.native_treatments import _digest

pytestmark = pytest.mark.unit


def _strategy_field(text, field):
    parsed = parse_text(text)
    assert not parsed.errors
    strategy = parsed.root.first("ai_strategy_default")
    assert strategy is not None
    assert isinstance(strategy.value, Block)
    block = strategy.value
    for name in field.split("."):
        value = block.first(name)
        assert value is not None
        assert isinstance(value.value, Block)
        block = value.value
    return block


@pytest.mark.parametrize("navy", [None, -1, 0, 24, 25, 49, 50, 75, 100])
@pytest.mark.parametrize("default", [None, False, True])
def test_unproven_field_has_no_active_rule_or_binding_even_at_old_thresholds(navy, default):
    source = decision_rules.load()
    values: dict[str, object] = {reader.key: None for reader in source.readers}
    values.update(navy=navy, default=default, gdp=1, infamy=0, war=False, route_maritime=True)
    assert "colonial_interest_ratio" not in decision_rules.evaluate(source, values, is_ai=True)
    assert all(rule.field != ("colonial_interest_ratio",) for rule in source.rules)
    assert all(binding.field != "colonial_interest_ratio" for binding in bindings.build())


@pytest.mark.integration
def test_complete_production_restores_native_ratio_ast_without_claiming_control():
    _policy, _extensions, generated = distribution.package_inputs()
    native = decisions.BASELINE.read_text(encoding="utf-8")
    produced = generated["common/ai_strategies/00_default_strategy.txt"]
    expected = _strategy_field(native, "colonial_interest_ratio")
    actual = _strategy_field(produced, "colonial_interest_ratio")
    assert _digest(actual) == _digest(expected)
    assert _digest(actual) == "4a4a4342151af33b74989498b00e2bd840da9e60862680b47ecbf17e7a4564ba"
    assert (
        "# SITAI BEGIN colonial_interest_ratio"
        not in generated["common/ai_strategies/00_default_strategy.txt"]
    )
    contract = json.loads(engine_scope.strategy_snapshot())
    assert "colonial_interest_ratio" not in contract["consumers"]
    model = compiler.load_model()
    assert model.consumer_ir is not None
    assert all(w.field != "colonial_interest_ratio" for w in model.consumer_ir.writers)
    retired = migration_baseline.validated_retirements(model.consumer_ir)
    historical = json.loads(migration_baseline.DEFAULT_SOURCE.read_bytes())
    original = {
        (row["source"], row["definition"])
        for row in historical["rules"]
        if row["field"] == "colonial_interest_ratio"
    }
    assert len(original) == 5
    assert original <= retired
    stance = "strategic_region_stance_type_scores.stance_colonize_region"
    assert _digest(_strategy_field(produced, stance)) == _digest(_strategy_field(native, stance))
    assert not any(w.field == f"ai_strategy_default.{stance}" for w in model.consumer_ir.writers)
    assert any(
        w.field == "ai_strategy_default.wanted_num_supply_ships" for w in model.consumer_ir.writers
    )


def test_reintroducing_a_renamed_unproven_writer_still_fails_retirement():
    model = compiler.load_model()
    assert model.consumer_ir is not None
    template = next(w for w in model.consumer_ir.writers if w.kind == "rule_action")
    unsafe = replace(
        template,
        source="mod/decisions/information.toml",
        definition="new_unproven_colonial_writer",
        writer_id="new_unproven_colonial_writer",
        field="colonial_interest_ratio",
    )
    bundle = replace(model.consumer_ir, writers=(*model.consumer_ir.writers, unsafe))
    with pytest.raises(ValueError, match="原版恢复字段仍有活跃作者"):
        migration_baseline.validate_bundle(bundle)
