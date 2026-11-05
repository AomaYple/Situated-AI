"""Continuous support mappings attest actual metadata and output, not invented cards."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from pdx import config, decision_adapters, decisions, distribution, equipment_opportunities
from pdx.model import Block
from pdx.situated import audit, domain_coverage, vanilla_inventory
from pdx.situated.decision_ir import (
    ConsumerIRBundle,
    ContextBinding,
    EvaluationContext,
    WriterDecisionIR,
)
from pdx.situated.support_program import SupportProgram

pytestmark = pytest.mark.unit

SOURCE = "common/ai_strategies/00_default_strategy.txt"


def test_continuous_program_api_keeps_empty_independent_denominator():
    scope = vanilla_inventory.VanillaInventory("fixture", {}, "scope", (), (), (), 0)
    report = domain_coverage.native_coverage(scope, (), continuous_programs=())
    assert report["denominator"] == 0
    assert report["continuous_programs"] == []


@pytest.fixture(scope="module")
def real_production():
    return distribution.package_inputs(include_engineering_metadata=True)[2]


@pytest.fixture(scope="module")
def controlled_output():
    """A declared unit fixture; the separate integration test must prove build()."""
    extra = replace(decisions.Extensions(), market_enabled=True, security_enabled=True)
    program = SupportProgram.from_extensions(extra)
    source = "research/vanilla-ai/1.15.0/00_default_strategy.txt"
    writer = WriterDecisionIR(
        writer_id=program.writer_id,
        kind="support_program",
        source="mod/decisions/extensions.toml",
        definition=program.writer_id,
        consumer_id="diplomatic_play_support",
        field="diplomatic_play_support",
        actor="root",
        target="target_country",
        operation="add",
        vanilla_tail="preserve",
        owner="situated_kernel",
        program=program,
        evaluation_context=EvaluationContext(
            actor_scope=ContextBinding("root", "country", "actor", source, 210),
            targets=(
                ContextBinding("target_country", "country", "target", source, 211),
                ContextBinding("enemy_country", "country", "target", source, 212),
            ),
            evidence=tuple(f"{source}:{line}" for line in (210, 211, 212)),
        ),
    )
    metadata = {
        "situated_actions": {"consumer_ir": ConsumerIRBundle(1, (), (writer,)).as_dict()},
        "default_field_owners": {"diplomatic_play_support": "situated_kernel"},
    }
    return {
        SOURCE: decisions.patch_default(
            decisions.BASELINE.read_text(encoding="utf-8"),
            replace(decisions.load(), enabled=False),
            extra,
        ),
        ".metadata/metadata.json": json.dumps(metadata),
    }


@pytest.mark.integration
def test_real_build_program_has_an_exact_native_mapping(real_production, real_native_scope):
    scope, sources = real_native_scope
    report = domain_coverage.native_coverage(
        scope,
        (),
        native_sources=sources,
        continuous_programs=audit._production_continuous_bindings(real_production),
    )
    assert report["counts"]["actual_covered"] == 1
    assert report["denominator"] == 1


def _native_scope(getter: bytes):
    raw = b"\xef\xbb\xbf" + decisions.BASELINE.read_bytes()
    parsed = vanilla_inventory.parse_bytes(raw, path=SOURCE)
    strategy = parsed.root.first("ai_strategy_default")
    assert strategy is not None
    assert isinstance(strategy.value, Block)
    support = strategy.value.first("diplomatic_play_support")
    assert support is not None
    assert isinstance(support.value, Block)
    surface = vanilla_inventory.VanillaSurface(
        surface_id="support",
        source=SOURCE,
        definition="ai_strategy_default",
        field="diplomatic_play_support",
        actor_scope="country",
        target_scope="scope:country=country;scope:enemy_country=country",
        operation="additive_score",
        capability="direct",
        status="pending",
        getter=None,
        getter_note="consumer is not a getter",
        scope_evidence=(f"{SOURCE}:{support.line}",),
        responsibility_step="S3",
        source_line=support.line,
    )
    getter_source = "common/script_values/01_power_bloc_values.txt"
    sources = {SOURCE: raw, getter_source: getter}
    scope = vanilla_inventory.VanillaInventory(
        "locked-support-fixture",
        {source: hashlib.sha256(value).hexdigest() for source, value in sources.items()},
        "independent-scope",
        (surface,),
        ("ai_strategies", "script_values"),
        ("game",),
        2,
    )
    return scope, sources


@pytest.fixture
def native_scope(monkeypatch):
    """Synthetic getter and its pin exercise checks without claiming native evidence."""
    getter_source = "common/script_values/01_power_bloc_values.txt"
    # The production binding contract requires the call at line 30. This is a
    # deliberately synthetic source; only this fixture's proof pin is replaced.
    getter = b"\n" * 28 + (
        b'fixture = {\n    multiply = "scope:target.economic_dependence(ROOT)"\n}\n'
    )
    baseline = copy.deepcopy(equipment_opportunities.load_baseline())
    baseline["sources"][getter_source] = hashlib.sha256(getter).hexdigest()
    monkeypatch.setattr(equipment_opportunities, "load_baseline", lambda: baseline)
    return _native_scope(getter)


@pytest.fixture
def real_native_scope():
    """The integration test retains the actual source and unmodified production pin."""
    getter_source = "common/script_values/01_power_bloc_values.txt"
    return _native_scope((config.GAME / getter_source).read_bytes())


def test_controlled_program_maps_without_fabricating_an_action(controlled_output, native_scope):
    programs = audit._production_continuous_bindings(controlled_output)
    assert len(programs) == 1
    assert programs[0].writer.kind == "support_program"
    scope, sources = native_scope
    report = domain_coverage.native_coverage(
        scope, (), native_sources=sources, continuous_programs=programs
    )
    assert report["denominator"] == scope.discovered_count == 1
    assert report["counts"]["actual_covered"] == 1, report["rows"][0]["binding_issues"]
    assert report["rows"][0]["covered_actions"] == ["diplomatic_play_support_program"]
    assert report["continuous_programs"][0]["binding_status"] == "interface_bound"
    assert report["continuous_programs"][0]["business_complete"] is False


def test_report_consumes_same_package_metadata_and_keeps_its_output_hashes(
    controlled_output, native_scope, tmp_path, monkeypatch
):
    scope, sources = native_scope
    game = tmp_path / "game"
    for source, raw in sources.items():
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    monkeypatch.setattr(config, "GAME", game)

    def package_inputs(*, include_engineering_metadata=False):
        assert include_engineering_metadata is True
        return None, None, controlled_output

    monkeypatch.setattr(distribution, "package_inputs", package_inputs)
    monkeypatch.setattr(audit, "load_model", lambda: SimpleNamespace(action_instances=()))
    monkeypatch.setattr(audit.vanilla_inventory, "discover", lambda: scope)
    monkeypatch.setattr(decision_adapters, "load", lambda: SimpleNamespace(policies=()))
    captured: dict[str, Any] = {}

    def treatments(inventory, native, outputs, **kwargs):
        captured.update(outputs=outputs, coverage=kwargs["coverage"])
        return {"denominator": inventory.discovered_count, "business_complete": False}

    monkeypatch.setattr(audit.native_treatments, "native_treatments", treatments)
    monkeypatch.setattr(
        audit.business_review,
        "review",
        lambda *_args, **_kwargs: {"business_complete": False},
    )
    result = audit.native_report()
    assert result["production_output_contract"] == {
        "mode": "engineering_package_inputs",
        "include_engineering_metadata": True,
        "hash_scope": "same_invocation_outputs_including_engineering_metadata",
        "standard_zip_manifest": False,
        "standard_package_difference": "metadata_json_is_full_engineering_metadata",
    }
    coverage = result["native_coverage"]
    assert isinstance(coverage, dict)
    assert coverage["counts"]["actual_covered"] == 1
    program = coverage["continuous_programs"][0]
    assert (
        program["production_sha256"]
        == hashlib.sha256(controlled_output[SOURCE].encode()).hexdigest()
    )
    assert (
        program["metadata_sha256"]
        == hashlib.sha256(controlled_output[".metadata/metadata.json"].encode()).hexdigest()
    )
    assert captured["outputs"][SOURCE] == controlled_output[SOURCE].encode()
    assert captured["coverage"] is coverage


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "field",
        "actor",
        "targets",
        "operation",
        "program",
        "body",
        "owner",
        "missing_writer",
        "duplicate_writer",
    ],
)
def test_actual_output_contract_rejects_a_tampered_support_writer(controlled_output, fault):
    generated = copy.deepcopy(controlled_output)
    metadata = json.loads(generated[".metadata/metadata.json"])
    bundle = metadata["situated_actions"]["consumer_ir"]
    writer = next(w for w in bundle["writers"] if w["kind"] == "support_program")
    if fault == "source":
        writer["source"] = "mod/decisions/actions.toml"
    elif fault == "field":
        writer["field"] = "recklessness"
    elif fault == "actor":
        writer["actor"] = "owner"
    elif fault == "targets":
        writer["evaluation_context"]["targets"] = []
    elif fault == "operation":
        writer["operation"] = "multiply"
    elif fault == "program":
        writer["program"]["single_clamp"] = False
    elif fault == "body":
        generated[SOURCE] = generated[SOURCE].replace("max = 50", "max = 49")
    elif fault == "owner":
        writer["owner"] = "legacy_support"
    elif fault == "missing_writer":
        bundle["writers"].remove(writer)
    else:
        bundle["writers"].append(copy.deepcopy(writer))
    generated[".metadata/metadata.json"] = json.dumps(metadata)
    with pytest.raises(ValueError, match=r"连续|支持"):
        audit._production_continuous_bindings(generated)


@pytest.mark.parametrize("fault", ["source", "field", "unit", "native_operation", "targets"])
def test_continuous_interface_never_grants_a_wrong_native_contract(
    controlled_output, native_scope, fault
):
    binding = audit._production_continuous_bindings(controlled_output)[0]
    scope, sources = native_scope
    if fault in {"source", "field"}:
        binding = replace(
            binding,
            native=replace(
                binding.native,
                **{
                    fault: "common/ai_strategies/other.txt" if fault == "source" else "recklessness"
                },
            ),
        )
    elif fault == "unit":
        binding = replace(binding, unit="probability")
    elif fault == "native_operation":
        scope = replace(scope, surfaces=(replace(scope.surfaces[0], operation="override"),))
    else:
        scope = replace(scope, surfaces=(replace(scope.surfaces[0], target_scope="none"),))
    report = domain_coverage.native_coverage(
        scope, (), native_sources=sources, continuous_programs=(binding,)
    )
    assert report["counts"]["actual_covered"] == 0
    assert not report["binding_complete"]


def test_disabled_output_does_not_register_a_continuous_writer():
    assert (
        audit._production_continuous_bindings({".metadata/metadata.json": '{"id":"situated-ai"}'})
        == ()
    )


@pytest.mark.parametrize("fault", ["getter_missing", "getter_drift", "native_hash", "native_actor"])
def test_frozen_input_contract_does_not_borrow_production_claims(
    controlled_output, native_scope, fault
):
    programs = audit._production_continuous_bindings(controlled_output)
    scope, native = native_scope
    sources = dict(native)
    getter_source = "common/script_values/01_power_bloc_values.txt"
    if fault == "getter_missing":
        sources.pop(getter_source)
    elif fault == "getter_drift":
        sources[getter_source] += b"\n# changed frozen native\n"
        scope = replace(
            scope,
            source_hashes={
                **scope.source_hashes,
                getter_source: hashlib.sha256(sources[getter_source]).hexdigest(),
            },
        )
    elif fault == "native_hash":
        sources[SOURCE] += b"\n# changed frozen native\n"
        scope = replace(
            scope,
            source_hashes={
                **scope.source_hashes,
                SOURCE: hashlib.sha256(sources[SOURCE]).hexdigest(),
            },
        )
    else:
        scope = replace(scope, surfaces=(replace(scope.surfaces[0], actor_scope="state"),))
    report = domain_coverage.native_coverage(
        scope, (), native_sources=sources, continuous_programs=programs
    )
    assert report["counts"]["actual_covered"] == 0
    assert report["binding_issue_count"] == 1


@pytest.mark.parametrize("fault", ["duplicate_body", "unmarked_write", "owner_map", "getter"])
def test_unregistered_body_and_metadata_claims_are_explicit_failures(controlled_output, fault):
    generated = copy.deepcopy(controlled_output)
    metadata = json.loads(generated[".metadata/metadata.json"])
    if fault == "duplicate_body":
        source = generated[SOURCE]
        start = source.index("\t\t# SITAI BEGIN diplomatic_play_support\n")
        end = source.index("\t\t# SITAI END diplomatic_play_support\n", start)
        end += len("\t\t# SITAI END diplomatic_play_support\n")
        generated[SOURCE] += source[start:end]
    elif fault == "unmarked_write":
        generated[SOURCE] = generated[SOURCE].replace(
            "\t\t# SITAI BEGIN diplomatic_play_support\n",
            "\t\tadd = 1\n\t\t# SITAI BEGIN diplomatic_play_support\n",
        )
    elif fault == "owner_map":
        metadata["default_field_owners"]["diplomatic_play_support"] = "legacy"
    else:
        writer = next(
            row
            for row in metadata["situated_actions"]["consumer_ir"]["writers"]
            if row["kind"] == "support_program"
        )
        writer["program"]["market"]["country_getter"] = "ROOT.gdp"
    generated[".metadata/metadata.json"] = json.dumps(metadata)
    with pytest.raises(ValueError, match=r"连续|支持"):
        audit._production_continuous_bindings(generated)
