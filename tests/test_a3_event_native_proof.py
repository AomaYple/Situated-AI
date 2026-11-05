"""Exact event program proofs preserve real options and unknown native defaults."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_a3_event_integration import production  # noqa: F401

from pdx import config, decision_adapters, decision_interfaces
from pdx import event_opportunities as event
from pdx.parser import parse_bytes
from pdx.situated import action_instances, compiler, domain_coverage, vanilla_inventory
from pdx.situated.native_treatments import (
    _Dependencies,
    _event_program_proofs,
    _resolve,
    _Sources,
    native_treatments,
)

METADATA = ".metadata/metadata.json"


@pytest.fixture(scope="module")
def exact_events(production):  # noqa: F811
    inputs, adapters, bundle = production
    digest = hashlib.sha256(
        event.PARAMETERS.read_bytes()
        + b"\0baseline:"
        + event.FROZEN.read_bytes()
        + b"\0generator:"
        + Path(event.__file__).read_bytes()
    ).hexdigest()
    files, contract = decision_adapters.build(
        replace(adapters, event_opportunities_sha256=digest),
        texts=inputs,
        enabled_domains=frozenset({"political"}),
        consumer_ir=bundle,
    )
    native = {source: (config.GAME / source).read_bytes() for source in inputs}
    candidates: list[vanilla_inventory.VanillaSurface] = []
    options: list[vanilla_inventory.VanillaEventOption] = []
    for source in (event.SOURCE, event.PLAGUE, event.DISASTERS, event.SOL):
        parsed = parse_bytes(native[source], path=source)
        for parent in parsed.root.assignments():
            discovered, surfaces = vanilla_inventory._event_candidates(source, parent)
            options.extend(discovered)
            candidates.extend(surfaces)
    proven = vanilla_inventory._proven_event_surfaces(native, candidates)
    surfaces = tuple(surface for surface in proven if surface.legal)
    assert len(surfaces) == 23
    inventory = vanilla_inventory.VanillaInventory(
        "exact_supplied_events",
        {source: hashlib.sha256(raw).hexdigest() for source, raw in native.items()},
        "b" * 64,
        surfaces,
        ("events",),
        ("events", "common"),
        len(native),
        event_options=tuple(options),
    )
    metadata = {
        "situated_actions": {"consumer_ir": bundle.as_dict()},
        "consumer_adapters": contract,
        "source_fingerprint": {
            "consumer_adapters_generator_sha256": contract["generator_sha256"],
            "consumer_interfaces_sha256": hashlib.sha256(
                Path(decision_interfaces.__file__).read_bytes()
            ).hexdigest(),
        },
    }
    output = {source: text.encode() for source, text in files.items()}
    output[METADATA] = json.dumps(metadata).encode()
    instances = tuple(
        action_instances.ActionInstance(
            action_id=program.writer_id,
            kind="event_program",
            source=program.source,
            rule_id=program.option,
            domain="political",
            consumer_field=program.field,
            operation="add",
            value=0,
            condition_facts=tuple(reader.key for reader in program.readers()),
            owner="event_opportunities",
            vanilla_tail="preserve",
            evidence=program.evaluation_context().evidence,
            family_id="political",
            evaluation_context=program.evaluation_context(),
        )
        for program in event.compile_programs()
    )
    coverage = domain_coverage.native_coverage(inventory, instances, native_sources=native)
    assert coverage["counts"]["actual_covered"] == 23
    return inventory, native, output, coverage


def _proofs(case, *, complete=True):
    inventory, native, output, _ = case
    before = _Sources(native)
    effective = {**native, **output}
    dependencies = _Dependencies(
        before,
        _Sources(effective, reuse=before),
        native,
        effective,
        inventory.source_hashes,
        production_complete=complete,
    )
    return _event_program_proofs(inventory, dependencies, output)


def test_all_current_real_programs_distinguish_original_and_new_weight_slots(exact_events):
    proofs = _proofs(exact_events)
    assert len(proofs) == 23
    assert sum(proof["native_weight_present"] for proof in proofs.values()) == 2
    assert sum(not proof["native_weight_present"] for proof in proofs.values()) == 21
    assert {proof["policy"] for proof in proofs.values()} == {
        "additive_to_explicit_native_aiweight",
        "new_explicit_ai_policy_native_default_unknown",
    }
    inventory, native, output, coverage = exact_events
    report = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    assert report["counts"]["implemented_numeric"] == 23
    for row in report["rows"]:
        assert row["issues"] == [], row
        assert row["source_protection"]["context_closed"] is True, row
        assert row["source_protection"]["dependencies_closed"] is True, row
        assert row["source_protection"]["proven"] is False
        assert row["interface"]["control_authorized"] is True
        assert row["active_unknown_usage"] is False
        assert row["business_complete"] is False


def test_final_script_whitespace_form_preserves_exact_event_proof(exact_events):
    inventory, native, output, coverage = exact_events
    # This is the actual final production transformation, independently
    # witnessed with line-end padding present in the locked native source.
    final = {
        source: (re.sub(r"(?m)[\t ]+$", "", raw.decode()).rstrip("\n") + "\n").encode()
        if source.endswith(".txt")
        else raw
        for source, raw in output.items()
    }
    assert final[event.SOURCE] != output[event.SOURCE]
    case = inventory, native, final, coverage
    assert len(_proofs(case)) == 23
    # Canonical whitespace does not excuse an additional native definition.
    final[event.SOURCE] += b"\nforged_event = {}\n"
    assert _proofs((inventory, native, final, coverage)) == {}


@pytest.mark.parametrize(
    "fault",
    [
        "scalar",
        "reader",
        "context",
        "unknown_key",
        "count",
        "owner",
        "source_owner",
        "contract",
        "interface",
        "fingerprint",
        "digest",
        "duplicate",
        "extra_writer",
        "native_drift",
        "native_missing",
        "native_hash",
        "unknown_surface",
        "overlay",
        "tail",
        "random",
        "cost",
        "effect",
        "variable",
        "caller",
        "relocated",
        "copy",
        "repeated",
    ],
)
def test_exact_event_proof_rejects_wrong_metadata_inputs_and_original_context(exact_events, fault):
    inventory, original, generated, coverage = exact_events
    native, output = dict(original), dict(generated)
    metadata = json.loads(output[METADATA])
    bundle = metadata["situated_actions"]["consumer_ir"]
    writer = bundle["writers"][0]
    if fault == "scalar":
        writer["event_program"]["scalar"]["neutral"] = 99
    elif fault == "reader":
        writer["event_program"]["readers"] = []
    elif fault == "context":
        writer["reader_context_bindings"] = []
    elif fault == "unknown_key":
        writer["undeclared"] = 1
    elif fault == "count":
        bundle["event_program_writer_count"] = True
    elif fault == "owner":
        bundle["field_owners"][writer["field"]] = "other"
    elif fault == "source_owner":
        bundle["source_field_owners"][f"{writer['source']}:{writer['field']}"] = "other"
    elif fault == "contract":
        metadata["consumer_adapters"]["event_programs"] = []
    elif fault == "interface":
        metadata["consumer_adapters"]["event_consumer_interfaces"] = []
    elif fault == "fingerprint":
        metadata["source_fingerprint"]["consumer_interfaces_sha256"] = "0" * 64
    elif fault == "digest":
        metadata["consumer_adapters"]["event_opportunities_sha256"] = "0" * 64
    elif fault == "duplicate":
        bundle["writers"].append(deepcopy(writer))
        bundle["writer_count"] += 1
    elif fault == "extra_writer":
        extra = deepcopy(writer)
        extra.update(kind="rule_action", writer_id="other", field="unregistered")
        extra.pop("event_program")
        bundle["writers"].append(extra)
        bundle["writer_count"] += 1
    elif fault in {"native_drift", "caller"}:
        source = event.YEARLY if fault == "caller" else event.DISASTERS
        native[source] += b"\n# drift\n"
        inventory = replace(
            inventory,
            source_hashes={
                source: hashlib.sha256(raw).hexdigest() for source, raw in native.items()
            },
        )
    elif fault == "native_missing":
        native.pop(event.YEARLY)
    elif fault == "native_hash":
        inventory = replace(
            inventory, source_hashes={**inventory.source_hashes, event.YEARLY: "0" * 64}
        )
    elif fault == "unknown_surface":
        inventory = replace(inventory, surfaces=inventory.surfaces[:-1])
    else:
        program = next(
            p for p in event.compile_programs() if p.option == "natural_disaster_events.1.b"
        )
        overlay = event.render(program).encode()
        text = output[event.DISASTERS]
        if fault == "copy":
            output["events/forged.txt"] = overlay
        elif fault == "relocated":
            text = text.replace(overlay, b"") + b"\n# relocated\n" + overlay
        elif fault == "repeated":
            text += overlay
        elif fault == "overlay":
            text = text.replace(b"state_population >= 1", b"state_population >= 0", 1)
        elif fault == "tail":
            text += b"\nforged = yes\n"
        elif fault == "random":
            text = text.replace(b"random_scope_state", b"every_scope_state", 1)
        elif fault == "cost":
            text = text.replace(
                b"money_amount_multiplier_medium", b"money_amount_multiplier_small", 1
            )
        elif fault == "effect":
            text = text.replace(b"add_devastation = 20", b"add_devastation = 0", 1)
        else:
            text = text.replace(b"name = natural_disaster_cooldown", b"name = wrong_cooldown", 1)
        output[event.DISASTERS] = text
    output[METADATA] = json.dumps(metadata).encode()
    assert _proofs((inventory, native, output, coverage)) == {}


def test_incomplete_manifest_and_wrong_coverage_never_authorize_event_control(exact_events):
    assert _proofs(exact_events, complete=False) == {}
    inventory, native, output, original = exact_events
    coverage = deepcopy(original)
    coverage["rows"][0]["covered_actions"] = ["forged"]
    report = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    assert any(
        row["interface"]["control_authorized"] is False
        for row in report["rows"]
        if row["declaration_id"] == coverage["rows"][0]["declaration_id"]
    )


def test_physical_selector_preserves_dots_and_never_invents_an_absent_weight():
    source = b"e.1={option={name=e.1.a ai_chance={base=5}} option={name=e.1.b}}"
    root = parse_bytes(source, path="event-test.txt").root
    assert _resolve(root, "e.1", "option[e.1.a].ai_chance")[1] == "found"
    assert _resolve(root, "e.1", "option[e.1.b].ai_chance") == (None, "missing")
    duplicate = parse_bytes(
        source.replace(b"name=e.1.b", b"name=e.1.a"), path="event-test.txt"
    ).root
    assert _resolve(duplicate, "e.1", "option[e.1.a].ai_chance") == (None, "ambiguous")


def test_invalid_whole_program_cannot_fall_back_to_numeric_shape_permission(exact_events):
    inventory, native, original, coverage = exact_events
    output = dict(original)
    metadata = json.loads(output[METADATA])
    metadata["consumer_adapters"]["event_programs"] = []
    output[METADATA] = json.dumps(metadata).encode()
    report = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    assert report["counts"]["implemented_numeric"] == 0
    assert all(not row["interface"]["control_authorized"] for row in report["rows"])
    assert all(row["active_unknown_usage"] for row in report["rows"])


def test_effective_caller_drift_and_stale_mutable_mapping_cannot_reuse_proof(exact_events):
    inventory, native, generated, _ = exact_events
    output = dict(generated)
    before = _Sources(native)
    effective = {**native, **output}
    dependencies = _Dependencies(
        before,
        _Sources(effective, reuse=before),
        native,
        effective,
        inventory.source_hashes,
        production_complete=True,
    )
    assert len(_event_program_proofs(inventory, dependencies, output)) == 23
    output[event.YEARLY] = native[event.YEARLY].replace(
        b"3 = natural_disaster_events.1", b"4 = natural_disaster_events.1", 1
    )
    assert _event_program_proofs(inventory, dependencies, output) == {}
    effective.update(output)
    changed = _Dependencies(
        before,
        _Sources(effective, reuse=before),
        native,
        effective,
        inventory.source_hashes,
        production_complete=True,
    )
    assert _event_program_proofs(inventory, changed, output) == {}


@pytest.fixture(scope="module")
def events_with_actual_health_writer(exact_events):
    inventory, _, _, _ = exact_events
    configured = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(
        dict(configured.policies)[event.HEALTH], event.HEALTH, model
    )
    selected = replace(
        configured,
        policies=((event.HEALTH, policy),),
        supply=None,
        acceptance_programs=(),
        initial_values=tuple(
            row for row in configured.initial_values if row.source == event.HEALTH
        ),
        scalar_values=tuple(row for row in configured.scalar_values if row[0] == event.HEALTH),
    )
    writers = tuple(
        writer
        for writer in model.consumer_ir.writers
        if writer.source == event.HEALTH or writer.kind == "event_program"
    )
    bundle = replace(model.consumer_ir, writers=writers, chain_bindings=(), chains_bound=False)
    inputs = decision_adapters.read_inputs(configured)
    generated, contract = decision_adapters.build(selected, texts=inputs, consumer_ir=bundle)
    native = {source: (config.GAME / source).read_bytes() for source in inputs}
    inventory = replace(
        inventory,
        source_hashes={source: hashlib.sha256(raw).hexdigest() for source, raw in native.items()},
    )
    metadata = {
        "situated_actions": {"consumer_ir": bundle.as_dict()},
        "consumer_adapters": contract,
        "source_fingerprint": {
            "consumer_adapters_generator_sha256": contract["generator_sha256"],
            "consumer_interfaces_sha256": hashlib.sha256(
                Path(decision_interfaces.__file__).read_bytes()
            ).hexdigest(),
        },
    }
    output = {source: text.encode() for source, text in generated.items()}
    output[METADATA] = json.dumps(metadata).encode()
    event_instances = tuple(row for row in model.action_instances if row.kind == "event_program")
    coverage = domain_coverage.native_coverage(inventory, event_instances, native_sources=native)
    return inventory, native, output, coverage


def test_real_health_numeric_writer_preserves_complete_referenced_law(
    events_with_actual_health_writer,
):
    case = events_with_actual_health_writer
    inventory, native, output, coverage = case
    assert output[event.HEALTH] != native[event.HEALTH]
    proofs = _proofs(case)
    assert len(proofs) == 23
    assert all(
        row["referenced_health_source"]["mode"] == "exact_registered_law_numeric_program"
        for row in proofs.values()
    )
    report = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    assert sum(row["interface"]["control_authorized"] for row in report["rows"]) == 23


@pytest.mark.parametrize(
    "fault",
    [
        "effect",
        "qualification",
        "deleted",
        "sibling",
        "numeric",
        "metadata",
        "reader",
        "duplicate_owner",
        "source_drift",
    ],
)
def test_effective_health_changes_outside_the_exact_registered_program_reject(
    events_with_actual_health_writer, fault
):
    inventory, native, generated, coverage = events_with_actual_health_writer
    output = dict(generated)
    raw = output[event.HEALTH]
    metadata = json.loads(output[METADATA])
    if fault == "effect":
        raw = raw.replace(
            b"state_standard_of_living_add = 0.5", b"state_standard_of_living_add = 9.5"
        )
    elif fault == "qualification":
        raw = raw.replace(b"unlocking_technologies", b"forged_technologies", 1)
    elif fault == "deleted":
        raw = b"# removed law definitions\n"
    elif fault == "sibling":
        raw += b"\nforged_law = { progressiveness = 999 }\n"
    elif fault == "numeric":
        raw = raw.replace(b"add =", b"subtract =", 1)
    elif fault in {"metadata", "reader"}:
        writer = next(
            row
            for row in metadata["situated_actions"]["consumer_ir"]["writers"]
            if row["source"] == event.HEALTH
        )
        if fault == "metadata":
            writer["owner"] = "forged"
        else:
            writer["reader_context_bindings"] = []
    elif fault == "duplicate_owner":
        output["common/laws/forged.txt"] = native[event.HEALTH]
    else:
        output["common/laws/moved_health.txt"] = raw
        raw = b"# moved\n"
    if fault not in {"metadata", "reader", "duplicate_owner"}:
        assert raw != output[event.HEALTH]
    output[event.HEALTH] = raw
    output[METADATA] = json.dumps(metadata).encode()
    assert _proofs((inventory, native, output, coverage)) == {}


@pytest.mark.parametrize("kind", ["missing", "duplicate", "parse_failure"])
def test_unresolved_registered_generated_weight_is_active_unknown(exact_events, kind):
    inventory, native, generated, coverage = exact_events
    output = dict(generated)
    program = next(p for p in event.compile_programs() if p.option == "natural_disaster_events.1.b")
    overlay = event.render(program).encode()
    if kind == "missing":
        output[event.DISASTERS] = output[event.DISASTERS].replace(overlay, b"")
    elif kind == "duplicate":
        output[event.DISASTERS] = output[event.DISASTERS].replace(overlay, overlay + overlay)
    else:
        output[event.DISASTERS] += b"\nmalformed = {\n"
    report = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    row = next(
        row
        for row in report["rows"]
        if row["field"] == "option[natural_disaster_events.1.b].ai_chance"
    )
    assert row["interface"]["control_authorized"] is False
    assert row["active_unknown_usage"] is True
    assert "generated_event_program_unproven" in row["issues"]


@pytest.mark.parametrize("removed", [False, True])
def test_independent_review_health_counterexamples_are_rejected(exact_events, removed):
    inventory, native, generated, coverage = exact_events
    raw = (
        b"# removed law definitions\n"
        if removed
        else native[event.HEALTH].replace(
            b"state_standard_of_living_add = 0.5", b"state_standard_of_living_add = 9.5"
        )
    )
    output = {**generated, event.HEALTH: raw}
    assert _proofs((inventory, native, output, coverage)) == {}
    report = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    assert all(not row["interface"]["control_authorized"] for row in report["rows"])
    assert all(row["active_unknown_usage"] for row in report["rows"])
