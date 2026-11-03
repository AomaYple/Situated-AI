"""Requirement-specific final reviews with actual six-role production witnesses.

These reviews never sign stage JSON. A supplied final report must match current
sources exactly; ordinary integration runs rebuild one shared native report.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import test_architecture_all_consumer_witnesses as legacy
import test_architecture_explicit_witnesses as explicit
import test_observed_relations_feedback as feedback
import test_observed_relations_witness_capture as witness
import test_situated_production_guards as guards

from pdx import config, country_state, decision_adapters, decision_rules, decisions, distribution
from pdx.parser import parse_text
from pdx.situated import architecture_receipts, audit, compiler, migration_baseline, relations
from pdx.situated.native_treatments import _digest
from pdx.situated.receipts import digest

if TYPE_CHECKING:
    from typing import Any

pytest_plugins = ("tools.ci.architecture_witness_capture",)
pytestmark = pytest.mark.integration
REQUIREMENTS = (
    ("S4", "legal_scope_disposition"),
    ("S4", "legacy_migration"),
    ("S4", "single_owner_no_bypass"),
    ("S4", "cross_domain_relations"),
    ("S5", "whole_mod_functional_review"),
    ("S5", "native_integration"),
)
ROLES = ("positive", "negative", "unknown", "disabled", "player", "native_tail")


@pytest.fixture(scope="module")
def final_candidate():
    before = architecture_receipts.source_snapshot(config.REPO)
    policy, extensions, generated = distribution.package_inputs(include_engineering_metadata=True)
    model = compiler.load_model()
    assert architecture_receipts.source_snapshot(config.REPO) == before
    files = {
        name: value.encode() if isinstance(value, str) else value
        for name, value in generated.items()
    }
    metadata = json.loads(files[".metadata/metadata.json"])
    raw = files["common/ai_strategies/00_default_strategy.txt"].decode()
    disk = (config.REPO / witness.GENERATED).read_bytes()
    assert disk == files["common/ai_strategies/00_default_strategy.txt"]
    actual = witness.pdx_eval.marked_block(raw, "joint_economic_balance", path=witness.GENERATED)
    overlay = compiler.strategy_overlay(model)[witness.FIELD]
    assert _digest(parse_text(actual).root) == _digest(parse_text(overlay).root)
    return {
        "model": model,
        "files": files,
        "metadata": metadata,
        "snapshot": digest(before),
        "r8": (model, actual, raw),
        "policy": policy,
        "extensions": extensions,
    }


@pytest.fixture(scope="module")
def final_native(final_candidate):
    selected = os.environ.get("SITAI_FINAL_NATIVE_REPORT")
    if selected:
        path = Path(selected)
        assert path.is_file(), f"explicit final native report missing: {path}"
        report = json.loads(path.read_bytes())
    else:
        report = audit.native_report()
    assert report["source_snapshot_sha256"] == final_candidate["snapshot"]
    assert report["plan_version"] == architecture_receipts.PLAN_VERSION
    treatments = report["native_treatments"]
    assert treatments["production_hashes"] == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in final_candidate["files"].items()
    }
    return report


def _migration_review(candidate):
    bundle = candidate["model"].consumer_ir
    assert bundle is not None
    migration_baseline.validate_bundle(bundle)
    retired = migration_baseline.validated_retirements(bundle)
    historical = json.loads(migration_baseline.DEFAULT_SOURCE.read_bytes())
    current = {(row.source, row.definition) for row in bundle.writers if row.kind == "rule_action"}
    old = {(row["source"], row["definition"]) for row in historical["rules"]}
    assert len(old) == 1401
    assert old <= current | retired
    # A same-count replacement or loss must not satisfy historical identity.
    survivor = next(
        row
        for row in bundle.writers
        if row.kind == "rule_action" and (row.source, row.definition) in old - retired
    )
    changed = replace(bundle, writers=tuple(row for row in bundle.writers if row != survivor))
    with pytest.raises(ValueError, match="历史迁移身份缺失"):
        migration_baseline.validate_bundle(changed)
    return {
        "historical_rules": len(old),
        "retired_identities": len(retired),
        "survivor_removal_rejected": True,
    }


def _owner_review(candidate):
    model = candidate["model"]
    assert compiler.audit(model) == []
    bundle = candidate["metadata"]["situated_actions"]["consumer_ir"]
    owners = defaultdict(set)
    for row in bundle["writers"]:
        assert row["owner"]
        owners[row["field"]].add(row["owner"])
    assert all(len(value) == 1 for value in owners.values())
    assert {field: next(iter(value)) for field, value in owners.items()} == bundle["field_owners"]
    for damage in ("missing_writer", "duplicate_writer", "writer_owner", "writer_operation"):
        broken = guards._damaged_model(model, damage)
        with pytest.raises(ValueError, match=r"IR|writer|行动"):
            compiler.strategy_overlay(broken)
    assert "common/on_actions/sitai_country_on_actions.txt" not in candidate["files"]
    assert "common/scripted_effects/sitai_country_effects.txt" not in candidate["files"]
    state = country_state.contract(country_state.load())
    assert state["schema"] == 2
    assert state["persistent_variables"] == []
    assert set(model.support_sources or {}).isdisjoint({"temporal", "arbitration"})
    support = audit._production_continuous_bindings(candidate["files"])
    assert len(support) == bundle["support_program_writer_count"]
    return {
        "writers": len(bundle["writers"]),
        "physical_fields": len(owners),
        "bad_writer_rejected": 4,
        "persistent_slots": 0,
    }


def _relations_review(candidate):
    model = candidate["model"]
    relations.validate(model.actions)
    # Hand-calculated real-world completed-school feedback, local missing
    # evidence, literacy saturation and independent wartime/default costs.
    feedback.test_enacted_public_school_and_institution_are_required_for_education_feedback(
        model, {"current_public_schools": True, "schools_present": True}, 0.0
    )
    feedback.test_enacted_public_school_and_institution_are_required_for_education_feedback(
        model, {"current_public_schools": None, "schools_present": True}, 0.025
    )
    feedback.test_observed_literacy_saturation_exits_education_and_informs_industry(
        model, {"current_public_schools": True, "schools_present": True}, 0.175
    )
    feedback.test_generic_reform_tempo_never_claims_an_industry_law_has_completed(model)
    feedback.test_default_cannot_weaken_wartime_diplomatic_restraint(model)
    first = next(row for row in model.actions if row.id == "industrial_foundation")
    duplicate = replace(first, complements=(*first.complements, "education_and_research"))
    with pytest.raises(ValueError, match="重复"):
        relations.validate((duplicate, *(row for row in model.actions if row != first)))
    return {
        "relations": len(model.relations),
        "completed_feedback": True,
        "local_unknown": True,
        "saturation_exit": True,
        "independent_cost": True,
        "duplicate_rejected": True,
    }


def _native_review(candidate, report, *, integration):
    scope, treatments = report["scope"], report["native_treatments"]
    rows = treatments["rows"]
    expected = [row["declaration_id"] for row in scope["surfaces"]]
    assert scope["discovered_count"] == treatments["denominator"] == len(expected) == 8856
    assert len(set(expected)) == len(expected)
    assert Counter(expected) == Counter(row["declaration_id"] for row in rows)
    assert scope["parse_failures"] == []
    assert treatments["production_manifest_complete_asserted"] is True
    assert all(row["active_unknown_usage"] is False for row in rows)
    unresolved = [
        row["declaration_id"]
        for row in rows
        if not (
            row["source_protection"]["proven"]
            or (
                row["implemented_numeric"]
                and row["interface"]["control_authorized"]
                and row["source_protection"]["context_closed"]
                and row["source_protection"]["dependencies_closed"]
            )
        )
    ]
    assert unresolved == [], unresolved[:20]
    if integration:
        for name, expected_hash in treatments["source_hashes_verified"].items():
            assert hashlib.sha256((config.GAME / name).read_bytes()).hexdigest() == expected_hash
        # Launcher metadata intentionally differs from engineering metadata;
        # every actual game script and localization byte must match this build.
        for name, raw in candidate["files"].items():
            if name.startswith(("common/", "events/", "localization/")):
                assert (config.REPO / "mod" / name).read_bytes() == raw, name
    return {
        "declarations": len(rows),
        "active_unknown": 0,
        "unresolved_source_obligations": 0,
        "manifest_verified": True,
        "installed_source_bytes": integration,
    }


@pytest.fixture(scope="module")
def final_whole_review(final_candidate):
    """Re-execute every consumer against this candidate, never import old captures."""
    candidate = final_candidate
    model = candidate["model"]
    adapters = decision_adapters.load()
    policies = ((legacy.INFO, decision_rules.load()), *adapters.policies)
    files = {
        name: raw.decode("utf-8-sig")
        for name, raw in candidate["files"].items()
        if name.endswith((".txt", ".yml", ".json"))
    }
    baseline = compiler.BASELINE.read_text(encoding="utf-8")
    # pytest exposes the original factory through __wrapped__ at runtime;
    # FixtureFunctionDefinition's type stub does not declare that attribute.
    legacy_candidate = cast("Any", legacy.witness_candidate).__wrapped__(
        (
            policies,
            model,
            files,
            files[legacy.DEFAULT],
            decision_adapters.read_inputs(adapters),
            baseline,
        )
    )
    rows = []

    def record(**case):
        # This callback receives only freshly executed independent/reference/
        # actual comparisons; previous stage captures are never read here.
        assert case["expected"] == case["reference"] == case["generated"]
        case["evidence_ids"] = ["a2.final.whole_mod_functional_review"]
        case["case_id"] = "final.S5.whole." + case["case_id"]
        rows.append(case)

    for source, field in legacy.IDENTITIES:
        legacy.test_each_legacy_physical_consumer_has_six_executed_roles(
            legacy_candidate, record, source, field
        )
    legacy.test_legacy_module_declares_only_its_actual_denominator(legacy_candidate)
    continuous = audit._production_continuous_bindings(files)
    assert len(continuous) == 1
    disabled_extensions = replace(
        candidate["extensions"],
        reform_enabled=False,
        market_enabled=False,
        security_enabled=False,
        economy_enabled=False,
        diplomacy_enabled=False,
    )
    disabled = decisions.build(
        replace(candidate["policy"], enabled=False), extensions=disabled_extensions
    )
    explicit_candidate = {
        "built": files[explicit.SOURCE],
        "model": model,
        "metadata": candidate["metadata"],
        "support": continuous[0].writer.program,
        "disabled": disabled[explicit.SOURCE],
        "baseline": baseline,
    }
    for row in explicit.CARDS:
        explicit.test_every_explicit_card_executes_actual_six_role_witnesses(
            explicit_candidate, record, row
        )
    explicit.test_continuous_support_executes_actual_six_role_witnesses(explicit_candidate, record)
    explicit.test_explicit_and_continuous_denominator_is_exact_and_separate(explicit_candidate)
    assert len(legacy.IDENTITIES) == 923
    assert len(explicit.CARDS) == 11
    assert len(rows) == (923 + 11 + 1) * len(ROLES)
    assert len({row["case_id"] for row in rows}) == len(rows)
    consumers = {
        (item["path"], item["definition"], item["field"])
        for row in rows
        for item in row["consumers"]
    }
    assert len(consumers) == 932
    assert Counter(row["role"] for row in rows) == dict.fromkeys(ROLES, 935)
    assert digest(architecture_receipts.source_snapshot(config.REPO)) == candidate["snapshot"]
    return {
        "review": {
            "legacy_consumers": 923,
            "explicit_cards": 11,
            "support_programs": 1,
            "physical_consumers": len(consumers),
            "executed_cases": len(rows),
            "roles": list(ROLES),
            "fresh_execution_sha256": digest(rows),
            "production_output_hashes": {
                name: hashlib.sha256(raw).hexdigest() for name, raw in candidate["files"].items()
            },
        },
        "rows": rows,
    }


def test_whole_mod_review_reexecutes_the_exact_current_consumer_matrix(final_whole_review):
    """Build-only verification; formal S5 capture occurs in its six role tests."""
    assert final_whole_review["review"]["executed_cases"] == 5610


@pytest.fixture(scope="module")
def final_reviews(final_candidate):
    candidate = final_candidate
    # These are independent requirements, not aliases to S2/S3 field matrices.
    migration = _migration_review(candidate)
    owner = _owner_review(candidate)
    relation = _relations_review(candidate)
    return {
        "legacy_migration": migration,
        "single_owner_no_bypass": owner,
        "cross_domain_relations": relation,
        "whole_mod_functional_review": {
            "migration": migration,
            "owner": owner,
            "observed_relations": relation,
        },
    }


@pytest.mark.parametrize(("stage", "requirement"), REQUIREMENTS)
@pytest.mark.parametrize("role", ROLES)
def test_requirement_specific_full_review_and_real_consumer_roles(
    final_candidate, final_reviews, architecture_witness, request, stage, requirement, role
):
    if requirement in {
        "legal_scope_disposition",
        "native_integration",
        "whole_mod_functional_review",
    }:
        report = request.getfixturevalue("final_native")
        integrated = _native_review(
            final_candidate, report, integration=requirement != "legal_scope_disposition"
        )
        review = {**final_reviews.get(requirement, {}), "native_scope": integrated}
    else:
        review = final_reviews[requirement]
    if requirement == "whole_mod_functional_review":
        whole = request.getfixturevalue("final_whole_review")
        review = {**review, "whole_mod_matrix": whole["review"]}
        for case in whole["rows"]:
            if case["role"] == role:
                architecture_witness(
                    **{**case, "input": {**case["input"], "whole_mod_review": whole["review"]}}
                )
    assert review
    candidate = final_candidate["r8"]

    def record(**case):
        production = [
            *case.pop("production"),
            "src/pdx/situated/migration_baseline.py",
            "src/pdx/situated/native_treatments.py",
        ]
        architecture_witness(
            evidence_ids=[f"a2.final.{requirement}"],
            **{
                **case,
                "case_id": f"final.{stage}.{requirement}.{role}",
                "input": {**case["input"], "requirement_review": review},
                "production": production,
            },
        )

    if role in {"positive", "negative", "unknown"}:
        school, expected = {
            "positive": (True, 0.0),
            "negative": (False, 0.025),
            "unknown": (None, 0.025),
        }[role]
        witness.test_actual_observed_school_feedback_role(candidate, record, role, school, expected)
    else:
        getattr(witness, f"test_actual_observed_feedback_{role}_role")(candidate, record)
