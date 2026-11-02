from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_rules
from pdx.situated import compiler, ir, pdx_eval

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


def test_default_strategy_reference_keeps_explicit_consumers_without_old_rule_matches():
    model = compiler.load_model()
    values = {"war": True, "default": False, "no_default": True, "peace": False}
    policy = decision_rules.load()
    assert decision_rules.evaluate(policy, values, is_ai=True) == {}
    result = compiler.evaluate_policy(policy, values, is_ai=True, config_model=model)
    assert result["diplomatic_play_neutrality"] == ("joint_fiscal_neutrality", 6.0)
    assert result["recklessness"] == ("joint_diplomatic_recklessness", -4.0)
    assert compiler.evaluate_policy(policy, values, is_ai=False, config_model=model) == {}


def test_explicit_neutral_owner_does_not_restore_old_writer():
    model = compiler.load_model()
    policy = decision_rules.load()
    values: dict[str, object] = {
        reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers
    }
    values.update(war=True, default=False, no_default=None, peace=False, infamy=30)
    # The old field could have a result, but production suppresses its writer
    # whenever the explicit consumer owns the field, including neutral cases.
    result = compiler.evaluate_policy(policy, values, is_ai=True, config_model=model)
    explicit = compiler.evaluate_actions(model, values, is_ai=True)
    for consumer in model.consumers:
        assert result.get(consumer.field) == explicit.get(consumer.field)


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
    """A local unknown cancels fiscal recovery, while known war still contributes."""

    model = compiler.load_model()
    field = "diplomatic_play_neutrality"
    result = compiler.evaluate_actions(
        model,
        {"default": None, "war": True, "peace": False, "no_default": None},
        is_ai=True,
    )
    assert result[field] == ("joint_fiscal_neutrality", 6.0)
    actual = pdx_eval.select(
        compiler.strategy_overlay(model)[field],
        {"is_ai": True, "in_default": None, "is_at_war": True},
    )
    assert (actual.action_id, actual.operation, actual.fallback) == (
        "joint_fiscal_neutrality",
        "add",
        "selected",
    )
    assert actual.delta == 6.0


def test_reference_action_exit_unknown_keeps_vanilla_boundary() -> None:
    """Unknown exit evidence removes its own card at the public typed boundary."""

    model = compiler.load_model()
    field = "diplomatic_play_neutrality"
    values = {"default": True, "no_default": None, "war": False, "peace": True}
    assert field not in compiler.evaluate_actions(model, values, is_ai=True)
    known = compiler.evaluate_actions(model, {**values, "no_default": False}, is_ai=True)
    assert known[field] == ("joint_fiscal_neutrality", 8.0)
    # The same local unknown must not erase a separately known wartime term.
    wartime = compiler.evaluate_actions(model, {**values, "war": True, "peace": False}, is_ai=True)
    assert wartime[field] == ("joint_fiscal_neutrality", 5.0)


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
