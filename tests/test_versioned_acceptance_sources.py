"""Current compiler, evidence identity and acceptance contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import config, decisions, version_contracts
from pdx.situated import (
    bindings,
    compatibility_115,
    compiler,
    domain_coverage,
    engine_scope,
    migration_baseline,
    vanilla_inventory,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def current_model():
    return compiler.load_model()


def test_current_ledgers_are_complete():
    rows = bindings.load()
    assert rows == bindings.build()
    assert len(rows) == 5872
    assert any("pm_coal_fired_plant_copper_cost" in row.definition for row in rows)
    assert bindings.check() == domain_coverage.check_counts() == []
    assert len(domain_coverage.load()) == 19


def test_current_contract_refuses_an_incomplete_binding_ledger(tmp_path):
    path = tmp_path / "bindings.toml"
    source = bindings.source_path().read_text(encoding="utf-8")
    first_complete_row, _, _ = source.rpartition("[[bindings]]")
    assert first_complete_row
    path.write_text(first_complete_row, encoding="utf-8")
    with pytest.raises(ValueError, match="绑定目录不完整"):
        bindings.load(path)


def test_current_contexts_use_the_current_binary_identity():
    strategy = compiler._frozen_strategy_contexts()
    context = strategy["recklessness"]
    assert context.actor_scope is not None
    assert context.actor_scope.source == "research/situated/1.15.2/engine-strategy.json"
    assert any("consumer=recklessness:va=0x14184c11f" in item for item in context.evidence)
    company = compiler._frozen_company_context()
    assert company.actor_scope is not None
    assert company.actor_scope.source == "research/situated/1.15.2/engine-company.json"


@pytest.mark.integration
def test_support_context_locates_current_field_comments():
    current = compiler.support_evaluation_context()
    assert current.actor_scope is not None
    assert current.actor_scope.source == version_contracts.DEFAULT_STRATEGY_SOURCE
    assert current.actor_scope.line == 210
    assert tuple(row.line for row in current.targets) == (211, 212)


@pytest.mark.integration
def test_changed_installed_baseline_bytes_cannot_borrow_scope_proof(tmp_path, monkeypatch):
    original = compiler.baseline_path()
    damaged = tmp_path / version_contracts.DEFAULT_STRATEGY_SOURCE
    damaged.parent.mkdir(parents=True)
    damaged.write_bytes(original.read_bytes() + b"\n")
    monkeypatch.setattr(config, "GAME", tmp_path)
    with pytest.raises(ValueError, match="默认策略原始字节漂移"):
        compiler.support_evaluation_context()


def test_release_model_and_metadata_use_verified_structure_without_installation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "GAME", tmp_path)
    model = compiler.load_model()
    policy, extensions = decisions.load(), decisions.load_extensions()
    fingerprint = decisions.source_fingerprint(policy, extensions, None, situated_model=model)
    context = compiler.declared_support_evaluation_context()
    assert fingerprint["baseline_sha256"] == version_contracts.contract().baseline_strategy_sha256
    assert (
        fingerprint["situated_default_strategy_structure_source_sha256"]
        == model.source_sha256["default_strategy_structure"]
    )
    assert context.actor_scope is not None
    assert context.actor_scope.source == version_contracts.DEFAULT_STRATEGY_SOURCE
    with pytest.raises(ValueError, match="缺少或无法读取锁定原版默认策略"):
        compatibility_115.snapshot(game=tmp_path)


def test_release_model_rejects_structure_declaration_drift(tmp_path, monkeypatch):
    projection = tmp_path / "default-strategy-structure.json"
    projection.write_bytes(compiler._DEFAULT_STRATEGY_PROJECTION.read_bytes() + b"\n")
    monkeypatch.setattr(compiler, "_DEFAULT_STRATEGY_PROJECTION", projection)
    with pytest.raises(ValueError, match="默认策略结构合同字节漂移"):
        compiler.load_model()


@pytest.mark.integration
def test_release_compatibility_refuses_changed_installed_strategy_bytes(tmp_path):
    relative = version_contracts.DEFAULT_STRATEGY_SOURCE
    changed = tmp_path / relative
    changed.parent.mkdir(parents=True)
    # Copy only to the test's temporary directory. The trailing change is
    # immaterial to the AST and must still fail the raw source gate.
    changed.write_bytes((config.GAME / relative).read_bytes() + b"\n")
    with pytest.raises(ValueError, match="当前原版默认策略原始字节漂移"):
        compatibility_115.snapshot(game=tmp_path)


def test_parameter_identity_pins_keep_the_full_auxiliary_set_without_permissions(
    tmp_path, monkeypatch
):
    current = vanilla_inventory._parameter_evidence_contract()
    assert len(current) == 19
    assert current["common/goods/00_goods.txt"] == (
        "5ef25e76d498cd4a8603732712a8248e03cb782d9e41bb95daba6dfd87feb0ab"
    )
    _mutate_research_file(monkeypatch, tmp_path, "inventory-parameters.json")
    with pytest.raises(ValueError, match="来源合同漂移"):
        vanilla_inventory.parameter_evidence_hashes(tmp_path)


def test_full_current_model_keeps_every_published_identity_or_reviewed_retirement(current_model):
    bundle = current_model.consumer_ir
    assert bundle is not None
    retired = migration_baseline.validated_retirements(bundle)
    assert len(retired) == 565
    historical = json.loads(migration_baseline.DEFAULT_SOURCE.read_bytes())
    current = {(row.source, row.definition) for row in bundle.writers}
    assert all(
        (row["source"], row["definition"]) in current | retired for row in historical["rules"]
    )
    assert len(historical["rules"]) == 1401
    assert len(bundle.writers) > 5800
    assert (
        current_model.source_sha256["strategy_context_snapshot"]
        == engine_scope._strategy_manifest()[2]
    )


@pytest.mark.parametrize("change", ["remove", "field", "tail"])
def test_versioned_retirement_redirect_still_requires_the_exact_live_replacement(
    current_model, change
):
    bundle = current_model.consumer_ir
    assert bundle is not None
    writer = next(
        row for row in bundle.writers if row.definition == "technology_dough_rollers_labor"
    )
    replacement = (
        None
        if change == "remove"
        else replace(
            writer,
            **(
                {"field": "another_tech.ai_weight"}
                if change == "field"
                else {"vanilla_tail": "lost"}
            ),
        )
    )
    changed = replace(
        bundle,
        writers=tuple(
            replacement if row is writer else row
            for row in bundle.writers
            if row is not writer or replacement is not None
        ),
    )
    with pytest.raises(ValueError, match="历史规则退役替代"):
        migration_baseline.validate_bundle(changed)


def test_current_native_retention_contract_is_additional_and_tamper_closed(
    current_model, tmp_path, monkeypatch
):
    _mutate_research_file(monkeypatch, tmp_path, "migration-retentions.json")
    with pytest.raises(ValueError, match="延续合同字节漂移"):
        migration_baseline.validate_bundle(current_model.consumer_ir)


def _mutate_research_file(monkeypatch, tmp_path, name, *, raw=None):
    research_path = version_contracts.research_path
    path = tmp_path / name
    path.write_bytes(research_path("situated", name).read_bytes() + b"\n" if raw is None else raw)
    monkeypatch.setattr(
        version_contracts,
        "research_path",
        lambda category, filename, version=None: (
            path
            if (category, filename) == ("situated", name)
            else research_path(category, filename, version)
        ),
    )


@pytest.mark.integration
def test_compatibility_native_field_ast_is_checked_beyond_its_manifest_hash(tmp_path, monkeypatch):
    data = json.loads(compatibility_115.declaration())
    data["fields"]["aggression"]["ast_sha256"] = "0" * 64
    raw = json.dumps(data).encode()
    _mutate_research_file(monkeypatch, tmp_path, "compatibility-production.json", raw=raw)
    monkeypatch.setattr(compatibility_115, "CURRENT_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="原版 AST 漂移：aggression"):
        compatibility_115.snapshot()


@pytest.mark.parametrize(
    ("field", "expected"),
    [("change_law_chance", "dynamic_numeric"), ("another_chance", "needs_review")],
)
def test_first_nonzero_native_classification_is_bound_to_current_exact_consumer(field, expected):
    from test_situated_native_protection import _fixture

    from pdx.situated.native_treatments import native_treatments

    source = "common/ai_strategies/00_default_strategy.txt"
    raw = f"ai_strategy_default={{{field}={{value=1}}}}".encode()
    inventory, sources, _ = _fixture(
        raw,
        source=source,
        definition="ai_strategy_default",
        field=field,
        actor_scope="country",
        target_scope="none",
        capability="direct",
        operation="first_nonzero_active_change_law_chance_else_default",
    )
    result = native_treatments(inventory, sources, {}, production_complete=True)
    row = result["rows"][0]
    assert row["interface_kind"] == expected
    assert row["implemented_numeric"] is False
    assert row["business_complete"] is False
