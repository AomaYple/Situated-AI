"""The full historical acceptance graph selects current, independently proved inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import decisions, version_contracts
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


@pytest.fixture(scope="module", autouse=True)
def selected_115():
    with version_contracts.select_version("1.15.0"):
        yield


@pytest.fixture(scope="module")
def current_model():
    with version_contracts.select_version("1.15.0"):
        return compiler.load_model()


def test_current_ledgers_are_complete_and_historical_bytes_are_unchanged():
    rows = bindings.load()
    assert rows == bindings.build()
    assert len(rows) == 5857
    assert any("pm_coal_fired_plant_copper_cost" in row.definition for row in rows)
    assert bindings.check() == domain_coverage.check_counts() == []
    assert len(domain_coverage.load()) == 19
    assert bindings.source_path() != bindings.DEFAULT_SOURCE
    assert domain_coverage.source_path() != domain_coverage.DEFAULT_SOURCE
    for path, digest in (
        (
            bindings.DEFAULT_SOURCE,
            "d9e81fc2b729a37ecf4a83c9b62255ae848bc49e84b3a9de09fe7838ffb40fae",
        ),
        (
            domain_coverage.DEFAULT_SOURCE,
            "617e016a86227e36a5b10d4c9069b8b2c26d9529fcf29368e6b62fc67341c452",
        ),
    ):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_current_contract_refuses_the_historical_binding_ledger():
    with pytest.raises(ValueError, match="绑定目录不完整"):
        bindings.load(bindings.DEFAULT_SOURCE)


def test_current_contexts_use_the_current_binary_identity():
    strategy = compiler._frozen_strategy_contexts()
    context = strategy["recklessness"]
    assert context.actor_scope is not None
    assert context.actor_scope.source == "research/situated/victoria3-1.15.0-strategy-scope.json"
    assert any("consumer=recklessness:va=0x14182761f" in item for item in context.evidence)
    assert all("1.14.5" not in item for item in context.evidence)
    company = compiler._frozen_company_context()
    assert company.actor_scope is not None
    assert company.actor_scope.source == "research/situated/victoria3-1.15.0-company-scope.json"
    assert all("1.14.5" not in item for item in company.evidence)


def test_support_context_locates_current_field_comments_and_preserves_historical_lines():
    current = compiler.support_evaluation_context()
    assert current.actor_scope is not None
    assert current.actor_scope.source == "research/vanilla-ai/1.15.0/00_default_strategy.txt"
    assert current.actor_scope.line == 210
    assert tuple(row.line for row in current.targets) == (211, 212)
    with version_contracts.select_version("1.14.5"):
        old = compiler.support_evaluation_context()
        assert old.actor_scope is not None
        assert old.actor_scope.line == 183
        assert tuple(row.line for row in old.targets) == (184, 185)


def test_current_baseline_bytes_cannot_borrow_old_scope_proof(tmp_path, monkeypatch):
    damaged = tmp_path / "default.txt"
    damaged.write_bytes(compiler.baseline_path().read_bytes() + b"\n")
    monkeypatch.setattr(compiler, "baseline_path", lambda: damaged)
    with pytest.raises(ValueError, match="原版底本与引擎证据不一致"):
        compiler.support_evaluation_context()
    with pytest.raises(ValueError, match="原件 SHA"):
        compiler._frozen_institution_contexts(
            compiler._frozen_strategy_contexts()["institution_scores"]
        )


def test_parameter_identity_pins_keep_the_full_auxiliary_set_without_permissions(
    tmp_path, monkeypatch
):
    current = vanilla_inventory._parameter_evidence_contract()
    assert set(current) == set(vanilla_inventory._PARAMETER_EVIDENCE_HASHES)
    assert len(current) == 19
    assert (
        current["common/goods/00_goods.txt"]
        != vanilla_inventory._PARAMETER_EVIDENCE_HASHES["common/goods/00_goods.txt"]
    )
    damaged = tmp_path / "parameters.json"
    damaged.write_bytes(vanilla_inventory._PARAMETER_115_SOURCE.read_bytes() + b"\n")
    monkeypatch.setattr(vanilla_inventory, "_PARAMETER_115_SOURCE", damaged)
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
    damaged = tmp_path / "retentions.json"
    damaged.write_bytes(migration_baseline._VERSION_115_SOURCE.read_bytes() + b"\n")
    monkeypatch.setattr(migration_baseline, "_VERSION_115_SOURCE", damaged)
    with pytest.raises(ValueError, match="延续合同字节漂移"):
        migration_baseline.validate_bundle(current_model.consumer_ir)


def test_compatibility_policy_projects_current_native_authority_without_changing_historical_source():
    raw = decisions.SOURCE.read_bytes()
    with version_contracts.select_version("1.14.5"):
        historical = decisions.load()
    current = decisions.load()
    assert current.game_version == "1.15.0"
    assert (
        current.baseline_sha256 == hashlib.sha256(compiler.baseline_path().read_bytes()).hexdigest()
    )
    assert current.package.status == "candidate"
    assert current.package.parent == "vanilla-1.15.0"
    assert historical.game_version == "1.14.5"
    assert historical.package.status == "released"
    assert current.source_sha256 != historical.source_sha256
    for name in ("enabled", "entry_weeks", "exit_weeks", "ttl_days", "neutrality", "aggression"):
        assert getattr(current, name) == getattr(historical, name)
    assert decisions.SOURCE.read_bytes() == raw


def test_compatibility_native_field_ast_is_checked_beyond_its_manifest_hash(tmp_path, monkeypatch):
    data = json.loads(compatibility_115.snapshot())
    data["fields"]["aggression"]["ast_sha256"] = "0" * 64
    path = tmp_path / "compatibility.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(compatibility_115, "SOURCE", path)
    monkeypatch.setattr(compatibility_115, "SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="原版 AST 漂移：aggression"):
        compatibility_115.snapshot()


@pytest.mark.parametrize(
    ("version", "field", "expected"),
    [
        ("1.15.0", "change_law_chance", "dynamic_numeric"),
        ("1.14.5", "change_law_chance", "needs_review"),
        ("1.15.0", "another_chance", "needs_review"),
    ],
)
def test_first_nonzero_native_classification_is_bound_to_current_exact_consumer(
    version, field, expected
):
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
    with version_contracts.select_version(version):
        result = native_treatments(inventory, sources, {}, production_complete=True)
    row = result["rows"][0]
    assert row["interface_kind"] == expected
    assert row["implemented_numeric"] is False
    assert row["business_complete"] is False
