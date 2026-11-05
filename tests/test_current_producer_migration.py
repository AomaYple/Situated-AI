"""Current initializer and reader contracts reject repins that change semantics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx import building_defaults, config, decision_adapters, decision_interfaces, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text


@pytest.fixture(scope="module")
def current_inputs():
    return json.loads(
        (config.REPO / "research/vanilla-ai/1.15.0/production-inputs.json").read_bytes()
    )["inputs"]


def test_current_law_references_require_complete_registered_definitions(current_inputs):
    source = "common/laws/00_internal_security.txt"
    inputs = {source: current_inputs[source]}
    evidence = decision_adapters.reader_evidence(inputs)
    assert evidence["law_type:law_okhrana"]["source"] == source
    assert evidence["law_type:law_third_section"]["source"] == source
    assert "law_type:law_invented" not in decision_adapters.reader_evidence(
        {source: "law_invented = { group = lawgroup_internal_security }"}
    )
    damaged = inputs[source].replace("law_okhrana = {", "law_invented = {", 1)
    assert "law_type:law_okhrana" not in decision_adapters.reader_evidence({source: damaged})


def test_only_eleven_historical_absent_buildings_have_native_default_permission():
    data = json.loads(building_defaults.snapshot())
    assert len(data["initializers"]) == 11
    assert {row["id"] for row in data["initializers"]} == {
        "building_arms_industry",
        "building_artillery_foundry",
        "building_livestock_ranch",
        "building_logging_camp",
        "building_rubber_plantation",
        "building_fishing_wharf",
        "building_whaling_station",
        "building_oil_rig",
        "building_coffee_plantation",
        "building_sugar_plantation",
        "building_banana_plantation",
    }
    assert {row["define"] for row in data["initializers"]} == {"NAI.PRODUCTION_BUILDING_BASE_VALUE"}
    assert data["contract"]["frame"]["injected_investor_country"] is False
    assert data["contract"]["roles"]["payer"] == "unresolved"
    assert data["contract"]["aggregation"]["zero_is_terminal_in_production_main"] is False
    assert data["contract"]["open_obligations"]


def test_initializer_preserves_complete_parent_and_restores_only_proven_1000(current_inputs):
    source = "common/buildings/01_industry.txt"
    item = decision_adapters.InitialValue(
        source,
        ("building_arms_industry", "ai_value"),
        "common/defines/00_ai.txt",
        ("NAI", "PRODUCTION_BUILDING_BASE_VALUE"),
    )
    original = current_inputs[source]
    rendered = decision_adapters._initialize(original, [item], current_inputs, {})
    fragment = "\n\t# SITAI BEGIN initialized:building_arms_industry.ai_value\n\tai_value = { value = 1000 }\n\t# SITAI END initialized:building_arms_industry.ai_value\n"
    assert rendered.count(fragment) == 1
    assert rendered.replace(fragment, "", 1) == original


@pytest.mark.parametrize(
    "expression", ["0", "{}", "{ if = { limit = { always = no } add = 2000 } }"]
)
def test_explicit_zero_empty_or_false_condition_never_becomes_absent_default(
    current_inputs, expression
):
    source = "common/buildings/01_industry.txt"
    item = decision_adapters.InitialValue(
        source,
        ("building_arms_industry", "ai_value"),
        "common/defines/00_ai.txt",
        ("NAI", "PRODUCTION_BUILDING_BASE_VALUE"),
    )
    text = current_inputs[source].replace(
        "building_arms_industry = {", f"building_arms_industry = {{ ai_value = {expression}", 1
    )
    with pytest.raises(ValueError, match="已经存在"):
        decision_adapters._initialize(text, [item], current_inputs, {})


@pytest.mark.parametrize(
    "change", ["parent", "duplicate", "category", "define", "unknown_building"]
)
def test_initializer_rejects_changed_parent_and_metadata_after_source_repin(current_inputs, change):
    source = "common/buildings/01_industry.txt"
    item = decision_adapters.InitialValue(
        source,
        ("building_arms_industry", "ai_value"),
        "common/defines/00_ai.txt",
        ("NAI", "PRODUCTION_BUILDING_BASE_VALUE"),
    )
    original = current_inputs[source]
    if change == "parent":
        original = original.replace(
            "building_arms_industry = {", "building_arms_industry = { arbitrary_new_cost = 1", 1
        )
    elif change == "duplicate":
        original += "\nbuilding_arms_industry = {}\n"
    elif change == "category":
        original = original.replace(
            "building_arms_industry = {",
            "building_arms_industry = { building_group = bg_government",
            1,
        )
    elif change == "define":
        item = replace(item, define=("NAI", "GOVERNMENT_BUILDING_BASE_VALUE"))
    else:
        item = replace(item, field=("building_textile_mills", "ai_value"))
    # A caller can provide arbitrary newly hashed text; parent authority is independent.
    with pytest.raises(ValueError):
        decision_adapters._initialize(original, [item], {**current_inputs, source: original}, {})


@pytest.mark.parametrize("mutation", ["unit", "role", "comparison", "version"])
def test_lj10_semantic_changes_reject_even_if_outer_manifest_is_repinned(
    tmp_path, monkeypatch, mutation
):
    data = json.loads(decision_interfaces._LJ10_EVIDENCE.read_bytes())
    if mutation == "unit":
        data["positive_native_guard"]["readers"][0]["unit"] = "battalions"
    elif mutation == "role":
        data["reader"]["actor"] = "target_country"
    elif mutation == "comparison":
        data["positive_native_guard"]["comparison"] = (
            "ROOT.wanted_army_size_script_value >= ROOT.wanted_marines_size_script_value"
        )
    else:
        data["baseline"] = "victoria3-1.14.5-windows-x64"
    raw = json.dumps(data).encode()
    path = tmp_path / "proof.json"
    path.write_bytes(raw)
    monkeypatch.setattr(decision_interfaces, "_LJ10_EVIDENCE", path)
    monkeypatch.setattr(
        decision_interfaces, "_LJ10_EVIDENCE_SHA256", hashlib.sha256(raw).hexdigest()
    )
    with pytest.raises(ValueError, match="合同漂移"):
        decision_interfaces.proven_reader_words()


def test_named_army_formula_requires_current_barracks_level_unit():
    reader = decision_rules.Reader(
        "army", "wanted_army_size_script_value", "root", "barracks_levels", "number"
    )
    assert decision_interfaces.reader_scope(reader, ()) == "country"
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(replace(reader, unit="battalions"), ())


@pytest.mark.integration
@pytest.mark.skipif(
    not (config.GAME / "common").is_dir(), reason="requires pinned current installation"
)
def test_current_building_and_lj10_native_spans_sources_and_formula_parents():
    assert len(building_defaults.verify_game(config.GAME)) == 21
    assert (
        dict(decision_interfaces.verify_lj10_game(config.GAME))["@engine/binaries/victoria3.exe"]
        == "473186e8d8deba993651e0ae4cf02a003b02f5accb99b096a6a0a8bd9506cbaa"
    )


def test_current_default_retains_conquest_capacity_and_cossack_structure(current_inputs):
    text = current_inputs["common/ai_strategies/00_default_strategy.txt"]
    definition = parse_text(text).root.first("ai_strategy_default")
    assert definition is not None
    assert isinstance(definition.value, Block)
    root = definition.value
    assert len(root.all("cossack_host_scores")) == 1
    # Exact current full source is pinned independently by the strategy proof;
    # these assertions guard the specifically forbidden legacy restoration.
    goals = root.first("strategic_region_stance_type_scores")
    assert goals is not None
    assert isinstance(goals.value, Block)
    conquest = goals.value.first("stance_conquer_region")
    assert conquest is not None
    assert isinstance(conquest.value, Block)
    scalars = []
    stack = [conquest.value]
    while stack:
        for node in stack.pop().items:
            if not isinstance(node, Assignment):
                continue
            if isinstance(node.value, Block):
                stack.append(node.value)
            elif isinstance(node.value, Scalar):
                scalars.append((node.key, node.op, node.value.unquoted))
    assert ("carrying_capacity", ">=", "10") in scalars
    assert ("navy_size", ">=", "25") not in scalars
