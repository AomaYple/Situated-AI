from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_rules
from pdx.situated import compiler, ir

pytestmark = pytest.mark.unit


def test_action_ir_roundtrip_preserves_complete_rule():
    policy = decision_rules.load()
    for rule in policy.rules:
        item = ir.from_rule(rule, source="test")
        assert item.to_rule() == rule
        assert item.priority == rule.priority


def test_reference_rejects_missing_legacy_writer():
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy = decision_rules.load()
    model = replace(model, consumer_ir=replace(model.consumer_ir, writers=()))
    with pytest.raises(ValueError, match=r"writer|IR"):
        compiler.evaluate_policy(policy, {}, is_ai=True, config_model=model)


def test_compiler_rejects_duplicate_legacy_writer():
    model = compiler.load_model()
    assert model.consumer_ir is not None
    writer = next(item for item in model.consumer_ir.writers if item.kind == "rule_action")
    model = replace(
        model, consumer_ir=replace(model.consumer_ir, writers=(*model.consumer_ir.writers, writer))
    )
    with pytest.raises(ValueError, match="重复"):
        compiler.compile_policy(decision_rules.load(), config_model=model)


def test_all_bindings_lower_from_complete_ir():
    model = compiler.load_model()
    policies = (
        ("mod/decisions/information.toml", decision_rules.load()),
        *decision_adapters.load().policies,
    )
    count = 0
    for source, policy in policies:
        compiled, _ = compiler.compile_policy(policy, source, model)
        originals = {rule.id: rule for rule in policy.rules}
        assert len(compiled.semantic_ir) == len(originals)
        for item in compiled.semantic_ir:
            assert (
                replace(item, priority=item.origin_priority, origin_priority=None).to_rule()
                == originals[item.action_id]
            )
            count += 1
        assert decision_rules.evaluate(compiled, {}, is_ai=False) == {}
        assert decision_rules.evaluate(compiled, {}, is_ai=True) == {}
    assert count == 1455


def test_reference_action_selection_blocks_lower_candidate_when_higher_core_is_unknown():
    """未知的高优先级核心条件必须保持原版，不能落到低档行动。"""

    model = compiler.load_model()
    consumer = next(item for item in model.consumers if item.id == "fiscal_neutrality")
    actions = [item for item in model.decision_ir if item.consumer_id == consumer.id]
    selected = compiler._select_action(
        actions,
        {
            "default": None,
            "war": True,
            "peace": False,
            "no_default": None,
        },
    )
    assert selected is None


def test_reference_action_exit_unknown_keeps_vanilla_boundary() -> None:
    """未知退出条件与生成的 NOT/OR 门一致，不能落到低档候选。"""

    model = compiler.load_model()
    action = next(item for item in model.decision_ir if item.action_id == "fiscal_recovery")
    selected = compiler._select_action(
        [replace(action, requires_all=("peace",), exit_when=("default",))],
        {"peace": True, "default": None},
    )
    assert selected is None


@pytest.mark.parametrize(
    ("attribute", "value"),
    [("priority", 999999), ("why", "drift"), ("contexts", ("drift",)), ("value", 999.0)],
)
def test_reference_and_lowering_reject_semantic_drift(attribute, value):
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy = decision_rules.load()
    target = policy.rules[0].id
    writers = []
    for writer in model.consumer_ir.writers:
        if writer.definition == target and writer.source == "mod/decisions/information.toml":
            assert writer.legacy is not None
            writers.append(replace(writer, legacy=replace(writer.legacy, **{attribute: value})))
        else:
            writers.append(writer)
    model = replace(model, consumer_ir=replace(model.consumer_ir, writers=tuple(writers)))
    with pytest.raises(ValueError, match="不一致"):
        compiler.compile_policy(policy, config_model=model)
    with pytest.raises(ValueError, match="不一致"):
        compiler.evaluate_policy(policy, {}, is_ai=True, config_model=model)
