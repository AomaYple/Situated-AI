"""Exact school-policy migration proof, independent of live game installation."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from pdx import version_contracts
from pdx.situated import migration_baseline as migration
from pdx.situated import network_profile, network_support, production_profile
from pdx.situated.decision_ir import WriterDecisionIR


@pytest.fixture(scope="module", autouse=True)
def current_version():
    with version_contracts.select_version("1.15.1"):
        yield


@pytest.fixture
def contract():
    value = migration._versioned_contract()
    assert value is not None
    return value


def test_school_successor_proves_exact_frozen_retirement_cross_product(contract):
    redirects = migration._school_network_replacements(contract, ())
    proof = contract["school_policy_migration"]
    assert len(redirects) == 36
    assert redirects == frozenset(
        ("mod/decisions/information.toml", retired, replacement)
        for retired in proof["retired_definitions"]
        for replacement in proof["replacement_bridge_ids"]
    )
    assert not any("unreviewed_school" in identity for identity in redirects)


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
def test_school_successor_refuses_other_version_contexts(contract, version):
    with (
        version_contracts.select_version(version),
        pytest.raises(ValueError, match=r"只允许精确1\.15\.1"),
    ):
        migration._school_network_replacements(contract, ())


@pytest.mark.parametrize(
    "damage",
    ["policy_hash", "missing_bridge_mapping", "unknown_retirement", "successor_operation"],
)
def test_school_successor_refuses_damaged_policy_identity(contract, damage):
    proof = contract["school_policy_migration"]
    if damage == "policy_hash":
        proof["policy_sha256"] = "0" * 64
    elif damage == "missing_bridge_mapping":
        proof["replacement_bridge_ids"].pop("remaining_school_capacity")
    elif damage == "unknown_retirement":
        proof["retired_definitions"].append("unreviewed_school")
    else:
        proof["successor"]["operation"] = "multiply"
    with pytest.raises(ValueError, match=r"学校网络替代.*漂移"):
        migration._school_network_replacements(contract, ())


@pytest.mark.parametrize("renamed", [False, True])
def test_school_successor_refuses_legacy_or_renamed_writer_double_count(contract, renamed):
    writer = WriterDecisionIR(
        writer_id="test-school",
        kind="rule_action",
        source="mod/decisions/information.toml",
        definition="renamed_school" if renamed else "remaining_school_fiscal",
        consumer_id="test-school",
        field="institution_scores.institution_schools" if renamed else "unrelated.field",
        actor="root",
        target="none",
        operation="multiply",
        vanilla_tail="retain_original_qualification_cost_random_execution",
        owner="test",
    )
    with pytest.raises(ValueError, match="旧学校writer或双重计分"):
        migration._school_network_replacements(contract, (writer,))


def test_school_successor_refuses_missing_actual_bridge(contract, monkeypatch):
    real_audit = network_profile.audit

    def damaged_audit(profile):
        audit = deepcopy(real_audit(profile))
        programs = cast("list[dict[str, object]]", audit["programs"])
        school = next(row for row in programs if row["consumer"] == "a0-pol-schools")
        school["bridges"] = [
            row
            for row in cast("list[dict[str, object]]", school["bridges"])
            if row["id"] != "school-capacity-fiscal"
        ]
        return audit

    monkeypatch.setattr(network_profile, "audit", damaged_audit)
    with pytest.raises(ValueError, match="实际桥或读取合同漂移"):
        migration._school_network_replacements(contract, ())


def test_school_successor_refuses_changed_native_tail(contract, monkeypatch):
    real_build = network_profile.build

    def damaged_build(profile):
        files = dict(real_build(profile))
        name = "common/ai_strategies/00_default_strategy.txt"
        files[name] += "\n# unreviewed native tail change\n"
        return files

    monkeypatch.setattr(network_profile, "build", damaged_build)
    with pytest.raises(ValueError, match="原版资格成本或完整尾部保护漂移"):
        migration._school_network_replacements(contract, ())


@pytest.mark.parametrize("version", ["1.15.0", "1.15.1"])
def test_school_support_matrix_uses_numeric_witness_for_its_actual_version(version):
    with version_contracts.select_version(version):
        profile = production_profile.load_profile(production_profile.baseline_root(version))
        rows = network_support.matrix(profile, network_profile.compile_profile(profile))
    expected = (
        "tests/test_release_1151_integration.py::"
        "test_school_additive_policy_has_literal_independent_pdx_witness"
        if version == "1.15.1"
        else "tests/test_network_profile.py::test_school_complete_costs_and_agenda_residual"
    )
    school = [
        row for row in rows if row["consumer"] == "a0-pol-schools" and row["production_eligible"]
    ]
    assert school
    assert all(row["status"] == "production_bound" for row in school)
    assert all(expected in cast("list[str]", row["witnesses"]) for row in school)
    wrong = (
        "test_school_complete_costs_and_agenda_residual"
        if version == "1.15.1"
        else "test_school_additive_policy_has_literal_independent_pdx_witness"
    )
    assert not any(
        wrong in witness for row in school for witness in cast("list[str]", row["witnesses"])
    )
