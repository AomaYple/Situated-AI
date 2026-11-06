"""Independent physical/role counterexamples and one actual captured-source check."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_a4_discovery import captured_fixture

from tools.ci import a4_classify as classify
from tools.ci import a4_discovery as discovery
from tools.ci import a4_scope as gate


def physical_fixture():
    raw = captured_fixture()
    by_id = {item["declaration_id"]: item for item in raw["surfaces"]}
    for slot, option in zip(raw["event_slots"], raw["event_options"], strict=True):
        option.update(event_type="state_event", default_option=None)
        for member, line in zip(
            slot["surface_declaration_ids"],
            option["weight_lines"] or [option["source_line"]],
            strict=True,
        ):
            by_id[member]["source_line"] = line
    return raw


def test_physical_identity_preserves_duplicate_fields_slots_and_bare_parent():
    raw = physical_fixture()
    result = classify.classify(raw, discovery.project(raw), {})
    physical = list(result["physical"].values())
    assert len(physical) == 3
    assert len({row["owner_id"] for row in physical}) == 2
    assert len({row["slot"]["slot_id"] for row in physical}) == 2
    explicit = [row for row in physical if row["slot"]["explicit_weight"]]
    assert [row["source_line"] for row in explicit] == [5, 6]
    assert explicit[0]["node_positions"] != explicit[1]["node_positions"]
    assert len(result["observations"]) == len(discovery.project(raw)["entries"])
    assert result["raw_duplicates"] == discovery.project(raw)["raw_duplicates"]
    assert all(row["original_ambiguity"] for row in physical)
    bare_owner = next(item for item in raw["definitions"] if item["definition"] == "data")
    protection = result["structures"][bare_owner["declaration_id"]]
    assert protection["reference_ids"] == ["ref-physical"]
    assert protection["protection_acceptance"].startswith("pending")


def test_missing_weight_and_state_event_never_receive_country_or_default_authority():
    raw = physical_fixture()
    result = classify.classify(raw, discovery.project(raw), {})
    missing = next(
        row for row in result["physical"].values() if row["syntax_kind"] == "missing_field"
    )
    assert missing["slot"]["event_type"] == "state_event"
    assert missing["slot"]["node_position"] == [1, -1, 0]
    assert missing["node_ids"] == []
    assert missing["contract"] is None
    assert missing["interface_status"] == "pending"
    assert missing["obligation_status"] == "pending"
    assert not missing["writer_authority"]
    assert not missing["getter_authority"]


@pytest.mark.parametrize("fault", ["owner", "field_line", "slot_line", "drop_member"])
def test_physical_source_owner_and_ast_omissions_fail(fault):
    raw = physical_fixture()
    catalog = discovery.project(raw)
    if fault == "owner":
        raw["definitions"][2]["definition_index"] = 1
    elif fault == "field_line":
        raw["surfaces"][0]["source_line"] = 900
    elif fault == "slot_line":
        raw["event_slots"][0]["source_line"] = 900
    else:
        raw["definitions"][2]["surface_declaration_ids"].pop()
    with pytest.raises((ValueError, KeyError)):
        classify.classify(raw, catalog, {})


@pytest.mark.parametrize("fault", ["source", "owner", "field", "definition_key"])
def test_contract_applicability_does_not_follow_names_or_repin(fault):
    source = "common/company_types/example.txt"
    contracts = {
        "company_types": {
            "path": "proof.json",
            "member": "contracts",
            "data": {
                "script_hashes": {source: "a" * 64},
                "contracts": [
                    {
                        "field": "ai_weight",
                        "actor": "country",
                        "target": "definition_only:company_type",
                        "operation": "base_candidate_score",
                    }
                ],
            },
        }
    }
    row = {
        "family": "company_types",
        "field": "ai_weight",
        "source": source,
        "definition": "ai_country_technology",
    }
    proven = classify.applicable_contract(row, "a" * 64, contracts)
    assert proven is not None
    assert proven["actor"] == "country"
    assert proven["target"] == "definition_only:company_type"
    if fault == "source":
        digest = "b" * 64
    else:
        digest = "a" * 64
        row[{"owner": "family", "field": "field", "definition_key": "field"}[fault]] = {
            "owner": "company_charter_types",
            "field": "ai_construction_targets",
            "definition_key": "ai_country_technology",
        }[fault]
    assert classify.applicable_contract(row, digest, contracts) is None


@pytest.mark.parametrize(
    ("family", "field", "token", "expected"),
    [
        (
            "production_method_groups",
            "ai_selection",
            "most_profitable",
            "literal_enum_or_reference",
        ),
        ("modifier_type_definitions", "game_data.ai_value", "0", "literal_constant"),
        (
            "ship_types",
            "ai_ship_category",
            "ai_ship_category_submarines",
            "literal_enum_or_reference",
        ),
        ("scripted_buttons", "ai_chance", "0", "literal_constant"),
    ],
)
def test_literal_syntax_does_not_claim_live_getter_or_zero_rejection(
    family, field, token, expected
):
    node = {"kind": "scalar", "text": token}
    assert classify.syntax_kind(family, field, node) == expected


def test_product_selectors_preserve_physical_occurrence_and_exact_family():
    records = {
        "copper_1": {
            "family": "buildings",
            "definition": "building_copper_mine",
            "field": "ai_value",
        },
        "copper_2": {
            "family": "buildings",
            "definition": "building_copper_mine",
            "field": "ai_value",
        },
        "charter": {
            "family": "company_charter_types",
            "definition": "building_copper_mine",
            "field": "ai_value",
        },
        "display": {
            "family": "buildings",
            "definition": "building_copper_mine",
            "field": "display_name",
        },
    }
    selector = [{"family": "buildings", "definition": "copper", "field": "^ai_value$"}]
    assert classify.select(records, selector) == ["copper_1", "copper_2"]


@pytest.mark.parametrize("fault", ["target", "predecessor", "physical", "completion"])
def test_product_mapping_cannot_drop_original_targets_or_sign_by_metadata(fault):
    maps = {
        "targets": {"B02.6": {"physical_ids": ["copper"], "status": "pending"}},
        "predecessors": {"old": {"physical_ids": ["copper"], "status": "pending"}},
    }
    if fault == "target":
        maps["targets"].clear()
    elif fault == "predecessor":
        maps["predecessors"].clear()
    elif fault == "physical":
        maps["targets"]["B02.6"]["physical_ids"] = ["invented"]
    else:
        maps["targets"]["B02.6"]["status"] = "verified"
    with pytest.raises(ValueError):
        classify.verify_product_maps(maps, {"copper": {}}, {"B02.6"}, {"old"})


def _writer_product_fixture():
    source = "common/buildings/a.txt"
    physical = {"observed": {"source": source, "definition": "building_a", "field": "ai_weight"}}
    structures = {
        "parent": {"source": source, "definition": "building_a"},
        "other_source": {"source": "common/buildings/b.txt", "definition": "building_a"},
        "other_parent": {"source": source, "definition": "building_b"},
    }
    writers = {
        "direct": {
            "source": source,
            "field": "building_a.ai_weight",
            "native_source": source,
            "native_field": "building_a.ai_weight",
            "native_parent_ids": ["parent"],
            "native_physical_ids": ["observed"],
            "actor": "root",
            "target": "state",
        },
        "child": {
            "source": source,
            "field": "building_a.ai_construction_targets.building_copper_mine.value",
            "native_source": source,
            "native_field": "building_a.ai_construction_targets.building_copper_mine.value",
            "native_parent_ids": ["parent"],
            "native_physical_ids": [],
            "actor": "owner",
            "target": "state",
        },
    }
    maps = {
        "targets": {
            "G01": {"physical_ids": ["observed"], "structural_ids": []},
            "U01": {"physical_ids": ["observed"], "structural_ids": []},
            "B01.1": {"physical_ids": ["observed"], "structural_ids": ["parent"]},
            "B01.2": {"physical_ids": [], "structural_ids": ["other_source", "other_parent"]},
            "R01": {"physical_ids": ["observed"], "structural_ids": ["parent"]},
        },
        "predecessors": {
            "implemented": {
                "physical_ids": ["observed"],
                "structural_ids": ["parent"],
                "migration_contract": {"actor": "root", "target": "state"},
            },
            "pending": {"physical_ids": ["observed"], "structural_ids": ["parent"]},
        },
    }
    classify.bind_product_writers(physical, structures, writers, maps)
    return physical, structures, writers, maps


def test_parent_only_products_preserve_full_child_role_and_exact_migration_selection():
    physical, structures, writers, maps = _writer_product_fixture()
    child = writers["child"]
    assert child["native_physical_ids"] == []
    assert (child["actor"], child["target"]) == ("owner", "state")
    assert child["native_field"] == "building_a.ai_construction_targets.building_copper_mine.value"
    assert child["product_bindings"] == {
        "status": "pending",
        "writer_authority": False,
        "goal_edges": {
            "G01": "all_current_writers",
            "U01": "all_current_writers",
            "B01.1": "exact_native_parent_child_field",
            "R01": "exact_native_parent_child_field",
            "predecessor:pending": "exact_native_parent_child_field",
        },
    }
    assert maps["targets"]["B01.2"]["current_writer_ids"] == []
    assert maps["predecessors"]["implemented"]["current_writer_ids"] == ["direct"]
    assert maps["predecessors"]["pending"]["current_writer_ids"] == ["child", "direct"]
    assert set(physical) == {"observed"}
    classify.verify_writer_product_closure(physical, structures, writers, maps)


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "parent_source",
        "parent",
        "field",
        "reparent",
        "child_field",
        "goal_omission",
        "writer_omission",
        "authority",
    ],
)
def test_parent_only_product_closure_rejects_source_parent_field_and_edge_drift(fault):
    physical, structures, writers, maps = _writer_product_fixture()
    child = writers["child"]
    if fault == "source":
        child["native_source"] = "common/buildings/b.txt"
    elif fault == "parent_source":
        structures["parent"]["source"] = "common/buildings/c.txt"
    elif fault == "parent":
        child["native_parent_ids"] = ["other_parent"]
    elif fault == "field":
        child["native_field"] = "building_b.ai_value"
    elif fault == "reparent":
        child["native_source"] = "common/buildings/b.txt"
        child["native_parent_ids"] = ["other_source"]
    elif fault == "child_field":
        child["native_field"] = "building_a.unrelated_child.value"
    elif fault == "goal_omission":
        maps["targets"]["U01"]["current_writer_ids"].remove("child")
    elif fault == "writer_omission":
        del child["product_bindings"]["goal_edges"]["B01.1"]
    else:
        child["product_bindings"]["writer_authority"] = True
    with pytest.raises(
        ValueError, match=r"source/parent/child|closure drift|edge/status/authority"
    ):
        classify.verify_writer_product_closure(physical, structures, writers, maps)


def test_parent_only_product_closure_requires_concrete_B_responsibility():
    physical, structures, writers, maps = _writer_product_fixture()
    maps["targets"]["B01.1"]["structural_ids"] = []
    with pytest.raises(ValueError, match="lacks concrete B responsibility"):
        classify.bind_product_writers(physical, structures, writers, maps)


@pytest.fixture(scope="module")
def actual_projection():
    sources = gate.Sources(Path(__file__).resolve().parents[1])
    values = classify.artifacts(sources)
    return sources, values


def test_actual_all_current_writers_keep_global_and_parent_only_product_responsibilities(
    actual_projection,
):
    _, values = actual_projection
    writers, targets = values["migration_writers"], values["targets"]
    child_ids = {key for key, writer in writers.items() if not writer["native_physical_ids"]}
    assert len(child_ids) == 425
    assert Counter(writers[key]["kind"] for key in child_ids) == {
        "rule_action": 392,
        "supply_program": 33,
    }
    for goal, target in targets.items():
        if goal.startswith(("G", "U")):
            assert set(target["current_writer_ids"]) == set(writers)
        if goal.startswith("R"):
            for endpoint, directions in target["endpoints"].items():
                assert target["structural_endpoints"][endpoint] == sorted(
                    {
                        parent
                        for direction in directions
                        for parent in targets[direction]["structural_ids"]
                    }
                )
    for identity in child_ids:
        writer = writers[identity]
        assert any(goal.startswith("B") for goal in writer["product_bindings"]["goal_edges"])
        assert writer["product_bindings"]["status"] == "pending"
        assert writer["product_bindings"]["writer_authority"] is False
        assert all(
            values["structures"][parent]["source"] == writer["native_source"]
            and writer["native_field"].startswith(values["structures"][parent]["definition"] + ".")
            for parent in writer["native_parent_ids"]
        )
    for target in [*targets.values(), *values["predecessors"].values()]:
        members = set(target["physical_ids"])
        old_direct = {
            key
            for key, writer in writers.items()
            if members.intersection(writer["native_physical_ids"])
        }
        new_direct = set(target["current_writer_ids"]) - child_ids
        assert new_direct == old_direct
        if target.get("migration_contract"):
            assert set(target["current_writer_ids"]) == old_direct
    assert len(values["physical"]) == len(values["responsibilities"]) == 14924


def test_actual_classification_matches_captured_ast_and_unchanged_target_denominators(
    actual_projection,
):
    sources, values = actual_projection
    physical = values["physical"]
    assert len(physical) == 14924
    assert len(values["observations"]) == 56196
    assert len(values["structures"]) == 22465
    assert len(values["unexpanded_observations"]) == 71
    slots = [row["slot"] for row in physical.values() if row["slot"]]
    assert len(slots) == 5158
    assert Counter(slot["explicit_weight"] for slot in slots) == {True: 1599, False: 3559}
    assert sum(bool(row["original_ambiguity"]) for row in physical.values()) == 42
    assert Counter(row["family"] for row in physical.values())["scripted_buttons"] == 263
    assert len({row["slot"]["slot_id"] for row in physical.values() if row["slot"]}) == 5158
    assert {key[0] for key in values["targets"]} == {"G", "B", "R", "U"}
    assert Counter(key[0] for key in values["targets"]) == {"G": 8, "B": 64, "R": 12, "U": 10}
    assert len(values["predecessors"]) == 96
    assert len(values["semantic_resolutions"]) == 34
    event = values["shared_native_atoms"]["event"]
    assert len(event["physical_bindings"]) == 41
    assert Counter(row["event_type"] for row in event["physical_bindings"].values()) == {
        "state_event": 25,
        "country_event": 10,
        None: 6,
    }
    assert not values["shared_native_atoms"]["innovation"]["B04_2_complete"]
    for goal, family, definition in [
        ("B04.2", "buildings", "building_university"),
        ("B12.5", "ai_strategies", "ai_strategy_default"),
    ]:
        members = [physical[m] for m in values["targets"][goal]["physical_ids"]]
        assert any(row["family"] == family and row["definition"] == definition for row in members)
    copper_parents = [values["structures"][m] for m in values["targets"]["B02.6"]["structural_ids"]]
    assert any(row["definition"] == "building_copper_mine" for row in copper_parents)
    assert not any(row["definition"] == "building_copper_mine" for row in physical.values())
    assert all(
        not row["writer_authority"] and not row["getter_authority"] for row in physical.values()
    )
    for name, value in values.items():
        assert sources.json(f"{classify.DIRECTORY}/{name}.json") == value


@pytest.mark.parametrize("fault", ["owner", "occurrence", "field", "original_ambiguity"])
def test_reviewed_family_proof_rejects_wrong_physical_applicability(actual_projection, fault):
    sources, values = actual_projection
    identity = next(iter(values["semantic_resolutions"]))
    physical = dict(values["physical"])
    physical[identity] = dict(physical[identity])
    if fault == "owner":
        physical[identity]["definition"] = "other_button_same_field"
    elif fault == "occurrence":
        physical[identity]["node_positions"] = [[0, -1, 0]]
    elif fault == "field":
        physical[identity]["field"] = "ai_weight"
    else:
        physical[identity]["original_ambiguity"] = None
    with pytest.raises(ValueError, match="wrong owner/field/occurrence"):
        classify.repeated_resolutions(sources, physical)


def test_actual_migration_indexes_writers_readers_ast_and_fixed_task6_package(actual_projection):
    import gzip
    import hashlib
    import io
    import json
    import zipfile

    sources, values = actual_projection
    writers = values["migration_writers"]
    assert len(writers) == 6193
    assert Counter(row["kind"] for row in writers.values()) == {
        "rule_action": 6114,
        "action_card": 11,
        "supply_program": 33,
        "event_program": 28,
        "acceptance_program": 6,
        "regional_resource_program": 1,
    }
    assert all(row["native_parent_ids"] for row in writers.values())
    assert all(
        row["generated_path"] in {"mod/" + path for path in values["migration_files"]}
        for row in writers.values()
    )
    assert any(row["reader_context_bindings"] for row in writers.values())
    university = [row for row in writers.values() if row["field"] == "building_university.ai_value"]
    assert university
    assert {row["actor"] for row in university} == {"owner"}
    assert not any(row["field"] == "building_copper_mine.ai_value" for row in writers.values())
    assert len(values["migration_files"]) == 117
    packed = sources.read(classify.PACKAGE)
    package = gzip.decompress(packed)
    assert hashlib.sha256(package).hexdigest() == classify.PACKAGE_SHA256
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("DISTRIBUTION-MANIFEST.json"))
        assert manifest
        for path in values["migration_files"]:
            data = archive.read(path)
            generated = (sources.root / "mod" / path).read_bytes()
            assert data == (
                b"\xef\xbb\xbf" + generated if path.endswith((".txt", ".yml")) else generated
            )


def test_protection_or_literal_classification_cannot_close_product_need():
    row = {
        "disposition": "retain_native",
        "interface_status": "native_handled",
        "obligation_status": "pending",
    }
    assert gate.conclusion(row) == "nonterminal"
    row.update(disposition="unsupported", interface_status="boundary_unknown")
    assert gate.conclusion(row) == "nonterminal"


def _legacy_fact_fixture(predicates, *, required=(), anchors=(), context=False):
    from pdx.situated.decision_ir import (
        ConsumerIRBundle,
        ContextBinding,
        EvaluationContext,
        LegacyDecisionIR,
        WriterDecisionIR,
    )

    source = (
        "common/diplomatic_actions/40_subjects_knowledge_sharing.txt"
        if context
        else "common/buildings/06_urban_center.txt"
    )
    definition = "da_knowledge_sharing" if context else "building_art_academy"
    field = "ai.propose_score" if context else "ai_value"
    actor = "root" if context else "owner"
    legacy = LegacyDecisionIR(
        action_id="writer",
        source=source,
        definition="rule",
        domain="market",
        consumer_id=f"{definition}.{field}",
        field=f"{definition}.{field}",
        actor=actor,
        target="none",
        operation="multiply",
        value=0.9,
        predicates=predicates,
        vanilla_tail="preserve",
        required_known_facts=required,
        unknown_cost_required_known_facts=anchors,
    )
    writer = WriterDecisionIR(
        writer_id="writer",
        kind="rule_action",
        source=source,
        definition="rule",
        consumer_id=legacy.consumer_id,
        field=legacy.field,
        actor=actor,
        target="none",
        operation="multiply",
        vanilla_tail="preserve",
        owner="consumer_adapters",
        legacy=legacy,
        predicates=predicates,
        evaluation_context=EvaluationContext(
            status="observed",
            actor_scope=ContextBinding("root", "country", "actor", source, 1),
            targets=(),
            auxiliary_scopes=(),
            evidence=(source + ":1",),
        )
        if context
        else None,
        reader_context_bindings=((predicates[0][0], "root", "country", "actor"),)
        if context
        else (),
    )
    physical = {"physical": {"source": source, "definition": definition, "field": field}}
    parents = {"parent": {"source": source, "definition": definition}}
    return ConsumerIRBundle(schema=1, actions=(), writers=(writer,)), physical, parents


@pytest.mark.parametrize(
    ("predicates", "anchors", "expected"),
    [
        (
            (("state_owner_default", "=", True),),
            ("cost_owner_population",),
            ["cost_owner_population", "state_owner_default"],
        ),
        ((("state_owner_fine_art_balance", "<", 0.0),), (), ["state_owner_fine_art_balance"]),
        (
            (("state_owner_fine_art_balance", "<", 0.0), ("state_owner_fine_art_price", ">", 0.25)),
            (),
            ["state_owner_fine_art_balance", "state_owner_fine_art_price"],
        ),
        ((("state_infrastructure", "<", 0.0),), (), ["state_infrastructure"]),
    ],
)
def test_null_context_art_writers_keep_exact_production_fact_inputs(predicates, anchors, expected):
    bundle, physical, parents = _legacy_fact_fixture(predicates, anchors=anchors)
    row = classify.migration_writers(bundle, physical, parents)["writer"]
    assert row["fact_ids"] == expected
    assert row["evaluation_context"] is None
    assert row["reader_context_bindings"] == []
    assert row["actor"] == "owner"


def test_fact_input_union_preserves_rhs_required_and_existing_context_without_duplicates():
    from pdx.decision_rules import FactReference

    bundle, physical, parents = _legacy_fact_fixture(
        (("balance", "<", FactReference("reserve", "ROOT.reserve")),),
        required=("entity",),
        anchors=("entity",),
        context=True,
    )
    row = classify.migration_writers(bundle, physical, parents)["writer"]
    assert row["fact_ids"] == ["balance", "entity", "reserve"]
    assert row["reader_context_bindings"] == [["balance", "root", "country", "actor"]]
    assert row["semantics"]["legacy_action"]["predicates"][0][2] == {
        "key": "reserve",
        "expression": "ROOT.reserve",
    }


@pytest.mark.parametrize("role", ["actor", "target"])
def test_fact_input_extraction_does_not_authorize_a_changed_legacy_role(role):
    bundle, physical, parents = _legacy_fact_fixture((("state_infrastructure", "<", 0.0),))
    bundle = replace(bundle, writers=(replace(bundle.writers[0], **{role: "foreign"}),))
    with pytest.raises(ValueError, match="actor/target drift"):
        classify.migration_writers(bundle, physical, parents)


def _program_reader_fixture(source="events/a.txt", scope="root", role="actor"):
    reader = {
        "key": "default",
        "engine": "in_default",
        "scope": scope,
        "unit": "boolean",
        "kind": "boolean",
        "argument": None,
        "minimum": None,
        "maximum": None,
        "path": [],
        "value_field": None,
        "parameters": [],
    }
    actor = {"name": "root", "kind": "country", "role": "actor", "source": source, "line": 1}
    target = {"name": scope, "kind": "country", "role": role, "source": source, "line": 2}
    return {
        "writer_id": "option",
        "source": source,
        "event_program": {
            "readers": [reader],
            "reader_context_bindings": [["default", scope, "country", role]],
        },
        "reader_context_bindings": [["default", scope, "country", role]],
        "evaluation_context": {
            "status": "observed",
            "actor_scope": actor,
            "targets": [target] if scope != "root" else [],
            "auxiliary_scopes": [],
            "evidence": [source + ":1", source + ":2"],
        },
    }


def test_program_local_getters_cannot_borrow_global_or_other_source_role():
    first = classify.program_reader_facts(_program_reader_fixture())["default"]
    second = classify.program_reader_facts(
        _program_reader_fixture("events/b.txt", "target_country", "target")
    )["default"]
    assert first["id"] == "program:events/a.txt#option:default"
    assert second["id"] == "program:events/b.txt#option:default"
    assert first["id"] != second["id"]
    assert first["id"] != "default"
    assert first["reader_context_binding"] == ["root", "country", "actor"]
    assert second["reader_context_binding"] == ["target_country", "country", "target"]
    assert first["reader_contracts"][0]["reader"]["engine"] == "in_default"
    assert second["reader_contracts"][0]["reader"]["scope"] == "target_country"


@pytest.mark.parametrize("fault", ["missing", "role", "program_binding"])
def test_program_local_reader_closure_rejects_missing_or_wrong_binding(fault):
    writer = _program_reader_fixture()
    if fault == "missing":
        writer["reader_context_bindings"] = []
    elif fault == "role":
        writer["reader_context_bindings"][0][3] = "target"
        writer["event_program"]["reader_context_bindings"][0][3] = "target"
    else:
        writer["reader_context_bindings"][0][1] = "target_country"
    with pytest.raises(
        ValueError, match=r"coverage mismatch|scope/role drift|differs from production"
    ):
        classify.program_reader_facts(writer)


def test_program_exists_getter_keeps_root_evaluation_and_subject_binding_separate():
    writer = _program_reader_fixture("events/b.txt", "target_country", "target")
    reader = writer["event_program"]["readers"][0]
    reader.update(engine="exists", scope="root", argument="scope:target_country")
    fact = classify.program_reader_facts(writer)["default"]
    assert fact["scope"] == "root"
    assert fact["reader_context_binding"] == ["target_country", "country", "target"]
    assert fact["reader_contracts"][0]["reader"]["argument"] == "scope:target_country"


def test_all_original_implemented_objectives_have_exact_current_roles_and_writers(
    actual_projection,
):
    _, values = actual_projection
    implemented = {
        identity: row
        for identity, row in values["predecessors"].items()
        if row["old_status"] == "implemented"
    }
    assert len(implemented) == 17
    for objective in implemented.values():
        assert objective["mapping_precision"] == "exact_source_owner_field_role"
        writers = [
            values["migration_writers"][identity] for identity in objective["current_writer_ids"]
        ]
        assert writers
        assert {writer["actor"] for writer in writers} == {objective["migration_contract"]["actor"]}
        assert {writer["target"] for writer in writers} == {
            objective["migration_contract"]["target"]
        }
        assert all(
            writer["native_parent_ids"] and writer["semantic_ir_sha256"] for writer in writers
        )
        assert objective["migration_contract"]["witness_functions"]


@pytest.mark.parametrize(
    "fault",
    [
        "raw_observation",
        "resolution",
        "writer",
        "migration",
        "original_objective",
        "owner",
        "current_native_boundary",
    ],
)
def test_index_checkpoint_rejects_missing_raw_resolution_writer_or_objective(
    actual_projection, fault
):
    _, original = actual_projection
    values = dict(original)
    accepted: dict[str, dict[str, Any]] = {
        identity: {}
        for identity, row in values["predecessors"].items()
        if row["old_status"] == "implemented"
    }
    assert classify.index_checkpoint(values, accepted)["product_completion"] is False
    if fault in {"raw_observation", "resolution", "writer", "original_objective"}:
        key = {
            "raw_observation": "unexpanded_observations",
            "resolution": "semantic_resolutions",
            "writer": "migration_writers",
            "original_objective": "predecessors",
        }[fault]
        values[key] = original[key].copy()
        if isinstance(values[key], list):
            values[key].pop()
        else:
            values[key].pop(next(iter(values[key])))
    elif fault == "migration":
        accepted.pop(next(iter(accepted)))
    elif fault == "owner":
        values["unexpanded_observations"] = [
            dict(row) for row in original["unexpanded_observations"]
        ]
        values["unexpanded_observations"][0]["definition"] = "wrong_owner"
    else:
        values["current_native_boundaries"] = {}
    with pytest.raises(ValueError, match=r"denominator|physical|lineage|boundary"):
        classify.index_checkpoint(values, accepted)


@pytest.mark.parametrize(
    ("identity", "status", "stage"),
    [
        ("B04.2.1", "pending", "A4-3"),
        ("R02.1", "pending", "A4-4"),
        ("C2.1", "pending", "A4-2"),
        ("C5.1", "pending", "A4-2"),
        ("C6.1", "pending", "A4-4"),
        ("C9.1", "pending", "A4-6"),
        ("B05.5.7", "implemented", "A4-1"),
    ],
)
def test_original_product_and_current_migration_have_distinct_source_bound_stages(
    identity, status, stage
):
    record = {"id": "D:a3:" + identity, "origin": "a3", "identity": identity}
    old = {identity: {"status": status}}
    assert gate.responsibility_stage(record, old)[0] == stage
    row = {"stage": stage, "discovery_ids": [record["id"]]}
    gate.validate_responsibility_stages({"row": row}, {record["id"]: record}, old)
    row["stage"] = "A4-5"
    with pytest.raises(ValueError, match="wrong claimed responsibility stage"):
        gate.validate_responsibility_stages({"row": row}, {record["id"]: record}, old)


@pytest.mark.parametrize("fault", ["failed", "missing", "skipped", "stale_junit"])
def test_migration_acceptance_rejects_failed_missing_skipped_or_stale_witness(tmp_path, fault):
    """Reject broken evidence before loading a current-model migration closure."""
    node = "tests/test_migration.py::test_actual"
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite><testcase classname="tests.test_migration" '
        'name="test_actual"/></testsuite></testsuites>',
        encoding="utf8",
    )
    sources = gate.Sources(tmp_path)
    receipt = {
        "exit_code": 0,
        "failed": [],
        "selection": [node],
        "passed": [node],
        "junit": sources.reference("junit.xml"),
    }
    if fault == "failed":
        receipt.update(exit_code=1, failed=[node])
    elif fault == "missing":
        receipt["selection"] = []
    elif fault == "skipped":
        junit.write_text(
            '<testsuites><testsuite><testcase classname="tests.test_migration" '
            'name="test_actual"><skipped/></testcase></testsuite></testsuites>',
            encoding="utf8",
        )
        receipt["junit"] = gate.Sources(tmp_path).reference("junit.xml")
    else:
        junit.write_text("changed after binding", encoding="utf8")
    discovery.write_json(tmp_path / classify.MIGRATION_RECEIPT, receipt)
    discovery.write_json(
        tmp_path / classify.MIGRATION_PATH,
        {"objectives": {"synthetic-negative-only": {"witness_nodes": [node]}}},
    )
    with pytest.raises(ValueError, match=r"migration witness|migration JUnit|stale hash"):
        classify.migration_acceptance(gate.Sources(tmp_path), {}, replay=False)
