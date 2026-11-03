"""The actual missing-company score path, including native AST preservation."""

import re
from dataclasses import replace
from typing import Any

import pytest

from pdx import company_sectors, country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/company_types/99_basic_companies.txt"


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    model = compiler.load_model()
    policy = compiler.compile_policy(dict(adapters.policies)[SOURCE], SOURCE, model)[0]
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        scalar_values=(),
        initial_values=tuple(i for i in adapters.initial_values if i.source == SOURCE),
    )
    files, contract = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return selected, policy, inputs, files[SOURCE], contract


def tree(node):
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, tree(node.value)
    assert isinstance(node, Block)
    return tuple(tree(i) for i in node.items)


def test_missing_base_score_is_one_and_every_native_definition_survives(production):
    selected, policy, inputs, generated, _contract = production
    before, after = parse_text(inputs[SOURCE]), parse_text(generated)
    assert not before.errors
    assert not after.errors
    expected = {item.field for item in selected.initial_values}
    assert expected == {rule.field for rule in policy.rules}
    assert len(expected) == 26
    # Gold uses observed operating mines, never a fictitious market gold price.
    assert ("company_basic_gold_mining", "ai_weight") in expected
    assert not any(reader.key.startswith("country_goods_gold_") for reader in policy.readers)
    for field in expected:
        before_definition = before.root.first(field[0])
        after_definition = after.root.first(field[0])
        assert before_definition is not None
        assert after_definition is not None
        original = before_definition.value
        actual = after_definition.value
        assert isinstance(original, Block)
        assert isinstance(actual, Block)
        assert not original.all("ai_weight")
        weight = actual.all("ai_weight")
        assert len(weight) == 1
        assert isinstance(weight[0].value, Block)
        base = weight[0].value.first("value")
        assert base is not None
        assert isinstance(base.value, Scalar)
        assert base.value.unquoted == "1"
    stripped = re.sub(
        r"(?ms)^\s*# SITAI BEGIN (information|initialized):[^\n]+\n.*?^\s*# SITAI END (information|initialized):[^\n]+\n",
        "\n",
        generated,
    )
    assert tree(parse_text(stripped).root) == tree(before.root)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1),
        ({"country_goods_clothes_balance": -1}, 1.12),
        ({"country_goods_clothes_balance": -1, "country_goods_clothes_price": 0.5}, 1.2),
        ({"country_goods_clothes_balance": -1, "country_goods_fabric_price": 0.5}, 0.97),
        (
            {
                "country_goods_clothes_balance": -1,
                "country_goods_fabric_price": 0.5,
                "default": True,
            },
            0.77,
        ),
        ({"country_goods_clothes_balance": None, "default": True}, 0.8),
    ],
)
def test_default_textiles_uses_exact_same_joint_program(changes, expected, production):
    _selected, policy, _inputs, text, _contract = production
    values = {reader.key: None for reader in policy.readers}
    values.update(changes)
    root: dict[str, Any] = {"is_ai": True}
    for reader in policy.readers:
        current = root
        for part in reader.path:
            current = current.setdefault(part, {})
        if reader.parameters:
            current.setdefault(reader.engine, {})[tuple(reader.parameters)] = values[reader.key]
        else:
            current[reader.engine] = values[reader.key]
    start = text.index("# SITAI BEGIN information:company_basic_textiles.ai_weight")
    end = text.index("# SITAI END information:company_basic_textiles.ai_weight", start)
    overlay = "\n".join(text[start:end].splitlines()[1:])
    assert pdx_eval.select(overlay, {"ROOT": root}).delta == pytest.approx(expected)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(
        "company_basic_textiles.ai_weight"
    )
    assert (1 if reference is None else reference[1]) == pytest.approx(expected)
    assert pdx_eval.select(overlay, {"ROOT": {**root, "is_ai": False}}).operation is None
    assert (
        pdx_eval.select(overlay, {"ROOT": {"is_ai": True}, "scope:target_country": root}).delta == 1
    )


@pytest.mark.parametrize(
    "existing",
    ["ai_weight = {}", "ai_weight = {value=0}", "ai_weight = {value=-2}", "ai_weight = {value=3}"],
)
def test_initializer_refuses_every_existing_score(existing, production):
    selected, _policy, inputs, _generated, _contract = production
    item = next(i for i in selected.initial_values if i.field[0] == "company_basic_textiles")
    original = inputs[SOURCE]
    definition = parse_text(original).root.first(item.field[0])
    assert definition is not None
    lines = original.splitlines(keepends=True)
    position = sum(len(line) for line in lines[: definition.line])
    changed = original[:position] + "\n" + existing + "\n" + original[position:]
    with pytest.raises(ValueError, match="已经存在"):
        decision_adapters._initialize(changed, [item], inputs, {})


def test_disabled_generation_has_no_initializer_or_company_override(production):
    selected, _policy, inputs, _generated, _contract = production
    files, _ = decision_adapters.build(
        selected, texts=inputs, enabled_domains=frozenset(), country_policy=country_state.load()
    )
    assert files == {}
    assert company_sectors.initialized_fields(company_sectors.load_baseline())
