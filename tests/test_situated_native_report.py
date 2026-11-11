"""The public native report uses fresh outputs, independent inputs and real joins."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from pdx import cli, config, decision_adapters, decisions, distribution
from pdx.situated import audit
from pdx.situated.action_instances import ActionInstance
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface

if TYPE_CHECKING:
    from typing import Any

pytestmark = pytest.mark.unit


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    game = tmp_path / "game"
    native = {
        "common/company_types/fixture.txt": b"company={ai_weight={value=10} ai_will_do={always=no}}",
        "common/modifier_type_definitions/fixture.txt": b"modifier={game_data={ai_value=0}}",
        "common/company_types/companies.md": b"fixture field documentation\n",
    }
    for source, raw in native.items():
        target = game / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    def surface(source, definition, field, operation, actor="country", capability="direct"):
        return VanillaSurface(
            surface_id=f"{definition}.{field}",
            source=source,
            definition=definition,
            field=field,
            actor_scope=actor,
            target_scope="none",
            operation=operation,
            capability=capability,
            status="pending",
            getter=None,
            getter_note="not a getter",
            scope_evidence=(f"{source}:1",),
            responsibility_step="S4",
            source_line=1,
        )

    surfaces = (
        surface("common/company_types/fixture.txt", "company", "ai_weight", "base_candidate_score"),
        surface("common/company_types/fixture.txt", "company", "ai_will_do", "eligibility"),
        surface(
            "common/modifier_type_definitions/fixture.txt",
            "modifier",
            "game_data.ai_value",
            "modifier_ai_value",
            "global",
            "indirect",
        ),
    )
    scope = VanillaInventory(
        baseline_id="independent-fixture",
        scope_hash="b" * 64,
        source_hashes={
            **{key: hashlib.sha256(raw).hexdigest() for key, raw in native.items()},
            "@engine/fixture.exe": "e" * 64,
        },
        surfaces=surfaces,
        scanned_directories=("company_types", "modifier_type_definitions"),
        content_roots=("game",),
        parsed_files=2,
    )
    instance = ActionInstance(
        action_id="actual_company_preference",
        kind="rule_action",
        source="common/company_types/fixture.txt",
        rule_id="real_material_need",
        domain="industry",
        consumer_field="company.ai_weight",
        operation="multiply",
        value=1.08,
        condition_facts=("known_material_need",),
        owner="actual_owner",
        vanilla_tail="retained",
        evidence=("known_material_need",),
    )
    generated = {
        "common/company_types/fixture.txt": "company={ai_weight={value=10 multiply=1.08} ai_will_do={always=no}}",
        ".metadata/metadata.json": '{"id":"situated-ai"}\n',
        "thumbnail.png": b"\x89PNG\r\n",
    }
    model = SimpleNamespace(action_instances=(instance,))
    monkeypatch.setattr(config, "GAME", game)

    def package_inputs(*, include_engineering_metadata=False):
        assert include_engineering_metadata is True
        return None, None, generated

    monkeypatch.setattr(distribution, "package_inputs", package_inputs)
    monkeypatch.setattr(audit, "load_model", lambda: model)
    monkeypatch.setattr(audit.vanilla_inventory, "discover", lambda: scope)
    monkeypatch.setattr(decision_adapters, "load", lambda: SimpleNamespace(policies=()))
    return SimpleNamespace(
        game=game,
        native=native,
        generated=generated,
        model=model,
        scope=scope,
        source="common/company_types/fixture.txt",
    )


def test_real_join_preserves_independent_denominator_and_current_output_identity(pipeline):
    result = cast("dict[str, Any]", audit.native_report())
    scope, coverage, treatments = (
        result["scope"],
        result["native_coverage"],
        result["native_treatments"],
    )
    assert scope["discovered_count"] == treatments["denominator"] == 3
    assert coverage["counts"]["actual_covered"] == 1
    assert coverage["counts"]["unimplemented_legal"] == 2
    assert treatments["counts"]["implemented_numeric"] == 1
    assert treatments["counts"]["retained_native"] == 2
    assert {row["declaration_id"] for row in treatments["rows"]} == {
        row.declaration_id for row in pipeline.scope.surfaces
    }
    assert treatments["source_hashes_verified"] == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in pipeline.native.items()
    }
    assert treatments["production_hashes"] == {
        name: hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()
        for name, raw in pipeline.generated.items()
    }
    gate = next(row for row in treatments["rows"] if row["field"] == "ai_will_do")
    assert gate["native_terminal"] == "always_false"
    assert gate["status"] == "retained_native"
    assert not result["business_complete"]
    assert not treatments["business_complete"]
    assert result["evidence_category"] == "static_check"


@pytest.mark.parametrize("fault", ["wrong_scope", "wrong_source", "unknown_native_scope"])
def test_real_coverage_rejection_survives_report_facade(pipeline, monkeypatch, fault):
    instance = pipeline.model.action_instances[0]
    if fault == "wrong_scope":
        pipeline.model.action_instances = (replace(instance, actor_scope="state"),)
    elif fault == "wrong_source":
        pipeline.model.action_instances = (
            replace(instance, source="common/company_types/other.txt"),
        )
    else:
        scope = replace(
            pipeline.scope,
            surfaces=(
                replace(pipeline.scope.surfaces[0], actor_scope="unknown"),
                *pipeline.scope.surfaces[1:],
            ),
        )
        monkeypatch.setattr(audit.vanilla_inventory, "discover", lambda: scope)
    result = cast("dict[str, Any]", audit.native_report())
    assert result["native_coverage"]["counts"]["actual_covered"] == 0
    assert result["native_treatments"]["counts"]["implemented_numeric"] == 0
    assert result["native_treatments"]["denominator"] == 3
    if fault == "wrong_scope":
        assert result["native_coverage"]["binding_issue_count"] == 1
    elif fault == "wrong_source":
        assert (
            result["native_coverage"]["unmatched_production"][0]["reason"]
            == "native_surface_missing"
        )
    else:
        assert result["native_treatments"]["counts"]["needs_review"] == 1
        assert result["native_coverage"]["counts"]["unsupported"] == 0


def test_build_is_used_instead_of_stale_mod_files(pipeline, tmp_path, monkeypatch):
    stale = tmp_path / "stale-mod" / pipeline.source
    stale.parent.mkdir(parents=True)
    stale.write_bytes(pipeline.native[pipeline.source])
    monkeypatch.setattr(decisions, "PRODUCT", stale.parents[2])
    result = cast("dict[str, Any]", audit.native_report())
    row = next(row for row in result["native_treatments"]["rows"] if row["field"] == "ai_weight")
    assert row["ast_status"] == "changed"
    assert row["status"] == "implemented_numeric"
    assert stale.read_bytes() == pipeline.native[pipeline.source]


def test_discovery_to_read_source_drift_is_fatal(pipeline):
    (pipeline.game / pipeline.source).write_bytes(pipeline.native[pipeline.source] + b"# drift")
    with pytest.raises(ValueError, match=r"字节不一致|SHA"):
        audit.native_report()


def test_missing_discovered_native_bytes_is_fatal_instead_of_inherited(pipeline):
    (pipeline.game / pipeline.source).unlink()
    with pytest.raises(FileNotFoundError):
        audit.native_report()


@pytest.mark.parametrize("stage", ["build", "discovery", "model", "policy"])
def test_upstream_verification_failures_propagate_without_legacy_fallback(
    pipeline, monkeypatch, stage
):
    def fail(*, include_engineering_metadata=None):
        assert include_engineering_metadata is (True if stage == "build" else None)
        raise ValueError(f"{stage} failed explicitly")

    target, name = {
        "build": (distribution, "package_inputs"),
        "discovery": (audit.vanilla_inventory, "discover"),
        "model": (audit, "load_model"),
        "policy": (decision_adapters, "load"),
    }[stage]
    monkeypatch.setattr(target, name, fail)
    monkeypatch.setattr(audit, "report", lambda: pytest.fail("legacy fallback called"))
    with pytest.raises(ValueError, match=f"{stage} failed explicitly"):
        audit.native_report()


def test_cli_native_option_runs_real_pipeline_and_does_not_call_legacy_report(
    pipeline, tmp_path, monkeypatch
):
    monkeypatch.setattr(audit, "report", lambda: pytest.fail("legacy report called"))
    monkeypatch.setattr(cli.situated, "load_model", lambda: pytest.fail("legacy contract called"))
    target = tmp_path / "native.json"
    result = CliRunner().invoke(
        cli.app, ["situated", "report", "--native", "--output", str(target)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["native_treatments"]["counts"]["implemented_numeric"] == 1
    assert payload["scope"]["discovered_count"] == 3
    assert not payload["business_complete"]


def test_cli_native_error_is_nonzero_and_does_not_overwrite_previous_report(
    pipeline, tmp_path, monkeypatch
):
    def fail(*, include_engineering_metadata=False):
        assert include_engineering_metadata is True
        raise ValueError("native fingerprint drift")

    monkeypatch.setattr(distribution, "package_inputs", fail)
    monkeypatch.setattr(audit, "report", lambda: pytest.fail("legacy fallback called"))
    target = tmp_path / "report.json"
    target.write_text('{"previous":"retained"}\n', encoding="utf-8")
    before = target.read_bytes()
    result = CliRunner().invoke(
        cli.app, ["situated", "report", "--native", "--output", str(target)]
    )
    assert result.exit_code == cli.EXIT_FAILED
    assert "native fingerprint drift" in result.output
    assert "已写入" not in result.output
    assert target.read_bytes() == before


def test_existing_cli_default_path_remains_explicitly_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        audit, "native_report", lambda: pytest.fail("native build unexpectedly called")
    )
    monkeypatch.setattr(
        cli.situated, "load_model", lambda: SimpleNamespace(contract=lambda: {"mode": "legacy"})
    )
    monkeypatch.setattr(
        audit, "report", lambda: SimpleNamespace(as_dict=lambda: {"old_receipt": True})
    )
    target = tmp_path / "legacy.json"
    result = CliRunner().invoke(cli.app, ["situated", "report", "--output", str(target)])
    assert result.exit_code == 0, result.output
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "mode": "legacy",
        "coverage": {"old_receipt": True},
    }


def test_public_report_keeps_fresh_call_order_and_exact_candidate_evaluation(pipeline, monkeypatch):
    calls = []
    original_build = distribution.package_inputs
    original_model = audit.load_model
    original_discover = audit.vanilla_inventory.discover
    original_policies = decision_adapters.load

    def build(*, include_engineering_metadata=False):
        calls.append("build")
        return original_build(include_engineering_metadata=include_engineering_metadata)

    def model():
        calls.append("model")
        return original_model()

    def discover():
        calls.append("discover")
        return original_discover()

    def policies():
        calls.append("policies")
        return original_policies()

    monkeypatch.setattr(distribution, "package_inputs", build)
    monkeypatch.setattr(audit, "load_model", model)
    monkeypatch.setattr(audit.vanilla_inventory, "discover", discover)
    monkeypatch.setattr(decision_adapters, "load", policies)
    public = audit.native_report()
    assert calls == ["build", "model", "discover", "policies"]
    calls.clear()
    generated = {
        name: raw.encode("utf-8") if isinstance(raw, str) else raw
        for name, raw in pipeline.generated.items()
    }
    reused = audit._native_report_from_candidate(pipeline.model, generated)
    assert calls == ["discover", "policies"]
    assert reused == public


@pytest.mark.parametrize("change", ["production", "metadata", "model"])
def test_candidate_report_uses_each_exact_supplied_candidate_without_reuse(pipeline, change):
    generated = {
        name: raw.encode("utf-8") if isinstance(raw, str) else raw
        for name, raw in pipeline.generated.items()
    }
    before = cast("dict[str, Any]", audit._native_report_from_candidate(pipeline.model, generated))
    model = pipeline.model
    if change == "production":
        generated[pipeline.source] += b"\n# another candidate\n"
    elif change == "metadata":
        generated[".metadata/metadata.json"] = b'{"id":"another-candidate"}\n'
    else:
        model = SimpleNamespace(
            action_instances=(replace(pipeline.model.action_instances[0], actor_scope="state"),)
        )
    after = cast("dict[str, Any]", audit._native_report_from_candidate(model, generated))
    assert after["scope"] == before["scope"]
    assert after["native_treatments"]["production_hashes"] == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in generated.items()
    }
    if change == "model":
        assert before["native_coverage"]["counts"]["actual_covered"] == 1
        assert after["native_coverage"]["counts"]["actual_covered"] == 0
        assert after["native_treatments"]["counts"]["implemented_numeric"] == 0
    else:
        assert (
            after["native_treatments"]["production_hashes"]
            != (before["native_treatments"]["production_hashes"])
        )


@pytest.mark.parametrize("fault", ["metadata", "native_drift", "missing_native", "unsafe_path"])
def test_candidate_report_keeps_real_input_rejections(pipeline, fault):
    generated = {
        name: raw.encode("utf-8") if isinstance(raw, str) else raw
        for name, raw in pipeline.generated.items()
    }
    error: type[Exception] = ValueError
    if fault == "metadata":
        generated[".metadata/metadata.json"] = b"not JSON"
    elif fault == "native_drift":
        (pipeline.game / pipeline.source).write_bytes(pipeline.native[pipeline.source] + b"# drift")
    elif fault == "missing_native":
        (pipeline.game / pipeline.source).unlink()
        error = FileNotFoundError
    else:
        generated["../outside.txt"] = b"outside = {}"
    with pytest.raises(error):
        audit._native_report_from_candidate(pipeline.model, generated)
