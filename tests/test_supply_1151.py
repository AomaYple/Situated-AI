"""Independent witnesses for the three reviewed 1.15.1 stance compositions."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from test_native_parameter_boundary_proofs import _dependencies
from test_native_parameter_boundary_proofs import supply_enum_case as _supply_enum_fixture

from pdx import decision_adapters, version_contracts
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import engine_scope, production_profile, supply_program, vanilla_inventory
from pdx.situated.decision_ir import WriterDecisionIR
from pdx.situated.native_treatments import _supply_enum_projections, native_treatments

SOURCE = "common/ai_strategies/00_default_strategy.txt"
GOODS = "common/goods/00_goods.txt"
OVERLAP = {"oil", "radios", "telephones"}
WORDS = frozenset(
    {"market_goods_delta", "market_goods_pricier", "wants_high_supply", "market", "mg:grain"}
)
pytestmark = pytest.mark.unit


def _stances(text):
    parsed = parse_text(text)
    assert not parsed.errors
    strategy = parsed.root.first("ai_strategy_default")
    assert strategy is not None
    assert isinstance(strategy.value, Block)
    stances = strategy.value.first("goods_stances")
    assert stances is not None
    assert isinstance(stances.value, Block)
    return stances.value


def _ast(node):
    if isinstance(node, Block):
        return tuple(_ast(item) for item in node.items)
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _ast(node.value)
    assert isinstance(node, Scalar)
    return node.text, node.quoted


@pytest.fixture(scope="module")
def case():
    with version_contracts.select_version("1.15.1"):
        adapters = decision_adapters.load()
        assert adapters.supply is not None
        plan = adapters.supply
        text = (production_profile.baseline_root() / "game" / SOURCE).read_text(
            encoding="utf-8-sig"
        )
        # Real pinned native triggers; synthetic name-only goods definitions
        # isolate the patcher's duplicate/unknown-name contract offline. These
        # definitions grant no production reader/source/engine authority.
        inputs = {SOURCE: text, GOODS: " ".join(f"{good}={{}}" for good in plan.goods)}
        result = decision_adapters._supply_patch(text, plan, inputs, WORDS, plan.actions())
        return plan, text, inputs, result


def test_all_three_native_stances_have_one_typed_idempotent_writer(case):
    plan, original, _, output = case
    programs = {program.good: program for program in plan.actions()}
    before, after = _stances(original), _stances(output)
    assert set(before.keys()) & set(plan.goods) == OVERLAP
    assert len(plan.goods) == 33
    for good in OVERLAP:
        assert programs[good].operation == "idempotent_or"
        assert len(after.all(good)) == 1
        body = after.first(good).value
        assert body.keys() == ["stance", "trigger"]
        assert _ast(body.first("stance")) == _ast(before.first(good).value.first("stance"))
        union = body.first("trigger").value.first("OR").value
        assert union.keys() == ["AND", "AND"]
        assert _ast(union.items[0].value) == _ast(before.first(good).value.first("trigger").value)
        native_stance = programs[good].native_stance
        assert native_stance is not None
        start, end = supply_program.block_span(native_stance.body, ("<anonymous>", "trigger"))
        assert "OR = { AND = " + native_stance.body[start:end] in programs[good].composed_body()
    for good in set(before.keys()) - OVERLAP:
        assert _ast(before.first(good)) == _ast(after.first(good))
    assert sum(program.operation == "append" for program in programs.values()) == 30
    assert all(
        program.render() == program.action.render()
        for program in programs.values()
        if program.good not in OVERLAP
    )


def _evaluate(block, facts):
    values = []
    for item in block.items:
        assert isinstance(item, Assignment)
        if item.key in {"AND", "OR"}:
            assert isinstance(item.value, Block)
            children = [_evaluate(Block([child]), facts) for child in item.value.items]
            values.append(all(children) if item.key == "AND" else any(children))
        elif isinstance(item.value, Block):
            values.append(item.key in facts and _evaluate(item.value, facts[item.key]))
        elif isinstance(item.value, Scalar) and item.key == "exists":
            values.append(item.value.text in facts)
        elif item.key == "is_ai":
            values.append(facts.get("is_ai") is True)
        elif isinstance(item.value, Scalar) and item.key in {
            "has_technology_researched",
            "has_building",
        }:
            values.append(item.value.text in facts.get(item.key, set()))
        else:
            assert isinstance(item.value, Scalar)
            actual = facts.get(item.key)
            expected = float(item.value.text)
            values.append(
                actual is not None and (actual > expected if item.op == ">" else actual < expected)
            )
    return all(values)


@pytest.mark.parametrize("good", sorted(OVERLAP))
def test_native_only_scarcity_only_both_neither_player_and_unknown(case, good):
    _, original, _, output = case
    native = _stances(original).first(good).value.first("trigger").value
    generated = _stances(output).first(good).value.first("trigger").value
    tech = {"oil": "combustion_engine", "radios": "nco_training", "telephones": "telephone"}[good]
    for ai, native_active, scarce, present in itertools.product((True, False), repeat=4):
        facts: dict[str, Any] = {
            "is_ai": ai,
            "has_technology_researched": {tech} if native_active else set(),
            "has_building": {"building_government_administration"},
        }
        if present:
            facts["market"] = {
                f"mg:{good}": {
                    "market_goods_pricier": 0.5 if scarce else 0,
                    "market_goods_delta": -1,
                }
            }
        expected_native = _evaluate(native, facts)
        assert _evaluate(generated, facts) is (expected_native or (ai and scarce and present))
        program = next(item for item in case[0].actions() if item.good == good)
        assert program.evaluate(
            is_ai=ai,
            price=0.5 if scarce else 0,
            delta=-1,
            market_present=present,
            good_present=present,
            native_active=expected_native,
        ) == ("wants_high_supply" if _evaluate(generated, facts) else None)
        if not ai or not present:
            assert _evaluate(generated, facts) is expected_native
    for missing in ("market_goods_pricier", "market_goods_delta", f"mg:{good}"):
        facts = {
            "is_ai": True,
            "market": {f"mg:{good}": {"market_goods_pricier": 0.5, "market_goods_delta": -1}},
        }
        if missing.startswith("mg:"):
            facts["market"].pop(missing)
        else:
            facts["market"][f"mg:{good}"].pop(missing)
        assert not _evaluate(generated, facts)


@pytest.mark.parametrize(
    "damage",
    [
        "combustion_engine",
        "stance = wants_high_supply",
        "has_technology_researched = line_infantry",
    ],
)
def test_composition_rejects_native_or_sibling_drift(case, damage):
    plan, original, inputs, _ = case
    changed = original.replace(damage, damage + "_unreviewed", 1)
    with pytest.raises(ValueError):
        decision_adapters._supply_patch(changed, plan, inputs, WORDS, plan.actions())


def test_historical_plan_retains_only_unchanged_append_programs():
    with version_contracts.select_version("1.15.0"):
        plan = decision_adapters.load().supply
        assert plan is not None
        assert len(plan.actions()) == 33
        assert all(program.operation == "append" for program in plan.actions())
        assert all("native_stance" not in program.as_dict() for program in plan.actions())


def test_supply_disabled_emits_no_stance_changes(case):
    plan, original, inputs, _ = case
    assert decision_adapters._supply_programs(plan, None, enabled=False) == ()
    adapters = decision_adapters.AdapterSet(
        tuple((name, hashlib.sha256(text.encode()).hexdigest()) for name, text in inputs.items()),
        (),
        "0" * 64,
        supply=plan,
    )
    files, metadata = decision_adapters.build(adapters, texts=inputs)
    assert SOURCE not in files
    assert {**inputs, **files}[SOURCE].encode() == original.encode()
    assert metadata["supply_plan"] is None


@pytest.mark.parametrize("good", sorted(OVERLAP))
def test_full_reference_native_branch_survives_disabled_player_and_unknown(case, good):
    program = next(item for item in case[0].actions() if item.good == good)
    for ai, enabled, present in itertools.product(
        (True, False, None), (True, False), (True, False, None)
    ):
        facts: dict[str, Any] = {
            "is_ai": ai,
            "price": None,
            "delta": None,
            "enabled": enabled,
            "market_present": present,
            "good_present": present,
        }
        assert program.evaluate(**facts, native_active=True) == "wants_high_supply"
        assert program.evaluate(**facts, native_active=False) is None
        assert program.evaluate(**facts, native_active=None) is None
    assert (
        program.evaluate(is_ai=True, price=0.5, delta=-1, native_active=None) == "wants_high_supply"
    )


def test_native_technology_and_building_alternatives_are_preserved(case):
    generated = _stances(case[3])
    radios = generated.first("radios").value.first("trigger").value
    for technology in (
        "nco_training",
        "mobile_armor",
        "defense_in_depth",
        "battleship_tech",
        "carrier_tech",
    ):
        assert _evaluate(radios, {"is_ai": False, "has_technology_researched": {technology}})
    telephones = generated.first("telephones").value.first("trigger").value
    for technology_present, building in itertools.product((True, False), repeat=2):
        assert _evaluate(
            telephones,
            {
                "is_ai": False,
                "has_technology_researched": {"telephone"} if technology_present else set(),
                "has_building": {"building_government_administration"} if building else set(),
            },
        ) is (technology_present and building)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "wrong_program", "extra_overlap"])
def test_patcher_rejects_incomplete_or_unreviewed_programs(case, damage):
    plan, original, inputs, _ = case
    programs = plan.actions()
    if damage == "missing":
        programs = programs[:-1]
    elif damage == "duplicate":
        programs = (*programs, programs[0])
    elif damage == "wrong_program":
        programs = tuple(replace(program, native_stance=None) for program in programs)
    else:
        original = original.replace(
            "goods_stances = {", "goods_stances = { wood = { stance = wants_high_supply }", 1
        )
        inputs = {**inputs, SOURCE: original}
    with pytest.raises(ValueError):
        decision_adapters._supply_patch(original, plan, inputs, WORDS, programs)


def test_typed_writer_operation_tracks_each_concrete_program(case):
    for program in case[0].actions():
        writer = WriterDecisionIR(
            writer_id=program.writer_id,
            kind="supply_program",
            source=program.source,
            definition=program.good,
            consumer_id=program.consumer_id,
            field=program.field,
            actor="root",
            target="market_goods",
            operation=program.operation,
            vanilla_tail="preserve",
            owner="supply_plan",
            supply_program=program,
        )
        assert writer.validate_supply_program() is program
        with pytest.raises(ValueError):
            replace(
                writer, operation="append" if program.operation != "append" else "idempotent_or"
            ).validate_supply_program()
    with version_contracts.select_version("1.15.0"), pytest.raises(ValueError):
        supply_program.native_stances_1151()
    stance = next(program.native_stance for program in case[0].actions() if program.native_stance)
    with pytest.raises(ValueError):
        replace(stance, body=stance.body.replace("trigger", "unreviewed"))


@pytest.fixture
def composition_projection_case(case, tmp_path, monkeypatch):
    """Real pinned triggers with explicitly synthetic ancillary name/getter proof.

    The existing audit fixture supplies synthetic interfaces, metadata and goods;
    its test-only source pins isolate whole-source enum projection. No production
    authority or historic evidence file is changed or inferred from these bytes.
    """
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.15.1")
    inventory, native, generated, path = cast("Any", _supply_enum_fixture).__wrapped__(
        tmp_path, monkeypatch
    )
    plan, original, inputs, output = case
    native[SOURCE] = original.encode()
    native[GOODS] = inputs[GOODS].encode()
    adapters = replace(
        decision_adapters.load(),
        supply=plan,
        sources=tuple((name, hashlib.sha256(raw).hexdigest()) for name, raw in native.items()),
    )
    monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    evidence = dict(vanilla_inventory._parameter_evidence_contract())
    evidence[GOODS] = hashlib.sha256(native[GOODS]).hexdigest()
    monkeypatch.setattr(vanilla_inventory, "_parameter_evidence_contract", lambda: evidence)
    monkeypatch.setattr(
        engine_scope,
        "strategy_snapshot",
        lambda: json.dumps(
            {"script_hashes": {SOURCE: hashlib.sha256(native[SOURCE]).hexdigest()}}
        ).encode(),
    )
    metadata = json.loads(generated[".metadata/metadata.json"])
    contract = metadata["consumer_adapters"]
    contract["sources"] = dict(adapters.sources)
    contract["supply_program_generator_sha256"] = hashlib.sha256(
        Path(supply_program.__file__).read_bytes()
    ).hexdigest()
    contract["supply_plan"].update(
        goods=list(plan.goods), consumer_programs=[program.as_dict() for program in plan.actions()]
    )
    generated[SOURCE] = output.encode()
    generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    inventory = replace(inventory, source_hashes=dict(adapters.sources))
    return inventory, native, generated, path


def test_audit_restores_all_native_source_context_without_numeric_credit(
    composition_projection_case,
):
    projections = _supply_enum_projections(_dependencies(composition_projection_case))[SOURCE]
    assert len(projections) == 33
    assert sum(row["kind"] == "registered_enum_idempotent_or" for row in projections.values()) == 3
    assert sum(row["kind"] == "registered_enum_addition" for row in projections.values()) == 30
    assert all(row["business_complete"] is False for row in projections.values())
    inventory, native, generated, _ = composition_projection_case
    surface = replace(
        inventory.surfaces[0],
        source=SOURCE,
        definition="ai_strategy_default",
        field="goods_stances",
        source_line=1,
        parent_field=None,
        parent_source_line=None,
    )
    report = native_treatments(
        replace(inventory, surfaces=(surface,)), native, generated, production_complete=True
    )
    assert report["rows"][0]["source_protection"]["context_closed"]
    assert not report["rows"][0]["implemented_numeric"]


def _enum_leaf_case(case):
    """Keep the three native leaves as separate discovered responsibilities.

    Ancillary source/getter authority remains the explicitly synthetic fixture
    above. The three leaves, native triggers and complete production ORs use
    the real frozen source and actual patcher output.
    """
    inventory, native, generated, path = case
    stances = _stances(native[SOURCE].decode("utf-8-sig"))
    scopes = vanilla_inventory._strategy_scopes(native)
    surfaces = tuple(
        vanilla_inventory._surface(
            SOURCE,
            "ai_strategy_default",
            f"goods_stances.{good}",
            stances.first(good).line,
            scopes.get("goods_stances", vanilla_inventory._Scope()),
        )
        for good in sorted(OVERLAP)
    )
    return replace(inventory, surfaces=surfaces), native, generated, path


def _enum_leaf_report(case, *, complete=True):
    inventory, native, generated, _ = _enum_leaf_case(case)
    report = native_treatments(inventory, native, generated, production_complete=complete)
    assert report["denominator"] == inventory.discovered_count == 3
    assert {row["declaration_id"] for row in report["rows"]} == {
        surface.declaration_id for surface in inventory.surfaces
    }
    return report


def test_all_three_actual_union_leaves_have_native_preservation_not_numeric_credit(
    composition_projection_case,
):
    report = _enum_leaf_report(composition_projection_case)
    assert {row["field"] for row in report["rows"]} == {f"goods_stances.{good}" for good in OVERLAP}
    for row in report["rows"]:
        protection = row["source_protection"]
        assert protection["proven"]
        assert protection["context_closed"]
        assert protection["dependencies_closed"]
        assert protection["native_enum_projection"]
        assert not protection["structural_projection"]
        binding = protection["native_enum_binding"]
        assert binding["kind"] == "registered_enum_idempotent_or"
        assert binding["field"] == row["field"]
        assert binding["restored_native_ast_sha256"] == row["native_ast_sha256"]
        assert binding["effective_ast_sha256"] == row["effective_ast_sha256"]
        assert binding["native_sources"]
        assert row["interface_kind"] == "needs_review"
        assert not row["interface"]["known"]
        assert not row["active_unknown_usage"]
        assert not row["implemented_numeric"]
        assert not row["interface"]["control_authorized"]
        assert row["business_obligation"]["disposition"] == "preserve_native"


def test_disabled_supply_retains_all_three_native_leaves_without_a_projection(
    composition_projection_case,
):
    _, native, generated, _ = composition_projection_case
    generated[SOURCE] = native[SOURCE]
    metadata = json.loads(generated[".metadata/metadata.json"])
    metadata["consumer_adapters"]["supply_plan"] = None
    generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    report = _enum_leaf_report(composition_projection_case)
    for row in report["rows"]:
        assert row["ast_status"] == "retained"
        assert row["source_protection"]["proven"]
        assert not row["source_protection"]["native_enum_projection"]
        assert row["source_protection"]["native_enum_binding"] is None
        assert not row["active_unknown_usage"]
        assert not row["implemented_numeric"]


@pytest.mark.parametrize("damage", ["metadata", "missing_metadata", "incomplete"])
def test_claimed_union_cannot_hide_missing_actual_candidate_authority(
    composition_projection_case, damage
):
    _, _, generated, _ = composition_projection_case
    if damage != "incomplete":
        metadata = json.loads(generated[".metadata/metadata.json"])
        if damage == "missing_metadata":
            metadata["consumer_adapters"].pop("supply_plan")
        else:
            metadata["consumer_adapters"]["supply_plan"]["behavior_verified"] = True
        generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    report = _enum_leaf_report(composition_projection_case, complete=damage != "incomplete")
    for row in report["rows"]:
        assert not row["source_protection"]["proven"]
        assert not row["source_protection"]["native_enum_projection"]
        assert row["active_unknown_usage"]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            b'icon = "gfx/interface/icons/ai_strategy_icons/placate_population.dds"',
            b'icon = "unreviewed.dds"',
        ),
        (b"nationalization_cost(scope:target_country)", b"nationalization_cost(root)"),
    ],
    ids=["source_companion", "native_cost"],
)
def test_valid_enum_union_cannot_mask_other_native_source_or_cost_changes(
    composition_projection_case, before, after
):
    _, _, generated, _ = composition_projection_case
    assert before in generated[SOURCE]
    generated[SOURCE] = generated[SOURCE].replace(before, after, 1)
    # The three OR expressions remain proven, while whole-source protection
    # independently rejects a sibling or retained cost-operand change.
    projections = _supply_enum_projections(_dependencies(composition_projection_case))[SOURCE]
    assert sum(row["kind"] == "registered_enum_idempotent_or" for row in projections.values()) == 3
    report = _enum_leaf_report(composition_projection_case)
    for row in report["rows"]:
        assert row["source_protection"]["native_enum_projection"]
        assert not row["source_protection"]["context_closed"]
        assert not row["source_protection"]["proven"]
        assert row["active_unknown_usage"]


@pytest.mark.parametrize(
    "damage", ["native", "stance", "player", "market", "good", "duplicate", "sibling", "extra"]
)
def test_audit_rejects_changed_native_or_scarcity_or_sibling(composition_projection_case, damage):
    _, _, generated, _ = composition_projection_case
    before, after = {
        "native": (b"combustion_engine", b"unreviewed_technology"),
        "stance": (b"stance = wants_high_supply", b"stance = export"),
        "player": (b"is_ai = yes exists = market", b"is_ai = no exists = market"),
        "market": (b"exists = market market =", b"always = yes market ="),
        "good": (b"exists = mg:oil", b"always = yes"),
        "duplicate": (b"goods_stances = {", b"goods_stances = { oil = {}"),
        "sibling": (
            b"has_technology_researched = line_infantry",
            b"has_technology_researched = unreviewed",
        ),
        "extra": (b"goods_stances = {", b"goods_stances = { invented = {}"),
    }[damage]
    assert before in generated[SOURCE]
    generated[SOURCE] = generated[SOURCE].replace(before, after, 1)
    assert not _supply_enum_projections(_dependencies(composition_projection_case))
    report = _enum_leaf_report(composition_projection_case)
    for row in report["rows"]:
        assert not row["source_protection"]["native_enum_projection"]
        assert not row["source_protection"]["proven"]
        assert row["business_obligation"]["disposition"] == "unresolved"
        assert row["active_unknown_usage"] or row["ast_status"] == "ambiguous"
