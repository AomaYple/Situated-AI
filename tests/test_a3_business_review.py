"""Native business identities cannot be converted into false completion."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest
from test_situated_native_treatments import _coverage

from pdx import config
from pdx.situated import business_review as business
from pdx.situated.native_treatments import (
    _Dependencies,
    _digest,
    _resolve,
    _Sources,
    native_treatments,
)
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface

pytestmark = pytest.mark.integration


def test_frozen_denominator_and_specific_business_reasons_remain_distinct():
    data = business.load()
    assert len(data["rows"]) + len(data["unresolved_common_ids"]) == 1579
    assert len(data["retained_event_rows"]) + len(data["unresolved_event_option_rows"]) == 4840
    assert all(not group["new_behavior"] for group in data["groups"].values())
    assert data["C1_complete"] is False


@pytest.mark.parametrize(
    "fault", ["omit", "duplicate", "complete", "new_capability", "empty_reason", "missing_parent"]
)
def test_controlled_contract_rejects_omission_and_false_completion(tmp_path, fault):
    data = business.load()
    if fault == "omit":
        data["unresolved_event_option_rows"].pop()
    elif fault == "duplicate":
        data["unresolved_common_ids"][0] = data["rows"][0]["surface_id"]
    elif fault == "complete":
        data["C1_complete"] = True
    elif fault == "new_capability":
        next(iter(data["groups"].values()))["counts_as_new_capability"] = True
    elif fault == "empty_reason":
        next(iter(data["groups"].values()))["reasons"] = [""]
    else:
        data["rows"][0]["parent_context"] = "missing"
    path = tmp_path / "business.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        business.load(path)


@pytest.fixture(scope="module")
def exact_native():
    data = business.load()
    row = next(
        row for row in data["rows"] if row["parent_context"].startswith("common/country_ranks/")
    )
    context = data["parent_contexts"][row["parent_context"]]
    assert context["named_reference_proof_ids"] == []
    data = {
        **data,
        "rows": [row],
        "parent_contexts": {row["parent_context"]: context},
        "retained_event_rows": [],
    }
    source = context["source"]
    raw = (config.GAME / source).read_bytes()
    surface = VanillaSurface(
        surface_id=row["surface_id"],
        source=source,
        definition=context["definition"],
        field=row["field"],
        actor_scope="unknown",
        target_scope="unknown",
        operation="value",
        capability="pending",
        status="pending",
        getter=None,
        getter_note="not a runtime getter",
        scope_evidence=(),
        responsibility_step="S4",
        source_line=row["source_line"],
        declaration_occurrence=row["declaration_occurrence"],
    )
    inventory = VanillaInventory(
        baseline_id=data["baseline_id"],
        source_hashes={source: hashlib.sha256(raw).hexdigest()},
        scope_hash=data["common_scope_hash"],
        surfaces=(surface,),
        scanned_directories=("country_ranks",),
        content_roots=("common",),
        parsed_files=1,
    )
    return data, inventory, {source: raw}, source


def test_whole_source_protection_is_required_besides_frozen_native_identity(exact_native):
    data, inventory, sources, source = exact_native
    for complete in (False, True):
        treatment = native_treatments(inventory, sources, {}, production_complete=complete)
        result = business.review(inventory, sources, {}, treatment, data=data)
        assert result["C1_complete"] is False
        assert result["business_complete"] is False
        assert result["common_review_rows"][0]["disposition"] == (
            "retained_exact_native_policy" if complete else "production_protection_unproven"
        )
    changed = {source: sources[source] + b"\nunknown_new_definition = { value = 10 }\n"}
    treatment = native_treatments(inventory, sources, changed, production_complete=True)
    result = business.review(inventory, sources, changed, treatment, data=data)
    assert result["common_review_rows"][0]["disposition"] == "production_protection_unproven"
    assert result["unresolved_common_ids"] == data["unresolved_common_ids"]


@pytest.mark.parametrize("fault", ["source", "parent", "field", "identity", "line", "missing"])
def test_actual_physical_source_parent_and_field_identity_cannot_be_bypassed(exact_native, fault):
    original, inventory, native, source = exact_native
    data, native = copy.deepcopy(original), dict(native)
    if fault == "source":
        native[source] += b"\n# drift\n"
    elif fault == "parent":
        next(iter(data["parent_contexts"].values()))["parent_ast_sha256"] = "0" * 64
    elif fault == "field":
        data["rows"][0]["field_ast_sha256"] = "0" * 64
    elif fault == "identity":
        inventory = replace(
            inventory, surfaces=(replace(inventory.surfaces[0], definition="foreign"),)
        )
    elif fault == "line":
        data["rows"][0]["source_line"] += 1
    else:
        native = {}
    treatment = {"rows": [], "production_manifest_complete_asserted": True}
    with pytest.raises(ValueError):
        business.review(inventory, native, {}, treatment, data=data)


@pytest.fixture
def native_opaque_reference(exact_native):
    original, inventory, sources, _source = exact_native
    data, sources = copy.deepcopy(original), dict(sources)
    dependency = "common/script_values/a3_business_review_test.txt"
    sources[dependency] = b"native_policy = { value = 1 add = unknown_native_operand }\n"
    inventory = replace(
        inventory,
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
    )
    parsed = _Sources(sources)
    dependencies = _Dependencies(
        parsed,
        parsed,
        sources,
        sources,
        {name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
    )
    caller, state = _resolve(parsed.roots[dependency], "native_policy", "__body__")
    assert state == "found"
    proofs, preserved = dependencies.opaque_proofs(caller, caller, numeric=True, source=dependency)
    assert preserved
    proof = proofs["script_values", "unknown_native_operand"]
    identity = hashlib.sha256(
        json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    data["reference_proofs"] = {identity: proof}
    next(iter(data["parent_contexts"].values()))["named_reference_proof_ids"] = [identity]
    return data, inventory, sources, dependency


def test_native_opaque_operand_is_protected_at_its_caller_without_authorizing_a_getter(
    native_opaque_reference,
):
    data, inventory, sources, dependency = native_opaque_reference
    assert next(iter(data["reference_proofs"].values()))["interface_authorized"] is False
    treatment = native_treatments(inventory, sources, {}, production_complete=True)
    result = business.review(inventory, sources, {}, treatment, data=data)
    assert result["counts"] == {"retained_exact_native_policy": 1}
    assert not result["C1_complete"]
    # The same operand under a different branch is a different inherited use.
    changed = {
        dependency: b"native_policy = { value = 1 if = { limit = { always = yes } add = unknown_native_operand } }\n"
    }
    result = business.review(inventory, sources, changed, treatment, data=data)
    assert result["counts"] == {"production_protection_unproven": 1}


@pytest.mark.parametrize("fault", ["occurrence", "authorization", "caller"])
def test_rehashed_opaque_proof_cannot_forge_occurrences_or_reader_permission(
    native_opaque_reference, fault
):
    data, inventory, sources, _dependency = native_opaque_reference
    proof = next(iter(data["reference_proofs"].values()))
    if fault == "occurrence":
        proof["native_occurrences"] = ["forged/path"]
        proof["occurrences"] = ["forged/path"]
    elif fault == "authorization":
        proof["interface_authorized"] = True
    else:
        proof["native_ast_sha256"] = "0" * 64
    identity = hashlib.sha256(
        json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    data["reference_proofs"] = {identity: proof}
    next(iter(data["parent_contexts"].values()))["named_reference_proof_ids"] = [identity]
    treatment = native_treatments(inventory, sources, {}, production_complete=True)
    with pytest.raises(ValueError, match="不透明"):
        business.review(inventory, sources, {}, treatment, data=data)


@pytest.fixture
def composed_native_container():
    source = "common/ai_strategies/00_default_strategy.txt"
    dependency = "common/script_values/a3_composed_native.txt"
    raw = (
        b"@keep = 2\nai_strategy_default = { wargoal_scores = { "
        b"conquer_state = { value = 10 } other = { value = native_policy } } }\n"
    )
    native = {source: raw, dependency: b"native_policy = { value = 3 }\n"}
    parsed = _Sources(native)
    parent_node, _ = _resolve(parsed.roots[source], "ai_strategy_default", "__body__")
    container, _ = _resolve(parsed.roots[source], "ai_strategy_default", "wargoal_scores")
    assert container is not None
    parent = VanillaSurface(
        surface_id="parent",
        source=source,
        definition="ai_strategy_default",
        field="wargoal_scores",
        actor_scope="unknown",
        target_scope="unknown",
        operation="strategy_score_map",
        capability="pending",
        status="pending",
        getter=None,
        getter_note="container is not a reader",
        scope_evidence=(),
        responsibility_step="D0",
        source_line=container.line,
    )
    child = replace(
        parent,
        surface_id="child",
        field="wargoal_scores.conquer_state",
        actor_scope="country",
        target_scope="none",
        operation="wargoal_multiplier",
        capability="direct",
        scope_evidence=(f"{source}:2",),
    )
    inventory = VanillaInventory(
        "composition",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
        "a" * 64,
        (parent, child),
        ("ai_strategies", "script_values"),
        ("common",),
        2,
    )
    coverage = _coverage(replace(inventory, surfaces=(child,)))
    coverage["denominator"] = 2
    output = {source: raw.replace(b"value = 10", b"value = 11")}
    dependencies = _Dependencies(parsed, parsed, native, native, inventory.source_hashes)
    proofs, valid = dependencies.check(container, container, numeric=False)
    assert valid
    assert len(proofs) == 1
    reference = proofs[0]
    reference_id = hashlib.sha256(
        json.dumps(reference, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    data = {
        "rows": [
            {
                "surface_id": parent.surface_id,
                "field": parent.field,
                "source_line": parent.source_line,
                "declaration_occurrence": parent.declaration_occurrence,
                "field_ast_sha256": _digest(container),
                "parent_context": "parent",
                "business_family": "native_map",
                "reason_index": 0,
            }
        ],
        "parent_contexts": {
            "parent": {
                "source": source,
                "definition": parent.definition,
                "parent_ast_sha256": _digest(parent_node),
                "source_sha256": inventory.source_hashes[source],
                "named_reference_proof_ids": [reference_id],
            }
        },
        "reference_proofs": {reference_id: reference},
        "groups": {"native_map": {"reasons": ["Preserve the ordered map and its native policy."]}},
        "retained_event_rows": [],
        "unresolved_common_ids": ["still-unresolved"],
        "unresolved_event_option_rows": [],
        "limitations": ["static check only"],
    }
    return data, inventory, native, output, coverage, source, dependency


def test_native_parent_composes_proven_children_without_becoming_a_reader(
    composed_native_container,
):
    data, inventory, native, output, coverage, _, _ = composed_native_container
    treatment = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    parent, child = treatment["rows"]
    assert parent["interface"]["known"] is False
    assert parent["interface"]["control_authorized"] is False
    assert child["status"] == "implemented_numeric"
    composition = parent["source_protection"]["structural_composition"]
    assert composition["children"][0]["declaration_id"] == child["declaration_id"]
    assert composition["interface_authorized"] is False
    result = business.review(inventory, native, output, treatment, data=data)
    assert result["counts"] == {"retained_native_structure_with_verified_numeric_children": 1}
    assert result["unresolved_common_ids"] == ["still-unresolved"]
    assert result["C1_complete"] is False
    assert result["common_review_rows"][0]["counts_as_new_capability"] is False


def test_composition_does_not_create_a_parent_parameter_reader_contract(composed_native_container):
    _, inventory, native, output, _, source, _ = composed_native_container
    changed = {
        **native,
        **output,
        source: output[source].replace(
            b"value = 11",
            b"value = 11 if = { limit = { ROOT = { pop_type_percent_country = { pop_type = slaves percent > 0.1 } } } add = 1 }",
        ),
    }
    parsed = _Sources(native)
    effective = _Sources(changed, reuse=parsed)
    dependencies = _Dependencies(
        parsed, effective, native, changed, inventory.source_hashes, production_complete=True
    )
    before, _ = _resolve(parsed.roots[source], "ai_strategy_default", "wargoal_scores")
    after, _ = _resolve(effective.roots[source], "ai_strategy_default", "wargoal_scores")
    assert before is not None
    assert after is not None
    rows, valid = dependencies.parameter_conditions(
        before, after, source, "ai_strategy_default", "wargoal_scores", "unknown"
    )
    assert valid is False
    assert next(iter(rows.values()))["status"] == "unproven_parameter_reader"


@pytest.fixture
def nonfrozen_child_dependency(composed_native_container):
    data, inventory, native, output, coverage, source, _dependency = composed_native_container
    introduced = "common/scripted_triggers/a3_child_only.txt"
    native[introduced] = b"child_only_policy = { always = yes }\n"
    output[introduced] = native[introduced]
    output[source] = output[source].replace(
        b"value = 11", b"value = 11 if = { limit = { child_only_policy = yes } add = 1 }"
    )
    inventory = replace(
        inventory,
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
    )
    coverage["source_hashes"] = inventory.source_hashes
    treatment = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    assert treatment["rows"][1]["status"] == "implemented_numeric"
    assert all(
        proof["definition"] != "child_only_policy" for proof in data["reference_proofs"].values()
    )
    assert any(
        proof["definition"] == "child_only_policy" for proof in treatment["rows"][1]["dependencies"]
    )
    result = business.review(inventory, native, output, treatment, data=data)
    assert result["counts"] == {"retained_native_structure_with_verified_numeric_children": 1}
    return data, inventory, native, output, treatment, source, introduced


@pytest.mark.parametrize(
    "fault",
    [
        "changed",
        "removed",
        "added_owner",
        "native_drift",
        "receipt_source",
        "rehashed_changed",
        "rehashed_removed",
        "rehashed_added_owner",
        "rehashed_same_ast",
        "rehashed_relocated",
    ],
)
def test_composition_rechecks_nonfrozen_child_dependency_in_current_complete_mapping(
    nonfrozen_child_dependency, fault
):
    data, inventory, native, output, treatment, source, introduced = nonfrozen_child_dependency
    unchanged_default = output[source]
    mutation = fault.removeprefix("rehashed_")
    if mutation == "changed":
        output[introduced] = b"child_only_policy = { always = no }\n"
    elif mutation == "removed":
        if fault.startswith("rehashed_"):
            output[introduced] = b"# child-only dependency declaration removed\n"
        else:
            output.pop(introduced)
    elif mutation == "added_owner":
        output["common/scripted_triggers/a3_other_owner.txt"] = native[introduced]
    elif mutation == "same_ast":
        output[introduced] += b"# same AST, changed current source identity\n"
    elif mutation == "relocated":
        output[introduced] = b"# definition now owned by another effective source\n"
        output["common/scripted_triggers/a3_relocated.txt"] = native[introduced]
    elif mutation == "native_drift":
        native[introduced] += b"# changed supplied native identity\n"
    else:
        receipt = next(
            proof
            for proof in treatment["rows"][1]["dependencies"]
            if proof["definition"] == "child_only_policy"
        )
        receipt["effective_source"] = "common/scripted_triggers/foreign.txt"
    if fault.startswith("rehashed_"):
        treatment["production_hashes"] = {
            name: hashlib.sha256(raw).hexdigest() for name, raw in output.items()
        }
    assert output[source] == unchanged_default
    result = business.review(inventory, native, output, treatment, data=data)
    assert result["counts"] == {"production_protection_unproven": 1}


@pytest.mark.parametrize(
    "fault",
    [
        "manifest",
        "source",
        "extra_child",
        "child_proof",
        "missing_child",
        "reference",
        "sibling",
        "variable",
        "order",
    ],
)
def test_composed_parent_rejects_stale_or_incomplete_child_and_source_proofs(
    composed_native_container, fault
):
    data, inventory, native, output, coverage, source, dependency = composed_native_container
    treatment = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    if fault == "manifest":
        treatment["production_manifest_complete_asserted"] = False
    elif fault == "child_proof":
        treatment["rows"][1]["dependencies"].append({"status": "unproven"})
    elif fault == "missing_child":
        treatment["rows"].pop()
    elif fault == "source":
        output[source] += b"\nunknown = {}"
    elif fault == "extra_child":
        output[source] = output[source].replace(
            b"wargoal_scores = {", b"wargoal_scores = { extra = { value = 9 }"
        )
    elif fault == "reference":
        output[dependency] = b"native_policy = { value = 4 }"
    elif fault == "sibling":
        output[source] = output[source].replace(b"value = native_policy", b"value = 9")
    elif fault == "variable":
        output[source] = output[source].replace(b"@keep = 2", b"@keep = 3")
    else:
        output[source] = output[source].replace(
            b"conquer_state = { value = 11 } other = { value = native_policy }",
            b"other = { value = native_policy } conquer_state = { value = 11 }",
        )
    result = business.review(inventory, native, output, treatment, data=data)
    assert result["counts"] == {"production_protection_unproven": 1}
