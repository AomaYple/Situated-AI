"""Fixed observations: exact native templates, typed boundaries and provenance."""

import hashlib
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from pdx import config
from pdx import observation_queries as queries
from pdx.parser import parse_text
from pdx.textio import normalized_text

LAW = queries.LawMovementSupport("law_anarchy", 0.10)
IG = queries.LawInterestGroupSupport("law_anarchy")
STATE = queries.AnyStateMarketAccessBelow(0.9)
ART = queries.OwnBuildingActiveMethod("building_art_academy", "pm_realist_art", 1)
QUERIES = (LAW, STATE, ART, IG)


@pytest.mark.parametrize(
    ("engine", "parameters", "expected"),
    [
        ("any_political_movement", {"law": "law_anarchy", "minimum_support": "0.10"}, LAW),
        ("any_interest_group", {"law": "law_anarchy"}, IG),
        ("any_scope_state", {"threshold": "0.90"}, STATE),
        (
            "any_scope_building",
            {"building": "building_art_academy", "method": "pm_realist_art", "min_level": "1"},
            ART,
        ),
    ],
)
def test_exact_reader_parameter_signatures_have_fixed_typed_meaning(engine, parameters, expected):
    assert queries.from_reader(engine, parameters) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            LAW,
            "any_political_movement = { law_enactment_stance = { law = law_type:law_anarchy value > neutral } political_movement_support >= 0.1 }",
        ),
        (
            IG,
            "any_interest_group = { law_stance = { law = law_type:law_anarchy value > neutral } }",
        ),
        (STATE, "any_scope_state = { market_access < 0.9 }"),
        (
            ART,
            "any_scope_building = { is_building_type = building_art_academy has_active_production_method = pm_realist_art level >= 1 }",
        ),
    ],
)
def test_handwritten_exact_pdx_templates_and_owned_collection_names(query, expected):
    rendered = queries.render(query)
    assert rendered == expected
    assert not parse_text(rendered).errors
    assert "any_country" not in rendered
    assert "any_neighbouring" not in rendered
    assert "scope:target_country" not in rendered


def test_render_and_parameter_conversion_do_not_read_files(monkeypatch):
    def fail(*_args, **_kwargs):
        pytest.fail("pure rendering attempted filesystem I/O")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)
    assert queries.render(queries.from_reader("any_scope_state", {"threshold": "1"})) == (
        "any_scope_state = { market_access < 1.0 }"
    )


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"law": "law_anarchy"},
        {"law": "law_anarchy", "minimum_support": ".1"},
        {"law": "law_anarchy", "minimum_support": "1e-1"},
        {"law": "law_anarchy", "minimum_support": "nan"},
        {"law": "law_anarchy", "minimum_support": "inf"},
        {"law": "law_anarchy", "minimum_support": "-0.1"},
        {"law": "law_anarchy", "minimum_support": "1.01"},
        {"law": "law_anarchy", "minimum_support": " 0.1"},
        {"law": "law_anarchy", "minimum_support": "00.1"},
        {"law": "law_anarchy", "minimum_support": True},
        {"law": "law_anarchy", "minimum_support": 0.1},
        {"law": "law_anarchy", "minimum_support": "0.1", "scope": "other_country"},
        {"law": "law_unknown", "minimum_support": "0.1"},
        {"law": "law_type:law_anarchy", "minimum_support": "0.1"},
        {"law": "law_anarchy } always = yes", "minimum_support": "0.1"},
    ],
)
def test_movement_reader_rejects_wrong_shape_invalid_ids_and_free_expression(parameters):
    with pytest.raises(ValueError):
        queries.from_reader("any_political_movement", parameters)


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"threshold": "0"},
        {"threshold": "1.1"},
        {"threshold": "-0.1"},
        {"threshold": "NaN"},
        {"threshold": "1", "infrastructure_delta": "-20"},
        {"threshold": "1", "owner": "ROOT"},
    ],
)
def test_state_query_is_only_the_proven_market_access_template(parameters):
    with pytest.raises(ValueError):
        queries.from_reader("any_scope_state", parameters)


@pytest.mark.parametrize(
    "changes",
    [
        {"building": "building_arts_academy"},
        {"building": "building_railway"},
        {"method": "pm_unknown"},
        {"method": "pm_public_motor_carriages"},
        {"min_level": "0"},
        {"min_level": "1001"},
        {"min_level": "1.0"},
        {"min_level": "01"},
        {"min_level": "-1"},
        {"min_level": "1e2"},
        {"min_level": "1", "state": "root"},
    ],
)
def test_building_query_cannot_mix_building_types_aliases_methods_or_extra_scopes(changes):
    parameters = {
        "building": "building_art_academy",
        "method": "pm_realist_art",
        "min_level": "1",
        **changes,
    }
    with pytest.raises(ValueError):
        queries.from_reader("any_scope_building", parameters)


@pytest.mark.parametrize(
    "query",
    [
        queries.LawMovementSupport("law_anarchy", True),
        queries.LawMovementSupport("law_anarchy", float("nan")),
        queries.AnyStateMarketAccessBelow(float("inf")),
        queries.AnyStateMarketAccessBelow(0),
        queries.OwnBuildingActiveMethod("building_art_academy", "pm_realist_art", True),
        queries.OwnBuildingActiveMethod("building_art_academy", "pm_realist_art", cast("Any", 1.5)),
        "any_country = { always = yes }",
        object(),
    ],
)
def test_direct_dataclass_construction_cannot_bypass_validation(query):
    with pytest.raises(ValueError):
        queries.render(query)


def test_only_four_collection_engines_are_registered():
    assert {
        "any_political_movement",
        "any_scope_state",
        "any_scope_building",
        "any_interest_group",
    } == queries.QUERY_ENGINES
    with pytest.raises(ValueError):
        queries.from_reader("any_country", {"threshold": "1"})


@pytest.fixture(scope="module")
def native_texts() -> dict[str, str]:
    return {
        source: (config.GAME / source).read_text(encoding="utf-8-sig")
        for source in queries.SOURCE_HASHES
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    "query",
    [
        *(queries.LawMovementSupport(law) for law in queries.LAW_SOURCES),
        *(queries.LawInterestGroupSupport(law) for law in queries.LAW_SOURCES),
        STATE,
        *(replace(ART, method_id=method) for method in sorted(queries.ART_METHODS)),
    ],
)
def test_real_original_sources_compile_all_supported_ids_with_precise_provenance(
    native_texts, query
):
    compiled = queries.compile_query(query, native_texts)
    assert compiled.expression == queries.render(query)
    assert (compiled.actor, compiled.kind, compiled.world_scans) == ("country", "boolean", 0)
    assert set(dict(compiled.source_hashes)) == set(queries.required_sources(query))
    assert compiled.unknown_policy == queries.UNKNOWN_POLICY
    assert "missing_collection=unknown" in compiled.unknown_policy
    assert "complete_empty_collection=false" in compiled.unknown_policy
    assert "not constant time" in compiled.runtime_cost
    assert compiled.local_collections in (
        ("owned_political_movements",),
        ("owned_states",),
        ("owned_buildings",),
        ("owned_interest_groups",),
    )
    for source, digest in compiled.source_hashes:
        assert hashlib.sha256(normalized_text(native_texts[source]).encode()).hexdigest() == digest
    for reference in compiled.references:
        source, line = reference.rsplit(":", 1)
        assert source in dict(compiled.source_hashes)
        assert 0 < int(line) <= len(native_texts[source].splitlines())


@pytest.mark.integration
@pytest.mark.parametrize("query", QUERIES)
def test_compilation_requires_every_selected_source_and_rejects_source_drift(native_texts, query):
    for source in queries.required_sources(query):
        missing = {key: value for key, value in native_texts.items() if key != source}
        with pytest.raises(ValueError, match="缺少必需原版来源"):
            queries.compile_query(query, missing)
        changed = {**native_texts, source: native_texts[source] + "\n# changed\n"}
        with pytest.raises(ValueError, match="原版来源漂移"):
            queries.compile_query(query, changed)


@pytest.mark.integration
def test_compiler_normalization_matches_production_inputs(native_texts):
    with_bom_crlf = {
        source: "\ufeff" + normalized_text(text).replace("\n", "\r\n")
        for source, text in native_texts.items()
    }
    assert queries.compile_query(STATE, with_bom_crlf) == queries.compile_query(STATE, native_texts)


def _accept_test_source(monkeypatch, source: str, replacement: str) -> None:
    # Permit a deliberately edited test fingerprint to prove the independent
    # AST checks still reject a matching file with an unproved consumer shape.
    monkeypatch.setitem(
        queries.SOURCE_HASHES,
        source,
        hashlib.sha256(normalized_text(replacement).encode()).hexdigest(),
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("query", "source", "old", "new"),
    [
        (
            LAW,
            "common/laws/01_economic_system.txt",
            "political_movement_support >= 0.10",
            "political_movement_support > 0.10",
        ),
        (
            STATE,
            "common/journal_entries/06_portugal_politics.txt",
            "market_access < 1",
            "market_access > 1",
        ),
        (ART, "common/journal_entries/00_art_jes.txt", "occupancy >= 0.9", "occupancy > 0.9"),
        (
            ART,
            "common/buildings/06_urban_center.txt",
            "\t\tpmg_base_building_art_academy",
            "\t\tpmg_unknown_art",
        ),
        (
            ART,
            "common/production_method_groups/06_urban_center.txt",
            "\t\tpm_realist_art",
            "\t\tpm_unknown_art",
        ),
    ],
)
def test_matching_source_fingerprint_does_not_replace_complete_ast_or_membership_evidence(
    native_texts, monkeypatch, query, source, old, new
):
    original = native_texts[source]
    assert old in original
    changed = original.replace(old, new)
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError):
        queries.compile_query(query, {**native_texts, source: changed})


@pytest.mark.integration
def test_law_parameter_must_have_one_actual_definition_even_after_shape_validation(
    native_texts, monkeypatch
):
    source = queries.LAW_SOURCES["law_anarchy"]
    changed = native_texts[source] + "\nlaw_anarchy = { }\n"
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError, match="唯一块"):
        queries.compile_query(LAW, {**native_texts, source: changed})


@pytest.mark.integration
@pytest.mark.parametrize(
    ("query", "source", "key"),
    [
        (LAW, "common/laws/00_distribution_of_power.txt", "law_anarchy"),
        (LAW, "common/laws/01_economic_system.txt", "ai_enact_weight_modifier"),
        (STATE, "common/journal_entries/06_portugal_politics.txt", "complete"),
        (STATE, "common/journal_entries/06_portugal_politics.txt", "any_scope_state"),
        (ART, "common/buildings/06_urban_center.txt", "building_art_academy"),
        (ART, "common/buildings/06_urban_center.txt", "production_method_groups"),
        (ART, "common/production_method_groups/06_urban_center.txt", "production_methods"),
        (ART, "common/production_methods/06_urban_center.txt", "pm_realist_art"),
    ],
)
@pytest.mark.parametrize("operation", ["prefix", "operator"])
def test_repinning_cannot_turn_conditional_or_prefixed_blocks_into_ordinary_evidence(
    native_texts, monkeypatch, query, source, key, operation
):
    original = native_texts[source]
    replacement = "INJECT:" + key + " = {" if operation == "prefix" else key + " ?= {"
    changed, count = re.subn(
        r"(?m)^([ \t]*)" + re.escape(key) + r"[ \t]*=[ \t]*\{",
        lambda match: match[1] + replacement,
        original,
    )
    assert count > 0
    assert not parse_text(changed).errors
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError):
        queries.compile_query(query, {**native_texts, source: changed})


@pytest.mark.integration
@pytest.mark.parametrize(
    ("query", "source", "old"),
    [
        (STATE, "common/journal_entries/06_portugal_politics.txt", "market_access < 1"),
        (LAW, "common/laws/01_economic_system.txt", "political_movement_support >= 0.10"),
        (ART, "common/journal_entries/00_art_jes.txt", "occupancy >= 0.9"),
    ],
)
@pytest.mark.parametrize("extra", ["unexpected", "{}", "INJECT:"])
def test_repinning_cannot_hide_bare_anonymous_or_prefixed_query_members(
    native_texts, monkeypatch, query, source, old, extra
):
    original = native_texts[source]
    assert old in original
    new = extra + old if extra == "INJECT:" else extra + "\n" + old
    changed = original.replace(old, new)
    assert not parse_text(changed).errors
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError):
        queries.compile_query(query, {**native_texts, source: changed})


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source", "key"),
    [
        ("common/buildings/06_urban_center.txt", "building_art_academy"),
        ("common/production_method_groups/06_urban_center.txt", "pmg_base_building_art_academy"),
        ("common/production_methods/06_urban_center.txt", "pm_realist_art"),
    ],
)
def test_repinning_does_not_authorize_duplicate_building_group_or_method_definitions(
    native_texts, monkeypatch, source, key
):
    changed = native_texts[source] + "\n" + key + " = {}\n"
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError, match="唯一块"):
        queries.compile_query(ART, {**native_texts, source: changed})


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"law": "law_unknown"},
        {"law": "law_type:law_anarchy"},
        {"law": "law_anarchy } always = yes"},
        {"law": True},
        {"law": "law_anarchy", "minimum_support": "0.10"},
        {"law": "law_anarchy", "minimum_clout": "0.10"},
        {"law": "law_anarchy", "interest_group": "ig_trade_unions"},
        {"law": "law_anarchy", "stance": "law_enactment_stance"},
    ],
)
def test_interest_group_reader_preserves_exact_actual_stance_and_parameter_identity(parameters):
    with pytest.raises(ValueError):
        queries.from_reader("any_interest_group", parameters)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("value > neutral", "value >= neutral"),
        ("law_stance = {", "law_enactment_stance = {"),
        ("law_stance = {", "INJECT:law_stance = {"),
        ("law_stance = {", "law_stance ?= {"),
        ("law_stance = {", "unexpected law_stance = {"),
        ("law_stance = {", "{} law_stance = {"),
        ("any_interest_group = {", "INJECT:any_interest_group = {"),
        ("any_interest_group = {", "any_interest_group ?= {"),
        ("law = law_type:law_council_republic", "law = law_type:law_anarchy"),
    ],
)
def test_interest_group_query_cannot_repin_inexact_stance_or_conditional_ast(
    native_texts, monkeypatch, old, new
):
    source = "common/journal_entries/00_communism.txt"
    original = native_texts[source]
    assert old in original
    changed = original.replace(old, new)
    assert not parse_text(changed).errors
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError):
        queries.compile_query(IG, {**native_texts, source: changed})


@pytest.mark.integration
def test_interest_group_query_requires_actual_parameter_law_definition(native_texts, monkeypatch):
    source = queries.LAW_SOURCES[IG.law_id]
    original = native_texts[source]
    assert "law_anarchy = {" in original
    changed = original.replace("law_anarchy = {", "law_other_anarchy = {")
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError, match="唯一块"):
        queries.compile_query(IG, {**native_texts, source: changed})


@pytest.mark.integration
def test_market_total_consumption_evidence_has_exact_country_path_car_identity_and_mechanism(
    native_texts,
):
    references = queries.verify_market_consumption_sources(native_texts)
    assert len(references) == 3
    assert {reference.rsplit(":", 1)[0] for reference in references} == set(
        queries.MARKET_CONSUMPTION_SOURCES
    )
    for reference in references:
        source, line = reference.rsplit(":", 1)
        assert 0 < int(line) <= len(native_texts[source].splitlines())


@pytest.mark.integration
@pytest.mark.parametrize("source", queries.MARKET_CONSUMPTION_SOURCES)
def test_market_consumption_requires_each_locked_source(native_texts, source):
    missing = {name: text for name, text in native_texts.items() if name != source}
    with pytest.raises(ValueError, match="缺少必需原版来源"):
        queries.verify_market_consumption_sources(missing)
    with pytest.raises(ValueError, match="原版来源漂移"):
        queries.verify_market_consumption_sources(
            {**native_texts, source: native_texts[source] + "\n#changed\n"}
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        ("events/law_events/state_atheism.txt", "type = country_event", "type = state_event"),
        ("events/law_events/state_atheism.txt", "placement = ROOT", "placement = THIS"),
        (
            "events/law_events/state_atheism.txt",
            "name = state_atheism.1.c",
            "name = state_atheism.1.other",
        ),
        (
            "events/law_events/state_atheism.txt",
            "state_atheism.1 = {",
            "INJECT:state_atheism.1 = {",
        ),
        ("events/law_events/state_atheism.txt", "state_atheism.1 = {", "state_atheism.1 ?= {"),
        (
            "events/law_events/state_atheism.txt",
            "market_goods_consumption > 100",
            "market_goods_consumption >= 100",
        ),
        (
            "events/law_events/state_atheism.txt",
            "market_goods_consumption > 100",
            "INJECT:market_goods_consumption > 100",
        ),
        (
            "events/law_events/state_atheism.txt",
            "market_goods_consumption > 100",
            "unexpected market_goods_consumption > 100",
        ),
        (
            "events/law_events/state_atheism.txt",
            "market_goods_consumption > 100",
            "{} market_goods_consumption > 100",
        ),
        ("events/law_events/state_atheism.txt", "mg:opium = {", "INJECT:mg:opium = {"),
        ("events/law_events/state_atheism.txt", "mg:opium = {", "mg:opium ?= {"),
        (
            "common/scripted_triggers/00_gfx_route_graphics_triggers.txt",
            "mg:automobiles = {",
            "mg:tools = {",
        ),
        (
            "common/scripted_triggers/00_gfx_route_graphics_triggers.txt",
            "mg:automobiles = {",
            "INJECT:mg:automobiles = {",
        ),
        (
            "common/scripted_triggers/00_gfx_route_graphics_triggers.txt",
            "market_goods_sell_orders >= 10",
            "market_goods_consumption > 10",
        ),
        (
            "common/goods/00_goods.txt",
            "pop_consumption_can_add_infrastructure = yes",
            "pop_consumption_can_add_infrastructure = no",
        ),
        (
            "common/goods/00_goods.txt",
            "pop_consumption_can_add_infrastructure = yes",
            "INJECT:pop_consumption_can_add_infrastructure = yes",
        ),
        (
            "common/goods/00_goods.txt",
            "pop_consumption_can_add_infrastructure = yes",
            "pop_consumption_can_add_infrastructure ?= yes",
        ),
        ("common/goods/00_goods.txt", "automobiles = {", "INJECT:automobiles = {"),
    ],
)
def test_repinning_words_cannot_replace_complete_market_consumption_evidence(
    native_texts, monkeypatch, source, old, new
):
    original = native_texts[source]
    assert old in original
    changed = original.replace(old, new)
    assert not parse_text(changed).errors
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError):
        queries.verify_market_consumption_sources({**native_texts, source: changed})


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source", "extra"),
    [
        ("events/law_events/state_atheism.txt", "\nstate_atheism.1 = {}\n"),
        (
            "common/scripted_triggers/00_gfx_route_graphics_triggers.txt",
            "\ngfx_car_condition_trigger = {}\n",
        ),
        ("common/goods/00_goods.txt", "\nautomobiles = {}\n"),
    ],
)
def test_market_consumer_and_goods_definitions_must_remain_unique(
    native_texts, monkeypatch, source, extra
):
    changed = native_texts[source] + extra
    _accept_test_source(monkeypatch, source, changed)
    with pytest.raises(ValueError, match="唯一块"):
        queries.verify_market_consumption_sources({**native_texts, source: changed})
