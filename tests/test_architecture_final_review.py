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

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_rules,
    decisions,
    distribution,
    version_contracts,
)
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import (
    architecture_receipts,
    audit,
    compiler,
    migration_baseline,
    pdx_eval,
    relations,
    vanilla_inventory,
)
from pdx.situated.native_treatments import _digest, _resolve
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
# Independent list of the concrete, nonnumeric supply decisions promised by
# the existing product, rather than a denominator read from its own metadata.
SUPPLY_GOODS = (
    "automobiles",
    "clothes",
    "coffee",
    "explosives",
    "fabric",
    "fertilizer",
    "fine_art",
    "fish",
    "fruit",
    "furniture",
    "glass",
    "groceries",
    "iron",
    "lead",
    "liquor",
    "luxury_clothes",
    "luxury_furniture",
    "meat",
    "merchant_marine",
    "oil",
    "opium",
    "porcelain",
    "radios",
    "rubber",
    "steel",
    "sugar",
    "sulfur",
    "tea",
    "telephones",
    "tobacco",
    "tools",
    "wine",
    "wood",
)


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
        assert (
            digest(architecture_receipts.source_snapshot(config.REPO))
            == (final_candidate["snapshot"])
        )
        # Keep both full native closure checks from package_inputs while
        # reusing this module's freshly generated complete candidate.
        distribution.verify_compatibility_installation()
        report = audit._native_report_from_candidate(
            final_candidate["model"], final_candidate["files"]
        )
        distribution.verify_compatibility_installation()
        assert (
            digest(architecture_receipts.source_snapshot(config.REPO))
            == (final_candidate["snapshot"])
        )
    assert report["source_snapshot_sha256"] == final_candidate["snapshot"]
    assert report["plan_version"] == architecture_receipts.PLAN_VERSION
    # Re-discover the installed originals independently of the supplied/built
    # treatment report. A report cannot choose its own source denominator.
    installed_scope = vanilla_inventory.discover()
    assert report["scope"] == installed_scope.as_dict()
    treatments = report["native_treatments"]
    assert treatments["production_hashes"] == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in final_candidate["files"].items()
    }
    return report


@pytest.fixture(scope="module")
def final_disabled(final_candidate):
    return decisions.build(
        replace(final_candidate["policy"], enabled=False),
        extensions=replace(
            final_candidate["extensions"],
            reform_enabled=False,
            market_enabled=False,
            security_enabled=False,
            economy_enabled=False,
            diplomacy_enabled=False,
        ),
    )


@pytest.fixture(scope="module")
def final_supply(final_candidate, final_disabled):
    """Parse each frozen source once; never cache across candidate sessions."""
    candidate = final_candidate
    bundle = candidate["model"].consumer_ir
    assert bundle is not None
    writers = [w for w in bundle.writers if w.kind == "supply_program"]
    programs = {
        w.supply_program.good: w.supply_program for w in writers if w.supply_program is not None
    }
    assert len(writers) == len(programs) == len(SUPPLY_GOODS)
    assert set(programs) == set(SUPPLY_GOODS)
    source = explicit.SOURCE
    original = parse_text(compiler.baseline_path().read_text(encoding="utf-8")).root
    installed_original = parse_text((config.GAME / source).read_text(encoding="utf-8-sig")).root
    current = parse_text(candidate["files"][source].decode("utf-8-sig")).root
    disabled = parse_text(final_disabled[source]).root
    original_map, status = _resolve(original, "ai_strategy_default", "goods_stances")
    assert status == "found"
    assert original_map is not None
    assert isinstance(original_map.value, Block)
    originals = {item.key: _digest(item) for item in original_map.value.assignments()}
    installed_map, status = _resolve(installed_original, "ai_strategy_default", "goods_stances")
    assert status == "found"
    assert installed_map is not None
    assert isinstance(installed_map.value, Block)
    installed_originals = {item.key: _digest(item) for item in installed_map.value.assignments()}
    assert originals == installed_originals
    assert (
        len(originals)
        == {"1.14.5": 17, "1.15.0": 18, "1.15.1": 21}[version_contracts.active_version()]
    )
    actual_map, status = _resolve(current, "ai_strategy_default", "goods_stances")
    assert status == "found"
    assert actual_map is not None
    assert isinstance(actual_map.value, Block)
    actual_originals = {
        item.key: _digest(item) for item in actual_map.value.assignments() if item.key in originals
    }
    assert {item.key for item in actual_map.value.assignments()} == set(originals) | set(
        SUPPLY_GOODS
    )
    assert actual_originals == originals
    return {
        "programs": programs,
        "current": current,
        "disabled": disabled,
        "originals": originals,
        "actual_originals": actual_originals,
    }


def _supply_rows(context, good):
    """Compare handwritten enum outcomes with reference and actual PDX trigger."""
    assert good in SUPPLY_GOODS
    program = context["programs"][good]
    source = explicit.SOURCE
    field = f"goods_stances.{good}"
    current, disabled = context["current"], context["disabled"]
    originals, actual_originals = context["originals"], context["actual_originals"]
    node, status = _resolve(current, "ai_strategy_default", field)
    assert status == "found"
    assert node is not None
    assert isinstance(node.value, Block)
    stance, trigger = node.value.first("stance"), node.value.first("trigger")
    assert stance is not None
    assert isinstance(stance.value, Scalar)
    assert trigger is not None
    assert isinstance(trigger.value, Block)
    assert len(node.value.items) == 2
    disabled_node, _ = _resolve(disabled, "ai_strategy_default", field)
    assert disabled_node is None
    native_hash = digest(originals)
    observed_native_hash = digest(actual_originals)
    # All conjuncts here describe this one good's actual scarcity, rather than
    # nation-wide finance/education/politics prerequisites for all construction.
    scenarios: tuple[tuple[str, bool, float | None, int, bool, bool, str | None], ...] = (
        ("positive", True, 0.5, -10, True, True, "wants_high_supply"),
        ("negative", True, 0.25, -10, True, True, None),
        ("unknown", True, None, -10, True, True, None),
        ("disabled", True, 0.5, -10, True, True, None),
        ("player", False, 0.5, -10, True, True, None),
        ("native_tail", True, 0.5, 0, True, True, None),
    )
    for role, is_ai, price, delta, market_present, good_present, selected in scenarios:
        enabled = role != "disabled"
        inputs = {
            "good": good,
            "contract_version": version_contracts.active_version(),
            "is_ai": is_ai,
            "price": price,
            "delta": delta,
            "market_present": market_present,
            "good_present": good_present,
            "enabled": enabled,
            "native_stances": originals,
        }
        observation = {
            "is_ai": is_ai,
            "market": {
                f"mg:{good}": {"market_goods_pricier": price, "market_goods_delta": delta},
            },
        }
        expected = {"selected": selected, "native_stances_sha256": native_hash}
        reference = {
            "selected": program.evaluate(
                is_ai=is_ai,
                price=price,
                delta=delta,
                market_present=market_present,
                good_present=good_present,
                enabled=enabled,
            ),
            "native_stances_sha256": native_hash,
        }
        generated = {
            "selected": stance.value.unquoted
            if enabled and pdx_eval.condition(trigger.value, observation) is True
            else None,
            "native_stances_sha256": observed_native_hash,
        }
        assert expected == reference == generated, (good, role)
        yield {
            "case_id": f"supply.{good}.{role}",
            "role": role,
            "input": inputs,
            "expected": expected,
            "reference": reference,
            "generated": generated,
            "production": [
                "mod/decisions/adapters.toml",
                "src/pdx/decision_adapters.py",
                "src/pdx/situated/supply_program.py",
                "src/pdx/situated/decision_ir.py",
                "src/pdx/situated/compiler.py",
            ],
            "consumers": [
                {
                    "path": (decisions.product_path().relative_to(config.REPO) / source).as_posix(),
                    "definition": "ai_strategy_default",
                    "field": field,
                }
            ],
        }


@pytest.mark.parametrize("good", SUPPLY_GOODS)
def test_each_actual_supply_enum_has_six_roles(final_supply, architecture_witness, good):
    for case in _supply_rows(final_supply, good):
        architecture_witness(evidence_ids=["a2.supply.market_trade_company_diplomacy"], **case)


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
    assert scope["discovered_count"] == treatments["denominator"] == len(expected)
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
                assert (decisions.product_path() / name).read_bytes() == raw, name
    return {
        "declarations": len(rows),
        "active_unknown": 0,
        "unresolved_source_obligations": 0,
        "manifest_verified": True,
        "installed_source_bytes": integration,
    }


@pytest.fixture(scope="module")
def final_whole_review(final_candidate, final_disabled, final_supply):
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
    baseline = compiler.baseline_path().read_text(encoding="utf-8")
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
    disabled = final_disabled
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
    for good in SUPPLY_GOODS:
        for case in _supply_rows(final_supply, good):
            record(**case)
    expected_legacy = {"1.14.5": 927, "1.15.0": 937}[version_contracts.active_version()]
    assert len(legacy.IDENTITIES) == expected_legacy
    assert len(explicit.CARDS) == 11
    # The external fleet script body and its actual strategy reference are
    # separate physical consumers; both require their own six executed roles.
    expected_cases_per_role = expected_legacy + 1 + len(explicit.CARDS) + 1 + len(SUPPLY_GOODS)
    assert len(rows) == expected_cases_per_role * len(ROLES)
    assert len({row["case_id"] for row in rows}) == len(rows)
    consumers = {
        (item["path"], item["definition"], item["field"])
        for row in rows
        for item in row["consumers"]
    }
    # Establish the physical field set from rules, explicit cards, the native
    # fleet reference, support and the independent supply list before comparing
    # executed records. Coexisting responsibilities can share physical fields.
    expected_consumers = {
        tuple(legacy._consumer(source, field)[key] for key in ("path", "definition", "field"))
        for source, field in legacy.IDENTITIES
    }
    current_path = (decisions.product_path().relative_to(config.REPO) / explicit.SOURCE).as_posix()
    expected_consumers.update(
        (current_path, explicit.DEFINITION, card[1]) for card in explicit.CARDS
    )
    expected_consumers.add((current_path, explicit.DEFINITION, "diplomatic_play_support"))
    fleet_links = {
        (
            (decisions.product_path().relative_to(config.REPO) / source).as_posix(),
            field[0],
            ".".join(field[1:]),
        )
        for source, field in legacy.IDENTITIES
        if legacy._consumer(source, field)["field"] == "__body__"
    }
    assert len(fleet_links) == 1
    expected_consumers.update(fleet_links)
    expected_consumers.update(
        (current_path, explicit.DEFINITION, f"goods_stances.{good}") for good in SUPPLY_GOODS
    )
    assert consumers == expected_consumers
    assert Counter(row["role"] for row in rows) == dict.fromkeys(ROLES, expected_cases_per_role)
    assert digest(architecture_receipts.source_snapshot(config.REPO)) == candidate["snapshot"]
    return {
        "review": {
            "contract_version": version_contracts.active_version(),
            "legacy_consumers": expected_legacy,
            "legacy_strategy_links": 1,
            "explicit_cards": 11,
            "support_programs": 1,
            "supply_enum_programs": 33,
            "physical_consumers": len(consumers),
            "executed_cases": len(rows),
            "expected_cases": expected_cases_per_role * len(ROLES),
            "roles": list(ROLES),
            "fresh_execution_sha256": digest(rows),
            "production_output_hashes": {
                name: hashlib.sha256(raw).hexdigest() for name, raw in candidate["files"].items()
            },
        },
        "rows": rows,
    }


@pytest.mark.parametrize("role", ROLES)
def test_whole_mod_review_reexecutes_the_exact_current_consumer_matrix(
    final_whole_review, architecture_witness, role
):
    """Capture every freshly executed consumer under this candidate's full matrix."""
    whole = final_whole_review
    review = whole["review"]
    assert review["executed_cases"] == review["expected_cases"]
    for case in whole["rows"]:
        if case["role"] == role:
            architecture_witness(
                **{**case, "input": {**case["input"], "whole_mod_review": whole["review"]}}
            )


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
    final_candidate, architecture_witness, request, stage, requirement, role
):
    if requirement in {"legal_scope_disposition", "native_integration"}:
        reviews = {}
    else:
        reviews = request.getfixturevalue("final_reviews")
    if requirement in {
        "legal_scope_disposition",
        "native_integration",
        "whole_mod_functional_review",
    }:
        report = request.getfixturevalue("final_native")
        integrated = _native_review(
            final_candidate, report, integration=requirement != "legal_scope_disposition"
        )
        review = {**reviews.get(requirement, {}), "native_scope": integrated}
    else:
        review = reviews[requirement]
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
