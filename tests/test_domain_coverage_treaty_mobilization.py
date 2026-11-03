"""Exact native report joins for frozen treaty proposals and medical formations."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from pdx import decision_adapters, mobilization_opportunities, treaty_opportunities
from pdx.model import Block
from pdx.parser import parse_bytes
from pdx.situated import compiler, domain_coverage, vanilla_inventory
from pdx.situated.decision_ir import ContextBinding, EvaluationContext

pytestmark = pytest.mark.unit
MEDICAL = "common/mobilization_options/00_mobilization_option.txt"


@pytest.fixture(scope="module")
def production():
    model = compiler.load_model()
    policies = dict(decision_adapters.load().policies)
    inputs = {}
    for module in (mobilization_opportunities, treaty_opportunities):
        baseline = module.load_baseline()
        for source, row in baseline["originals"].items():
            inputs[source] = bytes.fromhex(row["bytes"])
    instances = tuple(
        item
        for item in model.action_instances
        if item.source == MEDICAL or item.source.startswith("common/treaty_articles/")
    )
    identities = {(item.source, *item.consumer_field.split(".", 1)) for item in instances}
    surfaces = []
    for source, definition, field in sorted(identities):
        parsed = parse_bytes(inputs[source], path=source)
        assert not parsed.errors
        node = parsed.root.first(definition)
        assert node is not None
        leaf = node.value
        assignment = None
        for part in field.split("."):
            assert isinstance(leaf, Block)
            assignment = leaf.first(part)
            assert assignment is not None
            leaf = assignment.value
        assert assignment is not None
        scope = vanilla_inventory._scope(
            source.split("/")[-2], tuple(field.split(".")), inputs, {}, node, source
        )
        surfaces.append(
            vanilla_inventory._surface(source, definition, field, assignment.line, scope)
        )
    inventory = vanilla_inventory.VanillaInventory(
        baseline_id="independent_frozen_source_numeric_bindings",
        source_hashes={source: hashlib.sha256(raw).hexdigest() for source, raw in inputs.items()},
        scope_hash="a" * 64,
        surfaces=tuple(surfaces),
        scanned_directories=("mobilization_options", "treaty_articles"),
        content_roots=("frozen_originals",),
        parsed_files=len(inputs),
    )
    return inventory, instances, inputs, policies, model.action_instances


def test_real_bindings_close_only_reviewed_frozen_native_declarations(production):
    inventory, instances, inputs, policies, _ = production
    assert len(instances) == 93
    assert len(inventory.surfaces) == 22
    report = domain_coverage.native_coverage(
        inventory, instances, native_sources=inputs, production_policies=policies
    )
    assert report["binding_issue_count"] == 0
    assert report["counts"]["actual_covered"] == 22
    assert sum(len(row["covered_actions"]) for row in report["rows"]) == 93
    assert report["denominator"] == 22
    assert report["inventory_status_counts"] == {"pending": 22}


@pytest.mark.parametrize("family", ["medical", "treaty"])
@pytest.mark.parametrize(
    "damage",
    [
        "add",
        "actor",
        "target",
        "owner",
        "tail",
        "value",
        "facts",
        "context",
        "definition",
        "source",
        "field",
        "policy_actor",
        "policy_root",
        "policy_rule",
    ],
)
def test_exact_instances_cannot_borrow_frozen_numeric_or_country_owner_permissions(
    production, family, damage
):
    inventory, instances, inputs, policies, _ = production
    instance = next(item for item in instances if (item.source == MEDICAL) == (family == "medical"))
    definition, leaf = instance.consumer_field.split(".", 1)
    surface = next(
        row
        for row in inventory.surfaces
        if (row.source, row.definition, row.field) == (instance.source, definition, leaf)
    )
    inventory = replace(inventory, surfaces=(surface,))
    policies = dict(policies)
    if damage == "add":
        instance = replace(instance, operation="add")
    elif damage == "actor":
        instance = replace(instance, actor_scope="root" if family == "medical" else "owner")
    elif damage == "target":
        instance = replace(instance, target_scope="target_or_none")
    elif damage == "owner":
        instance = replace(instance, owner="information_rules")
    elif damage == "tail":
        instance = replace(instance, vanilla_tail="retained")
    elif damage == "value":
        instance = replace(instance, value=instance.value + 0.01)
    elif damage == "facts":
        instance = replace(instance, condition_facts=())
    elif damage == "context":
        fake = EvaluationContext(
            actor_scope=ContextBinding("root", "country", "actor", "fake", 1), evidence=("fake:1",)
        )
        instance = replace(instance, evaluation_context=fake)
    elif damage == "definition":
        instance = replace(instance, consumer_field=f"unreviewed_candidate.{leaf}")
    elif damage == "source":
        instance = replace(instance, source="common/treaty_articles/unreviewed_source.txt")
    elif damage == "field":
        instance = replace(instance, consumer_field=f"{definition}.ai.evaluation_chance")
    else:
        policy = policies[instance.source]
        if damage == "policy_actor":
            policy = replace(policy, actor_path=() if family == "medical" else ("owner",))
        elif damage == "policy_root":
            policy = replace(policy, native_root="state")
        else:
            policy = replace(
                policy,
                rules=tuple(
                    replace(rule, operation="add") if rule.id == instance.rule_id else rule
                    for rule in policy.rules
                ),
            )
        policies[instance.source] = policy
    report = domain_coverage.native_coverage(
        inventory, (instance,), native_sources=inputs, production_policies=policies
    )
    assert report["counts"]["actual_covered"] == 0
    assert report["binding_issue_count"] or report["unmatched_production"]


@pytest.mark.parametrize("family", ["medical", "treaty"])
@pytest.mark.parametrize(
    "damage", ["operation", "actor", "target", "line", "evidence", "capability"]
)
def test_native_surface_must_retain_exact_frozen_field_contract(production, family, damage):
    inventory, instances, inputs, policies, _ = production
    instance = next(item for item in instances if (item.source == MEDICAL) == (family == "medical"))
    definition, leaf = instance.consumer_field.split(".", 1)
    surface = next(
        row
        for row in inventory.surfaces
        if (row.source, row.definition, row.field) == (instance.source, definition, leaf)
    )
    updates = {
        "operation": {"operation": "score"},
        "actor": {"actor_scope": "country" if family == "medical" else "military_formation"},
        "target": {"target_scope": "definition_only:candidate"},
        "line": {"source_line": surface.source_line + 1},
        "evidence": {"scope_evidence": ("fake:1",)},
        "capability": {"capability": "indirect"},
    }
    surface = replace(surface, **updates[damage])
    report = domain_coverage.native_coverage(
        replace(inventory, surfaces=(surface,)),
        (instance,),
        native_sources=inputs,
        production_policies=policies,
    )
    assert report["counts"]["actual_covered"] == 0
    assert report["binding_issue_count"] == 1


@pytest.mark.parametrize(
    "damage", ["missing_sources", "missing_policy", "raw_drift", "raw_and_inventory_drift"]
)
def test_source_and_policy_proof_are_required_even_with_correct_object_labels(production, damage):
    inventory, instances, inputs, policies, _ = production
    inputs, policies = dict(inputs), dict(policies)
    if damage == "missing_sources":
        inputs = {}
    elif damage == "missing_policy":
        policies = {}
    else:
        inputs[MEDICAL] += b"# byte drift\n"
        if damage == "raw_drift":
            with pytest.raises(ValueError, match="字节不一致"):
                domain_coverage.native_coverage(
                    inventory, instances, native_sources=inputs, production_policies=policies
                )
            return
        hashes = dict(inventory.source_hashes)
        hashes[MEDICAL] = hashlib.sha256(inputs[MEDICAL]).hexdigest()
        inventory = replace(inventory, source_hashes=hashes)
    report = domain_coverage.native_coverage(
        inventory, instances, native_sources=inputs, production_policies=policies
    )
    expected = 72 if damage == "raw_and_inventory_drift" else 93
    assert report["binding_issue_count"] == expected


@pytest.mark.parametrize("family", ["medical", "treaty"])
def test_unreviewed_real_candidate_cannot_borrow_neighbor_consumer_permission(production, family):
    inventory, instances, inputs, policies, _ = production
    instance = next(item for item in instances if (item.source == MEDICAL) == (family == "medical"))
    source, definition, leaf = (
        (MEDICAL, "mobilization_option_forced_march", "ai_weight")
        if family == "medical"
        else ("common/treaty_articles/03_ship_transfer.txt", "ship_transfer", "ai.proposal_weight")
    )
    if source not in inputs:
        baseline = treaty_opportunities.load_baseline()
        source = baseline["candidates"][definition]["source"]
    node = parse_bytes(inputs[source], path=source).root.first(definition)
    assert node is not None
    field = node.value
    weight = None
    for part in leaf.split("."):
        assert isinstance(field, Block)
        weight = field.first(part)
        assert weight is not None
        field = weight.value
    assert weight is not None
    scope = vanilla_inventory._scope(
        source.split("/")[-2], tuple(leaf.split(".")), inputs, {}, node, source
    )
    surface = vanilla_inventory._surface(source, definition, leaf, weight.line, scope)
    instance = replace(instance, source=source, consumer_field=f"{definition}.{leaf}")
    report = domain_coverage.native_coverage(
        replace(inventory, surfaces=(surface,)),
        (instance,),
        native_sources=inputs,
        production_policies=policies,
    )
    assert report["counts"]["actual_covered"] == 0
    assert report["binding_issue_count"] == 1


def test_six_colonial_pending_numeric_consumers_remain_rejected(production):
    inventory, _, inputs, policies, all_instances = production
    assert not any(item.consumer_field == "colonial_interest_ratio" for item in all_instances)
    template = next(
        item for item in all_instances if item.source == "mod/decisions/information.toml"
    )
    # Keep the rejection regression after withdrawing the unsafe production
    # writers: merely reintroducing six familiar names must not authorize scope.
    instances = tuple(
        replace(
            template,
            action_id=f"unsafe_colonial_{index}",
            rule_id=f"unsafe_colonial_{index}",
            consumer_field="colonial_interest_ratio",
            target_scope="target_state",
        )
        for index in range(6)
    )
    surface = vanilla_inventory.VanillaSurface(
        surface_id="pending_colonial_interest_ratio",
        source="common/ai_strategies/00_default_strategy.txt",
        definition="ai_strategy_default",
        field="colonial_interest_ratio",
        actor_scope="unknown",
        target_scope="unknown",
        operation="override_value",
        capability="pending",
        status="pending",
        getter=None,
        getter_note="pending native field scope",
        scope_evidence=(),
        responsibility_step="D0.03",
        source_line=1,
    )
    report = domain_coverage.native_coverage(
        replace(inventory, surfaces=(surface,)),
        instances,
        native_sources=inputs,
        production_policies=policies,
    )
    assert report["binding_issue_count"] == 6
    assert report["counts"]["actual_covered"] == 0
    assert report["counts"]["pending"] == 1
    assert set(report["rows"][0]["binding_issues"].values()) == {
        "numeric_consumer_contract_unproven"
    }


def test_common_inventory_uses_exact_pinned_event_corroboration_without_expanding_denominator(
    production,
):
    inventory, instances, inputs, policies, _ = production
    event = "events/tech_events/trench_warfare.txt"
    inputs = {source: raw for source, raw in inputs.items() if source != event}
    hashes = {
        source: digest for source, digest in inventory.source_hashes.items() if source != event
    }
    inventory = replace(inventory, source_hashes=hashes)
    report = domain_coverage.native_coverage(
        inventory, instances, native_sources=inputs, production_policies=policies
    )
    assert report["binding_issue_count"] == 0
    assert report["denominator"] == 22
    assert event not in report["source_hashes"]
    # There is no exemption for missing common/ witnesses or inventoried events.
    for source in (
        "common/on_actions/00_code_on_actions.txt",
        "common/mobilization_options/mobilization_options.md",
    ):
        damaged = {name: raw for name, raw in inputs.items() if name != source}
        rejected = domain_coverage.native_coverage(
            inventory, instances, native_sources=damaged, production_policies=policies
        )
        assert rejected["binding_issue_count"] == 72
    event_inventory = replace(
        inventory,
        source_hashes={
            **inventory.source_hashes,
            event: hashlib.sha256(
                bytes.fromhex(
                    mobilization_opportunities.load_baseline()["originals"][event]["bytes"]
                )
            ).hexdigest(),
        },
    )
    rejected = domain_coverage.native_coverage(
        event_inventory, instances, native_sources=inputs, production_policies=policies
    )
    assert rejected["binding_issue_count"] == 72
