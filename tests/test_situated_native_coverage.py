"""Independent native denominator and exact production binding counterexamples."""

import hashlib
from dataclasses import replace

import pytest

from pdx import decision_rules
from pdx.situated.action_instances import ActionInstance
from pdx.situated.decision_ir import ContextBinding, EvaluationContext
from pdx.situated.domain_coverage import NativeConsumerBinding, native_coverage
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface

pytestmark = pytest.mark.unit


def _surface(name="ai_strategy_default", field="score", **changes):
    row = VanillaSurface(
        surface_id=f"{name}:{field}",
        source="common/ai_strategies/00_default_strategy.txt",
        definition=name,
        field=field,
        actor_scope="country",
        target_scope="none",
        operation="additive_score",
        capability="direct",
        status="pending",
        getter=None,
        getter_note="not proven",
        scope_evidence=("native/readme.md:1",),
        responsibility_step="B0",
        source_line=1,
    )
    return replace(row, **changes)


def _inventory(*surfaces, **changes):
    value = VanillaInventory(
        baseline_id="fixture-baseline",
        source_hashes={"fixture": "a" * 64},
        scope_hash="b" * 64,
        surfaces=surfaces,
        scanned_directories=("ai_strategies",),
        content_roots=("game",),
        parsed_files=1,
    )
    return replace(value, **changes)


def _instance(name="rule", **changes):
    value = ActionInstance(
        action_id=name,
        kind="rule_action",
        source="mod/decisions/information.toml",
        rule_id=name,
        domain="test",
        consumer_field="score",
        operation="add",
        value=1.0,
        condition_facts=("need",),
        owner="information_rules",
        vanilla_tail="retained",
        evidence=("need",),
    )
    return replace(value, **changes)


def test_independent_native_denominator_is_not_production_instance_count():
    first = _surface()
    second = _surface(field="future_score")
    instances = (_instance("one"), _instance("two"))
    baseline = native_coverage(_inventory(first), instances)
    expanded = native_coverage(_inventory(first, second), instances)
    assert baseline["denominator"] == 1
    assert baseline["counts"]["actual_covered"] == 1
    assert expanded["denominator"] == 2
    assert expanded["counts"]["actual_covered"] == 1
    assert expanded["unimplemented_legal"] == [second.declaration_id]
    assert not expanded["binding_complete"]
    assert expanded["rows"][0]["status"] == "pending"
    assert expanded["inventory_status_counts"] == {"pending": 2}
    assert expanded["source_hashes"] == {"fixture": "a" * 64}


def test_adapter_definition_and_full_field_path_are_exact():
    source = "common/buildings/00_mines.txt"
    surface = _surface("building_iron_mine", "ai.weight", source=source)
    correct = _instance(
        source=source, consumer_field="building_iron_mine.ai.weight", actor_scope="owner"
    )
    good = native_coverage(_inventory(surface), (correct,))
    assert good["counts"]["actual_covered"] == 1
    for wrong in (
        replace(correct, source="common/buildings/01_mines.txt"),
        replace(correct, consumer_field="building_coal_mine.ai.weight"),
        replace(correct, consumer_field="building_iron_mine.weight"),
    ):
        result = native_coverage(_inventory(surface), (wrong,))
        assert result["counts"]["actual_covered"] == 0
        assert result["counts"]["unimplemented_legal"] == 1
        assert result["unmatched_production"][0]["reason"] == "native_surface_missing"


def test_information_only_binds_default_strategy_not_same_field_in_another_strategy():
    other = _surface("ai_strategy_other")
    result = native_coverage(_inventory(other), (_instance(),))
    assert result["actual_covered"] == []
    assert result["unimplemented_legal"] == [other.declaration_id]


def test_missing_production_and_all_inventory_capabilities_remain_visible():
    surfaces = (
        _surface(field="legal"),
        _surface(field="indirect", capability="indirect"),
        _surface(field="pending", capability="pending"),
        _surface(field="unknown", actor_scope="unknown"),
        _surface(field="observe", capability="observation", operation="read"),
        _surface(field="unexposed", capability="unexposed", status="engine_unexposed"),
        _surface(field="unproven_unexposed", capability="unexposed", scope_evidence=()),
    )
    result = native_coverage(_inventory(*surfaces), ())
    assert result["denominator"] == 7
    assert result["counts"] == {
        "actual_covered": 0,
        "unimplemented_legal": 2,
        "pending": 1,
        "unknown": 2,
        "observation": 1,
        "unsupported": 1,
    }
    assert result["capability_counts"]["indirect"] == 1
    assert sum(result["counts"].values()) == result["denominator"]
    assert not result["binding_complete"]


def test_exact_production_binding_cannot_promote_unknown_or_observation_to_covered():
    for surface in (
        _surface(actor_scope="unknown"),
        _surface(capability="pending"),
        _surface(capability="observation"),
        _surface(ambiguity="duplicate_definition"),
    ):
        result = native_coverage(_inventory(surface), (_instance(),))
        assert result["actual_covered"] == []
        assert result["rows"][0]["matched_actions"] == ["rule"]
        assert result["rows"][0]["covered_actions"] == []


def test_explicit_card_needs_real_explicit_native_consumer_mapping():
    instance = _instance("card_recovery", kind="action_card", source="mod/decisions/actions.toml")
    native = _surface()
    missing = native_coverage(_inventory(native), (instance,))
    assert missing["unmatched_production"][0]["reason"] == "native_binding_missing"
    binding = NativeConsumerBinding(native.source, native.definition, native.field)
    covered = native_coverage(
        _inventory(native), (instance,), explicit_consumers={instance.action_id: binding}
    )
    assert covered["counts"]["actual_covered"] == 1
    with pytest.raises(ValueError, match="实际显式行动卡"):
        native_coverage(_inventory(native), (), explicit_consumers={instance.action_id: binding})


def test_explicit_mapping_cannot_reassign_the_actual_card_field():
    instance = _instance("card_recovery", kind="action_card", source="mod/decisions/actions.toml")
    native = _surface(field="another_score")
    result = native_coverage(
        _inventory(native),
        (instance,),
        explicit_consumers={
            instance.action_id: NativeConsumerBinding(
                native.source, native.definition, native.field
            )
        },
    )
    assert result["actual_covered"] == []
    assert result["unmatched_production"][0]["reason"] == "explicit_field_mismatch"


@pytest.mark.parametrize(
    "source", ["../common/a.txt", "C:/common/a.txt", "common/../a.txt", "common\\a.txt"]
)
def test_native_paths_cannot_be_normalized_into_another_identity(source):
    with pytest.raises(ValueError, match="精确相对来源"):
        NativeConsumerBinding(source, "definition", "field")


def test_object_type_mismatch_and_boolean_eligibility_are_not_numeric_coverage():
    for surface, reason in (
        (_surface(actor_scope="state"), "actor_type_mismatch"),
        (_surface(operation="eligibility"), "numeric_consumer_contract_unproven"),
    ):
        result = native_coverage(_inventory(surface), (_instance(),))
        assert result["counts"]["actual_covered"] == 0
        assert result["rows"][0]["binding_issues"] == {"rule": reason}


def _context(target_name, kind, role):
    actor = ContextBinding("root", "country", "actor", "native/readme.md", 1)
    target = ContextBinding(target_name, kind, role, "native/readme.md", 2)
    return EvaluationContext(
        actor_scope=actor,
        targets=(target,) if role == "target" else (),
        auxiliary_scopes=(target,) if role == "auxiliary" else (),
        evidence=("native/readme.md:1", "native/readme.md:2"),
    )


def test_named_object_requires_documented_type_and_name_not_just_writer_label():
    surface = _surface(target_scope="scope:target_state=state")
    instance = _instance(target_scope="target_state")
    missing = native_coverage(_inventory(surface), (instance,))
    assert missing["rows"][0]["binding_issues"] == {"rule": "evaluation_context_unproven"}
    wrong = replace(instance, evaluation_context=_context("law", "law", "auxiliary"))
    rejected = native_coverage(_inventory(surface), (wrong,))
    assert rejected["rows"][0]["binding_issues"] == {"rule": "target_type_mismatch"}
    correct = replace(instance, evaluation_context=_context("target_state", "state", "target"))
    assert native_coverage(_inventory(surface), (correct,))["counts"]["actual_covered"] == 1


def test_ambiguous_duplicate_native_identity_and_parse_failures_prevent_complete_binding():
    surface = _surface()
    duplicate = replace(surface, declaration_occurrence=2, source_line=2)
    result = native_coverage(_inventory(surface, duplicate), (_instance(),))
    assert result["denominator"] == 2
    assert result["counts"]["actual_covered"] == 0
    assert result["unmatched_production"][0]["reason"] == "native_identity_ambiguous"
    failed = native_coverage(_inventory(surface, parse_failures=("broken.txt",)), (_instance(),))
    assert failed["counts"]["actual_covered"] == 1
    assert failed["parse_failures"] == ["broken.txt"]
    assert not failed["binding_complete"]


def test_one_valid_writer_cannot_hide_another_incompatible_binding():
    valid = _instance("good")
    invalid = _instance("bad", actor_scope="state")
    result = native_coverage(_inventory(_surface()), (valid, invalid))
    assert result["counts"]["actual_covered"] == 1
    assert result["binding_issue_count"] == 1
    assert result["rows"][0]["binding_issues"] == {"bad": "actor_type_mismatch"}
    assert not result["binding_complete"]


def test_empty_discovery_is_never_complete_by_vacuous_zero_counts():
    result = native_coverage(_inventory(), ())
    assert result["denominator"] == 0
    assert not result["binding_complete"]


_BUILDING_DOC = (
    b"# base AI value, default NAI.BUILDING_BASE_VALUE or NAI.GOVERNMENT_BUILDING_BASE_VALUE\n"
    b"# scope is state the building is located in\n"
    b"# be careful with expensive triggers\n"
    b"ai_value = script value\n"
)


def _source_inventory(surfaces, sources):
    return _inventory(
        *surfaces,
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
    )


def _building_policy(source_bytes, instance, **changes):
    rule = decision_rules.Rule(
        id=instance.rule_id,
        domain=instance.domain,
        field=tuple(instance.consumer_field.split(".")),
        priority=1,
        value=instance.value,
        conditions=(decision_rules.Predicate("need", "=", True),),
        why="fixture",
        counterexample="fixture",
        operation=instance.operation,
    )
    return replace(
        decision_rules.RuleSet(
            readers=(),
            rules=(rule,),
            baseline_sha256=hashlib.sha256(
                source_bytes.decode("utf-8-sig")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .encode("utf-8")
            ).hexdigest(),
            source_sha256="fixture",
            enabled_domains=frozenset({instance.domain}),
            actor_path=("owner",),
        ),
        **changes,
    )


def test_implicit_building_is_separate_and_needs_frozen_default_and_real_owner_policy():
    source = "common/buildings/01_industry.txt"
    raw = b"building_test = { building_group = bg_test }"
    sources = {source: raw, "common/buildings/buildings.md": _BUILDING_DOC}
    native = _surface(field="unrelated")
    inventory = _source_inventory((native,), sources)
    instance = _instance(
        source=source, consumer_field="building_test.ai_value", actor_scope="owner"
    )
    policy = _building_policy(raw, instance)
    report = native_coverage(
        inventory, (instance,), native_sources=sources, production_policies={source: policy}
    )
    assert report["denominator"] == 1
    assert report["counts"]["actual_covered"] == 0
    assert len(report["implicit_covered"]) == 1
    assert report["implicit_rows"][0]["actor_scope"] == "state"
    assert report["implicit_rows"][0]["covered_actions"] == [instance.action_id]
    assert "NAI.BUILDING_BASE_VALUE" in report["implicit_rows"][0]["default"]
    assert report["rows"][0]["status"] == "pending"
    missing_policy = native_coverage(inventory, (instance,), native_sources=sources)
    assert missing_policy["implicit_covered"] == []
    for changed in (replace(policy, actor_path=()), replace(policy, baseline_sha256="drift")):
        rejected = native_coverage(
            inventory, (instance,), native_sources=sources, production_policies={source: changed}
        )
        assert rejected["implicit_covered"] == []


def test_existing_state_building_actor_uses_documented_root_and_actual_owner_path():
    source = "common/buildings/03_mines.txt"
    raw = b"building_test = { ai_value = { value = 1 } }"
    sources = {source: raw, "common/buildings/buildings.md": _BUILDING_DOC}
    surface = _surface("building_test", "ai_value", source=source, actor_scope="state")
    instance = _instance(
        source=source, consumer_field="building_test.ai_value", actor_scope="owner"
    )
    policy = _building_policy(raw, instance)
    report = native_coverage(
        _source_inventory((surface,), sources),
        (instance,),
        native_sources=sources,
        production_policies={source: policy},
    )
    assert report["counts"]["actual_covered"] == 1
    assert report["implicit_covered"] == []
    assert report["rows"][0]["actor_scope"] == "state"
    no_doc = native_coverage(
        _source_inventory((surface,), sources),
        (instance,),
        native_sources={source: raw},
        production_policies={source: policy},
    )
    assert no_doc["counts"]["actual_covered"] == 0


@pytest.mark.parametrize(
    "raw",
    [
        b"building_test = { ai_value = 1 }",
        b"building_other = {}",
        b"REPLACE:building_test = {}",
        b"building_test = {} building_test = {}",
    ],
)
def test_implicit_building_cannot_ignore_existing_field_wrong_object_or_duplicates(raw):
    source = "common/buildings/example.txt"
    sources = {source: raw, "common/buildings/buildings.md": _BUILDING_DOC}
    instance = _instance(
        source=source, consumer_field="building_test.ai_value", actor_scope="owner"
    )
    result = native_coverage(
        _source_inventory((), sources),
        (instance,),
        native_sources=sources,
        production_policies={source: _building_policy(raw, instance)},
    )
    assert result["implicit_covered"] == []
    assert result["unmatched_production"][0]["reason"] == "native_surface_missing"


def test_missing_cross_file_building_evidence_or_duplicate_definition_is_not_implicit_proof():
    source = "common/buildings/a.txt"
    other = "common/buildings/b.txt"
    raw = b"building_test = {}"
    sources = {source: raw, other: raw, "common/buildings/buildings.md": _BUILDING_DOC}
    instance = _instance(
        source=source, consumer_field="building_test.ai_value", actor_scope="owner"
    )
    for supplied in (sources, {source: raw, "common/buildings/buildings.md": _BUILDING_DOC}):
        result = native_coverage(
            _source_inventory((), sources),
            (instance,),
            native_sources=supplied,
            production_policies={source: _building_policy(raw, instance)},
        )
        assert result["implicit_covered"] == []


def test_optional_source_bytes_must_match_independent_inventory_hashes():
    with pytest.raises(ValueError, match="独立盘点字节不一致"):
        native_coverage(_inventory(), (), native_sources={"common/example.txt": b"new bytes"})


def test_raw_inventory_and_decoded_adapter_hashes_keep_separate_byte_contracts():
    source = "common/buildings/example.txt"
    raw = b"\xef\xbb\xbfbuilding_test = {\r\n building_group = bg_test\r\n}\r\n"
    sources = {source: raw, "common/buildings/buildings.md": _BUILDING_DOC}
    instance = _instance(
        source=source, consumer_field="building_test.ai_value", actor_scope="owner"
    )
    policy = _building_policy(raw, instance)
    assert policy.baseline_sha256 != hashlib.sha256(raw).hexdigest()
    result = native_coverage(
        _source_inventory((), sources),
        (instance,),
        native_sources=sources,
        production_policies={source: policy},
    )
    assert len(result["implicit_covered"]) == 1


def test_secret_goal_score_projects_only_exact_original_parent_and_preserves_pending():
    source = "common/ai_strategies/00_default_strategy.txt"
    raw = b"ai_strategy_default = { secret_goal_scores = { conquer = { trigger = {} score = { value = 1 } } } }"
    surface = _surface(
        field="secret_goal_scores.conquer", capability="pending", actor_scope="unknown"
    )
    instance = _instance(
        source=source, consumer_field="ai_strategy_default.secret_goal_scores.conquer.score"
    )
    result = native_coverage(
        _source_inventory((surface,), {source: raw}), (instance,), native_sources={source: raw}
    )
    assert result["unmatched_production"] == []
    assert result["pending"] == [surface.declaration_id]
    assert result["actual_covered"] == []
    assert result["rows"][0]["field_projections"][instance.action_id] == {
        "writer_field": "secret_goal_scores.conquer.score",
        "consumer_field": "secret_goal_scores.conquer",
    }
    missing = native_coverage(_source_inventory((surface,), {source: raw}), (instance,))
    assert missing["unmatched_production"]


@pytest.mark.parametrize(
    "goal",
    [
        "conquer = { score = {} score = {} }",
        "REPLACE:conquer = { score = {} }",
        "conquer = { trigger = {} }",
        "conquer = { score = 1 }",
        "conquer = { score = {} } conquer = { score = {} }",
    ],
)
def test_secret_goal_projection_cannot_guess_ambiguous_or_adjacent_structure(goal):
    source = "common/ai_strategies/00_default_strategy.txt"
    raw = ("ai_strategy_default = { secret_goal_scores = { " + goal + " } }").encode()
    instance = _instance(
        source=source, consumer_field="ai_strategy_default.secret_goal_scores.conquer.score"
    )
    result = native_coverage(
        _source_inventory((_surface(field="secret_goal_scores.conquer"),), {source: raw}),
        (instance,),
        native_sources={source: raw},
    )
    assert result["actual_covered"] == []
    assert result["unmatched_production"]
