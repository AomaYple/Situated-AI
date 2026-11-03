"""Native preservation evidence never licenses unknown interfaces or new business."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace

import pytest

from pdx.situated.native_treatments import native_treatments
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface

pytestmark = pytest.mark.unit


def _fixture(raw, *, source="common/ai_strategies/fixture.txt", **fields):
    surface = VanillaSurface(
        surface_id="protected",
        source=source,
        definition="candidate",
        field="unknown",
        actor_scope="unknown",
        target_scope="unknown",
        operation="declared_field",
        capability="pending",
        status="pending",
        getter=None,
        getter_note="no authority inferred",
        scope_evidence=(f"{source}:1",),
        responsibility_step="D0",
        source_line=1,
    )
    surface = replace(surface, **fields)
    inventory = VanillaInventory(
        baseline_id="fixture",
        source_hashes={source: hashlib.sha256(raw).hexdigest()},
        scope_hash="c" * 64,
        surfaces=(surface,),
        scanned_directories=(source.split("/")[1],),
        content_roots=("game",),
        parsed_files=1,
    )
    return inventory, {source: raw}, source


def _binding(inventory):
    return {
        "baseline_id": inventory.baseline_id,
        "scope_hash": inventory.scope_hash,
        "source_hashes": inventory.source_hashes,
        "denominator": len(inventory.surfaces),
        "rows": [
            {
                **asdict(surface),
                "declaration_id": surface.declaration_id,
                "coverage_status": "actual_covered",
                "covered_actions": ["typed_writer"],
                "matched_actions": ["typed_writer"],
                "legal": surface.legal,
                "unknown_scope": False,
                "binding_issues": {},
            }
            for surface in inventory.surfaces
        ],
    }


def test_repeated_ngui_blocks_resolve_the_unique_physical_field_without_control_authority():
    raw = b"NGUI={other=1}\nNGUI={AI_ICON_FONT=230}\n"
    inv, sources, _ = _fixture(
        raw,
        source="common/defines/interfaces.txt",
        definition="NGUI",
        field="AI_ICON_FONT",
        source_line=2,
        actor_scope="global",
        target_scope="none",
        capability="observation",
        operation="global_parameter",
    )
    report = native_treatments(inv, sources, {}, production_complete=True)
    row = report["rows"][0]
    assert row["native_ast_sha256"] is not None
    assert row["status"] == "needs_review"
    assert row["source_protection"]["proven"]
    assert not row["interface"]["control_authorized"]
    assert not row["business_obligation"]["complete"]
    assert (
        row["context_sha256"]
        == hashlib.sha256(
            json.dumps(
                asdict(inv.surfaces[0]), sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )


def test_each_duplicate_native_declaration_has_evidence_but_merge_semantics_remain_unknown():
    raw = b"candidate={\nai_chance={value=10}\nai_chance={value=100}\n}\n"
    inv, sources, _ = _fixture(
        raw,
        source="common/scripted_buttons/austria.txt",
        field="ai_chance",
        source_line=2,
        actor_scope="country",
        target_scope="none",
        capability="direct",
        operation="chance",
        ambiguity="duplicate_field_merge_semantics_unknown",
    )
    inv = replace(
        inv,
        surfaces=(
            inv.surfaces[0],
            replace(inv.surfaces[0], source_line=3, declaration_occurrence=2, surface_id="second"),
        ),
    )
    report = native_treatments(inv, sources, {}, production_complete=True)
    first, second = report["rows"]
    assert first["native_ast_sha256"] != second["native_ast_sha256"]
    for row in report["rows"]:
        assert row["native_ast_sha256"] is not None
        assert row["source_protection"]["proven"]
        assert row["status"] == "needs_review"
        assert not row["interface"]["known"]
        assert "duplicate_field_merge_semantics_unknown" in row["issues"]


@pytest.mark.parametrize("fault", ["occurrence", "line", "boolean_occurrence"])
def test_wrong_physical_declaration_identity_cannot_prove_native_protection(fault):
    inv, sources, _ = _fixture(b"candidate={unknown=1}")
    change = (
        {"declaration_occurrence": 2}
        if fault == "occurrence"
        else (
            {"declaration_occurrence": True}
            if fault == "boolean_occurrence"
            else {"source_line": 4}
        )
    )
    inv = replace(inv, surfaces=(replace(inv.surfaces[0], **change),))
    row = native_treatments(inv, sources, {}, production_complete=True)["rows"][0]
    assert not row["source_protection"]["proven"]
    assert not row["interface"]["control_authorized"]


def test_unknown_source_can_be_protected_without_becoming_a_known_interface_or_business():
    inv, sources, _ = _fixture(b"candidate={unknown={unexposed_engine_flag=yes}}")
    row = native_treatments(inv, sources, {}, production_complete=True)["rows"][0]
    assert row["source_protection"]["mode"] == "whole_source_inherited"
    assert row["source_protection"]["proven"]
    assert not row["interface"]["known"]
    assert not row["active_unknown_usage"]
    assert row["business_obligation"] == {"disposition": "preserve_native", "complete": False}
    incomplete = native_treatments(inv, sources, {})["rows"][0]
    assert not incomplete["source_protection"]["proven"]


def test_retained_named_dependency_keeps_its_ambient_file_variables():
    inv, sources, _ = _fixture(b"candidate={unknown={native_value>0}}")
    helper = "common/script_values/native.txt"
    sources[helper] = b"@scale=1 native_value={value=@scale}"
    inv = replace(
        inv, source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()}
    )
    row = native_treatments(
        inv, sources, {helper: b"@scale=9 native_value={value=@scale}"}, production_complete=True
    )["rows"][0]
    assert row["ast_status"] == "retained"
    assert not row["source_protection"]["proven"]
    assert not row["source_protection"]["dependencies_closed"]
    assert "native_dependency_unproven" in row["issues"]


def test_named_dependency_does_not_assume_reordered_variable_bindings_are_equivalent():
    inv, sources, _ = _fixture(b"candidate={unknown={native_value>0}}")
    helper = "common/script_values/native.txt"
    sources[helper] = b"@a=1 @b=@a native_value={value=@b}"
    inv = replace(
        inv, source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()}
    )
    row = native_treatments(
        inv, sources, {helper: b"@b=@a @a=1 native_value={value=@b}"}, production_complete=True
    )["rows"][0]
    assert not row["source_protection"]["proven"]
    assert not row["source_protection"]["dependencies_closed"]


@pytest.mark.parametrize(
    "raw",
    [
        b"candidate={unknown=@external}",
        b"@a=@b @b=@a candidate={unknown=@a}",
        b"@a=1 @a=2 candidate={unknown=@a}",
    ],
)
def test_unclosed_ambient_variable_bindings_cannot_prove_retained_source(raw):
    inv, sources, _ = _fixture(raw)
    row = native_treatments(inv, sources, {}, production_complete=True)["rows"][0]
    assert row["ast_status"] == "retained"
    assert not row["source_protection"]["proven"]
    assert not row["source_protection"]["dependencies_closed"]


@pytest.mark.parametrize(
    "replacement",
    [
        b"@local=2 candidate={unknown=1 weight={value=10}}",
        b"@local=1 candidate={unknown=1 weight={value=20}}",
        b"@local=1 candidate={unknown=1 weight={value=10} new_parent={flag=yes}}",
        b"@local=1 candidate={unknown=1 weight={value=10}} other={new_flag=yes}",
    ],
)
def test_mixed_override_must_close_the_entire_parent_and_file_variable_boundary(replacement):
    raw = b"@local=1 candidate={unknown=1 weight={value=10}}"
    inv, sources, source = _fixture(raw)
    row = native_treatments(inv, sources, {source: replacement}, production_complete=True)["rows"][
        0
    ]
    assert row["ast_status"] == "retained"
    assert not row["source_protection"]["proven"]
    assert not row["source_protection"]["context_closed"]


def test_unchanged_unknown_field_in_a_mixed_file_requires_covered_typed_sibling_edits():
    raw = b"candidate={unknown=1 weight={value=10}}"
    inv, sources, source = _fixture(raw, source="common/ai_regional_objectives/fixture.txt")
    sibling = replace(
        inv.surfaces[0],
        surface_id="weight",
        field="weight",
        actor_scope="country",
        target_scope="none",
        capability="direct",
        operation="score",
    )
    inv = replace(inv, surfaces=(*inv.surfaces, sibling))
    generated = {source: raw.replace(b"value=10", b"value=10 multiply=1.1")}
    report = native_treatments(
        inv, sources, generated, coverage=_binding(inv), production_complete=True
    )
    observer, writer = report["rows"]
    assert writer["status"] == "implemented_numeric"
    assert observer["source_protection"]["proven"]
    assert observer["source_protection"]["mode"] == "mixed_override"
    assert not observer["interface"]["control_authorized"]
    assert not writer["source_protection"]["proven"]


def test_structural_parent_protection_projects_only_proven_child_changes():
    raw = b"candidate={weights={primary={value=10} secondary={value=20}}}"
    inv, sources, source = _fixture(
        raw,
        field="weights",
        operation="strategy_score_map",
        capability="observation",
        actor_scope="definition_structure",
        target_scope="none",
    )
    child = replace(
        inv.surfaces[0],
        surface_id="child",
        field="weights.primary",
        operation="score",
        capability="direct",
        actor_scope="country",
    )
    inv = replace(inv, surfaces=(*inv.surfaces, child))
    generated = {source: raw.replace(b"value=10", b"value=10 multiply=1.1")}
    parent, writer = native_treatments(
        inv, sources, generated, coverage=_binding(inv), production_complete=True
    )["rows"]
    assert writer["status"] == "implemented_numeric"
    assert parent["ast_status"] == "changed"
    assert parent["source_protection"]["proven"]
    assert parent["source_protection"]["structural_projection"]
    assert not parent["active_unknown_usage"]
    assert not parent["interface"]["control_authorized"]
    generated[source] = generated[source].replace(b"value=20", b"value=99")
    parent = native_treatments(
        inv, sources, generated, coverage=_binding(inv), production_complete=True
    )["rows"][0]
    assert not parent["source_protection"]["proven"]
    assert parent["active_unknown_usage"]


def _opaque_case(native_body, generated_body):
    inv, sources, source = _fixture(
        f"candidate={{weight={{{native_body}}}}}".encode(),
        source="common/ai_regional_objectives/fixture.txt",
        field="weight",
        operation="score",
        actor_scope="country",
        target_scope="none",
        capability="direct",
    )
    return native_treatments(
        inv,
        sources,
        {source: f"candidate={{weight={{{generated_body}}}}}".encode()},
        coverage=_binding(inv),
        production_complete=True,
    )["rows"][0]


def test_native_opaque_numeric_operand_is_preserved_by_occurrence_not_by_a_name_whitelist():
    row = _opaque_case(
        "value=unregistered_native_operand", "value=unregistered_native_operand multiply=1.1"
    )
    assert row["status"] == "implemented_numeric"
    assert row["dependencies"][0]["status"] == "retained_opaque"
    assert row["dependencies"][0]["occurrences"]


def test_numeric_binding_cannot_authorize_an_ambient_variable_rewrite():
    raw = b"@factor=1 candidate={weight={value=@factor}}"
    inv, sources, source = _fixture(
        raw,
        source="common/ai_regional_objectives/fixture.txt",
        field="weight",
        operation="score",
        actor_scope="country",
        target_scope="none",
        capability="direct",
    )
    row = native_treatments(
        inv,
        sources,
        {source: b"@factor=2 candidate={weight={value=@factor multiply=1.1}}"},
        coverage=_binding(inv),
        production_complete=True,
    )["rows"][0]
    assert not row["interface"]["control_authorized"]
    assert row["active_unknown_usage"]
    assert not row["source_protection"]["dependencies_closed"]


@pytest.mark.parametrize(
    "body",
    [
        "value=1 add=unregistered_native_operand",
        "value=unregistered_native_operand add=unregistered_native_operand",
        "value=1 if={limit={always=yes} add=unregistered_native_operand}",
    ],
)
def test_native_opaque_operand_moved_or_duplicated_is_an_unproven_new_use(body):
    row = _opaque_case("value=unregistered_native_operand", body)
    assert row["status"] == "needs_review"
    assert "native_dependency_unproven" in row["issues"]
    assert not row["interface"]["control_authorized"]
    assert row["active_unknown_usage"]


def test_native_opaque_operand_keeps_its_exact_branch_guard():
    row = _opaque_case(
        "value=1 if={limit={always=yes} add=unregistered_native_operand}",
        "value=1 if={limit={always=no} add=unregistered_native_operand}",
    )
    assert row["status"] == "needs_review"
    assert "native_dependency_unproven" in row["issues"]


def test_new_quoted_accessor_remains_unproven_even_when_the_name_occurs_in_native_sources():
    row = _opaque_case("value=1", 'value=1 add="ROOT.economic_dependence(scope:country)"')
    assert "generated_numeric_shape_unproven" in row["issues"]
    assert "native_dependency_unproven" in row["issues"]
    assert row["active_unknown_usage"]


def _generated_helper_case(
    body,
    *,
    call="ROOT={sitai_context_stable_capacity=yes}",
    helper_source=None,
    complete=True,
):
    source = "common/ai_strategies/00_default_strategy.txt"
    inv, sources, _ = _fixture(
        b"ai_strategy_default={change_law_chance={value=10}}",
        source=source,
        definition="ai_strategy_default",
        field="change_law_chance",
        actor_scope="country",
        target_scope="none",
        capability="direct",
        operation="additive_percentage_chance",
    )
    helper = helper_source or "common/scripted_triggers/sitai_country_triggers.txt"
    generated = {
        source: f"ai_strategy_default={{change_law_chance={{value=10 if={{limit={{{call}}} add=1}}}}}}".encode(),
        helper: f"sitai_context_stable_capacity={{{body}}}".encode(),
    }
    return native_treatments(
        inv,
        sources,
        generated,
        coverage=_binding(inv),
        production_complete=complete,
    )


def test_registered_generated_helper_checks_actual_typed_body_at_the_country_consumer():
    row = _generated_helper_case("is_ai=yes AND={legitimacy>=0}")["rows"][0]
    assert row["status"] == "implemented_numeric"
    proof = row["dependencies"][0]
    assert proof["status"] == "proven_generated"
    assert proof["effective_source_sha256"]
    assert proof["effective_ast_sha256"]
    assert proof["consumer_context_sha256"] == row["context_sha256"]
    assert not row["business_obligation"]["complete"]


def test_generated_helper_cannot_assume_that_its_definition_index_is_complete():
    row = _generated_helper_case("is_ai=yes legitimacy>=0", complete=False)["rows"][0]
    assert row["status"] == "needs_review"
    assert "native_dependency_unproven" in row["issues"]
    assert not row["interface"]["control_authorized"]


@pytest.mark.parametrize(
    ("body", "call", "source"),
    [
        ("is_ai=yes phantom_reader>0", "ROOT={sitai_context_stable_capacity=yes}", None),
        ("is_ai=yes legitimacy>=0", "scope:country={sitai_context_stable_capacity=yes}", None),
        ("is_ai=yes legitimacy>=0", "ROOT={sitai_context_stable_capacity={PARTNER=ROOT}}", None),
        (
            "is_ai=yes sitai_context_stable_capacity=yes",
            "ROOT={sitai_context_stable_capacity=yes}",
            None,
        ),
        (
            "is_ai=yes legitimacy>=0",
            "ROOT={sitai_context_stable_capacity=yes}",
            "common/scripted_triggers/shadow.txt",
        ),
        (
            "is_ai=yes has_variable=unproved_variable",
            "ROOT={sitai_context_stable_capacity=yes}",
            None,
        ),
        ("is_ai=yes has_variable=yes", "ROOT={sitai_context_stable_capacity=yes}", None),
        ("is_ai=yes pop_type_percent_country>0", "ROOT={sitai_context_stable_capacity=yes}", None),
    ],
)
def test_generated_helper_does_not_grant_unknown_leaf_scope_parameter_cycle_or_source(
    body, call, source
):
    row = _generated_helper_case(body, call=call, helper_source=source)["rows"][0]
    assert row["status"] == "needs_review"
    assert "native_dependency_unproven" in row["issues"]
    assert row["active_unknown_usage"]
