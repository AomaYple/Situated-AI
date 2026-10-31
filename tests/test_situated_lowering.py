"""K5 独立 IR/PDX 见证合同。"""

import pytest

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


def test_ir_is_stable_and_complete_for_all_production_rules():
    items = ir.from_rules(_all_rules())
    assert len(items) == 1401
    assert len({item.action_id for item in items}) == 1401
    assert all(item.vanilla_tail for item in items)


@pytest.mark.integration
def test_generated_production_text_is_independently_parseable():
    info = decision_rules.load()
    adapters = decision_adapters.load()
    country_policy = country_state.load()
    generated = {
        name: text
        for name, text in decisions.build(
            information_rules=info,
            consumer_adapters=adapters,
            country_policy=country_policy,
            extensions=decisions.load_extensions(profile="release"),
        ).items()
        if name.endswith(".txt")
    }
    witness = lowering.witnesses(generated)
    assert witness
    assert not lowering.mismatches(ir.from_rules(_all_rules()), generated)


@pytest.mark.integration
def test_generated_action_blocks_have_independent_ast_shape():
    generated = {
        name: text
        for name, text in decisions.build(
            information_rules=decision_rules.load(),
            consumer_adapters=decision_adapters.load(),
            country_policy=country_state.load(),
            extensions=decisions.load_extensions(profile="release"),
        ).items()
        if name.endswith(".txt")
    }
    witnesses = lowering.ast_witnesses(generated)
    assert witnesses
    assert lowering.ast_mismatches(generated) == ()
    assert all(item.parsed and item.has_limit and item.has_write for item in witnesses)
