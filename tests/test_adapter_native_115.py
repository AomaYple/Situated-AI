"""Independent failures and exact native changes in migrated broad adapters.

This is the historical engineering compatibility path, separate from the R2
three-consumer candidate package and from runtime behavior evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tomllib
from pathlib import Path

import pytest

from pdx import (
    company_sectors,
    config,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    version_contracts,
)
from pdx.model import Block, Scalar
from pdx.parser import parse_text


@pytest.fixture(scope="module")
def declaration():
    return tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def information():
    return tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def native_inputs(declaration):
    return {
        source: (config.GAME / source).read_text(encoding="utf-8-sig")
        for source in declaration["sources"]
    }


@pytest.mark.integration
def test_full_current_parent_field_default_authority_has_exact_independent_denominators(
    declaration, information, native_inputs
):
    actual = decision_adapters.native_contract_data(
        declaration, native_inputs, information=information
    )
    assert actual == decision_adapters.native_authority_115()
    assert len(actual["sources"]) == 103
    assert len(actual["fields"]) == 246  # 233 adapters plus 13 information fields.
    kinds = {
        kind: sum(row["kind"] == kind for row in actual["fields"])
        for kind in ("missing_declared_default", "declared_scalar", "numeric_block")
    }
    assert kinds == {"missing_declared_default": 11, "declared_scalar": 2, "numeric_block": 233}
    missing = [row for row in actual["fields"] if row["kind"] == "missing_declared_default"]
    assert {row["default"]["value"] for row in missing} == {"1000"}
    assert all(row["parents"] and row["parents"][0]["ast_sha256"] for row in actual["fields"])


@pytest.mark.integration
@pytest.mark.parametrize(
    "damage",
    ["duplicate-parent", "parent-op", "field-op", "field-prefix", "scalar-kind", "missing-default"],
)
def test_native_authority_rejects_ambiguous_or_changed_write_shapes(
    declaration, native_inputs, damage
):
    source = "common/buildings/03_mines.txt"
    text = native_inputs[source]
    if damage == "duplicate-parent":
        text += "\nbuilding_iron_mine = { ai_value = { value = 1000 } }\n"
    elif damage == "parent-op":
        text = text.replace("building_iron_mine =", "building_iron_mine ?=", 1)
    elif damage == "field-op":
        text = text.replace("ai_value =", "ai_value ?=", 1)
    elif damage == "field-prefix":
        text = text.replace("ai_value =", "INJECT:ai_value =", 1)
    elif damage == "scalar-kind":
        assert "ai_value = 5000" in text
        text = text.replace("ai_value = 5000", "ai_value = unknown_expression", 1)
    else:
        changed = copy.deepcopy(declaration)
        changed["initial_values"] = [
            row
            for row in changed["initial_values"]
            if row["field"] != "building_arms_industry.ai_value"
        ]
        with pytest.raises(ValueError, match="authority"):
            decision_adapters.native_contract_data(changed, native_inputs)
        return
    with pytest.raises(ValueError, match="authority"):
        decision_adapters.native_contract_data(declaration, {**native_inputs, source: text})


@pytest.mark.integration
def test_native_changes_keep_journal_aware_blocks_and_only_initialize_actual_missing_fields():
    with version_contracts.select_version("1.15.0"):
        adapters = decision_adapters.load()
    building_initial = [
        row for row in adapters.initial_values if row.source.startswith("common/buildings/")
    ]
    assert len(building_initial) == 11
    assert ("building_food_industry", "ai_value") not in {row.field for row in building_initial}
    native = parse_text(
        (config.GAME / "common/buildings/01_industry.txt").read_text(encoding="utf-8-sig")
    ).root
    food = native.first("building_food_industry")
    assert food is not None
    assert isinstance(food.value, Block)
    score = food.value.first("ai_value")
    assert score is not None
    assert isinstance(score.value, Block)
    base = score.value.first("value")
    assert base is not None
    assert isinstance(base.value, Scalar)
    assert base.value.text == "1000"
    bonuses = [
        row.value.first("add") for row in score.value.all("if") if isinstance(row.value, Block)
    ]
    assert any(
        row is not None and isinstance(row.value, Scalar) and row.value.text == "2500"
        for row in bonuses
    )
    # Native journal can change 1000 into 3500. Keeping that block is necessary;
    # reusing the old default would silently erase a real 1.15 policy input.
    assert 1000 + 2500 == 3500
    assert (
        sum(
            rule.field == ("building_food_industry", "ai_value")
            for _, policy in adapters.policies
            for rule in policy.rules
        )
        > 0
    )


@pytest.mark.integration
def test_new_hyphenated_company_retains_native_identity_and_receives_sector_program():
    with version_contracts.select_version(
        config.game_version()["caligula_branch"].removeprefix("release/")
    ):
        data = company_sectors.verify_game(config.GAME)
        adapters = decision_adapters.load()
    assert data["counts"] == {
        "companies": 231,
        "explicit_weight": 205,
        "implicit_weight": 26,
        "primary_buildings": 49,
    }
    company = "company_russo-baltic_wagon_factory"
    profile = data["profiles"][company]
    assert profile["source"] == "common/company_types/00_companies_ip5.txt"
    rules = [row for row in data["rules"] if row["field"] == company + ".ai_weight"]
    assert rules
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", row["id"]) for row in rules)
    policy = dict(adapters.policies)[profile["source"]]
    assert {row["id"] for row in rules} <= {row.id for row in policy.rules}
    assert all(
        row.field == (company, "ai_weight")
        for row in policy.rules
        if row.id in {item["id"] for item in rules}
    )


@pytest.mark.unit
def test_native_authority_cannot_bless_an_empty_numeric_block():
    declaration = {
        "sources": {"fixture.txt": "unused"},
        "initial_values": [],
        "scalar_values": [],
        "rules": [{"source": "fixture.txt", "field": "building.ai_value"}],
    }
    with pytest.raises(ValueError, match="数值块"):
        decision_adapters.native_contract_data(
            declaration, {"fixture.txt": "building = { ai_value = { } }"}
        )


@pytest.mark.integration
def test_changed_default_cannot_hide_behind_an_updated_source_hash():
    with version_contracts.select_version(
        config.game_version()["caligula_branch"].removeprefix("release/")
    ):
        adapters = decision_adapters.load()
        texts = decision_adapters.read_inputs(adapters)
        source = "common/defines/00_ai.txt"
        native = texts[source]
        texts[source], substitutions = re.subn(
            r"(PRODUCTION_BUILDING_BASE_VALUE\s*=\s*)1000", r"\g<1>1001", native, count=1
        )
        assert substitutions == 1
        # Rehashing a source declaration is insufficient: exact defaults and
        # parent ASTs remain independently pinned in the authority artifact.
        from dataclasses import replace

        sources = dict(adapters.sources)
        sources[source] = hashlib.sha256(texts[source].encode()).hexdigest()
        changed = replace(adapters, sources=tuple(sorted(sources.items())))
        with pytest.raises(ValueError, match="native parent/field/default AST drift"):
            decision_adapters.read_inputs(changed, texts=texts)


@pytest.mark.unit
@pytest.mark.parametrize("damage", ["old-helper", "prefix", "quoted", "extra-scalar"])
def test_current_subject_branch_requires_complete_exact_reachability_ast(damage):
    baseline = "ai_strategy_default = { subject_value = { value = 50 if = { limit = { OR = { scope:target_country = { is_subject_of = root } can_reach_target_country_to_subjugate = { TARGET_COUNTRY = scope:target_country } } } add = 0 } multiply = 0 } }"
    if damage == "old-helper":
        baseline = baseline.replace(
            "can_reach_target_country_to_subjugate", "can_reach_target_country"
        )
    elif damage == "prefix":
        baseline = baseline.replace("OR =", "INJECT:OR =")
    elif damage == "quoted":
        baseline = baseline.replace("is_subject_of = root", 'is_subject_of = "root"')
    else:
        baseline = baseline.replace("limit = {", "limit = { stray_atom")
    with version_contracts.select_version("1.15.0"), pytest.raises(ValueError, match="保护形状"):
        decision_rules._protected_offsets(
            baseline,
            {("ai_strategy_default", "subject_value")},
            parse_text(baseline).root,
            (),
        )


@pytest.mark.integration
def test_new_scripted_predicate_is_reproducible_without_reading_old_manifest(tmp_path, monkeypatch):
    expected = decision_interfaces.scripted_predicate_path().read_bytes()
    destination = tmp_path / "current-predicate.json"
    monkeypatch.setattr(decision_interfaces, "scripted_predicate_path", lambda: destination)
    monkeypatch.setattr(
        decision_interfaces, "SCRIPTED_PREDICATE_SOURCE", tmp_path / "absent-old.json"
    )
    decision_interfaces.write_scripted_trigger_authority_115(config.GAME)
    assert destination.read_bytes() == expected
    destination.write_bytes(expected + b" ")
    with pytest.raises(ValueError, match="existing reviewed evidence drift"):
        decision_interfaces.write_scripted_trigger_authority_115(config.GAME)
    assert destination.read_bytes() == expected + b" "


@pytest.mark.integration
def test_current_state_witness_retains_optional_owner_and_victim_memory():
    sources = (
        decision_interfaces.STATE_DEVASTATION_SOURCE,
        "common/on_actions/00_code_on_actions.txt",
    )
    texts = {source: (config.GAME / source).read_text(encoding="utf-8-sig") for source in sources}
    assert "owner ?=" in texts[sources[0]]
    with version_contracts.select_version(
        config.game_version()["caligula_branch"].removeprefix("release/")
    ):
        references = decision_interfaces.verify_state_devastation_sources(texts)
        assert len(references) == 3
        changed = {**texts, sources[0]: texts[sources[0]].replace("owner ?=", "owner =")}
        with pytest.raises(ValueError, match="来源漂移"):
            decision_interfaces.verify_state_devastation_sources(changed)


@pytest.mark.unit
@pytest.mark.parametrize(
    "damage", ["schema", "version", "provenance", "claim", "nested-claim", "missing-pm"]
)
def test_current_company_envelope_cannot_claim_version_provenance_or_nested_authority(
    tmp_path, monkeypatch, damage
):
    data = json.loads(company_sectors.BASELINE_115.read_bytes())
    if damage == "schema":
        data["schema"] = True
    elif damage == "version":
        data["game_version"] = "1.14.5"
    elif damage == "provenance":
        data["provenance"]["builder_source_sha256"] = "0" * 64
    elif damage == "claim":
        data["verified"] = True
    elif damage == "nested-claim":
        data["payload"]["profiles"]["company_lkab"]["verified"] = True
    else:
        building = data["payload"]["profiles"]["company_lkab"]["base_recipes"][0]
        data["payload"]["building_profiles"][building]["groups"][0]["methods"] = []
    path = tmp_path / "company-current.json"
    path.write_text(company_sectors._canonical(data), encoding="utf-8", newline="\n")
    monkeypatch.setattr(company_sectors, "BASELINE_115", path)
    with version_contracts.select_version("1.15.0"), pytest.raises(ValueError):
        company_sectors.load_baseline()


@pytest.mark.integration
def test_current_company_recapture_requires_installed_authority_before_replacing_evidence(
    tmp_path, monkeypatch
):
    destination = tmp_path / "evidence.json"
    destination.write_bytes(b"prior reviewed artifact")
    monkeypatch.setattr(company_sectors, "BASELINE_115", destination)
    with version_contracts.select_version("1.15.0"):
        inputs = company_sectors.read_inputs(config.GAME)
        monkeypatch.setattr(company_sectors, "read_inputs", lambda _game: inputs)
        with pytest.raises(ValueError):
            company_sectors.write_baseline(tmp_path / "missing-game")
    assert destination.read_bytes() == b"prior reviewed artifact"


@pytest.mark.unit
def test_current_company_builder_identity_includes_helpers_outside_derive(tmp_path, monkeypatch):
    source = Path(company_sectors.__file__).read_bytes()
    changed = source.replace(b"def _building(", b"def _changed_building(", 1)
    assert changed != source
    alternate = tmp_path / "company_sectors.py"
    alternate.write_bytes(changed)
    monkeypatch.setattr(company_sectors, "__file__", str(alternate))
    with (
        version_contracts.select_version("1.15.1"),
        pytest.raises(ValueError, match="生成来源漂移"),
    ):
        company_sectors.load_baseline()
