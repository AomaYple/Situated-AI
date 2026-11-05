"""Exact event consumers cross the real IR, generation and independent scope gates."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_interfaces
from pdx import event_opportunities as event
from pdx.parser import parse_text
from pdx.situated import action_instances, compiler, domain_coverage, vanilla_inventory
from pdx.situated.decision_ir import ConsumerIRBundle, WriterDecisionIR

pytestmark = pytest.mark.integration


def _writer(program):
    return WriterDecisionIR(
        writer_id=program.writer_id,
        kind="event_program",
        source=program.source,
        definition=program.option,
        consumer_id=program.consumer_id,
        field=program.field,
        actor="root",
        target="none",
        operation="add",
        vanilla_tail="preserve",
        owner="event_opportunities",
        event_program=program,
        evaluation_context=program.evaluation_context(),
        reader_context_bindings=program.reader_bindings(),
    )


@pytest.fixture(scope="module")
def production():
    inputs = event.frozen_inputs()
    plans = event.compile_programs()
    adapters = decision_adapters.AdapterSet(
        sources=tuple(sorted(event.load()["sources"].items())),
        policies=(),
        source_sha256="a" * 64,
        event_programs=plans,
    )
    bundle = ConsumerIRBundle(1, (), tuple(_writer(plan) for plan in plans))
    return inputs, adapters, bundle


def test_real_compiler_and_adapter_emit_the_same_frozen_event_instances(production):
    inputs, adapters, _ = production
    configured = decision_adapters.load()
    assert configured.event_programs == adapters.event_programs
    assert configured.event_opportunities_sha256
    assert configured.import_blockade_opportunities_sha256
    model = compiler.load_model()
    assert model.consumer_ir is not None
    programs = decision_adapters._event_programs(configured, model.consumer_ir, enabled=True)
    assert len(programs) == 28
    assert {p.option for p in programs} == set(
        event.OPTIONS
        + event.PLAGUE_OPTIONS
        + event.DISASTER_OPTIONS
        + event.SOL_OPTIONS
        + event.HOKKAIDO_OPTIONS
    )
    writers = [row for row in model.consumer_ir.writers if row.kind == "event_program"]
    assert all(row.event_program is program for row, program in zip(writers, programs, strict=True))
    instances = tuple(row for row in model.action_instances if row.kind == "event_program")
    assert {row.action_id for row in instances} == {program.writer_id for program in programs}
    assert len([row for row in model.production_consumers if row.source == event.SOURCE]) == 2
    expected_bounds = {
        **{
            f"event_option:{option}": (0, -10, 10, 10, "delta_to_explicit_native_aiweight")
            for option in event.OPTIONS
        },
        **{
            f"event_option:{option}": (
                0,
                -34 if option.endswith(".b") else -2,
                4,
                34 if option.endswith(".b") else 4,
                "delta_to_explicit_native_aiweight",
            )
            for option in event.HOKKAIDO_OPTIONS
        },
        **{
            f"event_option:{option}": (
                50,
                0,
                100,
                100,
                "absolute_new_aiweight_native_default_unknown",
            )
            for option in event.PLAGUE_OPTIONS + event.DISASTER_OPTIONS
        },
        **{
            f"event_option:{option}": (
                50,
                12,
                88,
                88,
                "absolute_new_aiweight_native_default_unknown",
            )
            for option in event.SOL_OPTIONS
        },
    }
    actual_bounds = {
        row.id: (
            row.scalar_neutral,
            row.scalar_lower,
            row.scalar_upper,
            row.max_delta,
            row.numeric_policy,
        )
        for row in model.production_consumers
        if row.id in expected_bounds
    }
    assert actual_bounds == expected_bounds

    assert len([row for row in model.observation_contracts if row[0] == event.SOURCE]) == 3
    domain_contract = model.contract()["domain_coverage"]
    assert isinstance(domain_contract, dict)
    coverage = domain_contract["domains"]["social"]
    event_targets = [row for row in coverage["targets"] if row["source"] == event.SOURCE]
    assert {row["definition"] for row in event_targets} == set(event.OPTIONS)
    bundle = replace(
        model.consumer_ir, writers=tuple(writers), chain_bindings=(), chains_bound=False
    )
    generated, metadata = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset({"political"}), consumer_ir=bundle
    )
    assert set(generated) == {
        event.SOURCE,
        event.PLAGUE,
        event.DISASTERS,
        event.SOL,
        event.HOKKAIDO,
    }
    assert generated == event.patch(inputs, consumer_programs=programs)
    assert metadata["event_programs"] == [program.as_dict() for program in programs]
    assert isinstance(metadata["field_owners"], list)
    assert len(metadata["field_owners"]) == 28
    assert action_instances.missing_witnesses(instances, generated) == ()
    assert action_instances.missing_witnesses(instances, {}) == tuple(
        row.action_id for row in instances
    )
    assert all(
        decision_interfaces.event_consumer(program)["world_scans"] == 0 for program in programs
    )
    values = {"average_sol": 7, "opponent_exists": True, "opponent_clout": 0.2}
    assert {
        program.option: program.evaluate(values, is_ai=True)
        for program in programs
        if program.source == event.SOURCE
    } == dict(zip(event.OPTIONS, (-2, -2), strict=True))


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "program", "scope", "selector", "tail", "kind", "reader", "parent"],
)
def test_missing_mutated_or_conflicting_ir_cannot_recompile_an_alternate_author(
    production, mutation
):
    inputs, adapters, bundle = production
    first, second, *remaining = bundle.writers
    rows: tuple[WriterDecisionIR, ...]
    if mutation == "missing":
        rows = (first,)
    elif mutation == "duplicate":
        rows = (first, second, first)
    elif mutation == "program":
        assert first.event_program is not None
        scalar = replace(first.event_program.scalar, neutral=1)
        rows = (replace(first, event_program=replace(first.event_program, scalar=scalar)), second)
    elif mutation == "scope":
        rows = (replace(first, evaluation_context=None), second)
    elif mutation == "selector":
        rows = (replace(first, definition="healthcare_laws.5"), second)
    elif mutation == "tail":
        rows = (replace(first, vanilla_tail="replace"), second)
    elif mutation == "kind":
        rows = (replace(first, kind="rule_action"), second)
    elif mutation == "reader":
        rows = (replace(first, reader_context_bindings=()), second)
    else:
        rows = (
            first,
            second,
            WriterDecisionIR(
                "parent",
                "rule_action",
                event.SOURCE,
                "parent",
                "parent",
                event.EVENT,
                "root",
                "none",
                "add",
                "preserve",
                "event_opportunities",
            ),
        )
    changed = replace(bundle, writers=(*rows, *remaining))
    with pytest.raises(ValueError):
        decision_adapters.build(
            adapters, texts=inputs, enabled_domains=frozenset({"political"}), consumer_ir=changed
        )
    with pytest.raises(ValueError):
        decision_adapters.build(
            adapters, texts=inputs, enabled_domains=frozenset(), consumer_ir=changed
        )


def test_disabled_event_emits_nothing_and_standalone_freezes_the_same_explicit_ir(production):
    inputs, adapters, bundle = production
    generated, metadata = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset(), consumer_ir=bundle
    )
    assert generated == {}
    assert metadata["event_programs"] == []
    assert metadata["field_owners"] == []
    standalone, _ = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset({"political"})
    )
    assert standalone == event.patch(inputs)
    with pytest.raises(ValueError, match="缺失"):
        decision_adapters.build(
            adapters,
            texts=inputs,
            enabled_domains=frozenset({"political"}),
            consumer_ir=ConsumerIRBundle(1, (), ()),
        )
    with pytest.raises(ValueError, match="覆盖"):
        decision_adapters.build(
            adapters,
            texts=inputs,
            enabled_domains=frozenset({"political"}),
            consumer_ir=bundle,
            overlays={event.SOURCE: inputs[event.SOURCE]},
        )


def test_independent_complete_sources_authorize_only_the_current_exact_options(production):
    inputs, _, bundle = production
    raw = {source: text.encode("utf-8") for source, text in inputs.items()}
    surfaces: list[vanilla_inventory.VanillaSurface] = []
    for source in (event.SOURCE, event.PLAGUE, event.DISASTERS, event.SOL, event.HOKKAIDO):
        for definition in parse_text(inputs[source]).top_assignments:
            _, rows = vanilla_inventory._event_candidates(source, definition)
            surfaces.extend(rows)
    proven = vanilla_inventory._proven_event_surfaces(raw, surfaces)
    assert sum(row.legal for row in proven) == 28
    assert sum(row.legal for row in proven if row.source == event.PLAGUE) == 3
    inventory = vanilla_inventory.VanillaInventory(
        "independent_complete_event_context",
        {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
        "a" * 64,
        tuple(proven),
        ("events",),
        ("events",),
        2,
    )
    instances = tuple(
        action_instances.ActionInstance(
            action_id=writer.writer_id,
            kind="event_program",
            source=writer.source,
            rule_id=writer.definition,
            domain="political",
            consumer_field=writer.field,
            operation="add",
            value=0,
            condition_facts=tuple(reader.key for reader in writer.event_program.readers()),
            owner="event_opportunities",
            vanilla_tail="preserve",
            evidence=writer.evaluation_context.evidence,
            evaluation_context=writer.evaluation_context,
        )
        for writer in bundle.writers
    )
    report = domain_coverage.native_coverage(inventory, instances, native_sources=raw)
    assert report["counts"]["actual_covered"] == 28
    assert report["binding_issue_count"] == 0
    assert all(
        row["coverage_status"] == "actual_covered"
        for row in report["rows"]
        if row["source"] == event.PLAGUE and row["definition"] == event.PLAGUE_EVENT
    )
    changed = tuple(replace(row, evaluation_context=None) for row in instances)
    failed = domain_coverage.native_coverage(inventory, changed, native_sources=raw)
    assert failed["counts"]["actual_covered"] == 0
    assert failed["binding_issue_count"] == 28
    assert not any(row.legal for row in vanilla_inventory._proven_event_surfaces({}, surfaces))


def test_legacy_event_inputs_still_authorize_only_legacy_programs(production):
    inputs, _, _ = production
    raw = {name: inputs[name].encode() for name in event.LEGACY_SOURCES}
    candidates: list[vanilla_inventory.VanillaSurface] = []
    for source in (event.SOURCE, event.PLAGUE, event.DISASTERS, event.SOL, event.HOKKAIDO):
        for definition in parse_text(inputs[source]).top_assignments:
            _, rows = vanilla_inventory._event_candidates(source, definition)
            candidates.extend(rows)
    proven = vanilla_inventory._proven_event_surfaces(raw, candidates)
    assert sum(row.legal for row in proven) == 21
    assert not any(row.legal for row in proven if row.source == event.SOL)
    assert not any(row.legal for row in proven if row.source == event.HOKKAIDO)
