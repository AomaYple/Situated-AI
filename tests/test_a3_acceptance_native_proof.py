"""The exact directed acceptance bridge closes source protection, never gameplay."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_a3_treaty_acceptance_integration import production  # noqa: F401

from pdx import decision_adapters, decision_interfaces
from pdx import treaty_acceptance_opportunities as acceptance
from pdx.parser import parse_bytes
from pdx.situated import action_instances, domain_coverage, vanilla_inventory
from pdx.situated.native_treatments import (
    _acceptance_program_proof,
    _Dependencies,
    _resolve,
    _Sources,
    native_treatments,
)

METADATA = ".metadata/metadata.json"


@pytest.fixture(scope="module", params=("no_tariffs", "military_assistance"))
def exact_acceptance(production, request):  # noqa: F811
    inputs, adapters, bundle = production
    programs = tuple(writer.acceptance_program for writer in bundle.writers)
    assert all(program is not None for program in programs)
    program = next(program for program in programs if program.definition == request.param)
    assert program is not None
    digest = hashlib.sha256(
        acceptance.PARAMETERS.read_bytes()
        + b"\0baseline:"
        + acceptance.FROZEN.read_bytes()
        + b"\0generator:"
        + Path(acceptance.__file__).read_bytes()
    ).hexdigest()
    generated, contract = decision_adapters.build(
        replace(adapters, treaty_acceptance_opportunities_sha256=digest),
        texts=inputs,
        enabled_domains=frozenset({"diplomacy"}),
        consumer_ir=bundle,
    )
    native = {name: text.encode() for name, text in inputs.items()}
    surfaces = []
    for current in sorted(programs, key=lambda current: current is not program):
        root = parse_bytes(native[current.source], path=current.source).root
        definition = root.first(current.definition)
        node, state = _resolve(root, current.definition, "ai.inherent_accept_score")
        assert definition is not None
        assert node is not None
        assert state == "found"
        scope = vanilla_inventory._treaty_scope(
            ("ai", "inherent_accept_score"), native, definition, current.source
        )
        surfaces.append(
            vanilla_inventory._surface(
                current.source, current.definition, "ai.inherent_accept_score", node.line, scope
            )
        )
    inventory = vanilla_inventory.VanillaInventory(
        "exact_supplied_acceptance",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
        "a" * 64,
        tuple(surfaces),
        ("treaty_articles",),
        ("common",),
        1,
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
    output = {name: text.encode() for name, text in generated.items()}
    output[METADATA] = json.dumps(metadata).encode()
    instances = tuple(
        action_instances.ActionInstance(
            action_id=current.writer_id,
            kind="acceptance_program",
            source=current.source,
            rule_id=current.definition,
            domain="diplomacy",
            consumer_field=current.field,
            operation="add",
            value=0,
            condition_facts=tuple(reader.key for reader in current.readers()),
            owner="treaty_acceptance_opportunities",
            vanilla_tail="preserve",
            evidence=current.evaluation_context().evidence,
            family_id="diplomacy",
            evaluation_context=current.evaluation_context(),
        )
        for current in programs
    )
    coverage = domain_coverage.native_coverage(inventory, instances, native_sources=native)
    assert coverage["counts"]["actual_covered"] == 2
    return inventory, native, output, coverage


def _proof(case):
    inventory, native, output, _ = case
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
    return _acceptance_program_proof(inventory.surfaces[0], inventory, dependencies, output)


def test_exact_supplied_acceptance_proves_the_program_and_preserves_the_whole_source(
    exact_acceptance,
):
    proof = _proof(exact_acceptance)
    assert proof["status"] == "proven_generated"
    assert set(proof["native_inputs"]) == acceptance.SOURCES
    inventory, native, output, coverage = exact_acceptance
    metadata = json.loads(output[METADATA])
    selected = next(
        writer
        for writer in metadata["situated_actions"]["consumer_ir"]["writers"]
        if writer["definition"] == inventory.surfaces[0].definition
    )
    canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    assert proof["writer_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert proof["definition"] == selected["writer_id"]
    assert proof["native_source"] == selected["source"]
    result = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    row = next(
        row for row in result["rows"] if row["definition"] == inventory.surfaces[0].definition
    )
    assert row["status"] == "implemented_numeric"
    assert row["issues"] == []
    assert row["source_protection"]["context_closed"] is True
    assert row["source_protection"]["dependencies_closed"] is True
    assert row["interface"]["control_authorized"] is True
    assert row["active_unknown_usage"] is False
    assert row["business_complete"] is False


def test_complete_candidate_proves_both_distinct_writers_independently(exact_acceptance):
    inventory, native, output, coverage = exact_acceptance
    proofs = [
        _proof((replace(inventory, surfaces=(surface,)), native, output, coverage))
        for surface in inventory.surfaces
    ]
    assert {proof["status"] for proof in proofs} == {"proven_generated"}
    assert {proof["definition"] for proof in proofs} == {
        program.writer_id for program in acceptance.compile_programs()
    }
    assert len({proof["writer_sha256"] for proof in proofs}) == 2
    assert len({proof["overlay_sha256"] for proof in proofs}) == 2


@pytest.mark.parametrize(
    "fault",
    [
        "schema",
        "boolean_schema",
        "program",
        "roles",
        "reader",
        "unknown_field",
        "metadata",
        "count",
        "owner",
        "extra_writer",
        "source",
        "target",
        "input",
        "exists",
        "tail",
        "duplicate",
        "missing_native",
        "drift_native",
        "generator",
        "interfaces",
        "physical_source",
        "missing_writer",
        "duplicate_writer",
        "source_hash",
        "other_program",
        "missing_output",
        "wrong_writer_sha",
        "native_source_hash",
    ],
)
def test_acceptance_proof_rejects_changed_identity_context_or_physical_suffix(
    exact_acceptance, fault
):
    inventory, original, generated, coverage = exact_acceptance
    native, output = dict(original), dict(generated)
    metadata = json.loads(output[METADATA])
    bundle = metadata["situated_actions"]["consumer_ir"]
    program = next(
        p for p in acceptance.compile_programs() if p.definition == inventory.surfaces[0].definition
    )
    writer = next(row for row in bundle["writers"] if row["writer_id"] == program.writer_id)
    if fault in {"schema", "boolean_schema"}:
        bundle["schema"] = 999 if fault == "schema" else True
    elif fault == "program":
        writer["acceptance_program"]["actor"] = "source_country"
    elif fault == "roles":
        writer["evaluation_context"]["auxiliary_scopes"][1]["kind"] = "treaty"
    elif fault == "reader":
        writer["reader_context_bindings"] = []
    elif fault == "unknown_field":
        writer["unknown"] = True
    elif fault == "metadata":
        metadata["consumer_adapters"]["acceptance_programs"] = []
    elif fault == "count":
        bundle["acceptance_program_writer_count"] = True
    elif fault == "owner":
        bundle["field_owners"][program.field] = "other"
    elif fault == "extra_writer":
        extra = deepcopy(writer)
        extra.update(writer_id="extra", kind="rule_action", field=f"{program.definition}.ai")
        extra.pop("acceptance_program")
        bundle["writers"].append(extra)
        bundle["writer_count"] += 1
    elif fault == "missing_native":
        native.pop(acceptance.DOC)
    elif fault == "drift_native":
        native[acceptance.DOC] += b"\nchanged"
        inventory = replace(
            inventory,
            source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
        )
    elif fault in {"generator", "interfaces"}:
        key = (
            "consumer_adapters_generator_sha256"
            if fault == "generator"
            else "consumer_interfaces_sha256"
        )
        metadata["source_fingerprint"][key] = "0" * 64
    elif fault == "physical_source":
        output["common/treaty_articles/extra.txt"] = output[program.source]
    elif fault == "missing_writer":
        bundle["writers"].remove(writer)
        bundle["writer_count"] -= 1
        bundle["acceptance_program_writer_count"] -= 1
    elif fault == "duplicate_writer":
        bundle["writers"].append(deepcopy(writer))
        bundle["writer_count"] += 1
        bundle["acceptance_program_writer_count"] += 1
    elif fault == "source_hash":
        metadata["consumer_adapters"]["sources"][program.source] = "0" * 64
    elif fault == "other_program":
        other = next(row for row in bundle["writers"] if row is not writer)
        other["acceptance_program"]["actor"] = "source_country"
    elif fault == "missing_output":
        output.pop(program.source)
    elif fault == "wrong_writer_sha":
        # A copied sibling program must never witness this source's writer.
        other = next(row for row in bundle["writers"] if row is not writer)
        writer["acceptance_program"] = deepcopy(other["acceptance_program"])
    elif fault == "native_source_hash":
        inventory = replace(
            inventory, source_hashes={**inventory.source_hashes, program.source: "0" * 64}
        )
    else:
        text = output[program.source].decode()
        overlay = acceptance.render(program)
        if fault == "source":
            changed = overlay.replace("scope:source_country", "scope:target_country")
        elif fault == "target":
            changed = overlay.replace("scope:target_country", "scope:source_country")
        elif fault == "input":
            changed = (
                overlay.replace("article.input_market_goods(root)", "article.treaty")
                if program.definition == "no_tariffs"
                else overlay.replace("any_scope_treaty", "scope:article.treaty")
            )
        elif fault == "exists":
            changed = overlay.replace("exists = scope:article", "always = yes", 1)
        elif fault == "duplicate":
            changed = overlay + overlay
        else:
            changed = "add = 3" + overlay
        assert changed != overlay
        output[program.source] = text.replace(overlay, changed).encode()
    output[METADATA] = json.dumps(metadata).encode()
    assert _proof((inventory, native, output, coverage)) == {}


def test_exact_acceptance_never_masks_an_opaque_native_sibling(exact_acceptance):
    inventory, native, output, coverage = exact_acceptance
    changed = dict(output)
    source = inventory.surfaces[0].source
    changed[source] = changed[source].replace(b"value = 0.1", b"value = 0.2", 1)
    assert changed[source] != output[source]
    result = native_treatments(
        inventory, native, changed, coverage=coverage, production_complete=True
    )
    row = next(
        row for row in result["rows"] if row["definition"] == inventory.surfaces[0].definition
    )
    assert row["source_protection"]["context_closed"] is False
    assert row["interface"]["control_authorized"] is False
    assert row["active_unknown_usage"] is True


@pytest.mark.parametrize(
    ("source", "old", "new", "inside_score"),
    [
        (
            acceptance.MILITARY_SOURCE,
            b"scope:treaty.binding_period >= 1825",
            b"scope:treaty.binding_period >= 1826",
            True,
        ),
        (
            acceptance.MILITARY_SOURCE,
            b"country_military_goods_cost_mult = 0.10",
            b"country_military_goods_cost_mult = 0.11",
            False,
        ),
        (
            acceptance.MILITARY_SOURCE,
            b"country_military_goods_cost_mult = -0.1",
            b"country_military_goods_cost_mult = -0.2",
            False,
        ),
        (
            acceptance.MILITARY_SOURCE,
            b"maintenance_paid_by = source_country",
            b"maintenance_paid_by = target_country",
            False,
        ),
        (
            acceptance.MILITARY_SOURCE,
            b"army_power_projection > scope:other_country.army_power_projection",
            b"army_power_projection >= scope:other_country.army_power_projection",
            False,
        ),
        (acceptance.MILITARY_SOURCE, b"consequences = freeze", b"consequences = none", False),
        (acceptance.POWER_VALUES, b"military_expenses < 2000", b"military_expenses < 2001", False),
    ],
)
def test_military_whole_native_parent_effects_and_reference_are_protected(
    exact_acceptance, source, old, new, inside_score
):
    inventory, native, output, coverage = exact_acceptance
    military_surface = next(
        surface for surface in inventory.surfaces if surface.definition == "military_assistance"
    )
    changed = dict(output)
    original = changed.get(source, native[source])
    assert old in original
    if source == acceptance.POWER_VALUES:
        prefix, helper = original.split(b"ai_accept_join_request_score_treaties = {", 1)
        assert old in helper
        changed[source] = (
            prefix + b"ai_accept_join_request_score_treaties = {" + helper.replace(old, new, 1)
        )
    else:
        changed[source] = original.replace(old, new, 1)
    if inside_score:
        assert (
            _proof((replace(inventory, surfaces=(military_surface,)), native, changed, coverage))
            == {}
        )
    result = native_treatments(
        inventory, native, changed, coverage=coverage, production_complete=True
    )
    row = next(row for row in result["rows"] if row["definition"] == "military_assistance")
    assert (
        row["source_protection"]["context_closed"] is False
        or row["source_protection"]["dependencies_closed"] is False
    )
    assert row["interface"]["control_authorized"] is False
    assert row["active_unknown_usage"] is True
