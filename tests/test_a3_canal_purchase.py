"""Exact recurring canal purchase cost, distinct from native liquidity gates."""

from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render

from pdx import canal_opportunities as canals
from pdx import decision_adapters, decision_interfaces, decision_rules
from pdx.parser import parse_text
from pdx.situated import programs

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def policy():
    derived = canals.derive({"readers": {}})
    return programs.enable(
        decision_rules.from_data(
            {
                "schema": 1,
                "baseline_sha256": canals.load()["sources"][canals.SOURCE],
                "domains": {"geography": True},
                "readers": derived["readers"],
                "rules": [
                    {k: v for k, v in row.items() if k != "source"} for row in derived["rules"]
                ],
            },
            source_sha256="0" * 64,
        ),
        source=canals.SOURCE,
    )


@pytest.fixture(scope="module")
def locked_inputs():
    # Getters are proven by the complete source-locked production inputs;
    # the independent canal freeze separately proves costs and native tails.
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    canals.verify_inputs(inputs)
    return adapters.sources, inputs


@pytest.fixture(scope="module")
def production(policy, locked_inputs):
    sources, inputs = locked_inputs
    adapters = decision_adapters.AdapterSet(
        policies=((canals.SOURCE, policy),),
        sources=sources,
        source_sha256="0" * 64,
        canal_opportunities_sha256="0" * 64,
    )
    files, _ = decision_adapters.build(adapters, texts=inputs)
    return files[canals.SOURCE], adapters, inputs


@pytest.mark.parametrize("name", ["suez", "panama"])
@pytest.mark.parametrize(
    ("income", "factor"),
    [
        (50000, 1),
        (30000, 1),
        (29999.99, 0.9),
        (0, 0.9),
        (-0.01, 0.8),
        (-50000, 0.8),
        (None, 0.8),
    ],
)
def test_purchase_cashflow_hand_numbers_and_actual_pdx_preserve_native_twenty(
    policy, production, name, income, factor
):
    text, _, inputs = production
    field = f"{name}_canal_purchase.ai_chance"
    values = {
        "net_surplus": income,
        "cost_country_population": 1000,
        "bureaucracy": -999,
        "default": True,
    }
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(field, ("", 1))[
        1
    ] == pytest.approx(factor)
    native = _block(
        _block(parse_text(inputs[canals.SOURCE]).root, f"{name}_canal_purchase"), "ai_chance"
    )
    body = "\n".join(_render(row) for row in native.items if getattr(row, "key", "") != "value")
    body += "\n" + _overlay(text, field)
    facts = {
        "ROOT": {
            "is_ai": True,
            "gold_reserves": 16000000,
            "net_fixed_income": 110000,
            "net_total_income": income,
            "total_population": 1000,
            "is_at_war": False,
            "is_diplomatic_play_committed_participant": False,
            "bureaucracy": -999,
            "in_default": True,
        }
    }
    assert _native_number(0, body, facts) == pytest.approx(20 * factor)
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert (
        decision_rules.evaluate_ir(replace(policy, enabled_domains=frozenset()), values, is_ai=True)
        == {}
    )


@pytest.mark.parametrize("name", ["suez", "panama"])
@pytest.mark.parametrize(
    ("gold", "fixed", "war", "play", "expected"),
    [
        (15000000, 100000, False, False, 0),
        (15000000.01, 100000, False, False, 8),
        (1, 100000.01, False, False, 8),
        (0, 100001, False, False, 0),
        (16000000, 110000, True, False, 0),
        (16000000, 110000, False, True, 0),
    ],
)
def test_exact_native_boundaries_and_war_zero_never_revived(
    production, name, gold, fixed, war, play, expected
):
    text, _, inputs = production
    field = f"{name}_canal_purchase.ai_chance"
    native = _block(
        _block(parse_text(inputs[canals.SOURCE]).root, f"{name}_canal_purchase"), "ai_chance"
    )
    body = "\n".join(_render(row) for row in native.items if getattr(row, "key", "") != "value")
    body += "\n" + _overlay(text, field)
    facts = {
        "ROOT": {
            "is_ai": True,
            "gold_reserves": gold,
            "net_fixed_income": fixed,
            "net_total_income": -1,
            "is_at_war": war,
            "is_diplomatic_play_committed_participant": play,
        }
    }
    assert _native_number(0, body, facts) == pytest.approx(expected)


def test_exact_purchase_catalog_cost_sources_and_no_survey_cashflow_dependency(policy):
    rows = {row["field"]: row for row in canals.consumer_catalog()}
    assert set(rows) == {*canals.FIELDS, *canals.PURCHASE_FIELDS}
    for name in ("suez", "panama"):
        row = rows[f"{name}_canal_purchase.ai_chance"]
        assert (row["cost"], row["duration_months"], row["cost_unit"]) == (
            30000,
            120,
            "currency_per_week",
        )
        assert row["cost_source"] == canals.PURCHASE_MODIFIERS
        assert row["cost_modifier"] == f"{name}_purchase"
        contract = decision_interfaces.consumer(
            tuple(row["field"].split(".")), (), source=canals.SOURCE, native_root="country"
        )
        assert contract["native_unit"] == "relative_weight"
        for rule in policy.rules:
            if rule.field == (f"{name}_survey_decision", "ai_chance"):
                assert "net_surplus" not in rule.input_keys()
            if rule.field == (f"{name}_canal_purchase", "ai_chance"):
                assert rule.input_keys() == {"net_surplus", "cost_country_population"}
                assert rule.conservative_unknown_facts == ("net_surplus",)
                assert rule.unknown_cost_required_known_facts == ("cost_country_population",)


def test_full_native_ast_player_disabled_and_source_identity_preserved(policy, production):
    text, adapters, inputs = production
    stripped = text
    for field in (*canals.FIELDS, *canals.PURCHASE_FIELDS):
        begin = stripped.index(f"# SITAI BEGIN information:{field}")
        end = stripped.index(f"# SITAI END information:{field}", begin)
        end = stripped.index("\n", end) + 1
        stripped = stripped[:begin] + stripped[end:]
    assert _render(parse_text(stripped).root) == _render(parse_text(inputs[canals.SOURCE]).root)
    files, _ = decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())
    assert files == {}
    for source in canals.load()["sources"]:
        with pytest.raises(ValueError, match="漂移"):
            canals.verify_inputs({**inputs, source: inputs[source] + "\n"})
    assert all(rule.operation == "multiply" and rule.value > 0 for rule in policy.rules)


@pytest.mark.parametrize("name", ["suez", "panama"])
def test_each_purchase_writes_only_its_own_exact_consumer(policy, locked_inputs, name):
    field = (f"{name}_canal_purchase", "ai_chance")
    rules = tuple(r for r in policy.rules if r.field == field)
    keys = {key for rule in rules for key in rule.input_keys()}
    selected = programs.enable(
        replace(
            policy,
            rules=rules,
            readers=tuple(reader for reader in policy.readers if reader.key in keys),
            semantic_ir=(),
            consumer_programs=(),
        ),
        source=canals.SOURCE,
    )
    sources, inputs = locked_inputs
    adapters = decision_adapters.AdapterSet(
        policies=((canals.SOURCE, selected),),
        sources=sources,
        source_sha256="0" * 64,
        canal_opportunities_sha256="0" * 64,
    )
    files, _ = decision_adapters.build(adapters, texts=inputs)
    assert files[canals.SOURCE].count("# SITAI BEGIN") == 1
    assert f"# SITAI BEGIN information:{name}_canal_purchase.ai_chance" in files[canals.SOURCE]


@pytest.mark.parametrize("name", ["suez", "panama"])
@pytest.mark.parametrize(
    ("income", "population", "factor"),
    [
        (None, None, 1),
        (None, 1000, 0.8),
        (-1, None, 0.8),
        (30000, None, 1),
    ],
)
def test_unknown_pressure_requires_root_entity_but_known_pressure_needs_no_anchor(
    policy, production, name, income, population, factor
):
    text, _, _ = production
    field = f"{name}_canal_purchase.ai_chance"
    values = {"net_surplus": income, "cost_country_population": population}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(field, ("", 1))[
        1
    ] == pytest.approx(factor)
    facts = {"ROOT": {"is_ai": True, "net_total_income": income, "total_population": population}}
    assert _native_number(10, _overlay(text, field), facts) == pytest.approx(10 * factor)
