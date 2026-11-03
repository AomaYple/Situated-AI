"""D5 ConsumerDecisionIR 的当前登记合同。"""

from typing import cast

import pytest
from _situated_sources import production_policy_sources, production_supply_sources

from pdx.situated.compiler import load_model
from pdx.situated.decision_ir import compile_decisions

pytestmark = pytest.mark.unit


def test_每张行动卡都有资格证据成本回退和原版尾部():
    model = load_model()
    items = compile_decisions(model.actions, model.consumers, model.relations)
    assert len(items) == len(model.actions)
    assert all(item.consumer_id for item in items)
    assert all(item.vanilla_tail for item in items)
    assert all(item.unknown_policy == "vanilla" for item in items)
    assert any(item.core_evidence for item in items)


def test_统一行动行承诺单次限幅():
    model = load_model()
    items = compile_decisions(model.actions, model.consumers, model.relations)
    for item in items:
        assert 0 < item.max_delta <= item.consumer_max_delta
        assert item.operation in {"add", "multiply"}
        assert item.single_clamp is True


def test_统一生产bundle包含全部legacy和显式writer():
    model = load_model()
    assert model.consumer_ir is not None
    bundle = model.consumer_ir
    supply = production_supply_sources().rules
    assert len(bundle.writers) == len(model.action_instances) + len(supply)
    assert {item.kind for item in bundle.writers} == {
        "rule_action",
        "action_card",
        "supply_program",
    }
    assert sum(item.kind == "supply_program" for item in bundle.writers) == len(supply)
    assert {
        (item.source, item.definition, item.field)
        for item in bundle.writers
        if item.kind == "supply_program"
    } == supply
    assert {item.writer_id for item in bundle.writers if item.kind == "supply_program"} == {
        f"supply_{good}" for _source, good, _field in supply
    }
    assert sum(item.kind == "rule_action" for item in bundle.writers) == len(
        production_policy_sources().rules
    )
    assert {
        (item.source, item.definition, item.field)
        for item in bundle.writers
        if item.kind == "rule_action"
    } == production_policy_sources().rules
    assert sum(item.kind == "action_card" for item in bundle.writers) == len(model.actions)
    payload = bundle.as_dict()
    assert payload["legacy_writer_count"] == len(production_policy_sources().rules)
    assert payload["legacy_semantic_count"] == len(production_policy_sources().rules)
    assert payload["action_card_writer_count"] == len(model.actions)
    assert payload["supply_program_writer_count"] == len(supply)
    assert payload["support_program_writer_count"] == 0
    assert len(set(bundle.writer_ids())) == len(bundle.writers)
    assert all(item.vanilla_tail for item in bundle.writers)


def test_统一生产writer具有唯一owner且与实例一致():
    model = load_model()
    assert model.consumer_ir is not None
    instances = {(item.source, item.rule_id): item for item in model.action_instances}
    legacy = [item for item in model.consumer_ir.writers if item.kind == "rule_action"]
    assert len({item.owner for item in legacy}) >= 2
    for item in legacy:
        instance = instances[(item.source, item.definition)]
        assert item.owner == instance.owner
    cards = [item for item in model.consumer_ir.writers if item.kind == "action_card"]
    assert cards
    assert {item.owner for item in cards} == {"situated_kernel"}


def test_legacy_writer绑定与owner逐项反查且每个消费者字段只有一个owner():
    """数量和 marker 之外，必须验证生产 bundle 的身份没有旁路漂移。"""

    model = load_model()
    assert model.consumer_ir is not None
    bundle = model.consumer_ir
    instances = {
        item.action_id: item for item in model.action_instances if item.kind == "rule_action"
    }
    bindings = {(item.source, item.definition): item for item in model.binding_rows}
    writers = tuple(item for item in bundle.writers if item.kind == "rule_action")

    assert len(instances) == len(production_policy_sources().rules)
    assert len(bindings) == len(production_policy_sources().rules)
    assert {
        (item.source, item.rule_id, item.consumer_field) for item in instances.values()
    } == production_policy_sources().rules
    assert {
        (item.source, item.definition, item.field) for item in bindings.values()
    } == production_policy_sources().rules
    assert {(item.source, item.definition) for item in writers} == set(bindings)

    owners: dict[str, str] = {}
    for writer in writers:
        instance = instances[writer.writer_id]
        binding = bindings[(writer.source, writer.definition)]
        assert writer.field == instance.consumer_field == binding.field
        assert writer.operation == instance.operation == binding.operation
        assert writer.actor == instance.actor_scope == binding.actor
        expected_target = (
            "target_state"
            if instance.target_scope == "target_or_none" and binding.target == "target_state"
            else instance.target_scope
        )
        assert writer.target == expected_target == binding.target
        previous = owners.setdefault(writer.field, instance.owner)
        assert previous == instance.owner
        assert instance.owner


def test_legacy_writer携带完整规则语义而不是只有登记身份():
    model = load_model()
    assert model.consumer_ir is not None
    writers = tuple(item for item in model.consumer_ir.writers if item.kind == "rule_action")
    assert len(writers) == len(production_policy_sources().rules)
    assert all(item.legacy is not None for item in writers)
    for writer in writers:
        assert writer.legacy is not None
        assert writer.legacy.action_id == writer.writer_id
        assert writer.legacy.definition == writer.definition
        assert writer.legacy.source == writer.source
        assert writer.legacy.field == writer.field
        assert writer.legacy.operation == writer.operation
        assert writer.legacy.actor == writer.actor
        assert writer.legacy.target == writer.target
        assert writer.legacy.vanilla_tail == writer.vanilla_tail
        assert writer.legacy.predicates == writer.predicates


def test_production_contract_owner_matches_actual_legacy_instances():
    model = load_model()
    production = cast("dict[str, object]", model.contract()["production"])
    fields = cast("list[dict[str, object]]", production["fields"])
    rows = {(row["source"], row["field"]): row for row in fields}
    expected = {
        (item.source, item.consumer_field): item.owner
        for item in model.action_instances
        if item.kind == "rule_action"
    }
    assert set(rows) == set(expected)
    assert {key: rows[key]["owner"] for key in expected} == expected


def test_action_card_instance_matches_consumer_and_writer_contracts():
    model = load_model()
    assert model.consumer_ir is not None
    consumers = {item.id: item for item in model.consumers}
    writers = {item.writer_id: item for item in model.consumer_ir.writers}
    instances = [item for item in model.action_instances if item.kind == "action_card"]
    assert instances
    for instance in instances:
        writer = writers[instance.action_id]
        action = writer.action
        assert action is not None
        consumer = consumers[action.consumer_id]
        assert instance.consumer_field == consumer.field == writer.field == action.field
        assert instance.operation == consumer.operation == writer.operation == action.operation
        assert instance.actor_scope == consumer.scope == writer.actor
        assert instance.vanilla_tail == consumer.vanilla_tail == writer.vanilla_tail
