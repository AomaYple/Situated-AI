"""Whole Mod production output must satisfy the same exact audit contracts."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace

import pytest

from pdx import config, decision_adapters, distribution, event_opportunities
from pdx.situated import audit, business_review, domain_coverage, vanilla_inventory
from pdx.situated.native_treatments import (
    _Dependencies,
    _event_program_proofs,
    _Sources,
    native_treatments,
)

pytestmark = pytest.mark.integration
SOURCES = {
    "common/decisions/00_decisions.txt",
    "common/mobilization_options/00_mobilization_option.txt",
}


@pytest.fixture(scope="module")
def complete_candidate():
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    output = {name: raw.encode() if isinstance(raw, str) else raw for name, raw in files.items()}
    inventory = vanilla_inventory.discover()
    native = {
        name: (config.GAME / name).read_bytes()
        for name in inventory.source_hashes
        if not name.startswith("@")
    }
    return inventory, native, output


def test_complete_production_event_programs_have_no_unproven_projection(complete_candidate):
    inventory, native, output = complete_candidate
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
    proofs = _event_program_proofs(inventory, dependencies, output)
    assert len(proofs) == len(event_opportunities.compile_programs()) == 23
    assert all(row["interface_authorized"] for row in proofs.values())


@pytest.fixture(scope="module")
def retained_siblings(complete_candidate):
    inventory, native, output = complete_candidate
    inventory = replace(
        inventory,
        surfaces=tuple(surface for surface in inventory.surfaces if surface.source in SOURCES),
    )
    data = business_review.load()
    rows = [
        row
        for row in data["rows"]
        if row["business_family"] == "common_tail_exact_retention"
        and data["parent_contexts"][row["parent_context"]]["source"] in SOURCES
    ]
    assert len(rows) == 4
    data = {
        **data,
        "rows": rows,
        "retained_event_rows": [],
        "parent_contexts": {
            row["parent_context"]: data["parent_contexts"][row["parent_context"]] for row in rows
        },
    }
    model = audit.load_model()
    coverage = domain_coverage.native_coverage(
        inventory,
        model.action_instances,
        explicit_consumers={
            item.action_id: domain_coverage.NativeConsumerBinding(
                "common/ai_strategies/00_default_strategy.txt",
                "ai_strategy_default",
                item.consumer_field,
            )
            for item in model.action_instances
            if item.kind == "action_card"
        },
        native_sources=native,
        production_policies=dict(decision_adapters.load().policies),
        continuous_programs=audit._production_continuous_bindings(output),
    )
    treatment = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    return data, inventory, native, output, treatment


def test_registered_siblings_do_not_invalidate_unchanged_native_choices(retained_siblings):
    data, inventory, native, output, treatment = retained_siblings
    result = business_review.review(inventory, native, output, treatment, data=data)
    assert result["counts"] == {"retained_exact_native_policy": 4}
    assert all(not row["counts_as_new_capability"] for row in result["common_review_rows"])


@pytest.mark.parametrize(
    "fault",
    [
        "unregistered_sibling",
        "fake_child_receipt",
        "native_effect",
        "ir_owner",
        "ir_binding",
        "ir_count",
        "ir_schema",
        "ir_boolean_schema",
    ],
)
def test_retained_siblings_require_current_full_program_and_child_proofs(retained_siblings, fault):
    data, inventory, native, original, receipt = retained_siblings
    output = dict(original)
    receipt = copy.deepcopy(receipt)
    source = "common/decisions/00_decisions.txt"
    if fault == "unregistered_sibling":
        output[source] += b"\nforged_decision = { ai_chance = 100 }\n"
    elif fault == "native_effect":
        output[source] = output[source].replace(b"days = short_modifier_time", b"days = 999")
        assert output[source] != original[source]
    elif fault == "fake_child_receipt":
        child = next(
            row
            for row in receipt["rows"]
            if row["source"] == source and row["status"] == "implemented_numeric"
        )
        child["dependencies"].append(
            {"family": "forged", "definition": "forged", "status": "proven_parameter_reader"}
        )
    else:
        import json

        metadata = json.loads(output[".metadata/metadata.json"])
        bundle = metadata["situated_actions"]["consumer_ir"]
        writer = next(row for row in bundle["writers"] if row["source"] == source)
        if fault == "ir_owner":
            writer["owner"] = "forged"
        elif fault == "ir_binding":
            writer["reader_context_bindings"] = []
        elif fault in {"ir_schema", "ir_boolean_schema"}:
            bundle["schema"] = 999 if fault == "ir_schema" else True
        else:
            bundle["writer_count"] += 1
        output[".metadata/metadata.json"] = json.dumps(metadata).encode()
    receipt["production_hashes"] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in output.items()
    }
    result = business_review.review(inventory, native, output, receipt, data=data)
    selected_ids = {
        row["surface_id"]
        for row in data["rows"]
        if data["parent_contexts"][row["parent_context"]]["source"] == source
    }
    selected = [row for row in result["common_review_rows"] if row["surface_id"] in selected_ids]
    assert len(selected) == 2
    assert all(row["disposition"] == "production_protection_unproven" for row in selected)
