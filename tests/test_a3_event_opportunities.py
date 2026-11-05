"""Independent AIWeight AST arithmetic against the exact medical choice."""

import re
from dataclasses import replace

import pytest

from pdx import event_opportunities as event
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def production():
    inputs = event.frozen_inputs()
    return inputs, event.patch(inputs)[event.SOURCE]


def _block(parent, key):
    rows = parent.all(key)
    assert len(rows) == 1
    assert isinstance(rows[0].value, Block)
    return rows[0].value


def _options(text):
    parent = _block(parse_text(text).root, "healthcare_laws.5")
    return {row.value.first("name").value.unquoted: row.value for row in parent.all("option")}


def _aiweight(block, facts):
    base = block.first("base")
    assert base is not None
    assert isinstance(base.value, Scalar)
    value = float(base.value.unquoted)
    for row in block.assignments():
        if row.key == "base":
            continue
        assert row.key == "modifier"
        assert isinstance(row.value, Block)
        trigger = _block(row.value, "trigger")
        amount = row.value.first("add")
        assert amount is not None
        assert isinstance(amount.value, Scalar)
        if pdx_eval.condition(trigger, facts) is True:
            value += float(amount.value.unquoted)
    return value


@pytest.mark.parametrize(
    ("sol", "clout", "exists", "a", "b"),
    [
        (10, 0.1, True, 0, 0),
        (7, 0.1, True, 8, -8),
        (8, 0.1, True, 0, 0),
        (7, 0.2, True, -2, -2),
        (10, 0.2, True, -10, 6),
        (None, 0.3, True, -10, 6),
        (7, None, True, -2, -8),
        (7, None, False, 8, -8),
        (None, None, False, 0, 0),
        (7, True, True, -2, -8),
        (7, -1, True, -2, -8),
        (7, 1.1, True, -2, -8),
        (float("nan"), 0.1, True, 0, 0),
    ],
)
def test_shared_program_and_actual_weight_ast_have_handwritten_tradeoffs(
    production, sol, clout, exists, a, b
):
    native, generated = production
    observed = {"average_sol": sol, "opponent_exists": exists, "opponent_clout": clout}
    reference = event.evaluate(observed, is_ai=True)
    facts = {
        "is_ai": True,
        "average_sol": sol,
        "scope:anti_public_healthcare_ig": {"ig_clout": clout, "ig_approval": -6}
        if exists
        else None,
    }
    before, after = _options(native[event.SOURCE]), _options(generated)
    for name, expected in zip(event.OPTIONS, (a, b), strict=True):
        assert reference[name] == expected
        assert (
            _aiweight(_block(after[name], "ai_chance"), facts)
            - _aiweight(_block(before[name], "ai_chance"), facts)
            == expected
        )


def test_player_switch_and_wrong_entity_do_not_supply_observations(production):
    native, generated = production
    assert event.patch(native, enabled_domains=frozenset()) == {}
    assert event.evaluate({}, is_ai=False) == {}
    assert event.evaluate({}, is_ai=True, enabled_domains=frozenset()) == {}
    before, after = _options(native[event.SOURCE]), _options(generated)
    facts = {
        "is_ai": False,
        "average_sol": 7,
        "scope:anti_public_healthcare_ig": {"ig_clout": 0.4, "ig_approval": -6},
    }
    for name in event.OPTIONS:
        assert _aiweight(_block(after[name], "ai_chance"), facts) == _aiweight(
            _block(before[name], "ai_chance"), facts
        )
    facts = {
        "is_ai": True,
        "scope:anti_public_healthcare_ig": None,
        "scope:interest_group": {"ig_clout": 0.5},
        "other_country": {"average_sol": 1},
    }
    for name in event.OPTIONS:
        assert _aiweight(_block(after[name], "ai_chance"), facts) == _aiweight(
            _block(before[name], "ai_chance"), facts
        )


def test_complete_native_ast_preserved_and_only_one_suffix_per_exact_option(production):
    native, generated = production
    stripped = re.sub(
        r"(?ms)^\s*# SITAI BEGIN event:[^\n]+\n.*?^\s*# SITAI END event:[^\n]+\n", "\n", generated
    )

    def shape(node):
        if isinstance(node, Scalar):
            return node.text
        if isinstance(node, Block):
            return tuple(shape(row) for row in node.items)
        return (node.key, node.op, node.prefix, shape(node.value))

    assert shape(parse_text(stripped).root) == shape(parse_text(native[event.SOURCE]).root)
    assert all(generated.count(f"# SITAI BEGIN event:{name}\n") == 1 for name in event.OPTIONS)
    # Full preservation includes event/cancel/option triggers, default flag,
    # saved IG, original approval penalty, random effects and actual modifiers.


def test_source_drift_and_binding_clamp_are_hard_failures(production):
    native, _ = production
    for source in native:
        with pytest.raises(ValueError, match="来源漂移"):
            event.patch({**native, source: native[source] + "\n# drift"})
    program = event.compile_programs()[0]
    with pytest.raises(ValueError, match="最终限幅"):
        event.render(replace(program, scalar=replace(program.scalar, lower=-1, upper=1)))


def test_catalog_proves_exact_option_and_leaves_plague_default_unknown(production):
    native, _ = production
    catalog = event.consumer_catalog()
    assert set(catalog) == set(
        event.OPTIONS + event.PLAGUE_OPTIONS + event.DISASTER_OPTIONS + event.SOL_OPTIONS
    )
    assert all(row["native_root"] == "country" for row in catalog.values())
    assert all(
        catalog[name]["default_weight"] == "unsupported_not_consumed" for name in event.OPTIONS
    )
    assert all(
        "unknown_not_inferred" in catalog[name]["default_weight"] for name in event.PLAGUE_OPTIONS
    )
    plague = event._options(_block(parse_text(native[event.PLAGUE]).root, "plague.5"))
    assert all(not option.all("ai_chance") for option in plague.values())
