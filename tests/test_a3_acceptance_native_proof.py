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


@pytest.fixture(scope="module")
def exact_acceptance(production):  # noqa: F811
    inputs, adapters, bundle = production
    program = bundle.writers[0].acceptance_program
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
    root = parse_bytes(native[acceptance.SOURCE], path=acceptance.SOURCE).root
    definition = root.first(acceptance.DEFINITION)
    node, state = _resolve(root, acceptance.DEFINITION, "ai.inherent_accept_score")
    assert definition is not None
    assert node is not None
    assert state == "found"
    scope = vanilla_inventory._treaty_scope(
        ("ai", "inherent_accept_score"), native, definition, acceptance.SOURCE
    )
    surface = vanilla_inventory._surface(
        acceptance.SOURCE, acceptance.DEFINITION, "ai.inherent_accept_score", node.line, scope
    )
    inventory = vanilla_inventory.VanillaInventory(
        "exact_supplied_acceptance",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
        "a" * 64,
        (surface,),
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
    instance = action_instances.ActionInstance(
        action_id=program.writer_id,
        kind="acceptance_program",
        source=program.source,
        rule_id=program.definition,
        domain="diplomacy",
        consumer_field=program.field,
        operation="add",
        value=0,
        condition_facts=tuple(reader.key for reader in program.readers()),
        owner="treaty_acceptance_opportunities",
        vanilla_tail="preserve",
        evidence=program.evaluation_context().evidence,
        family_id="diplomacy",
        evaluation_context=program.evaluation_context(),
    )
    coverage = domain_coverage.native_coverage(inventory, (instance,), native_sources=native)
    assert coverage["counts"]["actual_covered"] == 1
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
    result = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    row = result["rows"][0]
    assert row["status"] == "implemented_numeric"
    assert row["issues"] == []
    assert row["source_protection"]["context_closed"] is True
    assert row["source_protection"]["dependencies_closed"] is True
    assert row["interface"]["control_authorized"] is True
    assert row["active_unknown_usage"] is False
    assert row["business_complete"] is False


@pytest.mark.parametrize(
    "fault",
    [
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
    ],
)
def test_acceptance_proof_rejects_changed_identity_context_or_physical_suffix(
    exact_acceptance, fault
):
    inventory, original, generated, coverage = exact_acceptance
    native, output = dict(original), dict(generated)
    metadata = json.loads(output[METADATA])
    bundle = metadata["situated_actions"]["consumer_ir"]
    writer = bundle["writers"][0]
    if fault == "program":
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
        bundle["field_owners"][acceptance.FIELD] = "other"
    elif fault == "extra_writer":
        extra = deepcopy(writer)
        extra.update(writer_id="extra", kind="rule_action", field="no_tariffs.ai")
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
        output["common/treaty_articles/extra.txt"] = output[acceptance.SOURCE]
    else:
        text = output[acceptance.SOURCE].decode()
        overlay = acceptance.render(acceptance.compile_program())
        if fault == "source":
            changed = overlay.replace("scope:source_country", "scope:target_country")
        elif fault == "target":
            changed = overlay.replace("scope:target_country", "scope:source_country")
        elif fault == "input":
            changed = overlay.replace("article.input_market_goods(root)", "article.treaty")
        elif fault == "exists":
            changed = overlay.replace("exists = scope:article", "always = yes", 1)
        elif fault == "duplicate":
            changed = overlay + overlay
        else:
            changed = "add = 3" + overlay
        assert changed != overlay
        output[acceptance.SOURCE] = text.replace(overlay, changed).encode()
    output[METADATA] = json.dumps(metadata).encode()
    assert _proof((inventory, native, output, coverage)) == {}


def test_exact_acceptance_never_masks_an_opaque_native_sibling(exact_acceptance):
    inventory, native, output, coverage = exact_acceptance
    changed = dict(output)
    changed[acceptance.SOURCE] = changed[acceptance.SOURCE].replace(
        b"value = 0.1", b"value = 0.2", 1
    )
    assert changed[acceptance.SOURCE] != output[acceptance.SOURCE]
    result = native_treatments(
        inventory, native, changed, coverage=coverage, production_complete=True
    )
    row = result["rows"][0]
    assert row["source_protection"]["context_closed"] is False
    assert row["interface"]["control_authorized"] is False
    assert row["active_unknown_usage"] is True
