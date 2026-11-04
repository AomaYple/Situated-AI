"""Legal opportunities preserve real mechanisms and never invent taxable bases."""

from __future__ import annotations

import copy
import tomllib
from collections import Counter

import pytest

from pdx import config, decision_rules, law_opportunities
from pdx.situated import programs

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def derived():
    raw = tomllib.loads((config.REPO / "mod/decisions/adapters.toml").read_text(encoding="utf-8"))
    return law_opportunities.derive(raw)


def _policy(derived, source):
    rows = [rule for rule in derived["rules"] if rule["source"] == source]
    used = {clause["fact"] for rule in rows for clause in rule["conditions"]}
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": "0" * 64,
            "domains": dict.fromkeys({row["domain"] for row in rows}, True),
            "readers": {key: derived["readers"][key] for key in sorted(used)},
            "rules": [
                {key: value for key, value in row.items() if key != "source"} for row in rows
            ],
        },
        source_sha256="0" * 64,
    )
    return programs.enable(policy, source=source)


def _value(derived, law, changes):
    source = next(row["source"] for row in derived["covered"] if row["id"] == law)
    policy = _policy(derived, source)
    values = {
        reader.key: False if reader.kind == "boolean" else max(reader.minimum or 0, 0)
        for reader in policy.readers
    }
    values.update(changes)
    result = decision_rules.evaluate(policy, values, is_ai=True).get(
        f"{law}.ai_enact_weight_modifier"
    )
    return result[1] if result else 0


def test_six_complete_native_families_have_37_unique_concrete_consumers(derived):
    assert len(derived["covered"]) == 52
    assert len({(row["source"], row["field"]) for row in derived["covered"]}) == 52
    assert sorted(Counter(row["source"] for row in derived["covered"]).values()) == [
        3,
        4,
        5,
        5,
        6,
        6,
        6,
        8,
        9,
    ]
    assert all(rule["contribution_group"] for rule in derived["rules"])
    assert not any(rule.get("intent") or rule.get("contexts") for rule in derived["rules"])
    assert not any(
        c["fact"] in {"industrial", "war", "loans", "coord_layer_foundation"}
        for rule in derived["rules"]
        for c in rule["conditions"]
    )


@pytest.mark.parametrize("law", ["law_proportional_taxation", "law_graduated_taxation"])
def test_loans_do_not_predict_tax_revenue_and_real_agenda_joins_cost(derived, law):
    assert _value(derived, law, {"loans": True, "legitimacy": 60}) == 0
    supported = {f"law_context_{law}_movement_base": True}
    assert _value(derived, law, supported) == 6
    assert _value(derived, law, {**supported, f"law_context_{law}_movement_strong": True}) == 10
    crisis = {"legitimacy": 10, "insurrection": True, "radical_share": 0.3}
    assert _value(derived, law, {**supported, **crisis}) == -4
    assert (
        _value(
            derived,
            law,
            {
                **supported,
                **crisis,
                "bureaucracy": -1,
                "law_context_current_law_consumption_based_taxation": True,
            },
        )
        == -10
    )
    assert _value(derived, law, {**supported, **crisis, "legitimacy": None}) == 6
    assert _value(derived, law, {**crisis, f"law_context_{law}_movement_base": None}) == -10


def test_trade_need_has_a_foundation_without_a_peace_or_health_gate(derived):
    law = "law_free_trade"
    need = {
        "law_context_current_law_mercantilism": True,
        "grain_balance": -1,
        "loans": True,
        "default": True,
        "war": True,
        "literacy": 0.1,
    }
    assert _value(derived, law, need) == 8
    assert _value(derived, law, {**need, "grain_price": 0.251}) == 15
    assert _value(derived, law, {**need, "grain_price": None}) == 8
    assert _value(derived, law, {**need, "grain_balance": 0}) == 0
    assert (
        _value(derived, law, {**need, "legitimacy": 10, "insurrection": True, "radical_share": 0.3})
        == -2
    )
    assert _value(derived, law, {**need, "tools_balance": -1}) == 8


def test_interventionism_uses_actual_transition_tax_capacity_and_administration(derived):
    law = "law_interventionism"
    need = {"law_context_current_law_traditionalism": True, "tools_balance": -1}
    assert _value(derived, law, need) == 10
    assert _value(derived, law, {**need, "bureaucracy": -1}) == 4
    assert _value(derived, law, {**need, "owned_incorporated_tax_shortfall": True}) == 16
    assert (
        _value(
            derived,
            law,
            {
                **need,
                "bureaucracy": -1,
                "owned_incorporated_tax_shortfall": True,
                "legitimacy": 10,
                "insurrection": True,
                "radical_share": 0.3,
            },
        )
        == 0
    )
    assert _value(derived, law, {**need, "law_context_current_law_traditionalism": None}) == 0


def test_rural_transition_is_a_real_current_law_difference(derived):
    law = "law_tenant_farmers"
    assert (
        _value(
            derived,
            law,
            {
                "law_context_current_law_serfdom": True,
                "peasant_share": 0.6,
                "war": True,
                "default": True,
            },
        )
        == 12
    )
    assert _value(derived, law, {"peasant_share": 0.9}) == 0


@pytest.mark.parametrize("law", ["law_migration_controls", "law_commercialized_agriculture"])
def test_actual_policy_agenda_is_distinct_from_guessed_migration_or_profit(derived, law):
    assert _value(derived, law, {"industrial": True, "literacy": 0.8, "peasant_share": 0.7}) == 0
    assert _value(derived, law, {f"law_context_{law}_movement_base": True}) == 6


@pytest.mark.parametrize("fault", ["schema", "candidate", "tuning"])
def test_malformed_configuration_is_rejected(monkeypatch, fault):
    data = copy.deepcopy(law_opportunities.load())
    if fault == "schema":
        data["schema"] = True
    elif fault == "candidate":
        data["candidates"]["../other"] = data["candidates"].pop("law_traditionalism")
    else:
        data["tuning"]["agenda_base"] = float("nan")
    monkeypatch.setattr(law_opportunities.tomllib, "loads", lambda *_: data)
    with pytest.raises(ValueError):
        law_opportunities.load()


@pytest.mark.integration
def test_complete_native_sources_and_definitions_are_verified_without_looking_up_a_game():
    sources = law_opportunities.load()["sources"]
    inputs = {source: (config.GAME / source).read_text(encoding="utf-8-sig") for source in sources}
    law_opportunities.verify_inputs(inputs)
    source = next(iter(sources))
    with pytest.raises(ValueError, match="漂移"):
        law_opportunities.verify_inputs({**inputs, source: inputs[source] + "\n"})
    with pytest.raises(ValueError, match="漂移"):
        law_opportunities.verify_inputs(
            {key: value for key, value in inputs.items() if key != source}
        )
