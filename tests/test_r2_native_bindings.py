"""R2 interface proof needs actual ASTs and native bytes, not metadata claims."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import version_contracts
from pdx.parser import parse_text
from pdx.situated import domain_coverage, network_profile, production_profile, r2_native
from pdx.situated.native_treatments import _AuditMetadata, _kind, native_treatments
from pdx.situated.profile_configuration import ProfileConfiguration
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface, _road_maintenance_scope

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def current_version():
    with version_contracts.select_version("1.15.1"):
        yield


def _candidate(configuration):
    root = production_profile.baseline_root()
    profile = production_profile.load_profile(root)
    originals = {
        row.source.removeprefix("game/"): (root / row.source).read_bytes()
        for row in profile.declarations
    }
    generated = {name: raw.decode("utf-8-sig") for name, raw in originals.items()}
    network = network_profile.compose(generated, profile, configuration=configuration)
    generated[".metadata/metadata.json"] = json.dumps(
        {"action_network": network, "configuration": configuration.identity()}
    )
    return profile, originals, generated


@pytest.fixture(scope="module")
def candidate():
    return _candidate(ProfileConfiguration())


def test_three_actual_outputs_bind_and_metadata_projection_keeps_their_configuration(candidate):
    profile, originals, generated = candidate
    raw = generated[".metadata/metadata.json"]
    metadata = _AuditMetadata(raw)
    assert set(metadata.document(raw)) == {"action_network", "configuration"}
    bindings = r2_native.production_bindings(generated, originals, metadata=metadata)
    assert {item.consumer for item in bindings} == set(profile.consumer_ids)
    assert len(bindings) == 3
    for binding in bindings:
        assert (
            binding.production_sha256
            == hashlib.sha256(generated[binding.source].encode()).hexdigest()
        )
        assert binding.native_sha256 == hashlib.sha256(originals[binding.source]).hexdigest()
        assert binding.native_ast_sha256 != binding.effective_ast_sha256
        assert binding.reader_evidence


@pytest.mark.parametrize("consumer", ["a0-econ-road", "a0-pol-schools", "a0-dip-relations"])
@pytest.mark.parametrize(
    "damage", ["metadata", "overlay", "native_tail", "duplicate", "moved", "native_input"]
)
def test_claims_cannot_hide_changed_expression_tail_source_or_order(candidate, consumer, damage):
    profile, original_sources, original_generated = candidate
    originals, generated = dict(original_sources), dict(original_generated)
    row = next(item for item in profile.declarations if item.id == consumer)
    source = row.source.removeprefix("game/")
    content = generated[source]
    begin = f"\n\t# SITAI POLICY 1.15.1 BEGIN {consumer}\n"
    end = f"\t# SITAI POLICY 1.15.1 END {consumer}\n"
    start, stop = content.index(begin), content.index(end) + len(end)
    marker = content[start:stop]
    if damage == "metadata":
        metadata = json.loads(generated[".metadata/metadata.json"])
        metadata["action_network"]["writers"][0]["enabled"] = False
        generated[".metadata/metadata.json"] = json.dumps(metadata)
    elif damage == "overlay":
        generated[source] = (
            content[:start] + marker.replace("value = 0", "value = 1", 1) + content[stop:]
        )
    elif damage == "native_tail":
        literal = {
            "a0-econ-road": "value = 25",
            "a0-pol-schools": "value = 10",
            "a0-dip-relations": "value = 5",
        }[consumer]
        # Change inside the exact selected consumer, leaving valid syntax and
        # all metadata/output declarations intact.
        node = r2_native._node(content, (row.definition, *row.field))
        lines = content.splitlines(keepends=True)
        offset = sum(len(line) for line in lines[: node.line])
        generated[source] = content[:offset] + content[offset:].replace(literal, literal + "9", 1)
    elif damage == "duplicate":
        generated[source] = content[:stop] + marker + content[stop:]
    elif damage == "moved":
        restored = content[:start] + content[stop:]
        node = r2_native._node(restored, (row.definition, *row.field))
        lines = restored.splitlines(keepends=True)
        # Move road after its original tail; move the others before their base.
        offset = sum(len(line) for line in lines[: node.line])
        # Placing road before value resets the contribution; the other two
        # append after the native body, so this also changes their legal order.
        generated[source] = restored[:offset] + marker + restored[offset:]
    else:
        originals[source] += b"\n# unreviewed native input\n"
    with pytest.raises(ValueError):
        r2_native.production_bindings(generated, originals)


def test_missing_candidate_metadata_and_false_disabled_claims_fail(candidate):
    _, originals, generated = candidate
    missing = {**generated, ".metadata/metadata.json": "{}"}
    with pytest.raises(ValueError, match="without its candidate declaration"):
        r2_native.production_bindings(missing, originals)
    _, disabled_native, disabled = _candidate(ProfileConfiguration(core=False))
    assert r2_native.production_bindings(disabled, disabled_native) == ()
    source = "common/decrees/00_decree.txt"
    disabled[source] = generated[source]
    with pytest.raises(ValueError, match="disabled writer"):
        r2_native.production_bindings(disabled, disabled_native)


def test_exact_road_scope_never_promotes_another_decree_or_changed_original(candidate):
    _, originals, _ = candidate
    source = "common/decrees/00_decree.txt"
    parsed = parse_text(originals[source].decode("utf-8-sig"))
    road = parsed.root.first("decree_road_maintenance")
    assert road is not None
    scope = _road_maintenance_scope(originals, road, source)
    assert (scope.actor, scope.target, scope.operation, scope.capability) == (
        "state",
        "scope:country=country",
        "relative_weight",
        "direct",
    )
    other = parsed.root.first("decree_violent_suppression")
    assert other is not None
    assert _road_maintenance_scope(originals, other, source).capability == "pending"
    assert (
        _road_maintenance_scope(
            {**originals, source: originals[source] + b"\n"}, road, source
        ).capability
        == "pending"
    )
    assert (
        _road_maintenance_scope(originals, replace(road, key="invented"), source).capability
        == "pending"
    )


def _inventory(bindings, originals):
    contexts = {
        "a0-econ-road": ("state", "scope:country=country", "relative_weight"),
        "a0-pol-schools": ("country", "definition_only:institution_type", "additive_score"),
        "a0-dip-relations": ("country", "scope:target=country", "score"),
    }
    surfaces = tuple(
        VanillaSurface(
            surface_id=binding.consumer,
            source=binding.source,
            definition=binding.definition,
            field=binding.field,
            actor_scope=contexts[binding.consumer][0],
            target_scope=contexts[binding.consumer][1],
            operation=contexts[binding.consumer][2],
            capability="direct",
            status="pending",
            getter=None,
            getter_note="fixture static context, no runtime claim",
            scope_evidence=(f"{binding.source}:{binding.source_line}",),
            responsibility_step="D0",
            source_line=binding.source_line,
        )
        for binding in bindings
    )
    return VanillaInventory(
        "fixture",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in originals.items()},
        "b" * 64,
        surfaces,
        (),
        ("game",),
        3,
    )


def test_exact_coverage_joins_three_interfaces_without_changing_native_denominator(candidate):
    _, originals, generated = candidate
    bindings = r2_native.production_bindings(generated, originals)
    inventory = _inventory(bindings, originals)
    report = domain_coverage.native_coverage(
        inventory, (), native_sources=originals, network_programs=bindings
    )
    assert report["denominator"] == inventory.discovered_count == 3
    assert report["counts"]["actual_covered"] == 3
    assert report["binding_issue_count"] == 0
    assert {row["covered_actions"][0] for row in report["rows"]} == {
        item.consumer for item in bindings
    }
    for surface, binding in zip(inventory.surfaces, bindings, strict=True):
        native = r2_native._node(
            originals[binding.source].decode("utf-8-sig"),
            (binding.definition, *binding.field.split(".")),
        )
        assert _kind(surface, native) == "dynamic_numeric"
        for damaged in (
            replace(surface, actor_scope="unknown"),
            replace(surface, target_scope="none"),
            replace(surface, source_line=surface.source_line + 1),
            replace(surface, capability="pending"),
        ):
            assert r2_native.native_issue(binding, damaged) is not None


def test_valid_r2_expression_cannot_mask_a_changed_native_decree_cost(candidate):
    _, originals, generated = candidate
    changed = dict(generated)
    source = "common/decrees/00_decree.txt"
    changed[source] = changed[source].replace("cost = 100", "cost = 101", 1)
    bindings = r2_native.production_bindings(changed, originals)
    # Binding one numeric leaf licenses only that leaf. The normal native
    # treatment must still reject changed costs/siblings in the complete file.
    inventory = _inventory(bindings, originals)
    coverage = domain_coverage.native_coverage(
        inventory, (), native_sources=originals, network_programs=bindings
    )
    report = native_treatments(
        inventory,
        originals,
        {name: value.encode() for name, value in changed.items()},
        coverage=coverage,
        production_complete=True,
    )
    road = next(row for row in report["rows"] if row["source"] == source)
    assert road["source_protection"]["context_closed"] is False
    assert road["active_unknown_usage"] is True
    assert "native_companion_changed:cost" in road["issues"]
