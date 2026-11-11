"""Typed native responsibility does not manufacture numeric or business coverage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from pdx import config, decision_adapters, distribution, version_contracts
from pdx.model import Block
from pdx.parser import parse_bytes
from pdx.situated.native_treatments import native_treatments
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface, discover

pytestmark = pytest.mark.unit


def _case(family, field, body, *, operation="eligibility", capability="direct"):
    source = f"common/{family}/fixture.txt"
    raw = f"candidate = {{ {body} }}\n".encode()
    node = parse_bytes(raw, path=source).root.first("candidate")
    for key in field.split("."):
        assert node is not None
        assert isinstance(node.value, Block)
        node = node.value.first(key)
    assert node is not None
    surface = VanillaSurface(
        surface_id="surface",
        source=source,
        definition="candidate",
        field=field,
        actor_scope="country",
        target_scope="none",
        operation=operation,
        capability=capability,
        status="pending",
        getter=None,
        getter_note="no getter",
        scope_evidence=(f"{source}:1",),
        responsibility_step="S4",
        source_line=node.line,
    )
    inventory = VanillaInventory(
        baseline_id="fixture",
        source_hashes={source: hashlib.sha256(raw).hexdigest()},
        scope_hash="b" * 64,
        surfaces=(surface,),
        scanned_directories=(family,),
        content_roots=("game",),
        parsed_files=1,
    )
    return inventory, {source: raw}, source


def _coverage(inventory):
    surface = inventory.surfaces[0]
    return {
        "baseline_id": inventory.baseline_id,
        "denominator": inventory.discovered_count,
        "scope_hash": inventory.scope_hash,
        "source_hashes": inventory.source_hashes,
        "rows": [
            {
                **asdict(surface),
                "declaration_id": surface.declaration_id,
                "source": surface.source,
                "definition": surface.definition,
                "field": surface.field,
                "coverage_status": "actual_covered",
                "covered_actions": ["actual_program"],
                "matched_actions": ["actual_program"],
                "legal": surface.legal,
                "unknown_scope": False,
                "binding_issues": {},
            }
        ],
    }


@pytest.mark.parametrize(
    ("family", "field", "body", "kind"),
    [
        (
            "modifier_type_definitions",
            "game_data.ai_value",
            "game_data={ai_value=0}",
            "static_modifier_valuation",
        ),
        ("company_types", "ai_will_do", "ai_will_do={always=yes}", "eligibility"),
        (
            "company_types",
            "ai_construction_targets.building_mine.level",
            "ai_construction_targets={building_mine={level=5 state_trigger={always=yes}}}",
            "static_construction_cap",
        ),
        ("country_creation", "ai_will_do", "ai_will_do={always=no}", "eligibility"),
        (
            "country_formation",
            "ai_will_do",
            "ai_will_do={has_technology_researched=nationalism}",
            "eligibility",
        ),
        (
            "ai_regional_objectives",
            "stances",
            "stances={stance_protect_region}",
            "static_reference_list",
        ),
        (
            "ai_regional_objectives",
            "complete",
            "complete={has_variable=observed}",
            "completion_observation",
        ),
        ("ai_regional_objectives", "invalid", "invalid={always=no}", "completion_observation"),
        ("ai_regional_objectives", "possible", "possible={always=yes}", "eligibility"),
        (
            "ai_regional_objectives",
            "on_complete",
            "on_complete={remove_variable=observed}",
            "lifecycle_effect",
        ),
        (
            "ai_regional_objectives",
            "on_invalid",
            "on_invalid={remove_variable=observed}",
            "lifecycle_effect",
        ),
        (
            "ai_regional_objectives",
            "on_create",
            "on_create={set_variable=observed}",
            "lifecycle_effect",
        ),
        ("ai_regional_objectives", "weight", "weight={value=10}", "dynamic_numeric"),
    ],
)
def test_verified_original_is_retained_without_claiming_business(family, field, body, kind):
    inventory, sources, _ = _case(family, field, body)
    report = native_treatments(inventory, sources, {}, production_complete=True)
    row = report["rows"][0]
    assert row["declaration_id"] == inventory.surfaces[0].declaration_id
    assert row["interface_kind"] == kind
    assert row["status"] == "retained_native"
    assert row["effective_origin"] == "native_inherited"
    assert row["ast_status"] == "retained"
    assert not row["business_complete"]
    assert not report["business_complete"]


def test_missing_production_manifest_cannot_prove_inheritance():
    inventory, sources, _ = _case("country_creation", "ai_will_do", "ai_will_do={always=no}")
    row = native_treatments(inventory, sources, {})["rows"][0]
    assert row["status"] == "missing_evidence"
    assert "production_manifest_incomplete" in row["issues"]


def test_formatting_and_bom_change_preserves_ordered_ast():
    inventory, sources, source = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    generated = {
        source: b"\xef\xbb\xbfcandidate={\r\n# changed line\r\nai_will_do = { always = yes } }"
    }
    row = native_treatments(inventory, sources, generated)["rows"][0]
    assert row["status"] == "retained_native"
    assert row["native_ast_sha256"] == row["effective_ast_sha256"]


@pytest.mark.parametrize("family", ["company_types", "country_creation", "country_formation"])
def test_native_false_is_not_revived_by_coverage(family):
    inventory, sources, source = _case(family, "ai_will_do", "ai_will_do={always=no}")
    report = native_treatments(
        inventory,
        sources,
        {source: b"candidate={ai_will_do={always=yes}}"},
        coverage=_coverage(inventory),
    )
    row = report["rows"][0]
    assert row["native_terminal"] == "always_false"
    assert row["status"] == "changed_native"
    assert "native_eligibility_changed" in row["issues"]
    assert not row["implemented_numeric"]


@pytest.mark.parametrize(
    "body",
    [
        "value=unproven add={always=yes}",
        "value=1 if={always=yes}",
        "desc=only_description",
        "add=1",
        "value=1 else={multiply=2}",
        "value=1 else_if={limit={always=yes} add=2}",
        "value=1 if={limit={always=yes} add=2} else={add=1} else={add=3}",
        "value=1 if={limit={always=yes} limit={always=no} add=2}",
        "value=1 if={limit=yes add=2}",
        "value=1 if={limit={always=yes} add={always=yes}}",
        "value=1 if={limit={always=yes} add=2} add=1 else={add=3}",
        "value=1 if={limit={always=yes} add=2} else={limit={always=no} add=3}",
        "value=1 add={value=1 multiply=yes}",
        'value=1 add="2"',
        "value=1 add={value=2 unexpected=3}",
        "value=1 add={value=2 INJECT:multiply=3}",
        "value=1 add={value=2 {} multiply=3}",
        "value=1 add={value=2 bare multiply=3}",
        "value=1 add={desc=only_description}",
        "value=1 value=2",
        "value=1 fixed_range={min=0 max=1}",
        "base=1 modifier={always=yes add=1}",
    ],
)
def test_unproven_numeric_grammar_is_rejected_for_inline_and_registered_values(body):
    inventory, sources, source = _case("ai_regional_objectives", "weight", "weight={value=10}")
    row = native_treatments(
        inventory,
        sources,
        {source: f"candidate={{weight={{{body}}}}}".encode()},
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["status"] == (
        "needs_review" if body == "value=unproven add={always=yes}" else "changed_native"
    )
    assert "generated_numeric_shape_unproven" in row["issues"]
    inventory, sources, generated = _fleet_case()
    generated[decision_adapters._VALUE_SOURCE] = (
        f"{decision_adapters._FLEET_VALUE}={{{body}}}".encode()
    )
    row = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))["rows"][0]
    assert row["status"] == "needs_review"
    assert "native_dependency_unproven" in row["issues"]
    assert "generated_numeric_shape_unproven" in row["issues"]
    assert row["resolved_numeric_value"] is None


def _dependent_case():
    inventory, sources, source = _case(
        "ai_regional_objectives", "weight", "weight=shared_native_weight"
    )
    helper = "common/script_values/native_values.txt"
    sources[helper] = b"shared_native_weight={value=10}"
    inventory = replace(
        inventory,
        source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
    )
    return inventory, sources, source, helper


@pytest.mark.parametrize(
    "fault", ["changed", "missing", "duplicate", "shadow", "malformed", "cycle", "transitive"]
)
def test_unchanged_numeric_reference_does_not_hide_changed_or_unproven_dependency(fault):
    inventory, sources, _, helper = _dependent_case()
    generated = {}
    if fault == "changed":
        generated[helper] = b"shared_native_weight={value=100}"
    elif fault == "missing":
        generated[helper] = b"other={value=10}"
    elif fault == "duplicate":
        generated[helper] = sources[helper] * 2
    elif fault == "shadow":
        generated["common/script_values/shadow.txt"] = sources[helper]
    elif fault == "malformed":
        generated[helper] = b"shared_native_weight={"
    elif fault == "cycle":
        generated[helper] = b"shared_native_weight={value=shared_native_weight}"
    else:
        sources[helper] = b"shared_native_weight={value=second_weight} second_weight={value=10}"
        inventory = replace(
            inventory,
            source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
        )
        generated[helper] = sources[helper].replace(b"value=10", b"value=100")
    row = native_treatments(inventory, sources, generated, production_complete=True)["rows"][0]
    assert row["ast_status"] == "retained"
    assert row["status"] == "needs_review"
    assert "native_dependency_unproven" in row["issues"]
    assert row["dependencies"]


def test_retained_dependency_has_unique_source_ast_and_raw_byte_identities():
    inventory, sources, _, helper = _dependent_case()
    generated = {helper: sources[helper] + b"# comment changes source bytes only\n"}
    row = native_treatments(inventory, sources, generated, production_complete=True)["rows"][0]
    assert row["status"] == "retained_native"
    proof = row["dependencies"][0]
    assert proof["definition"] == "shared_native_weight"
    assert proof["family"] == "script_values"
    assert proof["native_source"] == proof["effective_source"] == helper
    assert proof["native_source_sha256"] == hashlib.sha256(sources[helper]).hexdigest()
    assert proof["effective_source_sha256"] == hashlib.sha256(generated[helper]).hexdigest()
    assert proof["native_ast_sha256"] == proof["effective_ast_sha256"]
    assert proof["status"] == "retained"


def test_missing_native_dependency_bytes_cannot_be_called_retained():
    inventory, sources, source, _ = _dependent_case()
    row = native_treatments(inventory, {source: sources[source]}, {}, production_complete=True)[
        "rows"
    ][0]
    assert row["status"] == "needs_review"
    assert "native_dependency_unproven" in row["issues"]


def test_retained_scripted_trigger_call_tracks_its_changed_numeric_dependency():
    inventory, sources, _source = _case(
        "company_types", "ai_will_do", "ai_will_do={native_allow=yes}"
    )
    trigger = "common/scripted_triggers/native.txt"
    helper = "common/script_values/native.txt"
    sources[trigger] = b"native_allow={native_value>0}"
    sources[helper] = b"native_value={value=10}"
    inventory = replace(
        inventory,
        source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
    )
    row = native_treatments(
        inventory, sources, {helper: b"native_value={value=0}"}, production_complete=True
    )["rows"][0]
    assert row["status"] == "needs_review"
    assert {proof["definition"] for proof in row["dependencies"]} == {
        "native_allow",
        "native_value",
    }


@pytest.mark.parametrize("route", ["generated", "fleet", "companion"])
@pytest.mark.parametrize(
    "fault", ["changed", "removed", "duplicate", "malformed", "cycle", "source_subset", "new", None]
)
def test_every_actual_consumer_audits_named_trigger_dependencies(route, fault):
    trigger = "common/scripted_triggers/known.txt"
    if route == "fleet":
        inventory, sources, generated = _fleet_case()
        generated[decision_adapters._VALUE_SOURCE] = (
            decision_adapters._FLEET_VALUE.encode()
            + b"={value=1 if={limit={known_gate=yes} multiply=1.1}}"
        )
    elif route == "companion":
        inventory, sources, _source = _case(
            "company_types",
            "ai_weight",
            "ai_weight={value=10} ai_will_do={known_gate=yes}",
            operation="base_candidate_score",
        )
        generated = {}
    else:
        inventory, sources, source = _case(
            "ai_regional_objectives", "weight", "weight={value=10}", operation="score"
        )
        generated = {
            source: b"candidate={weight={value=10 if={limit={known_gate=yes} multiply=1.1}}}"
        }
    sources[trigger] = b"known_gate={always=yes}"
    if fault == "cycle":
        sources[trigger] = b"known_gate={second_gate=yes} second_gate={known_gate=yes}"
    if fault == "new":
        generated[trigger] = sources.pop(trigger)
    inventory = replace(
        inventory,
        source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
    )
    if fault == "changed":
        generated[trigger] = b"known_gate={always=no}"
    elif fault == "removed":
        generated[trigger] = b"different_gate={always=yes}"
    elif fault == "duplicate":
        generated[trigger] = sources[trigger] * 2
    elif fault == "malformed":
        generated[trigger] = b"known_gate={"
    elif fault == "source_subset":
        sources.pop(trigger)
    row = native_treatments(
        inventory, sources, generated, coverage=_coverage(inventory), production_complete=True
    )["rows"][0]
    assert row["status"] == (
        "needs_review"
        if fault is not None
        else "retained_native"
        if route == "companion"
        else "implemented_numeric"
    )
    assert row["dependencies"]
    assert not row["business_complete"]
    if fault is not None:
        assert not row["implemented_numeric"]
        assert "native_dependency_unproven" in row["issues"]
        if route == "companion":
            companion = next(item for item in row["companions"] if item["field"] == "ai_will_do")
            assert not companion["retained"]
            assert companion["dependencies"]


@pytest.mark.parametrize(
    ("key", "wrong"),
    [
        ("actor_scope", "state"),
        ("target_scope", "scope:law=law"),
        ("operation", "eligibility"),
        ("capability", "pending"),
        ("surface_id", "wrong"),
        ("source_line", 99),
        ("declaration_occurrence", True),
        ("scope_evidence", []),
        ("parent_field", "unexpected"),
        ("legal", False),
        ("unknown_scope", True),
    ],
)
def test_receipt_context_and_declaration_identity_must_match_exactly(key, wrong):
    inventory, sources, source = _case(
        "ai_regional_objectives", "weight", "weight={value=10}", operation="score"
    )
    coverage = _coverage(inventory)
    coverage["rows"][0][key] = wrong
    row = native_treatments(
        inventory, sources, {source: b"candidate={weight={value=11}}"}, coverage=coverage
    )["rows"][0]
    assert row["status"] == "changed_native"
    assert not row["implemented_numeric"]


@pytest.mark.parametrize("fault", ["baseline", "denominator", "missing_context", None])
def test_receipt_identity_and_json_roundtrip_are_checked(fault):
    inventory, sources, source = _case(
        "ai_regional_objectives", "weight", "weight={value=10}", operation="score"
    )
    coverage = json.loads(json.dumps(_coverage(inventory)))
    if fault == "baseline":
        coverage["baseline_id"] = "another_baseline"
    elif fault == "denominator":
        coverage["denominator"] = True
    elif fault == "missing_context":
        del coverage["rows"][0]["getter_note"]
    row = native_treatments(
        inventory, sources, {source: b"candidate={weight={value=11}}"}, coverage=coverage
    )["rows"][0]
    assert row["status"] == ("implemented_numeric" if fault is None else "changed_native")


EXACT_DEFAULT_OPERATIONS = [
    ("wanted_army_size", "additive_army_size_target"),
    ("wanted_navy_size", "additive_navy_size_target"),
    ("wanted_construction_output", "additive_construction_output_target"),
    ("ship_construction_output_multiplier", "additive_ship_construction_output_multiplier"),
    ("nationalization_desire", "additive_nationalization_desire"),
    ("wanted_marines", "additive_marine_size_target"),
    ("target_marine_formation_size", "additive_marine_formation_size_target"),
]


def _default_case(field, operation):
    inventory, sources, old = _case(
        "ai_strategies", field, f"{field}={{value=10}}", operation=operation
    )
    source = "common/ai_strategies/00_default_strategy.txt"
    raw = sources[old].replace(b"candidate", b"ai_strategy_default")
    surface = replace(inventory.surfaces[0], source=source, definition="ai_strategy_default")
    inventory = replace(
        inventory, surfaces=(surface,), source_hashes={source: hashlib.sha256(raw).hexdigest()}
    )
    return inventory, {source: raw}, source


@pytest.mark.parametrize(("field", "operation"), EXACT_DEFAULT_OPERATIONS)
def test_seven_proven_default_operations_are_numerical_only_at_the_exact_consumer(field, operation):
    inventory, sources, source = _default_case(field, operation)
    generated = {source: sources[source].replace(b"value=10", b"value=10 multiply=1.08")}
    row = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))["rows"][0]
    assert row["interface_kind"] == "dynamic_numeric"
    assert row["status"] == "implemented_numeric"


@pytest.mark.parametrize(("field", "operation"), EXACT_DEFAULT_OPERATIONS)
@pytest.mark.parametrize(
    "fault", ["source", "definition", "field", "actor", "target", "capability", "operation"]
)
def test_new_operation_names_do_not_license_an_unregistered_context(field, operation, fault):
    inventory, sources, source = _default_case(field, operation)
    surface = inventory.surfaces[0]
    if fault == "source":
        destination = "common/ai_strategies/unregistered.txt"
        sources = {destination: sources[source]}
        source = destination
        surface = replace(surface, source=source)
    elif fault == "definition":
        sources[source] = sources[source].replace(b"ai_strategy_default", b"another_strategy")
        surface = replace(surface, definition="another_strategy")
    elif fault == "field":
        sources[source] = sources[source].replace(field.encode(), b"unregistered_field")
        surface = replace(surface, field="unregistered_field")
    elif fault == "actor":
        surface = replace(surface, actor_scope="state")
    elif fault == "target":
        surface = replace(surface, target_scope="scope:target_country=country")
    elif fault == "capability":
        surface = replace(surface, capability="indirect")
    else:
        surface = replace(
            surface,
            operation="additive_army_size_target"
            if field == "wanted_navy_size"
            else "additive_navy_size_target",
        )
    inventory = replace(
        inventory,
        surfaces=(surface,),
        source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
    )
    generated = {source: sources[source].replace(b"value=10", b"value=10 multiply=1.08")}
    row = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))["rows"][0]
    assert row["status"] == "needs_review"
    assert not row["implemented_numeric"]


@pytest.mark.parametrize(
    ("family", "field"), [("company_types", "ai_weight"), ("ai_regional_objectives", "weight")]
)
@pytest.mark.parametrize(("_default_field", "operation"), EXACT_DEFAULT_OPERATIONS)
def test_exact_default_operation_is_not_licensed_by_another_numeric_family(
    family, field, _default_field, operation
):
    inventory, sources, source = _case(family, field, f"{field}={{value=10}}", operation=operation)
    row = native_treatments(
        inventory,
        sources,
        {source: sources[source].replace(b"value=10", b"value=10 multiply=1.08")},
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["status"] == "needs_review"
    assert not row["implemented_numeric"]


def test_generated_helper_cannot_replace_missing_native_dependency_evidence():
    inventory, sources, source, helper = _dependent_case()
    row = native_treatments(
        inventory, {source: sources[source]}, {helper: sources[helper]}, production_complete=True
    )["rows"][0]
    assert row["status"] == "needs_review"
    assert row["dependencies"][0]["native_source_sha256"] is None


@pytest.mark.parametrize(
    "native_body",
    [
        "base=10 modifier={has_variable=native_condition factor=1.5}",
        "value=native_value if={limit={native_trigger={native_parameter=yes}} add=1}",
        "add=10 if={limit={always=yes} multiply=2}",
    ],
)
def test_native_only_numeric_fragments_can_be_preserved_but_not_newly_introduced(native_body):
    inventory, sources, source = _case(
        "ai_regional_objectives", "weight", f"weight={{{native_body}}}", operation="score"
    )
    if "native_value" in native_body:
        helper = "common/script_values/native.txt"
        sources[helper] = b"native_value={value=10}"
        inventory = replace(
            inventory,
            source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
        )
    generated = {
        source: sources[source].replace(
            native_body.encode(), (native_body + " multiply=1.08").encode()
        )
    }
    row = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))["rows"][0]
    assert row["status"] == "implemented_numeric"
    if "modifier" in native_body:
        generated[source] = generated[source].replace(b"factor=1.5", b"factor=2")
        row = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))[
            "rows"
        ][0]
        assert row["status"] == "changed_native"


@pytest.mark.parametrize("fault", [None, "removed", "changed", "reordered"])
def test_implicit_native_accumulator_requires_all_original_operations_in_order(fault):
    native_body = (
        "if={limit={always=yes} add=10} min=0 max=100 if={limit={always=no} add=1} else={add=2}"
    )
    inventory, sources, source = _case(
        "ai_regional_objectives", "weight", f"weight={{{native_body}}}", operation="score"
    )
    body = native_body.replace("min=0", "if={limit={always=yes} multiply=1.08} min=0")
    if fault == "removed":
        body = body.replace("min=0", "")
    elif fault == "changed":
        body = body.replace("max=100", "max=200")
    elif fault == "reordered":
        body = body.replace("min=0 max=100", "max=100 min=0")
    row = native_treatments(
        inventory,
        sources,
        {source: f"candidate={{weight={{{body}}}}}".encode()},
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["status"] == ("implemented_numeric" if fault is None else "changed_native")


@pytest.fixture(scope="module")
def installed_inventory():
    return discover(game=config.GAME)


@pytest.mark.integration
def test_each_added_operation_has_installed_scope_evidence_and_supported_actual_numeric_ast(
    installed_inventory,
):
    from pdx.situated.native_treatments import _kind, _numeric_shape, _resolve

    source = "common/ai_strategies/00_default_strategy.txt"
    native = parse_bytes((config.GAME / source).read_bytes(), path=source).root
    # Exercise the full current compatibility generation, including its added
    # operations; the narrow R2 profile intentionally retains these native fields.
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    generated_source = files[source]
    generated_raw = (
        generated_source.encode("utf-8") if isinstance(generated_source, str) else generated_source
    )
    generated = parse_bytes(generated_raw, path=source).root
    for field, operation in EXACT_DEFAULT_OPERATIONS:
        candidates = [
            surface
            for surface in installed_inventory.surfaces
            if surface.source == source
            and surface.definition == "ai_strategy_default"
            and surface.field == field
        ]
        assert len(candidates) == 1
        surface = candidates[0]
        assert surface.operation == operation
        assert (surface.actor_scope, surface.target_scope, surface.capability) == (
            "country",
            "none",
            "direct",
        )
        assert surface.scope_evidence
        assert surface.legal
        assert not surface.ambiguity
        before, state = _resolve(native, surface.definition, field)
        after, generated_state = _resolve(generated, surface.definition, field)
        assert state == generated_state == "found"
        assert before is not None
        assert after is not None
        assert _kind(surface, before) == "dynamic_numeric"
        assert _numeric_shape(after, before), field


@pytest.mark.parametrize(
    ("field", "body", "replacement", "issue"),
    [
        (
            "complete",
            "complete={has_variable=real_completion}",
            "complete={always=yes}",
            "completion_condition_changed",
        ),
        (
            "on_invalid",
            "on_invalid={remove_variable=baseline}",
            "on_invalid={}",
            "lifecycle_effect_changed",
        ),
        (
            "weight",
            "weight={value=10 multiply=0}",
            "weight={value=100}",
            "native_zero_changed_unproven",
        ),
    ],
)
def test_native_completion_lifecycle_and_zero_require_proof(field, body, replacement, issue):
    inventory, sources, source = _case("ai_regional_objectives", field, body)
    row = native_treatments(
        inventory,
        sources,
        {source: f"candidate={{{replacement}}}".encode()},
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["status"] == "changed_native"
    assert issue in row["issues"]
    assert not row["implemented_numeric"]


def test_cap_preservation_includes_state_filter_and_company_native_gate():
    body = "ai_will_do={always=no} ai_construction_targets={building_mine={level=5 state_trigger={state_region=s:STATE_ONE}}}"
    inventory, sources, source = _case(
        "company_types",
        "ai_construction_targets.building_mine.level",
        body,
    )
    generated = {source: sources[source].replace(b"STATE_ONE", b"STATE_TWO")}
    row = native_treatments(inventory, sources, generated)["rows"][0]
    assert row["ast_status"] == "retained"
    assert row["status"] == "changed_native"
    assert "native_companion_changed:ai_construction_targets.building_mine" in row["issues"]
    changed_gate = {source: sources[source].replace(b"always=no", b"always=yes")}
    row = native_treatments(inventory, sources, changed_gate)["rows"][0]
    assert "native_companion_changed:ai_will_do" in row["issues"]


def test_numeric_change_requires_exact_current_coverage_and_is_not_functional_acceptance():
    inventory, sources, source = _case("ai_regional_objectives", "weight", "weight={value=10}")
    generated = {source: b"candidate={weight={value=10 multiply=1.08}}"}
    absent = native_treatments(inventory, sources, generated)["rows"][0]
    assert absent["status"] == "changed_native"
    report = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))
    row = report["rows"][0]
    assert row["status"] == "implemented_numeric"
    assert row["implemented_numeric"]
    assert row["ast_status"] == "changed"
    assert not row["business_complete"]
    assert report["counts"]["retained_native"] == 0


def test_retained_numeric_with_binding_is_still_retained_not_new_implementation():
    inventory, sources, _ = _case("ai_regional_objectives", "weight", "weight={value=10}")
    row = native_treatments(
        inventory,
        sources,
        sources,
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["status"] == "retained_native"
    assert not row["implemented_numeric"]


@pytest.mark.parametrize("problem", ["hash", "identity", "duplicate", "issues", "status"])
def test_coverage_cannot_license_wrong_or_ambiguous_bindings(problem):
    inventory, sources, source = _case("ai_regional_objectives", "weight", "weight={value=10}")
    coverage = _coverage(inventory)
    if problem == "hash":
        coverage["scope_hash"] = "stale"
    elif problem == "identity":
        coverage["rows"][0]["field"] = "possible"
    elif problem == "duplicate":
        coverage["rows"] *= 2
    elif problem == "issues":
        coverage["rows"][0]["binding_issues"] = {"actual_program": "wrong_scope"}
    else:
        coverage["rows"][0]["coverage_status"] = "unimplemented_legal"
    row = native_treatments(
        inventory,
        sources,
        {source: b"candidate={weight={value=12}}"},
        coverage=coverage,
    )["rows"][0]
    assert row["status"] == "changed_native"
    assert not row["implemented_numeric"]


def test_source_hash_drift_is_hard_failure():
    inventory, sources, source = _case("country_creation", "ai_will_do", "ai_will_do={always=no}")
    with pytest.raises(ValueError, match="SHA"):
        native_treatments(inventory, {source: sources[source] + b"# drift"}, sources)


@pytest.mark.parametrize(
    "path", ["../escape.txt", "common/../x.txt", "C:/secret.txt", "common\\x.txt", "common//x.txt"]
)
def test_noncanonical_source_paths_rejected(path):
    inventory, sources, _ = _case("country_creation", "ai_will_do", "ai_will_do={always=no}")
    with pytest.raises(ValueError, match="path"):
        native_treatments(inventory, sources, {path: b"x={}"})


@pytest.mark.parametrize(
    "replacement",
    [
        b"candidate={ai_will_do={}} candidate={ai_will_do={}}",
        b"candidate={ai_will_do={} ai_will_do={}}",
    ],
)
def test_duplicate_production_definition_or_field_never_proves_retention(replacement):
    inventory, sources, source = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    row = native_treatments(inventory, sources, {source: replacement})["rows"][0]
    assert row["status"] == "missing_evidence"
    assert row["ast_status"] == "ambiguous"


def test_duplicate_cross_source_definition_never_proves_retention():
    inventory, sources, source = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    generated = {source: sources[source], "common/company_types/shadow.txt": sources[source]}
    row = native_treatments(inventory, sources, generated)["rows"][0]
    assert row["status"] == "missing_evidence"
    assert "production_definition_ambiguous" in row["issues"]


def test_missing_native_or_removed_field_is_not_retained():
    inventory, sources, source = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    for native, generated in [({}, sources), (sources, {source: b"candidate={}"})]:
        row = native_treatments(inventory, native, generated)["rows"][0]
        assert row["status"] == "missing_evidence"
    row = native_treatments(inventory, sources, {source: b"candidate={"})["rows"][0]
    assert "production_parse_failure" in row["issues"]


def test_unknown_directory_scope_and_ambiguity_remain_reviewable():
    inventory, sources, _ = _case("new_native_family", "ai_weight", "ai_weight={value=1}")
    row = native_treatments(inventory, sources, sources)["rows"][0]
    assert row["status"] == "needs_review"
    assert row["interface_kind"] == "needs_review"
    inventory = replace(
        inventory,
        surfaces=(replace(inventory.surfaces[0], capability="pending", actor_scope="unknown"),),
    )
    row = native_treatments(inventory, sources, sources)["rows"][0]
    assert row["native_capability"] == "pending"
    assert row["status"] == "needs_review"
    assert row["status"] != "unsupported"


def test_all_declaration_ids_survive_including_existing_observations():
    inventory, sources, _ = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    original = inventory.surfaces[0]
    extra = replace(
        original, surface_id="second", declaration_occurrence=2, ambiguity="duplicate_field"
    )
    inventory = replace(inventory, surfaces=(original, extra))
    report = native_treatments(inventory, sources, sources)
    assert report["denominator"] == 2
    assert {r["declaration_id"] for r in report["rows"]} == {
        original.declaration_id,
        extra.declaration_id,
    }
    assert sum(report["counts"].values()) == 2
    # The inventory's second occurrence has no corresponding physical input.
    # Keep the identity in the denominator, but do not invent source evidence.
    assert report["rows"][1]["status"] == "missing_evidence"
    assert "native_declaration_occurrence_missing" in report["rows"][1]["issues"]
    assert not report["rows"][1]["source_protection"]["proven"]


@pytest.mark.parametrize("value", ["0.0", "-0", "+0.000"])
def test_all_numeric_zero_spellings_remain_protected(value):
    inventory, sources, source = _case(
        "ai_regional_objectives",
        "weight",
        f"weight={{value={value}}}",
    )
    row = native_treatments(
        inventory,
        sources,
        {source: b"candidate={weight={value=1}}"},
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["native_terminal"] == "zero"
    assert row["status"] == "changed_native"


def test_base_zero_alone_is_protected_but_conditional_additions_are_not_flattened():
    inventory, sources, source = _case(
        "scripted_buttons", "ai_chance", "ai_chance={base=0}", operation="chance"
    )
    changed = {source: b"candidate={ai_chance={base=100}}"}
    row = native_treatments(inventory, sources, changed, coverage=_coverage(inventory))["rows"][0]
    assert row["native_terminal"] == "zero"
    assert not row["implemented_numeric"]
    inventory, sources, _ = _case(
        "scripted_buttons",
        "ai_chance",
        "ai_chance={base=0 modifier={trigger={has_variable=actual} add=10}}",
        operation="chance",
    )
    assert native_treatments(inventory, sources, sources)["rows"][0]["native_terminal"] is None


@pytest.mark.parametrize("invalid_complete", ["false", 1, None])
def test_boolean_manifest_and_duplicate_inventory_ids_are_explicit_contracts(invalid_complete):
    inventory, sources, _ = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    with pytest.raises(ValueError, match="boolean"):
        native_treatments(inventory, sources, {}, production_complete=invalid_complete)
    inventory = replace(inventory, surfaces=inventory.surfaces * 2)
    with pytest.raises(ValueError, match="IDs"):
        native_treatments(inventory, sources, sources)


def test_scalar_alias_between_native_and_production_rejected():
    inventory, sources, source = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    with pytest.raises(ValueError, match="path alias"):
        native_treatments(inventory, sources, {source.upper(): sources[source]})


def test_numeric_coverage_cannot_license_a_boolean_expression():
    inventory, sources, source = _case("ai_regional_objectives", "weight", "weight={value=10}")
    row = native_treatments(
        inventory,
        sources,
        {source: b"candidate={weight={always=yes}}"},
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["status"] == "changed_native"
    assert "generated_numeric_shape_unproven" in row["issues"]


def test_nonordinary_native_definition_or_stale_line_never_retained():
    inventory, sources, source = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    raw = sources[source].replace(b"candidate =", b"REPLACE:candidate =")
    inventory = replace(inventory, source_hashes={source: hashlib.sha256(raw).hexdigest()})
    assert (
        native_treatments(inventory, {source: raw}, {source: raw})["rows"][0]["status"]
        == "missing_evidence"
    )
    inventory, sources, source = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    inventory = replace(inventory, surfaces=(replace(inventory.surfaces[0], source_line=99),))
    assert (
        "native_source_line_mismatch"
        in native_treatments(inventory, sources, sources)["rows"][0]["issues"]
    )


def test_original_order_is_part_of_qualification_contract():
    inventory, sources, source = _case(
        "company_types",
        "ai_will_do",
        "ai_will_do={has_variable=one has_variable=two}",
    )
    generated = {source: b"candidate={ai_will_do={has_variable=two has_variable=one}}"}
    row = native_treatments(inventory, sources, generated)["rows"][0]
    assert row["status"] == "changed_native"
    assert row["native_ast_sha256"] != row["effective_ast_sha256"]


def test_native_internal_comparison_is_observed_without_becoming_a_writer():
    inventory, sources, _ = _case(
        "company_types",
        "ai_construction_targets.building_mine.state_trigger.level",
        "ai_construction_targets={building_mine={state_trigger={level > 3}}}",
        operation="read",
        capability="observation",
    )
    row = native_treatments(inventory, sources, sources)["rows"][0]
    assert row["status"] == "needs_review"
    assert row["ast_status"] == "retained"
    assert not row["implemented_numeric"]


@pytest.mark.integration
def test_full_first_batch_against_installed_native_declarations(installed_inventory):
    inventory = installed_inventory
    families = {
        "modifier_type_definitions",
        "company_types",
        "country_creation",
        "country_formation",
        "ai_regional_objectives",
    }
    selected = tuple(
        surface for surface in inventory.surfaces if surface.source.split("/")[-2] in families
    )
    inventory = replace(inventory, surfaces=selected)
    sources = {
        source: (config.GAME / Path(source)).read_bytes()
        for source in {surface.source for surface in selected}
    }
    report = native_treatments(inventory, sources, {}, production_complete=True)
    assert report["denominator"] == len(selected)
    assert {row["declaration_id"] for row in report["rows"]} == {
        surface.declaration_id for surface in selected
    }
    counts = report["interface_counts"]
    current = version_contracts.is_115()
    # Independent native AST counts retain the historical denominator too.
    assert counts["static_modifier_valuation"] == (2291 if current else 2197)
    assert counts["static_construction_cap"] == (271 if current else 261)
    assert counts["lifecycle_effect"] == 12
    assert counts["completion_observation"] == (8 if current else 5)
    gates = [row for row in report["rows"] if row["interface_kind"] == "eligibility"]
    for family, expected in [
        ("company_types", 231 if current else 221),
        ("country_creation", 394),
        ("country_formation", 74 if current else 73),
    ]:
        assert sum(row["source"].split("/")[-2] == family for row in gates) == expected
    assert sum(row["native_terminal"] == "always_false" for row in gates) == 398
    assert report["counts"]["changed_native"] == 0
    assert report["counts"]["missing_evidence"] == 0
    assert report["counts"]["implemented_numeric"] == 0
    assert not report["business_complete"]


def _neutral_case(family="laws"):
    field = "ai_enact_weight_modifier" if family == "laws" else "interest_group_government_weight"
    inventory, sources, source = _case(
        family,
        field,
        f"{field}={{value=0}}",
        operation="additive_score",
    )
    row = replace(inventory.surfaces[0], target_scope="scope:law=law")
    if family == "ai_strategies":
        destination = "common/ai_strategies/00_default_strategy.txt"
        raw = sources[source].replace(b"candidate", b"ai_strategy_default")
        sources = {destination: raw}
        source = destination
        row = replace(
            row,
            source=source,
            definition="ai_strategy_default",
            target_scope="scope:interest_group=interest_group",
        )
    inventory = replace(
        inventory,
        surfaces=(row,),
        source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
    )
    return inventory, sources, source


@pytest.mark.parametrize("family", ["laws", "ai_strategies"])
def test_documented_additive_neutral_zero_can_reduce_the_base_score(family):
    inventory, sources, source = _neutral_case(family)
    generated = {source: sources[source].replace(b"value=0", b"value=0 add=-10")}
    row = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))["rows"][0]
    # Native base 100 + native modifier 0 = 100; new modifier 0 - 10 gives 90.
    assert 100 + (0 - 10) == 90
    assert row["native_terminal"] == "neutral_zero"
    assert row["status"] == "implemented_numeric"
    assert "native_zero_changed_unproven" not in row["issues"]
    assert not row["business_complete"]


@pytest.mark.parametrize("tail", ["value=10 multiply=0", "value=10 value=0"])
def test_additive_field_does_not_waive_an_explicit_zero_tail(tail):
    inventory, sources, source = _neutral_case()
    raw = sources[source].replace(b"value=0", tail.encode())
    sources = {source: raw}
    inventory = replace(inventory, source_hashes={source: hashlib.sha256(raw).hexdigest()})
    row = native_treatments(
        inventory,
        sources,
        {
            source: raw.replace(tail.encode(), b"value=100"),
        },
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["native_terminal"] == "zero"
    assert row["status"] == "changed_native"


@pytest.mark.parametrize("fault", ["operation", "actor", "target", "field", "source"])
def test_neutral_zero_permission_is_not_inferred_from_a_zero_or_field_name(fault):
    inventory, sources, source = _neutral_case()
    surface = inventory.surfaces[0]
    if fault == "operation":
        surface = replace(surface, operation="chance")
    elif fault == "actor":
        surface = replace(surface, actor_scope="state")
    elif fault == "target":
        surface = replace(surface, target_scope="none")
    elif fault == "field":
        surface = replace(surface, field="ai_weight")
        sources = {source: sources[source].replace(b"ai_enact_weight_modifier", b"ai_weight")}
    else:
        destination = "common/buildings/fixture.txt"
        sources = {destination: sources[source]}
        source = destination
        surface = replace(surface, source=source)
    inventory = replace(
        inventory,
        surfaces=(surface,),
        source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
    )
    row = native_treatments(
        inventory,
        sources,
        {
            source: sources[source].replace(b"value=0", b"value=100"),
        },
        coverage=_coverage(inventory),
    )["rows"][0]
    assert row["native_terminal"] == "zero"
    assert not row["implemented_numeric"]


def _fleet_case():
    adapters = decision_adapters
    field = ".".join(adapters._FLEET_FIELD[1:])
    inventory, sources, old_source = _case(
        "ai_strategies",
        field,
        "fleet_compositions={secondary_fleet={mission_type_weights={protect_supply=1.0}}}",
        operation="multiplicative_score",
    )
    source = adapters._FLEET_SOURCE
    raw = sources[old_source].replace(b"candidate", adapters._FLEET_FIELD[0].encode())
    surface = replace(inventory.surfaces[0], source=source, definition=adapters._FLEET_FIELD[0])
    inventory = replace(
        inventory, surfaces=(surface,), source_hashes={source: hashlib.sha256(raw).hexdigest()}
    )
    generated = {
        source: raw.replace(
            b"protect_supply=1.0", f"protect_supply={adapters._FLEET_VALUE}".encode()
        ),
        adapters._VALUE_SOURCE: f"{adapters._FLEET_VALUE}={{value=1.0 multiply=0.8}}".encode(),
    }
    return inventory, {source: raw}, generated


def test_registered_external_fleet_value_is_resolved_to_its_actual_generated_ast():
    inventory, sources, generated = _fleet_case()
    row = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))["rows"][0]
    assert 1.0 * 0.8 == 0.8
    assert row["status"] == "implemented_numeric"
    assert row["resolved_numeric_value"]["source"] == decision_adapters._VALUE_SOURCE
    assert row["resolved_numeric_value"]["definition"] == decision_adapters._FLEET_VALUE
    assert len(row["resolved_numeric_value"]["ast_sha256"]) == 64
    assert (
        row["resolved_numeric_value"]["source_sha256"]
        == hashlib.sha256(generated[decision_adapters._VALUE_SOURCE]).hexdigest()
    )


def test_registered_fleet_value_supports_nested_literal_math_with_native_trigger_readers():
    inventory, sources, generated = _fleet_case()
    helper = decision_adapters._VALUE_SOURCE
    generated[helper] = (
        decision_adapters._FLEET_VALUE.encode()
        + b"""={
        value=1
        if={limit={exists=ROOT ROOT={is_ai=yes navy_size>0}}
            multiply={value=1 add={value=0
                if={limit={ROOT={is_at_war=yes}} add=0.25}
                else_if={limit={ROOT={navy_size>10}} add=0.1}}
                min=1 max=1.25}}
    }"""
    )
    first = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))["rows"][
        0
    ]
    assert first["status"] == "implemented_numeric"
    generated[helper] = generated[helper].replace(b"add=0.25", b"add=0.15")
    second = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))[
        "rows"
    ][0]
    assert second["status"] == "implemented_numeric"
    assert (
        first["resolved_numeric_value"]["ast_sha256"]
        != second["resolved_numeric_value"]["ast_sha256"]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "wrong_name",
        "quoted",
        "wrong_field",
        "wrong_source",
        "empty",
        "duplicate",
        "shadow",
        "direct_cycle",
        "indirect_cycle",
        "unresolved_math",
        "malformed",
        "alias",
        "nested_alias",
        "scalar_helper",
        "prefixed_helper",
        "family_parse_failure",
    ],
)
def test_registered_fleet_resolution_rejects_unproven_source_identity_and_dependency(fault):
    inventory, sources, generated = _fleet_case()
    adapters = decision_adapters
    source, helper = adapters._FLEET_SOURCE, adapters._VALUE_SOURCE
    name = adapters._FLEET_VALUE.encode()
    if fault == "missing":
        del generated[helper]
    elif fault == "wrong_name":
        generated[source] = generated[source].replace(name, b"invented_value")
    elif fault == "quoted":
        generated[source] = generated[source].replace(name, b'"' + name + b'"')
    elif fault in {"wrong_field", "wrong_source"}:
        surface = inventory.surfaces[0]
        if fault == "wrong_field":
            sources[source] = sources[source].replace(b"protect_supply", b"raid_supply")
            generated[source] = generated[source].replace(b"protect_supply", b"raid_supply")
            surface = replace(surface, field=surface.field.replace("protect_supply", "raid_supply"))
        else:
            destination = "common/ai_strategies/other.txt"
            sources = {destination: sources[source]}
            generated[destination] = generated.pop(source)
            surface = replace(surface, source=destination)
        inventory = replace(
            inventory,
            surfaces=(surface,),
            source_hashes={key: hashlib.sha256(raw).hexdigest() for key, raw in sources.items()},
        )
    elif fault == "empty":
        generated[helper] = name + b"={}"
    elif fault == "duplicate":
        generated[helper] *= 2
    elif fault == "shadow":
        generated["common/script_values/shadow.txt"] = generated[helper]
    elif fault == "direct_cycle":
        generated[helper] = name + b"={value=" + name + b"}"
    elif fault == "indirect_cycle":
        generated[helper] = (
            name
            + b"={value=1 if={limit={other_value>0} multiply=0.8}} other_value={value="
            + name
            + b"}"
        )
    elif fault == "unresolved_math":
        generated[helper] = name + b"={value=unproven_value}"
    elif fault == "alias":
        generated[helper] = name + b"={value=another_value} another_value={value=1}"
    elif fault == "nested_alias":
        generated[helper] = (
            name
            + b"={value=1 if={limit={always=yes} multiply={value=another_value}}} another_value={value=1}"
        )
    elif fault == "scalar_helper":
        generated[helper] = name + b"=1"
    elif fault == "prefixed_helper":
        generated[helper] = b"REPLACE:" + generated[helper]
    elif fault == "family_parse_failure":
        generated["common/script_values/ambiguous.txt"] = b"another_value={"
    else:
        generated[helper] = name + b"={"
    row = native_treatments(inventory, sources, generated, coverage=_coverage(inventory))["rows"][0]
    assert row["status"] == "needs_review"
    assert "native_dependency_unproven" in row["issues"]
    assert "generated_numeric_shape_unproven" in row["issues"]
    assert row["dependencies"]
    assert not row["implemented_numeric"]
