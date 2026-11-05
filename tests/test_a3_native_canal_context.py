"""Production ROOT bindings and independent native coverage for exact native fields."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import canal_opportunities as canal
from pdx import country_state, decision_adapters, decision_interfaces
from pdx import native_action_opportunities as native
from pdx.model import Block
from pdx.parser import parse_bytes, parse_text
from pdx.situated import compiler, domain_coverage, vanilla_inventory
from pdx.situated.decision_ir import ContextBinding

pytestmark = pytest.mark.integration
SOURCES = {*native.CANDIDATES.values(), canal.SOURCE}


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policies = dict(adapters.policies)
    instances = tuple(item for item in model.action_instances if item.source in SOURCES)
    texts = {**native.load_baseline()["texts"], **canal.frozen_inputs()}
    inputs = {source: text.encode("utf-8") for source, text in texts.items()}
    surfaces = []
    for source, field in sorted({(item.source, item.consumer_field) for item in instances}):
        definition, leaf = field.split(".", 1)
        parsed = parse_bytes(inputs[source], path=source)
        assert not parsed.errors
        declaration = parsed.root.first(definition)
        assert declaration is not None
        current = declaration.value
        weight = None
        for part in leaf.split("."):
            assert isinstance(current, Block)
            weight = current.first(part)
            assert weight is not None
            current = weight.value
        assert weight is not None
        scope = vanilla_inventory._scope(
            source.split("/")[-2], tuple(leaf.split(".")), inputs, {}, declaration, source
        )
        surfaces.append(vanilla_inventory._surface(source, definition, leaf, weight.line, scope))
    inventory = vanilla_inventory.VanillaInventory(
        baseline_id="independent_native_action_canal_complete_sources",
        source_hashes={source: hashlib.sha256(raw).hexdigest() for source, raw in inputs.items()},
        scope_hash="a" * 64,
        surfaces=tuple(surfaces),
        scanned_directories=("diplomatic_actions", "decisions"),
        content_roots=("frozen_complete_sources",),
        parsed_files=len(inputs),
    )
    return adapters, model, policies, instances, inventory, inputs


def test_real_production_context_ir_readers_and_roles(production):
    _, model, policies, instances, _, _ = production
    assert len(instances) == 17
    assert len({(item.source, item.consumer_field) for item in instances}) == 8
    assert model.consumer_ir is not None
    for instance in instances:
        policy = policies[instance.source]
        assert policy.native_root == "country"
        assert not policy.actor_path
        context = instance.evaluation_context
        assert context is not None
        assert context.status == "observed"
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
            "root",
            "country",
            "actor",
        )
        assert not context.targets
        assert not context.auxiliary_scopes
        assert instance.target_scope == "none"
        role = decision_interfaces.consumer(
            tuple(instance.consumer_field.split(".")),
            (),
            source=instance.source,
            native_root="country",
        )
        assert role["writer_unit"] == "multiplier"
        assert role["native_unit"] == (
            "relative_weight" if instance.source == canal.SOURCE else "score"
        )
        assert role["role"] == (
            "vanilla_country_decision_relative_weight"
            if instance.source == canal.SOURCE
            else "vanilla_diplomatic_action_proposal_priority"
        )
        writer = next(
            row
            for row in model.consumer_ir.writers
            if row.source == instance.source and row.writer_id == instance.action_id
        )
        assert writer.evaluation_context == context
        assert writer.reader_context_bindings
        assert all(
            binding[1:] == ("root", "country", "actor")
            for binding in writer.reader_context_bindings
        )


def test_independent_inventory_closes_exact_registered_consumers_only(production):
    _, _, policies, instances, inventory, inputs = production
    report = domain_coverage.native_coverage(
        inventory, instances, native_sources=inputs, production_policies=policies
    )
    assert report["binding_issue_count"] == 0
    assert report["counts"]["actual_covered"] == 8
    assert report["denominator"] == 8
    assert sum(len(row["covered_actions"]) for row in report["rows"]) == 17


def test_actual_adapter_generation_preserves_complete_source_and_joint_numbers(production):
    adapters, model, _, _, _, _ = production
    policies = tuple(
        (source, compiler.compile_policy(policy, source, model)[0])
        for source, policy in adapters.policies
        if source in SOURCES
    )
    selected = replace(
        adapters, policies=policies, supply=None, initial_values=(), scalar_values=()
    )
    inputs = decision_adapters.read_inputs(selected)
    generated, metadata = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    consumers = metadata["consumers"]
    assert isinstance(consumers, list)
    assert len(consumers) == 5
    for source, policy in policies:
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            generated[source],
            flags=re.DOTALL,
        )
        assert _render(parse_text(stripped).root) == _render(parse_text(inputs[source]).root)
        values: dict[str, object] = {
            "liberty": 90,
            "war_defeat": True,
            "default": True,
            "net_surplus": -100,
            "bureaucracy": 999,
        }
        facts = _facts(policy, values)
        for field in policy.groups():
            name = ".".join(field)
            if source == canal.SOURCE:
                base, expected = (10, 6.5) if name in canal.FIELDS else (10, 8)
            elif source == native.CANDIDATES["decrease_payments"]:
                base, expected = 10, 8.5
            elif source == native.CANDIDATES["join_power_bloc"]:
                base, expected = 20, 17
            elif source == native.CANDIDATES["da_knowledge_sharing"]:
                base, expected = 10, 10
            else:
                base, expected = 100, 113
            assert _native_number(base, _overlay(generated[source], name), facts) == pytest.approx(
                expected
            )


@pytest.mark.parametrize("family", ["native", "canal"])
@pytest.mark.parametrize(
    "damage",
    [
        "owner",
        "target",
        "context",
        "evidence",
        "value",
        "operation",
        "policy_root",
        "policy_rule",
        "missing_source",
        "resigned_source",
    ],
)
def test_coverage_cannot_borrow_neighbor_role_or_repin_wrong_source(production, family, damage):
    _, _, policies, instances, inventory, inputs = production
    instance = next(row for row in instances if (row.source == canal.SOURCE) == (family == "canal"))
    source = instance.source
    definition, leaf = instance.consumer_field.split(".", 1)
    surface = next(
        row
        for row in inventory.surfaces
        if (row.source, row.definition, row.field) == (source, definition, leaf)
    )
    inventory = replace(inventory, surfaces=(surface,))
    policies, inputs = dict(policies), dict(inputs)
    if damage == "owner":
        instance = replace(instance, actor_scope="owner")
    elif damage == "target":
        instance = replace(instance, target_scope="target_country")
    elif damage in {"context", "evidence"}:
        context = instance.evaluation_context
        assert context is not None
        context = (
            replace(
                context,
                targets=(ContextBinding("target_country", "country", "target", "fake", 1),),
                evidence=(*context.evidence, "fake:1"),
            )
            if damage == "context"
            else replace(context, evidence=(*context.evidence, "fake:1"))
        )
        instance = replace(instance, evaluation_context=context)
    elif damage == "value":
        instance = replace(instance, value=instance.value + 0.01)
    elif damage == "operation":
        instance = replace(instance, operation="add")
    elif damage == "policy_root":
        policies[source] = replace(policies[source], native_root="state")
    elif damage == "policy_rule":
        policies[source] = replace(
            policies[source],
            rules=tuple(
                replace(row, value=row.value + 0.01) if row.id == instance.rule_id else row
                for row in policies[source].rules
            ),
        )
    else:
        document = canal.HELP if family == "canal" else native.README
        if damage == "missing_source":
            inputs.pop(document)
        else:
            inputs[document] += b"\n# drift"
            inventory = replace(
                inventory,
                source_hashes={
                    **inventory.source_hashes,
                    document: hashlib.sha256(inputs[document]).hexdigest(),
                },
            )
    report = domain_coverage.native_coverage(
        inventory, (instance,), native_sources=inputs, production_policies=policies
    )
    assert report["counts"]["actual_covered"] == 0
    assert report["binding_issue_count"] == 1


@pytest.mark.parametrize("family", ["native", "canal"])
@pytest.mark.parametrize(
    "damage",
    [
        "target_reader",
        "owner_reader",
        "target_context",
        "wrong_field",
        "wrong_source",
        "actor_path",
    ],
)
def test_production_reader_context_rejects_aliases_and_unreviewed_fields(
    production, family, damage
):
    _, _, policies, instances, _, _ = production
    instance = next(row for row in instances if (row.source == canal.SOURCE) == (family == "canal"))
    policy = policies[instance.source]
    rule = next(row for row in policy.rules if row.id == instance.rule_id)
    readers = {row.key: row for row in policy.readers}
    key = rule.conditions[0].fact
    actor_path: tuple[str, ...] = ()
    field, source, context, _unused_actor_path = (
        instance.consumer_field,
        instance.source,
        instance.evaluation_context,
        (),
    )
    assert context is not None
    if damage == "target_reader":
        readers[key] = replace(readers[key], scope="target_country")
    elif damage == "owner_reader":
        readers[key] = replace(readers[key], path=("owner",))
    elif damage == "target_context":
        context = replace(
            context,
            targets=(ContextBinding("target_country", "country", "target", "fake", 1),),
            evidence=(*context.evidence, "fake:1"),
        )
    elif damage == "wrong_field":
        field = (
            field.replace("propose_score", "accept_score")
            if family == "native"
            else "suez_stop_survey_decision.ai_chance"
        )
    elif damage == "wrong_source":
        source = source.rsplit("/", 1)[0] + "/unreviewed.txt"
    else:
        actor_path = ("owner",)
    with pytest.raises(ValueError):
        compiler.validate_context_readers(
            field,
            context,
            readers,
            rule.conditions,
            actor_path=actor_path,
            input_keys=tuple(rule.input_keys()),
            source=source,
            native_root="country",
        )


@pytest.mark.parametrize("family", ["native", "canal"])
@pytest.mark.parametrize("damage", ["field", "source", "root", "actor"])
def test_consumer_interface_does_not_authorize_neighbor_role(production, family, damage):
    _, _, _, instances, _, _ = production
    instance = next(row for row in instances if (row.source == canal.SOURCE) == (family == "canal"))
    actor: tuple[str, ...] = ()
    field, source, root, _unused_actor = (
        tuple(instance.consumer_field.split(".")),
        instance.source,
        "country",
        (),
    )
    if damage == "field":
        field = (*field[:-1], "accept_score")
    elif damage == "source":
        source = source.rsplit("/", 1)[0] + "/unreviewed.txt"
    elif damage == "root":
        root = "state"
    else:
        actor = ("owner",)
    with pytest.raises(ValueError):
        decision_interfaces.consumer(field, actor, source=source, native_root=root)
