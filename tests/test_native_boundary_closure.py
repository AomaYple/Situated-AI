"""Exact optional consumers and inherited recursive syntax never grant control."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace

import pytest

from pdx.situated.native_treatments import native_treatments
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface

pytestmark = pytest.mark.unit


def _inventory(sources, *, source, definition="candidate", field="unknown"):
    surface = VanillaSurface(
        surface_id="observer",
        source=source,
        definition=definition,
        field=field,
        actor_scope="unknown",
        target_scope="unknown",
        operation="declared_field",
        capability="pending",
        status="pending",
        getter=None,
        getter_note="no control authorized",
        scope_evidence=(f"{source}:1",),
        responsibility_step="D0",
        source_line=1,
    )
    return VanillaInventory(
        baseline_id="fixture",
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
        scope_hash="c" * 64,
        surfaces=(surface,),
        scanned_directories=(source.split("/")[1],),
        content_roots=("game",),
        parsed_files=len(sources),
    )


def _implicit_fixture():
    source = "common/buildings/fixture.txt"
    sources = {
        source: b"candidate={unknown=1 possible={always=yes}}",
        "common/buildings/buildings.md": (
            b"# base AI value, default NAI.BUILDING_BASE_VALUE or NAI.GOVERNMENT_BUILDING_BASE_VALUE\n"
            b"# scope is state the building is located in\n"
            b"ai_value = script value\n"
        ),
    }
    inventory = _inventory(sources, source=source)
    row = {
        "source": source,
        "definition": "candidate",
        "field": "ai_value",
        "actor_scope": "state",
        "target_scope": "none",
        "operation": "score",
        "default": "NAI.BUILDING_BASE_VALUE_or_NAI.GOVERNMENT_BUILDING_BASE_VALUE",
        "evidence": [
            "common/buildings/buildings.md:1",
            "common/buildings/buildings.md:2",
            "common/buildings/buildings.md:3",
            f"{source}:1",
        ],
        "matched_actions": ["building_writer"],
        "covered_actions": ["building_writer"],
        "binding_issues": {},
    }
    coverage = {
        "baseline_id": inventory.baseline_id,
        "scope_hash": inventory.scope_hash,
        "source_hashes": inventory.source_hashes,
        "denominator": 1,
        "rows": [],
        "implicit_rows": [row],
    }
    generated = {source: b"candidate={unknown=1 possible={always=yes} ai_value={value=100 add=2}}"}
    return inventory, sources, generated, coverage, source


def test_registered_implicit_leaf_closes_unchanged_sibling_without_control_authority():
    inventory, sources, generated, coverage, _source = _implicit_fixture()
    report = native_treatments(
        inventory, sources, generated, coverage=coverage, production_complete=True
    )
    observer = report["rows"][0]
    assert observer["source_protection"]["context_closed"]
    assert observer["source_protection"]["proven"]
    assert not observer["interface"]["control_authorized"]
    assert not observer["implemented_numeric"]
    assert report["denominator"] == 1
    assert not report["business_complete"]


@pytest.mark.parametrize(
    "fault",
    [
        "unregistered",
        "wrong_object",
        "wrong_source",
        "wrong_scope",
        "wrong_default",
        "coverage_issue",
        "unmatched_action",
        "duplicate_receipt",
        "source_incomplete",
        "drifted_docs",
        "duplicate_object",
        "duplicate_field",
        "changed_eligibility",
        "unregistered_extra_field",
        "unproven_macro",
        "new_opaque_operand",
        "unproven_helper",
        "invalid_numeric_shape",
        "unknown_condition",
        "wrong_reader_scope",
        "unproven_parameter_contract",
        "incomplete_production",
    ],
)
def test_implicit_mapping_cannot_hide_unproven_source_or_leaf(fault):
    inventory, sources, generated, coverage, source = _implicit_fixture()
    complete = True
    if fault == "unregistered":
        coverage["implicit_rows"] = []
    elif fault == "wrong_object":
        coverage["implicit_rows"][0]["definition"] = "another"
    elif fault == "wrong_source":
        coverage["implicit_rows"][0]["source"] = "common/buildings/another.txt"
    elif fault == "wrong_scope":
        coverage["implicit_rows"][0]["actor_scope"] = "country"
    elif fault == "wrong_default":
        coverage["implicit_rows"][0]["default"] = "arbitrary"
    elif fault == "coverage_issue":
        coverage["implicit_rows"][0]["binding_issues"] = {"building_writer": "unproven"}
    elif fault == "unmatched_action":
        coverage["implicit_rows"][0]["matched_actions"] = []
    elif fault == "duplicate_receipt":
        coverage["implicit_rows"].append(copy.deepcopy(coverage["implicit_rows"][0]))
    elif fault == "source_incomplete":
        inventory = replace(
            inventory,
            source_hashes={**inventory.source_hashes, "common/buildings/missing.txt": "a" * 64},
        )
        coverage["source_hashes"] = inventory.source_hashes
    elif fault == "drifted_docs":
        sources["common/buildings/buildings.md"] = b"unproven consumer\n"
        inventory = replace(
            inventory,
            source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
        )
        coverage["source_hashes"] = inventory.source_hashes
    elif fault == "duplicate_object":
        generated["common/buildings/another.txt"] = b"candidate={ai_value={value=1}}"
    elif fault == "duplicate_field":
        generated[source] = generated[source].replace(
            b"ai_value={", b"ai_value={value=1} ai_value={"
        )
    elif fault == "changed_eligibility":
        generated[source] = generated[source].replace(b"always=yes", b"always=no")
    elif fault == "unregistered_extra_field":
        generated[source] = generated[source].replace(b"unknown=1", b"unknown=1 new_permission=yes")
    elif fault == "unproven_macro":
        generated[source] = generated[source].replace(b"value=100", b"value=@unproven")
    elif fault == "new_opaque_operand":
        generated[source] = generated[source].replace(b"value=100", b'value="unknown_getter"')
    elif fault == "unproven_helper":
        generated[source] = generated[source].replace(b"value=100", b"value=unproven_value")
    elif fault == "invalid_numeric_shape":
        generated[source] = generated[source].replace(b"value=100", b"unproven_operation=100")
    elif fault == "unknown_condition":
        generated[source] = generated[source].replace(
            b"add=2", b"if={limit={invented_reader>0} add=2}"
        )
    elif fault == "wrong_reader_scope":
        generated[source] = generated[source].replace(b"add=2", b"if={limit={bureaucracy>0} add=2}")
    elif fault == "unproven_parameter_contract":
        generated[source] = generated[source].replace(
            b"add=2",
            b"if={limit={is_production_method_active={building_type=candidate production_method=unknown}} add=2}",
        )
    else:
        complete = False
    observer = native_treatments(
        inventory, sources, generated, coverage=coverage, production_complete=complete
    )["rows"][0]
    assert not observer["source_protection"]["proven"]
    assert not observer["interface"]["control_authorized"]


def test_implicit_actual_conditions_use_existing_reader_scope_contract():
    inventory, sources, generated, coverage, source = _implicit_fixture()
    generated[source] = generated[source].replace(
        b"add=2",
        b"if={limit={exists=ROOT ROOT={exists=owner owner={is_ai=yes bureaucracy>0}}} add=2}",
    )
    row = native_treatments(
        inventory, sources, generated, coverage=coverage, production_complete=True
    )["rows"][0]
    assert row["source_protection"]["proven"]
    assert not row["interface"]["control_authorized"]


def _recursive_case(raw, generated=None, *, complete=True):
    source = "common/scripted_triggers/fixture.txt"
    sources = {source: raw}
    inventory = _inventory(sources, source=source, definition="alpha", field="__body__")
    return native_treatments(
        inventory,
        sources,
        {source: generated} if generated is not None else {},
        production_complete=complete,
    )["rows"][0]


@pytest.mark.parametrize(
    "raw",
    [
        b'alpha={custom_description={text="alpha" always=yes}}',
        b"alpha={overlord ?= {alpha=yes}}",
        b"alpha={beta=yes} beta={overlord ?= {alpha=yes}}",
    ],
)
def test_native_metadata_and_recursive_components_prove_inheritance_only(raw):
    row = _recursive_case(raw)
    assert row["source_protection"]["proven"]
    assert not row["active_unknown_usage"]
    assert not row["interface"]["control_authorized"]
    assert not row["business_obligation"]["complete"]


@pytest.mark.parametrize(
    "generated",
    [
        b"alpha={beta=yes} beta={alpha=yes new_guard=yes}",
        b"alpha={beta=yes} beta={alpha=yes gamma=yes} gamma={alpha=yes}",
        b"alpha={other_scope={beta=yes}} beta={alpha=yes}",
        b"alpha={beta=yes} beta={alpha=yes} @extra=1",
    ],
)
def test_recursive_inheritance_cannot_authorize_changed_calls_or_source(generated):
    row = _recursive_case(b"alpha={beta=yes} beta={alpha=yes}", generated)
    assert not row["source_protection"]["proven"]
    assert not row["interface"]["control_authorized"]


def test_quoted_runtime_operand_is_not_metadata():
    source = "common/scripted_triggers/fixture.txt"
    sources = {source: b'alpha={runtime_condition="beta"} beta={always=yes}'}
    inventory = _inventory(sources, source=source, definition="alpha", field="__body__")
    row = native_treatments(
        inventory,
        sources,
        {source: b'alpha={runtime_condition="beta"} beta={always=no}'},
        production_complete=True,
    )["rows"][0]
    assert not row["source_protection"]["proven"]
    assert any(proof["definition"] == "beta" for proof in row["dependencies"])


def test_description_text_block_is_not_a_localization_label_exemption():
    source = "common/scripted_triggers/fixture.txt"
    sources = {source: b"alpha={custom_description={text={beta=yes}}} beta={always=yes}"}
    inventory = _inventory(sources, source=source, definition="alpha", field="__body__")
    row = native_treatments(
        inventory,
        sources,
        {source: b"alpha={custom_description={text={beta=yes}}} beta={always=no}"},
        production_complete=True,
    )["rows"][0]
    assert any(proof["definition"] == "beta" for proof in row["dependencies"])


def _macro_case(native, generated=None):
    source = "common/defines/fixture.txt"
    sources = {source: native}
    inventory = _inventory(sources, source=source, definition="NMilitary", field="AI_LIMIT")
    return native_treatments(
        inventory,
        sources,
        {source: generated} if generated is not None else {},
        production_complete=True,
    )["rows"][0]


def test_nested_lexical_macros_preserve_source_without_evaluating_expressions():
    row = _macro_case(
        b"NMilitary={AI_LIMIT=25000} "
        b"NPops={@threshold=0.4 @factor=@[1/threshold] LIMIT=@threshold SCALE=@factor}"
    )
    assert row["source_protection"]["proven"]
    assert not row["interface"]["control_authorized"]
    assert not row["business_obligation"]["complete"]


@pytest.mark.parametrize(
    "body",
    [
        b"NPops={LIMIT=@threshold @threshold=0.4}",
        b"NPops={@factor=@[1/threshold] @threshold=0.4 LIMIT=@factor}",
        b"NPops={@threshold=@factor @factor=@threshold LIMIT=@factor}",
        b"NPops={@threshold=0.4} NCountry={LIMIT=@threshold}",
        b"NPops={inner={@threshold=0.4} LIMIT=@threshold}",
    ],
)
def test_native_macro_forward_cycles_and_wrong_scope_remain_unproven(body):
    row = _macro_case(b"NMilitary={AI_LIMIT=25000} " + body)
    assert not row["source_protection"]["proven"]


@pytest.mark.parametrize(
    "body",
    [
        b"NPops={@threshold=0.5 LIMIT=@threshold}",
        b"NPops={@threshold=0.4 LIMIT=@threshold @extra=1}",
        b"NPops={@threshold=0.4} NCountry={LIMIT=@threshold}",
    ],
)
def test_lexical_macro_binding_changes_cannot_be_signed_by_unchanged_ai_constant(body):
    native = b"NMilitary={AI_LIMIT=25000} NPops={@threshold=0.4 LIMIT=@threshold}"
    row = _macro_case(native, b"NMilitary={AI_LIMIT=25000} " + body)
    assert not row["source_protection"]["proven"]
