"""K5 独立 IR/PDX 见证合同。"""

import pytest
from _situated_sources import production_policy_sources

from pdx import country_state, decision_adapters, decision_rules, decisions
from pdx.situated import ir, lowering

pytestmark = pytest.mark.unit


def _all_rules():
    info = decision_rules.load()
    adapters = decision_adapters.load()
    return tuple(
        [("mod/decisions/information.toml", item) for item in info.rules]
        + [(source, item) for source, policy in adapters.policies for item in policy.rules]
    )


def test_joint_variant_witness_decodes_decimal_neutral_without_binary_rounding():
    text = (
        "# ACTION program_example [joint]; consumer\n"
        "if = { limit = { is_ai = yes } multiply = { value = 1\n"
        "# tier [fiscal]; local contribution\n"
        "if = { limit = { in_default = yes } add = -0.18 }\n"
        "min = 0.5 max = 1.5 } }\n"
    )
    (witness,) = lowering.witnesses({"sample.txt": text})
    assert witness.action_id == "tier"
    assert witness.operation == "multiply"
    assert witness.value == 0.82


def test_ir_is_stable_and_complete_for_all_production_rules():
    items = ir.from_rules(_all_rules())
    expected = production_policy_sources().rules
    assert len(items) == len(expected)
    assert len({item.action_id for item in items}) == len(expected)
    assert {(item.source, item.action_id, item.field) for item in items} == expected
    assert all(item.vanilla_tail for item in items)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("multiply = 1.3", ()),
        ("multiply = { value = 1.3 desc = SAMPLE_REASON }", ()),
        ("add = { value = 0.5 min = -1 max = 1 }", ()),
        ("multiply = { desc = SAMPLE_REASON }", ("sample",)),
        ("multiply = { value > 1.3 }", ("sample",)),
        ("if = { limit = { always = yes } multiply = 1.3 }", ()),
        ("if = { limit = { always = no } multiply = 1.3 }", ("sample",)),
        ("if = { limit = { always != yes } multiply = 1.3 }", ("sample",)),
        ("if = { limit = { always = yes is_ai = yes } multiply = 1.3 }", ("sample",)),
        ("if = { limit = { always = yes } multiply = 1.3 else = {} }", ("sample",)),
        ("if = { limit = { always = yes } multiply = 1.3 stray }", ("sample",)),
        ("if = { limit = { always = yes } }", ("sample",)),
        ("limit = { multiply = 1.3 }", ("sample",)),
    ],
)
def test_ast_witness_checks_write_through_exact_unconditional_lowering(body, expected):
    text = (
        "# sample [economy]; local auxiliary proof\nif = { limit = { is_ai = yes } " + body + " }"
    )
    assert lowering.ast_mismatches({"sample.txt": text}) == expected


@pytest.fixture(scope="module")
def generated_texts():
    return {
        name: text
        for name, text in decisions.build(
            information_rules=decision_rules.load(),
            consumer_adapters=decision_adapters.load(),
            country_policy=country_state.load(),
            extensions=decisions.load_extensions(profile="release"),
        ).items()
        if name.endswith(".txt")
    }


@pytest.mark.integration
def test_generated_production_text_is_independently_parseable(generated_texts):
    witness = lowering.witnesses(generated_texts)
    assert witness
    assert not lowering.mismatches(ir.from_rules(_all_rules()), generated_texts)


@pytest.mark.integration
def test_generated_action_blocks_have_independent_ast_shape(generated_texts):
    witnesses = lowering.ast_witnesses(generated_texts)
    assert witnesses
    assert lowering.ast_mismatches(generated_texts) == ()
    assert all(item.parsed and item.has_limit and item.has_write for item in witnesses)
