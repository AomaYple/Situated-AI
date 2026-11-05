"""Exact common dispositions require installed witnesses and current protection."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace

import pytest
from test_a3_event_native_proof import exact_events, production  # noqa: F401

from pdx import config
from pdx.model import Assignment, Block, Scalar
from pdx.situated import business_review as business
from pdx.situated.native_treatments import _resolve, _Sources, native_treatments
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface

pytestmark = pytest.mark.integration
FAMILY = "common_tail_exact_retention"


@pytest.fixture(scope="module")
def retained_common():
    frozen = business.load()
    rows = [row for row in frozen["rows"] if row["business_family"] == FAMILY]
    context_ids = {row["parent_context"] for row in rows}
    data = {
        **frozen,
        "rows": rows,
        "parent_contexts": {key: frozen["parent_contexts"][key] for key in context_ids},
        "retained_event_rows": [],
    }
    sources = {context["source"] for context in data["parent_contexts"].values()}
    sources.update(support["source"] for support in data["business_supports"].values())
    sources.update(proof["native_source"] for proof in data["reference_proofs"].values())
    native = {source: (config.GAME / source).read_bytes() for source in sources}
    surfaces = tuple(
        VanillaSurface(
            row["surface_id"],
            data["parent_contexts"][row["parent_context"]]["source"],
            data["parent_contexts"][row["parent_context"]]["definition"],
            row["field"],
            "unknown",
            "unknown",
            "value",
            "pending",
            "pending",
            None,
            "static native retention grants no reader",
            (),
            "S4",
            row["source_line"],
            declaration_occurrence=row["declaration_occurrence"],
        )
        for row in rows
    )
    inventory = VanillaInventory(
        "common_retention_test",
        {source: hashlib.sha256(raw).hexdigest() for source, raw in native.items()},
        frozen["common_scope_hash"],
        surfaces,
        ("common",),
        ("common", "events"),
        len(native),
    )
    treatment = native_treatments(inventory, native, {}, production_complete=True)
    return data, inventory, native, treatment


def _result(case, *, output=None, treatment=None):
    data, inventory, native, original, *search = case
    return business.review(
        inventory,
        native,
        output or {},
        treatment or original,
        data=data,
        search_sources=search[0] if search else None,
    )


def _mutate(native, source, definition):
    text = native[source].decode("utf-8-sig")
    node, state = _resolve(_Sources({source: native[source]}).roots[source], definition, "__body__")
    assert state == "found"
    leaves = []

    def visit(value):
        if isinstance(value, Assignment):
            if isinstance(value.value, Scalar) and (
                re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value.value.text)
                or value.value.text in {"yes", "no"}
            ):
                leaves.append(value)
            visit(value.value)
        elif isinstance(value, Block):
            for child in value.items:
                visit(child)

    visit(node)
    assert leaves, definition
    leaf = next(
        (
            item
            for item in leaves
            if isinstance(item.value, Scalar) and item.value.text not in {"yes", "no"}
        ),
        leaves[0],
    )
    assert isinstance(leaf.value, Scalar)
    old = leaf.value.text
    new = "no" if old == "yes" else "yes" if old == "no" else str(float(old) + 1)
    lines = text.splitlines(keepends=True)
    pattern = (
        r"("
        + re.escape(leaf.key)
        + r"\s*"
        + re.escape(leaf.op)
        + r"\s*)"
        + re.escape(old)
        + r"(?![\w.])"
    )
    lines[leaf.line - 1], count = re.subn(
        pattern, lambda match: match[1] + new, lines[leaf.line - 1], count=1
    )
    assert count == 1, (source, definition, leaf.key, old)
    return {source: "".join(lines).encode()}


def test_all_exact_dispositions_are_specific_and_do_not_close_the_plan(retained_common):
    data, _, _, _ = retained_common
    result = _result(retained_common)
    assert result["counts"] == {
        "retained_exact_native_policy": 19,
        "production_protection_unproven": 2,
    }
    assert result["C1_complete"] is result["business_complete"] is False
    assert all(row["counts_as_new_capability"] is False for row in result["common_review_rows"])
    assert (
        len({data["groups"][FAMILY]["reasons"][row["reason_index"]] for row in data["rows"]}) == 21
    )
    assert len(data["unresolved_common_ids"]) == 472


@pytest.mark.parametrize("index", range(21))
def test_each_current_qualification_effect_or_weight_change_is_rejected(retained_common, index):
    data, _, native, original = retained_common
    row = data["rows"][index]
    context = data["parent_contexts"][row["parent_context"]]
    output = _mutate(native, context["source"], context["definition"])
    # Rehashing a copied proof cannot certify new current semantics.
    treatment = copy.deepcopy(original)
    treatment["production_hashes"] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in output.items()
    }
    result = _result(retained_common, output=output, treatment=treatment)
    selected = next(r for r in result["common_review_rows"] if r["surface_id"] == row["surface_id"])
    assert selected["disposition"] == "production_protection_unproven"


@pytest.mark.parametrize(
    "definition",
    [
        "modifier_tangena_ordeal",
        "modifier_reclaiming_land",
        "ai_expedition_simulator_start",
        "modifier_large_expedition_cost",
        "modifier_privy_purse_payments",
        "new_delhi_cost_modifier",
        "je_princely_states",
        "plague.5",
        "unit_occupation_mult",
        "character_battle_condition_rapid_advance_mult",
        "character_battle_condition_lost_mult",
        "je_montenegrin_raiding",
        "modifier_montenegrin_disobedience",
        "je_law_imposition",
        "je_british_dictate_law",
        "je_global_test",
        "lands_of_anarchy_harka_mod",
        "je_lands_of_anarchy",
        "je_land_reclamation",
    ],
)
def test_actual_rationale_support_and_saved_callers_are_current(retained_common, definition):
    data, _, native, original = retained_common
    matches = [s for s in data["business_supports"].values() if s["definition"] == definition]
    assert len(matches) == 1
    support = matches[0]
    output = _mutate(native, support["source"], definition)
    treatment = copy.deepcopy(original)
    treatment["production_hashes"] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in output.items()
    }
    result = _result(retained_common, output=output, treatment=treatment)
    assert result["counts"].get("production_protection_unproven", 0) > 0


@pytest.mark.parametrize(
    "fault", ["incomplete", "stale_manifest", "duplicate_owner", "variable", "relocated"]
)
def test_reference_and_full_current_protection_cannot_be_replaced_by_native_identity(
    retained_common, fault
):
    data, _, native, original = retained_common
    output = {}
    treatment = copy.deepcopy(original)
    proof = next(
        p for p in data["reference_proofs"].values() if p["definition"] == "modifier_tangena_ordeal"
    )
    source = proof["native_source"]
    if fault == "incomplete":
        treatment["production_manifest_complete_asserted"] = False
    elif fault == "stale_manifest":
        output["common/static_modifiers/a3_new_source.txt"] = b"other = {}"
    elif fault == "duplicate_owner":
        output["common/static_modifiers/a3_new_source.txt"] = (
            b"modifier_tangena_ordeal = { state_mortality_mult = 0.1 }"
        )
    elif fault == "variable":
        output[source] = b"@a3_fault = 2\n" + native[source]
    else:
        # A same-AST definition in another file must not become a new owner.
        output[source] = native[source].replace(
            b"modifier_tangena_ordeal", b"renamed_tangena_ordeal"
        )
        output["common/static_modifiers/a3_new_source.txt"] = (
            b"modifier_tangena_ordeal = { state_mortality_mult = 0.1 }"
        )
    if fault != "stale_manifest":
        treatment["production_hashes"] = {
            name: hashlib.sha256(raw).hexdigest() for name, raw in output.items()
        }
    result = _result(retained_common, output=output, treatment=treatment)
    selected = next(
        r for r in result["common_review_rows"] if r["surface_id"] == data["rows"][0]["surface_id"]
    )
    assert selected["disposition"] == "production_protection_unproven"


@pytest.mark.parametrize(
    "fault",
    [
        "replace_identity",
        "omit_migration",
        "empty_reason",
        "duplicate_reason",
        "drop_support",
        "new_behavior",
        "drop_reference",
        "drop_caller",
    ],
)
def test_migration_contract_cannot_drop_or_reclassify_obligations(tmp_path, fault):
    data = business.load()
    rows = [row for row in data["rows"] if row["business_family"] == FAMILY]
    if fault == "replace_identity":
        data["unresolved_common_ids"][0] = "a" * 64
    elif fault == "omit_migration":
        rows[0]["business_family"] = "native_specialized_strategy_additive"
    elif fault == "empty_reason":
        data["groups"][FAMILY]["reasons"][0] = ""
    elif fault == "duplicate_reason":
        rows[0]["reason_index"] = rows[1]["reason_index"]
    elif fault == "drop_support":
        rows[0]["business_support_ids"] = []
    elif fault == "drop_reference":
        context = data["parent_contexts"][rows[0]["parent_context"]]
        context["named_reference_proof_ids"] = []
    elif fault == "drop_caller":
        data["business_supports"].pop(
            "common/journal_entries/99_test_global_je.txt::je_global_test"
        )
    else:
        data["groups"][FAMILY]["new_behavior"] = True
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        business.load(path)


@pytest.fixture(scope="module")
def current_plague(retained_common, exact_events):  # noqa: F811
    data, common_inventory, common_native, _ = retained_common
    event_inventory, event_native, output, coverage = exact_events
    native = {**common_native, **event_native}
    inventory = VanillaInventory(
        "common_and_event_retention_test",
        {source: hashlib.sha256(raw).hexdigest() for source, raw in native.items()},
        common_inventory.scope_hash,
        (*common_inventory.surfaces, *event_inventory.surfaces),
        ("common", "events"),
        ("common", "events"),
        len(native),
        event_options=event_inventory.event_options,
    )
    coverage = copy.deepcopy(coverage)
    coverage["source_hashes"] = inventory.source_hashes
    coverage["denominator"] = len(inventory.surfaces)
    treatment = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    return data, inventory, native, output, treatment


def test_scheduler_retention_accepts_the_complete_current_changed_event_program(current_plague):
    data, inventory, native, output, treatment = current_plague
    result = business.review(inventory, native, output, treatment, data=data)
    assert result["counts"] == {
        "retained_exact_native_policy": 19,
        "production_protection_unproven": 2,
    }


@pytest.mark.parametrize("fault", ["event_effect", "metadata", "caller", "health_effect", "owner"])
def test_scheduler_rechecks_complete_event_projection_and_supports(current_plague, fault):
    from pdx import event_opportunities as event

    data, inventory, native, original_output, original = current_plague
    output = dict(original_output)
    treatment = copy.deepcopy(original)
    if fault == "event_effect":
        output.update(_mutate(output, event.PLAGUE, "plague.5"))
    elif fault == "metadata":
        metadata = json.loads(output[".metadata/metadata.json"])
        metadata["situated_actions"]["consumer_ir"]["event_program_writer_count"] = 0
        output[".metadata/metadata.json"] = json.dumps(metadata).encode()
    elif fault == "caller":
        output.update(_mutate(native, event.PLAGUE_DECISION, "spanish_flu_response"))
    elif fault == "health_effect":
        # The complete proof must protect health-law effects as well as readers.
        output.update(_mutate(native, event.HEALTH, "law_charitable_health_system"))
    else:
        output["events/a3_duplicate_plague.txt"] = b"plague.5 = { option = { name = a } }"
    treatment["production_hashes"] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in output.items()
    }
    result = business.review(inventory, native, output, treatment, data=data)
    row = next(r for r in data["rows"] if r["parent_context"].endswith("::spanish_flu_response"))
    selected = next(r for r in result["common_review_rows"] if r["surface_id"] == row["surface_id"])
    assert selected["disposition"] == "production_protection_unproven"


@pytest.mark.parametrize(
    "call",
    [
        "add_journal_entry = { type = je_global_test }",
        "scripted_button = je_global_test_button",
        "scripted_button = je_global_test_button_2",
    ],
)
def test_unreachable_test_je_retention_rejects_new_current_invocations(complete_test_je, call):
    data, _, _, original, _ = complete_test_je
    output = {
        "events/a3_new_test_invocation.txt": (
            "new_invoker = { immediate = { " + call + " } }"
        ).encode()
    }
    treatment = copy.deepcopy(original)
    treatment["production_hashes"] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in output.items()
    }
    result = _result(complete_test_je, output=output, treatment=treatment)
    test_ids = {
        row["surface_id"]
        for row in data["rows"]
        if "::je_global_test_button" in row["parent_context"]
    }
    assert len(test_ids) == 2
    assert all(
        row["disposition"] == "production_protection_unproven"
        for row in result["common_review_rows"]
        if row["surface_id"] in test_ids
    )


@pytest.fixture(scope="module")
def complete_test_je(retained_common):
    """A no-caller claim requires all frozen search bytes, even files without hits."""
    data, inventory, _, _ = retained_common
    selected = [row for row in data["rows"] if "::je_global_test_button" in row["parent_context"]]
    contexts = {row["parent_context"] for row in selected}
    data = {
        **data,
        "rows": selected,
        "parent_contexts": {key: data["parent_contexts"][key] for key in contexts},
    }
    closed = data["business_supports"][
        "common/journal_entries/99_test_global_je.txt::je_global_test"
    ]["closed_invocations"]
    search = business.search_inputs()
    assert {source: hashlib.sha256(raw).hexdigest() for source, raw in search.items()} == closed[
        "source_hashes"
    ]
    declared = closed["scope_evidence"]["inventory_source_hashes"]
    native = {source: search[source] for source in declared}
    ids = {row["surface_id"] for row in selected}
    inventory = replace(
        inventory,
        source_hashes=declared,
        surfaces=tuple(surface for surface in inventory.surfaces if surface.surface_id in ids),
        parsed_files=len(native),
    )
    treatment = native_treatments(inventory, native, {}, production_complete=True)
    return data, inventory, native, treatment, search


def test_complete_native_search_proves_the_two_actual_test_je_retentions(complete_test_je):
    result = _result(complete_test_je)
    assert result["counts"] == {"retained_exact_native_policy": 2}


@pytest.mark.parametrize(
    "fault",
    [
        "declared_caller_omitted",
        "declared_caller_present",
        "frozen_no_hit_source_omitted",
        "frozen_no_hit_source_undeclared",
    ],
)
def test_full_search_rejects_missing_native_bytes_and_incomplete_declared_scope(
    complete_test_je, fault
):
    data, original_inventory, original_native, _, original_search = complete_test_je
    native = dict(original_native)
    search = dict(original_search)
    inventory = original_inventory
    if fault.startswith("declared_caller"):
        source = "events/a3_missing_native_invoker.txt"
        raw = b"new_invoker = { immediate = { add_journal_entry = { type = je_global_test } } }"
        inventory = replace(
            inventory,
            source_hashes={**inventory.source_hashes, source: hashlib.sha256(raw).hexdigest()},
            parsed_files=inventory.parsed_files + 1,
        )
        if fault.endswith("present"):
            native[source] = raw
            search[source] = raw
    else:
        source = "common/country_ranks/00_country_ranks.txt"
        assert source in native
        search.pop(source)
        native.pop(source, None)
        if fault.endswith("undeclared"):
            inventory = replace(
                inventory,
                source_hashes={
                    key: digest for key, digest in inventory.source_hashes.items() if key != source
                },
            )
    treatment = native_treatments(inventory, native, {}, production_complete=True)
    result = business.review(inventory, native, {}, treatment, data=data, search_sources=search)
    assert result["counts"] == {"production_protection_unproven": 2}


@pytest.mark.parametrize("malformed", [False, True])
def test_search_only_new_caller_is_never_accepted(complete_test_je, malformed):
    data, inventory, native, treatment, original_search = complete_test_je
    search = dict(original_search)
    search["events/a3_search_only_caller.txt"] = (
        b"caller = { add_journal_entry = { type = je_global_test }" + (b"" if malformed else b" }")
    )
    result = business.review(inventory, native, {}, treatment, data=data, search_sources=search)
    assert result["counts"] == {"production_protection_unproven": 2}


def test_search_and_inventory_cannot_disagree_about_shared_bytes(complete_test_je):
    data, inventory, native, _, original_search = complete_test_je
    search = dict(original_search)
    source = "common/journal_entries/99_test_global_je.txt"
    changed = {**native, source: native[source] + b"\n# different candidate\n"}
    changed_inventory = replace(
        inventory,
        source_hashes={
            **inventory.source_hashes,
            source: hashlib.sha256(changed[source]).hexdigest(),
        },
    )
    current = native_treatments(changed_inventory, changed, {}, production_complete=True)
    result = business.review(
        changed_inventory, changed, {}, current, data=data, search_sources=search
    )
    assert result["counts"] == {"production_protection_unproven": 2}


def test_search_only_invalid_encoding_cannot_prove_no_caller(complete_test_je):
    data, inventory, native, treatment, original_search = complete_test_je
    search = {
        **original_search,
        "events/a3_unreadable_search.txt": b"\xff\xfe"
        + "type = je_global_test".encode("utf-16-le"),
    }
    result = business.review(inventory, native, {}, treatment, data=data, search_sources=search)
    assert result["counts"] == {"production_protection_unproven": 2}


def test_engine_identity_does_not_become_a_search_file(complete_test_je):
    data, inventory, native, treatment, search = complete_test_je
    inventory = replace(
        inventory,
        source_hashes={
            **inventory.source_hashes,
            "@engine/binaries/victoria3.exe": "a" * 64,
            "@version/launcher-settings.json.txt": "b" * 64,
        },
    )
    result = business.review(inventory, native, {}, treatment, data=data, search_sources=search)
    assert result["counts"] == {"retained_exact_native_policy": 2}
