"""A directed acceptance program is an actual typed production consumer."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from test_a3_military_assistance import _actual as _military_actual
from test_a3_military_assistance import _values as _military_values
from test_a3_treaty_acceptance import _actual, _context, _values

from pdx import decision_adapters, decision_interfaces
from pdx import treaty_acceptance_opportunities as accept
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import action_instances, compiler, domain_coverage, vanilla_inventory
from pdx.situated.decision_ir import ConsumerIRBundle, WriterDecisionIR

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def production():
    inputs = accept.frozen_inputs()
    programs = accept.compile_programs()
    adapters = decision_adapters.AdapterSet(
        sources=tuple(sorted(accept.load()["sources"].items())),
        policies=(),
        source_sha256="a" * 64,
        acceptance_programs=programs,
    )
    bundle = ConsumerIRBundle(1, (), tuple(program.writer_ir() for program in programs))
    return inputs, adapters, bundle


def test_real_compiler_freezes_the_current_accepting_country_article_and_goods(production):
    inputs, adapters, _ = production
    configured = decision_adapters.load()
    assert configured.acceptance_programs == adapters.acceptance_programs
    assert configured.treaty_acceptance_opportunities_sha256
    model = compiler.load_model()
    assert model.consumer_ir is not None
    programs = decision_adapters._acceptance_programs(configured, model.consumer_ir, enabled=True)
    assert len(programs) == 2
    program = next(p for p in programs if p.definition == "no_tariffs")
    writers = tuple(row for row in model.consumer_ir.writers if row.kind == "acceptance_program")
    writer = next(row for row in writers if row.definition == "no_tariffs")
    assert writer.acceptance_program is program
    assert writer.definition == "no_tariffs"
    assert writer.evaluation_context is not None
    assert writer.evaluation_context.targets == ()
    assert {row.kind for row in writer.evaluation_context.auxiliary_scopes} == {
        "country",
        "treaty_article_options",
        "market_goods",
    }
    assert (
        len(
            [
                row
                for row in model.observation_contracts
                if row[0] == accept.SOURCE and row[1].startswith("acceptance_")
            ]
        )
        == 8
    )
    contract = model.contract()["domain_coverage"]
    assert isinstance(contract, dict)
    assert any(
        row["definition"] == "no_tariffs" and row["consumer_id"] == accept.FIELD
        for row in contract["domains"]["diplomacy"]["targets"]
    )
    subset = ConsumerIRBundle(1, (), writers)
    generated, metadata = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset({"diplomacy"}), consumer_ir=subset
    )
    assert set(generated) == {p.source for p in programs}
    assert metadata["acceptance_programs"] == [p.as_dict() for p in programs]
    assert decision_interfaces.acceptance_consumer(program)["native_unit"] == "acceptance_score"
    assert metadata["field_owners"] == [
        {"source": p.source, "field": p.field, "owner": "treaty_acceptance_opportunities"}
        for p in sorted(programs, key=lambda p: (p.source, p.field))
    ]
    instances = tuple(row for row in model.action_instances if row.kind == "acceptance_program")
    assert action_instances.missing_witnesses(instances, generated) == ()
    assert action_instances.missing_witnesses(instances, {}) == tuple(
        sorted(p.writer_id for p in programs)
    )
    military = next(p for p in programs if p.definition == "military_assistance")
    military_writer = next(row for row in writers if row.definition == military.definition)
    assert military_writer.acceptance_program is military
    assert military_writer.evaluation_context == military.evaluation_context()
    assert {row.kind for row in military.evaluation_context().auxiliary_scopes} == {
        "country",
        "treaty_article_options",
    }
    assert {
        row[1]
        for row in model.observation_contracts
        if row[0] == military.source and row[1].startswith("military_")
    } == {reader.key for reader in military.readers()}
    assert any(
        row["definition"] == military.definition and row["consumer_id"] == military.field
        for row in contract["domains"]["diplomacy"]["targets"]
    )
    for changes, expected in (
        ({"net_total_income": -1}, -6),
        ({"in_default": True}, -10),
        ({"root": "B", "in_default": True}, 0),
        ({"military_expenses": None, "in_default": True}, 0),
    ):
        values = _military_values(**changes)
        assert military.evaluate(values, is_ai=True) == expected
        assert _military_actual(generated[military.source], values) == expected
    for tariff_changes, expected in (
        ({"net_total_income": -1}, -8),
        ({"in_default": None}, -12),
        ({"root": "B"}, 6),
        ({"input_market_goods_exists": False}, 0),
    ):
        values = _values(**tariff_changes)
        assert program.evaluate(values, is_ai=True) == expected
        assert _actual(generated[accept.SOURCE], _context(values)) == expected


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "program", "roles", "reader", "field", "tail", "kind", "parent"],
)
@pytest.mark.parametrize("definition", ["no_tariffs", "military_assistance"])
def test_acceptance_cannot_silently_recompile_mutated_or_missing_supplied_ir(
    production, mutation, definition
):
    inputs, adapters, bundle = production
    writer = next(row for row in bundle.writers if row.definition == definition)
    assert writer.acceptance_program is not None
    rows: tuple[WriterDecisionIR, ...]
    if mutation == "missing":
        rows = ()
    elif mutation == "duplicate":
        rows = (writer, writer)
    elif mutation == "program":
        rows = (
            replace(
                writer,
                acceptance_program=replace(writer.acceptance_program, actor="source_country"),
            ),
        )
    elif mutation == "roles":
        rows = (replace(writer, evaluation_context=None),)
    elif mutation == "reader":
        rows = (replace(writer, reader_context_bindings=()),)
    elif mutation == "field":
        rows = (replace(writer, field=f"{definition}.ai.contextual_accept_score"),)
    elif mutation == "tail":
        rows = (replace(writer, vanilla_tail="replace"),)
    elif mutation == "kind":
        rows = (replace(writer, kind="rule_action"),)
    else:
        rows = (
            writer,
            WriterDecisionIR(
                "parent",
                "rule_action",
                writer.source,
                "parent",
                "parent",
                f"{definition}.ai",
                "root",
                "none",
                "add",
                "preserve",
                "treaty_acceptance_opportunities",
            ),
        )
    changed = replace(
        bundle,
        writers=tuple(
            row
            for original in bundle.writers
            for row in (rows if original is writer else (original,))
        ),
    )
    with pytest.raises(ValueError):
        decision_adapters.build(
            adapters, texts=inputs, enabled_domains=frozenset({"diplomacy"}), consumer_ir=changed
        )
    with pytest.raises(ValueError):
        decision_adapters.build(
            adapters, texts=inputs, enabled_domains=frozenset(), consumer_ir=changed
        )


def test_disabled_and_standalone_paths_share_the_same_immutable_acceptance_plan(production):
    inputs, adapters, bundle = production
    disabled, metadata = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset(), consumer_ir=bundle
    )
    assert disabled == {}
    assert metadata["acceptance_programs"] == []
    assert metadata["field_owners"] == []
    standalone, _ = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset({"diplomacy"})
    )
    expected = {}
    for program in adapters.acceptance_programs:
        expected.update(accept.patch(inputs, consumer_program=program))
    assert standalone == expected
    # Other physical leaves may compose, while changing this score is rejected.
    overlay = inputs[accept.SOURCE].replace("value = 0.1", "value = 0.2")
    merged, _ = decision_adapters.build(
        adapters,
        texts=inputs,
        enabled_domains=frozenset({"diplomacy"}),
        consumer_ir=bundle,
        overlays={accept.SOURCE: overlay},
    )
    assert "value = 0.2" in merged[accept.SOURCE]
    invalid = inputs[accept.SOURCE].replace(
        "inherent_accept_score = {", "inherent_accept_score = { add = 1"
    )
    with pytest.raises(ValueError, match="双作者"):
        decision_adapters.build(
            adapters,
            texts=inputs,
            enabled_domains=frozenset({"diplomacy"}),
            consumer_ir=bundle,
            overlays={accept.SOURCE: invalid},
        )


@pytest.mark.parametrize("definition", ["no_tariffs", "military_assistance"])
def test_independent_native_inventory_joins_only_the_exact_inherent_consumer(
    production, definition
):
    inputs, _, bundle = production
    raw = {source: text.encode("utf-8") for source, text in inputs.items()}
    writer = next(row for row in bundle.writers if row.definition == definition)
    declaration = parse_text(inputs[writer.source]).root.first(definition)
    assert declaration is not None
    assert isinstance(declaration.value, Block)
    ai = declaration.value.first("ai")
    assert ai is not None
    assert isinstance(ai.value, Block)
    score = ai.value.first("inherent_accept_score")
    assert score is not None
    scope = vanilla_inventory._treaty_scope(
        ("ai", "inherent_accept_score"), raw, declaration, writer.source
    )
    surface = vanilla_inventory._surface(
        writer.source,
        definition,
        "ai.inherent_accept_score",
        score.line,
        scope,
    )
    inventory = vanilla_inventory.VanillaInventory(
        "independent_directed_acceptance",
        {source: hashlib.sha256(value).hexdigest() for source, value in raw.items()},
        "a" * 64,
        (surface,),
        ("treaty_articles",),
        ("common",),
        1,
    )
    assert writer.acceptance_program is not None
    assert writer.evaluation_context is not None
    instance = action_instances.ActionInstance(
        action_id=writer.writer_id,
        kind="acceptance_program",
        source=writer.source,
        rule_id=writer.definition,
        domain="diplomacy",
        consumer_field=writer.field,
        operation="add",
        value=0,
        condition_facts=tuple(reader.key for reader in writer.acceptance_program.readers()),
        owner=writer.owner,
        vanilla_tail="preserve",
        evidence=writer.evaluation_context.evidence,
        family_id="diplomacy",
        evaluation_context=writer.evaluation_context,
    )
    report = domain_coverage.native_coverage(inventory, (instance,), native_sources=raw)
    assert report["counts"]["actual_covered"] == 1
    assert report["binding_issue_count"] == 0
    bad = domain_coverage.native_coverage(
        inventory, (replace(instance, evaluation_context=None),), native_sources=raw
    )
    assert bad["counts"]["actual_covered"] == 0
    assert bad["binding_issue_count"] == 1
