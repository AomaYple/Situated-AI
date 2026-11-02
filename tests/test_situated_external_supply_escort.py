"""D8.19：既有次要舰队护送的单压力低档与双压力高档。"""

import re
from dataclasses import replace

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.unit

SOURCE = "common/ai_strategies/00_default_strategy.txt"
VALUE_SOURCE = "common/script_values/sitai_adapter_values.txt"
VALUE_NAME = "sitai_adapter_fleet_supply_weight"
FIELD = "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply"
HIGH = ("structural_wartime_supply_escort", 1.25)
PRICE = ("structural_wartime_supply_price_escort", 1.10)
BALANCE = ("structural_wartime_supply_balance_escort", 1.10)
WITNESSES = [
    ({}, HIGH),
    ({"steamers_price": 0.249}, BALANCE),
    ({"steamers_price": 0.25}, BALANCE),
    ({"steamers_price": 0.251}, HIGH),
    ({"steamers_balance": -0.001}, HIGH),
    ({"steamers_balance": 0}, PRICE),
    ({"steamers_balance": 0.001}, PRICE),
    ({"steamers_price": 0.25, "steamers_balance": 0}, None),
    ({"steamers_price": None}, None),
    ({"steamers_balance": None}, None),
    ({"steamers_price": float("nan")}, None),
    ({"steamers_balance": float("inf")}, None),
    ({"steamers_price": True}, None),
    ({"war": False}, None),
    ({"war": None}, None),
    ({"navy": 0}, None),
    ({"navy": -1}, None),
    ({"navy": None}, None),
    ({"default": True}, HIGH),
    ({"default": True, "steamers_balance": 0}, PRICE),
    ({"default": True, "steamers_price": 0.25}, BALANCE),
]


def _values(**changes):
    return {"war": True, "navy": 1, "steamers_price": 0.3, "steamers_balance": -1, **changes}


@pytest.fixture(scope="module")
def escort_adapters():
    adapters = decision_adapters.load()
    policy = dict(adapters.policies)[SOURCE]
    rules = tuple(rule for rule in policy.rules if ".".join(rule.field) == FIELD)
    policy = replace(policy, rules=rules, enabled_domains=frozenset({"military"}), semantic_ir=())
    return replace(
        adapters,
        policies=((SOURCE, policy),),
        initial_values=(),
        supply=None,
        scalar_values=tuple(
            row for row in adapters.scalar_values if row[0] == SOURCE and ".".join(row[1]) == FIELD
        ),
    )


@pytest.mark.parametrize(("changes", "expected"), WITNESSES)
def test_existing_fleet_protection_has_handwritten_pressure_tiers(
    escort_adapters, changes, expected
):
    policy = dict(escort_adapters.policies)[SOURCE]
    result = decision_rules.evaluate(policy, _values(**changes), is_ai=True)
    assert result.get(FIELD) == expected


@pytest.fixture(scope="module")
def escort_generated(escort_adapters):
    model = compiler.load_model()
    assert model.consumer_ir is not None
    compiled = tuple(
        (source, compiler.compile_policy(policy, source, model)[0])
        for source, policy in escort_adapters.policies
    )
    escort_adapters = replace(escort_adapters, policies=compiled)
    inputs = decision_adapters.read_inputs(escort_adapters)
    files, _ = decision_adapters.build(
        escort_adapters,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    script = files[VALUE_SOURCE]
    begin = script.index(f"# SITAI BEGIN information:{FIELD}")
    end = script.index(f"# SITAI END information:{FIELD}", begin)
    lines: list[str] = []
    for line in script[begin:end].splitlines()[1:]:
        if line.lstrip().startswith(("if =", "else_if =")) and (
            not lines or not lines[-1].lstrip().startswith("# ")
        ):
            lines.append("# escort_unknown_guard [military]; preserve native value")
        lines.append(line)
    return inputs, files, "\n".join(lines)


def _facts(values, *, is_ai=True, root_exists=True, market_exists=True):
    country = {
        "is_ai": is_ai,
        "is_at_war": values["war"],
        "navy_size": values["navy"],
        "market": {
            "mg:steamers": {
                "market_goods_pricier": values["steamers_price"],
                "market_goods_delta": values["steamers_balance"],
            }
        }
        if market_exists
        else None,
    }
    return {"ROOT": country if root_exists else None}


@pytest.mark.integration
@pytest.mark.parametrize(("changes", "expected"), WITNESSES)
def test_generated_fleet_pdx_keeps_complete_scopes_and_local_unknown(
    escort_generated, changes, expected
):
    _, _, overlay = escort_generated
    actual = pdx_eval.select(overlay, _facts(_values(**changes)))
    if expected is None:
        assert actual.fallback in {"vanilla", "unknown"} or (
            actual.action_id == "escort_unknown_guard" and actual.delta == 1
        )
    else:
        assert (actual.action_id, actual.delta) == expected
        assert actual.operation == "multiply"
    factor = actual.delta if actual.operation == "multiply" else 1
    assert factor == pytest.approx(expected[1] if expected else 1)
    assert 0 * factor == 0


def _at(text, path):
    block: Block | Scalar = parse_text(text).root
    parts = path.split(".")
    for index, key in enumerate(parts):
        assert isinstance(block, Block)
        item = block.first(key)
        assert item is not None
        assert item.value is not None
        block = item.value
        if index < len(parts) - 1:
            assert isinstance(block, Block)
    return block


def _tree(node):
    if isinstance(node, Block):
        return [(item.key, item.op, _tree(item.value)) for item in node.assignments()]
    return node.unquoted


@pytest.mark.integration
def test_fleet_native_roles_qualification_zero_and_disabled_paths_are_preserved(
    escort_adapters, escort_generated
):
    inputs, files, overlay = escort_generated
    native = inputs[SOURCE]
    generated = files[SOURCE]
    fleet = "ai_strategy_default.fleet_compositions"
    assert _tree(_at(native, f"{fleet}.main_battle_fleet")) == _tree(
        _at(generated, f"{fleet}.main_battle_fleet")
    )
    assert (
        _at(native, f"{fleet}.main_battle_fleet.mission_type_weights.protect_supply").unquoted
        == "0.0"
    )
    assert _at(native, FIELD).unquoted == "1.0"
    assert _at(generated, FIELD).unquoted == VALUE_NAME
    assert _at(files[VALUE_SOURCE], VALUE_NAME).first("value").value.unquoted == "1.0"
    # Restore the named scalar in a test copy: every native role, other mission
    # weight, potential and num_fleets_wanted must then match the locked source.
    restored = generated.replace(f"protect_supply = {VALUE_NAME}", "protect_supply = 1.0")
    assert _tree(_at(restored, fleet)) == _tree(_at(native, fleet))
    assert not re.search(
        r"\b(?:set_variable|change_variable|remove_variable)\b", files[VALUE_SOURCE]
    )
    disabled, _ = decision_adapters.build(
        escort_adapters, texts=inputs, enabled_domains=frozenset()
    )
    assert disabled == {}
    policy = dict(escort_adapters.policies)[SOURCE]
    assert decision_rules.evaluate(policy, _values(), is_ai=False) == {}
    for context in ({"is_ai": False}, {"root_exists": False}, {"market_exists": False}):
        actual = pdx_eval.select(overlay, _facts(_values(), **context))
        assert actual.fallback in {"vanilla", "unknown"} or (
            actual.action_id == "escort_unknown_guard" and actual.delta == 1
        )
