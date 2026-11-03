"""Naval research follows actual fleet use, not payment for future ships."""

from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/technology/technologies/20_military.txt"
TECHNOLOGIES = ("dreadnought_tech", "battleship_tech", "carrier_tech")


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    raw = dict(adapters.policies)[SOURCE]
    rules = tuple(rule for rule in raw.rules if rule.field[0] in TECHNOLOGIES)
    keys = {key for rule in rules for key in rule.input_keys()}
    raw = replace(
        raw,
        rules=rules,
        readers=tuple(r for r in raw.readers if r.key in keys),
        enabled_domains=frozenset(rule.domain for rule in rules),
        semantic_ir=(),
        consumer_programs=(),
    )
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy = compiler.compile_policy(raw, SOURCE, model)[0]
    selected = replace(
        adapters, policies=((SOURCE, policy),), initial_values=(), scalar_values=(), supply=None
    )
    files, _ = decision_adapters.build(
        selected, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policy, files[SOURCE]


@pytest.mark.parametrize("technology", TECHNOLOGIES)
@pytest.mark.parametrize(
    ("navy", "war", "expected"),
    [
        (5, True, 1.15),
        (5, False, 1.08),
        (5, None, 1.08),
        (0, True, 1),
        (0, None, 1),
        (None, True, 1),
        (None, None, 1),
        (-1, True, 1),
        (True, True, 1),
    ],
)
@pytest.mark.parametrize("default", [True, None])
def test_actual_fleet_use_and_unknown_war_have_local_research_effects(
    production, technology, navy, war, expected, default
):
    policy, text = production
    values = {reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers}
    # Research opens an option; it neither purchases ships nor commits their
    # materials. Fiscal distress cannot invent an immediate research bill.
    values.update(own_navy=navy, war=war, default=default, coord_need_fiscal=True)
    root: dict[str, Any] = {"is_ai": True}
    for reader in policy.readers:
        assert reader.scope == "root"
        assert not reader.path
        if reader.argument:
            root.setdefault(reader.engine, {})[(("argument", reader.argument),)] = values[
                reader.key
            ]
        else:
            root[reader.engine] = values[reader.key]
        if reader.engine.startswith("sitai_context_"):
            root[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                values[reader.key] is not None
            )
    field = f"{technology}.ai_weight"
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    if expected == 1:
        assert reference is None
    else:
        assert reference is not None
        assert reference[1] == pytest.approx(expected)
    start = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", start)
    overlay = "\n".join(text[start:end].splitlines()[1:])
    result = pdx_eval.select(overlay, {"ROOT": root})
    assert result.delta == pytest.approx(expected)
    assert pdx_eval.select(overlay, {"ROOT": {**root, "is_ai": False}}).operation is None
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
